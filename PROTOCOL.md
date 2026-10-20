# Protocol spec for the Integration

This file is the only protocol input for the build session. It tells the
Integration what to do on each Route. The terms are from `CONTEXT.md`.

## Sources

| Tag | Source | Version read |
|---|---|---|
| NLE | `jtoniolo/NoLongerEvil-SelfHosted`, `src/nolongerevil/` | `main` at `cdb86ea` |
| CJ | `cjserio/nest-thermostat-protocol-docs`, `NEST_CLOUD_PROTOCOL_REFERENCE.md` | `main`, read 2026-10-19 |

Each rule has a tag. "NLE" means that the NLE server does it and the
Thermostat works with it. "CJ" means that the CJ document says it. "DECISION"
means that this spec chooses the behavior. "GAP" means that nobody knows
yet. A real capture can close a GAP.

No code is copied from NLE. This file records protocol facts and behavior only.

## 1. Rules for the whole server

1. All temperatures on the wire are Celsius floats. This applies to every
   bucket. (CJ)
2. Never send HTTP 401. The Thermostat can go into a credential loop. (CJ)
3. Never send the header `X-nl-set-client-credentials`. (DECISION, CJ
   recommends this for home servers.)
4. Do not do pairing. Do not use entry keys to give access. Accept all
   requests. (DECISION, NLE default `require_device_pairing=False`)
5. Do not enable `SO_KEEPALIVE` on the server socket. The Thermostat cannot
   answer keepalive probes while it sleeps. (CJ) The aiohttp default does not
   enable it on accepted sockets, so do nothing.
6. Every URL that the Integration sends to the Thermostat must include an
   explicit port, also for port 80. Without the port, the Thermostat cannot
   wake from a push (WoWLAN, wake on wireless LAN). (CJ, NLE)
7. Do not answer 404 or 403 for a Route that the Thermostat calls. The
   Thermostat resets its communication state on 404 and 403. (CJ) Use the
   catch-all rules in section 3.
8. On a 400, the Thermostat tries 2 more times and then stops. Send 400 only
   for a body that is not JSON. (CJ)

## 2. Addressing

### 2.1 Bind address and Advertised URL

- The Integration owns its own port. Use the `emulated_hue` pattern:
  `aiohttp.web.AppRunner` and `aiohttp.web.TCPSite`. (README decision)
- Default Bind address: `0.0.0.0:9543`. (DECISION) The live Endpoint is
  `http://10.0.6.63:9543/entry`. The NLE add-on holds port 9543 now.
- Default Advertised URL: `http://<HA LAN IP>:9543`. The config flow asks for
  it. The Advertised URL is always a LAN address. (CONTEXT)
- If the user enters a URL without a port, add the port of the Bind address.
  (NLE `api_origin_with_port`)

### 2.2 The Endpoint and the Route paths

The Thermostat calls `<Endpoint>` to register. Then it uses the URLs from the
`/entry` response. The Thermostat caches those URLs. It registers again
"periodically or after errors". (CJ)

DECISION: advertise the same paths as NLE. Then a Thermostat that cached the
NLE URLs works with the Integration on the first boot, with no change.

| Purpose | URL that `/entry` returns |
|---|---|
| `czfe_url` | `<adv>/nest/transport` |
| `transport_url` | `<adv>/nest/transport` |
| `direct_transport_url` | `<adv>/nest/transport` |
| `passphrase_url` | `<adv>/nest/passphrase` |
| `ping_url` | `<adv>/nest/transport` (NLE sends the transport URL here) |
| `pro_info_url` | `<adv>/nest/pro_info` |
| `weather_url` | `<adv>/nest/weather/v1?query=` |
| `upload_url` | `<adv>/nest/upload` |
| `software_update_url` | `""` |
| `server_version` | any string, for example `"1.0.0"` |
| `tier_name` | `"local"` |

