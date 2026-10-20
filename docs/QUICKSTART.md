# Quick start: the first test of LocalNestThermostat

Use this file as a checklist. Do the steps in order. The terms are from
`CONTEXT.md`.

## Live values

| Item | Value |
|---|---|
| HA instance | `homeassistant.toniolo.ca` |
| Thermostat serial | `02AA01AC10130C7T` |
| Endpoint on the Thermostat | `http://10.0.6.63:9543/entry` (do not change it) |
| Port | `9543` |
| Advertised URL | `http://10.0.6.63:9543` |
| Integration domain | `nest_local` |

## 1. Stop the NLE add-on

- [ ] In HA, go to **Settings > Add-ons**, open the NLE add-on, and click **Stop**.
- [ ] Turn off **Start on boot** for the add-on, so that it does not take port
      9543 again after a restart.

## 2. Install the Integration

Do one of these two procedures.

With HACS:

- [ ] In HACS, open the menu (three dots) and click **Custom repositories**.
- [ ] Add `https://github.com/jtoniolo/nest-thermostat` with the type
      **Integration**.
- [ ] Find **LocalNestThermostat** in HACS and click **Download**.

Without HACS:

- [ ] Copy the folder `custom_components/nest_local/` from this repo to
      `/config/custom_components/nest_local/` on the HA host.

Then:

- [ ] Restart HA.

## 3. Add the Integration

- [ ] Go to **Settings > Devices & services > Add integration**.
- [ ] Search for **LocalNestThermostat** and select it.
- [ ] Set **Port** to `9543`.
- [ ] Set **Advertised URL** to `http://10.0.6.63:9543`.
- [ ] Click **Submit**.
- [ ] If the entry shows "Retrying setup", port 9543 is still in use. Go back
      to step 1.
- [ ] On the integration page, open the menu (three dots) and click
      **Enable debug logging**.

## 4. Reboot the Thermostat

The Integration starts with no data. A reboot makes the Thermostat upload its
full state (`PROTOCOL.md` gap 7).

- [ ] On the Thermostat, go to **Settings > Reset > Restart**.
- [ ] Wait until the Thermostat shows the home screen again (about 2 minutes).

## 5. Check the result

- [ ] Go to **Settings > Devices & services > LocalNestThermostat**. One
      device, "Nest 02AA01AC10130C7T", is present.
- [ ] The climate entity shows the room temperature, the HVAC mode, and the
      target temperature. It does not show "unknown" or "unavailable".
- [ ] The fan binary sensor is present.
- [ ] Change the target temperature in HA. The Thermostat display changes in
      less than 1 minute.
- [ ] Change the target temperature on the Thermostat. The HA entity changes
      in less than 1 minute.
- [ ] Set the HVAC mode in HA. The Thermostat shows the new mode.
- [ ] Set the fan to **on**, then to **auto**. The fan sensor follows.

If a check fails, do not change the Endpoint. Keep the debug log for the
diagnosis.

## 6. Get the debug log

- [ ] On the integration page, click **Disable debug logging**. HA then
      downloads the log file.
- [ ] Keep the file. It records each raw Entry, Subscribe, and Put. It also
      records the Subscribe path (gap 1) and the `user.*` and `structure.*`
      keys (gap 3).

## 7. Replace the old MQTT entities

The new entities have new entity IDs. The automation
`automation.climate_control` uses the old IDs.

- [ ] Go to **Settings > Devices & services > MQTT** and delete the old
      Thermostat device.
- [ ] Rename the new climate entity to `climate.nest_02aa01ac10130c7t`.
- [ ] Rename the new fan sensor to `binary_sensor.nest_02aa01ac10130c7t_fan`.
- [ ] Set the area of the new device to `entry_way`.
- [ ] Open `automation.climate_control` and make sure that it shows no
      missing entities.

## Go back to the NLE add-on

Do this only if the test fails and you need the Thermostat to work again.

- [ ] Disable the LocalNestThermostat config entry.
- [ ] Start the NLE add-on.
