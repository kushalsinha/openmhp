#!/usr/bin/env python3
"""Generate assets/hero.svg: a pixel-block wordmark with a circuit-trace outline.

    python assets/make_hero.py            -> assets/hero.svg, assets/hero-dark.svg
"""
from pathlib import Path

# 5x7 pixel glyphs (rows top to bottom, '#' = block)
GLYPHS = {
    "O": ["#####", "#...#", "#...#", "#...#", "#...#", "#...#", "#####"],
    "P": ["#####", "#...#", "#...#", "#####", "#....", "#....", "#...."],
    "E": ["#####", "#....", "#....", "####.", "#....", "#....", "#####"],
    "N": ["#...#", "##..#", "##..#", "#.#.#", "#..##", "#..##", "#...#"],
    "M": ["#...#", "##.##", "#.#.#", "#.#.#", "#...#", "#...#", "#...#"],
    "H": ["#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"],
    " ": [".....", ".....", ".....", ".....", ".....", ".....", "....."],
}
CELL, GAP, LETTER_GAP, LINE_GAP = 22, 3, 18, 40
TEAL, TRACE = "#3FB59A", "#2B8F78"


def layout(lines: list[str]):
    """Yield (x, y) of every block, plus per-letter bounding boxes."""
    blocks, boxes = [], []
    y0 = 0
    width = 0
    for line in lines:
        x0 = 0
        for ch in line:
            g = GLYPHS[ch]
            bx, by = x0, y0
            for r, row in enumerate(g):
                for c, px in enumerate(row):
                    if px == "#":
                        blocks.append((x0 + c * (CELL + GAP), y0 + r * (CELL + GAP)))
            w = 5 * CELL + 4 * GAP
            boxes.append((bx, by, w, 7 * CELL + 6 * GAP, ch))
            x0 += w + LETTER_GAP
        width = max(width, x0 - LETTER_GAP)
        y0 += 7 * CELL + 6 * GAP + LINE_GAP
    return blocks, boxes, width, y0 - LINE_GAP


def trace_path(g: list[str], ox: int, oy: int) -> str:
    """A thin 'circuit trace' following the letter's outer cells, offset down-right."""
    pts = []
    for r, row in enumerate(g):
        for c, px in enumerate(row):
            if px == "#":
                x, y = ox + c * (CELL + GAP), oy + r * (CELL + GAP)
                pts.append((x, y))
    # outline: union of cell rectangles, drawn as one polyline around each cell edge that borders empty space
    d = []
    cells = {(c, r) for r, row in enumerate(g) for c, px in enumerate(row) if px == "#"}
    for (c, r) in cells:
        x, y = ox + c * (CELL + GAP), oy + r * (CELL + GAP)
        x2, y2 = x + CELL, y + CELL
        if (c, r - 1) not in cells: d.append(f"M{x},{y}H{x2}")
        if (c, r + 1) not in cells: d.append(f"M{x},{y2}H{x2}")
        if (c - 1, r) not in cells: d.append(f"M{x},{y}V{y2}")
        if (c + 1, r) not in cells: d.append(f"M{x2},{y}V{y2}")
    return " ".join(d)


def svg(lines, dark=False):
    blocks, boxes, w, h = layout(lines)
    pad, off = 30, 9
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w + 2 * pad + off} {h + 2 * pad + off}" width="{(w + 2 * pad + off) // 2}" role="img" aria-label="{" ".join(lines)}">']
    if dark:
        out.append(f'<rect width="100%" height="100%" fill="#121618"/>')
    # traces first (behind), offset
    for (bx, by, bw, bh, ch) in boxes:
        if ch == " ":
            continue
        out.append(f'<path d="{trace_path(GLYPHS[ch], bx + pad + off, by + pad + off)}" fill="none" stroke="{TRACE}" stroke-width="2.5" stroke-linecap="square" opacity="0.9"/>')
    for (x, y) in blocks:
        out.append(f'<rect x="{x + pad}" y="{y + pad}" width="{CELL}" height="{CELL}" rx="2" fill="{TEAL}"/>')
    out.append("</svg>")
    return "\n".join(out)


if __name__ == "__main__":
    here = Path(__file__).parent
    (here / "hero.svg").write_text(svg(["OPEN", "MHP"]))
    (here / "hero-dark.svg").write_text(svg(["OPEN", "MHP"], dark=True))
    print("wrote assets/hero.svg, assets/hero-dark.svg")
