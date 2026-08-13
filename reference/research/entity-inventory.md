# Entity Inventory and Home Assistant's Entity Rules

Research input for [the entity model](https://github.com/jtoniolo/nest-thermostat/issues/9).
This document gathers facts. It decides nothing. Where more than one platform is
defensible, the field is listed in [section 9](#9-ambiguous-fields--decisions-for-a-human)
and left open.

Vocabulary follows `CONTEXT.md`: Thermostat, Firmware, Integration, NLE server, Endpoint,
Route, Bind address, Advertised URL, Settings API, Model string, Generation, the flash.
The Model string is opaque data — nothing in this inventory keys off it, and nothing
branches on Generation.

## Sources and how they are cited

| Source | Authority | Citation form |
|--------|-----------|---------------|
| Home Assistant core, **version 2026.5.4** (`homeassistant/const.py:18-20`), installed at `<venv>/lib/python3.14/site-packages/homeassistant/` | Authoritative for everything HA-shaped | `homeassistant/<path>:LINE` |
| Home Assistant developer documentation | Authoritative for documented convention | full URL |
| NLE server, `codykociemba/NoLongerEvil-SelfHosted`, in-tree at `reference/NoLongerEvil-SelfHosted/` (MIT) | **Protocol reference only.** Read, never copied. | `src/nolongerevil/<path>:LINE` |
| Protocol reference, `cjserio/nest-thermostat-protocol-docs` rev 2.9 (MIT) | Primary for the wire protocol | `NEST_CLOUD_PROTOCOL_REFERENCE.md:LINE` |
| Distilled transport contract | Derived, on branch `research/protocol-reference` | `protocol-transport-contract.md §N` |
| Bucket-types findings | Derived, on branch `research/bucket-types` | `bucket-types.md §N` |

Every line number in this document was read first-hand at the cited path.

---

## 1. Executive summary

- NLE's discovery module declares **19** entities: **1 climate, 10 sensor, 7 binary_sensor,
  1 number**. Sixteen are unconditional; three are gated on `has_fan`. Ticket #6 fixed this
  set as the capability floor.
- The **"~45 settings" figure in the map is wrong.** Four different numbers are in play and
  only one of them is 45 — and that one is a docstring the source itself contradicts.
  See [section 2](#2-the-field-counts).
- Meeting #6's bar ("all settings changeable, all telemetry surfaced") produces **127
  entities**, not 19. The breakdown is in [section 8](#8-the-proposed-entity-set).
- The **availability decision from #6 collides with the state model from #8**, and HA has a
  documented pattern that resolves it. See [section 7](#7-availability-in-local-push-integrations).
- The mode-dependent temperature surface NLE achieves by republishing MQTT discovery has a
  **native equivalent that is a free choice, not a constraint**. See
  [section 6.2](#62-the-two-temperature-feature-flags).
- **Nine names in NLE's settings whitelist do not exist in the protocol reference.** See
  [section 10](#10-discrepancies-between-sources).

---

## 2. The field counts

Four figures are in circulation and they are not the same thing. The map currently blurs
them.

| Figure | Value | Source |
|--------|-------|--------|
| Total registered fields in the `device` bucket | **239** | `NEST_CLOUD_PROTOCOL_REFERENCE.md:1223` |
| — of them device-only (server cannot write) | **113** | `NEST_CLOUD_PROTOCOL_REFERENCE.md:1235` |
| — of them special (custom processing, not in standard PUT) | **23** | `NEST_CLOUD_PROTOCOL_REFERENCE.md:1236` |
| — of them cloud-writable | **103** | `NEST_CLOUD_PROTOCOL_REFERENCE.md:1237` |
| Fields NLE's server actually whitelists for writing | **34** | `src/nolongerevil/routes/control/command.py:375-421` |
| The "~45" in the map | **45** | `src/nolongerevil/routes/control/command.py:19` (a docstring) |

**Where "~45" came from.** The NLE module docstring says *"Generic setter for ~45
whitelisted device fields"* at `src/nolongerevil/routes/control/command.py:19`. The set it
describes, `DEVICE_SETTING_WHITELIST` at `src/nolongerevil/routes/control/command.py:375`,
closes at line 422 and contains **34** quoted names, counted mechanically. The docstring is
stale. The map inherited the docstring's number, not the code's.

> A parallel session reported this count as 32. I counted 34 first-hand, twice, once by eye
> and once by parsing the block between `command.py:375` and its closing brace. The full
> list is in [section 4.3](#43-nles-34-whitelisted-settings-verbatim) so the count can be
> checked without re-reading the source. This is a discrepancy, recorded as one.

**None of these four numbers is "the settings a person would want in HA."** They measure
different things:

- **239** is the wire surface. It includes hardware registers, out-of-box wizard flags and
  fields the Firmware never populates.
- **103 cloud-writable** is the theoretical write surface. Of those, the reference itself
  buckets **24** as *"HVAC source/delivery (wiring configuration)"*
  (`NEST_CLOUD_PROTOCOL_REFERENCE.md:1387-1389`), **8** as *"Setup wizard state
  (out-of-box)"* (`:1391-1393`) and **2** as *"Installation flow"* (`:1395-1397`). Those 34
  are commissioning state, set once at install by the installer, and are not settings a
  user changes. That leaves roughly **69** cloud-writable fields with any user-facing
  meaning.
- **34** is what one peer implementation chose to expose. It is evidence of what is safe to
  write, not a ceiling — #6 explicitly made NLE's choices a floor.
- **The reference individually names about 140 of the 239 fields.** The remaining ~99 exist
  only inside the category counts at `NEST_CLOUD_PROTOCOL_REFERENCE.md:1229-1237`. **A
  complete entity set therefore cannot be derived from the reference alone.** Whatever #9
  decides, the last ~99 fields will be discovered from live PUT traffic, which the map's
  debug-logging commitment already covers.

**Recommendation for what "all settings changeable" should mean.** The cloud-writable set
minus commissioning state — about **69 fields** — is the only figure that matches #6's
sentence. It is a superset of NLE's 34, so the floor is preserved. This is a
recommendation; #9 decides.

---

## 3. NLE's 19 entities — the capability floor

Read from `src/nolongerevil/integrations/mqtt/home_assistant_discovery.py` and the state
publisher `src/nolongerevil/integrations/mqtt/mqtt_integration.py`.

The definitive list is the removal-topic list at
`home_assistant_discovery.py:663-683`, which enumerates exactly 19 topics. The assembly
function `get_all_discovery_configs` at `home_assistant_discovery.py:520-647` emits 16
unconditionally and 3 more when `has_fan` is true (`:571`, `:636`, `:642`).

**Composition: 1 climate + 10 sensor + 7 binary_sensor + 1 number = 19.**

> A parallel session reported this as 1 climate + 9 sensor + 7 binary_sensor + 1 number,
> which sums to 18. That is **refuted**: there are ten sensors — temperature, humidity,
> outdoor temperature, battery, rssi, filter runtime, time to target, compressor lockout,
> local IP and fan timer remaining — at `home_assistant_discovery.py:665, 666, 667, 668,
> 672, 674, 675, 677, 680, 681`.

### 3.1 The climate entity

Declared at `home_assistant_discovery.py:19-132`.

| Aspect | Value | Backing field | Citation |
|--------|-------|---------------|----------|
| `unique_id` | `nolongerevil_{serial}` | — | `:65` |
| Device grouping | `identifiers: ["nolongerevil_{serial}"]`, `model: "Nest Thermostat"`, `manufacturer: "Google Nest"`, `sw_version: "NoLongerEvil"` | — | `:71-77` |
| Availability | topic `{prefix}/{serial}/availability`, payloads `online` / `offline` | — | `:79-83` |
| Temperature unit | `"C"`, always | — | `:86` (and the docstring at `:28-29`) |
| Precision / step | `0.5` / `0.5` | — | `:88-89` |
| Min / max temp | `9` / `32` | hardcoded, not device-derived | `:114-115` |
| Current temperature | — | `shared.current_temperature`, falling back to `device.current_temperature` | `mqtt_integration.py:522-524` |
| Current humidity | — | `device.current_humidity` | `mqtt_integration.py:533-536` |
| HVAC modes | built from capability flags; `off` always present, then `heat` if `can_heat`, `cool` if `can_cool`, `heat_cool` if both | `shared.can_heat`, `shared.can_cool`, falling back to the same names in `device` | `:52-61` |
| HVAC mode state | — | `shared.target_temperature_type` | `:48`, `mqtt_integration.py:515` |
| HVAC action | derived | see [3.4](#34-the-hvac-action-derivation) | `helpers.py:138-188` |
| Fan modes | `["auto", "on"]`, only when `has_fan` | `device.fan_timer_timeout`, `device.fan_control_state` | `:103-106`, `helpers.py:191-210` |
| Preset modes | `["home", "away", "eco"]` | `structure.manual_eco_all` first, then `device.eco.mode` | `:110-112`, `helpers.py:213-243` |
| Target temperature | mode-dependent — see [3.2](#32-the-mode-dependent-temperature-surface) | `shared.target_temperature`, `shared.target_temperature_low`, `shared.target_temperature_high` | `:124-130`, `consts.py:23-31` |

`HaMode`, `HaFanMode` and `HaPreset` are defined at `src/nolongerevil/lib/consts.py:8-44`.

### 3.2 The mode-dependent temperature surface

**Confirmed.** `MODE_TEMPERATURE_TOPICS` at
`src/nolongerevil/integrations/mqtt/consts.py:23-31` maps:

| HA mode | Temperature topics advertised |
|---------|-------------------------------|
| `off` | none |
| `heat` | single, from `shared.target_temperature` |
| `cool` | single, from `shared.target_temperature` |
| `heat_cool` | two, from `shared.target_temperature_low` and `shared.target_temperature_high` |

**Discovery is republished on every state change.** `_publish_ha_state` calls
`_publish_discovery` unconditionally before publishing any state, at
`mqtt_integration.py:518-520`, with the in-source comment that this is *"critical for
heat_cool mode to show dual temperature sliders"*. `_publish_ha_state` is itself called from
`on_device_state_change` at `mqtt_integration.py:456`, from the command handler at
`mqtt_integration.py:354`, and from `_publish_initial_state` at `mqtt_integration.py:867`.
Stale topics for the other modes are actively blanked at `mqtt_integration.py:545-547`.

This is an MQTT-transport workaround. The native equivalent is a genuine choice, not a
constraint — see [section 6.2](#62-the-two-temperature-feature-flags).

### 3.3 The 18 non-climate entities

`Cat.` is the declared `entity_category`; blank means none (a primary entity).

| # | Platform | Name | Bucket + field | Device class | Unit | State class | Cat. | Decl. | Derivation |
|---|----------|------|----------------|--------------|------|-------------|------|-------|------------|
| 1 | sensor | Temperature | `shared.current_temperature` | `temperature` | `°C` | `measurement` | | `:135-152` | direct; `mqtt_integration.py:522` |
| 2 | sensor | Humidity | `device.current_humidity` | `humidity` | `%` | `measurement` | | `:155-172` | direct; `mqtt_integration.py:534` |
| 3 | sensor | Outdoor Temperature | `device.outdoor_temperature`, then `shared.outside_temperature`, then `device.outside_temperature` | `temperature` | `°C` | `measurement` | | `:175-192` | three-way fallback; `mqtt_integration.py:594-598`. **Provenance pending — see [11.1](#111-outdoor-temperature-provenance--ticket-11--20)** |
| 4 | binary_sensor | Occupancy | `device.auto_away`, then `device.away` | `occupancy` | — | — | | `:195-212` | `helpers.py:287-300`; payload `home`/`away`, `:203-204` |
| 5 | binary_sensor | Fan | `shared.hvac_fan_state` | `running` | — | — | | `:215-232` | `helpers.py:303-312`. Gated on `has_fan` (`:571`) |
| 6 | binary_sensor | Eco Mode | `device.eco.leaf`, then `device.leaf` | `power` | — | — | | `:235-252` | `helpers.py:315-328`. Device class `power` for a leaf icon is a poor fit |
| 7 | sensor | Battery | `device.battery_level` | `battery` | `%` | `measurement` | | `:255-272` | voltage→percent, `helpers.py:261-284` |
| 8 | sensor | WiFi Signal | `device.rssi` | `signal_strength` | `dBm` | `measurement` | diagnostic | `:275-293` | `-abs(rssi)`; `mqtt_integration.py:644-650` |
| 9 | binary_sensor | Filter Replacement Needed | `device.filter_replacement_needed` | `problem` | — | — | diagnostic | `:296-317` | direct; `mqtt_integration.py:655-661` |
| 10 | sensor | Filter Runtime | `device.filter_runtime_sec` | *(none; icon `mdi:air-filter`)* | `d` | `total_increasing` | diagnostic | `:320-341` | `round(sec / 86400, 1)`; `mqtt_integration.py:664-671` |
| 11 | sensor | Time to Target | `device.time_to_target` | *(none; icon `mdi:clock-outline`)* | `min` | `measurement` | | `:344-364` | treated as **absolute epoch**: `(ts - now) // 60`; `mqtt_integration.py:678-688`. **Contradicts the reference — see [10.2](#102-time_to_target-is-seconds-or-an-epoch-not-both)** |
| 12 | binary_sensor | Sunlight Correction Active | `device.sunlight_correction_active` | *(none; icon `mdi:weather-sunny`)* | — | — | diagnostic | `:367-388` | direct; `mqtt_integration.py:696-701` |
| 13 | sensor | Compressor Lockout | `device.compressor_lockout_timeout` | *(none; icon `mdi:timer-lock`)* | `s` | `measurement` | diagnostic | `:391-409` | direct; `mqtt_integration.py:705-711` |
| 14 | binary_sensor | Learning Mode | `device.learning_mode` | *(none; icon `mdi:school`)* | — | — | diagnostic | `:412-430` | direct; `mqtt_integration.py:714-719`. **This field is cloud-writable — see [9.1](#91-writable-fields-nle-exposes-read-only)** |
| 15 | binary_sensor | Heat Pump Ready | `device.heatpump_ready` | *(none; icon `mdi:heat-pump`)* | — | — | diagnostic | `:433-454` | direct; `mqtt_integration.py:723-728`. Field name absent from the reference |
| 16 | sensor | Local IP | `device.local_ip` | *(none; icon `mdi:ip-network`)* | — | — | diagnostic | `:457-473` | direct; `mqtt_integration.py:732-737` |
| 17 | sensor | Fan Timer Remaining | `device.fan_timer_timeout` | *(none; icon `mdi:fan-clock`)* | `min` | `measurement` | | `:476-493` | absolute epoch → `(timeout - now) // 60`, else `0`; `mqtt_integration.py:741-762`. Gated on `has_fan` (`:636`) |
| 18 | number | Fan Duration | `device.fan_timer_duration_minutes` | *(none; icon `mdi:fan-clock`)* | `min` | — | | `:496-517` | min 15, max 1440, step 15, mode `slider` (`:507-510`); command clamps to the same range and defaults to 60 (`mqtt_integration.py:318-322`, `:766`). Gated on `has_fan` (`:642`). **Field name absent from the reference** |

Every one of the 18 carries the same availability block, `{prefix}/{serial}/availability`
with `online`/`offline`.

### 3.4 The HVAC action derivation

`src/nolongerevil/integrations/mqtt/helpers.py:138-188`, in strict order:

1. If `shared.target_temperature_type == "off"` → `off` (`:154-155`).
2. Else if any of `hvac_heater_state`, `hvac_heat_x2_state`, `hvac_heat_x3_state`,
   `hvac_aux_heater_state`, `hvac_alt_heat_state` (all `shared`) → `heating` (`:158-167`).
3. Else if any of `hvac_ac_state`, `hvac_cool_x2_state`, `hvac_cool_x3_state` (all `shared`)
   → `cooling` (`:170-177`).
4. Else if `device.fan_timer_timeout > now` or `device.fan_control_state` → `fan`
   (`:180-186`).
5. Else → `idle` (`:188`).

Note it consults five heat flags but the reference names **seven** heat-side flags —
`hvac_alt_heat_x2_state` and `hvac_emer_heat_state` are both omitted from NLE's check
(`NEST_CLOUD_PROTOCOL_REFERENCE.md:1424-1428`). A Thermostat running emergency heat with no
other flag set would report `idle`. Recorded as a defect in the reference implementation,
not as a pattern to copy.

### 3.5 The mode mapping

`src/nolongerevil/lib/consts.py:106-120`.

| Nest `target_temperature_type` | HA `HVACMode` | Citation |
|---|---|---|
| `off` | `off` | `consts.py:107` |
| `heat` | `heat` | `consts.py:108` |
| `cool` | `cool` | `consts.py:109` |
| `range` | `heat_cool` | `consts.py:110` |
| `emergency` | `heat` — *"Emergency heat is a heating mode"* | `consts.py:111` |

The reverse map (`consts.py:115-120`) has no entry for `emergency`, so **the round trip is
lossy**: a Thermostat in emergency heat presents as `heat`, and setting `heat` from HA
writes `heat`, silently dropping emergency. The string `"heat-cool"` is accepted as an alias
for `range` on input (`helpers.py:105-106`). Whether the Integration keeps or loses the
emergency distinction is a decision for #9 — listed in
[section 9](#9-ambiguous-fields--decisions-for-a-human).

### 3.6 The preset mapping, and why it reads `structure` first

`src/nolongerevil/integrations/mqtt/helpers.py:213-243`:

1. `structure.manual_eco_all` truthy → `away` (`:233-234`).
2. Else `device.eco.mode == "manual-eco"` → `eco` (`:239-241`).
3. Else → `home` (`:243`).

The in-source justification at `helpers.py:219-222` is behavioural, not stylistic: *"We use
`manual_eco_all` instead of `away` because the firmware's schedule preconditioning reverts
auto-eco (from `away=true`) but respects manual-eco."* The protocol reference corroborates
this directly in its comparison table at `NEST_CLOUD_PROTOCOL_REFERENCE.md:2245-2249`, where
`manual_eco_all` is immediate and blocks preconditioning while `away` is delayed and *"can
end eco early"*.

Ticket #8 settled that the Integration must create the `structure` bucket itself, so the
authoritative source for the eco preset is a bucket we own outright.

**A defect in the command path**: `preset: away` and `preset: eco` both dispatch
`set_away(True)` (`mqtt_integration.py:293-317`). The two presets are indistinguishable on
write even though they are distinguishable on read.

### 3.7 Unit conversions the entity layer must perform

| Value | Raw form | Conversion | Citation |
|---|---|---|---|
| Battery | volts, float | linear 3.5 V → 0 %, 4.0 V → 100 %, clamped both ends | `helpers.py:261-284` |
| Filter runtime | seconds | `round(sec / 86400, 1)` → days | `mqtt_integration.py:667` |
| Time to target | **absolute Unix epoch** | `(ts - now) // 60`, floored at 0, skipped entirely when `0` | `mqtt_integration.py:678-690` |
| Fan timer remaining | **absolute Unix epoch** | `(timeout - now) // 60`, else `0` | `mqtt_integration.py:741-762` |
| RSSI | positive magnitude | `-abs(value)` → dBm | `mqtt_integration.py:646` |

**The last two are absolute timestamps, and computing a countdown from them at publish time
is a bug waiting to happen** — the value goes stale the moment it is written and only
refreshes on the next PUT, which for a sleeping Thermostat can be five minutes away.

HA's own answer is `SensorDeviceClass.TIMESTAMP`
(`homeassistant/components/sensor/const.py:112`), which takes an absolute datetime and lets
the frontend render the countdown live. Note that `TIMESTAMP` permits **no** state class —
its entry in the allowed-state-class map is the empty set at
`homeassistant/components/sensor/const.py:833`. The alternative,
`SensorDeviceClass.DURATION` (`:221`), does permit every state class (`:793`) but stores a
fixed number that decays.

Recorded as an ambiguity: see [section 9](#9-ambiguous-fields--decisions-for-a-human).

---

## 4. The writable settings surface

### 4.1 The eight command types

`src/nolongerevil/routes/control/command.py:11-24` documents the dispatcher and its bucket
routing.

| Command | Target bucket | Fields written | Citation |
|---|---|---|---|
| `set_temperature` | `shared` | `target_temperature`, or `target_temperature_low`/`_high` | `command.py:12`, `:96` |
| `set_mode` | `shared` | `target_temperature_type`; `off`/`heat`/`cool`/`heat-cool`/`emergency`; `"eco"` explicitly rejected | `command.py:13-14` |
| `set_away` | `structure` | `manual_eco_all`, `manual_eco_timestamp` | `command.py:15`, `:23` |
| `set_fan` | `device` | fan timer | `command.py:16` |
| `set_eco_temperatures` | `device` | eco high/low bounds | `command.py:17`, `:252` |
| `set_schedule` | `schedule` | full weekly replacement, ver 2 — **replacement, not merge** | `command.py:18`, `:24` |
| `set_schedule_mode` | `shared` | `schedule_mode` | `command.py:19`, `:370` |
| `set_device_setting` | `device` | any of the 34 whitelisted names | `command.py:20`, `:424-` |

Temperature commands clamp via `validate_and_clamp_temperatures`
(`command.py:27`, `:96`, `:252`); mode commands check `can_heat`, `can_cool` and
`has_emer_heat` (`command.py:28`).

### 4.2 NLE's temperature bounds

| Bound | Value | Citation |
|---|---|---|
| `min_heat` | 4.5 °C | `src/nolongerevil/lib/types.py:164` |
| `max_heat` | 32.0 °C | `src/nolongerevil/lib/types.py:165` |
| `min_cool` | 9.0 °C | `src/nolongerevil/lib/types.py:166` |
| `max_cool` | 32.0 °C | `src/nolongerevil/lib/types.py:167` |
| absolute `min_celsius` | 7.222 °C (45 °F) | `src/nolongerevil/lib/types.py:169`, `src/nolongerevil/utils/temperature_safety.py:11` |
| absolute `max_celsius` | 35.0 °C (95 °F) | `src/nolongerevil/lib/types.py:170`, `src/nolongerevil/utils/temperature_safety.py:12` |
| module constants | `TEMP_MIN_C = 4.5`, `TEMP_MAX_C = 32.0` | `src/nolongerevil/routes/control/command.py:256-257` |
| MQTT climate advertisement | min 9, max 32 | `home_assistant_discovery.py:114-115` |

For comparison, HA's platform defaults are `DEFAULT_MIN_TEMP = 7` and
`DEFAULT_MAX_TEMP = 35` (`homeassistant/components/climate/const.py:122-123`).

**Where our bounds should come from.** Ticket #6 decided safety temperatures are the
Thermostat's own, surfaced and not re-clamped. The Thermostat reports `lower_safety_temp`
and `upper_safety_temp` in the `device` bucket
(`NEST_CLOUD_PROTOCOL_REFERENCE.md:1980-1983`), and both `min_temp` and `max_temp` may vary
at runtime on a native entity (see [6.4](#64-what-may-vary-at-runtime)). So `min_temp` and
`max_temp` should track the reported safety limits, with HA's 7/35 as the fallback only
before the first PUT arrives. NLE's 9/32 is a hardcoded guess and should not be copied.

### 4.3 NLE's 34 whitelisted settings, verbatim

`src/nolongerevil/routes/control/command.py:375-421`, in source order, grouped by the
comments the source itself provides.

| Group | Fields | Count |
|---|---|---|
| Safety (`:377`) | `lower_safety_temp_enabled`, `upper_safety_temp_enabled`, `lower_safety_temp`, `upper_safety_temp` | 4 |
| Temperature lock (`:382`) | `temp_lock_on`, `temp_lock_pin_hash`, `temp_lock_high_temp`, `temp_lock_low_temp` | 4 |
| Learning and preconditioning (`:387`) | `learning_mode`, `preconditioning_enabled`, `preconditioning_active` | 3 |
| Humidity (`:391`) | `target_humidity_enabled`, `target_humidity` | 2 |
| Display (`:394`) | `temperature_scale`, `time_to_target`, `time_to_target_training_status` | 3 |
| Sunblock (`:398`) | `sunlight_correction_enabled` | 1 |
| Fan (`:400`) | `fan_timer_duration_minutes`, `fan_duty_cycle`, `fan_duty_start_time`, `fan_duty_end_time`, `fan_schedule_speed` | 5 |
| Heat pump (`:406`) | `heat_pump_aux_threshold_enabled`, `heat_pump_aux_threshold`, `heat_pump_comp_threshold_enabled`, `heat_pump_comp_threshold` | 4 |
| Wiring / equipment (`:411`) | `equipment_type`, `heat_source` | 2 |
| Hot water, EU models (`:414`) | `hot_water_boost_time_to_end`, `hot_water_active` | 2 |
| Filter (`:417`) | `filter_reminder_enabled`, `filter_reminder_level` | 2 |
| Locale (`:420`) | `postal_code`, `country_code` | 2 |
| **Total** | | **34** |

Nine of these names do not appear anywhere in the protocol reference — see
[section 10.1](#101-nine-whitelisted-names-are-not-in-the-protocol-reference).

---

## 5. Field-by-field inventory

Access mode uses the reference's own three-way split
(`NEST_CLOUD_PROTOCOL_REFERENCE.md:1229-1237`): **device-only** (server cannot write),
**special** (custom processing, absent from standard PUT), **cloud-writable**.
`Cat.` is the proposed entity category — `cfg` = config, `diag` = diagnostic, blank = a
primary entity. A `†` marks a field also listed in
[section 9](#9-ambiguous-fields--decisions-for-a-human).

### 5.1 `shared` bucket — the primary control surface

All fields from `NEST_CLOUD_PROTOCOL_REFERENCE.md:1411-1433`.

| Field | Access | Type | Proposed platform | Device class | Unit | Cat. |
|---|---|---|---|---|---|---|
| `target_temperature` | cloud-writable | float | climate (target temp) | — | °C | |
| `target_temperature_high` | cloud-writable | float | climate (range high) | — | °C | |
| `target_temperature_low` | cloud-writable | float | climate (range low) | — | °C | |
| `target_temperature_type` | cloud-writable | enum `heat`/`cool`/`range`/`emergency`/`off` | climate (`hvac_mode`) † | — | — | |
| `current_temperature` | device-only | float | climate (`current_temperature`) + sensor | `temperature` | °C | |
| `target_change_pending` | cloud-writable | bool | **no entity** — protocol display-wake flag (`:1460-1518`) | — | — | |
| `touched_by` | cloud-writable | object | **no entity** — protocol metadata the server sets (`:1520-1547`) | — | — | |
| `schedule_mode` | cloud-writable | enum `HEAT`/`COOL`/`RANGE` | `select` † | — | — | cfg |
| `can_heat` | device-only | bool | **no entity** — shapes `hvac_modes` † | — | — | |
| `can_cool` | device-only | bool | **no entity** — shapes `hvac_modes` † | — | — | |
| `hvac_heater_state` | device-only | bool | climate (`hvac_action`) + `binary_sensor` † | `running` | — | diag |
| `hvac_heat_x2_state` | device-only | bool | `binary_sensor` † | `running` | — | diag |
| `hvac_heat_x3_state` | device-only | bool | `binary_sensor` † | `running` | — | diag |
| `hvac_aux_heater_state` | device-only | bool | `binary_sensor` | `running` | — | diag |
| `hvac_alt_heat_state` | device-only | bool | `binary_sensor` | `running` | — | diag |
| `hvac_alt_heat_x2_state` | device-only | bool | `binary_sensor` | `running` | — | diag |
| `hvac_emer_heat_state` | device-only | bool | `binary_sensor` | `running` | — | diag |
| `hvac_ac_state` | device-only | bool | climate (`hvac_action`) + `binary_sensor` † | `running` | — | diag |
| `hvac_cool_x2_state` | device-only | bool | `binary_sensor` † | `running` | — | diag |
| `hvac_cool_x3_state` | device-only | bool | `binary_sensor` † | `running` | — | diag |
| `hvac_fan_state` | device-only | bool | `binary_sensor` (NLE #5) | `running` | — | |
| `name` | cloud-writable | string | **no entity** — feeds `DeviceInfo.name` † | — | — | |
| `auto_away` | device-only | int, `0`=home `1`=away | `binary_sensor` (NLE #4) † | `occupancy` | — | |

`auto_away` is documented as living in `shared`, not `device`
(`NEST_CLOUD_PROTOCOL_REFERENCE.md:1247-1249, 1258`) — NLE reads it from `device`
(`helpers.py:296`). See [10.3](#103-bucket-placement-disagreements).

The `bucket-types` findings record the matching trap: the `occupancy` bucket is **not**
where occupancy comes from; `auto_away` is (`bucket-types.md` §5, §Cross-Cutting).

### 5.2 `structure` bucket

All fields from `NEST_CLOUD_PROTOCOL_REFERENCE.md:1560-1573`. Server → device only
(`:1554`); ticket #8 settled that the Integration creates this bucket.

| Field | Access | Type | Proposed platform | Device class | Unit | Cat. |
|---|---|---|---|---|---|---|
| `manual_eco_all` | cloud-writable | bool | climate `preset_mode` (`eco`/`away`) † | — | — | |
| `manual_eco_timestamp` | cloud-writable | int, **Unix seconds** | **no entity** — written alongside `manual_eco_all`, 600 s validation window (`:1563`) | — | — | |
| `away` | cloud-writable | bool | `switch` †, distinct from `manual_eco_all` (`:2245-2249`) | — | — | cfg |
| `name` | cloud-writable | string | **no entity** | — | — | |
| `devices` | cloud-writable | array | **no entity** — protocol bookkeeping | — | — | |
| `house_type` | cloud-writable | string | `select` (values undocumented †) | — | — | cfg |
| `renovation_date` | cloud-writable | string, year | `text` or `number` † | — | — | cfg |
| `num_thermostats` | cloud-writable | string | **no entity** | — | — | |
| `country_code` | cloud-writable | string, ISO | `text` † | — | — | cfg |
| `postal_code` | cloud-writable | string | `text` † | — | — | cfg |
| `location` | cloud-writable | object | **no entity** — HA owns location | — | — | |
| `time_zone` | cloud-writable | object | **no entity** — HA owns the timezone | — | — | |
| `dr_reminder_enabled` | cloud-writable | bool | **no entity** — demand-response, inert without utility enrolment (`bucket-types.md` §6, §The Utility Program Dependency) | — | — | |

### 5.3 `device` bucket — read-only telemetry

Named fields only. From `NEST_CLOUD_PROTOCOL_REFERENCE.md:1243-1263`, `:1905-1910`,
`:1916-1924`, `:1944-1957`, and the feature tables at `:1963-2133`.

| Field | Access | Type | Proposed platform | Device class | Unit | Cat. |
|---|---|---|---|---|---|---|
| `current_humidity` | device-only | int | climate (`current_humidity`) + sensor (NLE #2) | `humidity` | `%` | |
| `backplate_temperature` | device-only | float | `sensor` | `temperature` | °C | diag |
| `battery_level` | device-only | float † | `sensor` (NLE #7) | `battery` | `%` | diag |
| `serial_number` | device-only | string | **no entity** — `DeviceInfo.serial_number` | — | — | |
| `current_version` | device-only | string | **no entity** — `DeviceInfo.sw_version` † | — | — | |
| `model_version` | device-only | string | **no entity** — `DeviceInfo.model` / `model_id`. **Opaque; nothing branches on it** | — | — | |
| `local_ip` | device-only | string | `sensor` (NLE #16) † | — | — | diag |
| `mac_address` | device-only | string | **no entity** — `DeviceInfo.connections` | — | — | |
| `error_code` | device-only | string | `sensor` (`enum`) † | `enum` | — | diag |
| `leaf` | device-only | bool | `binary_sensor` (NLE #6) † | — | — | |
| `eco_mode` | device-only | JSON **string** (`:1944-1949`) | `sensor` (`enum`: `schedule` / `manual-eco` / `auto-eco`, `:2259-2263`) † | `enum` | — | diag |
| `eco` | **special** | object: `mode`, `touched_by`, `mode_update_timestamp`, `touched_user_id` (`:2213-2219`) | **no entity** — the write path for eco exit † | — | — | |
| `time_to_target` | device-only † | int | `sensor` (NLE #11) † | — | `min` or timestamp | |
| `time_to_target_training` | device-only | enum `ready`/`training`/`not_ready` (`:1957`) | `sensor` (`enum`) | `enum` | — | diag |
| `has_fan` | device-only | bool | **no entity** — gates the fan surface † | — | — | |
| `has_emer_heat` | device-only | bool | **no entity** — gates emergency mode † | — | — | |
| `has_humidifier` | device-only | bool | **no entity** — gates humidity surface † | — | — | |
| `has_dehumidifier` | device-only | bool | **no entity** † | — | — | |
| `has_hot_water_control` | device-only | bool | **no entity** — gates hot water † | — | — | |
| `safety_state` | device-only | enum `safe`/`below`/`above` (`:1986`) | `sensor` (`enum`) | `enum` | — | diag |
| `safety_temp_activating_hvac` | device-only | bool | `binary_sensor` | `problem` | — | diag |
| `safety_state_time` | device-only | timestamp (`:1989`) | `sensor` | `timestamp` | — | diag |
| `preconditioning_ready` | device-only | bool | `binary_sensor` | — | — | diag |
| `eta_preconditioning_active` | device-only | bool | `binary_sensor` | `running` | — | diag |
| `sunlight_correction_active` | device-only | bool | `binary_sensor` (NLE #12) | — | — | diag |
| `sunlight_correction_ready` | device-only | bool | `binary_sensor` | — | — | diag |
| `fan_cooling_state` | device-only | string (`:1975`) | `sensor` (`enum`) | `enum` | — | diag |
| `hot_water_active` | device-only † | bool | `binary_sensor` | `running` | — | diag |
| `hvac_smoke_safety_shutoff_active` | device-only | bool | `binary_sensor` | `problem` | — | diag |
| `hvac_safety_shutoff_active` | device-only | bool | `binary_sensor` | `problem` | — | diag |
| `filter_replacement_needed` | device-only | bool | `binary_sensor` (NLE #9) | `problem` | — | diag |
| `filter_runtime_sec` | device-only | int, seconds | `sensor` (NLE #10) † | `duration` | `d` or `s` | diag |
| `wiring_error` | device-only (`:1723-1732`) | string | `sensor` (`enum`) | `enum` | — | diag |
| `heat_link_connection` | device-only (`:1723-1732`) | string | `sensor` (`enum`) | `enum` | — | diag |
| `dehumidifier_state` | device-only (`:1723-1732`) | string | `sensor` (`enum`) | `enum` | — | diag |
| `auto_dehum_state` | device-only (`:1723-1732`) | string | `sensor` (`enum`) | `enum` | — | diag |
| `humidifier_state` | device-only (`:1723-1732`) | string | `sensor` (`enum`) | `enum` | — | diag |
| `fan_control_state` | device-only (`:1723-1732`) | bool | **no entity** — feeds `fan_mode` and `hvac_action` | — | — | |
| `away_temperature_low_adjusted` | device-only (`:1723-1732`) | float | `sensor` | `temperature` | °C | diag |
| `away_temperature_high_adjusted` | device-only (`:1723-1732`) | float | `sensor` | `temperature` | °C | diag |
| `tou_icon` | device-only (`:1723-1732`) | — | **no entity** — utility state, inert (`bucket-types.md` §12) | — | — | |
| `demand_charge_icon` | device-only (`:1723-1732`) | — | **no entity** — utility state, inert (`bucket-types.md` §14) | — | — | |
| `rssi` | *not in the reference* | number | `sensor` (NLE #8) | `signal_strength` | `dBm` | diag |
| `heatpump_ready` | *not in the reference* | bool | `binary_sensor` (NLE #15) | — | — | diag |
| `outdoor_temperature` | *not in the reference* | float | `sensor` (NLE #3) — **provenance pending, [11.1](#111-outdoor-temperature-provenance--ticket-11--20)** | `temperature` | °C | |

The twelve fields marked `(:1723-1732)` are the reference's explicitly
consistency-checked write-protected set: pushing a differing value makes the Thermostat mark
the field dirty and re-send its own. They are read-only in the strongest sense.

### 5.4 `device` bucket — cloud-writable settings

From the reference's own category tables at `NEST_CLOUD_PROTOCOL_REFERENCE.md:1274-1397`,
cross-read against the feature reference at `:1963-2133` for units and enum values.

**Eco temperatures and safety** (`:1276-1286`, `:1978-1991`)

| Field | Type | Proposed platform | Device class | Unit / range | Cat. |
|---|---|---|---|---|---|
| `away_temperature_high` | float | `number` | `temperature` | °C | cfg |
| `away_temperature_low` | float | `number` | `temperature` | °C | cfg |
| `away_temperature_high_enabled` | bool | `switch` | — | — | cfg |
| `away_temperature_low_enabled` | bool | `switch` | — | — | cfg |
| `upper_safety_temp` | float | `number` † | `temperature` | °C | cfg |
| `lower_safety_temp` | float | `number` † | `temperature` | °C | cfg |
| `upper_safety_temp_enabled` | bool | `switch` | — | — | cfg |
| `lower_safety_temp_enabled` | bool | `switch` | — | — | cfg |

**Temperature lock** (`:1288-1295`, `:1993-2004`)

| Field | Type | Proposed platform | Device class | Unit / range | Cat. |
|---|---|---|---|---|---|
| `temperature_lock` | bool | `switch` | — | — | cfg |
| `temperature_lock_low_temp` | float | `number` | `temperature` | °C | cfg |
| `temperature_lock_high_temp` | float | `number` | `temperature` | °C | cfg |
| `temperature_lock_pin_hash` | string | **no entity** † — a credential | — | — | cfg |

**Fan** (`:1297-1310`, `:1963-1976`)

| Field | Type | Proposed platform | Device class | Unit / range | Cat. |
|---|---|---|---|---|---|
| `fan_mode` | enum `off`/`auto`/`duty-cycle` (`:1969`) | `select` † | — | — | cfg |
| `fan_timer_duration` | int, **seconds** (`:1970`) | `number` † | `duration` | s | cfg |
| `fan_timer_timeout` | int, Unix epoch; `0` stops (`:1971`) | climate `fan_mode` write path + `sensor` (NLE #17) † | `timestamp` | — | |
| `fan_duty_cycle` | int, minutes per hour (`:1972`) | `number` | — | `min` | cfg |
| `fan_duty_start_time` | int, seconds from midnight | `time` † | — | — | cfg |
| `fan_duty_end_time` | int, seconds from midnight | `time` † | — | — | cfg |
| `fan_cooling_enabled` (Airwave) | bool (`:1973`) | `switch` | — | — | cfg |
| `fan_heat_cool_speed` | string | `select` (values undocumented †) | — | — | cfg |
| `fan_schedule_speed` | string | `select` (values undocumented †) | — | — | cfg |
| `fan_timer_speed` | string | `select` (values undocumented †) | — | — | cfg |

**Eco / away** (`:1312-1318`)

| Field | Type | Proposed platform | Device class | Unit / range | Cat. |
|---|---|---|---|---|---|
| `auto_away_enable` | bool | `switch` | — | — | cfg |
| `home_away_input` | bool | `switch` | — | — | cfg |
| `auto_away_reset` | bool | `button` † — momentary | — | — | cfg |

**Humidity** (`:1320-1334`, `:2032-2043`)

| Field | Type | Proposed platform | Device class | Unit / range | Cat. |
|---|---|---|---|---|---|
| `target_humidity` | float, percent | `number` † | `humidity` | `%` | cfg |
| `target_humidity_enabled` | bool | `switch` | — | — | cfg |
| `auto_dehum_enabled` | bool | `switch` | — | — | cfg |
| `humidifier_type` | string | `select` (values undocumented †) | — | — | cfg |
| `dehumidifier_type` | string | `select` (values undocumented †) | — | — | cfg |
| `humidifier_fan_activation` | bool | `switch` | — | — | cfg |
| `dehumidifier_fan_activation` | bool | `switch` | — | — | cfg |
| `dehumidifier_orientation_selected` | string | `select` (values undocumented †) | — | — | cfg |
| `humidity_control_lockout_enabled` | bool | `switch` | — | — | cfg |
| `humidity_control_lockout_start_time` | int, seconds from midnight | `time` † | — | — | cfg |
| `humidity_control_lockout_end_time` | int, seconds from midnight | `time` † | — | — | cfg |

**Heat pump and dual fuel** (`:1336-1347`, `:2055-2061`)

| Field | Type | Proposed platform | Device class | Unit / range | Cat. |
|---|---|---|---|---|---|
| `dual_fuel_breakpoint` | float | `number` | `temperature` | °C | cfg |
| `dual_fuel_breakpoint_override` | string | `select` (values undocumented †) | — | — | cfg |
| `dual_fuel_selected` | bool | `switch` | — | — | cfg |
| `heat_pump_aux_threshold` | float | `number` | `temperature` | °C | cfg |
| `heat_pump_aux_threshold_enabled` | bool | `switch` | — | — | cfg |
| `heat_pump_comp_threshold` | float | `number` | `temperature` | °C | cfg |
| `heat_pump_comp_threshold_enabled` | bool | `switch` | — | — | cfg |
| `heatpump_savings` | enum `max-savings`/`balanced`/`max-comfort` (`:2059`) | `select` | — | — | cfg |

**Learning, scheduling and preconditioning** (`:1349-1356`, `:2006-2030`)

| Field | Type | Proposed platform | Device class | Unit / range | Cat. |
|---|---|---|---|---|---|
| `learning_mode` | bool | `switch` † (NLE makes it read-only) | — | — | cfg |
| `preconditioning_enabled` | bool | `switch` | — | — | cfg |
| `max_nighttime_preconditioning_seconds` | int, seconds | `number` | `duration` | s | cfg |
| `schedule_learning_reset` | bool | `button` † — momentary | — | — | cfg |

**Compressor lockout** (`:2095-2102`)

| Field | Type | Proposed platform | Device class | Unit / range | Cat. |
|---|---|---|---|---|---|
| `compressor_lockout_enabled` | bool | `switch` | — | — | cfg |
| `compressor_lockout_timeout` | int, seconds | `number` † (NLE makes it a read-only sensor, #13) | `duration` | s | cfg |

**Hot water, UK/EU** (`:1358-1366`, `:2071-2082`) — all gated on `has_hot_water_control`

| Field | Type | Proposed platform | Device class | Unit / range | Cat. |
|---|---|---|---|---|---|
| `hot_water_mode` | enum `schedule`/`off` (`:2077`) | `select` | — | — | cfg |
| `hot_water_temperature` | float | `number` | `temperature` | °C | cfg |
| `hot_water_boost_time_to_end` | int, Unix epoch | `sensor` (`timestamp`) + `button` to boost † | `timestamp` | — | cfg |
| `hot_water_away_enabled` | bool | `switch` | — | — | cfg |
| `heat_link_manual_mode` | bool | `switch` | — | — | cfg |

**Smoke and CO shutoff** (`:2084-2093`)

| Field | Type | Proposed platform | Device class | Unit / range | Cat. |
|---|---|---|---|---|---|
| `smoke_safety_shutoff_enabled` | bool | `switch` | — | — | cfg |
| `safety_shutoff_enabled` | bool | `switch` | — | — | cfg |

**Display, sound and device configuration** (`:1368-1379`, `:2104-2111`)

| Field | Type | Proposed platform | Device class | Unit / range | Cat. |
|---|---|---|---|---|---|
| `temperature_scale` | enum `F`/`C`, display only (`:2110`) | `select` † | — | — | cfg |
| `click_sound` | bool or string † (`:2109` vs `:1371`) | `switch` † | — | — | cfg |
| `farsight_screen` | string | `select` (values undocumented †) | — | — | cfg |
| `should_wake_on_approach` | bool | `switch` | — | — | cfg |
| `sunlight_correction_enabled` | bool | `switch` | — | — | cfg |
| `radiant_control_enabled` | bool | `switch` | — | — | cfg |
| `ob_orientation` | string | `select` (values undocumented †) — wiring | — | — | cfg |
| `ob_persistence` | string | `select` (values undocumented †) — wiring | — | — | cfg |
| `where_id` | string, UUID | `select` † — room assignment; NLE keeps a 28-entry name table at `helpers.py:18-47` | — | — | cfg |
| `pro_id` | string | **no entity** — installer record; the Pro programme is defunct (`bucket-types.md` §1) | — | — | |
| `logging_priority` | string | **no entity** — replaced by HA's own debug-logging toggle (#6 §11) | — | — | |

**Leaf thresholds** (`:2113-2124`)

| Field | Type | Proposed platform | Device class | Unit / range | Cat. |
|---|---|---|---|---|---|
| `leaf_threshold_heat` | float | `number` | `temperature` | °C | cfg |
| `leaf_threshold_cool` | float | `number` | `temperature` | °C | cfg |
| `leaf_schedule_delta` | float | `number` † — the learning algorithm also writes it | `temperature` | °C | cfg |
| `leaf_away_low` | float | `number` | `temperature` | °C | cfg |
| `leaf_away_high` | float | `number` | `temperature` | °C | cfg |

**Filter reminder** (`:1381-1385`, `:2126-2133`)

| Field | Type | Proposed platform | Device class | Unit / range | Cat. |
|---|---|---|---|---|---|
| `filter_reminder_enabled` | bool | `switch` | — | — | cfg |
| `filter_changed_date` | int, Unix epoch | `sensor` (`timestamp`) + `button` "filter changed" † | `timestamp` | — | cfg |
| `filter_changed_set_date` | int | **no entity** — bookkeeping | — | — | |
| `filter_replacement_threshold_sec` | int, seconds | `number` | `duration` | s | cfg |

**Commissioning state — proposed as no entities at all**

- **HVAC source/delivery, 24 fields** (`:1387-1389`): `alt_heat_delivery`,
  `alt_heat_source`, `alt_heat_x2_delivery`, `alt_heat_x2_source`, `aux_heat_delivery`,
  `aux_heat_source`, `cooling_delivery`, `cooling_source`, `cooling_x2_delivery`,
  `cooling_x2_source`, `cooling_x3_delivery`, `cooling_x3_source`, `emer_heat_delivery`,
  `emer_heat_enable`, `emer_heat_source`, `forced_air`, `heater_delivery`, `heater_source`,
  `heat_x2_delivery`, `heat_x2_source`, `heat_x3_delivery`, `heat_x3_source`, `star_type`,
  `y2_type`. Wiring configuration, set at install. Writing these wrong misdrives the HVAC.
- **Setup wizard, 8 fields** (`:1391-1393`): `oob_interview_completed`,
  `oob_temp_completed`, `oob_test_completed`, `oob_startup_completed`,
  `oob_summary_completed`, `oob_where_completed`, `oob_wifi_completed`,
  `oob_wires_completed`.
- **Installation flow, 2 fields** (`:1395-1397`): `ifj_assisting_device_id`, `ifj_result`.

Whether any of the 24 wiring fields deserve a diagnostic read-only surface is listed in
[section 9](#9-ambiguous-fields--decisions-for-a-human).

### 5.5 `schedule` bucket

Schema at `NEST_CLOUD_PROTOCOL_REFERENCE.md:2316-2419`; conventions confirmed in
`protocol-transport-contract.md` §7.7 and §13.

| Aspect | Value | Citation |
|---|---|---|
| Version | always `2` | `:2350-2360` |
| Top-level | `ver`, `name`, `schedule_mode` (`HEAT`/`COOL`/`RANGE`), `days` | `:2350-2360` |
| Day keys | `"0"`–`"6"`, **day 0 = Monday** | `:2361-2377` |
| Setpoint keys | sequential integer strings within each day | `:2379-2392` |
| Setpoint fields | `type`, `time`, `entry_type` (`setpoint`/`continuation`), `temp` (HEAT/COOL), `temp-min`/`temp-max` (RANGE) | `:2379-2392` |
| Time encoding | seconds from midnight, 0–86399 | `:2383-2405` |
| Max setpoints | 96 per day; practical max 10–12 | `:2587-2589` |
| Push rule | always push the **complete** schedule, never individual setpoints | `:2447-2487` |
| Sync guards | 15 s debounce; pending local edits discard pushes silently; older timestamps rejected | `:2569-2585` |
| Learning interaction | with `learning_mode` on, the Thermostat may modify a pushed schedule | `:2591-2597` |

**HA has no native weekly-thermostat-schedule platform.** Ticket #6 decided the schedule is
read *and* written. The surface is a genuine open question — see
[section 9](#9-ambiguous-fields--decisions-for-a-human).

---

## 6. Home Assistant's entity rules, verified in core

All read from HA **2026.5.4** (`homeassistant/const.py:18-20`).

### 6.1 `ClimateEntityFeature`

`homeassistant/components/climate/const.py:140-151`.

| Member | Bit | Line |
|---|---|---|
| `TARGET_TEMPERATURE` | 1 | `:143` |
| `TARGET_TEMPERATURE_RANGE` | 2 | `:144` |
| `TARGET_HUMIDITY` | 4 | `:145` |
| `FAN_MODE` | 8 | `:146` |
| `PRESET_MODE` | 16 | `:147` |
| `SWING_MODE` | 32 | `:148` |
| `TURN_OFF` | 128 | `:149` |
| `TURN_ON` | 256 | `:150` |
| `SWING_HORIZONTAL_MODE` | 512 | `:151` |

`TURN_ON` and `TURN_OFF` are **plain required features with no deprecation shim**. They gate
`turn_on`, `turn_off` and `toggle` at
`homeassistant/components/climate/__init__.py:133-150`. The old
`_enable_turn_on_off_backwards_compatibility` attribute is gone from core except for one
leftover assignment in an unrelated integration
(`homeassistant/components/teslemetry/climate.py:383`); nothing in `climate/__init__.py`
reads it. The Thermostat has a real `off` mode, so both bits apply.

### 6.2 The two temperature feature flags

**Declaring both at once is legal.** Nothing in `climate/__init__.py` or `climate/const.py`
forbids, warns about, or deprecates the combination.

`state_attributes` keys purely off the feature bits, with two independent `if` statements
and no `elif`:

- `homeassistant/components/climate/__init__.py:362-368` emits `temperature` when
  `TARGET_TEMPERATURE` is set.
- `homeassistant/components/climate/__init__.py:370-376` emits `target_temp_high` and
  `target_temp_low` when `TARGET_TEMPERATURE_RANGE` is set.

So with both bits set, all three attributes are emitted and **it is the entity's job to
return `None` from the properties that do not apply to the current mode.**

**Two core precedents, one on each side of the choice:**

- **Static both**: `ecobee` declares `TARGET_TEMPERATURE | PRESET_MODE |
  TARGET_TEMPERATURE_RANGE | FAN_MODE` as a module constant
  (`homeassistant/components/ecobee/climate.py:196-201`).
- **Computed once from the mode set, then fixed**: `nest` builds the bitmap in
  `_get_supported_features` (`homeassistant/components/nest/climate.py:255-269`), adding
  `TARGET_TEMPERATURE_RANGE` if `HEAT_COOL` is among `hvac_modes` and `TARGET_TEMPERATURE`
  if `HEAT` or `COOL` is. It does **not** vary them per current mode. It then returns `None`
  from the inapplicable properties: `target_temperature` returns `None` unless the mode is
  `HEAT` or `COOL` (`nest/climate.py:150-158`), and `target_temperature_high` / `_low`
  return `None` unless the mode is `HEAT_COOL` (`nest/climate.py:161-176`).

**Trade-off.** Static-both matches both precedents and produces zero capability churn.
Per-mode-dynamic gives a cleaner UI in each mode but rewrites the entity registry on every
Thermostat mode change (see [6.4](#64-what-may-vary-at-runtime)). Recommended: static-both
plus `None` returns, following `nest`. **#9 decides.**

**Runtime validation checks the feature bit only, never the current mode.**
`async_service_temperature_set` raises `ServiceValidationError` if `temperature` is passed
without `TARGET_TEMPERATURE` (`climate/__init__.py:775-782`) or if `target_temp_low` is
passed without `TARGET_TEMPERATURE_RANGE` (`:783-791`), then rejects an inverted range
(`:798-808`) and an out-of-`min_temp`/`max_temp` value (`:827-830`). **Nothing ties the
temperature form to the current `hvac_mode`.** A caller may therefore send a single
`temperature` while the Thermostat sits in `range`. The Integration must tolerate it — the
Thermostat's own `target_temperature_type` is the authority, and the write should be mapped
onto whichever `shared` field that mode actually uses, or rejected explicitly, rather than
written blind.

### 6.3 `HVACMode`, `HVACAction` and presets

`HVACMode`, `homeassistant/components/climate/const.py:6-30`: `OFF = "off"` (`:10`),
`HEAT = "heat"` (`:13`), `COOL = "cool"` (`:16`), `HEAT_COOL = "heat_cool"` (`:19`),
`AUTO = "auto"` (`:23`), `DRY = "dry"` (`:26`), `FAN_ONLY = "fan_only"` (`:29`).

The distinction that matters here is documented in the enum's own comments:
`HEAT_COOL` is *"The device supports heating/cooling to a range"* (`:18`), while `AUTO` is
*"The temperature is set based on a schedule, learned behavior, AI or some other related
mechanism. User is not able to adjust the temperature"* (`:21-22`). Nest `range` maps to
`HEAT_COOL`, not `AUTO`, despite the Thermostat's learning — because the user *can* adjust
the temperature.

`HVACAction`, `homeassistant/components/climate/const.py:83-94`: `COOLING` (`:86`),
`DEFROSTING` (`:87`), `DRYING` (`:88`), `FAN` (`:89`), `HEATING` (`:90`), `IDLE` (`:91`),
`OFF` (`:92`), `PREHEATING` (`:93`).

`PREHEATING` (`:93`) is worth noting against `eta_preconditioning_active`.

Preset constants, `homeassistant/components/climate/const.py:34-56`: `PRESET_NONE = "none"`
(`:35`), `PRESET_ECO = "eco"` (`:38`), `PRESET_AWAY = "away"` (`:41`),
`PRESET_BOOST = "boost"` (`:44`), `PRESET_COMFORT = "comfort"` (`:47`),
`PRESET_HOME = "home"` (`:50`), `PRESET_SLEEP = "sleep"` (`:53`),
`PRESET_ACTIVITY = "activity"` (`:56`).

**Presets are plain strings, not an enum** — unlike `HVACMode`, there is no `StrEnum` and
nothing validates a preset against the constant list. Custom presets are therefore
mechanically possible. NLE uses `home`/`away`/`eco`, all three of which happen to be core
constants.

Fan constants, `:60-69`: `FAN_ON = "on"` (`:60`), `FAN_OFF = "off"` (`:61`),
`FAN_AUTO = "auto"` (`:62`), plus `LOW`, `MEDIUM`, `HIGH`, `TOP`, `MIDDLE`, `FOCUS`,
`DIFFUSE`.

Default bounds: `DEFAULT_MIN_TEMP = 7`, `DEFAULT_MAX_TEMP = 35`,
`DEFAULT_MIN_HUMIDITY = 30`, `DEFAULT_MAX_HUMIDITY = 99`
(`homeassistant/components/climate/const.py:122-125`).

### 6.4 What may vary at runtime

`supported_features`, `capability_attributes` and `original_device_class` are compared
against the entity registry on **every state write** and updated when they differ
(`homeassistant/helpers/entity.py:1206-1249`). So they can legally change at runtime.

There is a soft brake: `CAPABILITIES_UPDATE_LIMIT = 100`
(`homeassistant/helpers/entity.py:82`). Exceeding 100 capability changes in a rolling hour
logs *"Entity %s (%s) is updating its capabilities too often, please %s"*
(`homeassistant/helpers/entity.py:1230-1241`). A Thermostat changes mode a handful of times
a day, so per-mode-dynamic features would not trip this — but it is churn for no protocol
reason.

`min_temp`, `max_temp` and `target_temperature_step` ride in `capability_attributes`
(`homeassistant/components/climate/__init__.py:317-324`), so they are subject to exactly the
same comparison and may likewise vary at runtime. **This is what makes #6's "surface the
Thermostat's own safety temperatures" implementable**: `min_temp` and `max_temp` can track
`lower_safety_temp` / `upper_safety_temp` as they change.

### 6.5 `has_entity_name` and naming

`homeassistant/helpers/entity.py:626-631` resolves `has_entity_name` from
`_attr_has_entity_name` first, then the entity description
(`homeassistant/helpers/entity.py:260`). It defaults to `False` on `EntityDescription`
(`:260`) and is part of the cached-property set (`:435`).

Name composition: `homeassistant/helpers/entity.py:715-735` resolves `_attr_name` first, then
a translated name via `_name_translation_key`, then the entity description's name, then a
device-class-derived name (`_device_class_name_helper`,
`homeassistant/helpers/entity.py:633-646`), which itself returns `None` outright unless
`has_entity_name` is set (`:639-640`). `has_entity_name` also participates in the registry
diff at `homeassistant/helpers/entity.py:1601`.

The documented convention — quality-scale rule `has-entity-name`, Bronze,
<https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/has-entity-name> —
is Bronze-tier and states, verbatim: *"When the name of the entity is set to `None`, the name
of the device will be used as the name of the entity. In this case, the lock entity will just
be called 'My device'. This should be done for the main feature of the device."* The same page
states *"There are no exceptions to this rule."* So `_attr_has_entity_name = True` always, and
the entity representing the device's main feature sets `_attr_name = None`. For us the main
feature is the climate entity. Every other entity gets a
name or a translation key, and HA composes "*Device name* Entity name" for the friendly
name. General entity documentation: <https://developers.home-assistant.io/docs/core/entity>.

### 6.6 `unique_id`

`homeassistant/helpers/entity.py:621-623` — a plain property returning `_attr_unique_id`.
Core does not validate the content; the constraint is a documented convention plus a
registry collision check in `homeassistant/helpers/entity_platform.py`, which writes
`supported_features=entity.supported_features` and the rest of the registry row at
`homeassistant/helpers/entity_platform.py:941`.

Quality-scale rule `entity-unique-id`, Bronze,
<https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/entity-unique-id>,
which defers the substance to the entity-registry documentation:
<https://developers.home-assistant.io/docs/entity_registry_index>. That page states an entity
is identified by *"a combination of the platform type (for example, `light`), and the
integration name (domain) (for example, hue) and the unique ID of the entity"*, and it lists
the sources explicitly:

- **Acceptable**: *"Serial number of a device"*; *"MAC address: formatted using
  `homeassistant.helpers.device_registry.format_mac`"*; latitude/longitude; *"Unique
  identifier that is physically printed on the device or burned into an EEPROM"*.
- **Unacceptable**: *"IP Address"*, *"Device Name"*, *"Hostname"*, *"URL"*, *"Email
  addresses"*, *"Usernames"*.

All six unacceptable sources can change without the device changing.

For us: the Thermostat's serial is extractable from every request, from the Basic Auth user
ID `d.{SERIAL}.{suffix}` (`NEST_CLOUD_PROTOCOL_REFERENCE.md:480-481`,
`protocol-transport-contract.md` §9). So `f"{serial}_{key}"` is both stable and
recommended-shaped. The `local_ip` entity is a *value* we surface, never an id component.

Note what NLE does and why it is not a template: it uses `nolongerevil_{serial}` for the
climate entity (`home_assistant_discovery.py:65`) and `nolongerevil_{serial}_{suffix}` for
the rest. The `nolongerevil_` prefix is doing the job HA's own domain scoping already does.

Related, and for #19 and #10 rather than #9: quality-scale rule `unique-config-entry`,
Bronze,
<https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/unique-config-entry>
— the config flow must refuse to add the same Thermostat twice, via `async_set_unique_id`
plus `_abort_if_unique_id_configured`. The serial is the natural key there too.

### 6.7 `DeviceInfo`

Defined in `homeassistant/helpers/device_registry.py`. Documentation:
<https://developers.home-assistant.io/docs/device_registry_index>.

Proposed mapping for the Thermostat:

| `DeviceInfo` field | Value | Source |
|---|---|---|
| `identifiers` | `{(DOMAIN, serial)}` | Basic Auth user ID (`NEST_CLOUD_PROTOCOL_REFERENCE.md:480-481`) |
| `connections` | `{(CONNECTION_NETWORK_MAC, mac)}` | `device.mac_address` (`:1262`) or the `/entry` form field `mac` (`:417`) |
| `serial_number` | serial | as above |
| `manufacturer` | `"Nest"` / `"Google Nest"` † | not reported by the Thermostat |
| `model` | `device.model_version` — **opaque, nothing branches on it** | `:1261` |
| `model_id` | the `/entry` `model` form field, e.g. `Diamond-2.6` — **opaque** | `:414-423` |
| `sw_version` | `device.current_version` | `:1260` |
| `hw_version` | the `/entry` `backplate_model` form field † | `:414-423` |
| `name` | `shared.name`, or the `where` bucket room name | `:1433`, `:1595-1601` |
| `configuration_url` | the Thermostat's Settings API base — but it is an IP, so it moves † | — |
| `suggested_area` | resolved from `device.where_id` via the `where` bucket † | `:1372-1379`, `:1595-1601` |

Two Model-string cautions carried forward: the reference does not define a model-string
taxonomy and the sources disagree (`protocol-transport-contract.md` §21.12), and per
`CONTEXT.md` the Model string is opaque data. It populates `model` / `model_id` for display
and nothing more.

### 6.8 `EntityCategory`

`homeassistant/const.py:955-970`:

```
CONFIG = "config"       # :964  "An entity which allows changing the configuration of a device."
DIAGNOSTIC = "diagnostic"  # "An entity exposing some configuration parameter, or diagnostics of a device."
```

The enum docstring at `homeassistant/const.py:956-961` states the behavioural consequence,
which is the real reason to get this right: an entity with a category *"will not be exposed
to cloud, Alexa, or Google Assistant components"* and *"not be included in indirect service
calls to devices or areas"*.

So a categorised entity is **excluded from "turn off everything in the living room"**. That
is the correct behaviour for the 78 configuration entities below, and it is why
the climate entity, the room temperature and humidity sensors, occupancy, fan-running and
the leaf indicator must stay uncategorised.

Resolution order on the entity: `_attr_entity_category` first, then the entity description
(`homeassistant/helpers/entity.py:921-926`); the description field defaults to `None`
(`homeassistant/helpers/entity.py:255`).

### 6.9 Device classes and state classes we will use

| Enum | Members used | Line |
|---|---|---|
| `SensorDeviceClass.TEMPERATURE` | `"temperature"` | `homeassistant/components/sensor/const.py:434` |
| `SensorDeviceClass.HUMIDITY` | `"humidity"` | `:267` |
| `SensorDeviceClass.BATTERY` | `"battery"` | `:165` |
| `SensorDeviceClass.SIGNAL_STRENGTH` | `"signal_strength"` — measurement only (`:827`) | `:406` |
| `SensorDeviceClass.DURATION` | `"duration"` — any state class (`:793`) | `:221` |
| `SensorDeviceClass.TIMESTAMP` | `"timestamp"` — **no state class permitted** (`:833`) | `:112` |
| `SensorDeviceClass.ENUM` | `"enum"` | `:104` |
| `SensorStateClass` | `MEASUREMENT` (`:546`), `MEASUREMENT_ANGLE` (`:549`), `TOTAL` (`:552`), `TOTAL_INCREASING` (`:557`) | `:543-560` |
| `NumberDeviceClass.TEMPERATURE` | `"temperature"`; units `°C`, `°F`, `K` | `homeassistant/components/number/const.py:405-409` |
| `NumberDeviceClass.DURATION` | `"duration"`; units `d`, `h`, `min`, `s`, `ms`, `μs` | `homeassistant/components/number/const.py:195-199` |
| `NumberMode` | `AUTO`, `BOX`, `SLIDER` | `homeassistant/components/number/const.py:97-102` |

`select`, `button`, `time` and `text` have **no device class** — nothing to assign.

Quality-scale entity rules, all Gold, so out of scope for phase one but cheap to satisfy
now: `entity-device-class`, `entity-category`, `entity-disabled-by-default`,
`entity-translations`, `devices`; index at
<https://developers.home-assistant.io/docs/core/integration-quality-scale/rules>. Note the
carve-out that `binary_sensor`, `number`, `sensor` and `update` entities **with a device
class set** may omit translation keys — which is why setting device classes wherever
possible pays twice.

Where the proposed set would **break** a Gold rule as drafted:
`entity-disabled-by-default` — 78 configuration entities and 40 diagnostics is a
lot of noise for a single wall thermostat. The cheap fix is
`_attr_entity_registry_enabled_default = False` on the rarely-touched config entities,
decided per-entity in #9. Everything else in the proposed set satisfies its rule already.

---

## 7. Availability in local push integrations

### 7.1 The conflict is real

Ticket #8 settled: push via `DataUpdateCoordinator` with no `update_interval`, driven by
`async_set_updated_data`. Ticket #6 settled: Thermostat availability becomes **entity**
availability, off the hold window.

Verified in core:

- `CoordinatorEntity.available` returns `self.coordinator.last_update_success` and nothing
  else (`homeassistant/helpers/update_coordinator.py:691-693`).
- `async_set_updated_data` sets `self.last_update_success = True` **unconditionally**
  (`homeassistant/helpers/update_coordinator.py:609`).

So a pure-push coordinator never fails, `last_update_success` is permanently `True`, and a
Thermostat that has been unplugged for a week still reads as available. **The collision is
real.**

Two supporting facts:

- `update_interval=None` is properly supported: `_schedule_refresh` short-circuits and
  creates no timer (`homeassistant/helpers/update_coordinator.py:254-257`).
- `async_set_update_error(err)` is the missing half — it sets
  `last_update_success = False` and notifies listeners
  (`homeassistant/helpers/update_coordinator.py:594-600`). It is guarded so it only logs and
  notifies on the transition (`:597`).

### 7.2 The three patterns core actually uses

**Pattern A — connection-close callback.** Connection-driven integrations flip availability
when the transport reports a disconnect. Widespread; e.g. `livisi/climate.py:97, 117`,
`nibe_heatpump/climate.py:97`. **This does not fit us.** The Thermostat is *supposed* to be
silent between long-polls (`protocol-transport-contract.md` §7.5, §11), and it deliberately
opens overlapping subscriptions without closing the old one
(`NEST_CLOUD_PROTOCOL_REFERENCE.md:756-779`). Silence is not a fault, and a closed
connection is not a dead device.

**Pattern B — coordinator error.** Call `async_set_update_error` when the Integration knows
something is wrong. Useful for genuine faults, insufficient on its own for "the device
stopped calling in", because nothing generates the error.

**Pattern C — a deadline timer reset on every inbound message.** This is the canonical
answer for a device that is intentionally silent, and core has it twice.

*MQTT `expire_after`* — the reference implementation of the idiom
(`homeassistant/components/mqtt/sensor.py`):

1. On each message, clear the expired flag, cancel the old trigger, and arm a new one:
   `self._expiration_trigger = async_call_later(self.hass, self._expire_after,
   self._value_is_expired)` (`:283-295`).
2. When it fires, set `_expired = True` and `async_write_ha_state()` (`:388-392`).
3. `available` ANDs the normal availability with `not expired` (`:395-400`).
4. State is restored across restarts with the remaining time recomputed from
   `last_state.last_changed` (`:205-231`).

*`nasweb`* — the closest structural match in core, because it is `local_push` with the
device pushing into an HTTP endpoint HA serves
(`homeassistant/components/nasweb/manifest.json`, `"iot_class": "local_push"`,
`"dependencies": ["webhook"]`). Its coordinator docstring states the case exactly: *"Since
status updates are managed through push notifications, this class schedules periodic checks
to ensure that devices are marked unavailable if updates haven't been received for a
prolonged period"* (`homeassistant/components/nasweb/coordinator.py:87-90`).

- Its own `async_set_updated_data` records `self.last_update = self._hass.loop.time()` and
  re-arms the check (`homeassistant/components/nasweb/coordinator.py:138-145`).
- `_schedule_last_update_check` cancels any pending timer and arms
  `event.async_call_at(...)` for `now + STATUS_UPDATE_MAX_TIME_INTERVAL`
  (`homeassistant/components/nasweb/coordinator.py:164-180`).
- The fired job just notifies listeners; the entity re-evaluates
  (`homeassistant/components/nasweb/coordinator.py:153-162`).
- The entity computes availability from staleness:
  `if self.coordinator.last_update is None or time.time() - entity_last_update >=
  STATUS_UPDATE_MAX_TIME_INTERVAL: self._attr_available = False`
  (`homeassistant/components/nasweb/climate.py:90-99`), called from
  `_handle_coordinator_update` before `async_write_ha_state()`
  (`homeassistant/components/nasweb/climate.py:101-113`).
- The entity starts unavailable: `self._attr_available = False` in `__init__`
  (`homeassistant/components/nasweb/climate.py:78`).
- Its threshold is a single named constant,
  `STATUS_UPDATE_MAX_TIME_INTERVAL = 60` (`homeassistant/components/nasweb/const.py:6`).

The timer API: `async_call_later(hass, delay, action) -> CALLBACK_TYPE`
(`homeassistant/helpers/event.py:1575-1587`), accepting seconds or a `timedelta`; the
returned callable cancels.

### 7.3 What this means for us

The shape is Pattern C, exactly as #6 anticipated: reset a watchdog on **every inbound
Thermostat contact** — a subscribe, a PUT, or a ping — and mark the entities unavailable
when it fires. No background polling loop, one timer, cancelled and re-armed.

**Express the threshold as a formula, not a constant.** The hold duration is #14's output.
The reference fixes the relationship: `X-nl-suspend-time-max` must be ≤ 350 s,
`hold_time = suspend_time_max - 10`, and a connection idle for ~360 s makes the Thermostat
declare it dead and resubscribe (`NEST_CLOUD_PROTOCOL_REFERENCE.md:1089-1117`;
`protocol-transport-contract.md` §7.5). So the availability deadline should be a stated
multiple of the hold — enough headroom to absorb one missed reconnect without flapping —
and it moves automatically if #14 changes the hold. Ticket #14 sets the multiplier; the
Integration must not carry a bare `300`.

Two mechanical notes. First, `CoordinatorEntity.available` is a plain property
(`homeassistant/helpers/update_coordinator.py:691-693`) and can simply be overridden to AND
the coordinator's own check with a staleness check, which is what MQTT does at
`homeassistant/components/mqtt/sensor.py:395-400`. Second, `available` on the base entity
defaults to `_attr_available` (`homeassistant/helpers/entity.py:864-866`), so the flag can
be set directly in the update callback in the `nasweb` style instead.

**Per-entity or device-wide?** Core offers no device-wide availability helper. Both
precedents set it per entity — `nasweb` recomputes it in each entity's
`_handle_coordinator_update`, MQTT computes it per entity. For us every entity is backed by
the same single Thermostat, so the natural implementation is one shared staleness check on
the coordinator that every entity consults, giving device-wide behaviour through per-entity
mechanics.

---

## 8. The proposed entity set

This is a count, not a design. It follows mechanically from #6's bar applied to
[section 5](#5-field-by-field-inventory), with the `†` fields resolved the way the table
proposes. **#9 may move any of these.**

| Platform | Primary | Diagnostic | Config | Total | Where enumerated |
|---|---|---|---|---|---|
| `climate` | 1 | — | — | **1** | [3.1](#31-the-climate-entity), [5.1](#51-shared-bucket--the-primary-control-surface) |
| `sensor` | 5 | 20 | — | **25** | [5.3](#53-device-bucket--read-only-telemetry), [5.4](#54-device-bucket--cloud-writable-settings) |
| `binary_sensor` | 3 | 20 | — | **23** | [5.1](#51-shared-bucket--the-primary-control-surface), [5.3](#53-device-bucket--read-only-telemetry) |
| `switch` | — | — | 29 | **29** | [5.2](#52-structure-bucket), [5.4](#54-device-bucket--cloud-writable-settings) |
| `number` | — | — | 21 | **21** | [5.4](#54-device-bucket--cloud-writable-settings) |
| `select` | — | — | 17 | **17** | [5.1](#51-shared-bucket--the-primary-control-surface), [5.2](#52-structure-bucket), [5.4](#54-device-bucket--cloud-writable-settings) |
| `time` | — | — | 4 | **4** | [5.4](#54-device-bucket--cloud-writable-settings) |
| `button` | — | — | 4 | **4** | [5.4](#54-device-bucket--cloud-writable-settings) |
| `text` | — | — | 3 | **3** | [5.2](#52-structure-bucket) |
| **Total** | **9** | **40** | **78** | **127** | |

The 78 config entities exceed the ~69 user-facing cloud-writable `device` fields because
they also cover `shared.schedule_mode`, six `structure` fields, and four `button`s that pair
with a timestamp sensor rather than backing a field of their own.

Reading of the numbers:

- **127** is the ceiling implied by "all user-facing settings changeable, all named
  telemetry surfaced". It is not a recommendation.
- **19** is the floor, from #6.
- The gap is almost entirely the config layer: NLE exposes exactly **one** writable device
  setting as an entity (fan duration) out of the 34 its own API whitelists. Everything else
  in its 34 is reachable only through its REST control API — which #6 dropped. **So "all
  settings changeable from HA" is genuinely new work, not a port.**
- If #9 wants a smaller first cut, the natural cleave is the config layer: ship the 49
  read-oriented entities (which contain all 18 non-`number` entities of the floor) plus the
  fan-duration `number` that completes the floor — 50 entities — and add config entities by
  group thereafter.
- Everything above is derived from the ~140 fields the reference names. The remaining ~99 of
  the 239 are undocumented and will only appear in live PUT traffic.

---

## 9. Ambiguous fields — decisions for a human

Every entry here has more than one defensible answer. **These are not resolved in this
document.**

### 9.1 Writable fields NLE exposes read-only

NLE ships these as read-only sensors, yet the protocol reference marks them cloud-writable.
`switch`/`number` (controllable) or `binary_sensor`/`sensor` (observable)?

| Field | NLE's choice | Reference says | Citation |
|---|---|---|---|
| `learning_mode` | `binary_sensor`, diagnostic | cloud-writable bool | `home_assistant_discovery.py:412-430` vs `NEST_CLOUD_PROTOCOL_REFERENCE.md:1353`, `:2024` |
| `compressor_lockout_timeout` | `sensor`, seconds, diagnostic | cloud-writable int | `home_assistant_discovery.py:391-409` vs `:2101` |
| `sunlight_correction_enabled` | not exposed (only `_active` is) | cloud-writable bool | `:1375`, `:2050` |

### 9.2 The two absolute-epoch fields

`fan_timer_timeout` and `time_to_target`. A `timestamp` sensor is live and correct but
displays an end time; a `duration` sensor in minutes is what a user reads at a glance but
decays between PUTs, and for a sleeping Thermostat that is up to five minutes of drift. NLE
chose decaying minutes (`mqtt_integration.py:678-690`, `:741-762`). Same question for
`hot_water_boost_time_to_end`, `filter_changed_date` and `safety_state_time`.

### 9.3 Emergency heat

Nest `emergency` has no HA `HVACMode`. NLE collapses it into `heat`
(`src/nolongerevil/lib/consts.py:111`) and the reverse map cannot produce it
(`:115-120`), so the round trip is lossy. Options: collapse and lose it; expose emergency as
a preset; expose it as a separate `switch`; or model it as `HVACAction` only, since
`hvac_emer_heat_state` exists in `shared`.

### 9.4 The eco/away preset triad

`manual_eco_all` (structure), `away` (structure) and `eco.mode` (device) are three
distinct mechanisms with different semantics — immediate vs delayed, blocking
preconditioning vs not (`NEST_CLOUD_PROTOCOL_REFERENCE.md:2245-2249`). HA presets are a
single-valued list. Do `away` and `eco` map to two presets backed by two mechanisms, or one
preset plus a separate `switch` for `away`? NLE collapsed them and made both write
`set_away(True)` (`mqtt_integration.py:293-317`), which loses the distinction on write.

### 9.5 The schedule surface

HA has no weekly-thermostat-schedule platform. #6 requires read **and** write. Candidates: a
custom service pair with the schedule as an entity attribute; per-day `text` entities; a
`calendar` entity; JSON in the climate entity's `extra_state_attributes`; or a config
sub-entry. Each is defensible and none is idiomatic. Layered on top: the 15 s debounce, the
silent discard while the user is editing on the dial, and the fact that `learning_mode` may
rewrite whatever we push (`NEST_CLOUD_PROTOCOL_REFERENCE.md:2569-2597`).

### 9.6 Static vs per-mode temperature features

Settled as *legal either way* in [6.2](#62-the-two-temperature-feature-flags); the choice is
open. Static-both follows `ecobee` and `nest`; per-mode-dynamic gives a cleaner UI and costs
registry churn.

### 9.7 Capability flags

`can_heat`, `can_cool`, `has_fan`, `has_emer_heat`, `has_humidifier`, `has_dehumidifier`,
`has_hot_water_control`. Three options, all defensible: shape `hvac_modes` and
`supported_features` and create no entity; create diagnostic `binary_sensor`s so automations
can see the wiring; or gate whole platforms so the entities simply do not exist. NLE takes
the first for `can_heat`/`can_cool` (`home_assistant_discovery.py:52-61`) and the third for
`has_fan` (`:571`, `:636`, `:642`).

### 9.8 Duplicate temperature and humidity

`shared.current_temperature` and `device.current_humidity` are already climate-entity
properties, yet NLE also publishes them as standalone sensors
(`home_assistant_discovery.py:135-172`). Duplication is redundant but standalone sensors are
far easier to graph and template against. #6 keeps the 19 as a floor, which argues for
keeping both.

### 9.9 The undocumented enums

Fifteen cloud-writable string fields have no documented value set anywhere:
`fan_heat_cool_speed`, `fan_schedule_speed`, `fan_timer_speed`, `humidifier_type`,
`dehumidifier_type`, `dehumidifier_orientation_selected`, `dual_fuel_breakpoint_override`,
`farsight_screen`, `ob_orientation`, `ob_persistence`, `logging_priority`, `house_type`,
`heat_link_connection`, `wiring_error`, `error_code`. A `select` needs an options list. Ship
them as `text`, defer them until live traffic reveals the values, or guess. Not decidable
from the sources available.

### 9.10 The 24 wiring fields

Struck from the config surface in [5.4](#54-device-bucket--cloud-writable-settings) as
commissioning state. But they *are* cloud-writable, so "all settings changeable" arguably
covers them. Read-only diagnostics, hidden entirely, or exposed with a warning?

### 9.11 `temperature_lock_pin_hash`

A credential. `text` (usable, leaks a hash into the state machine and the recorder),
service-call only, or omitted. The lock itself (`temperature_lock`) and its bounds are
unambiguous.

### 9.12 `click_sound`

The reference contradicts itself: `boolean` in the feature table
(`NEST_CLOUD_PROTOCOL_REFERENCE.md:2109`), `string` in the cloud-writable table (`:1371`).
`switch` or `select` depends on which is right.

### 9.13 `local_ip`

A `sensor` whose value is an IP. Useful for reaching the Settings API; also a
low-cardinality string that changes on DHCP renewal and is forbidden as a `unique_id`
component. Sensor, `DeviceInfo.configuration_url`, both, or neither.

### 9.14 `where_id` and `suggested_area`

`where_id` is a UUID naming a room, resolved through the `where` bucket
(`NEST_CLOUD_PROTOCOL_REFERENCE.md:1595-1601`). NLE hardcodes a 28-entry lookup table
(`helpers.py:18-47`) — Nest's own well-known UUIDs. Does it become a `select`, a read-only
`sensor`, `DeviceInfo.suggested_area`, or nothing, given HA already has areas?

### 9.15 `battery_level` units

The reference contradicts itself: *"Battery charge level (0.0–1.0)"*
(`NEST_CLOUD_PROTOCOL_REFERENCE.md:1908`) versus the battery-behaviour table, which is
plainly volts — 3.8 V normal, 3.6 V WiFi disabled (`:1152-1169`). NLE treats it as volts
and maps 3.5–4.0 V onto 0–100 % (`helpers.py:261-284`). If it is really 0.0–1.0, NLE's
converter clamps every real reading to 0 %. A `battery` device class demands a percentage; a
`voltage` sensor demands volts. Cannot be settled from the documents — needs live traffic.

### 9.16 `filter_runtime_sec`

`duration` device class in seconds (raw, correct, unreadable), or NLE's days conversion
(readable, lossy at `round(..., 1)`) with `total_increasing`
(`home_assistant_discovery.py:331-333`). HA converts `duration` units natively
(`homeassistant/components/sensor/const.py:580`), so the raw seconds path may render days
anyway.

### 9.17 Firmware version

`device.current_version` as `DeviceInfo.sw_version` (idiomatic, invisible on a dashboard) or
also a diagnostic `sensor` (queryable in templates and automations). Same question for
`backplate_model` and `hw_version`.

---

## 10. Discrepancies between sources

Recorded because a discrepancy is a finding.

### 10.1 Nine whitelisted names are not in the protocol reference

Searched the full text of `NEST_CLOUD_PROTOCOL_REFERENCE.md` for each name in backticks.
**Zero hits** for: `temp_lock_on`, `temp_lock_pin_hash`, `temp_lock_high_temp`,
`temp_lock_low_temp`, `fan_timer_duration_minutes`, `time_to_target_training_status`,
`equipment_type`, `heat_source`, `preconditioning_active`, `filter_reminder_level`.

Four of them look like a systematic rename of the temperature-lock group. The reference uses
`temperature_lock`, `temperature_lock_pin_hash`, `temperature_lock_high_temp`,
`temperature_lock_low_temp` (`NEST_CLOUD_PROTOCOL_REFERENCE.md:1287-1295`); NLE uses
`temp_lock_*`. Two more are near-misses: `time_to_target_training_status` versus the
reference's `time_to_target_training` (`:1257`, `:1957`), and `heat_source` versus the
reference's `heater_source` (`:1389`).

`fan_timer_duration_minutes` is the one with a consequence for us. The reference's field is
`fan_timer_duration`, in **seconds** (`:1303`, `:1970`). NLE's is a minutes value it clamps
to 15–1440 and defaults to 60 (`mqtt_integration.py:318-322`, `:766`), and its `number`
entity is built on it (`home_assistant_discovery.py:496-517`). Either the Firmware really
carries a separate minutes field the reference omits, or **NLE invented a field and stored
it in the device bucket as private state**. On the reference's write-protection rules
(`NEST_CLOUD_PROTOCOL_REFERENCE.md:1723-1732`) an unrecognised field would simply be ignored
by the Thermostat, which is consistent with NLE using it purely as a server-side preference —
its `set` handler stores the preference and only then computes a real `fan_timer_timeout`
from it (`mqtt_integration.py:324-333`). **The Integration should write
`fan_timer_duration` in seconds and hold any UI-facing minutes value as its own state.**

Two of the nine are also flatly *not* cloud-writable per the reference:
`preconditioning_active` (the reference has `eta_preconditioning_active`, device → server,
`:2015`) and `time_to_target` (device-only, `:1256`). Whitelisting them for writing looks
like a bug in the peer implementation.

Three further names NLE reads but the reference never mentions: `rssi`, `heatpump_ready`,
`outdoor_temperature`.

### 10.2 `time_to_target` is seconds or an epoch, not both

The reference says twice that it is a duration: *"Estimated seconds until the target
temperature is reached. `0` when at target"* (`NEST_CLOUD_PROTOCOL_REFERENCE.md:1955`) and
*"Estimated seconds to reach target temperature"* (`:1256`).

NLE treats it as an **absolute Unix timestamp**, computing `(target_timestamp - now) // 60`
and flooring at zero when it is in the past (`mqtt_integration.py:678-690`).

These cannot both be right. If the reference is right, NLE's sensor reads roughly 30 million
minutes. That NLE ships it suggests it was written against real hardware — but it is a
peer implementation, not evidence. **Resolvable only from live traffic.** Until then, treat
the encoding as unknown and do not hardcode either reading.

### 10.3 Bucket placement disagreements

- `current_temperature`: listed as **shared** in the bucket tables and in the explicit note
  *"`current_temperature` and `auto_away` are in the shared bucket, not the device bucket"*
  (`NEST_CLOUD_PROTOCOL_REFERENCE.md:1247-1249`), but as **Device** in the "Current
  conditions" table at `:1907`. The reference contradicts itself. NLE hedges by reading
  `shared` first and falling back to `device` (`mqtt_integration.py:522-524`).
- `auto_away`: documented as **shared** (`:1258`); NLE reads it from **device**
  (`helpers.py:296`).
- `current_humidity`: **device** everywhere (`:1245`, `:1908`) — consistent.
- `can_heat` / `can_cool`: **shared** only, per changelog rev 2.6
  (`protocol-transport-contract.md` §22); NLE reads `shared` first with a `device` fallback
  (`home_assistant_discovery.py:52-53`).

The Integration should read defensively across both buckets rather than trusting either
document.

### 10.4 `eco` and `eco_mode` are two different fields

Earlier notes conflated them. The reference documents both:

- **`eco_mode`** — *"The device reports its eco mode through the `eco_mode` field in the
  device bucket. This is a **read-only JSON string**"*
  (`NEST_CLOUD_PROTOCOL_REFERENCE.md:1944-1949`), carrying `mode`, `touched_by`,
  `mode_update_timestamp`, `touched_user_id`. Its value set is `schedule` / `manual-eco` /
  `auto-eco` (`:2257-2263`).
- **`eco`** — the **write** path, shown as a nested object in the eco-exit example:
  `"eco": {"mode": "schedule", "touched_by": 3, "mode_update_timestamp": ...}`
  (`:2213-2219`). The reference calls the `eco.mode` write *"the most reliable exit path —
  the device applies it unconditionally with no timestamp validation"* (`:2227`).

So `eco` is the special-access write field and `eco_mode` is the device-only read field.
`protocol-transport-contract.md` §21.9 flagged the type as ambiguous; that ambiguity is
**partly a conflation of two fields**, and partly real — the reference calls `eco_mode` a
JSON *string* while showing `eco` as a nested *object*, and does not say whether they share
an encoding.

**NLE reads the wrong one.** It reads `device_values.get("eco", {})` behind an
`isinstance(eco, dict)` guard (`helpers.py:239-241`, `:324-326`) — the write field, not
`eco_mode`. The defensive `isinstance` guard is itself consistent with the value sometimes
arriving as a string. Nothing in the MQTT layer settles the encoding. **Recorded as
unresolved**, for whichever ticket owns reference gaps.

### 10.5 NLE's HVAC action misses two heat flags

`derive_hvac_action` checks five heat-side flags (`helpers.py:158-164`) where the reference
names seven, omitting `hvac_alt_heat_x2_state` and `hvac_emer_heat_state`
(`NEST_CLOUD_PROTOCOL_REFERENCE.md:1424-1428`, and the equipment-category table at
`:1932-1938`). A Thermostat running emergency heat alone reports `idle`. Do not copy.

---

## 11. Cross-ticket notes

### 11.1 Outdoor temperature provenance — ticket #11 / #20

NLE ships an outdoor-temperature sensor reading `device.outdoor_temperature`, then
`shared.outside_temperature`, then `device.outside_temperature`
(`home_assistant_discovery.py:175-192`, `mqtt_integration.py:594-598`).

**None of those three names appears anywhere in the protocol reference** — the only
weather-adjacent thing it documents is the `weather_url` field in the `/entry` response
(`NEST_CLOUD_PROTOCOL_REFERENCE.md:448`). And the `nle-omissions` findings establish that
NLE's weather Route is a **caching proxy** to `weather.nest.com`, keyed by
`(postal_code, country)`, serving the Thermostat directly — it never writes a bucket field
(`omissions.md` §1).

So the value must be written into the `device` or `shared` bucket by the **Thermostat**,
presumably after it fetches weather itself. **Not established from source.** Marked
provenance-pending; ticket #20 owns settling it. **Do not assert a source in the spec.**

The dependency runs both ways: if the outdoor temperature only exists because the Thermostat
successfully called `weather_url`, then this entity's existence depends on #11's choice of
weather source. Recorded against #11 and #20.

### 11.2 Availability threshold — ticket #14

[Section 7.3](#73-what-this-means-for-us) gives the pattern. The threshold must be a stated
multiple of the hold window, which #14 owns. No bare constant.

### 11.3 Config-flow uniqueness — tickets #19 and #10

`unique-config-entry` (Bronze) requires `async_set_unique_id` plus
`_abort_if_unique_id_configured` on the serial. Same key as the entity `unique_id` prefix.

### 11.4 The `structure` bucket — ticket #8

The eco preset's authoritative source is `structure.manual_eco_all`, and #8 settled that the
Integration creates the `structure` bucket itself. The two decisions are consistent: the
preset reads a bucket we own outright.

### 11.5 Reference gaps

Three items belong to whichever ticket owns reference gaps: the `eco` / `eco_mode` encoding
([10.4](#104-eco-and-eco_mode-are-two-different-fields)), the `time_to_target` encoding
([10.2](#102-time_to_target-is-seconds-or-an-epoch-not-both)), and the `battery_level` unit
([9.15](#915-battery_level-units)). All three are resolvable from live PUT traffic and from
nothing else.
