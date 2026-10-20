"""Wire rules for the Nest protocol. This module does not use Home Assistant."""

from __future__ import annotations

import base64
import binascii
import re
import time
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

_LEGACY_PREFIXES = {
    "/czfe/": "/nest/transport/",
    "/transport/": "/nest/transport/",
    "/weather/": "/nest/weather/",
    "/pro_info/": "/nest/pro_info/",
}
_LEGACY_PATHS = {
    "/entry": "/nest/entry",
    "/entry/": "/nest/entry",
    "/ping": "/nest/ping",
    "/passphrase": "/nest/passphrase",
    "/transport": "/nest/transport",
    "/upload": "/nest/upload",
}
_PUT_FIELDS = ("object_key", "base_object_revision", "if_object_revision")


def now_ms() -> int:
    """Return the time now in milliseconds."""
    return int(time.time() * 1000)


def normalize_path(path: str) -> str:
    """Change a legacy path to its /nest/ form (PROTOCOL.md section 3)."""
    if path.startswith("/nest/"):
        return path
    if path in _LEGACY_PATHS:
        return _LEGACY_PATHS[path]
    for prefix, new in _LEGACY_PREFIXES.items():
        if path.startswith(prefix):
            return new + path[len(prefix) :]
    return path


def match_route(method: str, path: str) -> str:
    """Return the name of the handler for a request."""
    path = normalize_path(path).rstrip("/") or "/"
    if path == "/nest/entry":
        return "entry" if method in ("GET", "POST") else "unknown"
    if path == "/nest/transport" or path.startswith("/nest/transport/"):
        if method == "POST":
            return "put" if path.endswith("/put") else "subscribe"
        if method == "GET":
            return "object_list"
        return "unknown"
    routes = {
        ("GET", "/nest/ping"): "ping",
        ("GET", "/nest/passphrase"): "passphrase",
        ("POST", "/nest/upload"): "upload",
        ("GET", "/info"): "info",
    }
    if (method, path) in routes:
        return routes[(method, path)]
    if method == "GET" and path.startswith("/nest/pro_info"):
        return "pro_info"
    if method == "GET" and path.startswith("/nest/weather/"):
        return "weather"
    return "unknown"


def clean_serial(value: str | None) -> str | None:
    """Return the cleaned serial, or None if it is not valid."""
    if not value:
        return None
    serial = re.sub(r"[^A-Za-z0-9]", "", value).upper()
    return serial if len(serial) >= 10 else None


def _serial_from_user_id(user_id: str) -> str:
    if "." not in user_id:
        return user_id
    parts = user_id.split(".")
    return parts[1] or parts[0]


def serial_from_request(
    headers: Mapping[str, str],
    query: Mapping[str, str],
    path_serial: str | None = None,
) -> str | None:
    """Get the serial from the first source that has a valid one (section 5)."""
    candidates: list[str | None] = []
    auth = headers.get("Authorization", "")
    if auth[:6].lower() == "basic ":
        try:
            decoded = base64.b64decode(auth[6:].strip()).decode("utf-8", "replace")
        except binascii.Error, ValueError:
            decoded = ""
        candidates.append(_serial_from_user_id(decoded.split(":", 1)[0]))
    client_id = headers.get("X-nl-client-id")
    if client_id:
        candidates.append(_serial_from_user_id(client_id))
    candidates.append(headers.get("X-nl-device-id"))
    candidates.append(headers.get("X-NL-Device-Serial"))
    candidates.append(query.get("serial"))
    candidates.append(path_serial)
    for candidate in candidates:
        if serial := clean_serial(candidate):
            return serial
    return None


def server_is_newer(server_ts: int, client_ts: int) -> bool:
    """Return True if the server copy of a Bucket must go to the Thermostat."""
    if client_ts == 0:
        return True
    if server_ts == 0:
        return False
    return server_ts > client_ts


def wire_object(
    key: str, revision: int, timestamp: int, value: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Return a Bucket in the field order that the Thermostat needs."""
    obj: dict[str, Any] = {
        "object_revision": revision,
        "object_timestamp": timestamp,
        "object_key": key,
    }
    if value is not None:
        obj["value"] = value
    return obj


def parse_put(body: Mapping[str, Any]) -> list[tuple[str, Any, dict[str, Any]]]:
    """Return (key, if_object_revision, data) for each object in a Put body."""
    result: list[tuple[str, Any, dict[str, Any]]] = []
    for name, item in body.items():
        if name == "session":
            continue
        if name == "objects" and isinstance(item, list):
            for obj in item:
                if isinstance(obj, dict) and obj.get("object_key"):
                    value = obj.get("value")
                    data = dict(value) if isinstance(value, dict) else {}
                    result.append(
                        (obj["object_key"], obj.get("if_object_revision"), data)
                    )
            continue
        if isinstance(item, dict) and item.get("object_key"):
            data = {k: v for k, v in item.items() if k not in _PUT_FIELDS}
            result.append((item["object_key"], item.get("if_object_revision"), data))
    return result


def advertised_origin(url: str, port: int) -> str:
    """Return the Advertised URL with an explicit port and no trailing slash."""
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"Not an HTTP URL: {url}")
    host = parts.hostname
    if ":" in host:
        host = f"[{host}]"
    return f"{parts.scheme}://{host}:{parts.port or port}{parts.path.rstrip('/')}"
