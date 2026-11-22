"""Test-design gates, traceability, generated rules, and stale paths (#71)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "runtime"))

import conformance  # noqa: E402
import hosts  # noqa: E402
import sdlc_flows  # noqa: E402

TECHNIQUES = (
    "Equivalence partitioning",
    "Boundary value analysis",
    "Decision table",
    "State transition",
    "Pairwise",
    "Metamorphic",
    "Scenario",
    "Error guessing",
)


def test_test_design_card_names_each_technique():
    text = (ROOT / "references" / "test-design.md").read_text(encoding="utf-8")
    for name in TECHNIQUES:
        assert name in text
    assert len(text.splitlines()) < 80
    for relative in (
        "references/test-docs/test-plan.md",
        "references/test-docs/completion-report.md",
        "references/test-docs/incident-report.md",
    ):
        body = (ROOT / relative).read_text(encoding="utf-8")
        assert body.strip()
    plan = (ROOT / "references" / "test-docs" / "test-plan.md").read_text(encoding="utf-8")
    assert "Likelihood" in plan
    assert "Impact" in plan
    assert "25010" in plan
    assert "25059" in plan
    assert "shall" not in plan.casefold()


def test_missing_negative_check_fails_an_input_without_an_invalid_or_boundary():
    criteria = [{"id": "FR-1", "text": "The amount is accepted", "input_bearing": True}]
    only_valid = [{"criterion_id": "FR-1", "technique": "equivalence", "partition": "valid"}]
    refused = sdlc_flows.negative_check_gate(criteria, only_valid)
    assert refused["ok"] is False
    assert refused["reasons"] == ["missing-negative-check"]
    invalid = [{"criterion_id": "FR-1", "technique": "equivalence", "partition": "invalid"}]
    assert sdlc_flows.negative_check_gate(criteria, invalid)["ok"] is True
    boundary = [{"criterion_id": "FR-1", "technique": "bva", "boundary": "max+1", "partition": "boundary"}]
    assert sdlc_flows.negative_check_gate(criteria, boundary)["ok"] is True
    plain = [{"id": "FR-2", "text": "The page has a title"}]
    assert sdlc_flows.negative_check_gate(plain, [])["ok"] is True


def test_missing_reference_when_a_cited_symbol_is_absent(tmp_path: Path):
    (tmp_path / "LoginPage.java").write_text("class LoginPage {}\n", encoding="utf-8")
    found = sdlc_flows.missing_reference(["LoginPage"], tmp_path)
    assert found["ok"] is True
    missing = sdlc_flows.missing_reference(["MissingCheckoutPage"], tmp_path)
    assert missing["ok"] is False
    assert missing["reasons"] == ["missing-reference"]
    assert "MissingCheckoutPage" in missing["missing"]


def test_traceability_matrix_and_high_impact_risk():
    matrix = sdlc_flows.traceability_matrix(
        [{"id": "FR-1"}],
        [{"id": "check-1", "criterion_id": "FR-1", "result": "passed"}],
    )
    assert "| FR-1 | check-1 | passed |" in matrix
    risk = sdlc_flows.risk_register_gate([{"id": "R1", "likelihood": 2, "impact": 5, "test": ""}])
    assert risk["ok"] is False
    assert "owner-decision-high-impact-untested" in risk["reasons"]
    covered = sdlc_flows.risk_register_gate([{"id": "R1", "likelihood": 2, "impact": 5, "test": "check-1"}])
    assert covered["ok"] is True


def test_agents_block_sections_stay_short_and_keep_owner_text(tmp_path: Path):
    block = hosts.agents_md_block(project=ROOT)
    assert len(block.splitlines()) <= 60
    for heading in ("## Commands", "## Testing", "## Boundaries", "## More"):
        assert heading in block
    assert "Before every task, follow the canonical" in block
    merged = hosts.merge_instruction(b"Owner rule stays.\n", block, relative="AGENTS.md").decode()
    assert "Owner rule stays." in merged
    assert merged.index(hosts.END) < merged.index("Owner rule stays.")
    copilot = hosts.copilot_instruction_block()
    project = tmp_path
    (project / "AGENTS.md").write_text(block, encoding="utf-8")
    (project / ".github").mkdir()
    (project / ".github" / "copilot-instructions.md").write_text(copilot, encoding="utf-8")
    assert hosts.competing_policy_errors(project) == []
    hosts.consume_merge_handoffs()
    before = {key: None for key in hosts.managed_paths()}
    after = hosts.desired_content(before, maven_runtime=None, project=tmp_path)
    for relative in hosts.TESTING_RULE_PATHS:
        text = after[relative].decode()
        assert "invalid partition" in text
    assert 'applyTo:' in after[".github/instructions/testing.instructions.md"].decode()
    assert "paths:" in after[".claude/rules/testing.md"].decode()
    assert "globs:" in after[".cursor/rules/testing.mdc"].decode()
    owned = hosts.testing_rule_bytes(
        ".claude/rules/testing.md",
        b"# Owner testing note\n",
    )
    assert owned == b"# Owner testing note\n"
    hosts.consume_merge_handoffs()


def test_stale_generated_path_names_a_missing_file(tmp_path: Path):
    generated = tmp_path / "AGENTS.md"
    generated.write_text(
        "Test: `python3 -m pytest -q tests/present.py`\n"
        "Also `tests/missing.py`\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "present.py").write_text("x = 1\n", encoding="utf-8")
    errors = conformance.check_stale_generated_paths(tmp_path, ["AGENTS.md"])
    assert errors == ["stale-path: tests/missing.py"]
    assert conformance.check_stale_generated_paths(tmp_path, ["nope.md"]) == ["stale-path: nope.md missing"]
