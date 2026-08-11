# Protocol Transport Contract

Distilled from `cjserio/nest-thermostat-protocol-docs` revision 2.9 (2026-02-25, MIT).
The reference is 2,873 lines documenting the Nest cloud protocol against real gen 2
hardware. This contract covers everything a server implementation needs.

**Source**: `NEST_CLOUD_PROTOCOL_REFERENCE.md` in the `cjserio/nest-thermostat-protocol-docs`
repository. All section/line references below are to that file unless otherwise noted.

---

## 1. Routes the Thermostat Calls

The Thermostat initiates all connections. The Integration must serve these three Routes
plus one ancillary Route for pairing.

| Route | Method | Content-Type | Purpose | Ref |
|-------|--------|-------------|---------|-----|
| `POST /entry` | POST | `application/x-www-form-urlencoded` | Initial registration. Returns the `transport_url` for all subsequent communication. | Lines 387-473 |
| `POST /{czid}/subscribe` | POST | `application/json` | Long-poll for server-to-device pushes. The Thermostat holds the connection open and sleeps; the server pushes data or closes to drive the reconnect cycle. | Lines 125-243 |
| `POST /{czid}/put` | POST | `application/json` | Device-to-server state updates. The Thermostat sends local state changes. | Lines 246-383 |
| `GET {passphrase_url}` | GET | N/A | Entry key fetch for device pairing. The `passphrase_url` is returned in the `/entry` response. | Lines 546-580 |

The `{czid}` path segment is opaque to the protocol; the Thermostat uses whatever
`transport_url` it received from `/entry` and appends `/subscribe` or `/put`. The
server can use it for routing but must not require a specific value.

**Source**: Lines 122-124, 387-473, 125-243, 246-383.

---

## 2. Request and Response Shapes

### 2.1 POST /entry

#### Request

```http
POST /entry HTTP/1.1
Content-Type: application/x-www-form-urlencoded
Authorization: Basic <base64(userid:password)>

reset=FALSE&mac=18B430ABCDEF&model=Diamond-2.6&request_id=1&software_version=5.9.3-5&wireless_reg_domain=US&backplate_model=Backplate-2.1
```

**Request headers**:

| Header | Required | Notes |
|--------|----------|-------|
| `Authorization` | Yes (production firmware) | HTTP Basic Auth. User ID format: `d.{SERIAL}.{suffix}`. Always present on production firmware. | 
| `Content-Type` | Yes | Must be `application/x-www-form-urlencoded`. |
| `X-nl-device-id` | No | Bare serial. Non-production only. Fallback if no `Authorization`. |

**Source**: Lines 397-411.

**Request body fields** (form-urlencoded):

| Field | Required | Description |
|-------|----------|-------------|
| `reset` | Yes | `TRUE` after factory reset, `FALSE` otherwise. |
| `mac` | Yes | WiFi MAC address, 12 hex chars, no separators. |
| `model` | Yes | Model string (e.g. `Diamond-2.6`, `Flintstone-4.0`). |
| `request_id` | Yes | Monotonically increasing counter. |
| `software_version` | Yes | Firmware version (e.g. `5.9.3-5`). |
| `wireless_reg_domain` | No | WiFi regulatory domain (e.g. `US`). |
| `backplate_model` | No | Backplate model string. |

**Source**: Lines 414-423.

#### Response

```http
HTTP/1.1 200 OK
Content-Type: application/json

{
  "transport_url": "https://your-server.example.com:443"
}
```

**Response body fields**:

| Field | Required | Description |
|-------|----------|-------------|
| `transport_url` | Yes | Base URL for all subsequent calls. **Must include explicit port.** |
| `passphrase_url` | No | Entry key endpoint for pairing. |
| `ping_url` | No | Connectivity check endpoint. |
| `weather_url` | No | Weather data endpoint. |
| `upload_url` | No | Device log upload endpoint. |

**Response headers**:

| Header | Required | Description |
|--------|----------|-------------|
| `X-nl-set-client-credentials` | No | Provisions credentials as `"userid password"`. |

**Error codes**: 200 success, 302 redirect (follow), 401 retry with backoff, 5xx retry with backoff.

**Source**: Lines 426-473.

---

### 2.2 POST /{czid}/subscribe

#### Request

```http
POST /{czid}/subscribe HTTP/1.1
Content-Type: application/json
X-nl-protocol-version: 1
Authorization: Basic <base64(userid:password)>

{
  "chunked": true,
  "session": "18b430deadbeefSERIAL",
  "objects": [
    {"object_key": "device.SERIAL", "object_revision": 3, "object_timestamp": 1707148800000},
    {"object_key": "shared.SERIAL", "object_revision": 2, "object_timestamp": 1707148800000}
  ]
}
```

**Request headers**:

| Header | Required | Notes |
|--------|----------|-------|
| `X-nl-protocol-version` | Yes | Always `1`. |
| `Authorization` | Yes (production) | Basic Auth with `d.{SERIAL}.{suffix}` user ID. |
| `X-nl-device-swversion` | No | Software version string. |
| `X-nl-longest-wake` | No | Vestigial. Safe to ignore. |
| `X-nl-client-id` | No | Non-production only. |

**Source**: Lines 148-155.

**Request body fields**:

