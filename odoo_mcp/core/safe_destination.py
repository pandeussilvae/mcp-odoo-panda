"""Destination policy + IP-pinned XML-RPC/HTTP for ephemeral Odoo calls (anti-SSRF).

Standalone (no Odward imports). Fail-closed. Lab exceptions use ODWARD_* env flags
when this server runs under Odward Connect; defaults deny private/HTTP.
"""

from __future__ import annotations

import http.client
import ipaddress
import logging
import os
import socket
import ssl
import xmlrpc.client
from dataclasses import dataclass
from enum import Enum
from typing import Callable
from urllib.parse import urlparse, urlunparse
from urllib.request import OpenerDirector, ProxyHandler, Request, build_opener

logger = logging.getLogger(__name__)

# Cloud metadata / link-local (IMDSv1 classic + IPv6).
_METADATA_V4 = ipaddress.ip_address("169.254.169.254")
_METADATA_V6 = ipaddress.ip_address("fd00:ec2::254")

# Overridable in tests (deterministic DNS).
ResolveFn = Callable[[str, int | None, int, int, int], list]
_resolve_fn: ResolveFn = socket.getaddrinfo


class DestinationClass(str, Enum):
    PUBLIC = "public"
    LOOPBACK = "loopback"
    PRIVATE = "private"
    LINK_LOCAL = "link_local"
    MULTICAST = "multicast"
    UNSPECIFIED = "unspecified"
    METADATA = "metadata"
    OTHER = "other"


class DestinationPolicyError(ValueError):
    """URL / destination rejected by anti-SSRF policy (safe for bind mapping)."""

    def __init__(self, reason: str = "destination_denied"):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class PinnedAddr:
    ip: str
    family: int  # socket.AF_INET / AF_INET6
    classification: DestinationClass


@dataclass(frozen=True)
class PinnedDestination:
    """Validated destination: TCP must use ``ip``; TLS name is ``hostname``."""

    url: str  # canonical URL without trailing path noise (scheme://host[:port])
    hostname: str  # original hostname (IDNA ASCII)
    port: int
    scheme: str  # http | https
    ip: str
    family: int
    classification: DestinationClass

    @property
    def base_url(self) -> str:
        return self.url.rstrip("/")


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def allow_private_odoo_url() -> bool:
    return _env_flag("ODWARD_ALLOW_PRIVATE_ODOO_URL")


def allow_http_odoo_url() -> bool:
    return _env_flag("ODWARD_ALLOW_HTTP_ODOO_URL")


def lab_profile_enabled() -> bool:
    return _env_flag("ODWARD_LAB_PROFILE")


def deployment_is_production() -> bool:
    return os.getenv("ODWARD_DEPLOYMENT", "").strip().lower() in {"production", "prod"}


def assert_ssrf_lab_flags_allowed() -> None:
    """Refuse process start when lab SSRF exceptions are active in production.

    Lab flags also require ODWARD_LAB_PROFILE=1 outside production so a stray
    env cannot silently weaken SaaS.
    """
    private = allow_private_odoo_url()
    http = allow_http_odoo_url()
    if not private and not http:
        return
    if deployment_is_production():
        raise RuntimeError(
            "ODWARD_ALLOW_PRIVATE_ODOO_URL / ODWARD_ALLOW_HTTP_ODOO_URL are forbidden "
            "when ODWARD_DEPLOYMENT is production/prod."
        )
    if not lab_profile_enabled():
        raise RuntimeError(
            "ODWARD_ALLOW_PRIVATE_ODOO_URL / ODWARD_ALLOW_HTTP_ODOO_URL require "
            "ODWARD_LAB_PROFILE=1 (isolated lab only)."
        )


def set_dns_resolver(fn: ResolveFn | None) -> ResolveFn:
    """Install a test DNS resolver; pass None to restore socket.getaddrinfo."""
    global _resolve_fn
    previous = _resolve_fn
    _resolve_fn = socket.getaddrinfo if fn is None else fn
    return previous