`<adv>` is the Advertised URL with its port and with no trailing slash. (NLE)
CJ marks only `transport_url` as required.

## 3. Route table

Normalize the path first. Then match the Route. (NLE `url_normalizer`)

Path normalization: if the path does not start with `/nest/`, apply the first
rule that matches:

| Legacy path | Normalized path |
|---|---|
| `/entry` or `/entry/` | `/nest/entry` |
| `/ping` | `/nest/ping` |
| `/passphrase` | `/nest/passphrase` |
| `/czfe/<rest>` | `/nest/transport/<rest>` |
| `/transport` or `/transport/<rest>` | `/nest/transport/<rest>` |
| `/weather/<rest>` | `/nest/weather/<rest>` |
| `/upload` | `/nest/upload` |
| `/pro_info/<rest>` | `/nest/pro_info/<rest>` |

DECISION: implement the normalization as one catch-all aiohttp handler
(`/{tail:.*}`) that dispatches on the normalized path. This is simpler than a
middleware that re-resolves routes.

| Method | Normalized path | Handler |
|---|---|---|
| GET, POST | `/nest/entry` | Entry, section 4 |
| POST | `/nest/transport` | Subscribe, section 6 |
| POST | `/nest/transport/<anything>/subscribe` | Subscribe |
| POST | `/nest/transport/put` | Put, section 7 |
| POST | `/nest/transport/<anything>/put` | Put |
| POST | any other path under `/nest/transport/` | Subscribe (DECISION, GAP 1) |
| GET | `/nest/transport/device/<serial>` and any other GET under `/nest/transport/` | Object list, section 8.1 |
| GET | `/nest/ping` | `{"status": "ok", "timestamp": <now ms>}` (NLE) |
| GET | `/nest/passphrase` | Section 8.2 |
| GET | `/nest/pro_info/<code>` | Section 8.3 |
| POST | `/nest/upload` | Read the body, log its size at debug, return `{"status": "ok"}` (NLE) |
| GET | `/nest/weather/<anything>` | Section 8.4 |
| GET | `/info` | Section 8.5 |
| any | anything else | Log at warning level. Return 200 `{}`. (DECISION, rule 1.7) |

## 4. Entry

- Methods: GET and POST. (NLE)
- The body is form-urlencoded. Fields: `reset`, `mac`, `model`, `request_id`,
  `software_version`, `wireless_reg_domain`, `backplate_model`. (CJ) Log
  them at debug level. Store `model` (the Model string), `mac`, and
  `software_version` as attributes for the HA device. No logic keys off
  `model`. (README)
- The response is JSON with the URLs from section 2.2. Status 200. No special
  headers. (NLE, CJ)

## 5. Device identity

Get the serial from the first source that has one: (NLE, CJ)

1. `Authorization: Basic <b64>`. Decode it. Split on the first `:` to get the
   user ID. If the user ID has a `.`, split it on `.`. Use segment 1 if it is
   not empty. Else use segment 0. Production format: `d.<SERIAL>.<suffix>`.
2. Header `X-nl-client-id`. Same format and same split.
3. Header `X-nl-device-id`. A bare serial.
4. Header `X-NL-Device-Serial`.
5. Query parameter `serial`.
6. Path segment `<serial>` (the object list Route only).

Clean the serial: remove all characters that are not `[A-Za-z0-9]`, then
make it uppercase. The serial is not valid if it has fewer than 10
characters. Subscribe and Put without a valid serial: send 400
`{"error": "Device serial required"}`. (NLE)

The Basic auth password is the Thermostat's `api_key`. The Settings API uses
it. (NLE) DECISION: do not store it in v1.

## 6. Subscribe (the long poll)

### 6.1 Request

Body (JSON):

```json
{"chunked": true, "session": "18b430...SERIAL",
 "objects": [{"object_key": "device.SERIAL", "object_revision": 3, "object_timestamp": 1707148800000}, ...]}
```

