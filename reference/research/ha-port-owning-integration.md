# HA prior art: port-owning custom integration

Research for issue jtoniolo/nest-thermostat#4. Patterns a build session needs when
the Integration binds its own socket and accepts inbound connections from the
Thermostat.

**HA version read against:** 2026.9.0.dev0 (`dev` branch, pyproject.toml).

---

## 1. The aiohttp AppRunner / TCPSite lifecycle

### How emulated_hue does it

`emulated_hue` is YAML-configured (no config entry), so the lifecycle is simpler —
it is the clearest example of a raw AppRunner/TCPSite in HA core.

**Setup** (`homeassistant/components/emulated_hue/__init__.py`):

```python
async def async_setup(hass, yaml_config):
    local_ip = await async_get_source_ip(hass)
    config = Config(hass, yaml_config.get(DOMAIN, {}), local_ip)
    await config.async_setup()

    app = web.Application()
    app[KEY_HASS] = hass
    app._on_startup.freeze()          # workaround: no changes during startup
    await app.startup()

    # register views (routes) on the app ...

    async def _start(event):
        await start_emulated_hue_bridge(hass, config, app)

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _start)
    return True
```

The `web.Application` is created and its routes are registered during
`async_setup`, but the socket is not opened until HA fires
`EVENT_HOMEASSISTANT_STARTED`.

**Start** (same file, `start_emulated_hue_bridge`):

```python
async def start_emulated_hue_bridge(hass, config, app):
    protocol = await async_create_upnp_datagram_endpoint(...)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, config.host_ip_addr, config.listen_port)
    try:
        await site.start()
    except OSError as error:
        _LOGGER.error("Failed to create HTTP server at port %d: %s",
                       config.listen_port, error)
        protocol.close()
        return

    async def stop_emulated_hue_bridge(event):
        protocol.close()
        await site.stop()
        await runner.cleanup()

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stop_emulated_hue_bridge)
```

The teardown callback is registered on `EVENT_HOMEASSISTANT_STOP`.
Three resources are released in order: the UDP protocol, the TCPSite, and the
AppRunner.

Key takeaway: the three-object lifecycle is **runner → site → (on stop) site.stop
→ runner.cleanup**. If `site.start()` throws `OSError` (port in use), the function
returns early and logs an error rather than crashing setup.

Source: `homeassistant/components/emulated_hue/__init__.py`,
`homeassistant/components/emulated_hue/upnp.py`.

### How homekit does it (config-entry variant)

`homekit` uses a config entry, so the lifecycle is richer.

**async_setup_entry** (`homeassistant/components/homekit/__init__.py`):

```python
async def async_setup_entry(hass, entry):
    conf = entry.data
    options = entry.options
    port = conf[CONF_PORT]
    ip_address = conf.get(CONF_IP_ADDRESS, _DEFAULT_BIND)
    advertise_ips = conf.get(CONF_ADVERTISE_IP) or \
                    await network.async_get_announce_addresses(hass)

    homekit = HomeKit(hass, name, port, ip_address, ...)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, homekit.async_stop)
    )

    entry.runtime_data = HomeKitEntryData(homekit=homekit, ...)
    entry.async_on_unload(async_at_started(hass, _async_start_homekit))
    return True
```

Critical pattern: `entry.async_on_unload(...)` registers teardown callbacks that
fire automatically when `async_unload_entry` is called — the stop listener, the
update listener, and the start listener are all unloaded in one shot.

**async_unload_entry** (same file):

```python
async def async_unload_entry(hass, entry):
    homekit = entry.runtime_data.homekit
    if homekit.status == STATUS_RUNNING:
        await homekit.async_stop()

    for _ in range(SHUTDOWN_TIMEOUT):          # 30 iterations
        if async_port_is_available(entry.data[CONF_PORT]):
            break
        await asyncio.sleep(PORT_CLEANUP_CHECK_INTERVAL_SECS)  # 1 second

    return True
```

After stopping the driver, the unload function **polls until the port is free**
before returning. This prevents a reload from failing because the old socket
has not yet been fully released by the OS. `SHUTDOWN_TIMEOUT = 30` and
`PORT_CLEANUP_CHECK_INTERVAL_SECS = 1` give a 30-second budget.

`async_port_is_available` is a `@callback` (synchronous) that attempts to bind a
test socket to the port; if `bind()` raises `OSError`, the port is still in use.

Source: `homeassistant/components/homekit/__init__.py`,
`homeassistant/components/homekit/const.py`,
`homeassistant/components/homekit/util.py`.

