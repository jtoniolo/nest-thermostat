# NLE Server Feature Inventory

Source: `codykociemba/NoLongerEvil-SelfHosted` at commit `bca8781012639c1cefc4a08c103fc892158fb630`.

The NLE server is 10,969 lines of Python across 47 source files, plus a 1,673-line
self-contained HTML dashboard. The transport/subscribe protocol core is 1,012 lines
(`routes/nest/transport.py`). The remainder divides into MQTT bridging (~2,000 lines),
persistence and models (~1,900 lines), dashboard and control API (~1,800 lines), and
supporting infrastructure.

For each capability: what it does, where it lives, roughly how much code it is, and
what it exists to serve -- the Thermostat's requirements, the user's convenience, or
the standalone-service architecture.

---

## 1. Device-Facing Protocol

**What it is.** The HTTP server that impersonates Nest's cloud for the Firmware. This
is the irreducible core: without it, the Thermostat has nobody to talk to.

### 1.1 Service Discovery (`/nest/entry`)

- **Source:** `routes/nest/entry.py` (78 lines).
- **What it does:** The Thermostat calls this on boot (or when its Endpoint changes).
  Returns a JSON map of service URLs: `czfe_url`, `transport_url`,
  `direct_transport_url`, `passphrase_url`, `ping_url`, `pro_info_url`, `weather_url`,
  `upload_url`, `software_update_url`. All point back at the NLE server's own Routes.
  Accepts entry metadata from the device (reset reason, MAC, model string, firmware
  version).
- **Exists to serve:** Thermostat requirement. The Firmware calls `/entry` at boot and
  refuses to proceed without valid URLs.

### 1.2 Transport -- Subscribe (Long-Poll)

- **Source:** `routes/nest/transport.py` (1,012 lines), `services/subscription_manager.py` (301 lines).
- **What it does:** `POST /nest/transport` -- the main protocol endpoint. The
  Thermostat sends its current bucket revisions (device, shared, structure, schedule,
  user, and ~20 other known bucket types). The server compares timestamps, merges any
  inline state updates (value with rev/ts = 0), and responds via Transfer-Encoding:
  chunked. If the server has newer data, it sends it immediately. Otherwise it holds
  the connection open (default ~290 seconds, configurable via `SUSPEND_TIME_MAX`) and
  waits for server-side changes to push. The connection close itself is the primary
  wake mechanism (via WoWLAN); no tickle/empty body is sent on timeout.
  - Supports two request formats: named bucket fields and objects array.
  - Handles `target_change_pending` transient flag specially to avoid update loops.
  - Injects user and structure buckets for paired devices to complete pairing.
  - Inter-chunk batching: after sending the first chunk, waits up to 3 seconds for
    additional data before closing.
  - Buffers undelivered data on connection loss for replay on next subscribe.
- **Exists to serve:** Thermostat requirement. This is the Nest cloud protocol; the
  Firmware will not function without a server that speaks it.

### 1.3 Transport -- PUT (State Updates)

- **Source:** `routes/nest/transport.py` (within the same 1,012 lines).
- **What it does:** `POST /nest/transport/put` -- the Thermostat sends state deltas
  (partial bucket updates). Server merges into stored buckets. Supports conditional
  writes (`if_object_revision` -- CAS). Only bumps revision/timestamp when values
  actually changed (prevents spurious full-bucket pushes). Returns rev/ts/key only,
  not the full merged value (avoids stale-temperature race). Syncs user away/weather
  state after device bucket changes.
- **Exists to serve:** Thermostat requirement.

### 1.4 Transport -- Device Object Listing

- **Source:** `routes/nest/transport.py` (handle_transport_get, within the same file).
- **What it does:** `GET /nest/transport/device/{serial}` -- returns metadata (rev, ts,
  key) for all stored buckets for a device. Handles legacy `czfe` paths. Ensures a
  `device_alert_dialog` bucket exists for paired devices.
- **Exists to serve:** Thermostat requirement.

### 1.5 Ping

- **Source:** `routes/nest/ping.py` (27 lines).
- **What it does:** `GET /nest/ping` -- returns `{"status": "ok", "timestamp": ...}`.
- **Exists to serve:** Thermostat requirement. The Firmware pings the server to verify
  connectivity.

### 1.6 Passphrase / Entry Key (Device Pairing)

