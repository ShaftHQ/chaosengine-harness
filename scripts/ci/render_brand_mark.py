#!/usr/bin/env python3
"""Scan-convert the Quantum Mandate symbol into the installer mark table.

The runtime paints this table. It does not parse SVG. CI fails when the
checked-in table drifts from this script.
"""

from __future__ import annotations

import argparse
import math
import re
import struct
import sys
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SVG = ROOT / "assets" / "brand" / "symbol-primary.svg"
LOCKUP_LIGHT = ROOT / "assets" / "brand" / "lockup-light.svg"
LOCKUP_DARK = ROOT / "assets" / "brand" / "lockup-dark.svg"
TARGET = ROOT / "runtime" / "ce_ui.py"
# Wordmark strokes. Neither colour is the core, and neither is blue or cyan.
_ARMOUR_STROKE = {"#10141C", "#F2F7FF"}
_NUMBER = r"-?(?:\d+(?:\.\d+)?|\.\d+)"
START = "# >>> generated: brand_mark\n"
END = "# <<< generated: brand_mark\n"
# Rows, columns. Cell aspect is 1:2, so screen ratio is cols / (rows * 2).
# Wide 13/16 = 0.8125 and stack 8/10 = 0.80 stay within 10% of the SVG ink.
WIDE = (8, 13)
STACK = (5, 8)
SAMPLES = 3
# Majority of the 3x3 sample. One armour hit is not coverage: it fattens the
# stroke until the gates weld to the spine and to each other.
COVERAGE = SAMPLES * SAMPLES // 2 + 1

# UL=1, UR=2, LL=4, LR=8. One code point per occupied 2x2 cell.
QUADS = {
    0x0: " ",
    0x1: "▘",
    0x2: "▝",
    0x3: "▀",
    0x4: "▖",
    0x5: "▌",
    0x6: "▞",
    0x7: "▛",
    0x8: "▗",
    0x9: "▚",
    0xA: "▐",
    0xB: "▜",
    0xC: "▄",
    0xD: "▙",
    0xE: "▟",
    0xF: "█",
}


def parse_path(body: str, *, min_points: int = 3) -> list[list[tuple[float, float]]]:
    """Filled symbol paths need 3 points. Wordmark strokes also keep a single segment."""
    tokens = re.findall(r"[MLHVZ]|-?\d+(?:\.\d+)?", body)
    subpaths: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    index = 0
    cx = cy = 0.0
    start = (0.0, 0.0)

    def flush() -> None:
        nonlocal current
        if len(current) >= min_points:
            subpaths.append(current)
        current = []

    while index < len(tokens):
        command = tokens[index]
        if command not in "MLHVZ":
            raise SystemExit(f"unsupported SVG path token {command}")
        index += 1
        if command == "Z":
            if current and current[-1] != start:
                current.append(start)
            flush()
            continue
        if command == "M":
            flush()
            cx = float(tokens[index])
            cy = float(tokens[index + 1])
            index += 2
            start = (cx, cy)
            current = [start]
            while index < len(tokens) and tokens[index] not in "MLHVZ":
                cx = float(tokens[index])
                cy = float(tokens[index + 1])
                index += 2
                current.append((cx, cy))
            continue
        if command == "L":
            while index < len(tokens) and tokens[index] not in "MLHVZ":
                cx = float(tokens[index])
                cy = float(tokens[index + 1])
                index += 2
                current.append((cx, cy))
            continue
        if command == "H":
            while index < len(tokens) and tokens[index] not in "MLHVZ":
                cx = float(tokens[index])
                index += 1
                current.append((cx, cy))
            continue
        while index < len(tokens) and tokens[index] not in "MLHVZ":
            cy = float(tokens[index])
            index += 1
            current.append((cx, cy))
    flush()
    return subpaths


def load_layers(text: str) -> list[tuple[str, list[list[tuple[float, float]]]]]:
    layers = []
    for match in re.finditer(r"<path\b([^>]*)/?>", text):
        attrs = match.group(1)
        fill = re.search(r'fill="(#[0-9A-Fa-f]{6})"', attrs)
        path = re.search(r'\sd="([^"]+)"', attrs)
        if fill is None or path is None:
            raise SystemExit("symbol path is missing fill or d")
        color = fill.group(1).upper()
        if color not in {"#10141C", "#FF3B4D"}:
            raise SystemExit(f"symbol uses a colour outside armour and core: {color}")
        kind = "core" if color == "#FF3B4D" else "armour"
        layers.append((kind, parse_path(path.group(1))))
    if [kind for kind, _subs in layers].count("core") != 1:
        raise SystemExit("symbol must contain one core path")
    return layers


