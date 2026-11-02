//! Collection after a run: where every sent probe landed, and an extract of every block that
//! holds one, for the rank and load covariates (§6.9). Read-only RPC.
//!
//!   landings.jsonl      one line per sent probe: slot, index in the block, error, fee charged
//!   blocks.jsonl.gz     one line per block: producer (fee-reward recipient), scheduled leader,
//!                       and per transaction, in block order, the inputs of the scheduler's key
//!
//! The key itself (reward * 1e6 / (cost + 1)) is rebuilt from these inputs by the analysis.
//! Re-running resumes: blocks already in the file are not fetched again.

use std::collections::{BTreeSet, HashMap, HashSet};
use std::fs::{self, File};
use std::io::{BufRead, BufReader, Write};
use std::path::Path;
use std::time::Duration;

use anyhow::{anyhow, Context, Result};
use flate2::read::MultiGzDecoder;
use flate2::write::GzEncoder;
use serde_json::{json, Value};

use crate::rpc::Rpc;

const COMPUTE_BUDGET: &str = "ComputeBudget111111111111111111111111111111";
const SYSTEM: &str = "11111111111111111111111111111111";
const VOTE: &str = "Vote111111111111111111111111111111111111111";

/// Inputs of the scheduler key for one transaction, rebuilt from the block.
#[derive(Debug, Default, PartialEq)]
pub struct TxRow {
    pub fee: u64,
    pub sigs: u64,
    pub writable: u64,
    pub data_bytes: u64,
    /// requested CU limit, or the default the runtime assumes when none is set
    pub cu_limit: u64,
    pub cu_limit_set: bool,
    pub cu_price: u64,
    pub data_limit: u64,
    pub cu_consumed: u64,
    pub ok: bool,
    pub vote: bool,
}

/// One transaction of a `getBlock` response (`encoding: json`).
pub fn tx_row(tx: &Value) -> Result<TxRow> {
    let msg = &tx["transaction"]["message"];
    let meta = &tx["meta"];
    let h = &msg["header"];
    let keys: Vec<&str> = msg["accountKeys"].as_array().context("accountKeys")?.iter().filter_map(|k| k.as_str()).collect();
    let loaded_w: Vec<&str> =
        meta["loadedAddresses"]["writable"].as_array().map(|a| a.iter().filter_map(|k| k.as_str()).collect()).unwrap_or_default();
    let loaded_r: Vec<&str> =
        meta["loadedAddresses"]["readonly"].as_array().map(|a| a.iter().filter_map(|k| k.as_str()).collect()).unwrap_or_default();
    let all: Vec<&str> = keys.iter().chain(&loaded_w).chain(&loaded_r).copied().collect();
    let sigs = tx["transaction"]["signatures"].as_array().map(|a| a.len() as u64).unwrap_or(1);
    let nrs = h["numRequiredSignatures"].as_u64().unwrap_or(1);
    let ros = h["numReadonlySignedAccounts"].as_u64().unwrap_or(0);
    let rou = h["numReadonlyUnsignedAccounts"].as_u64().unwrap_or(0);
    let writable = (nrs - ros) + (keys.len() as u64).saturating_sub(nrs + rou) + loaded_w.len() as u64;
    let mut row = TxRow { sigs, writable, data_limit: 64 * 1024 * 1024, ..Default::default() };
    let mut default_cu = 0u64;
    for ix in msg["instructions"].as_array().context("instructions")? {
        let program = ix["programIdIndex"].as_u64().and_then(|i| all.get(i as usize)).copied().unwrap_or("");
        let data = bs58::decode(ix["data"].as_str().unwrap_or("")).into_vec()?;
        row.data_bytes += data.len() as u64;
        match program {
            VOTE => row.vote = true,
            COMPUTE_BUDGET => {
                match data.first() {
                    Some(2) if data.len() >= 5 => {
                        row.cu_limit = u32::from_le_bytes(data[1..5].try_into()?) as u64;
                        row.cu_limit_set = true;
                    }
                    Some(3) if data.len() >= 9 => row.cu_price = u64::from_le_bytes(data[1..9].try_into()?),
                    Some(4) if data.len() >= 5 => row.data_limit = u32::from_le_bytes(data[1..5].try_into()?) as u64,
                    _ => {}
                }
                default_cu += 3_000;
            }
            SYSTEM => default_cu += 3_000,
            _ => default_cu += 200_000,
        }
    }
    if !row.cu_limit_set {
        row.cu_limit = default_cu.min(1_400_000);
    }
    row.fee = meta["fee"].as_u64().unwrap_or(0);
    row.cu_consumed = meta["computeUnitsConsumed"].as_u64().unwrap_or(0);
    row.ok = meta["err"].is_null();
    Ok(row)
}

