//! Timing: sub-millisecond waits on Windows, a wall-clock anchor for logs, and a slot clock fed by
//! the RPC node's WebSocket notifications.

use std::collections::{BTreeMap, VecDeque};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use chrono::{DateTime, Utc};
use futures_util::{SinkExt, StreamExt};
use serde_json::{json, Value};
use tokio_tungstenite::tungstenite::Message;

/// Sleeps coarsely, then spins (yielding to the runtime) for the last 20 ms.
/// The Windows timer alone overshoots by up to ~15 ms, which is larger than the gaps we control.
pub async fn sleep_until_precise(t: Instant) {
    let guard = Duration::from_millis(20);
    if let Some(left) = t.checked_duration_since(Instant::now()) {
        if left > guard {
            tokio::time::sleep_until((t - guard).into()).await;
        }
    }
    while Instant::now() < t {
        tokio::task::yield_now().await;
    }
}

/// Maps monotonic instants to UTC and back; intervals are always taken from `Instant`.
#[derive(Clone, Copy)]
pub struct Anchor {
    inst: Instant,
    utc: DateTime<Utc>,
}

impl Anchor {
    pub fn now() -> Self {
        Self { inst: Instant::now(), utc: Utc::now() }
    }

    pub fn utc(&self, t: Instant) -> DateTime<Utc> {
        if t >= self.inst {
            self.utc + chrono::Duration::from_std(t - self.inst).unwrap_or_default()
        } else {
            self.utc - chrono::Duration::from_std(self.inst - t).unwrap_or_default()
        }
    }

    /// Microseconds since the anchor (signed).
    pub fn us(&self, t: Instant) -> i64 {
        if t >= self.inst {
            (t - self.inst).as_micros() as i64
        } else {
            -((self.inst - t).as_micros() as i64)
        }
    }

    /// Unix time in seconds of a local instant.
    pub fn unix_secs(&self, t: Instant) -> f64 {
        self.utc.timestamp_micros() as f64 / 1e6 + self.us(t) as f64 / 1e6
    }

    /// Local instant of a unix time in seconds.
    pub fn instant_at(&self, unix_secs: f64) -> Option<Instant> {
        let d = unix_secs - self.utc.timestamp_micros() as f64 / 1e6;
        if d >= 0.0 {
            Some(self.inst + Duration::from_secs_f64(d))
        } else {
            self.inst.checked_sub(Duration::from_secs_f64(-d))
        }
    }
}

/// SNTP: offset of the local clock from true time (local - true), in seconds, from the sample with
/// the smallest round trip. Used to place the RPC node's own timestamps on our clock.
pub async fn ntp_offset(server: &str) -> anyhow::Result<(f64, f64)> {
    use tokio::net::UdpSocket;
    const NTP_UNIX_DELTA: f64 = 2_208_988_800.0;
    let sock = UdpSocket::bind("0.0.0.0:0").await?;
    sock.connect(server).await?;
    let anchor = Anchor::now();
    let mut best: Option<(f64, f64)> = None;
    for _ in 0..6 {
        let mut req = [0u8; 48];
        req[0] = 0x23; // LI 0, version 4, mode 3 (client)
        let t0 = Instant::now();
        sock.send(&req).await?;
        let mut buf = [0u8; 48];
        let Ok(Ok(n)) = tokio::time::timeout(Duration::from_secs(2), sock.recv(&mut buf)).await else { continue };
        let t3 = Instant::now();
        if n < 48 {
            continue;
        }
        let ts = |o: usize| {
            let secs = u32::from_be_bytes(buf[o..o + 4].try_into().unwrap()) as f64;
            let frac = u32::from_be_bytes(buf[o + 4..o + 8].try_into().unwrap()) as f64 / 4_294_967_296.0;
            secs + frac - NTP_UNIX_DELTA
        };
        let (t1, t2) = (ts(32), ts(40));
        let (c0, c3) = (anchor.unix_secs(t0), anchor.unix_secs(t3));
        let rtt = (c3 - c0) - (t2 - t1);
        let offset = ((c0 - t1) + (c3 - t2)) / 2.0;
        if best.is_none_or(|(_, r)| rtt < r) {
            best = Some((offset, rtt));
        }
        tokio::time::sleep(Duration::from_millis(200)).await;
    }
    best.ok_or_else(|| anyhow::anyhow!("no NTP reply from {server}"))
}

#[derive(Default)]
struct ClockState {
    /// (slot, local arrival) of `slotNotification`s, newest last
    samples: VecDeque<(u64, Instant)>,
    /// per slot: local arrival and the node's own timestamp (unix ms) of `firstShredReceived`
    first_shred: BTreeMap<u64, (Instant, Option<f64>)>,
    reconnects: u32,
}