def winding(subpaths: list[list[tuple[float, float]]], x: float, y: float) -> int:
    total = 0
    for poly in subpaths:
        count = len(poly)
        for edge in range(count):
            x0, y0 = poly[edge]
            x1, y1 = poly[(edge + 1) % count]
            if (y0 <= y < y1) or (y1 <= y < y0):
                if y1 == y0:
                    continue
                cross = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
                if x < cross:
                    total += 1 if y0 < y1 else -1
    return total


def covered(subpaths: list[list[tuple[float, float]]], x: float, y: float) -> bool:
    return winding(subpaths, x, y) != 0


def ink_box(layers: list[tuple[str, list[list[tuple[float, float]]]]]) -> tuple[float, float, float, float]:
    xs = [point[0] for _kind, subs in layers for sub in subs for point in sub]
    ys = [point[1] for _kind, subs in layers for sub in subs for point in sub]
    return min(xs), min(ys), max(xs), max(ys)


def raster(layers: list[tuple[str, list]], rows: int, cols: int) -> tuple[tuple[str, str], ...]:
    """Letterbox the ink into ``cols`` by ``rows`` cells. A cell is 1 wide and 2 tall."""
    left, top, right, bottom = ink_box(layers)
    ink_w = right - left
    ink_h = bottom - top
    if ink_w <= 0 or ink_h <= 0:
        raise SystemExit("symbol ink box is empty")
    box_w = float(cols)
    box_h = float(rows * 2)
    scale = min(box_w / ink_w, box_h / ink_h)
    drawn_w = ink_w * scale
    drawn_h = ink_h * scale
    pad_x = (box_w - drawn_w) / 2.0
    pad_y = (box_h - drawn_h) / 2.0
    px_w = cols * 2
    px_h = rows * 2
    x_step = box_w / px_w
    y_step = box_h / px_h

    def paint(px: int, py: int) -> str:
        hits = {"core": 0, "armour": 0}
        for sy in range(SAMPLES):
            for sx in range(SAMPLES):
                sx_box = (px + (sx + 0.5) / SAMPLES) * x_step
                sy_box = (py + (sy + 0.5) / SAMPLES) * y_step
                if (
                    sx_box < pad_x
                    or sy_box < pad_y
                    or sx_box >= pad_x + drawn_w
                    or sy_box >= pad_y + drawn_h
                ):
                    continue
                x = left + (sx_box - pad_x) / scale
                y = top + (sy_box - pad_y) / scale
                kind = ""
                for layer_kind, subpaths in layers:
                    if covered(subpaths, x, y):
                        kind = layer_kind
                if kind:
                    hits[kind] += 1
        if hits["core"] >= COVERAGE and hits["core"] > hits["armour"]:
            return "c"
        if hits["armour"] >= COVERAGE:
            return "a"
        return " "

    pixels = [[paint(px, py) for px in range(px_w)] for py in range(px_h)]
    table = []
    for row in range(rows):
        glyphs = []
        mask = []
        for col in range(cols):
            block = (
                pixels[row * 2][col * 2],
                pixels[row * 2][col * 2 + 1],
                pixels[row * 2 + 1][col * 2],
                pixels[row * 2 + 1][col * 2 + 1],
            )
            votes = {"c": 0, "a": 0}
            for sample in block:
                if sample != " ":
                    votes[sample] += 1
            # One foreground colour per cell: keep only the winning layer's
            # quadrants, so red never spills onto the spine or the gates.
            kind = "c" if votes["c"] and votes["c"] >= votes["a"] else "a"
            bits = 0
            for sample, weight in zip(block, (0x1, 0x2, 0x4, 0x8)):
                if sample == kind:
                    bits |= weight
            glyphs.append(QUADS[bits])
            mask.append("c" if bits and kind == "c" else " ")
        table.append(("".join(glyphs), "".join(mask)))
    if not any("c" in mask for _glyphs, mask in table):
        raise SystemExit(f"core disappeared at {rows}x{cols}")
    return tuple(table)


def assert_samples(layers: list[tuple[str, list]]) -> None:
    """The scan has to keep the aperture, the core, and the empty margin."""
    expect = {
        (400.0, 180.0): "armour",
        (548.0, 486.0): "core",
        (50.0, 50.0): "",
    }
    for (x, y), wanted in expect.items():
        kind = ""
        for layer_kind, subpaths in layers:
            if covered(subpaths, x, y):
                kind = layer_kind
        if kind != wanted:
            raise SystemExit(f"sample {(x, y)} is {kind or 'empty'}, expected {wanted or 'empty'}")


