"""Measurements for the OpenMHP paper's figures. Writes CSV next to this file.

    PYTHONPATH=. python paper/figures/bench.py

Three experiments:
  context.csv   tokens in the agent's context vs laboratory size, naive vs progressive
  retrieval.csv whether search returns a device satisfying the task's constraints, vs size
  effort.csv    source lines per instrument integration, by route

Token counts use the same proxy as examples/scale_demo.py (len(json)//4) so that the
numbers here and the 1,224,382 figure in the specification are produced the same way.
It is a proxy, not a tokeniser, and the paper says so.
"""
import csv
import json
import random
import statistics
import subprocess
import time
from pathlib import Path

from openmhp.directory import Directory
from openmhp.driver import Driver
from openmhp.devices.sim_thermocycler import DESCRIPTOR as TC
from openmhp.devices.sim_arm import DESCRIPTOR as ARM

HERE = Path(__file__).parent
ROOT = HERE.parent.parent

CLASSES = {
    "thermocycler":   ("Bio-Rad C1000", "96-well block. Lid must be closed before a run.", ["pcr", "heating"]),
    "liquid_handler": ("Opentrons Flex", "8-channel pipetting robot with gripper.", ["pipetting", "plates"]),
    "robot_arm":      ("PF400", "Plate-handling arm. Light curtain interlock.", ["plates", "motion"]),
    "microscope":     ("Nikon Ti2 confocal", "Inverted confocal for live-cell imaging.", ["imaging", "confocal"]),
    "plate_reader":   ("BMG CLARIOstar", "Absorbance/fluorescence plate reader.", ["assay", "optical"]),
    "centrifuge":     ("Eppendorf 5910", "Swing-bucket centrifuge. Balance within 1 g.", ["spin"]),
    "incubator":      ("Thermo Heracell", "CO2 incubator at 37 C.", ["cells", "37c"]),
    "hotplate":       ("IKA C-MAG", "Magnetic stirrer hotplate in fume hood.", ["heating", "chemistry"]),
}
# task-level phrasing, deliberately NOT copied from the device description, so that
# retrieval is not being graded on its ability to echo a string back.
INTENT = {
    "thermocycler":   "run a 30 cycle PCR on a 96 well plate",
    "liquid_handler": "pipette reagents into a plate",
    "robot_arm":      "move a plate between the deck and an instrument",
    "microscope":     "image live cells at high magnification",
    "plate_reader":   "measure absorbance of a plate",
    "centrifuge":     "spin down samples",
    "incubator":      "keep cells at 37 C overnight",
    "hotplate":       "heat and stir a flask",
}
NBAYS = 40


class SimGeneric(Driver):
    def __init__(self, descriptor):
        self.descriptor = descriptor
        super().__init__()
    def on_read(self, name): return 0
    def on_write(self, name, value): pass
    def on_invoke(self, job): return {"ok": True}


def make_device(i, rng):
    cls = rng.choice(list(CLASSES))
    make_model, blurb, tags = CLASSES[cls]
    base = ARM if cls == "robot_arm" else TC
    d = json.loads(json.dumps(base))
    bay = f"bay {i % NBAYS + 1}"
    d["device"] = {"id": f"{cls}-{i:05d}", "class": cls, "make": make_model.split()[0],
                   "model": " ".join(make_model.split()[1:]), "location": bay, "tags": tags,
                   "description": blurb, "notes": f"{blurb} Located in {bay}, bench {i % 6 + 1}."}
    return cls, bay, SimGeneric(d)


tok = lambda obj: len(json.dumps(obj)) // 4


def build(n, seed=7):
    rng = random.Random(seed)
    drivers, meta = {}, {}
    for i in range(n):
        cls, bay, drv = make_device(i, rng)
        key = f"dev{i}"
        drivers[key] = drv
        meta[key] = (cls, bay)
    d = Directory()
    for key, drv in drivers.items():
        d.add_driver(drv, f"local:{key}")
    return drivers, meta, d


# ---------------------------------------------------------------- experiment 1
def context_curve(sizes):
    rows = []
    for n in sizes:
        drivers, meta, directory = build(n)
        naive = sum(tok(drv.rpc("device/describe", {}, "x")) for drv in drivers.values())
        hits = directory.search("run a 30 cycle PCR on a 96 well plate in bay 12",
                                cls="thermocycler", limit=5)
        chosen = drivers[hits[0]["target"].split(":")[1]]
        prog = (tok(hits)
                + tok(chosen.rpc("device/describe", {"detail": "summary"}, "x"))
                + tok(chosen.rpc("device/describe",
                                 {"select": {"actions": ["run_protocol"],
                                             "settings": ["target_temperature"]}}, "x")))
        rows.append({"devices": n, "naive_tokens": naive, "progressive_tokens": prog,
                     "ratio_pct": round(100 * prog / naive, 4)})
        print(f"  n={n:>6}  naive={naive:>10,}  progressive={prog:>6,}  "
              f"({100*prog/naive:.3f}%)")
    return rows


