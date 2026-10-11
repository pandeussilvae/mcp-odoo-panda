"""PR-S1 confine: Odward Connect sidecar entrypoint never uses legacy XMLRPCHandler.

The real Docker CMD is ``python /app/run_ephemeral.py`` (infra/Dockerfile.panda).
That path must stay on ``ephemeral_odoo`` + ``safe_destination`` only.
"""

from __future__ import annotations

import ast
import importlib
import inspect
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = REPO_ROOT / "run_ephemeral.py"
LEGACY_FORBIDDEN = {
    "XMLRPCHandler",
    "HandlerFactory",
    "ConnectionPool",
    "OdooMCPServer",
    "xmlrpc_handler",
    "handler_factory",
    "connection_pool",
    "mcp_server",
}


def _collect_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            names.add(mod)
            for part in mod.split("."):
                if part:
                    names.add(part)
            for alias in node.names:
                names.add(alias.name)
    return names


def test_run_ephemeral_source_has_no_legacy_xmlrpc_imports():
    assert ENTRYPOINT.is_file(), "sidecar entrypoint missing"
    imports = _collect_imports(ENTRYPOINT)
    for forbidden in LEGACY_FORBIDDEN:
        assert forbidden not in imports, f"run_ephemeral imports legacy surface: {forbidden}"


def test_run_ephemeral_dispatch_wires_only_ephemeral_odoo():
    """Static wiring: main() imports ephemeral_dispatch_tool + run_sdk_http_server."""
    src = ENTRYPOINT.read_text(encoding="utf-8")
    assert "ephemeral_dispatch_tool" in src
    assert "run_sdk_http_server" in src
    assert "XMLRPCHandler" not in src
    assert "HandlerFactory" not in src
    assert "ConnectionPool" not in src


@pytest.mark.asyncio
async def test_entrypoint_dispatch_never_instantiates_xmlrpc_handler(monkeypatch):
    """Runtime: tool dispatch through the entrypoint closure never constructs XMLRPCHandler."""
    from odoo_mcp.core import xmlrpc_handler as xh
    from odoo_mcp.core.ephemeral_odoo import ephemeral_dispatch_tool

    created: list[object] = []
    real_init = xh.XMLRPCHandler.__init__

    def tracking_init(self, config):  # noqa: ANN001
        created.append(config)
        raise AssertionError("legacy XMLRPCHandler must not be constructed on sidecar path")

    monkeypatch.setattr(xh.XMLRPCHandler, "__init__", tracking_init)

    # Also ensure ServerProxy in the legacy module is never used.
    with patch.object(xh, "ServerProxy", side_effect=AssertionError("legacy ServerProxy")):
        conn = {
            "url": "https://8.8.8.8",
            "db": "db",
            "username": "u",
            "password": "p",
            "connect_ip": "8.8.8.8",
        }
        # Destination policy would allow the public IP; stub TCP/XML-RPC under ephemeral.
        with patch(
            "odoo_mcp.core.ephemeral_odoo._xmlrpc_execute_kw",
            return_value=0,
        ):
            out = await ephemeral_dispatch_tool(
                conn, "odoo.search_count", {"model": "res.partner", "domain": []}
            )
            assert out == 0

    assert created == []
    del real_init  # monkeypatch restores __init__


def test_ephemeral_module_does_not_import_xmlrpc_handler():
    import odoo_mcp.core.ephemeral_odoo as eph

    src = inspect.getsource(eph)
    assert "xmlrpc_handler" not in src
    assert "XMLRPCHandler" not in src
    imports = _collect_imports(Path(inspect.getfile(eph)))
    assert "xmlrpc_handler" not in imports
    assert "XMLRPCHandler" not in imports


def test_mcp_sdk_server_connection_overlay_does_not_touch_pool():
    from odoo_mcp.core import mcp_sdk_server as sdk

    src = Path(inspect.getfile(sdk)).read_text(encoding="utf-8")
    assert "XMLRPCHandler" not in src
    assert "ConnectionPool" not in src
    assert "HandlerFactory" not in src


def test_reimport_entrypoint_module_graph_excludes_legacy_handlers():
    """Importing the entrypoint helpers must not load xmlrpc_handler."""
    # Fresh-ish check: xmlrpc_handler may already be loaded by other tests; assert
    # the live dispatch import graph from run_ephemeral source AST instead.
    tree = ast.parse(ENTRYPOINT.read_text(encoding="utf-8"))
    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)
        elif isinstance(node, ast.Import):
            imported_modules.extend(a.name for a in node.names)
    assert "odoo_mcp.core.ephemeral_odoo" in imported_modules
    assert "odoo_mcp.core.mcp_sdk_server" in imported_modules
    assert not any("xmlrpc_handler" in m for m in imported_modules)
    assert not any("connection_pool" in m for m in imported_modules)
    assert not any("mcp_server" in m for m in imported_modules)


def test_dockerfile_panda_cmd_is_run_ephemeral():
    """When built from Odward Connect, Dockerfile.panda must CMD run_ephemeral.

    This test is skipped when the panda repo is checked out alone without the
    parent Odward Connect tree; CI for Odward vendor runs with parent present.
    """
    dockerfile = REPO_ROOT.parents[1] / "infra" / "Dockerfile.panda"
    if not dockerfile.is_file():
        # Standalone panda clone (GitHub PR CI) — assert entrypoint file exists.
        assert ENTRYPOINT.is_file()
        pytest.skip("parent Odward Connect Dockerfile.panda not in tree")
    text = dockerfile.read_text(encoding="utf-8")
    assert "run_ephemeral.py" in text
    assert "CMD" in text
    assert "mcp_server" not in text
