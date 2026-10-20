"""Fixtures for the nest_local tests."""

import base64

import pytest

from custom_components.nest_local.hub import NestHub
from custom_components.nest_local.server import NestServer

SERIAL = "02AA01AC10130C7T"
AUTH = {
    "Authorization": "Basic "
    + base64.b64encode(f"d.{SERIAL}.abc123:apikey".encode()).decode()
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant load the custom integration in every test."""
    return


@pytest.fixture
def hub() -> NestHub:
    """Return a hub with short times for the tests."""
    return NestHub(hold_timeout=0.4, batch_window=0.2)


@pytest.fixture
async def client(hub, aiohttp_client, socket_enabled):
    """Return a test client for the server."""
    server = NestServer(hub, "http://10.0.0.5:9543", 9543, "0.1.0")
    return await aiohttp_client(server.make_app())
