"""The Bucket store and the Subscriptions. This module does not use Home Assistant.

The hub keeps all Buckets for each Thermostat, merges the writes from the
Thermostat and from Home Assistant, and pushes commands to the held
Subscriptions. The HTTP server and the entities both use it.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import secrets
import string
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .const import (
    AVAILABLE_WINDOW,
    BATCH_WINDOW,
    DEFAULT_STRUCTURE_ID,
    DEFAULT_USER_ID,
    HOLD_TIMEOUT,
)
from .protocol import now_ms, parse_put, server_is_newer, wire_object

_LOGGER = logging.getLogger(__name__)

_PASSPHRASE_LIFE_MS = 60 * 60 * 1000
_PASSPHRASE_EXPIRES_MS = 90 * 60 * 1000
_REQUEST_FIELDS = ("objects", "session", "chunked")


@dataclass
class Bucket:
    """One Bucket of Thermostat state."""

    revision: int
    timestamp: int
    value: dict[str, Any]


@dataclass
class Subscription:
    """One held Subscribe connection. The value None on the queue closes it."""

    serial: str
    id: int
    queue: asyncio.Queue[list[dict[str, Any]] | None] = field(
        default_factory=asyncio.Queue
    )


@dataclass
class DeviceRecord:
    """All the data that the Integration keeps for one Thermostat."""

    serial: str
    buckets: dict[str, Bucket] = field(default_factory=dict)
    user_id: str | None = None
    structure_id: str | None = None
    entry: dict[str, str] = field(default_factory=dict)
    last_seen: float | None = None
    pending: list[dict[str, Any]] = field(default_factory=list)


def _request_objects(body: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return the request objects of a subscribe body, in both formats."""
    objects = [
        obj
        for obj in body.get("objects") or []
        if isinstance(obj, dict) and obj.get("object_key")
    ]
    for name, item in body.items():
        if (
            name not in _REQUEST_FIELDS
            and isinstance(item, dict)
            and item.get("object_key")
        ):
            objects.append(item)
    return objects


