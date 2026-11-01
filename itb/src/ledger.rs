//! Spend ledger. Every live send reserves its worst-case fee here *before* the bytes leave, and a
//! reservation that would cross the cap is refused. The ledger is one append-only file shared by
//! all runs, so the cap holds for the whole project (pilot + main runs), not per run.
//! After a run, `collect` and the chain balances are reconciled against these reservations.

use std::fs::{self, File, OpenOptions};
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};

use anyhow::Result;
use serde_json::json;

pub struct Ledger {
    path: PathBuf,
    cap: u64,
    reserved: u64,
    file: File,
}

impl Ledger {
    pub fn open(path: &Path, cap_lamports: u64) -> Result<Self> {
        if let Some(dir) = path.parent() {
            fs::create_dir_all(dir)?;
        }
        let mut reserved = 0;
        if path.exists() {
            for line in BufReader::new(File::open(path)?).lines() {
                let v: serde_json::Value = serde_json::from_str(&line?)?;
                reserved += v["lamports"].as_u64().unwrap_or(0);
            }
        }
        let file = OpenOptions::new().create(true).append(true).open(path)?;
        Ok(Self { path: path.to_path_buf(), cap: cap_lamports, reserved, file })
    }

    pub fn reserved(&self) -> u64 {
        self.reserved
    }

    pub fn cap(&self) -> u64 {
        self.cap
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    /// Reserves `lamports` or refuses if the cap would be exceeded.
    pub fn reserve(&mut self, lamports: u64, run_id: &str, what: &str) -> Result<bool> {
        if self.reserved + lamports > self.cap {
            return Ok(false);
        }
        self.reserved += lamports;
        let line = json!({"utc": chrono::Utc::now().to_rfc3339(), "run_id": run_id, "what": what, "lamports": lamports, "total": self.reserved});
        writeln!(self.file, "{line}")?;
        self.file.flush()?;
        Ok(true)
    }
}
