"""Doctor contracts for release vs commit, git-husk, and completion-scoped hooks.

Issues #224, #225, #226, and #227. These tests name the installer behavior;
they do not bump VERSION.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
import unittest.mock as mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SHA = "0123456789abcdef" * 2 + "01234567"
HEAD = "fedcba9876543210" * 2 + "fedcba98"
assert len(SHA) == 40 and len(HEAD) == 40

SURFACE_PATHS = {
    "claude": ".claude/settings.json",
    "codex": ".codex/hooks.json",
    "copilot": ".github/hooks/chaos-engine.json",
    "gemini": ".gemini/settings.json",
    "grok": ".grok/hooks/lifecycle.json",
    "opencode": ".opencode/plugins/chaos-engine-receipt.js",
    "cursor": ".cursor/hooks.json",
    "antigravity": ".agents/hooks.json",
}
HOOK_HOSTS = (
    "claude",
    "codex",
    "copilot",
    "gemini",
    "grok",
    "opencode",
    "cursor",
    "antigravity",
)
SELF_ENFORCED = (
    "entry --full",
    "retrieve",
    "delete-check",
    "ethics-check",
    "pre-done",
    "dod",
    "checkpoint",
    "resume",
    "maintain",
)
CORE_HOOKS = (
    "hooks/guard.py",
    "hooks/kernel.py",
    "hooks/launch.js",
    "hooks/launch.py",
    "hooks/lifecycle.py",
    "hooks/reflection.py",
)


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True)


class ReleaseCommitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.install = load("ce_doctor_224_install", ROOT / "install.py")
        cls.bootstrap = load("ce_doctor_224_bootstrap", ROOT / "bootstrap.py")
        cls.version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()

    def test_health_report_prints_release_after_full_commit(self):
        rendered = self.install.format_health_report(
            {"kind": "doctor", "status": "healthy", "commit": SHA}
        )
        lines = rendered.splitlines()
        self.assertEqual(f"commit: {SHA}", lines[1])
        self.assertEqual(f"release: {self.version}", lines[2])
        self.assertNotIn(SHA[:12] + "…", rendered)
        self.assertNotIn(SHA[:12] + "...", rendered)

    def test_source_behind_names_release_and_full_shas(self):
        project = Path("/tmp/ce-224-project")
        with mock.patch.object(self.install, "installed_commit_of", return_value=SHA), \
                mock.patch.object(
                    self.install, "detect_project_chaos_engine_source", return_value=None
                ):
            lonely = " ".join(self.install.source_behind_advisory(project))
        self.assertIn(f"release: {self.version}", lonely)
        self.assertIn(f"commit: {SHA}", lonely)
        self.assertNotRegex(lonely, rf"commit: {SHA[:12]}(?:\s|\()")

        source = Path("/tmp/ce-224-source")
        with mock.patch.object(self.install, "installed_commit_of", return_value=SHA), \
                mock.patch.object(
                    self.install, "detect_project_chaos_engine_source", return_value=source
                ), mock.patch.object(self.install, "detect_full_commit", return_value=HEAD):
            behind = " ".join(self.install.source_behind_advisory(project))
        self.assertIn(self.version, behind)
        self.assertIn(SHA, behind)
        self.assertIn(HEAD, behind)
        self.assertNotIn(f"HEAD {HEAD[:12]}", behind)
        self.assertNotRegex(behind, rf"commit: {SHA[:12]}(?:\s|\()")

        with mock.patch.object(self.install, "installed_commit_of", return_value=SHA), \
                mock.patch.object(
                    self.install, "detect_project_chaos_engine_source", return_value=source
                ), mock.patch.object(self.install, "detect_full_commit", return_value=SHA):
            matched = " ".join(self.install.source_behind_advisory(project))
        self.assertIn(f"release: {self.version}", matched)
        self.assertIn(f"commit: {SHA}", matched)
        self.assertIn("matches source HEAD", matched)

    def test_agent_summary_uses_one_release_commit_line_inside_the_budget(self):
        document = {
            "status": "healthy",
            "policySha256": "ab" * 32,
            "components": {"core": {"status": "healthy"}},
        }
        with mock.patch.object(
            self.install, "source_behind_advisory", return_value=("commit:", SHA[:12])
        ):
            # The implementation must replace a 12-hex advisory, not pass it through.
            rendered = self.install.format_agent_summary(document)
        # Drive the real formatter with a full advisory the new helper returns.
        with mock.patch.object(
            self.install,
            "source_behind_advisory",
            return_value=("release:", self.version, "commit:", SHA),
        ):
            rendered = self.install.format_agent_summary(document)
        self.assertLessEqual(len(rendered.splitlines()), self.install.AGENT_SUMMARY_MAX_LINES)
        self.assertIn(f"release: {self.version} commit: {SHA}", rendered)
        self.assertNotRegex(rendered, rf"commit: {SHA[:12]}(?:\s|\()")

    def test_commit_label_is_the_full_sha_and_may_exceed_width(self):
        stream = io.StringIO()
        environment = {"COLUMNS": "30", "NO_COLOR": "1", "TERM": "dumb", "PATH": "/usr/bin"}
        with mock.patch.dict(os.environ, environment, clear=True):
            reporter = self.bootstrap.InstallReporter(
                stream=stream, clock=lambda: 1.0, environ=environment
            )
            reporter.note_commit(SHA)
            row = reporter._aligned_live_row("Commit", reporter.commit_label or "")
            truncated = reporter._truncate(row)
        self.assertEqual(SHA, reporter.commit_label)
        self.assertNotIn("…", reporter.commit_label or "")
        self.assertNotIn("...", reporter.commit_label or "")
        self.assertIn(SHA, row)
        self.assertIn(SHA, truncated)
        self.assertTrue(self.bootstrap.line_may_exceed_width(row))
        self.assertIn(SHA, stream.getvalue())
        identity = self.bootstrap.identity_line(
            version=self.version, repository="ShaftHQ/chaosengine-harness", ref="main", sha=SHA
        )
        self.assertIn(f"({SHA[:12]})", identity)
        self.assertNotIn(SHA, identity)

    def test_release_line_keeps_the_short_healthy_report_within_four_lines(self):
        document = {
            "status": "healthy",
            "commit": "a" * 40,
            "components": {
                "core": {"status": "healthy", "taskImpact": "required"},
                "hooks": {"status": "healthy", "taskImpact": "required"},
                "maven-tools-mcp": {"status": "absent", "taskImpact": "optional"},
            },
        }
        rendered = self.install.format_health_report(document)
        self.assertLessEqual(len(rendered.splitlines()), 4)
        self.assertIn(f"release: {self.version}", rendered)


class GitHuskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.install = load("ce_doctor_225_install", ROOT / "install.py")
        cls.hooks = load("ce_doctor_225_git_hooks", ROOT / "runtime" / "git_hooks.py")
        cls.stores = load("ce_doctor_225_stores", ROOT / "runtime" / "stores.py")

    def _husk(self, project: Path, *, remote: bool) -> None:
        git_dir = project / ".git"
        git_dir.mkdir()
        (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        config = "[core]\n\trepositoryformatversion = 0\n"
        if remote:
            config += '[remote "origin"]\n\turl = https://example.invalid/repo.git\n'
        (git_dir / "config").write_text(config, encoding="utf-8")

    def test_config_text_keeps_a_remote_when_git_remote_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            self._husk(project, remote=True)
            self.assertTrue(self.install._git_has_remote(project))
            advice = self.install._husk_recovery_advice(project)
        self.assertIn("git-husk", advice)
        self.assertIn("references/box-durability.md", advice)
        self.assertNotIn("bot-entry.md", advice)
        self.assertNotIn("--no-secret-guard", advice)
        self.assertNotIn("git add -A", advice)
        self.assertIn("fresh clone", advice.casefold())
        self.assertIn("git init", advice)
        lowered = advice.casefold()
        self.assertTrue("do not" in lowered or "don't" in lowered)

    def test_local_husk_advice_backs_up_git_and_commits_explicit_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            self._husk(project, remote=False)
            self.assertFalse(self.install._git_has_remote(project))
            advice = self.install._husk_recovery_advice(project)
        self.assertIn("git-husk", advice)
        self.assertIn("references/box-durability.md", advice)
        self.assertNotIn("bot-entry.md", advice)
        self.assertNotIn("--no-secret-guard", advice)
        self.assertNotIn("git add -A", advice)
        self.assertIn("tracked-safe", advice)
        self.assertIn("git init", advice)
        self.assertIn(".git", advice)

    def test_recovery_required_husk_blocks_graphify_and_mempalace_repairs(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            self._husk(project, remote=True)
            result = {
                "status": "healthy",
                "components": {
                    "graphify": {
                        "status": "degraded",
                        "fixNext": "python3 .chaos-engine/install.py repair --project . --component graphify",
                    },
                    "mempalace": {
                        "status": "healthy",
                        "fixNext": "python3 .chaos-engine/install.py repair --project . --component mempalace",
                    },
                },
            }
            self.install.apply_git_husk_doctor(result, project)
        husk = result["components"]["git-husk"]
        self.assertEqual("recovery-required", husk["status"])
        self.assertIn("references/box-durability.md", str(husk["fixNext"]))
        self.assertNotIn("--no-secret-guard", str(husk["fixNext"]))
        for name in ("graphify", "mempalace"):
            row = result["components"][name]
            self.assertEqual("degraded", row["status"])
            self.assertEqual("git-husk", row["blockedBy"])
            self.assertNotIn("--component graphify", str(row["fixNext"]))
            self.assertNotIn("--component mempalace", str(row["fixNext"]))
            self.assertNotIn("--no-secret-guard", str(row["fixNext"]))
            self.assertIn("references/box-durability.md", str(row["fixNext"]))

    def test_repair_store_is_blocked_before_the_secret_guard_schedule(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / ".chaos-engine").mkdir()
            self._husk(project, remote=False)
            manifest = {"source": {"commit": "a" * 40}}
            with mock.patch.object(self.install, "verify_install", return_value=manifest), \
                    mock.patch.object(self.install, "load_installed_controller", return_value=mock.Mock()), \
                    mock.patch.object(self.install, "_install_store_schedule") as schedule:
                graphify = self.install.repair_component(project, "graphify")
                mempalace = self.install.repair_component(project, "mempalace")
        schedule.assert_not_called()
        for result, name in ((graphify, "graphify"), (mempalace, "mempalace")):
            self.assertEqual("blocked", result["status"])
            self.assertEqual(name, result["component"])
            self.assertEqual("git-husk", result["blockedBy"])
            self.assertIn("references/box-durability.md", str(result["fixNext"]))
            self.assertNotIn("--no-secret-guard", str(result["fixNext"]))
            self.assertNotIn("git add -A", str(result["fixNext"]))

    def test_secret_guard_husk_points_at_box_durability_and_the_flag_still_skips(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            self._husk(project, remote=True)
            guard = project / "secret_guard.py"
            guard.write_text("print('ok')\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"CHAOS_ENGINE_SECRET_GUARD": "1"}):
                failed = self.hooks.install_secret_guard(project, guard)
        self.assertEqual("failed", failed["status"])
        self.assertIn("git-husk", str(failed["reason"]))
        self.assertIn("references/box-durability.md", str(failed["reason"]))
        self.assertNotIn("--no-secret-guard", str(failed["reason"]))
        with mock.patch.dict(os.environ, {"CHAOS_ENGINE_SECRET_GUARD": "0"}):
            skipped = self.hooks.install_secret_guard(project, guard)
        self.assertEqual("skipped", skipped["status"])

    def test_unborn_graphify_hint_uses_tracked_paths_and_a_husk_has_no_commit_command(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = root / "graph"
            graph.mkdir()
            registry = root / "registry"
            registry.mkdir()
            unborn = root / "unborn"
            unborn.mkdir()
            _git(unborn, "init", "-q")
            husk = root / "husk"
            husk.mkdir()
            _git(husk, "init", "-q")
            (husk / ".git" / "HEAD").write_text("b" * 40 + "\n", encoding="utf-8")
            env = os.environ.copy()
            env["CHAOS_ENGINE_GRAPHIFY_OUT"] = str(graph)
            env["CHAOS_ENGINE_STORE_REGISTRY"] = str(registry)
            with mock.patch.dict(os.environ, env, clear=True):
                plain = self.stores.graphify_doctor_row(unborn)
                blocked = self.stores.graphify_doctor_row(husk)
        self.assertIsNotNone(plain)
        self.assertNotIn("git add -A", str(plain["fixNext"]))
        self.assertIn("tracked-safe", str(plain["fixNext"]))
        self.assertIn("git commit", str(plain["fixNext"]))
        self.assertIsNotNone(blocked)
        self.assertNotIn("git add -A", str(blocked["fixNext"]))
        self.assertNotIn("git commit", str(blocked["fixNext"]))
        self.assertIn("references/box-durability.md", str(blocked["fixNext"]))

    def _commit_repo(self, project: Path) -> None:
        _git(project, "init", "-q", "-b", "main")
        _git(project, "config", "user.email", "husk@example.invalid")
        _git(project, "config", "user.name", "Husk Test")
        (project / "keep.txt").write_text("keep\n", encoding="utf-8")
        _git(project, "add", "keep.txt")
        _git(project, "commit", "-qm", "init")

    def test_nested_directory_husk_is_not_hidden_by_parent_walk(self):
        """A directory husk inside a committed repo must not inherit that commit."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent = root / "parent"
            parent.mkdir()
            self._commit_repo(parent)
            graph = root / "graph"
            graph.mkdir()
            registry = root / "registry"
            registry.mkdir()
            env = os.environ.copy()
            env["CHAOS_ENGINE_GRAPHIFY_OUT"] = str(graph)
            env["CHAOS_ENGINE_STORE_REGISTRY"] = str(registry)
            for label, extra in (
                ("missing-objects-and-refs", ()),
                ("missing-refs", ("objects",)),
            ):
                with self.subTest(label=label):
                    nested = parent / label
                    nested.mkdir()
                    git_dir = nested / ".git"
                    git_dir.mkdir()
                    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
                    for name in extra:
                        (git_dir / name).mkdir()
                    calls: list[list[str]] = []
                    with mock.patch.dict(os.environ, env, clear=True):
                        self.assertTrue(self.stores._has_commit(nested))
                        row = self.stores.graphify_doctor_row(nested)
                        result = self.stores.refresh(
                            nested, runner=lambda command, cwd: calls.append(command) or 0
                        )
                    self.assertIsNotNone(row)
                    self.assertEqual("absent", row["status"])
                    self.assertIn("references/box-durability.md", str(row["fixNext"]))
                    self.assertNotIn("--component graphify", str(row["fixNext"]))
                    self.assertNotIn("git commit", str(row["fixNext"]))
                    self.assertEqual(0, result)
                    self.assertEqual([], calls)

    def test_linked_worktree_is_not_a_git_metadata_husk(self):
        """A gitfile pointing at ``worktrees/<name>`` uses the common dir, not the gitdir."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent = root / "parent"
            parent.mkdir()
            self._commit_repo(parent)
            linked = root / "linked"
            _git(parent, "worktree", "add", "-q", "-b", "linked", str(linked))
            self.assertTrue((linked / ".git").is_file())
            self.assertFalse(self.stores._git_metadata_husk(linked))
            self.assertFalse(self.stores._git_metadata_husk(parent))
            manual = root / "manual"
            manual.mkdir()
            worktree_git = parent / ".git" / "worktrees" / "manual"
            worktree_git.mkdir(parents=True)
            (worktree_git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
            (manual / ".git").write_text(
                "gitdir: ../parent/.git/worktrees/manual\n", encoding="utf-8"
            )
            self.assertFalse(self.stores._git_metadata_husk(manual))

    def test_submodule_shaped_husk_does_not_climb_to_the_parent_git_dir(self):
        """``gitdir: ../.git/modules/child`` stays a husk when the parent has objects/.

        Only ``worktrees/<name>`` climbs to the common dir. A modules gitdir
        with no ``objects/`` or ``refs/`` blocks refresh and store repair
        before the secret-guard schedule.
        """
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent = root / "parent"
            parent.mkdir()
            self._commit_repo(parent)
            module = parent / ".git" / "modules" / "child"
            module.mkdir(parents=True)
            (module / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
            child = parent / "child"
            child.mkdir()
            (child / ".git").write_text(
                "gitdir: ../.git/modules/child\n", encoding="utf-8"
            )
            (child / ".chaos-engine").mkdir()

            self.assertTrue(self.stores._git_metadata_husk(child))
            self.assertTrue(self.install.is_husk_git(child))
            owned = self.hooks._owned_common_dir(child / ".git")
            self.assertIsNotNone(owned)
            self.assertEqual(module.resolve(), Path(owned).resolve())
            self.assertNotEqual((parent / ".git").resolve(), Path(owned).resolve())

            calls: list[list[str]] = []
            refreshed = self.stores.refresh(
                child, runner=lambda command, cwd: calls.append(list(command)) or 0
            )
            self.assertEqual(0, refreshed)
            self.assertEqual([], calls)

            manifest = {"source": {"commit": "a" * 40}}
            with mock.patch.object(self.install, "verify_install", return_value=manifest), \
                    mock.patch.object(
                        self.install, "load_installed_controller", return_value=mock.Mock()
                    ), \
                    mock.patch.object(self.install, "_install_store_schedule") as schedule:
                graphify = self.install.repair_component(child, "graphify")
                mempalace = self.install.repair_component(child, "mempalace")
        schedule.assert_not_called()
        for result, name in ((graphify, "graphify"), (mempalace, "mempalace")):
            self.assertEqual("blocked", result["status"])
            self.assertEqual(name, result["component"])
            self.assertEqual("git-husk", result["blockedBy"])
            self.assertIn("references/box-durability.md", str(result["fixNext"]))

    def test_absolute_gitdir_resolves_worktree_and_symlinked_module_husk(self):
        """Absolute ``gitdir:`` paths resolve before the worktrees/modules check.

        A real worktree gitdir stays healthy. An absolute ``gitdir:`` that
        points at ``worktrees/<name>`` and is a symlink to ``modules/<name>``
        resolves to the module and is a husk.
        """
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent = root / "parent"
            parent.mkdir()
            self._commit_repo(parent)
            linked = root / "linked"
            _git(parent, "worktree", "add", "-q", "-b", "linked", str(linked))
            gitfile = linked / ".git"
            relative = gitfile.read_text(encoding="utf-8").split(":", 1)[1].strip()
            absolute = (linked / relative).resolve()
            gitfile.write_text(f"gitdir: {absolute}\n", encoding="utf-8")
            self.assertFalse(self.install.is_husk_git(linked))

            module = parent / ".git" / "modules" / "ghost"
            module.mkdir(parents=True)
            (module / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
            link = parent / ".git" / "worktrees" / "ghost"
            link.symlink_to(module, target_is_directory=True)
            child = root / "ghost-child"
            child.mkdir()
            (child / ".git").write_text(f"gitdir: {link}\n", encoding="utf-8")
            resolved = self.install.resolve_git_common_dir(child)
            self.assertIsNotNone(resolved)
            self.assertEqual(module.resolve(), Path(resolved).resolve())
            self.assertTrue(self.install.is_husk_git(child))


class CompletionHookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.install = load("ce_doctor_226_install", ROOT / "install.py")
        cls.bootstrap = load("ce_doctor_226_bootstrap", ROOT / "bootstrap.py")
        cls.surfaces = load("ce_doctor_226_surfaces", ROOT / "runtime" / "hook_surfaces.py")
        cls.overlay = load("ce_doctor_226_overlay", ROOT / "runtime" / "worktree_overlay.py")
        cls.fixture = load("ce_doctor_226_fixture", ROOT / "tests" / "scripts" / "ce_installed_fixture.py")

    def test_canonical_hook_surfaces_match_the_eight_production_hosts(self):
        self.assertEqual(HOOK_HOSTS, self.surfaces.HOOK_SURFACE_HOSTS)
        self.assertEqual(SURFACE_PATHS, dict(self.surfaces.HOOK_SURFACE_PATHS))
        self.assertEqual(HOOK_HOSTS, self.overlay.HOOK_HOSTS)
        self.assertEqual(HOOK_HOSTS, self.fixture.HOOK_HOSTS)
        conformance = load("ce_doctor_226_conformance", ROOT / "runtime" / "conformance.py")
        self.assertEqual(set(HOOK_HOSTS), set(conformance.production_hook_registry()))

    def _overlay_scripts(self, target: Path) -> None:
        for relative in CORE_HOOKS:
            path = target / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# hook\n", encoding="utf-8")

    def _satisfy_required_components(self, project: Path, target: Path) -> None:
        """Keep non-hook rows from escalating so hook status is what the assertion sees."""
        def touch(path: Path, text: str = "{}\n") -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

        for relative in (
            "skills/chaos-engine/SKILL.md",
            "vendor/caveman/PIN.json",
            "vendor/ponytail/PIN.json",
            "vendor/icm-architect/PIN.json",
            "skills/self-improve/SKILL.md",
            "references/work-github-playbook.md",
            "manifest.json",
        ):
            touch(target / relative, "#\n")
        for relative in (
            ".agents/skills/chaos-engine/SKILL.md",
            "plugins/caveman/skills/caveman/SKILL.md",
            "plugins/ponytail/skills/ponytail/SKILL.md",
            "plugins/icm-architect/skills/icm-architect/SKILL.md",
            ".agents/plugins/marketplace.json",
            ".claude-plugin/marketplace.json",
            "plugins/chaos-engine/.codex-plugin/plugin.json",
            "plugins/chaos-engine/.claude-plugin/plugin.json",
            "plugins/caveman/.codex-plugin/plugin.json",
            "plugins/caveman/.claude-plugin/plugin.json",
            "plugins/ponytail/.codex-plugin/plugin.json",
            "plugins/ponytail/.claude-plugin/plugin.json",
            "plugins/icm-architect/.codex-plugin/plugin.json",
            "plugins/icm-architect/.claude-plugin/plugin.json",
            ".mcp.json",
            ".codex/config.toml",
            ".memory/config.json",
            "mempalace.yaml",
        ):
            touch(project / relative)
        agents = project / ".claude" / "agents"
        agents.mkdir(parents=True, exist_ok=True)
        for index in range(10):
            (agents / f"chaos-engine-{index}.md").write_text("#\n", encoding="utf-8")

    def _doctor(self, project: Path, target: Path) -> dict:
        self._satisfy_required_components(project, target)
        controller = mock.Mock()
        controller.retrieval_configs_healthy.return_value = True
        controller.mempalace_runtime_status.return_value = {"status": "healthy"}
        controller.maven_tools_cache_status.return_value = {"status": "absent"}
        controller.selected_maven_tools_cache_status = None
        result: dict = {"status": "healthy"}
        with mock.patch.object(self.install, "load_manifest", return_value={}), \
                mock.patch.object(self.install, "_attach_l84_l92_doctor_findings"), \
                mock.patch.object(self.install, "_apply_shared_store_doctor"), \
                mock.patch.object(self.install, "read_bundle_options", return_value={}):
            self.install.attach_component_status(
                result, project, target, "healthy", controller, inspect_retrieval_state=False,
            )
        return result

    def test_unattended_install_expects_every_hook_surface(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            target = project / ".chaos-engine"
            self._overlay_scripts(target)
            result = self._doctor(project, target)
        hooks = result["components"]["hooks"]
        self.assertEqual("degraded", hooks["status"])
        self.assertEqual("advisory", hooks["taskImpact"])
        self.assertEqual("healthy", result["status"])
        self.assertEqual(
            [SURFACE_PATHS[host] for host in HOOK_HOSTS],
            list(hooks["hookHostsMissing"]),
        )
        self.assertIn("repair --project . --component hooks", str(hooks["fixNext"]))

    def test_selected_hook_host_ignores_unselected_receipts(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            target = project / ".chaos-engine"
            self._overlay_scripts(target)
            self.install.record_completion_targets(project, ("cursor",))
            missing = self._doctor(project, target)
            cursor = project / SURFACE_PATHS["cursor"]
            cursor.parent.mkdir(parents=True, exist_ok=True)
            cursor.write_text("{}\n", encoding="utf-8")
            # An unselected receipt must not prove health and must not fail it.
            codex = project / SURFACE_PATHS["codex"]
            codex.parent.mkdir(parents=True, exist_ok=True)
            codex.write_text("{}\n", encoding="utf-8")
            present = self._doctor(project, target)
        degraded = missing["components"]["hooks"]
        self.assertEqual("degraded", degraded["status"])
        self.assertEqual("required", degraded["taskImpact"])
        self.assertEqual("recovery-required", missing["status"])
        self.assertEqual([SURFACE_PATHS["cursor"]], list(degraded["hookHostsMissing"]))
        self.assertNotIn(SURFACE_PATHS["codex"], list(degraded["hookHostsMissing"]))
        healthy = present["components"]["hooks"]
        self.assertEqual("healthy", healthy["status"])
        self.assertEqual("healthy", present["status"])
        self.assertNotIn("hookHostsMissing", healthy)

    def test_grok_bot_only_is_an_instruction_only_advisory(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            target = project / ".chaos-engine"
            self._overlay_scripts(target)
            self.install.record_completion_targets(project, ("grok-bot",))
            result = self._doctor(project, target)
        hooks = result["components"]["hooks"]
        self.assertEqual("sync-advisory", hooks["status"])
        self.assertNotEqual("healthy", hooks["status"])
        self.assertNotEqual("degraded", hooks["status"])
        self.assertEqual("advisory", hooks["taskImpact"])
        self.assertEqual("completion-target", hooks["scope"])
        self.assertEqual(["grok-bot"], list(hooks["completionTargets"]))
        self.assertEqual([], list(hooks["hookHostsExpected"]))
        row = hooks["instructionOnly"][0]
        self.assertEqual("grok-bot", row["host"])
        self.assertEqual("GAP-GROKBOT-HOOKS", row["gap"])
        self.assertEqual("GAP-BOT-ENTRY", row["residualRisk"])
        self.assertEqual(list(SELF_ENFORCED), list(row["selfEnforced"]))
        detail = str(hooks["detail"])
        self.assertIn("GAP-GROKBOT-HOOKS", detail)
        self.assertIn("GAP-BOT-ENTRY", detail)
        for command in SELF_ENFORCED:
            self.assertIn(command, detail)
        self.assertIn("tool.py", detail)
        learning = hooks["learningSession"]
        self.assertEqual("advisory", learning["status"])
        self.assertEqual("self", learning["enforcedBy"])
        self.assertIs(False, learning["gateInstalled"])
        self.assertEqual("healthy", result["status"])

    def test_mixed_targets_require_the_hook_surface_and_keep_the_advisory(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            target = project / ".chaos-engine"
            self._overlay_scripts(target)
            self.install.record_completion_targets(project, ("cursor", "grok-bot"))
            missing = self._doctor(project, target)
            cursor = project / SURFACE_PATHS["cursor"]
            cursor.parent.mkdir(parents=True, exist_ok=True)
            cursor.write_text("{}\n", encoding="utf-8")
            present = self._doctor(project, target)
        degraded = missing["components"]["hooks"]
        self.assertEqual("degraded", degraded["status"])
        self.assertEqual([SURFACE_PATHS["cursor"]], list(degraded["hookHostsMissing"]))
        self.assertEqual("grok-bot", degraded["instructionOnly"][0]["host"])
        self.assertEqual("GAP-GROKBOT-HOOKS", degraded["instructionOnly"][0]["gap"])
        healthy = present["components"]["hooks"]
        self.assertEqual("healthy", healthy["status"])
        self.assertEqual("grok-bot", healthy["instructionOnly"][0]["host"])
        self.assertEqual("Stop", healthy["learningSession"]["enforcedBy"])

    def test_agent_summary_names_the_grok_bot_gap_without_changing_the_verdict(self):
        document = {
            "status": "healthy",
            "policySha256": "cd" * 32,
            "components": {
                "core": {"status": "healthy"},
                "hooks": {
                    "status": "sync-advisory",
                    "taskImpact": "advisory",
                    "instructionOnly": [
                        {
                            "host": "grok-bot",
                            "gap": "GAP-GROKBOT-HOOKS",
                            "residualRisk": "GAP-BOT-ENTRY",
                            "selfEnforced": list(SELF_ENFORCED),
                        }
                    ],
                },
            },
        }
        rendered = self.install.format_agent_summary(document)
        self.assertLessEqual(len(rendered.splitlines()), self.install.AGENT_SUMMARY_MAX_LINES)
        self.assertTrue(rendered.startswith("doctor: pass"))
        self.assertIn("GAP-GROKBOT-HOOKS", rendered)
        self.assertIn("GAP-BOT-ENTRY", rendered)
        self.assertIn("tool.py", rendered)
        self.assertEqual(1, sum(1 for line in rendered.splitlines() if "GAP-GROKBOT-HOOKS" in line))

    def test_grok_bot_card_lists_self_enforced_commands_and_gap_bot_entry(self):
        card = self.bootstrap.format_host_onboarding_cards(targets=("grok-bot",))
        self.assertIn("GAP-GROKBOT-HOOKS", card)
        self.assertIn("GAP-BOT-ENTRY", card)
        self.assertIn("tool.py", card)
        for command in SELF_ENFORCED:
            self.assertIn(command, card)
        self.assertNotIn("Grok Bot", self.bootstrap.format_host_onboarding_cards())

    def test_doctor_json_does_not_grow_a_top_level_release_key(self):
        self.assertNotIn("release", self.install._DIAGNOSTIC_FIELDS["doctor"])
        self.assertNotIn("releaseVersion", self.install._DIAGNOSTIC_FIELDS["doctor"])


class OpenCodeToolResponseShapeTests(unittest.TestCase):
    """The generated plugin source forwards tool output. Node execution is the sibling file."""

    @classmethod
    def setUpClass(cls):
        cls.surfaces = load("ce_doctor_227_surfaces", ROOT / "runtime" / "hook_surfaces.py")

    def test_payload_for_mentions_tool_response(self):
        source = self.surfaces.opencode_plugin_source()
        start = source.index("function payloadFor")
        end = source.index("async function guard")
        body = source[start:end]
        self.assertIn("tool_response", body)
        self.assertIn("PostToolUse", body)


if __name__ == "__main__":
    unittest.main()