/// Slot clock.
///
/// The public WebSocket delivers notifications in bursts and 1-5 s late, so local arrival times
/// are useless as a clock. `firstShredReceived` notifications carry the node's own timestamp of
/// the event, which delivery does not distort. We fit `server_time = a + b * slot` on those
/// timestamps and place server time on our clock with an SNTP offset (the local Windows clock is
/// not synchronised). The result predicts when the RPC node receives the first shred of a slot;
/// `rpc_lag_ms` in the run (calibrated in the pilot) converts that to the moment the leader starts
/// the slot. Without NTP we use the fastest delivery instead; without server timestamps, arrivals.
#[derive(Clone)]
pub struct SlotClock {
    state: Arc<Mutex<ClockState>>,
    anchor: Anchor,
    /// local clock minus true time, seconds
    ntp_offset: Option<f64>,
}

/// unix_secs(slot) = y0 + a + b * (slot - s0) + d
struct Line {
    s0: u64,
    y0: f64,
    a: f64,
    b: f64,
    d: f64,
}

pub struct ClockFit {
    pub slot_secs: f64,
    pub samples: usize,
    pub latest_slot: u64,
    pub age_ms: f64,
    /// median absolute deviation of the points around the line
    pub residual_ms: f64,
    pub mode: &'static str,
    /// delay of the fastest 5% of WebSocket deliveries after the node's own timestamp
    /// (corrected for the NTP offset when known)
    pub delivery_offset_ms: Option<f64>,
}

/// Raw notification arrivals, for the `clock` diagnostic.
pub struct RawClock {
    pub notifications: Vec<(u64, Instant)>,
    pub first_shreds: Vec<(u64, Instant, Option<f64>)>,
}

fn median(v: &mut [f64]) -> f64 {
    v.sort_by(|a, b| a.partial_cmp(b).unwrap());
    v[v.len() / 2]
}

fn quantile(v: &mut [f64], q: f64) -> f64 {
    v.sort_by(|a, b| a.partial_cmp(b).unwrap());
    v[((v.len() - 1) as f64 * q) as usize]
}

/// Median slope over point pairs at least 15 slots apart.
fn robust_slope(xs: &[f64], ys: &[f64]) -> Option<f64> {
    let mut slopes: Vec<f64> = (0..xs.len())
        .flat_map(|i| (i + 1..xs.len()).map(move |j| (i, j)))
        .filter(|(i, j)| xs[*j] - xs[*i] >= 15.0)
        .map(|(i, j)| (ys[j] - ys[i]) / (xs[j] - xs[i]))
        .collect();
    if slopes.is_empty() {
        None
    } else {
        Some(median(&mut slopes))
    }
}

impl SlotClock {
    pub fn start(ws_url: String, ntp_offset: Option<f64>) -> Self {
        let clock = SlotClock { state: Arc::new(Mutex::new(ClockState::default())), anchor: Anchor::now(), ntp_offset };
        let c = clock.clone();
        tokio::spawn(async move {
            loop {
                if let Err(e) = c.run_ws(&ws_url).await {
                    eprintln!("slot clock: {e:#}; reconnecting");
                }
                c.state.lock().unwrap().reconnects += 1;
                tokio::time::sleep(Duration::from_millis(500)).await;
            }
        });
        clock
    }

    async fn run_ws(&self, url: &str) -> anyhow::Result<()> {
        let (mut ws, _) = tokio_tungstenite::connect_async(url).await?;
        ws.send(Message::Text(json!({"jsonrpc": "2.0", "id": 1, "method": "slotSubscribe"}).to_string())).await?;
        ws.send(Message::Text(json!({"jsonrpc": "2.0", "id": 2, "method": "slotsUpdatesSubscribe"}).to_string())).await?;
        loop {
            let msg = match tokio::time::timeout(Duration::from_secs(5), ws.next()).await {
                Err(_) => anyhow::bail!("no message for 5 s"),
                Ok(None) => anyhow::bail!("closed"),
                Ok(Some(m)) => m?,
            };
            let now = Instant::now();
            match msg {
                Message::Text(t) => {
                    let Ok(v) = serde_json::from_str::<Value>(&t) else { continue };
                    let mut st = self.state.lock().unwrap();
                    match v["method"].as_str() {
                        Some("slotNotification") => {
                            if let Some(slot) = v["params"]["result"]["slot"].as_u64() {
                                if st.samples.back().is_none_or(|(s, _)| slot > *s) {
                                    st.samples.push_back((slot, now));
                                    while st.samples.len() > 300 {
                                        st.samples.pop_front();
                                    }
                                }
                            }
                        }
                        Some("slotsUpdatesNotification") => {
                            let r = &v["params"]["result"];
                            if r["type"].as_str() == Some("firstShredReceived") {
                                if let Some(slot) = r["slot"].as_u64() {
                                    let server_ms = r["timestamp"].as_u64().map(|x| x as f64);
                                    st.first_shred.entry(slot).or_insert((now, server_ms));
                                    while st.first_shred.len() > 300 {
                                        let k = *st.first_shred.keys().next().unwrap();
                                        st.first_shred.remove(&k);
                                    }
                                }
                            }
                        }
                        _ => {}
                    }
                }
                Message::Ping(p) => ws.send(Message::Pong(p)).await?,
                Message::Close(_) => anyhow::bail!("server closed"),
                _ => {}
            }
        }
    }

