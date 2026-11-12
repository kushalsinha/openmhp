---
mhp: "2026-09-12"
id: micro-manager-microscope-01
class: microscope
make: any (Micro-Manager)
model: Micro-Manager hardware configuration via pymmcore-plus
location: ""
tags: [microscope, imaging, micro-manager, pymmcore, stage, fluorescence]
description: Any microscope that Micro-Manager drives (camera, XY stage, focus stage, filter or light-source presets in a .cfg configuration), controlled in-process through pymmcore-plus. Pick it to set exposure and channel, move the stage in micrometres, snap single images as TIFF, or acquire a Z stack of up to 500 planes. Travel limits are the lab's and must be set in config.json before any move; it does not do autofocus, multi-dimensional acquisitions or tiling, and it does not run Micro-Manager's own acquisition engine.
driver: driver.py:MicroManagerMicroscope
sim: sim.py:SimMicroManagerMicroscope
---

# Micro-Manager microscope (pymmcore-plus)

Micro-Manager's device adapters do the hardware; pymmcore-plus loads them in this process from the
hardware configuration file the lab built in Micro-Manager's Hardware Configuration Wizard. The package
exposes the four things every configured microscope has: a camera, an XY stage, a focus stage and a config
group of channel presets. Micro-Manager's GUI must not hold the same hardware at the same time.

## Operating procedure

1. Read `connected`, `camera` and `channels`; read `xy_position` and `z_um` to know where the stage is.
2. Write `channel` to one of `channels`, and `exposure_ms`.
3. Invoke `snap`; the result names the TIFF and records exposure, Z and channel.
4. To image elsewhere invoke `move_xy` with coordinates inside the lab's soft limits; it waits for the stage.
   Refocus by writing `z_um` in small steps while snapping.
5. For a stack invoke `acquire_z_stack` (start, end, step); planes land in one folder, Z returns to where it
   was. Cancel the job to stop early.

## What to watch

- The shipped position bounds are placeholders. `soft_limits_um` in config.json is what protects the
  objective and the sample; set it from the stage's travel and the objective's working distance.
- `move_xy` cannot be cancelled while the stage is moving (pymmcore blocks); emergency stop halts stages.
- A channel name that is not in `channels` is refused; the names come from the loaded configuration.
- Saturated 16-bit images (65535) mean exposure or illumination is too high; the package does not check.
- The twin is the demo configuration's shape (256x256 16-bit camera, four channels) with synthetic beads.

## Resources

- `references/setup.md`: pymmcore-plus and the device adapters, the .cfg file, config.json, the first hardware test.
- `references/pymmcore.md`: the MMCore calls used, with the unverified ones listed.
- `config.example.json`: configuration file, channel group, soft limits, data folder.
