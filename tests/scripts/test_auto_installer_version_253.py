"""Issue #253: automatic commit-date version calculation on startup."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
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
            self.assertEqual(expected, (overlay / "VERSION").read_text(encoding="utf-8").strip())
            manifest = json.loads((overlay / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(third, manifest["source"]["commit"])
            self.assertEqual(third, INSTALL.verify_install(overlay)["source"]["commit"])

            finding = INSTALL._ce_version_after_upgrade_finding(project, overlay)
            self.assertIsNotNone(finding)
            self.assertEqual("healthy", finding["status"])
            self.assertEqual(expected, finding["installedVersion"])
            self.assertEqual(expected, finding["intendedVersion"])
            self.assertNotIn("(L92)", str(finding["detail"]))
            self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
