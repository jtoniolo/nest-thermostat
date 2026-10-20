"""The HTTP server that the Thermostat calls. This module does not use Home Assistant.

The server owns its own port with the aiohttp AppRunner and TCPSite pattern
of emulated_hue. One catch-all handler normalizes the path and dispatches on
it (PROTOCOL.md section 3).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from aiohttp import web

from .const import (
    DEFER_DEVICE_WINDOW,
    DISABLE_DEFER_WINDOW,
    MAX_SUBSCRIPTIONS,
    SUSPEND_TIME_MAX,
)
from .hub import NestHub, Subscription
from .protocol import (
    match_route,
    normalize_path,
    now_ms,
    serial_from_request,
    wire_object,
)

_LOGGER = logging.getLogger(__name__)

_DISABLE_DEFER_FIELDS = frozenset(
    {
        "target_temperature",
        "target_temperature_high",
        "target_temperature_low",
        "target_temperature_type",
        "hvac_mode",
    }
)
_ENTRY_FIELDS = (
    "reset",
    "mac",
    "model",
    "request_id",
    "software_version",
    "wireless_reg_domain",
    "backplate_model",
)
_SERIAL_REQUIRED = {"error": "Device serial required"}
# The aiohttp and asyncio errors for a write to a closed connection.
_WRITE_ERRORS = (ConnectionError, RuntimeError, asyncio.CancelledError)


def _dumps(data: Any) -> bytes:
    return json.dumps(data, separators=(",", ":")).encode()


class NestServer:
    """Answer the Routes that the Thermostat calls."""

    def __init__(
        self, hub: NestHub, advertised_url: str, port: int, version: str
    ) -> None:
        """Initialize the server. The Advertised URL must have its port."""
        self.hub = hub
        self.advertised_url = advertised_url
        self.port = port
        self.version = version
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._handlers = {
            "entry": self._entry,
            "subscribe": self._subscribe,
            "put": self._put,
            "object_list": self._object_list,
            "ping": self._ping,
            "passphrase": self._passphrase,
            "pro_info": self._pro_info,
            "upload": self._upload,
            "weather": self._weather,
            "info": self._info,
        }

    def make_app(self) -> web.Application:
        """Return the aiohttp application."""
        # The Thermostat can upload logs that are larger than the 1 MB default.
        app = web.Application(client_max_size=16 * 1024 * 1024)
        app.router.add_route("*", "/{tail:.*}", self.handle)
        return app

    async def async_start(self, host: str) -> None:
        """Bind the port and start the server."""
        runner = web.AppRunner(self.make_app())
        await runner.setup()
        site = web.TCPSite(runner, host, self.port)
        try:
            await site.start()
        except OSError:
            await runner.cleanup()
            raise
        self._runner, self._site = runner, site
        _LOGGER.info("Listening on %s:%s for %s", host, self.port, self.advertised_url)

    async def async_stop(self) -> None:
        """Close the held Subscriptions and stop the server."""
        if self._runner is None:
            return
        runner, self._runner, self._site = self._runner, None, None
        self.hub.close_all()
        await runner.cleanup()

    async def handle(self, request: web.Request) -> web.StreamResponse:
        """Dispatch a request on its normalized path."""
        route = match_route(request.method, request.path)
        handler = self._handlers.get(route)
        if handler is None:
            _LOGGER.warning(
                "Unknown request %s %s (%s)",
                request.method,
                request.path_qs,
                normalize_path(request.path),
            )
            return web.json_response({})
        return await handler(request)

    def _serial(self, request: web.Request, path_serial: str | None = None):
        return serial_from_request(request.headers, request.query, path_serial)

    def _headers(self) -> dict[str, str]:
        return {
            "X-nl-service-timestamp": str(now_ms()),
            "X-nl-suspend-time-max": str(SUSPEND_TIME_MAX),
            "X-nl-defer-device-window": str(DEFER_DEVICE_WINDOW),
        }

    async def _json_body(self, request: web.Request) -> dict[str, Any] | None:
        try:
            body = json.loads(await request.read() or b"{}")
        except ValueError:
            return None
        return body if isinstance(body, dict) else None

    # Entry and the small Routes.

    async def _entry(self, request: web.Request) -> web.Response:
        form = await request.post() if request.method == "POST" else request.query
        facts = {name: str(form[name]) for name in _ENTRY_FIELDS if name in form}
        _LOGGER.debug("Entry %s: %s", request.path, facts)
        self.hub.set_entry(self._serial(request), facts)
        adv = self.advertised_url
        return web.json_response(
            {
                "czfe_url": f"{adv}/nest/transport",
                "transport_url": f"{adv}/nest/transport",
                "direct_transport_url": f"{adv}/nest/transport",
                "passphrase_url": f"{adv}/nest/passphrase",
                "ping_url": f"{adv}/nest/transport",
                "pro_info_url": f"{adv}/nest/pro_info",
                "weather_url": f"{adv}/nest/weather/v1?query=",
                "upload_url": f"{adv}/nest/upload",
                "software_update_url": "",
                "server_version": self.version,
                "tier_name": "local",
            }
        )

    async def _ping(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "timestamp": now_ms()})

    async def _passphrase(self, request: web.Request) -> web.Response:
        code, expires = self.hub.passphrase(self._serial(request))
        return web.json_response({"value": code, "expires": expires})

    async def _pro_info(self, request: web.Request) -> web.Response:
        code = normalize_path(request.path).rstrip("/").rsplit("/", 1)[-1]
        return web.json_response(
            {
                "id": 1,
                "pro_id": code,
                "dba": "nest_local",
                "locality": "Local",
                "rating": 5.0,
            }
        )

    async def _upload(self, request: web.Request) -> web.Response:
        body = await request.read()
        _LOGGER.debug("Upload of %d bytes", len(body))
        return web.json_response({"status": "ok"})

    async def _weather(self, request: web.Request) -> web.Response:
        _LOGGER.debug("Weather query %s", request.query_string)
        return web.json_response({})

    async def _info(self, request: web.Request) -> web.Response:
        return web.json_response(
            {
                "server": "nest_local",
                "version": self.version,
                "api_origin": self.advertised_url,
                "cloudregisterurl": f"{self.advertised_url}/entry",
                "port": self.port,
                "ssl": False,
                "require_device_pairing": False,
            }
        )

    async def _object_list(self, request: web.Request) -> web.Response:
        parts = normalize_path(request.path).rstrip("/").split("/")
        path_serial = None
        if len(parts) >= 5 and parts[3] == "device":
            path_serial = parts[4].removeprefix("device.")
        serial = self._serial(request, path_serial)
        if serial is None:
            return web.json_response(_SERIAL_REQUIRED, status=400)
        record = self.hub.devices.get(serial)
        buckets = record.buckets.items() if record else []
        return web.json_response(
            {"objects": [wire_object(k, b.revision, b.timestamp) for k, b in buckets]},
            headers=self._headers(),
        )

    # Put.

    async def _put(self, request: web.Request) -> web.Response:
        body = await self._json_body(request)
        if body is None:
            return web.json_response({"error": "Body is not JSON"}, status=400)
        serial = self._serial(request)
        if serial is None:
            return web.json_response(_SERIAL_REQUIRED, status=400)
        _LOGGER.debug("Put %s from %s: %s", request.path, serial, body)
        objects = self.hub.apply_put(serial, body)
        return web.json_response({"objects": objects}, headers=self._headers())

    # Subscribe.

    async def _subscribe(self, request: web.Request) -> web.StreamResponse:
        body = await self._json_body(request)
        if body is None:
            return web.json_response({"error": "Body is not JSON"}, status=400)
        serial = self._serial(request)
        if serial is None:
            return web.json_response(_SERIAL_REQUIRED, status=400)
        _LOGGER.debug(
            "Subscribe %s from %s, session %s, objects %s",
            request.path,
            serial,
            body.get("session"),
            [
                (
                    o.get("object_key"),
                    o.get("object_revision"),
                    o.get("object_timestamp"),
                )
                for o in body.get("objects") or []
                if isinstance(o, dict)
            ],
        )

        over_limit = self.hub.subscription_count(serial) >= MAX_SUBSCRIPTIONS
        send = [] if over_limit else self.hub.subscribe_objects(serial, body)
        if over_limit:
            _LOGGER.warning("Thermostat %s has too many Subscriptions", serial)

        headers = self._headers()
        if any(_DISABLE_DEFER_FIELDS & set(obj.get("value", {})) for obj in send):
            headers["X-nl-disable-defer-window"] = str(DISABLE_DEFER_WINDOW)

        if body.get("chunked") is False:
            return web.json_response({"objects": send}, headers=headers)

        response = web.StreamResponse(headers=headers)
        response.content_type = "application/json"
        response.enable_chunked_encoding()
        await response.prepare(request)

        if send or over_limit:
            try:
                await response.write(_dumps({"objects": send}))
                await response.write_eof()
            except _WRITE_ERRORS:
                _LOGGER.debug("Subscribe write for %s failed", serial)
                self.hub.add_pending(serial, send)
            return response

        subscription = self.hub.add_subscription(serial)
        try:
            await self._hold(response, subscription)
        finally:
            self.hub.remove_subscription(subscription)
        return response

    async def _hold(
        self, response: web.StreamResponse, subscription: Subscription
    ) -> None:
        """Hold the Subscription, and write each push as its own chunk."""
        item = await self._next(subscription, self.hub.hold_timeout)
        while item is not None:
            try:
                await response.write(_dumps({"objects": item}))
            except _WRITE_ERRORS:
                _LOGGER.debug("Push to %s failed, keep it", subscription.serial)
                self.hub.add_pending(subscription.serial, item + _drain(subscription))
                return
            item = await self._next(subscription, self.hub.batch_window)
        try:
            await response.write_eof()
        except _WRITE_ERRORS:
            _LOGGER.debug("Close of a Subscription for %s failed", subscription.serial)

    async def _next(
        self, subscription: Subscription, timeout: float
    ) -> list[dict[str, Any]] | None:
        try:
            async with asyncio.timeout(timeout):
                return await subscription.queue.get()
        except TimeoutError:
            return None


def _drain(subscription: Subscription) -> list[dict[str, Any]]:
    """Return all objects that are still on the queue."""
    objects: list[dict[str, Any]] = []
    while not subscription.queue.empty():
        item = subscription.queue.get_nowait()
        if item is not None:
            objects.extend(item)
    return objects