- Production firmware sends the `objects` array. (CJ) NLE also accepts named
  bucket fields: a top-level key that is a known bucket type, with a dict
  value that has `object_key`. Accept both. (NLE)
- `session` is the same for the life of the Thermostat. Never use it as a
  key. Log it only. (CJ)
- Headers `X-nl-protocol-version: 1`, `X-nl-device-swversion`, and
  `X-nl-longest-wake` are information only. (CJ)
- Skip each object that has no `object_key`. (NLE)
- Inline update (NLE only, CJ says production does not do this): if an
  object has `value`, and `object_revision` is 0 or missing, and
  `object_timestamp` is 0 or missing, treat it as a write. Merge it as in
  section 7.3. Then process the object as normal.

### 6.2 Which buckets to send

For each request object, get the server copy of that bucket. If there is no
server copy, use a placeholder with revision 0, timestamp 0, and an empty
value. (NLE)

Send the server copy when `server_is_newer(server_ts, client_ts)` is true:
(NLE, CJ)

```
if client_ts == 0: return True     # the Thermostat has no data
if server_ts == 0: return False    # the server has no data
return server_ts > client_ts       # equal means in sync
```

Revision is not used for this decision. (CJ, NLE)

If `client_ts > server_ts` and the request object has `value`, merge the
value into the server copy and store the client revision and client
timestamp. (NLE) If the object has no `value`, do nothing. The Thermostat
sends its data with Put.

Then add the extra buckets in section 6.5.

### 6.3 Response headers

Send these headers on every subscribe response: (NLE, CJ)

| Header | Value |
|---|---|
| `Content-Type` | `application/json` |
| `Transfer-Encoding` | `chunked` (aiohttp sets this when `enable_chunked_encoding()` is called, or when no content length is set on a `StreamResponse`) |
| `X-nl-service-timestamp` | now, in ms |
| `X-nl-suspend-time-max` | `300` |
| `X-nl-defer-device-window` | `15` |
| `X-nl-disable-defer-window` | `60`, only when the body that goes out now has one of `target_temperature`, `target_temperature_high`, `target_temperature_low`, `target_temperature_type`, `hvac_mode` |

The headers go out before the body. So `X-nl-disable-defer-window` is only
possible for buckets that the server sends immediately (section 6.4 case A).
A push on a held connection cannot add it. (NLE)

If the request body has `"chunked": false`, send a normal JSON response
immediately with `{"objects": [...]}`, or `{"objects": []}`. The Thermostat
waits only 7 seconds in this mode. (NLE, CJ)

### 6.4 Response body and the hold

Call `response.prepare()` immediately. After the headers, the Thermostat can
sleep. (NLE, CJ)

- **Case A, buckets to send now:** write one chunk
  `{"objects": [<bucket>, ...]}`. Then write EOF. (NLE)
- **Case B, nothing to send:** register a Subscription (section 6.6). Wait on
  its queue for up to the hold time (290 s).
  - Data arrives: write it as one chunk. Then wait up to 3 s for more data.
    Write each new item as its own chunk. Each chunk is a complete
    `{"objects": [...]}` document. When 3 s pass with no data, write EOF.
    The Thermostat closes after 5 s with no chunk, so the gap must stay
    under 5 s. (NLE, CJ)
  - Hold time ends: close the connection. Do not write a body. Do not send
    an empty JSON object. (NLE, CJ) The end chunk `0\r\n\r\n` is correct.
    aiohttp writes it when the handler returns. The close wakes the
    Thermostat, and it subscribes again.
  - The write fails (connection reset): put the data that did not go out into
    the pending buffer for that serial (section 6.6).
  - Always remove the Subscription when the handler ends (`finally`).

Bucket format in a response (CJ, NLE). The field order is required. The
Thermostat can ignore an object if `object_key` comes first:

