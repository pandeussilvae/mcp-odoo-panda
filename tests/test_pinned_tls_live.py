"""Real TCP+TLS tests against an isolated local endpoint (test CA).

Covers: pinning, SNI/hostname verify, invalid cert, wrong hostname,
no secondary DNS, error propagation, normal XML-RPC over pinned HTTPS.
"""

from __future__ import annotations

import ssl
import socket
import threading
import xmlrpc.client
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from ipaddress import ip_address
from typing import Callable
from unittest.mock import patch

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from odoo_mcp.core.safe_destination import (
    DestinationPolicyError,
    PinnedDestination,
    DestinationClass,
    open_xmlrpc_proxy,
    open_xmlrpc_transport,
    set_dns_resolver,
    validate_odoo_destination,
)


HOSTNAME = "odoo.test.local"


@dataclass
class _TlsBundle:
    ca_pem: bytes
    cert_pem: bytes
    key_pem: bytes
    wrong_cert_pem: bytes
    wrong_key_pem: bytes


def _build_tls_bundle() -> _TlsBundle:
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Odward Test CA")])
    now = datetime.now(timezone.utc)
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=7))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )

    def _leaf(cn: str):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
        cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(ca_name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(days=2))
            .add_extension(
                x509.SubjectAlternativeName([x509.DNSName(cn)]),
                critical=False,
            )
            .sign(ca_key, hashes.SHA256())
        )
        return key, cert

    leaf_key, leaf_cert = _leaf(HOSTNAME)
    wrong_key, wrong_cert = _leaf("evil.other.local")

    def _pem_cert(c):
        return c.public_bytes(serialization.Encoding.PEM)

    def _pem_key(k):
        return k.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )

    return _TlsBundle(
        ca_pem=_pem_cert(ca_cert),
        cert_pem=_pem_cert(leaf_cert),
        key_pem=_pem_key(leaf_key),
        wrong_cert_pem=_pem_cert(wrong_cert),
        wrong_key_pem=_pem_key(wrong_key),
    )


