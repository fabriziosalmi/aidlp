import base64
import logging

import pytest
from unittest.mock import patch
from mitmproxy.test import tflow

from src.proxy_core import (
    AUTH_REALM,
    PROXY_AUTH_HEADER,
    DLPAddon,
    credential_matches,
    is_loopback_host,
)

TOKEN = "s3cret-token"


@pytest.fixture
def addon():
    """A DLPAddon with the heavy engine mocked out."""
    with patch("src.proxy_core.DLPEngine") as MockEngine:
        engine = MockEngine.return_value

        async def redact(text, request_id="unknown"):
            return text, {}

        engine.redact = redact
        # The health probe now consults real subsystem state.
        engine.health_report = lambda: (True, {"terms_loaded": True})
        yield DLPAddon()


def _flow(header=None, path="/v1/chat", method="POST", content=b"hello"):
    flow = tflow.tflow()
    flow.request.method = method
    flow.request.path = path
    flow.request.headers["Content-Type"] = "text/plain"
    flow.request.content = content
    if header is not None:
        flow.request.headers[PROXY_AUTH_HEADER] = header
    return flow


def _basic(user, password):
    raw = f"{user}:{password}".encode()
    return "Basic " + base64.b64encode(raw).decode()


# --- pure helpers ---------------------------------------------------------


@pytest.mark.parametrize(
    "host,expected",
    [
        ("127.0.0.1", True),
        ("::1", True),
        ("localhost", True),
        ("127.0.0.53", True),
        ("0.0.0.0", False),
        ("", False),  # mitmproxy's "every interface"
        ("192.168.1.10", False),
        ("proxy.internal", False),  # unresolvable name: assume routable
    ],
)
def test_is_loopback_host(host, expected):
    assert is_loopback_host(host) is expected


@pytest.mark.parametrize(
    "header,expected",
    [
        (f"Bearer {TOKEN}", True),
        (f"bearer {TOKEN}", True),
        (_basic("anyone", TOKEN), True),
        (f"Bearer {TOKEN}x", False),
        (_basic("anyone", "wrong"), False),
        ("Bearer", False),
        ("", False),
        ("Basic !!!not-base64!!!", False),
        ("Basic " + base64.b64encode(b"nocolon").decode(), False),
        (f"Digest {TOKEN}", False),
    ],
)
def test_credential_matches(header, expected):
    assert credential_matches(header, TOKEN) is expected


def test_credential_never_matches_without_a_token():
    assert credential_matches("Bearer ", "") is False
    assert credential_matches(_basic("u", ""), "") is False


# --- bind policy ----------------------------------------------------------


def test_loopback_without_token_is_allowed_but_warns(addon, caplog):
    addon.auth_token = None
    with caplog.at_level(logging.WARNING, logger="dlp_proxy"):
        addon.apply_bind_policy("127.0.0.1")

    assert addon.auth_required is False
    assert addon.deny_all is False
    assert "No proxy.auth_token is set" in caplog.text


def test_routable_bind_without_token_refuses_to_relay(addon, caplog):
    """An unauthenticated listener on a routable interface is an open relay."""
    addon.auth_token = None
    with caplog.at_level(logging.CRITICAL, logger="dlp_proxy"):
        addon.apply_bind_policy("0.0.0.0")

    assert addon.deny_all is True
    assert "Refusing to relay" in caplog.text


def test_token_lifts_the_routable_bind_refusal(addon):
    addon.auth_token = TOKEN
    addon.apply_bind_policy("0.0.0.0")

    assert addon.auth_required is True
    assert addon.deny_all is False


# --- enforcement on the data path ----------------------------------------


@pytest.mark.asyncio
async def test_open_relay_is_refused_with_403(addon):
    """Fallback path: mitmproxy normally exits on the CRITICAL log first.

    This covers the case where the addon runs anyway -- nothing may be
    relayed for a caller we cannot identify.
    """
    addon.auth_token = None
    addon.apply_bind_policy("0.0.0.0")

    flow = _flow()
    await addon.request(flow)

    assert flow.response is not None
    assert flow.response.status_code == 403
    assert b"proxy_misconfigured" in flow.response.content


@pytest.mark.asyncio
async def test_missing_credentials_get_407(addon):
    addon.auth_token = TOKEN
    addon.apply_bind_policy("0.0.0.0")

    flow = _flow()
    await addon.request(flow)

    assert flow.response.status_code == 407
    assert flow.response.headers["Proxy-Authenticate"] == AUTH_REALM


@pytest.mark.asyncio
async def test_wrong_credentials_get_407(addon):
    addon.auth_token = TOKEN
    addon.apply_bind_policy("0.0.0.0")

    flow = _flow(header=f"Bearer {TOKEN}-nope")
    await addon.request(flow)

    assert flow.response.status_code == 407


@pytest.mark.asyncio
@pytest.mark.parametrize("header", [f"Bearer {TOKEN}", _basic("anyone", TOKEN)])
async def test_valid_credentials_are_forwarded_and_stripped(addon, header):
    """The proxy's own credential must never reach the upstream."""
    addon.auth_token = TOKEN
    addon.apply_bind_policy("0.0.0.0")

    flow = _flow(header=header)
    await addon.request(flow)

    assert flow.response is None  # not answered by us; goes upstream
    assert PROXY_AUTH_HEADER not in flow.request.headers


@pytest.mark.asyncio
async def test_health_probe_stays_reachable_without_credentials(addon):
    """Container health checks run without credentials and reveal nothing."""
    addon.auth_token = TOKEN
    addon.apply_bind_policy("0.0.0.0")

    flow = _flow(path="/_health", method="GET", content=b"")
    await addon.request(flow)

    assert flow.response.status_code in (200, 503)


def test_connect_is_authorised_before_the_tunnel_exists(addon):
    """Checking only in request() would let the tunnel open first."""
    addon.auth_token = TOKEN
    addon.apply_bind_policy("0.0.0.0")

    flow = _flow(method="CONNECT")
    addon.http_connect(flow)

    assert flow.response.status_code == 407


def test_connect_passes_with_valid_credentials(addon):
    addon.auth_token = TOKEN
    addon.apply_bind_policy("0.0.0.0")

    flow = _flow(method="CONNECT", header=f"Bearer {TOKEN}")
    addon.http_connect(flow)

    assert flow.response is None


# --- metrics listener -----------------------------------------------------


def test_metrics_server_binds_its_configured_host():
    """The Prometheus endpoint is unauthenticated; it must not default wide.

    Starting it moved out of DLPAddon.__init__ into the composition root, so
    building the addon no longer has network side effects.
    """
    from src.proxy_core import build_addon

    with patch("src.proxy_core.DLPEngine"), patch(
        "src.proxy_core.start_http_server"
    ) as start:
        build_addon()

    _, kwargs = start.call_args
    assert kwargs["addr"] == "127.0.0.1"
