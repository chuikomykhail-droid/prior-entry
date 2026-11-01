//! Experimental design: arms, probe parameters, send-gap grids and per-family quotas.
//!
//! A pair is two probes A and B from the same payer (so they conflict and execute one after
//! the other). B is sent `s_ms` after A (negative: before A). The recorded outcome is whether
//! B lands before A in the block.
//!
//!   FEE   A cheap, B dear, s >= 0, inside the window       -> the clock curve G(s)
//!   REV   A cheap, B dear, s < 0  (B first)                  -> noise ceiling
//!   TIE   A and B equal, s >= 0                              -> tie-break rule
//!   PRE   A cheap, B dear, s > 0, both before the window     -> buffered = one batch
//!   KEY   X/Y contrasts sent together before the window       -> which sort key

use std::collections::HashMap;

use rand::rngs::StdRng;
use rand::seq::SliceRandom;
use rand::Rng;
use serde::Serialize;

use crate::tx::ProbeParams;

pub const KIB32: u32 = 32 * 1024;
pub const MIB64: u32 = 64 * 1024 * 1024;

/// priority fee 500 lamports
pub const CHEAP: ProbeParams = ProbeParams { cu_limit: 600, cu_price: 833_333, loaded_data: KIB32 };
/// priority fee 3000 lamports
pub const DEAR: ProbeParams = ProbeParams { cu_limit: 600, cu_price: 5_000_000, loaded_data: KIB32 };

pub const DEFAULT_GRID_MS: &[f64] =
    &[0.0, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0, 10.0, 12.0, 15.0, 18.0, 21.0, 25.0, 30.0, 35.0, 40.0, 50.0, 60.0, 80.0, 100.0, 150.0];
pub const REV_GRID_MS: &[f64] = &[-2.0, -5.0, -10.0, -20.0, -50.0];
pub const PRE_GRID_MS: &[f64] = &[50.0, 100.0, 150.0, 250.0];
/// Gap between X and Y of a KEY pair; the sign (who goes first) is random.
pub const KEY_GAP_MS: f64 = 0.3;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize)]
pub enum Arm {
    #[serde(rename = "FEE")]
    Fee,
    #[serde(rename = "REV")]
    Rev,
    #[serde(rename = "TIE")]
    Tie,
    #[serde(rename = "PRE")]
    Pre,
    #[serde(rename = "KEY_C1")]
    KeyC1,
    #[serde(rename = "KEY_C2")]
    KeyC2,
    #[serde(rename = "KEY_C3")]
    KeyC3,
}

pub const ARMS: &[Arm] = &[Arm::Fee, Arm::Rev, Arm::Tie, Arm::Pre, Arm::KeyC1, Arm::KeyC2, Arm::KeyC3];

impl Arm {
    pub fn pre_window(self) -> bool {
        matches!(self, Arm::Pre | Arm::KeyC1 | Arm::KeyC2 | Arm::KeyC3)
    }

    /// Probes per pair (A, B).
    pub fn params(self) -> (ProbeParams, ProbeParams) {
        match self {
            Arm::Fee | Arm::Rev | Arm::Pre => (CHEAP, DEAR),
            Arm::Tie => (CHEAP, CHEAP),
            // X = A, Y = B. Winners: C1 rc:X p:tie f:tie; C2 rc:X p:Y f:Y; C3 rc:X p:X f:Y.
            Arm::KeyC1 => (CHEAP, ProbeParams { loaded_data: MIB64, ..CHEAP }),
            Arm::KeyC2 => (CHEAP, ProbeParams { loaded_data: MIB64, ..DEAR }),
            Arm::KeyC3 => (DEAR, ProbeParams { cu_limit: 6_000, cu_price: 1_000_000, loaded_data: KIB32 }),
        }
    }

    pub fn default_quota(self) -> u32 {
        match self {
            Arm::Fee => 160,
            Arm::Rev => 30,
            Arm::Tie => 40,
            Arm::Pre => 20,
            Arm::KeyC1 | Arm::KeyC2 | Arm::KeyC3 => 15,
        }
    }
}

#[derive(Clone, Debug, Serialize)]
pub struct PairPlan {
    pub arm: Arm,
    pub a: ProbeParams,
    pub b: ProbeParams,
    /// fire time of A relative to the predicted start of the leader window
    pub a_offset_ms: f64,
    /// fire time of B minus fire time of A
    pub s_ms: f64,
}

impl PairPlan {
    pub fn max_fee(&self) -> u64 {
        self.a.total_fee() + self.b.total_fee()
    }
}

pub struct Timing {
    pub in_offset_ms: f64,
    pub in_step_ms: f64,
    pub pre_offset_ms: f64,
}

pub struct Design {
    pub grid_ms: Vec<f64>,
    pub quota: HashMap<Arm, u32>,
    /// pairs planned so far, per family and arm
    pub planned: HashMap<(String, Arm), u32>,
    pub timing: Timing,
    pub pairs_per_window: usize,
}