```json
{"object_revision": 458, "object_timestamp": 1707148800000, "object_key": "shared.SERIAL", "value": {...}}
```

Python `dict` keeps insertion order, and `json.dumps` keeps it. Build the
dict in this order. NLE also adds `"updatedAt": <ms>` after `object_key`.
CJ does not have it. DECISION: do not send `updatedAt`.

A tickle is an empty chunked body that closes at once. Use it only on
shutdown, to make the Thermostat reconnect fast. (CJ) DECISION: on unload,
close all held connections with EOF and no body.

### 6.5 Extra buckets: user and structure

The Thermostat does not subscribe to the structure bucket by default. The
server must add it to a subscribe response. (CJ) Eco control needs the
structure bucket.

CJ says that the Thermostat checks for a pairing token before it processes a
structure bucket. The user bucket with a `name` field gives that token. NLE
sends the user bucket and the structure bucket only to "owned" devices. For
devices with no owner, NLE sends `structure.default` only if it exists.

DECISION: the Integration acts as the owner of every Thermostat. On each
subscribe, add these buckets when `client_ts < server_ts`, or when the
Thermostat has not received them since the Integration started:

| Bucket | Key | Value at creation |
|---|---|---|
| user | `user.<user_id>` | `{"name": "<user_id>"}` |
| structure | `structure.<structure_id>` | `{"name": "Home", "devices": ["<serial>"]}` |

Create each bucket once with revision 1 and timestamp now, and store it.

Choose the IDs as follows:

1. If the subscribe request lists a `user.*` key, use that ID. If it lists a
   `structure.*` key, use that ID. The Thermostat lists the keys that it
   knows. (CJ) This keeps the pairing token that NLE gave it.
2. Else use `user_id = "nest_local"` and `structure_id = "default"`.

Store the chosen IDs with the Thermostat. GAP 3 covers this whole section.

NLE stores `devices` as bare serials. CJ shows `"device.<serial>"`. The
Thermostat processes the bucket either way. (CJ) DECISION: use the NLE form.

### 6.6 Subscriptions and the pending buffer

- A Subscription has a server-made unique ID, the serial, and an
  `asyncio.Queue`. (NLE, CJ)
- A serial can have more than one Subscription at the same time. This
  happens when the Thermostat wakes early or thinks that a connection is
  dead (after about 360 s idle). Push to all of them. Remove only the one
  that ends. (CJ)
- Limit: 100 Subscriptions for each serial. Over the limit, write
  `{"objects": []}` and EOF. (NLE)
- Pending buffer: when a push cannot go out, append its objects to a list
  for the serial. When a new Subscription starts, put the list on its queue
  and clear the list. (NLE)
- If no Subscription is open when a command runs, do not queue anything. The
  command made the server timestamp newer, so the next subscribe sends the
  bucket (section 6.2). (NLE)

## 7. Put (the Thermostat writes)

### 7.1 Request

Production format (CJ): keys at the top level, data fields inline.

```json
{"session": "sess",
 "shared.SERIAL": {"object_key": "shared.SERIAL", "if_object_revision": 457, "target_temperature": 21.5},
 "device.SERIAL": {"object_key": "device.SERIAL", "base_object_revision": 122, "fan_timer_timeout": 900}}
```

For each top-level key other than `session`: if the value is a dict with
`object_key`, take the value. Remove `object_key`, `base_object_revision`,
and `if_object_revision`. The rest is the data. (NLE) Also accept
`{"objects": [{"object_key": ..., "value": {...}}]}`. (NLE)

Skip an object that has no data. Log it at warning level. (NLE)

### 7.2 Conditional write

- Only `shared` uses `if_object_revision`. All other buckets use
  `base_object_revision`, and it is information only. (CJ)
- If `if_object_revision` is present and is not equal to the server revision
  (0 if there is no server copy), do not merge. Add
  `{"object_revision": <server rev>, "object_timestamp": <server ts>, "object_key": <key>}`
  to the response. Continue with the next object. (NLE)
