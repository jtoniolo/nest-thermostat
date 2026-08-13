# Subscribe hold and push lifecycle

Research findings for [#14](https://github.com/jtoniolo/nest-thermostat/issues/14). Every
number and rule below is a policy a build session can implement directly. Nothing here is
a preference; the four genuine forks in the road are collected in
[§10 Open questions](#10-open-questions-for-a-human).

## 0. Sources and how they are cited

| Short form | What it is | Where |
|---|---|---|
| `CONTRACT:NNN` | The distilled transport contract, 1102 lines | `git show research/protocol-reference:reference/research/protocol-transport-contract.md` |
| `NLE/<path>:NNN` | The NLE server. **Protocol reference only — read, never copied.** | `reference/NoLongerEvil-SelfHosted/src/nolongerevil/<path>` |
| `HA/<path>:NNN` | Home Assistant core, authoritative upstream | `/var/home/jeff/repo/homeassistant/renogy-ha/.venv/lib/python3.14/site-packages/homeassistant/<path>` |
| `AIOHTTP/<path>:NNN` | aiohttp 3.13.5, the version HA pins | `/var/home/jeff/repo/homeassistant/renogy-ha/.venv/lib/python3.14/site-packages/aiohttp/<path>` |

Authority order when sources disagree: **the contract wins over the NLE server**, and
**HA core on disk wins over the developer documentation**. Every disagreement found is
recorded in [§9](#9-where-the-sources-contradict-each-other).

`aiohttp` version confirmed at `AIOHTTP/__init__.py:1` (`__version__ = "3.13.5"`). The NLE
server pins only `aiohttp>=3.9.0` (`NLE/../pyproject.toml:29`), so its behaviour was not
necessarily validated against 3.13.5. Several findings below turn on that difference.

---

## 1. The numbers, in one table

Everything a build session needs to hard-code or make configurable.

| Name | Value | Unit | Where it goes | Source |
|---|---|---|---|---|
| `suspend_time_max` | **300** | s | `X-nl-suspend-time-max` response header on every subscribe | `CONTRACT:168`, `CONTRACT:592` |
| `suspend_time_max` hard ceiling | **350** | s | validation bound; never exceed | `CONTRACT:592`, `CONTRACT:1096`, `NLE/config/environment.py:68` |
| Hold duration | **290** | s | `hold = suspend_time_max - 10` | `CONTRACT:593-594`, `NLE/config/environment.py:187` |
| Margin under `suspend_time_max` | **10** | s | the formula's constant; "sufficient" | `CONTRACT:594` |
| Thermostat idle-abandon threshold | **~360** | s | never approach it | `CONTRACT:596-598` |
| Inter-chunk batching window | **3.0** | s | after the first chunk, wait this long for more | `CONTRACT:733`, `NLE/routes/nest/transport.py:81` |
| Thermostat inter-chunk closing timer | **5** | s | resets on every chunk received | `CONTRACT:730-731` |
| Non-chunked immediate timeout | **7** | s | the penalty for omitting `Transfer-Encoding: chunked` | `CONTRACT:577-578` |
| Thermostat wake latency on push | **100–500** | ms | independent of `suspend_time_max` | `CONTRACT:748-749` |
| `X-nl-defer-device-window` | **15** | s | optional response header; contract recommends 15–30 | `CONTRACT:176`, `NLE/config/environment.py:75` |
| `X-nl-disable-defer-window` | **60** | s | send only when pushing temperature fields | `CONTRACT:177`, `NLE/config/environment.py:83` |
| `AppRunner(shutdown_timeout=…)` | **10** | s | matches HA's own HTTP server | `HA/components/http/__init__.py:678-680` |
| `AppRunner(tcp_keepalive=…)` | **False** | — | **mandatory**, see [§8.1](#81-so_keepalive-is-on-by-default-in-aiohttp-and-must-be-turned-off) | `CONTRACT:604-611`, `AIOHTTP/web_protocol.py:187` |
| `AppRunner(handler_cancellation=…)` | **True** | — | see [§7.5](#75-handler_cancellation-is-what-makes-a-dead-socket-hold-end-early) | `HA/components/http/__init__.py:679` |
| Entry-unload task budget | **10** | s | HA's fixed budget in `_async_process_on_unload` | `HA/config_entries.py:1227` |
| Port-availability poll on unload | **30 × 1** | s | HomeKit's guard, `SHUTDOWN_TIMEOUT` × `PORT_CLEANUP_CHECK_INTERVAL_SECS` | `HA/components/homekit/const.py:14`, `HA/components/homekit/__init__.py:161` |

Derived rule the build must enforce in one place:

```
assert 5 <= suspend_time_max <= 350          # NLE/config/environment.py:67-68
hold_seconds = suspend_time_max - 10         # CONTRACT:594
assert hold_seconds < suspend_time_max < 360 # CONTRACT:596
```

---

## 2. Hold duration, the margin, and the failure past ~360 s

### 2.1 Who drives the cycle

**The Integration drives the reconnect cycle, not the Thermostat.** The Thermostat does
not close a subscribe connection of its own accord during normal operation
(`CONTRACT:587-588`). The Integration closing the connection is what wakes the Thermostat
via WoWLAN and causes it to resubscribe (`NLE/routes/nest/transport.py:732-733`,
`NLE/config/environment.py:178-180`).

This was inverted in earlier revisions of the protocol reference and corrected against real
hardware in revision 2.5: *"Server controls the reconnect cycle, not the device. Hold time
must be **shorter** than suspend time. Previous guidance was inverted and incorrect."*
(`CONTRACT:1097`).

### 2.2 The three timers, and why 290

Three independent timers govern the hold. They must be ordered
`hold < suspend_time_max < idle_abandon`:

1. **Hold — 290 s, ours.** The Integration's own `asyncio.wait_for` timeout on the hold.
   This is the primary mechanism (`NLE/config/environment.py:178`, called "the PRIMARY
   mechanism that drives the subscribe cycle" at `NLE/routes/nest/transport.py:36-37`).
2. **`suspend_time_max` — 300 s, the Thermostat's safety net.** Advertised in
   `X-nl-suspend-time-max`. It is the maximum time the Thermostat may sleep before its own
   wake timer fires *if the Integration has not already closed*
   (`NLE/config/environment.py:69-70`). Because the hold fires first, this timer should
   never actually be reached.
3. **~360 s — the Thermostat's idle-abandon threshold.** Not configurable, not
   advertised, a property of the Firmware (`CONTRACT:596`).

The 10-second margin between 1 and 2 is stated as sufficient in the contract
(`CONTRACT:594`) and implemented as a plain subtraction, not a percentage:

> `return float(self.suspend_time_max - 10)` — `NLE/config/environment.py:187`

The 50-second gap between 2 and 3 is the safety budget that absorbs network latency and
event-loop delay.

### 2.3 The failure mode past ~360 s

Verbatim from the contract:

> **Critical**: If the connection remains idle for ~360 seconds, the Thermostat considers
> it dead and resubscribes on a **new** connection without closing the old one, creating
> overlapping subscriptions. — `CONTRACT:596-598`

Two consequences a build session must plan for:

- **Socket leak on the Integration side.** The abandoned connection is not closed by the
  Thermostat. The Integration's handler is still parked in `wait_for`, holding a socket
  and a task. Nothing on the wire tells it the peer is gone. It survives until the
  Integration's own hold timeout expires, or until TCP eventually errors out. The NLE
  server observes exactly this and logs it as
  *"held dead connection for {hold}s — device already resubscribed"*
  (`NLE/routes/nest/transport.py:776-779`), gated on the subscription count exceeding one
  (`NLE/routes/nest/transport.py:774-775`). Its subscription manager logs the same event
  from the other side as a stale-subscription warning
  (`NLE/services/subscription_manager.py:115-126`).
- **Duplicate pushes.** Both connections are live subscriptions, so a push goes to both
  (see [§6](#6-overlapping-subscriptions-for-one-thermostat)). Harmless but wasteful.

**Rule:** the 290 s hold exists precisely so this never happens. Do not make the hold
configurable independently of `suspend_time_max` — derive it, so the invariant cannot be
broken by configuration.

### 2.4 Why the old "600" number is wrong

Revision 2.6 of the protocol reference records: *"`X-nl-suspend-time-max` was documented as
600 in examples but must be <=350. … Contradictions found against hardware."*
(`CONTRACT:1096`). Treat any value above 350 as a bug. The NLE server encodes the ceiling
as a validation bound rather than a comment — `ge=5, le=350`
(`NLE/config/environment.py:67-68`) — and the Integration should do the same.

---

## 3. Clean close via the chunked terminator

### 3.1 What the terminator is and where it comes from

Closing a hold means writing the final chunk of a chunked HTTP body: the three-byte length
`0`, then `\r\n\r\n` (`CONTRACT:600`).

**The Integration does not write those bytes by hand, and must not try to.** In aiohttp,
`StreamResponse.write_eof()` with no trailing data emits exactly `b"0\r\n\r\n"`:

> `self._write(b"0\r\n\r\n")` — `AIOHTTP/http_writer.py:330`

reached from `StreamResponse.write_eof` (`AIOHTTP/web_response.py:572-586`) via
`StreamWriter.write_eof` (`AIOHTTP/http_writer.py:323-333`).

### 3.2 aiohttp always sends the terminator — you cannot opt out

After a handler returns, aiohttp's `finish_response` calls `write_eof()` unconditionally:

```python
await prepare_meth(request)
await resp.write_eof()
```
— `AIOHTTP/web_protocol.py:720-721`

`write_eof()` is idempotent (`AIOHTTP/web_response.py:577-578` guards on `_eof_sent`), so
calling it in the handler and letting aiohttp call it again is safe. **But the converse is
not true: skipping it in the handler does not suppress it.** Returning the response ends
the request, and aiohttp terminates the chunked body.

This matters because the NLE server deliberately tries to suppress the terminator on the
hold-timeout path:

> ```python
> # Only terminate chunked response if we actually sent data
> # Empty body (0\r\n\r\n) is a "tickle" that forces reconnect
> # On timeout, device has already resubscribed, so don't send tickle
> if data_sent:
> ```
> — `NLE/routes/nest/transport.py:797-800`

**That suppression does not work.** The handler returns the `StreamResponse` at
`NLE/routes/nest/transport.py:809`, and aiohttp emits `0\r\n\r\n` anyway at
`AIOHTTP/web_protocol.py:721`. See [§9.1](#91-the-nle-server-cannot-suppress-the-terminator-and-should-not-try).

### 3.3 The rule for the Integration

**Every subscribe hold ends by terminating the chunked body, on every path — data sent,
hold timeout, or shutdown.** This is both what the contract asks for (`CONTRACT:600`) and
the only thing aiohttp will do. Write it explicitly:

```
finally:
    deregister the subscription
    await response.write_eof()      # idempotent; suppress ConnectionError
return response
```

Guard it against a dead peer. The NLE server's `except (ConnectionResetError,
ConnectionError)` around `write_eof` (`NLE/routes/nest/transport.py:804-807`) is the right
shape and worth keeping.

### 3.4 The terminator on an empty body is the "service tickle", and that is fine

The contract names an empty chunked body a *service tickle* that forces the Thermostat to
reconnect, and blesses it for "graceful shutdown, load balancer migration, force state
refresh", but not for "normal operation" (`CONTRACT:738-743`).

Reconcile that with §3.2 as follows: on the hold-timeout path the Integration *wants* the
Thermostat to reconnect — that is the whole point of the 290 s cycle
(`NLE/routes/nest/transport.py:771-773`). The empty terminator delivers exactly the desired
behaviour. The "not for normal operation" caution is about sending a tickle *early*, as a
substitute for real data, not about closing a hold that has run its course. **No behaviour
change is required. The Integration simply lets the terminator go out every time.**

### 3.5 Headers must reach the wire before the hold, and only `StreamResponse` does that

The Thermostat becomes eligible to sleep the moment it has the response headers
(`NLE/routes/nest/transport.py:14-15`, `CONTRACT:190-191`). aiohttp 3.13.5 **buffers
response headers** by default and coalesces them with the first body write
(`AIOHTTP/http_writer.py:210-232`, `_headers_buf`). If they were buffered here, the
Thermostat would sit awake for the whole 290 s hold and the power saving would be lost.

Verified safe for the class we need: `StreamResponse` sets
`_send_headers_immediately = True` (`AIOHTTP/web_response.py:92`), so `prepare()` →
`_write_headers()` calls `writer.send_headers()` at once
(`AIOHTTP/web_response.py:537-548`). Plain `web.Response` sets it to `False`
(`AIOHTTP/web_response.py:626`).

**Rule: the subscribe handler must use `web.StreamResponse` and `await
response.prepare(request)` before entering the hold. Never `web.Response`.**

On chunking, prefer the supported API. `response.enable_chunked_encoding()` sets
`_chunked`, which drives `writer.enable_chunking()` and sets the header
(`AIOHTTP/web_response.py:493-501`). Setting the `Transfer-Encoding: chunked` header by
hand, as the NLE server does (`NLE/routes/nest/transport.py:684`), happens to reach the
same state through the no-content-length branch
(`AIOHTTP/web_response.py:502-508`) — but it is incidental, not contractual.

---

## 4. How a pending state change interrupts a hold

### 4.1 The mechanism

A held subscribe is an `await` on a per-subscription notification queue, bounded by the
hold timeout:

```python
changed_objects = await asyncio.wait_for(
    notify_queue.get(),
    timeout=settings.connection_hold_timeout,
)
```
— `NLE/routes/nest/transport.py:735-738`

A state change anywhere else in the process ends the hold by putting the changed objects on
that queue. The NLE server does this with `put_nowait`, under a lock, for every live
subscription belonging to the serial
(`NLE/services/subscription_manager.py:181-194`). The write path that triggers it — merge
into state, bump revision and timestamp, then notify — is at
`NLE/routes/control/command.py:538-563`.

For the Integration the same shape applies, with the HA entity's service call standing in
for NLE's control API:

```
entity service call
  → write the field into the in-memory bucket map
  → bump revision + timestamp ONLY if the merged value really differs   (settled in #8)
  → put the formatted object on every live subscription queue for that Thermostat
  → each held handler wakes, writes one chunk, then batches for 3 s, then terminates
```

The push payload must be `{"objects": [...]}` with each object's fields in the order
`object_revision`, `object_timestamp`, `object_key`, `value` — field order is load-bearing
(`CONTRACT:521-523`, and the NLE server carries the same warning as a comment at
`NLE/services/subscription_manager.py:213-223`).

### 4.2 The zero-hold case: data already newer at subscribe time

Not every push interrupts a hold. If, at the moment the subscribe arrives, the Integration
already holds objects with a timestamp newer than the Thermostat's, it must send them
immediately and close, without ever entering the hold
(`NLE/routes/nest/transport.py:701-708`; the same branch decides the
`X-nl-disable-defer-window` header *before* `prepare()`, at
`NLE/routes/nest/transport.py:675-679`, because headers cannot be changed afterwards).

This is a hard sequencing constraint on the handler: **decide every response header,
including `X-nl-disable-defer-window`, before calling `prepare()`.**

### 4.3 The inter-chunk batching window: 3 seconds

Once the first chunk has gone out, the connection is not closed straight away. The
Thermostat's 5-second closing timer **resets on each chunk it receives**
(`CONTRACT:730-731`), so more than one chunk may be sent on one connection. The window to
wait for the next one is **3 seconds**, chosen to sit safely under 5:

> `INTER_CHUNK_BATCH_TIMEOUT = 3.0` — `NLE/routes/nest/transport.py:81`, with the rationale
> at `NLE/routes/nest/transport.py:78-80`: *"Must be under the device's 5-second
> inter-chunk timeout so the connection never idles out on the device side."*

The loop is: write chunk → wait up to 3 s for another → on data, write and repeat → on
timeout, break and terminate (`NLE/routes/nest/transport.py:750-763`).

**Each chunk must be a complete, self-contained `{"objects": [...]}` JSON document.** The
Thermostat parses every chunk independently (`CONTRACT:580-581`). Never split one JSON
document across two chunks. aiohttp gives one chunk per `await response.write(...)` call
(`AIOHTTP/http_writer.py:112-117`, `_write_chunked_payload`), so one `write()` per document
is the rule.

**Numbers for the batch loop:**

| Step | Timeout | On expiry |
|---|---|---|
| Initial wait for any data | 290 s | terminate, no body |
| Wait for chunk *n+1* after chunk *n* | 3 s | terminate |
| Thermostat's own closing timer | 5 s, resets per chunk | Thermostat closes |

There is no documented cap on the number of chunks per connection. The window is what
bounds it.

### 4.4 Display wake rides along with the push

When the push carries `target_temperature`, `target_temperature_high` or
`target_temperature_low`, also set `target_change_pending: true` in the same value, to wake
the physical display. The Thermostat then PUTs `target_change_pending: false` to
acknowledge, and the Integration must accept that `false` without re-pushing `true`
(`CONTRACT:757-764`). Do **not** set it for `target_temperature_type`, `away`, fan
settings, or any `device`/`structure` field (`CONTRACT:764`). The NLE server's transient
special case for this field is at `NLE/routes/nest/transport.py:394-397`.

Independently, when the pushed objects contain temperature or mode fields, add the
`X-nl-disable-defer-window` header so the Thermostat confirms immediately instead of
waiting out its defer window. The NLE server's field set for that test is
`target_temperature`, `target_temperature_high`, `target_temperature_low`,
`target_temperature_type`, `hvac_mode` (`NLE/routes/nest/transport.py:307-313`).

### 4.5 Drop the NLE server's pending-push replay buffer

The NLE server buffers objects whose delivery failed on a broken socket and replays them to
the next subscription (`NLE/services/subscription_manager.py:146-159`, replayed at
`NLE/services/subscription_manager.py:100-107`, filled at
`NLE/routes/nest/transport.py:789-791`).

**Do not port it.** It is redundant against the Integration's own design. The Thermostat
lists every bucket it holds, with revision and timestamp, in the body of every subscribe
(`CONTRACT:116-120`). The Integration compares those timestamps against its own state and
sends anything newer immediately (`§4.2`, `NLE/routes/nest/transport.py:701-708`). A push
lost to a broken socket is therefore re-derived from the state map on the very next
subscribe, at most a few seconds later. A replay buffer adds a second source of truth about
what the Thermostat has, which is precisely the duplication the "build only what applies"
rule exists to prevent. The state map plus the timestamp comparison is the whole mechanism.

---

## 5. Where the hold actually runs — not in an HA task

This is the single most consequential structural finding, and it reframes the unload
question in [§7](#7-cancelling-holds-on-config-entry-unload).

**The hold is not a task the Integration creates.** It runs inside the aiohttp
request-handler task, which aiohttp creates itself, one per request, inside the connection's
`RequestHandler.start()` loop:

```python
coro = self._handle_request(request, start, request_handler)
if sys.version_info >= (3, 12):
    task = asyncio.Task(coro, loop=loop, eager_start=True)
```
— `AIOHTTP/web_protocol.py:603-607`

That task belongs to the `Server` object built by the `AppRunner`
(`AIOHTTP/web_runner.py:389-396`), which the Integration owns. It is **never** registered
with `entry.async_create_task` or `entry.async_create_background_task`, so HA's config-entry
task machinery has no handle on it at all.

Consequently, questions of the form *"which entry task API should the hold use?"* have no
answer, because none applies. The correct question is *"how does the Integration tear down
its own `AppRunner` without stalling the unload?"* — [§7](#7-cancelling-holds-on-config-entry-unload).

For completeness, both entry task APIs were verified on disk, because the answer bears on
any *other* long-lived work the Integration does create (a Settings API poll, a discovery
sweep):

- `entry.async_create_task` adds to `self._tasks` (`HA/config_entries.py:1360-1361`).
- `entry.async_create_background_task` adds to `self._background_tasks`
  (`HA/config_entries.py:1388-1389`), documented as *"Background tasks are automatically
  canceled when config entry is unloaded"* (`HA/config_entries.py:1375`), delegating to
  `hass.async_create_background_task` (`HA/core.py:816-845`), which uses
  `create_eager_task` (`HA/util/async_.py:25-44`).

**Cross-check confirmed.** The claim relayed to this session — that `async_create_task`
tasks are only *awaited* while `async_create_background_task` tasks are *cancelled first,
then awaited*, both under one 10-second budget — is correct, verbatim:

```python
cancel_message = f"Config entry {self.title} with {self.domain} unloading"
for task in self._background_tasks:
    task.cancel(cancel_message)

_, pending = await asyncio.wait(
    [*self._tasks, *self._background_tasks], timeout=10
)

for task in pending:
    self.logger.warning(
        "Unloading %s (%s) config entry. Task %s did not complete in time", …
```
— `HA/config_entries.py:1222-1236`

**Rule for any long-lived work the Integration does own: use
`entry.async_create_background_task`, never `entry.async_create_task`.** Anything in
`_tasks` that cannot finish within 10 seconds stalls every unload for the full 10 seconds
and then logs a warning per task.

---

## 6. Overlapping subscriptions for one Thermostat

### 6.1 The rule

Confirmed identically in both sources:

> When the Thermostat wakes early (e.g. user interaction), it may send a new subscribe while
> the server still holds the previous connection. Both are valid simultaneously.
> Track each subscription independently using a server-generated ID. When pushing data,
> send to all active subscriptions for the device. Remove connections only on timeout.
> — `CONTRACT:718-724`

Three sub-rules, each verified against `NLE/services/subscription_manager.py`:

1. **Key on a server-generated ID, never on the Thermostat's `session`.** The Thermostat
   reuses its session ID across requests, so it is not a unique subscription key
   (`CONTRACT:140`). The NLE server uses a UUID and keeps `session_id` for logging only:
   *"The device's session_id is preserved for logging but not used as a key - devices reuse
   session IDs across requests, which would cause race conditions if used for keying."*
   (`NLE/services/subscription_manager.py:33-36`; UUID at
   `NLE/services/subscription_manager.py:38` and `:91`).
2. **Push to every live subscription for the serial.** One queue per subscription, iterate
   them all (`NLE/services/subscription_manager.py:181-194`).
3. **Remove on timeout only, never proactively.** A second subscribe arriving does **not**
   evict the first. The NLE server's stale detection at
   `NLE/services/subscription_manager.py:115-126` only *logs* a warning; the removal
   happens in the held handler's own `finally` block
   (`NLE/routes/nest/transport.py:793-795`), which by construction runs when that hold ends
   on its own terms.

### 6.2 Data structure

`dict[serial, dict[subscription_id, Subscription]]`
(`NLE/services/subscription_manager.py:56`) with an `asyncio.Lock` around every mutation
(`NLE/services/subscription_manager.py:59`, taken at `:81`, `:136`, `:152`, `:181`). Each
subscription carries its own `asyncio.Queue` and a creation timestamp
(`NLE/services/subscription_manager.py:41-42`).

The outer keying by serial survives even in the single-Thermostat case, because it is the
push fan-out unit. Keep it.

### 6.3 The cap

The NLE server caps concurrent subscriptions per device and, when the cap is hit, refuses
the subscription (`NLE/services/subscription_manager.py:83-88`, returning `None`); the
transport handler then sends an empty `{"objects": []}` body and closes
(`NLE/routes/nest/transport.py:713-718`). The default is 100
(`NLE/config/environment.py:61-64`).

A cap is worth keeping — an unbounded set of held sockets is a resource leak with no upper
bound — but 100 is an arbitrary number inherited from a multi-tenant server. In normal
operation with a 290 s hold and a ~360 s abandon threshold, at most two subscriptions can
legitimately overlap. **The value is flagged as [Q2](#q2-the-overlapping-subscription-cap).**

Note the refusal path returns an empty `objects` array, which the contract explicitly warns
against for the *no-updates* case — *"To indicate no updates: hold the connection open
without sending body data. Do not send an empty object."* (`CONTRACT:190-191`). Here it is
not the no-updates case, it is a refusal, and closing immediately is the intent. Keep the
distinction clear in the code.

---

## 7. Cancelling holds on config-entry unload

### 7.1 What HA core actually does, verified on disk

The unload sequence, read from `HA/config_entries.py`:

| Step | Code | Line |
|---|---|---|
| 1 | state → `UNLOAD_IN_PROGRESS` | `HA/config_entries.py:1021-1022` |
| 2 | `await component.async_unload_entry(hass, self)` — **the integration's own teardown, including platform unloading. No timeout wraps this call.** | `HA/config_entries.py:1024` |
| 3 | `await self._async_process_on_unload(hass)` | `HA/config_entries.py:1030-1031` |
| 3a | ↳ pop and call every `async_on_unload` callback; if one returns a coroutine, wrap it with `async_create_task(eager_start=True)` | `HA/config_entries.py:1214-1217` |
| 3b | ↳ cancel every `_background_tasks` entry | `HA/config_entries.py:1223-1224` |
| 3c | ↳ `asyncio.wait([*_tasks, *_background_tasks], timeout=10)` | `HA/config_entries.py:1226-1228` |
| 3d | ↳ warn once per task still pending | `HA/config_entries.py:1230-1236` |
| 4 | `object.__delattr__(self, "runtime_data")` | `HA/config_entries.py:1032-1033` |
| 5 | state → `NOT_LOADED` | `HA/config_entries.py:1035` |

**Cross-check: confirmed exactly as relayed.** The relayed ordering claim
(platforms → `async_on_unload` → background cancel → 10 s await → `runtime_data` deleted →
`NOT_LOADED`) matches the code line for line. One clarification worth writing down:
"platforms unloaded" is not a separate core step — it happens *inside* the integration's
own `async_unload_entry` at step 2, wherever the integration calls
`async_unload_platforms`. So the integration controls what precedes step 3.

`async_on_unload` itself is a plain append (`HA/config_entries.py:1203-1210`) and accepts
either a plain callable or one returning a coroutine
(`Callable[[], Coroutine[Any, Any, None] | None]`, `HA/config_entries.py:1204-1206`).

**Cross-check: `async_on_unload` callbacks also run when setup FAILS. Confirmed.**

```python
finally:
    if not result and domain_is_integration:
        await self._async_process_on_unload(hass)
```
— `HA/config_entries.py:892-894`

So every teardown callback the Integration registers must be safe to run against a
half-built server: `runner` may be `None`, `site` may never have started, the subscription
registry may be empty. Write the teardown defensively and register it only after the object
it tears down exists.

The developer documentation is consistent but much less specific — it says only that on
unload an integration must *"clean up all entities, unsubscribe any event listener and close
all connections"*, and describes `async_unload_entry` without mentioning `async_on_unload`,
`async_create_background_task`, or which helper cancels tasks
(<https://developers.home-assistant.io/docs/config_entries_index>). **The on-disk source
wins and is the citation of record.**

### 7.2 The stall: `runner.cleanup()` will block for up to ~120 s if holds are live

This is the practical answer #14 owes a build session, and it is not obvious.

Tearing down an aiohttp server is `await site.stop()` then `await runner.cleanup()`
(`HA/components/http/__init__.py:710-713`, and the same pair in `emulated_hue` at
`HA/components/emulated_hue/__init__.py:122-123`). `cleanup()` runs:

```python
self._server.pre_shutdown()
await self.shutdown()
await self._server.shutdown(self._shutdown_timeout)
```
— `AIOHTTP/web_runner.py:307-309`

Follow each:

- **`pre_shutdown()`** calls `conn.close()` on every connection
  (`AIOHTTP/web_server.py:65-67`). `RequestHandler.close()` only sets `self._close = True`
  and cancels the *idle* waiter (`AIOHTTP/web_protocol.py:456-464`). **It does not touch a
  running handler.** A held subscribe is unaffected.
- **`Server.shutdown(timeout)`** gathers `conn.shutdown(timeout)` over all connections
  (`AIOHTTP/web_server.py:69-72`), i.e. `RequestHandler.shutdown`
  (`AIOHTTP/web_protocol.py:295-343`), which does two sequential waits, **each** bounded by
  the *same* `timeout`:
  1. `await self._handler_waiter` under `ceil_timeout(timeout)`
     (`AIOHTTP/web_protocol.py:307-314`). That future is only resolved when the handler
     finishes (`AIOHTTP/web_protocol.py:544-546`). A 290-second hold will not finish, so
     this wait burns the full timeout.
  2. `self._current_request._cancel(asyncio.CancelledError())` then
     `await asyncio.shield(self._task_handler)` under another `ceil_timeout(timeout)`
     (`AIOHTTP/web_protocol.py:325-330`). `_cancel` feeds an exception to the *request
     payload*, not to the handler task — a handler parked on `queue.get()` never sees it.
     So this wait burns the full timeout too.
  3. Only then `self._task_handler.cancel()` and `force_close()`
     (`AIOHTTP/web_protocol.py:340-343`).

**Therefore: with `AppRunner`'s default `shutdown_timeout=60.0`
(`AIOHTTP/web_runner.py:249-256`), a single live hold makes `runner.cleanup()` take ~120
seconds.** That runs at step 2 of the unload table, inside `async_unload_entry`, which core
does **not** bound with any timeout (`HA/config_entries.py:1024`). A reload of the config
entry would appear to hang for two minutes.

Even HA's own `shutdown_timeout=10` (`HA/components/http/__init__.py:679`) would give ~20
seconds. Still unacceptable for a reload.

### 7.3 The rule: end the holds yourself, before you touch the runner

Cancellation alone is **not** enough, and waiting for the runner to force it is far too
slow. The Integration must actively end every hold first, then tear the server down. The
teardown, in order:

```
async_unload_entry(hass, entry):
  1. await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
  2. await server.async_close_all_holds()     # see below — signals, does not cancel
  3. await site.stop()
  4. await runner.cleanup()                   # now returns promptly: no handler is parked
  5. poll for port availability                # see §7.4
  return True
```

Step 2 is the piece that does not exist in the NLE server and that the Integration must
add. It is a **signal**, not a cancellation:

- Keep the subscription registry ([§6.2](#62-data-structure)) reachable from the server
  object on `entry.runtime_data` (settled in #8).
- Add a `closing` flag or a sentinel value. On unload, put the sentinel on every live
  subscription's queue, then `await` until the registry empties (bounded — see below).
- Each held handler's `wait_for` returns the sentinel, breaks out of the hold, skips the
  batch loop, runs its normal `finally` (deregister), and returns the response. aiohttp
  writes `0\r\n\r\n` (`AIOHTTP/web_protocol.py:721` → `AIOHTTP/http_writer.py:330`) and the
  handler task completes.
- The Thermostat sees a clean close, treats it as the ordinary end of a hold, and
  resubscribes — which is exactly the contract's sanctioned use of the terminator for
  "graceful shutdown" (`CONTRACT:740-742`).

This is strictly better than cancelling the handler tasks. A cancelled handler cannot run
`write_eof` cleanly, so the Thermostat sees a truncated chunked body instead of a proper
terminator; the contract's clean-close path (`CONTRACT:600`) is skipped.

Bound the wait in step 2 defensively — a couple of seconds, then fall through to step 3
regardless. Combined with an explicit `AppRunner(shutdown_timeout=10)`, the worst case
becomes bounded and small instead of ~120 s, and the well-behaved case is near-instant.

Register the whole thing so it also fires on setup failure
(`HA/config_entries.py:892-894`). Two shapes are available:

- Do it in `async_unload_entry` (HomeKit's shape,
  `HA/components/homekit/__init__.py:411-431`) — runs at step 2 of the table, before
  `_async_process_on_unload`, and gives full control of ordering.
- Register a teardown coroutine with `entry.async_on_unload(...)`
  (`HA/config_entries.py:1203-1210`) — runs at step 3a, and is the only one of the two that
  also fires on setup failure.

**Both, and they do different jobs.** Put the ordered teardown in `async_unload_entry`,
made idempotent; register the same idempotent teardown with `entry.async_on_unload` so a
failed setup also releases the port. Idempotence is what makes registering it twice safe,
and it is required anyway by the half-built-server case.

### 7.4 The port-availability poll: keep it

**Cross-check: confirmed, with one correction to the stated reason.** HomeKit does poll:

```python
for _ in range(SHUTDOWN_TIMEOUT):
    if async_port_is_available(entry.data[CONF_PORT]):
        break
    …
    await asyncio.sleep(PORT_CLEANUP_CHECK_INTERVAL_SECS)
```
— `HA/components/homekit/__init__.py:421-429`, with `SHUTDOWN_TIMEOUT = 30`
(`HA/components/homekit/const.py:14`) and `PORT_CLEANUP_CHECK_INTERVAL_SECS = 1`
(`HA/components/homekit/__init__.py:161`). So **30 attempts at 1-second intervals**, as
relayed.

**Correction: the reason is not `TIME_WAIT`.** The probe binds a socket with `SO_REUSEADDR`
set (`HA/components/homekit/util.py:618-622`, `:621`), and `SO_REUSEADDR` is precisely what
makes binding over a `TIME_WAIT` socket succeed on Linux. What the probe actually detects is
a socket still in `LISTEN` — the old server not yet fully released. Record this so nobody
"optimises away" the poll on the mistaken belief that `SO_REUSEADDR` on the real listener
would make it unnecessary; it would not, because the old listener is still bound.

**Cross-check: `emulated_hue` does not poll — confirmed** (`site.stop()` +
`runner.cleanup()` only, `HA/components/emulated_hue/__init__.py:119-123`). But it is a weak
counter-example and should not be followed: it is YAML-only, so it has no reload path at
all, and it tears down on `EVENT_HOMEASSISTANT_STOP`
(`HA/components/emulated_hue/__init__.py:125`) where nothing is about to rebind the port.
The Integration is config-entry based and **will** rebind the same port immediately on
reload.

**Keep the poll.** It is cheap, it is HA's own prior art for exactly our situation, and #4
already recorded it as the reload-race guard. Reuse HomeKit's numbers (30 × 1 s) and its
probe shape (a non-blocking `SO_REUSEADDR` socket, bind, close —
`HA/components/homekit/util.py:625-635`).

Place it **last**, after `runner.cleanup()`, as HomeKit does. With §7.3 in place it should
find the port free on the first attempt.

### 7.5 `handler_cancellation` is what makes a dead-socket hold end early

`AppRunner(handler_cancellation=True)` makes aiohttp cancel the handler task when the
client's connection is lost:

```python
if handler_cancellation and self._task_handler is not None:
    self._task_handler.cancel()
```
— `AIOHTTP/web_protocol.py:385-386`, in `connection_lost`

HA's own HTTP server enables it (`HA/components/http/__init__.py:679`). The NLE server does
not (`NLE/main.py:308` passes only `keepalive_timeout`), which is why its holds on
already-dead sockets sit for the full 290 s and it has to log them after the fact
(`NLE/routes/nest/transport.py:774-779`).

**Enable it.** Two consequences the handler must be written for:

- The hold will raise `asyncio.CancelledError` on peer disconnect. Catch it alongside
  `ConnectionResetError` / `ConnectionError`, deregister the subscription in `finally`, and
  re-raise or return cleanly. The NLE server's `except (asyncio.CancelledError,
  ConnectionResetError, ConnectionError)` at `NLE/routes/nest/transport.py:786` is the right
  set; note that swallowing `CancelledError` without re-raising is generally wrong, and the
  `finally` at `NLE/routes/nest/transport.py:793-795` is what makes the deregistration
  reliable regardless.
- It does **not** help with unload. `handler_cancellation` fires from `connection_lost`,
  which shutdown does not trigger. [§7.3](#73-the-rule-end-the-holds-yourself-before-you-touch-the-runner) is still required.

### 7.6 What a leaked hold would cost

For the record, so the build session knows what "no leaked task and no socket" is guarding
against. Without §7.3, on every reload: one aiohttp handler task per live hold, each pinning
an open socket, surviving up to ~120 s inside the new entry's lifetime; a re-bound listener
racing the old one on the same port; and a Thermostat holding a connection to a server that
no longer has state for it. With §7.3 the count is zero on both, and the reload is prompt.

---

## 8. Constraints, not decisions

Both were named in #14 as constraints. Both were verified, and **one of them is actively
violated by the default configuration** — which makes it the most actionable finding in this
document after [§7.2](#72-the-stall-runnercleanup-will-block-for-up-to-120-s-if-holds-are-live).

### 8.1 `SO_KEEPALIVE` is ON by default in aiohttp and must be turned off

The contract prohibits it outright:

> **Do NOT enable server-side `SO_KEEPALIVE`.** The Thermostat does not respond to
> keep-alive probes while the CPU is asleep (WiFi hardware maintains the TCP connection
> during CPU sleep). Keep-alive probes will go unanswered and the OS will eventually kill
> the connection. — `CONTRACT:604-609`

**Cross-check: the relayed claim that "nothing in the aiohttp server path sets it for us" is
REFUTED.** aiohttp sets `SO_KEEPALIVE` on every accepted connection, by default:

```python
tcp_keepalive: bool = True,
```
— `AIOHTTP/web_protocol.py:187` (`RequestHandler.__init__`)

```python
real_transport = cast(asyncio.Transport, transport)
if self._tcp_keepalive:
    tcp_keepalive(real_transport)
```
— `AIOHTTP/web_protocol.py:348-350` (`connection_made`)

```python
sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
```
— `AIOHTTP/tcp_helpers.py:16`

The half of the claim that concerns HA core is correct: `SO_KEEPALIVE` appears **nowhere** in
the `homeassistant` package (grep over the whole package: zero hits), and the only
`setsockopt` calls are `SO_REUSEADDR` / `SO_REUSEPORT` / `SO_BROADCAST` and multicast options
in `HA/components/emulated_hue/upnp.py:156-167`, `SO_REUSEADDR` in
`HA/components/homekit/util.py:621`, and `SO_RCVBUF` in
`HA/components/mqtt/client.py:587`. But HA core is not where it comes from — **aiohttp is**,
and HA's own HTTP server therefore runs with `SO_KEEPALIVE` on, since
`HA/components/http/__init__.py:678-680` does not disable it.

**Rule — mandatory:**

```python
runner = web.AppRunner(
    app,
    tcp_keepalive=False,        # CONTRACT:604-611 forbids SO_KEEPALIVE
    handler_cancellation=True,  # §7.5
    shutdown_timeout=10,        # §7.2
)
```

The kwarg reaches `RequestHandler`: `AppRunner.__init__(**kwargs)` stores them
(`AIOHTTP/web_runner.py:371-374` → `AIOHTTP/web_runner.py:249-256`), `_make_server` passes
them to `Application._make_handler(**self._kwargs)`
(`AIOHTTP/web_runner.py:389-396`), which forwards them into `Server(...)`
(`AIOHTTP/web_app.py:419-444`), whose `__call__` builds `RequestHandler(self, loop=…,
**self._kwargs)` (`AIOHTTP/web_server.py:74-77`). Verified end to end.

This is also an independent argument for the decision already taken in #4 and #7 — the
Integration owns its **own** `AppRunner` and `TCPSite`, and does not register Routes on HA's
shared HTTP server. The shared server has `SO_KEEPALIVE` on and cannot be reconfigured
per-integration.

Note on severity: on stock Linux, `net.ipv4.tcp_keepalive_time` defaults to 7200 s, far
longer than a 290 s hold, so probes would not normally fire inside one hold anyway. The
prohibition is still the rule to follow — a tuned host, a router, or any middlebox that
honours the flag can break the hold, and the contract records it as verified behaviour.
Cost of compliance: one kwarg.

### 8.2 The explicit port on the Advertised URL

> **Always include an explicit port in the `transport_url`.** The Thermostat's URL parser
> fails to extract ports from URLs that omit them, breaking WoWLAN functionality.
> — `CONTRACT:561-562`

Symptoms if broken: the Thermostat works while awake, but server push fails to wake it, and
its logs show packet size 0 instead of ~40 bytes (`CONTRACT:569-570`).

This lands squarely in the subscribe lifecycle even though it is set at `/entry` time:
**WoWLAN is the mechanism by which closing a hold wakes the Thermostat.** If the port is
missing from the Advertised URL, the whole 290 s cycle silently degrades to "the Thermostat
only ever notices things when it happens to be awake". A build session must treat the
explicit port as a precondition of the hold working at all, not as an `/entry` detail.

The NLE server normalises this defensively rather than trusting configuration — parse the
URL, and if `parsed.port is None`, splice the server port into the netloc
(`NLE/config/environment.py:155-167`). Worth copying as a *behaviour*: construct the
Advertised URL from a host and a port, never from a free-text string, so it cannot be
port-less.

Restated from #6, and unchanged here: the Advertised URL is the HA host's LAN IP, never a
tunnel URL.

### 8.3 aiohttp's `keepalive_timeout` is a non-issue in 3.13.5 — do not copy NLE's workaround

The NLE server inflates it defensively:

```python
# aiohttp keepalive_timeout must exceed connection_hold_timeout so the HTTP
# server doesn't close idle connections before our hold loop finishes.
keepalive_timeout = int(settings.connection_hold_timeout) + 60
```
— `NLE/main.py:305-308`

Verified against 3.13.5: **not needed.** The default is already 3630 s
(`AIOHTTP/web_protocol.py:186`), and more fundamentally the keep-alive timer is only armed
*after* a response completes (`AIOHTTP/web_protocol.py:670-677`) and only force-closes when
the handler is idle waiting for the next request
(`AIOHTTP/web_protocol.py:504-505`, guarded on `self._waiter`). It cannot touch an in-flight
handler.

The NLE server pins `aiohttp>=3.9.0` (`NLE/../pyproject.toml:29`), where the default was
much lower, which is the likely origin of the workaround. Do not port it. If a build session
wants belt-and-braces, setting it explicitly is harmless — but it is not a protocol
requirement and should not be presented as one.

---

## 9. Where the sources contradict each other

### 9.1 The NLE server cannot suppress the terminator, and should not try

- **The NLE server** intends to skip the chunked terminator when a hold times out with no
  data sent, to avoid a "tickle" (`NLE/routes/nest/transport.py:797-800`, and the design
  note at `NLE/routes/nest/transport.py:40-42`).
- **aiohttp** sends it regardless, from `finish_response`
  (`AIOHTTP/web_protocol.py:720-721` → `AIOHTTP/http_writer.py:330`).
- **The contract** says a connection is closed by sending the terminator
  (`CONTRACT:600`) and lists an empty body under sanctioned uses including graceful shutdown
  (`CONTRACT:738-742`).

**The contract wins, and aiohttp agrees with it.** The NLE server's suppression is dead code
that does not achieve its stated intent. The Integration should terminate every hold
explicitly and drop the conditional entirely. There is no behavioural risk: the terminator
after a 290 s hold produces exactly the resubscribe the cycle depends on.

### 9.2 `SO_KEEPALIVE`: the contract forbids it, the NLE server leaves it on

The NLE server never passes `tcp_keepalive=False` (`NLE/main.py:308`), so every one of its
accepted connections has `SO_KEEPALIVE` set by aiohttp
(`AIOHTTP/web_protocol.py:187`, `:348-350`). The contract prohibits it
(`CONTRACT:604-609`). **The contract wins.** The NLE server is in violation; do not take
its `AppRunner` construction as a template. See
[§8.1](#81-so_keepalive-is-on-by-default-in-aiohttp-and-must-be-turned-off).

### 9.3 The relayed cross-check on `SO_KEEPALIVE` was half right

Recorded because the discrepancy is itself a finding. The claim that "`SO_KEEPALIVE` appears
nowhere in HA core" is **true and verified**. The conclusion drawn from it — that nothing in
the aiohttp server path sets it for us — is **false**: aiohttp sets it, by default, for
everyone including HA's own HTTP server. Grepping HA core alone is not sufficient to answer
this question; the dependency had to be read.

### 9.4 The HomeKit port poll guards `LISTEN`, not `TIME_WAIT`

Recorded in [§7.4](#74-the-port-availability-poll-keep-it). The poll is right, the commonly
stated reason is wrong, and the distinction matters because the wrong reason would justify
deleting the poll.

### 9.5 The developer documentation is thinner than the source

The config-entry docs describe `async_unload_entry` and the duty to *"clean up all entities,
unsubscribe any event listener and close all connections"*, but say nothing about
`async_on_unload`, `async_create_background_task`, the 10-second budget, or the
setup-failure path
(<https://developers.home-assistant.io/docs/config_entries_index>). Not a contradiction, a
gap. **The on-disk source is the citation of record throughout
[§7](#7-cancelling-holds-on-config-entry-unload).**

---

## 10. Open questions for a human

Four genuine forks. Each is a preference the sources do not settle; none blocks writing the
rest of the lifecycle. Everything not listed here was resolved by reading.

### Q1. Is `suspend_time_max` fixed at 300, or a config-entry option?

The contract recommends 300 and caps at 350 (`CONTRACT:168`, `CONTRACT:592`). The NLE server
makes it configurable over `5..350` (`NLE/config/environment.py:65-73`) because it serves
arbitrary deployments. The Integration serves one Thermostat on a LAN. Fixing it at 300
removes a config-flow field, a validation rule and a whole class of user error; exposing it
buys a tuning knob for a hold nobody has a reason to tune. Note the hold must stay derived
either way (`hold = suspend_time_max - 10`), never independently settable.

### Q2. The overlapping-subscription cap

A cap is worth having ([§6.3](#63-the-cap)). The NLE server's 100
(`NLE/config/environment.py:61-64`) is a multi-tenant number. With a 290 s hold against a
~360 s abandon, at most two subscriptions overlap legitimately, so something like 4 leaves
generous headroom while actually bounding the leak. Choosing between "keep 100 as
effectively unbounded" and "a tight cap that could in principle refuse a legitimate
subscribe" is a risk preference, not a fact.

### Q3. `X-nl-defer-device-window` — value, and whether to expose it

The contract recommends 15–30 s and allows 0 to disable (`CONTRACT:176`); the NLE server
defaults to 15 (`NLE/config/environment.py:74-81`). Higher values batch dial-turning into
fewer PUTs; lower values make HA reflect a dial turn sooner. This is a
responsiveness-versus-chatter trade-off that touches the entity model, so it may belong to
whichever ticket owns the entity surface rather than here. Same question for
`X-nl-disable-defer-window` (60 s, `NLE/config/environment.py:82-89`).

### Q4. Should a hold be ended proactively when HA is *stopping*, as well as on unload?

[§7.3](#73-the-rule-end-the-holds-yourself-before-you-touch-the-runner) covers config-entry
unload and reload. Home Assistant shutting down is a different event: closing the holds makes
the Thermostat immediately resubscribe against a host that is going away, and it will retry
with backoff against a closed port (`CONTRACT:926`, 5xx/refused → exponential backoff).
Leaving them for the OS to reap is also defensible — the process is exiting. Both are
correct; which is kinder to the Thermostat's battery and logs is a judgement call, and
`entry.async_on_unload` fires on shutdown too, so the choice must be made deliberately rather
than fallen into.

---

## 11. Build checklist

Everything above, as steps.

**Server construction**
- [ ] Own `AppRunner` + `TCPSite`; do not register Routes on HA's shared HTTP server (#4, #7, and [§8.1](#81-so_keepalive-is-on-by-default-in-aiohttp-and-must-be-turned-off)).
- [ ] `AppRunner(app, tcp_keepalive=False, handler_cancellation=True, shutdown_timeout=10)`.
- [ ] Advertised URL built from host + port so it can never be port-less ([§8.2](#82-the-explicit-port-on-the-advertised-url)).

**Subscribe handler**
- [ ] Decide every response header, including `X-nl-disable-defer-window`, **before** `prepare()`.
- [ ] `X-nl-suspend-time-max: 300`, `X-nl-service-timestamp`, `X-nl-defer-device-window`.
- [ ] `web.StreamResponse` + `enable_chunked_encoding()` + `await prepare(request)` — headers on the wire immediately ([§3.5](#35-headers-must-reach-the-wire-before-the-hold-and-only-streamresponse-does-that)).
- [ ] If any bucket is already newer than the Thermostat's copy: write it, terminate, return. No hold.
- [ ] Otherwise register a subscription under a fresh UUID and hold with `wait_for(queue.get(), timeout=290)`.
- [ ] On data: one `write()` per complete `{"objects": [...]}` document, field order `object_revision`, `object_timestamp`, `object_key`, `value`.
- [ ] Then batch: `wait_for(queue.get(), timeout=3.0)` in a loop until it expires.
- [ ] On hold timeout: no body. Just end.
- [ ] `finally`: deregister the subscription, `await write_eof()` guarded against `ConnectionError`.
- [ ] Handle `CancelledError` (from `handler_cancellation`) alongside the connection errors.

**Subscription registry**
- [ ] `dict[serial, dict[uuid, Subscription]]`, one `asyncio.Queue` each, one `asyncio.Lock` around every mutation.
- [ ] Never key on the Thermostat's `session`.
- [ ] Push fans out to every live subscription for the serial.
- [ ] Remove only from the held handler's own `finally`.
- [ ] No pending-push replay buffer ([§4.5](#45-drop-the-nle-servers-pending-push-replay-buffer)).

**Unload**
- [ ] One idempotent teardown coroutine, safe against a half-built server.
- [ ] Called from `async_unload_entry` **and** registered with `entry.async_on_unload` (setup-failure path, `HA/config_entries.py:892-894`).
- [ ] Order: unload platforms → signal all holds closed (bounded wait) → `site.stop()` → `runner.cleanup()` → port-availability poll, 30 × 1 s.
- [ ] Any *other* long-lived work uses `entry.async_create_background_task`, never `entry.async_create_task` ([§5](#5-where-the-hold-actually-runs--not-in-an-ha-task)).

**Tests** (no hardware; drive from this document)
- [ ] Hold returns after exactly `suspend_time_max - 10`, and the body is empty.
- [ ] A push during a hold produces one chunk within milliseconds, then a second chunk if a second push lands inside 3 s, then termination ~3 s after the last.
- [ ] Two concurrent subscribes for one serial both receive the same push.
- [ ] Unload with two live holds completes promptly and leaves the port bindable — the regression test for [§7.2](#72-the-stall-runnercleanup-will-block-for-up-to-120-s-if-holds-are-live).
- [ ] `SO_KEEPALIVE` is unset on an accepted connection — the regression test for [§8.1](#81-so_keepalive-is-on-by-default-in-aiohttp-and-must-be-turned-off).
- [ ] Every response object serialises with `object_revision` and `object_timestamp` before `object_key`.
