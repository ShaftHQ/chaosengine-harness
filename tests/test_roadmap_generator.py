"""Offline checks for the ROADMAP.md generator (ShaftHQ/SHAFT_ENGINE#8061 R6)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("roadmap", ROOT / ".github" / "scripts" / "roadmap.py")
roadmap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(roadmap)


def _node(number, title, state="OPEN"):
    return {
        "number": number,
        "title": title,
        "url": f"https://github.com/o/r/issues/{number}",
        "state": state,
        "repository": {"nameWithOwner": "o/r"},
    }


EPIC = {
    "number": 1,
    "title": "Epic",
    "url": "https://github.com/o/r/issues/1",
    "state": "OPEN",
    "subIssues": {"nodes": [_node(3, "Third first"), _node(2, "Done one", "CLOSED"), _node(4, "Pipe | title")]},
}


def test_render_keeps_epic_order_and_splits_done():
    text = roadmap.render(EPIC, "2026-01-01")
    assert text.index("#3]") < text.index("#4]")
    assert "| 1 | [o/r#3]" in text and "| 2 | [o/r#4]" in text
    done = text.split("## Done", 1)[1]
    assert "o/r#2" in done and "o/r#3" not in done
    assert "Pipe \\| title" in text
    assert "Generated on 2026-01-01" in text


def test_check_ignores_date_and_flags_drift(tmp_path):
    data = tmp_path / "epic.json"
    data.write_text(json.dumps(EPIC), encoding="utf-8")
    out = tmp_path / "ROADMAP.md"
    out.write_text(roadmap.render(EPIC, "2000-01-01"), encoding="utf-8")
    assert roadmap.main(["--check", "--from-json", str(data), "--output", str(out)]) == 0

    changed = dict(EPIC, subIssues={"nodes": EPIC["subIssues"]["nodes"] + [_node(5, "New child")]})
    data.write_text(json.dumps(changed), encoding="utf-8")
    assert roadmap.main(["--check", "--from-json", str(data), "--output", str(out)]) == 1
    assert roadmap.main(["--from-json", str(data), "--output", str(out)]) == 0
    assert "o/r#5" in out.read_text(encoding="utf-8")


def test_committed_roadmap_is_a_generated_view():
    text = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
    assert text.startswith("# Roadmap\n")
    assert roadmap.GENERATED_PREFIX in text
    assert "Edit the epic, not this file." in text
