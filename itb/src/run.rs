//! The measurement loop. Dry-run by default: the real leader schedule, real windows, real signed
//! transactions and real waits, but nothing is written to the network. `--live` sends.

use std::collections::{HashMap, HashSet};
use std::fs::{self, File};
use std::io::{BufWriter, Write};
use std::net::SocketAddr;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use anyhow::{bail, Context, Result};
use rand::rngs::StdRng;
use rand::SeedableRng;
use serde_json::{json, Value};

use crate::clock::{sleep_until_precise, Anchor, SlotClock};
use crate::cluster::{self, Node, Snapshot, Window};
use crate::design::{Design, PairPlan, Timing};
use crate::keys::{self, Keypair};
use crate::ledger::Ledger;
use crate::quic;
use crate::rpc::Rpc;
use crate::tx::{self, Pubkey};

pub struct RunConfig {
    pub live: bool,
    pub cap_lamports: u64,
    pub minutes: f64,
    pub families: Vec<String>,
    pub per_family: usize,
    pub out_root: PathBuf,
    pub keys_dir: PathBuf,
    pub ledger_path: PathBuf,
    pub in_offset_ms: f64,
    pub in_step_ms: f64,
    pub pre_offset_ms: f64,
    pub rpc_lag_ms: f64,
    pub pairs_per_window: usize,
    pub max_windows: Option<usize>,
    pub seed: u64,
    pub quota_scale: f64,
    pub connect: bool,
    pub grid_ms: Vec<f64>,
    pub concurrent_windows: usize,
}

struct Shared {
    run_id: String,
    mode: &'static str,
    live: bool,
    connect: bool,
    rpc: Arc<Rpc>,
    clock: SlotClock,
    anchor: Anchor,
    blockhash: std::sync::Mutex<Option<([u8; 32], Instant)>>,
    ledger: Option<std::sync::Mutex<Ledger>>,
    tx_log: std::sync::Mutex<BufWriter<File>>,
    win_log: std::sync::Mutex<BufWriter<File>>,
    endpoint: quinn::Endpoint,
    conns: tokio::sync::Mutex<HashMap<SocketAddr, quinn::Connection>>,
    payers: Vec<Arc<Keypair>>,
    pairs_per_window: usize,
    stop: AtomicBool,
    pairs_fired: AtomicUsize,
}

fn write_line(w: &std::sync::Mutex<BufWriter<File>>, v: &Value) {
    let mut w = w.lock().unwrap();
    let _ = writeln!(w, "{v}");
    let _ = w.flush();
}

