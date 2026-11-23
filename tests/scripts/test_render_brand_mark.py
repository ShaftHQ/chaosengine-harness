"""Scan of the lockup symbol: coverage, aperture, gates, and the red core.

``lockup-dark.svg`` uses the same Quantum Mandate paths as
``symbol-primary.svg``. A quadrant that lights on any armour sample fattens
those strokes until the gates weld to each other and to the spine, and a mixed
cell that votes core paints that red across armour quadrants.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SVG = ROOT / "assets" / "brand" / "symbol-primary.svg"
# UL, UR, LL, LR. Matches render_brand_mark.QUADS.
_BITS = (0x1, 0x2, 0x4, 0x8)

# Points in the symbol's user space. Empty points sit in negative space of the
# lockup. Ink points sit on the C, the spine, the three gates, and the core.
_INK = {
    "c armour": (400.0, 180.0),
    "core": (548.0, 486.0),
    "spine": (640.0, 200.0),
    "upper gate": (800.0, 250.0),
    "middle gate": (780.0, 460.0),
    "lower gate": (800.0, 760.0),
}
# Gaps an any-hit sample fills. The 5x8 tier is too coarse to open the two
# lower gate slots; those stay out of this list.
_GAPS = {
    (8, 13): {
        "aperture": (450.0, 500.0),
        "upper gate clear of the middle gate": (780.0, 390.0),
        "middle gates clear of each other": (760.0, 524.0),
        "lower gate clear of the bottom gate": (760.0, 660.0),
    },
    (5, 8): {
        "aperture": (450.0, 500.0),
        "spine clear of the upper gate": (676.0, 220.0),
        "spine clear of the lower gate": (676.0, 780.0),
        "upper gate clear of the middle gate": (780.0, 390.0),
    },
}


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    spec.loader.exec_module(module)
    return module


MARK = load("ce_render_brand_mark", ROOT / "scripts" / "ci" / "render_brand_mark.py")


def _rect(x0: float, y0: float, x1: float, y1: float) -> list[list[tuple[float, float]]]:
    return [[(x0, y0), (x1, y0), (x1, y1), (x0, y1)]]


def _source(layers, x: float, y: float) -> str:
    kind = ""
    for layer_kind, subpaths in layers:
        if MARK.covered(subpaths, x, y):
            kind = layer_kind
    return {"core": "c", "armour": "a"}.get(kind, " ")


def _letterbox(layers, rows: int, cols: int):
    left, top, right, bottom = MARK.ink_box(layers)
    ink_w = right - left
    ink_h = bottom - top
    box_w = float(cols)
    box_h = float(rows * 2)
    scale = min(box_w / ink_w, box_h / ink_h)
    drawn_w = ink_w * scale
    drawn_h = ink_h * scale
    return {
        "left": left,
        "top": top,
        "pad_x": (box_w - drawn_w) / 2.0,
        "pad_y": (box_h - drawn_h) / 2.0,
        "scale": scale,
        "x_step": box_w / (cols * 2),
        "y_step": box_h / (rows * 2),
        "box_w": box_w,
        "box_h": box_h,
    }


def _pixel(box, x: float, y: float) -> tuple[int, int]:
    sx = box["pad_x"] + (x - box["left"]) * box["scale"]
    sy = box["pad_y"] + (y - box["top"]) * box["scale"]
    if not (0 <= sx < box["box_w"] and 0 <= sy < box["box_h"]):
        raise AssertionError(f"({x}, {y}) is outside the mark")
    px = min(int(box["box_w"] / box["x_step"]) - 1, int(sx / box["x_step"]))
    py = min(int(box["box_h"] / box["y_step"]) - 1, int(sy / box["y_step"]))
    return px, py


def _quadrant(table, box, x: float, y: float) -> str:
    """Ink of the quadrant that contains this symbol point, after cell voting."""
    px, py = _pixel(box, x, y)
    row, col = py // 2, px // 2
    glyphs, mask = table[row]
    bits = next(key for key, value in MARK.QUADS.items() if value == glyphs[col])
    if bits & _BITS[(py % 2) * 2 + (px % 2)] == 0:
        return " "
    return "c" if mask[col] == "c" else "a"


def _centers(table, layers, rows: int, cols: int):
    box = _letterbox(layers, rows, cols)
    found = []
    for row, (glyphs, mask) in enumerate(table):
        for col, glyph in enumerate(glyphs):
            bits = next(key for key, value in MARK.QUADS.items() if value == glyph)
            for index, bit in enumerate(_BITS):
                if bits & bit == 0:
                    continue
                px = col * 2 + index % 2
                py = row * 2 + index // 2
                x = box["left"] + ((px + 0.5) * box["x_step"] - box["pad_x"]) / box["scale"]
                y = box["top"] + ((py + 0.5) * box["y_step"] - box["pad_y"]) / box["scale"]
                found.append((mask[col], _source(layers, x, y), row, col))
    return found


def test_thin_armour_sample_does_not_count_as_coverage() -> None:
    """One or two armour samples must not light a quadrant. A solid core must."""
    layers = [
        ("armour", _rect(0.02, 0.02, 0.12, 0.70)),
        ("core", _rect(1.0, 0.0, 2.0, 2.0)),
    ]
    glyphs, mask = MARK.raster(layers, 1, 2)[0]
    assert glyphs[0] == " "
    assert mask[0] == " "
    assert glyphs[1] == "█"
    assert mask[1] == "c"
    assert MARK.COVERAGE == MARK.SAMPLES * MARK.SAMPLES // 2 + 1


def test_wide_and_stack_keep_the_aperture_and_the_gate_gaps() -> None:
    layers = MARK.load_layers(SVG.read_text(encoding="utf-8"))
    for rows, cols in (MARK.WIDE, MARK.STACK):
        table = MARK.raster(layers, rows, cols)
        box = _letterbox(layers, rows, cols)
        for name, point in _GAPS[(rows, cols)].items():
            assert _source(layers, *point) == " ", name
            assert _quadrant(table, box, *point) == " ", (rows, cols, name)
        for name, point in _INK.items():
            expect = _source(layers, *point)
            assert expect in {"a", "c"}, name
            assert _quadrant(table, box, *point) == expect, (rows, cols, name)


def test_red_core_never_bleeds_into_armour() -> None:
    """A tie paints only the core quadrants. Armour never keeps a core quadrant."""
    tied = [
        ("armour", _rect(0.0, 0.0, 0.5, 2.0)),
        ("core", _rect(0.5, 0.0, 1.0, 2.0)),
    ]
    glyph, mask = MARK.raster(tied, 1, 1)[0]
    bits = next(key for key, value in MARK.QUADS.items() if value == glyph)
    assert mask == "c"
    assert bits & 0xA == 0xA
    assert bits & 0x5 == 0

    # The right cell keeps a solid core so the scan's core check still has one.
    armour_wins = [
        ("armour", _rect(0.0, 0.0, 1.0, 2.0)),
        ("core", _rect(0.0, 0.0, 0.5, 1.0) + _rect(1.0, 0.0, 2.0, 2.0)),
    ]
    row = MARK.raster(armour_wins, 1, 2)
    glyph, mask = row[0]
    bits = next(key for key, value in MARK.QUADS.items() if value == glyph[0])
    assert mask[0] == " "
    assert bits & 0x1 == 0
    assert bits & 0xE == 0xE
    assert mask[1] == "c"

    layers = MARK.load_layers(SVG.read_text(encoding="utf-8"))
    for rows, cols in (MARK.WIDE, MARK.STACK):
        table = MARK.raster(layers, rows, cols)
        centers = _centers(table, layers, rows, cols)
        assert any(painted == "c" for painted, _source_kind, _row, _col in centers)
        for painted, source, row, col in centers:
            if painted == "c":
                assert source == "c", (rows, cols, row, col, source)
            else:
                assert source != "c", (rows, cols, row, col, source)
