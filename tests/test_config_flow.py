"""Tests for the config flow."""

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.nest_local.const import CONF_ADVERTISED_URL, CONF_PORT, DOMAIN


async def test_user_step(hass: HomeAssistant):
    """Test that the flow suggests the LAN URL and adds the port."""
    with patch(
        "custom_components.nest_local.config_flow.async_get_source_ip",
        return_value="10.0.0.5",
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
    assert result["type"] is FlowResultType.FORM
    schema = result["data_schema"].schema
    defaults = {str(k): k.default() for k in schema}
    assert defaults[CONF_ADVERTISED_URL] == "http://10.0.0.5:9543"
    assert defaults[CONF_PORT] == 9543

    with patch("custom_components.nest_local.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_PORT: 9543, CONF_ADVERTISED_URL: "http://10.0.0.5"},
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "EvilAgain"
    assert result["data"] == {
        CONF_PORT: 9543,
        CONF_ADVERTISED_URL: "http://10.0.0.5:9543",
    }


async def test_bad_url(hass: HomeAssistant):
    """Test that a URL with no scheme shows an error."""
    with patch(
        "custom_components.nest_local.config_flow.async_get_source_ip",
        return_value="10.0.0.5",
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PORT: 9543, CONF_ADVERTISED_URL: "10.0.0.5"}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_ADVERTISED_URL: "invalid_url"}