### Pattern for the Integration

Combining both approaches, the Integration should:

1. Create the `web.Application` and register routes in `async_setup_entry`.
2. Create the `web.AppRunner` and `web.TCPSite` only after HA has started
   (listen for `EVENT_HOMEASSISTANT_STARTED` or use `async_at_started`).
3. Wrap `site.start()` in a `try/except OSError` so a port conflict does not crash
   the entry.
4. In `async_unload_entry`: call `site.stop()` then `runner.cleanup()`, then poll
   `async_port_is_available` until the port is free before returning `True`.
5. Use `entry.async_on_unload(...)` to register all teardown callbacks so that
   unload/reload cleans up automatically.

---

## 2. async_get_source_ip

### Signature and semantics

Defined in `homeassistant/components/network/__init__.py`:

```python
async def async_get_source_ip(
    hass: HomeAssistant,
    target_ip: str | UndefinedType = UNDEFINED,
) -> str:
```

- When `target_ip` is `UNDEFINED` (the default), it tries three targets in order:
  `PUBLIC_TARGET_IP`, `MDNS_TARGET_IP`, `LOOPBACK_TARGET_IP`. This finds the
  adapter the OS would use to reach the internet.
- When a specific `target_ip` is given, it finds the adapter that would route to
  that address.
- The underlying mechanism (`homeassistant/components/network/util.py`,
  `async_get_source_ip`) creates a UDP socket, connects to `(target_ip, 1)`, and
  reads `getsockname()[0]` — a standard trick to discover the source IP without
  sending any traffic.
- The result is cross-checked against the `network` integration's list of enabled
  adapter IPv4 addresses. If the OS-reported source IP is not in the enabled list,
  it falls back to the first enabled address.

### How emulated_hue uses it

```python
local_ip = await async_get_source_ip(hass)      # default, no target
config = Config(hass, yaml_config.get(DOMAIN, {}), local_ip)
```

The returned IP becomes the Bind address and (if not overridden) the Advertised
URL. The user can override either via `host_ip` and `advertise_ip` in YAML.

### How homekit / zeroconf uses it

`homekit` calls `network.async_get_announce_addresses(hass)` instead, which
internally calls `async_get_source_ip(hass, target_ip=MDNS_TARGET_IP)` and puts
that address first in the announce list. The result is passed to pyhap as the
`advertised_address` parameter.

### Relevance to the Integration

The Integration should call `async_get_source_ip(hass)` to discover the default IP
for the Bind address and the Advertised URL. If the user overrides either in the
config entry's options, respect that. The `network` dependency must be declared in
`manifest.json`.

Source: `homeassistant/components/network/__init__.py`,
`homeassistant/components/network/util.py`.

---

## 3. Network integration: adapters and subnets

### The Adapter model

Defined in `homeassistant/components/network/models.py`:

```python
class Adapter(TypedDict):
    name: str
    index: int | None
    enabled: bool
    auto: bool
    default: bool
    ipv6: list[IPv6ConfiguredAddress]
    ipv4: list[IPv4ConfiguredAddress]

class IPv4ConfiguredAddress(TypedDict):
    address: str
    network_prefix: int          # e.g. 24 for /24
```

Each adapter carries a list of IPv4 addresses with their `network_prefix`.
A `/24` prefix means a 256-address subnet; a `/16` means 65,536 addresses.
The Integration should use `network_prefix` from the adapter data rather than
assuming `/24`.

### Getting the adapter list

```python
from homeassistant.components.network import async_get_adapters

adapters = await async_get_adapters(hass)
```

This returns every adapter the OS reports (via the `ifaddr` library), filtered to
those the user has enabled in the `network` integration settings. The `enabled` flag
distinguishes user-selected adapters from all detected adapters.

### Computing subnets and broadcast addresses

`homeassistant/components/network/__init__.py` provides
`async_get_ipv4_broadcast_addresses(hass)` which uses `ip_interface` from the
standard library to compute the broadcast address of each enabled adapter's
network:

```python
interface = ip_interface(f"{ip_info['address']}/{ip_info['network_prefix']}")
broadcast = IPv4Address(interface.network.broadcast_address.exploded)
```

For the Integration's subnet sweep (discovering the Thermostat), the same
`ip_interface` construction gives `interface.network`, which yields every host
address via `interface.network.hosts()`. This respects the actual subnet size
instead of hardcoding `/24`.

### Announce addresses