    fn fit(&self) -> Option<(Line, ClockFit)> {
        let st = self.state.lock().unwrap();
        let server: Vec<(u64, Instant, f64)> =
            st.first_shred.iter().filter_map(|(s, (t, ms))| ms.map(|m| (*s, *t, m / 1e3))).collect();
        if server.len() >= 25 {
            let pts = &server[server.len().saturating_sub(150)..];
            let s0 = pts[0].0;
            let y0 = pts[0].2;
            let xs: Vec<f64> = pts.iter().map(|p| (p.0 - s0) as f64).collect();
            let ys: Vec<f64> = pts.iter().map(|p| p.2 - y0).collect();
            let b = robust_slope(&xs, &ys)?;
            let mut icpt: Vec<f64> = xs.iter().zip(&ys).map(|(x, y)| y - b * x).collect();
            let a = median(&mut icpt);
            let mut dev: Vec<f64> = xs.iter().zip(&ys).map(|(x, y)| (y - a - b * x).abs()).collect();
            let resid = median(&mut dev);
            let mut delays: Vec<f64> = pts.iter().map(|p| self.anchor.unix_secs(p.1) - p.2).collect();
            let fastest = quantile(&mut delays, 0.05);
            let d = self.ntp_offset.unwrap_or(fastest);
            let last = pts.last().unwrap();
            let info = ClockFit {
                slot_secs: b,
                samples: pts.len(),
                latest_slot: last.0,
                age_ms: last.1.elapsed().as_secs_f64() * 1e3,
                residual_ms: resid * 1e3,
                mode: if self.ntp_offset.is_some() { "server_timestamp+ntp" } else { "server_timestamp" },
                delivery_offset_ms: Some((fastest - self.ntp_offset.unwrap_or(0.0)) * 1e3),
            };
            return Some((Line { s0, y0, a, b, d }, info));
        }
        // Fallback: local arrivals, anchored on the least-delayed notifications.
        let local: Vec<(u64, Instant)> = if st.first_shred.len() >= 25 {
            st.first_shred.iter().map(|(s, (t, _))| (*s, *t)).collect()
        } else {
            st.samples.iter().copied().collect()
        };
        if local.len() < 25 {
            return None;
        }
        let pts = &local[local.len().saturating_sub(120)..];
        let s0 = pts[0].0;
        let y0 = self.anchor.unix_secs(pts[0].1);
        let xs: Vec<f64> = pts.iter().map(|p| (p.0 - s0) as f64).collect();
        let ys: Vec<f64> = pts.iter().map(|p| self.anchor.unix_secs(p.1) - y0).collect();
        let b = robust_slope(&xs, &ys)?;
        let mut icpt: Vec<f64> = xs.iter().zip(&ys).map(|(x, y)| y - b * x).collect();
        let a = quantile(&mut icpt, 0.1);
        let mut dev: Vec<f64> = icpt.iter().map(|c| (c - a).abs()).collect();
        let resid = median(&mut dev);
        let last = pts.last().unwrap();
        let info = ClockFit {
            slot_secs: b,
            samples: pts.len(),
            latest_slot: last.0,
            age_ms: last.1.elapsed().as_secs_f64() * 1e3,
            residual_ms: resid * 1e3,
            mode: "arrival",
            delivery_offset_ms: None,
        };
        Some((Line { s0, y0, a, b, d: 0.0 }, info))
    }

    /// Local instant at which the RPC node is predicted to receive the first shred of `slot`.
    pub fn predict(&self, slot: u64) -> Option<Instant> {
        let (l, _) = self.fit()?;
        self.anchor.instant_at(l.y0 + l.a + l.b * (slot as f64 - l.s0 as f64) + l.d)
    }

    /// Fractional slot the RPC node is predicted to be at, now.
    pub fn current_slot_f64(&self) -> Option<f64> {
        let (l, _) = self.fit()?;
        let now = self.anchor.unix_secs(Instant::now());
        Some(l.s0 as f64 + (now - l.d - l.y0 - l.a) / l.b)
    }

    pub fn info(&self) -> Option<ClockFit> {
        self.fit().map(|(_, i)| i)
    }

    pub fn raw(&self) -> RawClock {
        let st = self.state.lock().unwrap();
        RawClock {
            notifications: st.samples.iter().copied().collect(),
            first_shreds: st.first_shred.iter().map(|(s, (t, m))| (*s, *t, *m)).collect(),
        }
    }

    /// `firstShredReceived` records with slot > `after`: (slot, local arrival, server unix ms).
    pub fn first_shreds_after(&self, after: u64) -> Vec<(u64, Instant, Option<f64>)> {
        let st = self.state.lock().unwrap();
        st.first_shred.range(after + 1..).map(|(s, (t, m))| (*s, *t, *m)).collect()
    }

    pub fn reconnects(&self) -> u32 {
        self.state.lock().unwrap().reconnects
    }

    pub fn anchor(&self) -> Anchor {
        self.anchor
    }
}