def classify_ip(ip: str | ipaddress.IPv4Address | ipaddress.IPv6Address) -> DestinationClass:
    """Classify one IP. IPv4-mapped IPv6 uses the embedded IPv4 classification."""
    addr = ipaddress.ip_address(ip)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        return classify_ip(addr.ipv4_mapped)

    if addr == _METADATA_V4 or addr == _METADATA_V6:
        return DestinationClass.METADATA
    if addr.is_loopback:
        return DestinationClass.LOOPBACK
    if addr.is_unspecified:
        return DestinationClass.UNSPECIFIED
    if addr.is_multicast:
        return DestinationClass.MULTICAST
    if addr.is_link_local:
        return DestinationClass.LINK_LOCAL
    # AWS/GCP metadata sits in 169.254.0.0/16 (link-local); already covered.
    if addr.is_private:
        return DestinationClass.PRIVATE
    if addr.is_reserved or addr.is_global is False:
        # Carrier-grade NAT, documentation, etc. — fail closed.
        if not addr.is_global:
            return DestinationClass.OTHER
    if addr.is_global:
        return DestinationClass.PUBLIC
    return DestinationClass.OTHER


def _is_allowed_class(cls: DestinationClass, *, allow_private: bool) -> bool:
    if cls == DestinationClass.PUBLIC:
        return True
    if allow_private and cls in {
        DestinationClass.PRIVATE,
        DestinationClass.LOOPBACK,
        DestinationClass.LINK_LOCAL,
    }:
        # Lab mesh may use private/loopback/link-local hostnames — never metadata.
        return True
    return False


def parse_odoo_destination(url: str, *, allow_http: bool | None = None) -> tuple[str, str, int, str]:
    """Parse + canonicalize. Returns (canonical_base_url, hostname, port, scheme)."""
    raw = (url or "").strip()
    if not raw:
        raise DestinationPolicyError("empty_host")
    if "://" not in raw:
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").lower()
    if scheme not in {"http", "https"}:
        raise DestinationPolicyError("non_http_scheme")
    allow_http_eff = allow_http_odoo_url() if allow_http is None else allow_http
    if scheme == "http" and not allow_http_eff:
        raise DestinationPolicyError("http_denied")
    if parsed.username is not None or parsed.password is not None:
        raise DestinationPolicyError("userinfo_denied")
    host = parsed.hostname
    if not host:
        raise DestinationPolicyError("empty_host")
    # IDNA: reject broken hosts; normalize unicode.
    try:
        hostname = host.encode("idna").decode("ascii").lower()
    except (UnicodeError, UnicodeDecodeError) as exc:
        raise DestinationPolicyError("invalid_host") from exc
    if scheme == "https":
        port = int(parsed.port or 443)
    else:
        port = int(parsed.port or 80)
    if port <= 0 or port > 65535:
        raise DestinationPolicyError("invalid_port")
    netloc = hostname if (scheme == "https" and port == 443) or (scheme == "http" and port == 80) else f"{hostname}:{port}"
    canonical = urlunparse((scheme, netloc, "", "", "", ""))
    return canonical, hostname, port, scheme


def resolve_odoo_destination(hostname: str) -> list[PinnedAddr]:
    """Resolve A/AAAA for hostname. Empty list on failure (caller fail-closed)."""
    host = (hostname or "").strip().lower()
    if not host:
        return []
    # Literal IP — no DNS.
    try:
        ipaddress.ip_address(host.strip("[]"))
        lit = host.strip("[]")
        family = socket.AF_INET6 if ":" in lit else socket.AF_INET
        return [PinnedAddr(ip=lit, family=family, classification=classify_ip(lit))]
    except ValueError:
        pass
    try:
        infos = _resolve_fn(host, None, socket.AF_UNSPEC, socket.SOCK_STREAM, 0)
    except OSError:
        return []
    seen: set[str] = set()
    out: list[PinnedAddr] = []
    for family, _type, _proto, _canon, sockaddr in infos:
        if family not in (socket.AF_INET, socket.AF_INET6):
            continue
        ip = sockaddr[0]
        if ip in seen:
            continue
        seen.add(ip)
        out.append(PinnedAddr(ip=ip, family=family, classification=classify_ip(ip)))
    return out


