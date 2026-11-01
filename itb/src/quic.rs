//! QUIC transport to a leader's TPU, the way Solana clients do it: TLS 1.3, ALPN `solana-tpu`,
//! a self-signed Ed25519 client certificate (we are unstaked, so its key is irrelevant to the
//! server), no server certificate validation, one transaction per unidirectional stream.

use std::net::SocketAddr;
use std::sync::Arc;
use std::time::{Duration, Instant};

use anyhow::{anyhow, Result};
use quinn::crypto::rustls::{QuicClientConfig, QuicServerConfig};
use rustls::client::danger::{HandshakeSignatureValid, ServerCertVerified, ServerCertVerifier};
use rustls::crypto::CryptoProvider;
use rustls::pki_types::{CertificateDer, PrivateKeyDer, PrivatePkcs8KeyDer, ServerName, UnixTime};
use rustls::{DigitallySignedStruct, SignatureScheme};

pub const ALPN_TPU: &[u8] = b"solana-tpu";
/// SNI Agave's own TPU client uses.
pub const SERVER_NAME: &str = "connect";

fn provider() -> Arc<CryptoProvider> {
    Arc::new(rustls::crypto::ring::default_provider())
}

fn self_signed() -> Result<(CertificateDer<'static>, PrivateKeyDer<'static>)> {
    let kp = rcgen::KeyPair::generate_for(&rcgen::PKCS_ED25519)?;
    let cert = rcgen::CertificateParams::new(vec!["solana".to_string()])?.self_signed(&kp)?;
    Ok((cert.der().clone(), PrivateKeyDer::Pkcs8(PrivatePkcs8KeyDer::from(kp.serialize_der()))))
}

#[derive(Debug)]
struct SkipServerVerification(Arc<CryptoProvider>);

impl ServerCertVerifier for SkipServerVerification {
    fn verify_server_cert(
        &self,
        _end_entity: &CertificateDer<'_>,
        _intermediates: &[CertificateDer<'_>],
        _server_name: &ServerName<'_>,
        _ocsp: &[u8],
        _now: UnixTime,
    ) -> Result<ServerCertVerified, rustls::Error> {
        Ok(ServerCertVerified::assertion())
    }

    fn verify_tls12_signature(
        &self,
        message: &[u8],
        cert: &CertificateDer<'_>,
        dss: &DigitallySignedStruct,
    ) -> Result<HandshakeSignatureValid, rustls::Error> {
        rustls::crypto::verify_tls12_signature(message, cert, dss, &self.0.signature_verification_algorithms)
    }

    fn verify_tls13_signature(
        &self,
        message: &[u8],
        cert: &CertificateDer<'_>,
        dss: &DigitallySignedStruct,
    ) -> Result<HandshakeSignatureValid, rustls::Error> {
        rustls::crypto::verify_tls13_signature(message, cert, dss, &self.0.signature_verification_algorithms)
    }

    fn supported_verify_schemes(&self) -> Vec<SignatureScheme> {
        self.0.signature_verification_algorithms.supported_schemes()
    }
}

pub fn client_endpoint() -> Result<quinn::Endpoint> {
    let provider = provider();
    let (cert, key) = self_signed()?;
    let mut crypto = rustls::ClientConfig::builder_with_provider(provider.clone())
        .with_protocol_versions(&[&rustls::version::TLS13])?
        .dangerous()
        .with_custom_certificate_verifier(Arc::new(SkipServerVerification(provider)))
        .with_client_auth_cert(vec![cert], key)?;
    crypto.alpn_protocols = vec![ALPN_TPU.to_vec()];
    let mut config = quinn::ClientConfig::new(Arc::new(QuicClientConfig::try_from(crypto)?));
    let mut transport = quinn::TransportConfig::default();
    transport.keep_alive_interval(Some(Duration::from_secs(1)));
    transport.max_idle_timeout(Some(Duration::from_secs(10).try_into()?));
    config.transport_config(Arc::new(transport));
    let mut ep = quinn::Endpoint::client("0.0.0.0:0".parse()?)?;
    ep.set_default_client_config(config);
    Ok(ep)
}

/// Connects and returns the connection plus the handshake duration.
pub async fn connect(ep: &quinn::Endpoint, addr: SocketAddr, timeout: Duration) -> Result<(quinn::Connection, Duration)> {
    let t0 = Instant::now();
    let connecting = ep.connect(addr, SERVER_NAME)?;
    let conn = tokio::time::timeout(timeout, connecting).await.map_err(|_| anyhow!("handshake timeout"))??;
    Ok((conn, t0.elapsed()))
}

/// Writes one transaction on an already opened stream and finishes it.
/// Returns the instant the bytes were handed to the QUIC stack.
pub async fn write_tx(mut stream: quinn::SendStream, bytes: &[u8]) -> Result<Instant> {
    stream.write_all(bytes).await?;
    let t = Instant::now();
    stream.finish()?;
    Ok(t)
}

/// A local QUIC sink used to calibrate send timing: records when each stream arrives.
pub fn server_endpoint(bind: SocketAddr) -> Result<quinn::Endpoint> {
    let (cert, key) = self_signed()?;
    let mut crypto = rustls::ServerConfig::builder_with_provider(provider())
        .with_protocol_versions(&[&rustls::version::TLS13])?
        .with_no_client_auth()
        .with_single_cert(vec![cert], key)?;
    crypto.alpn_protocols = vec![ALPN_TPU.to_vec()];
    let mut config = quinn::ServerConfig::with_crypto(Arc::new(QuicServerConfig::try_from(crypto)?));
    let mut transport = quinn::TransportConfig::default();
    transport.max_concurrent_uni_streams(1024u32.into());
    config.transport_config(Arc::new(transport));
    Ok(quinn::Endpoint::server(config, bind)?)
}
