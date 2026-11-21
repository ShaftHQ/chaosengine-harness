"""Installer scenarios through the shipped install.sh entry point.

Each case starts from a clean project and runs ``install.sh`` (or the
installed ``install.py`` for doctor, addons, verify, and uninstall).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bash_path import posix_bash  # noqa: E402
from test_issue33_shaft import (  # noqa: E402
    NEW,
    OLD,
    REPO,
    ROOT,
    _ShaftServer,
    _modules,
    _pom,
)

OFFER = {
    "schemaVersion": 1,
    "framework": "SHAFT_ENGINE",
    "detect": {"manifest": "pom.xml", "groupId": "io.github.shafthq"},
    "agenticInstall": {
        "posix": "touch agentic-offer-ran",
        "nt": "New-Item -ItemType File agentic-offer-ran | Out-Null",
    },
}
DROP_LINE = "ChaosEngine: --without-shaft-engine-users also drops shaft-core-developers"
OFFER_LINE = "ChaosEngine: SHAFT_ENGINE agentic installer was not run (default No)."
PROFILE = {
    "schemaVersion": 1,
    "name": "shaft",
    "repository": "ShaftHQ/SHAFT_ENGINE",
    "defaultBranch": "main",
    "postInstall": {
        "script": "scripts/mcp/install_shaft_agentic_tools.py",
        "args": ["--install-shaft-skills", "--install-shaft-cli"],
    },
}


def _path_without_agent_clis() -> str:
    """Hide host Claude/Codex so doctor does not demand client activation.

    Scenario installs skip tool provisioning and do not activate plugins.
    A detected CLI with no marketplace for this temp project is recovery-required.
    """
    kept: list[str] = []
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if not entry:
            continue
        directory = Path(entry)
        if (directory / "claude").exists() or (directory / "codex").exists():
            continue
        kept.append(entry)
    return os.pathsep.join(kept) or "/usr/bin:/bin"


def _env(tmp_path: Path, origin: str) -> dict[str, str]:
    env = os.environ.copy()
    for key in (
        "CHAOS_ENGINE_ADDONS",
        "CHAOS_ENGINE_NO_AUTO_ADDONS",
        "CHAOS_ENGINE_DRY_RUN",
        "CHAOS_ENGINE_SHAFT_SKILLS_VERSION",
        "CHAOS_ENGINE_KEEP_EDITS",
        "CHAOS_ENGINE_PREREQUISITES",
        "CHAOS_ENGINE_OFFLINE",
    ):
        env.pop(key, None)
    env.update(
        {
            "CI": "1",
            "CHAOS_ENGINE_SKIP_TOOLS": "1",
            "CHAOS_ENGINE_NO_INPUT": "1",
            "CHAOS_ENGINE_LOCAL_CLONE": str(ROOT),
            "CHAOS_ENGINE_FIXTURE_ORIGIN": "http://127.0.0.1:1",
            "CHAOS_ENGINE_CACHE_DIR": str(tmp_path / "cache"),
            "CHAOS_ENGINE_SHAFT_FIXTURE_ORIGIN": origin,
            "PATH": _path_without_agent_clis(),
        }
    )
    return env


def _run(project: Path, args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    # A cp1252 console decodes the child's UTF-8 arrow unless the child is forced to UTF-8.
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return subprocess.run(
        [posix_bash(), str(ROOT / "install.sh"), *args],
        cwd=project,
        env=env,
        capture_output=True,
        encoding="utf-8",
        timeout=300,
        check=False,
    )


def _cli(project: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    if env is None:
        env = os.environ.copy()
        env["PATH"] = _path_without_agent_clis()
    return subprocess.run(
        [sys.executable, str(project / ".chaos-engine" / "install.py"), *args, "--project", str(project)],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


def _seed_host_skills(project: Path) -> tuple[Path, Path]:
    agents = project / ".agents" / "skills" / "local.md"
    claude = project / ".claude" / "skills" / "shaft-cli" / "SKILL.md"
    agents.parent.mkdir(parents=True)
    claude.parent.mkdir(parents=True)
    agents.write_bytes(b"agents\n")
    claude.write_bytes(b"claude-shaft\n")
    return agents, claude


def _assert_host_skills(agents: Path, claude: Path) -> None:
    assert agents.read_bytes() == b"agents\n"
    assert claude.read_bytes() == b"claude-shaft\n"


def _distribution(project: Path) -> str:
    manifest = json.loads((project / ".chaos-engine" / "manifest.json").read_text(encoding="utf-8"))
    return str(manifest["distribution"]["id"])


def _doctor(project: Path) -> dict:
    completed = _cli(project, "doctor", "--json")
    assert completed.returncode == 0, completed.stdout[-2500:] + completed.stderr[-2500:]
    document = json.loads(completed.stdout)
    if document.get("status") != "healthy":
        rows = {
            name: item.get("status")
            for name, item in (document.get("components") or {}).items()
            if isinstance(item, dict) and item.get("status") != "healthy"
        }
        pytest.fail(f"doctor {document.get('status')}: {rows}")
    return document


def _runtime_provision_argv(argv: object) -> bool:
    """True when a doctor child is `python -m venv` or ensurepip (#77)."""
    parts = [str(part) for part in argv] if isinstance(argv, (list, tuple)) else [str(argv)]
    if "ensurepip" in parts:
        return True
    return "-m" in parts and "venv" in parts


def _load_installed_install(project: Path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "ce_installed_doctor_venv", project / ".chaos-engine" / "install.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_skip_tools_doctor_json_does_not_launch_venv(tmp_path, monkeypatch, capsys):
    """doctor --json on a skip-tools install stays healthy and does not provision (#77)."""
    project = tmp_path / "plain"
    project.mkdir()
    completed = _run(project, ["--hosts", "grok"], _env(tmp_path, "http://127.0.0.1:1"))
    _assert_ran(completed)
    launched: list[list[str]] = []
    real_run = subprocess.run

    def run(argv, *args, **kwargs):
        parts = [str(part) for part in argv] if isinstance(argv, (list, tuple)) else [str(argv)]
        launched.append(parts)
        if _runtime_provision_argv(parts):
            return subprocess.CompletedProcess(argv, 1, "", "blocked-venv")
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setenv("PATH", _path_without_agent_clis())
    monkeypatch.setattr(
        sys,
        "argv",
        [str(project / ".chaos-engine" / "install.py"), "doctor", "--json", "--project", str(project)],
    )
    code = _load_installed_install(project).main()
    captured = capsys.readouterr()
    provisioned = [parts for parts in launched if _runtime_provision_argv(parts)]
    assert provisioned == [], provisioned
    assert code == 0, captured.out[-2500:] + captured.err[-2500:]
    document = json.loads(captured.out)
    assert document["status"] == "healthy"


def test_skip_tools_doctor_is_not_healthy_without_palace_sqlite(tmp_path, monkeypatch, capsys):
    """A palace directory without sqlite_exact.sqlite3 still fails doctor (L84)."""
    project = tmp_path / "plain"
    project.mkdir()
    completed = _run(project, ["--hosts", "grok"], _env(tmp_path, "http://127.0.0.1:1"))
    _assert_ran(completed)
    (project / ".chaos-engine-state" / "mempalace").mkdir(parents=True)
    launched: list[list[str]] = []
    real_run = subprocess.run

    def run(argv, *args, **kwargs):
        parts = [str(part) for part in argv] if isinstance(argv, (list, tuple)) else [str(argv)]
        launched.append(parts)
        if _runtime_provision_argv(parts):
            return subprocess.CompletedProcess(argv, 1, "", "blocked-venv")
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setenv("PATH", _path_without_agent_clis())
    monkeypatch.setattr(
        sys,
        "argv",
        [str(project / ".chaos-engine" / "install.py"), "doctor", "--json", "--project", str(project)],
    )
    install = _load_installed_install(project)
    code = install.main()
    captured = capsys.readouterr()
    provisioned = [parts for parts in launched if _runtime_provision_argv(parts)]
    assert provisioned == [], provisioned
    document = json.loads(captured.out)
    assert document["status"] != "healthy"
    assert code != 0
    mempalace = document["components"]["mempalace"]
    assert mempalace["status"] == "invalid"
    assert install._component_severity(mempalace) != "ok"
    assert install.component_fix_next("mempalace", mempalace)


def test_skip_tools_absent_stores_are_not_repair_warnings(tmp_path, monkeypatch, capsys):
    """Absent memory, mempalace, and graphify stay quiet after an intentional skip."""
    project = tmp_path / "plain"
    project.mkdir()
    completed = _run(project, ["--hosts", "grok"], _env(tmp_path, "http://127.0.0.1:1"))
    _assert_ran(completed)
    launched: list[list[str]] = []
    real_run = subprocess.run

    def run(argv, *args, **kwargs):
        parts = [str(part) for part in argv] if isinstance(argv, (list, tuple)) else [str(argv)]
        launched.append(parts)
        if _runtime_provision_argv(parts):
            return subprocess.CompletedProcess(argv, 1, "", "blocked-venv")
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setenv("PATH", _path_without_agent_clis())
    monkeypatch.setattr(
        sys,
        "argv",
        [str(project / ".chaos-engine" / "install.py"), "doctor", "--json", "--project", str(project)],
    )
    install = _load_installed_install(project)
    code = install.main()
    captured = capsys.readouterr()
    provisioned = [parts for parts in launched if _runtime_provision_argv(parts)]
    assert provisioned == [], provisioned
    assert code == 0, captured.out[-2500:] + captured.err[-2500:]
    document = json.loads(captured.out)
    expected = {
        "memory": "advisory",
        "mempalace": "advisory",
        "graphify": "required-when-indexed",
    }
    for name, impact in expected.items():
        item = document["components"][name]
        assert item["status"] == "absent", name
        assert item["taskImpact"] == impact, name
        assert item["intentionalSkip"] is True, name
        assert install._component_severity(item) == "ok", name
        assert install.component_fix_next(name, item) is None, name


def _addons(project: Path) -> dict:
    completed = _cli(project, "addons", "--json")
    assert completed.returncode == 0, completed.stderr[-2000:]
    return json.loads(completed.stdout)


def _core_tree(project: Path, *, exit_code: int = 0) -> None:
    pack = project / "shaft-skills" / "ce-pack"
    pack.mkdir(parents=True)
    (pack / "profile.json").write_text(json.dumps(PROFILE) + "\n", encoding="utf-8")
    (pack / "entrypoint.md").write_text("entrypoint\n", encoding="utf-8")
    skill = project / "shaft-skills" / "shaft-cli"
    skill.mkdir()
    (skill / "SKILL.md").write_text("local skill\n", encoding="utf-8")
    script = project / "scripts" / "mcp" / "install_shaft_agentic_tools.py"
    script.parent.mkdir(parents=True)
    script.write_text(
        textwrap.dedent(
            f"""\
            import pathlib, sys
            pathlib.Path("agentic-tools-ran").write_text(" ".join(sys.argv[1:]) + "\\n", encoding="utf-8")
            raise SystemExit({exit_code})
            """
        ),
        encoding="utf-8",
    )
    (project / "pom.xml").write_text(
        "<project><artifactId>shaft-parent</artifactId></project>\n",
        encoding="utf-8",
    )


def _assert_ran(completed: subprocess.CompletedProcess[str], code: int = 0) -> None:
    assert completed.returncode == code, completed.stderr[-2500:] + completed.stdout[-1500:]


def test_offer_restores_addon_bytes_and_ci_does_not_run(tmp_path):
    """The consumer offer defaults to No, and accepting it puts the add-on tree back."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("ce_offer_prereq", ROOT / "runtime" / "prerequisites.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    project = tmp_path / "offer"
    project.mkdir()
    addon = project / ".chaos-engine" / "addons" / "shaft-engine-users"
    addon.mkdir(parents=True)
    (addon / "SKILL.md").write_bytes(b"skill\n")
    (project / "pom.xml").write_text(_pom(OLD), encoding="utf-8")
    calls = []

    def runner(argv, **_kwargs):
        calls.append(argv)
        (addon / "SKILL.md").write_bytes(b"clobbered\n")
        (addon / "extra.txt").write_bytes(b"x\n")
        return type("Done", (), {"returncode": 0})()

    declined = module.framework_steps(
        project, OFFER, install_ok=False, env={"CHAOS_ENGINE_PREREQUISITES": "install"},
        runner=runner, ask=lambda *_args, **_kwargs: False,
    )
    assert declined["agenticInstall"] == "declined"
    assert calls == []
    accepted = module.framework_steps(
        project, OFFER, install_ok=False, env={"CHAOS_ENGINE_PREREQUISITES": "install"},
        runner=runner, ask=lambda *_args, **_kwargs: True,
    )
    assert accepted["agenticInstall"] == "installed"
    assert (addon / "SKILL.md").read_bytes() == b"skill\n"
    assert not (addon / "extra.txt").exists()
    calls.clear()
    reported = module.framework_steps(
        project, OFFER, install_ok=True, env={"CI": "1"}, runner=runner, ask=lambda *_a, **_k: True,
    )
    assert reported["agenticInstall"] == "reported"
    assert calls == []


def test_maven_property_version_offers_and_defaults_to_no(tmp_path, capsys):
    """HRSD pins shaft.version in properties and imports it from the BOM."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("ce_offer_property", ROOT / "runtime" / "prerequisites.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    project = tmp_path / "prop"
    project.mkdir()
    (project / "pom.xml").write_text(
        textwrap.dedent(
            """\
            <project>
              <properties><shaft.version>10.4.20261108</shaft.version></properties>
              <dependencyManagement>
                <dependencies>
                  <dependency>
                    <groupId>io.github.shafthq</groupId>
                    <artifactId>shaft-bom</artifactId>
                    <version>${shaft.version}</version>
                  </dependency>
                </dependencies>
              </dependencyManagement>
              <dependencies>
                <dependency>
                  <groupId>io.github.shafthq</groupId>
                  <artifactId>shaft-engine</artifactId>
                </dependency>
              </dependencies>
            </project>
            """
        ),
        encoding="utf-8",
    )
    assert module.framework_version(project, "io.github.shafthq", "pom.xml") == "10.4.20261108"
    calls: list[object] = []
    result = module.framework_steps(
        project,
        OFFER,
        install_ok=True,
        env={"CI": "1"},
        runner=lambda argv, **_kwargs: calls.append(argv),
        ask=lambda *_args, **_kwargs: True,
    )
    assert result["version"] == "10.4.20261108"
    assert result["agenticInstall"] == "reported"
    assert calls == []
    assert OFFER_LINE in capsys.readouterr().err


def test_commented_pom_property_does_not_win(tmp_path):
    """A commented shaft.version or dependency is not the version the offer uses."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("ce_offer_comment", ROOT / "runtime" / "prerequisites.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    project = tmp_path / "commented"
    project.mkdir()
    (project / "pom.xml").write_text(
        textwrap.dedent(
            """\
            <project>
              <!-- <properties><shaft.version>1.0.20260101</shaft.version></properties> -->
              <properties><shaft.version>10.4.20261108</shaft.version></properties>
              <!--
              <dependency>
                <groupId>io.github.shafthq</groupId>
                <artifactId>shaft-engine</artifactId>
                <version>9.0.20260101</version>
              </dependency>
              -->
              <dependencies>
                <dependency>
                  <groupId>io.github.shafthq</groupId>
                  <artifactId>shaft-bom</artifactId>
                  <version>${shaft.version}</version>
                </dependency>
              </dependencies>
            </project>
            """
        ),
        encoding="utf-8",
    )
    assert module.framework_version(project, "io.github.shafthq", "pom.xml") == "10.4.20261108"


def test_offer_restores_addons_when_the_installer_raises(tmp_path):
    """A timeout or a deleted add-on tree still comes back from the snapshot."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("ce_offer_timeout", ROOT / "runtime" / "prerequisites.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    project = tmp_path / "timeout"
    project.mkdir()
    addon = project / ".chaos-engine" / "addons" / "shaft-engine-users"
    addon.mkdir(parents=True)
    (addon / "SKILL.md").write_bytes(b"skill\n")
    (project / "pom.xml").write_text(_pom(OLD), encoding="utf-8")

    def runner(argv, **_kwargs):
        skill = addon / "SKILL.md"
        skill.unlink()
        skill.symlink_to("/tmp/not-the-skill")
        shutil.rmtree(project / ".chaos-engine" / "addons")
        raise subprocess.TimeoutExpired(argv, 1)

    with pytest.raises(subprocess.TimeoutExpired):
        module.framework_steps(
            project, OFFER, install_ok=True, env={"CHAOS_ENGINE_PREREQUISITES": "install"},
            runner=runner, ask=lambda *_args, **_kwargs: True,
        )
    assert (addon / "SKILL.md").read_bytes() == b"skill\n"
    assert not (addon / "SKILL.md").is_symlink()


def _offer_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("ce_offer_review2", ROOT / "runtime" / "prerequisites.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _skill_project(tmp_path: Path, name: str) -> tuple[Path, Path]:
    project = tmp_path / name
    project.mkdir()
    addon = project / ".chaos-engine" / "addons" / "shaft-engine-users"
    addon.mkdir(parents=True)
    (addon / "SKILL.md").write_bytes(b"skill\n")
    (project / "pom.xml").write_text(_pom(OLD), encoding="utf-8")
    return project, addon


def test_offer_restore_does_not_follow_a_replaced_addons_root(tmp_path):
    """Replacing the add-on root must not write or delete through that link."""
    module = _offer_module()
    project, addon = _skill_project(tmp_path, "symlink-root")
    outside = tmp_path / "outside-root"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_bytes(b"keep\n")

    def runner(argv, **_kwargs):
        root = project / ".chaos-engine" / "addons"
        shutil.rmtree(root)
        root.symlink_to(outside, target_is_directory=True)
        (outside / "planted.txt").write_bytes(b"planted\n")
        return type("Done", (), {"returncode": 0})()

    module.framework_steps(
        project, OFFER, install_ok=True, env={"CHAOS_ENGINE_PREREQUISITES": "install"},
        runner=runner, ask=lambda *_args, **_kwargs: True,
    )
    assert secret.read_bytes() == b"keep\n"
    assert (outside / "planted.txt").read_bytes() == b"planted\n"
    restored = project / ".chaos-engine" / "addons"
    assert not restored.is_symlink()
    assert (restored / "shaft-engine-users" / "SKILL.md").read_bytes() == b"skill\n"


def test_offer_restore_replaces_a_file_and_an_intermediate_link(tmp_path):
    """A file at the add-on root, or a linked parent, is replaced in the project."""
    module = _offer_module()
    project, addon = _skill_project(tmp_path, "file-root")
    outside = tmp_path / "outside-file"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_bytes(b"keep\n")

    def replace_with_file(argv, **_kwargs):
        root = project / ".chaos-engine" / "addons"
        shutil.rmtree(root)
        root.write_bytes(b"not-a-directory")
        return type("Done", (), {"returncode": 0})()

    module.framework_steps(
        project, OFFER, install_ok=True, env={"CHAOS_ENGINE_PREREQUISITES": "install"},
        runner=replace_with_file, ask=lambda *_args, **_kwargs: True,
    )
    assert (project / ".chaos-engine" / "addons" / "shaft-engine-users" / "SKILL.md").read_bytes() == b"skill\n"

    project, addon = _skill_project(tmp_path, "linked-parent")

    def replace_parent(argv, **_kwargs):
        shutil.rmtree(addon)
        addon.symlink_to(outside, target_is_directory=True)
        return type("Done", (), {"returncode": 0})()

    module.framework_steps(
        project, OFFER, install_ok=True, env={"CHAOS_ENGINE_PREREQUISITES": "install"},
        runner=replace_parent, ask=lambda *_args, **_kwargs: True,
    )
    assert secret.read_bytes() == b"keep\n"
    restored = project / ".chaos-engine" / "addons" / "shaft-engine-users" / "SKILL.md"
    assert restored.is_file()
    assert not restored.is_symlink()
    assert restored.read_bytes() == b"skill\n"
    assert not addon.is_symlink()


def test_offline_reports_package_install_and_the_offer(tmp_path, monkeypatch):
    """Windows winget argv is a list. Offline reports it and does not run it."""
    module = _offer_module()
    project, _addon = _skill_project(tmp_path, "offline")
    calls: list[object] = []

    def runner(argv, **_kwargs):
        calls.append(list(argv))
        return type("Done", (), {"returncode": 0})()

    def version_of(_exe):
        return ()

    monkeypatch.setenv("CHAOS_ENGINE_OFFLINE", "1")
    monkeypatch.setattr(module.shutil, "which", lambda *_args, **_kwargs: None)
    report = module.provision(
        project,
        env={"CHAOS_ENGINE_PREREQUISITES": "install"},
        runner=runner,
        windows=True,
        version_of=version_of,
    )
    assert calls == []
    winget = next(row for row in report["tools"] if row["tool"] == "winget")
    assert winget["action"] == "install"
    assert winget["status"] == "reported"
    assert "Add-AppxPackage" in str(winget["command"])
    hook = dict(OFFER)
    hook["upgrader"] = "https://example.invalid/upgrader.py"
    hook["latestReleaseRepository"] = "ShaftHQ/SHAFT_ENGINE"

    def refuse(*_args, **_kwargs):
        raise AssertionError("offline offer must not ask or fetch")

    steps = module.framework_steps(
        project,
        hook,
        install_ok=True,
        env={"CHAOS_ENGINE_PREREQUISITES": "install"},
        runner=runner,
        ask=refuse,
        latest_tag=refuse,
    )
    assert steps["agenticInstall"] == "reported"
    assert steps["upgrade"] == "latest-unknown"
    assert calls == []
    monkeypatch.delenv("CHAOS_ENGINE_OFFLINE")
    module.provision(
        project,
        env={"CHAOS_ENGINE_PREREQUISITES": "install"},
        runner=runner,
        windows=True,
        version_of=version_of,
    )
    assert calls
    assert calls[0][0] == "powershell"


def test_provision_names_the_tool_on_stderr(tmp_path, monkeypatch, capsys):
    """Tool names stay off stderr. The captured trace keeps the argv (#131)."""
    module = _offer_module()
    project, _addon = _skill_project(tmp_path, "stderr-tool")

    def which(exe, *_args, **_kwargs):
        # pom.xml marks mvn. Finding the exe with no version is a skip, not an install.
        return r"C:\maven\bin\mvn.cmd" if exe == "mvn" else None

    monkeypatch.setattr(module.shutil, "which", which)
    seen: list = []

    def runner(argv, **_kwargs):
        seen.append(argv)
        return type("Done", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    report = module.provision(
        project,
        env={"CHAOS_ENGINE_PREREQUISITES": "install"},
        runner=runner,
        windows=True,
        version_of=lambda _exe: (),
    )
    captured = capsys.readouterr()
    bare = [line.strip() for line in captured.err.splitlines()]
    assert "winget" not in bare
    assert "mvn" not in bare
    assert "winget" not in captured.out
    assert "mvn" not in captured.out
    assert any(row["tool"] == "winget" for row in report["tools"])
    skipped = next(row for row in report["tools"] if row["tool"] == "mvn")
    assert skipped["action"] == "skip"
    assert seen
    assert any("winget" in str(part).lower() or "powershell" in str(part).lower() for argv in seen for part in argv)
    trace = getattr(report["tools"], "trace", None)
    assert trace
    assert any("powershell" in record["argv"] for record in trace)


def test_bootstrap_invokes_the_installed_offer(tmp_path):
    boot, *_rest = _modules()
    project = tmp_path / "wired"
    overlay = project / ".chaos-engine"
    overlay.mkdir(parents=True)
    (overlay / "prerequisites.py").write_text(
        "def run(project, *, install_ok):\n"
        "    from pathlib import Path\n"
        "    Path(project, 'offer-called').write_text('yes\\n', encoding='utf-8')\n"
        "    return {'mode': 'report'}\n",
        encoding="utf-8",
    )
    boot._run_framework_offers(project)
    assert (project / "offer-called").read_text(encoding="utf-8") == "yes\n"


def test_plain_project_stays_portable_without_shaft_addons(tmp_path):
    project = tmp_path / "plain"
    project.mkdir()
    agents, claude = _seed_host_skills(project)
    env = _env(tmp_path, "http://127.0.0.1:1")
    completed = _run(project, ["--hosts", "grok"], env)
    _assert_ran(completed)
    assert _distribution(project) == "portable"
    installed = _addons(project)["installed"]
    assert "shaft-engine-users" not in installed
    assert "shaft-core-developers" not in installed
    assert "design-skills" not in installed
    assert "grok" not in installed
    _assert_host_skills(agents, claude)
    assert not (project / "agentic-offer-ran").exists()
    assert not (project / "agentic-tools-ran").exists()
    _doctor(project)
    owned = project / ".chaos-engine" / "install.py"
    owned.write_text(owned.read_text(encoding="utf-8") + "\n# edited-by-test\n", encoding="utf-8")
    verified = _cli(project, "verify")
    assert verified.returncode == 1
    assert "install.py" in verified.stderr
    kept = _run(project, ["--keep-edits"], env)
    _assert_ran(kept, 3)
    assert "fix-next: review those files, then rerun without --keep-edits" in kept.stderr
    assert "# edited-by-test" in owned.read_text(encoding="utf-8")
    removed = _cli(project, "uninstall")
    assert removed.returncode == 0, removed.stderr[-2000:]
    assert not (project / ".chaos-engine").exists()
    saved = list((project / ".chaos-engine-state" / "kept-edits").rglob("install.py"))
    assert saved and "# edited-by-test" in saved[0].read_text(encoding="utf-8")


def test_maven_consumer_pins_project_tag_and_does_not_run_the_offer(tmp_path):
    boot, *_rest = _modules()
    server = _ShaftServer(boot, extra={"ce-addons/shaft-engine-users/post-install.json": json.dumps(OFFER).encode()})
    origin = server.start()
    project = tmp_path / "maven"
    project.mkdir()
    (project / "pom.xml").write_text(_pom(OLD), encoding="utf-8")
    agents, claude = _seed_host_skills(project)
    try:
        completed = _run(project, [], _env(tmp_path, origin))
        _assert_ran(completed)
        assert OFFER_LINE in completed.stderr
        assert not (project / "agentic-offer-ran").exists()
        assert _distribution(project) == "portable"
        installed = set(_addons(project)["installed"])
        assert "shaft-engine-users" in installed
        assert "shaft-core-developers" not in installed
        receipt = json.loads(
            (project / ".chaos-engine" / "addons" / "shaft-engine-users" / "receipt.json").read_text(encoding="utf-8")
        )
        assert receipt["tag"] == OLD
        offer = project / ".chaos-engine" / "addons" / "shaft-engine-users" / "post-install.json"
        assert json.loads(offer.read_text(encoding="utf-8"))["schemaVersion"] == 1
        skill = (project / ".chaos-engine" / "addons" / "shaft-engine-users" / "shaft-cli" / "SKILL.md").read_text(encoding="utf-8")
        assert OLD in skill
        _assert_host_skills(agents, claude)
        assert not any(hit.startswith(f"/repos/{REPO}/releases/latest") for hit in server.hits)
        _doctor(project)
        receipt["tag"] = NEW
        (project / ".chaos-engine" / "addons" / "shaft-engine-users" / "receipt.json").write_text(
            json.dumps(receipt) + "\n", encoding="utf-8"
        )
        warned = _cli(project, "doctor")
        assert warned.returncode == 0, warned.stdout[-2000:]
        text = warned.stdout + warned.stderr
        assert f"[warning] SHAFT project version {OLD} differs from installed skills {NEW}" in text
        assert f"fix-next: rerun the install one-liner or pass --shaft-skills-version {OLD}" in text
    finally:
        server.close()


def test_gradle_consumer_pins_the_coordinate_and_stays_portable(tmp_path):
    boot, *_rest = _modules()
    server = _ShaftServer(boot)
    origin = server.start()
    project = tmp_path / "gradle"
    project.mkdir()
    (project / "build.gradle.kts").write_text(
        f'dependencies {{ implementation("io.github.shafthq:shaft-engine:{OLD}") }}\n',
        encoding="utf-8",
    )
    agents, claude = _seed_host_skills(project)
    try:
        completed = _run(project, [], _env(tmp_path, origin))
        _assert_ran(completed)
        assert _distribution(project) == "portable"
        installed = set(_addons(project)["installed"])
        assert installed == {"shaft-engine-users"} or "shaft-engine-users" in installed and "shaft-core-developers" not in installed
        receipt = json.loads(
            (project / ".chaos-engine" / "addons" / "shaft-engine-users" / "receipt.json").read_text(encoding="utf-8")
        )
        assert receipt["tag"] == OLD
        assert not (project / ".chaos-engine" / "addons" / "shaft-core-developers").exists()
        _assert_host_skills(agents, claude)
        _doctor(project)
    finally:
        server.close()


def test_snapshot_uses_latest_once_then_reuses_that_tag(tmp_path):
    boot, *_rest = _modules()
    server = _ShaftServer(boot, extra={"ce-addons/shaft-engine-users/post-install.json": json.dumps(OFFER).encode()})
    origin = server.start()
    project = tmp_path / "snapshot"
    project.mkdir()
    (project / "pom.xml").write_text(_pom("10.4.20261112-SNAPSHOT"), encoding="utf-8")
    env = _env(tmp_path, origin)
    try:
        first = _run(project, [], env)
        _assert_ran(first)
        assert "not a release tag; using 10.4.20261112" in (first.stdout + first.stderr)
        receipt = json.loads(
            (project / ".chaos-engine" / "addons" / "shaft-engine-users" / "receipt.json").read_text(encoding="utf-8")
        )
        assert receipt["tag"] == NEW
        latest = sum(1 for hit in server.hits if hit.startswith(f"/repos/{REPO}/releases/latest"))
        assert latest >= 1
        second = _run(project, [], env)
        _assert_ran(second)
        again = sum(1 for hit in server.hits if hit.startswith(f"/repos/{REPO}/releases/latest"))
        assert again == latest
        receipt = json.loads(
            (project / ".chaos-engine" / "addons" / "shaft-engine-users" / "receipt.json").read_text(encoding="utf-8")
        )
        assert receipt["tag"] == NEW
        assert not (project / "agentic-offer-ran").exists()
    finally:
        server.close()


def test_core_checkout_installs_both_addons_and_runs_local_post_install(tmp_path):
    project = tmp_path / "core"
    project.mkdir()
    _core_tree(project)
    agents, claude = _seed_host_skills(project)
    completed = _run(project, [], _env(tmp_path, "http://127.0.0.1:1"))
    _assert_ran(completed)
    assert _distribution(project) == "repository"
    installed = set(_addons(project)["installed"])
    assert {"shaft-engine-users", "shaft-core-developers"} <= installed
    assert not (project / ".chaos-engine" / "addons" / "shaft-engine-users" / "post-install.json").exists()
    marker = (project / "agentic-tools-ran").read_text(encoding="utf-8")
    assert marker.strip() == "--install-shaft-skills --install-shaft-cli"
    _assert_host_skills(agents, claude)
    _doctor(project)


def test_pack_post_install_failure_keeps_the_core(tmp_path):
    project = tmp_path / "core-fail"
    project.mkdir()
    _core_tree(project, exit_code=1)
    completed = _run(project, [], _env(tmp_path, "http://127.0.0.1:1"))
    assert completed.returncode != 0
    assert "pack postInstall failed" in completed.stderr
    assert "ChaosEngine itself is installed" in completed.stderr
    assert (project / ".chaos-engine" / "manifest.json").is_file()
    assert (project / "agentic-tools-ran").is_file()


def test_skip_pack_post_install_does_not_run_the_script(tmp_path):
    project = tmp_path / "core-skip"
    project.mkdir()
    _core_tree(project)
    completed = _run(project, ["--skip-pack-post-install"], _env(tmp_path, "http://127.0.0.1:1"))
    _assert_ran(completed)
    assert "Skipped shaft pack postInstall (--skip-pack-post-install)." in completed.stderr
    assert not (project / "agentic-tools-ran").exists()
    assert (project / ".chaos-engine" / "manifest.json").is_file()


def test_dry_run_prints_the_shaft_line_and_writes_nothing(tmp_path):
    boot, *_rest = _modules()
    server = _ShaftServer(boot)
    origin = server.start()
    project = tmp_path / "dry"
    project.mkdir()
    (project / "pom.xml").write_text(_pom(NEW), encoding="utf-8")
    before = sorted(path.relative_to(project).as_posix() for path in project.rglob("*"))
    try:
        completed = _run(project, ["--dry-run"], _env(tmp_path, origin))
        _assert_ran(completed)
        text = completed.stdout + completed.stderr
        assert f"SHAFT {NEW} from pom.xml → shaft-engine-users @ {NEW}" in text
        after = sorted(path.relative_to(project).as_posix() for path in project.rglob("*"))
        assert after == before
    finally:
        server.close()


def test_unknown_addon_fails_closed_and_lists_names(tmp_path):
    project = tmp_path / "unknown"
    project.mkdir()
    completed = _run(project, ["--with-not-an-addon"], _env(tmp_path, "http://127.0.0.1:1"))
    assert completed.returncode != 0
    text = completed.stdout + completed.stderr
    assert "unknown ChaosEngine add-on: not-an-addon" in text
    assert "design-skills" in text
    assert not (project / ".chaos-engine").exists()


def test_removing_a_required_addon_is_refused(tmp_path):
    project = tmp_path / "refuse"
    project.mkdir()
    _core_tree(project)
    completed = _run(
        project,
        ["--without-shaft-engine-users", "--with-shaft-core-developers"],
        _env(tmp_path, "http://127.0.0.1:1"),
    )
    assert completed.returncode != 0
    text = completed.stdout + completed.stderr
    assert "cannot remove ChaosEngine add-on shaft-engine-users: required by shaft-core-developers" in text
    assert DROP_LINE not in text
    assert not (project / ".chaos-engine").exists()
    denial = project / ".chaos-engine-state" / "addon-denials.json"
    if denial.is_file():
        assert "shaft-engine-users" not in denial.read_text(encoding="utf-8")


def test_without_users_on_a_core_checkout_is_remembered(tmp_path):
    project = tmp_path / "optout"
    project.mkdir()
    (project / "pom.xml").write_text(
        "<project><artifactId>shaft-parent</artifactId></project>\n",
        encoding="utf-8",
    )
    (project / "shaft-skills" / "ce-pack").mkdir(parents=True)
    (project / "shaft-skills" / "ce-pack" / "profile.json").write_text(
        json.dumps({"repository": "ShaftHQ/SHAFT_ENGINE", "name": "shaft"}) + "\n",
        encoding="utf-8",
    )
    (project / "shaft-skills" / "ce-pack" / "entrypoint.md").write_text("entrypoint\n", encoding="utf-8")
    env = _env(tmp_path, "http://127.0.0.1:1")
    first = _run(project, ["--without-shaft-engine-users"], env)
    _assert_ran(first)
    assert DROP_LINE in (first.stdout + first.stderr)
    assert not (project / ".chaos-engine" / "addons" / "shaft-engine-users").exists()
    assert not (project / ".chaos-engine" / "addons" / "shaft-core-developers").exists()
    denial = json.loads((project / ".chaos-engine-state" / "addon-denials.json").read_text(encoding="utf-8"))
    assert denial["denied"] == ["shaft-engine-users"]
    second = _run(project, [], env)
    _assert_ran(second)
    assert not (project / ".chaos-engine" / "addons" / "shaft-engine-users").exists()
    assert not (project / ".chaos-engine" / "addons" / "shaft-core-developers").exists()


def test_no_auto_addons_does_not_detect_shaft(tmp_path):
    boot, *_rest = _modules()
    server = _ShaftServer(boot)
    origin = server.start()
    project = tmp_path / "manual"
    project.mkdir()
    (project / "pom.xml").write_text(_pom(NEW), encoding="utf-8")
    try:
        completed = _run(project, ["--no-auto-addons"], _env(tmp_path, origin))
        _assert_ran(completed)
        assert "shaft-engine-users" not in set(_addons(project)["installed"])
        assert not any(f"/repos/{REPO}/" in hit for hit in server.hits)
    finally:
        server.close()


def test_design_skills_installs_only_when_asked(tmp_path):
    project = tmp_path / "design"
    project.mkdir()
    flagged = _run(project, ["--with-design-skills"], _env(tmp_path, "http://127.0.0.1:1"))
    _assert_ran(flagged)
    assert "design-skills" in set(_addons(project)["installed"])
    assert "shaft-engine-users" not in set(_addons(project)["installed"])
    env = _env(tmp_path, "http://127.0.0.1:1")
    env["CHAOS_ENGINE_ADDONS"] = "design-skills"
    other = tmp_path / "design-env"
    other.mkdir()
    selected = _run(other, [], env)
    _assert_ran(selected)
    assert "design-skills" in set(_addons(other)["installed"])