def validate_odoo_destination(
    url: str,
    *,
    allow_private: bool | None = None,
    allow_http: bool | None = None,
) -> PinnedDestination:
    """Orchestrate parse → resolve → classify (fail-closed) → pin one allowed addr."""
    allow_private_eff = allow_private_odoo_url() if allow_private is None else allow_private
    canonical, hostname, port, scheme = parse_odoo_destination(url, allow_http=allow_http)

    # Literal IP in URL host.
    addrs = resolve_odoo_destination(hostname)
    if not addrs:
        raise DestinationPolicyError("dns_failed")

    # Fail-closed rebinding: any disallowed address ⇒ deny (unless all allowed).
    disallowed = [a for a in addrs if not _is_allowed_class(a.classification, allow_private=allow_private_eff)]
    if disallowed:
        raise DestinationPolicyError("address_denied")

    allowed = [a for a in addrs if _is_allowed_class(a.classification, allow_private=allow_private_eff)]
    if not allowed:
        raise DestinationPolicyError("address_denied")

    # Prefer IPv4 for broader reachability; stable order.
    allowed.sort(key=lambda a: (0 if a.family == socket.AF_INET else 1, a.ip))
    pick = allowed[0]
    return PinnedDestination(
        url=canonical,
        hostname=hostname,
        port=port,
        scheme=scheme,
        ip=pick.ip,
        family=pick.family,
        classification=pick.classification,
    )


def assert_redirect_allowed(from_pin: PinnedDestination, location: str) -> PinnedDestination:
    """Re-validate redirect Location against the same policy."""
    if not location or not str(location).strip():
        raise DestinationPolicyError("redirect_denied")
    loc = str(location).strip()
    if loc.startswith("/"):
        # Same-origin relative — rebuild with pinned host.
        loc = f"{from_pin.scheme}://{from_pin.hostname}:{from_pin.port}{loc}"
    return validate_odoo_destination(loc)


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, pinned: PinnedDestination, timeout: float):
        # Host header / logical host stays on original hostname.
        super().__init__(pinned.hostname, pinned.port, timeout=timeout)
        self._pinned = pinned

    def connect(self) -> None:
        self.sock = socket.create_connection((self._pinned.ip, self._pinned.port), self.timeout)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, pinned: PinnedDestination, timeout: float, context: ssl.SSLContext):
        super().__init__(
            pinned.hostname,
            pinned.port,
            timeout=timeout,
            context=context,
        )
        self._pinned = pinned
        self._ssl_context = context

    def connect(self) -> None:
        raw = socket.create_connection((self._pinned.ip, self._pinned.port), self.timeout)
        # SNI + cert verify on original hostname (not the pinned IP).
        self.sock = self._ssl_context.wrap_socket(raw, server_hostname=self._pinned.hostname)


class PinnedXMLRPCTransport(xmlrpc.client.Transport):
    """HTTP XML-RPC transport that dials the pinned IP only."""

    def __init__(self, pinned: PinnedDestination, timeout: float = 25.0):
        super().__init__(use_datetime=False, use_builtin_types=True)
        self._pinned = pinned
        self._timeout = max(0.5, float(timeout))

    def set_timeout(self, timeout: float) -> None:
        self._timeout = max(0.5, float(timeout))
        conn = getattr(self, "_connection", None)
        if isinstance(conn, tuple) and len(conn) >= 2 and conn[1] is not None:
            conn[1].timeout = self._timeout
            sock = getattr(conn[1], "sock", None)
            if sock is not None:
                sock.settimeout(self._timeout)

    def make_connection(self, host):  # noqa: ANN001 — xmlrpc API
        if self._connection and host == self._connection[0]:
            return self._connection[1]
        conn = _PinnedHTTPConnection(self._pinned, self._timeout)
        self._connection = host, conn
        return conn


class PinnedXMLRPCSafeTransport(xmlrpc.client.SafeTransport):
    """HTTPS XML-RPC: TCP to pinned IP, TLS SNI/verify on original hostname."""

    def __init__(self, pinned: PinnedDestination, timeout: float = 25.0, *, context: ssl.SSLContext | None = None):
        super().__init__(use_datetime=False, use_builtin_types=True)
        self._pinned = pinned
        self._timeout = max(0.5, float(timeout))
        self.context = context or ssl.create_default_context()

    def set_timeout(self, timeout: float) -> None:
        self._timeout = max(0.5, float(timeout))
        conn = getattr(self, "_connection", None)
        if isinstance(conn, tuple) and len(conn) >= 2 and conn[1] is not None:
            conn[1].timeout = self._timeout
            sock = getattr(conn[1], "sock", None)
            if sock is not None:
                sock.settimeout(self._timeout)

    def make_connection(self, host):  # noqa: ANN001 — xmlrpc API
        if self._connection and host == self._connection[0]:
            return self._connection[1]
        conn = _PinnedHTTPSConnection(self._pinned, self._timeout, self.context)
        self._connection = host, conn
        return conn


