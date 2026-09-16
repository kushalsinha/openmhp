"""``mhp`` command line: the second of the three control surfaces.

    mhp serve local:openmhp.devices.sim_thermocycler:SimThermocycler --http 8765
    mhp node ~/instruments --http 18900          # every package folder in one directory, one host
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
    ap.add_argument("target", help="lab | validate | skills | serve | node | serve-directory | http://host:port | stdio:<cmd> | local:<mod>:<Class> | pkg:<device folder>")
    ap.add_argument("verb", nargs="?", help="find|describe [card|summary|full]|resources [path]|limits|read|write|invoke|status|cancel|wait|estop|reset|acquire|release|rpc")
    ap.add_argument("args", nargs="*")
    ap.add_argument("--wait", action="store_true", help="block until an invoked job finishes")
    ap.add_argument("--approved", action="store_true", help="assert human confirmation was obtained")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--sim", action="store_true", help="(lab add) use the package's simulated twin")
    ap.add_argument("--location", help="(lab add) where the instrument stands, e.g. \"bay 3, fume hood 2\"")
    ap.add_argument("--http", type=int, metavar="PORT", help="(serve) listen on HTTP instead of stdio; (node) base port, one per package")
    a = ap.parse_args(argv)

    if a.target == "serve":
        from .transport import serve_http, serve_stdio
        drv = _load_driver(a.verb)
        return serve_http(drv, port=a.http) if a.http else serve_stdio(drv)

    if a.target == "node":                  # mhp node <packages-dir> [--http BASE_PORT]
        import threading
        from pathlib import Path
        from .package import load_driver
        from .transport import serve_http
        base = a.http or 18900
        root = Path(a.verb or ".").expanduser()
        folders = sorted(p.parent for p in root.glob("*/DEVICE.md"))
        if not folders:
            ap.error(f"no device packages under {root} (looked for */DEVICE.md)")
        print(f"serving {len(folders)} package(s) from {root}, ports {base}..{base + len(folders) - 1}", file=sys.stderr)
        for i, folder in enumerate(folders):
            port = base + i
            try:
                drv = load_driver(folder)
            except Exception as e:                          # noqa: BLE001  one bad package must not take the rest down
                print(f"  {folder.name:24s} SKIPPED: {type(e).__name__}: {e}", file=sys.stderr)
                continue
            threading.Thread(target=serve_http, args=(drv,), kwargs={"host": "0.0.0.0", "port": port}, daemon=True).start()
            print(f"  {drv.descriptor['device']['id']:24s} http://0.0.0.0:{port}  ({folder})", file=sys.stderr)
        print("advertising on the LAN if zeroconf is installed (pip install \"openmhp[all]\"); Ctrl-C to stop", file=sys.stderr)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            return 0

    if a.target == "lab":                   # mhp lab scan [host ...] | add <target> | remove <id> | list | home
        from .fleet import Fleet, HOME
        fleet = Fleet()
        v, x = a.verb or "list", a.args
        if v == "scan":
            found = fleet.scan(hosts=x or None)
            print(json.dumps(found, indent=2))
            if found:
                print(f"\n{len(found)} device(s) not yet in your lab. Add one with:  mhp lab add {found[0]['target']}", file=sys.stderr)
            else:
                print("no new MHP devices answered. Devices advertise on _mhp._tcp or answer /mhp.json; try `mhp lab scan <host>`.", file=sys.stderr)
        elif v == "add":
            card = fleet.add(x[0], sim=a.sim, location=a.location)
            print(json.dumps(card, indent=2))
            print(f"added {card['id']}", file=sys.stderr)
            if not card.get("location"):
                print(f'no location yet; set it with:  mhp lab location {card["id"]} "bay 3"', file=sys.stderr)
        elif v == "location":
            if len(x) < 2:
                ap.error('usage: mhp lab location <device id> "bay 3, fume hood 2"')
            card = fleet.set_location(x[0], " ".join(x[1:]))
            print(f"{card['id']} is at {card['location']}", file=sys.stderr)
        elif v == "remove":
            print("removed" if fleet.remove(x[0]) else "not in lab", x[0])
        elif v == "list":
            print(json.dumps(fleet.list(), indent=2))
        elif v == "home":
            print(HOME)
        elif v == "demo":                   # add the two bundled simulated instruments
            from pathlib import Path
            for name in ("thermocycler-01", "arm-01"):
                card = fleet.add(str(Path(__file__).parent / "devices" / name))
                print(f"added {card['id']} ({card['class']}, {card['location']})", file=sys.stderr)
            print(json.dumps(fleet.list(), indent=2))
        else:
            ap.error(f"unknown lab verb {v} (scan|add|location|remove|list|home|demo)")
        return 0

    if a.target == "validate":              # mhp validate <device package folder>
        from .validate import main as vmain
        return vmain([a.verb, *a.args])

    if a.target == "skills":                # mhp skills install [dir ...]
        from .skills_install import main as smain
        return smain([a.verb or "install", *a.args])

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
