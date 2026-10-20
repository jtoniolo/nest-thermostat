"""The nest_local integration: a local server for a Nest thermostat.

The Integration owns its own port. The Thermostat, with the NoLongerEvil
firmware, calls it in place of the Nest cloud.
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.loader import async_get_integration

from .const import (
    CONF_ADVERTISED_URL,
    CONF_PORT,
    DOMAIN,
    SAVE_DELAY,
    STORAGE_VERSION,
)
from .hub import NestHub
from .protocol import advertised_origin
from .server import NestServer

PLATFORMS = [Platform.BINARY_SENSOR, Platform.CLIMATE, Platform.SENSOR]
BIND_HOST = "0.0.0.0"
AVAILABILITY_INTERVAL = timedelta(seconds=60)

type NestLocalConfigEntry = ConfigEntry[NestHub]


async def async_setup_entry(hass: HomeAssistant, entry: NestLocalConfigEntry) -> bool:
    """Start the server and add the entities."""
    store: Store[dict] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
    hub = NestHub()
    hub.load(await store.async_load())
    hub.on_save = lambda: store.async_delay_save(hub.as_dict, SAVE_DELAY)

    port = entry.data[CONF_PORT]
    integration = await async_get_integration(hass, DOMAIN)
    server = NestServer(
        hub,
        advertised_origin(entry.data[CONF_ADVERTISED_URL], port),
        port,
        str(integration.version),
    )
    try:
        await server.async_start(BIND_HOST)
    except OSError as err:
        raise ConfigEntryNotReady(f"Cannot listen on port {port}: {err}") from err

    entry.runtime_data = hub

    async def stop_server() -> None:
        await server.async_stop()
        await store.async_save(hub.as_dict())

    entry.async_on_unload(stop_server)
    entry.async_on_unload(
        async_track_time_interval(
            hass, lambda now: hub.notify_all(), AVAILABILITY_INTERVAL
        )
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: NestLocalConfigEntry) -> bool:
    """Remove the entities. The unload callbacks then stop the server."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
