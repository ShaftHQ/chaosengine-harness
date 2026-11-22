# Installer visual bugs (2026-11-22)

Evidence for the installer visual-bug spec (see the linked issue). Branch-only until the issue's finalization step moves this folder to `main`.

| File | What it is |
| --- | --- |
| `rog-installer-screenshot.jpg` | Owner's run on Linux Mint (GNOME Terminal/VTE, about 102 columns), `main@db38269`, VERSION 0.4.20261115.5 |
| `logo-aspect-comparison.png` | `assets/brand/symbol-primary.svg` next to the shipped 4x16 and 3x12 tables and aspect-correct 8x13 and 5x8 rasters, drawn with 10x21 px cells |
| `repro/sim.py` | Drives `bootstrap.InstallReporter` in the real call order (`_run_core_install`) into a [pyte](https://pypi.org/project/pyte/) screen. `real` adds the two `print(..., file=sys.stderr)` lines from `bootstrap.py` L5904-5910; `clean` leaves them out |
| `repro/screen-*-real.txt`, `repro/screen-102x30-clean.txt` | Emulated final screens at 102x30, 80x24 and 120x30 |
| `repro/replay.py`, `repro/e2e-screen-102x30.txt` | A real end-to-end one-liner run in a 102x30 pty on Linux, replayed through pyte: the last `Verify installation running` frame and the final screen |

Run: `CE_REPO=<checkout> python sim.py 102 30 real` (needs `pip install pyte`).
