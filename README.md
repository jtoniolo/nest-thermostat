# nest-thermostat

Getting a **Nest Learning Thermostat gen 2** into Home Assistant as a local-only device,
after Google shut off the cloud for gen 1 and gen 2 on 25 October 2025.

The intended deliverable is a **Home Assistant custom integration** that speaks the
thermostat's protocol directly. Nothing is implemented yet.

## Status

| | |
|---|---|
| Research | Done — see `reference/PLAN.md` |
| Thermostat flashed | No |
| Integration | Not started |

## Decisions

These override anything in `reference/PLAN.md`, which predates them.

- **Build our own server as an HA custom integration.** Native entities, no MQTT hop,
  no second container.
- **We are not running NoLongerEvil's server.** Not as a baseline, not as a fallback,
  not to capture traffic. To get ground truth on what the device actually sends, have
  our own server log raw requests from its first boot; that is the same capture
  without a second container and an MQTT hop.
- **His server is a protocol reference only — no code is copied from it.** Read it to
  understand what the spec leaves out, then write our own implementation. Its licence
  would permit copying with attribution, but reading-not-copying avoids the
  attribution bookkeeping entirely and keeps the codebase ours.
- **No ESPHome wire tap.** Rejected outright. Not building an ESP device for this.
  The `esphome/` config that used to live here has been deleted.
- **No Sett replacement board.** Staying on the Nest hardware.

The flash itself is unavoidable and unchanged: NoLongerEvil firmware over USB is the
only way in. That is the firmware, not the server — the two decisions are independent.

- **We use NLE's firmware as-is and do not rebuild, fork, or patch it.** The
  integration is a client of it. Rejecting NLE's *server* says nothing about the
  firmware; the device needs it to talk to anything but Google. Practically: the
  port-8080 settings API and the endpoint redirect are NLE additions we depend on,
  and where a firmware build deviates from the docs we adapt on our side, not theirs.

- **Support gen 1 as well as gen 2.** NLE lists both as fully supported (gen 3 in
  development), and the protocol is generation-agnostic — one set of endpoints, one
  bucket model, with the device model carried as an ordinary field. So gen 1 costs us
  nothing structurally.

  The rule this implies: **no branching on generation, and no hardcoded model string.**
  Derive entities from the capabilities the device actually reports, so a unit with
  fewer wire terminals simply yields fewer entities. That is less code than a
  generation switch, and it is what would make gen 3 work for free.

  Scope honestly: with only a gen 2 on hand, the goal is *don't preclude gen 1*, not
  *verified gen 1 support*.

  Note the gen 1 **flash** is much harder than gen 2's — mini USB, and it needs the
  case opened, the battery removed, and contacts bridged with tweezers while the
  loader runs. `PLAN.md`'s "no soldering, no opening the case" is gen 2 only.

  Unresolved: the model strings disagree across sources — `PLAN.md` says
  `Display-2.8`, the protocol spec's examples are `Diamond-2.6` / `Flintstone-4.0`,
  NLE's docs describe a display model of "2.8" or "1.12". Probably two different
  naming systems. It resolves itself once a real `/entry` hits our log. Another
  reason to key no logic off it.

## Layout

```
CONTEXT.md            Glossary. Source of truth for what each term means.
reference/            Research materials. Read-only in spirit — nothing here is code we ship.
  NoLongerEvil-SelfHosted/
                      Reference clone of codykociemba/NoLongerEvil-SelfHosted (MIT),
                      gitignored — re-clone it, never edit it. Protocol reference
                      ONLY: read it to learn what the spec omits (weather_url,
                      upload_url, pro_info_url, /info), then write our own. No code
                      is copied from it. Protocol core is
                      src/nolongerevil/routes/nest/transport.py.
  PLAN.md             The original research doc. AI-generated, unverified, superseded in parts.
  scripts/
    00-preflight.sh   Pre-flash checks: host/libusb/udev, port scan, settings checklist.
                      Still current — independent of any server decision.
    10-verify.sh      Post-flash verification. Only the manual checklist at the bottom
                      survives; the curl/MQTT half targeted NLE's server and is dead.
```

The integration will land in `custom_components/nest_local/` when it starts.

## Credits

This project would not be possible without:

- **[Cody Kociemba](https://github.com/codykociemba)** — the
  [NoLongerEvil firmware](https://github.com/codykociemba/NoLongerEvil-Thermostat),
  which is what makes a cloud-abandoned thermostat reachable at all, and the
  [self-hosted server](https://github.com/codykociemba/NoLongerEvil-SelfHosted), read
  here as a protocol reference.
- **[cjserio](https://github.com/cjserio)** — the
  [Nest cloud protocol reference](https://github.com/cjserio/nest-thermostat-protocol-docs),
  documented against real hardware.

This is an independent implementation. No code is copied from either project.

## License

MIT — see `LICENSE`.

## Provenance

Everything under `reference/` was produced by Claude in a research session. It is a
survey, not a verified spec, and it was not reviewed against hardware. Treat its
factual claims as leads to check, and its recommendations as options that were
considered — several of which were rejected, above.

Real sources to build from, none of them vendored here yet:

- `cjserio/nest-thermostat-protocol-docs` — the protocol reference
- `codykociemba/NoLongerEvil-SelfHosted` — MIT, covers what the spec doesn't
  (`weather_url`, `upload_url`, `pro_info_url`, `/info`)
- `emulated_hue` in HA core — the AppRunner/TCPSite pattern for an integration
  that owns a port
