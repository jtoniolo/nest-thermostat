"""The sensors of the nest_local integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfElectricPotential
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import NestLocalEntity, setup_entities
from .thermostat import ThermostatView


@dataclass(frozen=True, kw_only=True)
class NestLocalSensorDescription(SensorEntityDescription):
    """A sensor that reads one field of the device Bucket."""

    value_fn: Callable[[ThermostatView], Any]


SENSORS = (
    NestLocalSensorDescription(
        key="humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda view: view.device.get("current_humidity"),
    ),
    NestLocalSensorDescription(
        key="battery_voltage",
        translation_key="battery_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda view: view.device.get("battery_level"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add each sensor when the Thermostat reports its field."""
    setup_entities(
        entry,
        async_add_entities,
        [
            (
                description.key,
                lambda view, d=description: d.value_fn(view) is not None,
                lambda hub, serial, d=description: NestLocalSensor(hub, serial, d),
            )
            for description in SENSORS
        ],
    )


class NestLocalSensor(NestLocalEntity, SensorEntity):
    """A sensor of the Thermostat."""

    entity_description: NestLocalSensorDescription

    def __init__(self, hub, serial: str, description: NestLocalSensorDescription):
        """Initialize the sensor."""
        super().__init__(hub, serial, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        """Return the value of the field."""
        return self.entity_description.value_fn(self.view)
