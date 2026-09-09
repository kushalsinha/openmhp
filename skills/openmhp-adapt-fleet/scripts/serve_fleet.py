#!/usr/bin/env python3
"""Serve many device packages from one host, one HTTP port each.

    python serve_fleet.py 18921 devices/arm-01 devices/star-01 devices/furnace-02
Ports are assigned in order starting at the first argument.
"""
import sys
import threading

from openmhp.package import load_driver
from openmhp.transport import serve_http

if len(sys.argv) < 3:
    sys.exit(__doc__)
base = int(sys.argv[1])
for i, folder in enumerate(sys.argv[2:]):
    dev = load_driver(folder)
    threading.Thread(target=serve_http, args=(dev,), kwargs={"host": "0.0.0.0", "port": base + i}, daemon=True).start()
    print(f"{dev.descriptor['device']['id']:24s} http://0.0.0.0:{base + i}")
threading.Event().wait()
