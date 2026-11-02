//! Gossip snapshot (client family, version, TPU address), stake, target selection and
//! leader windows from the slot-leader schedule.

use std::collections::HashMap;
use std::net::SocketAddr;

use anyhow::{anyhow, Result};
use chrono::{DateTime, Utc};
use serde::Serialize;
use serde_json::{json, Value};

use crate::rpc::Rpc;

/// Client families measured, in order of stake.
pub const FAMILIES: &[&str] =
    &["AgaveBam", "JitoLabs", "HarmonicAgave", "HarmonicFiredancer", "Firedancer", "FireBAM", "Agave", "Rakurai"];

#[derive(Clone, Debug, Serialize)]
pub struct Node {
    pub identity: String,
    pub client_id: String,
    pub version: String,
    pub tpu_quic: Option<SocketAddr>,
    pub stake: u64,
}

pub struct Snapshot {
    pub taken_at: DateTime<Utc>,
    pub nodes: HashMap<String, Node>,
}

impl Snapshot {
    pub async fn take(rpc: &Rpc) -> Result<Self> {
        let taken_at = Utc::now();
        let gossip = rpc.call("getClusterNodes", json!([])).await?;
        let votes = rpc.call("getVoteAccounts", json!([{"commitment": "confirmed"}])).await?;
        let mut stake: HashMap<String, u64> = HashMap::new();
        for key in ["current", "delinquent"] {
            for v in votes[key].as_array().into_iter().flatten() {
                if let (Some(id), Some(s)) = (v["nodePubkey"].as_str(), v["activatedStake"].as_u64()) {
                    *stake.entry(id.to_string()).or_default() += s;
                }
            }
        }
        let mut nodes = HashMap::new();
        for n in gossip.as_array().ok_or_else(|| anyhow!("getClusterNodes: not an array"))? {
            let Some(id) = n["pubkey"].as_str() else { continue };
            nodes.insert(
                id.to_string(),
                Node {
                    identity: id.to_string(),
                    client_id: client_id(n),
                    version: n["version"].as_str().unwrap_or("").to_string(),
                    tpu_quic: n["tpuQuic"].as_str().and_then(|s| s.parse().ok()),
                    stake: stake.get(id).copied().unwrap_or(0),
                },
            );
        }
        Ok(Self { taken_at, nodes })
    }

    /// Top `per_family` staked validators of each family that advertise a QUIC TPU.
    pub fn targets(&self, families: &[String], per_family: usize) -> Vec<Node> {
        let mut out = Vec::new();
        for fam in families {
            let mut v: Vec<&Node> =
                self.nodes.values().filter(|n| &n.client_id == fam && n.stake > 0 && n.tpu_quic.is_some()).collect();
            v.sort_by(|a, b| b.stake.cmp(&a.stake));
            out.extend(v.into_iter().take(per_family).cloned());
        }
        out
    }

    /// The validators named by identity, in the given order; every one must be in gossip with a
    /// QUIC TPU and stake. The family is whatever gossip says now.
    pub fn named(&self, identities: &[String]) -> Result<Vec<Node>> {
        let mut out = Vec::new();
        for id in identities {
            let n = self.nodes.get(id).ok_or_else(|| anyhow!("validator {id}: not in gossip"))?;
            if n.tpu_quic.is_none() || n.stake == 0 {
                return Err(anyhow!("validator {id}: no QUIC TPU or no stake"));
            }
            out.push(n.clone());
        }
        Ok(out)
    }
}

fn client_id(n: &Value) -> String {
    match &n["clientId"] {
        Value::String(s) => s.clone(),
        Value::Number(x) => format!("Unknown({x})"),
        _ => "Unknown".to_string(),
    }
}

#[derive(Clone, Debug, Serialize)]
pub struct Window {
    pub leader: String,
    pub first_slot: u64,
    pub slots: u64,
}

/// Leader windows (runs of consecutive slots with one leader) starting at or after `start`.
pub async fn windows(rpc: &Rpc, start: u64, count: u64) -> Result<Vec<Window>> {
    let mut leaders = Vec::new();
    let mut s = start;
    while (leaders.len() as u64) < count {
        let n = (count - leaders.len() as u64).min(5000);
        let chunk = rpc.slot_leaders(s, n).await?;
        if chunk.is_empty() {
            break;
        }
        s += chunk.len() as u64;
        leaders.extend(chunk);
    }
    let mut out: Vec<Window> = Vec::new();
    for (i, l) in leaders.into_iter().enumerate() {
        let slot = start + i as u64;
        match out.last_mut() {
            Some(w) if w.leader == l && w.first_slot + w.slots == slot => w.slots += 1,
            _ => out.push(Window { leader: l, first_slot: slot, slots: 1 }),
        }
    }
    // The first run may be the tail of a window that started before `start`.
    if let Some(w) = out.first() {
        if w.slots < 4 {
            out.remove(0);
        }
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn node(id: &str, fam: &str, tpu: Option<&str>, stake: u64) -> (String, Node) {
        let n = Node { identity: id.into(), client_id: fam.into(), version: "1".into(), tpu_quic: tpu.map(|t| t.parse().unwrap()), stake };
        (id.into(), n)
    }

    #[test]
    fn targets_named_or_by_stake() {
        let snap = Snapshot {
            taken_at: Utc::now(),
            nodes: [
                node("big", "AgaveBam", Some("1.1.1.1:5010"), 30),
                node("mid", "AgaveBam", Some("1.1.1.2:5010"), 20),
                node("small", "AgaveBam", Some("1.1.1.3:5010"), 10),
                node("notpu", "Firedancer", None, 50),
                node("fd", "Firedancer", Some("2.2.2.2:9007"), 5),
            ]
            .into_iter()
            .collect(),
        };
        let ids = |v: Vec<Node>| v.into_iter().map(|n| n.identity).collect::<Vec<_>>();
        assert_eq!(ids(snap.targets(&["AgaveBam".into(), "Firedancer".into()], 2)), ["big", "mid", "fd"]);
        assert_eq!(ids(snap.named(&["small".into(), "fd".into()]).unwrap()), ["small", "fd"]);
        assert!(snap.named(&["nobody".into()]).is_err());
        assert!(snap.named(&["notpu".into()]).is_err());
    }
}
