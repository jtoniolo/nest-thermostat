# The weather surface

Research for [#20](https://github.com/jtoniolo/nest-thermostat/issues/20). Input to
[#11](https://github.com/jtoniolo/nest-thermostat/issues/11), which chooses the source.
This document presents the contract and the consequences. It chooses nothing.

Vocabulary follows `CONTEXT.md`: Thermostat, Firmware, Integration, NLE server, Endpoint,
Route, Advertised URL.

## Sources and how they are cited

| Tag | Source | How cited |
|-----|--------|-----------|
| **NLE** | The NLE server, `codykociemba/NoLongerEvil-SelfHosted`, cloned at `reference/NoLongerEvil-SelfHosted/` (gitignored). Protocol reference only — read, never copied. | file path + line |
| **REF** | `cjserio/nest-thermostat-protocol-docs`, `NEST_CLOUD_PROTOCOL_REFERENCE.md`, fetched from `raw.githubusercontent.com/cjserio/nest-thermostat-protocol-docs/main/` | line number in that file |
| **ARCHIVE** | Live responses from Nest's own weather Route, captured by the Internet Archive before the cloud shut down | Wayback URL |
| **CLIENT** | Third-party clients that consumed the same Route against the real Nest cloud | repo, tag, file, line |

Every claim below is tagged **VERIFIED** (read in one of those sources) or **INFERENCE**
(reasoned from them). Nothing here was tested against a Thermostat; there is no hardware
in the loop, per the map.

---

## 1. Summary

The weather surface is a **read-only, client-pull, side-channel Route**. It is not part of
the bucket protocol at all: no subscribe, no PUT, no revisions, no `object_key`. The
Thermostat simply GETs a URL it was handed at `/entry` and parses JSON.

Ticket [#3](https://github.com/jtoniolo/nest-thermostat/issues/3)'s finding — "weather is
a cached proxy and not load-bearing for HVAC" — is **confirmed** as to the NLE server's
implementation, and **confirmed** as to HVAC control. Two of its statements need
correcting, and one new constraint was found that materially changes the shape of #11:

1. **Correction.** #3 says the NLE server "does not define or transform the schema; it
   forwards whatever Nest's weather API returns." That is accurate but incomplete in a way
   that matters: the upstream it forwards from, `weather.nest.com`, **no longer exists**.
   The NLE server's weather Route is therefore dead code in practice — every request
   fails upstream and returns HTTP 502. The NLE server is a specimen of the *plumbing*,
   not a working example.
2. **Correction.** #3 describes the request as carrying `postal_code` and `country` query
   parameters. The real wire form is a **single `query` parameter**, and the NLE server
   reads parameter names the Thermostat does not send (§4.3).
3. **New constraint.** The postal code and country do **not** arrive from the Thermostat.
   Per the protocol reference they live in the **`structure` bucket**, which is
   server → device only. The Integration must **supply** them before the Thermostat can
   ask for weather at all (§3).

The full response schema **was** recovered — not from the NLE server, which never defines
it, but from archived live responses of Nest's own Route (§5).

---

## 2. How the Thermostat discovers the Route

### 2.1 `weather_url` in the `/entry` response

**VERIFIED (REF).** `weather_url` is one of the optional fields of the `/entry` response.
The reference documents it in a single line and says nothing else about it:

> `| weather_url | No | Weather data endpoint. |` — REF line 448

`No` is the "Required" column. **The reference marks `weather_url` as optional.** Omitting
it from the `/entry` response is a documented, in-contract choice (see §8.5).

**VERIFIED (NLE).** The NLE server always emits it, as
`reference/NoLongerEvil-SelfHosted/src/nolongerevil/routes/nest/entry.py:55`:

```
"weather_url": f"{origin}/nest/weather/v1?query=",
```

`origin` is `settings.api_origin_with_port` (entry.py:28) — the same Advertised URL used
for `transport_url` and the rest (entry.py:49-56).

### 2.2 The trailing `?query=` is the whole contract

**VERIFIED (ARCHIVE).** The real Nest cloud emitted the same shape. A 2012 writeup of a
captured Nest login response records:

> `"weather_url": "http://www.wunderground.com/auto/nestlabs/geo/current/i?query="`
>
> — <https://wiredprairie.github.io/wiredprairie.us-website/blog/archives/date/2012/10/>

**VERIFIED (CLIENT).** `weather_url` is a **prefix**, and the client appends the query
token to it by plain string concatenation — no URL building, no parameter encoding:

> `url = self._nest_api.urls['weather_url'] + postal_code`
>
> — `jkoelker/python-nest` v2.11.0, `nest/nest.py:979`
> (<https://raw.githubusercontent.com/jkoelker/python-nest/v2.11.0/nest/nest.py>)

**INFERENCE.** The Firmware does the same. The URL the NLE server hands out ends in a bare
`?query=` for exactly one reason: to be concatenated onto. Both the historical Nest value
and the NLE value share that terminator, and a third-party client written against the real
cloud concatenates. This is strong but not directly observed on a Thermostat.

**Consequence for the Integration.** The Advertised URL logic that already applies to
`transport_url` applies here. The value must be an address on the Thermostat's own network
and must carry the explicit port, per the reference's port rule. Anything the Integration
puts in `weather_url` will come back with a query token glued to its end, so it must end in
`?query=` (or at least in a `?…=` or `&…=`).

---

## 3. Where the postal code and country come from

This is the part that most changes #11.

### 3.1 The reference puts them in the `structure` bucket

**VERIFIED (REF).** A grep of the entire 2,800-line reference for `postal`, `country`,
`zip`, `latitude`, `weather`, `outdoor`, `outside_temp`, `sunrise` and `sunset` returns
exactly four lines. Three of them are these, and all three sit inside the
`### structure bucket` field table (heading at REF line 1549):

| REF line | Field | Type | Reference's description |
|----------|-------|------|-------------------------|
| 1568 | `country_code` | string | ISO country code |
| 1569 | `postal_code` | string | Postal/ZIP code |
| 1570 | `location` | object | Location data (zipcode, country, latitude, longitude) |

The reference states of that bucket, verbatim:

> **Direction**: Server → device only
>
> "Home-level settings that apply to all devices in a structure. The device never sends
> this bucket in PUT requests." — REF lines 1551-1554

**So the Integration is the origin of the postal code, not the recipient of it.** The
Thermostat cannot tell the Integration where it is. Until the Integration pushes a
`structure` bucket carrying `postal_code` and `country_code`, the Thermostat has no query
token to send.

This dovetails with the already-settled finding on
[#8](https://github.com/jtoniolo/nest-thermostat/issues/8): the Integration must create the
`structure` bucket anyway (for `manual_eco_all`), and the Thermostat does not subscribe to
it until the server has pushed it once. Weather adds two more fields to a bucket that is
already on the build list; it adds no new machinery.

### 3.2 There is also a `device`-bucket `postal_code`

**VERIFIED (CLIENT).** `python-nest` reads a postal code from **both** buckets, as two
separate properties on two separate classes:

> `Device.postal_code` → `return self._device['postal_code']`
> — python-nest v2.11.0, `nest/nest.py:469-470`
>
> `Structure.postal_code` → `return self._structure['postal_code']`
> — python-nest v2.11.0, `nest/nest.py:907-908`
>
> `Structure.country_code` → `return self._structure['country_code']`
> — python-nest v2.11.0, `nest/nest.py:835-836`

**VERIFIED (NLE).** The NLE server only ever looks in the `device` bucket, and uses the
name `country`, not `country_code`:

- `reference/NoLongerEvil-SelfHosted/src/nolongerevil/services/sqlmodel_service.py:848-853`
  reads `device.{serial}` and takes `postal_code`, then `country` with a hardcoded default
  of `"US"`.
- `reference/NoLongerEvil-SelfHosted/src/nolongerevil/routes/nest/transport.py:448` treats
  `postal_code` as a field that can arrive in a **device-bucket PUT** — it re-syncs weather
  when `"postal_code" in value`.
- `reference/NoLongerEvil-SelfHosted/src/nolongerevil/routes/control/command.py:420-421`
  lists `postal_code` and `country_code` in its cloud-writable device-field whitelist,
  under a `# Locale` comment.

**INFERENCE, with a caveat.** Both a `structure.postal_code` and a `device.postal_code`
appear to exist. The reference documents only ~15 named fields out of the device bucket's
239 (REF lines 1222, 1239-1264), so its silence on a device-bucket `postal_code` is not
evidence of absence. Two independent sources — a client written against the real cloud, and
the NLE server — both act as though the device bucket has one.

The name of the country field is an **unresolved conflict**: the reference says
`country_code` (structure), the NLE server reads `country` (device), and `python-nest`
reads `country_code` (structure). Nothing available settles which name the Firmware uses in
the device bucket.

**Practical reading for #11.** Write `postal_code` and `country_code` into the `structure`
bucket, because that is what the reference documents and what is server-writable by
definition. Additionally accept and store a `postal_code` if one turns up in a device PUT —
the store-and-serve rule from #8 covers that for free. Do not depend on the device-bucket
one arriving.

### 3.3 What the query token looks like

**VERIFIED (CLIENT).** The token is the postal code and the country code joined by a comma,
with no space:

> `merge_code = self.postal_code + ',' + self.country_code`
> — `jkoelker/python-nest` v3.1.0, `nest/nest.py:176`
> (<https://raw.githubusercontent.com/jkoelker/python-nest/v3.1.0/nest/nest.py>)

So the full request is:

```
GET {weather_url}{postal_code},{country_code}
```

which for the NLE server's `weather_url` expands to:

```
GET /nest/weather/v1?query=94304,US
```

**VERIFIED (ARCHIVE).** The token is not always a postal code. The literal string `ipv4`
is a valid token, meaning "geolocate me from my source IP":

> `https://developers.nest.com/weather/v1?query=ipv4` — archived 200 response,
> <https://web.archive.org/web/20170203163528id_/https://developers.nest.com/weather/v1?query=ipv4>

That is almost certainly what the NLE server's `("ip", "auto")` cache-key fallback
(weather_service.py:85-86) was written for.

**INFERENCE.** A Thermostat with no `postal_code` in either bucket most likely sends
`?query=ipv4`. Not observed.

---

## 4. The request, precisely

### 4.1 Wire form

**VERIFIED (NLE, ARCHIVE, CLIENT).**

| Property | Value |
|----------|-------|
| Method | `GET` |
| Path | whatever `weather_url` said; the NLE server serves `/nest/weather/v1` |
| Query | a single parameter, `query`, whose value is `{postal_code},{country_code}` or `ipv4` |
| Body | none |
| Auth | none required (§4.4) |
| Content negotiation | none observed; the response is `application/json` |

### 4.2 Routes the NLE server registers

**VERIFIED (NLE).** `reference/NoLongerEvil-SelfHosted/src/nolongerevil/routes/nest/weather.py:59-60`
registers two GETs on the same handler: the exact path `/nest/weather/v1`, and a catch-all
`/nest/weather/{path:.*}`. A middleware rewrites the legacy un-prefixed form — the pattern
`^/weather/(.*)$` maps to `/nest/weather/\1`
(`src/nolongerevil/middleware/url_normalizer.py:22`).

**INFERENCE.** The catch-all and the legacy rewrite exist because the Firmware may have a
`weather_url` baked in from a previous Endpoint, or may append a path rather than a query.
Serving a catch-all under the weather prefix is cheap insurance. Not observed.

### 4.3 The NLE server reads the wrong parameter names

**VERIFIED (NLE).** The handler reads `postal_code` and `country` from the query string:

- `weather.py:27` → `request.query.get("postal_code")`
- `weather.py:28` → `request.query.get("country")`

But the URL it advertises ends in `?query=` (entry.py:55), so the parameter the Thermostat
actually sends is named `query`. Both `.get()` calls therefore return `None`.

**Consequence, VERIFIED by reading the code path.** `postal_code` and `country` being
`None` makes `weather_service.py:85-86` fall back to the cache key `("ip", "auto")`.
Every Thermostat, in every location, shares one cache entry. The raw query string is still
forwarded upstream verbatim (weather.py:29, weather_service.py:132-133), so a *live*
upstream would still have returned the right city — but the cache would serve one
location's weather to every Thermostat.

The NLE server's own test suite never exercises this: `test_default_cache_keys`
(`tests/test_weather_service.py:130-139`) asserts the `("ip", "auto")` fallback is
*correct* behaviour when no parameters are given, and no test drives the HTTP handler with
a realistic `?query=` string.

**Do not copy this.** Parse the `query` parameter, split on the comma.

### 4.4 Authentication

**VERIFIED (NLE).** The weather Route is unauthenticated in every mode. In open mode
(`REQUIRE_DEVICE_PAIRING=false`, the default) the auth middleware returns before any check
(`src/nolongerevil/middleware/device_auth.py:79-82`). In paired mode only transport POSTs
and uploads are gated; the docstring lists weather among the always-allowed Routes
(`device_auth.py:60`, and the comment and gate expression at `device_auth.py:87-92`).

**INFERENCE.** The Integration should not require auth here either. Pairing does not apply
to this project at all (settled on #8), so the point is moot in practice.

### 4.5 Poll frequency

**NOT ESTABLISHED.** Nothing in the reference, the NLE server, or the archived material
says how often the Firmware fetches weather.

Two weak indications, both from clients rather than from the Thermostat: `python-nest`
caches for 270 s (`nest/nest.py:969`), and the NLE server caches for 600 s (§7). Both are
*client/server* choices, not observations of the Firmware.

**What would establish it:** a request log from a Thermostat pointed at a server that
answers `/entry` with a `weather_url`. The NLE server's own `DEBUG_LOGGING` would capture
it. That needs hardware, so it is out of scope for this map — and it does not block a
build, because a server does not care how often it is asked.

---

## 5. The response, field by field

### 5.1 The NLE server does not define a schema

**VERIFIED (NLE).** This is worth stating plainly, because the ticket asks for "the exact
response shape the NLE server returns." The answer is: **the NLE server has no schema.** It
is a byte-for-byte passthrough.

`weather_service.py:119-147` (`_fetch_weather`) appends the raw query string to a hardcoded
upstream URL, and on HTTP 200 returns `await response.json()` unchanged
(`weather_service.py:140-141`). `weather.py:38-39` serializes that dict straight back out.
No field is read, renamed, defaulted, or validated anywhere on the path.

The upstream constant is `weather_service.py:15`:

```
NEST_WEATHER_URL = "https://weather.nest.com/weather/v1"
```

**VERIFIED (ARCHIVE).** That host is gone. The Internet Archive's most recent capture of
`https://weather.nest.com/weather/v1?query=` is a **404**, dated 2026-08-02
(Wayback CDX index for `nest.com`, filtered on `weather/v1`).

**Therefore:** running the NLE server today, every weather request 502s (§8.1). It is not a
working reference for this surface — only for the plumbing around it.

### 5.2 The schema, recovered from archived live responses

The schema below is **VERIFIED (ARCHIVE)** — it is read off two complete, real responses
from Nest's own `/weather/v1` Route, captured while the cloud was live.

Capture A, 2017-02-03:
<https://web.archive.org/web/20170203163528id_/https://developers.nest.com/weather/v1?query=ipv4>

Capture B, 2015-09-17:
<https://web.archive.org/web/20150917151054id_/https://developer.nest.com/weather/v1?query=ipv4>

#### Top level: keyed by the query token

The response is a JSON object with **exactly one key: the query token that was sent**.
Capture A, sent with `?query=ipv4`, came back keyed by the resolved IP, `"207.241.226.216"`.
Capture B, same, keyed by `"207.241.226.234"`.

**VERIFIED (CLIENT).** For a postal-code query the key is the postal token verbatim:

> `value = response.json()[postal_code]`
> — python-nest v2.11.0, `nest/nest.py:982`, where `postal_code` is the `{postal},{cc}`
> merge code built at v3.1.0 `nest/nest.py:176`

So a request for `?query=94304,US` returns `{"94304,US": { … }}`.

**This is the single most easily-missed detail in the whole contract.** A payload that
omits the wrapper — that returns the inner object directly — is a different shape, and a
client that indexes by the token gets a `KeyError`. The NLE server itself gets this wrong
elsewhere in its own code (§6.2).

#### `current` — object

Present in both captures. Capture B is the richer one; capture A dropped four fields, so
**consumers must treat every field as optional**.

| Key | Type | Units / format | A | B |
|-----|------|----------------|---|---|
| `temp_f` | number | degrees Fahrenheit | `32.0` | `74` |
| `temp_c` | number | degrees Celsius | `0.0` | `23.3` |
| `condition` | string | human-readable, e.g. `"Mostly Cloudy"`, `"Scattered Clouds"` | yes | yes |
| `icon` | string | slug, e.g. `"mostlycloudy"`, `"partlycloudy"` | yes | yes |
| `humidity` | integer | percent relative | `48` | `77` |
| `sunrise` | integer | Unix epoch **seconds** | `1486129380` | `1442493120` |
| `sunset` | integer | Unix epoch **seconds** | `1486167660` | `1442537479` |
| `wind_dir` | string | compass abbreviation, e.g. `"E"`, `"SSE"` | yes | yes |
| `wind_mph` | number | miles per hour | `13` | `5` |
| `gmt_offset` | string | signed hours, e.g. `"-06.00"` | yes | yes |
| `wind_kph` | number | kilometres per hour | — | `8.0` |
| `timezone` | string | abbreviation, e.g. `"CDT"` | — | yes |
| `lengthofday` | integer | minutes (`739` ≈ 12 h 19 min, consistent with the sunrise/sunset delta) | — | `739` |
| `observation_time` | integer | Unix epoch seconds | — | `1442501100` |

Note `temp_f` and `temp_c` are both present and are the same reading in two scales; the
Thermostat is not expected to convert.

#### `location` — object

| Key | Type | Notes | A | B |
|-----|------|-------|---|---|
| `station_id` | string | may be the literal `"unknown"` | yes | yes |
| `zip` | string | postal code | `"79401"` | `"79401"` |
| `city` | string | | yes | yes |
| `state` | string | | `"TX"` | `"TX"` |
| `country` | string | ISO two-letter | `"US"` | `"US"` |
| `lat` | string | decimal degrees, **as a string** | `"33.591678"` | yes |
| `lon` | string | decimal degrees, **as a string** | `"-101.852307"` | yes |
| `short_name` | string | e.g. `"Lubbock,TX"` | yes | yes |
| `full_name` | string | free-form; the two captures disagree wildly on format (a street address in A, `"Lubbock,TX 79457 US"` in B) | yes | yes |
| `timezone` | string | abbreviation, e.g. `"CST"` | yes | yes |
| `timezone_long` | string | IANA zone, e.g. `"America/Chicago"` | yes | yes |
| `gmt_offset` | string | signed hours; note the two captures format it differently — `"-06.00"` in A, `"-5.00"` in B | yes | yes |

**VERIFIED (CLIENT).** `location.timezone_long` and `location.gmt_offset` are the two fields
a real client depended on, in that order of preference:

> `self._tz = pytz.timezone(weather['location']['timezone_long'])` … else
> `self._tz = NestTZ(weather['location']['gmt_offset'])`
> — python-nest v2.11.0, `nest/nest.py:236-239`

#### `forecast` — object with two arrays

**`forecast.daily[]`** — six entries in A, ten in B.

| Key | Type | Units | A | B |
|-----|------|-------|---|---|
| `date` | integer | Unix epoch seconds, midnight local | yes | yes |
| `temp_low_f` / `temp_high_f` | number | Fahrenheit | yes | yes |
| `temp_low_c` / `temp_high_c` | number | Celsius | yes | yes |
| `humidity` | integer | percent | yes | yes |
| `condition` | string | | yes | yes |
| `icon` | string | | yes | yes |
| `wind_dir` | string | | — | yes |
| `wind_kph` | number | km/h | — | yes |

**`forecast.hourly[]`** — 48 entries in capture A.

| Key | Type | Units |
|-----|------|-------|
| `hour` | integer | 1-based index into the array, `1`…`48` |
| `time` | integer | Unix epoch seconds |
| `temp_f` | number | Fahrenheit |
| `temp_c` | number | Celsius |
| `humidity` | integer | percent |

**VERIFIED (CLIENT).** A real client navigated exactly `['current']`,
`['forecast']['daily']` and `['forecast']['hourly']` — python-nest v2.11.0,
`nest/nest.py:243-251`. There are no other consumed paths.

#### `meta` — object

Present in capture A only: `{"zip_prefix": false, "zip_query": true}`. Booleans describing
how the server resolved the query token. **No client reads it.** Absent from capture B.

### 5.3 Reconciling the NLE server against the third-party clients

It is natural to ask which source wins where the NLE server and the historic third-party
clients disagree — the NLE server being the implementation actually exercised against the
Firmware we target. **The question does not arise, and the reason is the finding.**

**VERIFIED (NLE).** The NLE server has no response shape to compare against. It reads no
field, names no field, and defaults no field. `_fetch_weather` returns
`await response.json()` verbatim (`weather_service.py:140-141`); the Route serialises that
dict unchanged (`weather.py:38-39`). The upstream it forwards from is
`https://weather.nest.com/weather/v1` (`weather_service.py:15`) — **the same Route the
archived captures and the third-party clients were talking to.**

So the comparison collapses:

| | |
|---|---|
| Is the NLE server's shape the same as the historic shape? | **Identical, by construction.** It is a byte-for-byte proxy of that exact Route. |
| Superset or subset? | Neither. There is no transformation to be a superset or subset of. |
| Does that mean the historic shape is proven against the Firmware? | **No.** It means the NLE server never tested the shape either — it only ever relayed it. Nobody in either source read a weather field and acted on it. |

The one place the NLE server *does* name weather fields — `sync_user_weather_from_device`
reading `current` and `location` (§6.2) — reads them at the wrong nesting level and is
unreachable in the default configuration. It is not evidence of a validated shape; it is a
bug in dead code.

**Consequence.** The archived live captures in §5.2 are the *only* evidence of this
surface's schema that exists anywhere. They are stronger evidence than the NLE server, not
weaker: they are what the Route actually returned. The NLE server contributes the plumbing —
the Route path, the `?query=` terminator, the caching, the failure codes — and contributes
nothing at all about the body.

Three corrections to the third-party summary, all **VERIFIED (ARCHIVE)** against the two
captures in §5.2:

1. **`sunrise` and `sunset` are present.** Both captures carry them inside `current`, as
   Unix epoch seconds. What remains true is that no consumer for them was found — not in the
   reference, not in the NLE server (§6.4). Present in the payload, unused as far as anyone
   can show.
2. **Temperatures are served in both scales, not Celsius only.** `temp_c` and `temp_f` are
   both present at every level that carries a temperature — `current`, `forecast.daily[]`
   (as `temp_low_*`/`temp_high_*`), and `forecast.hourly[]`.
3. **Wind is served in both units, and unevenly.** The 2015 capture carries `wind_mph` and
   `wind_kph` in `current` and `wind_kph` in `forecast.daily[]`; the 2017 capture carries
   only `wind_mph`, and no wind at all in the forecast. This is the clearest single instance
   of the schema drift that underwrites the "all fields optional" reading.

`display_city` is correctly excluded — it belongs to the other endpoint (§5.4).

**On verifying the query-token wrapper.** It cannot be settled from
`routes/nest/weather.py`; that file never touches the body, so it is silent on the question.
It is settled instead by the two archived responses, both of which are wrapped, and by
python-nest indexing the parsed body by the token (`nest/nest.py:982`). See §5.2.

### 5.4 A different, non-`weather_url` schema exists — do not confuse them

**VERIFIED (ARCHIVE, CLIENT).** Nest also ran an app-facing weather API at
`https://home.nest.com/api/0.1/weather/forecast/{postal_code},{country_code}` with a
**completely different schema** — top level `display_city`, `city`, `now`, `forecast`, no
query-token wrapper; `now.current_temperature`, `now.current_humidity`, `now.current_wind`,
`now.conditions`, `now.icon`, `now.sunrise`, `now.sunset`, `now.wind_direction`,
`now.gmt_offset`, `now.station_id`; and `forecast.daily[]` using
`high_temperature`/`low_temperature`/`conditions`.

- Archived live response:
  <https://web.archive.org/web/20221222002007id_/https://home.nest.com/api/0.1/weather/forecast/6825MD,NL>
- Client: `gboudreau/nest-api`, `nest.class.php:154-171`
  (<https://raw.githubusercontent.com/gboudreau/nest-api/master/nest.class.php>) builds that
  URL and reads `$weather->now->current_temperature` and `$weather->now->current_humidity`.

**This is the app's API, not `weather_url`.** It is recorded here only so nobody implements
the wrong schema — the `now` shape is the more widely-blogged one, and it is wrong for this
surface.

An incidental data point from that client, worth noting for §8: it comments that the
forecast API "will often return a '502 Bad Gateway' or '503 Service Unavailable' response…
meh" and swallows the error (`nest.class.php:162-165`). Nest's own weather infrastructure
was routinely flaky, and clients were built to tolerate it.

---

## 6. What the Thermostat does with the data

### 6.1 Nothing in HVAC control depends on it

**VERIFIED (REF).** The word `weather` appears **once** in the entire protocol reference —
line 448, the `/entry` field table. There is no weather input to any documented control
path: not the schedule (REF "Temperature schedules"), not eco mode, not the state-interaction
matrix, not `target_temperature` resolution. #3's conclusion holds.

**VERIFIED (NLE).** Nothing in the NLE server reads a weather field to make a decision. The
only consumer of cached weather data anywhere in the server is
`sync_user_weather_from_device` (§6.2), which writes it to a display bucket.

### 6.2 The one place weather enters the bucket store — and it is broken

**VERIFIED (NLE).** `src/nolongerevil/services/sqlmodel_service.py:835-874` copies cached
weather into the **`user` bucket**, as a `weather` sub-object shaped
`{"current": …, "location": …, "updatedAt": <ms>}` (lines 863-868).

Three things about that path:

1. **It reads the wrong nesting level.** It does `weather.data.get("current")` and
   `weather.data.get("location")` (lines 865-866), but the cached payload is the raw
   upstream body — which is wrapped in the query-token key (§5.2). Both `.get()` calls
   return `None` against a real response. The NLE server would write
   `{"current": null, "location": null, "updatedAt": …}`.
2. **It almost never runs.** Every one of its three call sites is guarded by an existing
   `device_owner` record — `routes/nest/transport.py:437-445`, `:448-454`, and `:931-935`.
   With pairing off, which is the NLE server's default and this project's settled position
   (#8), no owner record exists and the function is never called.
3. **The `user` bucket does not apply here.** The reference says it "exists solely to
   trigger pairing completion on the device. The device ignores all fields except `name`."
   (REF lines 1581-1587). #8 already settled that this project emits no `user` bucket at all.

**Conclusion.** This is dead code twice over. It is not evidence that the Thermostat reads
weather from a bucket.

### 6.3 Outdoor temperature — the question, answered

This was raised as decision-critical for #11: if outdoor temperature flows from the weather
surface, a static payload silently kills a real sensor.

**VERIFIED (NLE), exhaustively.** A grep of the **entire** NLE tree, all file types, for
`outdoor_temperature`, `outside_temperature`, `outdoorTemperature` and `outsideTemperature`
returns **eleven hits and not one write site**. Every hit is in the MQTT layer:

- `src/nolongerevil/integrations/mqtt/mqtt_integration.py:594-597` — a three-way read with
  fallback: `device.outdoor_temperature`, else `shared.outside_temperature`, else
  `device.outside_temperature`.
- `mqtt_integration.py:599-603` — publishes it, only `if outdoor_temp is not None`.
- `src/nolongerevil/integrations/mqtt/home_assistant_discovery.py:175-182`, `:561-562`,
  `:667` — the MQTT discovery payload and topic for the sensor.

**The NLE server never writes either field into any bucket.** It reads whatever happens to
be in the store and publishes it if non-null. This is corroborated by a parallel inventory
of every bucket field the NLE server writes across `shared`, `device`, `structure`,
`schedule`, `device_alert_dialog` and `user`: neither name appears in it.

**VERIFIED (REF).** Neither `outdoor_temperature` nor `outside_temperature` appears
**anywhere** in the protocol reference — the grep in §3.1 covered both and returned zero
hits. So the per-field access-mode tables cannot settle this: the field is not in them. The
reference names roughly 15 fields out of the device bucket's 239 and 113 device-only ones
(REF lines 1222, 1229-1238, 1239-1264), so its silence is not evidence of absence.

**Verdict: CANNOT BE ESTABLISHED from available sources.**

Specifically:

- **Ruled out:** server-injected from weather. The NLE server demonstrably does not do it,
  and there is no documented server-writable field to do it with.
- **Not ruled out:** reported by the Thermostat. If the field is populated at all, the
  Thermostat must PUT it, and the three-name fallback in the NLE code reads like a guess by
  someone who did not know which name the Firmware uses — evidence of uncertainty, not of
  presence.
- **Not ruled out:** never populated. On the NLE server today, with `weather.nest.com` dead
  (§5.1), that sensor is certainly always empty.

**What would establish it:** a device-bucket PUT capture from a flashed Thermostat, or the
Firmware's full 239-field device-bucket registry. Both need hardware, which the map places
out of scope.

**On the specific hypothesis** that the Thermostat parses the weather response and renders
an outdoor temperature on screen while the NLE server's own HA sensor for it stays empty:
that is **consistent with every fact above and is not established by any of them.** It
requires two unverified steps — that the gen 1/gen 2 screen renders weather at all (§6.4,
not established, and Google scopes the on-device weather display to gen 3), and that the
Thermostat does *not* also PUT the value back. The second half of it — that the NLE server's
`outdoor_temperature` sensor is empty — is separately **certain today** for a much duller
reason: its upstream is dead, so no weather data reaches it at all (§5.1). Do not treat
"NLE's sensor is empty" as evidence about what the Thermostat displays.

**The part that does not need settling, and is what #11 actually turns on.** A Nest Learning
Thermostat has **no outdoor sensor**. Whatever path an outdoor temperature takes, its only
possible upstream origin is the weather response. So:

> If the Integration serves a static weather payload, an outdoor-temperature reading is
> either absent or a frozen constant — under **every** branch above. The uncertainty is
> about *whether the entity exists*, never about *whether a static payload could make it
> correct*.

That is enough to price the decision on #11 without resolving the field question.

### 6.4 What the Thermostat visibly does

**NOT ESTABLISHED for gen 1 and gen 2.** No primary source was found showing what a gen 1 or
gen 2 Thermostat renders from the weather response on its own screen.

What *is* verified, and points the other way:

- **VERIFIED.** Google's own support page for "Weather isn't displaying" scopes on-screen
  weather to Farsight, and Farsight to the **3rd gen** Learning Thermostat:
  <https://support.google.com/googlenest/answer/9235741>. Gen 1 and gen 2 have no Farsight.
  The failure text that page documents is "Can't get the weather right now. nest.com/m2".
- **VERIFIED (REF), by absence.** The reference contains no weather-driven display field,
  no sunrise/sunset consumer, and no outdoor-temperature field.
- **VERIFIED.** Sunblock is **not** fed by this surface. The Thermostat's
  `sunlight_correction_enabled` / `sunlight_correction_active` fields are about its own
  built-in sunlight sensor compensating for direct sun falling on the unit — not solar
  times. `sunrise` and `sunset` appear in the weather payload (§5.2) but appear nowhere in
  the reference or in the NLE server.

**INFERENCE, held loosely.** On a gen 1 or gen 2 Thermostat the weather surface may have no
visible effect at all — it may have existed to feed the Nest phone app and the "Home Report"
email rather than the device screen. Neither confirmed nor refuted.

**What would establish it:** watching a flashed gen 2 Thermostat with and without a
`weather_url`. Hardware; out of scope.

### 6.5 Present, absent, or stale

Combining the above:

| State | HVAC control | Bucket state | Thermostat display |
|-------|--------------|--------------|--------------------|
| **Present** | unaffected — VERIFIED (§6.1) | unaffected; nothing writes a bucket from weather — VERIFIED (§6.2) | possibly nothing on gen 1/gen 2 — NOT ESTABLISHED (§6.4) |
| **Absent** | unaffected — VERIFIED | unaffected — VERIFIED | at worst, a weather element goes blank or shows an error string — INFERENCE from the gen 3 behaviour Google documents |
| **Stale** | unaffected — VERIFIED | unaffected — VERIFIED | shows old numbers; nothing in any source says the Thermostat detects or flags staleness. There is no timestamp field the Firmware is documented to check — `current.observation_time` exists but only in the older capture (§5.2) |

**Stale is indistinguishable from fresh, as far as any source shows.** The NLE server relies
on this: it serves arbitrarily old cached data on upstream failure with no marker (§7.3).

---

## 7. Where the NLE server sources the data, and its caching

### 7.1 Upstream

**VERIFIED (NLE).** One hardcoded host, no API key, no credentials:

- `services/weather_service.py:15` — `NEST_WEATHER_URL = "https://weather.nest.com/weather/v1"`
- `weather_service.py:131-133` — the raw inbound query string is appended verbatim
- `weather_service.py:42-46` — a dedicated `aiohttp` session with **SSL verification
  disabled** and a 30-second total timeout. The stated reason (`weather_service.py:37-39`)
  is that the host used a private CA, "Nest Private Server Certificate Authority", absent
  from public trust stores.
- `weather_service.py:139-141` — only HTTP 200 is accepted; any other status returns `None`
  (`:142-144`), and `aiohttp.ClientError` is caught and returns `None` (`:145-147`).

**VERIFIED (ARCHIVE).** As established in §5.1, the host is dead — Wayback's latest capture
of it is a 404 dated 2026-08-02.

### 7.2 Cache

**VERIFIED (NLE).**

| Property | Value | Citation |
|----------|-------|----------|
| Key | the tuple `(postal_code, country)` | `weather_service.py:89`; storage predicate at `services/sqlmodel_service.py:384-387` |
| Key fallback | `("ip", "auto")` when either is missing | `weather_service.py:85-86` |
| Stored value | the entire upstream body, JSON-serialised to a text column | `models/integration.py:22-31`; `models/converters.py:126-133` |
| Backing store | SQLite table `weather`, composite primary key `(postalCode, country)`, plus `fetchedAt` as an integer millisecond timestamp | `models/integration.py:22-30` |
| TTL | **600 000 ms = 600 s = 10 minutes**, default, settable via `WEATHER_CACHE_TTL_MS` | `config/environment.py:55-58`; exposed in seconds at `config/environment.py:170-172`; documented in the NLE `README.md:111`; also set explicitly in `.env.example:21` and `docker-compose.yml:35` |
| Freshness test | `datetime.now() - fetched_at < timedelta(seconds=ttl)` | `weather_service.py:65-66` |
| Eviction | none by age. A write deletes all rows for that key and inserts one — so exactly one row per key, forever | `sqlmodel_service.py:394-414` |
| Read | most recent by `fetchedAt`, limit 1 | `sqlmodel_service.py:388-389` |

Note the practical consequence of the §4.3 bug: because the handler never extracts a real
postal code, the key is *always* `("ip", "auto")` in practice, so the table holds one row.

### 7.3 Failure behaviour — the stale-serve rule

**VERIFIED (NLE).** `weather_service.py:68-117` implements this order:

1. Read the cache. If a row exists **and** is within TTL → return it (`:89-92`).
2. Otherwise fetch upstream (`:98`).
3. On success, write the cache and return the fresh body (`:99-108`).
4. On **any** exception, log it and fall through (`:109-110`).
5. If a cached row exists — **however old** — return it, logging a warning (`:112-115`).
6. Otherwise return `None` (`:117`), which the Route turns into HTTP 502 (§8.1).

So the cache is a fallback of unbounded age, not just a rate limiter. There is no
stale-while-revalidate, no negative caching, and no backoff: every request during an
upstream outage attempts a fresh 30-second-timeout fetch before falling back.

### 7.4 What the NLE server's tests actually pin down

**VERIFIED (NLE).** `tests/test_weather_service.py` has 12 tests. None constrains the
response schema — the fixtures use invented payloads like `{"temp": 20}` and
`{"temperature": 22, "conditions": "sunny"}` (lines 82, 120, 167). Enumerated:

| Test | Line | Pins down |
|------|------|-----------|
| `test_initialization` | 30 | constructor stores the backend; no session yet |
| `test_creates_session` | 41 | `initialize()` creates a session |
| `test_session_has_timeout` | 48 | (asserts only that the session exists — vacuous) |
| `test_closes_session` | 60 | `close()` clears the session |
| `test_close_without_init_is_safe` | 67 | `close()` before `initialize()` does not raise |
| `test_fresh_cache_is_valid` | 76 | a just-fetched row is valid |
| `test_stale_cache_is_invalid` | 86 | a one-hour-old row is invalid at the default TTL |
| `test_edge_case_just_expired` | 97 | at a 300 s TTL, 301 s old is invalid — TTL is exclusive |
| `test_returns_cached_data` | 114 | a valid cache hit short-circuits, and the lookup is called with exactly `("12345", "US")` |
| `test_default_cache_keys` | 130 | with no arguments the lookup key is `("ip", "auto")` |
| `test_returns_stale_cache_on_fetch_error` | 142 | an exception from the fetch still returns the stale body |
| `test_caches_fetched_data` | 162 | a successful fetch writes a row carrying the postal code, country and body |
| `test_returns_none_on_complete_failure` | 180 | no cache and no fetch → `None` |
| `test_raises_if_not_initialized` | 194 | fetching before `initialize()` raises `RuntimeError` |
| `test_builds_url_with_query_string` | 200 | the raw query string is appended to the upstream URL |
| `test_returns_none_on_non_200` | 218 | a 404 upstream yields `None` |

The one that matters for the Integration is the last-but-one: it confirms **passthrough of
the raw query string**, which is what makes the NLE server schema-agnostic.

---

## 8. Consequences of each answering strategy

All of this section is **INFERENCE** built on the verified facts above, except where marked.
None of it has been observed on a Thermostat.

### 8.1 The Integration returns an error

**VERIFIED (NLE)** as to what the NLE server does: `routes/nest/weather.py:40-45` returns
HTTP **502** with the body `{"error": "Weather service unavailable"}` whenever the service
yields `None`. Today, with the upstream dead, that is its only outcome.

**INFERENCE** as to the Thermostat: this is benign. The NLE server has shipped in this state
and is in use, and the failure mode is a Route that always 502s. Corroborated by
`gboudreau/nest-api`'s comment that Nest's own weather API "will often return a '502 Bad
Gateway' or '503 Service Unavailable' response… meh" (`nest.class.php:162`) — flaky weather
was the normal condition on the real cloud, so the Firmware necessarily tolerates it.

### 8.2 The Integration does not answer at all

The concern is not the missing weather; it is the **socket**. If the Route is unregistered,
the Integration's `aiohttp` app returns 404, which is a fast, clean answer and behaves like
§8.1.

The risk case is a Route that **hangs**. Nothing establishes what the Firmware's client
timeout is, or whether its weather fetch shares a connection or a task with the transport
loop. A weather fetch that blocks for minutes is the one variant with any plausible route to
disturbing the subscribe cycle.

**Recommendation, not a decision:** always answer, and answer fast. 404, 502 and a minimal
JSON body are all cheap; never leave the Route unregistered on a path that could hang.

### 8.3 The Integration returns a minimal or static payload

Structurally safe: nothing in HVAC control, the bucket store, or the sync rules reads any of
it (§6.1, §6.2).

The costs are confined to display, and there are exactly two:

1. **A frozen outdoor temperature, or none.** Per §6.3, whichever branch is true, a static
   payload cannot produce a correct outdoor reading. If a Thermostat-reported
   `outdoor_temperature` field turns out to exist, a static payload would make it a constant
   — and worse than absent, because a constant looks live.
2. **Whatever a gen 1/gen 2 screen shows, frozen.** Unknown, possibly nothing (§6.4).

Note the schema drift between the two archived captures (§5.2): fields present in 2015 were
absent in 2017 and the Firmware carried on. **INFERENCE:** the Firmware's parser tolerates
missing fields. This is the main reason to think a minimal payload is safe, and it is the
strongest evidence available short of hardware.

### 8.4 The Integration never supplies a postal code

This is the failure mode that is easy to build by accident, because it needs no code to be
wrong — only code to be missing.

Per §3.1 the postal code and country originate in the `structure` bucket, which the
Integration owns and must create anyway (settled on #8, for `manual_eco_all`). If the
Integration creates that bucket without `postal_code` and `country_code`, the Thermostat has
no location.

What follows is **INFERENCE**, since the Firmware's behaviour here is unobserved. Two
plausible outcomes, and both are benign:

1. The Thermostat sends `?query=ipv4` — the documented "geolocate me from my source IP"
   token, verified live in both archived captures (§3.3). Against an Integration on the LAN
   this resolves to nothing useful, but the Integration is the one answering, so it can
   answer however it likes.
2. The Thermostat does not call `weather_url` at all, having nothing to ask about.

Either way HVAC control is unaffected (§6.1) and no bucket state changes (§6.2).

**The point for #11 is that this is a real decision, not a default.** Whichever weather
source is chosen, someone has to decide where the postal code comes from — a config-entry
field, HA's own `hass.config` latitude/longitude reverse-geocoded, or nothing at all. It
cannot be read off the Thermostat (§3.1). If #11 chooses a source that already knows the
location (an HA weather entity does), the postal code may still be needed purely to make the
Thermostat ask the question.

### 8.5 The Integration omits `weather_url` from `/entry`

**VERIFIED (REF).** The reference marks the field optional (line 448, "Required: No"), so
this is in-contract, not a hack.

**INFERENCE.** The Thermostat then never asks. This is the cleanest degenerate option — no
Route to serve, no payload to fake, no frozen value pretending to be live — and it is
strictly better than serving a static payload *if* the goal is to avoid a misleading
display.

The counter-consideration: it is a one-way door within a config entry. If a Thermostat
caches `weather_url` from a previous `/entry`, changing your mind means it may keep hitting
a Route you removed — which is why the NLE server's catch-all under `/nest/weather/`
(§4.2) is worth keeping regardless.

---

## 9. The minimum viable response

**The smallest payload consistent with every verified fact:**

```json
{"<query token>": {}}
```

That is: an object with exactly one key — the query token the Thermostat sent, echoed back
verbatim — whose value is an empty object.

The **wrapper is the only load-bearing part of the shape.** It is verified from two archived
live responses and from a client that indexes the response by the token
(python-nest v2.11.0 `nest/nest.py:982`). Everything inside it is verified-optional by the
schema drift between the 2015 and 2017 captures (§5.2).

**A safer minimum**, if you want the shape to look like weather rather than like a stub —
still tiny, and every key is verified-present in both captures:

```json
{
  "94304,US": {
    "current": {
      "temp_c": 20.0,
      "temp_f": 68.0,
      "humidity": 50,
      "condition": "Clear",
      "icon": "clear"
    },
    "location": {
      "zip": "94304",
      "city": "Palo Alto",
      "country": "US",
      "timezone_long": "America/Los_Angeles",
      "gmt_offset": "-08.00"
    }
  }
}
```

Notes on that payload:

- `temp_c` and `temp_f` must agree; the Firmware is not documented to convert (§5.2).
- `timezone_long` and `gmt_offset` are the only two fields a real client was seen to
  require, and it needed only one of the pair (python-nest `nest/nest.py:236-239`).
- `forecast` is omitted. Verified-absent from nothing — it was present in both captures — so
  omitting it is **inference**, resting on the drift argument. Include an empty
  `"forecast": {"daily": [], "hourly": []}` if you want to be conservative; it costs nothing.
- `sunrise` / `sunset` are omitted: no consumer was found in the reference or in the NLE
  server (§6.4).

**Echoing the token is not optional and not free.** The Integration must parse the `query`
parameter and use its literal value as the key. Do not use the parameter names the NLE
server reads (§4.3) — those are a bug.

---

## 10. Open questions

| # | Question | Blocks a build? | What would settle it |
|---|----------|-----------------|----------------------|
| 1 | How often does the Firmware poll `weather_url`? | No — a server does not care | Request log from a flashed Thermostat |
| 2 | Does a gen 1 / gen 2 Thermostat render weather on its own screen at all? | No | Observation, with and without `weather_url` |
| 3 | Does `outdoor_temperature` (or `outside_temperature`) exist as a Thermostat-reported bucket field? | No — §6.3 shows the answer does not change the cost of a static payload | A device-bucket PUT capture, or the 239-field registry |
| 4 | Does the device bucket carry a `postal_code` alongside the structure one, and is the country field named `country` or `country_code` there? | No — store-and-serve covers it either way | Same |
| 5 | What is the Firmware's client timeout on the weather fetch, and does a hang affect the subscribe cycle? | Only for §8.2 | Observation |
| 6 | Is the top-level key for a postal query the literal token, or a normalised form? | Mildly — echoing the token verbatim is the safe move either way | An archived `/weather/v1` capture with a postal-code query; only `?query=ipv4` captures were found |

None of these blocks the spec. Every one needs hardware, which the map places out of scope.
