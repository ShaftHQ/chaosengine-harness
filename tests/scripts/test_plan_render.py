"""Golden renders and inert plan text."""

from __future__ import annotations

import html.parser
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "runtime"))

import plan_model  # noqa: E402
import plan_render  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "plan"


def _golden_plan() -> dict:
    return plan_model.normalize(json.loads((FIXTURE / "all-status.plan.json").read_text(encoding="utf-8")))


def test_golden_formats_match_bytes():
    plan = _golden_plan()
    caps = plan_render.fixed_caps(unicode=True, width=80, tty=True)
    assert plan_render.render_term(plan, caps) == (FIXTURE / "all-status.term").read_text(encoding="utf-8")
    assert plan_render.render_md(plan) == (FIXTURE / "all-status.md").read_text(encoding="utf-8")
    assert plan_render.render_mermaid(plan) == (FIXTURE / "all-status.mermaid").read_text(encoding="utf-8")
    assert plan_render.render_html(plan) == (FIXTURE / "all-status.html").read_text(encoding="utf-8")
    assert plan_render.render_walkthrough_md(plan, FIXTURE) == (FIXTURE / "all-status.walkthrough.md").read_text(encoding="utf-8")


def test_seven_step_header_and_ascii():
    steps = [
        plan_model.blank_step("s1", "One", "done"),
        plan_model.blank_step("s2", "Two", "done"),
        plan_model.blank_step("s3", "Three", "done"),
        plan_model.blank_step("s4", "Four", "in_progress"),
        plan_model.blank_step("s5", "Five", "pending"),
        plan_model.blank_step("s6", "Six", "failed"),
        plan_model.blank_step("s7", "Seven", "skipped"),
    ]
    steps[3]["activeText"] = "Running tests"
    plan = plan_model.fresh_plan("seven", steps, explanation="Seven", now=0)
    text = plan_render.render_term(plan, plan_render.fixed_caps(unicode=True, width=80, tty=True))
    assert "Plan: Seven  3/7 done" in text
    assert "◉ Running tests" in text
    ascii_text = plan_render.render_term(plan, plan_render.fixed_caps(unicode=False, width=80, tty=False))
    assert "[x]" in ascii_text
    assert "[>]" in ascii_text
    assert "✓" not in ascii_text
    assert "\x1b" not in ascii_text


def test_term_truncates_to_width():
    plan = plan_model.fresh_plan("wide", [plan_model.blank_step("s1", "x" * 80)], explanation="Title", now=0)
    text = plan_render.render_term(plan, plan_render.fixed_caps(unicode=True, width=20, tty=True))
    assert all(len(line) <= 20 for line in text.splitlines())
    assert text.splitlines()[1].endswith("…")


def test_script_title_is_inert_in_html_and_mermaid():
    step = plan_model.blank_step("s1", 'before <script>alert(1)</script> "]')
    plan = plan_model.fresh_plan("inject", [step], explanation="Inject", now=0)
    page = plan_render.render_html(plan)
    chart = plan_render.render_mermaid(plan)
    assert "<script" not in page.casefold()
    assert "&lt;script&gt;" in page
    assert "<script" not in chart.casefold()
    assert "#quot;#rbrack;" in chart
    assert "#lt;script#gt;" in chart


def test_html_has_no_http_src():
    plan = _golden_plan()
    page = plan_render.render_html(plan)

    class SrcParser(html.parser.HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.srcs: list[str] = []

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            for key, value in attrs:
                if key == "src":
                    self.srcs.append(value or "")

    parser = SrcParser()
    parser.feed(page)
    assert parser.srcs
    assert all(not src.startswith(("http://", "https://")) for src in parser.srcs)


def test_mermaid_uses_depends_on_edges():
    steps = [plan_model.blank_step("s1", "One"), plan_model.blank_step("s2", "Two"), plan_model.blank_step("s3", "Three")]
    steps[1]["dependsOn"] = ["s1"]
    plan = plan_model.fresh_plan("edges", steps, now=0)
    chart = plan_render.render_mermaid(plan)
    assert "s1 --> s2" in chart
    assert "s2 --> s3" not in chart


def test_changed_and_missing_evidence(tmp_path):
    log = tmp_path / "log.txt"
    log.write_text("ok\nexit: 0\n", encoding="utf-8")
    step = plan_model.blank_step("s1", "Check", "done")
    step["evidence"] = [plan_model.build_evidence(f"test:{log.name}", tmp_path)]
    plan = plan_model.fresh_plan("ev", [step], goal="Check", now=0)
    assert "exit 0" in plan_render.render_walkthrough_md(plan, tmp_path)
    log.write_text("changed\nexit: 1\n", encoding="utf-8")
    assert "changed (sha mismatch)" in plan_render.render_walkthrough_md(plan, tmp_path)
    log.unlink()
    assert "missing" in plan_render.render_walkthrough_md(plan, tmp_path)
