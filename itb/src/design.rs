//! Experimental design: series, lanes, probe parameters, send-gap grids and per-family quotas.
//!
//! A pair is two probes A and B from the same payer (so they conflict and execute one after
//! the other). B is sent `s_ms` after A (negative: before A). The recorded outcome is whether
//! B lands before A in the block.
//!
//!   FEE      A cheap, B dear, s >= 0, inside the window      -> the clock curve G(s)
//!   REV      A cheap, B dear, s < 0  (B first)                 -> noise ceiling
//!   CTRL_C2  X (cheap, small loaded-data limit) and Y (dear, 64 MiB limit) together, before
//!            the window                                        -> which sort key
//!
//! Every pair rides in one lane. The lane changes only the requested CU limit (and with it the
//! CU price), never the lamports:
//!   VIP  600 CU       the key sits at ~98th percentile of mainnet
//!   ECO  200,000 CU   the wallet default and market median, key at ~50th-67th percentile

use std::collections::HashMap;
use std::path::Path;

use anyhow::{bail, Context, Result};
use rand::rngs::StdRng;
use rand::seq::SliceRandom;
use rand::Rng;
use serde::{Deserialize, Serialize};

use crate::tx::ProbeParams;

pub const KIB32: u32 = 32 * 1024;
pub const MIB64: u32 = 64 * 1024 * 1024;

/// VIP lane, priority fee 500 lamports
pub const CHEAP_VIP: ProbeParams = ProbeParams { cu_limit: 600, cu_price: 833_333, loaded_data: KIB32 };
/// VIP lane, priority fee 3000 lamports
pub const DEAR_VIP: ProbeParams = ProbeParams { cu_limit: 600, cu_price: 5_000_000, loaded_data: KIB32 };
/// ECO lane, priority fee 500 lamports
pub const CHEAP_ECO: ProbeParams = ProbeParams { cu_limit: 200_000, cu_price: 2_500, loaded_data: KIB32 };
/// ECO lane, priority fee 3000 lamports
pub const DEAR_ECO: ProbeParams = ProbeParams { cu_limit: 200_000, cu_price: 15_000, loaded_data: KIB32 };
/// C2 control: X wins on reward/cost and on cost alone, Y on CU price and on total fee.
pub const C2_X: ProbeParams = CHEAP_VIP;
pub const C2_Y: ProbeParams = ProbeParams { cu_limit: 600, cu_price: 5_000_000, loaded_data: MIB64 };

/// Base grid of the main run (30% of FEE pairs); ECO adds `ECO_EXTRA_GRID_MS`.
pub const BASE_GRID_MS: &[f64] =
    &[0.0, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0, 10.0, 12.0, 15.0, 18.0, 21.0, 25.0, 30.0, 35.0, 40.0, 50.0, 60.0, 80.0, 100.0, 150.0];
pub const ECO_EXTRA_GRID_MS: &[f64] = &[200.0, 300.0];
pub const PILOT_GRID_MS: &[f64] = &[0.0, 5.0, 20.0, 60.0, 150.0];
pub const REV_GRID_MS: &[f64] = &[-2.0, -5.0, -10.0, -20.0];
pub const PILOT_REV_GRID_MS: &[f64] = &[-5.0, -20.0];
/// Gap between X and Y of a C2 pair; the sign (who goes first) is random.
pub const CTRL_GAP_MS: f64 = 0.3;
/// Share of FEE pairs drawn uniformly from [0, 2 mu_hat] once a pilot estimate exists.
pub const UNIFORM_SHARE: f64 = 0.7;
/// Payer keys reserved per concurrent window: the largest window (small families).
pub const PAYERS_PER_WINDOW: usize = 6;
/// Unstaked QUIC limit is 20 streams per 100 ms per connection; we stay at 8.
pub const MAX_STREAMS_PER_100MS: usize = 8;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize)]
pub enum Lane {
    #[serde(rename = "VIP")]
    Vip,
    #[serde(rename = "ECO")]
    Eco,
}

