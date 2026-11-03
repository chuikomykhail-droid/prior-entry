mod clock;
mod cluster;
mod collect;
mod design;
mod guard;
mod keys;
mod ledger;
mod quic;
mod rpc;
mod run;
mod tools;
mod tx;

use std::path::PathBuf;
use std::sync::Arc;

use anyhow::{bail, Result};
use clap::{Parser, Subcommand};

#[derive(Parser)]
#[command(name = "itb", about = "Inside the Block: the scheduling clock of Solana leaders, measured with paired probes")]
struct Cli {
    /// JSON-RPC endpoint (read-only use, plus funding transfers)
    #[arg(long, env = "ITB_RPC_URL", default_value = rpc::DEFAULT_RPC, global = true)]
    rpc: String,
    #[command(subcommand)]
    cmd: Cmd,
}

#[derive(Subcommand)]
enum Cmd {
    /// Create keys/funder.json and keys/payer-NN.json (never overwrites)
    Keygen {
        #[arg(long, default_value = "keys")]
        keys: PathBuf,
        /// 6 per concurrent window (the largest window, small families)
        #[arg(long, default_value_t = 12)]
        payers: usize,
    },
    /// Show funder and payer balances
    Balances {
        #[arg(long, default_value = "keys")]
        keys: PathBuf,
    },
    /// Simulate every probe variant on mainnet (nothing is sent)
    Simulate {
        #[arg(long, default_value = "data/checks")]
        out: PathBuf,
    },
    /// QUIC handshake with target TPUs, no transactions
    Probe {
        #[arg(long, value_delimiter = ',', default_values_t = default_families())]
        families: Vec<String>,
        #[arg(long, default_value_t = 3)]
        per_family: usize,
        #[arg(long, default_value = "data/checks")]
        out: PathBuf,
    },
    /// Record slot notifications and report the slot-clock fit
    Clock {
        #[arg(long, default_value_t = 40)]
        seconds: u64,
        #[arg(long, default_value = "data/checks")]
        out: PathBuf,
    },
    /// Measure our own send-gap precision against a local QUIC sink
    Calibrate {
        #[arg(long, default_value_t = 420)]
        pairs: usize,
        #[arg(long, default_value = "data/checks")]
        out: PathBuf,
    },
    /// Top up the payers from the funder (sends real transfers)
    Fund {
        #[arg(long, default_value = "keys")]
        keys: PathBuf,
        /// SOL per payer on top of the rent-exempt minimum
        #[arg(long)]
        per_payer_sol: f64,
        #[arg(long, default_value = "data/ledger.jsonl")]
        ledger: PathBuf,
        #[arg(long, default_value_t = 0.045)]
        cap_sol: f64,
    },
    /// Return all payer balances to the funder (sends real transfers)
    Sweep {
        #[arg(long, default_value = "keys")]
        keys: PathBuf,
        #[arg(long, default_value = "data/ledger.jsonl")]
        ledger: PathBuf,
        #[arg(long, default_value_t = 0.045)]
        cap_sol: f64,
    },
    /// Write a text (the pre-registration's hashes) on mainnet in a memo from the funder; only
    /// simulated unless --send is given
    Memo {
        text: String,
        /// Actually send it (5,000 lamports)
        #[arg(long)]
        send: bool,
        #[arg(long, default_value = "keys")]
        keys: PathBuf,
        #[arg(long, default_value = "data/ledger.jsonl")]
        ledger: PathBuf,
        #[arg(long, default_value_t = 0.045)]
        cap_sol: f64,
    },
    /// The measurement. Dry-run unless --live is given.
    Run {
        /// Actually send the probes. Without it nothing leaves this machine.
        #[arg(long)]
        live: bool,
        /// Project-wide spend cap enforced by the ledger (all runs together); at most 0.045
        #[arg(long, default_value_t = 0.045)]
        cap_sol: f64,
        /// UTC time after which nothing is sent (required with --live), e.g. 2026-11-03T20:00:00Z
        #[arg(long)]
        not_after: Option<chrono::DateTime<chrono::Utc>>,
        #[arg(long, default_value_t = 5.0)]
        minutes: f64,
        #[arg(long, value_delimiter = ',', default_values_t = default_families())]
        families: Vec<String>,
        /// validators per family (the top staked ones that advertise a QUIC TPU)
        #[arg(long, default_value_t = 2)]
        per_family: usize,
        /// Target exactly these validator identities instead (overrides --families and --per-family)
        #[arg(long, value_delimiter = ',')]
        validators: Option<Vec<String>>,
        /// Label recorded in meta.json, e.g. smoke, pilot, A, B (the analysis groups sessions by it)
        #[arg(long)]
        session: Option<String>,
        #[arg(long, default_value = "data/raw")]
        out: PathBuf,
        #[arg(long, default_value = "keys")]
        keys: PathBuf,
        #[arg(long, default_value = "data/ledger.jsonl")]
        ledger: PathBuf,
        /// In-window probes fire at random moments in [lo, hi] ms after the window anchor
        #[arg(long, default_value_t = 120.0)]
        start_lo_ms: f64,
        #[arg(long, default_value_t = 650.0)]
        start_hi_ms: f64,
        /// C2 control pairs fire this far from the predicted window start
        #[arg(long, default_value_t = -300.0, allow_negative_numbers = true)]
        ctrl_offset_ms: f64,
        /// How far the RPC node's first shred trails the leader's slot start (calibrated in the pilot)
        #[arg(long, default_value_t = 100.0)]
        rpc_lag_ms: f64,
        /// Window anchor: the slot clock's prediction, or the first-shred event of the window
        #[arg(long, value_enum, default_value_t = run::AnchorMode::Predicted)]
        anchor: run::AnchorMode,
        /// With --anchor event: give up on the window's in-window pairs if the event is this late
        #[arg(long, default_value_t = 250.0)]
        event_wait_ms: f64,
        #[arg(long, default_value_t = 2)]
        concurrent_windows: usize,
        #[arg(long)]
        max_windows: Option<usize>,
        #[arg(long)]
        seed: Option<u64>,
        /// Multiply the per-family pair quotas (e.g. 0.2 for a pilot)
        #[arg(long, default_value_t = 1.0)]
        quota_scale: f64,
        /// In dry-run, also open the QUIC connections (still sends nothing)
        #[arg(long)]
        connect: bool,
        /// Frozen grids per family and lane (design/grids.json, written by the analysis from the pilot)
        #[arg(long)]
        design: Option<PathBuf>,
        /// Pilot grids: FEE s in {0, 5, 20, 60, 150} ms, REV s in {-5, -20} ms
        #[arg(long)]
        pilot: bool,
        /// Send-gap grid for every FEE pair, ms (overrides the design file and --pilot)
        #[arg(long, value_delimiter = ',', allow_negative_numbers = true)]
        grid: Option<Vec<f64>>,
        /// Send-gap grid for REV pairs, ms (negative)
        #[arg(long, value_delimiter = ',', allow_negative_numbers = true)]
        rev_grid: Option<Vec<f64>>,
    },
    /// Freeze the main-run grids from pilot estimates of mu: {"family": {"VIP": mu_ms, "ECO": mu_ms}}
    FreezeGrids {
        #[arg(long)]
        mu_hat: PathBuf,
        #[arg(long, default_value = "design/grids.json")]
        out: PathBuf,
    },
    /// After a run: statuses, positions in the block and block extracts (read-only)
    Collect {
        /// run directory, e.g. data/runs/20261103T120000Z-live
        run: PathBuf,
        /// also extract these blocks (tests the extractor without probes)
        #[arg(long, value_delimiter = ',')]
        slots: Vec<u64>,
        /// pause between getBlock calls (the public RPC allows ~6 per 10 s)
        #[arg(long, default_value_t = 1500)]
        pace_ms: u64,
    },
}

