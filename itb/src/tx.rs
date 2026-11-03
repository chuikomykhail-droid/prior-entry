//! Hand-built legacy Solana transactions for the probes.
//!
//! Every probe has the same shape, so only the numbers change between arms:
//!   0 SetComputeUnitLimit(cu_limit)
//!   1 SetComputeUnitPrice(cu_price)          micro-lamports per CU
//!   2 SetLoadedAccountsDataSizeLimit(bytes)
//!   3 System transfer payer -> dest (lamports, 0 for probes)
//! The two probes of a pair share the fee payer, so they write-lock the same account and are
//! executed one after the other; `dest` is a fresh address per transaction, which makes every
//! message (and signature) unique without a memo.

use std::fmt;
use std::str::FromStr;

use anyhow::{anyhow, Result};
use serde::Serialize;

use crate::keys::Keypair;

pub const BASE_FEE_PER_SIGNATURE: u64 = 5_000;
/// Instruction data bytes of one probe: 5 + 9 + 5 + 12.
pub const PROBE_DATA_BYTES: u64 = 31;

#[derive(Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct Pubkey(pub [u8; 32]);

impl Pubkey {
    pub fn new_unique() -> Self {
        Pubkey(rand::random())
    }
}

impl fmt::Display for Pubkey {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&bs58::encode(self.0).into_string())
    }
}

impl fmt::Debug for Pubkey {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        fmt::Display::fmt(self, f)
    }
}

impl FromStr for Pubkey {
    type Err = anyhow::Error;
    fn from_str(s: &str) -> Result<Self> {
        let v = bs58::decode(s).into_vec()?;
        Ok(Pubkey(v.try_into().map_err(|_| anyhow!("pubkey {s}: not 32 bytes"))?))
    }
}

impl Serialize for Pubkey {
    fn serialize<S: serde::Serializer>(&self, s: S) -> std::result::Result<S::Ok, S::Error> {
        s.serialize_str(&self.to_string())
    }
}

pub const SYSTEM_PROGRAM: Pubkey = Pubkey([0; 32]);

pub fn compute_budget_program() -> Pubkey {
    "ComputeBudget111111111111111111111111111111".parse().expect("valid program id")
}

/// SPL Memo v2.
pub fn memo_program() -> Pubkey {
    "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr".parse().expect("valid program id")
}

/// Economic parameters of one probe.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
pub struct ProbeParams {
    pub cu_limit: u32,
    /// micro-lamports per compute unit
    pub cu_price: u64,
    pub loaded_data: u32,
}

impl ProbeParams {
    pub fn priority_fee(&self) -> u64 {
        ((self.cu_price as u128 * self.cu_limit as u128).div_ceil(1_000_000)) as u64
    }

    pub fn total_fee(&self) -> u64 {
        BASE_FEE_PER_SIGNATURE + self.priority_fee()
    }

    /// Agave cost-model estimate used by the scheduler (one signature, two writable accounts).
    pub fn agave_cost(&self) -> u64 {
        720 + 300 * 2 + PROBE_DATA_BYTES / 4 + self.cu_limit as u64 + 8 * (self.loaded_data as u64).div_ceil(32 * 1024)
    }

    /// Agave scheduler priority: reward * 1e6 / (cost + 1), reward = priority fee + 50% of the base fee.
    pub fn agave_priority(&self) -> u64 {
        (self.priority_fee() + BASE_FEE_PER_SIGNATURE / 2) * 1_000_000 / (self.agave_cost() + 1)
    }
}

fn shortvec(out: &mut Vec<u8>, mut n: usize) {
    loop {
        let b = (n & 0x7f) as u8;
        n >>= 7;
        if n == 0 {
            out.push(b);
            return;
        }
        out.push(b | 0x80);
    }
}

fn instruction(out: &mut Vec<u8>, program_index: u8, accounts: &[u8], data: &[u8]) {
    out.push(program_index);
    shortvec(out, accounts.len());
    out.extend_from_slice(accounts);
    shortvec(out, data.len());
    out.extend_from_slice(data);
}

/// Serialized legacy message for one probe.
pub fn probe_message(payer: &Pubkey, dest: &Pubkey, blockhash: &[u8; 32], p: &ProbeParams, lamports: u64) -> Vec<u8> {
    let mut m = Vec::with_capacity(256);
    // header: 1 required signature, 0 read-only signed, 2 read-only unsigned (the two programs)
    m.extend_from_slice(&[1, 0, 2]);
    shortvec(&mut m, 4);
    for k in [payer, dest, &compute_budget_program(), &SYSTEM_PROGRAM] {
        m.extend_from_slice(&k.0);
    }
    m.extend_from_slice(blockhash);
    shortvec(&mut m, 4);
    let mut d = vec![2u8];
    d.extend_from_slice(&p.cu_limit.to_le_bytes());
    instruction(&mut m, 2, &[], &d);
    let mut d = vec![3u8];
    d.extend_from_slice(&p.cu_price.to_le_bytes());
    instruction(&mut m, 2, &[], &d);
    let mut d = vec![4u8];
    d.extend_from_slice(&p.loaded_data.to_le_bytes());
    instruction(&mut m, 2, &[], &d);
    let mut d = 2u32.to_le_bytes().to_vec();
    d.extend_from_slice(&lamports.to_le_bytes());
    instruction(&mut m, 3, &[0, 1], &d);
    m
}