| Field | Type | Description |
|-------|------|-------------|
| `chunked` | boolean | Always `true`. |
| `session` | string | Device-scoped session ID. Reused across requests; **not** a unique subscription key. |
| `objects` | array | Current bucket state descriptors. |
| `objects[].object_key` | string | Bucket identifier (e.g. `device.09AA01AB12345678`). |
| `objects[].object_revision` | integer | Current revision for this bucket. |
| `objects[].object_timestamp` | integer | Milliseconds since Unix epoch. |

**Source**: Lines 158-169.

> **Critical**: The `objects` array format is the only format production firmware uses.
> Earlier documentation showed bucket data as top-level keys; that format is incorrect.
> (Line 169)

#### Response

```http
HTTP/1.1 200 OK
Transfer-Encoding: chunked
X-nl-suspend-time-max: 300
X-nl-service-timestamp: 1707148800000

{"objects": [{"object_revision": 458, "object_timestamp": 1707148800000, "object_key": "shared.SERIAL", "value": {"target_temperature": 22.00000}}]}
```

**Response headers** (required):

| Header | Required | Description |
|--------|----------|-------------|
| `Transfer-Encoding` | Yes | Must be `chunked`. |
| `X-nl-suspend-time-max` | Yes | Max seconds before device reconnects (recommended: 300). |
| `X-nl-service-timestamp` | Recommended | Server timestamp in milliseconds since epoch. |

**Response headers** (optional):

| Header | Description |
|--------|-------------|
| `X-nl-set-client-credentials` | Provision device credentials as `"userid password"`. |
| `X-nl-defer-device-window` | Delay (seconds) for device-initiated PUT batching. Max 3599. Recommended 15-30. |
| `X-nl-disable-defer-window` | Suppress defer delay for N seconds. Max 3599. |

**Source**: Lines 183-192, 951-1028.

**Response body**: JSON with an `objects` array. Each object contains:

| Field | Type | Description |
|-------|------|-------------|
| `object_revision` | integer | Updated revision. |
| `object_timestamp` | integer | Milliseconds since Unix epoch. |
| `object_key` | string | Bucket identifier. |
| `value` | object | The bucket data fields. |

To indicate no updates: hold the connection open without sending body data. Do not
send an empty object.

**Source**: Lines 196-234.

**Error codes**: 200 success, 401 re-authenticate, 5xx retry with backoff.

---

### 2.3 POST /{czid}/put

#### Request

```http
POST /{czid}/put HTTP/1.1
Content-Type: application/json
X-nl-protocol-version: 1
Authorization: Basic <base64(userid:password)>

{
  "session": "session_id",
  "shared.09AB1234": {
    "object_key": "shared.09AB1234",
    "base_object_revision": 457,
    "target_temperature": 21.5,
    "target_temperature_type": "heat"
  }
}
```

**Request headers**: Same as subscribe (`X-nl-protocol-version: 1`, `Authorization`).

**Request body**: Top-level keys are bucket identifiers. Each bucket object contains:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `session` | string | Yes | Session identifier. |
| `{bucket_key}` | object | Yes | One or more bucket objects keyed by identifier. |
| `object_key` | string | Yes | Matches the parent key. |
| `base_object_revision` | integer | Yes (most buckets) | Revision this update is based on. Informational only. |
| `if_object_revision` | integer | Conditional | Conditional write guard. Used only by the `shared` bucket. |
| `{field}` | varies | Yes | Data fields being updated. |

**Source**: Lines 278-307.

> **Note**: PUT request format differs from subscribe response format. PUT uses
> top-level bucket keys with inline fields. Subscribe wraps in `objects` array with
> nested `value`. (Lines 216-217)

#### Response

The PUT response is a **write receipt, not a data channel**. Return only
`{object_revision, object_timestamp, object_key}`. **Never include a `value` field.**

If the server includes `value` in the PUT response, the Thermostat applies every field
as authoritative cloud data with no per-key staleness check, silently overwriting any
local state the device has updated since the PUT was sent. This includes CAS conflict
responses.

**Source**: Lines 326-331, changelog rev 2.4.

**Error codes**: 200 success, 400 retry up to 2 times (3 total), 401 re-authenticate,
5xx retry with backoff.

**Source**: Lines 333-340.

---

### 2.4 GET {passphrase_url} (Entry Key)

#### Request

```http
GET {passphrase_url} HTTP/1.1
X-NL-Device-ID: 09AA01AB12345678
```

#### Response

```json
{
  "value": "123ABCD",
  "expires": 1707148800000
}
```

| Field | Type | Constraint |
|-------|------|------------|
| `value` | string | 7-character alphanumeric code. Device displays as `XXX-XXXX`. |
| `expires` | **number** | **Must be a JSON number, not a string.** Milliseconds since epoch. Must be at least 30 minutes in the future. |

If `expires` is sent as a string, the Thermostat silently rejects the response and
never displays the entry key.

The Thermostat polls this endpoint repeatedly until pairing completes. Return the same
unexpired key on each request.

**Source**: Lines 542-580.

---

## 3. Bucket Model and Object Types

### 3.1 Bucket Structure

State is organized into named data containers called buckets. Every bucket has:
- `object_key`: format `{type}.{identifier}` (e.g. `shared.09AB1234`)
- `object_revision`: monotonically increasing int32, incremented on each write
- `object_timestamp`: int64 milliseconds since Unix epoch

