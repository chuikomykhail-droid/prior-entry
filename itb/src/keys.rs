//! Ed25519 keypairs stored in the Solana CLI format: a JSON array of 64 bytes (secret || public).

use std::fs;
use std::path::Path;

use anyhow::{bail, Context, Result};
use ed25519_dalek::{Signer, SigningKey};

use crate::tx::Pubkey;

pub struct Keypair {
    sk: SigningKey,
}

impl Keypair {
    pub fn generate() -> Self {
        Self { sk: SigningKey::generate(&mut rand::rngs::OsRng) }
    }

    pub fn pubkey(&self) -> Pubkey {
        Pubkey(self.sk.verifying_key().to_bytes())
    }

    pub fn sign(&self, msg: &[u8]) -> [u8; 64] {
        self.sk.sign(msg).to_bytes()
    }

    pub fn read(path: &Path) -> Result<Self> {
        let text = fs::read_to_string(path).with_context(|| format!("reading {}", path.display()))?;
        let bytes: Vec<u8> = serde_json::from_str(&text).with_context(|| format!("parsing {}", path.display()))?;
        let arr: [u8; 64] = bytes.try_into().map_err(|_| anyhow::anyhow!("{}: expected 64 bytes", path.display()))?;
        let sk = SigningKey::from_keypair_bytes(&arr).with_context(|| format!("{}: invalid keypair", path.display()))?;
        Ok(Self { sk })
    }

    /// Writes a new keypair file; never overwrites an existing one.
    pub fn write_new(&self, path: &Path) -> Result<()> {
        if path.exists() {
            bail!("{} already exists, refusing to overwrite", path.display());
        }
        if let Some(dir) = path.parent() {
            fs::create_dir_all(dir)?;
        }
        let bytes = self.sk.to_keypair_bytes().to_vec();
        fs::write(path, serde_json::to_string(&bytes)?)?;
        Ok(())
    }
}

/// Loads `<dir>/payer-NN.json` files in name order.
pub fn load_payers(dir: &Path) -> Result<Vec<Keypair>> {
    let mut paths: Vec<_> = fs::read_dir(dir)
        .with_context(|| format!("reading {}", dir.display()))?
        .filter_map(|e| e.ok().map(|e| e.path()))
        .filter(|p| p.file_name().and_then(|n| n.to_str()).is_some_and(|n| n.starts_with("payer-") && n.ends_with(".json")))
        .collect();
    paths.sort();
    paths.iter().map(|p| Keypair::read(p)).collect()
}