/// Serialized legacy message for a plain transfer (funding and sweeping, not a probe).
pub fn transfer_message(from: &Pubkey, to: &Pubkey, blockhash: &[u8; 32], lamports: u64) -> Vec<u8> {
    let mut m = Vec::with_capacity(160);
    m.extend_from_slice(&[1, 0, 1]);
    shortvec(&mut m, 3);
    for k in [from, to, &SYSTEM_PROGRAM] {
        m.extend_from_slice(&k.0);
    }
    m.extend_from_slice(blockhash);
    shortvec(&mut m, 1);
    let mut d = 2u32.to_le_bytes().to_vec();
    d.extend_from_slice(&lamports.to_le_bytes());
    instruction(&mut m, 2, &[0, 1], &d);
    m
}

/// Serialized legacy message with one memo, signed (and paid) by `signer`: the pre-registration's hash.
pub fn memo_message(signer: &Pubkey, blockhash: &[u8; 32], text: &str) -> Vec<u8> {
    let mut m = Vec::with_capacity(112 + text.len());
    // 1 required signature, 0 read-only signed, 1 read-only unsigned (the program)
    m.extend_from_slice(&[1, 0, 1]);
    shortvec(&mut m, 2);
    for k in [signer, &memo_program()] {
        m.extend_from_slice(&k.0);
    }
    m.extend_from_slice(blockhash);
    shortvec(&mut m, 1);
    instruction(&mut m, 1, &[0], text.as_bytes());
    m
}

pub struct SignedTx {
    pub bytes: Vec<u8>,
    pub signature: [u8; 64],
}

impl SignedTx {
    pub fn signature_b58(&self) -> String {
        bs58::encode(self.signature).into_string()
    }
}

pub fn sign(message: Vec<u8>, signer: &Keypair) -> SignedTx {
    let signature = signer.sign(&message);
    let mut bytes = Vec::with_capacity(1 + 64 + message.len());
    shortvec(&mut bytes, 1);
    bytes.extend_from_slice(&signature);
    bytes.extend_from_slice(&message);
    SignedTx { bytes, signature }
}

/// A transaction with an all-zero signature, for `simulateTransaction` with `sigVerify: false`.
pub fn unsigned(message: &[u8]) -> Vec<u8> {
    let mut bytes = vec![1u8];
    bytes.extend_from_slice(&[0u8; 64]);
    bytes.extend_from_slice(message);
    bytes
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn shortvec_matches_spec() {
        let mut v = Vec::new();
        shortvec(&mut v, 0x7f);
        shortvec(&mut v, 0x80);
        shortvec(&mut v, 0x3fff);
        assert_eq!(v, vec![0x7f, 0x80, 0x01, 0xff, 0x7f]);
    }

    #[test]
    fn fees_and_priority() {
        let cheap = ProbeParams { cu_limit: 600, cu_price: 833_333, loaded_data: 32 * 1024 };
        assert_eq!(cheap.priority_fee(), 500);
        assert_eq!(cheap.agave_cost(), 1935);
        let big = ProbeParams { cu_limit: 600, cu_price: 833_333, loaded_data: 64 * 1024 * 1024 };
        assert_eq!(big.agave_cost(), 18_311);
        assert!(cheap.agave_priority() > big.agave_priority());
    }

    #[test]
    fn memo_message_layout() {
        let m = memo_message(&Pubkey([1; 32]), &[3; 32], "abc");
        assert_eq!(&m[..4], &[1, 0, 1, 2]);
        assert_eq!(&m[4 + 32..4 + 64], &memo_program().0);
        // one instruction: program 1, one account (the signer), 3 bytes of text
        assert_eq!(&m[4 + 64 + 32..], &[1, 1, 1, 0, 3, b'a', b'b', b'c']);
    }

    #[test]
    fn probe_size() {
        let p = ProbeParams { cu_limit: 600, cu_price: 1, loaded_data: 32 * 1024 };
        let m = probe_message(&Pubkey([1; 32]), &Pubkey([2; 32]), &[3; 32], &p, 0);
        let instr_data = 5 + 9 + 5 + 12;
        assert_eq!(instr_data as u64, PROBE_DATA_BYTES);
        assert_eq!(m.len(), 3 + 1 + 4 * 32 + 32 + 1 + (1 + 1 + 1 + 5) + (1 + 1 + 1 + 9) + (1 + 1 + 1 + 5) + (1 + 1 + 2 + 1 + 12));
    }
}