- Never put `value` in a Put response. This applies also to a conflict. The
  Thermostat applies a `value` as cloud data and loses its own local
  changes. (CJ, NLE)

### 7.3 Merge

```
merged = {**server_value, **data}          # shallow merge; keys not in data stay
changed = server copy missing or merged != server_value
revision  = server_rev + 1   if changed else server_rev
timestamp = now_ms           if changed else server_ts (now_ms if no server copy)
```

Store the result. (NLE) Do not change the timestamp when nothing changed.
Else the next subscribe sends a stale full bucket back, and that can cancel a
schedule setpoint on the Thermostat. (NLE)

- A shallow merge also keeps the fan timer fields. The NLE fan-timer guard
  adds nothing to a shallow merge. (NLE, by reading)
- `target_change_pending: false` from the Thermostat is a normal merge.
  Accept it. Never push `true` again in reply. (CJ, NLE)
- The Thermostat re-sends device-only fields when the server changes them.
  Accept them as normal. (CJ)
- NLE also stores the `x-nl-weave-device-id` header in the value.
  DECISION: do not do this.

### 7.4 Response

Status 200. Body `{"objects": [<rev, ts, key for each object>]}`. Use the
field order from section 6.4. Send the headers `X-nl-service-timestamp`,
`X-nl-suspend-time-max`, and `X-nl-defer-device-window`. (NLE, CJ)

A Put must not push anything to the Subscriptions. The Thermostat already has
the data. A push here caused stale setpoints in NLE. (NLE)

After a Put, tell the HA entities that the state changed (section 10).

### 7.5 `touched_by`

CJ says that the server should set `shared.touched_by` to
`{"touched_by": 2, "touched_at": <s>, "touched_tzo": <offset s>, "touched_user_id": ""}`
when the Thermostat puts a new `target_temperature`. It should use `3` for an
app change. NLE does not do this, and the Thermostat works.
DECISION: do not set `touched_by` in v1.

## 8. Other Routes

### 8.1 Object list (GET under `/nest/transport/`)

Get the serial from the path (`/device/<serial>` or `/device/device.<serial>`)
or from section 5. Return
`{"objects": [{"object_revision", "object_timestamp", "object_key"}, ...]}`
for all stored buckets of that serial, with no values. Use the headers from
section 7.4. If there is no serial, send 400. (NLE) NLE also creates a
`device_alert_dialog` bucket here. DECISION: skip that.

### 8.2 Passphrase

The Thermostat polls this Route while it shows an entry key. (CJ) The
Integration does no pairing, but the Route must not fail.

DECISION: return `{"value": "<7 alphanumeric chars>", "expires": <ms>}`.
Make one code for each serial. Keep it until 1 hour after creation, then
make a new one. `expires` must be a JSON number, at least 30 minutes in the
future. (CJ) The code does nothing.

### 8.3 Pro info

Return 200 with a fixed JSON object, for example
`{"id": 1, "pro_id": "<code>", "dba": "nest_local", "locality": "Local", "rating": 5.0}`.
(NLE shape)

### 8.4 Weather

NLE sends the query to `https://weather.nest.com/weather/v1?<query>` and
caches the answer for 10 minutes. The Thermostat sends `postal_code` and
`country` query parameters (NLE). GAP 4: nobody knows if that host still
answers, or what JSON the Thermostat expects.

DECISION for v1: return 200 `{}`. Log the query string at debug level.
Outdoor temperature on the Thermostat display is not in scope for v1.

### 8.5 `/info`

This is an NLE addition for setup tools. The Firmware does not need it.
DECISION: return
`{"server": "nest_local", "version": "<manifest version>", "api_origin": "<adv>", "cloudregisterurl": "<adv>/entry", "port": <port>, "ssl": false, "require_device_pairing": false}`.

## 9. Commands (HA writes to the Thermostat)

