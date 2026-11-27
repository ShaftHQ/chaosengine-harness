"""Issue #253: automatic commit-date version calculation on startup."""

from __future__ import annotations

import argparse
import importlib.util
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BOOTSTRAP = _load("ce_bootstrap_253", ROOT / "bootstrap.py")
INSTALL = _load("ce_install_253", ROOT / "install.py")
CE_VERSION = _load("ce_version_253", ROOT / "scripts/ci/ce_version.py")

STALE_VERSION = "1.20261120.0"
EXPECTED_DAY = "1.20261126"
NEXT_DAY = "1.20261127"


def _git(repo: Path, *args: str, when: str | None = None) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Test User",
        "GIT_AUTHOR_EMAIL": "test@example.invalid",
        "GIT_COMMITTER_NAME": "Test User",
        "GIT_COMMITTER_EMAIL": "test@example.invalid",
    }
    if when is not None:
        env["GIT_AUTHOR_DATE"] = when
        env["GIT_COMMITTER_DATE"] = when
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return completed.stdout.strip()


def _commit(repo: Path, when: str, label: str) -> str:
    (repo / "revision").write_text(label + "\n", encoding="utf-8")
    _git(repo, "add", "revision")
    _git(repo, "commit", "-qm", label, when=when)
    return _git(repo, "rev-parse", "HEAD")


def _repository(root: Path, version: str = STALE_VERSION) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q", "-b", "main")
    (root / "VERSION").write_text(f"{version}\n", encoding="utf-8")
    _commit(root, "2026-11-26T01:00:00Z", "first")
    return root


def _commit_document(
    sha: str,
    stamp: str,
    *,
    author_stamp: str | None = None,
    parents: list[str] | None = None,
) -> dict[str, object]:
    doc: dict[str, object] = {
        "sha": sha,
        "commit": {
            "committer": {"date": stamp},
            "author": {"date": author_stamp or stamp},
        },
    }
    if parents is not None:
        doc["parents"] = [{"sha": parent} for parent in parents]
    return doc


def _api_fetcher(commit: dict[str, object], commits: list[dict[str, object]]):
    calls: list[str] = []

    def fetch(request, timeout=None):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        calls.append(url)
        if "/commits?" in url:
            payload = commits
        else:
            payload = commit
        raw = json.dumps(payload).encode("utf-8")

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self, _limit=None):
                return raw

        return Response()

    return fetch, calls


