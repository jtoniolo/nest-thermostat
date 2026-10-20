"""The climate entity of the nest_local integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    ATTR_TARGET_TEMP_HIGH,
    ATTR_TARGET_TEMP_LOW,
    PRESET_ECO,
    PRESET_NONE,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import MAX_TEMP, MIN_TEMP
from .entity import NestLocalEntity, setup_entities
from .thermostat import FAN_AUTO, FAN_ON


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a climate entity for each Thermostat."""
    setup_entities(
        entry,
        async_add_entities,
        [("climate", lambda view: True, NestLocalClimate)],
    )


class NestLocalClimate(NestLocalEntity, ClimateEntity):
    """The Thermostat as a climate entity."""

    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 0.5
    _attr_min_temp = MIN_TEMP
    _attr_max_temp = MAX_TEMP
    _attr_preset_modes = [PRESET_NONE, PRESET_ECO]
    _attr_fan_modes = [FAN_AUTO, FAN_ON]

    def __init__(self, hub, serial: str) -> None:
        """Initialize the climate entity."""
        super().__init__(hub, serial, None)

    @property
    def supported_features(self) -> ClimateEntityFeature:
        """Return the features that the capabilities allow."""
        view = self.view
        features = (
            ClimateEntityFeature.PRESET_MODE
            | ClimateEntityFeature.TURN_OFF
            | ClimateEntityFeature.TURN_ON
        )
        if view.can_heat or view.can_cool:
            features |= ClimateEntityFeature.TARGET_TEMPERATURE
        if view.can_heat and view.can_cool:
            features |= ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
        if view.has_fan:
            features |= ClimateEntityFeature.FAN_MODE
        return features

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Return the HVAC modes that the capabilities allow."""
        return self.view.hvac_modes

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Return the HVAC mode."""
        return self.view.hvac_mode

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return the HVAC action."""
        return self.view.hvac_action

    @property
    def current_temperature(self) -> float | None:
        """Return the room temperature."""
        return self.view.current_temperature

    @property
    def current_humidity(self) -> float | None:
        """Return the room humidity."""
        return self.view.device.get("current_humidity")

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature in the single modes."""
        view = self.view
        if view.nest_mode in ("heat", "cool", "emergency"):
            return view.shared.get("target_temperature")
        return None

    @property
    def target_temperature_low(self) -> float | None:
        """Return the low target temperature in range mode."""
        view = self.view
        if view.nest_mode == "range":
            return view.shared.get("target_temperature_low")
        return None

    @property
    def target_temperature_high(self) -> float | None:
        """Return the high target temperature in range mode."""
        view = self.view
        if view.nest_mode == "range":
            return view.shared.get("target_temperature_high")
        return None

    @property
    def fan_mode(self) -> str | None:
        """Return the fan mode."""
        view = self.view
        return view.fan_mode if view.has_fan else None

    @property
    def preset_mode(self) -> str:
        """Return the preset."""
        return PRESET_ECO if self.view.eco_active else PRESET_NONE

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set the HVAC mode."""
        self._command(self.view.hvac_mode_deltas(hvac_mode))

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the target temperature, and the mode if HA gives one."""
        self._command(
            self.view.temperature_deltas(
                kwargs.get(ATTR_HVAC_MODE),
                kwargs.get(ATTR_TEMPERATURE),
                kwargs.get(ATTR_TARGET_TEMP_LOW),
                kwargs.get(ATTR_TARGET_TEMP_HIGH),
            )
        )

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set the fan mode."""
        self._command(self.view.fan_deltas(fan_mode))

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Enter or exit eco."""
        if preset_mode not in (PRESET_ECO, PRESET_NONE):
            raise ServiceValidationError(f"Unknown preset {preset_mode}")
        view = self.view
        if (preset_mode == PRESET_ECO) == view.eco_active:
            return
        self._command(view.eco_deltas(preset_mode == PRESET_ECO))