/// Columnar extract of one block, plus the index of each signature we care about.
pub fn block_extract(slot: u64, block: &Value, leader: Option<&str>, ours: &HashSet<String>) -> Result<(Value, Vec<Value>)> {
    let txs = block["transactions"].as_array().ok_or_else(|| anyhow!("block {slot}: no transactions"))?;
    let producer = block["rewards"]
        .as_array()
        .and_then(|r| r.iter().find(|x| x["rewardType"].as_str() == Some("Fee")))
        .and_then(|x| x["pubkey"].as_str())
        .map(str::to_string);
    let mut cols: HashMap<&str, Vec<Value>> = HashMap::new();
    let mut landings = Vec::new();
    for (i, tx) in txs.iter().enumerate() {
        let r = tx_row(tx).unwrap_or_default();
        for (k, v) in [
            ("fee", json!(r.fee)),
            ("sigs", json!(r.sigs)),
            ("writable", json!(r.writable)),
            ("data_bytes", json!(r.data_bytes)),
            ("cu_limit", json!(r.cu_limit)),
            ("cu_limit_set", json!(r.cu_limit_set as u8)),
            ("cu_price", json!(r.cu_price)),
            ("data_limit", json!(r.data_limit)),
            ("cu_consumed", json!(r.cu_consumed)),
            ("ok", json!(r.ok as u8)),
            ("vote", json!(r.vote as u8)),
        ] {
            cols.entry(k).or_default().push(v);
        }
        if let Some(sig) = tx["transaction"]["signatures"][0].as_str() {
            if ours.contains(sig) {
                landings.push(json!({"signature": sig, "slot": slot, "index": i, "fee": r.fee, "cu_consumed": r.cu_consumed,
                                     "ok": r.ok, "err": tx["meta"]["err"], "producer": producer, "leader": leader}));
            }
        }
    }
    let extract = json!({
        "slot": slot, "parent_slot": block["parentSlot"], "block_time": block["blockTime"], "block_height": block["blockHeight"],
        "blockhash": block["blockhash"], "producer": producer, "leader": leader, "n_tx": txs.len(), "tx": cols,
    });
    Ok((extract, landings))
}

fn read_jsonl(path: &Path) -> Result<Vec<Value>> {
    let f = File::open(path).with_context(|| format!("{}", path.display()))?;
    let reader: Box<dyn BufRead> =
        if path.extension().is_some_and(|e| e == "gz") { Box::new(BufReader::new(MultiGzDecoder::new(f))) } else { Box::new(BufReader::new(f)) };
    let mut out = Vec::new();
    for line in reader.lines() {
        let line = line?;
        if !line.trim().is_empty() {
            out.push(serde_json::from_str(&line)?);
        }
    }
    Ok(out)
}

async fn get_block(rpc: &Rpc, slot: u64) -> Result<Option<Value>> {
    let params = json!([slot, {"encoding": "json", "transactionDetails": "full", "rewards": true,
                               "maxSupportedTransactionVersion": 1, "commitment": "finalized"}]);
    match rpc.call("getBlock", params).await {
        Ok(v) if v.is_null() => Ok(None),
        Ok(v) => Ok(Some(v)),
        // skipped slots and slots not (yet) available answer with an error
        Err(e) if format!("{e:#}").contains("-32007") || format!("{e:#}").contains("-32009") => Ok(None),
        Err(e) => Err(e),
    }
}

