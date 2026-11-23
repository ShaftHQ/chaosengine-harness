"""GitHub CLI account install: official release asset, no package manager."""

from __future__ import annotations

import importlib.util
import io
import stat
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
CONTROLLER = ROOT / "runtime" / "dependencies.py"
PIN = "2.105.0"


def load_controller():
    spec = importlib.util.spec_from_file_location("chaos_engine_dependencies_gh", CONTROLLER)
    if spec is None or spec.loader is None:
        raise RuntimeError("dependency controller test module could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _archive_bytes(system: str, version: str, payload: bytes) -> bytes:
    if system == "linux":
        top = f"gh_{version}_linux_amd64"
        name = f"{top}/bin/gh"
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w:gz") as archive:
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            info.mode = 0o755
            archive.addfile(info, io.BytesIO(payload))
        return stream.getvalue()
    if system == "darwin":
        top = f"gh_{version}_macOS_arm64"
        member = f"{top}/bin/gh"
    else:
        top = f"gh_{version}_windows_amd64"
        member = f"{top}/bin/gh.exe"
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(member, payload)
    return stream.getvalue()


class GitHubCliAccountInstallTest(unittest.TestCase):
    def test_platform_assets_are_argv_lists_and_present_gh_skips_download(self):
        module = load_controller()
        cases = (
            ("linux", "x86_64", f"gh_{PIN}_linux_amd64.tar.gz", "gh"),
            ("linux", "aarch64", f"gh_{PIN}_linux_arm64.tar.gz", "gh"),
            ("darwin", "arm64", f"gh_{PIN}_macOS_arm64.zip", "gh"),
            ("darwin", "x86_64", f"gh_{PIN}_macOS_amd64.zip", "gh"),
            ("win32", "amd64", f"gh_{PIN}_windows_amd64.zip", "gh.exe"),
        )
        with tempfile.TemporaryDirectory() as temporary:
            bin_dir = Path(temporary) / "bin"
            for system, machine, asset, binary in cases:
                with self.subTest(system=system, machine=machine):
                    self.assertEqual(asset, module.gh_release_asset(PIN, system, machine))
                    plan = module.gh_account_plan(
                        found=None,
                        system=system,
                        machine=machine,
                        version=PIN,
                        bin_dir=bin_dir,
                    )
                    self.assertEqual("installed", plan["action"])
                    self.assertEqual(asset, plan["asset"])
                    self.assertEqual(["gh", "--version"], plan["probe"])
                    self.assertIsInstance(plan["probe"], list)
                    self.assertEqual(bin_dir / binary, plan["destination"])
                    self.assertEqual(1, len(plan["commands"]))
                    argv = plan["commands"][0]
                    self.assertIsInstance(argv, list)
                    self.assertTrue(all(isinstance(part, str) for part in argv))
                    self.assertNotIsInstance(plan["commands"], str)
                    self.assertIn(asset, plan["url"])
                    self.assertTrue(plan["url"].startswith(
                        f"https://github.com/cli/cli/releases/download/v{PIN}/"
                    ))
                    self.assertNotIn("bash", argv)
                    self.assertNotIn("sh", argv)
                    self.assertNotIn("cmd", argv)
                    self.assertNotIn("powershell", argv)
                    self.assertFalse(any(token in part for part in argv for token in (
                        "apt", "brew", "winget", "choco", "|", "&&",
                    )))
            present = module.gh_account_plan(
                found="/usr/bin/gh",
                system="linux",
                machine="x86_64",
                version=PIN,
                bin_dir=bin_dir,
            )
        self.assertEqual("reused", present["action"])
        self.assertEqual([], present["commands"])
        self.assertEqual(["gh", "--version"], present["probe"])

    def test_missing_gh_downloads_the_pinned_asset_into_the_account_bin(self):
        module = load_controller()
        payload = b"#!/bin/sh\necho gh version 2.105.0\n"
        digest = "ab" * 32

        class Body:
            def __init__(self, data: bytes):
                self.data = data

            def read(self, _size):
                data, self.data = self.data, b""
                return data

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        def opener(url, timeout=30):
            del timeout
            self.assertTrue(str(url).endswith(f"gh_{PIN}_checksums.txt"))
            text = f"{digest}  gh_{PIN}_linux_amd64.tar.gz\n".encode()
            return Body(text)

        with tempfile.TemporaryDirectory() as temporary:
            bin_dir = Path(temporary) / "bin"
            seen = {}

            def fake_download(url, destination, expected, opener=None, reporter=None):
                del opener, reporter
                seen["url"] = url
                seen["destination"] = Path(destination)
                seen["expected"] = expected
                Path(destination).write_bytes(_archive_bytes("linux", PIN, payload))

            with mock.patch.object(module, "_download_artifact", fake_download):
                installed = module.install_gh_release(
                    bin_dir,
                    version=PIN,
                    system="linux",
                    machine="x86_64",
                    opener=opener,
                )
            self.assertEqual(
                f"https://github.com/cli/cli/releases/download/v{PIN}/gh_{PIN}_linux_amd64.tar.gz",
                seen["url"],
            )
            self.assertEqual(bin_dir / f"gh_{PIN}_linux_amd64.tar.gz", seen["destination"])
            self.assertEqual(digest, seen["expected"])
            self.assertEqual(bin_dir / "gh", installed)
            self.assertEqual(payload, installed.read_bytes())
            self.assertTrue(installed.stat().st_mode & stat.S_IXUSR)

            def present(name):
                self.assertEqual("gh", name)
                return "/usr/bin/gh"

            with mock.patch.object(module, "install_gh_release") as installer:
                reused = module.provision_gh(
                    bin_dir,
                    version=PIN,
                    system="win32",
                    machine="amd64",
                    which=present,
                    opener=opener,
                )
            installer.assert_not_called()
            self.assertEqual("reused", reused["action"])
            self.assertEqual([], reused["commands"])
            self.assertEqual(["gh", "--version"], reused["probe"])
            self.assertEqual(f"gh_{PIN}_windows_amd64.zip", reused["asset"])
