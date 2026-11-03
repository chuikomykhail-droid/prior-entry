//! Smaller commands: key generation, balances, funding and sweeping the payers,
//! probe simulation, the QUIC handshake check and the send-timing calibration.

use std::collections::HashSet;
use std::fs;
use std::net::SocketAddr;
use std::path::Path;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use anyhow::{bail, Context, Result};
use serde_json::json;

use crate::clock::sleep_until_precise;
use crate::cluster::Snapshot;
use crate::design::{cell_params, DesignFile, GridSpec, Lane, BASE_GRID_MS, CELLS, DEAR_VIP, REV_GRID_MS};
use crate::guard::SendPermit;
use crate::keys::{self, Keypair};
use crate::ledger::Ledger;
use crate::quic;
use crate::rpc::Rpc;
use crate::tx::{self, Pubkey};

pub fn keygen(dir: &Path, payers: usize) -> Result<()> {
    fs::create_dir_all(dir)?;
    let funder = dir.join("funder.json");
    if !funder.exists() {
        Keypair::generate().write_new(&funder)?;
        println!("created {}", funder.display());
    }
    for i in 0..payers {
        let p = dir.join(format!("payer-{i:02}.json"));
        if !p.exists() {
            Keypair::generate().write_new(&p)?;
        }
    }
    let f = Keypair::read(&funder)?;
    println!("funder address (send SOL here): {}", f.pubkey());
    for (i, p) in keys::load_payers(dir)?.iter().enumerate() {
        println!("payer {i:02}: {}", p.pubkey());
    }
    Ok(())
}

pub async fn balances(rpc: &Rpc, dir: &Path) -> Result<()> {
    let funder = Keypair::read(&dir.join("funder.json"))?;
    let mut total = 0;
    let b = rpc.balance(&funder.pubkey().to_string()).await?;
    total += b;
    println!("funder   {}  {:.9} SOL", funder.pubkey(), b as f64 / 1e9);
    for (i, p) in keys::load_payers(dir)?.iter().enumerate() {
        let b = rpc.balance(&p.pubkey().to_string()).await?;
        total += b;
        println!("payer {i:02} {}  {:.9} SOL", p.pubkey(), b as f64 / 1e9);
    }
    println!("total {:.9} SOL", total as f64 / 1e9);
    Ok(())
}

async fn send_and_confirm(rpc: &Rpc, txb: &tx::SignedTx) -> Result<u64> {
    let sig = rpc.send_transaction(&txb.bytes).await?;
    for _ in 0..60 {
        tokio::time::sleep(Duration::from_secs(1)).await;
        if let Some(Some(st)) = rpc.signature_statuses(std::slice::from_ref(&sig)).await?.into_iter().next() {
            if !st["err"].is_null() {
                bail!("{sig}: failed: {}", st["err"]);
            }
            if matches!(st["confirmationStatus"].as_str(), Some("confirmed" | "finalized")) {
                return Ok(st["slot"].as_u64().unwrap_or(0));
            }
        }
    }
    bail!("{sig}: not confirmed in 60 s")
}