pub async fn run(rpc: Arc<Rpc>, cfg: RunConfig) -> Result<()> {
    let mode = if cfg.live { "live" } else { "dry" };
    let run_id = format!("{}-{mode}", chrono::Utc::now().format("%Y%m%dT%H%M%SZ"));
    let out = cfg.out_root.join(&run_id);
    fs::create_dir_all(&out)?;
    println!("run {run_id} -> {}", out.display());

    let ledger = if cfg.live {
        let l = Ledger::open(&cfg.ledger_path, cfg.cap_lamports)?;
        println!("ledger {}: {} of {} lamports already reserved", l.path().display(), l.reserved(), l.cap());
        Some(std::sync::Mutex::new(l))
    } else {
        None
    };
    let payers: Vec<Arc<Keypair>> = if cfg.live {
        let p = keys::load_payers(&cfg.keys_dir)?;
        if p.len() < cfg.pairs_per_window * cfg.concurrent_windows {
            bail!("need {} payer keys in {}, found {}", cfg.pairs_per_window * cfg.concurrent_windows, cfg.keys_dir.display(), p.len());
        }
        p.into_iter().map(Arc::new).collect()
    } else {
        (0..cfg.pairs_per_window * cfg.concurrent_windows).map(|_| Arc::new(Keypair::generate())).collect()
    };

    let ntp = match crate::clock::ntp_offset("time.google.com:123").await {
        Ok((off, rtt)) => {
            println!("NTP: local clock is {:+.1} ms off true time (rtt {:.1} ms)", off * 1e3, rtt * 1e3);
            Some((off, rtt))
        }
        Err(e) => {
            eprintln!("NTP failed ({e:#}); slot clock falls back to the fastest WebSocket deliveries");
            None
        }
    };
    let clock = SlotClock::start(rpc.ws_url(), ntp.map(|x| x.0));
    let warm = Instant::now();
    loop {
        if clock.info().is_some_and(|i| i.samples >= 15) {
            break;
        }
        if warm.elapsed() > Duration::from_secs(40) {
            bail!("slot clock: no WebSocket slot notifications from {}", rpc.ws_url());
        }
        tokio::time::sleep(Duration::from_millis(200)).await;
    }
    let ci = clock.info().unwrap();
    println!(
        "slot clock: {:.1} ms/slot, residual {:.1} ms, {} samples, mode {}, delivery offset {:?} ms",
        ci.slot_secs * 1e3,
        ci.residual_ms,
        ci.samples,
        ci.mode,
        ci.delivery_offset_ms
    );

    let snapshot = Snapshot::take(&rpc).await?;
    let targets = snapshot.targets(&cfg.families, cfg.per_family);
    if targets.is_empty() {
        bail!("no targets for families {:?}", cfg.families);
    }
    let targets: Arc<std::sync::RwLock<HashMap<String, Node>>> =
        Arc::new(std::sync::RwLock::new(targets.into_iter().map(|n| (n.identity.clone(), n)).collect()));

    let meta = json!({
        "run_id": run_id, "mode": mode, "started_utc": chrono::Utc::now().to_rfc3339(), "rpc": rpc.url,
        "seed": cfg.seed, "families": cfg.families, "per_family": cfg.per_family, "minutes": cfg.minutes,
        "cap_lamports": cfg.cap_lamports, "pairs_per_window": cfg.pairs_per_window,
        "timing": {"in_offset_ms": cfg.in_offset_ms, "in_step_ms": cfg.in_step_ms, "pre_offset_ms": cfg.pre_offset_ms, "rpc_lag_ms": cfg.rpc_lag_ms},
        "grid_ms": cfg.grid_ms, "quota_scale": cfg.quota_scale,
        "payers": payers.iter().map(|p| p.pubkey().to_string()).collect::<Vec<_>>(),
        "targets": targets.read().unwrap().values().collect::<Vec<_>>(),
        "gossip_snapshot_utc": snapshot.taken_at.to_rfc3339(),
        "ntp_offset_ms": ntp.map(|x| x.0 * 1e3), "ntp_rtt_ms": ntp.map(|x| x.1 * 1e3),
        "clock_at_start": {"slot_ms": ci.slot_secs * 1e3, "residual_ms": ci.residual_ms, "mode": ci.mode,
                           "delivery_offset_ms": ci.delivery_offset_ms},
        "itb_version": env!("CARGO_PKG_VERSION"),
    });
    fs::write(out.join("meta.json"), serde_json::to_string_pretty(&meta)?)?;

    let shared = Arc::new(Shared {
        run_id: run_id.clone(),
        mode,
        live: cfg.live,
        connect: cfg.live || cfg.connect,
        rpc: rpc.clone(),
        clock: clock.clone(),
        anchor: Anchor::now(),
        blockhash: std::sync::Mutex::new(None),
        ledger,
        tx_log: std::sync::Mutex::new(BufWriter::new(File::create(out.join("txs.jsonl"))?)),
        win_log: std::sync::Mutex::new(BufWriter::new(File::create(out.join("windows.jsonl"))?)),
        endpoint: quic::client_endpoint()?,
        conns: tokio::sync::Mutex::new(HashMap::new()),
        payers,
        pairs_per_window: cfg.pairs_per_window,
        stop: AtomicBool::new(false),
        pairs_fired: AtomicUsize::new(0),
    });

    // Background refreshers: blockhash every 5 s, gossip every 60 s.
    {
        let s = shared.clone();
        tokio::spawn(async move {
            loop {
                match s.rpc.latest_blockhash().await {
                    Ok((h, _)) => *s.blockhash.lock().unwrap() = Some((h, Instant::now())),
                    Err(e) => eprintln!("blockhash: {e:#}"),
                }
                tokio::time::sleep(Duration::from_secs(5)).await;
            }
        });
    }
    {
        let s = shared.clone();
        let t = targets.clone();
        let fams = cfg.families.clone();
        let per = cfg.per_family;
        let snap_log = out.join("gossip.jsonl");
        tokio::spawn(async move {
            let mut f = BufWriter::new(File::create(snap_log).expect("gossip log"));
            loop {
                tokio::time::sleep(Duration::from_secs(60)).await;
                match Snapshot::take(&s.rpc).await {
                    Ok(snap) => {
                        // keep the target list, refresh client id / version / TPU of each target
                        let mut tg = t.write().unwrap();
                        for (id, node) in tg.iter_mut() {
                            if let Some(n) = snap.nodes.get(id) {
                                *node = n.clone();
                            }
                        }
                        let _ = writeln!(f, "{}", json!({"utc": snap.taken_at.to_rfc3339(), "targets": tg.values().collect::<Vec<_>>()}));
                        let _ = f.flush();
                        let _ = (&fams, per);
                    }
                    Err(e) => eprintln!("gossip: {e:#}"),
                }
            }
        });
    }
    // Raw slot timing for the analysis: when the RPC node got the first shred of every slot
    // (its own clock) and when we heard about it (our clock, NTP offset in meta.json).
    {
        let c = clock.clone();
        let path = out.join("slots.jsonl");
        tokio::spawn(async move {
            let mut f = BufWriter::new(File::create(path).expect("slots log"));
            let mut last = 0u64;
            loop {
                tokio::time::sleep(Duration::from_secs(2)).await;
                let a = c.anchor();
                for (slot, t, server_ms) in c.first_shreds_after(last) {
                    last = last.max(slot);
                    let _ = writeln!(f, "{}", json!({"slot": slot, "server_unix_ms": server_ms, "local_unix_ms": a.unix_secs(t) * 1e3}));
                }
                let _ = f.flush();
            }
        });
    }
    while shared.blockhash.lock().unwrap().is_none() {
        tokio::time::sleep(Duration::from_millis(100)).await;
    }

    let mut design = Design::new(
        cfg.grid_ms.clone(),
        cfg.quota_scale,
        Timing { in_offset_ms: cfg.in_offset_ms, in_step_ms: cfg.in_step_ms, pre_offset_ms: cfg.pre_offset_ms },
        cfg.pairs_per_window,
    );
    let mut rng = StdRng::seed_from_u64(cfg.seed);
    let deadline = Instant::now() + Duration::from_secs_f64(cfg.minutes * 60.0);
    let permits = Arc::new(tokio::sync::Semaphore::new(cfg.concurrent_windows));
    let groups = Arc::new(std::sync::Mutex::new((0..cfg.concurrent_windows).collect::<Vec<usize>>()));
    let mut handled: HashSet<u64> = HashSet::new();
    let mut schedule: Vec<Window> = Vec::new();
    let mut schedule_at = Instant::now() - Duration::from_secs(3600);
    let mut started = 0usize;
    let lag = Duration::from_secs_f64(cfg.rpc_lag_ms / 1e3);

    while Instant::now() < deadline && !shared.stop.load(Ordering::Relaxed) && cfg.max_windows.is_none_or(|m| started < m) {
        if schedule_at.elapsed() > Duration::from_secs(15) {
            let from = clock.info().map(|i| i.latest_slot).unwrap_or(0);
            match cluster::windows(&rpc, from, 1200).await {
                Ok(w) => {
                    schedule = w;
                    schedule_at = Instant::now();
                }
                Err(e) => eprintln!("schedule: {e:#}"),
            }
        }
        let now = Instant::now();
        let mut chosen = None;
        {
            let tg = targets.read().unwrap();
            for w in &schedule {
                if handled.contains(&w.first_slot) || w.slots < 2 {
                    continue;
                }
                let Some(node) = tg.get(&w.leader) else { continue };
                if node.tpu_quic.is_none() || design.family_done(&node.client_id) {
                    continue;
                }
                let Some(pred) = clock.predict(w.first_slot) else { continue };
                let Some(t0) = pred.checked_sub(lag) else { continue };
                let lead = t0.saturating_duration_since(now);
                if t0 <= now || lead < Duration::from_millis(1600) {
                    continue;
                }
                if lead > Duration::from_secs(20) {
                    break;
                }
                chosen = Some((w.clone(), node.clone(), t0));
                break;
            }
        }
        let Some((w, node, t0)) = chosen else {
            tokio::time::sleep(Duration::from_millis(50)).await;
            continue;
        };
        let Ok(permit) = permits.clone().try_acquire_owned() else {
            tokio::time::sleep(Duration::from_millis(20)).await;
            continue;
        };
        let Some(plan) = design.plan_window(&node.client_id, &mut rng) else {
            handled.insert(w.first_slot);
            continue;
        };
        handled.insert(w.first_slot);
        started += 1;
        let group = groups.lock().unwrap().pop().expect("a free payer group per permit");
        let s = shared.clone();
        let g = groups.clone();
        tokio::spawn(async move {
            if let Err(e) = handle_window(&s, &w, &node, t0, &plan, group).await {
                eprintln!("window {}: {e:#}", w.first_slot);
            }
            g.lock().unwrap().push(group);
            drop(permit);
        });
    }

    // let running windows finish
    let _all = permits.acquire_many(cfg.concurrent_windows as u32).await?;
    let summary = json!({
        "run_id": run_id, "ended_utc": chrono::Utc::now().to_rfc3339(), "windows": started,
        "pairs_fired": shared.pairs_fired.load(Ordering::Relaxed),
        "stopped_by_cap": shared.stop.load(Ordering::Relaxed),
        "planned": design.planned.iter().map(|((f, a), n)| json!({"family": f, "arm": a, "pairs": n})).collect::<Vec<_>>(),
        "clock_reconnects": clock.reconnects(),
        "ledger_reserved_total": shared.ledger.as_ref().map(|l| l.lock().unwrap().reserved()),
    });
    fs::write(out.join("summary.json"), serde_json::to_string_pretty(&summary)?)?;
    println!("{}", serde_json::to_string_pretty(&summary)?);
    Ok(())
}