class _XmlRpcHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # noqa: ANN001
        return

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        _ = self.rfile.read(length)
        # Minimal XML-RPC response for common.version()
        body = (
            b"<?xml version='1.0'?>\n"
            b"<methodResponse><params><param><value>"
            b"<struct>"
            b"<member><name>server_version</name><value><string>17.0-test</string></value></member>"
            b"</struct>"
            b"</value></param></params></methodResponse>\n"
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/xml")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _start_https_server(cert_pem: bytes, key_pem: bytes) -> tuple[HTTPServer, int, threading.Thread]:
    httpd = HTTPServer(("127.0.0.1", 0), _XmlRpcHandler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    # Write temp files via SSLContext load from memory via temp path
    import tempfile
    from pathlib import Path

    tmp = Path(tempfile.mkdtemp(prefix="odward-tls-"))
    cert_path = tmp / "server.pem"
    key_path = tmp / "server.key"
    cert_path.write_bytes(cert_pem)
    key_path.write_bytes(key_pem)
    ctx.load_cert_chain(str(cert_path), str(key_path))
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    port = httpd.server_address[1]
    thr = threading.Thread(target=httpd.serve_forever, daemon=True)
    thr.start()
    return httpd, port, thr


@pytest.fixture(autouse=True)
def _lab_private(monkeypatch):
    set_dns_resolver(None)
    monkeypatch.setenv("ODWARD_LAB_PROFILE", "1")
    monkeypatch.setenv("ODWARD_ALLOW_PRIVATE_ODOO_URL", "1")
    monkeypatch.delenv("ODWARD_DEPLOYMENT", raising=False)
    yield
    set_dns_resolver(None)


@pytest.fixture(scope="module")
def tls_bundle() -> _TlsBundle:
    return _build_tls_bundle()


def _ssl_ctx_for_ca(ca_pem: bytes) -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    import tempfile
    from pathlib import Path

    tmp = Path(tempfile.mkdtemp(prefix="odward-ca-"))
    ca_path = tmp / "ca.pem"
    ca_path.write_bytes(ca_pem)
    ctx.load_verify_locations(str(ca_path))
    return ctx


def _pin(port: int) -> PinnedDestination:
    return PinnedDestination(
        url=f"https://{HOSTNAME}:{port}",
        hostname=HOSTNAME,
        port=port,
        scheme="https",
        ip="127.0.0.1",
        family=socket.AF_INET,
        classification=DestinationClass.LOOPBACK,
    )


def test_live_pinned_https_xmlrpc_ok(tls_bundle: _TlsBundle):
    httpd, port, _thr = _start_https_server(tls_bundle.cert_pem, tls_bundle.key_pem)
    try:
        dns_calls: list[str] = []

        def tracking_resolver(host, *a, **k):  # noqa: ANN001
            dns_calls.append(host)
            raise AssertionError(f"unexpected DNS for pinned dial: {host}")

        set_dns_resolver(tracking_resolver)
        pin = _pin(port)
        ctx = _ssl_ctx_for_ca(tls_bundle.ca_pem)
        # Capture peer TCP target
        connected: list[tuple] = []
        real_cc = socket.create_connection

        def watching_cc(address, timeout=None):  # noqa: ANN001
            connected.append(address)
            return real_cc(address, timeout)

        with patch(
            "odoo_mcp.core.safe_destination.socket.create_connection",
            side_effect=watching_cc,
        ):
            proxy = open_xmlrpc_proxy(
                f"https://{HOSTNAME}:{port}",
                "/xmlrpc/2/common",
                pinned=pin,
                context=ctx,
            )
            # xmlrpc method call
            ver = proxy.version()
        assert ver["server_version"] == "17.0-test"
        assert connected, "expected real TCP connect"
        assert connected[0][0] == "127.0.0.1"
        assert connected[0][1] == port
        assert dns_calls == []
    finally:
        # HTTPS+HTTPServer.shutdown can deadlock; close socket from a helper thread.
        threading.Thread(target=httpd.shutdown, daemon=True).start()
        httpd.server_close()


def test_live_sni_and_hostname_verify(tls_bundle: _TlsBundle):
    httpd, port, _thr = _start_https_server(tls_bundle.cert_pem, tls_bundle.key_pem)
    try:
        pin = _pin(port)
        ctx = _ssl_ctx_for_ca(tls_bundle.ca_pem)
        transport = open_xmlrpc_transport(pin, context=ctx)
        # Force a connection to observe SSL peer / SNI via successful handshake
        conn = transport.make_connection((HOSTNAME, port))
        conn.connect()
        assert conn.sock is not None
        assert isinstance(conn.sock, ssl.SSLSocket)
        assert conn.sock.server_hostname == HOSTNAME
        peercert = conn.sock.getpeercert()
        assert peercert  # verified against CA
        conn.close()
    finally:
        # HTTPS+HTTPServer.shutdown can deadlock; close socket from a helper thread.
        threading.Thread(target=httpd.shutdown, daemon=True).start()
        httpd.server_close()


def test_live_rejects_wrong_hostname_cert(tls_bundle: _TlsBundle):
    httpd, port, _thr = _start_https_server(
        tls_bundle.wrong_cert_pem, tls_bundle.wrong_key_pem
    )
    try:
        pin = _pin(port)
        ctx = _ssl_ctx_for_ca(tls_bundle.ca_pem)
        proxy = open_xmlrpc_proxy(
            f"https://{HOSTNAME}:{port}",
            "/xmlrpc/2/common",
            pinned=pin,
            context=ctx,
        )
        with pytest.raises(ssl.SSLCertVerificationError):
            proxy.version()
    finally:
        # HTTPS+HTTPServer.shutdown can deadlock; close socket from a helper thread.
        threading.Thread(target=httpd.shutdown, daemon=True).start()
        httpd.server_close()


def test_live_rejects_untrusted_cert(tls_bundle: _TlsBundle):
    """Server cert signed by our test CA must fail against empty trust store."""
    httpd, port, _thr = _start_https_server(tls_bundle.cert_pem, tls_bundle.key_pem)
    try:
        pin = _pin(port)
        ctx = ssl.create_default_context()  # system CAs only — test CA not present
        proxy = open_xmlrpc_proxy(
            f"https://{HOSTNAME}:{port}",
            "/xmlrpc/2/common",
            pinned=pin,
            context=ctx,
        )
        with pytest.raises(ssl.SSLError):
            proxy.version()
    finally:
        # HTTPS+HTTPServer.shutdown can deadlock; close socket from a helper thread.
        threading.Thread(target=httpd.shutdown, daemon=True).start()
        httpd.server_close()


def test_live_errors_propagate(tls_bundle: _TlsBundle):
    # Nothing listening on this port
    free = socket.socket()
    free.bind(("127.0.0.1", 0))
    port = free.getsockname()[1]
    free.close()
    pin = _pin(port)
    ctx = _ssl_ctx_for_ca(tls_bundle.ca_pem)
    proxy = open_xmlrpc_proxy(
        f"https://{HOSTNAME}:{port}",
        "/xmlrpc/2/common",
        pinned=pin,
        context=ctx,
    )
    with pytest.raises(OSError):
        proxy.version()


def test_validate_still_denies_without_lab_flags(monkeypatch, tls_bundle: _TlsBundle):
    monkeypatch.delenv("ODWARD_ALLOW_PRIVATE_ODOO_URL", raising=False)
    monkeypatch.delenv("ODWARD_LAB_PROFILE", raising=False)
    httpd, port, _thr = _start_https_server(tls_bundle.cert_pem, tls_bundle.key_pem)
    try:
        with pytest.raises(DestinationPolicyError):
            validate_odoo_destination(f"https://{HOSTNAME}:{port}")
    finally:
        # HTTPS+HTTPServer.shutdown can deadlock; close socket from a helper thread.
        threading.Thread(target=httpd.shutdown, daemon=True).start()
        httpd.server_close()


def test_no_dns_on_literal_pin_path(tls_bundle: _TlsBundle):
    """PinnedDestination path must not call getaddrinfo for the hostname."""
    httpd, port, _thr = _start_https_server(tls_bundle.cert_pem, tls_bundle.key_pem)
    try:
        calls: list[str] = []

        def boom(host, *a, **k):  # noqa: ANN001
            calls.append(str(host))
            raise AssertionError("DNS must not run on pinned dial")

        set_dns_resolver(boom)
        pin = _pin(port)
        ctx = _ssl_ctx_for_ca(tls_bundle.ca_pem)
        proxy = open_xmlrpc_proxy(
            f"https://{HOSTNAME}:{port}",
            "/xmlrpc/2/common",
            pinned=pin,
            context=ctx,
        )
        assert proxy.version()["server_version"] == "17.0-test"
        assert calls == []
    finally:
        # HTTPS+HTTPServer.shutdown can deadlock; close socket from a helper thread.
        threading.Thread(target=httpd.shutdown, daemon=True).start()
        httpd.server_close()
