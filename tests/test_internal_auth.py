"""PR-S1 hardening: gateway↔panda service-to-service auth."""

from __future__ import annotations

import secrets

import pytest
from starlette.testclient import TestClient

from odoo_mcp.core import internal_auth as ia
from odoo_mcp.core.mcp_sdk_server import build_asgi_app


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in (
        "ODWARD_INTERNAL_TOKEN",
        "ODWARD_REQUIRE_INTERNAL_AUTH",
        "ODWARD_DEPLOYMENT",
    ):
        monkeypatch.delenv(key, raising=False)
    yield


def _token() -> str:
    return secrets.token_hex(32)


async def _noop_dispatch(name, arguments, connection):  # noqa: ANN001
    return {"ok": True, "name": name}


def test_compare_digest_accepts_matching_token():
    t = _token()
    assert ia.verify_internal_token(t, t) is True


def test_compare_digest_rejects_wrong_token():
    assert ia.verify_internal_token(_token(), _token()) is False


def test_compare_digest_rejects_empty():
    t = _token()
    assert ia.verify_internal_token("", t) is False
    assert ia.verify_internal_token(None, t) is False
    assert ia.verify_internal_token(t, "") is False


def test_boot_fail_closed_when_missing(monkeypatch):
    monkeypatch.setenv("ODWARD_REQUIRE_INTERNAL_AUTH", "1")
    with pytest.raises(RuntimeError, match="misconfigured"):
        ia.assert_internal_auth_boot(require=True)


def test_boot_fail_closed_when_too_short(monkeypatch):
    monkeypatch.setenv("ODWARD_INTERNAL_TOKEN", "too-short")
    monkeypatch.setenv("ODWARD_REQUIRE_INTERNAL_AUTH", "1")
    with pytest.raises(RuntimeError, match="misconfigured"):
        ia.assert_internal_auth_boot(require=True)


def test_boot_fail_closed_in_production(monkeypatch):
    monkeypatch.setenv("ODWARD_DEPLOYMENT", "production")
    with pytest.raises(RuntimeError, match="misconfigured"):
        ia.assert_internal_auth_boot(require=False)


def test_boot_ok_with_strong_token(monkeypatch):
    t = _token()
    monkeypatch.setenv("ODWARD_INTERNAL_TOKEN", t)
    monkeypatch.setenv("ODWARD_REQUIRE_INTERNAL_AUTH", "1")
    assert ia.assert_internal_auth_boot(require=True) == t


def test_asgi_rejects_missing_token(monkeypatch):
    t = _token()
    monkeypatch.setenv("ODWARD_INTERNAL_TOKEN", t)
    monkeypatch.setenv("ODWARD_REQUIRE_INTERNAL_AUTH", "1")
    app = build_asgi_app(dispatch_tool=_noop_dispatch, require_internal_auth=True)
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 401
    body = resp.text
    assert t not in body
    assert "unauthorized" in body


def test_asgi_rejects_wrong_token(monkeypatch):
    t = _token()
    monkeypatch.setenv("ODWARD_INTERNAL_TOKEN", t)
    monkeypatch.setenv("ODWARD_REQUIRE_INTERNAL_AUTH", "1")
    app = build_asgi_app(dispatch_tool=_noop_dispatch, require_internal_auth=True)
    client = TestClient(app)
    resp = client.get(
        "/health",
        headers={ia.HEADER_INTERNAL_TOKEN: _token()},
    )
    assert resp.status_code == 401
    assert t not in resp.text


def test_asgi_accepts_valid_token_on_health(monkeypatch):
    t = _token()
    monkeypatch.setenv("ODWARD_INTERNAL_TOKEN", t)
    monkeypatch.setenv("ODWARD_REQUIRE_INTERNAL_AUTH", "1")
    app = build_asgi_app(dispatch_tool=_noop_dispatch, require_internal_auth=True)
    client = TestClient(app)
    h = {ia.HEADER_INTERNAL_TOKEN: t}
    health = client.get("/health", headers=h)
    assert health.status_code == 200
    assert health.json()["ok"] is True
    assert t not in health.text


def test_asgi_mcp_path_requires_token(monkeypatch):
    """Entire surface including /mcp is gated (401 before SDK session)."""
    t = _token()
    monkeypatch.setenv("ODWARD_INTERNAL_TOKEN", t)
    monkeypatch.setenv("ODWARD_REQUIRE_INTERNAL_AUTH", "1")
    app = build_asgi_app(dispatch_tool=_noop_dispatch, require_internal_auth=True)
    client = TestClient(app)
    mcp = client.post("/mcp", headers={"content-type": "application/json"}, content=b"{}")
    assert mcp.status_code == 401
    assert t not in mcp.text


def test_response_never_echoes_token(monkeypatch):
    t = _token()
    monkeypatch.setenv("ODWARD_INTERNAL_TOKEN", t)
    monkeypatch.setenv("ODWARD_REQUIRE_INTERNAL_AUTH", "1")
    app = build_asgi_app(dispatch_tool=_noop_dispatch, require_internal_auth=True)
    client = TestClient(app)
    resp = client.get("/health", headers={ia.HEADER_INTERNAL_TOKEN: t})
    assert t not in resp.text
    assert ia.HEADER_INTERNAL_TOKEN.lower() not in {k.lower() for k in resp.headers}
