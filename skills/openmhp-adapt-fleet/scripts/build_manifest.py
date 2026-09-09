#!/usr/bin/env python3
"""Build a directory manifest by asking each running MHP server for its card.

    python build_manifest.py fleet.json arm-01=http://bay3-pc:18921 star-01=http://bay1-pc:18921
    mhp serve-directory fleet.json --http 18900
"""
import sys

from openmhp.directory import Directory

if len(sys.argv) < 3:
    sys.exit(__doc__)
out, targets = sys.argv[1], dict(a.split("=", 1) for a in sys.argv[2:])
d = Directory.from_targets(targets)
d.save_manifest(out)
print(f"{len(d.cards)} devices -> {out}")
for cid, card in d.cards.items():
    print(f"  {cid:24s} {card['class']:16s} {card.get('location', ''):14s} {card.get('notes', '')[:50]}")
