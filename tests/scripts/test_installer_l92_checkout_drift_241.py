"""Issue #241: L92 stale harness checkout drift and rollback plugin reconciliation."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]


def _load_install():
    spec = importlib.util.spec_from_file_location("ce_install_241", ROOT / "install.py")
    module = importlib.util.module_from_spec(spec)
    if spec.loader is None:
        raise RuntimeError("install.py has no loader")
    spec.loader.exec_module(module)
    return module


INSTALL = _load_install()


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.email=test@example.com",
            "-c",
            "user.name=Test User",
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _init_harness_repo(root: Path, version: str) -> str:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    (root / "install.py").write_text("# stub\n", encoding="utf-8")
    skill = root / "skills" / "chaos-engine"
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text("# skill\n", encoding="utf-8")
    (root / "VERSION").write_text(f"{version}\n", encoding="utf-8")
    _git(root, "add", "install.py", "skills/chaos-engine/SKILL.md", "VERSION")
    _git(root, "commit", "-q", "-m", f"release {version}")
    return _git(root, "rev-parse", "HEAD")


def _write_overlay(project: Path, version: str, commit: str | None) -> Path:
    overlay = project / ".chaos-engine"
    overlay.mkdir(parents=True, exist_ok=True)
    (overlay / "VERSION").write_text(f"{version}\n", encoding="utf-8")
    if commit is not None:
        manifest = {"source": {"commit": commit, "kind": "local"}}
        (overlay / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return overlay


class _AccountDependencyController:
    def __init__(self, delegate):
        self._delegate = delegate

    def __getattr__(self, name):
        return getattr(self._delegate, name)

    def install_account_dependencies(self, project: Path, _specification, **_kwargs):
        receipt = {
            "schemaVersion": 2,
            "scope": "user",
            "components": {},
            "commands": {
                "memory-mcp": sys.executable,
                "mempalace-mcp": sys.executable,
                "node": sys.executable,
                "python3": sys.executable,
            },
        }
        (Path(project) / ".chaos-engine-dependencies.json").write_text(
            json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
        )
        return receipt


class InstallerL92CheckoutDrift241Test(unittest.TestCase):
    def test_stale_harness_checkout_with_fetched_newer_commit_is_healthy_advisory(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "harness"
            commit_a = _init_harness_repo(project, "0.4.20261115.5")
            _git(project, "checkout", "-q", "-b", "newer")
            (project / "VERSION").write_text("1.20261126.0\n", encoding="utf-8")
            _git(project, "add", "VERSION")
            _git(project, "commit", "-q", "-m", "bump to 1.20261126.0")
            commit_b = _git(project, "rev-parse", "HEAD")
            # Return working tree to older branch commit A while overlay is at commit B.
            _git(project, "checkout", "-q", commit_a)
            overlay = _write_overlay(project, "1.20261126.0", commit_b)

            finding = INSTALL._ce_version_after_upgrade_finding(project, overlay)
            components: dict[str, object] = {"core": {"status": "healthy"}}
            INSTALL._attach_l84_l92_doctor_findings(project, overlay, components)

        self.assertIsNotNone(finding)
        self.assertEqual("healthy", finding["status"])
        self.assertTrue(finding.get("checkoutDrift"))
        self.assertEqual("1.20261126.0", finding["installedVersion"])
        self.assertEqual("0.4.20261115.5", finding["intendedVersion"])
        self.assertIn(commit_b[:12], str(finding["detail"]))
        self.assertIn(commit_a[:12], str(finding["detail"]))
        self.assertIn("git checkout main && git pull --ff-only", str(finding["detail"]))
        self.assertEqual("healthy", components["core"]["status"])
        self.assertIn(commit_b[:12], str(components["core"].get("detail", "")))

    def test_stale_harness_checkout_with_unfetched_newer_commit_is_healthy_advisory(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "harness"
            commit_a = _init_harness_repo(project, "0.4.20261115.5")
            remote_commit = "b" * 40
            overlay = _write_overlay(project, "1.20261126.0", remote_commit)

            finding = INSTALL._ce_version_after_upgrade_finding(project, overlay)

        self.assertIsNotNone(finding)
        self.assertEqual("healthy", finding["status"])
        self.assertTrue(finding.get("checkoutDrift"))
        self.assertIn(remote_commit[:12], str(finding["detail"]))
        self.assertIn(commit_a[:12], str(finding["detail"]))
        self.assertIn("git checkout main && git pull --ff-only", str(finding["detail"]))

    def test_stale_overlay_on_newer_checkout_still_fails_closed_l92(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "harness"
            commit_a = _init_harness_repo(project, "0.4.20261115.5")
            (project / "VERSION").write_text("1.20261126.0\n", encoding="utf-8")
            _git(project, "add", "VERSION")
            _git(project, "commit", "-q", "-m", "bump to 1.20261126.0")
            # HEAD is now on newer commit B, while overlay stayed on older commit A.
            overlay = _write_overlay(project, "0.4.20261115.5", commit_a)
            finding_fetched = INSTALL._ce_version_after_upgrade_finding(project, overlay)

            # Also verify an unfetched commit with an older VERSION fails closed.
            _write_overlay(project, "0.4.20261115.5", "c" * 40)
            finding_unfetched = INSTALL._ce_version_after_upgrade_finding(project, overlay)

        for finding in (finding_fetched, finding_unfetched):
            self.assertIsNotNone(finding)
            self.assertEqual("invalid", finding["status"])
            self.assertIn("(L92)", str(finding["detail"]))

    def test_same_commit_version_mismatch_still_fails_closed_l92(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "harness"
            commit_a = _init_harness_repo(project, "0.4.20261115.5")
            overlay = _write_overlay(project, "1.20261126.0", commit_a)

            finding = INSTALL._ce_version_after_upgrade_finding(project, overlay)

        self.assertIsNotNone(finding)
        self.assertEqual("invalid", finding["status"])
        self.assertIn("(L92)", str(finding["detail"]))

    def test_non_git_project_mismatch_still_fails_closed_l92(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "plain-harness"
            project.mkdir()
            (project / "install.py").write_text("# stub\n", encoding="utf-8")
            (project / "skills" / "chaos-engine").mkdir(parents=True)
            (project / "skills" / "chaos-engine" / "SKILL.md").write_text("# s\n", encoding="utf-8")
            (project / "VERSION").write_text("0.4.20261115.5\n", encoding="utf-8")
            overlay = _write_overlay(project, "1.20261126.0", "b" * 40)

            finding = INSTALL._ce_version_after_upgrade_finding(project, overlay)

        self.assertIsNotNone(finding)
        self.assertEqual("invalid", finding["status"])
        self.assertIn("(L92)", str(finding["detail"]))

    def test_fetched_commit_with_tampered_overlay_version_fails_closed_l92(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "harness"
            commit_a = _init_harness_repo(project, "0.4.20261115.5")
            _git(project, "checkout", "-q", "-b", "mid")
            (project / "VERSION").write_text("0.4.20261116.0\n", encoding="utf-8")
            _git(project, "add", "VERSION")
            _git(project, "commit", "-q", "-m", "mid")
            commit_mid = _git(project, "rev-parse", "HEAD")
            _git(project, "checkout", "-q", commit_a)
            # Overlay claims 1.20261126.0 even though commit_mid:VERSION is 0.4.20261116.0.
            overlay = _write_overlay(project, "1.20261126.0", commit_mid)

            finding = INSTALL._ce_version_after_upgrade_finding(project, overlay)

        self.assertIsNotNone(finding)
        self.assertEqual("invalid", finding["status"])
        self.assertIn("(L92)", str(finding["detail"]))

    def test_unparseable_overlay_version_fails_closed_l92(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "harness"
            _init_harness_repo(project, "0.4.20261115.5")
            overlay = _write_overlay(project, "not-a-semver", "b" * 40)

            finding = INSTALL._ce_version_after_upgrade_finding(project, overlay)

        self.assertIsNotNone(finding)
        self.assertEqual("invalid", finding["status"])
        self.assertIn("(L92)", str(finding["detail"]))

    def test_unicode_superscript_version_fails_closed_l92(self):
        self.assertIsNone(INSTALL._parse_numeric_version_tuple("1.\u00b2.0"))
        self.assertIsNone(INSTALL._parse_numeric_version_tuple("1.\u0662.0"))
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "harness"
            _init_harness_repo(project, "0.4.20261115.5")
            overlay = _write_overlay(project, "1.\u00b2.0", "b" * 40)

            finding = INSTALL._ce_version_after_upgrade_finding(project, overlay)

        self.assertIsNotNone(finding)
        self.assertEqual("invalid", finding["status"])
        self.assertIn("(L92)", str(finding["detail"]))


class RollbackPluginReconciliation241Test(unittest.TestCase):
    def _setup_upgraded_account_project(self, project: Path) -> bytes:
        real_dep_loader = INSTALL.load_dependency_controller

        def load_account_dep(installed_root):
            return _AccountDependencyController(real_dep_loader(installed_root))

        with mock.patch.object(
            INSTALL, "load_dependency_controller", side_effect=load_account_dep
        ), mock.patch.object(INSTALL.shutil, "which", return_value=None):
            INSTALL.install_with_dependencies(
                project, ROOT, "1" * 40, with_maven_tools=False
            )
            base_hosts = INSTALL.load_installed_controller(project / ".chaos-engine", "hosts")
            _base_receipt, base_raw = base_hosts.read_receipt(project)
            INSTALL.install_with_dependencies(
                project, ROOT, "2" * 40, with_maven_tools=False
            )
        return base_raw

    def test_account_rollback_reconciles_stale_client_plugins(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "consumer"
            project.mkdir()
            self._setup_upgraded_account_project(project)

            real_dep_loader = INSTALL.load_dependency_controller
            real_ctrl_loader = INSTALL.load_installed_controller
            activations: list[tuple[str, Path]] = []

            def load_account_dep(installed_root):
                return _AccountDependencyController(real_dep_loader(installed_root))

            def load_ctrl(installed_root, name):
                controller = real_ctrl_loader(installed_root, name)
                if name == "hosts":
                    commit = json.loads(
                        (Path(installed_root) / "manifest.json").read_text(encoding="utf-8")
                    )["source"]["commit"]
                    controller.detected_plugin_status = mock.Mock(
                        return_value={
                            "claude": {
                                "status": "absent",
                                "marketplace": "healthy",
                                "plugin": "stale",
                                "plugins": {"chaos-engine": "stale"},
                            }
                        }
                    )

                    def _activate(proj):
                        activations.append((commit, Path(proj)))
                        return {"clients": {"claude": {"status": "healthy"}}}

                    controller.activate_detected_plugins = mock.Mock(side_effect=_activate)
                return controller

            with mock.patch.object(
                INSTALL, "load_dependency_controller", side_effect=load_account_dep
            ), mock.patch.object(
                INSTALL, "load_installed_controller", side_effect=load_ctrl
            ):
                restored = INSTALL.rollback(project)

            self.assertEqual((project / ".chaos-engine").resolve(), restored.resolve())
            self.assertEqual("1" * 40, INSTALL.status(project)["commit"])
            self.assertEqual([("1" * 40, project.resolve())], activations)

    def test_account_rollback_skips_activation_when_plugins_are_absent_and_preserves_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "consumer"
            project.mkdir()
            base_raw = self._setup_upgraded_account_project(project)

            real_dep_loader = INSTALL.load_dependency_controller
            real_ctrl_loader = INSTALL.load_installed_controller
            activations: list[mock.Mock] = []

            def load_account_dep(installed_root):
                return _AccountDependencyController(real_dep_loader(installed_root))

            def load_ctrl(installed_root, name):
                controller = real_ctrl_loader(installed_root, name)
                if name == "hosts":
                    controller.detected_plugin_status = mock.Mock(
                        return_value={
                            "claude": {
                                "status": "absent",
                                "marketplace": "absent",
                                "plugin": "absent",
                                "plugins": {"chaos-engine": "absent"},
                            }
                        }
                    )
                    activate_mock = mock.Mock(return_value={})
                    controller.activate_detected_plugins = activate_mock
                    activations.append(activate_mock)
                return controller

            with mock.patch.object(
                INSTALL, "load_dependency_controller", side_effect=load_account_dep
            ), mock.patch.object(
                INSTALL, "load_installed_controller", side_effect=load_ctrl
            ):
                INSTALL.rollback(project)

            self.assertEqual(0, sum(m.call_count for m in activations))
            restored_hosts = INSTALL.load_installed_controller(project / ".chaos-engine", "hosts")
            _restored_receipt, restored_raw = restored_hosts.read_receipt(project)
            self.assertEqual(base_raw, restored_raw)

    def test_account_rollback_survives_plugin_reconciliation_errors(self):
        for failure_mode in ("activate", "detect"):
            with self.subTest(failure_mode=failure_mode):
                with tempfile.TemporaryDirectory() as temporary:
                    project = Path(temporary) / "consumer"
                    project.mkdir()
                    self._setup_upgraded_account_project(project)

                    real_dep_loader = INSTALL.load_dependency_controller
                    real_ctrl_loader = INSTALL.load_installed_controller

                    def load_account_dep(installed_root):
                        return _AccountDependencyController(real_dep_loader(installed_root))

                    def load_ctrl(installed_root, name):
                        controller = real_ctrl_loader(installed_root, name)
                        if name == "hosts":
                            if failure_mode == "detect":
                                controller.detected_plugin_status = mock.Mock(
                                    side_effect=OSError("probe failed")
                                )
                            else:
                                controller.detected_plugin_status = mock.Mock(
                                    return_value={"claude": {"plugin": "stale"}}
                                )
                                controller.activate_detected_plugins = mock.Mock(
                                    side_effect=RuntimeError("claude cli failed")
                                )
                        return controller

                    with mock.patch.object(
                        INSTALL, "load_dependency_controller", side_effect=load_account_dep
                    ), mock.patch.object(
                        INSTALL, "load_installed_controller", side_effect=load_ctrl
                    ):
                        restored = INSTALL.rollback(project)

                    self.assertEqual((project / ".chaos-engine").resolve(), restored.resolve())
                    self.assertEqual("1" * 40, INSTALL.status(project)["commit"])


if __name__ == "__main__":
    unittest.main()