### 9.1 How a command writes

For each command: (NLE, with one DECISION)

1. Validate the input. On bad input, raise `HomeAssistantError` or
   `ServiceValidationError`. Never change a bad value into a default.
2. Make the delta (only the fields that change).
3. Merge the delta into the stored bucket. Set revision to server revision
   + 1 and timestamp to now in ms. Store it.
4. Push `{"object_revision", "object_timestamp", "object_key", "value": <delta>}`
   to all Subscriptions of the serial.

DECISION: push only the delta. NLE pushes the full bucket value. CJ shows
partial values in all of its push examples. CJ also warns that a stale
`target_temperature` in a push cancels a schedule setpoint. A delta cannot
carry a stale field.

A bucket that a later subscribe sends (section 6.2) is the full stored copy.
This is the NLE behavior.

### 9.2 HVAC mode

Field: `shared.target_temperature_type`. Do not set `target_change_pending`
for a mode change. (CJ)

| HA `HVACMode` | Nest value | Needs |
|---|---|---|
| `off` | `off` | nothing |
| `heat` | `heat` | `can_heat` |
| `cool` | `cool` | `can_cool` |
| `heat_cool` | `range` | `can_heat` and `can_cool` |

Read Nest to HA with this table in the other direction. Also map `emergency`
to `heat`. (NLE) Show only the modes that the capabilities allow. (CJ) Any
other HA value: raise an error. Do not send `off`. (Handoff rule)

`can_heat` and `can_cool` are in `shared`. NLE also reads them from `device`
as a fallback. Do the same. If both are missing, treat the capability as
present. (NLE)

The Thermostat keeps its previous mode when it goes to `off`. (CJ)

### 9.3 Target temperature

| Mode | Fields |
|---|---|
| `heat`, `cool`, `emergency` | `target_temperature` |
| `range` | `target_temperature_low`, `target_temperature_high` |

- Always add `target_change_pending: true`. It wakes the display. (CJ, NLE)
- Clamp to the safety bounds. The default bounds are 7.222 °C to 35.0 °C.
  NLE reads `safety_temp_min` and `safety_temp_max` from `device`, then from
  `shared`. (NLE) CJ recommends 4.5 °C to 32.0 °C. DECISION: HA
  `min_temp = 9`, `max_temp = 32`, and clamp to those values. GAP 6.
- HA sends `ATTR_TEMPERATURE` in single modes and `ATTR_TARGET_TEMP_LOW` and
  `ATTR_TARGET_TEMP_HIGH` in `heat_cool`. HA can send `ATTR_HVAC_MODE` in the
  same call. Write the mode first, then the temperature, as one delta.
- Changes under 0.01 °C do nothing on the Thermostat. (CJ) Round to 0.5 °C
  in HA (`target_temperature_step = 0.5`).

### 9.4 Eco (HA preset `eco`)

Enter eco: structure bucket delta
`{"manual_eco_all": true, "manual_eco_timestamp": <now in s>}`. (CJ, NLE)

Exit eco: push these together: (CJ)

- structure delta: `{"manual_eco_all": false, "manual_eco_timestamp": <now s>, "away": false}`
- device delta: `{"eco": {"mode": "schedule", "touched_by": 3, "mode_update_timestamp": <now s>}}`

NLE only writes `manual_eco_all`. CJ calls the device `eco.mode` write "the
most reliable exit path". DECISION: follow CJ. Put both buckets in one push.

`manual_eco_timestamp` is in seconds. The Thermostat ignores the change if
the value is more than 600 s from its clock. (CJ) Do not use the `away` field
to enter eco. (CJ)

Read eco state: GAP 5. NLE reads `device.eco.mode == "manual-eco"` (a dict) and
`structure.manual_eco_all`. CJ says the device reports `device.eco_mode`, a
JSON string with a `mode` key. Values: `schedule`, `manual-eco`, `auto-eco`.
Read both forms. Preset `eco` is active when the mode is `manual-eco` or
`auto-eco`. Else the preset is `none`.