# ---------------------------------------------------------------- experiment 2
def retrieval_curve(sizes, trials=200):
    """A query names a task and a bay. Success = the returned device is of the class that
    performs that task AND sits in the requested bay. With many same-class devices per bay,
    exact-id match is not well defined, so constraint satisfaction is the honest metric.

    Three conditions, to separate the ranker from the protocol's own structure:
      free      BM25 over the free-text query alone
      +class    the class filter directory/search already accepts
      +both     class and location filters, which is what mhp_find actually issues
    """
    rows = []
    for n in sizes:
        drivers, meta, directory = build(n)
        rng = random.Random(11)
        hit = {"free": 0, "cls": 0, "both": 0}
        lats = []
        k = 0
        for _ in range(trials):
            cls = rng.choice(list(CLASSES))
            bay = f"bay {rng.randint(1, NBAYS)}"
            if not any(m == (cls, bay) for m in meta.values()):
                continue
            k += 1
            q = f"{INTENT[cls]} in {bay}"
            want = (cls, bay)

            t0 = time.perf_counter()
            free = directory.search(q, limit=5)
            lats.append((time.perf_counter() - t0) * 1000)
            byc = directory.search(q, cls=cls, limit=5)
            both = directory.search(q, cls=cls, location=bay, limit=5)

            for label, hits in (("free", free), ("cls", byc), ("both", both)):
                got = [meta[h["target"].split(":")[1]] for h in hits]
                if got and got[0] == want:
                    hit[label] += 1
        k = k or 1
        rows.append({"devices": n, "trials": k,
                     "free_top1_pct": round(100 * hit["free"] / k, 2),
                     "class_top1_pct": round(100 * hit["cls"] / k, 2),
                     "both_top1_pct": round(100 * hit["both"] / k, 2),
                     "p50_ms": round(statistics.median(lats), 3),
                     "p95_ms": round(sorted(lats)[int(0.95 * len(lats)) - 1], 3)})
        r = rows[-1]
        print(f"  n={n:>6}  free={r['free_top1_pct']:5.1f}%  +class={r['class_top1_pct']:5.1f}%  "
              f"+both={r['both_top1_pct']:5.1f}%  p50={r['p50_ms']:.2f}ms  p95={r['p95_ms']:.2f}ms")
    return rows


# ---------------------------------------------------------------- experiment 3
def sloc(path):
    """Non-blank, non-comment source lines."""
    n = 0
    for line in Path(path).read_text().splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            n += 1
    return n


ROUTE = {
    "ika-c-mag-hs7": "serial (declared commands)",
    "manual-benchtop-centrifuge": "operator prompts",
    "opentrons-flex": "PyLabRobot adapter",
    "elveflow-ob1": "vendor SDK",
    "elveflow-mux-distributor": "vendor SDK",
    "biologic-sp300": "vendor SDK",
    "wasatch-raman-blaze": "vendor SDK",
    "sri-8610c-gc": "vendor SDK (.NET)",
}


def effort_table():
    rows = []
    for pkg in sorted((ROOT / "supported-devices").iterdir()):
        drv = pkg / "driver.py"
        desc = pkg / "descriptor.yaml"
        if not drv.is_file():
            continue
        rows.append({"package": pkg.name, "route": ROUTE.get(pkg.name, "unknown"),
                     "driver_sloc": sloc(drv),
                     "descriptor_lines": len(desc.read_text().splitlines()) if desc.is_file() else 0})
        print(f"  {pkg.name:30s} {rows[-1]['route']:26s} driver={rows[-1]['driver_sloc']:>4} "
              f"descriptor={rows[-1]['descriptor_lines']:>4}")
    return rows


def write(name, rows):
    if not rows:
        return
    with open(HERE / name, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"  -> {name}")


if __name__ == "__main__":
    SIZES = [10, 25, 50, 100, 250, 500, 1000, 2000, 5000, 10000]
    print("context cost vs laboratory size")
    write("context.csv", context_curve(SIZES))
    print("\nretrieval under growth")
    write("retrieval.csv", retrieval_curve(SIZES))
    print("\nintegration effort per instrument")
    write("effort.csv", effort_table())
