"""Finding MHP devices on the network.

Two mechanisms, both optional to the protocol and both used by ``mhp lab scan``:

1. mDNS / DNS-SD: servers advertise ``_mhp._tcp.local.`` with TXT records
   ``id``, ``class``, ``path=/mhp.json``. Needs the ``zeroconf`` package
   (``pip install openmhp[discovery]``); silently skipped without it.
2. HTTP probe: GET ``http://host:port/mhp.json`` on a list of hosts and the
   default MHP port range. Works everywhere, including networks that block
   multicast. The probe is parallel and each request has a short timeout.
"""
from __future__ import annotations

import json
import socket
import urllib.request
from concurrent.futures import ThreadPoolExecutor

DEFAULT_PORTS = list(range(18900, 18940))     # directory on 18900, devices from 18921 by convention
SERVICE = "_mhp._tcp.local."
_registered: dict = {}


# ------------------------------------------------------------- mDNS ---- #
def advertise(card: dict, port: int, host: str = "0.0.0.0") -> bool:
    """Announce a device (or directory) on the LAN. Returns False if zeroconf is missing."""
    try:
        from zeroconf import ServiceInfo, Zeroconf
    except ImportError:
        return False
    ip = _local_ip() if host in ("0.0.0.0", "") else host
    name = f"{card['id']}.{SERVICE}"
    info = ServiceInfo(SERVICE, name, addresses=[socket.inet_aton(ip)], port=port,
                       properties={"id": card["id"], "class": card.get("class", ""), "path": "/mhp.json",
                                   "mhp": card.get("mhp", "")}, server=f"{card['id']}.local.")
    zc = _registered.setdefault("zc", Zeroconf())
    zc.register_service(info)
    _registered[name] = info
    return True


def scan_mdns(timeout: float = 2.0) -> list[str]:
    """Return http://host:port targets of devices advertising _mhp._tcp. Empty without zeroconf."""
    try:
        from zeroconf import ServiceBrowser, Zeroconf
    except ImportError:
        return []
    import time
    found: list[str] = []

    class L:
        def add_service(self, zc, typ, name):
            info = zc.get_service_info(typ, name)
            if info and info.addresses:
                found.append(f"http://{socket.inet_ntoa(info.addresses[0])}:{info.port}")
        def update_service(self, *a): pass
        def remove_service(self, *a): pass

    zc = Zeroconf()
    try:
        ServiceBrowser(zc, SERVICE, L())
        time.sleep(timeout)
    finally:
        zc.close()
    return sorted(set(found))


# --------------------------------------------------------- HTTP probe ---- #
def probe(hosts: list[str], ports: list[int] | None = None, timeout: float = 0.4, workers: int = 64) -> list[dict]:
    """GET /mhp.json on every host:port; return [{target, card}] for those that answer."""
    ports = ports or DEFAULT_PORTS

    def one(hp):
        host, port = hp
        target = f"http://{host}:{port}"
        try:
            with urllib.request.urlopen(f"{target}/mhp.json", timeout=timeout) as r:
                d = json.loads(r.read())
            dev = d.get("device") or {}
            if not dev.get("id"):
                return None
            return {"target": target, "id": dev["id"], "class": dev.get("class"), "make": dev.get("make"),
                    "model": dev.get("model"), "location": dev.get("location"),
                    "description": dev.get("description") or (dev.get("notes") or "")[:120], "state": d.get("state")}
        except Exception:                                    # noqa: BLE001  refused, timeout, not MHP
            return None

    pairs = [(h, p) for h in hosts for p in ports]
    with ThreadPoolExecutor(min(workers, max(1, len(pairs)))) as ex:
        return [r for r in ex.map(one, pairs) if r]


def scan(hosts: list[str] | None = None, ports: list[int] | None = None, mdns_timeout: float = 2.0) -> list[dict]:
    """mDNS plus HTTP probe of localhost and any hosts given. Deduplicated by target."""
    hosts = list(dict.fromkeys(["127.0.0.1", *(hosts or [])]))
    found = {r["target"]: r for r in probe(hosts, ports)}
    for target in scan_mdns(mdns_timeout):
        if target not in found:
            host, port = target[len("http://"):].rsplit(":", 1)
            for r in probe([host], [int(port)]):
                found[r["target"]] = r
    return list(found.values())


def _local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except Exception:                                        # noqa: BLE001
        return "127.0.0.1"
    finally:
        s.close()
