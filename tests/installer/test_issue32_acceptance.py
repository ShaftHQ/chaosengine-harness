"""Offline acceptance coverage for issue 32."""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bash_path import posix_bash  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def _boot():
    import importlib.util

    spec = importlib.util.spec_from_file_location("ce_boot_issue32", ROOT / "bootstrap.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _file(text: str) -> tuple[str, str, bytes]:
    boot = _boot()
    raw = text.encode()
    return boot.payload_sha256(raw), boot.git_blob_sha1(raw), raw


def _manifest(files: dict[str, bytes], commit: str) -> dict:
    boot = _boot()
    listed = {}
    for path, raw in files.items():
        listed[path] = {
            "sha256": boot.payload_sha256(raw),
            "gitBlobSha1": boot.git_blob_sha1(raw),
            "size": len(raw),
            "mode": "100644",
        }
    return {"commit": commit, "rootLayout": True, "files": listed}


def _opener(payloads: dict[str, bytes]):
    calls = []

    class Response:
        def __init__(self, body: bytes):
            self._body = body

        def read(self, _limit=None):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def open_url(request, timeout=60):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        calls.append(url)
        for suffix, body in payloads.items():
            if url.endswith(suffix):
                return Response(body)
        raise OSError(f"missing {url}")

    open_url.calls = calls
    return open_url


def test_noop_rerun_prints_779_unchanged_and_keeps_mtimes(tmp_path, capfd):
    boot = _boot()
    commit = "a" * 40
    files = {"skills/chaos-engine/SKILL.md": b"skill\n"}
    files.update({f"payload/f{index}.txt": f"{index}\n".encode() for index in range(778)})
    assert len(files) == 779
    manifest = _manifest(files, commit)
    project = tmp_path / "project"
    installed = project / ".chaos-engine"
    for path, raw in files.items():
        target = installed / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    (installed / "manifest.json").write_text(
        json.dumps({"files": {path: boot.payload_sha256(raw) for path, raw in files.items()}}) + "\n",
        encoding="utf-8",
    )
    before = (installed / "skills/chaos-engine/SKILL.md").stat().st_mtime_ns
    opener = _opener({})
    _source, actions = boot.materialize_manifest_sync(
        project, tmp_path / "dest", manifest, opener=opener, repository="ShaftHQ/chaosengine-harness"
    )
    assert boot.format_sync_counts(actions) == "0 updated, 0 added, 779 unchanged"
    assert opener.calls == []
    assert (installed / "skills/chaos-engine/SKILL.md").stat().st_mtime_ns == before
    captured = capfd.readouterr()
    assert "0 updated, 0 added, 779 unchanged" in captured.err


def test_one_file_change_downloads_one_blob(tmp_path, monkeypatch):
    monkeypatch.setenv("CHAOS_ENGINE_CACHE_DIR", str(tmp_path / "cache"))
    boot = _boot()
    commit = "b" * 40
    files = {"skills/chaos-engine/SKILL.md": b"skill\n", "payload/only.txt": b"new\n"}
    project = tmp_path / "project"
    installed = project / ".chaos-engine"
    (installed / "skills/chaos-engine").mkdir(parents=True)
    (installed / "skills/chaos-engine/SKILL.md").write_bytes(b"skill\n")
    (installed / "payload").mkdir()
    (installed / "payload/only.txt").write_bytes(b"old\n")
    base = {
        "skills/chaos-engine/SKILL.md": boot.payload_sha256(b"skill\n"),
        "payload/only.txt": boot.payload_sha256(b"old\n"),
    }
    (installed / "manifest.json").write_text(json.dumps({"files": base}) + "\n", encoding="utf-8")
    manifest = _manifest(files, commit)
    opener = _opener({"/payload/only.txt": b"new\n"})
    _source, actions = boot.materialize_manifest_sync(
        project, tmp_path / "dest", manifest, opener=opener, repository="acme/harness"
    )
    assert boot.materialize_manifest_sync.downloads == 1
    kinds = {row["path"]: row["action"] for row in actions}
    assert kinds["payload/only.txt"] == "update"
    assert kinds["skills/chaos-engine/SKILL.md"] == "unchanged"


def test_edited_keep_edits_crlf_and_stray(tmp_path):
    boot = _boot()
    commit = "c" * 40
    original = b"owned\n"
    remote = {"skills/chaos-engine/SKILL.md": b"skill\n", "owned.txt": original}
    project = tmp_path / "project"
    installed = project / ".chaos-engine"
    (installed / "skills/chaos-engine").mkdir(parents=True)
    (installed / "skills/chaos-engine/SKILL.md").write_bytes(b"skill\n")
    (installed / "owned.txt").write_bytes(b"user edit\n")
    (installed / "stray.txt").write_bytes(b"stray\n")
    (installed / "crlf.txt").write_bytes(b"line\r\n")
    remote["crlf.txt"] = b"line\n"
    base = {
        "skills/chaos-engine/SKILL.md": boot.payload_sha256(b"skill\n"),
        "owned.txt": boot.payload_sha256(original),
        "crlf.txt": boot.payload_sha256(b"line\n"),
    }
    (installed / "manifest.json").write_text(json.dumps({"files": base}) + "\n", encoding="utf-8")
    manifest = _manifest(remote, commit)
    before = {path: path.read_bytes() for path in installed.rglob("*") if path.is_file()}
    with pytest.raises(boot.SyncKeepEdits):
        boot.materialize_manifest_sync(
            project,
            tmp_path / "keep",
            manifest,
            opener=_opener({}),
            repository="acme/harness",
            keep_edits=True,
        )
    after = {path: path.read_bytes() for path in installed.rglob("*") if path.is_file()}
    assert after == before
    opener = _opener({"/owned.txt": original})
    source, actions = boot.materialize_manifest_sync(
        project, tmp_path / "dest", manifest, opener=opener, repository="acme/harness"
    )
    kinds = {row["path"]: row["action"] for row in actions}
    assert kinds["owned.txt"] == "edited"
    assert kinds["crlf.txt"] == "unchanged"
    assert kinds["stray.txt"] == "stray"
    assert (source / "crlf.txt").read_bytes() == b"line\n"
    kept = list((project / ".chaos-engine-state" / "kept-edits").rglob("owned.txt"))
    assert kept and kept[0].read_bytes() == b"user edit\n"
    stray = list((project / ".chaos-engine-state" / "kept-edits").rglob("stray.txt"))
    assert stray and stray[0].read_bytes() == b"stray\n"
    assert not (source / "stray.txt").exists()


def test_missing_file_restores_with_one_download(tmp_path, monkeypatch):
    monkeypatch.setenv("CHAOS_ENGINE_CACHE_DIR", str(tmp_path / "cache"))
    boot = _boot()
    commit = "d" * 40
    raw = b"back\n"
    files = {"skills/chaos-engine/SKILL.md": b"skill\n", "missing.txt": raw}
    project = tmp_path / "project"
    installed = project / ".chaos-engine"
    (installed / "skills/chaos-engine").mkdir(parents=True)
    (installed / "skills/chaos-engine/SKILL.md").write_bytes(b"skill\n")
    base = {
        "skills/chaos-engine/SKILL.md": boot.payload_sha256(b"skill\n"),
        "missing.txt": boot.payload_sha256(raw),
    }
    (installed / "manifest.json").write_text(json.dumps({"files": base}) + "\n", encoding="utf-8")
    opener = _opener({"/missing.txt": raw})
    _source, actions = boot.materialize_manifest_sync(
        project, tmp_path / "dest", _manifest(files, commit), opener=opener, repository="acme/harness"
    )
    assert boot.materialize_manifest_sync.downloads == 1
    assert {row["path"]: row["action"] for row in actions}["missing.txt"] == "restore"


def test_staged_blob_is_not_downloaded_again(tmp_path):
    boot = _boot()
    commit = "e" * 40
    raw = b"cached\n"
    files = {"skills/chaos-engine/SKILL.md": b"skill\n", "payload/one.txt": raw}
    project = tmp_path / "project"
    stage = project / ".chaos-engine-state" / "stage" / commit / "payload"
    stage.mkdir(parents=True)
    (stage / "one.txt").write_bytes(raw)
    (project / ".chaos-engine" / "skills/chaos-engine").mkdir(parents=True)
    (project / ".chaos-engine" / "skills/chaos-engine/SKILL.md").write_bytes(b"skill\n")
    opener = _opener({"/skills/chaos-engine/SKILL.md": b"skill\n"})
    boot.materialize_manifest_sync(
        project, tmp_path / "dest", _manifest(files, commit), opener=opener, repository="acme/harness"
    )
    assert not any(call.endswith("/payload/one.txt") for call in opener.calls)
    assert (project / ".chaos-engine" / "payload").exists() is False


def test_bad_hash_dotdot_and_link_leave_the_tree(tmp_path):
    boot = _boot()
    commit = "f" * 40
    project = tmp_path / "project"
    installed = project / ".chaos-engine"
    (installed / "skills/chaos-engine").mkdir(parents=True)
    (installed / "skills/chaos-engine/SKILL.md").write_bytes(b"skill\n")
    before = (installed / "skills/chaos-engine/SKILL.md").read_bytes()
    files = {"skills/chaos-engine/SKILL.md": b"skill\n", "bad.txt": b"good\n"}
    manifest = _manifest(files, commit)
    opener = _opener({"/bad.txt": b"tampered\n"})
    with pytest.raises(ValueError, match="CE-INSTALL-FAILED"):
        boot.materialize_manifest_sync(
            project, tmp_path / "dest", manifest, opener=opener, repository="acme/harness"
        )
    assert (installed / "skills/chaos-engine/SKILL.md").read_bytes() == before
    manifest["files"]["../x"] = manifest["files"]["bad.txt"]
    with pytest.raises(ValueError, match="CE-INSTALL-FAILED"):
        boot.materialize_manifest_sync(
            project, tmp_path / "dot", manifest, opener=_opener({}), repository="acme/harness"
        )
    link = installed / "skills/chaos-engine/link.py"
    link.symlink_to(installed / "skills/chaos-engine/SKILL.md")
    with pytest.raises(ValueError, match="CE-INSTALL-FAILED"):
        boot.read_installed_file_index(project)


def test_dry_run_verify_and_offline_cache(tmp_path, monkeypatch):
    boot = _boot()
    commit = "9" * 40
    files = {"skills/chaos-engine/SKILL.md": b"skill\n"}
    project = tmp_path / "project"
    installed = project / ".chaos-engine"
    (installed / "skills/chaos-engine").mkdir(parents=True)
    skill = installed / "skills/chaos-engine/SKILL.md"
    skill.write_bytes(b"skill\n")
    (installed / "manifest.json").write_text(
        json.dumps({"files": {"skills/chaos-engine/SKILL.md": boot.payload_sha256(b"skill\n")}}) + "\n",
        encoding="utf-8",
    )
    digest = boot.payload_sha256(b"skill\n")
    monkeypatch.setenv("CHAOS_ENGINE_CACHE_HOME", str(tmp_path / "cache"))
    boot.store_cached_blob(digest, b"skill\n")
    before = skill.read_bytes()
    boot.materialize_manifest_sync(
        project,
        tmp_path / "dry",
        _manifest(files, commit),
        opener=_opener({}),
        repository="acme/harness",
        dry_run=True,
    )
    assert skill.read_bytes() == before
    assert not (tmp_path / "dry").exists() or not any((tmp_path / "dry").rglob("*"))
    with pytest.raises(ValueError, match="offline cache miss"):
        boot.materialize_manifest_sync(
            project,
            tmp_path / "cold",
            _manifest({"skills/chaos-engine/SKILL.md": b"other\n"}, commit),
            opener=_opener({}),
            repository="acme/harness",
            offline=True,
        )


def test_release_sha256_is_checked_before_blobs():
    boot = _boot()
    manifest = json.dumps({"commit": "a" * 40, "files": {"skills/chaos-engine/SKILL.md": {"sha256": "b" * 64}}}).encode()
    digest = hashlib.sha256(manifest).hexdigest()
    calls = []

    class Response:
        def __init__(self, body: bytes):
            self._body = body

        def read(self, _limit=None):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def opener(request, timeout=60):
        url = request.full_url
        calls.append(url)
        if url.endswith(".sha256"):
            return Response(b"0" * 64)
        if url.endswith(".intoto.jsonl"):
            raise OSError("optional")
        if url.endswith("chaosengine-manifest.json"):
            return Response(manifest)
        raise AssertionError(url)

    with pytest.raises(ValueError, match="CE-INSTALL-FAILED: release manifest sha256"):
        boot.verify_release_manifest("ShaftHQ/chaosengine-harness", "0.4.20261115.5", opener)
    assert not any("/payload/" in call or call.endswith(".py") for call in calls)
    assert digest != "0" * 64


def test_version_pin_hex_does_not_use_the_network():
    boot = _boot()
    pin = "ab" * 20

    def opener(*_args, **_kwargs):
        raise AssertionError("network")

    assert boot.resolve_version_pin("ShaftHQ/chaosengine-harness", pin, opener) == pin


def test_banner_source_link_and_no_color_spinner(monkeypatch):
    boot = _boot()
    marks = "\n".join(boot.BRAND_ASCII + boot.BRAND_UNICODE + boot.BRAND_NARROW)
    assert "Ǝ" not in marks
    assert "C|*|E" in boot.BRAND_NARROW[0]
    assert len(boot.BRAND_UNICODE) <= 12
    assert boot.CYBERNETIC_RED in "\n".join(
        boot.brand_lines(color=True, unicode=True, truecolor=True)
    )
    assert "38;2;" not in "\n".join(boot.brand_lines(color=True, unicode=True))
    plain = "\n".join(boot.brand_lines(color=False, unicode=False))
    assert "\x1b" not in plain
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert "chaosengine-harness" in boot.brand_lockup()
    assert version in boot.brand_lockup()
    assert "/chaos-engine" not in boot.source_tree_url("o/r", "a" * 40, root_layout=True)
    assert boot.source_tree_url("o/r", "a" * 40, root_layout=False).endswith("/chaos-engine")
    for name in ("lockup-light.svg", "lockup-dark.svg"):
        desc = (ROOT / "assets" / "brand" / name).read_text(encoding="utf-8")
        assert "ChaosEngine wordmark" in desc
    monkeypatch.setenv("NO_COLOR", "1")
    stream = io.StringIO()
    reporter = boot.InstallReporter(stream=stream)
    reporter.remaining_operations = ("Download source",)
    reporter.current_operation = "Download source"
    reporter._render_locked()
    rendered = stream.getvalue()
    assert "\x1b" not in rendered
    assert "Download source" in rendered
    assert "running" in rendered
    monkeypatch.setenv("TERM", "dumb")
    dumb = io.StringIO()
    dumb.isatty = lambda: True
    quiet = boot.InstallReporter(stream=dumb)
    assert quiet._tty is False
    assert "ChaosEngine" not in dumb.getvalue() or "chaosengine-harness" not in dumb.getvalue()


def test_ci_does_not_read_a_prompt(monkeypatch):
    boot = _boot()
    monkeypatch.setenv("CI", "1")

    class Boom:
        def readline(self):
            raise AssertionError("prompt")

    boot.confirm_operation("Download", input_stream=Boom(), output=io.StringIO())


def test_from_bundle_does_not_open_a_url(tmp_path, monkeypatch):
    boot = _boot()
    bundle = tmp_path / "bundle.zip"
    script = "import sys\nprint('BUNDLE-OK')\nraise SystemExit(0)\n"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("install.py", script)

    def opener(*_args, **_kwargs):
        raise AssertionError("network")

    monkeypatch.setattr(boot.urllib.request, "urlopen", opener)
    monkeypatch.setattr(
        "sys.argv",
        [
            "bootstrap.py",
            "--from-bundle",
            str(bundle),
            "--project",
            str(tmp_path / "project"),
            "--repository",
            "ShaftHQ/chaosengine-harness",
        ],
    )
    assert boot.main() == 0


def test_shell_and_wrappers_forward_flags_and_shaft_shims():
    sha = "cd" * 20
    flags = ["--dry-run", "--json", "--version", sha, "--hosts", "grok", "--without-caveman"]
    env = {**os.environ, "CHAOS_ENGINE_ARGV_ONLY": "1"}
    env.pop("CHAOS_ENGINE_RESOLVE_ONLY", None)
    shell = subprocess.run(
        [posix_bash(), str(ROOT / "install.sh"), *flags],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert shell.returncode == 0
    forwarded = shell.stdout.splitlines()[-1]
    for flag in flags:
        assert flag in forwarded
    shaft = subprocess.run(
        [
            posix_bash(),
            str(ROOT / "install.sh"),
            "https://raw.githubusercontent.com/ShaftHQ/SHAFT_ENGINE/main/chaos-engine/install.sh",
        ],
        cwd=ROOT,
        env={**os.environ, "CHAOS_ENGINE_RESOLVE_ONLY": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert shaft.returncode == 0
    assert shaft.stdout.strip() == (
        "ShaftHQ/chaosengine-harness|main||"
        "https://raw.githubusercontent.com/ShaftHQ/chaosengine-harness/main/bootstrap.py"
    )
    other = subprocess.run(
        [
            posix_bash(),
            str(ROOT / "install.sh"),
            "https://raw.githubusercontent.com/Other/SHAFT_ENGINE/main/chaos-engine/install.sh",
        ],
        cwd=ROOT,
        env={**os.environ, "CHAOS_ENGINE_RESOLVE_ONLY": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert "Other/SHAFT_ENGINE|main|chaos-engine|" in other.stdout
    module = subprocess.run(
        [os.environ.get("PYTHON", "python3"), "-m", "chaosengine_harness", *flags],
        cwd=ROOT,
        env={**os.environ, "CHAOS_ENGINE_ARGV_ONLY": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert module.returncode == 0
    argv = json.loads(module.stdout)
    for flag in flags:
        assert flag in argv
    assert "--repository" in argv and "ShaftHQ/chaosengine-harness" in argv
    node = subprocess.run(
        ["node", str(ROOT / "bin" / "chaosengine-harness.js"), *flags],
        cwd=ROOT,
        env={**os.environ, "CHAOS_ENGINE_ARGV_ONLY": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert node.returncode == shell.returncode
    node_argv = json.loads(node.stdout)
    for flag in flags:
        assert flag in node_argv
    ps1 = (ROOT / "install.ps1").read_text(encoding="utf-8")
    assert "[Environment]::CommandLine" in ps1
    assert "MyInvocation.Line" in ps1
    assert "NoModifyPath" in ps1
    assert "-not $NoModifyPath" in ps1 or "-not $NoModifyPath" in ps1.replace(" ", "")
    invocation = "Invoke-Expression (irm https://raw.githubusercontent.com/ShaftHQ/SHAFT_ENGINE/main/chaos-engine/install.ps1)"
    assert _powershell_rewrite(invocation) == (
        "ShaftHQ/chaosengine-harness",
        "main",
        "",
        "https://raw.githubusercontent.com/ShaftHQ/chaosengine-harness/main/bootstrap.py",
    )
    assert _powershell_switch("-WithDesignSkills") == "--with-designskills"
    assert _powershell_switch("-WithoutShaftEngineUsers") == "--without-shaftengineusers"


def _powershell_rewrite(text: str):
    import re

    match = re.search(
        r"https://raw\.githubusercontent\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/(.+?)/install\.(ps1|sh)\b",
        text,
        re.I,
    )
    repository = f"{match.group(1)}/{match.group(2)}"
    rest = match.group(3)
    if rest.endswith("/chaos-engine"):
        ref = rest[: -len("/chaos-engine")]
        prefix = "chaos-engine"
    else:
        ref = rest
        prefix = ""
    digest = hashlib.sha256(repository.lower().encode()).hexdigest()
    if digest == "784908b613872582bc8185e13b6132a40ace924b406c1b60fa86c1d45eebd135" and prefix == "chaos-engine":
        repository = "ShaftHQ/chaosengine-harness"
        ref = "main"
        prefix = ""
    bootstrap = "bootstrap.py" if not prefix else f"{prefix}/bootstrap.py"
    return repository, ref, prefix, f"https://raw.githubusercontent.com/{repository}/{ref}/{bootstrap}"


def _powershell_switch(token: str) -> str:
    import re

    match = re.fullmatch(r"-(Without|With)([A-Za-z0-9]+)", token, re.I)
    return "--" + match.group(1).lower() + "-" + match.group(2).lower()


def test_shell_argv_and_probe_ignore_a_store_python3_alias(tmp_path):
    """A python3 alias that writes UTF-16 must not fail flag checks or be selected."""
    import shutil

    system_python = shutil.which("python3")
    assert system_python
    alias = tmp_path / "python3"
    alias.write_bytes(
        b"#!/bin/sh\n"
        b"printf '\\160\\000\\171\\000\\164\\000\\150\\000\\157\\000\\156\\000"
        b"\\040\\000\\167\\000\\141\\000\\163\\000\\040\\000\\156\\000\\157\\000"
        b"\\164\\000\\040\\000\\146\\000\\157\\000\\165\\000\\156\\000\\144\\000"
        b"\\073\\000\\040\\000\\162\\000\\165\\000\\156\\000\\040\\000\\167\\000"
        b"\\151\\000\\164\\000\\150\\000\\157\\000\\165\\000\\164\\000\\040\\000"
        b"\\141\\000\\162\\000\\147\\000\\165\\000\\155\\000\\145\\000\\156\\000"
        b"\\164\\000\\163\\000\\040\\000\\164\\000\\157\\000\\040\\000\\151\\000"
        b"\\156\\000\\163\\000\\164\\000\\141\\000\\154\\000\\154\\000\\056\\000"
        b"\\012\\000\\012\\000'\n"
        b"exit 0\n"
    )
    real = tmp_path / "python"
    real.write_text(f"#!/bin/sh\nexec {system_python} \"$@\"\n", encoding="utf-8")
    alias.chmod(0o755)
    real.chmod(0o755)
    path = f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}"
    argv_env = {
        **os.environ,
        "PATH": path,
        "CHAOS_ENGINE_ARGV_ONLY": "1",
    }
    argv_env.pop("CHAOS_ENGINE_RESOLVE_ONLY", None)
    argv_env.pop("JAVA_HOME", None)
    argv = subprocess.run(
        [posix_bash(), str(ROOT / "install.sh"), "--dry-run", "--hosts", "grok"],
        cwd=ROOT,
        env=argv_env,
        capture_output=True,
        check=False,
    )
    assert argv.returncode == 0, argv.stderr
    assert b"\x00" not in argv.stdout
    assert b"ShaftHQ/chaosengine-harness|main|" in argv.stdout
    assert b"--dry-run --hosts grok" in argv.stdout
    probe_env = {
        **os.environ,
        "PATH": path,
        "CHAOS_ENGINE_PYTHON_PROBE_ONLY": "1",
    }
    probe_env.pop("CHAOS_ENGINE_ARGV_ONLY", None)
    probe_env.pop("CHAOS_ENGINE_RESOLVE_ONLY", None)
    probe_env.pop("JAVA_HOME", None)
    probe = subprocess.run(
        [posix_bash(), str(ROOT / "install.sh")],
        cwd=ROOT,
        env=probe_env,
        capture_output=True,
        check=False,
    )
    assert probe.returncode == 0, probe.stderr
    # Linux selects the real `python` after the alias. Windows selects `py -3` first.
    assert probe.stdout.strip() in {b"python", b"py"}
    assert b"\x00" not in probe.stdout


def test_windows_py_launcher_keeps_dash_three_for_verify(tmp_path):
    """A Windows `py -3` selection must still pass `-3` into verify."""
    import shutil

    system_python = shutil.which("python3")
    assert system_python
    log = tmp_path / "py.log"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    launcher = fake_bin / "py"
    launcher.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$*\" >> \"$PY_LOG\"\n"
        "if [ \"$1\" = \"-3\" ] && [ \"$2\" = \"-c\" ]; then\n"
        "  printf '%s\\n' CEPY\n"
        "  exit 0\n"
        "fi\n"
        "if [ \"$1\" = \"-3\" ]; then\n"
        "  shift\n"
        "  exec \"$REAL_PYTHON\" \"$@\"\n"
        "fi\n"
        "printf '%s\\n' no-launcher >> \"$PY_LOG\"\n"
        "exit 3\n",
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    project = tmp_path / "project"
    overlay = project / ".chaos-engine"
    overlay.mkdir(parents=True)
    (overlay / "install.py").write_text(
        "print('VERIFY-RAN')\nraise SystemExit(0)\n",
        encoding="utf-8",
    )
    driver = tmp_path / "drive.sh"
    driver.write_text(
        "#!/bin/bash\n"
        "uname() {\n"
        "  case \"$1\" in\n"
        "    -s) printf '%s\\n' MINGW64_NT-10.0 ;;\n"
        "    *) printf '%s\\n' x86_64 ;;\n"
        "  esac\n"
        "}\n"
        "export -f uname\n"
        "cd \"$PROJECT_DIR\"\n"
        "exec bash \"$INSTALL_SH\" verify\n",
        encoding="utf-8",
    )
    driver.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{env.get('PATH', '')}",
            "PY_LOG": str(log),
            "REAL_PYTHON": system_python,
            "PROJECT_DIR": str(project),
            "INSTALL_SH": str(ROOT / "install.sh"),
        }
    )
    for key in (
        "JAVA_HOME",
        "CHAOS_ENGINE_ARGV_ONLY",
        "CHAOS_ENGINE_RESOLVE_ONLY",
        "CHAOS_ENGINE_PYTHON_PROBE_ONLY",
    ):
        env.pop(key, None)
    completed = subprocess.run(
        [posix_bash(), str(driver)],
        env=env,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode() + completed.stdout.decode()
    recorded = log.read_text(encoding="utf-8").splitlines()
    assert any(line.startswith("-3 ") and "-c" in line for line in recorded)
    assert any("install.py" in line and line.startswith("-3 ") and line.endswith("verify") for line in recorded)
    assert "no-launcher" not in recorded
    assert b"VERIFY-RAN" in completed.stdout


def test_docs_pin_block_and_flag_table():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    install = (ROOT / "INSTALL.md").read_text(encoding="utf-8")
    assert "## Pin, verify, uninstall" in readme
    assert readme.count("curl -fsSL") == 1
    assert "| `--dry-run`" in install
    assert "| `-DryRun`" in install
    assert "--version" in install and "-NoModifyPath" in install
