"""Read the Thermostat state from its Buckets, and make the command deltas.

Each delta has only the fields that change (PROTOCOL.md section 9). No logic
here keys off the generation or the Model string.
"""

from __future__ import annotations

import json
import time
from typing import Any

from homeassistant.components.climate import HVACAction, HVACMode
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .const import MAX_TEMP, MIN_TEMP
from .hub import DeviceRecord

NEST_TO_HA_MODE = {
    "off": HVACMode.OFF,
    "heat": HVACMode.HEAT,
    "cool": HVACMode.COOL,
    "range": HVACMode.HEAT_COOL,
    "emergency": HVACMode.HEAT,
}
HA_TO_NEST_MODE = {
    HVACMode.OFF: "off",
    HVACMode.HEAT: "heat",
    HVACMode.COOL: "cool",
    HVACMode.HEAT_COOL: "range",
}
FAN_ON = "on"
FAN_AUTO = "auto"
ECO_MODES = ("manual-eco", "auto-eco")

_HEAT_FIELDS = (
    "hvac_heater_state",
    "hvac_heat_x2_state",
    "hvac_heat_x3_state",
    "hvac_aux_heater_state",
    "hvac_alt_heat_state",
    "hvac_alt_heat_x2_state",
    "hvac_emer_heat_state",
)
_COOL_FIELDS = ("hvac_ac_state", "hvac_cool_x2_state", "hvac_cool_x3_state")
_DEFAULT_FAN_DURATION = 3600


