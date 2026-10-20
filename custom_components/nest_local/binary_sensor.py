"""The binary sensors of the nest_local integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import NestLocalEntity, setup_entities


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a fan sensor when the Thermostat reports a fan."""
    setup_entities(
        entry,
        async_add_entities,
        [("fan", lambda view: view.reports_fan, NestLocalFanSensor)],
    )


class NestLocalFanSensor(NestLocalEntity, BinarySensorEntity):
    """On when the fan runs."""

    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_translation_key = "fan"

    def __init__(self, hub, serial: str) -> None:
        """Initialize the fan sensor."""
        super().__init__(hub, serial, "fan")

    @property
    def is_on(self) -> bool:
        """Return True if the fan runs."""
        return self.view.fan_running
