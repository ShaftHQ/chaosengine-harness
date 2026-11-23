"""Issue 177: an invalid managed Maven directory is removed and reprovisioned."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]


def load_hosts():
    path = ROOT / "runtime" / "hosts.py"
    spec = importlib.util.spec_from_file_location("chaos_engine_hosts_maven_177", path)
    module = importlib.util.module_from_spec(spec)
    if spec.loader is None:
        raise RuntimeError(f"no loader for {path}")
    spec.loader.exec_module(module)
    return module


HOSTS = load_hosts()
VERSION = "3.9.12"
PLATFORM = "linux-x64"


def _specification(digest: str) -> dict:
    return {
        "runtimes": {
            "maven": {
                "version": VERSION,
                "minimumVersion": "3.9.0",
                "artifacts": {
                    PLATFORM: {
                        "url": "https://example.invalid/maven.tgz",
                        "sha256": digest,
                    }
                },
            }
        }
    }


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def _jdk(root: Path) -> Path:
    home = root / "jdk"
    java = home / "bin" / "java"
    java.parent.mkdir(parents=True)
    java.write_text("#!/bin/sh\n", encoding="utf-8")
    java.chmod(0o755)
    return home


def _extract(_archive, transaction: Path) -> None:
    binary = transaction / "bin" / "mvn"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\necho 'Apache Maven 3.9.12'\n", encoding="utf-8")
    binary.chmod(0o755)


class ManagedMavenRebuild177Tests(unittest.TestCase):
    def test_invalid_managed_directory_is_rebuilt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / "maven" / VERSION / PLATFORM
            destination.mkdir(parents=True)
            (destination / "junk").write_bytes(b"not-maven")
            outside = destination.parent / "leave-this-tree"
            outside.mkdir()
            (outside / "keep").write_bytes(b"keep")
            archive = b"maven-archive"
            digest = hashlib.sha256(archive).hexdigest()
            opened = []

            def opener(url, **_kwargs):
                opened.append(url)
                return _Response(archive)

            dependencies = HOSTS._load_dependencies_controller()
            self.assertIsNotNone(dependencies)
            with mock.patch.object(HOSTS, "_load_dependencies_controller", return_value=dependencies), \
                    mock.patch.object(HOSTS, "managed_maven_root", return_value=destination), \
                    mock.patch.object(HOSTS, "_tools_host_platform", return_value=("linux", "x64", PLATFORM)), \
                    mock.patch.object(dependencies, "download_cache_root", return_value=root / "downloads"), \
                    mock.patch.object(dependencies, "_extract_runtime_archive", side_effect=_extract), \
                    mock.patch.dict(os.environ, {"JAVA_HOME": str(_jdk(root))}, clear=False):
                result = HOSTS.ensure_managed_maven(
                    _specification(digest),
                    opener=opener,
                    which=lambda *_args, **_kwargs: None,
                )
            mvn = destination / "bin" / "mvn"
            self.assertEqual(mvn.resolve(), result)
            self.assertIsNotNone(HOSTS.verified_managed_maven(mvn, PLATFORM, version=VERSION))
            self.assertFalse((destination / "junk").exists())
            self.assertEqual(b"keep", (outside / "keep").read_bytes())
            self.assertEqual(["https://example.invalid/maven.tgz"], opened)

    def test_missing_java_home_does_not_delete_the_invalid_tree(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / "maven" / VERSION / PLATFORM
            destination.mkdir(parents=True)
            marker = destination / "junk"
            marker.write_bytes(b"keep-me")
            opened = []

            def opener(*_args, **_kwargs):
                opened.append(True)
                raise AssertionError("opener must not run")

            with mock.patch.object(HOSTS, "managed_maven_root", return_value=destination), \
                    mock.patch.object(HOSTS, "_tools_host_platform", return_value=("linux", "x64", PLATFORM)), \
                    mock.patch.object(HOSTS, "_java_home_for_maven_probe", return_value=None), \
                    mock.patch.object(HOSTS, "_ambient_maven", return_value=None):
                with self.assertRaisesRegex(ValueError, "JAVA_HOME"):
                    HOSTS.ensure_managed_maven(
                        _specification("a" * 64),
                        opener=opener,
                        which=lambda *_args, **_kwargs: None,
                    )
            self.assertEqual(b"keep-me", marker.read_bytes())
            self.assertEqual([], opened)

    def test_linked_managed_root_is_not_deleted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "elsewhere"
            target.mkdir()
            (target / "keep").write_bytes(b"keep")
            destination = root / "maven" / VERSION / PLATFORM
            destination.parent.mkdir(parents=True)
            destination.symlink_to(target, target_is_directory=True)
            with mock.patch.object(HOSTS, "managed_maven_root", return_value=destination), \
                    mock.patch.object(HOSTS, "_tools_host_platform", return_value=("linux", "x64", PLATFORM)), \
                    mock.patch.dict(os.environ, {"JAVA_HOME": str(_jdk(root))}, clear=False):
                with self.assertRaisesRegex(ValueError, "existing managed Maven tree is invalid"):
                    HOSTS.ensure_managed_maven(
                        _specification("b" * 64),
                        opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                            AssertionError("opener")
                        ),
                        which=lambda *_args, **_kwargs: None,
                    )
            self.assertTrue(destination.is_symlink())
            self.assertEqual(b"keep", (target / "keep").read_bytes())


if __name__ == "__main__":
    unittest.main()
