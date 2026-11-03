//! The measurement loop. Dry-run by default: the real leader schedule, real windows, real signed
//! transactions and real waits, but nothing is written to the network. `--live` sends, and only
//! through a `SendPermit` (see `guard`).

use std::collections::{HashMap, HashSet};
use std::fs::{self, File};
use std::io::{BufWriter, Write};
use std::net::SocketAddr;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use anyhow::{bail, Context, Result};
use chrono::{DateTime, Utc};
use rand::rngs::StdRng;
use rand::seq::SliceRandom;
use rand::SeedableRng;
use serde_json::{json, Value};

use crate::clock::{sleep_until_precise, Anchor, SlotClock};
use crate::cluster::{self, Node, Snapshot, Window};
use crate::design::{self, Design, DesignFile, FamilyClass, Lane, PairPlan, Series, Timing, PAYERS_PER_WINDOW};
use crate::guard::{self, SendPermit};
use crate::keys::{self, Keypair};
use crate::ledger::Ledger;
use crate::quic;
use crate::rpc::Rpc;
use crate::tx::{self, Pubkey};

#[derive(Clone, Copy, Debug, PartialEq, Eq, clap::ValueEnum)]
pub enum AnchorMode {
    /// in-window pairs fire relative to the slot clock's prediction of the window start
    Predicted,
    /// relative to the first-shred event of the window's first slot; no event in time, no pairs
    Event,
}

impl AnchorMode {
    fn name(self) -> &'static str {
        match self {
            AnchorMode::Predicted => "predicted",
            AnchorMode::Event => "event",
        }
    }
}

pub struct RunConfig {
    pub live: bool,
    pub cap_lamports: u64,
    pub not_after: Option<DateTime<Utc>>,
    pub minutes: f64,
    pub families: Vec<String>,
    pub per_family: usize,
    /// explicit target identities; overrides `families` and `per_family`
    pub validators: Option<Vec<String>>,
    pub session: Option<String>,
    pub out_root: PathBuf,
    pub keys_dir: PathBuf,
    pub ledger_path: PathBuf,
    pub start_lo_ms: f64,
    pub start_hi_ms: f64,
    pub ctrl_offset_ms: f64,
    pub rpc_lag_ms: f64,
    pub anchor: AnchorMode,
    pub event_wait_ms: f64,
    pub max_windows: Option<usize>,
    pub seed: u64,
    pub quota_scale: f64,
    pub connect: bool,
    pub design_file: Option<PathBuf>,
    pub grid_ms: Option<Vec<f64>>,
    pub rev_grid_ms: Option<Vec<f64>>,
    pub concurrent_windows: usize,
}

/// A planned pair that never left goes back to the quota through this channel.
type Released = (String, Series, Lane);

/// How long before the predicted window start the start is predicted again (before the C2 pairs at
/// −300 ms and the connection ~700 ms before the first fire).
const ANCHOR_REFRESH_LEAD: Duration = Duration::from_millis(1200);
/// A window is skipped when the newest slot timestamp reached us longer ago than this (WebSocket
/// down: the anchor would be extrapolated blind). Healthy streams: at most 1.8 s in 378 windows.
const MAX_CLOCK_AGE_MS: f64 = 3000.0;
/// Payers must hold this multiple of their even share of the run's worst case above rent
/// (pairs go to random payers of a group, so some carry more than the average).
const PAYER_MARGIN: f64 = 1.5;

struct Shared {
    run_id: String,
    mode: &'static str,
    live: bool,
    connect: bool,
    permit: Option<SendPermit>,
    not_after: Option<DateTime<Utc>>,
    rpc: Arc<Rpc>,
    clock: SlotClock,
    anchor: Anchor,
    anchor_mode: AnchorMode,
    rpc_lag: Duration,
    event_wait: Duration,
    blockhash: std::sync::Mutex<Option<([u8; 32], Instant)>>,
    ledger: Option<std::sync::Mutex<Ledger>>,
    tx_log: std::sync::Mutex<BufWriter<File>>,
    win_log: std::sync::Mutex<BufWriter<File>>,
    endpoint: quinn::Endpoint,
    conns: tokio::sync::Mutex<HashMap<SocketAddr, quinn::Connection>>,
    payers: Vec<Arc<Keypair>>,
    released: tokio::sync::mpsc::UnboundedSender<Released>,
    stop: AtomicBool,
    pairs_fired: AtomicUsize,
    pairs_released: AtomicUsize,
}