def _group_transform(attrs: str) -> tuple[float, float, float, float]:
    translate = re.search(rf"translate\(\s*({_NUMBER})(?:[\s,]+({_NUMBER}))?\s*\)", attrs)
    scale = re.search(rf"scale\(\s*({_NUMBER})(?:[\s,]+({_NUMBER}))?\s*\)", attrs)
    tx = float(translate.group(1)) if translate else 0.0
    ty = float(translate.group(2) or 0.0) if translate else 0.0
    if scale is None:
        sx = sy = 1.0
    else:
        sx = float(scale.group(1))
        sy = float(scale.group(2) or sx)
    return tx, ty, sx, sy


def _symbol_group_transform(text: str) -> tuple[float, float, float, float]:
    for match in re.finditer(r"<g\b([^>]*)>", text):
        attrs = match.group(1)
        if "wordmark" in attrs or "transform" not in attrs:
            continue
        return _group_transform(attrs)
    raise SystemExit("lockup symbol group has no transform")


def _wordmark_paths(text: str) -> tuple[str, ...]:
    match = re.search(r'<g id="wordmark"[^>]*>(.*?)</g>', text)
    if match is None:
        raise SystemExit("lockup has no wordmark group")
    return tuple(re.findall(r'\sd="([^"]+)"', match.group(1)))


def load_wordmark(text: str) -> tuple[list[list[tuple[float, float]]], float]:
    """Wordmark strokes in lockup space. The background rect is not a path, so it is not ink."""
    match = re.search(r'<g id="wordmark"([^>]*)>(.*?)</g>', text)
    if match is None:
        raise SystemExit("lockup has no wordmark group")
    attrs, body = match.group(1), match.group(2)
    fill = re.search(r'\bfill="([^"]+)"', attrs)
    stroke = re.search(r'\bstroke="(#[0-9A-Fa-f]{6})"', attrs)
    width = re.search(r'\bstroke-width="(\d+(?:\.\d+)?)"', attrs)
    if fill is None or fill.group(1) != "none" or stroke is None or width is None:
        raise SystemExit("wordmark must be an unfilled armour stroke")
    color = stroke.group(1).upper()
    if color not in _ARMOUR_STROKE:
        raise SystemExit(f"wordmark stroke is not armour: {color}")
    tx, ty, _sx, _sy = _group_transform(attrs)
    polys: list[list[tuple[float, float]]] = []
    for path in re.findall(r'\sd="([^"]+)"', body):
        for sub in parse_path(path, min_points=2):
            polys.append([(point[0] + tx, point[1] + ty) for point in sub])
    if not polys:
        raise SystemExit("wordmark has no stroke paths")
    return polys, float(width.group(1))


def _segment_hits(
    start: tuple[float, float],
    end: tuple[float, float],
    half: float,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
) -> bool:
    """Square-capped stroke segment versus one quadrant. A shared edge counts as ink."""
    ax, ay = start
    bx, by = end
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy)
    if length == 0.0:
        return ax + half >= x0 and ax - half <= x1 and ay + half >= y0 and ay - half <= y1
    ux, uy = dx / length, dy / length
    px, py = -uy * half, ux * half
    cax, cay = ax - ux * half, ay - uy * half
    cbx, cby = bx + ux * half, by + uy * half
    corners = (
        (cax + px, cay + py),
        (cax - px, cay - py),
        (cbx - px, cby - py),
        (cbx + px, cby + py),
    )
    rect = ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
    for axis_x, axis_y in ((1.0, 0.0), (0.0, 1.0), (ux, uy), (-uy, ux)):
        projected = [point[0] * axis_x + point[1] * axis_y for point in corners]
        other = [point[0] * axis_x + point[1] * axis_y for point in rect]
        if max(projected) < min(other) or max(other) < min(projected):
            return False
    return True


def _stroke_hits(
    polys: list[list[tuple[float, float]]],
    half: float,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
) -> bool:
    for poly in polys:
        for index in range(len(poly) - 1):
            if _segment_hits(poly[index], poly[index + 1], half, x0, y0, x1, y1):
                return True
    return False