/// Tops every payer up to `rent-exempt minimum + per_payer` lamports from the funder. Checks first
/// that the funder can cover every top-up and its fee and stay rent-exempt, so it never stops halfway
/// for lack of funds.
pub async fn fund(rpc: &Rpc, dir: &Path, ledger_path: &Path, cap: u64, per_payer: u64) -> Result<()> {
    let funder = Keypair::read(&dir.join("funder.json"))?;
    let rent = rpc.minimum_rent_exempt(0).await?;
    let payers = keys::load_payers(dir)?;
    let want = rent + per_payer;
    let mut have = Vec::with_capacity(payers.len());
    for p in &payers {
        have.push(rpc.balance(&p.pubkey().to_string()).await?);
    }
    let top_ups: Vec<u64> = have.iter().map(|h| want.saturating_sub(*h)).collect();
    let n = top_ups.iter().filter(|x| **x > 0).count() as u64;
    let need = top_ups.iter().sum::<u64>() + n * tx::BASE_FEE_PER_SIGNATURE;
    let funder_has = rpc.balance(&funder.pubkey().to_string()).await?;
    println!(
        "funder {} has {:.9} SOL; {n} top-ups to {:.9} SOL each (rent {rent} + {per_payer}) need {:.9} SOL with fees",
        funder.pubkey(),
        funder_has as f64 / 1e9,
        want as f64 / 1e9,
        need as f64 / 1e9
    );
    if n > 0 && funder_has < need + rent {
        bail!("the funder needs {:.9} SOL (top-ups, fees, its own rent-exempt minimum), has {:.9}", (need + rent) as f64 / 1e9, funder_has as f64 / 1e9);
    }
    let mut ledger = Ledger::open(ledger_path, cap)?;
    for (i, p) in payers.iter().enumerate() {
        let have = rpc.balance(&p.pubkey().to_string()).await?;
        if have >= want {
            println!("payer {i:02}: {have} lamports, ok");
            continue;
        }
        if !ledger.reserve(tx::BASE_FEE_PER_SIGNATURE, "fund", &format!("fund payer {i:02}"))? {
            bail!("spend cap reached");
        }
        let (bh, _) = rpc.latest_blockhash().await?;
        let t = tx::sign(tx::transfer_message(&funder.pubkey(), &p.pubkey(), &bh, want - have), &funder);
        let slot = send_and_confirm(rpc, &t).await?;
        println!("payer {i:02}: +{} lamports, {} (slot {slot})", want - have, t.signature_b58());
    }
    Ok(())
}

/// Returns every payer's balance to the funder (each payer pays its own transfer fee).
pub async fn sweep(rpc: &Rpc, dir: &Path, ledger_path: &Path, cap: u64) -> Result<()> {
    let funder = Keypair::read(&dir.join("funder.json"))?;
    let mut ledger = Ledger::open(ledger_path, cap)?;
    for (i, p) in keys::load_payers(dir)?.iter().enumerate() {
        let have = rpc.balance(&p.pubkey().to_string()).await?;
        if have <= tx::BASE_FEE_PER_SIGNATURE {
            continue;
        }
        if !ledger.reserve(tx::BASE_FEE_PER_SIGNATURE, "sweep", &format!("sweep payer {i:02}"))? {
            bail!("spend cap reached");
        }
        let (bh, _) = rpc.latest_blockhash().await?;
        let t = tx::sign(tx::transfer_message(&p.pubkey(), &funder.pubkey(), &bh, have - tx::BASE_FEE_PER_SIGNATURE), p);
        let slot = send_and_confirm(rpc, &t).await?;
        println!("payer {i:02}: -{} lamports, {} (slot {slot})", have - tx::BASE_FEE_PER_SIGNATURE, t.signature_b58());
    }
    Ok(())
}

