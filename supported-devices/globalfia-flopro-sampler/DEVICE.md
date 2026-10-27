---
mhp: "2026-09-12"
id: flopro-sampler-01
class: sampler
make: Global FIA (Zone Fluidics)
model: FloPro Sampler, run by FloZF
location: ""
tags: [sampling, dilution, reactor, fraction-collector, flozf]
description: Global FIA FloPro Sampler, an automated reactor sampling and dilution unit with up to four sample probes and a 54-vial archive, run by its FloZF software. Pick it to draw a sample from a reactor probe, dilute it (primary 1:1-1:10, secondary 1:10-1:100) and send it to an archive vial, a chromatograph injection valve or an in-line detector, between or during chromatography runs. It runs the owner's validated FloZF sequences; it cannot invent new fluidic steps.
driver: driver.py:FloProSampler
sim: sim.py:SimFloProSampler
---

# FloPro Sampler (FloZF)

FloZF has no remote-control interface, but its sequences can talk to a serial port. This
package uses that: FloZF runs a small server sequence (`references/flozf_server_sequence.md`)
that keeps asking this package, over a virtual serial cable, whether there is work. When an
agent invokes `take_sample`, the next poll gets the job and its numbers (probe, dilutions, vial),
FloZF runs the owner's own sampling sequence with them, and reports DONE.

## Operating procedure

1. Read `connected`: true while FloZF's server sequence is polling (every few seconds). If false,
   a person starts the `mhp_server` sequence in FloZF.
2. Read `vials_used` to see which archive vials already hold samples.
3. Invoke `take_sample` with the destination (archive, inject or detector), the probe, the two
   dilution factors and, for archive, the vial. The job finishes when FloZF reports DONE
   (a sequence takes 5-8 minutes).
4. Invoke `rinse` between very different samples if the owner's FloZF project defines it.
5. When done for the day, invoke `stop_server` so FloZF leaves the loop.

## What to watch

- A job that is not picked up within `pickup_timeout_s` means FloZF is not polling (sequence
  stopped, port unplugged). Nothing was sampled.
- A job picked up but not finished means FloZF stopped mid-sequence; a person checks the
  instrument, because liquid may be left in the lines.
- Diluent reservoir is 300 mL; each sample uses up to 2 mL. The archive holds 54 vials.
- Emergency stop makes this package stop answering FloZF, so FloZF aborts at its next CHECK step
  and runs its "stop sequence" (pumps off). It is seconds, not instantaneous; a person can always
  press Stop in FloZF. After an e-stop, restart `mhp_server` in FloZF, then reset the device.

## Resources

- `references/setup.md`: virtual serial port pair, FloZF general serial device, config.json.
- `references/flozf_server_sequence.md`: the FloZF sequence to build, step by step, and the line protocol.
- `config.example.json`: serial port, sequence codes, timeouts.
