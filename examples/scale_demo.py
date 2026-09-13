"""Scale demo: 2,000 devices, one agent, no context overload.

Builds a lab of 2,000 simulated instruments across 8 classes and 40 bays,
indexes them in an MHP Directory, and shows what the agent's context would
cost the old way (every descriptor up front) versus the MHP way (search,
then open one).

    PYTHONPATH=. python examples/scale_demo.py
"""
import json
import random
import time

from openmhp.directory import Directory
from openmhp.driver import Driver
from openmhp.client import Lab, LocalDevice
from openmhp.devices.sim_thermocycler import DESCRIPTOR as TC
from openmhp.devices.sim_arm import DESCRIPTOR as ARM

random.seed(7)
CLASSES = {
    "thermocycler": ("Bio-Rad C1000", "96-well block. Lid must be closed before a run."),
    "liquid_handler": ("Opentrons Flex", "8-channel pipetting robot with gripper. Keep deck clear of loose tips."),
    "robot_arm": ("PF400", "Plate-handling arm between deck and instruments. Light curtain interlock."),
    "microscope": ("Nikon Ti2 confocal", "Inverted confocal for live-cell imaging. Objective turret is fragile."),
    "plate_reader": ("BMG CLARIOstar", "Absorbance/fluorescence/luminescence plate reader."),
    "centrifuge": ("Eppendorf 5910", "Swing-bucket centrifuge. Balance loads within 1 g."),
    "incubator": ("Thermo Heracell", "CO2 incubator at 37 C. Door open >30 s drops humidity."),
    "hotplate": ("IKA C-MAG", "Magnetic stirrer hotplate in fume hood. Plate reaches 500 C."),
}
TAGS = {"thermocycler": ["pcr", "heating"], "liquid_handler": ["pipetting", "plates"], "robot_arm": ["plates", "motion"],
        "microscope": ["imaging", "confocal"], "plate_reader": ["assay", "optical"], "centrifuge": ["spin"],
        "incubator": ["cells", "37c"], "hotplate": ["heating", "chemistry"]}


class SimGeneric(Driver):
    """Any descriptor, trivial behaviour: enough to be indexed and described."""
    def __init__(self, descriptor):
        self.descriptor = descriptor
        super().__init__()
    def on_read(self, name): return 0
    def on_write(self, name, value): pass
    def on_invoke(self, job): return {"ok": True}


def make_device(i: int) -> Driver:
    cls = random.choice(list(CLASSES))
    make_model, blurb = CLASSES[cls]
    base = TC if cls == "thermocycler" else ARM if cls == "robot_arm" else TC
    d = json.loads(json.dumps(base))                      # deep copy
    bay = f"bay {i % 40 + 1}"
    d["device"] = {"id": f"{cls}-{i:04d}", "class": cls, "make": make_model.split()[0],
                   "model": " ".join(make_model.split()[1:]), "location": bay, "tags": TAGS[cls],
                   "description": blurb, "notes": f"{blurb} Located in {bay}, bench {i % 6 + 1}."}
    return SimGeneric(d)


t0 = time.time()
drivers = {f"dev{i}": make_device(i) for i in range(2000)}
directory = Directory()
for name, drv in drivers.items():
    directory.add_driver(drv, f"local:{name}")             # in-process targets for the demo
print(f"indexed {len(directory.cards)} devices in {time.time()-t0:.2f}s")
print("classes:", directory.stats()["by_class"])

tok = lambda obj: len(json.dumps(obj)) // 4                # rough tokens
full_all = sum(tok(d.rpc("device/describe", {}, "x")) for d in drivers.values())
print(f"\nold way  : every descriptor in context up front  = {full_all:>9,} tokens")

q = "heat a 96-well plate to 95 C for PCR in bay 12"
t0 = time.time()
hits = directory.search(q, cls="thermocycler", state="idle", limit=5)
print(f"MHP way  : mhp_find({q!r})  [{(time.time()-t0)*1000:.1f} ms]")
for h in hits:
    print(f"           {h['id']:22s} {h['location']:8s} score {h['score']:5.2f}  {h['description'][:50]}")
cards = tok(hits)
chosen = drivers[hits[0]["target"].split(":")[1]]
summary = tok(chosen.rpc("device/describe", {"detail": "summary"}, "x"))
one_action = tok(chosen.rpc("device/describe", {"select": {"actions": ["run_protocol"], "settings": ["target_temperature"]}}, "x"))
print(f"           5 cards                                  = {cards:>9,} tokens")
print(f"           + summary of the chosen device           = {summary:>9,} tokens")
print(f"           + full spec of the 2 items it will use   = {one_action:>9,} tokens")
print(f"           total                                    = {cards+summary+one_action:>9,} tokens "
      f"({100*(cards+summary+one_action)/full_all:.2f}% of the old way)")

# And the agent operates it exactly as before, through the same client:
dev = LocalDevice(chosen, hits[0]["id"])
print("\noperate  :", dev.info["device"]["id"], "->", dev.write("target_temperature", 95))
