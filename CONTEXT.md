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
The base URL the Integration tells the Thermostat to call back on. Distinct from the Bind address because what we listen on and what is reachable from the Thermostat need not match.
_Avoid_: "our address", "the endpoint" (that is the Thermostat's copy of this value).

**Settings API**:
The small HTTP API the Firmware serves on the Thermostat itself, used to read and set its Endpoint.
_Avoid_: "the device API", "the local API".

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
