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

Write the package with the `openmhp-onboard-device` skill or by hand, include a `sim.py` twin
that needs no vendor library, add an entry to `openmhp/registry.json`, and extend the package
test in `tests/test_adapters.py`. Keep lab-specific values (addresses, serial numbers, SOPs) in
`config.json`, which is never committed; ship a `config.example.json` instead. When you have run
it on the instrument, change its status here to hardware tested.
