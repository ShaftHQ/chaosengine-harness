"""Focused regressions for #257 retrieval receipts and #258 worktree/doctor fallbacks."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class _TimeoutPolicy:
    HEAL_PROMPT = "heal"

    def project_mcp_policy_error(self, project: Path) -> None:
        return None

    def repair_user_github_mcp(self):
        raise subprocess.TimeoutExpired(["gh", "auth", "status"], 5)

    def user_mcp_policy_finding(self, project: Path) -> None:
        return None

    def user_skill_collision_error(self) -> None:
        return None


class RetrieveFixes257258Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.retrieve = _load("ce_retrieve_fixes_257_258", "runtime/retrieve.py")
        cls.policy = _load("ce_mcp_policy_fixes_258", "runtime/mcp_policy.py")
        cls.install = _load("ce_install_fixes_258", "install.py")
        cls.tool = _load("ce_tool_fixes_258", "tool.py")

    def test_mempalace_hit_keeps_a_bounded_excerpt_section(self):
        body = """# J12

Source: J12.md
Complaints escalation history: the board reviewed repeated failures.

Source: Other.md
Unrelated line.
"""
        completed = subprocess.CompletedProcess(
            ["git", "ls-files"], 0, stdout="src/notes/J12.md\nsrc/Other.md\n", stderr=""
        )
        with mock.patch.object(self.retrieve.subprocess, "run", return_value=completed):
            hits = self.retrieve._mempalace_hits(Path("/project"), body, "J12 Complaints")
        self.assertEqual(2, len(hits))
        self.assertEqual("src/notes/J12.md", hits[0]["path"])
        self.assertIn("Complaints escalation history", hits[0]["section"])
        self.assertNotIn("Unrelated line", hits[0]["section"])

    def test_graphify_source_shadows_are_normalized_and_deduplicated(self):
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            target = project / "src" / "main" / "java" / "Foo.java"
            target.parent.mkdir(parents=True)
            target.write_text("class Foo {}\n", encoding="utf-8")
            shadow = "source/src/main/java/Foo.java"
            bare = "src/main/java/Foo.java"
            hits = self.retrieve._normalize_graphify_paths(
                project,
                [{"path": shadow, "label": "shadow"}, {"path": bare, "label": "bare"}],
            )
            self.assertEqual([bare], [hit["path"] for hit in hits])
            hits = self.retrieve._normalize_graphify_paths(
                project, [{"path": shadow, "label": "shadow"}]
            )
            self.assertEqual([bare], [hit["path"] for hit in hits])

    def test_multiword_rg_fallback_tries_rare_tokens_after_literal_miss(self):
        calls: list[str] = []

        class Mindset:
            def run_rg(self, argv, cwd):
                calls.append(argv[-1])
                if len(calls) == 1:
                    return subprocess.CompletedProcess(argv, 1, "", "")
                return subprocess.CompletedProcess(
                    argv,
                    0,
                    "src/notes/J12.md:1: Complaints escalation history\n",
                    "",
                )

        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            with (
                mock.patch.object(self.retrieve, "_mindset", return_value=Mindset()),
                mock.patch.object(self.retrieve, "_verify_hits", side_effect=lambda p, h: h),
                mock.patch.object(
                    self.retrieve,
                    "question_rare_tokens",
                    return_value=["J12", "Complaints", "Escalation"],
                ),
            ):
                receipt = self.retrieve._run_rg(
                    project, "J12 Complaints Escalation history", "topic-query"
                )
        self.assertEqual(2, len(calls))
        self.assertEqual("J12|Complaints|Escalation", calls[1])
        self.assertEqual("used", receipt["status"])

    def test_linked_worktree_resolves_main_overlay_without_git_process(self):
        with tempfile.TemporaryDirectory() as raw:
            main = Path(raw) / "main"
            worktree = Path(raw) / "delegate"
            overlay = main / ".chaos-engine"
            overlay.mkdir(parents=True)
            (overlay / "install.py").write_text("# install\n", encoding="utf-8")
            tool_py = overlay / "tool.py"
            tool_py.write_text("# tool\n", encoding="utf-8")
            (main / ".git").mkdir()
            gitdir = main / ".git" / "worktrees" / "delegate"
            gitdir.mkdir(parents=True)
            (gitdir / "commondir").write_text("../..", encoding="utf-8")
            (worktree / "tools" / "repository-map").mkdir(parents=True)
            (worktree / "tools" / "repository-map" / "resolve_mempalace.py").write_text(
                "# resolver\n", encoding="utf-8"
            )
            (worktree / ".git").write_text(
                f"gitdir: {gitdir}\n", encoding="utf-8"
            )
            self.assertEqual(main, self.tool.shared_project_root(worktree))
            self.assertEqual(main, self.retrieve.project_root(worktree))
            self.assertEqual(tool_py, self.retrieve._tool_py(worktree))

    def test_gh_probe_timeout_is_explicit_and_caught(self):
        def runner(argv, **options):
            self.assertLessEqual(options["timeout"], 5)
            raise subprocess.TimeoutExpired(argv, options["timeout"])

        self.assertFalse(self.policy.gh_is_configured(runner))
        result = {"status": "healthy"}
        components = {"mcps": {"status": "healthy"}}
        self.install.apply_mcp_policy_doctor(result, components, Path("/project"), _TimeoutPolicy())
        self.assertEqual("healthy", result["status"])
        self.assertNotIn("githubMcpRepair", components["mcps"])


if __name__ == "__main__":
    unittest.main()
