"""Tests for the HTTP server (PROTOCOL.md section 14, cases 1 and 4 to 15)."""

import asyncio
import json
import time
from unittest.mock import AsyncMock

from custom_components.nest_local.server import NestServer

from .conftest import AUTH, SERIAL

SHARED = f"shared.{SERIAL}"
DEVICE = f"device.{SERIAL}"


def _docs(raw: bytes) -> list[dict]:
    """Split a body of one or more JSON documents."""
    decoder = json.JSONDecoder()
    text = raw.decode()
    docs, pos = [], 0
    while pos < len(text):
        doc, pos = decoder.raw_decode(text, pos)
        docs.append(doc)
    return docs


async def _wait_for_subscriptions(hub, count: int) -> None:
    for _ in range(100):
        if hub.subscription_count(SERIAL) == count:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("The Subscription did not open")


async def _prime(client) -> None:
    """Send the first subscribe, which gets the user and structure buckets."""
    resp = await client.post(
        "/nest/transport", json={"chunked": False, "objects": []}, headers=AUTH
    )
    assert resp.status == 200


def _store(hub, key: str, value: dict) -> None:
    hub.apply_put(SERIAL, {key: {"object_key": key, **value}})


async def test_entry_urls(client):
    """Test case 1: the URLs have an explicit port and the NLE paths."""
    adv = "http://10.0.0.5:9543"
    for method in ("get", "post"):
        resp = await getattr(client, method)("/entry", data={"model": "Display-2.8"})
        assert resp.status == 200
        body = await resp.json()
        assert body["czfe_url"] == f"{adv}/nest/transport"
        assert body["transport_url"] == f"{adv}/nest/transport"
        assert body["direct_transport_url"] == f"{adv}/nest/transport"
        assert body["passphrase_url"] == f"{adv}/nest/passphrase"
        assert body["ping_url"] == f"{adv}/nest/transport"
        assert body["pro_info_url"] == f"{adv}/nest/pro_info"
        assert body["weather_url"] == f"{adv}/nest/weather/v1?query="
        assert body["upload_url"] == f"{adv}/nest/upload"
        assert body["software_update_url"] == ""
        assert body["tier_name"] == "local"


async def test_entry_stores_facts(client, hub):
    """Test that the /entry form facts go to the device record."""
    await client.post(
        "/entry",
        data={"model": "Display-2.8", "mac": "aabb", "software_version": "5.9"},
        headers=AUTH,
    )
    assert hub.devices[SERIAL].entry["model"] == "Display-2.8"


async def test_subscribe_without_serial(client):
    """Test that subscribe and put without a serial send 400."""
    for path in ("/nest/transport", "/nest/transport/put"):
        resp = await client.post(path, json={"objects": []})
        assert resp.status == 400
        assert await resp.json() == {"error": "Device serial required"}


async def test_not_json(client):
    """Test that a body that is not JSON sends 400."""
    resp = await client.post("/nest/transport", data=b"{bad", headers=AUTH)
    assert resp.status == 400


async def test_subscribe_client_has_no_data(client, hub):
    """Test case 4: client_ts 0 sends the stored bucket at once, then EOF."""
    _store(hub, SHARED, {"target_temperature": 21.0})
    resp = await client.post(
        "/nest/transport",
        json={"chunked": True, "objects": [{"object_key": SHARED}]},
        headers=AUTH,
    )
    assert resp.status == 200
    assert resp.headers["X-nl-suspend-time-max"] == "300"
    assert resp.headers["X-nl-defer-device-window"] == "15"
    assert "X-nl-service-timestamp" in resp.headers
    start = time.monotonic()
    docs = _docs(await resp.read())
    assert time.monotonic() - start < 0.3
    assert len(docs) == 1
    objs = {o["object_key"]: o for o in docs[0]["objects"]}
    assert objs[SHARED]["value"] == {"target_temperature": 21.0}