fn default_families() -> Vec<String> {
    cluster::FAMILIES.iter().map(|s| s.to_string()).collect()
}

fn lamports(sol: f64) -> u64 {
    (sol * 1e9).round() as u64
}

#[tokio::main]
async fn main() -> Result<()> {
    let cli = Cli::parse();
    let rpc = Arc::new(rpc::Rpc::new(&cli.rpc)?);
    match cli.cmd {
        Cmd::Keygen { keys, payers } => tools::keygen(&keys, payers),
        Cmd::Balances { keys } => tools::balances(&rpc, &keys).await,
        Cmd::Simulate { out } => {
            if !tools::simulate(&rpc, &out).await? {
                bail!("a probe variant failed in simulation");
            }
            Ok(())
        }
        Cmd::Probe { families, per_family, out } => tools::probe(&rpc, &families, per_family, &out).await,
        Cmd::Calibrate { pairs, out } => tools::calibrate(pairs, &out).await,
        Cmd::Clock { seconds, out } => tools::clock(&rpc, seconds, &out).await,
        Cmd::Fund { keys, per_payer_sol, ledger, cap_sol } => {
            tools::fund(&rpc, &keys, &ledger, lamports(cap_sol), lamports(per_payer_sol)).await
        }
        Cmd::Sweep { keys, ledger, cap_sol } => tools::sweep(&rpc, &keys, &ledger, lamports(cap_sol)).await,
        Cmd::Memo { text, send, keys, ledger, cap_sol } => tools::memo(&rpc, &keys, &ledger, lamports(cap_sol), &text, send).await,
        Cmd::Run {
            live,
            cap_sol,
            not_after,
            minutes,
            families,
            per_family,
            validators,
            session,
            out,
            keys,
            ledger,
            start_lo_ms,
            start_hi_ms,
            ctrl_offset_ms,
            rpc_lag_ms,
            anchor,
            event_wait_ms,
            concurrent_windows,
            max_windows,
            seed,
            quota_scale,
            connect,
            design,
            pilot,
            grid,
            rev_grid,
        } => {
            let grid = grid.or_else(|| pilot.then(|| design::PILOT_GRID_MS.to_vec()));
            let rev_grid = rev_grid.or_else(|| pilot.then(|| design::PILOT_REV_GRID_MS.to_vec()));
            if lamports(cap_sol) > guard::HARD_CAP_LAMPORTS {
                bail!("--cap-sol {cap_sol} is above the project limit of 0.045 SOL");
            }
            if grid.as_ref().is_some_and(|g| g.iter().any(|s| *s < 0.0)) || rev_grid.as_ref().is_some_and(|g| g.iter().any(|s| *s >= 0.0)) {
                bail!("--grid takes s >= 0 and --rev-grid s < 0");
            }
            let cfg = run::RunConfig {
                live,
                cap_lamports: lamports(cap_sol),
                not_after,
                minutes,
                families,
                per_family,
                validators,
                session,
                out_root: out,
                keys_dir: keys,
                ledger_path: ledger,
                start_lo_ms,
                start_hi_ms,
                ctrl_offset_ms,
                rpc_lag_ms,
                anchor,
                event_wait_ms,
                max_windows,
                seed: seed.unwrap_or_else(rand::random),
                quota_scale,
                connect,
                design_file: design,
                grid_ms: grid,
                rev_grid_ms: rev_grid,
                concurrent_windows,
            };
            run::run(rpc, cfg).await
        }
        Cmd::FreezeGrids { mu_hat, out } => tools::freeze_grids(&mu_hat, &out),
        Cmd::Collect { run, slots, pace_ms } => collect::collect(&rpc, &run, &slots, std::time::Duration::from_millis(pace_ms)).await,
    }
}