`async_get_announce_addresses(hass)` returns all enabled IPs with the default one
first — suitable for mDNS/SSDP/zeroconf announcements. The Integration can use this
to decide what Advertised URL to push to the Thermostat.

Source: `homeassistant/components/network/__init__.py`,
`homeassistant/components/network/models.py`,
`homeassistant/components/network/util.py`.

---

## 4. DHCP discovery matchers in manifest.json

### The DHCPMatcher type

Defined in `homeassistant/loader.py`:

```python
class DHCPMatcherRequired(TypedDict, total=True):
    domain: str

class DHCPMatcherOptional(TypedDict, total=False):
    macaddress: str
    hostname: str
    registered_devices: bool

class DHCPMatcher(DHCPMatcherRequired, DHCPMatcherOptional):
    ...
```

### manifest.json format

The `dhcp` key is a list of matcher objects. Each matcher can specify:

- `macaddress` — an OUI prefix with wildcard, e.g. `"18B430*"`. The DHCP
  integration indexes matchers by the first 6 hex chars of the MAC (the OUI).
- `hostname` — a Unix filename pattern, e.g. `"nest-*"`. Matched with `fnmatch`.
- `registered_devices` — `true` to match any device already in the device registry
  for this integration's domain.

A matcher fires when **all** of its specified fields match. Multiple matchers in the
list are OR'd — any match triggers discovery.

Example for a Nest thermostat (hypothetical):

```json
{
  "dhcp": [
    {"macaddress": "18B430*"},
    {"hostname": "nest-*"}
  ]
}
```

### When matchers fire

The `dhcp` integration (`homeassistant/components/dhcp/__init__.py`) processes
clients from four sources:

1. **DHCPWatcher** — passively listens for DHCP packets on enabled adapters (via
   `aiodhcpwatcher`). Only sees new leases.
2. **DeviceTrackerWatcher** — watches `device_tracker` state changes for
   `source_type: router` entities.
3. **DeviceTrackerRegisteredWatcher** — listens for the
   `CONNECTED_DEVICE_REGISTERED` dispatcher signal.
4. **NetworkWatcher** — periodically (every 60 minutes) ARP-scans the network via
   `aiodiscover.DiscoverHosts`.

When a client's MAC/hostname matches, the `dhcp` integration calls
`discovery_flow.async_create_flow` with `source=SOURCE_DHCP` and a
`DhcpServiceInfo` containing `ip`, `hostname`, and `macaddress`. This starts the
integration's config flow at `async_step_dhcp`.

### The resulting discovery flow

The integration must implement `async_step_dhcp(self, discovery_info:
DhcpServiceInfo)` in its config flow handler. Typical pattern:

```python
async def async_step_dhcp(self, discovery_info: DhcpServiceInfo):
    self._discovered_ip = discovery_info.ip
    self._discovered_mac = discovery_info.macaddress
    await self.async_set_unique_id(discovery_info.macaddress)
    self._abort_if_unique_id_configured(updates={"host": discovery_info.ip})
    return await self.async_step_confirm()
```

The `_abort_if_unique_id_configured` call handles the case where the device is
already set up — it updates the stored IP without creating a duplicate entry.

### Relevance to the Integration

The Nest thermostat's NLE firmware uses a known MAC prefix. Declaring a DHCP matcher
with that OUI prefix means HA can auto-discover the thermostat when it appears on
the network, offering the user a config flow to set it up.

Source: `homeassistant/components/dhcp/__init__.py`,
`homeassistant/loader.py`,
https://developers.home-assistant.io/docs/creating_integration_manifest (DHCP
section).

---

## 5. External requirements in manifest.json

### The rules