async def test_held_subscription_gets_push(client, hub):
    """Test case 5: a held Subscription gets the delta, then EOF after the batch."""
    await _prime(client)
    _store(hub, SHARED, {"target_temperature": 21.0, "target_temperature_type": "heat"})
    bucket = hub.devices[SERIAL].buckets[SHARED]
    revision = bucket.revision
    request = {
        "objects": [
            {
                "object_key": SHARED,
                "object_revision": bucket.revision,
                "object_timestamp": bucket.timestamp,
            }
        ]
    }
    task = asyncio.create_task(
        client.post("/nest/transport", json=request, headers=AUTH)
    )
    await _wait_for_subscriptions(hub, 1)
    assert hub.command(SERIAL, {SHARED: {"target_temperature": 22.0}})
    await asyncio.sleep(0.1)
    assert hub.command(SERIAL, {DEVICE: {"fan_timer_timeout": 0}})
    resp = await task
    docs = _docs(await resp.read())
    pushed_at = time.monotonic()
    assert [d["objects"][0]["value"] for d in docs] == [
        {"target_temperature": 22.0},
        {"fan_timer_timeout": 0},
    ]
    assert docs[0]["objects"][0]["object_revision"] == revision + 1
    assert hub.devices[SERIAL].buckets[SHARED].value["target_temperature"] == 22.0
    assert hub.subscription_count(SERIAL) == 0
    assert pushed_at > 0


async def test_batch_window_before_eof(client, hub):
    """Test case 5: EOF comes one batch window after the last chunk."""
    await _prime(client)
    task = asyncio.create_task(
        client.post("/nest/transport", json={"objects": []}, headers=AUTH)
    )
    await _wait_for_subscriptions(hub, 1)
    start = time.monotonic()
    hub.command(SERIAL, {SHARED: {"target_temperature": 22.0}})
    resp = await task
    await resp.read()
    assert time.monotonic() - start >= hub.batch_window


async def test_hold_time_ends_with_no_body(client, hub):
    """Test case 6: the server closes at the hold time with no body."""
    await _prime(client)
    start = time.monotonic()
    resp = await client.post("/nest/transport", json={"objects": []}, headers=AUTH)
    assert resp.status == 200
    assert await resp.read() == b""
    assert time.monotonic() - start >= hub.hold_timeout
    assert hub.subscription_count(SERIAL) == 0


async def test_field_order(client, hub):
    """Test case 7: the response objects use the required field order."""
    _store(hub, SHARED, {"target_temperature": 21.0})
    resp = await client.post(
        "/nest/transport",
        json={"chunked": False, "objects": [{"object_key": SHARED}]},
        headers=AUTH,
    )
    for obj in (await resp.json())["objects"]:
        assert list(obj) == [
            "object_revision",
            "object_timestamp",
            "object_key",
            "value",
        ]


async def test_disable_defer_header(client, hub):
    """Test case 8: the header is present only for a temperature or mode field."""
    await _prime(client)
    _store(hub, DEVICE, {"fan_timer_timeout": 0})
    resp = await client.post(
        "/nest/transport", json={"objects": [{"object_key": DEVICE}]}, headers=AUTH
    )
    await resp.read()
    assert "X-nl-disable-defer-window" not in resp.headers

    _store(hub, SHARED, {"target_temperature": 21.0})
    resp = await client.post(
        "/nest/transport", json={"objects": [{"object_key": SHARED}]}, headers=AUTH
    )
    await resp.read()
    assert resp.headers["X-nl-disable-defer-window"] == "60"


async def _put(client, body: dict) -> list[dict]:
    resp = await client.post("/nest/transport/put", json=body, headers=AUTH)
    assert resp.status == 200
    assert resp.headers["X-nl-suspend-time-max"] == "300"
    return (await resp.json())["objects"]


async def test_put_matching_revision(client, hub):
    """Test case 9: a matching if_object_revision merges and increments."""
    _store(hub, SHARED, {"target_temperature": 21.0, "name": "Hall"})
    old = hub.devices[SERIAL].buckets[SHARED]
    old_rev, old_ts = old.revision, old.timestamp
    await asyncio.sleep(0.01)
    objs = await _put(
        client,
        {
            "session": "s",
            SHARED: {
                "object_key": SHARED,
                "if_object_revision": old_rev,
                "target_temperature": 21.5,
            },
        },
    )
    new = hub.devices[SERIAL].buckets[SHARED]
    assert new.value == {"target_temperature": 21.5, "name": "Hall"}
    assert new.revision == old_rev + 1
    assert new.timestamp > old_ts
    assert objs == [
        {
            "object_revision": new.revision,
            "object_timestamp": new.timestamp,
            "object_key": SHARED,
        }
    ]
    assert list(objs[0]) == ["object_revision", "object_timestamp", "object_key"]