/// Simulates every probe variant on mainnet without sending. The fee payer is a stand-in: a
/// funded validator identity, since signatures are not verified in simulation.
pub async fn simulate(rpc: &Rpc, out: &Path) -> Result<bool> {
    let snap = Snapshot::take(rpc).await?;
    let mut ids: Vec<_> = snap.nodes.values().filter(|n| n.stake > 0).collect();
    ids.sort_by(|a, b| b.stake.cmp(&a.stake));
    let mut stand_in = None;
    for n in ids.iter().take(20) {
        if rpc.balance(&n.identity).await.unwrap_or(0) >= 50_000_000 {
            stand_in = Some(n.identity.parse::<Pubkey>()?);
            break;
        }
    }
    let payer = stand_in.context("no funded stand-in payer found")?;
    let (bh, _) = rpc.latest_blockhash().await?;
    let mut seen = HashSet::new();
    let mut results = Vec::new();
    let mut ok = true;
    for (series, lane) in CELLS {
        let (a, b) = cell_params(*series, *lane);
        for p in [a, b] {
            if !seen.insert((p.cu_limit, p.cu_price, p.loaded_data)) {
                continue;
            }
            let msg = tx::probe_message(&payer, &Pubkey::new_unique(), &bh, &p, 0);
            let v = rpc.simulate(&tx::unsigned(&msg)).await?;
            let err = v["err"].clone();
            ok &= err.is_null();
            println!(
                "{:>13} limit {:>6} price {:>9} data {:>8}: err {}  units {}  priority {}",
                format!("{series:?}/{lane:?}"),
                p.cu_limit,
                p.cu_price,
                p.loaded_data,
                err,
                v["unitsConsumed"],
                p.agave_priority()
            );
            results.push(json!({"series": series, "lane": lane, "params": p, "fee": p.total_fee(), "agave_priority": p.agave_priority(),
                                "err": err, "unitsConsumed": v["unitsConsumed"], "logs": v["logs"]}));
        }
    }
    // A signed example with a throwaway key, for an independent check of the wire format and signature.
    let kp = Keypair::generate();
    let example = tx::sign(tx::probe_message(&kp.pubkey(), &Pubkey::new_unique(), &bh, &DEAR_VIP, 0), &kp);
    use base64::Engine;
    fs::create_dir_all(out)?;
    let path = out.join(format!("simulate-{}.json", chrono::Utc::now().format("%Y%m%dT%H%M%SZ")));
    fs::write(
        &path,
        serde_json::to_string_pretty(&json!({
            "stand_in_payer": payer.to_string(), "results": results,
            "example_signed_tx_base64": base64::engine::general_purpose::STANDARD.encode(&example.bytes),
            "example_signature": example.signature_b58(), "example_payer": kp.pubkey().to_string(),
        }))?,
    )?;
    println!("-> {}", path.display());
    Ok(ok)
}

/// QUIC handshake only, no transactions: does each target TPU accept an unstaked connection from
/// here, how long does the handshake take, and does the connection survive a few seconds?
pub async fn probe(rpc: &Rpc, families: &[String], per_family: usize, out: &Path) -> Result<()> {
    let snap = Snapshot::take(rpc).await?;
    let ep = quic::client_endpoint()?;
    let mut seen = HashSet::new();
    let mut rows = Vec::new();
    for n in snap.targets(families, per_family) {
        let Some(addr) = n.tpu_quic else { continue };
        if !seen.insert(addr) {
            continue;
        }
        let mut row = json!({"family": n.client_id, "identity": n.identity, "version": n.version, "tpu": addr.to_string(),
                             "stake_sol": n.stake as f64 / 1e9});
        match quic::connect(&ep, addr, Duration::from_secs(3)).await {
            Ok((c, dt)) => {
                row["handshake_ms"] = json!(dt.as_secs_f64() * 1e3);
                row["rtt_ms"] = json!(c.rtt().as_secs_f64() * 1e3);
                tokio::time::sleep(Duration::from_millis(2500)).await;
                row["alive_after_2_5s"] = json!(c.close_reason().is_none());
                if let Some(r) = c.close_reason() {
                    row["close_reason"] = json!(r.to_string());
                }
                c.close(0u32.into(), b"handshake probe");
            }
            Err(e) => row["error"] = json!(format!("{e:#}")),
        }
        println!(
            "{:<20} {:<46} {:<22} handshake {:>7} ms  alive {}  {}",
            n.client_id,
            n.identity,
            addr,
            row["handshake_ms"].as_f64().map(|x| format!("{x:.1}")).unwrap_or("-".into()),
            row["alive_after_2_5s"],
            row.get("error").or(row.get("close_reason")).map(|v| v.to_string()).unwrap_or_default()
        );
        rows.push(row);
    }
    ep.wait_idle().await;
    fs::create_dir_all(out)?;
    let path = out.join(format!("quic-probe-{}.json", chrono::Utc::now().format("%Y%m%dT%H%M%SZ")));
    fs::write(&path, serde_json::to_string_pretty(&rows)?)?;
    println!("-> {}", path.display());
    Ok(())
}

