# Setting up a Thorlabs PM100D-family power meter

## What to install

- `pip install pyvisa pyvisa-py pyusb` on the serving PC. The console is a USBTMC device:
  - Linux: add a udev rule so the user can open it (`SUBSYSTEM=="usb", ATTRS{idVendor}=="1313",
    MODE="0666"`), replug, and `python -m pyvisa.shell` should list
    `USB0::0x1313::0x8078::P00xxxxx::INSTR`.
  - macOS: pyusb with libusb (`brew install libusb`); the same resource string.
  - Windows: either NI-VISA, or pyvisa-py with libusb and the Thorlabs driver replaced by a
    WinUSB/libusb driver with Zadig. The Thorlabs Optical Power Monitor software claims the
    device while it runs; close it.
- Alternatively the Thorlabs `TLPM` library (ThorlabsPM100 on PyPI) also talks to it; this
  package does not use it, so it is not needed.

## Cable and port

USB-B on the console. The PM100USB is the console; the PM400 also has USB. The resource is the
VISA string that pyvisa lists; the product id differs per model (0x8078 PM100D, 0x8079 PM100A,
0x8072 PM100USB; PM400 unverified).

## Settings on the instrument

- Nothing to enable: SCPI over USBTMC is on whenever the console is on. The head is detected
  on plug-in; `sensor_head` tells you which.
- The front panel keeps working while the package holds the device; a person changing the
  wavelength on the panel changes what `wavelength` reads.

## Write the config

Copy `config.example.json` to `config.json` beside the package and set `resource`, or let
`mhp node setup` ask for it.

## First hardware test

1. With the head capped, `mhp serve pkg:<this folder>`; read `connected`, `sensor_head` and
   `last_error` (expect `0,"No error"`). `*IDN?` must contain "Thorlabs" or the probe refuses
   the resource.
2. Write `wavelength` to your source's wavelength; read `wavelength` back.
3. Invoke `zero` with the head still capped, then read `power` (a few nW on a photodiode head).
4. Uncap in the beam and read `power`; compare with the console display. Invoke `measure` and
   check the two replies are the wavelength and that power.
5. Write `wavelength` outside the head's range (for example 150) and confirm the write is
   refused by the descriptor; then write a value the head refuses (if the descriptor's range is
   wider than the head's) and read `last_error` to see the console's refusal.

Then set `wavelength` min and max in `descriptor.yaml` to the head's range and `mhp_lab
op='reload'`.

## Status

twin tested. Written from the Thorlabs PM100D Operation Manual (document 17654-D02, chapter
"SCPI command reference") and the PM100D/PM100A/PM100USB SCPI command summary, cross-checked
against the ThorlabsPM100 Python package's command names; not yet run on hardware. Items marked
unverified in `scpi.md` were not checked against an instrument.
