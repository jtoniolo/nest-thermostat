"""Tests for the wire rules (PROTOCOL.md sections 2, 3, and 5)."""

import base64

import pytest
from multidict import CIMultiDict

from custom_components.nest_local.protocol import (
    advertised_origin,
    match_route,
    serial_from_request,
    server_is_newer,
)


@pytest.mark.parametrize(
    ("method", "path", "route"),
    [
        ("GET", "/entry", "entry"),
        ("POST", "/entry/", "entry"),
        ("POST", "/nest/entry", "entry"),
        ("POST", "/transport/put", "put"),
        ("POST", "/nest/transport/put", "put"),
        ("POST", "/nest/transport/v7/put", "put"),
        ("POST", "/czfe/v7/subscribe", "subscribe"),
        ("POST", "/nest/transport", "subscribe"),
        ("POST", "/transport", "subscribe"),
        ("POST", "/nest/transport/anything", "subscribe"),
        ("GET", "/nest/transport/device/02AA01AC10130C7T", "object_list"),
        ("GET", "/ping", "ping"),
        ("GET", "/passphrase", "passphrase"),
        ("GET", "/nest/pro_info/12345", "pro_info"),
        ("POST", "/upload", "upload"),
        ("GET", "/nest/weather/v1", "weather"),
        ("GET", "/info", "info"),
        ("GET", "/what", "unknown"),
        ("DELETE", "/nest/entry", "unknown"),
    ],
)
def test_match_route(method, path, route):
    """Test case 2: the paths reach the correct handler."""
    assert match_route(method, path) == route


def _basic(user: str) -> CIMultiDict:
    token = base64.b64encode(f"{user}:pw".encode()).decode()
    return CIMultiDict({"Authorization": f"Basic {token}"})


def test_serial_from_basic_auth():
    """Test case 3: the serial comes from segment 1 of the user ID."""
    headers = _basic("d.09AA01AB12345678.BC7C9039")
    assert serial_from_request(headers, {}) == "09AA01AB12345678"


def test_serial_sources_in_order():
    """Test that each source works, and that the serial is cleaned."""
    assert serial_from_request(_basic("09aa01ab12345678"), {}) == "09AA01AB12345678"
    headers = CIMultiDict({"X-nl-client-id": "d.09AA01AB12345678.x"})
    assert serial_from_request(headers, {}) == "09AA01AB12345678"
    headers = CIMultiDict({"X-nl-device-id": "09-AA01-AB12345678"})
    assert serial_from_request(headers, {}) == "09AA01AB12345678"
    headers = CIMultiDict({"X-NL-Device-Serial": "09AA01AB12345678"})
    assert serial_from_request(headers, {}) == "09AA01AB12345678"
    assert serial_from_request(CIMultiDict(), {"serial": "09AA01AB1234"}) == (
        "09AA01AB1234"
    )
    assert serial_from_request(CIMultiDict(), {}, "09AA01AB12345678") == (
        "09AA01AB12345678"
    )


def test_serial_too_short():
    """Test that a serial with fewer than 10 characters is not valid."""
    assert serial_from_request(_basic("d.SHORT.x"), {}) is None


def test_server_is_newer():
    """Test the timestamp rule in section 6.2."""
    assert server_is_newer(5, 0)
    assert not server_is_newer(0, 5)
    assert server_is_newer(6, 5)
    assert not server_is_newer(5, 5)
    assert not server_is_newer(4, 5)


def test_advertised_origin():
    """Test that the Advertised URL always has an explicit port."""
    assert advertised_origin("http://10.0.0.5", 9543) == "http://10.0.0.5:9543"
    assert advertised_origin("http://10.0.0.5:80/", 9543) == "http://10.0.0.5:80"
    with pytest.raises(ValueError):
        advertised_origin("10.0.0.5", 9543)
