# What the NLE server does where the reference is silent

Research input for [#21](https://github.com/jtoniolo/nest-thermostat/issues/21).
Seven cases where the protocol reference is provisional, partial, or
implementation-defined. This document records **facts only**. The governing
principle — mimic the NLE server, or take the most permissive behaviour that
cannot corrupt Thermostat state — belongs to
[#15](https://github.com/jtoniolo/nest-thermostat/issues/15) and is not decided here.

Vocabulary follows `CONTEXT.md`: Thermostat, Firmware, Integration, NLE server,
Endpoint, Route, Bind address, Advertised URL, Settings API, Model string, Generation.

## Sources

| Rank | Source | How cited |
|------|--------|-----------|
| 1 | NLE server source, `codykociemba/NoLongerEvil-SelfHosted` (MIT). Clone at `reference/NoLongerEvil-SelfHosted/`, which is gitignored. | Paths below are relative to `reference/NoLongerEvil-SelfHosted/`. |
| 2 | The distilled transport contract, branch `research/protocol-reference`, `reference/research/protocol-transport-contract.md`. Section 21 enumerates these open questions. | "contract §N" |
| 3 | The undocumented-surfaces findings, branch `research/nle-omissions`, `reference/research/nle-server-undocumented-surfaces.md`. | "omissions §N" |
| 4 | Settled state model, [#8](https://github.com/jtoniolo/nest-thermostat/issues/8). Nothing here contradicts it. | "#8" |

**On quoting.** The NLE server is a protocol reference, read and never copied.
This document quotes a handful of its **comments** verbatim, because #21 asks for
them: they are the only record of corrections made against real hardware, and a
paraphrase would lose the evidence. No code is reproduced. The quotes are short,
attributed, and the source is MIT-licensed.

**Reading the verdicts.** *Deliberate* means the source carries a comment, a test,
or a validator that explains the behaviour. *Incidental* means the behaviour is
real and observable but nothing in the source explains or defends it — it falls
out of the implementation. *Not found in source* means the NLE server never
exercises the case at all, so it is no evidence either way.

---

## Summary

| # | Case | What the NLE server does | Deliberate or incidental | Risk if the Integration gets it wrong |
|---|------|--------------------------|--------------------------|----------------------------------------|
| 1 | 5xx retry and backoff | Never returns 5xx from any transport Route by design; transport errors are 400 and 401 only. The two device-facing 5xx it does emit are outside transport: 502 on weather-proxy failure, 503 on entry-key generation failure. No retry or backoff logic exists anywhere, in either direction. | **Incidental** — no error middleware, no comment, no policy. A 5xx on transport is an unhandled crash surfaced by the aiohttp default. | **Delay, not corruption.** The Thermostat retries 5xx with exponential backoff of unknown length (contract §18, §21.2). A long backoff means missed pushes and stale entity state; no bucket value is applied, so state cannot be corrupted by the 5xx itself. |
| 2 | `if_object_revision` rejection shape | HTTP **200**, no error field. The rejected bucket contributes one receipt of exactly `object_revision`, `object_timestamp`, `object_key`, in that order, carrying the **server's stored** revision — or `0`/`0` when no record exists. Processing continues to the next bucket. | **Deliberate** — the longest explanatory comment in the handler, plus three dedicated tests. | **Corruption.** Adding `value` silently overwrites the Thermostat's local state and clears its dirty flags, dropping the write with no retry. A non-200 status re-routes the Thermostat into the §18 error ladder (403/404 reset comms state). |
| 3 | Conflict reconciliation | Reconciliation happens **only** on subscribe, by timestamp comparison. The PUT path deliberately does not notify subscribers and does not piggyback any bucket. Two dated `NOTE`s record both behaviours being removed after they corrupted state on real hardware. | **Deliberate**, and the strongest hardware evidence in the whole source: two removals dated 2026-02-09 and 2026-02-10, with a test asserting the PUT handler never touches the subscription manager. | **Corruption.** Reconciling through the PUT response re-creates the exact race the NLE server removed: a stale `target_temperature` overwrites the Thermostat's schedule-derived setpoint. The symptom is the unit heating or cooling to the wrong temperature. |
| 4 | `X-nl-defer-device-window` at or beyond 3599 | Structurally cannot happen. Both defer headers are bounded `ge=0, le=3599` and validated at import; an out-of-range value raises and the server does not start. | Ceiling is **deliberate** (an explicit bound mirroring the reference). Device behaviour at or beyond it is **not found in source** — the NLE server never emits such a value, so it records no observation. | **Unknown by construction.** Contract §21.5 leaves reject / ignore / clamp unspecified. Worst case is a discarded response, so a lost push — the defer window only affects PUT timing, so it cannot corrupt a bucket directly. |
| 5 | Unservable HVAC mode | Refuses upstream rather than falling back: `set_mode` checks `can_heat` / `can_cool` / `has_emer_heat` and raises instead of sending. The transport path applies no mode validation at all. The NLE server records **no** observation of what the Thermostat does when it receives an unservable mode. | Guard is **deliberate** and documented in the module docstring; its permissive defaults are **incidental**; the fallback chain itself is **not found in source**. | **Lasting divergence, not corruption.** The Thermostat silently runs a mode other than the one Home Assistant displays. With `range` on single-stage wiring the high/low setpoints have no meaning, so the effective setpoint is unpredictable. |
| 6 | Clock-skew correction | Stamps `X-nl-service-timestamp` with current wall-clock milliseconds on every transport response. That is the entire mechanism. No threshold, no skew detection, no comparison of device time to server time anywhere in the source. | Header is **incidental** — unconditional and uncommented; nothing ties it to clock correction. The one deliberate, hardware-derived clock fact is the 600-second `manual_eco_timestamp` window in `set_away`. | **Silent no-op.** A `manual_eco_timestamp` outside 600 s of the Thermostat's clock is silently ignored by the Firmware — eco enter/exit does nothing and reports no error. A service timestamp off by more than ~10 minutes makes the Thermostat correct its clock to the Integration's, moving every schedule transition. |
| 7 | The `eco` field's type | **Never writes `eco` in any form.** None of its eight commands produces an `eco` key and its device-setting whitelist has no entry for one. It only ever *reads* a stored `eco`, at three sites, each behind an `isinstance(..., dict)` guard. Its sole eco control is `manual_eco_all` + `manual_eco_timestamp` on the `structure` bucket. | Writing `eco`: **not found in source**. Reading it as a dict: **incidental** — three defensive guards, uncommented and untested. Avoiding the `away` field: **deliberate** and hardware-derived. | **Silent failure to exit eco.** The NLE server implements only the `manual_eco_all: false` path, which changelog rev 2.7 records as silently droppable by the 600-second timestamp validation. It never writes `eco.mode: "schedule"`, which rev 2.9 records as the most reliable exit. Mimicking it inherits the weaker of the two documented paths, and the Thermostat stays in eco at away temperatures with no error reported. |
| 7a | `manual_eco_timestamp` units — the seconds/milliseconds trap | Writes Unix **seconds** (`int(time.time())`), correctly, while `object_timestamp` a few lines away in the same function is **milliseconds** (`int(time.time() * 1000)`). | **Deliberate** in the value, but the trap itself is unmarked — no comment flags the two units sitting side by side. | **Silent no-op.** Milliseconds where seconds are expected puts the timestamp ~55,000 years in the future, so it fails the 600-second window and the Firmware silently ignores the eco change. Eco never exits, and nothing reports an error. |

---

## 1. 5xx retry and backoff intervals

**What the reference says.** Contract §18 gives the Thermostat's side: 5xx → "Retry
with exponential backoff" (reference lines 2599-2626). Contract §21.2 records the
gap — the reference carries an explicit TODO, "Document retry intervals and backoff
strategy for 5xx errors from binary analysis" (reference line 2625), and marks the
whole Error Handling section "Partial". So the retry *interval* is unknown on both
sides of this document.

### What the NLE server does

**It never deliberately returns 5xx on a transport Route.** Every explicit error
return on the device-facing transport path is a 4xx:

| Condition | Status | Where |
|-----------|--------|-------|
| No serial on `GET /nest/transport/device/{serial}` | 400 | `src/nolongerevil/routes/nest/transport.py:252-253` |
| No serial on subscribe | 400 | `src/nolongerevil/routes/nest/transport.py:333-335` |
| Malformed JSON on subscribe | 400 | `src/nolongerevil/routes/nest/transport.py:339-340` |
| `objects` not a list on subscribe | 400 | `src/nolongerevil/routes/nest/transport.py:362-363` |
| No serial on PUT | 400 | `src/nolongerevil/routes/nest/transport.py:814-816` |
| Malformed JSON on PUT | 400 | `src/nolongerevil/routes/nest/transport.py:818-821` |
| `objects` not a list on PUT | 400 | `src/nolongerevil/routes/nest/transport.py:825-826` |
| No serial, in the auth middleware | 400 | `src/nolongerevil/middleware/device_auth.py:97-98` |
| Unknown device (pairing mode only) | 401 | `src/nolongerevil/middleware/device_auth.py:132-138` |
| Upload from a pending device | 401 | `src/nolongerevil/middleware/device_auth.py:125-127` |

Note the subscription cap does **not** produce an error: exceeding
`max_subscriptions_per_device` returns 200 with an empty `objects` array and closes
(`src/nolongerevil/routes/nest/transport.py:713-718`).

**The only device-facing 5xx in the whole server sit outside transport:**

- `502` when the upstream weather proxy returns nothing —
  `src/nolongerevil/routes/nest/weather.py:38-45`. Corroborates omissions §1: weather
  is a cached proxy and its failure is not load-bearing.
- `503` when entry-key generation fails —
  `src/nolongerevil/routes/nest/passphrase.py:118-123`. Unreachable for this project;
  #8 removed pairing entirely.

**There is no error-handling middleware.** The device-facing application is built
with exactly four middlewares — URL normalizer, device auth, device heartbeat, debug
logger (`src/nolongerevil/main.py:134-141`) — and none of them wraps the handler in a
`try`. `src/nolongerevil/middleware/url_normalizer.py:52-83` and
`src/nolongerevil/middleware/device_heartbeat.py:32-43` both call the handler bare.
Any unhandled exception in a transport handler therefore becomes aiohttp's default
500. That is the only way the Thermostat ever sees a 5xx from a transport Route, and
nothing in the source anticipates it.

**No retry or backoff logic exists anywhere in the server.** A sweep for
`backoff`, `retry`, `retries`, `exponential` across the source returns only:
the CAS-retry comment at `src/nolongerevil/routes/nest/transport.py:854-860`, which
describes the *Thermostat* retrying; and a docstring line in the control-API network
scan at `src/nolongerevil/routes/control/scan.py:109`. Neither is a server-side
backoff policy.

### Deliberate or incidental

**Incidental.** The absence of 5xx on transport is not defended by any comment, and
the 500 that an exception produces is aiohttp's default rather than a choice. The
NLE server has no position on 5xx; it simply never means to emit one. What *is*
implicitly deliberate is the shape of the failure it does handle: every anticipated
transport error is a 400, which under contract §18 costs the Thermostat two retries
and no state reset.

### Risk if the Integration gets it wrong

The failure mode is **delay, never corruption**. A 5xx carries no bucket values, so
the Thermostat applies nothing; the cost is the backoff interval, whose length is
unknown (contract §21.2). Concretely:

- A 5xx returned mid-subscribe ends the long-poll early and pushes the Thermostat
  into an unknown backoff. Any setpoint change made in Home Assistant during that
  window is not delivered until the Thermostat comes back, so the room sits at the
  old setpoint and the entity reports state the Thermostat does not have.
- Returning 5xx where the NLE server returns 400 is the more expensive error, because
  400 costs two bounded retries (contract §18) and 5xx costs an unbounded backoff.
- Returning 403 or 404 instead is worse than either: contract §18 has both reset the
  Thermostat's comms state.
- An unhandled exception in the Integration's own handlers produces the same
  uncontrolled 500 the NLE server can produce. The Integration inherits this unless
  it installs error handling the NLE server does not have.

---

## 2. The response shape when an `if_object_revision` guard rejects a write

**What is already settled.** #8 fixed the receipt: `object_revision`,
`object_timestamp` and `object_key`, and never a `value`. Contract §7.2 and
changelog rev 2.4 give the same rule, and omissions §7 records the compare-and-set
semantics. Contract §21.3 is what remains open — the reference calls the response
"implementation-defined" and prescribes neither a status code nor a body shape.
This section fills in the rest without contradicting #8.

### What the NLE server does

The whole guard is `src/nolongerevil/routes/nest/transport.py:845-869`. Verbatim,
the comment that explains it (lines 850-856):

> ```
> # CAS conflict: reject this bucket's write but keep processing
> # the rest.  Return rev/ts/key only — no value echo.  Including
> # value here would overwrite the device's local state (the
> # fields it was trying to PUT) and clear its dirty flags,
> # silently dropping the rejected write with no retry.  Without
> # value, the device keeps its local state, dirty flags survive,
> # and it retries the PUT next cycle with the updated revision.
> ```

Everything #21 asks for beyond #8:

1. **The status code is 200.** There is no separate return for a conflict. The
   handler appends the receipt and continues; the single response for the whole PUT
   is built at `src/nolongerevil/routes/nest/transport.py:951-954` with aiohttp's
   default 200. A conflict is not an HTTP error and carries no `error` key.

2. **The comparison is exact inequality against the stored revision**, not a
   greater-than — `src/nolongerevil/routes/nest/transport.py:846-849`. The guard runs
   only when `if_object_revision` is present; `None` skips it entirely.

3. **A missing record compares as revision 0**
   (`src/nolongerevil/routes/nest/transport.py:848`). So any non-zero
   `if_object_revision` against a bucket the Integration has never stored is a
   conflict, and the receipt returns `object_revision: 0`, `object_timestamp: 0`
   (`src/nolongerevil/routes/nest/transport.py:864-866`). This is the case that #8's
   revision-floor rule is designed to clear in one cycle.

4. **Rejection is per bucket, and the rest of the PUT still applies.** The `continue`
   at `src/nolongerevil/routes/nest/transport.py:869` moves to the next object rather
   than returning. Asserted by
   `tests/test_transport_put.py:113-158`, which puts a conflicting `shared` bucket
   and a clean `device` bucket in one request and requires two receipts back, the
   `shared` one unchanged at revision 5 and the `device` one advanced to 1.

5. **Field order is revision, timestamp, key** — the literal is built in that order
   at `src/nolongerevil/routes/nest/transport.py:862-868`. The ordering rule is stated
   at `src/nolongerevil/routes/nest/transport.py:215-216`: "IMPORTANT: Field order
   matters! object_revision and object_timestamp MUST appear before object_key in the
   JSON, or the device may not apply them correctly." Repeated for the push path at
   `src/nolongerevil/services/subscription_manager.py:213-214`. Contract §7.1 carries
   the same rule.

6. **The conflict receipt carries no `updatedAt`.** The shared formatter adds one
   (`src/nolongerevil/routes/nest/transport.py:223-224`), but the PUT handler does not
   use that formatter — both the success receipt
   (`src/nolongerevil/routes/nest/transport.py:922-926`) and the conflict receipt build
   their own three-key literal. `tests/test_transport_put.py:24` pins the allowed key
   set to exactly those three, and lines 74-105 assert it for the conflict case
   specifically.

7. **Headers are the standard three.** The PUT response goes out with
   `_make_response_headers()` (`src/nolongerevil/routes/nest/transport.py:953`), which
   is `X-nl-service-timestamp`, `X-nl-suspend-time-max` and `X-nl-defer-device-window`
   (`src/nolongerevil/routes/nest/transport.py:288-292`). `X-nl-disable-defer-window`
   is never sent on a PUT — the parameter defaults to `False`
   (`src/nolongerevil/routes/nest/transport.py:279`) and only the chunked subscribe
   path ever passes it.

8. **`base_object_revision` never rejects.** It is logged and dropped
   (`src/nolongerevil/routes/nest/transport.py:871-874`). Matches #8 and contract §5:
   `shared` is the only bucket using `if_object_revision`; everything else uses
   `base_object_revision`, which is informational.

9. **An object with no `value` is skipped before the guard runs**
   (`src/nolongerevil/routes/nest/transport.py:836-840`), so it produces no receipt at
   all. Worth noting because it means the response's object count can be lower than
   the request's, independently of any conflict.

### Deliberate or incidental

**Deliberate**, and among the best-evidenced behaviour in the source. It carries the
longest explanatory comment in the handler, it states the failure mode it prevents,
and it is pinned by three tests. The test module's own header dates the work
(`tests/test_transport_put.py:3-5`):

> ```
> Four bugs were fixed in this handler over 3 days (2026-02-09 through 2026-02-11),
> all variations of the server echoing stale bucket data back to the device. These
> tests cover the invariants that broke.
> ```

The 200 status is the one part that is closer to incidental — nothing comments on it,
it is simply what falls out of treating a conflict as a normal per-bucket outcome
rather than a request-level error. But it is consistent, tested at
`tests/test_transport_put.py:40`, and it is the only status the Thermostat can receive
for a mixed request that also contains successful writes.

### Risk if the Integration gets it wrong

- **Including `value` corrupts state.** The comment above names the mechanism: the
  Thermostat applies the value, clears its dirty flags, and never retries. The write
  the user made on the dial is lost silently. Contract §7.2 and changelog rev 2.4
  record the same, verified against hardware.
- **Returning a 4xx or 5xx instead of 200** routes the Thermostat into the contract
  §18 ladder. 400 costs two retries; 403 or 404 reset its comms state; 5xx triggers
  the unknown backoff of case 1. None of these deliver the fresh revision the
  Thermostat needs in order to retry successfully, so the conflict does not clear.
- **Aborting the whole request on the first conflict** drops the receipts for every
  later bucket in the same PUT. Contract §20 gives the Thermostat's fixed multi-bucket
  ordering, with `shared` — the only bucket that uses `if_object_revision` — late in
  the sequence but ahead of `device`, `where`, `rcs_settings`, `kryptonite` and
  `diagnostics`. A conflict on `shared` would therefore silently strand the telemetry
  buckets behind it.
- **Returning the client's revision instead of the server's** defeats the retry: the
  Thermostat re-sends with the same stale `if_object_revision` and conflicts forever.
  `tests/test_transport_put.py:105` pins this — "server's current, not client's".
- **Wrong field order** may cause the Thermostat not to apply the receipt at all
  (`src/nolongerevil/routes/nest/transport.py:215-216`, contract §7.1). This one fails
  silently and looks like a hung revision.

---

## 3. Conflict reconciliation, given the reference steers it to subscribe

**What the reference says.** Contract §21.4 identifies the tension directly: the
reference's conflict-detection section describes returning current state for
reconciliation, but its rev-2.4 rule forbids `value` in any PUT response, including a
conflict. So the documented reconciliation pattern cannot be used as written. The
contract's own reading is that reconciliation must run through subscribe. The NLE
server confirms this, and its comments record what happened when it did otherwise.

### What the NLE server does

**The PUT path performs no reconciliation whatsoever.** It merges, stores, and returns
receipts. Two dated `NOTE`s at
`src/nolongerevil/routes/nest/transport.py:937-949` record the two mechanisms that
were removed, verbatim:

> ```
> # NOTE: Previously notified long-poll subscribers here with the full merged
> # bucket after every PUT.  This was always redundant (the device already
> # receives the same data in the PUT response) and created a race condition:
> # if TCP delivery of the subscribe chunk was delayed even 1-2 seconds past a
> # schedule transition, the stale target_temperature from the pre-schedule
> # state would overwrite the schedule-set value.  Removed 2026-02-10.
> #
> # NOTE: Previously piggybacked shared.{serial} on every PUT response as a
> # "reliable sync point."  This caused stale target_temperature values from
> # old user commands to be re-pushed to the device after server restarts or
> # eco-exit, overriding the device's schedule-derived setpoint.  The subscribe
> # path already handles pushing newer server data via timestamp comparison,
> # which is the correct mechanism.  Removed 2026-02-09.
> ```

Both are pinned by tests: `tests/test_transport_put.py:219-242` requires that PUTting
only the `device` bucket returns exactly one object, and
`tests/test_transport_put.py:250-273` proves the handler never reads
`subscription_manager` off the application — it passes a plain dict that would
`KeyError` if touched.

The related receipt-shape comment at
`src/nolongerevil/routes/nest/transport.py:916-921` names the same race from the other
direction:

> ```
> # Build response — rev/ts/key only, no value echo.
> # The device already knows what it sent, and the subscribe channel
> # handles server→device pushes.  Echoing the full merged bucket here
> # caused stale target_temperature from the server's stored state to
> # overwrite the device's schedule-derived setpoint (race between
> # HVAC-state PUT and SetTargetTemperature on the device side).
> ```

**Reconciliation therefore happens entirely on subscribe, and only by timestamp.**

1. **Timestamp is the sole authority.** `_is_server_newer`
   (`src/nolongerevil/routes/nest/transport.py:966-986`) compares timestamps with no
   revision tiebreaker: client `0` means "no data" and always loses; server `0` means
   the server has nothing to send; equal timestamps mean already synced. The docstring
   cites the same external rev/ts guide the contract draws on
   (`src/nolongerevil/routes/nest/transport.py:969-970`). Matches contract §8 and #8's
   "the timestamp is the sync authority".

2. **Server newer → push.** The bucket is added to `outdated_objects`
   (`src/nolongerevil/routes/nest/transport.py:509-511`) and written to the chunked
   body immediately (`src/nolongerevil/routes/nest/transport.py:702-708`), with `value`
   included — the subscribe path is the one place a `value` legitimately goes to the
   Thermostat (`src/nolongerevil/routes/nest/transport.py:212-227`).

3. **Client newer → server yields.** The client's value is merged over the stored
   value and saved (`src/nolongerevil/routes/nest/transport.py:517-532`). Worth
   flagging: on this path the server stores the **client's** revision and timestamp
   verbatim (`src/nolongerevil/routes/nest/transport.py:527-528`) rather than minting
   its own, which is the opposite of the PUT path
   (`src/nolongerevil/routes/nest/transport.py:890-903`). Nothing comments on the
   asymmetry — see the incidental note below.

4. **Inline updates on subscribe are a write path.** A client object carrying a
   `value` with revision and timestamp of `0` is an update, not a subscription
   (`src/nolongerevil/routes/nest/transport.py:386-392`), and it takes the same
   change-detection rule as PUT: revision advances only when the merged value really
   differs (`src/nolongerevil/routes/nest/transport.py:456-463`). #8 §2 already carries
   this.

5. **`target_change_pending: false` is always accepted and never bumps the revision**
   (`src/nolongerevil/routes/nest/transport.py:394-416`) — the stored revision and
   timestamp are re-used deliberately at lines 410-411. The comment names the reason:
   "Always accept target_change_pending:false from device to avoid update loops"
   (lines 394-395). #8 §2 carries this too.

6. **Undelivered pushes are buffered and replayed, not dropped.** If the connection
   dies with a chunk in hand, the objects are handed to `store_pending_push`
   (`src/nolongerevil/routes/nest/transport.py:786-791`), buffered
   (`src/nolongerevil/services/subscription_manager.py:146-159`) and replayed onto the
   next subscription's queue
   (`src/nolongerevil/services/subscription_manager.py:100-107`).

7. **The `structure` bucket is force-pushed once per server session**, overriding the
   timestamp comparison. The module-level comment
   (`src/nolongerevil/routes/nest/transport.py:72-75`) is a hardware observation:

   > ```
   > # Devices that have received the structure bucket this server session.
   > # On first connect after server/device restart, we force-send the structure
   > # bucket even if timestamps match, because the device's internal mode may
   > # have reset while the cached timestamp persists in flash.
   > ```

   Applied at `src/nolongerevil/routes/nest/transport.py:605-612` and, for unclaimed
   devices, at lines 634-641. This is the one deliberate exception to timestamp
   authority. Note the caveat #8 §6 already records: in the NLE server's default open
   mode no owner record exists, so the paired branch never runs and its `structure`
   bucket is never created.

8. **Overlapping subscriptions are tolerated, not resolved.** A second subscription
   for the same serial is added alongside the first and merely logged as stale
   (`src/nolongerevil/services/subscription_manager.py:115-126`); the dead connection
   is left to time out (`src/nolongerevil/routes/nest/transport.py:774-779`). Pushes go
   to every live subscription (`src/nolongerevil/services/subscription_manager.py:181-
   194`), so during an overlap the same objects are delivered twice.

### Deliberate or incidental

**Deliberate**, and this is the strongest hardware evidence in the entire source. Two
independent mechanisms were built, observed to corrupt state, and removed on
consecutive days — 2026-02-09 and 2026-02-10 — with the reason written down in each
case and a regression test left behind. The force-push of `structure` (item 7) is
likewise deliberate and hardware-motivated.

Two things in this area are **incidental**:

- The revision/timestamp asymmetry in item 3. Adopting the client's revision verbatim
  on the subscribe merge path is uncommented and untested, and it can move the stored
  revision backwards. It is benign in the NLE server for the reason #8 §5 gives —
  the timestamp is the authority — but it is not a defended design.
- Overlapping-subscription tolerance in item 8. The code detects the condition and
  logs a warning rather than acting on it, which reads as diagnosis rather than
  intent.

### Risk if the Integration gets it wrong

- **Reconciling through the PUT response corrupts state.** This is the 2026-02-09
  removal. Values from an old command get re-pushed after a restart or an eco exit and
  override the Thermostat's schedule-derived setpoint. The user-visible symptom is the
  unit heating or cooling to a setpoint nobody asked for, persisting until the next
  schedule transition.
- **Notifying subscribers after a PUT re-creates the 2026-02-10 race.** The window is
  small — the comment says 1-2 seconds of TCP delay past a schedule transition is
  enough — and it will not show up in unit tests. It is a genuine race, so it will be
  intermittent and blamed on the Thermostat.
- **Using revision rather than timestamp to decide who is newer** breaks after any
  unclean shutdown, because the revision can move backwards while the timestamp
  cannot. #8 §5 already relies on timestamp authority for exactly this.
- **Dropping an undelivered chunk instead of buffering it** loses a push whenever the
  Thermostat's connection dies mid-write — routine on a NAT or a Wi-Fi roam. The
  Integration's entity state and the Thermostat then disagree until something else
  changes the bucket.
- **Never force-pushing `structure`** means eco mode can silently stop working after a
  restart, because the Thermostat's cached timestamp survives in flash while its
  internal mode does not.

---

## 4. `X-nl-defer-device-window` at or beyond the documented ceiling of 3599

**What the reference says.** Contract §21.5: values at or above 3600 are rejected, but
whether the header is silently ignored, the whole response is rejected, or the value
is clamped is unspecified (reference lines 964, 1008).

### What the NLE server does

**It cannot produce the case.** Both defer headers are integers bounded at
configuration load:

- `defer_device_window`, default 15, `ge=0, le=3599` —
  `src/nolongerevil/config/environment.py:74-81`
- `disable_defer_window`, default 60, `ge=0, le=3599` —
  `src/nolongerevil/config/environment.py:82-89`

**The bound fails closed, and it is not a clamp.** `settings = Settings()` runs at
module import (`src/nolongerevil/config/environment.py:201`), so an out-of-range
environment variable raises a pydantic validation error before the server binds a
port. There is no path that clamps an over-large value down to 3599 and continues, and
no path that omits the header instead.

Neither the field descriptions (`src/nolongerevil/config/environment.py:78-81`,
`86-89`) nor the module docstring (`src/nolongerevil/routes/nest/transport.py:46-48`)
explains where 3599 comes from or what the Thermostat does with a larger value. The
descriptions cover meaning and recommended range only — "0 = disabled (immediate PUT
on every change). Recommended: 15-30."

**Where the headers are emitted:**

| Header | Sent on | Where |
|--------|---------|-------|
| `X-nl-defer-device-window` | every non-chunked response — PUT receipts, non-chunked subscribe, transport GET | `src/nolongerevil/routes/nest/transport.py:291`, via `_make_response_headers()` at lines 274, 657, 661, 953 |
| `X-nl-defer-device-window` | every chunked subscribe | `src/nolongerevil/routes/nest/transport.py:687` |
| `X-nl-disable-defer-window` | chunked subscribe **only**, and only when the pushed objects contain temperature fields | `src/nolongerevil/routes/nest/transport.py:677-679`, `689-690` |

The disable-defer trigger set is `target_temperature`, `target_temperature_high`,
`target_temperature_low`, `target_temperature_type` and `hvac_mode`
(`src/nolongerevil/routes/nest/transport.py:307-313`). Note `hvac_mode` is not a bucket
field the Thermostat uses — contract §6 and §19 put the mode in
`target_temperature_type`, which is also in the set. Its presence is harmless and
looks incidental.

The value is always rendered with `str(int)`, so it is a plain decimal string with no
sign, no padding and no unit.

### Deliberate or incidental

Split:

- **The ceiling is deliberate.** An explicit `le=3599` on both fields, applied
  consistently, is a deliberate refusal to emit a value the reference says is
  rejected. That the bound is a hard startup failure rather than a clamp is also a
  choice, though an unexplained one.
- **The device's behaviour at or beyond the ceiling is not found in source.** The NLE
  server never sends such a value, so it has never observed the outcome and records
  no evidence. Contract §21.5 remains open, and the NLE server does not close it.

### Risk if the Integration gets it wrong

Unknown by construction — no source available to this project can say what the
Thermostat does with a header at or beyond 3600. What can be said about the blast
radius:

- The defer window governs only **when the Thermostat sends its PUT** after a local
  change. It carries no bucket values, so a mishandled header cannot write a wrong
  value into a bucket. This case is structurally unlike cases 2 and 3.
- The worst plausible outcome is the whole response being discarded. On a chunked
  subscribe that means a lost push — the same cost as case 1, and the same mitigation
  question.
- A very large accepted value would batch local dial changes for up to an hour, so
  Home Assistant would show a stale temperature while the Thermostat acts on the new
  one. Recoverable, but confusing, and it would look like the Integration had hung.
- `0` is a documented, in-range value meaning "no deferral, PUT on every change"
  (`src/nolongerevil/config/environment.py:80`). It is the safe end of the range, at
  the cost of more requests during a dial turn.
- Because the Integration owns its own configuration surface, the practical question
  #15 faces is whether to bound the value as the NLE server does, clamp it, or omit
  the header — not what the Thermostat does with an out-of-range one.

---

## 5. The fallback chain when the wiring cannot serve the requested HVAC mode

**What the reference says.** Contract §19 gives the mode table and the wiring each mode
requires: `heat` needs `can_heat`, `cool` needs `can_cool`, `range` needs both,
`emergency` needs `has_emer_heat`. If the server pushes a mode the wiring cannot
support, the Thermostat "silently falls back, preferring heat over cool" (reference
line 1800). Contract §21.6 records the gap: the exact chain for all combinations —
notably `range` on heat-only wiring — is not documented.

### What the NLE server does

**It prevents the situation instead of observing it.** The control-API `set_mode`
handler validates against the reported wiring and raises rather than sending —
`src/nolongerevil/routes/control/command.py:137-153`:

| Requested | Guard | Line |
|-----------|-------|------|
| `heat` | rejected unless `can_heat` | `command.py:146-147` |
| `cool` | rejected unless `can_cool` | `command.py:148-149` |
| `range` | rejected unless `can_heat` **and** `can_cool` | `command.py:150-151` |
| `emergency` | rejected unless `has_emer_heat` | `command.py:152-153` |

The intent is stated in the module docstring — "Mode commands check device
capabilities (can_heat, can_cool, has_emer_heat)"
(`src/nolongerevil/routes/control/command.py:28`).

**The wiring flags are read from `shared` first, then `device`**
(`src/nolongerevil/routes/control/command.py:143-145`), matching contract §22's rev-2.6
correction that `can_heat`/`can_cool` are shared-only. The same precedence appears in
the status route (`src/nolongerevil/routes/control/status.py:100-104`) and in MQTT
discovery (`src/nolongerevil/integrations/mqtt/home_assistant_discovery.py:52-60`),
where the advertised mode list is assembled from the same flags.

**Two gaps in the guard, neither commented:**

1. **The defaults are permissive.** `can_heat` and `can_cool` default to `True` and
   `has_emer_heat` to `False` when the flag is absent from both buckets
   (`src/nolongerevil/routes/control/command.py:143-145`).
2. **The guard is skipped entirely when neither bucket exists** — the whole block is
   inside `if device_obj or shared_obj:`
   (`src/nolongerevil/routes/control/command.py:140`). Before the Thermostat has first
   reported, any mode is sent unchecked.

**The transport path validates nothing.** Both the PUT merge
(`src/nolongerevil/routes/nest/transport.py:876-877`) and the subscribe merge
(`src/nolongerevil/routes/nest/transport.py:420-421`) are generic dictionary merges
with no field-level knowledge. A mode arriving by any route other than `set_mode`
reaches the Thermostat unexamined.

**Mode vocabulary.** `NestMode` is `off`, `heat`, `cool`, `range`, `emergency`
(`src/nolongerevil/lib/consts.py:75-82`) — matching contract §19. The API accepts
`heat-cool`, `range` and `auto` and folds all three to `range`
(`src/nolongerevil/lib/consts.py:95-103`). Going the other way, `emergency` is
presented to Home Assistant as `heat` with the comment "Emergency heat is a heating
mode" (`src/nolongerevil/lib/consts.py:111`) — a presentation choice in NLE's own MQTT
layer, not a device fallback. `eco` is explicitly rejected as a mode and routed to
`manual_eco_all` instead (`src/nolongerevil/routes/control/command.py:119-126`),
consistent with contract §6 and #8 §6.

**No observation of the fallback exists.** There is no comment, no test, and no log
line anywhere in the source describing what the Thermostat does on receiving an
unservable mode. `tests/` contains no mode-fallback test. The reference's one line
remains the only evidence available to this project.

### Deliberate or incidental

Three-way split, and this case is the clearest illustration of why #21 draws the
distinction:

- **The capability guard is deliberate** — four explicit checks, distinct error
  messages, and a docstring stating the intent.
- **The permissive defaults and the skipped-when-empty branch are incidental.** They
  are unexplained, and they mean the guard does not hold in exactly the state where
  it matters most: a freshly adopted Thermostat that has not yet reported its wiring.
- **The fallback chain itself is not found in source.** By guarding upstream, the NLE
  server ensures it never learns the answer. Mimicry has nothing to copy here.

### Risk if the Integration gets it wrong

The failure mode is **lasting divergence, not corruption of a bucket**.

- The Thermostat falls back *silently* (contract §19). No error, no rejected write.
  Home Assistant's climate entity reports the mode it asked for while the unit runs a
  different one, and nothing in the protocol reports the discrepancy back. The
  Integration cannot detect this from the PUT receipt, because the receipt carries no
  value (case 2) — it would only surface on a later subscribe, if the Thermostat
  writes the fallback mode back into `shared`, which is itself undocumented.
- `range` on single-stage wiring is the sharpest case, and precisely the one contract
  §21.6 flags as undocumented. In `range` the setpoint lives in
  `target_temperature_high`/`_low` rather than `target_temperature` (contract §19), so
  after a fallback to `heat` it is not defined which of the two the Thermostat uses.
  The room can end up at the cooling setpoint while heating.
- `emergency` without `has_emer_heat` is the most expensive to get wrong for reasons
  beyond the mode: contract §19 records that emergency heat saves and disables
  learning, saves and disables auto-away, and blocks preconditioning, restoring all of
  it on exit. A mode that silently fails to take may leave that save/restore state
  ambiguous.
- Copying the NLE server's guard verbatim carries its permissive defaults with it.
  Treating absent `can_heat`/`can_cool` as `True` allows exactly the unservable push
  the guard exists to prevent, during first adoption. Whether to default permissive,
  default closed, or refuse to offer a mode until the wiring is known is a #15
  question — but it is a question the NLE server answers only by accident.

---

## 6. Clock-skew correction

**What the reference says.** Contract §21.7: the Thermostat "automatically corrects its
clock if the skew between device time and server time exceeds approximately 10
minutes" (reference line 1051). The threshold is given only as approximate. Contract
§21.13 adds that the Thermostat's tolerance for rounding and truncation is not
documented beyond that ~10-minute correction and the 600-second eco window.

### What the NLE server does

**One thing, unconditionally: it stamps every transport response with the current
time.** `X-nl-service-timestamp` is set to `int(time.time() * 1000)` at:

- `src/nolongerevil/routes/nest/transport.py:289` — inside `_make_response_headers()`,
  so on transport GET (line 274), non-chunked subscribe (lines 657, 661) and every PUT
  receipt (line 953)
- `src/nolongerevil/routes/nest/transport.py:685` — the chunked subscribe header block

Both compute the value at response-build time, so it is always the server's current
wall clock in milliseconds, never a cached or replayed value.

**There is nothing else.** A sweep for `skew` and `clock` across the source returns
only two MDI icon names in the MQTT discovery layer
(`src/nolongerevil/integrations/mqtt/home_assistant_discovery.py:356`, `485`, `506`) and
the `set_away` docstring below. Specifically absent:

- no comparison of a device-reported time against the server's
- no threshold constant of any kind
- no correction, warning, or log line when the two disagree
- no reading of any device clock field on the inbound path — the PUT and subscribe
  handlers merge values generically
  (`src/nolongerevil/routes/nest/transport.py:876-877`, `420-421`) and never inspect a
  timestamp inside a bucket value

Note the distinction that matters: `object_timestamp` is the **sync** timestamp, minted
by the server (`src/nolongerevil/routes/nest/transport.py:463`, `899-903`), and it is
the sync authority per contract §8 and #8. It is not a device clock reading, and the
NLE server never treats it as one.

**The one deliberate, hardware-derived clock fact is in `set_away`.** Verbatim,
`src/nolongerevil/routes/control/command.py:165-168`:

> ```
> Uses manual_eco_all instead of the away field because the firmware's
> schedule preconditioning reverts auto-eco (triggered by away=true) but
> respects manual-eco. The manual_eco_timestamp must be within 600 seconds
> of the device clock or the firmware silently ignores the change.
> ```

Its mitigation is minimal: stamp `int(time.time())` at send time
(`src/nolongerevil/routes/control/command.py:178-181`) and rely on the server's clock
being right. Note the unit — **seconds** here, against milliseconds in the transport
headers. Contract §7.7 gives the same split, and contract §22 rev 2.7 records the
hardware observation behind it: `manual_eco_all: false` can be silently dropped by
that 600-second validation, observed as an eco-exit failure.

### Deliberate or incidental

Split, and in an unusual direction:

- **The `X-nl-service-timestamp` header is incidental** as a clock-correction
  mechanism. It is emitted unconditionally with no comment connecting it to the
  Thermostat's clock, it is not listed among the protocol-compliance notes in the
  module docstring (`src/nolongerevil/routes/nest/transport.py:44-48`), and no code
  reacts to skew. The NLE server supplies the raw material for the Thermostat's
  ~10-minute self-correction without appearing to know it.
- **The 600-second `manual_eco_timestamp` window is deliberate** and hardware-derived:
  a written-down Firmware behaviour, corroborated independently by the reference's own
  changelog. This is the only place the NLE server acknowledges that the Thermostat
  has a clock of its own.
- **The threshold in contract §21.7 is not found in source.** The NLE server neither
  measures nor confirms it. It remains "approximately 10 minutes" on the reference's
  authority alone.

### Risk if the Integration gets it wrong

The failure mode is **the silent no-op** — the most expensive kind to debug, because
nothing reports it.

- **A stale `manual_eco_timestamp` is silently discarded.** If the Integration reuses a
  cached timestamp, stamps it at scheduling time rather than send time, or writes
  milliseconds where seconds are expected (contract §7.7), the eco write does nothing
  and returns no error. Eco enter or exit appears to succeed in Home Assistant and
  does not happen. Milliseconds-for-seconds is the likely mistake, because the
  transport layer uses milliseconds everywhere else.
- **A wrong host clock has two effects at once**, and they compound. Every eco write
  falls outside the 600-second window, so eco stops working entirely; and once the
  service timestamp is off by more than ~10 minutes, the Thermostat corrects its own
  clock to the Integration's, moving every schedule transition by the error. The
  symptom is a Thermostat that heats at the wrong times *and* ignores eco, with no
  obvious common cause.
- **Direction matters for the correction.** The Thermostat trusts the Integration.
  Home Assistant hosts are normally NTP-synced, so the realistic risk here is not a
  wrong clock but a *stale* timestamp — a cached value, a queued command replayed
  after a delay, or a timestamp computed once at entity setup.
- **A replayed `X-nl-service-timestamp`** — for example a value captured once and
  reused on a buffered push (case 3, item 6) — would tell the Thermostat that time had
  stopped. The NLE server avoids this only because both call sites compute the value
  inline at response-build time.

---

## 7. The `eco` field's type, and which eco-exit path to use

**What the reference says.** Contract §21.9 calls this ambiguous: the Thermostat
reports `eco_mode` as "a read-only JSON string" containing a nested JSON object, while
the reference's exit-eco example shows `"eco": {"mode": "schedule", ...}` as a nested
object. Whether the server writes `eco.mode` as a nested object or as a JSON string
containing an object is left open.

### 7.1 The two fields are distinct, and the contract already says so

The proposal that `eco` and `eco_mode` are two different fields holds up against every
piece of evidence available in this repo:

| | `eco` | `eco_mode` |
|---|---|---|
| Bucket | `device` | `device` |
| Access class | **Special** — one of the 23 (contract §4, line 400, which names `eco` explicitly as an example of "Custom processing") | Device-only, read-only (contract §21.9) |
| Type | Object, with sub-fields `mode`, `touched_by`, `mode_update_timestamp`, `touched_user_id` | JSON **string** whose `mode` key carries `"schedule"`, `"manual-eco"` or `"auto-eco"` |
| Direction | Server **writes** it — contract §14 Exit step 3 pushes `eco.mode: "schedule"` to the device bucket | Device **reports** it |
| In a standard PUT? | **No** — contract §4 marks all 23 Special fields "In PUT? No" | Yes (device-only fields do appear in PUT, per contract §4) |

So §21.9's ambiguity largely dissolves: the Integration **writes the `eco` object** and
**reads the `eco_mode` string**, and comparing their types was comparing two different
fields. Contract §14's exit sequence and contract §4's Special-field row are mutually
consistent on `eco` being a written object.

**The limit of what I can verify.** The protocol reference itself
(`NEST_CLOUD_PROTOCOL_REFERENCE.md`) is **not in this repo** — only the distillation on
branch `research/protocol-reference` is. I can corroborate the split from the contract's
§4, §14 and §21.9, which independently record the object form and the string form, but I
**cannot** confirm the specific reference line numbers 1944, 2210-2218 or 2258. Someone
with the reference open should spot-check those before the split is treated as closed.

### 7.2 What the NLE server does: it never writes `eco`

This is the decisive finding, and it is a negative one.

**No write path produces an `eco` key.** The complete command surface is eight handlers
(`src/nolongerevil/routes/control/command.py:457-466`) routed to four buckets
(`src/nolongerevil/routes/control/command.py:469-478`):

| Command | Bucket | Writes |
|---|---|---|
| `set_temperature` | `shared` | setpoints, `target_change_pending` |
| `set_mode` | `shared` | `target_temperature_type` |
| `set_away` | `structure` | `manual_eco_all`, `manual_eco_timestamp` |
| `set_fan` | `device` | fan timer fields |
| `set_eco_temperatures` | `device` | `away_temperature_high` / `_low` |
| `set_schedule` | `schedule` | full replacement |
| `set_schedule_mode` | `shared` | schedule mode |
| `set_device_setting` | `device` | 36 whitelisted fields |

None emits `eco`. The `DEVICE_SETTING_WHITELIST`
(`src/nolongerevil/routes/control/command.py:375-456`, 36 entries) contains no `eco`, no
`eco_mode` and no `leaf`. Note that `set_eco_temperatures`
(`src/nolongerevil/routes/control/command.py:224-250`) is a false friend — it writes
`away_temperature_high` and `away_temperature_low`, which are the eco *temperatures* of
contract §14, not the `eco` object.

**The transport layer cannot supply the gap.** Both merge paths are generic dictionary
merges with no field-level knowledge (`src/nolongerevil/routes/nest/transport.py:876-877`
for PUT, `420-421` for subscribe). Whatever JSON type the Thermostat sends for `eco` is
stored verbatim and served back unchanged. The NLE server has no opinion about the type
because it never constructs one.

**It only reads `eco`, at three sites, all in its own application layer:**

| Site | Reads | Guard |
|---|---|---|
| `src/nolongerevil/routes/control/status.py:113-116` | `eco["mode"]`, published as the status field named `eco_mode` | `isinstance(..., dict)` else `None` |
| `src/nolongerevil/integrations/mqtt/helpers.py:239-240` | `eco["mode"] == "manual-eco"` → the ECO preset | `isinstance(eco, dict)` |
| `src/nolongerevil/integrations/mqtt/helpers.py:324-326` | `eco["leaf"]` → eco active, falling back to the top-level `leaf` field | `isinstance(eco, dict)` |

**How much do those guards prove? Very little, and it is worth being exact.** They
establish that the NLE server expects a dict when reading state the *Thermostat* sent.
They are not evidence about what a *server* should write, because the NLE server never
writes it. And they are not proof that a string ever arrives: an `isinstance` guard on
an untyped opaque bucket value is ordinary defensive coding, and there is no comment and
no test in the source distinguishing the two cases. What they do establish is the
failure mode: if `eco` arrived as a JSON string, all three guards fall through
silently — the preset reports HOME, `is_eco_active` falls back to the top-level `leaf`
field, and the status route reports `eco_mode: null`. No error, no log line.

One naming trap worth recording: the NLE server's status route calls its **output**
field `eco_mode` while sourcing it from the `eco` object's `mode` sub-key
(`src/nolongerevil/routes/control/status.py:113-116`). It never reads a bucket field
literally named `eco_mode`. That is a collision in NLE's presentation layer, not
evidence about the wire, and it is probably one origin of the conflation in §21.9.

### 7.3 Which eco-exit path the NLE server uses

Contract §14 Exit says push all three together: `manual_eco_all: false` +
`manual_eco_timestamp` on `structure`, `away: false` on `structure`, and
`eco.mode: "schedule"` on `device` — the third annotated "most reliable path -- no
timestamp validation, no readiness dependency", sourced to changelog rev 2.9.

**The NLE server pushes one of the three.** `set_away`
(`src/nolongerevil/routes/control/command.py:178-181`) returns exactly
`manual_eco_all` and `manual_eco_timestamp`, routed to `structure.{id}`
(`src/nolongerevil/routes/control/command.py:472`, resolved at lines 520-528) and pushed
to subscribers at line 562.

- It **never** writes `eco.mode: "schedule"` — the rev-2.9 path.
- It **never** writes `away: false`, and this omission *is* deliberate and
  hardware-derived. The docstring
  (`src/nolongerevil/routes/control/command.py:165-168`, quoted in full in case 6)
  explains that the Firmware's schedule preconditioning reverts auto-eco triggered by
  `away=true` but respects manual-eco. The same reasoning is repeated at
  `src/nolongerevil/integrations/mqtt/helpers.py:220-222`.
- It therefore relies **solely** on `manual_eco_all: false` — precisely the path
  changelog rev 2.7 records as silently droppable by the 600-second timestamp
  validation, observed on hardware as an eco-exit failure.

That is the sharp point of this case: on eco exit, mimicking the NLE server means
adopting the one path the reference documents as unreliable and skipping the one it
documents as most reliable.

### 7.4 The seconds-versus-milliseconds trap

`manual_eco_timestamp` is written as `int(time.time())` — Unix **seconds**
(`src/nolongerevil/routes/control/command.py:180`). That is correct per contract §7.7
and §14.

The trap is the proximity of the other convention. Inside the very function that stores
the result, `object_timestamp` is `int(time.time() * 1000)` — **milliseconds**
(`src/nolongerevil/routes/control/command.py:546` and `553`), matching the transport
layer (`src/nolongerevil/routes/nest/transport.py:463`, `899-903`). So a seconds value
and a milliseconds value are produced about 360 lines apart and land in the same write,
and **nothing in the source marks the distinction**. The only nearby warning is the
600-second note in the `set_away` docstring, which states the window without naming the
unit hazard.

Contract §7.7 lists the full split: `object_timestamp` in milliseconds,
`manual_eco_timestamp` and `touched_at` in seconds.

### Deliberate or incidental

Four-way, and this case needs the distinction more than any other:

- **Writing `eco`: not found in source.** The NLE server never does it. It offers no
  evidence on the object-versus-string question, and mimicry has nothing to copy.
- **Reading `eco` as a dict: incidental.** Three defensive guards, uncommented,
  untested, in the application layer that #6 already ruled out of scope. Weak evidence
  that the Thermostat sends an object, and no evidence about what to write.
- **Exiting eco via `manual_eco_all` alone: incidental, by omission.** No comment says
  the `eco.mode` path was considered and rejected; it is simply absent. This is an
  accident of the NLE server's feature set, not a judgement about reliability — and the
  reference's own changelog contradicts it.
- **Avoiding the `away` field, and using seconds for `manual_eco_timestamp`:
  deliberate.** Both are written down, and the first is hardware-derived.

### Risk if the Integration gets it wrong

All the failure modes here are **silent**, which is what gives this case teeth.

- **Wrong type on `eco`.** If `eco` must be an object and the Integration writes a JSON
  string (or the reverse), the write is either ignored or misparsed. Because §4 marks
  `eco` a Special field with custom processing, there is no reason to expect a
  well-formed rejection — and the PUT receipt carries no `value` (case 2), so the
  Integration cannot detect the failure from the response. The Thermostat stays in eco,
  holding `away_temperature_high`/`_low` instead of the schedule setpoint, indefinitely.
- **Writing `eco` in a standard PUT at all.** Contract §4 marks all 23 Special fields
  "In PUT? No". How the Integration is *meant* to write `eco` is therefore itself
  unresolved: contract §14 Exit plainly instructs pushing `eco.mode` to the device
  bucket, which on the server-to-device direction is a subscribe push, not a PUT — the
  Thermostat PUTs to the Integration, and the Integration pushes on subscribe (case 3).
  Read that way there is no contradiction: "not in PUT" describes the device-to-server
  direction, and the server writes `eco` the same way it writes any other bucket field,
  by pushing the merged `device` bucket on the subscribe channel. **This reading is
  inference, not something the sources state.** It should be confirmed before build.
- **Copying the NLE server's exit path** inherits the rev-2.7 failure: eco exit silently
  dropped when `manual_eco_timestamp` falls outside 600 seconds of the Thermostat's
  clock. Combined with case 6, a wrong or stale host clock makes eco exit fail *every
  time*, with the Integration reporting success.
- **Milliseconds for `manual_eco_timestamp`** puts the timestamp roughly 55,000 years
  ahead, so it fails the 600-second window on every attempt. Eco never exits. This is
  the single easiest error to make in this whole document, because every other timestamp
  in the protocol is milliseconds.
- **Reading `eco_mode` as though it were an object**, or `eco` as though it were a
  string, gives an entity that reports the wrong preset. Less severe than the write
  errors — it misreports rather than misacts — but it would mask a genuine eco failure,
  since Home Assistant would show whatever the misparse produced rather than the
  Thermostat's real state.

---

## Evidence bearing on #15

Laid out, not decided. #15 chooses between mimicking the NLE server and taking the
most permissive behaviour that cannot corrupt Thermostat state. The seven cases do not
divide evenly, and the useful axis is what each failure actually costs.

**Where mimicry has something to copy, and the copy is well-evidenced:**

- Case 2 and case 3 are deliberate, commented, tested, and — in case 3 — dated to
  specific corrections against real hardware on 2026-02-09 and 2026-02-10. The 600
  second window in case 6 is the same kind of fact. These are the cases where the NLE
  server paid for the knowledge.

**Where mimicry has nothing to copy:**

- Case 1: the NLE server has no 5xx policy; its only 5xx on transport is an unhandled
  crash.
- Case 4: it structurally cannot emit the value in question, so it has never observed
  the outcome.
- Case 5: it guards upstream precisely so the case never arises, and therefore records
  no fallback behaviour.
- Case 6: the correction threshold is unmeasured; only the eco window is known.
- Case 7: it never writes `eco`, so it has no position on the type at all.

**Where copying the NLE server would import an accident:**

- Case 5's permissive `can_heat`/`can_cool` defaults, and the guard being skipped
  before the Thermostat has reported.
- Case 3's subscribe-path adoption of the client's revision verbatim, which can move
  the stored revision backwards. Benign under #8's timestamp authority, but not a
  defended design.
- Case 1's lack of any error middleware, which turns any Integration bug into an
  uncontrolled 500 on a transport Route.
- Case 7's eco-exit path. This is the one place where mimicry is not merely uninformative
  but actively contradicted by the reference: the NLE server uses only
  `manual_eco_all: false`, which changelog rev 2.7 records as silently droppable, and
  never the `eco.mode: "schedule"` path rev 2.9 records as most reliable.

**What "cannot corrupt Thermostat state" separates:**

| Failure mode | Cases | Character |
|---|---|---|
| Writes a wrong value into a bucket | 2 (if `value` is echoed), 3 (if reconciled via PUT) | Corrupting. The Thermostat applies it as authoritative and clears its dirty flags. Recovery needs another correct write. |
| Delays or loses a push | 1, 4 | Not corrupting. Costs freshness; self-heals on the next successful cycle. |
| Diverges display from reality | 5 | Not corrupting at the bucket level, but persistent and undetectable from the protocol. |
| Silently does nothing | 6, 7 | Not corrupting. The write is dropped, not misapplied — but it reports success, and in case 7 it leaves the Thermostat stuck in eco at away temperatures. |

Three facts cut across the principle and are worth putting in front of the decision.

First, the corrupting failures are exactly the two cases where the NLE server is
deliberate — so on cases 2 and 3, mimicry and "cannot corrupt state" point the same
way, and the choice is not live.

Second, the cases where the two principles could diverge — 1, 4 and 5 — are precisely
the ones where the NLE server is silent, which means "mimic the NLE server" has no
content there and the second clause decides by default. #15 may find that the principle
only has to do real work on case 5, where a permissive reading (send the mode, let the
Thermostat fall back) and a conservative reading (refuse the mode) both avoid corruption
but differ in whether Home Assistant ends up lying about the state of the unit.

Third, case 7 does not fit either clause, and #15 should notice that. Mimicry points at
a path the reference says is unreliable; "most permissive that cannot corrupt state"
does not discriminate, because neither eco-exit path corrupts anything — both either
work or silently do nothing. The deciding consideration there is reliability, which is a
third criterion the principle as drafted does not contain. Belt-and-braces — pushing all
three fields of contract §14's exit sequence — is available and is what the reference
actually instructs, but it is a choice #15 has to make rather than one either clause
makes for it.