### 9.5 Fan

Show fan controls only if `has_fan` is true (`device`, then `shared`). (CJ, NLE)

- Fan `on`: device delta
  `{"fan_timer_timeout": <now s + duration>, "fan_timer_duration": <duration s>}`.
  CJ says to set both fields. NLE sets only the timeout. DECISION: set both.
  Duration: `device.fan_timer_duration` if present. Else
  `device.fan_timer_duration_minutes * 60` if present. Else 3600.
- Fan `auto`: device delta `{"fan_timer_timeout": 0}`.
- Read: the fan mode is `on` when `fan_timer_timeout > now s` or
  `fan_control_state` is true. Else `auto`. (NLE)

### 9.6 Out of scope for v1

Schedules (`schedule` bucket, `schedule_mode`), eco temperatures, emergency
heat as a command, temperature lock, learning, humidity control, and the
other device settings. The server must still store and serve every bucket
that it gets, with the rules in sections 6 and 7. That includes `schedule`.

## 10. Reading state for the entities

The Integration pushes state to HA. No polling. After each change to a
stored bucket, call the update callback for that serial.

| HA value | Source | Notes |
|---|---|---|
| Current temperature | `shared.current_temperature`, then `device.current_temperature` | GAP 2 |
| Current humidity | `device.current_humidity` | integer % |
| HVAC mode | `shared.target_temperature_type` | section 9.2 |
| Target temperature | `shared.target_temperature` | single modes |
| Target low and high | `shared.target_temperature_low`, `shared.target_temperature_high` | `range` |
| HVAC action | see below | |
| Fan mode | section 9.5 | |
| Preset | section 9.4 | |
| Battery level | `device.battery_level` | NLE treats it as a voltage. CJ says the battery voltage limits are 3.6 V to 3.8 V. Show the raw value as a voltage sensor. |
| Name | `shared.name`, then `shared.label`, then "Nest <serial>" | |
| Model string, firmware, MAC | `/entry` form, `device.model_version`, `device.current_version`, `device.mac_address` | device info only |

HVAC action (NLE, CJ):

1. Mode `off`: `HVACAction.OFF`.
2. Any of `hvac_heater_state`, `hvac_heat_x2_state`, `hvac_heat_x3_state`,
   `hvac_aux_heater_state`, `hvac_alt_heat_state`, `hvac_alt_heat_x2_state`,
   `hvac_emer_heat_state` true: `HEATING`.
3. Any of `hvac_ac_state`, `hvac_cool_x2_state`, `hvac_cool_x3_state` true:
   `COOLING`.
4. `hvac_fan_state` true, or the fan timer is active: `FAN`.
5. Else `IDLE`.

All `hvac_*_state` fields are in `shared`. (CJ, NLE)

Derive entities from the fields that the Thermostat reports. Do not branch on
generation or Model string. (README) For example, create the humidity sensor
only when `current_humidity` exists.

Availability: the Thermostat is available if a Subscribe or Put came in the
last `300 + 60` seconds. (DECISION)

## 11. Storage

- Use HA `helpers.storage.Store`, one store for each config entry. (Handoff)
- Contents: for each serial, all buckets as
  `{key: {"object_revision", "object_timestamp", "value"}}`, plus the chosen
  `user_id`, `structure_id`, and the `/entry` facts.
- Save with `async_delay_save` (a few seconds). Save at once on unload.
- Keep the set "structure sent since start" in memory only. It must reset when
  HA restarts. (NLE)

## 12. Timing constants