async def test_put_wrong_revision(client, hub):
    """Test case 10: a wrong if_object_revision does not merge."""
    _store(hub, SHARED, {"target_temperature": 21.0})
    bucket = hub.devices[SERIAL].buckets[SHARED]
    objs = await _put(
        client,
        {
            SHARED: {
                "object_key": SHARED,
                "if_object_revision": bucket.revision + 5,
                "target_temperature": 25.0,
            }
        },
    )
    assert hub.devices[SERIAL].buckets[SHARED].value == {"target_temperature": 21.0}
    assert objs == [
        {
            "object_revision": bucket.revision,
            "object_timestamp": bucket.timestamp,
            "object_key": SHARED,
        }
    ]


async def test_put_same_values(client, hub):
    """Test case 11: a Put with the same values changes nothing."""
    _store(hub, DEVICE, {"fan_timer_timeout": 0})
    bucket = hub.devices[SERIAL].buckets[DEVICE]
    rev, ts = bucket.revision, bucket.timestamp
    await asyncio.sleep(0.01)
    await _put(
        client,
        {
            DEVICE: {
                "object_key": DEVICE,
                "base_object_revision": 1,
                "fan_timer_timeout": 0,
            }
        },
    )
    bucket = hub.devices[SERIAL].buckets[DEVICE]
    assert (bucket.revision, bucket.timestamp) == (rev, ts)


async def test_put_objects_form(client, hub):
    """Test that the put also accepts the objects array."""
    await _put(
        client,
        {"objects": [{"object_key": DEVICE, "value": {"current_humidity": 40}}]},
    )
    assert hub.devices[SERIAL].buckets[DEVICE].value == {"current_humidity": 40}


async def test_put_does_not_push(client, hub):
    """Test case 12: a Put does not push to an open Subscription."""
    await _prime(client)
    task = asyncio.create_task(
        client.post("/nest/transport", json={"objects": []}, headers=AUTH)
    )
    await _wait_for_subscriptions(hub, 1)
    await _put(client, {SHARED: {"object_key": SHARED, "target_temperature": 20.0}})
    resp = await task
    assert await resp.read() == b""


async def test_two_subscriptions(client, hub):
    """Test case 13: a command pushes to both Subscriptions."""
    await _prime(client)
    tasks = [
        asyncio.create_task(
            client.post("/nest/transport", json={"objects": []}, headers=AUTH)
        )
        for _ in range(2)
    ]
    await _wait_for_subscriptions(hub, 2)
    hub.command(SERIAL, {SHARED: {"target_temperature": 19.0}})
    for task in tasks:
        resp = await task
        docs = _docs(await resp.read())
        assert docs[0]["objects"][0]["value"] == {"target_temperature": 19.0}


async def test_remove_one_subscription_leaves_the_other(hub):
    """Test case 13: ending one Subscription leaves the other."""
    hub.touch(SERIAL)
    first = hub.add_subscription(SERIAL)
    second = hub.add_subscription(SERIAL)
    hub.remove_subscription(first)
    hub.command(SERIAL, {SHARED: {"target_temperature": 19.0}})
    assert first.queue.empty()
    assert second.queue.get_nowait()[0]["value"] == {"target_temperature": 19.0}


async def test_push_to_reset_connection(client, hub):
    """Test case 14: a push that cannot go out goes to the next Subscription."""
    await _prime(client)
    server = NestServer(hub, "http://10.0.0.5:9543", 9543, "0.1.0")
    response = AsyncMock()
    response.write.side_effect = ConnectionResetError
    subscription = hub.add_subscription(SERIAL)
    hold = asyncio.create_task(server._hold(response, subscription))
    hub.command(SERIAL, {SHARED: {"target_temperature": 18.0}})
    hub.command(SERIAL, {DEVICE: {"fan_timer_timeout": 0}})
    await hold
    hub.remove_subscription(subscription)
    assert len(hub.devices[SERIAL].pending) == 2

    resp = await client.post("/nest/transport", json={"objects": []}, headers=AUTH)
    docs = _docs(await resp.read())
    assert [o["value"] for o in docs[0]["objects"]] == [
        {"target_temperature": 18.0},
        {"fan_timer_timeout": 0},
    ]
    assert hub.devices[SERIAL].pending == []


