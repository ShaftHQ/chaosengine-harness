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
            self.assertIn("a healthy doctor does not mean hooks ran", str(components["hooks"]["detail"]))
            self.assertIn("blocking: unverifiable", str(components["hooks"]["detail"]))

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

        required_degraded = {"status": "degraded", "taskImpact": "required"}
        self.assertTrue(self.install.component_escalates_overall(required_degraded))
        self.assertFalse(
            self.install.component_escalates_overall(
                {"status": "degraded", "taskImpact": "advisory"}
            )
        )
        required_doc = {
            "status": "healthy",
            "commit": "b" * 40,
            "components": {
                "core": {"status": "healthy", "taskImpact": "required"},
                "tools": required_degraded,
            },
            "hosts": {"status": "healthy"},
        }
        self.assertEqual(1, self.install.doctor_exit_code(required_doc))
        required_rendered = self.install.format_health_report(required_doc)
        self.assertNotIn("ChaosEngine doctor: healthy", required_rendered)
        self.assertIn("ChaosEngine doctor: recovery-required", required_rendered)

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

    def test_f3_memory_shim_repeat_calls_do_not_point_at_themselves(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real = root / "tool" / "memory-bin"
            real.parent.mkdir(parents=True)
            real.write_text("#!/bin/sh\necho memory-ok\n", encoding="utf-8")
            real.chmod(0o755)
            posix_bin = root / "posix-bin"
            self.deps._write_memory_shim(posix_bin, real)
            link = posix_bin / "memory"
            self.assertTrue(link.is_symlink())
            self.deps._write_memory_shim(posix_bin, link)
            self.assertTrue(link.is_symlink())
            self.assertEqual(real.resolve(), link.resolve())

            windows_bin = root / "windows-bin"
            with mock.patch.object(self.deps.os, "name", "nt"):
                self.deps._write_memory_shim(windows_bin, real)
                first = (windows_bin / "memory.cmd").read_text(encoding="utf-8")
                self.assertIn(str(real.resolve()), first)
                self.deps._write_memory_shim(windows_bin, windows_bin / "memory.cmd")
                second = (windows_bin / "memory.cmd").read_text(encoding="utf-8")
            self.assertEqual(first, second)
            self.assertNotIn("memory.cmd", second)
            self.assertIn(str(real.resolve()), second)

    def test_f3_javascript_symlink_is_wrapped_with_node_not_linked_to_bin(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / "pkg" / "memory.js"
            script.parent.mkdir(parents=True)
            script.write_text("console.log('memory-ok')\n", encoding="utf-8")
            bin_link = root / "node_modules" / ".bin" / "memory"
            bin_link.parent.mkdir(parents=True)
            bin_link.symlink_to(script)
            node = root / "node"
            node.write_text("#!/bin/sh\necho node\n", encoding="utf-8")
            bindir = root / "bin"
            self.deps._write_memory_shim(bindir, bin_link, node=node)
            self.deps._write_memory_shim(bindir, bin_link, node=node)
            shim = bindir / "memory"
            self.assertFalse(shim.is_symlink())
            body = shim.read_text(encoding="utf-8")
            self.assertIn(f'exec "{node}" "{script.resolve()}"', body)
            self.assertNotIn(str(bin_link), body)
            cmd = (bindir / "memory.cmd").read_text(encoding="utf-8")
            self.assertIn(str(script.resolve()), cmd)
            self.assertNotIn(str(bin_link), cmd)

    def test_f6_openbot_doctor_skips_failed_or_unbound_grok_host_environment(self):
        unbound = {
            "status": "failed",
            "code": "CE_GROK_PROJECT_UNBOUND",
            "detail": "Grok has no projectRoot for this directory",
        }
        failed = {
            "status": "failed",
            "code": "CE_GROK_INSPECT_FAILED",
            "detail": "Grok CLI probe failed",
        }
        untrusted = {
            "status": "sync-advisory",
            "detail": "projectTrusted is false; run `/hooks-trust`",
        }

        def record(project: Path, probe: dict, targets: tuple[str, ...], controller=None):
            result = {"hosts": {"status": "healthy"}}
            host = self.hosts if controller is None else controller
            with mock.patch.dict(
                os.environ,
                {"OPENBOT_HOME": "", "OPENBOT_SESSION_ID": "", "CHAOS_ENGINE_HOST": ""},
            ), mock.patch.object(host, "grok_runtime_status", return_value=probe):
                self.install._record_grok_doctor_probe(result, project, host, targets)
            return result

        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            skill = project / ".chaos-engine/skills/chaos-engine/SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("# ChaosEngine\n", encoding="utf-8")

            for probe in (unbound, failed):
                recorded = record(project, probe, ())
                self.assertEqual(probe["code"], recorded["hosts"]["grok"]["code"])
                self.assertEqual("failed", recorded["hosts"]["openbotHookHealth"]["status"])
                self.assertEqual("grok-hooks-probe", recorded["hosts"]["hostEnvironment"]["detail"])
                self.assertNotIn("/hooks-trust", json.dumps(recorded))

            both = record(project, failed, ("openbot", "grok"))
            self.assertEqual("grok-hooks-probe", both["hosts"]["hostEnvironment"]["detail"])
            self.assertNotIn("openbotHookHealth", both["hosts"])

            trusted_false = record(project, untrusted, ())
            self.assertIn("/hooks-trust", trusted_false["hosts"]["hostEnvironment"]["fixNext"])
            self.assertNotIn("openbotHookHealth", trusted_false["hosts"])

            openbot_only = record(project, failed, ("openbot",))
            self.assertEqual("failed", openbot_only["hosts"]["openbotHookHealth"]["status"])
            self.assertIn("hostEnvironment", openbot_only["hosts"])

            loaded = {
                "status": "failed",
                "code": "CE_GROK_PROJECT_UNBOUND",
                "hooksLoaded": True,
                "detail": "A ChaosEngine PreToolUse hook is loaded.",
            }
            loaded_openbot = record(project, loaded, ("openbot",))
            self.assertNotIn("hostEnvironment", loaded_openbot["hosts"])
            self.assertNotIn("openbotHookHealth", loaded_openbot["hosts"])

            empty_hooks = {
                "status": "sync-advisory",
                "hooks": [],
                "detail": "Grok project is trusted. Loaded hooks are missing.",
            }
            empty_openbot = record(project, empty_hooks, ("openbot",))
            self.assertEqual("CE_GROK_HOOKS_EMPTY", empty_openbot["hosts"]["openbotHookHealth"]["code"])
            self.assertIn("hostEnvironment", empty_openbot["hosts"])
            self.assertNotIn("/hooks-trust", json.dumps(empty_openbot))

            bare = type("BareController", (), {})()
            bare.grok_runtime_status = lambda _project: failed
            bare_result = {"hosts": {"status": "healthy"}}
            self.install._record_grok_doctor_probe(bare_result, project, bare, ())
            self.assertEqual("grok-hooks-probe", bare_result["hosts"]["hostEnvironment"]["detail"])
            self.assertNotIn("/hooks-trust", str(bare_result["hosts"]["hostEnvironment"]["fixNext"]))

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

    def test_openbot_empty_hooks_fail_the_hook_row(self):
        components = {
            "hooks": {
                "status": "sync-advisory",
                "taskImpact": "advisory",
                "detail": "instruction-only",
            }
        }
        result = {
            "status": "healthy",
            "hosts": {
                "status": "healthy",
                "openbotHookHealth": {
                    "status": "failed",
                    "code": "CE_GROK_HOOKS_EMPTY",
                    "detail": "hooks []",
                },
            },
            "components": components,
        }
        self.install._apply_openbot_grok_hook_denial(result, components)
        self.assertEqual("degraded", components["hooks"]["status"])
        self.assertEqual("required", components["hooks"]["taskImpact"])
        self.assertEqual("CE_GROK_HOOKS_EMPTY", components["hooks"]["code"])
        self.assertIn("not a healthy hook result", str(components["hooks"]["detail"]))
        self.install.reconcile_doctor_overall_status(result)
        self.assertEqual("recovery-required", result["status"])

    def test_openbot_doctor_warns_above_instruction_cap(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            target = project / ".chaos-engine"
            (target / "hooks").mkdir(parents=True)
            for name in ("guard.py", "kernel.py", "launch.js", "launch.py", "lifecycle.py", "reflection.py"):
                (target / "hooks" / name).write_text("# hook\n", encoding="utf-8")
            (project / "AGENTS.md").write_text("x" * 32001, encoding="utf-8")
            self.install.record_completion_targets(project, ("openbot",))
            components = {"hooks": {"status": "healthy", "taskImpact": "required"}}
            self.install._apply_completion_hook_health(
                project, target, components, host_controller=self.hosts
            )
            self.install._stamp_openbot_instruction_cap(project, components)
            warning = str(components["hooks"]["instructionCapWarning"])
            self.assertIn("32000", warning)
            self.assertIn("32001", warning)
            report = self.install.format_health_report(
                {"status": "healthy", "commit": "c" * 40, "components": components}
            )
            self.assertIn("[warning] hooks/openbot —", report)
            self.assertIn("32000", report)

            (project / "AGENTS.md").unlink()
            (project / "CLAUDE.md").write_text("y" * 32000, encoding="utf-8")
            capped = {"hooks": {"status": "healthy", "taskImpact": "required"}}
            self.install._apply_completion_hook_health(
                project, target, capped, host_controller=self.hosts
            )
            self.install._stamp_openbot_instruction_cap(project, capped)
            self.assertNotIn("instructionCapWarning", capped["hooks"])

    def test_grok_router_skill_pointer_uses_discovered_path(self):
        relative = self.hosts.GROK_ROUTER_SKILL
        self.assertEqual(".grok/skills/chaos-engine/SKILL.md", relative)
        paths = self.hosts.managed_paths()
        self.assertIn(relative, paths)
        self.assertIn(".claude/skills/chaos-engine/SKILL.md", paths)
        self.assertIn(".agents/skills/chaos-engine/SKILL.md", paths)
        before = {item: None for item in paths}
        rendered = self.hosts.desired_content(before, maven_runtime=None)
        body = rendered[relative].decode("utf-8")
        self.assertIn("skills/chaos-engine/SKILL.md", body)
        self.assertNotIn("measure thrice", body.casefold())
        self.assertLess(len(body), 2000)
        self.assertIn(".claude/skills/chaos-engine/SKILL.md", rendered)
        self.assertNotIn("openbot/hooks.json", rendered)

        def result(payload):
            return subprocess.CompletedProcess([], 0, json.dumps(payload), "")

        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            state = self.hosts.grok_runtime_status(
                project,
                executable="grok",
                runner=lambda *_a, **_k: result({"projectTrusted": True, "projectRoot": str(project), "hooks": []}),
            )
            self.assertEqual([], state["hooks"])
            self.assertIs(False, state["hooksLoaded"])
            self.assertNotIn("/hooks-trust", str(state["detail"]))


if __name__ == "__main__":
    unittest.main()
