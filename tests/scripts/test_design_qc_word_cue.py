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


def _review_line(**overrides: object) -> dict:
    line = {
        "text": "Fluent waits.",
        "words": [
            {"text": "Fluent", "start": 0.0, "end": 0.4},
            {"text": "waits", "start": 0.4, "end": 0.8},
        ],
        "word": "Fluent",
        "cue_at": 0.0,
        "cues": ["Fluent"],
        "picture": "queue holds one job",
        "take": "vo/01-fluent.wav",
    }
    line.update(overrides)
    return line


def _aspect(**overrides: object) -> dict:
    block = {"laid_out": True, "cropped": False, "overflow": False, "overlap": False}
    block.update(overrides)
    return block


def _good_review(**overrides: object) -> dict:
    payload = {
        "fps": 30,
        "lines": [_review_line()],
        "formats": {"16:9": _aspect(), "9:16": _aspect()},
        "hero": {
            "16:9": {"x": 0.3, "y": 0.2, "w": 0.4, "h": 0.4},
            "9:16": {"x": 0.2, "y": 0.15, "w": 0.6, "h": 0.5},
        },
        "score_payoff": {"start": 8.0, "end": 10.0, "score_db": -28.0, "vo_db": -16.0},
    }
    payload.update(overrides)
    return payload


def _sync(fps: float, cue_at: float, start: float = 1.0) -> dict:
    return {
        "fps": fps,
        "lines": [
            _review_line(
                word="Fluent",
                cue_at=cue_at,
                words=[{"text": "Fluent", "start": start, "end": start + 0.4}],
            )
        ],
    }


def test_cue_sync_tolerance_is_three_frames_or_150ms() -> None:
    assert design_qc.cue_sync_reasons(_sync(60, 1.150)) == []
    assert design_qc.cue_sync_reasons(_sync(60, 1.151)) == ["cue-sync"]
    assert design_qc.cue_sync_reasons(_sync(10, 1.3)) == []
    assert design_qc.cue_sync_reasons(_sync(10, 1.301)) == ["cue-sync"]
    assert design_qc.cue_sync_reasons(_sync(30, 1.12)) == []
    missing = _good_review()
    del missing["fps"]
    assert design_qc.cue_sync_reasons(missing) == ["missing-cue-sync"]
    no_cue = _good_review()
    del no_cue["lines"][0]["cue_at"]
    assert design_qc.cue_sync_reasons(no_cue) == ["missing-cue-sync"]


def test_retake_retimes_only_the_replaced_line() -> None:
    other = _review_line(word="Sleep", cues=["Sleep"], take="vo/02-sleep.wav", cue_at=1.0,
                         words=[{"text": "Sleep", "start": 1.0, "end": 1.4}])
    before = [_review_line(), other]
    moved = _review_line(
        cue_at=0.5,
        words=[
            {"text": "Fluent", "start": 0.5, "end": 0.9},
            {"text": "waits", "start": 0.9, "end": 1.3},
        ],
    )
    assert design_qc.retake_reasons(before, [moved, other], 0, 30) == []
    stale = _review_line(
        cue_at=0.0,
        words=[
            {"text": "Fluent", "start": 0.5, "end": 0.9},
            {"text": "waits", "start": 0.9, "end": 1.3},
        ],
    )
    assert design_qc.retake_reasons(before, [stale, other], 0, 30) == ["retake-stale-cue"]
    assert design_qc.retake_reasons(before, before, 0, 30) == ["retake-unchanged"]
    drifted = dict(other)
    drifted["take"] = "vo/02-sleep-again.wav"
    assert "retake-other-moved" in design_qc.retake_reasons(before, [moved, drifted], 0, 30)
    payload = _good_review(lines=[stale, other], fps=30)
    payload["retake"] = {"index": 0, "before": before}
    assert "retake-stale-cue" in design_qc.word_review_reasons(payload)["reasons"]


def test_orphaned_cue_fails() -> None:
    assert design_qc.orphaned_cue_reasons(_good_review()) == []
    renamed = _good_review()
    renamed["lines"][0]["cues"] = ["Sleep"]
    assert design_qc.orphaned_cue_reasons(renamed) == ["orphaned-cue"]
    gone = _good_review()
    del gone["lines"][0]["cues"]
    assert design_qc.orphaned_cue_reasons(gone) == ["orphaned-cue"]


