#!/usr/bin/env python3
"""Validate an MHP device package folder. Same as `mhp validate <folder>`.

    python validate_package.py devices/thermocycler-01
"""
import sys

from openmhp.validate import main

sys.exit(main())
