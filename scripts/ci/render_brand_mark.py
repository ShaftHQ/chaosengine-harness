#!/usr/bin/env python3
"""Scan-convert the Quantum Mandate symbol into the installer mark table.

The runtime paints this table. It does not parse SVG. CI fails when the
checked-in table drifts from this script.
"""

from __future__ import annotations

import argparse
import re
import struct
import sys
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SVG = ROOT / "assets" / "brand" / "symbol-primary.svg"
TARGET = ROOT / "runtime" / "ce_ui.py"
START = "# >>> generated: brand_mark\n"
END = "# <<< generated: brand_mark\n"
WIDE = (4, 16)
STACK = (3, 12)
SAMPLES = 3

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


def parse_path(body: str) -> list[list[tuple[float, float]]]:
    tokens = re.findall(r"[MLHVZ]|-?\d+(?:\.\d+)?", body)
    subpaths: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    index = 0
    cx = cy = 0.0
    start = (0.0, 0.0)
    while index < len(tokens):
        command = tokens[index]
        if command not in "MLHVZ":
            raise SystemExit(f"unsupported SVG path token {command}")
        index += 1
        if command == "Z":
            if current and current[-1] != start:
                current.append(start)
            if len(current) >= 3:
                subpaths.append(current)
            current = []
            continue
        if command == "M":
            if len(current) >= 3:
                subpaths.append(current)
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
    if len(current) >= 3:
        subpaths.append(current)
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


def _subpixel(
    layers: list[tuple[str, list[list[tuple[float, float]]]]],
    left: float,
    top: float,
    width: float,
    height: float,
    px: int,
    py: int,
    px_w: int,
    px_h: int,
) -> str:
    hits = {"core": 0, "armour": 0}
    for sy in range(SAMPLES):
        for sx in range(SAMPLES):
            x = left + (px + (sx + 0.5) / SAMPLES) * width / px_w
            y = top + (py + (sy + 0.5) / SAMPLES) * height / px_h
            kind = ""
            for layer_kind, subpaths in layers:
                if covered(subpaths, x, y):
                    kind = layer_kind
            if kind:
                hits[kind] += 1
    if hits["core"] > hits["armour"]:
        return "c"
    if hits["armour"]:
        return "a"
    if hits["core"]:
        return "c"
    return " "


def raster(layers: list[tuple[str, list]], rows: int, cols: int) -> tuple[tuple[str, str], ...]:
    """Return ``(glyphs, core mask)`` rows. Mask ``c`` is the red core."""
    left, top, right, bottom = ink_box(layers)
    width = right - left
    height = bottom - top
    px_w = cols * 2
    px_h = rows * 2
    pixels = [
        [_subpixel(layers, left, top, width, height, px, py, px_w, px_h) for px in range(px_w)]
        for py in range(px_h)
    ]
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
            bits = 0
            votes = {"c": 0, "a": 0}
            for sample, weight in zip(block, (0x1, 0x2, 0x4, 0x8)):
                if sample == " ":
                    continue
                bits |= weight
                votes[sample] += 1
            glyphs.append(QUADS[bits])
            if bits == 0:
                mask.append(" ")
            elif votes["c"] >= votes["a"] and votes["c"]:
                mask.append("c")
            else:
                mask.append(" ")
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


def render_text(wide: tuple, stack: tuple) -> str:
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
    layers = load_layers(SVG.read_text(encoding="utf-8"))
    assert_samples(layers)
    wide = raster(layers, *WIDE)
    stack = raster(layers, *STACK)
    return render_text(wide, stack), wide, stack


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
