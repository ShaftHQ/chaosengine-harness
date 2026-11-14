"""Root-or-nested source prefix for the bootstrap (ShaftHQ/SHAFT_ENGINE#8057 R1).

Offline fixtures only: a fake opener serves GitHub tree listings, raw blobs and
tarballs. A bootstrap that only understands the nested ``chaos-engine/`` prefix
fails the root-tree fixture.
"""

from __future__ import annotations

import gzip
import importlib.util
import io
import json
import os
import shutil
import subprocess  # nosec B404 - fixed local commands only
import tarfile
import tempfile
import unittest
import urllib.error
import unittest.mock as mock
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
COMMIT = "1" * 40
REPOSITORY = "ShaftHQ/chaosengine-harness"


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"ce_layout_{name}", ROOT / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BOOT = load("bootstrap")

SOURCE = {
    "skills/chaos-engine/SKILL.md": b"skill\n",
    "install.py": b"# installer\n",
    "VERSION": b"0.4.20261114.1\n",
    "references/a.md": b"ref\n",
    "CONTRIBUTING.md": b"contrib\n",
    "CHANGELOG.md": b"log\n",
    ".github/workflows/ci.yml": b"name: CI\n",
    "RESEARCH.md": b"notes\n",
    "SECURITY.md": b"security\n",
    "CODE_OF_CONDUCT.md": b"coc\n",
    "tests/test_x.py": b"# repo test\n",
    "references/CHANGELOG.md": b"kept: not at the root\n",
}
ORIGIN_ONLY = {
    "CONTRIBUTING.md", "CHANGELOG.md", ".github/workflows/ci.yml", "RESEARCH.md",
    "SECURITY.md", "CODE_OF_CONDUCT.md", "tests/test_x.py",
}


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def blob(path: str, content: bytes) -> dict:
    return {
        "path": path,
        "mode": "100644",
        "type": "blob",
        "size": len(content),
        "sha": BOOT.git_blob_sha1(content),
    }


def tree_entries(files: dict[str, bytes]) -> list[dict]:
    rows = [blob(path, content) for path, content in files.items()]
    dirs = sorted({str(PurePosixPath(p).parent) for p in files if "/" in p})
    expanded = set()
    for d in dirs:
        parts = PurePosixPath(d).parts
        for i in range(1, len(parts) + 1):
            expanded.add("/".join(parts[:i]))
    rows += [{"path": d, "mode": "040000", "type": "tree", "sha": "f" * 40} for d in sorted(expanded)]
    return rows


def one_level(files: dict[str, bytes], tree_sha) -> list[dict]:
    rows = []
    for name in sorted({PurePosixPath(p).parts[0] for p in files}):
        if name in files:
            rows.append(blob(name, files[name]))
        else:
            rows.append({"path": name, "mode": "040000", "type": "tree", "sha": tree_sha(name)})
    return rows


def tree_sha_of(files: dict[str, bytes]) -> str:
    return BOOT.source_directory_tree_sha({k: (v, False) for k, v in files.items()})


def tarball(files: dict[str, bytes], top: str = "ShaftHQ-chaosengine-harness-1111111") -> bytes:
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as archive:
        for path, content in files.items():
            info = tarfile.TarInfo(f"{top}/{path}")
            info.size = len(content)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(content))
    return gzip.compress(raw.getvalue())


class FakeGitHub:
    """Serves one commit whose repository is either root-layout or nested."""

    def __init__(self, repo_files: dict[str, bytes], *, fail_recursive=False, fail_raw=False):
        self.files = repo_files
        self.fail_recursive = fail_recursive
        self.fail_raw = fail_raw
        self.urls: list[str] = []
        self.root_sha = tree_sha_of(repo_files)
        self.subtrees = {}
        for top in {PurePosixPath(p).parts[0] for p in repo_files if "/" in p}:
            sub = {p[len(top) + 1 :]: c for p, c in repo_files.items() if p.startswith(top + "/")}
            self.subtrees[tree_sha_of(sub)] = sub
            self.subtrees.setdefault(top, tree_sha_of(sub))

    def __call__(self, request, timeout=0):
        del timeout
        url = request.full_url if hasattr(request, "full_url") else str(request)
        self.urls.append(url)
        trees = f"https://api.github.com/repos/{REPOSITORY}/git/trees/"
        if url == trees + COMMIT:
            listing = one_level(self.files, lambda name: self.subtrees[name])
            return Response(json.dumps({"sha": self.root_sha, "truncated": False, "tree": listing}).encode())
        if url.startswith(trees):
            sha, _, query = url[len(trees) :].partition("?")
            if self.fail_recursive:
                raise urllib.error.HTTPError(url, 404, "gone", {}, None)
            files = self.files if sha == self.root_sha else self.subtrees.get(sha)
            if files is None or not isinstance(files, dict):
                raise urllib.error.HTTPError(url, 404, "missing", {}, None)
            listing = tree_entries(files) if query == "recursive=1" else one_level(files, lambda n: "e" * 40)
            return Response(json.dumps({"sha": sha, "truncated": False, "tree": listing}).encode())
        raw = f"https://raw.githubusercontent.com/{REPOSITORY}/{COMMIT}/"
        if url.startswith(raw):
            if self.fail_raw:
                raise urllib.error.HTTPError(url, 404, "gone", {}, None)
            path = url[len(raw) :]
            if path not in self.files:
                raise urllib.error.HTTPError(url, 404, "missing", {}, None)
            return Response(self.files[path])
        if "codeload.github.com" in url or "/tarball/" in url:
            return Response(tarball(self.files))
        raise urllib.error.HTTPError(url, 404, "unexpected", {}, None)


