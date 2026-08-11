# NLE server undocumented surfaces

Behavioural reference derived from reading the NLE server source
(`codykociemba/NoLongerEvil-SelfHosted`, MIT).
No code, comments, or test fixtures are reproduced.
Field names, Route paths, header names, and query parameter names are wire-protocol
facts.

Vocabulary follows `CONTEXT.md`: Thermostat, Firmware, Integration, NLE server,
Endpoint, Route, Advertised URL, Settings API.

---

## 1. `weather_url`

**Source:** `routes/nest/weather.py`, `services/weather_service.py`

### How the Thermostat discovers it

The `/nest/entry` response includes a `weather_url` field.
The NLE server sets it to `{api_origin}/nest/weather/v1?query=`, with a trailing
`?query=` so the Thermostat can append its query parameters directly.

### Route

`GET /nest/weather/v1` (also `GET /nest/weather/{path}` as a catch-all).
Legacy paths without the `/nest` prefix (`/weather/...`) are rewritten by the URL
normalizer middleware.

### Request shape

A plain GET with query parameters. The Thermostat sends at minimum:

- `postal_code` -- ZIP or postal code
- `country` -- two-letter country code (e.g., `US`)

The NLE server reads these from the query string but also captures the entire raw
query string to pass through verbatim to the upstream weather API.

### Response shape

The response is a JSON object proxied from `https://weather.nest.com/weather/v1`.
The NLE server does not define or transform the schema; it forwards whatever Nest's
weather API returns. On success the status is 200 with the upstream JSON body.

### Caching

The NLE server caches weather responses keyed by `(postal_code, country)`.
When neither is provided, the cache key defaults to `("ip", "auto")`.
Cache TTL is configurable via `WEATHER_CACHE_TTL_MS` (default 600,000 ms = 10 minutes).
On a cache miss, the server fetches from Nest's weather endpoint.
On a fetch failure, it returns stale cached data if any exists; otherwise it returns
HTTP 502 with `{"error": "Weather service unavailable"}`.

### SSL note

The upstream `weather.nest.com` uses a private certificate authority
("Nest Private Server Certificate Authority") that is not in public trust stores.
The NLE server disables SSL verification for outbound requests to it.

### What happens if the Integration answers wrongly or not at all

If the weather Route returns an error or no data, the Thermostat loses ambient weather
display but continues functioning for HVAC control. Weather is informational; no
control logic depends on it. The NLE server returns 502 on upstream failure, which
the Thermostat handles gracefully.

---

## 2. `upload_url`

**Source:** `routes/nest/upload.py`

### How the Thermostat discovers it

The `/nest/entry` response includes an `upload_url` field, set to
`{api_origin}/nest/upload`.

### Route

`POST /nest/upload`.
Legacy path `/upload` is rewritten by the URL normalizer.

### Request shape

The Thermostat POSTs a raw binary body containing a device log file.
The body may be gzip-compressed.
The device serial is extracted from the request's `Authorization` header (HTTP Basic
Auth) or fallback headers, the same way as all other Nest Routes.

### Response shape

The NLE server always returns `{"status": "ok"}` with HTTP 200, regardless of whether
the log was actually stored. There is no error response -- the handler catches all
exceptions internally and still returns 200.

### Storage behaviour

Log storage is gated by a `STORE_DEVICE_LOGS` environment variable (default: off).
When enabled, logs are saved to `{DEVICE_LOGS_DIR}/{serial}/{timestamp}.log`.
If the payload is gzip-compressed, the server decompresses before writing; if
decompression fails (not actually gzipped), it writes the raw bytes.

### Auth gating

When `REQUIRE_DEVICE_PAIRING` is enabled, the device auth middleware rejects uploads
from PENDING-tier devices (those with an active entry key but no ownership record)
with HTTP 401. PAIRED devices pass through; UNKNOWN devices are rejected at the
transport gate before reaching this handler.

### What happens if the Integration answers wrongly or not at all

