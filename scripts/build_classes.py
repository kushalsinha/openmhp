#!/usr/bin/env python3
"""Build openmhp/classes.json, the SPEC 13 device-class vocabulary, from the mapping below.

Every class is the snake_case form of a published label where one exists: Allotrope Foundation
Ontology equipment (AFE, Allotrope first for analytical equipment), then the Chemical Methods
Ontology (CHMO), the Ontology for Biomedical Investigations (OBI) and NCI Thesaurus (NCIT). The
term's definition is fetched once from the OLS (EBI) or TIB terminology service and stored, so
the file works offline. A class of our own is minted only where no vocabulary has the term; it
carries `ref: null` and a `propose_to` hint. `match` says how close the reference is: `exact`,
`broader` (the term is more general than the class) or `narrower` (more specific).

    python scripts/build_classes.py          # fetch definitions, write openmhp/classes.json
    python scripts/build_classes.py --check  # verify every ref still resolves to its label (needs network)
    python scripts/build_classes.py --table  # print the SPEC 13 markdown rows

Old names stay valid as `aliases`; `mhp validate` accepts them and suggests the canonical one.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "openmhp" / "classes.json"

OBO = "http://purl.obolibrary.org/obo/"
AFO = "http://purl.allotrope.org/ontologies/equipment#"

# slug: (ref, match, aliases, conventions)
MAPPING: dict[str, tuple[str | None, str | None, list[str], str]] = {
    # ---- handling and imaging ----------------------------------------------------------------
    "thermal_cycler": ("OBI:0400116", "exact", ["thermocycler"],
                       "`lid_closed` interlock on the run action; `robot_access_ready`; a run action that is `cancellable`"),
    "liquid_handler": ("OBI:0400112", "exact", [], "`robot_access_ready`; positions named as the vendor names them in `notes`"),
    "robot_arm": ("NCIT:C20678", "broader", [], "a `locations` map; `robot_access_ready` on anything it serves"),
    "stage": (None, None, [], "a `locations` map; `robot_access_ready` on anything it serves"),
    "microscope": ("AFE_0000825", "exact", [], "an `acquire` action returning an image URI in `returns`"),
    "electron_microscope": ("CHMO:0001088", "exact", [],
                            "`vacuum_ready`, `beam_on`, `stage_position` signals; `load_sample` with `robot_access_ready` and `physical.automated_load`; `acquire_image` whose `returns` names the file and magnification; e-stop turns the beam off"),
    "camera": (None, None, [], "an `acquire` action returning an image URI in `returns`"),
    "sampler": ("AFE_0001711", "exact", ["autosampler"], "`robot_access_ready`; positions named as the vendor names them in `notes`"),
    # ---- analytical, method-driven -----------------------------------------------------------
    "chromatograph": ("AFE_0000392", "exact", ["gc", "hplc"],
                      "one method-driven run action (`methods: true`, SPEC 4.5) whose `returns` names the result file or table; `usage_count` counts injections"),
    "mass_spectrometer": ("AFE_0000648", "exact", [], "one method-driven run action whose `returns` names the result file; `usage_count` counts scans or runs"),
    "nuclear_magnetic_resonance_spectrometer": ("AFE_0002280", "exact", ["nmr", "nmr_spectrometer"],
                                                "one method-driven run action whose `returns` names the result folder; `usage_count` counts experiments"),
    "diffractometer": ("CHMO:0000950", "exact", [], "one method-driven scan action whose `returns` names the pattern file; `usage_count` counts scans"),
    "thermal_analyzer": ("AFE_0000733", "narrower", [], "one method-driven run action (DSC, TGA) whose `returns` names the result file; `usage_count` counts runs"),
    "microplate_reader": ("OBI:0001058", "exact", ["plate_reader"],
                          "one protocol-driven read action whose `returns` names the result table; `robot_access_ready` when the tray is out"),
    "dissolution_tester": (None, None, [], "a run action with typed media, speed and sampling times and `returns` naming the sample table; `usage_count` counts runs"),
    "capillary_electrophoresis_instrument": ("OBI:0001132", "exact", ["electrophoresis"],
                                             "one method-driven run action whose `returns` names the result file; `usage_count` counts injections"),
    "real_time_pcr_machine": ("OBI:0001110", "exact", ["qpcr"], "one plate-run action whose `returns` names the result export; `lid_closed` interlock; `usage_count` counts runs"),
    "flow_cytometer": ("CHMO:0001957", "exact", ["cytometer"], "one acquisition action whose `returns` names the FCS files; `usage_count` counts tubes or wells"),
    "spectrometer": ("AFE_0000857", "exact", ["spectrophotometer"], "an `acquire` action with typed integration time whose `returns` carries the spectrum or names its file"),
    "particle_analyzer": (None, None, [], "measurements as signals with units; a `measure` action whose `returns` carries the size distribution summary"),
    "biosensor": ("CHMO:0002795", "exact", [], "measurements as signals with units; `out_of_spec` from the instrument's self-check where it has one"),
    "cell_counter": ("AFE_0000524", "exact", [], "measurements as signals with units; a `count` action whose `returns` carries concentration and viability"),
    "profilometer": ("CHMO:0001994", "exact", [], "a `scan` action with typed length and force whose `returns` names the profile file and the step height"),
    "surface_analyzer": ("CHMO:0002648", "narrower", [], "a method-driven acquisition whose `returns` names the spectrum or image; vacuum readiness as a signal and interlock"),
    "rheometer": (None, None, [], "measured and setpoint temperature as separate signals; a method-driven run action whose `returns` names the result file; `lid_closed` interlock"),
    "mechanical_tester": (None, None, [], "`load`, `extension` and `crosshead_state` signals; `run_test` with typed rate and limits whose `returns` carries peak load and modulus; e-stop halts the crosshead; `hardware_stop: true`"),
    # ---- weighing, dosing, fluids ------------------------------------------------------------
    "balance": ("AFE_0000693", "exact", [], "`weigh` returning `{mass, unit, stable}`; `tare`; `calibration_status` from the instrument's own log where it has one"),
    "dispenser": ("NCIT:C69095", "broader", ["powder_dispenser"], "a `dose` action with typed target mass and tolerance whose `returns` carries the dispensed mass; `calibration_status` from the balance"),
    "pump": ("AFE_0000499", "exact", [], "`flow`/`pressure` signals in UCUM; a `stop` that zeroes the setpoint; `estop: true`"),
    "mass_flow_controller": ("AFE_0001671", "exact", ["flow_controller"], "`flow`/`pressure` signals in UCUM; a `stop` that zeroes the setpoint; `estop: true`"),
    "valve": ("AFE_0000795", "exact", [], "position as a setting with the vendor's names; `estop` leaves the valve where it is unless `safety.notes` says otherwise"),
    "titrator": ("AFE_0000876", "exact", [], "one method-driven titration whose `returns` carries the result and its unit; `usage_count` counts titrations"),
    # ---- temperature, motion, environment ----------------------------------------------------
    "hotplate": (None, None, [], "the measured value and the setpoint as separate signals; `estop` turns heating and stirring off"),
    "stirrer": ("AFE_0000812", "exact", [], "the measured value and the setpoint as separate signals; `estop` stops the motor"),
    "circulator": ("OBI:0400155", "broader", ["water_bath"], "the measured value and the setpoint as separate signals; `circulating` as a signal"),
    "temperature_controller": ("AFE_0000528", "exact", [], "the measured value and the setpoint as separate signals per loop"),
    "incubator": ("OBI:0000136", "exact", [], "the measured value and the setpoint as separate signals; `door_closed` as a signal and an interlock; `robot_access_ready` where a handling system loads it"),
    "oven": ("AFE_0000816", "exact", [], "the measured value and the setpoint as separate signals; `door_closed` as a signal and an interlock"),
    "furnace": ("NCIT:C49965", "exact", ["tube_furnace", "muffle_furnace"],
                "`temperature` and `temperature_setpoint` separate; `program_running` and `segment` signals; `run_program` with typed `segments` (target, ramp, dwell) and `returns`; `door_closed` interlock; watchdog `release`, because an abort mid-sinter is the damage"),
    "environmental_chamber": (None, None, ["stability_chamber", "climate_chamber"], "temperature and humidity measured and setpoint as separate signals; `door_closed` as a signal and an interlock"),
    "glovebox": (None, None, ["glove_box"],
                 "`o2_ppm`, `h2o_ppm`, `box_pressure` signals; `antechamber_state` enum; `antechamber_cycle` with a typed purge count; inner and outer door actions interlocked on each other; `robot_access_ready` only when the inner door is open and the box is still"),
    "shaker": ("OBI:0001076", "narrower", ["incubator_shaker"], "the measured value and the setpoint as separate signals; `lid_closed` interlock; `robot_access_ready` where a handling system loads it"),
    "centrifuge": ("OBI:0400106", "exact", [], "`lid_closed` interlock on the run action; `robot_access_ready`; a run action that is `cancellable`"),
    "lyophilizer": ("OBI:0001087", "exact", ["freeze_dryer"], "`lid_closed`/`door_closed` interlock on the run action; a recipe-driven run that is `cancellable`; watchdog `release`"),
    "rotary_evaporator": ("CHMO:0002199", "exact", ["evaporator", "rotavap"], "bath temperature, rotation and vacuum each as measured and setpoint; `lid_closed`-style interlock on lowering the flask; a run that is `cancellable`"),
    "reactor": ("AFE_0000153", "exact", [], "the measured value and the setpoint as separate signals; `door_closed`/`lid_closed` as a signal and an interlock where there is one; a recipe-driven run with `returns`"),
    "bioreactor": ("OBI:0001046", "exact", [], "the measured value and the setpoint as separate signals per loop; a recipe-driven run with `returns`; `robot_access_ready` where a sampler meets it"),
    "cryostat": ("OBI:0001072", "exact", [], "temperature and field measured and setpoint as separate signals; `chamber_state` enum; watchdog `release`"),
    # ---- synthesis and processing ------------------------------------------------------------
    "spin_coater": (None, None, [], "a `run_recipe` action with typed steps (speed, acceleration, duration) and `returns`; `lid_closed` and `vacuum_ok` interlocks; `estop` stops the chuck"),
    "mill": (None, None, ["ball_mill"], "a `run` action with typed speed and duration and `returns`; `lid_closed` interlock; `estop` stops the drive"),
    "deposition_system": ("CHMO:0002122", "narrower", ["sputter_system", "evaporation_system"],
                          "`base_pressure`, `process_pressure`, `power`/`power_setpoint`, `shutter_open`, `substrate_temperature` signals; `deposit` with `returns` carrying the thickness estimate; `base_pressure_ok` and `door_closed` interlocks; `hardware_stop: true` where the tool has one"),
    "3d_printer": (None, None, [], "a `print` action taking a file URI whose `returns` names the job; `door_closed` interlock; `estop` disables the heaters"),
    "cnc": (None, None, [], "a `run_program` action taking a file URI; `door_closed` interlock; `estop: true`"),
    "laser": ("OBI:0400064", "exact", [], "output enable as a boolean setting; `shutter_open` as a signal; `estop` closes the shutter and disables emission"),
    # ---- electrical and electrochemical ------------------------------------------------------
    "potentiostat": ("CHMO:0002427", "exact", [], "output enable as a boolean setting; `estop` disables every output; `returns` on acquisitions names the data file"),
    "battery_cycler": (None, None, ["battery_tester"],
                       "a `channel` parameter on every action; `start_protocol` with typed steps (mode, current, voltage, time limits) and `returns` carrying cycle count and last capacity; `channel_state` signal; `estop` opens every channel"),
    "source_meter": (None, None, ["source_measure_unit"], "output enable as a boolean setting; `estop` disables every output; `returns` on sweeps names the data file"),
    "lock_in_amplifier": ("CHMO:0002340", "exact", [], "output enable as a boolean setting; `estop` disables every output; `returns` on acquisitions names the data file"),
    "oscilloscope": ("OBI:0000948", "exact", [], "an `acquire` action whose `returns` names the waveform file"),
    "power_supply": ("OBI:0400142", "exact", [], "output enable as a boolean setting; `estop` disables every output"),
    "data_acquisition_device": ("AFE_0000555", "exact", ["daq"], "channels as signals with units; output enable as a boolean setting; `estop` disables every output"),
    "sensor": ("AFE_0002184", "exact", [], "measurements as signals with units; `out_of_spec` from the instrument's self-check where it has one"),
    "vacuum_gauge": (None, None, ["pressure_gauge"], "pressure as a signal in UCUM; `out_of_spec` from the gauge's self-check where it has one"),
    "generic": (None, None, [], "no convention; name the capabilities plainly and say in `notes` what the device is"),
}

# conventions per class are deliberately short; the full text lives in SPEC 13


def _get(url: str) -> dict:
    for _ in range(3):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.load(r)
        except Exception:                                  # noqa: BLE001
            time.sleep(1.5)
    return {}


def resolve(ref: str) -> dict | None:
    """Label, definition and IRI of a CURIE from OLS (OBO ontologies) or TIB (Allotrope)."""
    if ref.startswith("AFE_"):
        d = _get(f"https://api.terminology.tib.eu/api/search?q={ref}&ontology=afo&rows=5")
        for x in d.get("response", {}).get("docs", []):
            if x.get("short_form") == ref and str(x.get("iri", "")).startswith("http://purl.allotrope.org"):
                return {"label": x.get("label"), "definition": (x.get("description") or [None])[0], "iri": x["iri"],
                        "source": "Allotrope Foundation Ontology (AFO) equipment, CC-BY"}
        return None
    prefix, local = ref.split(":")
    iri = OBO + f"{prefix}_{local}"
    d = _get(f"https://www.ebi.ac.uk/ols4/api/ontologies/{prefix.lower()}/terms/"
             + urllib.parse.quote(urllib.parse.quote(iri, safe=""), safe=""))
    if not d.get("label"):
        return None
    source = {"CHMO": "Chemical Methods Ontology (CHMO), CC-BY", "OBI": "Ontology for Biomedical Investigations (OBI), CC-BY",
              "NCIT": "NCI Thesaurus (NCIT), public domain"}[prefix]
    return {"label": d["label"], "definition": (d.get("description") or [None])[0], "iri": iri, "source": source}


def build(fetch: bool = True) -> dict:
    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    out = {}
    for slug, (ref, match, aliases, conv) in MAPPING.items():
        entry = {"ref": ref, "match": match, "aliases": aliases, "conventions": conv}
        if ref:
            prev = old.get(slug, {})
            info = resolve(ref) if fetch else None
            if info is None and prev.get("ref") == ref:
                info = {k: prev.get(k) for k in ("label", "definition", "iri", "source")}
            if info is None:
                raise SystemExit(f"{slug}: cannot resolve {ref}")
            entry.update(info)
        else:
            entry.update({"label": None, "definition": None, "iri": None, "source": None,
                          "propose_to": "no published term; propose to the Allotrope Foundation or OBI"})
        out[slug] = entry
    return out


def check() -> int:
    bad = 0
    current = json.loads(OUT.read_text())
    for slug, e in current.items():
        if not e.get("ref"):
            continue
        info = resolve(e["ref"])
        if info is None:
            print(f"[ ] {slug}: {e['ref']} did not resolve (network?)")
            bad += 1
        elif info["label"] != e.get("label"):
            print(f"[ ] {slug}: {e['ref']} is now labelled {info['label']!r}, file says {e.get('label')!r}")
            bad += 1
    print(f"{len(current)} classes, {sum(1 for e in current.values() if e.get('ref'))} with references, {bad} problem(s)")
    return 1 if bad else 0


def table() -> str:
    rows = ["| class | reference | convention |", "|---|---|---|"]
    for slug, e in json.loads(OUT.read_text()).items():
        ref = f"[{e['ref']}]({e['iri']})" + ("" if e["match"] == "exact" else f" ({e['match']})") if e.get("ref") else "none yet"
        al = f" (also `{'`, `'.join(e['aliases'])}`)" if e.get("aliases") else ""
        rows.append(f"| `{slug}`{al} | {ref} | {e['conventions']} |")
    return "\n".join(rows)


def main(argv: list[str]) -> int:
    if "--check" in argv:
        return check()
    if "--table" in argv:
        print(table())
        return 0
    data = build(fetch="--offline" not in argv)
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(data)} classes, "
          f"{sum(1 for e in data.values() if e['ref'])} with references")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
