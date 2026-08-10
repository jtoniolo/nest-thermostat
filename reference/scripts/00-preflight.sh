#!/usr/bin/env bash
# Preflight checks before flashing a Nest Learning Thermostat gen 2.
# Run on the Linux/macOS machine you will flash from.
#
#   ./00-preflight.sh <thermostat-ip> [mqtt-broker-ip]
#
# Nothing here touches the thermostat's settings. It only looks.

set -uo pipefail

NEST_IP="${1:-}"
MQTT_IP="${2:-}"
OUT="preflight-$(date +%Y%m%d-%H%M%S)"

if [[ -z "$NEST_IP" ]]; then
  echo "usage: $0 <thermostat-ip> [mqtt-broker-ip]"
  exit 1
fi

mkdir -p "$OUT"
echo "Saving everything to ./$OUT/"
echo

pass() { echo "  OK    $*"; }
warn() { echo "  WARN  $*"; }
fail() { echo "  FAIL  $*"; }

# ---------------------------------------------------------------- host checks
echo "== Your machine =="
case "$(uname -s)" in
  Linux)  pass "Linux. Good." ;;
  Darwin) pass "macOS. Good." ;;
  *)      fail "$(uname -s) is not supported. You need Linux or macOS. Windows and WSL will not work." ;;
esac

command -v docker >/dev/null && pass "docker present" || warn "docker missing (needed for the self-hosted server)"
command -v nmap   >/dev/null && pass "nmap present"   || warn "nmap missing - install it, the port scan below is worth doing"

if [[ "$(uname -s)" == "Linux" ]]; then
  ldconfig -p 2>/dev/null | grep -q libusb-1.0 \
    && pass "libusb-1.0 present" \
    || warn "libusb-1.0 missing: sudo apt install libusb-1.0-0-dev libudev-dev"

  if ls /etc/udev/rules.d/ 2>/dev/null | xargs -I{} grep -l "0451" /etc/udev/rules.d/{} 2>/dev/null | grep -q .; then
    pass "udev rule for TI 0451 found"
  else
    warn "no udev rule for the TI device. Without it you must flash as root."
    echo '        sudo tee /etc/udev/rules.d/99-omap.rules <<<'"'"'SUBSYSTEM=="usb", ATTR{idVendor}=="0451", ATTR{idProduct}=="d00e", MODE="0666"'"'"
    echo '        sudo udevadm control --reload-rules'
  fi
fi
echo

# ------------------------------------------------------------ thermostat scan
echo "== Thermostat at $NEST_IP =="
if ping -c 2 -W 2 "$NEST_IP" >/dev/null 2>&1; then
  pass "responds to ping"
else
  warn "no ping response (it sleeps aggressively - this is normal, carry on)"
fi

if command -v nmap >/dev/null; then
  echo "  scanning common ports..."
  nmap -Pn -p 22,80,443,8080,9543,11095 "$NEST_IP" > "$OUT/nmap-common.txt" 2>&1
  grep -E "^[0-9]+/" "$OUT/nmap-common.txt" | sed 's/^/        /'

  if grep -qE "^8080/tcp\s+open" "$OUT/nmap-common.txt"; then
    echo
    echo "  >>> Port 8080 is OPEN on a stock unit. That is unexpected and interesting."
    echo "  >>> Try:  curl -v http://$NEST_IP:8080/cgi-bin/api/settings"
    echo "  >>> If it answers, there may be a no-flash path. Worth reporting."
    curl -s -m 5 "http://$NEST_IP:8080/cgi-bin/api/settings" > "$OUT/port8080.txt" 2>&1 || true
  fi

  echo "  full scan running in background -> $OUT/nmap-full.txt (takes a few minutes)"
  nohup nmap -Pn -p- "$NEST_IP" > "$OUT/nmap-full.txt" 2>&1 &
else
  warn "skipping port scan, nmap not installed"
fi

# MAC / vendor, useful for the router block later
if command -v arp >/dev/null; then
  arp -n "$NEST_IP" 2>/dev/null | tee "$OUT/arp.txt" | sed 's/^/        /'
fi
echo

# ------------------------------------------------------------------ mqtt check
if [[ -n "$MQTT_IP" ]]; then
  echo "== MQTT broker at $MQTT_IP =="
  if command -v nc >/dev/null && nc -z -w3 "$MQTT_IP" 1883 2>/dev/null; then
    pass "port 1883 reachable"
  else
    warn "cannot reach $MQTT_IP:1883"
  fi
  echo
fi

# ------------------------------------------------------------------- reminders
cat > "$OUT/RECORD-THESE-BY-HAND.md" <<'EOF'
# Write these down from the thermostat before you flash

Menu > Settings > Technical Info, and Settings > Equipment.

- [ ] Serial number
- [ ] Firmware version
- [ ] Wires connected (R, Rh, Rc, W, W2, Y, Y2, G, C, O/B) - photograph the base
- [ ] System type (conventional / heat pump, gas / electric, stages)
- [ ] O/B setting (O or B)
- [ ] Heat and cool setpoints, right now
- [ ] Full schedule - photograph every day
- [ ] Safety temperature settings
- [ ] Fan timer settings
- [ ] Battery voltage (Technical Info > Power)

Photograph every screen. You cannot get these back after the flash.
EOF

echo "== Next =="
echo "  1. Fill in $OUT/RECORD-THESE-BY-HAND.md. Photograph every screen."
echo "  2. Leave the thermostat on the wall for an hour to charge."
echo "  3. Have our integration running and listening BEFORE flashing."
echo "  4. Then flash."
echo
echo "Done. Results in ./$OUT/"