The Thermostat treats log upload as fire-and-forget. A non-200 response or a
connection failure does not affect Thermostat operation. The simplest valid
implementation is to accept the POST and return `{"status": "ok"}` without storing
anything.

---

## 3. `pro_info_url`

**Source:** `routes/nest/pro_info.py`

### How the Thermostat discovers it

The `/nest/entry` response includes a `pro_info_url` field, set to
`{api_origin}/nest/pro_info`.

### Route

`GET /nest/pro_info/{code}`.
Legacy path `/pro_info/{code}` is rewritten by the URL normalizer.

### Request shape

A plain GET. The `{code}` path parameter is a professional installer code -- a short
identifier that HVAC installers register with Nest.

### Response shape

The NLE server returns a JSON object with installer information fields:

- `id` -- numeric identifier (hardcoded to 1)
- `pro_id` -- echoes back the `{code}` from the path
- `dba` -- business name (NLE uses "nolongerevil")
- `locality` -- location description
- `website` -- URL
- `rating` -- numeric rating (NLE uses 5.0)

Optional fields that the NLE server leaves commented out but that exist in the
original schema: `street_address_1`, `street_address_2`, `region`, `postal_code`,
`email`, `phone`, `plain_email_address_for_referrals`.

### What happens if the Integration answers wrongly or not at all

Pro info is purely informational -- it populates the "installed by" screen on the
Thermostat. A missing or malformed response does not affect HVAC operation. The
simplest valid implementation is to return a minimal JSON object echoing the code
in `pro_id`.

---

## 4. `/info`

**Source:** `routes/nest/info.py`

### Route

`GET /info` (note: no `/nest` prefix -- this is at the server root).

### Purpose

Server provisioning discovery. This is not called by the Thermostat during normal
operation -- it is a convenience Route for humans or setup tools to discover the
server's connection parameters before configuring a Thermostat's Endpoint.

### Request shape

A plain GET with no parameters and no authentication.

### Response shape

JSON object with the following fields:

- `server` -- always the string `"nolongerevil"`
- `version` -- server software version (read from package metadata, fallback `"1.0.1"`)
- `api_origin` -- the configured base URL for Thermostat connections
- `cloudregisterurl` -- the value to write into the Thermostat's
  `/etc/nestlabs/client.config` (set to `{api_origin}/entry`)
- `ip` -- the IP address of the server (resolved from the hostname in `api_origin`;
  if the hostname is already an IP, it is used directly; on DNS failure, the raw
  hostname is returned)
- `port` -- the port extracted from `api_origin` (defaults to 443 for HTTPS, 80 for
  HTTP if not explicit)
- `ssl` -- boolean, true if `api_origin` uses the `https` scheme
- `require_device_pairing` -- boolean, current value of the pairing gate setting
- `entry_key_ttl_seconds` -- how long entry keys remain valid (integer, seconds)

### What happens if the Integration answers wrongly or not at all

No impact on the Thermostat. This Route is for human/tool consumption only. The
Integration may choose not to implement it at all if it exposes its own configuration
UI through Home Assistant.

---

## 5. Device authentication and pairing

**Source:** `middleware/device_auth.py`, `routes/nest/passphrase.py`,
`routes/nest/entry.py`, `routes/control/registration.py`,
`lib/serial_parser.py`

### The `REQUIRE_DEVICE_PAIRING` setting

The NLE server has a boolean setting `REQUIRE_DEVICE_PAIRING` that defaults to
**false** (open mode). When false, all devices are treated as PAIRED and can
subscribe and PUT without any prior registration.

When true, the server enforces a three-tier authentication model.

### Three-tier auth model

The device auth middleware runs on every request to the proxy (device-facing) app
and assigns one of three tiers, stored on the request as `device_auth_tier`:

1. **PAIRED** -- the device has a `DeviceOwner` record in the database. Full access
   to all transport Routes.

2. **PENDING** -- the device has an active (unexpired, unclaimed) entry key but no
   ownership record. Allowed to subscribe (to receive pairing buckets when
   registration completes), but PUT requests are silently accepted and discarded
   (the server returns `{"objects": []}` without processing), and uploads are
   rejected with HTTP 401.