def wordmark_span(
    symbol_layers: list,
    polys: list[list[tuple[float, float]]],
    stroke: float,
    transform: tuple[float, float, float, float],
) -> tuple[int, int]:
    """Symbol rows the lockup wordmark overlaps. Row 0 stays free for the version."""
    _tx, ty, _sx, sy = transform
    if sy == 0:
        raise SystemExit("symbol scale is zero")
    half = stroke / 2.0
    ys = [point[1] for poly in polys for point in poly]
    top = min(ys) - half
    bottom = max(ys) + half
    _left, ink_top, _right, ink_bottom = ink_box(symbol_layers)
    rows = WIDE[0]
    ink_h = ink_bottom - ink_top
    ink_w = _right - _left
    box_h = float(rows * 2)
    scale = min(float(WIDE[1]) / ink_w, box_h / ink_h)
    pad_y = (box_h - ink_h * scale) / 2.0

    def py_of(lock_y: float) -> float:
        user_y = (lock_y - ty) / sy
        return pad_y + (user_y - ink_top) * scale

    row0 = math.floor(py_of(top) / 2.0)
    row1 = math.floor((py_of(bottom) - 1e-9) / 2.0)
    if row1 < row0 or row0 < 0 or row1 >= rows:
        raise SystemExit(f"wordmark rows {row0}-{row1} fall outside the wide mark")
    if row0 == 0:
        raise SystemExit("wordmark occupies row 0, which holds the version")
    return row0, row1 - row0 + 1


def raster_wordmark(
    polys: list[list[tuple[float, float]]],
    stroke: float,
    rows: int,
    cols: int,
) -> tuple[tuple[str, str], ...]:
    """Letterbox the stroked wordmark. A quadrant is armour when the stroke crosses it.

    The symbol's majority rule would drop these strokes: they are thinner than a cell.
    The mask stays blank so the core colour cannot paint the wordmark.
    """
    half = stroke / 2.0
    xs = [point[0] for poly in polys for point in poly]
    ys = [point[1] for poly in polys for point in poly]
    left, top = min(xs) - half, min(ys) - half
    right, bottom = max(xs) + half, max(ys) + half
    ink_w = right - left
    ink_h = bottom - top
    if ink_w <= 0 or ink_h <= 0:
        raise SystemExit("wordmark ink box is empty")
    px_w = cols * 2
    px_h = rows * 2
    table = []
    for row in range(rows):
        glyphs = []
        for col in range(cols):
            bits = 0
            for dy, dx, weight in ((0, 0, 0x1), (0, 1, 0x2), (1, 0, 0x4), (1, 1, 0x8)):
                px = col * 2 + dx
                py = row * 2 + dy
                x0 = left + px / px_w * ink_w
                x1 = left + (px + 1) / px_w * ink_w
                y0 = top + py / px_h * ink_h
                y1 = top + (py + 1) / px_h * ink_h
                if _stroke_hits(polys, half, x0, y0, x1, y1):
                    bits |= weight
            glyphs.append(QUADS[bits])
        text = "".join(glyphs)
        table.append((text, " " * len(text)))
    if not any(glyph != " " for glyphs, _mask in table for glyph in glyphs):
        raise SystemExit("wordmark scan is blank")
    return tuple(table)


def scan_wordmark(
    symbol_layers: list,
    lockup_text: str,
) -> tuple[tuple[tuple[str, str], ...], int]:
    polys, stroke = load_wordmark(lockup_text)
    row, height = wordmark_span(symbol_layers, polys, stroke, _symbol_group_transform(lockup_text))
    half = stroke / 2.0
    xs = [point[0] for poly in polys for point in poly]
    ys = [point[1] for poly in polys for point in poly]
    ink_w = (max(xs) + half) - (min(xs) - half)
    ink_h = (max(ys) + half) - (min(ys) - half)
    cols = max(1, round((ink_w / ink_h) * height * 2))
    return raster_wordmark(polys, stroke, height, cols), row


def render_text(wide: tuple, stack: tuple, wordmark: tuple, wordmark_row: int) -> str:
    lines = [
        START.rstrip("\n"),
        "# Scan of assets/brand/symbol-primary.svg. Regenerate: python3 scripts/ci/render_brand_mark.py",
        "BRAND_MARK_WIDE = (",
    ]
    for glyphs, mask in wide:
        lines.append(f"    ({glyphs!r}, {mask!r}),")
    lines.append(")")
    lines.append("BRAND_MARK_STACK = (")
    for glyphs, mask in stack:
        lines.append(f"    ({glyphs!r}, {mask!r}),")
    lines.append(")")
    lines.append("# Wordmark scan of assets/brand/lockup-light.svg. Strokes are armour, not the core.")
    lines.append("BRAND_WORDMARK_WIDE = (")
    for glyphs, mask in wordmark:
        lines.append(f"    ({glyphs!r}, {mask!r}),")
    lines.append(")")
    lines.append(f"BRAND_WORDMARK_ROW = {wordmark_row}")
    lines.append(END.rstrip("\n"))
    return "\n".join(lines) + "\n"


