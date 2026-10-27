# Supported devices

Ready-made device packages for instruments that talk to OpenMHP directly. Each folder is one
package: `DEVICE.md` (card and operating instructions), `descriptor.yaml` (limits, approvals,
interlocks), `driver.py`, a simulated twin in `sim.py`, and usually `references/setup.md`.

```
mhp lab add github:kushalsinha/openmhp/supported-devices/<name> --sim    # rehearse with the twin
mhp lab add github:kushalsinha/openmhp/supported-devices/<name>          # the real instrument
```

| Package | Instrument | Talks through | Host | Status |
|---|---|---|---|---|
| [`ika-c-mag-hs7`](ika-c-mag-hs7) | IKA C-MAG HS 7 stirrer hotplate | serial, NAMUR commands | any | twin tested |
| [`opentrons-flex`](opentrons-flex) | Opentrons Flex liquid handler | PyLabRobot | any | twin tested |
| [`manual-benchtop-centrifuge`](manual-benchtop-centrifuge) | any benchtop centrifuge run by a person | operator prompts | any | template |
| [`elveflow-ob1`](elveflow-ob1) | Elveflow OB1 pressure controller, with MFS flow sensors | Elveflow SDK | Windows | twin tested |
| [`elveflow-mux-distributor`](elveflow-mux-distributor) | Elveflow MUX Distributor selection valve | Elveflow SDK | Windows | twin tested |
| [`biologic-sp300`](biologic-sp300) | BioLogic SP-300 potentiostat | EC-Lab Development Package, easy-biologic | Windows | twin tested |
| [`wasatch-raman-blaze`](wasatch-raman-blaze) | Wasatch Raman spectrometer behind a BlazeMetrics Blaze probe | Wasatch.PY | any | twin tested |
| [`sri-8610c-gc`](sri-8610c-gc) | SRI 8610C gas chromatograph | PeakSimple .NET connector, pythonnet | Windows | twin tested |

**Status** is honest about what has been exercised:

- **twin tested**: the package validates and its simulated twin passes the test suite through
  every safety gate. The real driver is written from the vendor's documentation and has not been
  confirmed on the instrument by the maintainers.
- **hardware tested**: someone has run the real driver on the instrument and said so in the
  package's setup note (firmware and SDK versions included).
- **template**: meant to be copied and adapted.

## Before you rely on one

The shipped limits are the instrument's range or a conservative placeholder, not your rig's.
Read the package's safety card (`mhp_lab op='safety_card'`), set the limits in `descriptor.yaml`
to what your cell, tubing or sample can take, and start with the first-hardware-test steps in
`references/setup.md`.

## Adding a device

Write the package with the `openmhp-onboard-device` skill or by hand, then run the gate:

```bash
mhp inclusion supported-devices/<name>
```

It reports two tiers. **Package** is the bar for any package anywhere: the validator, the rules a
driver must follow about the configuration it enforces, and behavioural proof from the package's
own twin that the gates refuse what they declare and that nothing the device reports is a handle
on what it enforces. **Submission** is what this repository needs in order to carry it — a twin
that loads with no vendor library, an entry in `openmhp/registry.json`, a row in the table above
with an honest status, `config.example.json` rather than a committed `config.json`, and a
`references/setup.md`. `[-]` means a check did not apply here and says why; it is not a pass.
Every package listed above passes both tiers, and `tests/test_inclusion.py` keeps it that way.

Then extend `tests/test_adapters.py` so the twin is exercised in CI, and open the PR. What each
check means and how to fix it:
[openmhp/skills/openmhp-onboard-device/references/inclusion.md](../openmhp/skills/openmhp-onboard-device/references/inclusion.md).
When you have run it on the instrument, change its status here to hardware tested and record the
firmware and SDK versions in the package's setup note.