def download(fake: FakeGitHub, destination: Path) -> Path:
    with mock.patch.object(BOOT.time, "sleep"):
        return BOOT.download_source_remote(REPOSITORY, COMMIT, destination, opener=fake)


def installed(source: Path) -> set[str]:
    return {p.relative_to(source).as_posix() for p in source.rglob("*") if p.is_file()}


class RootLayoutTest(unittest.TestCase):
    def test_root_tree_fixture_installs_root_source(self):
        fake = FakeGitHub(dict(SOURCE))
        with tempfile.TemporaryDirectory() as temporary:
            source = download(fake, Path(temporary))
            self.assertTrue((source / "skills/chaos-engine/SKILL.md").is_file())
            self.assertEqual(set(SOURCE) - ORIGIN_ONLY, installed(source))
        raw = [u for u in fake.urls if "raw.githubusercontent.com" in u]
        self.assertTrue(raw)
        self.assertFalse([u for u in raw if f"/{COMMIT}/chaos-engine/" in u], raw)

    def test_root_tree_tarball_fallback_verifies_root_identity(self):
        fake = FakeGitHub(dict(SOURCE), fail_raw=True)
        with tempfile.TemporaryDirectory() as temporary:
            source = download(fake, Path(temporary))
            self.assertEqual(set(SOURCE) - ORIGIN_ONLY, installed(source))
        self.assertTrue(any("codeload.github.com" in u for u in fake.urls))

    def test_root_tree_tarball_when_listing_fails_is_bound_to_root_tree_sha(self):
        fake = FakeGitHub(dict(SOURCE), fail_recursive=True)
        with tempfile.TemporaryDirectory() as temporary:
            source = download(fake, Path(temporary))
            self.assertEqual(set(SOURCE) - ORIGIN_ONLY, installed(source))

    def test_root_tree_tarball_with_tampered_bytes_fails_closed(self):
        fake = FakeGitHub(dict(SOURCE), fail_recursive=True)
        tampered = dict(SOURCE, **{"install.py": b"# evil\n"})
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
            fake, "__call__", wraps=fake.__call__
        ), mock.patch.object(BOOT.time, "sleep"):
            original = FakeGitHub.__call__

            def opener(request, timeout=0):
                url = request.full_url
                if "codeload.github.com" in url or "/tarball/" in url:
                    return Response(tarball(tampered))
                return original(fake, request, timeout)

            with self.assertRaises(ValueError):
                BOOT.download_source_remote(REPOSITORY, COMMIT, Path(temporary), opener=opener)
            self.assertFalse((Path(temporary) / "chaos-engine").exists())


class NestedLayoutTest(unittest.TestCase):
    def test_nested_fixture_keeps_legacy_prefix(self):
        nested = {f"chaos-engine/{k}": v for k, v in SOURCE.items()}
        nested["src/Main.java"] = b"class Main {}\n"
        fake = FakeGitHub(nested)
        with tempfile.TemporaryDirectory() as temporary:
            source = download(fake, Path(temporary))
            self.assertEqual(set(SOURCE) - ORIGIN_ONLY, installed(source))
        raw = [u for u in fake.urls if "raw.githubusercontent.com" in u]
        self.assertTrue(raw)
        self.assertTrue(all(f"/{COMMIT}/chaos-engine/" in u for u in raw), raw)
        self.assertFalse(any("Main.java" in u for u in fake.urls))


class FailClosedTest(unittest.TestCase):
    def test_neither_layout_fails_closed(self):
        fake = FakeGitHub({"README.md": b"x\n", "src/Main.java": b"class Main {}\n"})
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValueError):
                download(fake, Path(temporary))
            self.assertFalse((Path(temporary) / "chaos-engine").exists())

    def test_root_hint_without_skill_fails_closed(self):
        files = {k: v for k, v in SOURCE.items() if k != "skills/chaos-engine/SKILL.md"}
        files["skills/other/SKILL.md"] = b"other\n"
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValueError):
                download(FakeGitHub(files), Path(temporary))


