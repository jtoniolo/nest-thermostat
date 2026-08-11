# Bucket Types -- The 18 Specialized Buckets

Research into the 18 specialized bucket types enumerated by the protocol reference
but not documented in depth. Determines what each bucket carries, who writes it,
and whether it contains user-facing state that the Integration must expose.

**Sources:**

- **Protocol reference**: `cjserio/nest-thermostat-protocol-docs` revision 2.9
  (2026-02-25, MIT). Section 3.2 (bucket table), section 4 (write protection),
  section 20 (PUT order), section 21.11 (specialized buckets advisory).
- **NLE server**: `codykociemba/NoLongerEvil-SelfHosted` at commit
  `bca8781012639c1cefc4a08c103fc892158fb630` (MIT). Read as a protocol reference
  only; no code reproduced.

Vocabulary follows `CONTEXT.md`: Thermostat, Firmware, Integration, NLE server,
Endpoint, Route.

---

## Summary Table

| Bucket | Direction | Who writes | Verdict | Rationale |
|--------|-----------|------------|---------|-----------|
| `hvac_partner` | Bidirectional | Thermostat (installer data) | Protocol bookkeeping | Nest Pro installer records; program defunct |
| `topaz` | Server -> device | Server only | Protocol bookkeeping | Nest Protect smoke detectors; separate device type |
| `kryptonite` | Bidirectional | Both | Protocol bookkeeping | Nest Temperature Sensors; cannot pair without Google cloud |
| `servicegroup` | Server -> device | Server only | Protocol bookkeeping | Cloud service grouping metadata |
| `occupancy` | Device -> server | Thermostat only | Protocol bookkeeping | Raw presence sensor feed for cloud occupancy analysis |
| `demand_response` | Bidirectional | Both | User-facing state (conditional) | Utility demand response enrollment; Thermostat actively writes |
| `demand_response_event` | Bidirectional | Both | User-facing state (conditional) | Individual DR events; Thermostat actively writes |
| `utility` | Server -> device | Server only | Protocol bookkeeping | Utility company association metadata |
| `diamond_sensor_config` | Server -> device | Server only | Unknown and inert | Thermostat sensor configuration; no observed writes |
| `diamond_sensor_event` | Bidirectional | Both | Unknown and inert | Thermostat sensor events; Thermostat writes but fields unknown |
| `rate_plan` | Server -> device | Server only | Protocol bookkeeping | Utility rate plan definition; requires utility partnership |
| `tou` | Bidirectional | Both | User-facing state (conditional) | Time-of-use pricing state; Thermostat actively writes, has consistency-checked icon field |
| `demand_charge` | Server -> device | Server only | Protocol bookkeeping | Demand charge structure definition; requires utility partnership |
| `demand_charge_event` | Bidirectional | Both | User-facing state (conditional) | Demand charge events; Thermostat actively writes, has consistency-checked icon field |
| `rcs_settings` | Bidirectional | Both | Protocol bookkeeping | Remote Climate Sensor settings; sensors cannot pair without Google cloud |
| `cloud_algo` | Bidirectional | Both | Protocol bookkeeping | Cloud-computed algorithm state (home/away prediction, savings) |
| `diagnostics` | Bidirectional | Both | Unknown and inert | Device diagnostics; Thermostat writes but fields unknown |
| `tuneups` | Bidirectional | Both | Protocol bookkeeping | HVAC tuneup/maintenance reminders from Nest's cloud service |

**Verdict counts:** 4 user-facing (all conditional on utility program enrollment),
10 protocol bookkeeping, 4 unknown and inert.

---

## Evidence for Each Bucket

### 1. hvac_partner

**Object key:** `hvac_partner.{partnerId}`

**Direction:** Bidirectional.

**What it is:** Professional HVAC installer/partner information. This corresponds to
the Nest Pro program, which allowed HVAC installers to register with Nest and be
associated with installations they performed. The protocol reference lists it in the
bucket table without further field documentation.

**Evidence from PUT order:** The Thermostat includes `hvac_partner` in its PUT
sequence (position 13 of 17). This means the Thermostat has stored partner data
that it actively reports to the server.

**Evidence from NLE server:** Listed in `KNOWN_BUCKET_TYPES` for named-field
parsing. No bucket-specific logic -- stored and served back generically. Not surfaced
in the MQTT HA discovery, status API, or command API.