**Source**: Lines 1172-1177.

### 3.2 All Bucket Types (28 Total)

| Bucket | Object Key | Direction | Priority |
|--------|-----------|-----------|----------|
| `device` | `device.{serial}` | Bidirectional (restricted) | Essential |
| `shared` | `shared.{serial}` | Bidirectional | Essential |
| `structure` | `structure.{structureId}` | Server -> device | Essential |
| `user` | `user.{userId}` | Server -> device | Essential |
| `schedule` | `schedule.{serial}` | Bidirectional (guarded) | Essential |
| `where` | `where.{whereId}` | Bidirectional | Secondary |
| `message` | `message.{messageId}` | Bidirectional | Secondary |
| `link` | `link.{linkId}` | Server -> device | Secondary |
| `custom_schedule` | `custom_schedule.{id}` | Bidirectional | Secondary |
| `device_alert_dialog` | `device_alert_dialog.{id}` | Server -> device | Secondary |
| `hvac_partner` | `hvac_partner.{partnerId}` | Bidirectional | Specialized |
| `topaz` | `topaz.{topazId}` | Server -> device | Specialized |
| `kryptonite` | `kryptonite.{sensorId}` | Bidirectional | Specialized |
| `servicegroup` | `servicegroup.{id}` | Server -> device | Specialized |
| `occupancy` | `occupancy.{serial}` | Device -> server | Specialized |
| `demand_response` | `demand_response.{id}` | Bidirectional | Specialized |
| `demand_response_event` | `demand_response_event.{eventId}` | Bidirectional | Specialized |
| `utility` | `utility.{id}` | Server -> device | Specialized |
| `diamond_sensor_config` | `diamond_sensor_config.{id}` | Server -> device | Specialized |
| `diamond_sensor_event` | `diamond_sensor_event.{id}` | Bidirectional | Specialized |
| `rate_plan` | `rate_plan.{id}` | Server -> device | Specialized |
| `tou` | `tou.{id}` | Bidirectional | Specialized |
| `demand_charge` | `demand_charge.{id}` | Server -> device | Specialized |
| `demand_charge_event` | `demand_charge_event.{eventId}` | Bidirectional | Specialized |
| `rcs_settings` | `rcs_settings.{id}` | Bidirectional | Specialized |
| `cloud_algo` | `cloud_algo.{id}` | Bidirectional | Specialized |
| `diagnostics` | `diagnostics.{id}` | Bidirectional | Specialized |
| `tuneups` | `tuneups.{id}` | Bidirectional | Specialized |

**Direction key**:
- **Server -> device**: Pushed on subscribe. Device never PUTs.
- **Device -> server**: Device sends via PUT. Server stores.
- **Bidirectional**: Both sides read and write. Some have per-field restrictions.

**Source**: Lines 1180-1220.

### 3.3 Essential Bucket Details

#### device bucket

- 239 registered fields total.
- Object key: `device.{serial}`
- Revision type: `base_object_revision` (unconditional)
- Three access modes per field: device-only (113), special (23), cloud-writable (103).

**Source**: Lines 1221-1398.

#### shared bucket

- Primary thermostat control bucket.
- Object key: `shared.{serial}`
- **Only bucket that uses conditional writes** (`if_object_revision`). Server must
  reject writes when revision doesn't match.
- Key fields: `target_temperature`, `target_temperature_high`, `target_temperature_low`,
  `target_temperature_type`, `target_change_pending`, `schedule_mode`, `touched_by`,
  plus all `hvac_*_state` booleans (read-only) and `can_heat`/`can_cool` (read-only).

**Source**: Lines 1399-1501.

#### structure bucket

- Object key: `structure.{structureId}`
- Direction: Server -> device only.
- Key fields: `away`, `manual_eco_all`, `manual_eco_timestamp`, `name`, `devices`.
- The Thermostat does **not** subscribe to this bucket by default; the server must
  proactively include it in subscribe responses. Once delivered, the Thermostat
  remembers and requests it thereafter.

**Source**: Lines 1549-1575.

#### user bucket

- Object key: `user.{userId}`
- Direction: Server -> device only.
- Exists solely to trigger pairing. The `name` field completes pairing.

**Source**: Lines 1576-1586.

#### schedule bucket

- Object key: `schedule.{serial}`
- Direction: Bidirectional, subject to sync guards.
- Revision type: `base_object_revision` (unconditional).
- The Thermostat subscribes to this bucket automatically.

**Source**: Lines 1587-1593.

---

## 4. Per-Field Access Modes (device bucket)

| Mode | Count | Server Can Write? | In PUT? | Description |
|------|-------|-------------------|---------|-------------|
| Device-only | 113 | **No** -- device rejects and overwrites | Yes | Hardware state, sensors, computed values |
| Special | 23 | Varies | No | Custom processing (eco, HVAC capacities) |
| Cloud-writable | 103 | **Yes** | Yes | Configuration the server can push |

**Source**: Lines 1229-1238.

### Key Read-Only Fields (device reports, server stores)

