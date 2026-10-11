"""PR-S1 confine: authenticity/integrity of X-Odoo-Connect-Ip on panda.

Panda accepts ``X-Odoo-Connect-Ip`` from whoever can reach the HTTP port.
Integrity against SSRF still depends on ``pin_from_url_and_ip`` classification
plus TLS hostname verify. Authenticity (who may set the header) is a trust
boundary: Odward Connect gateway must be the only caller on the internal mesh.
"""

from __future__ import annotations

import socket
from unittest.mock import patch

import pytest

from odoo_mcp.core import ephemeral_odoo as eph
from odoo_mcp.core.mcp_sdk_server import connection_from_headers
from odoo_mcp.core.safe_destination import (
    DestinationPolicyError,
    pin_from_url_and_ip,
    set_dns_resolver,
)


@pytest.fixture(autouse=True)
def _reset_dns(monkeypatch):
    set_dns_resolver(None)
    for key in (
        "ODWARD_ALLOW_PRIVATE_ODOO_URL",
        "ODWARD_ALLOW_HTTP_ODOO_URL",
        "ODWARD_LAB_PROFILE",
        "ODWARD_DEPLOYMENT",
    ):
        monkeypatch.delenv(key, raising=False)
    yield
    set_dns_resolver(None)


def test_connection_from_headers_captures_connect_ip():
    headers = {
        "X-Odoo-Url": "https://odoo.example",
        "X-Odoo-Db": "db",
        "X-Odoo-User": "u",
        "X-Odoo-Password": "p",
        "X-Odoo-Connect-Ip": "8.8.8.8",
    }
    conn = connection_from_headers(headers)
    assert conn is not None
    assert conn["connect_ip"] == "8.8.8.8"


def test_pin_from_url_and_ip_denies_private_connect_ip():
    with pytest.raises(DestinationPolicyError, match="address_denied"):
        pin_from_url_and_ip("https://odoo.example", "10.0.0.5")


def test_pin_from_url_and_ip_denies_metadata_connect_ip():
    with pytest.raises(DestinationPolicyError, match="address_denied"):
        pin_from_url_and_ip("https://odoo.example", "169.254.169.254")


def test_pin_from_url_and_ip_denies_loopback_connect_ip():
    with pytest.raises(DestinationPolicyError, match="address_denied"):
        pin_from_url_and_ip("https://odoo.example", "127.0.0.1")


def test_pin_from_url_and_ip_denies_invalid_connect_ip():
    with pytest.raises(DestinationPolicyError, match="invalid_connect_ip"):
        pin_from_url_and_ip("https://odoo.example", "not-an-ip")


def test_pin_from_url_and_ip_denies_empty_connect_ip():
    with pytest.raises(DestinationPolicyError, match="empty_connect_ip"):
        pin_from_url_and_ip("https://odoo.example", "  ")


def test_forged_private_connect_ip_never_opens_tcp():
    """Direct sidecar call with private connect_ip must fail before TCP."""
    connected: list[tuple] = []

    def fake_create_connection(address, timeout=None):  # noqa: ANN001
        connected.append(address)
        raise AssertionError("TCP must not open for denied connect_ip")

    with patch(
        "odoo_mcp.core.safe_destination.socket.create_connection",
        side_effect=fake_create_connection,
    ):
        with pytest.raises(DestinationPolicyError):
            eph._xmlrpc_execute_kw(
                url="https://victim.example",
                db="db",
                username="u",
                password="p",
                model="res.partner",
                method="search_count",
                args=[[]],
                connect_ip="10.9.9.9",
            )
    assert connected == []


def test_public_connect_ip_dials_pin_not_hostname_dns():
    """Trusted pin dials the supplied public IP; DNS for hostname is not required."""
    def boom_dns(*_a, **_k):
        raise socket.gaierror(socket.EAI_NONAME, "must not resolve")

    set_dns_resolver(boom_dns)
    connected: list[tuple] = []

    def fake_create_connection(address, timeout=None):  # noqa: ANN001
        connected.append(address)
        raise OSError("captured")

    with patch(
        "odoo_mcp.core.safe_destination.socket.create_connection",
        side_effect=fake_create_connection,
    ):
        with pytest.raises(OSError, match="captured"):
            eph._xmlrpc_execute_kw(
                url="https://victim.example",
                db="db",
                username="u",
                password="p",
                model="res.partner",
                method="search_count",
                args=[[]],
                connect_ip="1.1.1.1",
            )
    assert connected[0][0] == "1.1.1.1"


def test_url_hostname_kept_for_tls_when_connect_ip_differs():
    """Pairing a public IP with a hostname still binds TLS/SNI to the hostname.

    Arbitrary public IP+URL pairing is possible if the caller can reach panda;
    certificate verification (hostname) remains the integrity control for TLS.
    """
    pin = pin_from_url_and_ip("https://odoo.example", "8.8.4.4")
    assert pin.hostname == "odoo.example"
    assert pin.ip == "8.8.4.4"
    assert pin.scheme == "https"