async fn connection(s: &Shared, addr: SocketAddr) -> Result<(quinn::Connection, Option<f64>)> {
    let mut conns = s.conns.lock().await;
    if let Some(c) = conns.get(&addr) {
        if c.close_reason().is_none() {
            return Ok((c.clone(), None));
        }
    }
    let (c, dt) = quic::connect(&s.endpoint, addr, Duration::from_millis(1500)).await?;
    conns.insert(addr, c.clone());
    Ok((c, Some(dt.as_secs_f64() * 1e3)))
}

async fn handle_window(s: &Arc<Shared>, w: &Window, node: &Node, t0: Instant, plan: &[PairPlan], group: usize) -> Result<()> {
    let tpu = node.tpu_quic.context("no TPU")?;
    let mut win = json!({
        "run_id": s.run_id, "mode": s.mode, "window_id": w.first_slot, "leader": w.leader, "family": node.client_id,
        "version": node.version, "tpu": tpu.to_string(), "stake": node.stake, "first_slot": w.first_slot, "window_slots": w.slots,
        "predicted_start_utc": s.anchor.utc(t0).to_rfc3339(), "predicted_start_us": s.anchor.us(t0), "pairs": plan.len(),
    });
    if let Some(ci) = s.clock.info() {
        win["clock"] = json!({"slot_ms": ci.slot_secs * 1e3, "residual_ms": ci.residual_ms, "samples": ci.samples,
                              "age_ms": ci.age_ms, "mode": ci.mode, "delivery_offset_ms": ci.delivery_offset_ms});
    }

    // Some ingress nodes (BAM) drop idle unstaked connections within seconds, so connect late:
    // ~700 ms before the first fire, which leaves room for a slow handshake.
    let first_fire = plan
        .iter()
        .map(|p| offset(offset(t0, p.a_offset_ms), p.s_ms.min(0.0)))
        .min()
        .unwrap_or(t0);
    if let Some(t) = first_fire.checked_sub(Duration::from_millis(700)) {
        tokio::time::sleep_until(t.into()).await;
    }
    let conn = if s.connect {
        match connection(s, tpu).await {
            Ok((c, dt)) => {
                win["connect_ms"] = json!(dt);
                Some(c)
            }
            Err(e) => {
                win["connect_error"] = json!(format!("{e:#}"));
                None
            }
        }
    } else {
        None
    };
    if s.live && conn.is_none() {
        win["skipped"] = json!("no connection");
        write_line(&s.win_log, &win);
        return Ok(());
    }

    let (blockhash, bh_at) = s.blockhash.lock().unwrap().context("no blockhash")?;
    win["blockhash_age_ms"] = json!(bh_at.elapsed().as_secs_f64() * 1e3);
    if bh_at.elapsed() > Duration::from_secs(20) {
        win["skipped"] = json!("stale blockhash");
        write_line(&s.win_log, &win);
        return Ok(());
    }

    let mut tasks = Vec::new();
    for (j, p) in plan.iter().enumerate() {
        let payer = s.payers[group * s.pairs_per_window + j].clone();
        let (dest_a, dest_b) = (Pubkey::new_unique(), Pubkey::new_unique());
        let txa = tx::sign(tx::probe_message(&payer.pubkey(), &dest_a, &blockhash, &p.a, 0), &payer);
        let txb = tx::sign(tx::probe_message(&payer.pubkey(), &dest_b, &blockhash, &p.b, 0), &payer);
        let ta = offset(t0, p.a_offset_ms);
        let tb = offset(ta, p.s_ms);
        let s = s.clone();
        let conn = conn.clone();
        let p = p.clone();
        let base = json!({
            "run_id": s.run_id, "mode": s.mode, "window_id": w.first_slot, "pair_id": format!("{}-{j}", w.first_slot),
            "arm": p.arm, "a_offset_ms": p.a_offset_ms, "s_ms": p.s_ms, "payer": payer.pubkey().to_string(),
            "leader": w.leader, "family": node.client_id, "version": node.version, "tpu": tpu.to_string(),
            "first_slot": w.first_slot, "window_slots": w.slots,
        });
        tasks.push(tokio::spawn(async move { fire_pair(&s, conn, base, (txa, dest_a, p.a, ta), (txb, dest_b, p.b, tb), p.max_fee()).await }));
    }
    let mut first_fire_slot = None;
    for t in tasks {
        if let Ok(Some(slot_est)) = t.await {
            first_fire_slot.get_or_insert(slot_est);
        }
    }
    if let Some(x) = first_fire_slot {
        win["slot_est_at_first_fire"] = json!(x);
        win["slot_est_minus_first_slot"] = json!(x - w.first_slot as f64);
    }
    write_line(&s.win_log, &win);
    Ok(())
}

