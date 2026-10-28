# The FloZF `mhp_server` sequence

Line protocol on the serial pair (FloZF sends, this package answers; every line ends in CR):

| FloZF sends | Answer | Meaning |
|---|---|---|
| `POLL` | `0` | nothing to do |
| `POLL` | `1`..`8` | run the sequence with this code (config `sequence_codes`) |
| `POLL` | `-1` | leave the server loop |
| `GET probe` / `GET dil1` / `GET dil2` / `GET vial` | a number | parameters of the job just picked up |
| `CHECK` | `OK` | still allowed to run; **no answer** means emergency stop |
| `DONE` | `OK` | the job finished |
| `ABORTED` | `OK` | sent from the stop sequence: the job failed |

Build it in FloZF's Develop page (steps from the `mhp` general serial device, the system steps
and variables):

```
evaluate            run = 1
mhp_server          [while: run==1]
    prompt for number   'POLL'          -> job
    do_archive          [if: job==1]
        prompt for number 'GET probe'   -> probe
        prompt for number 'GET dil1'    -> dil1
        prompt for number 'GET dil2'    -> dil2
        prompt for number 'GET vial'    -> vial
        <your FloPro sampling sequence to the archive, using probe, dil1, dil2, vial,
         with a gen command 'CHECK' step (Require Response = yes) between fluidic steps>
        gen command 'DONE'
    do_inject           [if: job==2]
        (same GET steps)
        <your FloPro sampling sequence to the injection valve>
        gen command 'DONE'
    do_detector         [if: job==3]  ...
    do_rinse            [if: job==9]
        <your rinse sequence>
        gen command 'DONE'
    leave               [if: job==-1]
        evaluate run = 0
    wait 2
```

How the emergency stop works: FloZF aborts a sequence when a device step gets no answer
(FloZF manual 1.4.8, Require Response = yes on the general serial device), and an aborted
sequence runs the project's "stop sequence". After an e-stop this package answers nothing, so
FloZF aborts at the next CHECK (or POLL). Put CHECK steps between the fluidic steps of every
sequence this server calls; the gap between them is the worst-case stop delay.

The project's "stop sequence" must turn the pumps off FIRST, then send `gen command 'ABORTED'`
(Require Response = no) so a stop is reported when the link is up. Test this once with the
reactor probe in water: start a sample, e-stop the device, and confirm the pumps stop. Use the codes you choose here in config.json `sequence_codes`.
