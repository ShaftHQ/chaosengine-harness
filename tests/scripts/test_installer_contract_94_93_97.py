"""Installer contract: fail closed, one freshness stamp, managed npm, CI matrix.

Issues 94, 93, and 97. These tests load their own module objects so they do not
share the offline repair patch on chaos_engine_installer.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
COMMIT = "a" * 40
WORKFLOW = ROOT / ".github/workflows" / "installer-contract.yml"
UPSTREAM = ROOT / ".github" / "workflows" / "upstream-watch.yml"
WINDOWS = ROOT / ".github" / "workflows" / "install-windows.yml"
CELL = ROOT / "scripts" / "ci" / "installer_contract_cell.py"
CI_SKILL = ROOT / "skills" / "ci-cd" / "SKILL.md"
ARCHITECT = ROOT / "skills" / "architect" / "SKILL.md"
RECEIPT = ROOT / "references" / "research-receipt.md"
CHANGELOG = ROOT / "CHANGELOG.md"

DOC_URLS = (
    "https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax.md",
    "https://docs.github.com/en/actions/reference/security/secure-use.md",
    "https://docs.github.com/en/actions/tutorials/store-and-share-data.md",
    "https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/run-job-variations.md",
    "https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/find-and-customize-actions.md",
)
ISSUE_97 = (
    ("non-maven", "fresh"),
    ("non-maven", "upgrade"),
    ("maven-not-shaft", "fresh"),
    ("maven-not-shaft", "upgrade"),
)
MUST_RUN = (
    ("windows-latest", "upgrade", "consumer-shaft"),
    ("windows-latest", "fresh", "empty"),
    ("windows-latest", "fresh", "shaft-dev"),
    ("ubuntu-latest", "upgrade", "shaft-dev"),
)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _installer():
    return _load("chaos_engine_installer_contract_949397", ROOT / "install.py")


def _stores():
    return _load("chaos_engine_stores_contract_949397", ROOT / "runtime" / "stores.py")


def _dependencies():
    return _load("chaos_engine_dependencies_contract_949397", ROOT / "runtime" / "dependencies.py")


def _doctor(blocked: tuple[str, ...] = ()) -> dict:
    components = {
        key: {"status": "healthy"}
        for key in ("hosts", "policy-overlay", "graphify", "mempalace")
    }
    for name in blocked:
        components[name] = {"status": "recovery-required"}
    return {
        "status": "recovery-required" if blocked else "healthy",
        "hosts": {"status": "recovery-required" if "hosts" in blocked else "healthy"},
        "components": components,
    }


class EmitContractTest(unittest.TestCase):
    def test_verify_needs_repair_is_one_line_and_not_ok(self):
        installer = _installer()
        args = SimpleNamespace(command="verify")
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = installer._emit_result(
                args,
                {"status": "needs-repair", "drifted": [], "failure": "needs-repair"},
            )
        self.assertEqual(1, code)
        self.assertEqual("needs-repair\n", stdout.getvalue())
        self.assertNotIn("verify: ok", stdout.getvalue())

    def test_install_needs_repair_is_one_line(self):
        installer = _installer()
        args = SimpleNamespace(command="install", json=False)
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = installer._emit_result(
                args, {"status": "needs-repair", "failure": "needs-repair"}
            )
        self.assertEqual(1, code)
        self.assertEqual("needs-repair\n", stdout.getvalue())
        self.assertNotIn("verify: ok", stdout.getvalue())


class UpgradeRebindTest(unittest.TestCase):
    def _upgrade(self, installer, project: Path, **patches):
        args = SimpleNamespace(project=project, source=None, commit=COMMIT)
        stack = [
            mock.patch.object(installer, "_guided_pin", return_value=(ROOT, COMMIT)),
            mock.patch.object(
                installer, "_publish_guided_overlay", return_value=project / ".chaos-engine"
            ),
            mock.patch.object(installer, "_strip_retired_mcp"),
        ]
        for item in stack:
            item.start()
            self.addCleanup(item.stop)
        for name, value in patches.items():
            active = mock.patch.object(installer, name, value)
            active.start()
            self.addCleanup(active.stop)
        return installer._run_guided_upgrade(args)

    def test_host_drift_rebinds_and_stays_needs_repair_when_still_broken(self):
        installer = _installer()
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            repair = mock.Mock(return_value={"status": "repaired"})
            result = self._upgrade(
                installer,
                project,
                upgrade_host_receipt_drift_needed=mock.Mock(return_value=True),
                repair_component=repair,
                _repair_policy_overlay=mock.Mock(),
                _doctor_result=mock.Mock(return_value=_doctor(("hosts",))),
            )
        repair.assert_called()
        self.assertEqual("hosts", repair.call_args.args[1])
        self.assertEqual("needs-repair", result.get("status"))
        self.assertNotEqual("installed", result.get("status"))

    def test_policy_drift_rebinds_then_installs_when_healthy(self):
        installer = _installer()
        state = {"blocked": ("policy-overlay",)}

        def doctor(_project):
            return _doctor(state["blocked"])

        def policy(_project, _runner):
            state["blocked"] = ()
            return {"status": "repaired", "component": "policy-overlay"}

        policy_mock = mock.Mock(side_effect=policy)
        with tempfile.TemporaryDirectory() as temporary:
            result = self._upgrade(
                installer,
                Path(temporary),
                upgrade_host_receipt_drift_needed=mock.Mock(return_value=False),
                repair_component=mock.Mock(),
                _repair_policy_overlay=policy_mock,
                _doctor_result=mock.Mock(side_effect=doctor),
            )
        policy_mock.assert_called()
        self.assertEqual("installed", result.get("status"))


class EscalatingDoctorContractTest(unittest.TestCase):
    """Escalating doctor rows fail install, upgrade, and verify closed."""

    def _document(self, installer, status: str) -> dict:
        components = {
            key: {"status": "healthy", "taskImpact": "required"}
            for key in ("hosts", "policy-overlay", "graphify", "mempalace")
        }
        components["mempalace"] = {"status": status, "taskImpact": "required"}
        document = {
            "status": "healthy",
            "hosts": {"status": "healthy", "taskImpact": "required"},
            "components": components,
        }
        installer.reconcile_doctor_overall_status(document)
        return document

    def _emit(self, installer, argv: list[str], patches: dict):
        args, extra = installer.parser().parse_known_args(argv)
        started = []
        for name, value in patches.items():
            active = mock.patch.object(installer, name, value)
            active.start()
            started.append(active)
        stdout = io.StringIO()
        try:
            with redirect_stdout(stdout):
                result = installer._command_result(args, extra)
                code = installer._emit_result(args, result)
        finally:
            for active in reversed(started):
                active.stop()
        return code, stdout.getvalue(), result

    def _install_argv(self, project: Path) -> list[str]:
        return [
            "install",
            "--project",
            str(project),
            "--source",
            str(ROOT),
            "--commit",
            COMMIT,
            "--skip-tools",
        ]

    def _install_patches(self, project: Path, doctor) -> dict:
        return {
            "install": mock.Mock(return_value=project / ".chaos-engine"),
            "post_install_housekeeping": mock.Mock(),
            "_doctor_result": doctor,
        }

    def test_invalid_mempalace_fails_install_upgrade_and_verify(self):
        installer = _installer()
        document = self._document(installer, "invalid")
        self.assertEqual("recovery-required", document["status"])
        doctor = mock.Mock(return_value=document)
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            installed = self._emit(
                installer,
                self._install_argv(project),
                self._install_patches(project, doctor),
            )
            upgraded = self._emit(
                installer,
                ["upgrade", "--project", str(project), "--source", str(ROOT), "--commit", COMMIT],
                {
                    "_publish_guided_overlay": mock.Mock(return_value=project / ".chaos-engine"),
                    "_strip_retired_mcp": mock.Mock(),
                    "_doctor_result": doctor,
                },
            )
            overlay = project / ".chaos-engine"
            overlay.mkdir()
            (overlay / "manifest.json").write_text(
                json.dumps({"files": {}}),
                encoding="utf-8",
            )
            verified = self._emit(
                installer,
                ["verify", "--project", str(project)],
                {"_doctor_result": doctor},
            )
        for code, stdout, _result in (installed, upgraded, verified):
            self.assertEqual(1, code)
            self.assertEqual("needs-repair\n", stdout)

    def test_migration_required_mempalace_fails_install(self):
        installer = _installer()
        document = self._document(installer, "migration-required")
        self.assertEqual("recovery-required", document["status"])
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            code, stdout, _result = self._emit(
                installer,
                self._install_argv(project),
                self._install_patches(project, mock.Mock(return_value=document)),
            )
        self.assertEqual(1, code)
        self.assertEqual("needs-repair\n", stdout)

    def test_doctor_exception_does_not_fail_a_completed_install(self):
        installer = _installer()
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            code, stdout, result = self._emit(
                installer,
                self._install_argv(project),
                self._install_patches(
                    project, mock.Mock(side_effect=OSError("doctor unavailable"))
                ),
            )
        self.assertEqual(0, code)
        self.assertEqual("installed", result.get("status"))
        self.assertNotIn("needs-repair", stdout)

    def test_degraded_mempalace_stays_installed(self):
        installer = _installer()
        document = self._document(installer, "degraded")
        self.assertEqual("healthy", document["status"])
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            code, stdout, result = self._emit(
                installer,
                self._install_argv(project),
                self._install_patches(project, mock.Mock(return_value=document)),
            )
        self.assertEqual(0, code)
        self.assertEqual("installed", result.get("status"))
        self.assertNotIn("needs-repair", stdout)

    def test_needs_repair_names_each_escalating_row_on_stderr(self):
        installer = _installer()
        components = {
            "hosts": {
                "status": "recovery-required",
                "taskImpact": "required",
                "detail": "host receipt drifted",
            },
            "policy-overlay": {"status": "healthy", "taskImpact": "required"},
            "graphify": {"status": "recovery-required"},
            "mempalace": {
                "status": "recovery-required",
                "taskImpact": "advisory",
                "detail": "palace sqlite missing",
            },
        }
        document = {
            "status": "recovery-required",
            "hosts": {"status": "healthy", "taskImpact": "required"},
            "components": components,
        }
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            with mock.patch.object(installer, "_doctor_result", return_value=document):
                result = installer._annotate_install_contract(
                    project, {"status": "installed", "root": str(project)}
                )
        self.assertEqual(["hosts", "graphify", "mempalace"], result["components"])
        self.assertTrue(all(isinstance(name, str) for name in result["components"]))
        self.assertEqual(
            ["hosts", "graphify", "mempalace"],
            [row["name"] for row in result["escalatingRows"]],
        )
        self.assertEqual("host receipt drifted", result["escalatingRows"][0]["detail"])
        self.assertEqual("advisory", result["escalatingRows"][2]["taskImpact"])
        args = SimpleNamespace(command="install", json=False)
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = installer._emit_result(args, result)
        self.assertEqual(1, code)
        self.assertEqual("needs-repair\n", stdout.getvalue())
        self.assertEqual(
            "needs-repair: hosts (recovery-required, impact=required): host receipt drifted\n"
            "needs-repair: graphify (recovery-required, impact=unknown): \n"
            "needs-repair: mempalace (recovery-required, impact=advisory): palace sqlite missing\n",
            stderr.getvalue(),
        )
        upgrade_args = SimpleNamespace(command="upgrade", json=False)
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            upgrade_code = installer._emit_result(upgrade_args, result)
        self.assertEqual(1, upgrade_code)
        self.assertEqual("needs-repair\n", stdout.getvalue())
        self.assertIn("needs-repair: mempalace (recovery-required, impact=advisory): palace sqlite missing", stderr.getvalue())

    def test_doctor_errors_keep_install_and_upgrade_installed(self):
        installer = _installer()
        for error in (ValueError("doctor unavailable"), OSError("doctor unavailable")):
            with tempfile.TemporaryDirectory() as temporary:
                project = Path(temporary)
                with mock.patch.object(installer, "_doctor_result", side_effect=error):
                    installed = installer._annotate_install_contract(
                        project, {"status": "installed", "root": str(project)}
                    )
                    upgraded = self._upgrade_without_rebind(installer, project)
            self.assertEqual("installed", installed.get("status"))
            self.assertNotIn("escalatingRows", installed)
            # Install and upgrade stay installed when doctor raises. Needs-repair
            # is only a non-empty escalating name list, and stderr has no rows.
            self.assertEqual("installed", upgraded.get("status"))
            self.assertNotIn("escalatingRows", upgraded)
            self.assertNotEqual("needs-repair", upgraded.get("failure"))
            for command, payload in (("install", installed), ("upgrade", upgraded)):
                stdout, stderr = io.StringIO(), io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = installer._emit_result(
                        SimpleNamespace(command=command, json=False), payload
                    )
                self.assertEqual(0, code, command)
                self.assertNotIn("needs-repair", stdout.getvalue())
                self.assertNotIn("needs-repair", stderr.getvalue())

    def _upgrade_without_rebind(self, installer, project: Path):
        args = SimpleNamespace(project=project, source=None, commit=COMMIT)
        with (
            mock.patch.object(installer, "_guided_pin", return_value=(ROOT, COMMIT)),
            mock.patch.object(
                installer, "_publish_guided_overlay", return_value=project / ".chaos-engine"
            ),
            mock.patch.object(installer, "_strip_retired_mcp"),
            mock.patch.object(installer, "_apply_install_config"),
            mock.patch.object(installer, "_instruction_replace", return_value=None),
            mock.patch.object(installer, "_bundle_flags_set", return_value=False),
            mock.patch.object(installer, "_rebind_contract_drift"),
        ):
            return installer._run_guided_upgrade(args)


class VersionPinTest(unittest.TestCase):
    def test_overlay_version_uses_source_pin_and_keeps_commit(self):
        installer = _installer()
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            overlay = project / ".chaos-engine"
            overlay.mkdir()
            (overlay / "VERSION").write_text("0.0.0\n", encoding="utf-8")
            source = project / "chaos-engine"
            source.mkdir()
            (source / "VERSION").write_text("0.4.20261115.5\n", encoding="utf-8")
            manifest = {"source": {"commit": COMMIT, "kind": "local"}}
            (overlay / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            finding = installer._ce_version_after_upgrade_finding(project, overlay)
            saved = json.loads((overlay / "manifest.json").read_text(encoding="utf-8"))
        self.assertIsNotNone(finding)
        self.assertEqual("invalid", finding["status"])
        self.assertEqual(COMMIT, saved["source"]["commit"])
        self.assertNotEqual("0.0.0", saved["source"]["commit"])

    def test_pack_version_difference_is_an_exception_when_core_matches(self):
        installer = _installer()
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            overlay = project / ".chaos-engine"
            overlay.mkdir()
            (overlay / "VERSION").write_text("0.4.20261115.5\n", encoding="utf-8")
            source = project / "chaos-engine"
            pack = source / "packs" / "demo"
            pack.mkdir(parents=True)
            (source / "VERSION").write_text("0.4.20261115.5\n", encoding="utf-8")
            (pack / "VERSION").write_text("9.9.9\n", encoding="utf-8")
            finding = installer._ce_version_after_upgrade_finding(project, overlay)
        self.assertEqual("healthy", finding["status"])
        self.assertIn("pack exception", finding["detail"])

    def test_consumer_project_version_is_not_the_source_pin(self):
        installer = _installer()
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            overlay = project / ".chaos-engine"
            overlay.mkdir()
            (overlay / "VERSION").write_text("0.0.0\n", encoding="utf-8")
            (project / "VERSION").write_text("9.9.9\n", encoding="utf-8")
            finding = installer._ce_version_after_upgrade_finding(project, overlay)
        self.assertIsNone(finding)


class FreshnessContractTest(unittest.TestCase):
    def test_graphify_refresh_stamp_matches_the_post_write_fingerprint(self):
        stores = _stores()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "keep.txt").write_text("before\n", encoding="utf-8")
            self.assertFalse(stores.is_git_work_tree(root))

            def runner(command, cwd):
                out = Path(command[command.index("--out") + 1])
                produced = out / "graphify-out"
                produced.mkdir(parents=True, exist_ok=True)
                (produced / "graph.json").write_text("{}\n", encoding="utf-8")
                (produced / "manifest.json").write_text("{}\n", encoding="utf-8")
                (Path(cwd) / "side-effect.txt").write_text("after\n", encoding="utf-8")
                return 0

            real_which = stores.shutil.which

            def which(command, *args, **kwargs):
                if command == "graphify":
                    return "graphify"
                return real_which(command, *args, **kwargs)

            with mock.patch.object(stores.shutil, "which", side_effect=which):
                code = stores.refresh(root, components=frozenset({"graphify"}), runner=runner)
            self.assertEqual(0, code)
            marker = json.loads(
                (root / "graphify-out" / ".chaos-engine-source-revision.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(stores.project_content_revision(root), marker["indexed_revision"])
            first, _detail = stores.graph_freshness(root)
            second, _again = stores.graph_freshness(root)
        self.assertTrue(first)
        self.assertTrue(second)

    def test_mempalace_non_git_marker_stays_current(self):
        stores = _stores()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "note.md").write_text("hello\n", encoding="utf-8")
            self.assertFalse(stores.is_git_work_tree(root))
            palace = stores.resolve_palace(root)
            palace.mkdir(parents=True)
            connection = sqlite3.connect(palace / "sqlite_exact.sqlite3")
            connection.execute("create table documents (id integer)")
            connection.execute("insert into documents values (1)")
            connection.commit()
            connection.close()
            stores.write_palace_marker(palace, stores.project_content_revision(root))
            self.assertTrue(stores._component_current(root, "mempalace"))
            self.assertTrue(stores._component_current(root, "mempalace"))

    def test_stale_fingerprint_fails_the_freshness_check(self):
        stores = _stores()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "keep.txt").write_text("a\n", encoding="utf-8")
            graph = root / "graphify-out"
            graph.mkdir()
            (graph / "graph.json").write_text("{}\n", encoding="utf-8")
            (graph / "manifest.json").write_text("{}\n", encoding="utf-8")
            stores.write_marker(graph, "ab" * 20)
            fresh, _message = stores.graph_freshness(root)
        self.assertFalse(fresh)

    def test_smoke_commands_query_instead_of_help_only(self):
        stores = _stores()
        commands = stores.store_smoke_commands()
        self.assertEqual(["query", "chaos-engine"], commands["graphify"])
        self.assertEqual(["search", "chaos-engine"], commands["mempalace"])
        self.assertNotIn("--help", commands["graphify"])
        self.assertNotIn("--help", commands["mempalace"])


class ManagedNpmTest(unittest.TestCase):
    def test_broken_managed_npm_cmd_names_that_path(self):
        dependencies = _dependencies()
        with tempfile.TemporaryDirectory() as temporary:
            node_root = Path(temporary)
            node_exe = node_root / "node.exe"
            npm = node_root / "npm.cmd"
            npx = node_root / "npx.cmd"
            node_exe.write_text("node\n", encoding="utf-8")
            npm.write_text("@echo broken\n", encoding="utf-8")
            npx.write_text("@echo npx\n", encoding="utf-8")

            def runner(argv, **_kwargs):
                text = " ".join(str(part) for part in argv)
                if "npm.cmd" in text:
                    return subprocess.CompletedProcess(argv, 1, "", "broken")
                return subprocess.CompletedProcess(argv, 0, "v22.0.0\n", "")

            def discover(_specification, preferred_commands=None, which=None, runner=None):
                system = r"C:\Program Files\nodejs\npm.cmd"
                local = {
                    "uv": {"healthy": True},
                    "python": {"healthy": True},
                    "java": {"healthy": True},
                    "node": {"healthy": True},
                }
                return local, {"npm": system, "npx": system, "node": system}

            with mock.patch.object(
                dependencies, "install_exact_node", return_value=str(node_exe)
            ), mock.patch.object(
                dependencies, "discover_account_commands", side_effect=discover
            ):
                with self.assertRaises(RuntimeError) as caught:
                    dependencies._reprobe_managed_account_runtimes(
                        Path(temporary),
                        {"dependencies": {"node": {"probe": ["node", "--version"]}}},
                        {"node": {"resolvedVersion": "22.0.0"}},
                        {},
                        {"node": {"healthy": False}},
                        {
                            "python": "reused",
                            "java": "reused",
                            "node": "installed",
                            "uv": "reused",
                        },
                        "windows",
                        runner=runner,
                        opener=None,
                    )
        message = str(caught.exception)
        self.assertIn(str(npm), message)
        self.assertIn("fix-next", message)
        self.assertNotIn("Program Files", message)


class StdinAndTimeoutTest(unittest.TestCase):
    def test_account_command_closes_stdin(self):
        dependencies = _dependencies()
        seen: dict = {}

        def runner(argv, **kwargs):
            seen.update(kwargs)
            return subprocess.CompletedProcess(argv, 0, "ok\n", "")

        with tempfile.TemporaryDirectory() as temporary:
            dependencies._run_account_command(
                [sys.executable, "-c", "print(1)"],
                Path(temporary),
                runner=runner,
            )
        self.assertIs(subprocess.DEVNULL, seen.get("stdin"))

    def test_wall_clock_stops_a_busy_extract(self):
        stores = _stores()
        script = (
            "import time\n"
            "end = time.monotonic() + 5\n"
            "while time.monotonic() < end:\n"
            "    pass\n"
        )
        with self.assertRaises(subprocess.TimeoutExpired):
            stores.run_until_stalled(
                [sys.executable, "-c", script],
                stall_seconds=30,
                wall_clock_seconds=0.4,
                capture_output=True,
                text=True,
            )

    def test_extract_runner_closes_stdin_and_sets_a_wall_clock(self):
        stores = _stores()
        seen: dict = {}

        def spy(args, **kwargs):
            seen.update(kwargs)
            return subprocess.CompletedProcess(args, 0, "", "")

        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch.object(stores, "run_until_stalled", side_effect=spy):
                stores._run(subprocess.run, ["graphify", "extract", "."], Path(temporary))
        self.assertIs(subprocess.DEVNULL, seen.get("stdin"))
        self.assertGreater(float(seen.get("wall_clock_seconds") or 0), 0)


class WorkflowContractTest(unittest.TestCase):
    def test_matrix_matches_the_sixteen_job_table(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        rows = re.findall(
            r"- os: (?P<os>\S+)\n\s+mode: (?P<mode>\S+)\n\s+context: (?P<context>\S+)\n"
            r"\s+framework: (?P<framework>\S+)\n\s+timeout: (?P<timeout>\d+)",
            text,
        )
        self.assertEqual(16, len(rows))
        self.assertLess(len(rows), 30)
        pairs = {(context, mode) for _os, mode, context, _framework, _timeout in rows}
        for pair in ISSUE_97:
            self.assertIn(pair, pairs)
        triples = {
            (os_name, mode, context)
            for os_name, mode, context, _framework, _timeout in rows
        }
        for triple in MUST_RUN:
            self.assertIn(triple, triples)
        self.assertIn("fail-fast: false", text)
        self.assertIn("contents: read", text)
        self.assertNotIn("contents: write", text)
        self.assertIn(
            "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1",
            text,
        )
        self.assertNotIn("actions/checkout@v4", text)
        self.assertIn('python-version: "3.11"', text)
        self.assertNotIn("CHAOS_ENGINE_SKIP_TOOLS", text)
        self.assertIn("installer-contract-${{ github.workflow }}-${{ github.ref }}", text)
        self.assertIn("cancel-in-progress: true", text)
        self.assertNotIn("installer-contract-${{ github.run_id }}", text)
        self.assertIn("if: always()", text)
        self.assertIn("installer_contract_cell.py", text)
        self.assertIn("< /dev/null", text)
        self.assertIn("--config-source", text)
        self.assertIn("--instructions-mode", text)
        factors = re.findall(
            r"- os: (?P<os>\S+)\n\s+mode: (?P<mode>\S+)\n\s+context: (?P<context>\S+)\n"
            r"(?:.*\n)*?\s+config_source: (?P<config>\S+)\n\s+scope: (?P<scope>\S+)\n"
            r"\s+instructions_mode: (?P<instructions>\S+)\n\s+pre_existing: (?P<pre>\S+)",
            text,
        )
        self.assertEqual(16, len(factors))
        assigned = {(row[0], row[1], row[2]): row[3:] for row in factors}
        self.assertEqual(
            ("none", "user", "merge", "rich"),
            assigned[("windows-latest", "fresh", "empty")],
        )
        self.assertEqual(
            ("project", "both", "replace", "rich"),
            assigned[("windows-latest", "upgrade", "consumer-shaft")],
        )
        self.assertEqual(
            ("none", "project", "merge", "none"),
            assigned[("ubuntu-latest", "fresh", "non-maven")],
        )

    def test_upstream_watch_stays_one_compare_job(self):
        text = UPSTREAM.read_text(encoding="utf-8")
        self.assertNotIn("strategy:", text)
        self.assertEqual(1, text.count("runs-on:"))

    def test_install_windows_fast_job_stays(self):
        text = WINDOWS.read_text(encoding="utf-8")
        self.assertIn("CHAOS_ENGINE_SKIP_TOOLS", text)
        self.assertIn('python-version: "3.11"', text)
        self.assertIn("actions/checkout@v4", text)

    def test_cell_script_covers_doctor_smoke_sentinel_and_timeouts(self):
        text = CELL.read_text(encoding="utf-8")
        self.assertIn("0.4.20261115.5", text)
        self.assertIn("DEVNULL", text)
        self.assertIn("uninstall", text)
        self.assertIn("sentinel", text)
        self.assertIn("query", text)
        self.assertIn("search", text)
        self.assertIn("timeout", text)
        self.assertIn("ignore_cleanup_errors=True", text)
        self.assertIn("Failed to fetch", text)
        self.assertIn("retrying once after a failed fetch", text)
        self.assertIn("rate limit exceeded", text)
        self.assertIn("_TRANSIENT_DELAYS_SECONDS = (60, 120)", text)
        self.assertIn("contract_http", text)
        probe = (ROOT / "scripts" / "ci" / "contract_http" / "sitecustomize.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("Authorization", probe)
        self.assertIn("github.com", probe)
        self.assertIn("v3.3.1", probe)
        self.assertIn("/repos/arvindand/maven-tools-mcp/releases/latest", probe)
        self.assertNotIn("ghs_", probe)

    def _cell(self):
        spec = importlib.util.spec_from_file_location("installer_contract_cell", CELL)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module

    def test_json_factor_skips_the_pinned_installer_and_checks_this_checkout(self):
        cell = self._cell()
        calls: list[list[str]] = []

        def run(argv, **_kwargs):
            calls.append(list(argv))
            return subprocess.CompletedProcess(argv, 0, '{"status":"installed"}\n', "")

        source = Path("/tmp/ce-contract-source")
        project = Path("/tmp/ce-contract-project")
        with mock.patch.object(cell, "_run", side_effect=run):
            cell._install(source, "a" * 40, project, 30, "json", assert_output=False)
            cell._install(source, "b" * 40, project, 30, "json")
            cell._upgrade(source, "c" * 40, project, 30, "json")
        self.assertNotIn("--json", calls[0])
        self.assertIn("install", calls[0])
        self.assertIn("--json", calls[1])
        self.assertIn("upgrade", calls[2])
        self.assertNotIn("--json", calls[2])

        def dirty(argv, **_kwargs):
            return subprocess.CompletedProcess(argv, 0, "[INFO] BUILD SUCCESS\n", "")

        with mock.patch.object(cell, "_run", side_effect=dirty):
            with self.assertRaises(SystemExit) as caught:
                cell._upgrade(source, "d" * 40, project, 30, "json")
        self.assertIn("json stdout is not one document", str(caught.exception))

    def test_upgrade_replace_recaptures_bytes_after_the_pinned_install(self):
        cell = self._cell()
        text = CELL.read_text(encoding="utf-8")
        recapture = text.index("_recapture_saved(project, saved)")
        self.assertLess(recapture, text.index("_upgrade(", recapture))
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / "AGENTS.md").write_bytes(b"User rule\nmerged\n")
            current = cell._recapture_saved(project, {"AGENTS.md": b"User rule\n"})
            self.assertEqual(b"User rule\nmerged\n", current["AGENTS.md"])
            missing = cell._recapture_saved(project, {"gone.md": b"keep\n"})
            self.assertEqual(b"keep\n", missing["gone.md"])

    def test_a_failed_fetch_is_retried_once(self):
        cell = self._cell()
        calls = {"n": 0}

        def run(argv, **_kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return subprocess.CompletedProcess(
                    argv, 1, "", "wget: Failed to fetch https://example.invalid/maven.zip\n"
                )
            return subprocess.CompletedProcess(argv, 0, "ok\n", "")

        slept: list[int] = []
        with (
            mock.patch.object(cell.subprocess, "run", side_effect=run),
            mock.patch.object(cell.time, "sleep", side_effect=slept.append),
        ):
            completed = cell._run(["install"], cwd=CELL.parent, timeout=5)
        self.assertEqual(0, completed.returncode)
        self.assertEqual(2, calls["n"])
        self.assertEqual([60], slept)

    def test_a_rate_limit_waits_then_retries_twice(self):
        cell = self._cell()
        calls = {"n": 0}
        slept: list[int] = []

        def run(argv, **_kwargs):
            calls["n"] += 1
            if calls["n"] < 3:
                return subprocess.CompletedProcess(
                    argv, 1, "", "HTTP Error 403: rate limit exceeded\n"
                )
            return subprocess.CompletedProcess(argv, 0, "ok\n", "")

        with (
            mock.patch.object(cell.subprocess, "run", side_effect=run),
            mock.patch.object(cell.time, "sleep", side_effect=slept.append),
        ):
            completed = cell._run(["install"], cwd=CELL.parent, timeout=5)
        self.assertEqual(0, completed.returncode)
        self.assertEqual(3, calls["n"])
        self.assertEqual([60, 120], slept)

    def test_a_product_failure_is_not_retried(self):
        cell = self._cell()
        calls = {"n": 0}

        def run(argv, **_kwargs):
            calls["n"] += 1
            return subprocess.CompletedProcess(argv, 1, "", "ChaosEngine install: Blocked\n")

        with mock.patch.object(cell.subprocess, "run", side_effect=run):
            with self.assertRaises(SystemExit) as raised:
                cell._run(["install"], cwd=CELL.parent, timeout=5)
        self.assertEqual(1, raised.exception.code)
        self.assertEqual(1, calls["n"])

    def test_github_download_uses_the_token_and_the_log_drops_the_query(self):
        probe = ROOT / "scripts" / "ci" / "contract_http"
        env = os.environ.copy()
        env["PYTHONPATH"] = str(probe)
        env["GITHUB_TOKEN"] = "synthetic-contract-token"
        script = """
