"""Mechanical test-engineering gates and the on-demand skill (#218)."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "runtime"))

import sdlc_flows  # noqa: E402

SKILL = ROOT / "skills" / "test-engineering"
REFERENCES = SKILL / "references"
TODAY = date(2026, 11, 24)
BANNED = ("ShaftHQ", "SHAFT_ENGINE")


def _frontmatter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    assert lines[0] == "---"
    found: dict[str, str] = {}
    for line in lines[1:]:
        if line == "---":
            break
        key, value = line.split(":", 1)
        found[key.strip()] = value.strip()
    return found


def _scope(marks: str = "in", *, extra: dict | None = None) -> dict:
    scope = {name: marks for name in sdlc_flows.ISO_25010}
    if extra:
        scope.update(extra)
    return scope


def _sarif(results, version="2.1.0"):
    return {"version": version, "runs": [{"results": results}]}


def _finding(uri, level="error", rule="R1", message="boom"):
    row = {
        "ruleId": rule,
        "message": {"text": message},
        "locations": [
            {"physicalLocation": {"artifactLocation": {"uri": uri}}},
        ],
    }
    if level is not None:
        row["level"] = level
    return row


def _diff(body: str) -> str:
    return (
        "diff --git a/tests/test_pay.py b/tests/test_pay.py\n"
        "--- a/tests/test_pay.py\n"
        "+++ b/tests/test_pay.py\n"
        "@@ -0,0 +1,4 @@\n"
        + body
    )


def _quarantine(**overrides):
    record = {
        "owner": "qa",
        "ticket": "T-1",
        "cause": "timing-async",
        "expires": TODAY.isoformat(),
    }
    record.update(overrides)
    return record


def test_skill_contract_size_description_and_banned_tokens():
    skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert len(skill.encode("utf-8")) <= 2100
    front = _frontmatter(skill)
    assert front["name"] == "test-engineering"
    assert front["license"] == "MIT"
    assert 90 <= len(front["description"]) <= 145
    assert "permissions:" not in skill
    for relative in (
        "references/test-analysis-design.md",
        "references/test-evidence-static.md",
        "references/test-report-flake.md",
        "../../references/test-design.md",
        "../../references/tdd.md",
        "../../references/tdd-failure-modes.md",
        "../../references/static-analysis-gate.md",
        "../../references/complexity-gate.md",
        "../../profiles/ai-sut/README.md",
        "../../runtime/sdlc_flows.py",
    ):
        assert (SKILL / relative).is_file()
    sizes = {
        "test-analysis-design.md": 4608,
        "test-evidence-static.md": 4096,
        "test-report-flake.md": int(3.8 * 1024),
    }
    blobs = [skill]
    for name, limit in sizes.items():
        body = (REFERENCES / name).read_text(encoding="utf-8")
        blobs.append(body)
        assert len(body.encode("utf-8")) <= limit, name
    joined = "\n".join(blobs)
    for token in BANNED:
        assert token not in joined


def test_analysis_reference_keeps_the_design_rules():
    text = (REFERENCES / "test-analysis-design.md").read_text(encoding="utf-8")
    for phrase in (
        "input_bearing",
        "controllability",
        "observability",
        "determinism",
        "min-1",
        "min+1",
        "max-1",
        "max+1",
        "0-switch",
        "1-switch",
        "allpairspy",
        "PICT",
        "Hypothesis",
        "jqwik",
        "fast-check",
        "proptest",
        "rapid",
        "FsCheck",
        "shrunk",
        "specified",
        "derived",
        "differential",
        "metamorphic",
        "human",
        "Q1",
        "Q4",
        "mutation_target",
        "insufficient-bva-depth",
    ):
        assert phrase in text


def test_evidence_reference_names_the_tool_matrix_and_sarif_slice():
    text = (REFERENCES / "test-evidence-static.md").read_text(encoding="utf-8")
    for phrase in (
        "MC/DC",
        "killed / (killed + survived)",
        "80%",
        "90%",
        "pytest-cov",
        "diff-cover",
        "mutmut",
        "StrykerJS",
        "JaCoCo",
        "PITest",
        "coverlet",
        "Stryker.NET",
        "go test -coverprofile",
        "cargo-llvm-cov",
        "cargo-mutants",
        "2.1.0",
        "Ruff",
        "mypy",
        "Bandit",
        "ESLint",
        "Biome",
        "tsc",
        "SpotBugs",
        "PMD",
        "Checkstyle",
        "ErrorProne",
        "golangci-lint",
        "Clippy",
        "Semgrep",
        "ShellCheck",
        "Hadolint",
        "actionlint",
        "Checkov",
        "static-finding",
        "note",
    ):
        assert phrase in text
    assert "static-analysis-gate.md" in text
    assert "complexity-gate.md" in text


def test_report_reference_names_formats_trace_and_flake_causes():
    text = (REFERENCES / "test-report-flake.md").read_text(encoding="utf-8")
    for phrase in (
        "CTRF",
        "JUnit",
        "Allure",
        "trace.zip",
        "Requirement",
        "Risk",
        "Technique",
        "Check",
        "Result",
        "Defect",
        "timing-async",
        "state-leakage",
        "network-env",
        "locator",
        "order-dependence",
        "time-random",
        "30 days",
        "defect_ratchet",
        "stable-failure",
        "flake-quarantine",
        "150",
    ):
        assert phrase in text


def test_negative_check_requires_a_boundary_value_or_invalid_partition():
    criteria = [{"id": "FR-1", "text": "The amount is accepted", "input_bearing": True}]
    bare = [{"criterion_id": "FR-1", "technique": "bva", "boundary": ""}]
    refused = sdlc_flows.negative_check_gate(criteria, bare)
    assert refused["ok"] is False
    assert refused["reasons"] == ["missing-negative-check"]
    assert refused["missing"] == ["FR-1"]
    technique_only = [{"criterion_id": "FR-1", "technique": "boundary"}]
    assert sdlc_flows.negative_check_gate(criteria, technique_only)["ok"] is False
    blank_value = [{"criterion_id": "FR-1", "technique": "bva", "boundary": "  "}]
    assert sdlc_flows.negative_check_gate(criteria, blank_value)["ok"] is False
    false_boundary = [{"criterion_id": "FR-1", "boundary": False, "partition": "boundary"}]
    assert sdlc_flows.negative_check_gate(criteria, false_boundary)["ok"] is False
    valued = [{"criterion_id": "FR-1", "technique": "bva", "boundary": "max+1"}]
    assert sdlc_flows.negative_check_gate(criteria, valued)["ok"] is True
    zero = [{"criterion_id": "FR-1", "boundary": 0}]
    assert sdlc_flows.negative_check_gate(criteria, zero)["ok"] is True
    invalid = [{"criterion_id": "FR-1", "partition": "invalid"}]
    assert sdlc_flows.negative_check_gate(criteria, invalid)["ok"] is True
    spelled = [{"criterion_id": "FR-1", "partition": " Invalid "}]
    assert sdlc_flows.negative_check_gate(criteria, spelled)["ok"] is True
    for partition in ("negative", "error"):
        check = [{"criterion_id": "FR-1", "partition": partition}]
        assert sdlc_flows.negative_check_gate(criteria, check)["ok"] is True
    plain = [{"id": "FR-2", "text": "The page has a title"}]
    assert sdlc_flows.negative_check_gate(plain, [])["ok"] is True


def test_completion_trace_rejects_header_and_separator_rows():
    words = "requirement check result\n"
    header = "| Requirement | Check | Result |\n"
    separator = "| --- | --- | --- |\n"
    alignment = "| :--- | :---: | ---: |\n"
    refused = sdlc_flows.iso_29119_template("completion", words + header + separator + alignment)
    assert refused["ok"] is False
    assert "missing-requirement-check-result-trace" in refused["reasons"]
    accepted = sdlc_flows.iso_29119_template(
        "completion report",
        "Requirement, check, and result.\n| FR-1 | check-1 | passed |\n",
    )
    assert accepted["ok"] is True
    wide = sdlc_flows.iso_29119_template(
        "completion",
        words + "| FR-1 | 12 | bva | check-1 | passed | D-1 |\n",
    )
    assert wide["ok"] is True
    mixed = sdlc_flows.iso_29119_template(
        "completion",
        words + "| FR-1 | --- | passed |\n",
    )
    assert mixed["ok"] is False


def test_three_column_trace_stays_requirement_check_result():
    matrix = sdlc_flows.traceability_matrix(
        [{"id": "FR-1"}],
        [{"id": "check-1", "criterion_id": "FR-1", "result": "passed"}],
    )
    assert matrix.splitlines()[0] == "| Requirement | Check | Result |"
    assert "Technique" not in matrix
    assert "| FR-1 | check-1 | passed |" in matrix


def test_full_trace_requires_six_cells_and_renders_the_header():
    empty = sdlc_flows.traceability_matrix_full([])
    assert empty["ok"] is False
    assert empty["reasons"] == ["incomplete-trace-row"]
    assert empty["matrix"].splitlines()[0] == (
        "| Requirement | Risk | Technique | Check | Result | Defect |"
    )
    partial = sdlc_flows.traceability_matrix_full(
        [{"requirement": "FR-1", "risk": "8", "technique": "bva", "check": "c1", "result": "passed"}]
    )
    assert partial["ok"] is False
    assert partial["reasons"] == ["incomplete-trace-row"]
    assert partial["missing"] == [0]
    full = sdlc_flows.traceability_matrix_full(
        [
            {
                "Requirement": "FR-1",
                "Risk": "12",
                "Technique": "3-value BVA",
                "Check": "check-1",
                "Result": "failed",
                "Defect": "D-1",
            },
            ["FR-2", "4", "equivalence", "check-2", "passed", ""],
        ]
    )
    assert full["ok"] is False
    assert full["missing"] == [1]
    assert "| FR-1 | 12 | 3-value BVA | check-1 | failed | D-1 |" in full["matrix"]
    done = sdlc_flows.traceability_matrix_full(
        [["FR-1", "4", "equivalence", "check-1", "passed", "none"]]
    )
    assert done["ok"] is True
    assert done["reasons"] == []
    assert done["missing"] == []
    numbered = sdlc_flows.traceability_matrix_full(
        [{
            "requirement": "FR-9",
            "risk": 0,
            "technique": "bva",
            "check": "c",
            "result": "passed",
            "defect": "none",
        }]
    )
    assert numbered["ok"] is True
    assert "| FR-9 | 0 | bva | c | passed | none |" in numbered["matrix"]
    junk = sdlc_flows.traceability_matrix_full(["not-a-row"])
    assert junk["ok"] is False
    assert junk["missing"] == [0]


@pytest.mark.parametrize(
    ("level", "check", "ok"),
    [
        (7, {}, True),
        (8, {}, False),
        (8, {"technique": "bva", "boundary": "max+1"}, False),
        (8, {"boundary": ["min-1", "min+1"]}, True),
        (8, {"boundary": "max-1, max+1"}, True),
        (8, {"points": ["low", "high"]}, True),
        (8, {"boundary": ["min-1", "min-1"]}, False),
        (8, {"technique": "decision-table"}, True),
        (8, {"technique": "Decision Table"}, True),
        (8, {"technique": "state_transition"}, True),
        (8, {"technique": "state-transition", "boundary": ""}, True),
        (15, {"technique": "equivalence", "boundary": "min"}, False),
        (25, {"boundary": ["min-1", "min", "min+1"]}, True),
        (0, {"technique": "bva"}, True),
    ],
)
def test_bva_depth_partitions(level, check, ok):
    result = sdlc_flows.bva_depth_gate(level, check)
    assert result["ok"] is ok
    assert result["reasons"] == ([] if ok else ["insufficient-bva-depth"])


def test_mutation_target_exists_under_root_and_survivors_block(tmp_path: Path):
    source = tmp_path / "runtime" / "pay.py"
    source.parent.mkdir()
    source.write_text("def pay():\n    return 1\n", encoding="utf-8")
    assert sdlc_flows.mutation_target_gate(7, "", survivors=[{"line": 1}])["ok"] is True
    missing = sdlc_flows.mutation_target_gate(8, "  ")
    assert missing["ok"] is False
    assert missing["reasons"] == ["missing-mutation-target"]
    absent = sdlc_flows.mutation_target_gate(8, "runtime/missing.py", repo_root=tmp_path)
    assert absent["reasons"] == ["missing-mutation-target"]
    outside = sdlc_flows.mutation_target_gate(8, "../pay.py", repo_root=tmp_path)
    assert outside["reasons"] == ["missing-mutation-target"]
    named = sdlc_flows.mutation_target_gate(8, "runtime/pay.py")
    assert named["ok"] is True
    present = sdlc_flows.mutation_target_gate(8, "runtime/pay.py", repo_root=tmp_path)
    assert present == {"ok": True, "reasons": []}
    both = sdlc_flows.mutation_target_gate(
        8,
        "runtime/pay.py",
        repo_root=tmp_path,
        survivors=[{"path": "runtime/pay.py", "line": 2}],
    )
    assert both["ok"] is False
    assert both["reasons"] == ["survived-mutant"]
    assert sdlc_flows.mutation_target_gate(8, "runtime/pay.py", repo_root=tmp_path, survivors=[])["ok"] is True
    escaped = tmp_path / "outside.py"
    # A path that resolves outside the root is not a target, even if the file exists.
    escaped.write_text("x = 1\n", encoding="utf-8")
    flee = sdlc_flows.mutation_target_gate(8, escaped, repo_root=tmp_path / "runtime")
    assert flee["ok"] is False
    assert "missing-mutation-target" in flee["reasons"]


def test_coverage_floors_and_ratchet_boundaries():
    assert sdlc_flows.coverage_gate(80, 70, 70)["ok"] is True
    assert sdlc_flows.coverage_gate(80.0, 70.0, 70.0)["reasons"] == []
    low_patch = sdlc_flows.coverage_gate(79.999, 70, 70)
    assert low_patch["reasons"] == ["patch-coverage"]
    assert sdlc_flows.coverage_gate(90, 70, 70, strict=True)["ok"] is True
    strict = sdlc_flows.coverage_gate(89.999, 71, 70, strict=True)
    assert strict["reasons"] == ["patch-coverage"]
    drop = sdlc_flows.coverage_gate(95, 69.9, 70)
    assert drop["reasons"] == ["coverage-ratchet"]
    equal = sdlc_flows.coverage_gate(80, 70, 70.0)
    assert equal["ok"] is True
    both = sdlc_flows.coverage_gate(10, 1, 2, strict=True)
    assert both["ok"] is False
    assert both["reasons"] == ["patch-coverage", "coverage-ratchet"]
    missing = sdlc_flows.coverage_gate(None, None, None)
    assert missing["reasons"] == ["patch-coverage", "coverage-ratchet"]


def test_quality_scope_names_missing_characteristics():
    software = sdlc_flows.quality_scope_gate(_scope("in"))
    assert software["ok"] is True
    assert software["missing"] == []
    partial = _scope("out")
    partial.pop("safety")
    refused = sdlc_flows.quality_scope_gate(partial)
    assert refused["ok"] is False
    assert refused["reasons"] == ["missing-quality-scope"]
    assert refused["missing"] == ["safety"]
    fuzzy = _scope("in")
    fuzzy["security"] = "partial"
    assert sdlc_flows.quality_scope_gate(fuzzy)["missing"] == ["security"]
    spaced = _scope(" IN ")
    assert sdlc_flows.quality_scope_gate(spaced)["ok"] is True
    ai_missing = sdlc_flows.quality_scope_gate(_scope("in"), subject="AI")
    assert ai_missing["ok"] is False
    assert ai_missing["missing"] == list(sdlc_flows.ISO_25059)
    ai = _scope("out", extra={name: "in" for name in sdlc_flows.ISO_25059})
    assert sdlc_flows.quality_scope_gate(ai, subject="ai")["ok"] is True
    assert sdlc_flows.quality_scope_gate(_scope("in"), subject="software")["ok"] is True
    assert sdlc_flows.quality_scope_gate(None)["missing"] == list(sdlc_flows.ISO_25010)


def test_sarif_blocks_error_warning_and_omitted_on_changed_paths():
    changed = ["runtime/sdlc_flows.py"]
    clean = sdlc_flows.sarif_gate(_sarif([]), changed)
    assert clean == {"ok": True, "reasons": [], "rows": [], "notes": [], "blocked": 0}
    bad = sdlc_flows.sarif_gate({"version": "2.1"}, changed)
    assert bad["ok"] is False
    assert bad["reasons"] == ["sarif-version"]
    assert bad["rows"] == []
    warning = sdlc_flows.sarif_gate(
        _sarif([_finding(r"runtime\sdlc_flows.py", level="Warning", rule="S1", message="leak")]),
        changed,
    )
    assert warning["ok"] is False
    assert warning["reasons"] == ["static-finding"]
    assert warning["blocked"] == 1
    assert warning["rows"][0]["path"] == "runtime/sdlc_flows.py"
    assert warning["rows"][0]["level"] == "warning"
    omitted = sdlc_flows.sarif_gate(_sarif([_finding("runtime/sdlc_flows.py", level=None)]), changed)
    assert omitted["rows"][0]["level"] == "omitted"
    assert omitted["ok"] is False
    blank = sdlc_flows.sarif_gate(_sarif([_finding("runtime/sdlc_flows.py", level="")]), changed)
    assert blank["ok"] is False
    noted = sdlc_flows.sarif_gate(
        _sarif(
            [
                _finding("runtime/sdlc_flows.py", level="note", message="style"),
                _finding("runtime/sdlc_flows.py", level="none"),
                _finding("other/pay.py", level="error"),
            ]
        ),
        changed,
    )
    assert noted["ok"] is True
    assert noted["rows"] == []
    assert noted["blocked"] == 0
    assert len(noted["notes"]) == 2
    prefixed = sdlc_flows.sarif_gate(
        _sarif([_finding("file:///work/runtime/sdlc_flows.py", level="error")]),
        changed,
    )
    assert prefixed["blocked"] == 1
    many = _sarif([_finding("runtime/sdlc_flows.py", level="error", rule=str(i)) for i in range(21)])
    capped = sdlc_flows.sarif_gate(many, changed, max_rows=2)
    assert capped["ok"] is False
    assert len(capped["rows"]) == 2
    assert capped["blocked"] == 21
    assert sdlc_flows.sarif_gate("not-a-document", changed)["reasons"] == ["sarif-version"]


def test_flake_quarantine_stable_failure_cannot_be_waived():
    stable = sdlc_flows.flake_quarantine_gate(["fail", "fail", "fail"], _quarantine(), today=TODAY)
    assert stable["ok"] is False
    assert stable["flake"] is False
    assert stable["passed"] is False
    assert stable["quarantined"] is False
    assert stable["reasons"] == ["stable-failure"]
    assert stable["defect_type"] == ""
    passed = sdlc_flows.flake_quarantine_gate(["pass", "pass", "pass"], today=TODAY)
    assert passed["ok"] is True
    assert passed["passed"] is True
    assert passed["flake"] is False
    short = sdlc_flows.flake_quarantine_gate(["fail", "fail"], today=TODAY)
    assert short["flake"] is True
    assert short["reasons"] == ["flake-quarantine"]
    mixed = sdlc_flows.flake_quarantine_gate(["pass", "fail", "pass"], None, today=TODAY)
    assert mixed["ok"] is False
    assert mixed["flake"] is True


@pytest.mark.parametrize(
    ("overrides", "ok"),
    [
        ({}, True),
        ({"expires": (TODAY + timedelta(days=30)).isoformat()}, True),
        ({"expires": (TODAY + timedelta(days=31)).isoformat()}, False),
        ({"expires": (TODAY - timedelta(days=1)).isoformat()}, False),
        ({"expires": "2026-11-24T00:00:00"}, False),
        ({"owner": "  "}, False),
        ({"ticket": ""}, False),
        ({"cause": "flaky"}, False),
        ({"cause": "state-leakage"}, True),
        ({"cause": "network-env"}, True),
        ({"cause": "locator"}, True),
        ({"cause": "order-dependence"}, True),
        ({"cause": "time-random"}, True),
    ],
)
def test_flake_quarantine_window_and_causes(overrides, ok):
    result = sdlc_flows.flake_quarantine_gate(
        ["pass", "fail", "pass"],
        _quarantine(**overrides),
        today=TODAY,
    )
    assert result["flake"] is True
    assert result["passed"] is False
    assert result["ok"] is ok
    assert result["quarantined"] is ok
    if ok:
        assert result["reasons"] == []
        assert result["defect_type"] == _quarantine(**overrides)["cause"]
    else:
        assert result["reasons"] == ["flake-quarantine"]


def test_flake_gate_uses_the_same_three_run_window_as_rerun_flake():
    judged = sdlc_flows.rerun_flake(["fail", "fail", "fail", "pass"])
    assert judged["flake"] is False
    result = sdlc_flows.flake_quarantine_gate(["fail", "fail", "fail", "pass"], today=TODAY)
    assert result["reasons"] == ["stable-failure"]
    disagree = sdlc_flows.flake_quarantine_gate(["FAIL", "fail", "fail"], today=TODAY)
    assert disagree["flake"] is True
    assert disagree["reasons"] == ["flake-quarantine"]


def test_assertion_signal_blocks_new_files_and_warns_on_edits():
    healthy = _diff("+def test_amount():\n+    assert 1 == 1\n")
    assert sdlc_flows.assertion_signal_gate(healthy) == {
        "ok": True,
        "status": "pass",
        "reasons": [],
    }
    bare = _diff("+def test_amount():\n+    pass\n")
    assert sdlc_flows.assertion_signal_gate(bare) == {
        "ok": False,
        "status": "block",
        "reasons": ["assertion-free"],
    }
    helper = _diff(
        "+def test_amount():\n"
        "+    helper()\n"
        "+\n"
        "+def helper():\n"
        "+    assert False\n"
    )
    blocked = sdlc_flows.assertion_signal_gate(helper)
    assert blocked["status"] == "block"
    assert blocked["ok"] is False
    edited = (
        "diff --git a/tests/test_pay.py b/tests/test_pay.py\n"
        "--- a/tests/test_pay.py\n"
        "+++ b/tests/test_pay.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def test_amount():\n"
        "-    assert 1 == 1\n"
        "+    value = 1\n"
    )
    review = sdlc_flows.assertion_signal_gate(edited, is_new_file=False)
    assert review == {"ok": True, "status": "review", "reasons": ["assertion-free"]}
    added = (
        "diff --git a/tests/test_pay.py b/tests/test_pay.py\n"
        "--- a/tests/test_pay.py\n"
        "+++ b/tests/test_pay.py\n"
        "@@ -1,2 +1,3 @@\n"
        " def test_amount():\n"
        "+    assert value == 1\n"
        "     return value\n"
    )
    assert sdlc_flows.assertion_signal_gate(added, is_new_file=False)["status"] == "pass"
    assert sdlc_flows.assertion_signal_gate("")["status"] == "pass"


@pytest.mark.parametrize(
    "body",
    [
        "+def test_raises():\n+    with pytest.raises(ValueError):\n+        pay(None)\n",
        "+def test_raise():\n+    raise AssertionError('no')\n",
        '+it("rejects", () => {\n+  expect(code).toBe(false);\n+});\n',
        "+func TestPay(t *testing.T) {\n+    t.Fatal(\"no\")\n+}\n",
        "+#[test]\n+fn keeps_total() {\n+    assert_eq!(1, 1);\n+}\n",
        "+    @Test\n+    void rejects() {\n+        assertThrows(IOException.class, () -> pay(null));\n+    }\n",
        "+    [Fact]\n+    public void Rejects() {\n+        Assert.Equal(1, total);\n+    }\n",
    ],
)
def test_assertion_tokens_across_stacks(body):
    result = sdlc_flows.assertion_signal_gate(_diff(body))
    assert result["ok"] is True
    assert result["status"] == "pass"
    assert result["reasons"] == []


@pytest.mark.parametrize(
    "body",
    [
        '+it("should raise", () => {})\n',
        "+def test_amount():\n+    # assert x == 1\n",
        '+def test_amount():\n+    """Does not raise."""\n',
        "+def test_amount():\n+    // assert x == 1\n",
        "+def test_amount():\n+    /* assert x == 1 */\n",
        "+def test_amount():\n+    note = 'assert x == 1'\n",
        "+def test_amount():\n+    /*\n+    assert x == 1\n+    */\n",
    ],
)
def test_f5_comments_and_strings_do_not_count_as_assertions(body):
    result = sdlc_flows.assertion_signal_gate(_diff(body))
    assert result == {"ok": False, "status": "block", "reasons": ["assertion-free"]}


@pytest.mark.parametrize(
    "body",
    [
        "+def test_amount():\n+    assert x == 1\n",
        "+def test_amount():\n+    self.assertEqual(a, b)\n",
        "+def test_amount():\n+    expect(res).toBe(200)\n",
        "+def test_amount():\n+    with pytest.raises(ValueError):\n+        pay(None)\n",
        "+def test_amount():\n+    assert 4 // 2 == 2\n",
        '+it("should raise", () => {\n+  expect(res).toBe(200);\n+})\n',
        "+def test_amount():\n+    note = 'no assert here'\n+    assert y == 2\n",
    ],
)
def test_f5_real_assertions_still_pass(body):
    result = sdlc_flows.assertion_signal_gate(_diff(body))
    assert result == {"ok": True, "status": "pass", "reasons": []}


@pytest.mark.parametrize(
    ("body", "ok", "status", "reasons"),
    [
        (
            "+it('t', () => { const note = `assert x` })\n",
            False,
            "block",
            ["assertion-free"],
        ),
        (
            "+it('t', () => { const note = `say \\`assert x\\`` })\n",
            False,
            "block",
            ["assertion-free"],
        ),
        (
            "+it('t', () => { const x = 1 // assert x })\n",
            False,
            "block",
            ["assertion-free"],
        ),
        (
            "+it('t', () => { const x = 1; // assert x })\n",
            False,
            "block",
            ["assertion-free"],
        ),
        (
            "+assert 4 // 2 == 2\n",
            True,
            "pass",
            [],
        ),
        (
            "+    const url = \"https://example.com\" // assert x\n",
            False,
            "block",
            ["assertion-free"],
        ),
    ],
)
def test_f9_templates_and_midline_comments(body, ok, status, reasons):
    assert sdlc_flows.assertion_signal_gate(_diff(body)) == {
        "ok": ok,
        "status": status,
        "reasons": reasons,
    }
