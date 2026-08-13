# The Settings API and the discovery mechanics

Research for [#19](https://github.com/jtoniolo/nest-thermostat/issues/19). Input to
[#10](https://github.com/jtoniolo/nest-thermostat/issues/10), which chooses between the
mechanisms. This document gathers facts and costs. **It decides nothing.**

Terms are used exactly as `CONTEXT.md` defines them: **Thermostat**, **Firmware**,
**Integration**, **NLE server**, **Endpoint**, **Route**, **Bind address**,
**Advertised URL**, **Settings API**.

## Trust levels used below

| Grade | Meaning |
|---|---|
| **A — implementation** | Source code of the thing itself. The Firmware's own Settings API CGI, or Home Assistant core on disk. |
| **B — first-party client / docs** | Code or documentation written by the same project against its own API: the NLE installer, the NLE server, the NLE docs site. |
| **C — community** | Forum, issue-tracker or gist material. Corroborating only. |

Every claim below carries its grade. Nothing is asserted on grade C alone.

Sources, in the order they were consulted:

- `reference/PLAN.md` §7.5 (in-tree), `reference/scripts/00-preflight.sh`,
  `reference/scripts/10-verify.sh`.
- The NLE server clone at `reference/NoLongerEvil-SelfHosted/` — protocol reference only,
  read, never copied.
- **The Firmware's own Settings API source**, published in `codykociemba/NoLongerEvil-Thermostat`
  at `firmware/builder/deps/settings`. This is grade A and it settles most of the open
  questions below. Reading it is not a dependency on the Firmware; the Firmware remains out of
  scope per `README.md`. It is read here exactly as the protocol reference is read.
- Home Assistant core on disk at
  `/var/home/jeff/repo/homeassistant/renogy-ha/.venv/lib/python3.14/site-packages/homeassistant/`
  — **version 2026.5.4** (`homeassistant/const.py:18-22`). Only the `homeassistant/` package was
  read; nothing was taken from the `renogy-ha` fork's own code.
- The Home Assistant developer documentation.
- The IEEE MA-L registry.

---

## 1. The Settings API

### 1.1 What serves it

BusyBox `httpd`, started by an init script the Firmware installs as `/etc/init.d/nleapi`:

```
${STARTDAEMON} -q -b -p "${HTTPDPID}" -a "${HTTPDCLIENTAPP}" -- -f -v -p 8080 -h /var/www
```

— `codykociemba/NoLongerEvil-Thermostat`, `firmware/builder/deps/nleapi`, `monit_start` branch
(grade A).

Facts that follow directly:

- **Port 8080**, document root `/var/www`, so `/var/www/cgi-bin/…` is served at `/cgi-bin/…`.
- **No `-c` httpd.conf is passed.** BusyBox `httpd` therefore has no server-level `Basic`
  authentication and no `.htpasswd`. All authentication in the Settings API is done inside the
  CGI script, on the request body. This matters: the API is *not* protected by HTTP auth in any
  window (grade A, by absence).
- It is supervised by `monit` (`firmware/builder/deps/httpd.monitrc`) and started from `rcS`, so
  it is up from boot and restarted if it dies (grade A).

`reference/scripts/00-preflight.sh:64-73` scans port 8080 among others and, if it answers on a
*stock* unit, prints "That is unexpected and interesting" — i.e. the in-tree scripts already
treat an open 8080 as the flashed-Firmware signature.

### 1.2 Routes

Installed by `firmware/builder/scripts/build-nleapi.sh`, which stages `deps/settings`,
`deps/update` and `deps/version` (grade A). Their locations come from the paths in the
community installer that the Firmware later absorbed
([gist `bengalaviz/45655d36c9aa301d816846c6c134d82c`](https://gist.github.com/bengalaviz/45655d36c9aa301d816846c6c134d82c),
grade C, corroborated by the identical shipped files at grade A):

| Route | Method | Purpose |
|---|---|---|
| `/cgi-bin/api/settings` | `GET` | Read the Endpoint |
| `/cgi-bin/api/settings` | `POST` | Write the Endpoint; also hand out the credential |
| `/cgi-bin/version` | `GET` | Static text file. Currently `0.0.1` (`firmware/builder/deps/version`) |
| `/cgi-bin/update` | `POST` | Replaces the whole `cgi-bin/api` directory from a downloaded, MD5-checked zip |

**Path ambiguity resolved.** Some community material shows `/cgi-bin/settings` without the
`/api/` segment — for example the body of
[NoLongerEvil-Thermostat#112](https://github.com/codykociemba/NoLongerEvil-Thermostat/issues/112)
(grade C). That is wrong. Both the gist and the shipped Firmware install the script at
`${CGIBINDIR}/api/settings` = `/var/www/cgi-bin/api/settings`, and every first-party client uses
`/cgi-bin/api/settings`:
`firmware/installer/electron/nest-configure.js:14` (`const BASE_PATH = '/cgi-bin/api/settings';`),
`firmware/installer/electron/nest-discovery.js:12`, and the NLE server's own
`reference/NoLongerEvil-SelfHosted/src/nolongerevil/routes/control/scan.py:28,130`. The docs site
also uses `/cgi-bin/api/settings`
([docs.nolongerevil.com/self-hosted/troubleshooting](https://docs.nolongerevil.com/self-hosted/troubleshooting)).
**Use `/cgi-bin/api/settings`.** Note the `/cgi-bin/update` Route is *not* under `/api/`.

**`/cgi-bin/update` is a live remote-code path.** It downloads a zip from a caller-supplied URL,
verifies only an MD5 the same caller supplies, and unzips it over `cgi-bin/api`
(`firmware/builder/deps/settings`'s sibling `deps/update`, grade A). The Integration must never
call it. It is recorded here only because it explains why the Settings API can change shape
under us — see §1.8.

### 1.3 `GET /cgi-bin/api/settings`

No credential. No request body. From the shipped CGI (grade A):

```sh
elif [[ "$REQUEST_METHOD" == "GET" ]]; then
  if [[ -n $CURRENT_SCHEME && -n $CURRENT_SERVER ]]; then
    STATUS=`printf '{"cloudregisterurl":"%s"}' $CURRENT_URL`
    HTTP_RETURN_CODE="200"
  fi
fi
```

- **200** with body exactly `{"cloudregisterurl":"<url>"}`.
- Headers: `Content-Type: application/json`, `Content-Length`, `Connection: Close`,
  `X-API-VERSION: 0.0.1` (the `return_response` function, grade A).
- **400** with an empty body if `/etc/nestlabs/client.config` is missing or holds no
  `cloudregisterurl` (`HTTP_RETURN_CODE` and `STATUS` both stay unset and fall through to
  `return_response "" ""`).

**GET returns only that one field.** It does **not** return `device_name`, and it does not
return device info of any kind. Two first-party clients read a `device_name` off a GET response
anyway — `scan.py:46` (`"device_name": data.get("device_name")`). Against the shipped CGI that
is always `None`. Do not depend on it.

**GET is never authenticated, in any window.** There is no credential check on the GET branch and
no server-level auth (§1.1). This is the fact that makes a sweep viable regardless of §2.

### 1.4 `POST /cgi-bin/api/settings`

One Route, three request shapes, dispatched in this order by the shipped CGI (grade A):

**(a) Credential handout by name — no time limit.**

```sh
INITIALIZEID=$(… sed -n 's/.*"initialize":"\([^"]*\)".*/\1/p')
if [[ -n "$INITIALIZEID" ]]; then
  if [[ "$DEVICE_NAME" == "$INITIALIZEID" ]]; then
    HTTP_OUTPUT=`printf '{"api_key":"%s"}' "$API_KEY"`
    return_response "200" "$HTTP_OUTPUT"
  fi
fi
```

`DEVICE_NAME=$(hostname)`. Request `{"initialize":"<hostname>"}` → **200**
`{"api_key":"<secret>"}`. If the value does not equal the hostname the branch simply falls
through to the normal credential check. **There is no uptime check and no lockfile on this
branch** — it works for the life of the flash.

The first-party client documents the hostname as the device serial:
`nest-configure.js:31` — `@param {string} serial  - device hostname (from SSH \`hostname\` command)`
— and `nest-configure.js:9` summarises the whole API as:

```
 *   POST {"initialize":"<serial>"}                   -> {"api_key":"<secret>"}
 *   POST {"setup":"true"}                            -> {"api_key":"<secret>","device_name":"<serial>"}
 *                                                       (first-boot window only: within 30min, default URL, lockfile absent)
 *   POST {"api_key":"<k>","endpoint":"<ip:port>"}    -> {"status":"new","cloudregisterurl":"<url>"}
 *   GET  /cgi-bin/api/settings                       -> {"cloudregisterurl":"<url>"}
```

(grade B — a first-party client's own docstring, matching the grade-A CGI line for line.)

**(b) First-boot credential handout — the thirty-minute window.** See §2.

**(c) Write the Endpoint.** Requires the credential:

```sh
API_TOKEN=$(… sed -n 's/.*"api_key":"\([^"]*\)".*/\1/p')
if [[ "$API_TOKEN" != "$API_KEY" ]]; then
  HTTP_OUTPUT=`printf '{"status":"%s"}' "Invalid or Missing API Key."`
  return_response "401" "$HTTP_OUTPUT"
fi
NEW_URL=$(… sed -n 's/.*"endpoint":"\([^"]*\)".*/\1/p')
```

Request: `{"api_key":"<secret>","endpoint":"http://<ip>:<port>"}`.

Responses:

| Status | Body | When |
|---|---|---|
| 200 | `{"device_name":"<hostname>","status":"new","cloudregisterurl":"<endpoint>/entry"}` | Written |
| 401 | `{"status":"Invalid or Missing API Key."}` | `api_key` absent or wrong |
| 400 | `{"status":"Invalid IP Address/Port."}` | `endpoint` failed `valid_ip_port` |
| 400 | *(empty)* | Valid credential but no `endpoint` field at all |
| 400 | `{"status":"Target file does not exist. /etc/nestlabs/client.config"}` | Config file missing |

Note the asymmetry: the 400 for an invalid address still carries `HTTP_RETURN_CODE` unset, so the
*status line* is 400 while the body explains. Treat the JSON body as the error detail and the
status code as the class.

### 1.5 The credential

`API_KEY=$(cat /etc/nestlabs/apikey.txt)`. If that file is absent the CGI creates it from
`assigned_cred_secret` in `/media/user-config/settings.config`, falling back to the hostname if
that is also absent (grade A):

```sh
check_for_api_key() {
 if [[ -z "${API_KEY}" ]]; then
  local secret=$(grep 'assigned_cred_secret' ${CREDFILE} | busybox2 sed -n 's/.*value="\([^"]*\)".*/\1/p')
  if [[ -z "${secret}" ]]; then
    secret="${DEVICE_NAME}"
  fi
  …
```

`assigned_cred_secret` is **the same secret the Thermostat uses as its HTTP Basic password when
it talks to its Endpoint.** The NLE server states this explicitly and harvests it from inbound
traffic:

- `reference/NoLongerEvil-SelfHosted/src/nolongerevil/middleware/device_auth.py:34-40` —
  `get_device_api_key`: *"Return the cached api_key for a device (its Basic Auth password). This
  is the credential required as `api_key` when configuring the device via its local HTTP API
  (`POST /cgi-bin/api/settings`)."*
- `device_auth.py:71-78` — captured from the `Authorization` header on **every** request,
  before any other check, into a module-level dict.
- `reference/NoLongerEvil-SelfHosted/src/nolongerevil/lib/serial_parser.py:91-117` —
  `extract_basic_auth_password`, splitting on the first colon only.
- Surfaced to its dashboard at `routes/control/status.py:51`.

**Three ways to obtain the credential, in descending order of usefulness to the Integration:**

1. **Harvest it from the Thermostat's own traffic.** Once the Thermostat has spoken to us even
   once, we have it — it is the Basic-auth password on every request. This makes a *re-push* on a
   port change free, and it needs no user interaction at all. (grade A + B.)
2. **`POST {"initialize":"<serial>"}`** — works forever, needs only the serial. The serial is on
   the Thermostat's own Technical Info screen (`reference/scripts/00-preflight.sh:103-105` already
   tells the user to write it down) and is also the Basic-auth username
   (`serial_parser.py:34-73`).
3. **`POST {"setup":"true"}`** during the first-boot window (§2), or SSH
   (`cat /etc/nestlabs/apikey.txt`) outside it.

The Firmware compares the credential **exactly**, as a shell string. The NLE server uppercases
and strips it before sending — `scan.py:128`, `payload["api_key"] = str(api_key).upper().strip()`
— which happens to work because the secret is uppercase hex, but is not something to copy.

### 1.6 Endpoint vs `cloudregisterurl` — the `/entry` suffix

This is load-bearing and it reconciles a real conflict between the sources.

The shipped CGI **appends `/entry` itself** before writing (grade A):

```sh
NEW_SERVER="${NEW_URL#*://}"
if valid_ip_port "$NEW_SERVER"; then
  cp $TARGET_FILE $BACKUP_FILE
  NEW_URL="$NEW_URL/entry"
  ESCAPED_URL=$(printf '%s' "$NEW_URL" | busybox2 sed 's/[&|]/\\&/g')
  busybox2 sed -i "s|<a key=\"cloudregisterurl\" value=\"[^\"]*\"|<a key=\"cloudregisterurl\" value=\"${ESCAPED_URL}\"|g" $TARGET_FILE
```

So:

- **What you POST as `endpoint` is the base URL with no path.** In `CONTEXT.md` terms it is
  exactly the **Advertised URL**, and once written it is the Thermostat's **Endpoint**.
- **What GET returns as `cloudregisterurl` is that value with `/entry` appended** — the
  Endpoint plus the `/entry` **Route**. `cloudregisterurl` is therefore *not* the Endpoint;
  it is the Endpoint concatenated with one Route. Do not let the two blur.
- The value is stored in `/etc/nestlabs/client.config`, in an XML-ish
  `<a key="cloudregisterurl" value="…"/>` element, with the previous file copied to
  `client.config.old` first.

**If you POST a URL that already ends in `/entry` you get `…/entry/entry`.** The first-party
client strips it defensively — `nest-configure.js:35`,
`const endpoint = cloudregisterurl.replace(/\/entry$/, '');` (grade B). The NLE server sends its
bare origin, `scan.py:126`, `payload: dict = {"endpoint": settings.api_origin}` (grade B).

Consumers must strip the path back off when comparing. The NLE server does exactly that, and says
why — `scan.py:34-43`:

```python
cloud_url = data.get("cloudregisterurl", "")
# Device may append a path (e.g. /entry) to the URL it stores;
# compare by stripping any path so we match on origin only.
```

### 1.7 Validation rules and traps in the write path

All grade A, from `valid_ip_port` and the POST branch of the shipped CGI.

1. **The scheme is stripped for validation but kept in what is stored.** `NEW_SERVER` is
   everything after `://`. The scheme itself is never checked, so `https://` would be accepted
   and stored — and would then not work, because the Integration serves plain HTTP (settled in
   [#6](https://github.com/jtoniolo/nest-thermostat/issues/6)). Always send `http://`.
2. **A path in the `endpoint` silently breaks port validation.** With `endpoint`
   `http://10.0.0.5:9543/entry`, `NEW_SERVER` is `10.0.0.5:9543/entry`; the port regex
   `s/.*:\([0-9]\+\)$/\1/p` is anchored to end-of-string and fails to match, so `port` is empty
   and the port range check is skipped entirely. The octet check still passes, the write
   proceeds, and you end up with `…/entry/entry`. **Send an origin, never a path.**
3. **Hostnames are not properly rejected.** `valid_ip_port` splits on `.` and compares each part
   with `-gt 255`; a non-numeric part is not a clean rejection. Do not rely on the Firmware to
   reject a hostname. The Advertised URL must be a LAN IP anyway
   ([#6](https://github.com/jtoniolo/nest-thermostat/issues/6)), so send one.
4. **All spaces are removed from the request body before parsing:**
   `RAW_BODY="${RAW_BODY// /}"`. There is no JSON parser — fields are pulled out with `sed`
   regexes for `"key":"value"`. Consequences: send compact JSON, use double quotes, never allow a
   space inside a value, and never send a body in which the literal text `"endpoint":"` appears
   more than once (the regexes are greedy and take the last occurrence).
5. **`Content-Type` is ignored.** The CGI reads stdin. Sending
   `Content-Type: application/json` is polite and is what the first-party clients do
   (`nest-configure.js:44`), but it is not checked.
6. **Escaping.** Only `&` and `|` are escaped before the `sed -i`. A `"` in the value would
   corrupt `client.config`. Another reason to send only `http://<ipv4>:<port>`.
7. **The explicit port is our rule, not the Firmware's.** The Firmware happily accepts an origin
   with no port. Omitting it breaks the Thermostat's port extraction and therefore the WoWLAN
   keepalive — `reference/PLAN.md:264` and, independently, the NLE server's own
   `config/environment.py:156-167` (`api_origin_with_port`: *"URLs without explicit ports may
   cause the device to fail port extraction, breaking TCP keepalive offload (WoWLAN)"*).
   **The Integration must always send an explicit port.** Note the NLE server does not follow its
   own rule here: `scan.py:126` sends `api_origin`, not `api_origin_with_port`.

### 1.8 Versioning and drift

Every response carries `X-API-VERSION`, sourced from `/var/www/cgi-bin/version`, currently
`0.0.1` (`firmware/builder/deps/version`, grade A). `/cgi-bin/update` can replace the whole
`cgi-bin/api` directory at runtime. So the Settings API is a **versioned, field-replaceable**
surface, not a frozen one. Reading `X-API-VERSION` and logging it costs nothing and would be the
early warning if it ever moves.

---

## 2. The thirty-minute window

`reference/PLAN.md:325` says: *"That 8080 API **locks behind a password ~30 minutes after boot**.
Sequence the flow as reboot → sweep → push and you get an unlocked API and a fresh `/entry` from
one action."* The NLE docs site says the same in prose:

> **Password protection:** If the thermostat has been powered on for more than 30 minutes, the
> NLEAPI is protected by a password. To find the password, SSH into the thermostat and read
> `/etc/nestlabs/apikey.txt`

— [docs.nolongerevil.com/self-hosted/troubleshooting](https://docs.nolongerevil.com/self-hosted/troubleshooting)
(grade B).

**Both descriptions are wrong in a way that matters, and the plan's recommended sequence does not
work.** The shipped CGI is unambiguous (grade A):

```sh
UPTIME=$(awk '{print int($1)}' /proc/uptime)
IS_DEFAULT=$(echo "$CURRENT_URL" | grep -c "backdoor.nolongerevil.com")
SETUP_LOCK="$NEST_CONFIG_DIR/.setup_done"
…
  # First-boot setup window: unconfigured + booted within 30 minutes + not already used
  SETUP_REQUEST=$(printf '%s\n' "$RAW_BODY" | busybox2 sed -n 's/.*"setup":"\([^"]*\)".*/\1/p')
  if [[ "$SETUP_REQUEST" == "true" && "$IS_DEFAULT" -eq 1 && "$UPTIME" -lt 1800 && ! -f "$SETUP_LOCK" ]]; then
    log_writer "First-boot setup window active. Granting api_key."
    touch "$SETUP_LOCK"
    HTTP_OUTPUT=`printf '{"api_key":"%s","device_name":"%s"}' "$API_KEY" "$DEVICE_NAME"`
    return_response "200" "$HTTP_OUTPUT"
  fi
```

### What actually locks

Not the API. **The credential handout.** Specifically, the `{"setup":"true"}` branch, which is
the only path that gives out the `api_key` without already knowing something. It fires only when
**all four** conditions hold:

1. the body contains `"setup":"true"`;
2. the current `cloudregisterurl` contains `backdoor.nolongerevil.com` — i.e. the Thermostat is
   still on the Firmware's shipped default Endpoint and has never been pointed anywhere;
3. `/proc/uptime` is under **1800 seconds**;
4. `/etc/nestlabs/.setup_done` does not exist.

On success it **creates `.setup_done`**, so the branch is **one-shot for the lifetime of the
flash**, not per boot. `/etc` is persistent, so rebooting does not clear it. And condition 2 fails
permanently the moment any Endpoint is written.

### What this corrects

- **The API is not unauthenticated for the first thirty minutes.** `POST` with an `endpoint`
  requires `api_key` from the very first second after boot. There is no window in which you can
  write the Endpoint without the credential.
- **GET is unauthenticated forever.** Reading the Endpoint is never gated by the window, by the
  lockfile, or by anything else.
- **`reboot → sweep → push` does not re-open anything.** After the first use, or after the first
  Endpoint write, no reboot re-opens the setup window. `PLAN.md:325` should be treated as
  superseded by this section.
- **It is a one-shot handout, not an auth gate on a timer.** Calling it "a lock" invites the wrong
  design.

### What a config flow can and cannot do, by window

| Situation | Read the Endpoint (GET) | Obtain the credential | Write the Endpoint |
|---|---|---|---|
| Freshly flashed, < 30 min uptime, never configured, `.setup_done` absent | Yes | Yes — `{"setup":"true"}`, returns `api_key` **and** the serial as `device_name` | Yes |
| Any time, serial known | Yes | Yes — `{"initialize":"<serial>"}` | Yes |
| Any time, the Thermostat has already talked to us | Yes | Yes — it is the Basic-auth password we already captured | Yes |
| Past the window, serial unknown, never talked to us | Yes | **No** — only SSH (`root` / `nolongerevil`, `cat /etc/nestlabs/apikey.txt`) | No |

The last row is the only genuinely blocked case, and it is escaped by asking the user for the
serial, which is printed on the Thermostat's own Technical Info screen. **The design consequence
for [#10](https://github.com/jtoniolo/nest-thermostat/issues/10): a config-flow step that asks for
the serial removes the entire dependency on the thirty-minute window and on SSH.** The window is
then a convenience that saves one form field on a fresh flash, not a mechanism the flow must be
sequenced around.

The first-party client agrees on the shape: `configureNest()` (`nest-configure.js:37-68`) uses
`initialize` as its primary path and `configureViaSetupWindow()` (`:83-118`) as the fallback
"when SSH is unavailable" — the reverse of what `PLAN.md` assumes.

---

## 3. Does an Endpoint change need a reboot?

**No.** The CGI restarts the Nest client service itself, ten seconds after answering
(grade A, shipped CGI):

```sh
sleep 10 && /etc/init.d/nestlabs restart &
```

That is a **service restart, not a device reboot**, and it is automatic. Nothing the caller does
triggers it and nothing the user does is required.

This contradicts the NLE docs, which say plainly *"After saving, reboot the thermostat."*
([troubleshooting](https://docs.nolongerevil.com/self-hosted/troubleshooting), grade B) and
`reference/PLAN.md:326`, which records the question as open.

**A reboot is still worth asking for, but for a different reason.** The Thermostat only sends its
**complete** state on a fresh boot; otherwise it sends deltas and the server never gets a full
picture. The NLE server's README says so twice:

> The thermostat only sends its complete state during a fresh boot. If your thermostat was
> previously connected to another server (or Nest's cloud), it will only send small updates and
> the server won't have a full picture of the device.

— `reference/NoLongerEvil-SelfHosted/README.md:64` and `:97` (grade B). `reference/scripts/10-verify.sh:32`
carries the same operational advice: *"If that is empty, reboot the thermostat: hold the display
for 10 seconds."*

So the distinction #10 needs:

- **For the Endpoint change to take effect** — no user action. Wait ~10 s plus the service
  restart, then wait for `/entry`.
- **For a complete initial state snapshot** — a reboot, once, at onboarding. This is a
  state-model concern ([#8](https://github.com/jtoniolo/nest-thermostat/issues/8)), not an
  addressing concern.

### Confirming success

Three signals, strongest last:

1. **The POST response.** `status` is the string `"new"`, and `cloudregisterurl` echoes the value
   written. The first-party client asserts exactly this: `nest-configure.js:61`,
   `if (updateData.status !== 'new') throw …`.
2. **Read back.** `GET` and string-compare `cloudregisterurl` against
   `<what you sent> + "/entry"`. `nest-configure.js:65-70` does this and treats a mismatch as
   failure. Cheap and immediate.
3. **Wait for `/entry` on our own port.** The Thermostat is the client, so the arrival of a
   `/entry` request from its IP is the only proof the whole path works — Advertised URL correct,
   Bind address reachable, service restarted. `reference/PLAN.md:321` proposes a ~60 s timeout.
   Given the CGI's own 10 s delay before the restart, a timeout materially under ~30 s would
   produce false failures.

---

## 4. Discovery mechanics

### 4.1 Subnet sweep of the Settings API

**What it is.** Probe every host address on the local network for something answering
`GET /cgi-bin/api/settings` on port 8080.

**Prior art, both grade B.**

*The NLE server*, `reference/NoLongerEvil-SelfHosted/src/nolongerevil/routes/control/scan.py`:

- `:83` — `network = ipaddress.IPv4Network(f"{host_ip}/24", strict=False)`. **Hard-coded /24.**
  The subnet is derived from `settings.api_origin`'s hostname, resolving it via
  `socket.gethostbyname` if it is not already an IP (`:71-82`).
- `:93-94` — `aiohttp.TCPConnector(limit=0)` and `ClientTimeout(connect=2, total=4)`. The comment
  at `:90-92` explains `limit=0`: it removes pool queuing so the connect timeout applies to the
  handshake and not to waiting for a pool slot.
- `:96-97` — all 254 probes fanned out at once via `asyncio.gather`.
- `:30-49` — a hit is `status == 200` and the body is parsed with `json(content_type=None)`;
  `configured` is computed by comparing scheme and netloc only.
- **No OUI filter, no ARP lookup, no mDNS.** Confirmed by reading the whole file.

*The NLE installer*, `firmware/installer/electron/nest-discovery.js` + `net-utils.js`, which is
more refined:

- Two phases. First a raw TCP connect probe to port 8080 with an **800 ms** timeout across all
  254 hosts (`nest-discovery.js:32`, `net-utils.js:21-40`, using `socket.destroy()` rather than
  `end()` to avoid waiting for FIN). Then an HTTP confirm on the hits only, 2 s timeout
  (`nest-discovery.js:12-21`).
- The confirmation predicate is `'cloudregisterurl' in data` (`:19`) — not a status check, a
  shape check. Stronger than the NLE server's.
- Also hard-coded /24: `net-utils.js:9-14` takes the first non-internal IPv4 address and keeps
  `parts.slice(0, 3)`, defaulting to `192.168.1` if none is found.
- Retry policy for a just-flashed unit: 45 s boot delay, re-scan every 10 s, give up at 3 minutes,
  then *"Please enter the IP address manually."* (`:3-5`, `:105-107`).

**CAN**

- Find the Thermostat with no user input at all on a flat /24, in about a second.
- Distinguish "something is on 8080" from "this is a flashed Thermostat" via the response shape.
- Tell you, in the same request, **where it is currently pointed** — so the flow can say
  "already configured", "pointed at the NLE server", or "still on the default
  `backdoor.nolongerevil.com`".
- Run at any time. GET is never gated (§1.3, §2).

**CANNOT**

- Cross a subnet, a VLAN, or client isolation. Silent failure, not an error.
- Tell you which Thermostat it is if there are several — the GET carries no identity. You must
  POST `initialize` (needing the serial) or wait for a `/entry` to learn a serial.
- Prove the device is a Nest. Any host serving that JSON on 8080 is indistinguishable. §4.2
  addresses this.
- Be assumed cheap on a large prefix. See below.

**COST, and what changes on a prefix that is not /24**

Both prior-art implementations assume /24. Home Assistant does not have to: `Adapter["ipv4"]` is a
list of `IPv4ConfiguredAddress`, which carries a real `network_prefix: int` —
`homeassistant/components/network/models.py:17-21` and `:24-35`, reached via
`await network.async_get_adapters(hass)` (`homeassistant/components/network/__init__.py:43-46`).
Ticket [#4](https://github.com/jtoniolo/nest-thermostat/issues/4) already found this. So the
Integration can and should compute the real host count instead of assuming 254.

Host count is `2**(32 - prefix) - 2`:

| Prefix | Hosts | Wall clock at 256-way concurrency, 800 ms timeout | Notes |
|---|---|---|---|
| /25 | 126 | ~0.8 s | one batch |
| /24 | 254 | ~0.8 s | one batch — the assumed case |
| /23 | 510 | ~1.6 s | two batches |
| /22 | 1 022 | ~3.2 s | four batches |
| /21 | 2 046 | ~6.4 s | |
| /20 | 4 094 | ~13 s | |
| /16 | 65 534 | **~3.5 min** | not viable in a config-flow step |

Wall clock is `ceil(hosts / concurrency) * timeout` in the worst case, where every address is
dead. Three cost drivers make a naive full fan-out worse than that arithmetic on a large prefix:

1. **File descriptors.** One socket per concurrent probe. The NLE server's `limit=0` fan-out of
   254 is fine; a fan-out of 65 534 is not. The exact ceiling is the process's `RLIMIT_NOFILE`,
   which varies by HA installation method — **I did not establish HA's actual soft limit** and it
   should not be assumed.
2. **The ARP/neighbour table.** Every probe to a non-existent host on the local segment forces an
   ARP resolution that must time out. Linux's neighbour table is garbage-collected against
   `net.ipv4.neigh.default.gc_thresh3`; overflowing it produces `neighbour table overflow` and
   degrades the *whole host's* networking, not just the sweep. This is a general property of
   Linux neighbour handling, not something I verified against a specific default on this machine.
3. **The event loop.** Even at `async` speed, tens of thousands of tasks is a real scheduling
   load inside a config-flow step that the user is watching.

**Mitigations that follow:** bound the concurrency with a semaphore rather than fanning out
`limit=0`; refuse or warn above some prefix width; and always offer manual entry
(§4.5). Note also that a /16 sweep touches 65 534 addresses that are probably not the user's — a
politeness and, on some networks, a security-monitoring problem.

### 4.2 Nest MAC OUI confirmation

**What it is.** After a sweep hit, look up the responder's MAC (from the local ARP/neighbour
table) and check the OUI. Turns "something answered" into "that is a Nest".

**The OUIs.** Fetched directly from the IEEE MA-L registry at
`https://standards-oui.ieee.org/oui/oui.csv` — **HTTP 200, 3 813 389 bytes, 39 928 records**
(grade A, primary registry, not a mirror). Exactly two records match `Nest Labs`:

```
MA-L,18B430,Nest Labs Inc.,3400 Hillview Ave. Palo Alto CA US 94304
MA-L,641666,Nest Labs Inc.,3400 Hillview Ave. Palo Alto CA US 94304
```

- **`18:B4:30`** and **`64:16:66`**. No other registrant string containing "Nest" is a thermostat
  vendor (the near-misses are Nestar, Nestlé Purina, Kinestral, and several "Honest" companies).
- The gen 1 and gen 2 units in scope date from 2011 and 2012, so **`18:B4:30` is the expected
  one**. Match both anyway; it costs one extra matcher.
- `reference/PLAN.md:315` names `18:B4:30` and is correct as far as it goes; it omits `64:16:66`.
- **`oui.csv` carries no registration dates**, so I did not verify the 2010-12-06 / 2017-03-29
  dates that circulate for these two blocks. The date claim is not needed for anything.
- **MA-M and MA-S were not checked** — `https://standards-oui.ieee.org/oui28/mam.csv` and
  `.../oui36/oui36.csv` both returned **HTTP 418**. A Nest MA-M/MA-S assignment is very unlikely
  for a 2011 consumer device (those registries serve small-volume vendors and did not exist in
  their current form then), but it is not ruled out. Retrying those two URLs, or a registry search
  at `regauth.standards.ieee.org`, would establish it.
- **Whether the WiFi MAC actually carries the Nest OUI rather than the WiFi chipset vendor's**
  is not established here. It is the normal arrangement — that is what an OUI assignment is for
  — and `PLAN.md` assumes it, but I found no primary confirmation for this model. An `arp -n`
  against a real unit settles it in one command; `reference/scripts/00-preflight.sh:82-84` already
  captures exactly that.
- The 802.15.4 radio (Ember EM357) is irrelevant: it was never enabled
  (`reference/PLAN.md`, §8, "The 802.15.4 radio").

**CAN**

- Remove false positives from a sweep at essentially zero cost, using the ARP entry that the
  sweep's own TCP handshake has just populated.
- Give a **stable unique ID candidate** that is not the IP — see §5.3.

**CANNOT**

- Discover anything by itself. It is a filter on a sweep, never a mechanism.
- Work across a router. ARP is link-local; a Thermostat on another subnet has no ARP entry on the
  HA host.
- Be read portably. There is no HA helper for "read the ARP table"; it means parsing
  `/proc/net/arp`, shelling out to `ip neigh`, or adding a dependency. Inside a container the
  table is the container's, which — on HA OS with host networking — is the host's, but this is
  environment-dependent and I did not verify it for each HA install method.

**COST.** Near zero for the lookup. The real cost is the platform-specific code to read the
neighbour table, and the fact that it silently returns nothing in some deployments.

### 4.3 Home Assistant DHCP matcher

**How it is declared.** A `dhcp` key in `manifest.json`, a list of matcher dicts. From
[the manifest docs](https://developers.home-assistant.io/docs/creating_integration_manifest):

> We support passively listening for DHCP discovery by the hostname and OUI, or matching device
> registry mac address when `registered_devices` is set to true. The manifest value is a list of
> matcher dictionaries, your integration is discovered if all items of any of the specified
> matchers are found in the DHCP data. Unix filename pattern matching is used for matching. It's
> up to your config flow to filter out duplicates.

So: **items within one matcher are ANDed, matchers are ORed.** Keys are `hostname`, `macaddress`,
`registered_devices`.

**How it actually behaves in core 2026.5.4** — and this differs from the documentation in one
important way. All of the following is from
`homeassistant/components/dhcp/__init__.py`:

- `:91-99` — matchers are indexed at setup. A matcher containing `registered_devices`
  short-circuits (`:93-95`) and **any `macaddress`/`hostname` in the same dict is ignored**. A
  matcher with `macaddress` is filed under `mac_address[:6]` (`:98`). Only a matcher with neither
  falls through to the hostname index, keyed on `hostname[0].lower()` (`:101-103`).
- `:242` — at match time the lookup key is `oui = uppercase_mac[:6]`.
- `:246-256` — for each candidate matcher, **only `hostname` is fnmatch'd**
  (`_memorized_fnmatch`, defined `:480-491`). **`macaddress` is never fnmatch'd.** It is matched
  solely by the six-character index key.

Consequences that a build session must not get wrong:

1. `{"macaddress": "18B430*"}` works, and the `*` is decorative — the match is on the first six
   characters regardless.
2. A wildcard **inside** the first six characters (`"18B4*"`) would be filed under the literal
   string `18B4*` and could never be looked up. Silent, total failure.
3. `macaddress` must be **uppercase, no separators** — the index is built from the manifest string
   verbatim (`:98`) and looked up with `uppercase_mac[:6]` (`:219`, `:242`).
4. The same trap exists for hostname: a pattern starting with a wildcard (`"*nest*"`) is filed
   under `*` and never matched.

`DhcpServiceInfo` — `homeassistant/helpers/service_info/dhcp.py` — carries exactly three fields:
`ip: str`, `hostname: str`, `macaddress: str`, with the docstring:

> Please note that for historical reason the DHCP service will always format it as a lowercase
> string without colons. eg. "AA:BB:CC:12:34:56" is stored as "aabbcc123456"

Constructed at `dhcp/__init__.py:269-273`; `hostname` is lowercased (`:218`, `:271`). The flow is
dispatched to `async_step_dhcp` via `discovery_flow.async_create_flow(..., {"source": SOURCE_DHCP}, ...)`
at `:279-286`.

**Three independent triggers, not one.** This settles the lease-renewal question that the
documentation does not answer. All are set up in `async_setup`, `dhcp/__init__.py:112-153`, and
all funnel into the same `WatcherBase.async_process_client` (`:176-286`):

1. **`DHCPWatcher`** (`:403-439`) — genuine passive packet sniffing, delegated to
   `aiodhcpwatcher==1.2.1` (`dhcp/manifest.json`). Its scapy filter is `"udp and (port 67 or 68)"`
   and it acts **only on `message-type == 3`, i.e. DHCPREQUEST** (`aiodhcpwatcher/__init__.py:20`,
   `:21`, `:58-59`, read from `bdraco/aiodhcpwatcher` — grade A for that library, but it is **not
   installed in the venv on this machine**, so this is read from the published source, not from
   disk). A DHCPREQUEST is sent both on a new lease and on a renewal, so this path *does* fire on
   renewal — but only if HA can see the packet, which needs the same L2 segment and a functional
   packet filter (it logs *"Cannot watch for dhcp packets without a functional packet filter"* and
   gives up, `aiodhcpwatcher/__init__.py:159-162`).
2. **`NetworkWatcher`** (`:289-339`) — an **active** sweep using `aiodiscover==2.7.1`, run at
   startup and then every `SCAN_INTERVAL = timedelta(minutes=60)` (`:71`, `:311-320`). It feeds
   IP/hostname/MAC triples into the same matcher path. **This is the answer to the lease
   question:** a Thermostat that never renews, and whose DHCPREQUEST HA never sees, is still
   picked up within an hour by this active sweep — provided `aiodiscover` can see it.
3. **`DeviceTrackerWatcher`** / **`DeviceTrackerRegisteredWatcher`** (`:342-400`) — anything a
   router integration reports as a `device_tracker` with `source_type == router`,
   `state == home`, and both `ip` and `mac` attributes.

There is also `RediscoveryWatcher` (`:442-471`): removing the config entry re-fires discovery for
the same MAC from cached address data, so a user who deletes and re-adds gets the card back
immediately.

**CAN**

- Give a free "Nest thermostat discovered — configure?" card with **one line of manifest**, no
  code beyond `async_step_dhcp`.
- Fire on a device that has been sitting on the network for months, via `NetworkWatcher`'s hourly
  active sweep, not only on a lease event.
- Supply the MAC, which is the best available stable unique ID (§5.3).
- Be a good citizen: `registered_devices: true` in a second matcher gets us an IP-change
  notification for a Thermostat we have already adopted, without broadening the OUI match.

**CANNOT**

- **Match on hostname.** The DHCP hostname the Thermostat sends is **not documented anywhere I
  could find**, and establishing it requires a packet capture of real hardware — which the map
  forbids as a blocker. This is a bounded constraint, not an open question: **the matcher must be
  built on `macaddress` against `18B430` and `641666` only.** If someone later captures a real
  unit, a hostname matcher can be added; nothing else changes.
- Be relied on as *the* mechanism. All three triggers can be silently unavailable: no packet
  filter, no router integration, `aiodiscover` blocked. `reference/PLAN.md:316` already calls it
  *"a bonus, not the mechanism"*, and that judgement survives everything found here.
- Tell us the Endpoint. It gives an IP; the sweep's GET is still what tells us where the
  Thermostat is pointed.
- Complete setup on its own. See §5.4.

**COST.** Two matcher dicts in `manifest.json` and an `async_step_dhcp` that sets the unique ID
and shows a confirm form. The `dhcp` integration itself is loaded by default in a standard HA
install; a `dependencies` entry is not needed, only the `dhcp` manifest key.

### 4.4 No mDNS / zeroconf

`reference/PLAN.md:318-319` states the Thermostat advertises nothing over mDNS, and reasons that
adding an Avahi service file would not survive a reflash and probably would not be woken by the
WoWLAN pattern set anyway.

**I could not independently confirm the negative from a primary source.** What I can report:

- The Firmware's published build tree (`codykociemba/NoLongerEvil-Thermostat`, 94 paths) contains
  **no** avahi, mdns, zeroconf or bonjour file, and the only network service it adds is the
  BusyBox `httpd` on 8080 (`firmware/builder/deps/nleapi`). That is grade A but weak evidence:
  the base rootfs is Google's and is not in this repo.
- **No first-party client uses mDNS to find the Thermostat.** Both the NLE installer
  (`nest-discovery.js`, a raw port sweep) and the NLE server (`scan.py`, an HTTP sweep) do a
  subnet sweep instead. If an mDNS record existed, neither would be written this way. That is
  strong circumstantial evidence at grade B.

**Recommendation for #10: treat zeroconf as unavailable.** A five-second `avahi-browse -at` on the
LAN with a flashed unit present would settle it definitively, and costs nothing once hardware
exists.

### 4.5 Manual entry

**What it is.** A form field for the Thermostat's IP address, and — per §2 — a field for its
serial.

**CAN**

- Work on a segmented network, across VLANs, with client isolation on, and where every automatic
  mechanism is silently dead.
- Escape every failure mode above. It has no preconditions beyond IP reachability, which the
  Integration needs anyway for the Advertised URL to work at all.
- Carry the serial, which unlocks the `initialize` credential path and therefore removes the
  thirty-minute window from the critical path entirely.

**CANNOT**

- Be discovery. The user must find the IP themselves, from the router's DHCP table or the
  Thermostat's own network screen.

**COST.** One step in the config flow. Both prior-art implementations fall back to it and say so
in their own error text — `nest-discovery.js:106`, *"Could not find Nest on the network after 3
minutes. Please enter the IP address manually."*

`reference/PLAN.md:317` is unambiguous: *"Always offer it. Sweeps fail on segmented networks."*

### 4.6 Side by side

| | Finds the device | Confirms it is a Nest | Reads the Endpoint | Works off-subnet | Needs user input | Cost |
|---|---|---|---|---|---|---|
| Sweep :8080 | Yes, on-subnet | Shape of the response only | **Yes** | No | None | Seconds on /24; unusable at /16 |
| MAC OUI | No — a filter | **Yes** | No | No | None | Platform-specific ARP read |
| DHCP matcher | Opportunistically | **Yes**, by OUI | No | Depends on the trigger | Confirmation only | Two manifest lines |
| Manual entry | Yes | No | Yes, once you have the IP | **Yes** | IP (+ serial) | One form step |

They are complementary, not alternatives. Note that only the sweep and manual entry read the
Endpoint, and only the DHCP matcher and the OUI check confirm the vendor.

---

## 5. Home Assistant config-flow and options-flow practice

Everything in this section was read from core on disk at **2026.5.4**
(`homeassistant/const.py:18-22`: `MAJOR_VERSION = 2026`, `MINOR_VERSION = 5`,
`PATCH_VERSION = "4"`). Paths are relative to
`/var/home/jeff/repo/homeassistant/renogy-ha/.venv/lib/python3.14/site-packages/homeassistant/`.
Nothing was read from the `renogy-ha` fork's own code.

### 5.1 Config flow shape

- `class ConfigFlow(ConfigEntryBaseFlow)` — `config_entries.py:2963`. Declared as
  `class NestLocalConfigFlow(ConfigFlow, domain=DOMAIN)`.
- `async_show_form(...)` — `config_entries.py:3505`.
- `async_create_entry(...)` — `config_entries.py:3354` (the `ConfigFlow` override; note
  `data_entry_flow` has its own at a different signature).
- `async_abort(...)` — `config_entries.py:3329`.
- Errors are a `dict[str, str]` passed to `async_show_form`; `"base"` for form-wide errors, a
  field name for field-specific ones.

### 5.2 Unique ID

- `async_set_unique_id(...)` — `config_entries.py:3112`.
- `_abort_if_unique_id_configured(updates=None, reload_on_update=True, *, error="already_configured", …)`
  — `config_entries.py:3063`. Its docstring: *"Requires strings.json entry corresponding to the
  `error` parameter in user visible flows."*
- `_abort_if_unique_id_mismatch(*, reason="unique_id_mismatch", …)` — `config_entries.py:3042`.
  It fires only under `SOURCE_REAUTH` or `SOURCE_RECONFIGURE`.

The developer docs list **unacceptable** unique-ID sources verbatim:

> Unacceptable sources for a unique ID: IP Address · Device Name · Hostname if it can be changed
> by the user · URL

([config flow docs](https://developers.home-assistant.io/docs/config_entries_config_flow_handler))

So the unique ID must be the Thermostat's **serial** — which is also its Basic-auth username
(`serial_parser.py:34-73`), its `hostname` for the `initialize` call, and what the setup window
returns as `device_name` — or its **MAC**. If a MAC is used it must be normalised with
`homeassistant.helpers.device_registry.format_mac` (`helpers/device_registry.py:282-299`), which
returns the lowercase colon-separated form. Note the mismatch to watch: `format_mac` produces
`aa:bb:cc:11:22:33`, while `DhcpServiceInfo.macaddress` arrives as `aabbcc112233`.

### 5.3 Options flow, and `OptionsFlowWithReload`

`OptionsFlowWithReload` **exists in core on disk** — `config_entries.py:3955-3964`:

```python
class OptionsFlowWithReload(OptionsFlow):
    """Automatic reloading class for config options flows.

    Triggers an automatic reload of the config entry when the flow ends with
    calling `async_create_entry` with changed options.
    It's not allowed to use this class if the integration uses config entry
    update listeners.
    """

    automatic_reload: bool = True
```

That last sentence is **enforced at runtime**, not merely advised —
`config_entries.py:3850-3865`:

```python
automatic_reload = False
if isinstance(flow, OptionsFlowWithReload):
    automatic_reload = flow.automatic_reload

if automatic_reload and entry.update_listeners:
    raise ValueError(
        "Config entry update listeners should not be used with OptionsFlowWithReload"
    )

if (
    self.hass.config_entries.async_update_entry(entry, options=result["data"])
    and automatic_reload is True
):
    self.hass.config_entries.async_schedule_reload(entry.entry_id)
```

Two details worth carrying forward: the reload is scheduled **only if `async_update_entry`
actually changed something**, so a no-op save does not bounce the socket; and the two patterns are
**mutually exclusive** — picking one forecloses the other.

The docs confirm the intent:

> If the integration should be reloaded after the config options change, it can subclass from
> `OptionsFlowWithReload` instead of `OptionsFlow`. `OptionsFlowWithReload` will automatically
> reload the integration once the options change. Since the most common reason to add an update
> listener is to reload the integration when the options have changed, `OptionsFlowWithReload`
> avoids the need for that listener.

([options flow docs](https://developers.home-assistant.io/docs/config_entries_options_flow_handler))

**This supersedes what [#4](https://github.com/jtoniolo/nest-thermostat/issues/4) recorded** —
that the pattern to copy is `homekit`'s manual update listener. For us, `OptionsFlowWithReload`
replaces the listener. But be clear about what is and is not true of core's own example:
**`homekit` has not migrated.** It still registers the listener by hand —
`components/homekit/__init__.py:384`:

```python
entry.async_on_unload(entry.add_update_listener(_async_update_listener))
```

with `_async_update_listener` at `:402-408` calling
`await hass.config_entries.async_reload(entry.entry_id)`; and its options flow is a plain
`OptionsFlow` (`components/homekit/config_flow.py:361-368` returns it;
`class OptionsFlowHandler(OptionsFlow)` at `:370`). `emulated_hue` has no config entry
at all — it is YAML-configured, and its `AppRunner`/`TCPSite` lifecycle at
`components/emulated_hue/__init__.py:105-108` is all it contributes. So both patterns are live and
correct; `OptionsFlowWithReload` is the current one, and #4's finding is a description of older
core code rather than of current guidance.

Other options-flow facts:

- `OptionsFlow.config_entry` is a **base-class property** — `config_entries.py:3919-3929`. Do
  **not** assign `self.config_entry = config_entry` in `__init__`. The property raises if touched
  during `__init__`.
- `async_get_options_flow(config_entry)` is a `@staticmethod @callback` on the config flow —
  `config_entries.py:2982`; the docs' snippet takes no arguments when constructing the handler.
- `OptionsFlowWithConfigEntry` (`config_entries.py:3931`) is explicitly *"being phased out, and
  should not be referenced in new code."* Do not use it.
- The first step of an options flow is always `async_step_init`.

### 5.4 Reconfigure flow — which flow owns which field

The docs draw the line explicitly:

> A config entry can allow reconfiguration by adding a reconfigure step. This provides a way for
> integrations to allow users to change config entry data without the need to implement an
> `OptionsFlow` for changing setup data which is not meant to be optional.

and, again:

> To allow the user to change config entry data which is not optional (`OptionsFlow`) and not
> directly related to authentication, for example a changed host name, integrations should
> implement the reconfigure step.

([config flow docs](https://developers.home-assistant.io/docs/config_entries_config_flow_handler))

The documented pattern is `async_step_reconfigure`, then
`await self.async_set_unique_id(...)`, then `self._abort_if_unique_id_mismatch()`, then
`return self.async_update_reload_and_abort(self._get_reconfigure_entry(), data_updates=data)`.
Verified in core:

- `SOURCE_RECONFIGURE` — `config_entries.py:131`; the handler is detected by
  `hasattr(handler, "async_step_reconfigure")` at `:609`.
- `_get_reconfigure_entry()` — `config_entries.py:3557`, raising `ValueError` if the source is
  not `SOURCE_RECONFIGURE` (`:3552-3553`).
- `async_update_reload_and_abort(entry, *, unique_id, title, data, data_updates, options, reason, reload_even_if_entry_is_unchanged=True)`
  — `config_entries.py:3458-3501`. It updates, then `async_schedule_reload`, then aborts with
  `reconfigure_successful`.

**Applied to our three fields**, using the docs' own test — "setup data which is not meant to be
optional" versus "mutable runtime preferences":

| Field | Nature | Belongs in |
|---|---|---|
| **Bind address** | Connection parameter. Changing it re-binds the socket. | `entry.data` → reconfigure |
| **Bind port** | Connection parameter. Changing it re-binds *and* invalidates the Endpoint on the Thermostat. | `entry.data` → reconfigure |
| **Advertised URL** | Connection parameter. It is literally the address the peer is told to dial. | `entry.data` → reconfigure |
| Thermostat IP | Connection parameter, and it can change on a DHCP lease. | `entry.data`, updated by discovery |
| Anything genuinely preferential (poll cadences, entity toggles) | Runtime preference | `entry.options` → options flow |

Core corroborates: `homekit` keeps its port in `entry.data`, not in options —
`components/homekit/__init__.py:422` reads `entry.data[CONF_PORT]`, and
`components/homekit/config_flow.py:355-358` de-duplicates on `entry.data[CONF_PORT]`.

**Consequence for [#10](https://github.com/jtoniolo/nest-thermostat/issues/10):** the ticket's
bullet about "what the options handler must re-push" is aimed at the wrong flow. Re-pushing the
Endpoint after a port change belongs in `async_step_reconfigure`, and the reload is then handled by
`async_update_reload_and_abort` rather than by `OptionsFlowWithReload`. If, after that
reclassification, no genuinely optional setting remains, the Integration may need **no options
flow at all**. That is #10's call, not mine.

### 5.5 A discovery step must never silently create an entry

Verbatim from the developer documentation:

> Invoking a discovery step should never result in a finished flow and a config entry. Always
> confirm with the user.

([config flow docs](https://developers.home-assistant.io/docs/config_entries_config_flow_handler),
in the "Discovery steps" section, alongside the requirement to check for in-progress duplicate
flows and to make sure the device is not already set up.)

**It is a documented convention, not a hard runtime rule.** I looked for enforcement in
`config_entries.py` and `data_entry_flow.py` and found none: nothing prevents an
`async_step_dhcp` from returning `async_create_entry` directly. It is checked by human review and
by the quality-scale process, not by the framework.

This constrains **[#10](https://github.com/jtoniolo/nest-thermostat/issues/10)** — a DHCP
discovery must land on a confirm form, never on a finished entry — and it constrains
**[#16](https://github.com/jtoniolo/nest-thermostat/issues/16)**, which asks whether an
unrecognised Thermostat is adopted silently. Per this rule, in the config-flow direction it must
not be. (Whether a *protocol-level* first contact from an unknown serial is accepted by the
running server is a different question and is not governed by this rule.)

### 5.6 Deciding the Advertised URL and the Bind port

- `async_get_source_ip(hass, target_ip=UNDEFINED)` lives in
  **`homeassistant/components/network/__init__.py:56-86`** — *not* in `helpers/network.py`. It
  gathers every enabled adapter's IPv4 addresses, probes for a source IP against
  `PUBLIC_TARGET_IP` then `MDNS_TARGET_IP` then `LOOPBACK_TARGET_IP`, and — importantly —
  **falls back to `all_ipv4s[0]` if the probed address is not among the configured ones**
  (`:86`). It raises `HomeAssistantError` only when there are no enabled IPv4 addresses *and* the
  socket trick fails.
- `async_get_adapters(hass)` — `components/network/__init__.py:43-46`, returning
  `list[Adapter]`. `Adapter` is a `TypedDict` with `name`, `index`, `enabled`, `auto`, `default`,
  `ipv6`, `ipv4` — `components/network/models.py:24-35`. Each `IPv4ConfiguredAddress` is
  `{address: str, network_prefix: int}` — `models.py:17-21`. **This is where the real subnet mask
  for §4.1 comes from.**
- Picking a free port: `homekit` has a worked pattern —
  `components/homekit/util.py:626-635` (`async_port_is_available`, a `SO_REUSEADDR` bind test) and
  `:638-664` (`async_find_next_available_port`, walking up from a start port while excluding ports
  already claimed by other config entries of the same domain). `PLAN.md:305-307` independently
  reaches the same design and adds the rule that matters: **persist the chosen port in the config
  entry; never bind port 0**, or the Endpoint on the Thermostat is orphaned on every restart.
- Teardown race: `components/homekit/async_unload_entry` polls `async_port_is_available` in a
  loop before returning (`components/homekit/__init__.py:411-430`), so a reload does not try to
  re-bind a port the old site has not finished releasing. For us the reload is triggered by a
  reconfigure, so this is directly applicable.

### 5.7 Note on the absence of port-binding guidance

There is **no** developer-documentation page on an integration that binds and owns a listening
port. That is not a gap to work around; it **corroborates
[#4](https://github.com/jtoniolo/nest-thermostat/issues/4)'s finding** that `emulated_hue` and
`homekit` are the only real precedent, and that reading their source is the right method. Nothing
in this research contradicts #4 on that point.

---

## 6. What I could not establish

Stated plainly, with what would settle each.

1. **The DHCP hostname the Thermostat sends.** Not documented in the Firmware source, the NLE
   server, the NLE docs, or anywhere I searched. *Settled by:* a packet capture, or `ip neigh` /
   the router's lease table, against a real flashed unit. **Until then the DHCP matcher must be
   `macaddress`-only.** This is a bounded design constraint, not a blocker.
2. **Whether the Thermostat's WiFi MAC actually carries a Nest OUI** rather than the WiFi
   chipset vendor's. Assumed by `PLAN.md`; normal practice; unverified for this model.
   *Settled by:* one `arp -n <ip>` — which `reference/scripts/00-preflight.sh:82-84` already runs.
3. **Whether Nest Labs holds an MA-M or MA-S block.** The IEEE MA-L file fetched cleanly (HTTP
   200) and gives exactly `18B430` and `641666`; `oui28/mam.csv` and `oui36/oui36.csv` both
   returned **HTTP 418**. *Settled by:* retrying those URLs or searching
   `regauth.standards.ieee.org`. Very unlikely to matter for a 2011/2012 device.
4. **Definitive proof the Thermostat advertises nothing over mDNS.** Strong circumstantial
   evidence only (§4.4). *Settled by:* `avahi-browse -at` with a flashed unit on the LAN.
5. **What `hostname` returns on a real unit.** The first-party client's docstring says it is the
   serial (`nest-configure.js:31`) and the setup window returns it as `device_name`, but I have
   not seen the value from hardware. If it is *not* the plain serial, the `initialize` path in §2
   needs the exact string, which changes what the config flow must ask the user for. *Settled by:*
   one `POST {"setup":"true"}` on a fresh flash, or SSH `hostname`, or one GET of the serial from
   the Thermostat's Technical Info screen compared against the Basic-auth username we capture.
6. **Whether the shipped Firmware build on Jeff's future unit matches `deps/settings` at HEAD.**
   The Settings API is versioned (`X-API-VERSION`, currently `0.0.1`) and field-replaceable via
   `/cgi-bin/update`. Everything in §1 describes HEAD. *Settled by:* reading `X-API-VERSION` off
   the real unit's first GET.
7. **Home Assistant's actual `RLIMIT_NOFILE`, and the neighbour-table thresholds on the target
   host.** Both bound how wide a sweep may safely fan out (§4.1). *Settled by:* reading
   `/proc/self/limits` and `sysctl net.ipv4.neigh.default.gc_thresh3` inside the running HA
   process's environment. Cheap, and worth doing before choosing a concurrency cap.
8. **Whether the ARP/neighbour table is readable from inside HA in every install method**
   (Container, Core-in-venv, OS, Supervised). Affects §4.2. *Settled by:* trying it on the target
   install.
9. **`aiodhcpwatcher` and `aiodiscover` behaviour read from disk.** Neither is installed in the
   venv on this machine; §4.3's claims about them come from their published source and from HA's
   `dhcp/manifest.json` pins (`aiodhcpwatcher==1.2.1`, `aiodiscover==2.7.1`). *Settled by:*
   reading them in a venv that actually has the `dhcp` integration's requirements installed.

---

## 7. Corrections to in-tree material

Recorded so the map's later tickets do not inherit them.

| Where | Says | Actually |
|---|---|---|
| `reference/PLAN.md:325` | The 8080 API locks behind a password ~30 min after boot; sequence `reboot → sweep → push` for an unlocked API | The API never unlocks. Writes always need the credential. What the 30 min gates is a **one-shot** `{"setup":"true"}` credential handout, further gated on the default Endpoint and a persistent lockfile. A reboot re-opens nothing. §2 |
| `reference/PLAN.md:326` | The Endpoint change "may not take effect until the device reboots"; test which it is | Tested, from the shipped CGI: the CGI restarts the `nestlabs` service itself after 10 s. No reboot needed for the change. A reboot is worth asking for only to get a full state snapshot. §3 |
| `reference/PLAN.md:315` | Nest Labs' OUI is `18:B4:30` | There are two: `18:B4:30` and `64:16:66`. §4.2 |
| `reference/PLAN.md:293` | POST `{"endpoint": "http://192.168.1.50:9543"}` | Correct — and the Firmware appends `/entry` itself, so what is stored is `…:9543/entry`. Sending a path yields `/entry/entry`. §1.6 |
| [#4](https://github.com/jtoniolo/nest-thermostat/issues/4) | `emulated_hue` and `homekit` reload the entry via a manual update listener | True of those two, still, in 2026.5.4 — but `OptionsFlowWithReload` is now the documented way and is mutually exclusive with the listener. §5.3 |
| NLE server `scan.py:46` | reads `device_name` from a GET response | GET returns only `cloudregisterurl`. Always `None`. §1.3 |
| NLE server `scan.py:126` | sends `settings.api_origin` as the endpoint | Its own `api_origin_with_port` exists for exactly this and is not used here. Send an explicit port. §1.7 |