def _minimal_source(root: Path) -> Path:
    source = root / "chaos-engine"
    source.mkdir(parents=True)
    for name in ("install.py", "VERSION", "distributions.json", "dependencies.json"):
        shutil.copy2(ROOT / name, source / name)
    for name in ("profiles/portable", "runtime", "hooks", "skills/chaos-engine"):
        shutil.copytree(
            ROOT / name,
            source / name,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
    return source


class LocalCommitVersion253Test(unittest.TestCase):
    def test_first_commit_of_day_wins_over_stale_static_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = _repository(Path(temporary) / "harness")
            self.assertEqual(EXPECTED_DAY + ".0", BOOTSTRAP.derive_commit_version(repo))
            self.assertEqual(EXPECTED_DAY + ".0", BOOTSTRAP.product_version(repo))
            self.assertEqual(EXPECTED_DAY + ".0", INSTALL.source_version(repo))
            self.assertEqual(EXPECTED_DAY + ".0", CE_VERSION.derive_commit_version(repo))
            self.assertEqual(STALE_VERSION, (repo / "VERSION").read_text(encoding="utf-8").strip())

    def test_second_and_third_commit_increment_and_next_day_resets(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = _repository(Path(temporary) / "harness")
            _commit(repo, "2026-11-26T02:00:00Z", "second")
            self.assertEqual(EXPECTED_DAY + ".1", BOOTSTRAP.derive_commit_version(repo))
            self.assertEqual(EXPECTED_DAY + ".1", BOOTSTRAP.product_version(repo))
            _commit(repo, "2026-11-26T23:59:59Z", "third")
            self.assertEqual(EXPECTED_DAY + ".2", BOOTSTRAP.product_version(repo))
            self.assertEqual(EXPECTED_DAY + ".2", INSTALL.source_version(repo))
            _commit(repo, "2026-11-27T00:00:01Z", "tomorrow")
            self.assertEqual(NEXT_DAY + ".0", BOOTSTRAP.product_version(repo))
            self.assertEqual(NEXT_DAY + ".0", INSTALL.source_version(repo))

    def test_shallow_checkout_falls_back_to_static_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = _repository(Path(temporary) / "origin")
            _commit(base, "2026-11-26T02:00:00Z", "second")
            clone = Path(temporary) / "shallow"
            _git(
                base,
                "clone",
                "-q",
                "--depth",
                "1",
                f"file://{base}",
                str(clone),
            )
            self.assertEqual("true", _git(clone, "rev-parse", "--is-shallow-repository"))
            (clone / "VERSION").write_text(STALE_VERSION + "\n", encoding="utf-8")
            self.assertEqual(STALE_VERSION, BOOTSTRAP.product_version(clone))
            self.assertEqual(STALE_VERSION, INSTALL.source_version(clone))
            with self.assertRaises(ValueError):
                CE_VERSION.derive_commit_version(clone)


class RemoteCommitVersion253Test(unittest.TestCase):
    def test_remote_derivation_counts_same_day_commits_newest_first_with_parents(self):
        sha = "a" * 40
        parent1 = "b" * 40
        parent0 = "c" * 40
        side_branch = "9" * 40
        prev_day = "8" * 40
        # Real GitHub /commits?sha=<sha> returns newest-first with target sha at index 0.
        commit = _commit_document(
            sha,
            "2026-11-26T03:00:00Z",
            author_stamp="2026-11-25T20:00:00Z",
            parents=[parent1, side_branch],
        )
        commits = [
            commit,
            _commit_document(side_branch, "2026-11-26T02:30:00Z", parents=[parent0]),
            _commit_document(parent1, "2026-11-26T02:00:00Z", parents=[parent0]),
            _commit_document(parent0, "2026-11-26T01:00:00Z", parents=[prev_day]),
            _commit_document(prev_day, "2026-11-25T23:59:59Z", parents=[]),
        ]
        fetcher, calls = _api_fetcher(commit, commits)
        self.assertEqual(
            "1.20261126.2",
            BOOTSTRAP.derive_remote_commit_version("ShaftHQ/chaosengine-harness", sha, fetcher=fetcher),
        )
        self.assertTrue(any("since=2026-11-26T00:00:00Z" in call for call in calls))
        self.assertTrue(any("until=2026-11-26T03:00:00Z" in call for call in calls))
        self.assertTrue(any("per_page=100" in call for call in calls))

    def test_remote_derivation_first_commit_of_day(self):
        sha = "d" * 40
        commit = _commit_document(sha, "2026-11-26T01:00:00Z")
        fetcher, _calls = _api_fetcher(commit, [commit])
        self.assertEqual(
            "1.20261126.0",
            BOOTSTRAP.derive_remote_commit_version("ShaftHQ/chaosengine-harness", sha, fetcher=fetcher),
        )

    def test_remote_derivation_network_error_is_graceful(self):
        def broken(_request, timeout=None):
            raise OSError("offline")

        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(
                BOOTSTRAP.derive_remote_commit_version(
                    "ShaftHQ/chaosengine-harness", "e" * 40, fetcher=broken
                )
            )
            with tempfile.TemporaryDirectory() as temporary:
                repo = _repository(Path(temporary) / "harness")
                self.assertEqual(EXPECTED_DAY + ".0", BOOTSTRAP.product_version(repo))
                empty = Path(temporary) / "lone-bootstrap"
                empty.mkdir()
                self.assertEqual(BOOTSTRAP._EMBEDDED_VERSION, BOOTSTRAP.product_version(empty))

    def test_invalid_override_is_ignored(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = _repository(Path(temporary) / "harness")
            with mock.patch.dict(
                os.environ,
                {"CHAOS_ENGINE_DERIVED_VERSION": "not-a-version"},
                clear=True,
            ):
                self.assertEqual(EXPECTED_DAY + ".0", BOOTSTRAP.product_version(repo))
                self.assertEqual(EXPECTED_DAY + ".0", INSTALL.source_version(repo))

    def test_receipt_carries_derived_version_only_when_supplied(self):
        kwargs = {
            "commit": "f" * 40,
            "doctor_status": "healthy",
            "healthy": 1,
            "total": 1,
            "clients": {},
            "trace": "trace.json",
        }
        plain = BOOTSTRAP.install_receipt_document(**kwargs)
        self.assertNotIn("version", plain)
        derived = BOOTSTRAP.install_receipt_document(**kwargs, version="1.20261126.2")
        self.assertEqual("1.20261126.2", derived["version"])


class InstallerDerivedVersion253Test(unittest.TestCase):
    def test_local_checkout_install_writes_derived_version_and_passes_l92(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "consumer"
            project.mkdir()
            source = _minimal_source(root / "source")
            (source / "VERSION").write_text(STALE_VERSION + "\n", encoding="utf-8")
            _git(source, "init", "-q", "-b", "main")
            first = _commit(source, "2026-11-26T01:00:00Z", "first")
            second = _commit(source, "2026-11-26T02:00:00Z", "second")
            third = _commit(source, "2026-11-26T03:00:00Z", "third")
            expected = "1.20261126.2"
            self.assertEqual(expected, INSTALL.source_version(source))

            (project / "install.py").write_text("# checkout stub\n", encoding="utf-8")
            skill = project / "skills" / "chaos-engine"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("# checkout stub\n", encoding="utf-8")
            (project / "VERSION").write_text(STALE_VERSION + "\n", encoding="utf-8")
            _git(project, "init", "-q", "-b", "main")
            _git(project, "add", "install.py", "skills/chaos-engine/SKILL.md", "VERSION")
            _git(project, "commit", "-qm", "checkout first", when="2026-11-26T01:00:00Z")
            (project / "f").write_text("2\n", encoding="utf-8")
            _git(project, "add", "f")
            _git(project, "commit", "-qm", "checkout second", when="2026-11-26T02:00:00Z")
            (project / "f").write_text("3\n", encoding="utf-8")
            _git(project, "add", "f")
            _git(project, "commit", "-qm", "checkout third", when="2026-11-26T03:00:00Z")

            overlay = INSTALL.install(project, source, third)
            self.assertEqual((source / "VERSION").read_bytes(), (overlay / "VERSION").read_bytes())
            manifest = json.loads((overlay / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(third, manifest["source"]["commit"])
            self.assertEqual(expected, manifest["source"]["version"])
            self.assertEqual(
                INSTALL.file_sha256(source / "VERSION"), manifest["files"]["VERSION"]
            )
            self.assertEqual(third, INSTALL.verify_install(overlay)["source"]["commit"])

            finding = INSTALL._ce_version_after_upgrade_finding(project, overlay)
            self.assertIsNotNone(finding)
            self.assertEqual("healthy", finding["status"])
            self.assertEqual(expected, finding["installedVersion"])
            self.assertEqual(expected, finding["intendedVersion"])
            self.assertNotIn("(L92)", str(finding["detail"]))
            self.assertNotEqual(first, second)


class ManifestPayloadInvariant253Test(unittest.TestCase):
    def test_install_keeps_payload_bytes_and_records_version_in_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "consumer"
            project.mkdir()
            source = _minimal_source(root / "source")
            _git(source, "init", "-q", "-b", "main")
            first = _commit(source, "2026-11-26T01:00:00Z", "first")
            second = _commit(source, "2026-11-26T02:00:00Z", "second")
            expected = "1.20261126.1"
            with mock.patch.dict(
                os.environ, {"CHAOS_ENGINE_DERIVED_VERSION": ""}, clear=False
            ):
                overlay = INSTALL.install(project, source, second)
            manifest = json.loads((overlay / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(expected, INSTALL.resolved_source_version(source))
            self.assertEqual(expected, manifest["source"]["version"])
            self.assertEqual((source / "VERSION").read_bytes(), (overlay / "VERSION").read_bytes())
            self.assertEqual(
                INSTALL.file_sha256(source / "VERSION"), manifest["files"]["VERSION"]
            )
            self.assertEqual(INSTALL.verify_install(overlay)["source"]["version"], expected)

            before = {
                path.relative_to(overlay): path.read_bytes()
                for path in overlay.rglob("*")
                if path.is_file()
            }
            with mock.patch.dict(
                os.environ, {"CHAOS_ENGINE_DERIVED_VERSION": ""}, clear=False
            ):
                INSTALL.install(project, source, second)
            after = {
                path.relative_to(overlay): path.read_bytes()
                for path in overlay.rglob("*")
                if path.is_file()
            }
            self.assertEqual(before, after)
            self.assertFalse((project / ".chaos-engine.backup").exists())
            self.assertNotEqual(first, second)

    def test_legacy_static_pin_is_never_replaced_by_commit_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "consumer"
            project.mkdir()
            source = _minimal_source(root / "source")
            legacy = "0.4.20261115.5"
            (source / "VERSION").write_text(legacy + "\n", encoding="utf-8")
            _git(source, "init", "-q", "-b", "main")
            _commit(source, "2026-11-26T01:00:00Z", "first")
            _commit(source, "2026-11-26T02:00:00Z", "second")

            (project / "install.py").write_text("# checkout stub\n", encoding="utf-8")
            skill = project / "skills" / "chaos-engine"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("# checkout stub\n", encoding="utf-8")
            (project / "VERSION").write_text(legacy + "\n", encoding="utf-8")
            _git(project, "init", "-q", "-b", "main")
            _git(project, "add", "install.py", "skills/chaos-engine/SKILL.md", "VERSION")
            _git(project, "commit", "-qm", "checkout", when="2026-11-26T01:00:00Z")
            head = _git(project, "rev-parse", "HEAD")

            with mock.patch.dict(
                os.environ, {"CHAOS_ENGINE_DERIVED_VERSION": ""}, clear=False
            ):
                self.assertEqual(legacy, INSTALL.resolved_source_version(source))
                self.assertEqual(legacy, INSTALL.source_intended_version(source))
                overlay = INSTALL.install(project, source, head)
                manifest = json.loads((overlay / "manifest.json").read_text(encoding="utf-8"))
                self.assertEqual(legacy, manifest["source"]["version"])
                finding = INSTALL._ce_version_after_upgrade_finding(project, overlay)
            self.assertEqual((source / "VERSION").read_bytes(), (overlay / "VERSION").read_bytes())
            self.assertEqual("healthy", finding["status"])
            self.assertEqual(legacy, finding["installedVersion"])
            self.assertEqual(legacy, finding["intendedVersion"])


class StaleCheckoutDerivedVersion253Test(unittest.TestCase):
    def _checkout(self, root: Path, first_version: str, second_version: str) -> tuple[Path, str, str]:
        project = root / "harness"
        project.mkdir(parents=True)
        (project / "install.py").write_text("# checkout stub\n", encoding="utf-8")
        skill = project / "skills" / "chaos-engine"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("# checkout stub\n", encoding="utf-8")
        (project / "VERSION").write_text(first_version + "\n", encoding="utf-8")
        _git(project, "init", "-q", "-b", "main")
        _git(project, "add", "install.py", "skills/chaos-engine/SKILL.md", "VERSION")
        _git(project, "commit", "-qm", "first", when="2026-11-26T01:00:00Z")
        first = _git(project, "rev-parse", "HEAD")
        (project / "VERSION").write_text(second_version + "\n", encoding="utf-8")
        _git(project, "add", "VERSION")
        _git(project, "commit", "-qm", "second", when="2026-11-26T02:00:00Z")
        second = _git(project, "rev-parse", "HEAD")
        _git(project, "checkout", "-q", first)
        return project, first, second

    def _finding(self, project: Path, commit: str, installed_version: str):
        overlay = project / ".chaos-engine"
        overlay.mkdir(parents=True, exist_ok=True)
        (overlay / "VERSION").write_text(installed_version + "\n", encoding="utf-8")
        manifest = {
            "source": {"commit": commit, "kind": "local", "version": installed_version}
        }
        (overlay / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return INSTALL._ce_version_after_upgrade_finding(project, overlay)

    def test_manifest_version_recognizes_stale_checkout_as_drift(self):
        with tempfile.TemporaryDirectory() as temporary:
            project, first, second = self._checkout(
                Path(temporary), "1.20261126.0", "1.20261126.1"
            )
            with mock.patch.dict(
                os.environ, {"CHAOS_ENGINE_DERIVED_VERSION": ""}, clear=False
            ):
                finding = self._finding(project, second, "1.20261126.1")
        self.assertEqual("healthy", finding["status"])
        self.assertTrue(finding["checkoutDrift"])
        self.assertEqual("1.20261126.1", finding["installedVersion"])
        self.assertEqual("1.20261126.0", finding["intendedVersion"])
        self.assertNotIn("(L92)", str(finding["detail"]))
        self.assertIn(second[:12], str(finding["detail"]))
        self.assertIn(first[:12], str(finding["detail"]))

    def test_empty_version_at_installed_commit_still_derives_expected(self):
        with tempfile.TemporaryDirectory() as temporary:
            project, _first, second = self._checkout(
                Path(temporary), "1.20261126.0", ""
            )
            with mock.patch.dict(
                os.environ, {"CHAOS_ENGINE_DERIVED_VERSION": ""}, clear=False
            ):
                finding = self._finding(project, second, "1.20261126.1")
        self.assertEqual("healthy", finding["status"])
        self.assertTrue(finding["checkoutDrift"])

    def test_legacy_pin_stale_checkout_is_healthy_drift(self):
        with tempfile.TemporaryDirectory() as temporary:
            project, first, second = self._checkout(
                Path(temporary), "0.4.20261115.1", "0.4.20261116.1"
            )
            with mock.patch.dict(
                os.environ, {"CHAOS_ENGINE_DERIVED_VERSION": ""}, clear=False
            ):
                finding = self._finding(project, second, "0.4.20261116.1")
        self.assertEqual("healthy", finding["status"])
        self.assertTrue(finding["checkoutDrift"])
        self.assertEqual("0.4.20261116.1", finding["installedVersion"])
        self.assertEqual("0.4.20261115.1", finding["intendedVersion"])
        self.assertIn(second[:12], str(finding["detail"]))
        self.assertIn(first[:12], str(finding["detail"]))

    def test_legacy_pin_mismatched_overlay_version_still_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            project, _first, second = self._checkout(
                Path(temporary), "0.4.20261115.1", "0.4.20261116.1"
            )
            with mock.patch.dict(
                os.environ, {"CHAOS_ENGINE_DERIVED_VERSION": ""}, clear=False
            ):
                finding = self._finding(project, second, "0.4.20261117.1")
        self.assertEqual("invalid", finding["status"])
        self.assertIn("(L92)", str(finding["detail"]))
        self.assertNotIn("checkoutDrift", finding)


class BootstrapVersionFlags253Test(unittest.TestCase):
    def test_external_override_is_not_replaced_by_startup_or_remote(self):
        with mock.patch.object(BOOTSTRAP, "_EXTERNAL_DERIVED_VERSION", None), mock.patch.object(
            BOOTSTRAP, "_DERIVED_VERSION_FROM_STARTUP", False
        ), mock.patch.object(
            BOOTSTRAP, "startup_commit_version", return_value="1.20261126.0"
        ), mock.patch.object(
            BOOTSTRAP, "derive_remote_commit_version", return_value="1.20261127.0"
        ) as derive, mock.patch.dict(
            os.environ,
            {
                "CHAOS_ENGINE_DERIVED_VERSION": "1.20261123.4",
                "CHAOS_ENGINE_OFFLINE": "",
            },
        ):
            previous = BOOTSTRAP.apply_install_flags(argparse.Namespace())
            try:
                self.assertEqual("1.20261123.4", os.environ["CHAOS_ENGINE_DERIVED_VERSION"])
                self.assertFalse(BOOTSTRAP._DERIVED_VERSION_FROM_STARTUP)
                BOOTSTRAP._resolve_remote_install_version(
                    "ShaftHQ/chaosengine-harness", "f" * 40, urllib.request.urlopen
                )
                derive.assert_not_called()
                self.assertEqual("1.20261123.4", os.environ["CHAOS_ENGINE_DERIVED_VERSION"])
            finally:
                BOOTSTRAP.restore_install_flags(previous)

    def test_startup_version_yields_to_remote_and_is_cleared_on_failure(self):
        with mock.patch.object(BOOTSTRAP, "_EXTERNAL_DERIVED_VERSION", None), mock.patch.object(
            BOOTSTRAP, "_DERIVED_VERSION_FROM_STARTUP", False
        ), mock.patch.object(
            BOOTSTRAP, "startup_commit_version", return_value="1.20261126.0"
        ), mock.patch.dict(
            os.environ,
            {"CHAOS_ENGINE_DERIVED_VERSION": "", "CHAOS_ENGINE_OFFLINE": ""},
        ):
            with mock.patch.object(
                BOOTSTRAP, "derive_remote_commit_version", return_value="1.20261127.0"
            ) as derive:
                previous = BOOTSTRAP.apply_install_flags(argparse.Namespace())
                try:
                    self.assertEqual("1.20261126.0", os.environ["CHAOS_ENGINE_DERIVED_VERSION"])
                    self.assertTrue(BOOTSTRAP._DERIVED_VERSION_FROM_STARTUP)
                    BOOTSTRAP._resolve_remote_install_version(
                        "ShaftHQ/chaosengine-harness", "a" * 40, urllib.request.urlopen
                    )
                    derive.assert_called_once_with(
                        "ShaftHQ/chaosengine-harness", "a" * 40, fetcher=urllib.request.urlopen
                    )
                    self.assertEqual("1.20261127.0", os.environ["CHAOS_ENGINE_DERIVED_VERSION"])
                finally:
                    BOOTSTRAP.restore_install_flags(previous)
            with mock.patch.object(
                BOOTSTRAP, "derive_remote_commit_version", return_value=None
            ):
                previous = BOOTSTRAP.apply_install_flags(argparse.Namespace())
                try:
                    self.assertEqual("1.20261126.0", os.environ["CHAOS_ENGINE_DERIVED_VERSION"])
                    BOOTSTRAP._resolve_remote_install_version(
                        "ShaftHQ/chaosengine-harness", "b" * 40, urllib.request.urlopen
                    )
                    self.assertNotIn("CHAOS_ENGINE_DERIVED_VERSION", os.environ)
                finally:
                    BOOTSTRAP.restore_install_flags(previous)

    def test_apply_and_restore_flags_restores_derived_version_globals(self):
        with mock.patch.object(
            BOOTSTRAP, "_EXTERNAL_DERIVED_VERSION", None
        ), mock.patch.object(
            BOOTSTRAP, "_DERIVED_VERSION_FROM_STARTUP", False
        ), mock.patch.object(
            BOOTSTRAP, "startup_commit_version", return_value="1.20261126.0"
        ), mock.patch.dict(
            os.environ,
            {"CHAOS_ENGINE_DERIVED_VERSION": "", "CHAOS_ENGINE_OFFLINE": ""},
        ):
            previous = BOOTSTRAP.apply_install_flags(argparse.Namespace())
            self.assertIsNone(BOOTSTRAP._EXTERNAL_DERIVED_VERSION)
            self.assertEqual("1.20261126.0", os.environ["CHAOS_ENGINE_DERIVED_VERSION"])
            self.assertTrue(BOOTSTRAP._DERIVED_VERSION_FROM_STARTUP)
            BOOTSTRAP.restore_install_flags(previous)
            self.assertIsNone(BOOTSTRAP._EXTERNAL_DERIVED_VERSION)
            self.assertFalse(BOOTSTRAP._DERIVED_VERSION_FROM_STARTUP)
            self.assertEqual([], BOOTSTRAP._DERIVED_VERSION_STATE_STACK)

            BOOTSTRAP._EXTERNAL_DERIVED_VERSION = "1.20261123.4"
            BOOTSTRAP._DERIVED_VERSION_FROM_STARTUP = True
            previous = BOOTSTRAP.apply_install_flags(argparse.Namespace())
            self.assertEqual("1.20261123.4", BOOTSTRAP._EXTERNAL_DERIVED_VERSION)
            self.assertFalse(BOOTSTRAP._DERIVED_VERSION_FROM_STARTUP)
            BOOTSTRAP.restore_install_flags(previous)
            self.assertEqual("1.20261123.4", BOOTSTRAP._EXTERNAL_DERIVED_VERSION)
            self.assertTrue(BOOTSTRAP._DERIVED_VERSION_FROM_STARTUP)
            self.assertEqual([], BOOTSTRAP._DERIVED_VERSION_STATE_STACK)

            BOOTSTRAP._EXTERNAL_DERIVED_VERSION = "1.20261123.4"
            BOOTSTRAP._DERIVED_VERSION_FROM_STARTUP = True
            BOOTSTRAP.restore_install_flags({})
            self.assertIsNone(BOOTSTRAP._EXTERNAL_DERIVED_VERSION)
            self.assertFalse(BOOTSTRAP._DERIVED_VERSION_FROM_STARTUP)

    def test_standalone_announce_uses_remote_version_before_the_header(self):
        with mock.patch.object(BOOTSTRAP, "_EXTERNAL_DERIVED_VERSION", None), mock.patch.object(
            BOOTSTRAP, "startup_commit_version", return_value=None
        ), mock.patch.object(
            BOOTSTRAP, "derive_remote_commit_version", return_value="1.20261127.0"
        ) as derive, mock.patch.dict(
            os.environ,
            {
                "CHAOS_ENGINE_DERIVED_VERSION": "",
                "CHAOS_ENGINE_OFFLINE": "",
                "CHAOS_ENGINE_QUIET": "",
                "NO_COLOR": "1",
            },
        ):
            BOOTSTRAP._resolve_announced_version(
                "ShaftHQ/chaosengine-harness", None, urllib.request.urlopen, argparse.Namespace()
            )
            derive.assert_called_once_with(
                "ShaftHQ/chaosengine-harness", "main", fetcher=urllib.request.urlopen
            )
            stream = io.StringIO()
            reporter = BOOTSTRAP.InstallReporter(stream=stream)
            reporter.announce(Path("/project"), "ShaftHQ/chaosengine-harness", "main")
            self.assertIn("1.20261127.0", stream.getvalue())

    def test_announce_skips_remote_lookup_offline_external_and_bundle(self):
        with mock.patch.object(BOOTSTRAP, "_EXTERNAL_DERIVED_VERSION", None), mock.patch.object(
            BOOTSTRAP, "startup_commit_version", return_value=None
        ), mock.patch.object(
            BOOTSTRAP, "derive_remote_commit_version", return_value="1.20261127.0"
        ) as derive, mock.patch.dict(
            os.environ,
            {"CHAOS_ENGINE_DERIVED_VERSION": "", "CHAOS_ENGINE_OFFLINE": "1"},
        ):
            BOOTSTRAP._resolve_announced_version(
                "ShaftHQ/chaosengine-harness", "main", urllib.request.urlopen, argparse.Namespace()
            )
            derive.assert_not_called()
        with mock.patch.object(
            BOOTSTRAP, "_EXTERNAL_DERIVED_VERSION", "1.20261126.0"
        ), mock.patch.object(
            BOOTSTRAP, "derive_remote_commit_version", return_value="1.20261127.0"
        ) as derive, mock.patch.dict(
            os.environ,
            {
                "CHAOS_ENGINE_DERIVED_VERSION": "1.20261126.0",
                "CHAOS_ENGINE_OFFLINE": "",
            },
        ):
            BOOTSTRAP._resolve_announced_version(
                "ShaftHQ/chaosengine-harness", "main", urllib.request.urlopen, argparse.Namespace()
            )
            derive.assert_not_called()
        with mock.patch.object(BOOTSTRAP, "_EXTERNAL_DERIVED_VERSION", None), mock.patch.object(
            BOOTSTRAP, "startup_commit_version", return_value=None
        ), mock.patch.object(
            BOOTSTRAP, "derive_remote_commit_version", return_value="1.20261127.0"
        ) as derive, mock.patch.dict(
            os.environ,
            {"CHAOS_ENGINE_DERIVED_VERSION": "", "CHAOS_ENGINE_OFFLINE": ""},
        ):
            BOOTSTRAP._resolve_announced_version(
                "ShaftHQ/chaosengine-harness",
                "main",
                urllib.request.urlopen,
                argparse.Namespace(from_bundle="bundle.tar.gz"),
            )
            derive.assert_not_called()

    def test_truncated_remote_page_fails_closed(self):
        day = "20261126"
        entries = [
            _commit_document(
                f"{index:040x}",
                "2026-11-26T03:00:00Z",
                parents=[f"{index + 1:040x}"],
            )
            for index in range(100)
        ]
        self.assertIsNone(BOOTSTRAP._count_remote_same_day(entries, entries[0]["sha"], day))
        short = entries[:99]
        self.assertEqual(99, BOOTSTRAP._count_remote_same_day(short, short[0]["sha"], day))

    def test_startup_version_still_derives_locally_when_offline(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = _repository(Path(temporary) / "harness")
            with mock.patch.object(
                BOOTSTRAP, "__file__", str(repo / "bootstrap.py")
            ), mock.patch.dict(
                os.environ,
                {
                    "CHAOS_ENGINE_OFFLINE": "1",
                    "CHAOS_ENGINE_DERIVED_VERSION": "",
                },
            ):
                self.assertEqual(EXPECTED_DAY + ".0", BOOTSTRAP.startup_commit_version())


if __name__ == "__main__":
    unittest.main()