def splice(source: str, block: str) -> str:
    if START in source and END in source:
        start = source.index(START)
        end = source.index(END)
        if end < start:
            raise SystemExit("brand_mark markers are out of order")
        return source[:start] + block + source[end + len(END) :]
    anchor = "# Cybernetic Red"
    at = source.find(anchor)
    if at < 0:
        raise SystemExit("ce_ui.py has no brand anchor")
    return source[:at] + block + "\n" + source[at:]


def build() -> tuple[str, tuple, tuple]:
    symbol_text = SVG.read_text(encoding="utf-8")
    light = LOCKUP_LIGHT.read_text(encoding="utf-8")
    dark = LOCKUP_DARK.read_text(encoding="utf-8")
    for path in re.findall(r'\sd="([^"]+)"', symbol_text):
        if path not in light or path not in dark:
            raise SystemExit("lockup is missing a symbol path")
    if _wordmark_paths(light) != _wordmark_paths(dark):
        raise SystemExit("lockup wordmark paths differ")
    layers = load_layers(symbol_text)
    assert_samples(layers)
    wide = raster(layers, *WIDE)
    stack = raster(layers, *STACK)
    left, top, right, bottom = ink_box(layers)
    ink = (right - left) / (bottom - top)
    for rows, cols in (WIDE, STACK):
        ratio = cols / (rows * 2)
        if abs(ratio - ink) / ink > 0.10:
            raise SystemExit(
                f"mark {rows}x{cols} aspect {ratio:.3f} is more than 10% from the symbol {ink:.3f}"
            )
    wordmark, wordmark_row = scan_wordmark(layers, light)
    return render_text(wide, stack, wordmark, wordmark_row), wide, stack


def _png(width: int, height: int, rgb: bytes) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + rgb[y * width * 3 : (y + 1) * width * 3] for y in range(height))
    return b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)),
            chunk(b"IDAT", zlib.compress(raw, 9)),
            chunk(b"IEND", b""),
        )
    )


def write_proof(directory: Path, table: tuple, name: str) -> None:
    """Paint the terminal cells. Armour is the theme foreground, not a fixed RGB."""
    rows = len(table)
    cols = len(table[0][0])
    scale = 12
    cell_w = scale
    cell_h = scale * 2
    width = cols * cell_w
    height = rows * cell_h
    themes = {
        "dark": ((18, 20, 26), (230, 232, 238), (255, 59, 77)),
        "light": ((247, 244, 239), (16, 20, 28), (255, 59, 77)),
    }
    directory.mkdir(parents=True, exist_ok=True)
    for theme, (background, armour, core) in themes.items():
        buffer = bytearray(bytes(background) * (width * height))
        for row, (glyphs, mask) in enumerate(table):
            for col, glyph in enumerate(glyphs):
                bits = next(key for key, value in QUADS.items() if value == glyph)
                color = core if mask[col] == "c" else armour
                for bit, (dx, dy) in ((0x1, (0, 0)), (0x2, (1, 0)), (0x4, (0, 1)), (0x8, (1, 1))):
                    if not bits & bit:
                        continue
                    x0 = col * cell_w + dx * (cell_w // 2)
                    y0 = row * cell_h + dy * (cell_h // 2)
                    for y in range(y0, y0 + cell_h // 2):
                        start = (y * width + x0) * 3
                        buffer[start : start + (cell_w // 2) * 3] = bytes(color) * (cell_w // 2)
        path = directory / f"{name}-{theme}.png"
        path.write_bytes(_png(width, height, bytes(buffer)))
        print(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--proof", type=Path)
    args = parser.parse_args(argv)
    block, wide, stack = build()
    if args.proof:
        write_proof(args.proof, wide, "brand-wide")
        write_proof(args.proof, stack, "brand-stack")
    original = TARGET.read_text(encoding="utf-8")
    updated = splice(original, block)
    if args.check:
        if updated != original:
            print("brand mark drift: run python3 scripts/ci/render_brand_mark.py", file=sys.stderr)
            return 1
        return 0
    if updated == original:
        print("unchanged")
        return 0
    TARGET.write_text(updated, encoding="utf-8")
    print("updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