3. **UNKNOWN** -- no entry key, no owner. Only the entry, passphrase, ping, weather,
   and device GET Routes are allowed. Transport POSTs and uploads get HTTP 401 with
   `{"error": "Device not authorized. Complete pairing first."}`.

Routes that are **not** gated (allowed regardless of tier): `/nest/entry`,
`/nest/passphrase`, `/nest/ping`, `/nest/weather/*`, `/nest/pro_info/*`,
GET requests to `/nest/transport/device/*`, and `/info`.

Routes that **are** gated: POST to any path containing `/nest/transport`, and POST
to `/nest/upload`.

### Basic Auth username convention: `d.{SERIAL}.{suffix}`

The Thermostat authenticates to the server using HTTP Basic Auth on every request.

The **username** encodes the device serial. Two formats are observed:

- **`nest.{SERIAL}`** -- a dotted prefix form where the serial follows `nest.`
- **`d.{SERIAL}.{random}`** -- used in the `X-nl-client-id` header when the device
  has DEFAULT credentials (no valid session). The first segment is `d`, the second
  is the serial, the third is a random suffix.

The server's serial extraction logic handles both: it splits on `.` and takes the
second segment if the string contains dots. If there is no dot, the entire username
is treated as the serial. Serials are sanitized to uppercase alphanumeric only and
must be at least 10 characters.

The **password** is the device's `api_key` -- the same credential needed to
configure the device via its Settings API (`POST /cgi-bin/api/settings` with an
`api_key` field). The NLE server caches this password from every incoming request
into an in-memory dictionary keyed by serial, so that the control API can later use
it to send commands to the device's Settings API. This cache is repopulated within
minutes of a server restart as devices reconnect.

### Additional serial extraction headers

Beyond Basic Auth, the server tries these sources in order to extract the serial
from any request:

1. `Authorization` header (Basic Auth username, as described above)
2. `X-nl-client-id` header (the `d.{SERIAL}.{random}` format)
3. `X-nl-device-id` header (raw serial)
4. `X-NL-Device-Serial` header (raw serial)
5. `serial` query parameter
6. `serial` URL path parameter

### Pairing flow

1. **Thermostat connects** to the server's `/nest/entry` Route and receives service
   URLs. No auth check occurs here.

2. **Thermostat requests an entry key** via `GET /nest/passphrase`. The server
   generates a 7-character alphanumeric code, stores it with the device serial and
   an expiration time (`ENTRY_KEY_TTL_SECONDS`, default 3600), and returns
   `{"value": "<code>", "expires": <millisecond_timestamp>}`.
   If an unexpired, unclaimed key already exists for this serial, the same key is
   returned (prevents invalidation during the polling loop).

   The server also creates a `device_alert_dialog.{serial}` bucket with
   `dialog_id: "confirm-pairing"` so the device displays a pairing confirmation
   screen.

3. **Thermostat displays the code** on its screen and begins polling
   `GET /nest/passphrase/status` to check whether the code has been claimed.
   Status responses:
   - `{"status": "no_key", "claimed": false}` -- no key exists
   - `{"status": "pending", "claimed": false, "expiresAt": <ms>}` -- key exists,
     not yet claimed
   - `{"status": "claimed", "claimed": true, "claimedBy": "<userId>",
     "claimedAt": <ms>}` -- key claimed, pairing complete

4. **User enters the code** into the NLE server's control API via
   `POST /api/register` with body `{"code": "<7-char-code>", "userId": "homeassistant"}`.
   The server validates the code, creates a `DeviceOwner` record linking the serial
   to the user, and immediately pushes a `user.{userId}` bucket (containing a `name`
   field set to the user ID) and a `structure.{structureId}` bucket (containing
   `name: "Home"` and `devices: [serial]`) to any held subscribe connections.

   The user bucket's `name` field is what triggers pairing completion on the device
   side. The structure bucket alone is not sufficient.