| Field | Type | Bucket | Description |
|-------|------|--------|-------------|
| `current_temperature` | float | shared | Current temperature (Celsius) |
| `current_humidity` | integer | device | Relative humidity (%) |
| `backplate_temperature` | float | device | Backplate temperature (Celsius) |
| `battery_level` | float | device | Battery charge level |
| `has_fan` | boolean | device | Fan control available |
| `has_humidifier` | boolean | device | Humidifier detected |
| `has_dehumidifier` | boolean | device | Dehumidifier detected |
| `leaf` | boolean | device | Leaf icon (energy-saving) |
| `auto_away` | integer | shared | Occupancy: 0=home, 1=away |
| `time_to_target` | integer | device | Seconds to reach target |
| `serial_number` | string | device | Device serial |
| `current_version` | string | device | Firmware version |
| `model_version` | string | device | Hardware model |
| `local_ip` | string | device | Device LAN IP |
| `mac_address` | string | device | WiFi MAC |

**Source**: Lines 1239-1264.

### Cloud-Writable Field Categories

The reference documents ~103 cloud-writable fields organized by category. Key categories:

- **Temperature settings**: `away_temperature_high/low`, `temperature_scale`, safety temps
- **Temperature lock**: `temperature_lock`, bounds, PIN hash
- **Fan settings**: `fan_mode`, `fan_timer_duration`, `fan_timer_timeout`, duty cycle, speeds
- **Eco/away**: `auto_away_enable`, `auto_away_reset`, `home_away_input`
- **Humidity control**: `target_humidity`, humidifier/dehumidifier config
- **Heat pump / dual fuel**: breakpoints, thresholds, compressor lockout
- **Learning and scheduling**: `learning_mode`, `preconditioning_enabled`
- **Hot water** (EU/UK): mode, boost, temperature
- **Device config**: `click_sound`, `farsight_screen`, `ob_orientation`, `where_id`
- **Filter reminders**: dates, threshold
- **HVAC wiring**: ~24 source/delivery fields
- **Setup wizard**: `oob_*` completed flags

**Source**: Lines 1265-1398.

### Write Protection Behavior

If the server pushes a value for any device-only field, the Thermostat compares it
against local state. If different, it marks the field dirty and re-sends its own value
in the next PUT. Twelve fields have explicit consistency checking and logging:
`heat_link_connection`, `error_code`, `wiring_error`, `auto_dehum_state`,
`away_temperature_low_adjusted`, `away_temperature_high_adjusted`, `dehumidifier_state`,
`demand_charge_icon`, `fan_control_state`, `fan_cooling_state`, `humidifier_state`, `tou_icon`.

**Source**: Lines 1723-1732.

### Safety Fields

When any safety-related field changes, the Thermostat forces four additional fields into
the PUT: `battery_level`, `safety_temp_activating_hvac`, `safety_state`, `safety_state_time`.

**Source**: Lines 1734-1736.

---

## 5. Shared Bucket -- Conditional Write Semantics

The `shared` bucket is the **only** bucket that uses `if_object_revision` in PUT
requests. When the Thermostat sends a PUT with `if_object_revision`, the server must
reject the write if the revision doesn't match the server's current stored revision.
All other buckets use `base_object_revision` (informational, no validation).

**Source**: Lines 1399-1407.

---

## 6. State-Interaction Matrix

The Thermostat's state is four independent dimensions:

| Dimension | Bucket | Key Field | Server-Writable? |
|-----------|--------|-----------|-------------------|
| HVAC mode | shared | `target_temperature_type` | Yes |
| Temperature setpoint | shared | `target_temperature` (+ variants) | Yes |
| Eco mode | structure | `manual_eco_all` | Yes |
| HVAC operation | shared | `hvac_*_state` fields | No (read-only) |

### State-Action Matrix

| Server Action | HVAC Mode | Temperature Source | Eco Mode | HVAC Runs? |
|--------------|-----------|-------------------|----------|------------|
| Set `target_temperature_type` to `"heat"` | -> Heat | Schedule or manual setpoint | Unchanged | If below setpoint |
| Set `target_temperature_type` to `"off"` | -> Off | -- | Unchanged | No |
| Set `manual_eco_all` to `true` | Unchanged | -> Eco temperatures | -> Manual-eco | Only outside eco band |
| Set `manual_eco_all` to `false` | Unchanged | -> Schedule setpoint (fresh lookup) | -> Schedule | If below/above setpoint |
| Push a new schedule | Unchanged | Updated for future transitions | Unchanged | Recalculated |
| Safety threshold crossed | Overridden | Overridden | Overridden | Forced on |
| Emergency mode set | -> Emergency | Manual setpoint | Unchanged | Emergency heat |
| User turns dial | Unchanged | -> Manual setpoint | Eco reverts to schedule | Recalculated |

**Source**: Lines 2136-2148.

### Eco Mode Feature Interactions

| Feature | Normal | During Eco |
|---------|--------|------------|
| Preconditioning | Runs normally | **Blocked** (manual-eco only) |
| Schedule following | Active | Timer continues; HVAC uses eco temps |
| Learning | Active | Paused |
| Safety temperature | Active | Active -- overrides eco |
| Fan timer | Active | Active |

**Source**: Lines 2150-2161.

---

## 7. Framing Rules the Reference Flags as Load-Bearing

### 7.1 JSON Field Ordering

**`object_revision` and `object_timestamp` MUST appear BEFORE `object_key` in all
response JSON objects.** Incorrect ordering causes parsing failures, sync issues, or
the Thermostat ignoring updates entirely.