async def test_closed_connection_ends_the_subscription(client, hub):
    """Test that a closed connection removes its Subscription."""
    await _prime(client)
    task = asyncio.create_task(
        client.post("/nest/transport", json={"objects": []}, headers=AUTH)
    )
    await _wait_for_subscriptions(hub, 1)
    (await task).close()
    await _wait_for_subscriptions(hub, 0)


async def test_user_and_structure_buckets(client, hub):
    """Test case 15: the first subscribe gets user and structure with known IDs."""
    request = {
        "chunked": False,
        "objects": [
            {"object_key": "user.123", "object_revision": 4, "object_timestamp": 1},
            {
                "object_key": "structure.abc",
                "object_revision": 4,
                "object_timestamp": 1,
            },
        ],
    }
    resp = await client.post("/nest/transport", json=request, headers=AUTH)
    objs = {o["object_key"]: o for o in (await resp.json())["objects"]}
    assert objs["user.123"]["value"] == {"name": "123"}
    assert objs["structure.abc"]["value"] == {"name": "Home", "devices": [SERIAL]}
    assert hub.devices[SERIAL].user_id == "123"
    assert hub.devices[SERIAL].structure_id == "abc"

    resp = await client.post(
        "/nest/transport", json={"chunked": False, "objects": []}, headers=AUTH
    )
    assert (await resp.json())["objects"] == []


async def test_default_user_and_structure(client, hub):
    """Test case 15: with no keys in the request, the default IDs are used."""
    resp = await client.post(
        "/nest/transport", json={"chunked": False, "objects": []}, headers=AUTH
    )
    keys = [o["object_key"] for o in (await resp.json())["objects"]]
    assert keys == ["user.nest_local", "structure.default"]


async def test_subscribe_merges_newer_client_value(client, hub):
    """Test that a newer client value merges with the client revision."""
    _store(hub, DEVICE, {"a": 1})
    ts = hub.devices[SERIAL].buckets[DEVICE].timestamp + 1000
    request = {
        "chunked": False,
        "objects": [
            {
                "object_key": DEVICE,
                "object_revision": 9,
                "object_timestamp": ts,
                "value": {"b": 2},
            }
        ],
    }
    await client.post("/nest/transport", json=request, headers=AUTH)
    bucket = hub.devices[SERIAL].buckets[DEVICE]
    assert bucket.value == {"a": 1, "b": 2}
    assert (bucket.revision, bucket.timestamp) == (9, ts)


async def test_other_routes(client, hub):
    """Test the small Routes in section 8."""
    _store(hub, SHARED, {"x": 1})
    resp = await client.get(f"/nest/transport/device/{SERIAL}")
    objs = (await resp.json())["objects"]
    assert objs[0]["object_key"] == SHARED
    assert "value" not in objs[0]

    body = await (await client.get("/nest/passphrase", headers=AUTH)).json()
    assert len(body["value"]) == 7
    assert body["expires"] > time.time() * 1000 + 30 * 60 * 1000
    again = await (await client.get("/nest/passphrase", headers=AUTH)).json()
    assert again["value"] == body["value"]

    assert (await (await client.get("/nest/ping")).json())["status"] == "ok"
    assert (await (await client.get("/nest/weather/v1?postal_code=1")).json()) == {}
    upload = await client.post("/nest/upload", data=b"log")
    assert await upload.json() == {"status": "ok"}
    pro = await (await client.get("/nest/pro_info/42")).json()
    assert pro["pro_id"] == "42"
    info = await (await client.get("/info")).json()
    assert info["cloudregisterurl"] == "http://10.0.0.5:9543/entry"
    assert info["port"] == 9543
    unknown = await client.get("/nothing")
    assert unknown.status == 200
    assert await unknown.json() == {}