impl Shared {
    fn past_deadline(&self) -> bool {
        self.not_after.is_some_and(|na| Utc::now() > na)
    }
}

fn write_line(w: &std::sync::Mutex<BufWriter<File>>, v: &Value) {
    let mut w = w.lock().unwrap();
    let _ = writeln!(w, "{v}");
    let _ = w.flush();
}

pub async fn run(rpc: Arc<Rpc>, cfg: RunConfig) -> Result<()> {
    let mode = if cfg.live { "live" } else { "dry" };
    let network = guard::network_check(&rpc).await?;
    println!("network: {network}");
    // the permit is issued before anything else happens, or the live run stops here
    let permit = if cfg.live { Some(SendPermit::for_mainnet(true, cfg.cap_lamports, cfg.not_after, &network)?) } else { None };
    if cfg.not_after.is_some_and(|na| na <= Utc::now()) {
        bail!("--not-after is in the past");
    }

    let design_file = match &cfg.design_file {
        Some(p) => DesignFile::read(p)?,
        None => DesignFile::default(),
    };
    let design_json = serde_json::to_value(&design_file)?;

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
    let need_payers = PAYERS_PER_WINDOW * cfg.concurrent_windows;
    let payers: Vec<Arc<Keypair>> = if cfg.live {
        let p = keys::load_payers(&cfg.keys_dir)?;
        if p.len() < need_payers {
            bail!("need {need_payers} payer keys in {}, found {}", cfg.keys_dir.display(), p.len());
        }
        p.into_iter().map(Arc::new).collect()
    } else {
        (0..need_payers).map(|_| Arc::new(Keypair::generate())).collect()
    };

    // one map from the monotonic clock to UTC for the whole run: the slot clock, the journals and NTP
    let anchor = Anchor::now();
    let ntp = match crate::clock::ntp_offset(crate::clock::NTP_SERVER, &anchor).await {
        Ok((off, rtt)) => {
            println!("NTP: local clock is {:+.1} ms off true time (rtt {:.1} ms)", off * 1e3, rtt * 1e3);
            Some((off, rtt))
        }
        Err(e) => {
            eprintln!("NTP failed ({e:#}); slot clock falls back to the fastest WebSocket deliveries");
            None
        }
    };
    let ntp_at_ms = anchor.unix_secs(Instant::now()) * 1e3;
    let clock = SlotClock::start(rpc.ws_url(), ntp.map(|x| x.0), anchor);
    let warm = Instant::now();
    // wait for the fit on the node's own timestamps; the arrival fit is a fallback only
    loop {
        match clock.info() {
            Some(i) if i.samples >= 15 && (i.mode != "arrival" || warm.elapsed() > Duration::from_secs(40)) => break,
            _ if warm.elapsed() > Duration::from_secs(40) => bail!("slot clock: no WebSocket slot notifications from {}", rpc.ws_url()),
            _ => tokio::time::sleep(Duration::from_millis(200)).await,
        }
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
    let targets = match &cfg.validators {
        Some(ids) => snapshot.named(ids)?,
        None => snapshot.targets(&cfg.families, cfg.per_family),
    };
    if targets.is_empty() {
        bail!("no targets for families {:?}", cfg.families);
    }
    let mut families: Vec<String> = Vec::new();
    for n in &targets {
        if !families.contains(&n.client_id) {
            families.push(n.client_id.clone());
        }
    }
    for n in &targets {
        println!("target {:<20} {} {} stake {:.0} SOL", n.client_id, n.identity, n.tpu_quic.map(|a| a.to_string()).unwrap_or_default(), n.stake as f64 / 1e9);
    }
    let targets: Arc<std::sync::RwLock<HashMap<String, Node>>> =
        Arc::new(std::sync::RwLock::new(targets.into_iter().map(|n| (n.identity.clone(), n)).collect()));

    let lanes: Vec<Value> = design::CELLS
        .iter()
        .map(|(s, l)| {
            let (a, b) = design::cell_params(*s, *l);
            json!({"series": s, "lane": l, "a": a, "b": b, "a_priority": a.agave_priority(), "b_priority": b.agave_priority(),
                   "a_cost": a.agave_cost(), "b_cost": b.agave_cost(), "pair_lamports": a.total_fee() + b.total_fee(),
                   "quota_main": FamilyClass::Main.quota(*s, *l), "quota_small": FamilyClass::Small.quota(*s, *l)})
        })
        .collect();
    let meta = json!({
        "run_id": run_id, "mode": mode, "started_utc": chrono::Utc::now().to_rfc3339(), "rpc": rpc.url,
        "network": network, "not_after_utc": cfg.not_after.map(|t| t.to_rfc3339()),
        "session": cfg.session, "seed": cfg.seed, "families": families, "per_family": cfg.per_family,
        "validators": cfg.validators, "minutes": cfg.minutes,
        "cap_lamports": cfg.cap_lamports, "concurrent_windows": cfg.concurrent_windows,
        "pairs_per_window": {"main": FamilyClass::Main.pairs_per_window(), "small": FamilyClass::Small.pairs_per_window()},
        "timing": {"start_lo_ms": cfg.start_lo_ms, "start_hi_ms": cfg.start_hi_ms, "ctrl_offset_ms": cfg.ctrl_offset_ms,
                   "rpc_lag_ms": cfg.rpc_lag_ms, "anchor": cfg.anchor.name(), "event_wait_ms": cfg.event_wait_ms},
        "cells": lanes, "design_file": cfg.design_file.as_ref().map(|p| p.display().to_string()), "design": design_json,
        "grid_override_ms": cfg.grid_ms, "rev_grid_ms": cfg.rev_grid_ms, "quota_scale": cfg.quota_scale,
        "payers": payers.iter().map(|p| p.pubkey().to_string()).collect::<Vec<_>>(),
        "targets": targets.read().unwrap().values().collect::<Vec<_>>(),
        "gossip_snapshot_utc": snapshot.taken_at.to_rfc3339(),
        "ntp_offset_ms": ntp.map(|x| x.0 * 1e3), "ntp_rtt_ms": ntp.map(|x| x.1 * 1e3),
        "clock_at_start": {"slot_ms": ci.slot_secs * 1e3, "residual_ms": ci.residual_ms, "mode": ci.mode,
                           "delivery_offset_ms": ci.delivery_offset_ms},
        "itb_version": env!("CARGO_PKG_VERSION"),
    });
    fs::write(out.join("meta.json"), serde_json::to_string_pretty(&meta)?)?;

    let (released_tx, mut released_rx) = tokio::sync::mpsc::unbounded_channel::<Released>();
    let shared = Arc::new(Shared {
        run_id: run_id.clone(),
        mode,
        live: cfg.live,
        connect: cfg.live || cfg.connect,
        permit,
        not_after: cfg.not_after,
        rpc: rpc.clone(),
        clock: clock.clone(),
        anchor,
        anchor_mode: cfg.anchor,
        rpc_lag: Duration::from_secs_f64(cfg.rpc_lag_ms / 1e3),
        event_wait: Duration::from_secs_f64(cfg.event_wait_ms / 1e3),
        blockhash: std::sync::Mutex::new(None),
        ledger,
        tx_log: std::sync::Mutex::new(BufWriter::new(File::create(out.join("txs.jsonl"))?)),
        win_log: std::sync::Mutex::new(BufWriter::new(File::create(out.join("windows.jsonl"))?)),
        endpoint: quic::client_endpoint()?,
        conns: tokio::sync::Mutex::new(HashMap::new()),
        payers,
        released: released_tx,
        stop: AtomicBool::new(false),
        pairs_fired: AtomicUsize::new(0),
        pairs_released: AtomicUsize::new(0),
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
                    }
                    Err(e) => eprintln!("gossip: {e:#}"),
                }
            }
        });
    }
    // NTP again every 30 s, against the run's anchor: the monotonic clock drifts (+52 ppm on the
    // measurement PC, ~0.2 s an hour), and both the slot clock and the analysis place the node's
    // timestamps on our clock with this offset.
    {
        let c = clock.clone();
        let path = out.join("ntp.jsonl");
        let first = ntp;
        tokio::spawn(async move {
            let mut f = BufWriter::new(File::create(path).expect("ntp log"));
            // `local_ms`: our clock when the measurement ended
            let mut log = |local_ms: f64, r: Result<(f64, f64)>| {
                let line = match r {
                    Ok((off, rtt)) => json!({"local_unix_ms": local_ms, "offset_ms": off * 1e3, "rtt_ms": rtt * 1e3}),
                    Err(e) => json!({"local_unix_ms": local_ms, "error": format!("{e:#}")}),
                };
                let _ = writeln!(f, "{line}");
                let _ = f.flush();
            };
            if let Some(x) = first {
                log(ntp_at_ms, Ok(x));
            }
            loop {
                tokio::time::sleep(Duration::from_secs(30)).await;
                let r = crate::clock::ntp_offset(crate::clock::NTP_SERVER, &anchor).await;
                if let Ok((off, _)) = r {
                    c.set_ntp_offset(off);
                }
                log(anchor.unix_secs(Instant::now()) * 1e3, r);
            }
        });
    }
    // Raw slot timing for the analysis: when the RPC node got the first shred of every slot
    // (its own clock) and when we heard about it (our clock; NTP offsets in ntp.jsonl).
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
        design_file,
        cfg.grid_ms.clone(),
        cfg.rev_grid_ms.clone(),
        cfg.quota_scale,
        Timing { start_lo_ms: cfg.start_lo_ms, start_hi_ms: cfg.start_hi_ms, ctrl_offset_ms: cfg.ctrl_offset_ms },
    );
    if cfg.live {
        check_payer_balances(&rpc, &shared.payers[..need_payers], &design, &families).await?;
    }
    let mut rng = StdRng::seed_from_u64(cfg.seed);
    let deadline = Instant::now() + Duration::from_secs_f64(cfg.minutes * 60.0);
    let permits = Arc::new(tokio::sync::Semaphore::new(cfg.concurrent_windows));
    // payer groups in rotation, so that spending spreads over all payers even when windows rarely overlap
    let groups = Arc::new(std::sync::Mutex::new((0..cfg.concurrent_windows).collect::<std::collections::VecDeque<usize>>()));
    let mut handled: HashSet<u64> = HashSet::new();
    let mut schedule: Vec<Window> = Vec::new();
    let mut schedule_at = Instant::now() - Duration::from_secs(3600);
    let mut started = 0usize;

    while Instant::now() < deadline
        && !shared.stop.load(Ordering::Relaxed)
        && !shared.past_deadline()
        && cfg.max_windows.is_none_or(|m| started < m)
    {
        while let Ok((f, s, l)) = released_rx.try_recv() {
            design.release(&f, s, l);
        }
        // every quota planned and nothing in flight (so nothing can come back): done
        if permits.available_permits() == cfg.concurrent_windows && families.iter().all(|f| design.family_done(f)) {
            while let Ok((f, s, l)) = released_rx.try_recv() {
                design.release(&f, s, l);
            }
            if families.iter().all(|f| design.family_done(f)) {
                println!("every quota is planned and fired");
                break;
            }
        }
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
                let Some(t0) = pred.checked_sub(shared.rpc_lag) else { continue };
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
        // payers are assigned to pairs at random, so an account rule cannot pose as a price rule
        let group = groups.lock().unwrap().pop_front().expect("a free payer group per permit");
        let mut slots: Vec<usize> = (0..PAYERS_PER_WINDOW).map(|j| group * PAYERS_PER_WINDOW + j).collect();
        slots.shuffle(&mut rng);
        let s = shared.clone();
        let g = groups.clone();
        tokio::spawn(async move {
            if let Err(e) = handle_window(&s, &w, &node, t0, &plan, &slots).await {
                eprintln!("window {}: {e:#}", w.first_slot);
            }
            g.lock().unwrap().push_back(group);
            drop(permit);
        });
    }

    // let running windows finish, then give the slot log time to record their slots: first-shred
    // notifications reach us 1-8 s late, and without them the analysis cannot place the last windows
    let _all = permits.acquire_many(cfg.concurrent_windows as u32).await?;
    tokio::time::sleep(Duration::from_secs(10)).await;
    while let Ok((f, s, l)) = released_rx.try_recv() {
        design.release(&f, s, l);
    }
    let mut planned: Vec<Value> = design
        .planned
        .iter()
        .map(|((f, s, l), n)| json!({"family": f, "series": s, "lane": l, "pairs": n, "quota": design.quota(f, *s, *l)}))
        .collect();
    planned.sort_by_key(|v| v.to_string());
    let summary = json!({
        "run_id": run_id, "ended_utc": chrono::Utc::now().to_rfc3339(), "windows": started,
        "pairs_fired": shared.pairs_fired.load(Ordering::Relaxed),
        "pairs_released": shared.pairs_released.load(Ordering::Relaxed),
        "stopped_by_cap": shared.stop.load(Ordering::Relaxed),
        "stopped_by_not_after": shared.past_deadline(),
        "planned": planned,
        "clock_reconnects": clock.reconnects(),
        "ledger_reserved_total": shared.ledger.as_ref().map(|l| l.lock().unwrap().reserved()),
    });
    fs::write(out.join("summary.json"), serde_json::to_string_pretty(&summary)?)?;
    println!("{}", serde_json::to_string_pretty(&summary)?);
    Ok(())
}

