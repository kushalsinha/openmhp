---
mhp: "2026-09-12"
id: gamry-potentiostat-01
class: potentiostat
class_ref: CHMO:0002427
make: Gamry Instruments
model: Interface 1010 / Reference 620 (Electrochemistry Toolkit, GamryCOM)
location: ""
tags: [electrochemistry, potentiostat, eis, voltammetry, materials-characterization, windows, com]
description: Gamry Interface 1010 and Reference 620 potentiostats on the Windows PC that runs the Gamry Framework, driven through the Electrochemistry Toolkit's COM interface (GamryCOM) with pywin32. Pick it to run an open-circuit reading, chronoamperometry, cyclic voltammetry or a potentiostatic impedance sweep on a three-electrode cell and to get back the trace or spectrum file with its end values, and to open or close the cell switch. Not for galvanostatic techniques, iR compensation, multiplexers or Framework sequences; the Dtaq, Signal and ReadZ call signatures are marked unverified until checked against the Toolkit reference manual.
driver: driver.py:Device
sim: sim.py:Sim
---

# Gamry Interface 1010 / Reference 620 (Electrochemistry Toolkit)

The Gamry Framework owns the instrument; its Electrochemistry Toolkit exposes the same hardware
control as COM objects (GamryCOM), so a Python process on the same Windows PC can enumerate the
instruments, open one, attach a signal generator and a data-acquisition object, run it and "cook"
the data. This package wraps four techniques as long actions, switches the cell on only for the
technique, writes each trace to a CSV in `data_dir`, and turns the cell off on any end.

## Operating procedure

1. Read `connected` and `device`. The Framework must be installed, the instrument on, and no other
   Framework script running on it (the Toolkit refuses an instrument in use).
2. Invoke `ocp` for a few seconds to check the cell is wired and wetted (a stable potential).
3. Invoke `ca`, `cv` or `eis` with the potentials the chemistry allows; the +/-1.5 V bounds are
   placeholders the lab tightens. Each is a job: poll it, or cancel it to stop the technique with the
   cell off. The result names the trace or spectrum file and carries the end values.
4. `output_enabled` closes the cell switch outside a technique (confirmed by a person); techniques do
   not need it and leave the cell off.

## What to watch

- `cell_on` true with no job running means `output_enabled` was set by hand; write it false or the
  e-stop clears it.
- EIS below 1 Hz takes minutes; the 60 s watchdog window is for silence from the controller, not for
  the technique's length (the job keeps renewing the lease).
- The Dtaq and Signal `Init` argument lists and the Cook column order in `driver.py` are marked
  unverified: the first hardware test compares one CA trace with the Framework's own.

## Resources

- `references/setup.md`: Windows, Gamry Framework and Toolkit licence, pywin32, config.json, first
  hardware test.
- `references/gamrycom.md`: the COM objects and calls used, their sources, and what is unverified.
- `config.example.json`: instrument section name, data folder, caps.
