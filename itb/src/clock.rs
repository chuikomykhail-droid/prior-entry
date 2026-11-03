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

pub const NTP_SERVER: &str = "time.google.com:123";

/// SNTP: offset of `anchor`'s clock from true time (anchor's UTC minus true), in seconds, and the
/// round trip of the sample used. Places the RPC node's own timestamps on our clock.
///
/// The anchor maps the monotonic clock to UTC, so the offset also carries the monotonic clock's
/// drift since the anchor was taken (+52 ppm on the measurement PC, ~0.2 s an hour): long runs
/// measure it again. Our network delivers some UDP replies twice; a duplicate read as the answer to
/// the next request looks like a 0.1 ms round trip with the offset wrong by the request spacing,
/// so replies must echo the request's nonce, and `pick_ntp` decides which sample counts.
pub async fn ntp_offset(server: &str, anchor: &Anchor) -> anyhow::Result<(f64, f64)> {
    use tokio::net::UdpSocket;
    const NTP_UNIX_DELTA: f64 = 2_208_988_800.0;
    let sock = UdpSocket::bind("0.0.0.0:0").await?;
    sock.connect(server).await?;
    let mut samples = Vec::new();
    for _ in 0..8 {
        let mut req = [0u8; 48];
        req[0] = 0x23; // LI 0, version 4, mode 3 (client)
        // a nonce as the transmit timestamp: the server echoes it as the originate timestamp, so a
        // late or duplicated reply to an earlier request is recognised and dropped (RFC 5905)
        let nonce: [u8; 8] = rand::random();
        req[40..48].copy_from_slice(&nonce);
        let t0 = Instant::now();
        sock.send(&req).await?;
        let deadline = t0 + Duration::from_secs(2);
        let mut buf = [0u8; 48];
        let t3 = loop {
            match tokio::time::timeout(deadline.saturating_duration_since(Instant::now()), sock.recv(&mut buf)).await {
                Ok(Ok(n)) if n >= 48 && buf[24..32] == nonce => break Some(Instant::now()),
                Ok(Ok(_)) => continue,
                _ => break None,
            }
        };
        let Some(t3) = t3 else { continue };
        let ts = |o: usize| {
            let secs = u32::from_be_bytes(buf[o..o + 4].try_into().unwrap()) as f64;
            let frac = u32::from_be_bytes(buf[o + 4..o + 8].try_into().unwrap()) as f64 / 4_294_967_296.0;
            secs + frac - NTP_UNIX_DELTA
        };
        let (t1, t2) = (ts(32), ts(40));
        let (c0, c3) = (anchor.unix_secs(t0), anchor.unix_secs(t3));
        if buf[0] & 0x07 != 4 || t2 < t1 {
            continue; // not a server reply
        }
        let rtt = (c3 - c0) - (t2 - t1);
        let offset = ((c0 - t1) + (c3 - t2)) / 2.0;
        samples.push((offset, rtt));
        tokio::time::sleep(Duration::from_millis(200)).await;
    }
    pick_ntp(&samples).ok_or_else(|| anyhow::anyhow!("no consistent NTP replies from {server} ({} replies)", samples.len()))
}