class NestHub:
    """Keep the Buckets and the Subscriptions of all Thermostats."""

    def __init__(
        self,
        hold_timeout: float = HOLD_TIMEOUT,
        batch_window: float = BATCH_WINDOW,
    ) -> None:
        """Initialize the hub."""
        self.hold_timeout = hold_timeout
        self.batch_window = batch_window
        self.devices: dict[str, DeviceRecord] = {}
        self.on_save: Callable[[], None] | None = None
        self.last_entry: dict[str, str] = {}
        self._subscriptions: dict[str, dict[int, Subscription]] = {}
        self._ids = itertools.count(1)
        self._listeners: list[Callable[[str], None]] = []
        # This set is in memory only, so it resets when Home Assistant restarts.
        self._extras_sent: set[tuple[str, str]] = set()
        self._passphrases: dict[str, tuple[str, int]] = {}

    # Storage.

    def load(self, data: Mapping[str, Any] | None) -> None:
        """Load the records from the stored data."""
        for serial, raw in ((data or {}).get("devices") or {}).items():
            record = DeviceRecord(
                serial=serial,
                user_id=raw.get("user_id"),
                structure_id=raw.get("structure_id"),
                entry=dict(raw.get("entry") or {}),
            )
            for key, bucket in (raw.get("buckets") or {}).items():
                record.buckets[key] = Bucket(
                    int(bucket["object_revision"]),
                    int(bucket["object_timestamp"]),
                    dict(bucket["value"]),
                )
            self.devices[serial] = record

    def as_dict(self) -> dict[str, Any]:
        """Return the data to store."""
        return {
            "devices": {
                serial: {
                    "buckets": {
                        key: {
                            "object_revision": bucket.revision,
                            "object_timestamp": bucket.timestamp,
                            "value": bucket.value,
                        }
                        for key, bucket in record.buckets.items()
                    },
                    "user_id": record.user_id,
                    "structure_id": record.structure_id,
                    "entry": record.entry,
                }
                for serial, record in self.devices.items()
            }
        }

    # Listeners.

    def add_listener(self, listener: Callable[[str], None]) -> Callable[[], None]:
        """Call the listener with the serial after each change."""
        self._listeners.append(listener)

        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove

    def notify_all(self) -> None:
        """Call the listeners for all serials, for example to update availability."""
        for serial in list(self.devices):
            self._notify(serial)

    def _notify(self, serial: str) -> None:
        for listener in list(self._listeners):
            listener(serial)

    def _changed(self, serial: str, save: bool = True) -> None:
        if save and self.on_save is not None:
            self.on_save()
        self._notify(serial)

    # Records.

    def touch(self, serial: str) -> DeviceRecord:
        """Return the record for the serial, and record the contact time."""
        record = self.devices.get(serial)
        if record is None:
            record = DeviceRecord(serial=serial, entry=dict(self.last_entry))
            self.devices[serial] = record
            _LOGGER.info("New Thermostat %s", serial)
        record.last_seen = time.monotonic()
        return record

    def available(self, serial: str) -> bool:
        """Return True if the Thermostat called in the availability window."""
        record = self.devices.get(serial)
        if record is None or record.last_seen is None:
            return False
        return time.monotonic() - record.last_seen < AVAILABLE_WINDOW

    def set_entry(self, serial: str | None, facts: dict[str, str]) -> None:
        """Keep the /entry form facts for the device info."""
        self.last_entry = facts
        if serial is not None:
            self.touch(serial).entry = facts
            self._changed(serial)

    def _merge(
        self, record: DeviceRecord, key: str, data: Mapping[str, Any], now: int
    ) -> bool:
        """Merge the data into a Bucket (PROTOCOL.md section 7.3)."""
        bucket = record.buckets.get(key)
        if bucket is None:
            record.buckets[key] = Bucket(1, now, dict(data))
            return True
        merged = {**bucket.value, **data}
        if merged == bucket.value:
            return False
        bucket.value = merged
        bucket.revision += 1
        # The timestamp must go up, also for two changes in one millisecond.
        bucket.timestamp = max(now, bucket.timestamp + 1)
        return True

    # The Thermostat writes.

    def apply_put(self, serial: str, body: Mapping[str, Any]) -> list[dict[str, Any]]:
        """Apply a Put and return the response objects (section 7)."""
        record = self.touch(serial)
        now = now_ms()
        changed = False
        result: list[dict[str, Any]] = []
        for key, if_revision, data in parse_put(body):
            if not data:
                _LOGGER.warning("Put for %s has no data", key)
                continue
            bucket = record.buckets.get(key)
            server_revision = bucket.revision if bucket else 0
            if if_revision is not None and if_revision != server_revision:
                _LOGGER.debug(
                    "Put conflict for %s: %s is not %s",
                    key,
                    if_revision,
                    server_revision,
                )
                result.append(
                    wire_object(key, server_revision, bucket.timestamp if bucket else 0)
                )
                continue
            changed |= self._merge(record, key, data, now)
            bucket = record.buckets[key]
            result.append(wire_object(key, bucket.revision, bucket.timestamp))
        self._changed(serial, save=changed)
        return result

    def subscribe_objects(
        self, serial: str, body: Mapping[str, Any]
    ) -> list[dict[str, Any]]:
        """Process a subscribe body and return the objects to send now (section 6)."""
        record = self.touch(serial)
        now = now_ms()
        changed = False
        send: list[dict[str, Any]] = []
        sent_keys: set[str] = set()
        requested = _request_objects(body)
        for obj in requested:
            key = obj["object_key"]
            client_rev = int(obj.get("object_revision") or 0)
            client_ts = int(obj.get("object_timestamp") or 0)
            value = obj.get("value")
            if isinstance(value, dict) and not client_rev and not client_ts:
                changed |= self._merge(record, key, value, now)
            bucket = record.buckets.get(key)
            if bucket is None:
                # Do not send a placeholder (PROTOCOL.md gap 8).
                if client_ts > 0 and isinstance(value, dict):
                    record.buckets[key] = Bucket(client_rev, client_ts, dict(value))
                    changed = True
                continue
            if server_is_newer(bucket.timestamp, client_ts):
                send.append(
                    wire_object(key, bucket.revision, bucket.timestamp, bucket.value)
                )
                sent_keys.add(key)
            elif client_ts > bucket.timestamp and isinstance(value, dict):
                bucket.value = {**bucket.value, **value}
                bucket.revision = client_rev
                bucket.timestamp = client_ts
                changed = True

        changed |= self._add_extras(record, requested, send, sent_keys, now)
        if record.pending:
            send.extend(record.pending)
            record.pending = []
        self._changed(serial, save=changed)
        return send

    def _add_extras(
        self,
        record: DeviceRecord,
        requested: list[dict[str, Any]],
        send: list[dict[str, Any]],
        sent_keys: set[str],
        now: int,
    ) -> bool:
        """Add the user and structure Buckets (PROTOCOL.md section 6.5)."""
        for obj in requested:
            bucket_type, _, bucket_id = obj["object_key"].partition(".")
            if bucket_type == "user" and bucket_id:
                record.user_id = bucket_id
            elif bucket_type == "structure" and bucket_id:
                record.structure_id = bucket_id
        record.user_id = record.user_id or DEFAULT_USER_ID
        record.structure_id = record.structure_id or DEFAULT_STRUCTURE_ID
        changed = False
        extras = (
            (f"user.{record.user_id}", {"name": record.user_id}),
            (
                f"structure.{record.structure_id}",
                {"name": "Home", "devices": [record.serial]},
            ),
        )
        for key, initial in extras:
            if key not in record.buckets:
                record.buckets[key] = Bucket(1, now, initial)
                changed = True
            if key not in sent_keys and (record.serial, key) not in self._extras_sent:
                bucket = record.buckets[key]
                send.append(
                    wire_object(key, bucket.revision, bucket.timestamp, bucket.value)
                )
                sent_keys.add(key)
            if key in sent_keys:
                self._extras_sent.add((record.serial, key))
        return changed

    # Home Assistant writes.

    def command(self, serial: str, deltas: Mapping[str, Mapping[str, Any]]) -> bool:
        """Store and push the deltas. Return False if nothing changed (section 9.1)."""
        record = self.devices.get(serial)
        if record is None:
            return False
        now = now_ms()
        objects: list[dict[str, Any]] = []
        for key, delta in deltas.items():
            bucket = record.buckets.get(key)
            if not delta or (
                bucket is not None
                and all(
                    name in bucket.value and bucket.value[name] == value
                    for name, value in delta.items()
                )
            ):
                continue
            self._merge(record, key, delta, now)
            bucket = record.buckets[key]
            objects.append(
                wire_object(key, bucket.revision, bucket.timestamp, dict(delta))
            )
        if not objects:
            _LOGGER.debug("Command for %s changes nothing", serial)
            return False
        _LOGGER.debug("Command for %s: %s", serial, objects)
        self.push(serial, objects)
        self._changed(serial)
        return True

    # Subscriptions.

    def add_subscription(self, serial: str) -> Subscription:
        """Register a new Subscription for the serial."""
        subscription = Subscription(serial=serial, id=next(self._ids))
        subscriptions = self._subscriptions.setdefault(serial, {})
        if subscriptions:
            _LOGGER.debug(
                "Thermostat %s has %d other Subscriptions",
                serial,
                len(subscriptions),
            )
        subscriptions[subscription.id] = subscription
        return subscription

    def remove_subscription(self, subscription: Subscription) -> None:
        """Remove one Subscription."""
        self._subscriptions.get(subscription.serial, {}).pop(subscription.id, None)

    def subscription_count(self, serial: str) -> int:
        """Return the number of open Subscriptions for the serial."""
        return len(self._subscriptions.get(serial, {}))

    def push(self, serial: str, objects: list[dict[str, Any]]) -> None:
        """Put the objects on the queue of each Subscription of the serial."""
        for subscription in self._subscriptions.get(serial, {}).values():
            subscription.queue.put_nowait(list(objects))

    def add_pending(self, serial: str, objects: list[dict[str, Any]]) -> None:
        """Keep objects that did not go out for the next Subscription."""
        if serial in self.devices:
            self.devices[serial].pending.extend(objects)

    def close_all(self) -> None:
        """Tell all held Subscriptions to close."""
        for subscriptions in self._subscriptions.values():
            for subscription in subscriptions.values():
                subscription.queue.put_nowait(None)

    # Passphrase.

    def passphrase(self, serial: str | None) -> tuple[str, int]:
        """Return the entry key and its expiry time in ms (section 8.2)."""
        now = now_ms()
        code, created = self._passphrases.get(serial or "", ("", 0))
        if not code or now - created > _PASSPHRASE_LIFE_MS:
            alphabet = string.ascii_uppercase + string.digits
            code = "".join(secrets.choice(alphabet) for _ in range(7))
            created = now
            self._passphrases[serial or ""] = (code, created)
        return code, created + _PASSPHRASE_EXPIRES_MS