class LocalCloneTest(unittest.TestCase):
    def test_root_layout_local_clone_copies_root_without_origin_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            clone = Path(temporary) / "clone"
            for path, content in SOURCE.items():
                target = clone / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
            (clone / ".git").mkdir()
            out = Path(temporary) / "out"
            out.mkdir()
            source = BOOT.copy_source_from_local_clone(clone, out)
            self.assertEqual(set(SOURCE) - ORIGIN_ONLY, installed(source))
            self.assertEqual(clone.resolve(), BOOT.resolve_local_clone(clone))


    def test_root_skill_wins_over_a_nested_folder_in_the_same_clone(self):
        with tempfile.TemporaryDirectory() as temporary:
            clone = Path(temporary) / "clone"
            for path, content in SOURCE.items():
                target = clone / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
            stale = clone / "chaos-engine"
            (stale / "skills/chaos-engine").mkdir(parents=True)
            (stale / "skills/chaos-engine/SKILL.md").write_bytes(b"stale\n")
            (stale / "install.py").write_bytes(b"# stale\n")
            (stale / "VERSION").write_bytes(b"0\n")
            out = Path(temporary) / "out"
            out.mkdir()
            source = BOOT.copy_source_from_local_clone(clone, out)
            self.assertEqual(b"skill\n", (source / "skills/chaos-engine/SKILL.md").read_bytes())

    def test_running_checkout_is_tried_before_its_parent(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            sibling = parent / "chaos-engine"
            (sibling / "skills/chaos-engine").mkdir(parents=True)
            (sibling / "install.py").write_bytes(b"# sibling\n")
            (sibling / "VERSION").write_bytes(b"0\n")
            clone = parent / "clone"
            for path, content in SOURCE.items():
                target = clone / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
            (clone / ".git").mkdir()
            shutil.copy2(ROOT / "bootstrap.py", clone / "bootstrap.py")
            module_spec = importlib.util.spec_from_file_location("ce_layout_clone_boot", clone / "bootstrap.py")
            module = importlib.util.module_from_spec(module_spec)
            module_spec.loader.exec_module(module)
            with mock.patch.dict(os.environ, {module.LOCAL_CLONE_ENV: ""}):
                self.assertEqual(clone.resolve(), module.resolve_local_clone())


class InstallerOmitTest(unittest.TestCase):
    def test_origin_only_repo_files_stay_out_of_adopter_payload(self):
        install = load("install")
        for name in ("CONTRIBUTING.md", "CODE_OF_CONDUCT.md", "SECURITY.md", "CHANGELOG.md", ".github/workflows/ci.yml", "tests/test_x.py"):
            self.assertTrue(install.is_origin_only(Path(name)), name)
        self.assertFalse(install.is_origin_only(Path("skills/chaos-engine/SKILL.md")))


class WrapperDefaultTest(unittest.TestCase):
    def resolve_sh(self, *args: str, **env: str) -> list[str]:
        clean = {k: v for k, v in os.environ.items() if not k.startswith("CHAOS_ENGINE_")}
        clean.update(env, CHAOS_ENGINE_RESOLVE_ONLY="1")
        with tempfile.TemporaryDirectory() as temporary:
            out = subprocess.run(  # nosec B603 B607
                ["sh", str(ROOT / "install.sh"), *args], cwd=temporary, env=clean,
                capture_output=True, text=True, check=True,
            ).stdout.strip()
        return out.split("|")

    def test_sh_defaults_to_standalone_main_root(self):
        self.assertEqual(
            [REPOSITORY, "main", "", f"https://raw.githubusercontent.com/{REPOSITORY}/main/bootstrap.py"],
            self.resolve_sh(),
        )

    def test_sh_explicit_url_still_wins(self):
        url = "https://raw.githubusercontent.com/acme/fork/dev/chaos-engine/install.sh"
        self.assertEqual(
            ["acme/fork", "dev", "chaos-engine", "https://raw.githubusercontent.com/acme/fork/dev/chaos-engine/bootstrap.py"],
            self.resolve_sh(url),
        )

    def test_sh_root_url_parses_root_prefix(self):
        url = f"https://raw.githubusercontent.com/{REPOSITORY}/main/install.sh"
        self.assertEqual("", self.resolve_sh(url)[2])

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh not installed")
    def test_ps1_defaults_to_standalone_main_root(self):
        script = (
            f". '{ROOT / 'install.ps1'}' -ParseOnly; "
            "$s = Resolve-ChaosEngineSource -Texts @('no url here'); "
            "Write-Output ($s.Repository + '|' + $s.Ref + '|' + $s.Prefix + '|' + $s.BootstrapUrl)"
        )
        clean = {k: v for k, v in os.environ.items() if not k.startswith("CHAOS_ENGINE_")}
        out = subprocess.run(  # nosec B603 B607
            ["pwsh", "-NoProfile", "-Command", script], env=clean, capture_output=True, text=True, check=True
        ).stdout.strip().splitlines()[-1]
        self.assertEqual(
            f"{REPOSITORY}|main||https://raw.githubusercontent.com/{REPOSITORY}/main/bootstrap.py", out
        )


if __name__ == "__main__":
    unittest.main()
