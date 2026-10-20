# Nest thermostat

Bringing a cloud-abandoned Nest Learning Thermostat into Home Assistant as a local-only
device. This glossary is the source of truth for what each term means; decisions live in
`README.md` and research in `reference/`.

## Language

### Parties

**Thermostat**:
The physical Nest Learning Thermostat on the wall. Gen 1 or gen 2.
_Avoid_: "the Nest" (ambiguous with the brand and the deleted Google account), "the display" (that is one part of it), "the device" when a broker or ESP board is also in play.

**Firmware**:
The NoLongerEvil build running on the Thermostat. Out of scope for this repo — installed by hand, unchanged, and never built, forked, patched or redistributed here. It is a fixed contract the Integration is compatible with, nothing more.
_Avoid_: "custom firmware" (implies a rewrite), "our firmware" (it is not ours), "NLE" alone (ambiguous with the NLE server).

**Integration**:
The Home Assistant custom integration being built here. It both answers the Thermostat and exposes the entities.
_Avoid_: "our server" (the server is one half of it), "the client" (the Thermostat is the client, not us).

**NLE server**:
Cody Kociemba's self-hosted server. A peer implementation of the same Firmware contract — read as a protocol reference, never run here and never copied from.
_Avoid_: "the server" unqualified, "upstream" (nothing flows from it to us).

### Addressing

**Endpoint**:
The base URL the Thermostat has been told to call. Exactly one exists at a time, and pointing it at the Integration is the only thing ever configured on the Thermostat by hand.
_Avoid_: using this word for an HTTP path — those are Routes.

**Route**:
One of the HTTP paths the Thermostat calls on whatever its Endpoint points to.
_Avoid_: "endpoint", "API" for a single path.

**Bind address**:
The address and port the Integration listens on.
_Avoid_: conflating with the Advertised URL — they are deliberately independent.

**Advertised URL**:
The base URL the Integration tells the Thermostat to call back on. Distinct from the Bind address because what we listen on and what is reachable from the Thermostat need not match. It is always an address on the Thermostat's own network — a host reachable from the internet is never one of these, however the Integration's host is published to the outside world.
_Avoid_: "our address", "the endpoint" (that is the Thermostat's copy of this value), "the public URL" or "the external URL" (those name how humans reach Home Assistant, which the Thermostat never uses).

**Settings API**:
The small HTTP API the Firmware serves on the Thermostat itself, used to read and set its Endpoint.
_Avoid_: "the device API", "the local API".

### Protocol

`PROTOCOL.md` has the full rules for these terms.

**Bucket**:
One named container of Thermostat state, for example `shared.<serial>`. It has an Object key, a Revision, a Timestamp, and a value dict.
_Avoid_: "object" alone (the wire format says `objects`, but this repo says Bucket), "record".

**Object key**:
The name of a Bucket, in the form `<type>.<id>`. The type is `device`, `shared`, `structure`, `user`, `schedule`, or another Bucket type.
_Avoid_: "bucket ID".

**Revision**:
The integer counter of a Bucket. It goes up by one on each change. It is used only for the conditional write on `shared`.
_Avoid_: "version".

**Timestamp**:
The time of the last change to a Bucket, in milliseconds since the Unix epoch. It is the only value that decides which copy of a Bucket is newer. Zero means "no data".
_Avoid_: "updatedAt" (an NLE server field that the Firmware does not need).

**Subscribe**:
The long-poll request from the Thermostat. The Integration holds the response open and sends data on it.
_Avoid_: "poll" alone, "listen".

**Subscription**:
One held Subscribe connection. One Thermostat can have more than one Subscription at the same time.
_Avoid_: "session" (the Thermostat sends a session value, but it is the same for all of its Subscriptions).

**Push**:
Data that the Integration writes on a held Subscription. It wakes the Thermostat.
_Avoid_: "notify", "tickle" (a tickle is an empty close, for shutdown only).

**Put**:
A request from the Thermostat that writes changed fields into Buckets.
_Avoid_: "update" alone.

**Hold time**:
How long the Integration keeps a Subscription open with no data before it closes it. It must be shorter than `X-nl-suspend-time-max`.
_Avoid_: "timeout" alone.

### Identity

**Model string**:
The hardware identifier the Thermostat reports about itself. Treated as opaque data — no behaviour keys off it.
_Avoid_: "generation" (that is the marketing name, not this value), "model" alone.

**Generation**:
The marketing name for a hardware revision — gen 1, gen 2, gen 3. Useful when discussing which units are supported and how hard each is to flash; never a branch in code.
_Avoid_: "version" (ambiguous with Firmware version).

### Process

**The flash**:
The one-time USB procedure that installs the Firmware. A prerequisite for the Integration and a separate piece of work from it.
_Avoid_: "the install", "the hack".
