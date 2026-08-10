#!/usr/bin/env bash
# Run after flashing and pointing the thermostat at your server.
#
#   ./10-verify.sh <server-ip> <mqtt-broker-ip> [mqtt-user] [mqtt-pass]

set -uo pipefail

SRV="${1:-}"
MQTT="${2:-}"
MU="${3:-}"
MP="${4:-}"

[[ -z "$SRV" ]] && { echo "usage: $0 <server-ip> <mqtt-broker-ip> [user] [pass]"; exit 1; }

pass() { echo "  OK    $*"; }
fail() { echo "  FAIL  $*"; }

echo "== Server =="
curl -s -m 5 "http://$SRV:8000/info" >/dev/null \
  && pass "thermostat API on :8000 answering" \
  || fail "nothing on :8000 - is the container up? docker compose logs"

curl -s -m 5 "http://$SRV:8082/" >/dev/null \
  && pass "control API / web UI on :8082 answering" \
  || fail "nothing on :8082"

echo
echo "== Has the thermostat checked in? =="
curl -s -m 5 "http://$SRV:8082/api/devices" | head -c 2000
echo
echo
echo "  If that is empty, reboot the thermostat: hold the display for 10 seconds."
echo

if [[ -n "$MQTT" ]] && command -v mosquitto_sub >/dev/null; then
  echo "== MQTT (15 seconds) =="
  AUTH=()
  [[ -n "$MU" ]] && AUTH=(-u "$MU" -P "$MP")
  timeout 15 mosquitto_sub -h "$MQTT" "${AUTH[@]}" \
    -t 'homeassistant/climate/#' -t 'nolongerevil/#' -v \
    | head -40
  echo
  echo "  Expect discovery messages under homeassistant/climate/. If you see them,"
  echo "  the climate entity is already in Home Assistant."
fi

echo
echo "== Then check by hand =="
echo "  - climate entity in HA shows the right room temperature"
echo "  - changing the setpoint in HA moves the dial on the wall"
echo "  - turning the dial on the wall updates HA"
echo "  - pull the server's network cable: the thermostat must keep heating on schedule"
echo "  - reboot HA: the thermostat must keep heating on schedule"