- **Source:** `routes/nest/passphrase.py` (166 lines).
- **What it does:** Two routes:
  - `GET /nest/passphrase` -- generates a 7-character alphanumeric pairing code for the
    Thermostat to display on its screen. Returns the same unexpired code on subsequent
    polls (the device re-requests until pairing completes). Creates a
    `device_alert_dialog` bucket for the pairing confirmation dialog.
  - `GET /nest/passphrase/status` -- the device polls this to check if the code has
    been claimed by a user.
  - Entry keys expire after `ENTRY_KEY_TTL_SECONDS` (default 3600).
- **Exists to serve:** Thermostat requirement (the Firmware initiates pairing via this
  endpoint). Also serves user convenience (visible pairing code).

### 1.7 Pro Info

- **Source:** `routes/nest/pro_info.py` (50 lines).
- **What it does:** `GET /nest/pro_info/{code}` -- returns stub installer information.
  The Firmware requests this for pro installer codes. The NLE server returns a generic
  "nolongerevil" response.
- **Exists to serve:** Thermostat requirement (the Firmware calls this URL; it must
  return valid JSON or the device logs errors).

### 1.8 Upload (Device Logs)

- **Source:** `routes/nest/upload.py` (53 lines).
- **What it does:** `POST /nest/upload` -- accepts device log file uploads (gzipped or
  raw). Optionally stores them to disk if `STORE_DEVICE_LOGS` is enabled. Always
  returns success.
- **Exists to serve:** Thermostat requirement (the Firmware periodically uploads
  diagnostic logs to the `upload_url`).

### 1.9 Server Info

- **Source:** `routes/nest/info.py` (69 lines).
- **What it does:** `GET /info` -- returns provisioning information: server name,
  version, `api_origin`, `cloudregisterurl`, IP, port, SSL status, and pairing
  configuration. Used by the network scanner and external tooling to identify an NLE
  server.
- **Exists to serve:** Standalone-service architecture (discovery by dashboard and
  network scanner).

### 1.10 URL Normalization

- **Source:** `middleware/url_normalizer.py` (98 lines).
- **What it does:** Middleware that maps legacy Nest URL paths (e.g. `/entry`,
  `/czfe/...`, `/transport/...`) to the canonical `/nest/` prefix. Supports backward
  compatibility with older Firmware versions.
- **Exists to serve:** Thermostat requirement (different Firmware versions use different
  URL patterns).

### 1.11 Protocol Response Headers

- **Source:** within `routes/nest/transport.py`.
- **What it does:** Every transport response includes three protocol headers:
  - `X-nl-service-timestamp` -- server time in milliseconds.
  - `X-nl-suspend-time-max` -- tells the device how long to sleep before its
    safety-net wake timer (configurable, default 300s).
  - `X-nl-defer-device-window` -- batching delay for rapid dial changes (default 15s).
  - `X-nl-disable-defer-window` -- sent when pushing temperature changes, tells the
    device to skip the defer delay (default 60s).
- **Exists to serve:** Thermostat requirement (the Firmware reads and obeys these
  headers).

---

## 2. Weather Provision

- **Source:** `services/weather_service.py` (147 lines), `routes/nest/weather.py` (60 lines).
- **What it does:** `GET /nest/weather/v1` -- proxies weather requests to
  `weather.nest.com` with a configurable cache TTL (`WEATHER_CACHE_TTL_MS`, default 10
  minutes). Disables SSL verification because Nest's weather service uses a private CA.
  Returns stale cache if the upstream is unavailable. Weather data is also synced to the
  user bucket when a device reports a postal code change (`sync_user_weather_from_device`
  in `sqlmodel_service.py`).
- **Exists to serve:** Thermostat requirement. The Firmware fetches weather to display
  on its screen; the `weather_url` in the entry response must resolve. Also user
  convenience (outdoor temperature display).

---

## 3. Persistence and Schema

- **Source:** `services/sqlmodel_service.py` (1,073 lines), `services/device_state_service.py`
  (258 lines), `services/abstract_device_state_manager.py` (395 lines), `models/` (6
  model files totaling ~270 lines), `models/converters.py` (273 lines), `models/base.py`
  (65 lines).