**Who writes:** The Thermostat PUTs partner data (presumably initially populated by
the installer during setup). The server could push updated partner information.

**Fields:** Unknown. The protocol reference does not document them.

**Verdict:** Protocol bookkeeping. The Nest Pro program is defunct. Even when it
existed, this was installer metadata -- not something a homeowner would configure or
monitor. Safe to store and pass through without surfacing.

---

### 2. topaz

**Object key:** `topaz.{topazId}`

**Direction:** Server -> device.

**What it is:** Nest Protect (smoke/CO detector) state. "Topaz" is Google's internal
code name for the Nest Protect. In the original Nest ecosystem, Thermostats and
Protects communicated through the cloud: when a Protect detected smoke, the server
could tell the Thermostat to shut down the HVAC to prevent circulating smoke.

**Evidence from NLE server:** Listed in `KNOWN_BUCKET_TYPES`. No special handling --
purely passthrough. Not surfaced in any NLE entity or API.

**Who writes:** Server only (pushed to the Thermostat via subscribe).

**Fields:** Unknown. Would have carried Protect device status (alarm state, battery,
connectivity). The Thermostat never PUTs this bucket.

**Verdict:** Protocol bookkeeping. We are building an integration for a standalone
Thermostat. No Nest Protects can connect to a local server (they use Thread/Weave
with Google's cloud). Even if one could, the Protect's state would be its own device
and would not flow through the Thermostat's integration.

---

### 3. kryptonite

**Object key:** `kryptonite.{sensorId}`

**Direction:** Bidirectional.

**What it is:** Nest Temperature Sensor state. "Kryptonite" is Google's internal
code name for the external temperature sensors that pair with a Nest Thermostat to
provide readings from other rooms. These sensors communicate with the Thermostat
via Bluetooth Low Energy (BLE) and reported their data through the cloud.

**Evidence from PUT order:** The Thermostat includes `kryptonite` in its PUT
sequence (position 17 of 17, last in the order). This confirms the Thermostat
can report temperature sensor data.

**Evidence from NLE server:** Listed in `KNOWN_BUCKET_TYPES`. No special handling.
Not surfaced in any NLE entity.

**Who writes:** Both. The Thermostat PUTs sensor readings it receives over BLE. The
server could push sensor configuration.

**Fields:** Unknown. Would carry: sensor temperature reading, battery level,
connectivity status, room assignment. The `rcs_settings` bucket (see below) carries
the configuration side.

**Verdict:** Protocol bookkeeping. The Kryptonite sensors pair with the Thermostat
over BLE but required Google's cloud for their data to be useful (the cloud decided
which sensor's reading to use for HVAC decisions). On the Firmware, these sensors
may still be physically paired and reporting, but the cloud logic that acted on their
data does not exist locally. If a sensor is paired, the Thermostat may PUT its
readings here, but without the cloud algorithm (see `cloud_algo`) to interpret them,
the data has no effect on HVAC behavior.

**What would settle this:** Observing whether a Thermostat with paired Kryptonite
sensors actually PUTs data to this bucket on the Firmware. If it does, the
temperature readings are user-facing telemetry that could be surfaced as additional
temperature sensors.

---

### 4. servicegroup

**Object key:** `servicegroup.{id}`

**Direction:** Server -> device.

**What it is:** Service group metadata. In Google's cloud, devices were organized
into service groups for coordinated management, firmware rollouts, and feature
flagging. A service group defined which devices received which features or updates.

**Evidence from NLE server:** Listed in `KNOWN_BUCKET_TYPES`. No special handling.
Not surfaced anywhere.

**Who writes:** Server only (pushed to the Thermostat). The Thermostat does not
appear in the PUT order for this bucket.

**Fields:** Unknown. Likely contained group identifiers, feature flags, or rollout
metadata.

**Verdict:** Protocol bookkeeping. Service groups are cloud infrastructure for
fleet management. They have no meaning for a single Thermostat communicating with
a local server. The Thermostat presumably ignores the contents and just stores
them for sync purposes.

---

### 5. occupancy

**Object key:** `occupancy.{serial}`

**Direction:** Device -> server.

**What it is:** Raw occupancy/presence sensor data. The Thermostat has a passive
infrared (PIR) sensor and can detect motion in the room. In Google's cloud, this
raw sensor data was aggregated across devices and time windows to compute the
Home/Away state (`auto_away` in the device bucket). The `occupancy` bucket carries
the raw sensor feed -- individual detection events or aggregated sensor readings --
not the derived Home/Away decision.

**Evidence from NLE server:** Listed in `KNOWN_BUCKET_TYPES`. The NLE server's
occupancy binary sensor entity is derived from `auto_away` in the **device** bucket
(via the `is_device_away()` helper), not from the `occupancy` bucket. This confirms
that the usable occupancy state lives in the device bucket, and the `occupancy`
bucket is the upstream raw feed.

**Who writes:** Thermostat only (Device -> server). The Thermostat sends raw sensor
events. The server was supposed to aggregate them and update `auto_away` in the
device bucket. The Thermostat does not appear in the PUT order for this bucket,
which is notable -- it may be sent outside the normal multi-bucket PUT sequence, or
it may only be sent when the Thermostat detects occupancy state that its local
algorithm cannot resolve.

**Fields:** Unknown. Raw PIR events or summary occupancy counts.

**Verdict:** Protocol bookkeeping. The derived occupancy state (`auto_away`) is
already in the device bucket and is already surfaced by the NLE server as an HA
entity. The raw sensor feed in the `occupancy` bucket was input to Google's cloud
occupancy algorithm, which does not exist locally. The Thermostat runs its own
local occupancy algorithm and publishes the result to `auto_away` regardless.

---

### 6. demand_response

**Object key:** `demand_response.{id}`

**Direction:** Bidirectional.

**What it is:** Demand response program enrollment and configuration. Nest's
"Rush Hour Rewards" and "Seasonal Savings" programs allowed utilities to send
signals to enrolled Thermostats during peak demand, adjusting temperature setpoints
temporarily. The `demand_response` bucket carries the enrollment state and program
parameters.

**Evidence from PUT order:** The Thermostat includes `demand_response` in its PUT
sequence (position 1 of 17, first in the order). This is significant: the
Thermostat prioritizes demand response data above all other buckets, suggesting
the Firmware treats it as active state.

**Evidence from NLE server:** Listed in `KNOWN_BUCKET_TYPES`. No special handling.
Not surfaced in any NLE entity.

**Who writes:** Both. The server pushes enrollment data and program parameters. The
Thermostat reports its response status and local override state.

**Fields:** Unknown. Would carry: program enrollment status, utility identifier,
DR program parameters, opt-in/opt-out preferences, temperature offset limits.

**Verdict:** User-facing state (conditional). If a user was enrolled in a demand
response program before their Thermostat was moved to the Firmware, this bucket may
still carry enrollment data. The Thermostat actively reports it. A user would want
to see whether a DR program is active and whether the Thermostat is currently
responding to a DR event. However, without the utility's cloud infrastructure to
send DR signals, no new events will arrive, making this effectively dormant. A user
who was never enrolled would have an empty bucket.

**What would settle this:** Observing the actual fields and values a Thermostat
sends for this bucket after being flashed to the Firmware. If the Firmware clears
this bucket on flash, it is inert. If it preserves pre-existing enrollment data,
it carries user-facing state.

---

### 7. demand_response_event

**Object key:** `demand_response_event.{eventId}`

**Direction:** Bidirectional.

**What it is:** Individual demand response events. When a utility signals a peak
demand period, an event is created in this bucket with start/end times and
temperature adjustment parameters. The Thermostat adjusts its setpoint accordingly
and reports its participation status.

**Evidence from PUT order:** Position 2 of 17 (second, right after
`demand_response`). The Firmware continues to report DR event state.

**Evidence from NLE server:** Listed in `KNOWN_BUCKET_TYPES`. No special handling.

**Who writes:** Both. The server creates events with utility signals. The
Thermostat reports its response (participating, opted out, completed).

**Fields:** Unknown. Would carry: event start/end times, temperature adjustment,
participation status, user opt-out flag.

**Verdict:** User-facing state (conditional). Same conditions as `demand_response`.
If the utility partnership infrastructure does not exist locally, no new events will
be created. Pre-existing event history may persist. A user would want to see active
DR events and their opt-in/out status.

---

### 8. utility

**Object key:** `utility.{id}`

**Direction:** Server -> device.

**What it is:** Utility company association. Google's Nest cloud matched a home's
location to its electricity/gas utility and pushed utility information to the
Thermostat. This enabled features like Rush Hour Rewards, energy reports, and
time-of-use pricing.

**Evidence from NLE server:** Listed in `KNOWN_BUCKET_TYPES`. No special handling.
Not surfaced.

**Who writes:** Server only. The Thermostat does not appear in the PUT order for
this bucket.

**Fields:** Unknown. Would carry: utility name, utility ID, program eligibility,
service territory information.

**Verdict:** Protocol bookkeeping. Utility association was a server-side function
of Google's cloud. The Integration has no way to look up which utility serves a
given address, and the Thermostat does not use this information independently. If
pre-existing utility data exists, it is informational only and not something a user
would configure.

---

### 9. diamond_sensor_config

**Object key:** `diamond_sensor_config.{id}`

**Direction:** Server -> device.

**What it is:** Thermostat sensor configuration. "Diamond" is Google's internal
code name for the Nest Thermostat gen 2 (as seen in the model string
`Diamond-2.6`). This bucket likely configures the Thermostat's own sensor
subsystem -- calibration offsets, sensor weights, or active sensor selection.

**Evidence from NLE server:** Listed in `KNOWN_BUCKET_TYPES`. No special handling.
Not surfaced.

**Who writes:** Server only. The Thermostat does not appear in the PUT order for
this bucket.

**Fields:** Unknown. No evidence of specific fields in either source.

**Verdict:** Unknown and inert. The sources do not document what fields this bucket
carries. The Thermostat does not PUT to it, so it is a receive-only bucket whose
configuration was presumably pushed by Google's cloud. Without knowing the fields
or their effects, the safest approach is to store and serve back whatever data
exists without modification.

**What would settle this:** Observing the subscribe request from a Thermostat to
see whether it requests this bucket. If it does and the bucket is empty, the
Thermostat presumably operates without it. If it contains data from the pre-flash
state, examining the fields would reveal whether they affect sensor behavior.

---

### 10. diamond_sensor_event

**Object key:** `diamond_sensor_event.{id}`

**Direction:** Bidirectional.

**What it is:** Thermostat sensor events. Events from the Thermostat's own sensor
subsystem -- possibly temperature anomaly alerts, sensor calibration events, or
readings that require special handling.

**Evidence from PUT order:** Position 11 of 17. The Thermostat actively reports
sensor events.

**Evidence from NLE server:** Listed in `KNOWN_BUCKET_TYPES`. No special handling.

**Who writes:** Both. The Thermostat PUTs sensor events. The server could push
acknowledgments or configuration responses.

**Fields:** Unknown. No evidence of specific fields in either source.

**Verdict:** Unknown and inert. The Thermostat writes to this bucket, but the field
structure is unknown. Without knowing what the events contain, there is no basis for
surfacing them. The safest approach is passthrough.

**What would settle this:** Capturing the actual PUT payload from a Thermostat
running the Firmware to see what fields and values are sent.

---

### 11. rate_plan

**Object key:** `rate_plan.{id}`

**Direction:** Server -> device.

**What it is:** Utility electricity rate plan definition. Part of Nest's energy
program integration, this bucket defines the rate structure the Thermostat uses to
optimize energy consumption. A rate plan specifies prices at different times of day,
seasons, and demand tiers.

**Evidence from NLE server:** Listed in `KNOWN_BUCKET_TYPES`. No special handling.

**Who writes:** Server only. The Thermostat does not PUT this bucket.

**Fields:** Unknown. Would carry: rate tiers, time-of-day pricing windows, seasonal
rates, demand charges. Related to the `tou` and `demand_charge` buckets.

**Verdict:** Protocol bookkeeping. Rate plans were pushed by Google's cloud based
on the home's utility (see `utility` bucket). The Integration has no source for
rate plan data. The Thermostat may use a cached rate plan for `tou_icon` display, but
this is a cosmetic feature that degrades gracefully without fresh data.

---

### 12. tou

**Object key:** `tou.{id}`

**Direction:** Bidirectional.

**What it is:** Time-of-Use pricing state. Tracks whether the current electricity
price is peak, off-peak, or mid-peak based on the rate plan. The Thermostat uses
this to display a pricing icon on its screen and can optionally adjust its behavior
to avoid peak-rate operation.

**Evidence from PUT order:** Position 12 of 17. The Thermostat actively reports TOU
state.

**Evidence from protocol reference (write protection, section 4):** The field
`tou_icon` is listed as one of 12 device-only fields with explicit consistency
checking. If the server pushes a value for `tou_icon` that differs from the
Thermostat's local state, the Thermostat marks it dirty, overwrites the server's
value, and re-sends its own. This proves that the Thermostat actively computes and
displays TOU state.

**Evidence from NLE server:** Listed in `KNOWN_BUCKET_TYPES`. No special handling.
Not surfaced in any NLE entity.

**Who writes:** Both. The Thermostat PUTs its current TOU state (including the icon
it is displaying). The server pushes TOU configuration from the rate plan.

**Fields:** Unknown specifically, but the existence of `tou_icon` in the device
bucket (with consistency checking) means the Thermostat renders this visually. The
`tou` bucket likely carries: current pricing tier, active TOU schedule, pricing
window boundaries.

**Verdict:** User-facing state (conditional). If a rate plan is configured and TOU
pricing is active, a user would want to see which pricing tier is current. The
Thermostat actively computes and displays this. However, without a rate plan (which
requires the `utility` and `rate_plan` buckets to be populated by a cloud service),
TOU has no input data and the bucket is empty. For Thermostats that had TOU
configured pre-flash, cached TOU data may persist and the Thermostat may continue
displaying a TOU icon based on stale data.

---

### 13. demand_charge

**Object key:** `demand_charge.{id}`

**Direction:** Server -> device.

**What it is:** Demand charge structure definition. Demand charges are a utility
billing mechanism where the customer pays based on their peak power draw during a
billing period, not just total consumption. This bucket defines the charge structure.

**Evidence from protocol reference (write protection, section 4):** The field
`demand_charge_icon` is listed as one of 12 device-only fields with explicit
consistency checking, identical treatment to `tou_icon`. This proves the Thermostat
actively computes and displays demand charge state.

**Evidence from NLE server:** Listed in `KNOWN_BUCKET_TYPES`. No special handling.

**Who writes:** Server only. The Thermostat does not PUT this bucket.

**Fields:** Unknown. Would carry demand charge thresholds, billing period
boundaries, peak demand limits.

**Verdict:** Protocol bookkeeping. Like `rate_plan`, this was pushed by Google's
cloud. The Integration has no source for demand charge data. The related
`demand_charge_icon` field in the device bucket is Thermostat-computed and will
reflect whatever cached data exists, but the source definition in this bucket is
server-originated.

---

### 14. demand_charge_event

**Object key:** `demand_charge_event.{eventId}`

**Direction:** Bidirectional.

**What it is:** Individual demand charge events. When the Thermostat detects
that power demand is approaching a threshold, or when the utility signals a
demand charge period, an event is created.

**Evidence from PUT order:** Position 15 of 17. The Thermostat actively reports
demand charge events.

**Evidence from NLE server:** Listed in `KNOWN_BUCKET_TYPES`. No special handling.

**Who writes:** Both. The Thermostat PUTs event status. The server could push
utility-originated events.

**Fields:** Unknown. Would carry: event timestamps, demand level, threshold status,
Thermostat response.

**Verdict:** User-facing state (conditional). Same conditions as `demand_response`
and `tou`. If demand charge data exists, a user would want to see it. Without the
utility infrastructure, no new events will be created.

---

### 15. rcs_settings

**Object key:** `rcs_settings.{id}`

**Direction:** Bidirectional.

**What it is:** Remote Climate Sensor configuration. RCS (Remote Climate Sensor) is
the feature name for Nest Temperature Sensors (code name "Kryptonite"). This bucket
configures which sensors are active, their room assignments, and the sensor schedule
(which room's temperature to use at what time).

**Evidence from PUT order:** Position 16 of 17. The Thermostat reports RCS
configuration state.

**Evidence from NLE server:** Listed in `KNOWN_BUCKET_TYPES`. No special handling.

**Who writes:** Both. The server pushes sensor schedules. The Thermostat reports
active sensor status.

**Fields:** Unknown specifically. Would carry: active sensor list, sensor-to-room
mapping, sensor schedule (time-based room priority), fallback behavior.

**Verdict:** Protocol bookkeeping. The Kryptonite sensors that RCS configures
require Google's cloud to function meaningfully (see `kryptonite` above). Without
active sensors reporting data, the configuration has nothing to configure. If a
Thermostat had sensors configured pre-flash, this bucket may retain stale
configuration, but the sensors themselves cannot connect to a local server.

**What would settle this:** Same as `kryptonite` -- determining whether BLE-paired
sensors continue to report readings to the Thermostat after flashing.

---

### 16. cloud_algo

**Object key:** `cloud_algo.{id}`

**Direction:** Bidirectional.

**What it is:** Cloud algorithm state. Google's cloud ran various algorithms on
Thermostat data: home/away prediction (using occupancy sensor data), energy savings
calculations, temperature recommendations, and learning adjustments. This bucket
carries the server-computed state of those algorithms.

**Evidence from PUT order:** Position 14 of 17. The Thermostat reports cloud
algorithm state (likely echoing what it received or reporting its local application
of the algorithm outputs).

**Evidence from NLE server:** Listed in `KNOWN_BUCKET_TYPES`. No special handling.

**Who writes:** Both. The server pushes algorithm outputs. The Thermostat reports
its application of them.

**Fields:** Unknown. Would carry: predicted occupancy schedule, savings estimates,
recommended setpoint adjustments.

**Verdict:** Protocol bookkeeping. The cloud algorithms that produced these values
do not exist locally. The Thermostat's local learning algorithm (`learning_mode` in
the device bucket) operates independently. Any cached cloud algorithm state is stale
and will not be refreshed. The Thermostat presumably falls back to its local
algorithms when cloud algorithm data is absent or stale.

---

### 17. diagnostics

**Object key:** `diagnostics.{id}`

**Direction:** Bidirectional.

**What it is:** Device diagnostics data. System health information, error logs,
performance metrics, and diagnostic state. In Google's cloud, this powered the
device health monitoring and proactive support features.

**Evidence from PUT order:** Position 17 of 17 (last in the PUT sequence). The
Thermostat reports diagnostics data.

**Evidence from NLE server:** Listed in `KNOWN_BUCKET_TYPES`. No special handling.
Not surfaced in any NLE entity.

**Who writes:** Both. The Thermostat PUTs diagnostic data. The server could push
diagnostic requests or configuration.

**Fields:** Unknown. Would carry: error counts, HVAC cycle statistics, sensor health,
connectivity metrics, firmware diagnostics. Likely overlaps with fields already in
the device bucket (`error_code`, `wiring_error`, `safety_state`) but may carry
time-series or detailed data that the device bucket's snapshot fields do not.

**Verdict:** Unknown and inert. The diagnostics data could theoretically be
user-facing (a power user might want HVAC cycle statistics or error history), but
without knowing the actual fields, there is no basis for surfacing anything. The
device bucket already carries the essential diagnostic fields (`error_code`,
`safety_state`, `battery_level`). The `diagnostics` bucket may carry supplementary
detail, but passthrough is safe.

**What would settle this:** Capturing the actual PUT payload to identify fields. If
it carries HVAC cycle counts, runtime hours, or detailed error history, those would
be user-facing telemetry worth surfacing.

---

### 18. tuneups

**Object key:** `tuneups.{id}`

**Direction:** Bidirectional.

**What it is:** HVAC tuneup and maintenance reminders. Google's Nest cloud offered
seasonal HVAC tuneup reminders (fall heating checkup, spring cooling checkup) based
on the system configuration and usage patterns.

**Evidence from PUT order:** Position 3 of 17 (third, after the demand response
pair). The Thermostat actively reports tuneup state.

**Evidence from NLE server:** Listed in `KNOWN_BUCKET_TYPES`. No special handling.

**Who writes:** Both. The server pushes tuneup schedules and reminders. The
Thermostat reports completion/dismissal status.

**Fields:** Unknown. Would carry: upcoming tuneup dates, tuneup type
(heating/cooling), completion status, reminder dismissal, pro installer referral.

**Verdict:** Protocol bookkeeping. The tuneup reminders were a cloud-originated
feature. Without Google's cloud generating new reminders, no new tuneups will appear.
The Thermostat may retain pre-existing tuneup records. The Integration already handles
HVAC maintenance through the filter reminder fields in the device bucket
(`filter_reminder_enabled`, `filter_replacement_needed`), which is the user-facing
maintenance data.

---

## Cross-Cutting Findings

### The NLE Server's Generic Passthrough Pattern

The NLE server treats all 18 specialized bucket types identically: they are listed
in `KNOWN_BUCKET_TYPES` so the named-field request parser recognizes them, but no
bucket-type-specific logic exists for any of them. The transport handler stores
whatever the Thermostat sends, serves it back on subscribe when the server's
timestamp is newer, and does nothing else with the data.

The NLE server's 19 HA entities are all derived from the `device`, `shared`, and
`structure` buckets exclusively. The command API writes only to `device`, `shared`,
`structure`, and `schedule` buckets. No specialized bucket data is surfaced to
Home Assistant or consumed by any NLE business logic.

This establishes a strong precedent: the NLE server's author, who has extensive
experience with the Firmware, judged that none of these buckets carry state worth
surfacing to HA.

### Which Buckets the Thermostat Actually PUTs

The protocol reference's PUT order (section 20) lists which buckets appear in
multi-bucket PUT requests. Of the 18 specialized buckets, the following are
confirmed to be actively written by the Thermostat:

1. `demand_response` (position 1)
2. `demand_response_event` (position 2)
3. `tuneups` (position 3)
4. `diamond_sensor_event` (position 11)
5. `tou` (position 12)
6. `hvac_partner` (position 13)
7. `cloud_algo` (position 14)
8. `demand_charge_event` (position 15)
9. `rcs_settings` (position 16)
10. `kryptonite` (position 17)
11. `diagnostics` (position 17)

The following specialized buckets are server-only (the Thermostat never PUTs them):

1. `topaz`
2. `servicegroup`
3. `utility`
4. `diamond_sensor_config`
5. `rate_plan`
6. `demand_charge`

The `occupancy` bucket is marked Device -> server in the protocol reference table,
but notably does **not** appear in the PUT order. This could mean it is sent outside
the normal multi-bucket PUT sequence or that the Firmware does not use it.

### Write-Protection Evidence

The protocol reference's write protection section (section 4) lists two fields in
the device bucket that relate to specialized buckets:

- `tou_icon` -- consistency-checked device-only field
- `demand_charge_icon` -- consistency-checked device-only field

Both fields are among the 12 that the Thermostat explicitly verifies against server
pushes and overwrites if different. This proves the Thermostat actively computes and
renders TOU and demand charge state on its display, even though the source data is
in specialized buckets.

### The Utility Program Dependency

Four of the user-facing-state buckets (`demand_response`, `demand_response_event`,
`tou`, `demand_charge_event`) share a common dependency: they only carry meaningful
data when the Thermostat is enrolled in a utility demand response or time-of-use
program. These programs required:

1. Google's cloud to identify the utility (via `utility` bucket)
2. The utility to have a partnership with Nest
3. The user to enroll through the Nest app

Without Google's cloud, no new utility programs can be enrolled, no new DR events
will arrive, and no new TOU schedules will be pushed. However, pre-existing
enrollment data and cached TOU schedules may persist in the Thermostat's flash
storage and continue to be reported. For a Thermostat that was never enrolled in
any utility program (the likely case for most units being flashed), these buckets
will be empty.

### Recommendation for the Integration

The Integration should implement the same generic passthrough pattern as the NLE
server for all 18 specialized bucket types:

1. **Store** whatever the Thermostat sends for each bucket.
2. **Serve it back** on subscribe when the server's timestamp is newer.
3. **Do not surface** any of them as HA entities in the initial implementation.
4. **Do not write** to any of them from the command API.

This matches the protocol reference's own advice (section 21.11, line 1697):
"Store any data the device sends for these buckets, and serve it back on subscribe."

The four conditionally-user-facing buckets (`demand_response`,
`demand_response_event`, `tou`, `demand_charge_event`) could be revisited if a user
reports that their Thermostat was enrolled in a utility program pre-flash and wants
to see that state. But this is a future enhancement, not a parity requirement.

The three unknown-and-inert buckets (`diamond_sensor_config`,
`diamond_sensor_event`, `diagnostics`) should be monitored by capturing actual PUT
payloads when a Thermostat connects to the Integration for the first time. If they
carry useful telemetry, they can be surfaced later.