/// The (offset, round trip) sample with the smallest round trip among those that agree with the
/// median offset within 25 ms, if at least three agree: a lone wrong sample does not win.
pub fn pick_ntp(samples: &[(f64, f64)]) -> Option<(f64, f64)> {
    if samples.len() < 3 {
        return None;
    }
    let mut offs: Vec<f64> = samples.iter().map(|s| s.0).collect();
    let med = median(&mut offs);
    let agree: Vec<(f64, f64)> = samples.iter().copied().filter(|s| (s.0 - med).abs() <= 0.025).collect();
    if agree.len() < 3 {
        return None;
    }
    agree.into_iter().min_by(|a, b| a.1.total_cmp(&b.1))
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
///
/// Slot times under Alpenglow drift like a random walk (≈30 ms per slot inside a window, ≈55 ms at
/// a leader change), so the slope comes from the last 150 slots but the line is pinned to the
/// last `RECENT` points: the prediction then extrapolates from the newest data, not from the middle
/// of the fit (offline check on 1,365 recorded window starts, 1 s ahead: error p10 −288 / p50 −27 /
/// p90 +145 ms, against −385 / −27 / +296 ms with the median intercept of all 150 points).
#[derive(Clone)]
pub struct SlotClock {
    state: Arc<Mutex<ClockState>>,
    anchor: Anchor,
    /// the anchor's clock minus true time, seconds: the latest accepted NTP measurement
    ntp_offset: Arc<Mutex<Option<f64>>>,
}

/// Newest server timestamps the line is pinned to.
const RECENT: usize = 4;

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
    /// `ntp_offset` must be measured against `anchor` (`ntp_offset(server, &anchor)`).
    pub fn start(ws_url: String, ntp_offset: Option<f64>, anchor: Anchor) -> Self {
        let clock = SlotClock { state: Arc::new(Mutex::new(ClockState::default())), anchor, ntp_offset: Arc::new(Mutex::new(ntp_offset)) };
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

    /// A new NTP measurement against the clock's anchor (the monotonic clock drifts).
    pub fn set_ntp_offset(&self, offset: f64) {
        *self.ntp_offset.lock().unwrap() = Some(offset);
    }

    pub fn ntp_offset(&self) -> Option<f64> {
        *self.ntp_offset.lock().unwrap()
    }

    fn fit(&self) -> Option<(Line, ClockFit)> {
        let ntp = self.ntp_offset();
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
            let a = median(&mut icpt[xs.len() - RECENT.min(xs.len())..]);
            let mut dev: Vec<f64> = xs.iter().zip(&ys).map(|(x, y)| (y - a - b * x).abs()).collect();
            let resid = median(&mut dev);
            let mut delays: Vec<f64> = pts.iter().map(|p| self.anchor.unix_secs(p.1) - p.2).collect();
            let fastest = quantile(&mut delays, 0.05);
            let d = ntp.unwrap_or(fastest);
            let last = pts.last().unwrap();
            let info = ClockFit {
                slot_secs: b,
                samples: pts.len(),
                latest_slot: last.0,
                age_ms: last.1.elapsed().as_secs_f64() * 1e3,
                residual_ms: resid * 1e3,
                mode: if ntp.is_some() { "server_timestamp+ntp" } else { "server_timestamp" },
                delivery_offset_ms: Some((fastest - ntp.unwrap_or(0.0)) * 1e3),
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

    /// The `firstShredReceived` event of `slot`, once it has reached us: (local arrival, the
    /// node's own timestamp placed on our clock when it and the NTP offset are known).
    pub fn first_shred_event(&self, slot: u64) -> Option<(Instant, Option<Instant>)> {
        let ntp = self.ntp_offset();
        let st = self.state.lock().unwrap();
        let (t, ms) = st.first_shred.get(&slot)?;
        let server = match (ms, ntp) {
            (Some(m), Some(off)) => self.anchor.instant_at(m / 1e3 + off),
            _ => None,
        };
        Some((*t, server))
    }

    pub fn reconnects(&self) -> u32 {
        self.state.lock().unwrap().reconnects
    }

    pub fn anchor(&self) -> Anchor {
        self.anchor
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_lone_wrong_sample_does_not_win() {
        // six genuine replies and one that looks 0.7 ms fast and 183 ms off (as a duplicated
        // reply read as the answer to the next request did on our network)
        let round = [(2.2701, 0.0371), (2.2703, 0.0365), (2.4529, 0.0007), (2.2699, 0.0362), (2.2702, 0.0368), (2.2700, 0.0374)];
        assert_eq!(pick_ntp(&round), Some((2.2699, 0.0362)));
        // without consensus there is no answer
        assert_eq!(pick_ntp(&[(2.27, 0.036), (2.45, 0.001)]), None);
        assert_eq!(pick_ntp(&[(2.27, 0.036), (2.45, 0.001), (2.49, 0.001), (2.10, 0.03)]), None);
        assert_eq!(pick_ntp(&[]), None);
    }

    #[tokio::test]
    async fn a_duplicated_reply_is_not_taken_for_the_next_request() {
        use tokio::net::UdpSocket;
        // a server on true time (here: the system clock) that sends every reply twice, as our network did
        let server = UdpSocket::bind("127.0.0.1:0").await.unwrap();
        let addr = server.local_addr().unwrap().to_string();
        tokio::spawn(async move {
            let mut buf = [0u8; 48];
            while let Ok((n, from)) = server.recv_from(&mut buf).await {
                if n < 48 {
                    continue;
                }
                let now = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap();
                let mut ts = [0u8; 8];
                ts[..4].copy_from_slice(&((now.as_secs() + 2_208_988_800) as u32).to_be_bytes());
                ts[4..].copy_from_slice(&(((now.subsec_nanos() as u64) << 32) / 1_000_000_000).to_be_bytes()[4..]);
                let mut reply = [0u8; 48];
                reply[0] = 0x24; // version 4, mode 4 (server)
                reply[1] = 1;
                reply[24..32].copy_from_slice(&buf[40..48]); // originate = the request's transmit
                reply[32..40].copy_from_slice(&ts);
                reply[40..48].copy_from_slice(&ts);
                for _ in 0..2 {
                    let _ = server.send_to(&reply, from).await;
                }
            }
        });
        let (offset, rtt) = ntp_offset(&addr, &Anchor::now()).await.unwrap();
        // a duplicate taken for the next reply would show up as ~0.2 s of offset (the request spacing)
        assert!(offset.abs() < 0.005, "offset {offset}");
        assert!((0.0..0.005).contains(&rtt), "rtt {rtt}");
    }
}