- **Total:** ~2,330 lines.
- **What it does:**
  - **SQLite database** at `SQLITE3_DB_PATH` (default `./data/database.sqlite`) via
    SQLModel/SQLAlchemy async with aiosqlite. Schema created at startup via
    `SQLModel.metadata.create_all`.
  - **Tables:** `DeviceObjectModel` (serial, object_key, object_revision,
    object_timestamp, value as JSON), `EntryKeyModel` (pairing codes), `UserInfoModel`,
    `DeviceOwnerModel`, `APIKeyModel`, `DeviceShareModel`, `DeviceShareInviteModel`,
    `IntegrationConfigModel`, `SessionModel` (session logging), `LogModel` (request
    logging), `WeatherDataModel` (weather cache).
  - **In-memory cache** in `DeviceStateService`: all device objects loaded into a dict
    at startup for low-latency reads. Writes go through cache and persist to SQLite.
  - **Integration manager state change notification:** on every upsert, computes
    changed fields and broadcasts a `DeviceStateChange` event to integrations (MQTT).
  - **User state management:** `update_user_away_status` aggregates away state across
    all devices owned by a user. `sync_user_weather_from_device` copies weather data
    from device postal code to the user bucket. `ensure_device_alert_dialog` bootstraps
    user and dialog buckets for paired devices.
- **Exists to serve:** Partially Thermostat requirement (state must survive server
  restarts or the device has to be factory-reset). Partially standalone-service
  architecture (the user model, API keys, sharing, and integration config only exist
  because it is a standalone service with its own user system).

---

## 4. MQTT Integration and Home Assistant Discovery

- **Source:** `integrations/mqtt/mqtt_integration.py` (875 lines),
  `integrations/mqtt/home_assistant_discovery.py` (683 lines),
  `integrations/mqtt/helpers.py` (328 lines), `integrations/mqtt/consts.py` (38 lines),
  `integrations/mqtt/topic_builder.py` (93 lines), `integrations/integration_manager.py`
  (214 lines), `integrations/base_integration.py` (79 lines).
- **Total:** ~2,310 lines.
- **What it does:**
  - **Bidirectional MQTT bridge.** Outbound: publishes device state to
    `{prefix}/{serial}/ha/state` on every state change. Inbound: subscribes to
    `{prefix}/+/ha/+/set` and `{prefix}/+/+/+/set`, dispatching commands through
    `execute_command()`.
  - **Home Assistant auto-discovery.** Publishes HA discovery payloads for up to 19
    entities per device: climate (main thermostat), temperature sensor, humidity
    sensor, outdoor temperature sensor, occupancy binary sensor, fan binary sensor,
    eco/leaf binary sensor, battery sensor, RSSI/WiFi signal sensor, filter replacement
    sensor, filter runtime sensor, time-to-target sensor, sunlight correction sensor,
    compressor lockout sensor, learning mode sensor, heat pump ready sensor, local IP
    sensor, fan timer remaining sensor, and fan duration number entity. Discovery is
    mode-aware: re-published on every state change because heat-cool mode changes which
    temperature topics are active.
  - **Availability tracking via MQTT:** publishes `online`/`offline` to
    `{prefix}/{serial}/availability`.
  - **Raw MQTT state publishing:** publishes full object JSON and individual field values
    to `{prefix}/{serial}/{object_type}` and `{prefix}/{serial}/{object_type}/{field}`.
  - **Integration manager:** lifecycle management, config polling every 10 seconds,
    state change broadcast to all active integrations.
- **Exists to serve:** Standalone-service architecture. This is the entire HA
  integration mechanism in the NLE model -- the server runs as a separate container and
  bridges to HA via MQTT. In a native HA integration, this entire layer is replaced by
  direct entity registration.

---

## 5. Web Dashboard

- **Source:** `routes/control/webui.py` (48 lines), `templates/index.html` (1,673 lines),
  `templates/nle-icon.png`, `templates/nle-favicon.png`.
- **Total:** ~1,720 lines (mostly the HTML/CSS/JS template).
- **What it does:** A self-contained single-page dashboard served at `GET /` on the
  control port. All CSS and JS are inlined (no external dependencies). Features:
  - Device status cards with real-time updates via SSE (`/api/events`).
  - Temperature control, mode switching, fan control.
  - Device pairing flow (enter entry key code, claim device).
  - Network scanner (scan subnet, configure discovered devices).
  - Device registration and deregistration.
  - Server configuration display.
  - Supports HA ingress via `X-Ingress-Path` header injection.
- **Exists to serve:** User convenience and standalone-service architecture. Without HA,
  this is the only UI. With HA, it supplements the HA dashboard.

