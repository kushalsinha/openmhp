---
mhp: "2026-09-12"
id: bench-power-supply-01
class: power_supply
make: Rigol
model: DP832 programmable DC power supply (DP831, DP821, DP811; Siglent and Aim-TTi by notes)
location: ""
tags: [power-supply, bench, dc, scpi, electronics, engineering]
description: Rigol DP800-series three-channel bench DC power supply (DP832 shipped; DP831, DP821, DP811 with their own channel ratings) over SCPI on LAN or USB. Sets voltage and current limit per channel, reads back measured voltage, current and power, and enables each output through a confirm-gated action with over-voltage and over-current protection on. Pick it to power a circuit or device under test at a known voltage with a current limit; not a battery charger, not an electronic load, and not for anything the channel's protection values have not been set for.
driver: driver.py:Device
sim: sim.py:Sim
---

# Rigol DP832 bench power supply

Three independent channels: CH1 and CH2 0 to 30 V at 3 A, CH3 0 to 5 V at 3 A (DP832). Each
channel has a voltage setpoint, a current limit (the supply goes into constant-current mode
when the load draws more), an over-voltage protection value and an over-current protection
value that trip the output off. The outputs are wired to the device under test by a person,
and the shipped setpoint limits are the instrument's full range: the lab lowers them to the
DUT before an agent operates it.

## Operating procedure

1. Read `connected` and `output_ch1` (expect false), and `last_error` (expect `0,"No error"`).
2. Write `voltage_setpoint_ch1` and `current_limit_ch1` for the DUT, then `ovp_ch1` a little
   above the setpoint and `ocp_ch1` a little above the expected draw. Or invoke `configure_ch1`
   to set all four in one job.
3. Invoke `enable_ch1`. It needs a person's confirmation: enabling an output is the moment a
   wiring mistake becomes a fault, and the DUT cannot be seen from here. It turns OVP and OCP
   on for the channel before the output.
4. Read `voltage_ch1`, `current_ch1` and `power_ch1`. A voltage below the setpoint with the
   current at the limit is constant-current mode: the DUT draws more than you allowed.
5. Invoke `disable_ch1` (or `all_off`) when done. Changing a setpoint while the output is on
   is applied immediately.

## What to watch

- `output_chN` false after you enabled it means the protection tripped (OVP, OCP or
  over-temperature); read `last_error`, fix the cause, then enable again with confirmation.
- CH3 on a DP832 is 5 V only; the descriptor caps it. The DP831 has an 8 V, a 30 V and a -30 V
  channel and the DP811 one 20 V/10 A or 40 V/5 A channel: edit the limits for those models.
- Emergency stop sends `:OUTP CH1,OFF`, `:OUTP CH2,OFF`, `:OUTP CH3,OFF`; the outputs are off
  within the command time. Energy stored in the DUT (capacitors, inductors) is the DUT's.
- Writes do not answer; the generic route waits the `timeout` for each one.

## Resources

- `references/setup.md`: LAN or USB, pyvisa, first hardware test, other vendors.
- `references/scpi.md`: the DP800 SCPI commands used, with Siglent and Aim-TTi equivalents.
