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
import os
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
    ap.add_argument("target", help="lab | log | validate | inclusion | conformance | skills | serve | node | gateway | serve-directory | http://host:port | stdio:<cmd> | local:<mod>:<Class> | pkg:<device folder>")
    ap.add_argument("verb", nargs="?", help="find|describe [card|summary|full]|resources [path]|limits|read|write|invoke|status|cancel|wait|estop|reset|acquire|release|rpc")
    ap.add_argument("args", nargs="*")
    ap.add_argument("--wait", action="store_true", help="block until an invoked job finishes")
    ap.add_argument("--approved", action="store_true", help="assert human confirmation was obtained")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--sim", action="store_true", help="(lab add) use the package's simulated twin")
    ap.add_argument("--location", help="(lab add) where the instrument stands, e.g. \"bay 3, fume hood 2\"")
    ap.add_argument("--http", type=int, metavar="PORT", help="(serve) listen on HTTP instead of stdio; (node) base port, one per package")
    ap.add_argument("--host", metavar="ADDR", help="(serve|node|serve-directory) bind address; default 127.0.0.1 (this machine only). Give this PC's LAN address to serve agents on the same network; the relay (--join) needs no open port at all")
    ap.add_argument("--token", help="device bearer token: required by a server reachable from the network, and presented by the client verbs (OPENMHP_DEVICE_TOKEN)")
    ap.add_argument("--no-auth", action="store_true", help="(serve|node) serve the network with no token; remote callers are then served but cannot confirm approval-gated operations")
    ap.add_argument("--install-service", action="store_true", help="(node) run in the background from now on, across reboots, with no terminal open")
    ap.add_argument("--uninstall-service", action="store_true", help="(node) remove a service installed with --install-service")
    ap.add_argument("--service-status", action="store_true", help="(node) is a service installed, and is it running")
    ap.add_argument("--dry-run-service", action="store_true", help="(node --install-service) print what would be written and run, but do neither")
    ap.add_argument("--check", action="store_true", help="(node) check the packages and ports and say what to fix, without serving")
    ap.add_argument("--name", help="(gateway init) the address lab PCs and agents will use for the gateway; (node --join) this PC's name at the gateway")
    ap.add_argument("--listen", type=int, metavar="PORT", help="(gateway init|serve) TLS port, default 443")
    ap.add_argument("--cert", metavar="FILE", help="(gateway init) TLS certificate from IT; a self-signed one is made otherwise")
    ap.add_argument("--key", metavar="FILE", help="(gateway init) private key for --cert")
    ap.add_argument("--join", nargs=2, metavar=("GATEWAY_URL", "CODE"), help="(node) pair this PC with a gateway once, using a code from `mhp gateway pair` there; later runs connect by themselves")
    ap.add_argument("--no-relay", action="store_true", help="(node) serve locally only, even if this PC has joined a gateway")
    a = ap.parse_args(argv)

    def _serve_token():
        """What the operator asked for: a token of their own, none at all, or the default (one is
        generated as soon as the bind address is reachable from another machine)."""
        return False if a.no_auth else a.token

    if a.target == "serve":
        from .transport import serve_http, serve_stdio
        drv = _load_driver(a.verb)
        return serve_http(drv, host=a.host or "127.0.0.1", port=a.http, token=_serve_token()) if a.http \
            else serve_stdio(drv)

    if a.target == "gateway":               # mhp gateway init | serve | pair | add-agent <name> | check | status
        from . import gateway
        return gateway.main(a.verb, a.args, server_name=a.name, listen=a.listen, cert=a.cert, key=a.key, host=a.host,
                            install_service=a.install_service, dry_run_service=a.dry_run_service)

    if a.target == "node":                  # mhp node <packages-dir> [--http BASE_PORT] [--install-service | ...]
        import threading
        from pathlib import Path
        from .package import load_driver
        from .transport import serve_http
        from . import service as svc

        if a.uninstall_service:
            r = svc.uninstall()
            for step in r["steps"]:
                print(f"  {step}", file=sys.stderr)
            print(("removed" if r["ok"] else "FAILED: " + r.get("error", "")), file=sys.stderr)
            return 0 if r["ok"] else 1
        if a.service_status:
            r = svc.status()
            if not r["installed"]:
                print(f"no service installed ({r['path']})", file=sys.stderr)
                return 1
            state = "running" if r["running"] else ("stopped" if r["running"] is False else "unknown")
            print(f"installed at {r['path']}: {state}" + (f" ({r['note']})" if r.get("note") else ""), file=sys.stderr)
            return 0

        base = a.http or 18900
        root = Path(a.verb or ".").expanduser()
        folders = sorted(p.parent for p in root.glob("*/DEVICE.md"))
        if not folders:
            ap.error(f"no device packages under {root} (looked for */DEVICE.md)")

        if a.install_service or a.dry_run_service:
            r = svc.install(root, base, dry_run=a.dry_run_service)
            print(f"--- {r['path']} ---", file=sys.stderr)
            print(r["content"], file=sys.stderr)
            for step in r.get("steps", []):
                print(f"  {step}", file=sys.stderr)
            if r["dry_run"]:
                print(f"dry run: nothing written. Command it would run at login/boot:\n  {' '.join(svc._command(root, base))}", file=sys.stderr)
            elif r["ok"]:
                print(f"installed. {r.get('note', '')}", file=sys.stderr)
                print(f"check any time with:  mhp node --service-status\nremove with:           mhp node --uninstall-service", file=sys.stderr)
            else:
                print(f"FAILED: {r.get('error') or 'see steps above'}", file=sys.stderr)
                return 1
            return 0

        from .transport import device_token, device_token_file, is_loopback
        host = a.host or "127.0.0.1"            # nothing listens off this PC unless asked; the relay dials out instead
        token = False if a.no_auth else (a.token or (None if is_loopback(host) else device_token(create=True)))

        # preflight: say what is wrong in words a person at the bench can act on, before anything serves
        import socket
        problems = []
        for i, folder in enumerate(folders):
            if (folder / "config.example.json").is_file() and not (folder / "config.json").is_file():
                copy = "copy" if os.name == "nt" else "cp"
                problems.append(f"{folder.name}: no config.json yet. In that folder run:  {copy} config.example.json config.json"
                                f"\n    then open config.json and fill in the serial numbers / ports / paths it asks for")
            try:
                with socket.socket() as sock:
                    sock.bind((host, base + i))
            except OSError:
                problems.append(f"port {base + i} (for {folder.name}) is already in use. Is another `mhp node` running? "
                                f"Close it (or `mhp node --service-status`), or start with  --http {base + 100}")
        if problems:
            print("\nBEFORE THIS PC CAN SERVE ITS INSTRUMENTS:", file=sys.stderr)
            for pr in problems:
                print(f"  - {pr}", file=sys.stderr)
            print(f"\nthen run again:  mhp node {root}" + (f" --http {base}" if a.http else ""), file=sys.stderr)
            if a.check or any("port" in pr for pr in problems):
                return 1
        elif a.check:
            print(f"all {len(folders)} package(s) under {root} are ready to serve on ports {base}..{base + len(folders) - 1}", file=sys.stderr)
            return 0

        served, drivers = [], {}
        print(f"serving {len(folders)} package(s) from {root}, ports {base}..{base + len(folders) - 1}", file=sys.stderr)
        for i, folder in enumerate(folders):
            port = base + i
            if any(folder.name in pr for pr in problems):
                print(f"  {folder.name:24s} SKIPPED until config.json exists", file=sys.stderr)
                continue
            try:
                drv = load_driver(folder)
            except Exception as e:                          # noqa: BLE001  one bad package must not take the rest down
                print(f"  {folder.name:24s} SKIPPED: {type(e).__name__}: {e}", file=sys.stderr)
                continue
            threading.Thread(target=serve_http, args=(drv,), kwargs={"host": host, "port": port, "token": token},
                             daemon=True).start()
            served.append((drv.descriptor["device"]["id"], port))
            drivers[drv.descriptor["device"]["id"]] = drv
            print(f"  {drv.descriptor['device']['id']:24s} http://{host}:{port}  ({folder})", file=sys.stderr)

        # the relay: this PC dials OUT to a gateway so agents beyond the firewall can reach these devices
        from . import relay as R
        relay_cfg = None
        if a.join:
            try:
                relay_cfg = R.join(a.join[0], a.join[1], drivers, name=a.name)
                print(f"joined gateway {relay_cfg['gateway']} as '{relay_cfg['name']}'; saved to {R.NODE_FILE}", file=sys.stderr)
            except SystemExit as e:
                print(f"\nCOULD NOT JOIN THE GATEWAY: {e}\n  (the instruments are still served locally; fix the above and run the --join command again)", file=sys.stderr)
        elif not a.no_relay:
            relay_cfg = R.load_node_config()
        relay_client = R.RelayClient(relay_cfg, drivers) if relay_cfg and drivers else None
        if relay_client:
            relay_client.start()

        from .discovery import _local_ip
        on_lan = not is_loopback(host)
        ip = host if host not in ("0.0.0.0", "::") else _local_ip()
        tok_where = ("the token you supplied" if a.token else
                     "OPENMHP_DEVICE_TOKEN" if os.environ.get("OPENMHP_DEVICE_TOKEN") else str(device_token_file()))
        print("\n" + "=" * 72 + f"\nThis PC now serves {len(served)} instrument(s). Leave this window open.", file=sys.stderr)
        print(f"To keep serving after a reboot with no window open, run once:  mhp node {root} --install-service", file=sys.stderr)
        if served and on_lan:
            print("\nAgents on the SAME network add the instruments with:", file=sys.stderr)
            for did, port in served:
                print(f"  mhp lab add http://{ip}:{port}", file=sys.stderr)
            if token:
                print(f"  and need the token in {tok_where}  (set OPENMHP_DEVICE_TOKEN=<token> on the agent machine)", file=sys.stderr)
        elif served:
            print("\nAgents on THIS PC add the instruments with:", file=sys.stderr)
            for did, port in served:
                print(f"  mhp lab add http://127.0.0.1:{port}", file=sys.stderr)
            print(f"  No other machine can reach these ports. To serve agents on the lab network too, restart with:  mhp node {root} --host {_local_ip()}", file=sys.stderr)
        if relay_client:
            print(f"\nAgents beyond the firewall: this PC connects out to the gateway {relay_cfg['gateway']} as '{relay_cfg['name']}'.", file=sys.stderr)
            print("  Nothing to open on the lab network. If the gateway is down, this PC keeps retrying by itself.", file=sys.stderr)
        elif served:
            print("\nAgents beyond the firewall: pair this PC with your lab's gateway once. Ask whoever runs it for a code", file=sys.stderr)
            print(f"  (`mhp gateway pair` there), then:  mhp node {root} --join https://<gateway> <code>", file=sys.stderr)
        if token is False and on_lan:
            print("\nWARNING: --no-auth: anyone on this network can drive these instruments, and agents cannot be asked for approvals.", file=sys.stderr)
        print("=" * 72, file=sys.stderr)
        print(("advertising on the LAN if zeroconf is installed (pip install \"openmhp[all]\"); " if on_lan else "") + "Ctrl-C to stop", file=sys.stderr)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            return 0

    if a.target == "lab":                   # mhp lab scan [host ...] | add <target> | accept [<id>] | remove <id> | list | home
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
        elif v == "accept":                 # the owner's own channel: what a bridge must ask a person for, they can do here
            from .client import package_folder
            from .package import declared_rulebook, rulebook_diff
            ids = x or sorted(fleet.diverged())
            if not ids:
                print("every package in this lab is the one it was accepted with", file=sys.stderr)
                return 0
            for did in ids:
                entry = fleet.devices.get(did)
                if entry is None:
                    ap.error(f"no device {did!r} in this lab")
                folder = package_folder(entry["target"])
                if folder is None:
                    print(f"{did}: {entry['target']} is not a package; its configuration lives elsewhere", file=sys.stderr)
                    continue
                changes = rulebook_diff(entry.get("rulebook") or {}, declared_rulebook(folder))
                for line in changes or ["(nothing the device enforces is different)"]:
                    print(f"  {line}", file=sys.stderr)
                fleet.accept(did)
                print(f"accepted: {did} enforces the package at {folder} from now on", file=sys.stderr)
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
            ap.error(f"unknown lab verb {v} (scan|add|accept|location|remove|list|home|demo)")
        return 0

    if a.target == "validate":              # mhp validate <device package folder>
        from .validate import main as vmain
        return vmain([a.verb, *a.args])

    if a.target == "inclusion":             # mhp inclusion <device package folder> [--json]
        from .inclusion import main as imain
        return imain([a.verb, *a.args] if a.verb else [])

    if a.target == "log":                   # mhp log [since] | mhp log audit
        from .runs import RunLog
        log = RunLog()
        if a.verb == "audit":
            r = log.audit()
            print(json.dumps(r, indent=2, default=str))
            return 0 if r["ok"] else 1
        w = log.window(int(a.verb or 0), int((a.args or [100])[0]))
        for e in w["events"]:
            print(json.dumps(e, default=str))
        print(f"# seq {w['seq']}, complete={w['complete']}, verified={w['verified']['ok']} "
              f"({w['verified']['records']} records); mhp log audit checks the whole record", file=sys.stderr)
        return 0 if w["complete"] and w["verified"]["ok"] else 1

    if a.target == "conformance":           # mhp conformance <target> [--json]
        import json as _json
        from .conformance import run as crun, report as creport
        if not a.verb:
            ap.error("mhp conformance <pkg:folder | http://host:port | local:mod:Class>")
        dev = connect(a.verb, "device-under-test")
        result = crun(dev)
        if "--json" in (a.args or []):
            print(_json.dumps(result, indent=2, default=str))
        else:
            print(creport(result))
        return 0 if all(result.get(lv, {}).get("ok") for lv in ("Core",)) else 1

    if a.target == "skills":                # mhp skills install [dir ...]
        from .skills_install import main as smain
        return smain([a.verb or "install", *a.args])

    if a.target == "serve-directory":       # mhp serve-directory manifest.json --http 18900
        from .directory import Directory
        from .transport import serve_http, serve_stdio
        d = Directory.from_manifest(a.verb) if a.verb.endswith(".json") else \
            Directory.from_targets(dict(t.split("=", 1) for t in [a.verb, *a.args]))
        return serve_http(d, host=a.host or "127.0.0.1", port=a.http, token=_serve_token()) if a.http \
            else serve_stdio(d)

    v, x = a.verb, a.args
    try:
        dev = connect(a.target, token=a.token)
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
