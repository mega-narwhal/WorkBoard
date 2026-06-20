"""Security tests for serve.BoardHandler._csrf_ok — the CSRF / DNS-rebinding guard.

The guard protects state-changing POSTs on a loopback server from cross-site
browser writes. These tests pin the security contract: same-origin browser POSTs
and tokenless local CLI writers are allowed; classic CSRF, DNS-rebinding, and
port-mismatch attempts are blocked.

The handler is built WITHOUT __init__ (object.__new__) and given a plain-dict
.headers (HTTPMessage.get is dict-like for our purposes). bind_host / auth_token
are CLASS attributes on BoardHandler, so each test resets them via the fixture.
"""
import pytest

import serve


@pytest.fixture(autouse=True)
def reset_class_attrs():
    """Reset the mutable class-level config the guard reads, before AND after
    each test, so cross-test leakage can't mask a regression."""
    saved_bind = serve.BoardHandler.bind_host
    saved_token = serve.BoardHandler.auth_token
    serve.BoardHandler.bind_host = "127.0.0.1"
    serve.BoardHandler.auth_token = None
    yield
    serve.BoardHandler.bind_host = saved_bind
    serve.BoardHandler.auth_token = saved_token


def csrf_ok(headers, *, bind_host="127.0.0.1", auth_token=None):
    """Run the real _csrf_ok against a minimal hand-built handler."""
    h = object.__new__(serve.BoardHandler)
    h.headers = dict(headers)
    serve.BoardHandler.bind_host = bind_host
    serve.BoardHandler.auth_token = auth_token
    return serve.BoardHandler._csrf_ok(h)


# ---------------------------------------------------------------------------
# ALLOW — legitimate writers
# ---------------------------------------------------------------------------

def test_csrf_allows_local_cli_no_origin():
    # card.py / hooks use urllib and send NO Origin; Host is loopback.
    assert csrf_ok({"Host": "127.0.0.1:7891"}) is True


def test_csrf_allows_same_origin_board_page():
    # The board page POSTs carry Origin == Host (loopback) -> allowed.
    assert csrf_ok({"Host": "127.0.0.1:7891",
                    "Origin": "http://127.0.0.1:7891"}) is True


def test_csrf_allows_localhost_and_ipv6_same_origin():
    # localhost and [::1] are recognised loopback authorities.
    assert csrf_ok({"Host": "localhost:7891",
                    "Origin": "http://localhost:7891"}) is True
    assert csrf_ok({"Host": "[::1]:7891",
                    "Origin": "http://[::1]:7891"},
                   bind_host="::1") is True


def test_csrf_allows_no_host_no_origin_http10():
    # HTTP/1.0 client with neither Host nor Origin -> not a browser CSRF, allow.
    assert csrf_ok({}) is True


def test_csrf_allows_lan_phone_when_explicitly_bound():
    # Documented LAN/phone flow: --host 0.0.0.0 + --auth-token. Same-origin
    # LAN IP is allowed because the loopback-Host check is relaxed off-loopback.
    # (auth_token is passed only to mirror the real flow; _csrf_ok ignores it.)
    assert csrf_ok({"Host": "192.168.1.50:7891",
                    "Origin": "http://192.168.1.50:7891"},
                   bind_host="0.0.0.0", auth_token="secret") is True


# ---------------------------------------------------------------------------
# BLOCK — attacks
# ---------------------------------------------------------------------------

def test_csrf_blocks_classic_cross_site_origin():
    # Loopback Host but a foreign Origin -> classic CSRF, blocked.
    assert csrf_ok({"Host": "127.0.0.1:7891",
                    "Origin": "https://evil.example"}) is False


def test_csrf_blocks_dns_rebind_to_loopback():
    # Attacker domain resolved to 127.0.0.1: Origin == Host (passes same-origin)
    # but Host is not a loopback authority while bound to loopback -> blocked.
    assert csrf_ok({"Host": "evil.example:7891",
                    "Origin": "http://evil.example:7891"}) is False


def test_csrf_blocks_same_host_different_port():
    # Origin host matches but the port differs -> not same-origin, blocked.
    assert csrf_ok({"Host": "127.0.0.1:7891",
                    "Origin": "http://127.0.0.1:9999"}) is False


def test_csrf_blocks_evil_host_without_origin_on_loopback_bind():
    # No Origin (so same-origin check is skipped) but a rebound non-loopback
    # Host while bound to loopback is still rejected.
    assert csrf_ok({"Host": "evil.example:7891"}) is False


def test_csrf_blocks_malformed_origin():
    # An Origin that urlsplit can't parse (raises ValueError) is rejected.
    # "http://[" raises "Invalid IPv6 URL" -> the except ValueError branch -> False.
    assert csrf_ok({"Host": "127.0.0.1:7891", "Origin": "http://["}) is False