def open_xmlrpc_transport(
    pinned: PinnedDestination,
    *,
    timeout: float = 25.0,
    context: ssl.SSLContext | None = None,
) -> xmlrpc.client.Transport:
    if pinned.scheme == "http":
        return PinnedXMLRPCTransport(pinned, timeout=timeout)
    return PinnedXMLRPCSafeTransport(pinned, timeout=timeout, context=context)


def open_xmlrpc_proxy(
    url: str,
    path: str,
    *,
    timeout: float = 25.0,
    pinned: PinnedDestination | None = None,
    context: ssl.SSLContext | None = None,
) -> xmlrpc.client.ServerProxy:
    """ServerProxy with destination policy + IP-pinned transport (no second DNS)."""
    pin = pinned or validate_odoo_destination(url)
    transport = open_xmlrpc_transport(pin, timeout=timeout, context=context)
    return xmlrpc.client.ServerProxy(f"{pin.base_url}{path}", allow_none=True, transport=transport)


def _refuse_redirects():
    from urllib.request import HTTPRedirectHandler

    class _NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
            raise DestinationPolicyError("redirect_denied")

    return _NoRedirect


def pinned_urlopen(
    url: str,
    data: bytes | None = None,
    *,
    headers: dict[str, str] | None = None,
    method: str = "GET",
    timeout: float = 30.0,
    pinned: PinnedDestination | None = None,
    context: ssl.SSLContext | None = None,
):
    """HTTP(S) request to a validated destination; ignores env proxy vars; no redirects."""
    import urllib.request

    pin = pinned or validate_odoo_destination(url)
    req = Request(url, data=data, headers=headers or {}, method=method)
    proxy = ProxyHandler({})  # empty → ignore HTTP(S)_PROXY / ALL_PROXY / NO_PROXY

    class _PinnedHTTPHandler(urllib.request.HTTPHandler):
        def http_open(self, req):  # noqa: ANN001
            return self.do_open(lambda *a, **k: _PinnedHTTPConnection(pin, timeout), req)

    class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
        def __init__(self):
            ctx = context or ssl.create_default_context()
            super().__init__(context=ctx)

        def https_open(self, req):  # noqa: ANN001
            ctx = context or ssl.create_default_context()

            def _factory(*_a, **_k):
                return _PinnedHTTPSConnection(pin, timeout, ctx)

            return self.do_open(_factory, req)

    opener: OpenerDirector = build_opener(
        proxy, _refuse_redirects(), _PinnedHTTPHandler(), _PinnedHTTPSHandler()
    )
    return opener.open(req, timeout=timeout)




def pin_from_url_and_ip(url: str, connect_ip: str, *, allow_private: bool | None = None, allow_http: bool | None = None) -> PinnedDestination:
    """Pin TCP to ``connect_ip`` after classifying it; hostname/TLS from ``url``.

    Used when a trusted upstream (Odward gateway) already validated and pinned.
    Still fail-closed: the supplied IP must itself be an allowed class.
    """
    allow_private_eff = allow_private_odoo_url() if allow_private is None else allow_private
    canonical, hostname, port, scheme = parse_odoo_destination(url, allow_http=allow_http)
    ip = (connect_ip or "").strip().strip("[]")
    if not ip:
        raise DestinationPolicyError("empty_connect_ip")
    try:
        ipaddress.ip_address(ip)
    except ValueError as exc:
        raise DestinationPolicyError("invalid_connect_ip") from exc
    cls = classify_ip(ip)
    if not _is_allowed_class(cls, allow_private=allow_private_eff):
        raise DestinationPolicyError("address_denied")
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    return PinnedDestination(
        url=canonical,
        hostname=hostname,
        port=port,
        scheme=scheme,
        ip=ip,
        family=family,
        classification=cls,
    )

def public_bind_message(exc: DestinationPolicyError) -> str:
    """Italian GUI-safe message — no internal IPs or classification details."""
    return "Questo indirizzo Odoo non è consentito. Usa un URL HTTPS pubblico valido."
