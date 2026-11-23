"""The D24 card's documented timings example passes the three word gates (#50)."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CARD = ROOT / "addons" / "design-skills" / "references" / "word-timed-explainer.md"
SPEC = importlib.util.spec_from_file_location(
    "design_qc_d24", ROOT / "addons" / "design-skills" / "scripts" / "design_qc.py"
)
design_qc = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = design_qc
SPEC.loader.exec_module(design_qc)


def _example(tmp_path: Path) -> Path:
    blocks = re.findall(r"^ *```json\n(.*?)^ *```", CARD.read_text(encoding="utf-8"), re.S | re.M)
    assert len(blocks) == 1, "D24 documents exactly one timings example"
    data = json.loads(blocks[0])
    path = tmp_path / "timings.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_card_example_passes_every_word_gate(tmp_path: Path) -> None:
    path = _example(tmp_path)
    for gate in ("wordtiming", "wordcue", "wordreview"):
        assert design_qc.main([gate, str(path)]) == 0, gate


def test_waiver_without_explicit_null_fails_closed(tmp_path: Path) -> None:
    path = _example(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["hero"]
    path.write_text(json.dumps(data), encoding="utf-8")
    assert design_qc.main(["wordreview", str(path)]) != 0
