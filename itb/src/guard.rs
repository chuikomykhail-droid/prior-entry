//! The only way probe bytes reach a socket is through a `SendPermit`. A permit for mainnet is
//! issued after every check of the live mode has passed: the explicit `--live` flag, a spend cap
//! at or below the project limit, a `--not-after` deadline in the near future, mainnet by genesis
//! hash and a current slot after Alpenglow. The permit also refuses every send after the deadline.

use std::net::SocketAddr;

use anyhow::{bail, Result};
use chrono::{DateTime, Utc};
use serde_json::{json, Value};

use crate::rpc::Rpc;

pub const MAINNET_GENESIS: &str = "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d";
/// Alpenglow activation on mainnet: epoch 1064, 21.10.2026, slot ~459,653,000. All our
/// measurements must lie after it; the margin covers the approximation.
pub const ALPENGLOW_SLOT: u64 = 459_653_000;
pub const ALPENGLOW_MARGIN_SLOTS: u64 = 20_000;
/// Hard project limit on spend, enforced again here (the ledger enforces `--cap-sol`).
pub const HARD_CAP_LAMPORTS: u64 = 45_000_000;
/// A live run may not be armed for more than this long.
pub const MAX_ARMED_HOURS: i64 = 12;

pub struct SendPermit {
    not_after: Option<DateTime<Utc>>,
    loopback_only: bool,
}

/// Network facts checked before a run, recorded in `meta.json` in dry-run and live alike.
pub async fn network_check(rpc: &Rpc) -> Result<Value> {
    let genesis = rpc.call("getGenesisHash", json!([])).await?;
    let slot = rpc.call("getSlot", json!([{"commitment": "confirmed"}])).await?;
    let genesis = genesis.as_str().unwrap_or("").to_string();
    let slot = slot.as_u64().unwrap_or(0);
    Ok(json!({
        "genesis_hash": genesis, "mainnet": genesis == MAINNET_GENESIS, "slot": slot,
        "after_alpenglow": slot > ALPENGLOW_SLOT + ALPENGLOW_MARGIN_SLOTS, "alpenglow_slot_approx": ALPENGLOW_SLOT,
    }))
}

impl SendPermit {
    /// Issues the permit for live probes on mainnet, or explains which check failed.
    pub fn for_mainnet(live: bool, cap_lamports: u64, not_after: Option<DateTime<Utc>>, network: &Value) -> Result<Self> {
        if !live {
            bail!("sending needs --live");
        }
        if cap_lamports > HARD_CAP_LAMPORTS {
            bail!("--cap-sol {} is above the hard limit of {} SOL", cap_lamports as f64 / 1e9, HARD_CAP_LAMPORTS as f64 / 1e9);
        }
        let Some(na) = not_after else { bail!("--live needs --not-after <UTC>") };
        let now = Utc::now();
        if na <= now {
            bail!("--not-after {na} is in the past");
        }
        if na - now > chrono::Duration::hours(MAX_ARMED_HOURS) {
            bail!("--not-after {na} is more than {MAX_ARMED_HOURS} h away");
        }
        if network["mainnet"] != json!(true) {
            bail!("not mainnet: genesis hash {}", network["genesis_hash"]);
        }
        if network["after_alpenglow"] != json!(true) {
            bail!("current slot {} is not safely after Alpenglow", network["slot"]);
        }
        Ok(SendPermit { not_after: Some(na), loopback_only: false })
    }

    /// For the calibration sink on this machine: only loopback addresses.
    pub fn loopback() -> Self {
        SendPermit { not_after: None, loopback_only: true }
    }

    /// Whether a write to `addr` is allowed right now.
    pub fn check(&self, addr: SocketAddr) -> Result<()> {
        if self.loopback_only && !addr.ip().is_loopback() {
            bail!("loopback permit used for {addr}");
        }
        if self.not_after.is_some_and(|na| Utc::now() > na) {
            bail!("past --not-after");
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn net(mainnet: bool, after: bool) -> Value {
        json!({"mainnet": mainnet, "after_alpenglow": after, "genesis_hash": "x", "slot": 1})
    }

    #[test]
    fn permit_needs_every_check() {
        let soon = Some(Utc::now() + chrono::Duration::hours(1));
        assert!(SendPermit::for_mainnet(true, 45_000_000, soon, &net(true, true)).is_ok());
        assert!(SendPermit::for_mainnet(false, 45_000_000, soon, &net(true, true)).is_err());
        assert!(SendPermit::for_mainnet(true, 45_000_001, soon, &net(true, true)).is_err());
        assert!(SendPermit::for_mainnet(true, 1, None, &net(true, true)).is_err());
        assert!(SendPermit::for_mainnet(true, 1, Some(Utc::now() - chrono::Duration::seconds(1)), &net(true, true)).is_err());
        assert!(SendPermit::for_mainnet(true, 1, Some(Utc::now() + chrono::Duration::hours(13)), &net(true, true)).is_err());
        assert!(SendPermit::for_mainnet(true, 1, soon, &net(false, true)).is_err());
        assert!(SendPermit::for_mainnet(true, 1, soon, &net(true, false)).is_err());
    }

    #[test]
    fn loopback_permit_stays_local() {
        let p = SendPermit::loopback();
        assert!(p.check("127.0.0.1:8009".parse().unwrap()).is_ok());
        assert!(p.check("1.2.3.4:8009".parse().unwrap()).is_err());
    }
}
