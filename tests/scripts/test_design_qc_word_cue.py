"""Word-cue gate: missing evidence fails closed. No ASR model is run."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "design_qc_wordcue", ROOT / "addons/design-skills/scripts/design_qc.py"
)
design_qc = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = design_qc
assert _SPEC.loader is not None
_SPEC.loader.exec_module(design_qc)


def _line(**overrides: object) -> dict:
    line = {
        "text": "Fluent waits.",
        "words": [
            {"text": "Fluent", "start": 0.0, "end": 0.42},
            {"text": "waits", "start": 0.42, "end": 0.9},
        ],
        "picture": "queue holds one job",
        "take": "vo/01-fluent.wav",
        "word": "Fluent",
        "overflow": False,
    }
    line.update(overrides)
    return line


def _data(*lines: dict, draft: bool = False) -> dict:
    payload: dict = {"lines": list(lines) or [_line()]}
    if draft:
        payload["draft"] = True
    return payload


def _reasons(data: dict, whisper: Path | None) -> list[str]:
    return design_qc.word_cue_reasons(data, whisper)


def test_addon_whisper_binary_is_absent() -> None:
    assert design_qc.addon_whisper_bin() is None


def test_overflow_text_fails(tmp_path: Path) -> None:
    whisper = tmp_path / "whisper-cli"
    whisper.write_bytes(b"")
    missing = _data(_line())
    del missing["lines"][0]["overflow"]
    assert _reasons(missing, whisper) == ["overflow-text"]
    assert _reasons(_data(_line(overflow=True)), whisper) == ["overflow-text"]
    assert _reasons(_data(_line(overflow="title clipped")), whisper) == ["overflow-text"]


def test_missing_take_fails(tmp_path: Path) -> None:
    whisper = tmp_path / "whisper-cli"
    whisper.write_bytes(b"")
    gone = _data(_line())
    del gone["lines"][0]["take"]
    assert _reasons(gone, whisper) == ["missing-take"]
    assert _reasons(_data(_line(take="  ")), whisper) == ["missing-take"]


def test_scratch_take_fails_when_shipped(tmp_path: Path) -> None:
    whisper = tmp_path / "whisper-cli"
    whisper.write_bytes(b"")
    scratch = _data(_line(take="vo/line.scratch.wav"))
    assert _reasons(scratch, whisper) == ["scratch-take"]
    assert _reasons(_data(_line(take="vo/scratch.wav")), whisper) == []


def test_cue_without_word_fails(tmp_path: Path) -> None:
    whisper = tmp_path / "whisper-cli"
    whisper.write_bytes(b"")
    unnamed = _data(_line())
    del unnamed["lines"][0]["word"]
    assert _reasons(unnamed, whisper) == ["cue-without-word"]
    assert _reasons(_data(_line(word="")), whisper) == ["cue-without-word"]
    assert _reasons(_data(_line(word="Sleep")), whisper) == ["cue-without-word"]


def test_shipped_missing_whisper_fails(tmp_path: Path, capsys) -> None:
    path = tmp_path / "timings.json"
    path.write_text(json.dumps(_data()), encoding="utf-8")
    code = design_qc.main(["wordcue", str(path)])
    out = capsys.readouterr().out
    assert code != 0
    assert "missing-whisper" in out


def test_draft_allows_missing_whisper_and_scratch_take(tmp_path: Path, capsys) -> None:
    path = tmp_path / "timings.json"
    path.write_text(
        json.dumps(_data(_line(take="vo/line.scratch.wav"), draft=True)),
        encoding="utf-8",
    )
    code = design_qc.main(["wordcue", str(path)])
    out = capsys.readouterr().out
    assert code == 0
    assert '"status": "pass"' in out


def test_shipped_fake_timing_passes_without_running_whisper(tmp_path: Path) -> None:
    marker = tmp_path / "whisper-ran"
    whisper = tmp_path / "whisper-cli"
    whisper.write_text(f"#!/bin/sh\ntouch {marker}\n", encoding="utf-8")
    whisper.chmod(0o755)
    assert _reasons(_data(), whisper) == []
    assert not marker.exists()
