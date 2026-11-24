"""Offline SHAFT detection and version-pinned skills (issue 33)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

# unittest discovery imports this module. pytest is not required for that path.
try:
    import pytest
except ModuleNotFoundError:
    pytest = None

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bash_path import posix_bash  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OLD = "10.4.20261108"
NEW = "10.4.20261112"
REPO = "ShaftHQ/SHAFT_ENGINE"


def _modules():
    import importlib.util

    def load(name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    boot = load("ce_boot_shaft", ROOT / "bootstrap.py")
    detect = load("ce_detect_shaft", ROOT / "packs" / "shaft" / "detect.py")
    sync = load("ce_sync_shaft", ROOT / "packs" / "shaft" / "sync.py")
    install = load("ce_install_shaft", ROOT / "install.py")
    return boot, detect, sync, install


def _files(tag: str) -> dict[str, bytes]:
    files = {f"shaft-guide/f{index}.md": b"same\n" for index in range(100)}
    files.update({f"references/r{index}.md": b"same-ref\n" for index in range(16)})
    files["shaft-cli/SKILL.md"] = f"skill {tag}\n".encode()
    files["shaft-assertions/SKILL.md"] = f"assert {tag}\n".encode()
    files["references/guide.md"] = f"guide {tag}\n".encode()
    files["ce-pack/profile.json"] = b'{"repository":"ShaftHQ/SHAFT_ENGINE"}\n'
    files["ce-pack/entrypoint.md"] = b"entrypoint\n"
    files["scripts/mcp/install.sh"] = b"nope\n"
    files["scripts/mcp/install.ps1"] = b"nope\n"
    files["shaft-upgrader/run.sh"] = b"nope\n"
    files["scripts/install_shaft_agentic_tools.py"] = b"nope\n"
    files["post-install.json"] = b"{}\n"
    assert sum(
        1
        for path in files
        if (path.startswith("shaft-") or path.startswith("references/")) and not path.startswith("shaft-upgrader/")
    ) == 119
    return files


def _index_trees(boot, files: dict[str, bytes]) -> tuple[str, dict[str, dict], dict[str, bytes]]:
    trees: dict[str, dict] = {}
    blobs: dict[str, bytes] = {}

    def directory(paths: dict[str, bytes]) -> str:
        grouped: dict[str, dict[str, bytes]] = {}
        entries = []
        for path, content in sorted(paths.items()):
            name, _, rest = path.partition("/")
            if rest:
                grouped.setdefault(name, {})[rest] = content
            else:
                sha = boot.git_blob_sha1(content)
                blobs[sha] = content
                entries.append(("100644", name, sha, "blob"))
        for name, child in sorted(grouped.items()):
            sha = directory(child)
            entries.append(("40000", name, sha, "tree"))
        body = [
            ("100644" if kind == "blob" else "40000", name, sha)
            for _mode, name, sha, kind in entries
        ]
        tree_sha = boot.git_tree_sha1(body)
        trees[tree_sha] = {
            "sha": tree_sha,
            "truncated": False,
            "tree": [
                {"path": name, "mode": "100644" if kind == "blob" else "040000", "type": kind, "sha": sha}
                for _mode, name, sha, kind in entries
            ],
        }
        return tree_sha

    skills = directory(files)
    root_sha = boot.git_tree_sha1([("40000", "shaft-skills", skills)])
    trees[root_sha] = {
        "sha": root_sha,
        "truncated": False,
        "tree": [{"path": "shaft-skills", "mode": "040000", "type": "tree", "sha": skills}],
    }
    return root_sha, trees, blobs


class _ShaftServer:
    def __init__(self, boot, extra: dict[str, bytes] | None = None):
        self.hits: list[str] = []
        self.commits = {}
        self.trees = {}
        self.blobs = {}
        self.by_commit: dict[str, dict[str, bytes]] = {}
        self.extra = dict(extra or {})
        for tag in (OLD, NEW):
            payload = {**_files(tag), **self.extra}
            commit, trees, blobs = _index_trees(boot, payload)
            self.commits[tag] = commit
            self.trees.update(trees)
            self.blobs.update(blobs)
            self.by_commit[commit] = payload
        self.latest = NEW

    def start(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urlparse(self.path)
                path = unquote(parsed.path)
                server.hits.append(path + (("?" + parsed.query) if parsed.query else ""))
                if "recursive=1" in parsed.query:
                    self.send_error(400)
                    return
                if path == f"/repos/{REPO}/releases/latest":
                    body = json.dumps({"tag_name": server.latest}).encode()
                elif path.startswith(f"/repos/{REPO}/git/ref/tags/"):
                    tag = path.rsplit("/", 1)[-1]
                    commit = server.commits.get(tag)
                    if commit is None:
                        self.send_error(404)
                        return
                    body = json.dumps({"object": {"sha": commit, "type": "commit"}}).encode()
                elif path.startswith(f"/repos/{REPO}/git/trees/"):
                    sha = path.rsplit("/", 1)[-1]
                    document = server.trees.get(sha)
                    if document is None:
                        self.send_error(404)
                        return
                    body = json.dumps(document).encode()
                elif path.startswith(f"/{REPO}/"):
                    parts = path.strip("/").split("/")
                    if len(parts) < 5 or parts[3] != "shaft-skills":
                        self.send_error(404)
                        return
                    commit = parts[2]
                    relative = "/".join(parts[4:])
                    content = server.by_commit.get(commit, {}).get(relative)
                    if content is None or getattr(server, "corrupt", False):
                        if content is not None and server.corrupt:
                            content = b"tampered\n" + content
                        else:
                            self.send_error(404)
                            return
                    body = content
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                return

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        return f"http://127.0.0.1:{self.port}"

    def close(self):
        self.httpd.shutdown()


def _pom(version: str, artifact: str = "SHAFT_ENGINE") -> str:
    return f"""<project>
      <dependencies>
        <dependency>
          <groupId>io.github.shafthq</groupId>
          <artifactId>{artifact}</artifactId>
          <version>{version}</version>
        </dependency>
      </dependencies>
    </project>
    """


def _prepare(project: Path, source: Path, origin: str, sync, monkeypatch, removed=None, requested=None):
    monkeypatch.setenv("CHAOS_ENGINE_CACHE_DIR", str(project / ".cache"))
    monkeypatch.setenv("CHAOS_ENGINE_SHAFT_FIXTURE_ORIGIN", origin)
    monkeypatch.delenv("CHAOS_ENGINE_DRY_RUN", raising=False)
    monkeypatch.delenv("CHAOS_ENGINE_OFFLINE", raising=False)
    monkeypatch.delenv("CHAOS_ENGINE_NO_AUTO_ADDONS", raising=False)
    monkeypatch.delenv("CHAOS_ENGINE_SHAFT_SKILLS_VERSION", raising=False)
    return sync.prepare(project, source, __import__("urllib.request", fromlist=["urlopen"]).urlopen, requested=requested, removed=removed)


def test_maven_gradle_parent_and_caps(tmp_path, monkeypatch):
    _boot, detect, sync, install = _modules()
    server = _ShaftServer(_boot)
    origin = server.start()
    try:
        project = tmp_path / "user"
        project.mkdir()
        (project / "pom.xml").write_text(_pom(NEW), encoding="utf-8")
        source = tmp_path / "source"
        source.mkdir()
        result = _prepare(project, source, origin, sync, monkeypatch)
        receipt = json.loads((source / "addons" / "shaft-engine-users" / "receipt.json").read_text(encoding="utf-8"))
        files = list((source / "addons" / "shaft-engine-users").rglob("*"))
        payloads = [path for path in files if path.is_file() and path.name not in {"addon.json", "receipt.json"}]
        assert len(payloads) == 119
        assert receipt["tag"] == NEW
        assert receipt["version"] == NEW
        assert receipt["detectedFrom"] == "pom.xml"
        distribution, selected = install.plan_install(project, source)
        assert distribution == "portable"
        assert "shaft-engine-users" in selected
        assert "shaft-core-developers" not in selected
        for artifact in ("shaft-engine", "shaft-bom"):
            other = tmp_path / artifact
            other.mkdir()
            (other / "pom.xml").write_text(_pom(OLD, artifact), encoding="utf-8")
            assert detect.detect(other)["version"] == OLD
        parent = tmp_path / "parent"
        child = parent / "child"
        child.mkdir(parents=True)
        (parent / "pom.xml").write_text(
            "<project><properties><shaft.version>10.4.20261108</shaft.version></properties></project>",
            encoding="utf-8",
        )
        (child / "pom.xml").write_text(
            """<project>
              <parent><relativePath>..</relativePath></parent>
              <dependencies>
                <dependency>
                  <groupId>io.github.shafthq</groupId>
                  <artifactId>SHAFT_ENGINE</artifactId>
                  <version>${shaft.version}</version>
                </dependency>
              </dependencies>
            </project>""",
            encoding="utf-8",
        )
        assert detect.detect(child)["version"] == OLD
        modules = tmp_path / "modules"
        (modules / "module-a").mkdir(parents=True)
        (modules / "pom.xml").write_text("<project><modules><module>module-a</module></modules></project>", encoding="utf-8")
        (modules / "module-a" / "pom.xml").write_text(_pom(NEW), encoding="utf-8")
        assert detect.detect(modules)["kind"] == "user"
        deep = tmp_path / "deep"
        current = deep
        text = "<project><modules><module>m</module></modules></project>"
        current.mkdir()
        for depth in range(3):
            (current / "pom.xml").write_text(text, encoding="utf-8")
            current = current / "m"
            current.mkdir()
        (current / "pom.xml").write_text(_pom(NEW), encoding="utf-8")
        assert detect.detect(deep)["kind"] == "none"
        capped = tmp_path / "capped"
        capped.mkdir()
        modules_xml = "".join(f"<module>m{index}</module>" for index in range(60))
        (capped / "pom.xml").write_text(f"<project><modules>{modules_xml}</modules></project>", encoding="utf-8")
        for index in range(60):
            folder = capped / f"m{index}"
            folder.mkdir()
            (folder / "pom.xml").write_text(_pom(NEW) if index == 59 else "<project></project>", encoding="utf-8")
        read = detect.iter_poms(capped)
        assert len(read) == 50
        assert not any(path.name == "pom.xml" and path.parent.name == "m59" for path, _text in read)
        commented = tmp_path / "comment"
        commented.mkdir()
        (commented / "pom.xml").write_text(
            "<!-- <dependency><groupId>io.github.shafthq</groupId><artifactId>SHAFT_ENGINE</artifactId><version>10.4.20261112</version></dependency> -->",
            encoding="utf-8",
        )
        (commented / "src").mkdir()
        (commented / "src" / "App.java").write_text("import com.shaft.tools;\n", encoding="utf-8")
        assert detect.detect(commented)["kind"] == "none"
        gradle = tmp_path / "gradle"
        gradle.mkdir()
        (gradle / "build.gradle.kts").write_text(
            'dependencies { testImplementation("io.github.shafthq:SHAFT_ENGINE:10.4.20261108") }\n',
            encoding="utf-8",
        )
        assert detect.detect(gradle)["version"] == OLD
        catalog = tmp_path / "catalog"
        (catalog / "gradle").mkdir(parents=True)
        (catalog / "gradle" / "libs.versions.toml").write_text(
            '[versions]\nshaft = "10.4.20261108"\n[libraries]\nshaft = { module = "io.github.shafthq:SHAFT_ENGINE", version.ref = "shaft" }\n',
            encoding="utf-8",
        )
        assert detect.detect(catalog)["version"] == OLD
        mixed = tmp_path / "mixed"
        mixed.mkdir()
        (mixed / "pom.xml").write_text(_pom("${missing.prop}"), encoding="utf-8")
        (mixed / "build.gradle").write_text(
            'implementation "io.github.shafthq:SHAFT_ENGINE:10.4.20261112"\n',
            encoding="utf-8",
        )
        assert detect.detect(mixed)["version"] == NEW
        plain = tmp_path / "plain"
        plain.mkdir()
        calls = len(server.hits)
        assert detect.detect(plain)["kind"] == "none"
        _prepare(plain, tmp_path / "plain-source", origin, sync, monkeypatch)
        assert len(server.hits) == calls
    finally:
        server.close()


def test_unknown_version_then_reuse_and_upgrade_downloads(tmp_path, monkeypatch, capsys):
    boot, _detect, sync, _install = _modules()
    server = _ShaftServer(boot)
    origin = server.start()
    try:
        project = tmp_path / "snap"
        project.mkdir()
        (project / "pom.xml").write_text(_pom("1.0-SNAPSHOT"), encoding="utf-8")
        source = tmp_path / "source"
        source.mkdir()
        _prepare(project, source, origin, sync, monkeypatch)
        warning = capsys.readouterr().out
        assert "releases/latest" not in warning or NEW in warning
        assert f"using {NEW}" in warning
        receipt = json.loads((project / ".chaos-engine" / "addons" / "shaft-engine-users" / "receipt.json").read_text(encoding="utf-8")) if False else json.loads((source / "addons" / "shaft-engine-users" / "receipt.json").read_text(encoding="utf-8"))
        assert receipt["tag"] == NEW
        installed = project / ".chaos-engine" / "addons" / "shaft-engine-users"
        installed.mkdir(parents=True)
        for path in (source / "addons" / "shaft-engine-users").rglob("*"):
            if path.is_file():
                target = installed / path.relative_to(source / "addons" / "shaft-engine-users")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(path.read_bytes())
        before = len(server.hits)
        _prepare(project, tmp_path / "source2", origin, sync, monkeypatch)
        assert sync.prepare.downloads == 0
        blob_hits = [hit for hit in server.hits[before:] if f"/{REPO}/" in hit and "/git/" not in hit and "/releases/" not in hit]
        assert blob_hits == []
        upgraded = tmp_path / "upgrade"
        upgraded.mkdir()
        (upgraded / "pom.xml").write_text(_pom(OLD), encoding="utf-8")
        first = tmp_path / "upgrade-source"
        first.mkdir()
        _prepare(upgraded, first, origin, sync, monkeypatch)
        home = upgraded / ".chaos-engine" / "addons" / "shaft-engine-users"
        for path in (first / "addons" / "shaft-engine-users").rglob("*"):
            if path.is_file():
                target = home / path.relative_to(first / "addons" / "shaft-engine-users")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(path.read_bytes())
        (upgraded / "pom.xml").write_text(_pom(NEW), encoding="utf-8")
        second = tmp_path / "upgrade-next"
        second.mkdir()
        before = len([hit for hit in server.hits if "/git/" not in hit and "/releases/" not in hit])
        capsys.readouterr()
        _prepare(upgraded, second, origin, sync, monkeypatch)
        summary = capsys.readouterr().out
        assert f"SHAFT skills {NEW} (pom.xml): 3 updated, 116 unchanged" in summary
        assert sync.prepare.downloads == 3
        for path in (second / "addons" / "shaft-engine-users").rglob("*"):
            if path.is_file():
                target = home / path.relative_to(second / "addons" / "shaft-engine-users")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(path.read_bytes())
        _prepare(upgraded, tmp_path / "upgrade-again", origin, sync, monkeypatch)
        assert sync.prepare.downloads == 0
    finally:
        server.close()


def test_dry_run_line_opt_out_doctor_and_failures(tmp_path, monkeypatch, capsys):
    boot, detect, sync, install = _modules()
    server = _ShaftServer(boot)
    origin = server.start()
    try:
        project = tmp_path / "dry"
        project.mkdir()
        (project / "pom.xml").write_text(_pom(NEW), encoding="utf-8")
        monkeypatch.setenv("CHAOS_ENGINE_CACHE_DIR", str(tmp_path / "cache"))
        monkeypatch.setenv("CHAOS_ENGINE_DRY_RUN", "1")
        monkeypatch.setenv("CHAOS_ENGINE_SHAFT_FIXTURE_ORIGIN", origin)
        sync.prepare(project, tmp_path / "dry-source", boot.urllib.request.urlopen)
        assert capsys.readouterr().out.strip() == f"SHAFT {NEW} from pom.xml → shaft-engine-users @ {NEW} (119 files)"
        assert not (tmp_path / "dry-source" / "addons").exists()
        core = tmp_path / "core"
        skills = core / "shaft-skills"
        for relative, content in _files("local").items():
            if relative.startswith("scripts/") or relative.startswith("shaft-upgrader") or relative == "post-install.json":
                continue
            target = skills / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        (core / "pom.xml").write_text("<project><artifactId>shaft-parent</artifactId></project>", encoding="utf-8")
        calls = len(server.hits)
        monkeypatch.delenv("CHAOS_ENGINE_DRY_RUN", raising=False)
        sync.prepare(core, tmp_path / "core-source", boot.urllib.request.urlopen)
        assert len(server.hits) == calls
        assert (tmp_path / "core-source" / "addons" / "shaft-core-developers" / "ce-pack" / "profile.json").is_file()
        assert not (tmp_path / "core-source" / "addons" / "shaft-engine-users" / "post-install.json").exists()
        distribution, selected = install.plan_install(core, tmp_path / "core-source")
        assert distribution == "repository"
        assert "shaft-core-developers" in selected
        edited = skills / "shaft-cli" / "SKILL.md"
        old = edited.read_bytes()
        home = core / ".chaos-engine" / "addons" / "shaft-engine-users" / "shaft-cli"
        home.mkdir(parents=True)
        (home / "SKILL.md").write_bytes(old)
        edited.write_bytes(b"local edit\n")
        sync.prepare(core, tmp_path / "core-edited", boot.urllib.request.urlopen)
        assert (tmp_path / "core-edited" / "addons" / "shaft-engine-users" / "shaft-cli" / "SKILL.md").read_bytes() == b"local edit\n"
        kept = list((core / ".chaos-engine-state" / "kept-edits").rglob("SKILL.md"))
        assert kept and kept[0].read_bytes() == old
        capsys.readouterr()
        install.plan_install(core, tmp_path / "core-source", set(), {"shaft-engine-users"})
        notice = capsys.readouterr().out
        assert notice.count("ChaosEngine: --without-shaft-engine-users also drops shaft-core-developers") == 1
        denied = core / ".chaos-engine-state" / "addon-denials.json"
        assert "shaft-engine-users" in denied.read_text(encoding="utf-8")
        again, selected = install.plan_install(core, tmp_path / "core-source")
        assert "shaft-engine-users" not in selected
        assert "shaft-core-developers" not in selected
        monkeypatch.setenv("CHAOS_ENGINE_NO_AUTO_ADDONS", "1")
        info = detect.shaft_auto(project, {"shaft-engine-users"})
        assert info == (set(), set())
        monkeypatch.delenv("CHAOS_ENGINE_NO_AUTO_ADDONS", raising=False)
        user = tmp_path / "gone"
        user.mkdir()
        (user / "pom.xml").write_text("<project><artifactId>app</artifactId></project>", encoding="utf-8")
        previous = user / ".chaos-engine" / "addons" / "shaft-engine-users" / "shaft-cli"
        previous.mkdir(parents=True)
        (previous / "SKILL.md").write_bytes(b"edited skill\n")
        (previous.parent / "addon.json").write_text("{}", encoding="utf-8")
        (previous.parent / "receipt.json").write_text(
            json.dumps({"files": {"shaft-cli/SKILL.md": boot.payload_sha256(b"original\n")}}) + "\n",
            encoding="utf-8",
        )
        sync.prepare(user, tmp_path / "gone-source", boot.urllib.request.urlopen)
        kept = list((user / ".chaos-engine-state" / "kept-edits").rglob("SKILL.md"))
        assert kept and kept[0].read_bytes() == b"edited skill\n"
        _distribution, names = install.plan_install(user, tmp_path / "gone-source")
        assert "shaft-engine-users" not in names
        doctor_project = tmp_path / "doctor"
        doctor_project.mkdir()
        (doctor_project / "pom.xml").write_text(_pom(NEW), encoding="utf-8")
        receipt_path = doctor_project / ".chaos-engine" / "addons" / "shaft-engine-users"
        receipt_path.mkdir(parents=True)
        (receipt_path / "receipt.json").write_text(json.dumps({"tag": OLD, "version": OLD}) + "\n", encoding="utf-8")
        note = detect.doctor_note(doctor_project)
        rendered = install.format_health_report({"status": "healthy", "kind": "doctor", "shaftSkills": note})
        assert f"[warning] SHAFT project version {NEW} differs from installed skills {OLD}" in rendered
        assert f"fix-next: rerun the install one-liner or pass --shaft-skills-version {NEW}" in rendered
        monkeypatch.delenv("CHAOS_ENGINE_NO_AUTO_ADDONS", raising=False)
        down = tmp_path / "down"
        down.mkdir()
        (down / "pom.xml").write_text(_pom(NEW), encoding="utf-8")
        (down / ".chaos-engine" / "addons" / "shaft-engine-users").mkdir(parents=True)
        (down / ".chaos-engine" / "addons" / "shaft-engine-users" / "shaft-cli").mkdir()
        (down / ".chaos-engine" / "addons" / "shaft-engine-users" / "shaft-cli" / "SKILL.md").write_bytes(b"kept\n")
        monkeypatch.setenv("CHAOS_ENGINE_SHAFT_FIXTURE_ORIGIN", "http://127.0.0.1:1")
        kept_result = sync.prepare(down, tmp_path / "down-source", boot.urllib.request.urlopen)
        assert kept_result["status"] == "kept"
        assert "kept" in capsys.readouterr().out
        assert (tmp_path / "down-source" / "addons" / "shaft-engine-users" / "shaft-cli" / "SKILL.md").read_bytes() == b"kept\n"
        unsafe = tmp_path / "unsafe"
        unsafe.mkdir()
        (unsafe / "pom.xml").write_text(_pom("../x"), encoding="utf-8")
        with pytest.raises(ValueError, match="CE-INSTALL-FAILED"):
            sync.prepare(unsafe, tmp_path / "unsafe-source", boot.urllib.request.urlopen)
        (unsafe / "pom.xml").write_text(_pom("10.4.x"), encoding="utf-8")
        with pytest.raises(ValueError, match="CE-INSTALL-FAILED"):
            sync.prepare(unsafe, tmp_path / "unsafe-source", boot.urllib.request.urlopen)
        tamper = tmp_path / "tamper"
        tamper.mkdir()
        (tamper / "pom.xml").write_text(_pom(NEW), encoding="utf-8")
        marker = tamper / ".chaos-engine" / "addons" / "shaft-engine-users" / "shaft-cli"
        marker.mkdir(parents=True)
        (marker / "SKILL.md").write_bytes(b"untouched\n")
        monkeypatch.setenv("CHAOS_ENGINE_SHAFT_FIXTURE_ORIGIN", origin)
        server.corrupt = True
        with pytest.raises(ValueError, match="CE-INSTALL-FAILED"):
            sync.prepare(tamper, tmp_path / "tamper-source", boot.urllib.request.urlopen)
        assert (marker / "SKILL.md").read_bytes() == b"untouched\n"
        server.corrupt = False
    finally:
        server.close()


def test_install_sh_pins_skills_and_leaves_host_skill_dirs(tmp_path, monkeypatch):
    boot, _detect, _sync, _install = _modules()
    server = _ShaftServer(boot)
    origin = server.start()
    project = tmp_path / "app"
    project.mkdir()
    (project / "pom.xml").write_text(_pom(NEW), encoding="utf-8")
    agents = project / ".agents" / "skills" / "local.md"
    claude = project / ".claude" / "skills" / "local.md"
    agents.parent.mkdir(parents=True)
    claude.parent.mkdir(parents=True)
    agents.write_bytes(b"agents\n")
    claude.write_bytes(b"claude\n")
    env = os.environ.copy()
    env.update(
        {
            "CI": "1",
            "CHAOS_ENGINE_SKIP_TOOLS": "1",
            "CHAOS_ENGINE_NO_INPUT": "1",
            "CHAOS_ENGINE_LOCAL_CLONE": str(ROOT),
            "CHAOS_ENGINE_FIXTURE_ORIGIN": "http://127.0.0.1:1",
            "CHAOS_ENGINE_CACHE_DIR": str(tmp_path / "cache"),
            "CHAOS_ENGINE_SHAFT_FIXTURE_ORIGIN": origin,
        }
    )
    try:
        completed = subprocess.run(
            [posix_bash(), str(ROOT / "install.sh")],
            cwd=project,
            env=env,
            capture_output=True,
            text=True,
            timeout=240,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr[-2000:]
        receipt = json.loads((project / ".chaos-engine" / "addons" / "shaft-engine-users" / "receipt.json").read_text(encoding="utf-8"))
        assert receipt["tag"] == NEW
        assert agents.read_bytes() == b"agents\n"
        assert claude.read_bytes() == b"claude\n"
        assert not any("install_shaft_agentic_tools.py" in hit for hit in server.hits)
        assert not any(hit.endswith("/scripts/mcp/install.sh") or hit.endswith("/scripts/mcp/install.ps1") for hit in server.hits)
        assert not any("shaft-upgrader" in hit for hit in server.hits)
        assert "SHAFT_ENGINE" not in completed.stderr or "chaos-engine/bootstrap.py" not in completed.stderr
    finally:
        server.close()


def test_harness_fixture_origin_does_not_capture_shaft_downloads(monkeypatch):
    _boot, _detect, sync, _install = _modules()
    seen: list[str] = []
    headers: list[str | None] = []

    def opener(request, timeout=60):
        seen.append(request.full_url)
        headers.append(request.get_header("Authorization"))
        raise urllib.error.URLError("stop")

    monkeypatch.setenv("CHAOS_ENGINE_FIXTURE_ORIGIN", "http://127.0.0.1:1")
    monkeypatch.delenv("CHAOS_ENGINE_SHAFT_FIXTURE_ORIGIN", raising=False)
    monkeypatch.setattr(sync.bootstrap, "github_request_token", lambda: ("shaft-test-token", "test"))
    url = (
        "https://raw.githubusercontent.com/ShaftHQ/SHAFT_ENGINE/"
        "10.4.20261108/shaft-skills/ce-addons/shaft-engine-users/addon.json"
    )
    with pytest.raises(urllib.error.URLError):
        sync._read(opener, url)
    assert seen == [url]
    assert headers == ["Bearer shaft-test-token"]


_ABSENT = object()
_MISSING_SKILLS = {
    "warning": (
        "SHAFT skills are not installed. "
        "Run the installer or pass --with-shaft-engine-users."
    ),
    "fixNext": "fix-next: rerun the installer or pass --with-shaft-engine-users",
}


class DoctorNoteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        cls.sync = _modules()[2]

    def _project(self, *, version=None, tag=_ABSENT, denied=False, kind="user"):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        project = Path(directory.name)
        if kind == "empty":
            return project
        if kind == "plain":
            (project / "pom.xml").write_text(
                "<project><artifactId>app</artifactId></project>\n",
                encoding="utf-8",
            )
        elif kind == "core":
            (project / "pom.xml").write_text(
                "<project><artifactId>shaft-parent</artifactId></project>\n",
                encoding="utf-8",
            )
        else:
            (project / "pom.xml").write_text(_pom(version or NEW), encoding="utf-8")
            if tag is not _ABSENT:
                receipt = project / ".chaos-engine" / "addons" / "shaft-engine-users"
                receipt.mkdir(parents=True)
                (receipt / "receipt.json").write_text(
                    json.dumps({"tag": tag}) + "\n",
                    encoding="utf-8",
                )
        if denied:
            state = project / ".chaos-engine-state"
            state.mkdir(parents=True)
            (state / "addon-denials.json").write_text(
                json.dumps({"denied": ["shaft-engine-users"]}) + "\n",
                encoding="utf-8",
            )
        return project

    def test_missing_skills_warn_to_install(self):
        self.assertEqual(_MISSING_SKILLS, self.sync.doctor_note(self._project()))
        self.assertEqual(_MISSING_SKILLS, self.sync.doctor_note(self._project(tag="")))
        self.assertEqual(
            _MISSING_SKILLS,
            self.sync.doctor_note(self._project(version="1.0-SNAPSHOT")),
        )

    def test_denied_and_kind_none_stay_silent(self):
        self.assertIsNone(self.sync.doctor_note(self._project(denied=True)))
        self.assertIsNone(self.sync.doctor_note(self._project(tag="", denied=True)))
        self.assertIsNone(self.sync.doctor_note(self._project(kind="plain")))
        self.assertIsNone(self.sync.doctor_note(self._project(kind="empty")))
        self.assertIsNone(self.sync.doctor_note(self._project(kind="core")))
        self.assertIsNone(self.sync.doctor_note(self._project(kind="plain", denied=True)))

    def test_version_mismatch_matches_detect_including_when_denied(self):
        project = self._project(version=NEW, tag=OLD)
        note = self.sync.doctor_note(project)
        self.assertEqual(self.sync.detect.doctor_note(project), note)
        self.assertEqual(
            f"SHAFT project version {NEW} differs from installed skills {OLD}",
            note["warning"],
        )
        self.assertEqual(
            "fix-next: rerun the install one-liner or pass --shaft-skills-version " + NEW,
            note["fixNext"],
        )
        denied = self._project(version=NEW, tag=OLD, denied=True)
        denied_note = self.sync.doctor_note(denied)
        self.assertEqual(self.sync.detect.doctor_note(denied), denied_note)
        self.assertEqual(note["warning"], denied_note["warning"])
        self.assertEqual(note["fixNext"], denied_note["fixNext"])

    def test_matching_tag_and_unknown_version_do_not_warn_of_mismatch(self):
        self.assertIsNone(self.sync.doctor_note(self._project(version=NEW, tag=NEW)))
        unknown = self._project(version="1.0-SNAPSHOT", tag=OLD)
        self.assertIsNone(self.sync.doctor_note(unknown))
        self.assertIsNone(self.sync.detect.doctor_note(unknown))
