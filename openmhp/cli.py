"""``mhp`` command line: the second of the three control surfaces.

    mhp serve local:openmhp.devices.sim_thermocycler:SimThermocycler --http 8765
    mhp http://localhost:8765 describe
    mhp http://localhost:8765 read block_temperature lid_closed
    mhp http://localhost:8765 write target_temperature 95
    mhp http://localhost:8765 invoke run_protocol '{"steps":[{"temp":95,"hold_s":5}],"cycles":3}' --wait
    mhp http://localhost:8765 estop
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys

from .client import connect, RemoteError


def _load_driver(target: str):
    if target.startswith("local:"):
        mod, cls = target[len("local:"):].rsplit(":", 1)
        return getattr(importlib.import_module(mod), cls)()
    from .package import load_driver                    # a device package folder
    return load_driver(target[len("pkg:"):] if target.startswith("pkg:") else target)


def _parse_value(s: str):
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return s


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mhp", description="Open Model Hardware Protocol CLI")
    ap.add_argument("target", help="serve | serve-directory | http://host:port | stdio:<cmd> | local:<mod>:<Class> | pkg:<device folder>")
    ap.add_argument("verb", nargs="?", help="find|describe [card|summary|full]|resources [path]|limits|read|write|invoke|status|cancel|wait|estop|reset|acquire|release|rpc")
    ap.add_argument("args", nargs="*")
    ap.add_argument("--wait", action="store_true", help="block until an invoked job finishes")
    ap.add_argument("--approved", action="store_true", help="assert human confirmation was obtained")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--http", type=int, metavar="PORT", help="(serve) listen on HTTP instead of stdio")
    a = ap.parse_args(argv)

    if a.target == "serve":
        from .transport import serve_http, serve_stdio
        drv = _load_driver(a.verb)
        return serve_http(drv, port=a.http) if a.http else serve_stdio(drv)

    if a.target == "serve-directory":       # mhp serve-directory manifest.json --http 18900
        from .directory import Directory
        from .transport import serve_http, serve_stdio
        d = Directory.from_manifest(a.verb) if a.verb.endswith(".json") else \
            Directory.from_targets(dict(t.split("=", 1) for t in [a.verb, *a.args]))
        return serve_http(d, port=a.http) if a.http else serve_stdio(d)

    dev = connect(a.target)
    v, x = a.verb, a.args
    try:
        if v == "find":      out = dev.call("directory/search", {"query": " ".join(x)})["results"]
        elif v == "describe":
            out = dev.call("device/describe", {"detail": x[0]} if x else {})
        elif v == "resources":
            out = dev.call("resources/read", {"path": x[0]}) if x else dev.call("resources/list")
        elif v == "limits":  out = dev.limits()
        elif v == "read":    out = dev.call("signals/read", {"names": x} if x else {})["values"]
        elif v == "write":   out = dev.write(x[0], _parse_value(x[1]), a.approved, a.dry_run)
        elif v == "invoke":
            params = _parse_value(x[1]) if len(x) > 1 else {}
            job = dev.invoke(x[0], a.approved, a.dry_run, **params)
            out = dev.wait(job) if a.wait and not a.dry_run else job
        elif v == "status":  out = dev.status(x[0])
        elif v == "cancel":  out = dev.cancel(x[0])
        elif v == "wait":    out = dev.wait(x[0])
        elif v == "estop":   out = dev.estop(" ".join(x))
        elif v == "reset":   out = dev.reset()
        elif v == "acquire": out = dev.acquire()
        elif v == "release": out = dev.release()
        elif v == "rpc":     out = dev.call(x[0], _parse_value(x[1]) if len(x) > 1 else {})
        else:
            ap.error(f"unknown verb {v}")
    except RemoteError as e:
        print(json.dumps({"error": {"code": e.code, "message": e.message, "data": e.data}}, indent=2))
        return 1
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
