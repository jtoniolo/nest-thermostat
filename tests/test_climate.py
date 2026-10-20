"""Tests for the entities and the commands (PROTOCOL.md cases 16 to 20)."""

import time
from unittest.mock import patch

import pytest
from homeassistant.components.climate import (
    ATTR_FAN_MODE,
    ATTR_HVAC_MODE,
    ATTR_PRESET_MODE,
    ATTR_TARGET_TEMP_HIGH,
    ATTR_TARGET_TEMP_LOW,
    HVACAction,
    HVACMode,
)
from homeassistant.components.climate import (
    DOMAIN as CLIMATE_DOMAIN,
)
from homeassistant.const import ATTR_ENTITY_ID, ATTR_TEMPERATURE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nest_local.const import (
    CONF_ADVERTISED_URL,
    CONF_PORT,
    DOMAIN,
)

from .conftest import SERIAL

SHARED = f"shared.{SERIAL}"
DEVICE = f"device.{SERIAL}"
CLIMATE = "climate.hall"
FAN = "binary_sensor.hall_fan"


async def _setup(hass: HomeAssistant, entry: MockConfigEntry | None = None):
    if entry is None:
        entry = MockConfigEntry(
            domain=DOMAIN,
            unique_id=DOMAIN,
            data={CONF_PORT: 0, CONF_ADVERTISED_URL: "http://127.0.0.1:9543"},
        )
        entry.add_to_hass(hass)
    with patch("custom_components.nest_local.BIND_HOST", "127.0.0.1"):
        assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


@pytest.fixture
async def entry(hass: HomeAssistant, socket_enabled):
    """Set up the Integration with one Thermostat that reported its state."""
    entry = await _setup(hass)
    hub = entry.runtime_data
    hub.apply_put(
        SERIAL,
        {
            SHARED: {
                "object_key": SHARED,
                "name": "Hall",
                "target_temperature_type": "heat",
                "target_temperature": 20.0,
                "target_temperature_low": 19.0,
                "target_temperature_high": 24.0,
                "current_temperature": 21.3,
                "can_heat": True,
                "can_cool": True,
                "hvac_heater_state": True,
                "hvac_fan_state": False,
            },
            DEVICE: {
                "object_key": DEVICE,
                "has_fan": True,
                "fan_timer_timeout": 0,
                "fan_timer_duration": 900,
                "current_humidity": 41,
                "battery_level": 3.7,
            },
        },
    )
    hub.devices[SERIAL].structure_id = "default"
    await hass.async_block_till_done()
    return entry


async def _call(hass, service: str, **data):
    await hass.services.async_call(
        CLIMATE_DOMAIN, service, {ATTR_ENTITY_ID: CLIMATE, **data}, blocking=True
    )


def _shared(entry) -> dict:
    return entry.runtime_data.devices[SERIAL].buckets[SHARED].value


async def test_entities(hass: HomeAssistant, entry):
    """Test that the entities show the reported state."""
    state = hass.states.get(CLIMATE)
    assert state.state == HVACMode.HEAT
    assert state.attributes["current_temperature"] == 21.3
    assert state.attributes[ATTR_TEMPERATURE] == 20.0
    assert state.attributes["hvac_action"] == HVACAction.HEATING
    assert state.attributes[ATTR_FAN_MODE] == "auto"
    assert set(state.attributes["hvac_modes"]) == {"off", "heat", "cool", "heat_cool"}
    assert set(state.attributes["fan_modes"]) == {"auto", "on"}
    assert state.attributes[ATTR_PRESET_MODE] == "none"
    assert hass.states.get(FAN).state == "off"
    assert hass.states.get("sensor.hall_humidity").state == "41"
    assert hass.states.get("sensor.hall_battery_voltage").state == "3.7"


async def test_mode_heat_cool_writes_range(hass: HomeAssistant, entry):
    """Test case 16: heat_cool writes range."""
    await _call(hass, "set_hvac_mode", **{ATTR_HVAC_MODE: HVACMode.HEAT_COOL})
    assert _shared(entry)["target_temperature_type"] == "range"
    assert hass.states.get(CLIMATE).state == HVACMode.HEAT_COOL
    assert hass.states.get(CLIMATE).attributes[ATTR_TARGET_TEMP_LOW] == 19.0


async def test_unknown_mode_writes_nothing(hass: HomeAssistant, entry):
    """Test case 16: an unknown mode raises an error and writes nothing."""
    hub = entry.runtime_data
    sub = hub.add_subscription(SERIAL)
    entity = hass.data["climate"].get_entity(CLIMATE)
    with pytest.raises(ServiceValidationError):
        await entity.async_set_hvac_mode(HVACMode.DRY)
    assert _shared(entry)["target_temperature_type"] == "heat"
    assert sub.queue.empty()


async def test_mode_needs_capability(hass: HomeAssistant, entry):
    """Test that a mode the Thermostat cannot do raises an error."""
    entry.runtime_data.apply_put(
        SERIAL, {SHARED: {"object_key": SHARED, "can_cool": False}}
    )
    await hass.async_block_till_done()
    entity = hass.data["climate"].get_entity(CLIMATE)
    assert HVACMode.COOL not in entity.hvac_modes
    with pytest.raises(ServiceValidationError):
        await entity.async_set_hvac_mode(HVACMode.COOL)


