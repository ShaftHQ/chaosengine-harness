"""Regression tests for GitHub issue #260 (D1-D7, FR-1..FR-6, SC-1..SC-5)."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess  # nosec B404 - tests invoke fixed local Python/sh scripts.
import sys
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class OpenBotIssue260Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hosts = _load("ce_260_hosts", ROOT / "runtime" / "hosts.py")
        cls.stores = _load("ce_260_stores", ROOT / "runtime" / "stores.py")
        cls.deps = _load("ce_260_deps", ROOT / "runtime" / "dependencies.py")
        cls.conformance = _load("ce_260_conformance", ROOT / "runtime" / "conformance.py")
        cls.install = _load("ce_260_install", ROOT / "install.py")
        cls.bootstrap = _load("ce_260_bootstrap", ROOT / "bootstrap.py")

    def test_d1_openbot_host_identity_distinct_from_grok_and_grok_bot(self):
        entry = self.hosts.INSTRUCTION_ONLY_HOSTS["openbot"]
        self.assertEqual("AGENTS.md", entry["instructions"])
        self.assertEqual(".chaos-engine/skills/chaos-engine/SKILL.md", entry["skill"])
        self.assertEqual("GAP-OPENBOT-HOOKS", entry["gap"])
        self.assertNotEqual(self.hosts.INSTRUCTION_ONLY_HOSTS["grok-bot"]["gap"], entry["gap"])
        self.assertIn("openbot", self.bootstrap.INSTALL_HOST_IDS)
        self.assertEqual(("openbot",), self.bootstrap.parse_install_hosts("openbot"))

        parity = json.loads((ROOT / "scripts/ci/agent_harness_parity.json").read_text(encoding="utf-8"))
        self.assertIn("openbot", parity["hosts"])
        for row in parity["capabilities"]:
            self.assertIn("openbot", row)

        bug_yml = (ROOT / ".github/ISSUE_TEMPLATE/bug_report.yml").read_text(encoding="utf-8")
        self.assertIn("- OpenBot", bug_yml)
        self.assertIn('placeholder: "1.20261126.0"', bug_yml)

        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            skill = project / ".chaos-engine/skills/chaos-engine/SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("# ChaosEngine\n", encoding="utf-8")
            self.assertEqual("openbot", self.hosts.classify_instruction_host(project))
            self.assertEqual(
                "openbot",
                self.hosts.classify_instruction_host(project, environ={"OPENBOT_SESSION_ID": "ob-1"}),
            )

    def test_d2_grok_runtime_status_unbound_project_and_failed_probe_never_emit_hooks_trust(self):
        def result(stdout: str, returncode: int = 0):
            return subprocess.CompletedProcess([], returncode, stdout, "")

        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            unbound = self.hosts.grok_runtime_status(
                project,
                executable="grok",
                runner=lambda *_a, **_k: result(json.dumps({"projectRoot": None, "projectTrusted": False})),
            )
            self.assertEqual("failed", unbound["status"])
            self.assertEqual("CE_GROK_PROJECT_UNBOUND", unbound["code"])
            self.assertIs(False, unbound["hooksLoaded"])
            self.assertNotIn("/hooks-trust", str(unbound["detail"]))

            unbound_even_trusted = self.hosts.grok_runtime_status(
                project,
                executable="grok",
                runner=lambda *_a, **_k: result(json.dumps({"projectRoot": None, "projectTrusted": True, "hooks": []})),
            )
            self.assertEqual("failed", unbound_even_trusted["status"])
            self.assertIs(False, unbound_even_trusted["hooksLoaded"])
            self.assertNotIn("/hooks-trust", str(unbound_even_trusted["detail"]))

            for bad in (result("", 1), result("not-json", 0), result("{}", 0)):
                probe_fail = self.hosts.grok_runtime_status(
                    project,
                    executable="grok",
                    runner=lambda *_a, _r=bad, **_k: _r,
                )
                self.assertEqual("failed", probe_fail["status"])
                self.assertEqual("CE_GROK_INSPECT_FAILED", probe_fail["code"])
                self.assertIs(False, probe_fail["hooksLoaded"])
                self.assertNotIn("/hooks-trust", str(probe_fail["detail"]))

            untrusted = self.hosts.grok_runtime_status(
                project,
                executable="grok",
                runner=lambda *_a, **_k: result(json.dumps({"projectRoot": str(project), "projectTrusted": False})),
            )
            self.assertEqual("sync-advisory", untrusted["status"])
            self.assertIn("/hooks-trust", str(untrusted["detail"]))

    def test_d3_openbot_contract_requires_canonical_router_skill(self):
        canonical = (ROOT / "skills/chaos-engine/SKILL.md").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            target = project / ".chaos-engine"
            (target / "hooks").mkdir(parents=True)
            for name in ("guard.py", "kernel.py", "launch.js", "launch.py", "lifecycle.py", "reflection.py"):
                (target / "hooks" / name).write_text("# hook\n", encoding="utf-8")
            (project / "AGENTS.md").write_text(self.hosts.instruction_block(), encoding="utf-8")
            self.install.record_completion_targets(project, ("openbot",))

            # Missing canonical router skill fails closed.
            missing = self.hosts.openbot_skill_contract_status(project)
            self.assertEqual("recovery-required", missing["status"])
            self.assertFalse(missing["claimsHookEnforcement"])

            components = {"hooks": {"status": "healthy", "taskImpact": "required"}}
            self.install._apply_completion_hook_health(project, target, components, host_controller=self.hosts)
            self.assertEqual("recovery-required", components["hooks"]["status"])
            self.assertEqual("required", components["hooks"]["taskImpact"])

            # 190-byte pointer stub without canonical router also fails.
            skill = target / "skills/chaos-engine/SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("---\nname: chaos-engine\n---\nFollow pointer only.\n", encoding="utf-8")
            pointer_only = self.hosts.openbot_skill_contract_status(project)
            self.assertEqual("recovery-required", pointer_only["status"])

            # Canonical router body passes contract as instruction-only + explicit retrieve receipt.
            skill.write_text(canonical, encoding="utf-8")
            valid = self.hosts.openbot_skill_contract_status(project)
            self.assertEqual("healthy", valid["status"])
            self.assertEqual("instruction-only", valid["enforcement"])
            self.assertEqual("explicit-retrieve-receipt", valid["retrieveMode"])
            self.assertFalse(valid["claimsHookEnforcement"])

            components = {"hooks": {"status": "healthy", "taskImpact": "required"}}
            self.install._apply_completion_hook_health(project, target, components, host_controller=self.hosts)
            self.assertEqual("sync-advisory", components["hooks"]["status"])
            self.assertIn("GAP-OPENBOT-HOOKS", str(components["hooks"]["detail"]))
            self.assertIn("explicit retrieve receipt", str(components["hooks"]["detail"]))
            self.assertIn("no hook enforcement", str(components["hooks"]["detail"]))

    def test_d4_doctor_fails_closed_on_error_severity_components(self):
        doc = {
            "status": "healthy",
            "commit": "a" * 40,
            "components": {
                "core": {"status": "healthy", "taskImpact": "required"},
                "graphify": {"status": "degraded", "taskImpact": "required-when-indexed"},
                "mempalace": {"status": "degraded", "taskImpact": "advisory"},
            },
            "hosts": {"status": "healthy"},
        }
        self.assertTrue(self.install.component_escalates_overall(doc["components"]["graphify"]))
        self.assertFalse(self.install.component_escalates_overall(doc["components"]["mempalace"]))
        self.assertEqual(1, self.install.doctor_exit_code(doc))
        rendered = self.install.format_health_report(doc)
        self.assertNotIn("ChaosEngine doctor: healthy", rendered)
        self.assertIn("ChaosEngine doctor: recovery-required", rendered)

        reconciled = json.loads(json.dumps(doc))
        self.install.reconcile_doctor_overall_status(reconciled)
        self.assertEqual("recovery-required", reconciled["status"])
        self.assertEqual(1, self.install.doctor_exit_code(reconciled))

    def test_d5_non_git_graphify_refresh_matches_project_content_revision_and_recovers_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "nongit"
            project.mkdir()
            (project / "app.py").write_text("def hello():\n    return 1\n", encoding="utf-8")

            def invoke(command, _cwd):
                out = Path(command[command.index("--out") + 1]) / "graphify-out"
                out.mkdir(parents=True, exist_ok=True)
                (out / "graph.json").write_text('{"nodes": [], "edges": []}\n', encoding="utf-8")
                (out / "manifest.json").write_text('{"files": 1}\n', encoding="utf-8")
                return 0

            with mock.patch.object(self.stores, "_store_tool", return_value="graphify"):
                # First refresh on non-git fixture.
                rev1 = self.stores.store_revision(project)
                self.stores._refresh_graphify(
                    project, snapshot=project, scratch=project / ".scratch", revision=rev1, invoke=invoke
                )
                marker = json.loads((project / "graphify-out" / ".chaos-engine-source-revision.json").read_text(encoding="utf-8"))
                self.assertEqual(self.stores.project_content_revision(project), marker["indexed_revision"])
                self.assertEqual((True, str((project / "graphify-out").resolve())), self.stores.graph_freshness(project))

                # Second refresh when graphify-out already exists (backup rename path).
                rev2 = self.stores.store_revision(project)
                self.stores._refresh_graphify(
                    project, snapshot=project, scratch=project / ".scratch", revision=rev2, invoke=invoke
                )
                marker2 = json.loads((project / "graphify-out" / ".chaos-engine-source-revision.json").read_text(encoding="utf-8"))
                self.assertEqual(self.stores.project_content_revision(project), marker2["indexed_revision"])
                self.assertFalse((project / "graphify-out.replacing").exists())
                self.assertFalse((project / ".graphify-out.replacing").exists())
                self.assertTrue(self.stores.graph_freshness(project)[0])

                # Failed write_marker restores prior graphify-out from backup.
                (project / "graphify-out" / "sentinel.txt").write_text("keep-me\n", encoding="utf-8")
                with mock.patch.object(self.stores, "write_marker", side_effect=RuntimeError("boom")):
                    with self.assertRaises(RuntimeError):
                        self.stores._refresh_graphify(
                            project, snapshot=project, scratch=project / ".scratch", revision=rev2, invoke=invoke
                        )
                self.assertEqual("keep-me\n", (project / "graphify-out" / "sentinel.txt").read_text(encoding="utf-8"))

    def test_d6_memory_command_resolves_in_clean_shell_with_user_bin_on_path(self):
        if os.name == "nt":
            self.skipTest("POSIX clean-PATH shell check")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            user_dir = root / "user-data"
            fake_memory = root / "tool" / "memory-bin"
            fake_memory.parent.mkdir(parents=True)
            fake_memory.write_text("#!/bin/sh\necho memory-ok:$*\n", encoding="utf-8")
            fake_memory.chmod(0o755)

            with mock.patch.dict(
                os.environ,
                {"CHAOS_ENGINE_USER_DIR": str(user_dir), "CHAOS_ENGINE_USER_PATHS": "1"},
            ):
                self.deps.publish_user_tool_paths({"memory": str(fake_memory)})

            bindir = user_dir / "bin"
            self.assertTrue((bindir / "memory").exists())
            completed = subprocess.run(
                ["memory", "--help"],
                env={"PATH": str(bindir)},
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertIn("memory-ok:--help", completed.stdout)

    def test_d7_empty_mempalace_reports_empty_not_healthy_even_without_index_record(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            palace = project / ".chaos-engine-state" / "mempalace"
            palace.mkdir(parents=True)
            conn = sqlite3.connect(palace / "sqlite_exact.sqlite3")
            conn.execute("create table documents (id integer primary key, body text)")
            conn.commit()
            conn.close()

            stores = {
                "palace_drawer_count": self.stores.palace_drawer_count,
                "resolve_palace": lambda _p: palace,
            }
            with mock.patch.object(self.install, "_load_stores_module", return_value=stores):
                finding = self.install._mempalace_empty_finding(project, None)
                running = self.install._mempalace_empty_finding(project, {"status": "running"})
            self.assertIsNotNone(finding)
            self.assertEqual("empty", finding["status"])
            self.assertIn("0 drawers", str(finding["detail"]))
            self.assertIsNone(running)

            doc = {
                "status": "healthy",
                "commit": "a" * 40,
                "components": {
                    "core": {"status": "healthy", "taskImpact": "required"},
                    "mempalace": {
                        "status": finding["status"],
                        "taskImpact": "advisory",
                        "detail": finding["detail"],
                        "fixNext": finding["fixNext"],
                    },
                },
            }
            report = self.install.format_health_report(doc)
            self.assertIn("1/2 healthy", report)
            self.assertIn("[warning] mempalace — empty", report)


if __name__ == "__main__":
    unittest.main()