/// Records the RPC node's slot notifications for `seconds` and reports the slot-clock fit.
pub async fn clock(rpc: &Rpc, seconds: u64, out: &Path) -> Result<()> {
    let anchor = crate::clock::Anchor::now();
    let ntp = crate::clock::ntp_offset(crate::clock::NTP_SERVER, &anchor).await.ok();
    println!("NTP: {:?}", ntp.map(|(o, r)| format!("local clock {:+.1} ms off, rtt {:.1} ms", o * 1e3, r * 1e3)));
    let c = crate::clock::SlotClock::start(rpc.ws_url(), ntp.map(|x| x.0), anchor);
    let t0 = Instant::now();
    tokio::time::sleep(Duration::from_secs(seconds)).await;
    let raw = c.raw();
    let ms = |t: Instant| t.duration_since(t0).as_secs_f64() * 1e3;
    if let Some(i) = c.info() {
        println!(
            "fit: {:.2} ms/slot, MAD {:.1} ms, {} points, mode {}, delivery offset {:?} ms",
            i.slot_secs * 1e3,
            i.residual_ms,
            i.samples,
            i.mode,
            i.delivery_offset_ms
        );
    }
    println!(
        "notifications {}, firstShredReceived {} ({} with server timestamp), reconnects {}",
        raw.notifications.len(),
        raw.first_shreds.len(),
        raw.first_shreds.iter().filter(|x| x.2.is_some()).count(),
        c.reconnects()
    );
    let anchor = c.anchor();
    fs::create_dir_all(out)?;
    let path = out.join(format!("clock-{}.json", chrono::Utc::now().format("%Y%m%dT%H%M%SZ")));
    fs::write(
        &path,
        serde_json::to_string(&json!({
            "notifications": raw.notifications.iter().map(|(s, t)| (s, ms(*t))).collect::<Vec<_>>(),
            "first_shreds": raw.first_shreds.iter().map(|(s, t, m)| json!({"slot": s, "local_ms": ms(*t),
                "local_unix_ms": anchor.unix_secs(*t) * 1e3, "server_unix_ms": m})).collect::<Vec<_>>(),
        }))?,
    )?;
    println!("-> {}", path.display());
    Ok(())
}