async def test_range_temperature(hass: HomeAssistant, entry):
    """Test case 17: range writes low and high with target_change_pending."""
    hub = entry.runtime_data
    sub = hub.add_subscription(SERIAL)
    await _call(
        hass,
        "set_temperature",
        **{
            ATTR_HVAC_MODE: HVACMode.HEAT_COOL,
            ATTR_TARGET_TEMP_LOW: 18.5,
            ATTR_TARGET_TEMP_HIGH: 25.0,
        },
    )
    pushed = sub.queue.get_nowait()
    assert pushed[0]["object_key"] == SHARED
    assert pushed[0]["value"] == {
        "target_temperature_type": "range",
        "target_temperature_low": 18.5,
        "target_temperature_high": 25.0,
        "target_change_pending": True,
    }
    assert _shared(entry)["target_temperature_high"] == 25.0


async def test_single_temperature(hass: HomeAssistant, entry):
    """Test that heat writes target_temperature, clamped to the bounds."""
    hub = entry.runtime_data
    sub = hub.add_subscription(SERIAL)
    await _call(hass, "set_temperature", **{ATTR_TEMPERATURE: 22.0})
    assert sub.queue.get_nowait()[0]["value"] == {
        "target_temperature": 22.0,
        "target_change_pending": True,
    }


async def test_eco_exit_one_chunk(hass: HomeAssistant, entry):
    """Test case 18: eco exit pushes the structure and device deltas together."""
    hub = entry.runtime_data
    await _call(hass, "set_preset_mode", **{ATTR_PRESET_MODE: "eco"})
    structure = hub.devices[SERIAL].buckets["structure.default"].value
    assert structure["manual_eco_all"] is True
    assert hass.states.get(CLIMATE).attributes[ATTR_PRESET_MODE] == "eco"

    sub = hub.add_subscription(SERIAL)
    await _call(hass, "set_preset_mode", **{ATTR_PRESET_MODE: "none"})
    pushed = sub.queue.get_nowait()
    assert sub.queue.empty()
    by_key = {o["object_key"]: o["value"] for o in pushed}
    assert by_key["structure.default"]["manual_eco_all"] is False
    assert by_key["structure.default"]["away"] is False
    assert abs(by_key["structure.default"]["manual_eco_timestamp"] - time.time()) < 5
    assert by_key[DEVICE]["eco"]["mode"] == "schedule"
    assert by_key[DEVICE]["eco"]["touched_by"] == 3
    assert hass.states.get(CLIMATE).attributes[ATTR_PRESET_MODE] == "none"


async def test_fan(hass: HomeAssistant, entry):
    """Test that fan on sets the timer, and auto clears it."""
    await _call(hass, "set_fan_mode", **{ATTR_FAN_MODE: "on"})
    device = entry.runtime_data.devices[SERIAL].buckets[DEVICE].value
    assert device["fan_timer_duration"] == 900
    assert abs(device["fan_timer_timeout"] - (time.time() + 900)) < 5
    assert hass.states.get(CLIMATE).attributes[ATTR_FAN_MODE] == "on"
    assert hass.states.get(FAN).state == "on"
    await _call(hass, "set_fan_mode", **{ATTR_FAN_MODE: "auto"})
    device = entry.runtime_data.devices[SERIAL].buckets[DEVICE].value
    assert device["fan_timer_timeout"] == 0
    assert hass.states.get(FAN).state == "off"


async def test_commands_that_change_nothing(hass: HomeAssistant, entry):
    """Test case 20: no store and no push for a command that changes nothing."""
    hub = entry.runtime_data
    await _call(hass, "set_fan_mode", **{ATTR_FAN_MODE: "on"})
    shared = hub.devices[SERIAL].buckets[SHARED]
    device = hub.devices[SERIAL].buckets[DEVICE]
    before = (shared.revision, shared.timestamp, device.revision, device.timestamp)
    sub = hub.add_subscription(SERIAL)
    await _call(hass, "set_hvac_mode", **{ATTR_HVAC_MODE: HVACMode.HEAT})
    await _call(hass, "set_fan_mode", **{ATTR_FAN_MODE: "on"})
    shared = hub.devices[SERIAL].buckets[SHARED]
    device = hub.devices[SERIAL].buckets[DEVICE]
    after = (shared.revision, shared.timestamp, device.revision, device.timestamp)
    assert after == before
    assert sub.queue.empty()


async def test_store_round_trip(hass: HomeAssistant, entry):
    """Test case 19: the buckets survive an unload and a new setup."""
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    await _setup(hass, entry)
    hub = entry.runtime_data
    assert hub.devices[SERIAL].buckets[SHARED].value["name"] == "Hall"
    assert hub.devices[SERIAL].structure_id == "default"
    assert hass.states.get(CLIMATE) is not None


async def test_availability(hass: HomeAssistant, entry):
    """Test that the Thermostat is unavailable with no contact for 360 s."""
    assert hass.states.get(CLIMATE).state != "unavailable"
    record = entry.runtime_data.devices[SERIAL]
    record.last_seen -= 361
    entry.runtime_data.notify_all()
    await hass.async_block_till_done()
    assert hass.states.get(CLIMATE).state == "unavailable"