From the developer docs
(https://developers.home-assistant.io/docs/creating_integration_manifest):

- `requirements` is an array of pip-compatible strings.
- HA installs them into its `deps` subdirectory (or the venv's site-packages).
- **Custom integrations should only include requirements that are not required by
  the Core `requirements.txt`.**

### What HA pins centrally

`package_constraints.txt` (read from `dev` branch) pins, among others:

| Package      | Pinned version |
|-------------|---------------|
| aiohttp     | 3.14.3        |
| SQLAlchemy  | 2.0.51        |
| yarl        | 1.24.5        |
| multidict   | >=6.4.2       |
| cryptography| 48.0.1        |
| PyYAML      | 6.0.3         |
| requests    | 2.34.2        |

### What happens on a version conflict

If a custom integration's `requirements` specifies a different version of a package
that HA already ships (e.g. `aiohttp==3.9.0` when HA pins `3.14.3`), pip will
attempt to install the requested version. The result depends on the install
environment:

- In a **venv** (the normal case), pip may downgrade or upgrade the package,
  breaking HA core or other integrations that depend on the pinned version.
  HA does not sandbox per-integration installs.
- In **HA OS / Container**, the same applies but the damage is contained to the
  running instance.

There is no runtime isolation. A conflicting version can cause import errors,
attribute errors, or silent behavioral changes across the entire HA instance.

### Recommended alternatives

1. **Do not declare packages that HA already ships.** If the Integration needs
   aiohttp, it is already available — just import it. Do not pin a version.

2. **Vendor small modules inside the component.** If the Integration needs a
   small library (e.g. a protocol parser), copy its source into
   `custom_components/nest_local/lib/` and import from there. This avoids any
   interaction with HA's dependency resolution. The downside is maintenance burden
   for updates.

3. **Publish a standalone distribution** (e.g. on PyPI) for protocol-level code,
   and declare it in `requirements`. This works well when the library has no
   conflicting transitive dependencies. The library should pin only its own
   direct dependencies and use compatible-release specifiers (`~=`) to avoid
   colliding with HA's pins.

4. **Use `after_dependencies`** (not `dependencies`) for optional integrations
   whose requirements you want installed but whose setup you do not need to block
   on.

### For the Integration specifically

The Integration will use `aiohttp` for its HTTP server. **Do not list aiohttp in
requirements** — it is already present. Any protocol-parsing code (e.g. for the
Nest bucket format) should either be vendored inline or published as a small
standalone package with no aiohttp dependency.

Source: https://developers.home-assistant.io/docs/creating_integration_manifest,
`homeassistant/package_constraints.txt`.

---

## 6. Config flow, options flow, and the Store helper

### Config flow basics

A config entry is created via a config flow handler. The Integration needs one to
let the user specify the Bind address, port, and initial Endpoint for the
Thermostat.

Key lifecycle methods in the integration's `__init__.py`:

- `async_setup_entry(hass, entry)` — called when the entry is loaded. Create the
  server objects here; start listening after HA is started.
- `async_unload_entry(hass, entry)` — called on reload or removal. Stop the server,
  wait for the port to free, return `True`.

The config entry's `data` dict holds immutable settings (e.g. the unique ID /
MAC). The `options` dict holds mutable settings the user can change later.

### Options flow: re-pushing settings when they change

When the user changes the Advertised URL or port in the options flow, the
Integration needs to stop the old server, re-push the new Endpoint to the
Thermostat's Settings API, and start a new server.

Two approaches exist in HA core:

**Approach A — reload the entry** (what homekit does):

```python
# In async_setup_entry:
entry.async_on_unload(entry.add_update_listener(_async_update_listener))

# The listener:
async def _async_update_listener(hass, entry):
    await hass.config_entries.async_reload(entry.entry_id)
```

When options change, the listener triggers a full reload: `async_unload_entry`
runs (stopping the server and waiting for the port), then `async_setup_entry`
runs again with the new options. This is the simplest approach and avoids
partial-reconfiguration bugs.

HA 2024.11+ also provides `OptionsFlowWithReload`, which does the same thing
without needing a manual update listener — the entry is automatically reloaded
when the options flow completes.

**Approach B — hot-reconfigure** (more complex):

The update listener reads `entry.options`, computes what changed, and
reconfigures the running server in place. This avoids downtime but is harder to
get right. Neither `emulated_hue` nor `homekit` does this — both use reload.

**Recommendation for the Integration:** use the reload approach. When the options
flow changes the Advertised URL, the reload sequence is:

1. `async_unload_entry` stops the server, waits for port free.
2. `async_setup_entry` starts with new options, pushes the new Endpoint to the
   Thermostat via its Settings API, and starts the server on the (possibly new)
   Bind address.

### The Store helper

`homeassistant.helpers.storage.Store` provides JSON-file persistence that
integrates with HA's shutdown sequence (guaranteed final write).

```python
from homeassistant.helpers.storage import Store

class MyStore:
    def __init__(self, hass):
        self._store = Store(hass, version=1, key="nest_local")

    async def async_load(self):
        return await self._store.async_load()

    async def async_save(self, data):
        await self._store.async_save(data)
```

Constructor parameters:

| Parameter | Purpose |
|-----------|---------|
| `version` | Major schema version. Increment on breaking changes. |
| `minor_version` | Minor schema version (default 1). |
| `key` | Filename stem — stored as `.storage/{key}` in the HA config dir. |
| `private` | If `True`, the file is not exposed via the supervisor API. |
| `atomic_writes` | Use atomic file writes (rename-over). |

Store handles migration via `_async_migrate_func` (subclass and override).
It also supports `async_delay_save(data_func, delay)` to coalesce rapid writes —
`emulated_hue` uses this with a 60-second delay to batch entity-ID-to-number
mappings.

The Integration could use Store to persist:

- The Thermostat's last-known IP (for re-push on startup).
- Cached device capabilities / bucket state.
- Pairing or session state if the protocol needs it.

This is an alternative to putting everything in the config entry's `data` dict.
The trade-off: config entry data survives backup/restore and is visible in the
UI; Store data is a hidden file.

Source: `homeassistant/helpers/storage.py`,
`homeassistant/components/emulated_hue/config.py` (Store usage example).

---

## 7. Manifest.json examples from core

### emulated_hue

```json
{
  "domain": "emulated_hue",
  "name": "Emulated Hue",
  "after_dependencies": ["http"],
  "dependencies": ["network"],
  "documentation": "https://www.home-assistant.io/integrations/emulated_hue",
  "iot_class": "local_push",
  "quality_scale": "internal"
}
```

No `requirements` (uses only stdlib + aiohttp which HA provides).
Declares `network` as a dependency (needed for `async_get_source_ip`).

### homekit

```json
{
  "domain": "homekit",
  "name": "HomeKit Bridge",
  "after_dependencies": ["camera", "zeroconf"],
  "config_flow": true,
  "dependencies": ["ffmpeg", "http", "network"],
  "documentation": "https://www.home-assistant.io/integrations/homekit",
  "iot_class": "local_push",
  "requirements": ["HAP-python==5.0.0", "fnv-hash-fast==2.0.3", ...],
  "zeroconf": ["_homekit._tcp.local."]
}
```

`requirements` lists only packages HA does not already ship (HAP-python, etc.).
`dependencies` includes `network`.

### Template for the Integration

```json
{
  "domain": "nest_local",
  "name": "Nest Local",
  "config_flow": true,
  "dependencies": ["network"],
  "after_dependencies": ["dhcp"],
  "dhcp": [
    {"macaddress": "18B430*"}
  ],
  "documentation": "https://github.com/jtoniolo/nest-thermostat",
  "iot_class": "local_push",
  "requirements": [],
  "version": "0.1.0"
}
```

Notes:
- `dependencies: ["network"]` ensures `async_get_source_ip` and adapter APIs are
  available.
- `after_dependencies: ["dhcp"]` ensures the DHCP watcher is set up before this
  integration, so the MAC-prefix matcher fires, but does not hard-fail if DHCP is
  not configured.
- `dhcp` declares the OUI matcher. The actual MAC prefix for the Nest thermostat
  needs to be confirmed against real hardware.
- `requirements` is empty — aiohttp is already available and any protocol code
  will be vendored.
- `iot_class: "local_push"` — the Thermostat pushes data to the Integration.

---

## Summary of patterns for the build session

| Concern | Pattern | Source |
|---------|---------|--------|
| Socket lifecycle | `AppRunner` → `TCPSite` → `site.start()` in `EVENT_HOMEASSISTANT_STARTED`; `site.stop()` → `runner.cleanup()` on unload | emulated_hue `__init__.py` |
| Port leak on reload | Poll `async_port_is_available(port)` after stop, before returning from `async_unload_entry` | homekit `__init__.py` |
| Bind address | `async_get_source_ip(hass)` for default; user override in config entry options | network `__init__.py` |
| Advertised URL | `async_get_announce_addresses(hass)` or `async_get_source_ip` + user override | network `__init__.py` |
| Subnet sweep | `ip_interface(f"{addr}/{prefix}")` from adapter data; do not assume /24 | network models + `__init__.py` |
| DHCP discovery | `"dhcp": [{"macaddress": "XXXX*"}]` in manifest; implement `async_step_dhcp` | dhcp `__init__.py`, loader.py |
| External deps | Do not list aiohttp; vendor or publish protocol code separately | developer docs, `package_constraints.txt` |
| Options change | Reload the entry (`OptionsFlowWithReload` or `add_update_listener` + `async_reload`) | homekit `__init__.py` |
| Persistent state | `Store(hass, version=1, key="nest_local")` | `helpers/storage.py` |
| Teardown safety | `entry.async_on_unload(...)` for all listeners and callbacks | homekit `__init__.py` |
