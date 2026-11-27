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


def _git(cwd: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


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
                [{"path": shadow, "label": "shadow"}, {"path": bare, "label": "shadow"}],
            )
            self.assertEqual([bare], [hit["path"] for hit in hits])
            hits = self.retrieve._normalize_graphify_paths(
                project, [{"path": shadow, "label": "shadow"}]
            )
            self.assertEqual([bare], [hit["path"] for hit in hits])

    def test_graphify_relevance_floor_sees_second_label_in_same_file(self):
        body = (
            "NODE GenericWrapper [src=src/Escalation.java loc=L1]\n"
            "NODE handleEscalation [src=src/Escalation.java loc=L10]\n"
        )

        class Mindset:
            def relevance_floor(self, hits, query, *, project=None, texts=None):
                token = query.casefold()
                return [dict(hit) for hit in hits if token in str(hit.get("label") or "").casefold()]

            def store_budget_bytes(self, store):
                return 800

        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            target = project / "src" / "Escalation.java"
            target.parent.mkdir(parents=True)
            target.write_text("class Escalation {}\n", encoding="utf-8")
            completed = subprocess.CompletedProcess(["graphify"], 0, body, "")
            with (
                mock.patch.object(self.retrieve, "_mindset", return_value=Mindset()),
                mock.patch.object(self.retrieve, "_graphify_texts", return_value={}),
            ):
                receipt = self.retrieve._store_hit_receipt(
                    project, "graphify", "handleEscalation", completed, False
                )
        self.assertEqual("used", receipt["status"])
        self.assertEqual(["src/Escalation.java"], [hit["path"] for hit in receipt["hits"]])
        self.assertEqual(["handleEscalation"], [hit["label"] for hit in receipt["hits"]])

    def test_graphify_collapse_keeps_both_matching_labels_per_file(self):
        body = (
            "NODE handleEscalationAlpha [src=src/Escalation.java loc=L10]\n"
            "NODE handleEscalationBeta [src=src/Escalation.java loc=L20]\n"
        )

        class Mindset:
            def relevance_floor(self, hits, query, *, project=None, texts=None):
                token = query.casefold()
                return [dict(hit) for hit in hits if token in str(hit.get("label") or "").casefold()]

            def store_budget_bytes(self, store):
                return 800

        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            target = project / "src" / "Escalation.java"
            target.parent.mkdir(parents=True)
            target.write_text("class Escalation {}\n", encoding="utf-8")
            completed = subprocess.CompletedProcess(["graphify"], 0, body, "")
            with (
                mock.patch.object(self.retrieve, "_mindset", return_value=Mindset()),
                mock.patch.object(self.retrieve, "_graphify_texts", return_value={}),
            ):
                receipt = self.retrieve._store_hit_receipt(
                    project, "graphify", "handleEscalation", completed, False
                )
        self.assertEqual("used", receipt["status"])
        self.assertEqual(1, len(receipt["hits"]))
        self.assertEqual(
            ["handleEscalationAlpha", "handleEscalationBeta"], receipt["hits"][0]["labels"]
        )

    def test_graphify_shadow_does_not_rewrite_a_real_source_file(self):
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            shadow = "source/foo/Widget.java"
            bare = "foo/Widget.java"
            for relative in (shadow, bare):
                target = project / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("class Widget {}\n", encoding="utf-8")
            hits = self.retrieve._normalize_graphify_paths(
                project, [{"path": shadow, "label": "Widget", "line": 1}]
            )
        self.assertEqual([shadow], [hit["path"] for hit in hits])

    def test_graphify_shadow_before_bare_keeps_bare_line(self):
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            shadow = "source/src/Foo.java"
            bare = "src/Foo.java"
            hits = self.retrieve._normalize_graphify_paths(
                project,
                [
                    {"path": shadow, "label": "Foo", "line": 5},
                    {"path": bare, "label": "Foo", "line": 42},
                ],
            )
            self.assertEqual([bare], [hit["path"] for hit in hits])
            self.assertEqual([42], [hit["line"] for hit in hits])
            reversed_hits = self.retrieve._normalize_graphify_paths(
                project,
                [
                    {"path": bare, "label": "Foo", "line": 42},
                    {"path": shadow, "label": "Foo", "line": 5},
                ],
            )
            self.assertEqual([bare], [hit["path"] for hit in reversed_hits])
            self.assertEqual([42], [hit["line"] for hit in reversed_hits])

    def test_graphify_real_source_file_preserved_when_bare_hit_also_present(self):
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            shadow = "source/foo/Widget.java"
            bare = "foo/Widget.java"
            for relative in (shadow, bare):
                target = project / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("class Widget {}\n", encoding="utf-8")
            hits = self.retrieve._normalize_graphify_paths(
                project,
                [
                    {"path": shadow, "label": "Widget", "line": 1},
                    {"path": bare, "label": "Widget", "line": 2},
                ],
            )
        self.assertEqual([shadow, bare], [hit["path"] for hit in hits])

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
            self.assertEqual(worktree.resolve(), self.retrieve.project_root(worktree))
            self.assertEqual(tool_py, self.retrieve._tool_py(worktree))

    def test_project_root_stops_at_linked_worktree_boundary(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            main = base / "main"
            overlay = main / ".chaos-engine"
            overlay.mkdir(parents=True)
            (overlay / "install.py").write_text("# install\n", encoding="utf-8")

            wt = base / "wt"
            (wt / ".chaos-engine").mkdir(parents=True)
            (wt / ".chaos-engine" / "install.py").write_text("# install\n", encoding="utf-8")
            (wt / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
            nested = wt / "src" / "nested"
            nested.mkdir(parents=True)
            self.assertEqual(wt.resolve(), self.retrieve.project_root(nested))

            wt2 = base / "wt2"
            (wt2 / "sub" / ".chaos-engine").mkdir(parents=True)
            (wt2 / "sub" / ".chaos-engine" / "install.py").write_text(
                "# install\n", encoding="utf-8"
            )
            (wt2 / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
            deep = wt2 / "sub" / "deep"
            deep.mkdir(parents=True)
            self.assertEqual((wt2 / "sub").resolve(), self.retrieve.project_root(deep))

            wt3 = base / "wt3"
            wt3.mkdir()
            (wt3 / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
            nested3 = wt3 / "src" / "nested"
            nested3.mkdir(parents=True)
            self.assertEqual(wt3.resolve(), self.retrieve.project_root(nested3))

            wt4 = main / "wt4"
            wt4.mkdir()
            (wt4 / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
            nested4 = wt4 / "src" / "nested"
            nested4.mkdir(parents=True)
            self.assertEqual(wt4.resolve(), self.retrieve.project_root(nested4))

    def test_linked_worktree_retrieval_and_receipts_stay_worktree_scoped(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            main = base / "main"
            main.mkdir()
            _git(main, "init", "-q", "-b", "main")
            _git(main, "config", "user.email", "retrieve@example.test")
            _git(main, "config", "user.name", "Retrieve Test")
            (main / "baseline.txt").write_text("baseline\n", encoding="utf-8")
            _git(main, "add", "baseline.txt")
            _git(main, "commit", "-qm", "baseline")
            overlay = main / ".chaos-engine"
            overlay.mkdir()
            (overlay / "install.py").write_text("# install\n", encoding="utf-8")
            (overlay / "tool.py").write_text("# tool\n", encoding="utf-8")
            worktree = base / "worktree"
            _git(main, "worktree", "add", "-qb", "feature", str(worktree))
            (worktree / "only-in-worktree.txt").write_text("handleEscalation\n", encoding="utf-8")
            _git(worktree, "add", "only-in-worktree.txt")
            _git(worktree, "commit", "-qm", "feature")

            root = self.retrieve.project_root(worktree)
            self.assertEqual(worktree.resolve(), root)
            self.assertEqual(overlay / "tool.py", self.retrieve._tool_py(worktree))

            searched: list[Path] = []

            class Mindset:
                def run_rg(self, argv, *, cwd):
                    searched.append(Path(cwd))
                    needle = argv[-1]
                    lines: list[str] = []
                    for path in sorted(Path(cwd).rglob("*.txt")):
                        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                            if needle in line:
                                relative = path.relative_to(cwd).as_posix()
                                lines.append(f"{relative}:{number}:{line}")
                    return subprocess.CompletedProcess(argv, 0 if lines else 1, "\n".join(lines), "")

            with mock.patch.object(self.retrieve, "_mindset", return_value=Mindset()):
                rg_receipt = self.retrieve._run_rg(root, "handleEscalation", "worktree-scope")
            self.assertEqual([worktree.resolve()], searched)
            self.assertEqual("used", rg_receipt["status"])
            self.assertEqual(
                ["only-in-worktree.txt"], [hit["path"] for hit in rg_receipt["hits"]]
            )
            self.assertFalse((main / "only-in-worktree.txt").exists())

            live = self.retrieve._live_store_outcome(root, "handleEscalation")
            self.assertEqual("used", live["status"])
            self.assertIn("only-in-worktree.txt", [hit["path"] for hit in live["hits"]])

            self.retrieve._commit_retrieve_receipt(
                root,
                "graphify",
                "handleEscalation",
                {"status": "used", "reason": "hits", "hits": [{"path": "only-in-worktree.txt"}]},
            )
            self.assertTrue((worktree / ".chaos-engine-state/retrieve-justification.json").is_file())
            self.assertFalse((main / ".chaos-engine-state/retrieve-justification.json").exists())

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
