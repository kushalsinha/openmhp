# Serial reference: Ossila Spin Coater (TEMPLATE, unverified)

**Status of this command set: every frame below is a placeholder.** Ossila's *Spin Coater User
Manual*, manual version 3.1.B, product codes L2001A3 and L2001B1, product versions 3.0 and 1.0
(downloads.ossila.com/manuals/spin-coater.pdf; an older 3.0.F edition for the L2001A3 says the
same) describes a unit operated from its built-in touch display that "does not need an external PC
connection" and publishes no serial protocol. Ossila's solar simulator and monochromator manuals
do document serial commands over USB (angle-bracket delimited frames on the solar simulator), so a
command set for the spin coater may exist for newer firmware: ask Ossila (info@ossila.com), rewrite
the `serial:` block in descriptor.yaml and this table, and confirm on hardware.

## What the manual states (used for limits and behaviour)

| Item | L2001A3 | L2001B1 |
|---|---|---|
| Speed range | 120 to 6,000 rpm | 500 to 10,000 rpm |
| Speed stability | < 2 % | < 0.25 % |
| Spin time per step | 1 to 1,000 s | 1 to 3,600 s |
| Programs | 10 of up to 50 steps | 15 of up to 50 steps |
| Interlock | software/hardware lid interlock | same |
| Substrate hold | edge-held in the chuck, no vacuum | same |
| Power | 24 V DC, 2 A | same |
| Case | 170 x 225 x 140 mm, steel; PP (A3) or PTFE (B1) chuck and bowl | |

Acceleration between steps is settable on the unit; the manual's specification table gives no
rpm/s figure, so the 2,000 rpm/s cap in descriptor.yaml is a placeholder.

## Placeholder command set used by descriptor.yaml

Framing assumed: ASCII, 115200 8N1, LF-terminated, one reply line per command. **All unverified.**

| Command | Intended meaning | Twin reply | Used as |
|---|---|---|---|
| `?RPM` | actual chuck speed | `RPM <n>` | signal `speed_rpm` |
| `?LID` | lid state | `LID 1` closed, `LID 0` open | signal `lid_closed` |
| `?RUN` | a program is running | `RUN 1` / `RUN 0` | signal `running` |
| `?PRG` | selected program | `PRG <n>` | signal `program` |
| `?STEP` | current step | `STEP <n>` | signal `step` |
| `?TIME` | seconds left in the step | `TIME <n>` | signal `time_remaining` |
| `PRG <n>` | select program 1-10 (1-15 on the B1) | `OK` | setting `program`, run_recipe |
| `STEP <slot> <n> <rpm> <rpm/s> <s>` | write step n of a program (n = 1 clears it) | `OK` | run_recipe |
| `RUN` | start the selected program | `OK`, `ERR LID`, `ERR EMPTY` | run_recipe, start_program |
| `STOP` | stop the run | `OK` | stop, e-stop |

Derived by the driver, not a command: `robot_access_ready` (lid open and speed 0). No `vacuum_ok`
is declared because the unit has no vacuum chuck. Checksums: none assumed; if Ossila's frames carry
one, add `checksum: {kind: xor|sum8, ...}` to the `serial:` block (the driver supports it).