| Name | Value | Source |
|---|---|---|
| `SUSPEND_TIME_MAX` | 300 s | CJ, NLE. Range 250 to 350. |
| `HOLD_TIMEOUT` | 290 s (`SUSPEND_TIME_MAX - 10`) | CJ, NLE |
| `BATCH_WINDOW` | 3 s | CJ, NLE. Must be under 5 s. |
| `DEFER_DEVICE_WINDOW` | 15 s | NLE. CJ recommends 15 to 30. |
| `DISABLE_DEFER_WINDOW` | 60 s | CJ, NLE |
| `MAX_SUBSCRIPTIONS` | 100 per serial | NLE |
| `ECO_CLOCK_TOLERANCE` | 600 s | CJ |

## 13. Gaps

| # | Gap | Plan |
|---|---|---|
| 1 | The exact subscribe path. NLE routes `POST /nest/transport` and `POST /nest/transport/<v>/subscribe`. CJ writes `POST /{czid}/subscribe`. | The catch-all in section 3 takes all forms. Log the path at debug level on first boot. |
| 2 | `current_temperature` is in `shared` (CJ bucket table, NLE) or `device` (CJ "Read device state" table). | Read `shared` first, then `device`. |
| 3 | Does an unpaired Thermostat need the user bucket before it processes the structure bucket? Is Jeff's Thermostat paired with the NLE add-on now, and with what user ID? | Section 6.5. A capture of one subscribe request shows the `user.*` and `structure.*` keys that the Thermostat knows. |
| 4 | The weather host and the JSON format. | Return `{}` in v1. |
| 5 | The eco state field: `device.eco` (dict, NLE) or `device.eco_mode` (JSON string, CJ). | Read both. |
| 6 | The temperature range on the Thermostat dial. | 9 °C to 32 °C in v1. Check against the Thermostat. |
| 7 | Change-over from NLE. The Integration starts with no buckets. The Thermostat sends timestamps for its buckets, and the server has timestamp 0, so the server sends nothing. The server state stays partial until the Thermostat puts each field. | Test plan: reboot the Thermostat once after the Integration starts. CJ says a reboot makes the Thermostat upload its full state. Entities show "unknown" until then. |
| 8 | CJ says a server timestamp of 0 tells the Thermostat to upload its state. NLE never sends a placeholder. | Do not send placeholders in v1. Use the reboot in gap 7. |

## 14. Test cases for the build session

Each case is a request and the exact response or stored state.

1. Entry, GET and POST: the URLs have the explicit port. All paths match section 2.2.
2. Path normalization: `/entry`, `/transport/put`, and `/czfe/v7/subscribe` reach the correct handler.
3. Serial from `Basic base64("d.09AA01AB12345678.BC7C9039:pw")` is `09AA01AB12345678`.
4. Subscribe with `client_ts = 0` and a stored bucket: the bucket goes out at once, then EOF.
5. Subscribe with equal timestamps: the connection is held. A command pushes a delta chunk. EOF comes 3 s after the last chunk.
6. Subscribe with nothing to send, and no command: the server closes at the hold time with no body. Use a short hold time in the test.
7. Response field order: `object_revision`, `object_timestamp`, `object_key`, `value`.
8. `X-nl-disable-defer-window` is present only when the immediate body has a temperature or mode field.
9. Put with matching `if_object_revision`: merge, revision + 1, new timestamp, response with no `value`.
10. Put with a wrong `if_object_revision`: no merge, response is the server rev, ts, and key.
11. Put with the same values: revision and timestamp do not change.
12. Put does not push to an open Subscription.
13. Two Subscriptions for one serial: a command pushes to both. Ending one leaves the other.
14. A push to a reset connection goes to the pending buffer. The next Subscription gets it.
15. User and structure buckets: sent on the first subscribe after start, with IDs from the request keys when present.
16. Mode `heat_cool` writes `range`. An unknown mode raises an error and writes nothing.
17. Temperature in `range` writes low and high with `target_change_pending: true`.
18. Eco exit pushes the structure delta and the device `eco` delta in one chunk.
19. Store round trip: buckets survive an unload and a new setup.