/// Refuses a live run whose payers could run dry: each must hold `PAYER_MARGIN` times its even
/// share of the run's worst case (every quota fired, both probes landing) above rent. A payer that
/// cannot pay the fee and stay rent-exempt is refused by the leader, and its probes silently never land.
async fn check_payer_balances(rpc: &Rpc, payers: &[Arc<Keypair>], design: &Design, families: &[String]) -> Result<()> {
    let worst = worst_case_lamports(design, families);
    let share = (worst as f64 * PAYER_MARGIN / payers.len() as f64).ceil() as u64;
    let rent = rpc.minimum_rent_exempt(0).await?;
    let mut low = Vec::new();
    let mut poorest = u64::MAX;
    for p in payers {
        let key = p.pubkey().to_string();
        let free = rpc.balance(&key).await?.saturating_sub(rent);
        poorest = poorest.min(free);
        if free < share {
            low.push(format!("{key} ({free})"));
        }
    }
    println!("payers: this run's worst case is {worst} lamports; each payer needs {share} above rent, the poorest has {poorest}");
    if !low.is_empty() {
        bail!("payers with less than {share} lamports above rent: {}; top them up with `itb fund` first", low.join(", "));
    }
    Ok(())
}

/// Fees if every quota of the run is fired and both probes of every pair land.
fn worst_case_lamports(design: &Design, families: &[String]) -> u64 {
    families
        .iter()
        .flat_map(|f| design::CELLS.iter().map(move |(s, l)| (f, *s, *l)))
        .map(|(f, s, l)| {
            let (a, b) = design::cell_params(s, l);
            design.quota(f, s, l) as u64 * (a.total_fee() + b.total_fee())
        })
        .sum()
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

fn ms_between(later: Instant, earlier: Instant) -> f64 {
    if later >= earlier {
        (later - earlier).as_secs_f64() * 1e3
    } else {
        -((earlier - later).as_secs_f64() * 1e3)
    }
}

/// Waits for the first-shred event of `slot` until `until`; returns the anchor it implies
/// (the node's timestamp, else our arrival, minus the RPC lag) and the event record.
async fn wait_event(s: &Shared, slot: u64, pred_t0: Instant, until: Instant) -> (Option<Instant>, Value) {
    loop {
        if let Some((arrival, server)) = s.clock.first_shred_event(slot) {
            let base = server.unwrap_or(arrival);
            let anchor = base.checked_sub(s.rpc_lag).unwrap_or(base);
            let rec = json!({
                "arrival_minus_pred_ms": ms_between(arrival, pred_t0 + s.rpc_lag),
                "server_minus_pred_ms": server.map(|t| ms_between(t, pred_t0 + s.rpc_lag)),
                "anchor_shift_ms": ms_between(anchor, pred_t0),
                "anchor_from": if server.is_some() { "server_timestamp" } else { "arrival" },
            });
            return (Some(anchor), rec);
        }
        if Instant::now() >= until {
            return (None, json!({"missed": true}));
        }
        tokio::time::sleep(Duration::from_millis(2)).await;
    }
}

async fn handle_window(s: &Arc<Shared>, w: &Window, node: &Node, t0_chosen: Instant, plan: &[PairPlan], payer_slots: &[usize]) -> Result<()> {
    let tpu = node.tpu_quic.context("no TPU")?;
    // The window was chosen up to 20 s ahead; predict its start again shortly before it, from
    // the newest slot timestamps (the error grows with the distance extrapolated).
    if let Some(t) = t0_chosen.checked_sub(ANCHOR_REFRESH_LEAD) {
        tokio::time::sleep_until(t.into()).await;
    }
    let t0 = s.clock.predict(w.first_slot).and_then(|p| p.checked_sub(s.rpc_lag)).unwrap_or(t0_chosen);
    let mut win = json!({
        "run_id": s.run_id, "mode": s.mode, "window_id": w.first_slot, "leader": w.leader, "family": node.client_id,
        "family_class": FamilyClass::of(&node.client_id), "version": node.version, "tpu": tpu.to_string(), "stake": node.stake,
        "first_slot": w.first_slot, "window_slots": w.slots, "anchor_mode": s.anchor_mode.name(),
        "predicted_start_utc": s.anchor.utc(t0).to_rfc3339(), "predicted_start_us": s.anchor.us(t0),
        "chosen_start_utc": s.anchor.utc(t0_chosen).to_rfc3339(), "anchor_refresh_ms": ms_between(t0, t0_chosen),
        "pairs": plan.len(), "cells": plan.iter().map(|p| json!([p.series, p.lane])).collect::<Vec<_>>(),
    });
    let ci = s.clock.info();
    if let Some(ci) = &ci {
        win["clock"] = json!({"slot_ms": ci.slot_secs * 1e3, "residual_ms": ci.residual_ms, "samples": ci.samples,
                              "age_ms": ci.age_ms, "mode": ci.mode, "delivery_offset_ms": ci.delivery_offset_ms});
    }
    let release = |p: &PairPlan| {
        let _ = s.released.send((node.client_id.clone(), p.series, p.lane));
        s.pairs_released.fetch_add(1, Ordering::Relaxed);
    };
    if ci.is_none_or(|c| c.age_ms > MAX_CLOCK_AGE_MS) {
        win["skipped"] = json!("stale slot clock");
        plan.iter().for_each(release);
        write_line(&s.win_log, &win);
        return Ok(());
    }

    // Some ingress nodes (BAM) drop idle unstaked connections within seconds, so connect late:
    // ~700 ms before the first fire, which leaves room for a slow handshake.
    let first_fire = plan.iter().map(|p| offset(t0, p.fire_offsets()[0])).min().unwrap_or(t0);
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
        plan.iter().for_each(release);
        write_line(&s.win_log, &win);
        return Ok(());
    }

    let (blockhash, bh_at) = s.blockhash.lock().unwrap().context("no blockhash")?;
    win["blockhash_age_ms"] = json!(bh_at.elapsed().as_secs_f64() * 1e3);
    if bh_at.elapsed() > Duration::from_secs(20) {
        win["skipped"] = json!("stale blockhash");
        plan.iter().for_each(release);
        write_line(&s.win_log, &win);
        return Ok(());
    }

    // Sign everything now (at most ~2 s before the fire), then fire the pre-window pairs on the
    // predicted anchor and the in-window pairs on the window anchor.
    struct Signed {
        j: usize,
        plan: PairPlan,
        payer: Arc<Keypair>,
        a: (tx::SignedTx, Pubkey),
        b: (tx::SignedTx, Pubkey),
    }
    let mut pre = Vec::new();
    let mut inw = Vec::new();
    for (j, p) in plan.iter().enumerate() {
        let payer = s.payers[payer_slots[j]].clone();
        let (dest_a, dest_b) = (Pubkey::new_unique(), Pubkey::new_unique());
        let txa = tx::sign(tx::probe_message(&payer.pubkey(), &dest_a, &blockhash, &p.a, 0), &payer);
        let txb = tx::sign(tx::probe_message(&payer.pubkey(), &dest_b, &blockhash, &p.b, 0), &payer);
        let x = Signed { j, plan: p.clone(), payer, a: (txa, dest_a), b: (txb, dest_b) };
        if p.series.pre_window() {
            pre.push(x);
        } else {
            inw.push(x);
        }
    }

    let spawn = |x: Signed, anchor: Instant, anchor_kind: &'static str, skip: Option<&'static str>| {
        let p = x.plan;
        let ta = offset(anchor, p.a_offset_ms);
        let tb = offset(ta, p.s_ms);
        let base = json!({
            "run_id": s.run_id, "mode": s.mode, "window_id": w.first_slot, "pair_id": format!("{}-{}", w.first_slot, x.j),
            "series": p.series, "lane": p.lane, "a_offset_ms": p.a_offset_ms, "s_ms": p.s_ms, "anchor": anchor_kind,
            "payer": x.payer.pubkey().to_string(), "leader": w.leader, "family": node.client_id, "version": node.version,
            "tpu": tpu.to_string(), "first_slot": w.first_slot, "window_slots": w.slots,
            "not_after_utc": s.not_after.map(|t| t.to_rfc3339()),
        });
        let s = s.clone();
        let conn = conn.clone();
        let fam = node.client_id.clone();
        tokio::spawn(async move {
            let r = fire_pair(&s, conn, tpu, base, (x.a.0, x.a.1, p.a, ta), (x.b.0, x.b.1, p.b, tb), p.max_fee(), skip).await;
            if !r.fired {
                let _ = s.released.send((fam, p.series, p.lane));
                s.pairs_released.fetch_add(1, Ordering::Relaxed);
            }
            r
        })
    };

    let mut tasks = Vec::new();
    for x in pre {
        tasks.push(spawn(x, t0, "predicted", None));
    }
    let (anchor, kind, skip) = match s.anchor_mode {
        AnchorMode::Predicted => (t0, "predicted", None),
        AnchorMode::Event => {
            let (a, rec) = wait_event(s, w.first_slot, t0, t0 + s.rpc_lag + s.event_wait).await;
            win["event"] = rec;
            match a {
                Some(a) => (a, "event", None),
                None => (t0, "event", Some("no anchor event in time: skipped")),
            }
        }
    };
    for x in inw {
        tasks.push(spawn(x, anchor, kind, skip));
    }
    let mut first_fire_slot = None;
    let mut fired = 0;
    for t in tasks {
        if let Ok(r) = t.await {
            fired += r.fired as usize;
            if let Some(x) = r.slot_est {
                first_fire_slot.get_or_insert(x);
            }
        }
    }
    win["pairs_fired"] = json!(fired);
    if let Some(x) = first_fire_slot {
        win["slot_est_after_first_pair"] = json!(x);
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

struct Fired {
    /// went out (live) or would have gone out on time (dry-run)
    fired: bool,
    /// the slot clock's estimate just after the pair fired, for the window record
    slot_est: Option<f64>,
}

/// Fires one pair and writes both probes to the journal.
#[allow(clippy::too_many_arguments)]
async fn fire_pair(
    s: &Shared,
    conn: Option<quinn::Connection>,
    tpu: SocketAddr,
    base: Value,
    a: Probe,
    b: Probe,
    max_fee: u64,
    skip: Option<&'static str>,
) -> Fired {
    let (first_role, second_role, first, second) = if b.3 < a.3 { ("B", "A", b, a) } else { ("A", "B", a, b) };
    let mut error: Option<String> = skip.map(str::to_string);

    // Late guard: never fire a pair that would go out well after its planned moment.
    if error.is_none() && Instant::now() > first.3 + Duration::from_millis(50) {
        error = Some("late: skipped".into());
    }
    if error.is_none() && s.past_deadline() {
        error = Some("past --not-after: skipped".into());
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
        conn = match connection(s, tpu).await {
            Ok((c, _)) => Some(c),
            Err(e) => {
                error = Some(format!("reconnect: {e:#}"));
                None
            }
        };
    }
    if error.is_none() && s.live {
        match &conn {
            Some(c) => {
                let open = async { Ok::<_, anyhow::Error>((c.open_uni().await?, c.open_uni().await?)) };
                match tokio::time::timeout(Duration::from_millis(400), open).await {
                    Ok(Ok(st)) => streams = Some(st),
                    Ok(Err(e)) => error = Some(format!("open stream: {e:#}")),
                    Err(_) => error = Some("open stream: timeout".into()),
                }
            }
            None => error = Some("no connection".into()),
        }
    }

    let mut actual = [None, None];
    let mut sent = [false, false];
    let mut write_err: [Option<String>; 2] = [None, None];
    let mut slot_est = None;
    // A pair that is already behind its plan (slow event, slow stream opening) moves as a whole,
    // so the gap s between its probes survives; the shift is recorded.
    let mut shift = Duration::ZERO;
    if error.is_none() {
        let now = Instant::now() + Duration::from_micros(300);
        if now > first.3 {
            shift = now - first.3;
        }
    }
    if error.is_none() {
        let (sa, sb) = match streams {
            Some((x, y)) => (Some(x), Some(y)),
            None => (None, None),
        };
        for (k, (stream, probe)) in [(sa, &first), (sb, &second)].into_iter().enumerate() {
            // nothing but the wait sits between the two writes
            sleep_until_precise(probe.3 + shift).await;
            actual[k] = Some(match (stream, &s.permit) {
                (Some(st), Some(permit)) => match quic::write_tx(permit, tpu, st, &probe.0.bytes).await {
                    Ok(t) => {
                        sent[k] = true;
                        t
                    }
                    Err(e) => {
                        write_err[k] = Some(format!("write: {e:#}"));
                        Instant::now()
                    }
                },
                _ => Instant::now(),
            });
        }
        slot_est = s.clock.current_slot_f64();
        s.pairs_fired.fetch_add(1, Ordering::Relaxed);
    }

    // actual s: B's write minus A's write, from the monotonic clock
    let (a_k, b_k) = if first_role == "A" { (0, 1) } else { (1, 0) };
    let s_actual = match (actual[a_k], actual[b_k]) {
        (Some(ta), Some(tb)) => Some(ms_between(tb, ta)),
        _ => None,
    };
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
        v["agave_cost"] = json!(params.agave_cost());
        v["agave_priority"] = json!(params.agave_priority());
        v["planned_us"] = json!(s.anchor.us(*planned));
        v["planned_utc"] = json!(s.anchor.utc(*planned).to_rfc3339());
        if let Some(t) = actual[k] {
            v["write_us"] = json!(s.anchor.us(t));
            v["write_utc"] = json!(s.anchor.utc(t).to_rfc3339());
            v["late_us"] = json!(s.anchor.us(t) - s.anchor.us(*planned));
        }
        v["a_write_us"] = json!(actual[a_k].map(|t| s.anchor.us(t)));
        v["b_write_us"] = json!(actual[b_k].map(|t| s.anchor.us(t)));
        v["s_actual_ms"] = json!(s_actual);
        v["shift_ms"] = json!(shift.as_secs_f64() * 1e3);
        v["sent"] = json!(sent[k]);
        v["error"] = json!(error.clone().or_else(|| write_err[k].clone()));
        write_line(&s.tx_log, &v);
    }
    // a dry-run pair "fires" when it would have gone out on time; a live pair when A was written
    let fired = error.is_none() && (!s.live || sent.iter().any(|x| *x));
    Fired { fired, slot_est }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn worst_case_of_the_pilot_and_the_full_design() {
        let fams: Vec<String> = cluster::FAMILIES.iter().map(|f| f.to_string()).collect();
        let pilot = Design::new(DesignFile::default(), None, None, 0.1, Timing::default());
        // main: FEE 16 + 16, REV 2 + 2, C2 2 = 38 pairs; small: 5 + 5, 1 + 1, 1 = 13; 13,500 a pair
        assert_eq!(worst_case_lamports(&pilot, &fams), (5 * 38 + 3 * 13) * 13_500);
        let full = Design::new(DesignFile::default(), None, None, 1.0, Timing::default());
        assert_eq!(worst_case_lamports(&full, &fams), (5 * 365 + 3 * 120) * 13_500);
        assert_eq!(worst_case_lamports(&full, &fams[..1]), 365 * 13_500);
    }
}