fn offset(t: Instant, ms: f64) -> Instant {
    if ms >= 0.0 {
        t + Duration::from_secs_f64(ms / 1e3)
    } else {
        t - Duration::from_secs_f64(-ms / 1e3)
    }
}

type Probe = (tx::SignedTx, Pubkey, tx::ProbeParams, Instant);

/// Fires one pair; returns the slot clock's estimate at the first fire (for the window record).
async fn fire_pair(s: &Shared, conn: Option<quinn::Connection>, base: Value, a: Probe, b: Probe, max_fee: u64) -> Option<f64> {
    let (first_role, second_role, first, second) = if b.3 < a.3 { ("B", "A", b, a) } else { ("A", "B", a, b) };
    let mut error: Option<String> = None;

    // Late guard: never fire a pair that would go out well after its planned moment.
    if Instant::now() > first.3 + Duration::from_millis(50) {
        error = Some("late: skipped".into());
    }
    if error.is_none() {
        if let Some(l) = &s.ledger {
            match l.lock().unwrap().reserve(max_fee, &s.run_id, base["pair_id"].as_str().unwrap_or("")) {
                Ok(true) => {}
                Ok(false) => {
                    s.stop.store(true, Ordering::Relaxed);
                    error = Some("spend cap reached: skipped".into());
                }
                Err(e) => error = Some(format!("ledger: {e:#}")),
            }
        }
    }
    // Open both streams before the first fire moment so the gap is only the write.
    let mut streams = None;
    let mut conn = conn;
    if error.is_none() && s.live && conn.as_ref().is_some_and(|c| c.close_reason().is_some()) {
        // dropped since the window connected: one quick reconnect
        conn = match connection(s, conn.as_ref().unwrap().remote_address()).await {
            Ok((c, _)) => Some(c),
            Err(e) => {
                error = Some(format!("reconnect: {e:#}"));
                None
            }
        };
    }
    if error.is_none() && s.live {
        if let Some(c) = &conn {
            let open = async { Ok::<_, anyhow::Error>((c.open_uni().await?, c.open_uni().await?)) };
            match tokio::time::timeout(Duration::from_millis(400), open).await {
                Ok(Ok(st)) => streams = Some(st),
                Ok(Err(e)) => error = Some(format!("open stream: {e:#}")),
                Err(_) => error = Some("open stream: timeout".into()),
            }
        }
    }

    let mut actual = [None, None];
    let mut sent = [false, false];
    let mut write_err: [Option<String>; 2] = [None, None];
    let mut slot_est = None;
    if error.is_none() {
        let (sa, sb) = match streams {
            Some((x, y)) => (Some(x), Some(y)),
            None => (None, None),
        };
        for (k, (stream, probe)) in [(sa, &first), (sb, &second)].into_iter().enumerate() {
            sleep_until_precise(probe.3).await;
            if k == 0 {
                slot_est = s.clock.current_slot_f64();
            }
            actual[k] = Some(match stream {
                Some(st) => match quic::write_tx(st, &probe.0.bytes).await {
                    Ok(t) => {
                        sent[k] = true;
                        t
                    }
                    Err(e) => {
                        write_err[k] = Some(format!("write: {e:#}"));
                        Instant::now()
                    }
                },
                None => Instant::now(),
            });
        }
        s.pairs_fired.fetch_add(1, Ordering::Relaxed);
    }

    for (k, (role, pr)) in [(first_role, &first), (second_role, &second)].into_iter().enumerate() {
        let mut v = base.clone();
        let (txd, dest, params, planned) = pr;
        v["role"] = json!(role);
        v["send_rank"] = json!(k);
        v["signature"] = json!(txd.signature_b58());
        v["dest"] = json!(dest.to_string());
        v["cu_limit"] = json!(params.cu_limit);
        v["cu_price"] = json!(params.cu_price);
        v["loaded_data"] = json!(params.loaded_data);
        v["priority_fee"] = json!(params.priority_fee());
        v["total_fee"] = json!(params.total_fee());
        v["agave_priority"] = json!(params.agave_priority());
        v["planned_us"] = json!(s.anchor.us(*planned));
        v["planned_utc"] = json!(s.anchor.utc(*planned).to_rfc3339());
        if let Some(t) = actual[k] {
            v["actual_us"] = json!(s.anchor.us(t));
            v["actual_utc"] = json!(s.anchor.utc(t).to_rfc3339());
            v["late_us"] = json!(s.anchor.us(t) - s.anchor.us(*planned));
        }
        v["sent"] = json!(sent[k]);
        v["error"] = json!(error.clone().or_else(|| write_err[k].clone()));
        write_line(&s.tx_log, &v);
    }
    slot_est
}
