"""The config flow of the nest_local integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.network import async_get_source_ip
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import CONF_ADVERTISED_URL, CONF_PORT, DEFAULT_PORT, DOMAIN, NAME
from .protocol import advertised_origin


class NestLocalConfigFlow(ConfigFlow, domain=DOMAIN):
    """Ask for the port and the Advertised URL."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the only step."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        errors: dict[str, str] = {}
        if user_input is not None:
            port = user_input[CONF_PORT]
            try:
                url = advertised_origin(user_input[CONF_ADVERTISED_URL], port)
            except ValueError:
                errors[CONF_ADVERTISED_URL] = "invalid_url"
            else:
                return self.async_create_entry(
                    title=NAME, data={CONF_PORT: port, CONF_ADVERTISED_URL: url}
                )

        ip = await async_get_source_ip(self.hass)
        schema = vol.Schema(
            {
                vol.Required(CONF_PORT, default=DEFAULT_PORT): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=65535)
                ),
                vol.Required(
                    CONF_ADVERTISED_URL, default=f"http://{ip}:{DEFAULT_PORT}"
                ): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)