impl Design {
    pub fn new(grid_ms: Vec<f64>, quota_scale: f64, timing: Timing, pairs_per_window: usize) -> Self {
        let quota = ARMS.iter().map(|a| (*a, ((a.default_quota() as f64) * quota_scale).ceil() as u32)).collect();
        Self { grid_ms, quota, planned: HashMap::new(), timing, pairs_per_window }
    }

    fn remaining(&self, family: &str, arm: Arm) -> u32 {
        let done = self.planned.get(&(family.to_string(), arm)).copied().unwrap_or(0);
        self.quota[&arm].saturating_sub(done)
    }

    pub fn family_done(&self, family: &str) -> bool {
        ARMS.iter().all(|a| self.remaining(family, *a) == 0)
    }

    /// Plans one window for `family`: either all pairs before the window (PRE/KEY) or all inside
    /// (FEE/REV/TIE), chosen in proportion to what is still missing. `None` if the family is done.
    pub fn plan_window(&mut self, family: &str, rng: &mut StdRng) -> Option<Vec<PairPlan>> {
        let pre: u32 = ARMS.iter().filter(|a| a.pre_window()).map(|a| self.remaining(family, *a)).sum();
        let inw: u32 = ARMS.iter().filter(|a| !a.pre_window()).map(|a| self.remaining(family, *a)).sum();
        if pre + inw == 0 {
            return None;
        }
        let pre_window = rng.gen_range(0..pre + inw) < pre;
        let mut pairs = Vec::new();
        for j in 0..self.pairs_per_window {
            let candidates: Vec<(Arm, u32)> = ARMS
                .iter()
                .filter(|a| a.pre_window() == pre_window)
                .map(|a| (*a, self.remaining(family, *a)))
                .filter(|(_, r)| *r > 0)
                .collect();
            let total: u32 = candidates.iter().map(|(_, r)| r).sum();
            if total == 0 {
                break;
            }
            let mut pick = rng.gen_range(0..total);
            let arm = candidates
                .iter()
                .find(|(_, r)| {
                    if pick < *r {
                        true
                    } else {
                        pick -= r;
                        false
                    }
                })
                .map(|(a, _)| *a)
                .unwrap();
            let (a, b) = arm.params();
            let s_ms = match arm {
                Arm::Fee | Arm::Tie => *self.grid_ms.choose(rng).unwrap(),
                Arm::Rev => *REV_GRID_MS.choose(rng).unwrap(),
                Arm::Pre => *PRE_GRID_MS.choose(rng).unwrap(),
                _ => {
                    if rng.gen_bool(0.5) {
                        KEY_GAP_MS
                    } else {
                        -KEY_GAP_MS
                    }
                }
            };
            let a_offset_ms = if pre_window {
                self.timing.pre_offset_ms + 2.0 * j as f64
            } else {
                self.timing.in_offset_ms + self.timing.in_step_ms * j as f64
            };
            *self.planned.entry((family.to_string(), arm)).or_default() += 1;
            pairs.push(PairPlan { arm, a, b, a_offset_ms, s_ms });
        }
        Some(pairs)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use rand::SeedableRng;

    #[test]
    fn key_contrasts_separate_the_three_keys() {
        // (rc winner, price winner, total-fee winner); 0 = X (A), 1 = Y (B), 2 = tie
        let winner = |x: u64, y: u64| if x > y { 0 } else if y > x { 1 } else { 2 };
        let pattern = |f: &dyn Fn(&ProbeParams) -> u64| {
            [Arm::KeyC1, Arm::KeyC2, Arm::KeyC3].map(|arm| {
                let (x, y) = arm.params();
                winner(f(&x), f(&y))
            })
        };
        let rc = pattern(&|p| p.agave_priority());
        let price = pattern(&|p| p.cu_price);
        let fee = pattern(&|p| p.priority_fee());
        assert_eq!(rc, [0, 0, 0]);
        assert_eq!(price, [2, 1, 0]);
        assert_eq!(fee, [2, 1, 1]);
    }

    #[test]
    fn dear_beats_cheap_on_every_key() {
        assert!(DEAR.agave_priority() > CHEAP.agave_priority());
        assert!(DEAR.cu_price > CHEAP.cu_price);
        assert!(DEAR.priority_fee() > CHEAP.priority_fee());
        assert_eq!(CHEAP.priority_fee(), 500);
        assert_eq!(DEAR.priority_fee(), 3000);
    }

    #[test]
    fn quotas_are_filled_exactly() {
        let mut d = Design::new(DEFAULT_GRID_MS.to_vec(), 1.0, Timing { in_offset_ms: 150.0, in_step_ms: 150.0, pre_offset_ms: -500.0 }, 4);
        let mut rng = StdRng::seed_from_u64(7);
        let mut n = 0;
        while let Some(p) = d.plan_window("X", &mut rng) {
            n += p.len();
        }
        let total: u32 = ARMS.iter().map(|a| a.default_quota()).sum();
        assert_eq!(n as u32, total);
        assert!(d.family_done("X"));
    }
}