class ThermostatView:
    """A read view of the Buckets of one Thermostat."""

    def __init__(self, record: DeviceRecord) -> None:
        """Initialize the view."""
        self.record = record
        self.serial = record.serial
        self.shared_key = f"shared.{record.serial}"
        self.device_key = f"device.{record.serial}"

    def _value(self, key: str | None) -> dict[str, Any]:
        bucket = self.record.buckets.get(key) if key else None
        return bucket.value if bucket else {}

    @property
    def shared(self) -> dict[str, Any]:
        """Return the shared Bucket value."""
        return self._value(self.shared_key)

    @property
    def device(self) -> dict[str, Any]:
        """Return the device Bucket value."""
        return self._value(self.device_key)

    @property
    def structure_key(self) -> str | None:
        """Return the key of the structure Bucket, if it is known."""
        sid = self.record.structure_id
        return f"structure.{sid}" if sid else None

    @property
    def structure(self) -> dict[str, Any]:
        """Return the structure Bucket value."""
        return self._value(self.structure_key)

    # Device facts.

    @property
    def name(self) -> str:
        """Return the name of the Thermostat."""
        return (
            self.shared.get("name") or self.shared.get("label") or f"Nest {self.serial}"
        )

    def _capability(self, field: str) -> bool:
        """Read a capability from shared, then device. Missing means present."""
        for source in (self.shared, self.device):
            if field in source:
                return bool(source[field])
        return True

    @property
    def can_heat(self) -> bool:
        """Return True if the Thermostat can heat."""
        return self._capability("can_heat")

    @property
    def can_cool(self) -> bool:
        """Return True if the Thermostat can cool."""
        return self._capability("can_cool")

    @property
    def has_fan(self) -> bool:
        """Return True if the Thermostat reports a fan."""
        return bool(self.device.get("has_fan", self.shared.get("has_fan", False)))

    @property
    def reports_fan(self) -> bool:
        """Return True if the Thermostat reports a fan or a fan state."""
        return self.has_fan or "hvac_fan_state" in self.shared

    # Climate state.

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Return the HVAC modes that the capabilities allow."""
        modes = [HVACMode.OFF]
        if self.can_heat:
            modes.append(HVACMode.HEAT)
        if self.can_cool:
            modes.append(HVACMode.COOL)
        if self.can_heat and self.can_cool:
            modes.append(HVACMode.HEAT_COOL)
        return modes

    @property
    def nest_mode(self) -> str | None:
        """Return the Nest mode, for example range."""
        return self.shared.get("target_temperature_type")

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Return the HA HVAC mode."""
        return NEST_TO_HA_MODE.get(self.nest_mode or "")

    @property
    def current_temperature(self) -> float | None:
        """Return the room temperature (PROTOCOL.md gap 2)."""
        value = self.shared.get("current_temperature")
        if value is None:
            value = self.device.get("current_temperature")
        return value

    @property
    def fan_timer_active(self) -> bool:
        """Return True if the fan timer runs."""
        timeout = self.device.get("fan_timer_timeout") or 0
        return isinstance(timeout, int | float) and timeout > time.time()

    @property
    def fan_mode(self) -> str:
        """Return the fan mode."""
        if self.fan_timer_active or self.device.get("fan_control_state") is True:
            return FAN_ON
        return FAN_AUTO

    @property
    def fan_running(self) -> bool:
        """Return True if the fan runs."""
        return self.shared.get("hvac_fan_state") is True or self.fan_timer_active

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return the HVAC action."""
        if self.nest_mode is None:
            return None
        if self.nest_mode == "off":
            return HVACAction.OFF
        if any(self.shared.get(name) is True for name in _HEAT_FIELDS):
            return HVACAction.HEATING
        if any(self.shared.get(name) is True for name in _COOL_FIELDS):
            return HVACAction.COOLING
        if self.fan_running:
            return HVACAction.FAN
        return HVACAction.IDLE

    @property
    def eco_mode(self) -> str | None:
        """Return the eco mode from either device field (PROTOCOL.md gap 5)."""
        eco = self.device.get("eco")
        if isinstance(eco, dict) and eco.get("mode"):
            return eco["mode"]
        eco_mode = self.device.get("eco_mode")
        if isinstance(eco_mode, str):
            try:
                eco_mode = json.loads(eco_mode)
            except ValueError:
                return eco_mode
        if isinstance(eco_mode, dict):
            return eco_mode.get("mode")
        return None

    @property
    def eco_active(self) -> bool:
        """Return True if the Thermostat is in eco."""
        return (
            self.structure.get("manual_eco_all") is True or self.eco_mode in ECO_MODES
        )

    # Commands.

    def hvac_mode_deltas(self, hvac_mode: str) -> dict[str, dict[str, Any]]:
        """Return the delta for an HVAC mode (PROTOCOL.md section 9.2)."""
        nest_mode = HA_TO_NEST_MODE.get(hvac_mode)  # type: ignore[call-overload]
        if nest_mode is None or hvac_mode not in self.hvac_modes:
            raise ServiceValidationError(
                f"The Thermostat cannot use the HVAC mode {hvac_mode}"
            )
        if nest_mode == self.nest_mode:
            return {}
        return {self.shared_key: {"target_temperature_type": nest_mode}}

    def temperature_deltas(
        self,
        hvac_mode: str | None = None,
        temperature: float | None = None,
        low: float | None = None,
        high: float | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Return the delta for a mode and a temperature (section 9.3)."""
        deltas = self.hvac_mode_deltas(hvac_mode) if hvac_mode is not None else {}
        nest_mode = HA_TO_NEST_MODE.get(hvac_mode) if hvac_mode else self.nest_mode  # type: ignore[call-overload]
        fields: dict[str, float] = {}
        if nest_mode == "range":
            if low is None or high is None:
                raise ServiceValidationError(
                    "Give the low and the high temperature in heat_cool mode"
                )
            low, high = _clamp(low), _clamp(high)
            if low > high:
                raise ServiceValidationError("The low temperature is above the high")
            fields = {"target_temperature_low": low, "target_temperature_high": high}
        elif nest_mode in ("heat", "cool", "emergency"):
            if temperature is None:
                raise ServiceValidationError("Give the target temperature")
            fields = {"target_temperature": _clamp(temperature)}
        elif nest_mode == "off":
            raise ServiceValidationError("The Thermostat is off")
        else:
            raise HomeAssistantError("The Thermostat did not report its mode yet")
        changed = {k: v for k, v in fields.items() if self.shared.get(k) != v}
        if changed:
            shared = deltas.setdefault(self.shared_key, {})
            shared.update(changed)
            shared["target_change_pending"] = True
        return deltas

    def fan_deltas(self, fan_mode: str) -> dict[str, dict[str, Any]]:
        """Return the delta for a fan mode (PROTOCOL.md section 9.5)."""
        if not self.has_fan:
            raise ServiceValidationError("The Thermostat has no fan")
        if fan_mode == FAN_AUTO:
            return {self.device_key: {"fan_timer_timeout": 0}}
        if fan_mode != FAN_ON:
            raise ServiceValidationError(f"Unknown fan mode {fan_mode}")
        if self.fan_timer_active:
            return {}
        duration = self.device.get("fan_timer_duration")
        if not duration and self.device.get("fan_timer_duration_minutes"):
            duration = int(self.device["fan_timer_duration_minutes"]) * 60
        duration = int(duration or _DEFAULT_FAN_DURATION)
        return {
            self.device_key: {
                "fan_timer_timeout": int(time.time()) + duration,
                "fan_timer_duration": duration,
            }
        }

    def eco_deltas(self, enable: bool) -> dict[str, dict[str, Any]]:
        """Return the deltas to enter or exit eco (PROTOCOL.md section 9.4)."""
        structure_key = self.structure_key
        if structure_key is None:
            raise HomeAssistantError("The structure of the Thermostat is not known yet")
        now = int(time.time())
        if enable:
            return {
                structure_key: {"manual_eco_all": True, "manual_eco_timestamp": now}
            }
        return {
            structure_key: {
                "manual_eco_all": False,
                "manual_eco_timestamp": now,
                "away": False,
            },
            self.device_key: {
                "eco": {
                    "mode": "schedule",
                    "touched_by": 3,
                    "mode_update_timestamp": now,
                }
            },
        }


def _clamp(value: float) -> float:
    return min(max(float(value), MIN_TEMP), MAX_TEMP)