/// `itb collect`: statuses of every sent probe of the run in `run_dir`, then the blocks.
/// `extra_slots` adds blocks to extract regardless of probes (used to test the extractor).
pub async fn collect(rpc: &Rpc, run_dir: &Path, extra_slots: &[u64], pace: Duration) -> Result<()> {
    let txs_path = run_dir.join("txs.jsonl");
    let txs = if txs_path.exists() { read_jsonl(&txs_path)? } else { Vec::new() };
    let sigs: Vec<String> = txs
        .iter()
        .filter(|v| v["sent"].as_bool() == Some(true))
        .filter_map(|v| v["signature"].as_str().map(str::to_string))
        .collect();
    println!("{}: {} probes in the journal, {} sent", run_dir.display(), txs.len(), sigs.len());

    let mut status: HashMap<String, Value> = HashMap::new();
    for chunk in sigs.chunks(256) {
        let st = rpc.signature_statuses(chunk).await?;
        for (sig, s) in chunk.iter().zip(st) {
            if let Some(s) = s {
                status.insert(sig.clone(), s);
            }
        }
    }
    let mut slots: BTreeSet<u64> = status.values().filter_map(|s| s["slot"].as_u64()).collect();
    slots.extend(extra_slots);
    println!("{} of {} sent probes have a status, in {} blocks", status.len(), sigs.len(), slots.len());

    // scheduled leader of every slot, from the leader schedule
    let mut leaders: HashMap<u64, String> = HashMap::new();
    if let (Some(lo), Some(hi)) = (slots.first(), slots.last()) {
        let mut s = *lo;
        while s <= *hi {
            let n = (hi - s + 1).min(5000);
            for (i, l) in rpc.slot_leaders(s, n).await?.into_iter().enumerate() {
                leaders.insert(s + i as u64, l);
            }
            s += n;
        }
    }

    let blocks_path = run_dir.join("blocks.jsonl.gz");
    let mut done: HashSet<u64> = HashSet::new();
    let mut landings: Vec<Value> = Vec::new();
    if blocks_path.exists() {
        // resume: keep what is there, landings are rebuilt below from the kept blocks' records
        for b in read_jsonl(&blocks_path)? {
            if let Some(s) = b["slot"].as_u64() {
                done.insert(s);
            }
        }
        let lp = run_dir.join("landings.jsonl");
        if lp.exists() {
            landings = read_jsonl(&lp)?.into_iter().filter(|l| l["slot"].as_u64().is_some_and(|s| done.contains(&s))).collect();
        }
    }
    let ours: HashSet<String> = sigs.iter().cloned().collect();
    let file = fs::OpenOptions::new().create(true).append(true).open(&blocks_path)?;
    let mut gz = GzEncoder::new(file, flate2::Compression::default());
    let mut fetched = 0;
    for slot in &slots {
        if done.contains(slot) {
            continue;
        }
        let Some(block) = get_block(rpc, *slot).await? else {
            println!("slot {slot}: no block");
            continue;
        };
        let (extract, l) = block_extract(*slot, &block, leaders.get(slot).map(String::as_str), &ours)?;
        writeln!(gz, "{extract}")?;
        landings.extend(l);
        fetched += 1;
        if fetched % 10 == 0 {
            println!("{fetched} blocks fetched");
        }
        tokio::time::sleep(pace).await;
    }
    gz.finish()?;

    // probes with a status whose block we could not read keep the status alone
    let landed: HashSet<String> = landings.iter().filter_map(|l| l["signature"].as_str().map(str::to_string)).collect();
    for (sig, st) in &status {
        if !landed.contains(sig) {
            landings.push(json!({"signature": sig, "slot": st["slot"], "index": null, "err": st["err"], "status_only": true}));
        }
    }
    let mut f = File::create(run_dir.join("landings.jsonl"))?;
    for l in &landings {
        writeln!(f, "{l}")?;
    }
    let summary = json!({"utc": chrono::Utc::now().to_rfc3339(), "probes": txs.len(), "sent": sigs.len(),
                         "with_status": status.len(), "blocks": slots.len(), "blocks_fetched_now": fetched,
                         "landings_with_index": landed.len()});
    fs::write(run_dir.join("collect.json"), serde_json::to_string_pretty(&summary)?)?;
    println!("{summary}");
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn probe_row_matches_the_design() {
        // A VIP dear probe as getBlock (json) shows it.
        let ix = |data: Vec<u8>, p: u64| json!({"programIdIndex": p, "accounts": [], "data": bs58::encode(data).into_string()});
        let mut lim = vec![2u8];
        lim.extend(600u32.to_le_bytes());
        let mut price = vec![3u8];
        price.extend(5_000_000u64.to_le_bytes());
        let mut dl = vec![4u8];
        dl.extend((32u32 * 1024).to_le_bytes());
        let mut tr = 2u32.to_le_bytes().to_vec();
        tr.extend(0u64.to_le_bytes());
        let tx = json!({
            "transaction": {"signatures": ["x"], "message": {
                "header": {"numRequiredSignatures": 1, "numReadonlySignedAccounts": 0, "numReadonlyUnsignedAccounts": 2},
                "accountKeys": ["payer", "dest", COMPUTE_BUDGET, SYSTEM],
                "instructions": [ix(lim, 2), ix(price, 2), ix(dl, 2), ix(tr, 3)]}},
            "meta": {"fee": 8000, "err": null, "computeUnitsConsumed": 450, "loadedAddresses": {"writable": [], "readonly": []}}
        });
        let r = tx_row(&tx).unwrap();
        assert_eq!(r, TxRow { fee: 8000, sigs: 1, writable: 2, data_bytes: 31, cu_limit: 600, cu_limit_set: true,
                              cu_price: 5_000_000, data_limit: 32768, cu_consumed: 450, ok: true, vote: false });
        // cost and key as the scheduler computes them, as in design::DEAR_VIP
        let cost = 720 * r.sigs + 300 * r.writable + r.data_bytes / 4 + r.cu_limit + 8 * r.data_limit.div_ceil(32768);
        assert_eq!(cost, crate::design::DEAR_VIP.agave_cost());
        assert_eq!((r.fee - 2500 * r.sigs) * 1_000_000 / (cost + 1), crate::design::DEAR_VIP.agave_priority());
    }
}
