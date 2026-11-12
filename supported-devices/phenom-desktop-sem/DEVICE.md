---
mhp: "2026-09-12"
id: phenom-desktop-sem-01
class: electron_microscope
class_ref: CHMO:0000941
make: Thermo Fisher Scientific (Phenom-World)
model: Phenom XL G2 / G3 (Pharos, ProX by the same interface)
location: ""
tags: [sem, electron-microscope, imaging, desktop-sem, phenom, ppi, materials-characterization]
description: Template for the Thermo Scientific Phenom XL (and Pharos, ProX) desktop scanning electron microscope driven through the Phenom Programming Interface, the vendor's PyPhenom Python package talking to the instrument over the network. Pick it to pump a loaded holder in, move the motorised stage, set the high tension, auto-focus and acquire a backscattered or secondary electron image at a chosen magnification, resolution and dwell, saved as a TIFF, and to vent and present the holder again. The sample holder is placed by a person (or a robot at the loading port; no vendor loader is documented). Not for EDS, for the ProSuite analysis applications, or for Phenom Pure/Pro without the PPI licence. Member names beyond those in Thermo's own material are unverified and configurable.
driver: driver.py:PhenomSEM
sim: sim.py:SimPhenomSEM
---

# Phenom desktop SEM (PPI)

The Phenom is a sealed desktop SEM: a holder goes into the loading port, the instrument pumps it
through a venting/loading mechanism in under a minute, and a motorised X/Y stage moves the sample
under the beam. PPI (Phenom Programming Interface) is Thermo's licensed Python package, PyPhenom,
which connects over the network with the instrument's address, instrument ID and PPI licence
password. This package keeps every PPI call in `PhenomBackend`; the twin swaps that for a model
with the same loading times, stage range and imaging modes, and writes real TIFFs.

## Operating procedure

1. Read `connected`, `instrument_mode` and `operational_mode`. `vacuum_ready` true means the holder
   is loaded and under vacuum; `robot_access_ready` true means the holder is unloaded and presented
   at the loading port with nothing moving.
2. To load: a person or robot places the holder in the port (`robot_access_ready` must be true),
   then `load_sample` pumps it in (about 60 s); the job returns when the SEM is live.
3. `move_stage` to the position in millimetres from the stage centre (+/-50 mm on the XL's 100 x
   100 mm stage, less on a Pharos or ProX: set the limits to your model). Write `high_voltage`
   (kV) if the default is wrong.
4. `acquire_image` with magnification, width and height in pixels, dwell, frames to average and the
   detector mode; `auto_focus: true` focuses first. The result names the TIFF and the magnification
   actually set. Repeat per location; about 20 s per image with focus.
5. `unload_sample` vents and presents the holder; `robot_access_ready` then reads true.
6. E-stop puts the instrument in standby (beam off); `safety/reset` and `load_sample` bring it back.

## What to watch

- `operational_mode` reading `Loading` or `Unloading` longer than two minutes: the port did not seal;
  look at the holder.
- `instrument_mode` reading `Hibernate`: the source is cold and the first image after `Activate`
  takes minutes; the twin models this as a short delay.
- Magnification is set through the horizontal field width; the value in the result is what the
  instrument reports back, which differs a little from the request.

## Resources

- `references/setup.md`: the PPI licence, PyPhenom install, network address, instrument ID, first
  hardware test.
- `references/ppi.md`: the PyPhenom calls this package uses, their units, the sources and what is
  unverified.
- `config.example.json`: address, instrument ID, image folder; the PPI member names as an advanced
  block.