```json
// CORRECT
{"object_revision": 458, "object_timestamp": 1707148800000, "object_key": "shared.SERIAL", "value": {...}}

// INCORRECT -- will cause issues
{"object_key": "shared.SERIAL", "object_revision": 458, "object_timestamp": 1707148800000, "value": {...}}
```

Most JSON serialization libraries don't guarantee field order. Use ordered dictionaries,
manual string building, or a library that preserves insertion order.

This applies to both flat response format and the `objects` array format.

**Source**: Lines 218-234. Reiterated at lines 2703-2706, 2731-2733, 2767-2768.

### 7.2 PUT Write-Receipt Shape

The PUT response is a write receipt, not a data channel. Return only:

```json
{
  "object_revision": <incremented>,
  "object_timestamp": <current_ms>,
  "object_key": "<bucket_key>"
}
```

**No `value` field.** If the server includes `value`, the Thermostat applies every
field as authoritative cloud data with no per-key staleness check, silently overwriting
local state. This applies to CAS conflict responses too: return the updated revision so
the device can retry, but never include `value`.

**Source**: Lines 326-331, changelog rev 2.4 (lines 2859).

### 7.3 Explicit Port Rule on the Advertised URL

**Always include an explicit port in the `transport_url`.** The Thermostat's URL parser
fails to extract ports from URLs that omit them, breaking WoWLAN functionality.

```
WRONG:  https://server.example.com/path       (no port)
RIGHT:  https://server.example.com:443/path    (explicit port)
```

**Symptoms**: Device works while awake; server push fails to wake sleeping device;
device logs show packet size 0 instead of ~40 bytes.

**Source**: Lines 122-123, 2783-2823.

### 7.4 Chunked Transfer Encoding

Subscribe responses **must** use `Transfer-Encoding: chunked`. This is required for
server push capability. Without it, the Thermostat applies a 7-second immediate timeout
(expects the complete body within 7 seconds).

Each chunk must be a complete `{"objects": [...]}` JSON document. The Thermostat parses
each chunk independently.

**Source**: Lines 104-118, 1081-1087.

### 7.5 Reconnect Timing and Connection Hold

The server drives the reconnect cycle. The Thermostat does not close the connection on
its own during normal operation. Key timing constraints:

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `X-nl-suspend-time-max` | 300 (recommended) | Must be <= 350 (under ~360s idle timeout) |
| Connection hold time | 290 seconds | Must be < `X-nl-suspend-time-max` |
| Formula | `hold_time = suspend_time_max - 10` | 10-second margin is sufficient |

**Critical**: If the connection remains idle for ~360 seconds, the Thermostat considers
it dead and resubscribes on a **new** connection without closing the old one, creating
overlapping subscriptions.

To close a connection: send the final chunk terminator (`0\r\n\r\n`).

**Source**: Lines 1089-1117, changelog rev 2.5.

### 7.6 SO_KEEPALIVE Prohibition

**Do NOT enable server-side `SO_KEEPALIVE`.** The Thermostat does not respond to
keep-alive probes while the CPU is asleep (WiFi hardware maintains the TCP connection
during CPU sleep). Keep-alive probes will go unanswered and the OS will eventually
kill the connection.

**Source**: Lines 705-706, 1116.

### 7.7 Schedule, Temperature, and Time Unit Conventions

| Convention | Rule | Source |
|------------|------|--------|
| Day indexing | **Day 0 = Monday**, not Sunday. Days `"0"` through `"6"` (Mon-Sun). | Lines 2363-2377 |
| Temperature unit | **Always Celsius** across all buckets. `temperature_scale` (`F`/`C`) is display-only. | Lines 1717-1721 |
| Temperature precision | Float, up to 5 decimal places. Changes < ~0.01C ignored. Schedule precision ~0.25C. | Lines 1458-1459, 2428-2431 |
| Schedule time | **Seconds from midnight** (0-86399). e.g. 25200 = 7:00 AM. | Lines 2383-2405 |
| Timestamps (sync) | **Milliseconds** since Unix epoch (int64). | Lines 895-898 |
| `manual_eco_timestamp` | **Seconds** since Unix epoch (not milliseconds). Must be within 600s of device clock. | Lines 2189-2191 |
| `touched_at` | **Seconds** since Unix epoch. | Lines 1529, 1543 |

---

## 8. Versioning and Synchronization

### Sync Decision Rules

**Timestamp is the primary authority** for determining which data is newer.

| Condition | Result |
|-----------|--------|
| Server timestamp > Device timestamp | Accept server data |
| Server timestamp < Device timestamp | Keep local data |
| Server timestamp = Device timestamp | Use revision as tiebreaker (strict greater-than) |
| Server timestamp = 0 | Sentinel: "no data exists" -- device should send its state |

When timestamps are equal, the Thermostat uses strict greater-than on revision. If both
timestamp and revision are equal, the server data is considered stale and rejected.

**Source**: Lines 849-908.

### Revision vs Timestamp

| Field | Purpose | Used For |
|-------|---------|----------|
| `object_revision` | Write ordering | Conditional writes (reject on mismatch) |
| `object_timestamp` | Sync authority | Determining newer data |
| `if_object_revision` | Conditional write guard | PUT validation (shared bucket only) |
| `base_object_revision` | Informational | Debugging/logging (no validation) |

**Source**: Lines 888-908.

---

## 9. Authentication