pub const LANES: &[Lane] = &[Lane::Vip, Lane::Eco];

impl Lane {
    /// (A cheap, B dear)
    pub fn params(self) -> (ProbeParams, ProbeParams) {
        match self {
            Lane::Vip => (CHEAP_VIP, DEAR_VIP),
            Lane::Eco => (CHEAP_ECO, DEAR_ECO),
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize)]
pub enum Series {
    #[serde(rename = "FEE")]
    Fee,
    #[serde(rename = "REV")]
    Rev,
    #[serde(rename = "CTRL_C2")]
    CtrlC2,
}

impl Series {
    pub fn pre_window(self) -> bool {
        self == Series::CtrlC2
    }
}

/// Every (series, lane) cell that has a quota. C2 runs in the VIP lane only.
pub const CELLS: &[(Series, Lane)] = &[
    (Series::Fee, Lane::Vip),
    (Series::Fee, Lane::Eco),
    (Series::Rev, Lane::Vip),
    (Series::Rev, Lane::Eco),
    (Series::CtrlC2, Lane::Vip),
];

pub fn cell_params(series: Series, lane: Lane) -> (ProbeParams, ProbeParams) {
    match series {
        Series::Fee | Series::Rev => lane.params(),
        Series::CtrlC2 => (C2_X, C2_Y),
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
pub enum FamilyClass {
    #[serde(rename = "main")]
    Main,
    #[serde(rename = "small")]
    Small,
}

pub const MAIN_FAMILIES: &[&str] = &["AgaveBam", "JitoLabs", "HarmonicAgave", "HarmonicFiredancer", "Firedancer"];

impl FamilyClass {
    pub fn of(family: &str) -> Self {
        if MAIN_FAMILIES.contains(&family) {
            FamilyClass::Main
        } else {
            FamilyClass::Small
        }
    }

    pub fn quota(self, series: Series, lane: Lane) -> u32 {
        match (self, series, lane) {
            (_, Series::CtrlC2, Lane::Eco) => 0,
            (FamilyClass::Main, Series::Fee, _) => 160,
            (FamilyClass::Main, Series::Rev, _) => 15,
            (FamilyClass::Main, Series::CtrlC2, _) => 15,
            (FamilyClass::Small, Series::Fee, _) => 50,
            (FamilyClass::Small, Series::Rev, _) => 5,
            (FamilyClass::Small, Series::CtrlC2, _) => 10,
        }
    }

    /// Small families lead rarely, so their windows carry more pairs.
    pub fn pairs_per_window(self) -> usize {
        match self {
            FamilyClass::Main => 4,
            FamilyClass::Small => PAYERS_PER_WINDOW,
        }
    }
}

/// Where the s of a FEE pair comes from, per (family, lane).
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct GridSpec {
    /// s drawn uniformly from [lo, hi] with probability `uniform_share`
    #[serde(default)]
    pub uniform_ms: Option<(f64, f64)>,
    #[serde(default)]
    pub uniform_share: f64,
    /// otherwise one of these points
    pub points_ms: Vec<f64>,
    /// pilot estimate the uniform range was derived from (record only)
    #[serde(default)]
    pub mu_hat_ms: Option<f64>,
}

impl GridSpec {
    pub fn points(points: &[f64]) -> Self {
        GridSpec { uniform_ms: None, uniform_share: 0.0, points_ms: points.to_vec(), mu_hat_ms: None }
    }

    /// The main-run rule (§6.5): 70% uniform in [0, 2 mu_hat], at least [0, 10] and at most
    /// [0, 300] ms; 30% the base grid (ECO adds 200 and 300 ms).
    pub fn from_mu_hat(mu_hat_ms: f64, lane: Lane) -> Self {
        let hi = (2.0 * mu_hat_ms).clamp(10.0, 300.0);
        GridSpec { uniform_ms: Some((0.0, hi)), uniform_share: UNIFORM_SHARE, mu_hat_ms: Some(mu_hat_ms), ..Self::default_for(lane) }
    }

    pub fn default_for(lane: Lane) -> Self {
        let mut points = BASE_GRID_MS.to_vec();
        if lane == Lane::Eco {
            points.extend_from_slice(ECO_EXTRA_GRID_MS);
        }
        GridSpec::points(&points)
    }

    pub fn draw(&self, rng: &mut StdRng) -> f64 {
        match self.uniform_ms {
            Some((lo, hi)) if rng.gen_bool(self.uniform_share.clamp(0.0, 1.0)) => {
                // whole tenths of a ms: the recorded actual s carries the precision
                (rng.gen_range(lo..=hi) * 10.0).round() / 10.0
            }
            _ => *self.points_ms.choose(rng).expect("non-empty grid"),
        }
    }

    pub fn max_ms(&self) -> f64 {
        let p = self.points_ms.iter().copied().fold(0.0, f64::max);
        self.uniform_ms.map_or(p, |(_, hi)| p.max(hi))
    }
}

/// The frozen design file (`design/grids.json`): grids per family and lane, the REV grid.
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct DesignFile {
    #[serde(default)]
    pub frozen_utc: Option<String>,
    #[serde(default)]
    pub grids: HashMap<String, HashMap<Lane, GridSpec>>,
    #[serde(default)]
    pub rev_ms: Option<Vec<f64>>,
}

impl DesignFile {
    pub fn read(path: &Path) -> Result<Self> {
        let s = std::fs::read_to_string(path).with_context(|| format!("design file {}", path.display()))?;
        let d: DesignFile = serde_json::from_str(&s).with_context(|| format!("design file {}", path.display()))?;
        for (fam, lanes) in &d.grids {
            for (lane, g) in lanes {
                if g.points_ms.is_empty() || g.points_ms.iter().any(|s| *s < 0.0) {
                    bail!("design file: {fam}/{lane:?} needs non-negative grid points");
                }
                if g.max_ms() > 300.0 {
                    bail!("design file: {fam}/{lane:?} reaches {} ms, above 300", g.max_ms());
                }
            }
        }
        if d.rev_ms.as_ref().is_some_and(|r| r.is_empty() || r.iter().any(|s| *s >= 0.0)) {
            bail!("design file: rev_ms must be negative");
        }
        Ok(d)
    }
}

#[derive(Clone, Debug, Serialize)]
pub struct PairPlan {
    pub series: Series,
    pub lane: Lane,
    pub a: ProbeParams,
    pub b: ProbeParams,
    /// fire time of A relative to the window anchor
    pub a_offset_ms: f64,
    /// fire time of B minus fire time of A
    pub s_ms: f64,
}

impl PairPlan {
    pub fn max_fee(&self) -> u64 {
        self.a.total_fee() + self.b.total_fee()
    }

    /// Fire times of the two probes relative to the anchor, earliest first.
    pub fn fire_offsets(&self) -> [f64; 2] {
        let b = self.a_offset_ms + self.s_ms;
        if b < self.a_offset_ms {
            [b, self.a_offset_ms]
        } else {
            [self.a_offset_ms, b]
        }
    }
}

pub struct Timing {
    /// in-window probes fire within [lo, hi] ms of the window anchor
    pub start_lo_ms: f64,
    pub start_hi_ms: f64,
    /// C2 pairs fire this far from the anchor (negative: before the window)
    pub ctrl_offset_ms: f64,
}

impl Default for Timing {
    fn default() -> Self {
        Timing { start_lo_ms: 120.0, start_hi_ms: 650.0, ctrl_offset_ms: -300.0 }
    }
}

pub struct Design {
    pub grids: HashMap<String, HashMap<Lane, GridSpec>>,
    /// overrides every FEE grid when set (`--grid`)
    pub grid_override: Option<Vec<f64>>,
    pub rev_grid_ms: Vec<f64>,
    pub quota_scale: f64,
    /// pairs planned so far, per family and cell
    pub planned: HashMap<(String, Series, Lane), u32>,
    pub timing: Timing,
}

impl Design {
    pub fn new(file: DesignFile, grid_override: Option<Vec<f64>>, rev_grid_ms: Option<Vec<f64>>, quota_scale: f64, timing: Timing) -> Self {
        let rev_grid_ms = rev_grid_ms.or(file.rev_ms).unwrap_or_else(|| REV_GRID_MS.to_vec());
        Self { grids: file.grids, grid_override, rev_grid_ms, quota_scale, planned: HashMap::new(), timing }
    }

    pub fn quota(&self, family: &str, series: Series, lane: Lane) -> u32 {
        ((FamilyClass::of(family).quota(series, lane) as f64) * self.quota_scale).ceil() as u32
    }

    pub fn remaining(&self, family: &str, series: Series, lane: Lane) -> u32 {
        let done = self.planned.get(&(family.to_string(), series, lane)).copied().unwrap_or(0);
        self.quota(family, series, lane).saturating_sub(done)
    }

    /// Returns a planned pair that never left (late, no connection, no anchor event) to the quota.
    pub fn release(&mut self, family: &str, series: Series, lane: Lane) {
        if let Some(n) = self.planned.get_mut(&(family.to_string(), series, lane)) {
            *n = n.saturating_sub(1);
        }
    }

    pub fn family_done(&self, family: &str) -> bool {
        CELLS.iter().all(|(s, l)| self.remaining(family, *s, *l) == 0)
    }

    pub fn fee_grid(&self, family: &str, lane: Lane) -> GridSpec {
        if let Some(g) = &self.grid_override {
            return GridSpec::points(g);
        }
        self.grids.get(family).and_then(|m| m.get(&lane)).cloned().unwrap_or_else(|| GridSpec::default_for(lane))
    }

    /// Picks the cells of one window. FEE pairs are split evenly between the lanes; REV and
    /// C2 are mixed in by what is left of their quotas. `None` if the family is done.
    fn pick_cells(&self, family: &str, rng: &mut StdRng) -> Option<Vec<(Series, Lane)>> {
        let n = FamilyClass::of(family).pairs_per_window();
        let mut left: HashMap<(Series, Lane), u32> = CELLS.iter().map(|c| (*c, self.remaining(family, c.0, c.1))).collect();
        let fee: u32 = LANES.iter().map(|l| left[&(Series::Fee, *l)]).sum();
        let other: u32 = left.iter().filter(|(c, _)| c.0 != Series::Fee).map(|(_, r)| r).sum();
        if fee + other == 0 {
            return None;
        }
        let share = other as f64 / (fee + other) as f64;
        let n_other = ((0..n).filter(|_| rng.gen_bool(share)).count() as u32).min(other);
        let n_fee = (n as u32 - n_other).min(fee);

        let mut picks = Vec::with_capacity(n);
        let (fv, fe) = (left[&(Series::Fee, Lane::Vip)], left[&(Series::Fee, Lane::Eco)]);
        let mut v = n_fee / 2;
        let mut e = n_fee / 2;
        if n_fee % 2 == 1 {
            // the odd pair goes to the lane with more left (coin flip on a tie)
            if fv > fe || (fv == fe && rng.gen_bool(0.5)) {
                v += 1;
            } else {
                e += 1;
            }
        }
        if v > fv {
            e += v - fv;
            v = fv;
        }
        if e > fe {
            v = (v + e - fe).min(fv);
            e = fe;
        }
        picks.extend(std::iter::repeat_n((Series::Fee, Lane::Vip), v as usize));
        picks.extend(std::iter::repeat_n((Series::Fee, Lane::Eco), e as usize));
        *left.get_mut(&(Series::Fee, Lane::Vip)).unwrap() -= v;
        *left.get_mut(&(Series::Fee, Lane::Eco)).unwrap() -= e;

        // the rest, weighted by what is left: first the non-FEE draws, then anything to fill up
        let draw = |left: &mut HashMap<(Series, Lane), u32>, rng: &mut StdRng, non_fee: bool| -> Option<(Series, Lane)> {
            let cands: Vec<((Series, Lane), u32)> =
                CELLS.iter().filter(|c| !non_fee || c.0 != Series::Fee).map(|c| (*c, left[c])).filter(|(_, r)| *r > 0).collect();
            let total: u32 = cands.iter().map(|(_, r)| r).sum();
            if total == 0 {
                return None;
            }
            let mut k = rng.gen_range(0..total);
            for (c, r) in cands {
                if k < r {
                    *left.get_mut(&c).unwrap() -= 1;
                    return Some(c);
                }
                k -= r;
            }
            None
        };
        for _ in 0..n_other {
            if let Some(c) = draw(&mut left, rng, true) {
                picks.push(c);
            }
        }
        while picks.len() < n {
            match draw(&mut left, rng, false) {
                Some(c) => picks.push(c),
                None => break,
            }
        }
        picks.shuffle(rng);
        Some(picks)
    }

    /// Draws A's fire time for every in-window pair uniformly in [lo + max(0, -s), hi - max(0, s)],
    /// so that both probes of every pair fall in [lo, hi]; redraws until no 100 ms span holds
    /// more than `MAX_STREAMS_PER_100MS` writes.
    fn place(&self, pairs: &mut [PairPlan], rng: &mut StdRng) {
        let (lo, hi) = (self.timing.start_lo_ms, self.timing.start_hi_ms);
        for attempt in 0..200 {
            for p in pairs.iter_mut() {
                if p.series.pre_window() {
                    p.a_offset_ms = self.timing.ctrl_offset_ms + rng.gen_range(-20.0..=20.0);
                    continue;
                }
                let a_lo = lo + (-p.s_ms).max(0.0);
                let a_hi = (hi - p.s_ms.max(0.0)).max(a_lo);
                p.a_offset_ms = (rng.gen_range(a_lo..=a_hi) * 10.0).round() / 10.0;
            }
            if max_streams_per_100ms(pairs) <= MAX_STREAMS_PER_100MS || attempt == 199 {
                return;
            }
        }
    }

    /// Plans one window for `family`. `None` if the family is done.
    pub fn plan_window(&mut self, family: &str, rng: &mut StdRng) -> Option<Vec<PairPlan>> {
        let cells = self.pick_cells(family, rng)?;
        let span = self.timing.start_hi_ms - self.timing.start_lo_ms;
        let mut pairs: Vec<PairPlan> = cells
            .into_iter()
            .map(|(series, lane)| {
                let (a, b) = cell_params(series, lane);
                let s_ms = match series {
                    Series::Fee => self.fee_grid(family, lane).draw(rng).min(span),
                    Series::Rev => *self.rev_grid_ms.choose(rng).unwrap(),
                    Series::CtrlC2 => {
                        if rng.gen_bool(0.5) {
                            CTRL_GAP_MS
                        } else {
                            -CTRL_GAP_MS
                        }
                    }
                };
                PairPlan { series, lane, a, b, a_offset_ms: 0.0, s_ms }
            })
            .collect();
        self.place(&mut pairs, rng);
        for p in &pairs {
            *self.planned.entry((family.to_string(), p.series, p.lane)).or_default() += 1;
        }
        Some(pairs)
    }
}

/// Largest number of probe writes inside any 100 ms span.
pub fn max_streams_per_100ms(pairs: &[PairPlan]) -> usize {
    let mut t: Vec<f64> = pairs.iter().flat_map(|p| p.fire_offsets()).collect();
    t.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let mut best = 0;
    let mut j = 0;
    for i in 0..t.len() {
        while t[i] - t[j] >= 100.0 {
            j += 1;
        }
        best = best.max(i - j + 1);
    }
    best
}

#[cfg(test)]
mod tests {
    use super::*;
    use rand::SeedableRng;

    fn design(scale: f64) -> Design {
        Design::new(DesignFile::default(), None, None, scale, Timing::default())
    }

    #[test]
    fn lanes_cost_the_same_lamports() {
        assert_eq!(CHEAP_VIP.total_fee(), CHEAP_ECO.total_fee());
        assert_eq!(DEAR_VIP.total_fee(), DEAR_ECO.total_fee());
        assert_eq!(CHEAP_VIP.priority_fee(), 500);
        assert_eq!(CHEAP_ECO.priority_fee(), 500);
        assert_eq!(DEAR_VIP.priority_fee(), 3000);
        assert_eq!(DEAR_ECO.priority_fee(), 3000);
        assert_eq!(CHEAP_VIP.total_fee() + DEAR_VIP.total_fee(), 13_500);
        assert_eq!(C2_X.total_fee() + C2_Y.total_fee(), 13_500);
    }

    #[test]
    fn dear_beats_cheap_on_every_key_in_both_lanes() {
        for lane in LANES {
            let (a, b) = lane.params();
            assert!(b.agave_priority() > a.agave_priority(), "{lane:?} reward/cost");
            assert!(b.cu_price > a.cu_price, "{lane:?} CU price");
            assert!(b.priority_fee() > a.priority_fee(), "{lane:?} priority fee");
            assert!(b.total_fee() > a.total_fee(), "{lane:?} total fee");
            assert_eq!(a.agave_cost(), b.agave_cost(), "{lane:?}: equal cost, different reward");
        }
        // the lanes sit far apart in rank
        assert!(CHEAP_VIP.agave_priority() > 50 * DEAR_ECO.agave_priority());
        assert_eq!(CHEAP_VIP.agave_priority(), 1_549_586);
        assert_eq!(DEAR_VIP.agave_priority(), 2_840_909);
        assert_eq!(CHEAP_ECO.agave_priority(), 14_900);
        assert_eq!(DEAR_ECO.agave_priority(), 27_317);
    }

    #[test]
    fn c2_separates_the_keys() {
        // winner: 0 = X, 1 = Y, 2 = tie; higher wins except for cost, where lower wins
        let higher = |x: u64, y: u64| if x > y { 0 } else if y > x { 1 } else { 2 };
        let (x, y) = cell_params(Series::CtrlC2, Lane::Vip);
        assert_eq!(higher(x.agave_priority(), y.agave_priority()), 0, "reward/cost: X");
        assert_eq!(higher(x.cu_price, y.cu_price), 1, "CU price: Y");
        assert_eq!(higher(x.total_fee(), y.total_fee()), 1, "total fee: Y");
        assert_eq!(higher(y.agave_cost(), x.agave_cost()), 0, "cost alone: X");
        assert_eq!(y.agave_cost(), 18_311);
    }

    #[test]
    fn quotas_are_filled_exactly() {
        for (family, class) in [("AgaveBam", FamilyClass::Main), ("Rakurai", FamilyClass::Small)] {
            let mut d = design(1.0);
            let mut rng = StdRng::seed_from_u64(7);
            let mut got: HashMap<(Series, Lane), u32> = HashMap::new();
            let mut windows = 0;
            while let Some(p) = d.plan_window(family, &mut rng) {
                assert!(!p.is_empty() && p.len() <= class.pairs_per_window());
                windows += 1;
                for x in p {
                    *got.entry((x.series, x.lane)).or_default() += 1;
                }
            }
            for (s, l) in CELLS {
                assert_eq!(got.get(&(*s, *l)).copied().unwrap_or(0), class.quota(*s, *l), "{family} {s:?} {l:?}");
            }
            assert!(d.family_done(family));
            let total: u32 = CELLS.iter().map(|(s, l)| class.quota(*s, *l)).sum();
            assert_eq!(windows, total.div_ceil(class.pairs_per_window() as u32) as usize, "{family}: windows are full");
        }
        assert_eq!(CELLS.iter().map(|(s, l)| FamilyClass::Main.quota(*s, *l)).sum::<u32>(), 365);
        assert_eq!(CELLS.iter().map(|(s, l)| FamilyClass::Small.quota(*s, *l)).sum::<u32>(), 120);
    }

    #[test]
    fn fee_pairs_are_split_evenly_between_lanes() {
        let mut d = design(1.0);
        let mut rng = StdRng::seed_from_u64(11);
        let mut checked = 0;
        loop {
            let both_left = d.remaining("JitoLabs", Series::Fee, Lane::Vip) > 0 && d.remaining("JitoLabs", Series::Fee, Lane::Eco) > 0;
            let Some(p) = d.plan_window("JitoLabs", &mut rng) else { break };
            let v = p.iter().filter(|x| x.series == Series::Fee && x.lane == Lane::Vip).count() as i64;
            let e = p.iter().filter(|x| x.series == Series::Fee && x.lane == Lane::Eco).count() as i64;
            if both_left {
                assert!((v - e).abs() <= 1, "window with {v} VIP and {e} ECO FEE pairs");
                checked += 1;
            }
        }
        assert!(checked > 50);
    }

    #[test]
    fn start_moments_are_random_and_inside_the_window() {
        let mut d = design(1.0);
        let mut rng = StdRng::seed_from_u64(3);
        let mut offsets = Vec::new();
        while let Some(p) = d.plan_window("HarmonicAgave", &mut rng) {
            assert!(max_streams_per_100ms(&p) <= MAX_STREAMS_PER_100MS);
            for x in p {
                let [first, last] = x.fire_offsets();
                if x.series.pre_window() {
                    assert!((-320.5..=-279.5).contains(&first) && last < 0.0, "{x:?}");
                } else {
                    assert!(first >= 120.0 - 1e-9 && last <= 650.0 + 1e-9, "{x:?}");
                    if x.series == Series::Fee {
                        assert!(x.s_ms >= 0.0);
                        offsets.push(x.a_offset_ms);
                    } else {
                        assert!(x.s_ms < 0.0);
                    }
                }
            }
        }
        // spread over the window, not on a fixed step
        let early = offsets.iter().filter(|o| **o < 250.0).count();
        let late = offsets.iter().filter(|o| **o > 450.0).count();
        assert!(early > 30 && late > 15, "early {early}, late {late}");
        let distinct: std::collections::HashSet<i64> = offsets.iter().map(|o| (*o * 10.0) as i64).collect();
        assert!(distinct.len() > offsets.len() / 2);
    }

    #[test]
    fn grid_rule_from_pilot_estimate() {
        let g = GridSpec::from_mu_hat(3.0, Lane::Vip);
        assert_eq!(g.uniform_ms, Some((0.0, 10.0)));
        let g = GridSpec::from_mu_hat(40.0, Lane::Eco);
        assert_eq!(g.uniform_ms, Some((0.0, 80.0)));
        assert!(g.points_ms.contains(&300.0));
        let g = GridSpec::from_mu_hat(400.0, Lane::Eco);
        assert_eq!(g.uniform_ms, Some((0.0, 300.0)));
        let mut rng = StdRng::seed_from_u64(1);
        let g = GridSpec::from_mu_hat(20.0, Lane::Vip);
        let draws: Vec<f64> = (0..2000).map(|_| g.draw(&mut rng)).collect();
        assert!(draws.iter().all(|s| (0.0..=150.0).contains(s)));
        let uniform = draws.iter().filter(|s| **s <= 40.0).count() as f64 / draws.len() as f64;
        assert!(uniform > 0.75, "share at or below 2 mu_hat {uniform}");
    }

    #[test]
    fn design_file_round_trip() {
        let mut f = DesignFile { frozen_utc: Some("2026-11-03T20:00:00Z".into()), ..Default::default() };
        f.grids.insert("AgaveBam".into(), [(Lane::Vip, GridSpec::from_mu_hat(20.0, Lane::Vip))].into_iter().collect());
        let s = serde_json::to_string(&f).unwrap();
        assert!(s.contains("\"VIP\""));
        let back: DesignFile = serde_json::from_str(&s).unwrap();
        let d = Design::new(back, None, None, 1.0, Timing::default());
        assert_eq!(d.fee_grid("AgaveBam", Lane::Vip).uniform_ms, Some((0.0, 40.0)));
        assert_eq!(d.fee_grid("AgaveBam", Lane::Eco), GridSpec::default_for(Lane::Eco));
    }
}