/// Sends pairs to a local QUIC sink and compares the planned gap s with the gap at which the two
/// streams were written and the gap at which they arrived. Measures our own timing precision.
pub async fn calibrate(pairs: usize, out: &Path) -> Result<()> {
    let server = quic::server_endpoint("127.0.0.1:0".parse::<SocketAddr>()?)?;
    let addr = server.local_addr()?;
    let arrivals: Arc<Mutex<Vec<(u32, Instant)>>> = Arc::new(Mutex::new(Vec::new()));
    {
        let arrivals = arrivals.clone();
        tokio::spawn(async move {
            while let Some(inc) = server.accept().await {
                let arrivals = arrivals.clone();
                tokio::spawn(async move {
                    let Ok(conn) = inc.await else { return };
                    while let Ok(mut rs) = conn.accept_uni().await {
                        let t = Instant::now();
                        let arrivals = arrivals.clone();
                        tokio::spawn(async move {
                            if let Ok(buf) = rs.read_to_end(4096).await {
                                if buf.len() >= 4 {
                                    let id = u32::from_le_bytes(buf[..4].try_into().unwrap());
                                    arrivals.lock().unwrap().push((id, t));
                                }
                            }
                        });
                    }
                });
            }
        });
    }
    let ep = quic::client_endpoint()?;
    let (conn, _) = quic::connect(&ep, addr, Duration::from_secs(2)).await?;
    let permit = SendPermit::loopback();
    let mut sends = Vec::new();
    for i in 0..pairs {
        let s_ms = BASE_GRID_MS[i % BASE_GRID_MS.len()];
        let (sa, sb) = (conn.open_uni().await?, conn.open_uni().await?);
        let mut pa = vec![0u8; 250];
        let mut pb = vec![0u8; 250];
        pa[..4].copy_from_slice(&(2 * i as u32).to_le_bytes());
        pb[..4].copy_from_slice(&(2 * i as u32 + 1).to_le_bytes());
        let ta = Instant::now() + Duration::from_millis(5);
        let tb = ta + Duration::from_secs_f64(s_ms / 1e3);
        sleep_until_precise(ta).await;
        let wa = quic::write_tx(&permit, addr, sa, &pa).await?;
        sleep_until_precise(tb).await;
        let wb = quic::write_tx(&permit, addr, sb, &pb).await?;
        sends.push((i, s_ms, wa, wb));
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    tokio::time::sleep(Duration::from_millis(300)).await;
    let arr: std::collections::HashMap<u32, Instant> = arrivals.lock().unwrap().iter().copied().collect();
    let mut rows = Vec::new();
    let (mut send_err, mut arr_err) = (Vec::new(), Vec::new());
    for (i, s_ms, wa, wb) in sends {
        let send_gap = (wb - wa).as_secs_f64() * 1e3;
        let arr_gap = match (arr.get(&(2 * i as u32)), arr.get(&(2 * i as u32 + 1))) {
            (Some(a), Some(b)) => Some(if b >= a { (*b - *a).as_secs_f64() * 1e3 } else { -((*a - *b).as_secs_f64() * 1e3) }),
            _ => None,
        };
        send_err.push(send_gap - s_ms);
        if let Some(g) = arr_gap {
            arr_err.push(g - s_ms);
        }
        rows.push(json!({"pair": i, "s_ms": s_ms, "send_gap_ms": send_gap, "arrival_gap_ms": arr_gap}));
    }
    let stats = |v: &mut Vec<f64>| {
        v.sort_by(|a, b| a.partial_cmp(b).unwrap());
        let n = v.len().max(1) as f64;
        let mean = v.iter().sum::<f64>() / n;
        let sd = (v.iter().map(|x| (x - mean).powi(2)).sum::<f64>() / n).sqrt();
        let q = |p: f64| v.get(((v.len() as f64 - 1.0) * p).round() as usize).copied().unwrap_or(f64::NAN);
        json!({"n": v.len(), "mean_ms": mean, "sd_ms": sd, "p01_ms": q(0.01), "p50_ms": q(0.5), "p99_ms": q(0.99), "max_abs_ms": v.iter().map(|x| x.abs()).fold(0.0, f64::max)})
    };
    let summary = json!({"pairs": pairs, "send_gap_error": stats(&mut send_err), "arrival_gap_error": stats(&mut arr_err)});
    println!("{}", serde_json::to_string_pretty(&summary)?);
    fs::create_dir_all(out)?;
    let path = out.join(format!("calibrate-{}.json", chrono::Utc::now().format("%Y%m%dT%H%M%SZ")));
    fs::write(&path, serde_json::to_string_pretty(&json!({"summary": summary, "pairs": rows}))?)?;
    println!("-> {}", path.display());
    conn.close(0u32.into(), b"done");
    Ok(())
}

/// Applies the grid rule of the main run (§6.5) to the pilot estimates and writes the design file
/// that `run --design` reads. The file is committed before the main run (pre-registration).
pub fn freeze_grids(mu_hat: &Path, out: &Path) -> Result<()> {
    let mu: std::collections::HashMap<String, std::collections::HashMap<Lane, f64>> =
        serde_json::from_str(&fs::read_to_string(mu_hat).with_context(|| format!("{}", mu_hat.display()))?)?;
    let mut file = DesignFile { frozen_utc: Some(chrono::Utc::now().to_rfc3339()), rev_ms: Some(REV_GRID_MS.to_vec()), ..Default::default() };
    for (family, lanes) in mu {
        for (lane, m) in lanes {
            if !(m.is_finite() && m > 0.0) {
                bail!("{family}/{lane:?}: mu_hat {m} is not a positive number");
            }
            let g = GridSpec::from_mu_hat(m, lane);
            println!("{family:<20} {lane:?}  mu_hat {m:>7.1} ms  uniform {:?}  {} grid points", g.uniform_ms, g.points_ms.len());
            file.grids.entry(family.clone()).or_default().insert(lane, g);
        }
    }
    if let Some(dir) = out.parent() {
        fs::create_dir_all(dir)?;
    }
    fs::write(out, serde_json::to_string_pretty(&file)?)?;
    DesignFile::read(out)?;
    println!("-> {}", out.display());
    Ok(())
}