5. **On subsequent subscribes**, the transport handler checks for a `DeviceOwner`
   record and, if the device is paired, injects the user and structure buckets into
   the subscribe response whenever the device's timestamps are behind the server's.
   On the first connect after a server restart, the structure bucket is force-sent
   even if timestamps match, because the device's internal mode may have reset while
   its cached timestamp persists in flash.

---

## 6. Error responses

**Source:** `routes/nest/transport.py`, `middleware/device_auth.py`

### Transport Routes

The transport handler returns structured JSON errors for malformed requests:

- **Missing serial:** HTTP 400, `{"error": "Device serial required"}`
- **Invalid JSON body:** HTTP 400, `{"error": "Invalid JSON"}`
- **Invalid request structure:** HTTP 400, plain text
  `"Invalid request: objects array required"`
- **Too many subscriptions:** The handler does not return an error status; instead it
  sends an empty `{"objects": []}` response and closes the connection, so the device
  will resubscribe.

### Auth errors (when `REQUIRE_DEVICE_PAIRING` is true)

- **Unknown device on gated route:** HTTP 401,
  `{"error": "Device not authorized. Complete pairing first."}`
- **Pending device on upload:** HTTP 401, `{"error": "Not authorized"}`
- **Pending device on PUT:** HTTP 200, `{"objects": []}` (silently accepted, not
  processed)
- **Missing serial on gated route:** HTTP 400,
  `{"error": "Device serial required"}`

### Other Routes

- **Weather failure:** HTTP 502, `{"error": "Weather service unavailable"}`
- **Passphrase without serial:** HTTP 400, `{"error": "Device serial required"}`
- **Entry key generation failure:** HTTP 503,
  `{"error": "Entry key service unavailable"}`

### Pattern

All JSON error responses use the shape `{"error": "<message>"}`.
The server never returns HTML error pages to the Thermostat.
Non-auth errors use 4xx status codes; upstream proxy failures use 502; service
unavailability uses 503.

---

## 7. `if_object_revision` conflict semantics

**Source:** `routes/nest/transport.py` (PUT handler), `tests/test_transport_put.py`

### What it is

`if_object_revision` is a conditional-write (compare-and-swap) field that the
Thermostat may include in a PUT request for a given bucket. When present, it
asserts "only apply this write if the server's current `object_revision` for this
bucket matches this value."

### How the NLE server handles it

In the PUT handler, for each object in the request:

1. If `if_object_revision` is present in the request object, the server compares
   it against the current `object_revision` stored on the server for that
   `object_key`.

2. **Match:** the write proceeds normally -- the server merges the client's value
   into the stored bucket, bumps revision and timestamp (if values actually changed),
   and returns the result.

3. **Mismatch (CAS conflict):** the server **skips the merge** for this bucket.
   It returns only `object_revision`, `object_timestamp`, and `object_key` for
   the conflicting bucket -- crucially, **no `value` field** is included in the
   response. This is deliberate: omitting the value means the device keeps its
   local state and dirty flags intact, so it will retry the PUT on the next cycle
   with the updated revision number. If the server echoed back the merged value,
   it would overwrite the device's local state and clear its dirty flags, silently
   dropping the rejected write with no opportunity for retry.

4. **Per-bucket, not per-request:** a CAS conflict on one bucket does not abort
   the rest of the request. Other buckets in the same PUT are processed normally.
   The response always contains one entry per input bucket.

### `base_object_revision`

The PUT body may also include `base_object_revision`. The NLE server logs it but
does **not** use it for any rejection logic -- it is purely informational. Only
`if_object_revision` triggers a conditional check.

### Revision and timestamp bump rules

- Revision and timestamp are only bumped when the merged value actually differs from
  the stored value. Sending identical values in consecutive PUTs does not advance
  either counter. This prevents spurious full-bucket pushes on the next subscribe
  cycle.
- When values do change, the revision increments by 1 and the timestamp is set to
  the current time in milliseconds.
- Timestamp is the sole authority for sync decisions in the subscribe path (see next).