---

## 6. Control API

### 6.1 Commands

- **Source:** `routes/control/command.py` (642 lines).
- **What it does:** `POST /command` on the control port. Dispatches 8 command types:
  - `set_temperature` -- single target or high/low range, with safety bounds clamping.
  - `set_mode` -- HVAC mode (off/heat/cool/heat-cool/emergency). Validates device
    capabilities (`can_heat`, `can_cool`, `has_emer_heat`). Rejects "eco" (must use
    `set_away`).
  - `set_away` -- eco/away via `manual_eco_all` in structure bucket. Uses manual-eco
    instead of away because firmware's schedule preconditioning reverts auto-eco.
    Requires `manual_eco_timestamp` within 600s of device clock.
  - `set_fan` -- on/auto/duration. Checks `has_fan` capability.
  - `set_eco_temperatures` -- eco high/low bounds.
  - `set_schedule` -- full weekly schedule replacement (ver 2 format, validated).
  - `set_schedule_mode` -- HEAT/COOL/RANGE.
  - `set_device_setting` -- generic setter for ~45 whitelisted device bucket fields
    (safety temps, temp lock, learning mode, humidity, display, sunblock, fan duty
    cycle, heat pump thresholds, hot water, filter, locale).
  - Each command routes to the correct bucket (shared, device, structure, or schedule),
    merges or replaces, and pushes to the device via subscription manager.
- **Exists to serve:** User convenience (remote control). Also the dispatch layer used
  by MQTT inbound commands.

### 6.2 Status and Device Listing

- **Source:** `routes/control/status.py` (508 lines).
- **What it does:** Multiple endpoints on the control port:
  - `GET /status?serial=X` -- full device status (temperatures, mode, HVAC state,
    capabilities, eco, safety, learning, network info, api_key).
  - `GET /api/devices` -- list all registered devices with status.
  - `GET /api/schedule?serial=X` -- device schedule.
  - `GET /api/stats` -- server statistics (device count, subscription stats,
    availability).
  - `GET /api/config` -- server config for dashboard (api_origin, pairing mode).
  - `GET /api/events` -- Server-Sent Events stream for real-time UI updates.
  - `POST /notify-device` -- force notification to all subscribers (testing/refresh).
  - `POST /api/dismiss-pairing/{serial}` -- dismiss pairing dialog on device.
  - `DELETE /api/device` -- delete a device and all its stored state.
- **Exists to serve:** User convenience and standalone-service architecture (dashboard
  data source).

### 6.3 Network Scanner

