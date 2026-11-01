mod clock;
mod cluster;
mod design;
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
        #[arg(long, default_value_t = 8)]
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
        /// lamports per payer on top of the rent-exempt minimum
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
    /// The measurement. Dry-run unless --live is given.
    Run {
        /// Actually send the probes. Without it nothing leaves this machine.
        #[arg(long)]
        live: bool,
        /// Project-wide spend cap enforced by the ledger (all runs together)
        #[arg(long, default_value_t = 0.045)]
        cap_sol: f64,
        #[arg(long, default_value_t = 5.0)]
        minutes: f64,
        #[arg(long, value_delimiter = ',', default_values_t = default_families())]
        families: Vec<String>,
        #[arg(long, default_value_t = 3)]
        per_family: usize,
        #[arg(long, default_value = "data/runs")]
        out: PathBuf,
        #[arg(long, default_value = "keys")]
        keys: PathBuf,
        #[arg(long, default_value = "data/ledger.jsonl")]
        ledger: PathBuf,
        /// First in-window pair fires this long after the predicted window start. The slot
        /// clock is good to a few hundred ms, so in-window pairs aim at the middle of the window.
        #[arg(long, default_value_t = 250.0)]
        in_offset_ms: f64,
        #[arg(long, default_value_t = 150.0)]
        in_step_ms: f64,
        /// Pre-window pairs (PRE, KEY) fire this long before the predicted window start
        #[arg(long, default_value_t = -1000.0, allow_negative_numbers = true)]
        pre_offset_ms: f64,
        /// How far the RPC node's first shred trails the leader's slot start (calibrated in the pilot)
        #[arg(long, default_value_t = 100.0)]
        rpc_lag_ms: f64,
        #[arg(long, default_value_t = 3)]
        pairs_per_window: usize,
        #[arg(long, default_value_t = 2)]
        concurrent_windows: usize,
        #[arg(long)]
        max_windows: Option<usize>,
        #[arg(long)]
        seed: Option<u64>,
        /// Multiply the per-family pair quotas (e.g. 0.1 for a pilot)
        #[arg(long, default_value_t = 1.0)]
        quota_scale: f64,
        /// In dry-run, also open the QUIC connections (still sends nothing)
        #[arg(long)]
        connect: bool,
        /// Send-gap grid for FEE and TIE pairs, ms
        #[arg(long, value_delimiter = ',', allow_negative_numbers = true)]
        grid: Option<Vec<f64>>,
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
        Cmd::Run {
            live,
            cap_sol,
            minutes,
            families,
            per_family,
            out,
            keys,
            ledger,
            in_offset_ms,
            in_step_ms,
            pre_offset_ms,
            rpc_lag_ms,
            pairs_per_window,
            concurrent_windows,
            max_windows,
            seed,
            quota_scale,
            connect,
            grid,
        } => {
            if cap_sol > 0.05 {
                bail!("--cap-sol {cap_sol} is above the project limit of 0.05 SOL");
            }
            let cfg = run::RunConfig {
                live,
                cap_lamports: lamports(cap_sol),
                minutes,
                families,
                per_family,
                out_root: out,
                keys_dir: keys,
                ledger_path: ledger,
                in_offset_ms,
                in_step_ms,
                pre_offset_ms,
                rpc_lag_ms,
                pairs_per_window,
                max_windows,
                seed: seed.unwrap_or_else(rand::random),
                quota_scale,
                connect,
                grid_ms: grid.unwrap_or_else(|| design::DEFAULT_GRID_MS.to_vec()),
                concurrent_windows,
            };
            run::run(rpc, cfg).await
        }
    }
}