> **PROVISIONAL**: The reference marks the entire Authentication section as provisional.
> The Thermostat's auth system was designed for Google's cloud and companion app. The
> approaches documented "are functional but may not cover all firmware edge cases."
> (Lines 476-478)

### Production Firmware Behavior

On production firmware, the Thermostat **always** sends HTTP Basic Authentication. The
user ID format is `d.{SERIAL}.{suffix}`. The serial is extractable from every request.

**Source**: Lines 480-481, changelog rev 2.8.

### Recommended Home Server Approach

Skip credential provisioning entirely:
1. Accept all requests regardless of credentials (don't return 401).
2. Parse the Basic Auth user ID to extract the serial.
3. Look up the serial in your database.

**Source**: Lines 523-538.

### Credential Loop Warning

Provisioning credentials through a 401 response can cause a credential loop on some
firmware versions. Provision credentials only in 200 responses.

**Source**: Lines 520-522.

---

## 10. Pairing

### Flow

1. Server returns `passphrase_url` in `/entry` response.
2. Thermostat fetches entry key from `passphrase_url`, displays it as `XXX-XXXX`.
3. User enters the code in the application.
4. Server pushes **user bucket** (with `name` field) and **structure bucket** on the
   subscribe connection.
5. Pairing dialog dismisses.

**Critical**: The `user` bucket's `name` field is what completes pairing. The
`structure` bucket alone is insufficient.

**Source**: Lines 582-656.

### Maintaining Pairing State

Include both user and structure buckets in subscribe responses for paired devices on
**every reconnection**. There is no penalty for including them (device ignores
duplicates with matching timestamp).

**Source**: Lines 648-655.

---

## 11. Connection Lifecycle Details

### Overlapping Subscriptions

When the Thermostat wakes early (e.g. user interaction), it may send a new subscribe
while the server still holds the previous connection. Both are valid simultaneously.

Track each subscription independently using a server-generated ID. When pushing data,
send to all active subscriptions for the device. Remove connections only on timeout.

**Source**: Lines 756-779.

### Batching Multiple Pushes

Multiple chunks can be sent on a single subscribe connection. The Thermostat's 5-second
closing timer resets on each chunk received.

Recommended batch window: 3 seconds (must be under 5 seconds). Each chunk must be a
complete `{"objects": [...]}` JSON document.

**Source**: Lines 781-843.

### Service Tickle

Sending an empty body (`0\r\n\r\n`) forces the Thermostat to reconnect. Valid for:
graceful shutdown, load balancer migration, force state refresh. Not for normal
operation.

**Source**: Lines 726-744.

### Device Wake Timing

The Thermostat wakes within ~100-500ms when the server sends data, regardless of the
`X-nl-suspend-time-max` value.

**Source**: Lines 696-709.

---

## 12. Display Wake and target_change_pending

When pushing a temperature change, also set `target_change_pending: true` to wake the
physical display. The Thermostat then sends `target_change_pending: false` in a PUT to
acknowledge. The server must accept `false` without re-pushing `true`.

Set `target_change_pending: true` for: `target_temperature`,
`target_temperature_high`, `target_temperature_low`.

Do **not** set for: `target_temperature_type`, `away`, fan settings, or any device/structure bucket field.

**Source**: Lines 1460-1518.

---

## 13. Schedule Details

### Format

Schedule version is always `2`. Top-level fields: `ver`, `name`, `schedule_mode`
(`HEAT`/`COOL`/`RANGE`), `days` (keyed `"0"` through `"6"`, Monday through Sunday).

Within each day, setpoints are keyed by sequential integer strings (`"0"`, `"1"`, ...).

### Setpoint Fields

| Field | Modes | Description |
|-------|-------|-------------|
| `type` | All | Must match `schedule_mode` |
| `time` | All | Seconds from midnight |
| `entry_type` | All | `"setpoint"` (user-defined) or `"continuation"` (fill) |
| `temp` | HEAT, COOL | Target temperature (Celsius) |
| `temp-min` | RANGE | Lower bound (Celsius) |
| `temp-max` | RANGE | Upper bound (Celsius) |

**Source**: Lines 2316-2419.

### Sync Guards

1. **15-second debounce**: Multiple pushes within 15s -- only last takes effect.
   Bypassed during connection recovery.
2. **Pending local change**: If user is editing schedule on device, incoming pushes are
   discarded silently.
3. **Timestamp rejection**: Schedules with older timestamps are rejected.

**Source**: Lines 2568-2585.

### Additional Schedule Rules

- Always push the **complete** schedule, not individual setpoints.
- Max 96 setpoints per day (practical max ~10-12).
- Only `"setpoint"` entries need to be pushed; device fills in continuations.
- Custom schedules use `custom_schedule.{id}` with server-assigned IDs.
- If learning mode is enabled, the Thermostat may modify pushed schedules.

**Source**: Lines 2484-2596.

---

## 14. Eco Mode

### Enter

Push `manual_eco_all: true` and `manual_eco_timestamp` (Unix **seconds**, not
milliseconds) to the structure bucket. Timestamp must be within 600 seconds of device
clock.

**Source**: Lines 2170-2191.

### Exit

Push all three together:
1. `manual_eco_all: false` + `manual_eco_timestamp` in structure bucket
2. `away: false` in structure bucket
3. `eco.mode: "schedule"` in device bucket (most reliable path -- no timestamp
   validation, no readiness dependency)

**Source**: Lines 2193-2228, changelog rev 2.9.

### Eco Temperatures

During eco, the Thermostat uses `away_temperature_high` and `away_temperature_low` from
the device bucket. These are separate from `target_temperature` in shared.

**Source**: Lines 2234-2238.

---

## 15. target_temperature vs Schedule Setpoints

This is a critical interaction the reference calls out explicitly:

- The Thermostat evaluates its schedule **locally**. When a schedule transition fires,
  it updates `target_temperature` in the shared bucket.
- If the server re-pushes a stale `target_temperature` value, the Thermostat treats it
  as a new cloud override, canceling the schedule-derived setpoint.
- Any cloud-pushed `target_temperature` creates a **temporary hold** until the next
  schedule transition.
- Only include `target_temperature` in subscribe responses when it has genuinely changed.
- During eco mode, `target_temperature` continues to track the schedule (eco override
  happens at the HVAC control layer).

**Source**: Lines 1435-1457, changelog rev 2.2 (line 2861).

### Schedule Transition PUT Ordering

When a schedule transition fires, the Thermostat sends HVAC state changes first
(synchronous, non-delayable) and the temperature change second (through defer delay).
This creates a window where the server has updated HVAC states but still holds the
previous `target_temperature`.

Mitigation: Set `X-nl-defer-device-window` to 15-30 seconds.

**Source**: Lines 1449-1455, changelog rev 2.4.

---

## 16. Temperature Change Source Tracking (touched_by)

The server must set `touched_by` in the shared bucket when writing temperature changes.
The Thermostat reads this for display state (temperature holds, "Holding until...").

```json
{
  "touched_by": {
    "touched_by": 1,
    "touched_at": 1707148800,
    "touched_tzo": -18000,
    "touched_user_id": ""
  }
}
```

| `touched_by` value | When |
|---------------------|------|
| `1` | Server applying schedule transition |
| `2` | Device PUT a temperature (user turned dial) |
| `3` | Client app or external API pushed temperature |

`touched_at` is Unix **seconds**. `touched_tzo` is UTC offset in seconds.

**Source**: Lines 1520-1547, changelog rev 2.9.

---

## 17. Battery Behavior

| Voltage | Effect |
|---------|--------|
| 3.8V+ | Normal |
| 3.7V | +25 seconds added to sleep |
| 3.65V | Low battery flag set |
| 3.6V | **WiFi disabled** -- device goes offline |
| 3.5V | +225 seconds added to sleep |

Reconnects only after voltage recovers above 3.8V.

**Source**: Lines 1152-1169.

---

## 18. Error Handling

| Status | Device Behavior |
|--------|-----------------|
| 200 | Process response |
| 302 | Follow redirect (entry only) |
| 400 | Retry up to 2 times (3 total) |
| 401 | Re-authenticate |
| 403 | Reset comms state |
| 404 | Reset comms state |
| 5xx | Retry with exponential backoff |

**Source**: Lines 2599-2626.

---

## 19. HVAC Modes

| Value | Behavior | Temp Fields | Wiring Required |
|-------|----------|-------------|-----------------|
| `"heat"` | Heating only | `target_temperature` | `can_heat` |
| `"cool"` | Cooling only | `target_temperature` | `can_cool` |
| `"range"` | Auto heat/cool | `target_temperature_low`, `target_temperature_high` | both |
| `"off"` | All HVAC disabled | None | -- |
| `"emergency"` | Aux heat only | `target_temperature` | `has_emer_heat` |

Values are case-insensitive. Device sends lowercase.

If the server pushes a mode the wiring can't support, the Thermostat silently falls
back, preferring heat over cool.

Emergency heat automatically: saves/disables learning mode, saves/disables auto-away,
blocks preconditioning. All restored when emergency heat is turned off.

**Source**: Lines 1780-1812.

---

## 20. PUT Order (Debugging)

When the Thermostat sends a multi-bucket PUT, buckets appear in this order:

`demand_response` -> `demand_response_event` -> `tuneups` -> `structure` -> `schedule`
-> `custom_schedule` -> `message` -> `shared` -> `device` -> `where` ->
`diamond_sensor_event` -> `tou` -> `hvac_partner` -> `cloud_algo` ->
`demand_charge_event` -> `rcs_settings` -> `kryptonite` -> `diagnostics`

The server does not need to process them in order.

**Source**: Lines 1747-1752.

---

## 21. Open Questions (Provisional, Partial, or Implementation-Defined)

These items are explicitly flagged by the reference as not fully resolved. They must be
decided during implementation rather than assumed from this contract.

### 21.1 Authentication is Provisional

The entire Authentication section is marked "Provisional" (line 476). The reference
notes: "The approaches documented here are functional but may not cover all firmware
edge cases." Credential provisioning through 401 responses is known to cause loops on
"some firmware versions" but which versions is unspecified.

**Source**: Lines 476-478, document status table line 2840.

### 21.2 Error Handling is Partial

The Error handling section is marked "Partial" in the document status table (line 2846).
There is an explicit TODO: "Document retry intervals and backoff strategy for 5xx errors
from binary analysis" (line 2625). The exact backoff timing for 5xx retries is unknown.

**Source**: Lines 2625, 2846.

### 21.3 if_object_revision Rejection Response is Implementation-Defined

When the Thermostat sends `if_object_revision` (shared bucket) and the revision doesn't
match, "the specific server response for validation failure is implementation-defined"
(line 305). The reference does not prescribe a status code or response shape for this
case.

**Source**: Lines 305, 891-892.

### 21.4 Conflict Detection Behavior

The conflict detection section (lines 308-318) describes the happy path but the
reference's PUT response guidance (rev 2.4) says never to include `value` in PUT
responses, even for conflicts. This means the standard "return current state for
reconciliation" pattern cannot be used as described. The server must return only the
write receipt and push corrections via subscribe instead. The reconciliation path is
effectively: accept the PUT, push the correct state on the next subscribe.

**Source**: Lines 308-318 vs 326-331.

### 21.5 X-nl-defer-device-window / X-nl-disable-defer-window Rejection Threshold

Values >= 3600 are rejected but the reference doesn't specify the error behavior --
whether the header is silently ignored, the entire response is rejected, or the value
is clamped.

**Source**: Lines 964, 1008.

### 21.6 Device Behavior on Unsupported Mode Fallback

When the Thermostat receives a mode it can't support, it "silently falls back to a
supported mode -- preferring heat over cool" (line 1800). The exact fallback chain for
all combinations (e.g. `range` with only heat wiring) is not documented.

**Source**: Lines 1798-1801.

### 21.7 Clock Skew Correction Threshold

The Thermostat "automatically corrects its clock if the skew between device time and
server time exceeds approximately 10 minutes" (line 1051). The exact threshold is
approximate.

**Source**: Line 1051.

### 21.8 Entry Key Display Behavior Edge Cases

The entry key requires expiration at least 30 minutes in the future (line 567), but
what happens when the key expires while the device is displaying it is not documented.

**Source**: Lines 566-569.

### 21.9 eco.mode Field Type

The device reports `eco_mode` as "a read-only JSON string" (line 2944 area) containing
a nested JSON object. Whether the server writes `eco.mode` as a nested object or a JSON
string containing a JSON object is ambiguous from the exit eco example (lines 2213-2219)
which shows `"eco": {"mode": "schedule", ...}` as nested object.

**Source**: Lines 2194-2223, 2943-2949.

### 21.10 Weather, Upload, Ping, and Pro Info URLs

The `/entry` response can include `weather_url`, `upload_url`, and `ping_url`, but
the reference doesn't document their request/response formats. These are noted in
the README as things that the NLE server covers but the protocol docs do not.

**Source**: Lines 448-450, README.md lines 97-98, 139.

### 21.11 Non-Essential Bucket Details

The 18 specialized bucket types (servicegroup through diagnostics/tuneups) have minimal
documentation. The reference advises: "Store any data the device sends for these buckets,
and serve it back on subscribe" (line 1697). Their internal field structures are largely
undocumented.

**Source**: Lines 1695-1716.

### 21.12 Model String Ambiguity

The reference uses `Diamond-2.6` and `Flintstone-4.0` as example model strings (line 399).
The project README notes conflicting model strings across sources (`Display-2.8` in
PLAN.md, `Diamond-2.6`/`Flintstone-4.0` in the protocol docs, `2.8`/`1.12` in NLE docs).
The reference does not define the model string taxonomy.

**Source**: Line 399, project README lines 81-85.

### 21.13 Timestamp Precision Requirements

The reference uses milliseconds for sync timestamps and seconds for eco/touched_at
timestamps, but does not document the Thermostat's tolerance for rounding, truncation,
or minor clock discrepancies beyond the ~10-minute auto-correction and 600-second
eco window.

---

## 22. Changelog-Verified Corrections

The reference's changelog (lines 2850-2872) documents corrections to earlier revisions,
indicating claims verified against real hardware. Key corrections:

| Rev | What Was Fixed | Implication |
|-----|---------------|-------------|
| 2.9 | `touched_by` in shared bucket is Read/Write, not Read-only. Server sets it. `eco.mode: "schedule"` is most reliable eco exit. | Verified: device reads server-set `touched_by`. |
| 2.8 | Production firmware **always** uses Basic Auth. `X-nl-client-id`/`X-nl-device-id` are non-production only. | Verified against production firmware. |
| 2.7 | `manual_eco_all: false` can be silently dropped due to 600s timestamp validation. | Verified: eco exit failure observed. |
| 2.6 | `X-nl-suspend-time-max` was documented as 600 in examples but must be <=350. `current_humidity` is integer, not float. `can_heat`/`can_cool` are shared-only. | Contradictions found against hardware. |
| 2.5 | Server controls the reconnect cycle, not the device. Hold time must be **shorter** than suspend time. | Previous guidance was inverted and incorrect. |
| 2.4 | PUT response must never include `value`. Device applies `value` blindly. Schedule transition creates deterministic HVAC-first/temp-second PUT ordering. | Verified: silent state corruption from `value` in PUT responses. |
| 2.3 | Schedule timer continues during eco (not "suspended"). Eco exit does fresh schedule lookup; manual overrides not restored. | Corrected from earlier claim that eco "suspends" schedules. |
| 2.2 | Temperature examples were in Fahrenheit, should be Celsius. `target_temperature` is a user/cloud override. | All temperatures verified as Celsius internally. |

**Source**: Lines 2850-2872.