import urllib.error
import urllib.request
import sitecustomize

def fake(url, *args, **kwargs):
    print(url.get_header("Authorization") or "NONE")
    raise urllib.error.HTTPError(url.full_url, 403, "rate limit exceeded", None, None)

sitecustomize._original = fake
try:
    urllib.request.urlopen(
        "https://github.com/example/releases/download/v/a.zip?sig=secret", timeout=1
    )
except urllib.error.HTTPError:
    pass
"""
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("Bearer synthetic-contract-token", completed.stdout)
        self.assertIn("https://github.com/example/releases/download/v/a.zip", completed.stderr)
        self.assertNotIn("sig=secret", completed.stderr)
        self.assertNotIn("synthetic-contract-token", completed.stderr)

    def test_a_rate_limited_maven_tools_release_uses_the_published_tag(self):
        probe = ROOT / "scripts" / "ci" / "contract_http"
        env = os.environ.copy()
        env["PYTHONPATH"] = str(probe)
        script = """
import json
import urllib.error
import urllib.request
import sitecustomize

def fake(url, *args, **kwargs):
    raise urllib.error.HTTPError(url.full_url, 403, "rate limit exceeded", None, None)

sitecustomize._original = fake
with urllib.request.urlopen(
    "https://api.github.com/repos/arvindand/maven-tools-mcp/releases/latest", timeout=1
) as response:
    payload = json.loads(response.read().decode("utf-8"))
print(payload["tag_name"])
"""
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("v3.3.1", completed.stdout)
        self.assertIn("using tag v3.3.1", completed.stderr)


class SkillContractTest(unittest.TestCase):
    def test_ci_skill_names_the_checked_action_docs(self):
        text = CI_SKILL.read_text(encoding="utf-8")
        for url in DOC_URLS:
            self.assertIn(url, text)
        self.assertIn("github.run_id", text)

    def test_architect_points_at_bigger_picture_before_a_nontrivial_change(self):
        text = ARCHITECT.read_text(encoding="utf-8")
        self.assertIn("bigger-picture-first.md", text)
        self.assertNotIn("PreToolUse", text)

    def test_research_receipt_requires_the_official_manual_url(self):
        text = RECEIPT.read_text(encoding="utf-8")
        self.assertIn("official manual", text)

    def test_changelog_unreleased_records_the_contract(self):
        text = CHANGELOG.read_text(encoding="utf-8")
        unreleased = text.split("## [0.4", 1)[0]
        self.assertIn("needs-repair", unreleased)
        self.assertIn("installer-contract.yml", unreleased)


if __name__ == "__main__":
    unittest.main()
