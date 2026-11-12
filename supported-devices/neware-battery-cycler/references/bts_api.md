# Neware BTS 8.0 server TCP interface, as used by this package

## Sources

- An open-source (MIT) Python client for Neware BTS 8.0 cyclers, read for the message names, the
  envelope, the terminator, the channel addressing and the reply layout (no code copied). It states
  that the API must be enabled in the BTS client (Help > Mode settings) and may need an activation
  key from Neware, and that it was written for BTS 8.0 on Windows.
- Neware's BTS Client 8.0 user manual (newarebattery.com, BTSClient8.0-UserManual.pdf) and the
  "Basic operation" pages on neware.com.cn for the client/server architecture (server on a Windows
  PC, middle machines over TCP/IP, testers over RS-485) and the data export conventions (mA, mAh).
  The manual was not read in full; it does not document the API in the parts seen.
- Column conventions of BTSDA exports (Current (mA), Capacity (mAh)) from a public battery-data
  format guide, which is why `current_scale` and `capacity_scale` default to 0.001.

## Transport and envelope

- TCP socket to the BTS server PC, default port 502 (yes, the Modbus port; the server is not Modbus).
- Request: `<?xml version="1.0" encoding="UTF-8" ?><bts version="1.0"><cmd>NAME</cmd>...</bts>` followed
  by the terminator `\n\n#\r\n`. The reply uses the same envelope and ends with the same terminator.
- First command after connecting: `connect` with `<username>`, `<password>` and `<type>bfgs</type>`.
- A channel is addressed by attributes `ip`, `devtype`, `devid`, `subdevid`, `chlid` taken from the
  `getdevinfo` answer; the package names channels as pipelines `devid-subdevid-chlid`.

## Commands used

| Command | Body | Reply used | Verified |
|---|---|---|---|
| `connect` | username, password, type bfgs | ignored | from the MIT client |
| `getdevinfo` | none | elements inside `<middle>` with `ip`, `devtype`, `devid`, `subdevid`, `Channelid` | from the MIT client |
| `inquire` | `<list count="n"><inquire ip devtype devid subdevid chlid aux="0" barcode="1">true</inquire>...</list>` | one element per channel inside `<list>`; attributes `workstatus`, `voltage`, `current`, `capacity`, `step`, `cycle`, `time` | command from the MIT client; **attribute names unverified** (the client only says the reply carries status, cycle, step, current, voltage, time) |
| `start` | `<list count="1"><start ... barcode="BARCODE">PATH-OF-STEP-FILE</start><backup backupdir=... /></list>` | element `start` whose text is `ok` on success, otherwise `false` | from the MIT client |
| `stop` | `<list count="1"><stop ...>true</stop></list>` | element `stop` | from the MIT client |

Commands the MIT client names but this package does not use: `getchlstatus`, `inquiredf`, `download`,
`downloadlog`, `light`, `clearflag`, `downloadStepLayer`, and (unimplemented there too) `broadcaststop`,
`continue`, `chl_ctrl`, `goto`, `parallel`, `getparallel`, `resetalarm`, `reset`. The e-stop sends one
`stop` per channel rather than `broadcaststop`, whose body is unverified.

## Work status words

`finish`, `stop` and `protect` are the states the MIT client allows a start from (so they are
real). `working` for a running channel and `pause` are **unverified** spellings; the driver treats
anything else as running until it has seen a running state, then stops following when the status is
no longer `working`/`pause`.

## The step file (UNVERIFIED layout)

`start` points at a step file on the BTS server (the MIT client passes the path of an XML payload
exported from the BTS client). No public description of that XML exists. This package writes its
own layout:

```xml
<?xml version="1.0" encoding="UTF-8" ?><bts version="1.0">
<config type="step" barcode="CC-2026-0007" cycles="2">
  <step id="1" mode="CC_Chg" current_mA="22.500" volt_V="4.2000" time_s="14400.0"/>
  <step id="2" mode="CV_Chg" current_mA="2.000" volt_V="4.2000" time_s="3600.0"/>
  <step id="3" mode="Rest" time_s="600.0"/>
  <step id="4" mode="CC_DChg" current_mA="22.500" volt_V="3.0000" time_s="14400.0"/>
</config>
</bts>
```

Before the first hardware run: export a step file from the BTS client (Step editor > Save as XML),
compare it with the above, and rewrite `render_step_file` / `parse_step_file` in `driver.py` (the twin
reads the same layout, so it keeps working). Until then the start command on a real server is expected
to answer `false`. Mode names `CC_Chg`, `CV_Chg`, `CC_DChg`, `Rest` are placeholders.

## Units

The reply fields are scaled by `voltage_scale` (1), `current_scale` (0.001, mA to A) and
`capacity_scale` (0.001, mAh to Ah) from config.json; the defaults follow BTSDA's export units and are
**unverified** for the API.

## Twin

The twin answers the same XML (eight channels `1-1-1`..`1-1-8` of devtype 27) with a 45 mAh, 3.0-4.2 V
coin cell per channel and a 2 ohm internal resistance; `start` parses the step file the backend wrote
and runs it, `inquire` reports working/finish/stop/protect, V, mA, mAh, step and cycle; a limit above
4.3 V or a discharge cut-off below 2.5 V trips `protect`. Time is scaled by `OPENMHP_SIM_TIME_SCALE`.
