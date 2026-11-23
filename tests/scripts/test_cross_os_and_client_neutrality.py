"""Cross-OS command hygiene, any-client tiers, and relative link integrity."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REFS = ROOT / "references"
LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
FENCE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)
SKIP_PREFIXES = ("http://", "https://", "mailto:")


def _fenced(text: str) -> list[str]:
    return FENCE.findall(text)


def _relative_targets(text: str) -> list[str]:
    targets: list[str] = []
    for match in LINK.finditer(text):
        target = match.group(1).strip().split()[0]
        if target.startswith(SKIP_PREFIXES) or target.startswith("#"):
            continue
        if "<" in target or ">" in target:
            continue
        path_part = target.split("#", 1)[0].strip()
        if path_part.startswith("<") and path_part.endswith(">"):
            path_part = path_part[1:-1]
        if path_part:
            targets.append(path_part)
    return targets


def test_test_docs_are_linked_from_test_design_and_exist():
    text = (REFS / "test-design.md").read_text(encoding="utf-8")
    for name in ("test-plan.md", "completion-report.md", "incident-report.md"):
        assert f"](test-docs/{name})" in text
        assert (REFS / "test-docs" / name).is_file()


def test_host_parity_defines_universal_client_tiers():
    matrix = (REFS / "host-parity-matrix.md").read_text(encoding="utf-8")
    hooks = (REFS / "lifecycle-hooks.md").read_text(encoding="utf-8")
    for text in (matrix, hooks):
        assert "Universal / Any AI Client" in text
        assert "Tier 1" in text
        assert "Tier 2" in text
        assert "Tier 3" in text
    assert "Native hooks + shell" in matrix
    assert "Instruction discovery + shell, no native hooks" in matrix
    assert "Prompt/chat-only, no shell" in matrix


def test_copyable_command_fences_have_no_and_and_chains():
    for name in ("durable-jobs.md", "work-github-playbook.md"):
        text = (REFS / name).read_text(encoding="utf-8")
        for block in _fenced(text):
            assert " && " not in block, name


def test_ci_status_economy_has_no_hardcoded_tmp_path():
    text = (REFS / "ci-status-economy.md").read_text(encoding="utf-8")
    assert "/tmp/" not in text


def test_edited_guidance_has_no_broken_relative_links():
    paths = list((ROOT / "skills").glob("*/SKILL.md"))
    paths.extend((ROOT / "references").glob("*.md"))
    broken: list[str] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for target in _relative_targets(text):
            if not (path.parent / target).resolve().exists():
                broken.append(f"{path.relative_to(ROOT)} -> {target}")
    assert broken == []
