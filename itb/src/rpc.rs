//! Minimal JSON-RPC client. Used for reading only (schedule, gossip, blockhash, simulation);
//! probes never go through RPC. Funding and sweeping transfers are the only `sendTransaction` calls.

use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Duration;

use anyhow::{anyhow, bail, Context, Result};
use base64::Engine;
use serde_json::{json, Value};

pub const DEFAULT_RPC: &str = "https://api.mainnet-beta.solana.com";

pub struct Rpc {
    pub url: String,
    http: reqwest::Client,
    id: AtomicU64,
}

impl Rpc {
    pub fn new(url: &str) -> Result<Self> {
        let http = reqwest::Client::builder()
            .timeout(Duration::from_secs(60))
            .user_agent("inside-the-block/0.1")
            .build()?;
        Ok(Self { url: url.to_string(), http, id: AtomicU64::new(1) })
    }

    pub fn ws_url(&self) -> String {
        if let Some(rest) = self.url.strip_prefix("https://") {
            format!("wss://{rest}")
        } else if let Some(rest) = self.url.strip_prefix("http://") {
            format!("ws://{rest}")
        } else {
            self.url.clone()
        }
    }

    pub async fn call(&self, method: &str, params: Value) -> Result<Value> {
        let body = json!({"jsonrpc": "2.0", "id": self.id.fetch_add(1, Ordering::Relaxed), "method": method, "params": params});
        let mut last_err = None;
        for attempt in 0..6u32 {
            match self.http.post(&self.url).json(&body).send().await {
                Ok(resp) if resp.status().as_u16() == 429 => {
                    let wait = resp
                        .headers()
                        .get("retry-after")
                        .and_then(|v| v.to_str().ok())
                        .and_then(|v| v.parse::<u64>().ok())
                        .unwrap_or(2 + attempt as u64);
                    last_err = Some(anyhow!("{method}: HTTP 429"));
                    tokio::time::sleep(Duration::from_secs(wait)).await;
                }
                Ok(resp) => {
                    let status = resp.status();
                    let v: Value = resp.json().await.with_context(|| format!("{method}: HTTP {status}, bad JSON"))?;
                    if let Some(e) = v.get("error") {
                        bail!("{method}: {e}");
                    }
                    return v.get("result").cloned().ok_or_else(|| anyhow!("{method}: no result"));
                }
                Err(e) => {
                    last_err = Some(anyhow!("{method}: {e}"));
                    tokio::time::sleep(Duration::from_millis(500 * (attempt as u64 + 1))).await;
                }
            }
        }
        Err(last_err.unwrap_or_else(|| anyhow!("{method}: failed")))
    }

    /// (blockhash bytes, last valid block height)
    pub async fn latest_blockhash(&self) -> Result<([u8; 32], u64)> {
        let v = self.call("getLatestBlockhash", json!([{"commitment": "confirmed"}])).await?;
        let s = v["value"]["blockhash"].as_str().ok_or_else(|| anyhow!("no blockhash"))?;
        let bytes: [u8; 32] = bs58::decode(s).into_vec()?.try_into().map_err(|_| anyhow!("blockhash not 32 bytes"))?;
        Ok((bytes, v["value"]["lastValidBlockHeight"].as_u64().unwrap_or(0)))
    }

    pub async fn balance(&self, pubkey: &str) -> Result<u64> {
        let v = self.call("getBalance", json!([pubkey, {"commitment": "confirmed"}])).await?;
        v["value"].as_u64().ok_or_else(|| anyhow!("getBalance: no value"))
    }

    pub async fn minimum_rent_exempt(&self, data_len: usize) -> Result<u64> {
        let v = self.call("getMinimumBalanceForRentExemption", json!([data_len])).await?;
        v.as_u64().ok_or_else(|| anyhow!("rent: not a number"))
    }

    pub async fn simulate(&self, tx: &[u8]) -> Result<Value> {
        let b64 = base64::engine::general_purpose::STANDARD.encode(tx);
        let v = self
            .call(
                "simulateTransaction",
                json!([b64, {"encoding": "base64", "sigVerify": false, "replaceRecentBlockhash": true, "commitment": "processed"}]),
            )
            .await?;
        Ok(v["value"].clone())
    }

    pub async fn send_transaction(&self, tx: &[u8]) -> Result<String> {
        let b64 = base64::engine::general_purpose::STANDARD.encode(tx);
        let v = self
            .call("sendTransaction", json!([b64, {"encoding": "base64", "preflightCommitment": "confirmed", "maxRetries": 5}]))
            .await?;
        v.as_str().map(str::to_string).ok_or_else(|| anyhow!("sendTransaction: no signature"))
    }

    /// Statuses for up to 256 signatures; `None` where the signature is unknown.
    pub async fn signature_statuses(&self, sigs: &[String]) -> Result<Vec<Option<Value>>> {
        let v = self.call("getSignatureStatuses", json!([sigs, {"searchTransactionHistory": true}])).await?;
        let arr = v["value"].as_array().ok_or_else(|| anyhow!("getSignatureStatuses: no value"))?;
        Ok(arr.iter().map(|x| if x.is_null() { None } else { Some(x.clone()) }).collect())
    }

    pub async fn slot_leaders(&self, start: u64, limit: u64) -> Result<Vec<String>> {
        let v = self.call("getSlotLeaders", json!([start, limit])).await?;
        Ok(v.as_array().ok_or_else(|| anyhow!("getSlotLeaders: not an array"))?.iter().filter_map(|x| x.as_str().map(str::to_string)).collect())
    }
}