def test_narration_pace_cap_and_wpm_report() -> None:
    ok = design_qc.narration_pace_report(_good_review())
    assert ok["reasons"] == []
    assert ok["wps"] == [2.5]
    assert ok["wpm"] == [150.0]
    assert ok["wpm_band"] == [140, 160]
    assert ok["wps_max"] == 3.5

    def paced(count: int, end: float) -> dict:
        words = []
        for index in range(count):
            start = 0.0 if index == 0 else index * (end / count)
            stop = end if index == count - 1 else start + (end / count) * 0.5
            words.append({"text": f"w{index}", "start": start, "end": stop})
        return _good_review(lines=[_review_line(words=words, word="w0", cues=["w0"], cue_at=0.0)])

    cap = design_qc.narration_pace_report(paced(7, 2.0))
    assert "pace-fast" not in cap["reasons"]
    assert "pace-band" in cap["reasons"]
    assert cap["wps"] == [3.5]
    assert cap["wpm"] == [210.0]
    fast = design_qc.narration_pace_report(paced(7, 1.9))
    assert "pace-fast" in fast["reasons"]
    assert "pace-band" in fast["reasons"]
    slow = design_qc.narration_pace_report(paced(2, 1.0))
    assert slow["reasons"] == ["pace-band"]
    assert slow["wpm"] == [120.0]
    assert design_qc.narration_pace_report({"lines": []})["reasons"] == ["missing-pace"]


def test_format_overflow_requires_both_layouts() -> None:
    assert design_qc.format_layout_reasons(_good_review()) == []
    wide = _good_review()
    wide["formats"]["16:9"]["overflow"] = True
    assert design_qc.format_layout_reasons(wide) == ["overflow-16:9"]
    tall = _good_review()
    tall["formats"]["9:16"]["overlap"] = True
    assert design_qc.format_layout_reasons(tall) == ["overflow-9:16"]
    crop = _good_review()
    crop["formats"]["16:9"]["cropped"] = True
    assert "cropped-16:9" in design_qc.format_layout_reasons(crop)
    relaid = _good_review()
    relaid["formats"]["9:16"]["laid_out"] = False
    assert "cropped-9:16" in design_qc.format_layout_reasons(relaid)
    missing = _good_review()
    del missing["formats"]["9:16"]
    assert design_qc.format_layout_reasons(missing) == ["missing-format-9:16"]


def test_hero_anchor_inside_both_frames() -> None:
    assert design_qc.hero_anchor_reasons(_good_review()) == []
    off = _good_review()
    off["hero"]["9:16"] = {"x": 0.8, "y": 0.2, "w": 0.3, "h": 0.2}
    assert design_qc.hero_anchor_reasons(off) == ["hero-anchor"]
    gone = _good_review()
    del gone["hero"]
    assert design_qc.hero_anchor_reasons(gone) == ["missing-hero"]
    waived = _good_review(hero=None, hero_waiver="no hero in this piece")
    assert design_qc.hero_anchor_reasons(waived) == []


def test_score_stem_payoff_window() -> None:
    ok = design_qc.score_payoff_report(_good_review())
    assert ok["reasons"] == []
    assert ok["score_db"] == -28.0
    assert ok["vo_db"] == -16.0
    quiet = _good_review()
    quiet["score_payoff"]["vo_db"] = -30.0
    assert design_qc.score_payoff_report(quiet)["reasons"] == ["score-payoff"]
    point = _good_review()
    point["score_payoff"]["end"] = 8.0
    assert design_qc.score_payoff_report(point)["reasons"] == ["score-payoff"]
    gone = _good_review()
    del gone["score_payoff"]
    assert design_qc.score_payoff_report(gone)["reasons"] == ["score-payoff"]
    waived = _good_review(score_payoff=None, score_waiver="no score stem")
    assert design_qc.score_payoff_report(waived)["reasons"] == []


def test_wordreview_logs_wpm_and_fails_closed(tmp_path: Path, capsys) -> None:
    path = tmp_path / "timings.json"
    path.write_text(json.dumps(_good_review()), encoding="utf-8")
    code = design_qc.main(["wordreview", str(path)])
    out = capsys.readouterr().out
    assert code == 0
    assert '"status": "pass"' in out
    assert '"wpm": [150.0]' in out
    assert '"wpm_band": [140, 160]' in out
    assert '"wps_max": 3.5' in out
    empty = tmp_path / "empty.json"
    empty.write_text("  \n", encoding="utf-8")
    assert design_qc.main(["wordreview", str(empty)]) != 0
    assert "empty-file" in capsys.readouterr().out
    bare = tmp_path / "bare.json"
    bare.write_text("{}", encoding="utf-8")
    assert design_qc.main(["wordreview", str(bare)]) != 0
    failed = capsys.readouterr().out
    for reason in ("missing-pace", "missing-cue-sync", "orphaned-cue", "missing-format", "missing-hero", "score-payoff"):
        assert reason in failed
