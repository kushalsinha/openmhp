#!/usr/bin/env python3
"""Check a device package against what `supported-devices/` requires. Same as `mhp inclusion <folder>`.

    python check_inclusion.py devices/thermocycler-01
    python check_inclusion.py devices/thermocycler-01 --json

Runs the package's simulated twin: a descriptor is a claim, and a refusal is evidence.
Exit status is 0 when every check passed or was skipped as inapplicable.
"""
import sys

from openmhp.inclusion import main

sys.exit(main())
