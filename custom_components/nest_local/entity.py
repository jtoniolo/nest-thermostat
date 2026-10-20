"""The base entity and the entity creation for the nest_local integration."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .hub import NestHub
from .thermostat import ThermostatView

type EntityFactory = tuple[
    str, Callable[[ThermostatView], bool], Callable[[NestHub, str], Entity]
]


class NestLocalEntity(Entity):
    """An entity of one Thermostat. The hub pushes each change to it."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hub: NestHub, serial: str, key: str | None) -> None:
        """Initialize the entity."""
        self.hub = hub
        self.serial = serial
        self._attr_unique_id = f"{serial}_{key}" if key else serial
        view = self.view
        entry = hub.devices[serial].entry
        mac = view.device.get("mac_address") or entry.get("mac")
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, serial)},
            connections={(CONNECTION_NETWORK_MAC, mac)} if mac else set(),
            manufacturer="Nest",
            model=entry.get("model") or view.device.get("model_version"),
            name=view.name,
            serial_number=serial,
            sw_version=view.device.get("current_version")
            or entry.get("software_version"),
        )

    @property
    def view(self) -> ThermostatView:
        """Return a view of the current Buckets."""
        return ThermostatView(self.hub.devices[self.serial])

    @property
    def available(self) -> bool:
        """Return True if the Thermostat called in the last 360 s."""
        return self.hub.available(self.serial)

    async def async_added_to_hass(self) -> None:
        """Listen for changes from the hub."""
        self.async_on_remove(self.hub.add_listener(self._handle_change))

    @callback
    def _handle_change(self, serial: str) -> None:
        if serial == self.serial:
            self.async_write_ha_state()

    def _command(self, deltas: dict) -> None:
        self.hub.command(self.serial, deltas)


def setup_entities(
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    factories: Iterable[EntityFactory],
) -> None:
    """Add each entity when the Thermostat reports the fields that it needs."""
    hub: NestHub = entry.runtime_data
    created: set[tuple[str, str]] = set()
    factories = list(factories)

    @callback
    def check(serial: str) -> None:
        view = ThermostatView(hub.devices[serial])
        new = []
        for kind, condition, make in factories:
            if (serial, kind) not in created and condition(view):
                created.add((serial, kind))
                new.append(make(hub, serial))
        if new:
            async_add_entities(new)

    for serial in list(hub.devices):
        check(serial)
    entry.async_on_unload(hub.add_listener(check))