- **Source:** `routes/control/scan.py` (164 lines).
- **What it does:**
  - `POST /api/scan-network` -- scans the /24 subnet derived from `API_ORIGIN` for
    Nest devices by probing port 8080 (the Firmware's Settings API) on all 254 hosts
    concurrently (2-second timeout per probe). Returns each found device's IP, name,
    current `cloudregisterurl`, and whether it already points at this server.
  - `POST /api/configure-nest` -- POST to a discovered device's Settings API to point
    it at this NLE server. Accepts an optional `api_key` for authenticated configuration.
- **Exists to serve:** User convenience and standalone-service architecture. In an HA
  integration, the Settings API would be called directly from the config flow.

### 6.4 Registration

- **Source:** `routes/control/registration.py` (418 lines).
- **What it does:**
  - `POST /api/register` -- claim an entry key and register a device to a user. Creates
    ownership record, pushes user + structure buckets to complete pairing.
  - `GET /api/registered-devices` -- list devices registered to a user.
  - `DELETE /api/registered-devices/{serial}` -- delete device registration.
  - `POST /api/ensure-user` -- ensure a user exists in the database.
  - `POST /api/mqtt-config` -- configure MQTT integration via API.
- **Exists to serve:** Standalone-service architecture (NLE's own user/device management).

---

## 7. API Keys and Device Auth

### 7.1 API Key Authentication

- **Source:** `middleware/api_key_auth.py` (224 lines).
- **What it does:** Authenticates control API requests via API keys (prefix `nlapi_`).
  Supports `Authorization: Bearer` and `X-API-Key` headers. Keys are SHA-256 hashed in
  the database. Supports expiration, per-device scoping, and per-scope permissions
  (read/write/admin). Includes a `@require_api_key` decorator for protecting endpoints.
  In practice, the control API endpoints do not currently use this decorator, but the
  infrastructure exists.
- **Exists to serve:** Standalone-service architecture (multi-user access control).

### 7.2 Device Auth (Three-Tier)

- **Source:** `middleware/device_auth.py` (140 lines).
- **What it does:** Middleware on the device-facing port. Three tiers:
  - **PAIRED** -- device has an ownership record: full access.
  - **PENDING** -- device has an active entry key but no owner: subscribe OK, PUT
    silently dropped, upload rejected.
  - **UNKNOWN** -- no entry key, no owner: transport gets 401, only entry/passphrase
    allowed.
  - Captures the device's `api_key` (Basic Auth password) on every request and caches
    it in memory. This key is the credential needed to configure the device via its
    Settings API (`POST /cgi-bin/api/settings`), and is displayed in the dashboard.
  - When `REQUIRE_DEVICE_PAIRING` is `false` (default), all devices are treated as
    paired.
- **Exists to serve:** Both. The tiered auth model serves user convenience (security
  against rogue devices). The api_key capture serves user convenience (displays the
  credential needed for device configuration). The `REQUIRE_DEVICE_PAIRING` toggle
  serves standalone-service architecture (operator configuration).

---

## 8. Device Sharing, Pairing, and Structure Assignment

### 8.1 Device Sharing

- **Source:** `models/sharing.py` (41 lines), `services/sqlmodel_service.py` (sharing
  operations, ~100 lines within the service).
- **What it does:** Share device access with other users via `DeviceShare` records.
  Supports permission levels: `READ`, `WRITE`, `CONTROL`, `ADMIN`. Share invitations
  via tokens with accept/expire flow.
- **Exists to serve:** Standalone-service architecture (multi-user support). In HA, user
  access is managed by HA's own user system.

### 8.2 Pairing Flow

- **Source:** Spread across `routes/nest/passphrase.py`, `routes/control/registration.py`,
  `middleware/device_auth.py`, and `routes/nest/transport.py`.
- **What it does:** End-to-end pairing:
  1. Device calls `/nest/passphrase`, gets a 7-character code, displays it on screen.
  2. User reads code, enters it in the dashboard or API (`POST /api/register`).
  3. Server claims the entry key, creates a `DeviceOwner` record, pushes user + structure
     buckets to the device's held subscribe connection.
  4. Device receives user bucket (with `name` field), completes pairing.
  5. Dashboard dismisses pairing dialog via `POST /api/dismiss-pairing/{serial}`.
- **Exists to serve:** Partially Thermostat requirement (the Firmware's pairing protocol
  requires user + structure buckets). Partially standalone-service architecture (the
  entry-key-claim flow is the NLE server's user onboarding).

### 8.3 Structure Assignment

- **Source:** `utils/structure_assignment.py` (85 lines).
- **What it does:** Derives a structure ID from the device owner's user ID (strips
  `user_` prefix). Auto-assigns `structure_id` to device values when missing. Creates
  structure buckets with a "Home" name and device list. Forces structure bucket delivery
  on first connect after server restart.
- **Exists to serve:** Thermostat requirement (the Firmware requires a structure bucket
  for away mode and device grouping).

---

## 9. Availability and Heartbeat Tracking

- **Source:** `services/device_availability.py` (215 lines), `middleware/device_heartbeat.py`
  (45 lines).
- **What it does:**
  - **Heartbeat middleware:** on every device-facing request, marks the device as "seen"
    in the availability tracker.
  - **Availability service:** background task that checks every 30 seconds whether
    devices have been seen within the timeout window (default 300 seconds). Marks
    devices as unavailable after timeout. Notifies integration manager on connect/
    disconnect (triggers MQTT availability messages). Tracks initial availability from
    known serials loaded from storage.
- **Exists to serve:** User convenience (know if the device is online). Also serves the
  MQTT integration (online/offline availability topics for HA).

---

## 10. Fan Timers and Temperature Safety

### 10.1 Fan Timer Preservation

- **Source:** `utils/fan_timer.py` (133 lines).
- **What it does:** When the Thermostat sends a state update, preserves active fan timer
  fields (`fan_timer_timeout`, `fan_control_state`, `fan_timer_duration`,
  `fan_current_speed`, `fan_mode`) unless the update explicitly turns the fan off.
  Prevents device state updates from accidentally clearing a running fan timer.
- **Exists to serve:** Thermostat requirement (protocol compliance -- the Firmware
  expects fan timer state to survive across subscribe cycles).

### 10.2 Temperature Safety Bounds

- **Source:** `utils/temperature_safety.py` (144 lines).
- **What it does:** Enforces configurable min/max temperature limits on all temperature
  commands. Default bounds: 7.2C (45F) to 35C (95F). Reads device-specific bounds from
  `safety_temp_min`/`safety_temp_max` in device or shared buckets. Clamps values and
  logs warnings. Applied to: `target_temperature`, `target_temperature_high`,
  `target_temperature_low`, `away_temperature_high`, `away_temperature_low`.
- **Exists to serve:** User convenience (prevent extreme setpoints). Partially
  Thermostat requirement (the Firmware has its own safety limits, but the server
  enforces them too to catch bad commands before they reach the device).

---

## 11. Configuration Surface

Every environment variable and what it controls.

### 11.1 Server Identity and Networking

| Variable | Default | What it controls | Source |
|---|---|---|---|
| `API_ORIGIN` | `http://localhost:8000` | Base URL the Thermostat is told to call back on. Used in entry response URLs. Must be reachable from the Thermostat's network. | `config/environment.py` `api_origin` |
| `SERVER_PORT` | `8000` | Port for the device-facing HTTP server. | `config/environment.py` `server_port` |
| `CONTROL_PORT` | `8082` | Port for the control/dashboard HTTP server. | `config/environment.py` `control_port` |
| `CERT_DIR` | (none) | Directory containing `fullchain.pem` and `privkey.pem` for TLS. When set, the device-facing server serves HTTPS. | `config/environment.py` `cert_dir` |

### 11.2 Device Pairing

| Variable | Default | What it controls | Source |
|---|---|---|---|
| `REQUIRE_DEVICE_PAIRING` | `false` | When true, devices must complete entry-key pairing before transport access. When false, any device can PUT and subscribe without registration. | `config/environment.py` `require_device_pairing` |
| `ENTRY_KEY_TTL_SECONDS` | `3600` | How long a pairing code remains valid before expiring. | `config/environment.py` `entry_key_ttl_seconds` |

### 11.3 Protocol Timing

| Variable | Default | What it controls | Source |
|---|---|---|---|
| `SUSPEND_TIME_MAX` | `300` | Device's safety-net wake timer, in seconds. The server closes the connection 10 seconds before this. Must be 5-350s (WiFi keepalive constraint). Sent to the device as `X-nl-suspend-time-max`. | `config/environment.py` `suspend_time_max` |
| `DEFER_DEVICE_WINDOW` | `15` | Delay (seconds) before device sends PUT after local changes. Batches rapid dial turns. Sent as `X-nl-defer-device-window`. | `config/environment.py` `defer_device_window` |
| `DISABLE_DEFER_WINDOW` | `60` | After pushing temperature/mode changes, temporarily disable the defer delay for this many seconds. Sent as `X-nl-disable-defer-window`. | `config/environment.py` `disable_defer_window` |
| `MAX_SUBSCRIPTIONS_PER_DEVICE` | `100` | Maximum concurrent long-poll subscriptions per device. | `config/environment.py` `max_subscriptions_per_device` |

### 11.4 Weather

| Variable | Default | What it controls | Source |
|---|---|---|---|
| `WEATHER_CACHE_TTL_MS` | `600000` | How long (milliseconds) to cache weather responses before re-fetching from `weather.nest.com`. | `config/environment.py` `weather_cache_ttl_ms` |

### 11.5 Persistence

| Variable | Default | What it controls | Source |
|---|---|---|---|
| `SQLITE3_DB_PATH` | `./data/database.sqlite` | Path to the SQLite database file. Parent directory created automatically. | `config/environment.py` `sqlite3_db_path` |

### 11.6 MQTT

| Variable | Default | What it controls | Source |
|---|---|---|---|
| `MQTT_HOST` | (none) | MQTT broker hostname. Setting this enables MQTT integration. | `config/environment.py` `mqtt_host` |
| `MQTT_PORT` | `1883` | MQTT broker port. | `config/environment.py` `mqtt_port` |
| `MQTT_USER` | (none) | MQTT username. | `config/environment.py` `mqtt_user` |
| `MQTT_PASSWORD` | (none) | MQTT password. | `config/environment.py` `mqtt_password` |
| `MQTT_TOPIC_PREFIX` | `nolongerevil` | Prefix for all MQTT topics. | `config/environment.py` `mqtt_topic_prefix` |
| `MQTT_DISCOVERY_PREFIX` | `homeassistant` | Home Assistant MQTT discovery prefix. | `config/environment.py` `mqtt_discovery_prefix` |

### 11.7 Debug and Logging

| Variable | Default | What it controls | Source |
|---|---|---|---|
| `DEBUG_LOGGING` | `false` | Enable detailed per-request JSON log files in `DEBUG_LOGS_DIR`. | `config/environment.py` `debug_logging` |
| `DEBUG_LOGS_DIR` | `./data/debug-logs` | Directory for debug request/response log files. | `config/environment.py` `debug_logs_dir` |
| `STORE_DEVICE_LOGS` | `false` | Store device-uploaded log files to disk. | `config/environment.py` `store_device_logs` |
| `DEVICE_LOGS_DIR` | `./data/device-logs` | Directory for stored device logs, organized by serial. | `config/environment.py` `device_logs_dir` |

---

## 12. Supporting Infrastructure (Not a Feature Category, but Contributes)

### 12.1 Serial Parser

- **Source:** `lib/serial_parser.py` (225 lines).
- Extracts device serial from Basic Auth, `X-nl-serial` header, query parameters, and
  request path. Also extracts Weave device ID from `X-nl-weave-device-id` header and
  Basic Auth password (the device's api_key).

### 12.2 Debug Logger Middleware

- **Source:** `middleware/debug_logger.py` (144 lines).
- When `DEBUG_LOGGING` is enabled, logs every request and response as individual JSON
  files. Passthrough when disabled.

### 12.3 Dual-Port Architecture

- **Source:** `main.py` (383 lines).
- The NLE server runs two separate aiohttp applications on different ports: a
  device-facing "proxy" app with protocol middleware (URL normalizer, device auth,
  heartbeat, debug logger) and a control app with CORS and dashboard routes. The
  keepalive timeout on the proxy app is set to `connection_hold_timeout + 60` to prevent
  premature connection closes during long-poll.
- **Exists to serve:** Standalone-service architecture. The dual-port design separates
  the trusted device protocol from the user-facing API, allowing different middleware
  stacks and security models.

### 12.4 CORS

- **Source:** `main.py` (within `create_control_app`).
- The control API sends `Access-Control-Allow-Origin: *` on all responses. Allows the
  dashboard and external tools to call the API from any origin.
- **Exists to serve:** Standalone-service architecture (browser-based dashboard).

### 12.5 TLS

- **Source:** `main.py` (`get_ssl_context`).
- Optional TLS on the device-facing port via `CERT_DIR`. Loads `fullchain.pem` and
  `privkey.pem`.
- **Exists to serve:** Both. The Firmware supports HTTPS, and production deployments
  should use it. This is a deployment concern of a standalone service.

### 12.6 Docker and Deployment

- **Source:** `docker-compose.yml`, `Dockerfile` (not read, but referenced in README),
  `pyproject.toml`.
- Docker Compose with named volume for data persistence. Health check via
  `urllib.request.urlopen` to the control port. JSON log driver with rotation.
  Published to `ghcr.io/codykociemba/nolongerevil-selfhosted`.
- **Exists to serve:** Standalone-service architecture.

---

## Summary by Purpose

| Purpose | Capabilities | Approx. Lines |
|---|---|---|
| **Thermostat requirement** (must exist for the Firmware to function) | Entry, transport subscribe/PUT/GET, ping, passphrase, pro_info, upload, weather proxy, URL normalization, protocol headers, structure assignment, fan timer preservation | ~2,100 |
| **User convenience** (useful regardless of architecture) | Temperature safety, availability tracking, command dispatch, device status API, weather display | ~1,200 |
| **Standalone-service architecture** (exists because NLE is not part of HA) | MQTT bridge + HA discovery, web dashboard, dual-port server, API key auth, device sharing, registration/user management, network scanner, control API, CORS, TLS, Docker, persistence of user/integration/sharing state, SSE events | ~7,700 |

The "standalone-service" column is the large majority of the codebase. Much of it --
the entire MQTT layer, the dashboard, user/sharing/API-key management, network scanner,
SSE, dual-port architecture -- exists solely because the NLE server is a standalone
container that bridges to Home Assistant indirectly. A native HA integration replaces
that layer with HA's own entity system, config flow, user model, and UI.