### Interaction with subscribe

The subscribe handler uses **timestamp-only comparison** to decide what data to push
to the Thermostat. There is no revision tiebreaker: if the server's timestamp is
strictly greater than the client's, the server sends its data. Equal timestamps mean
"already synced" and no data is sent.

A zero timestamp from the client means "no data" and always triggers the server to
send its state. A zero timestamp from the server means "no data" and the server has
nothing to send.

### PUT response shape

After the CAS-echo fix, PUT responses contain **only** `object_revision`,
`object_timestamp`, and `object_key` for each bucket -- never `value`. The device
already knows what it sent; the subscribe channel handles server-to-device pushes.
Echoing the full merged bucket in the PUT response previously caused race conditions
where stale `target_temperature` values from the server's stored state would
overwrite the device's schedule-derived setpoint.

### PUT does not notify subscribers

The PUT handler does not push to long-poll subscribers. Previously it did, and this
caused a race condition: if TCP delivery of the subscribe chunk was delayed past a
schedule transition, the stale pre-schedule target temperature would overwrite the
new value. Since the device already receives its confirmation in the PUT response,
and the subscribe path handles server-to-device pushes via timestamp comparison,
there is no need for the PUT to also notify.

---

## 8. URL normalization (legacy path compatibility)

**Source:** `middleware/url_normalizer.py`, `tests/test_url_normalizer.py`

The NLE server normalizes legacy Firmware paths that lack the `/nest` prefix.
This middleware runs first, before body reading or auth.

Mappings:

| Legacy path | Normalized to |
|---|---|
| `/entry` | `/nest/entry` |
| `/ping` | `/nest/ping` |
| `/passphrase` | `/nest/passphrase` |
| `/czfe/*` | `/nest/transport/*` |
| `/transport/*` | `/nest/transport/*` |
| `/weather/*` | `/nest/weather/*` |
| `/upload` | `/nest/upload` |
| `/pro_info/*` | `/nest/pro_info/*` |

Paths that already start with `/nest/` pass through unchanged.
The `/czfe/` prefix is notable -- it refers to the Nest cloud's "Cloud Zoo Front End"
gateway, meaning older Firmware versions may use this path prefix.

The Integration should accept both prefixed and unprefixed forms, or at minimum the
forms the Firmware actually sends (observable on first connection).

---

## 9. Entry response: the complete service URL contract

**Source:** `routes/nest/entry.py`

For completeness, the full set of fields the NLE server returns from
`GET|POST /nest/entry`:

| Field | Value |
|---|---|
| `czfe_url` | `{origin}/nest/transport` |
| `transport_url` | `{origin}/nest/transport` |
| `direct_transport_url` | `{origin}/nest/transport` |
| `passphrase_url` | `{origin}/nest/passphrase` |
| `ping_url` | `{origin}/nest/transport` |
| `pro_info_url` | `{origin}/nest/pro_info` |
| `weather_url` | `{origin}/nest/weather/v1?query=` |
| `upload_url` | `{origin}/nest/upload` |
| `software_update_url` | `""` (empty string) |
| `server_version` | `"1.0.0"` |
| `tier_name` | `"local"` |

`{origin}` is the configured `API_ORIGIN` with an explicit port always included
(even for standard ports), because the Thermostat may fail to extract the port from
the URL for TCP keepalive offload (WoWLAN) if it is omitted.

The entry request body is `application/x-www-form-urlencoded` and may include:
`reset` (reset reason), `mac`, `model`, `software_version`, `request_id`.
Both GET and POST are accepted.

---

## 10. Heartbeat middleware

**Source:** `middleware/device_heartbeat.py`

Every request to the device-facing app passes through a heartbeat middleware that
extracts the serial and marks the device as "seen" in the device availability tracker.
This is how the NLE server knows a device is online without requiring a dedicated
ping -- any request (subscribe, PUT, weather, upload) counts as a heartbeat.

The Integration should do the same: update the device's last-seen timestamp on any
inbound request, rather than relying on a separate availability-check mechanism.
