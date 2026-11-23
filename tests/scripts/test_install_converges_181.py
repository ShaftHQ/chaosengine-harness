"""Issue 181: install leaves a harness tree doctor-clean without a later repair."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
COMMIT = "1" * 40


def load_install():
    spec = importlib.util.spec_from_file_location("ce_install_converge_181", ROOT / "install.py")
    module = importlib.util.module_from_spec(spec)
    if spec.loader is None:
        raise RuntimeError("install.py has no loader")
    spec.loader.exec_module(module)
    return module


INSTALL = load_install()


def _account_controller(specification: dict):
    def install_account(project, _specification, **_kwargs):
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
        project.joinpath(".chaos-engine-dependencies.json").write_text(
            json.dumps(receipt), encoding="utf-8"
        )
        return receipt

    return SimpleNamespace(
        load_specification=lambda _path: specification,
        install_account_dependencies=install_account,
    )


class InstallConverges181Tests(unittest.TestCase):
    def test_selected_completion_keeps_receipt_owned_hooks(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "checkout"
            project.mkdir()
            specification = json.loads((ROOT / "dependencies.json").read_text(encoding="utf-8"))

            def _refuse_plugin_activation(*_args, **_kwargs):
                raise AssertionError(
                    "install_with_dependencies called activate_detected_plugins under pytest"
                )

            real_load = INSTALL.load_installed_controller

            def _load_installed_controller(installed_root, name):
                controller = real_load(installed_root, name)
                if name == "hosts":
                    controller.activate_detected_plugins = _refuse_plugin_activation
                return controller

            with mock.patch.object(
                INSTALL, "load_dependency_controller", return_value=_account_controller(specification)
            ), mock.patch.object(INSTALL.shutil, "which", return_value=None), mock.patch.object(
                INSTALL, "load_installed_controller", side_effect=_load_installed_controller
            ):
                INSTALL.install_with_dependencies(
                    project, ROOT, COMMIT, with_maven_tools=False
                )
            INSTALL.unwire_receipt_shims(project)
            INSTALL.apply_install_host_completion(project, ("cursor",))
            hosts = INSTALL.load_installed_controller(project / ".chaos-engine", "hosts")
            verified = hosts.verify(project, core_commit=COMMIT)
            self.assertEqual("healthy", verified["status"])
            self.assertEqual([], verified.get("mismatches") or [])
            self.assertNotIn("CE_HOST_ADAPTER_DRIFT", json.dumps(verified))
            hooks = project / ".agents" / "hooks.json"
            self.assertTrue(hooks.is_file())
            receipt, _raw = hosts.read_receipt(project)
            wanted = hosts.decode_images(receipt["after"], nullable=True)[".agents/hooks.json"]
            self.assertEqual(wanted, hooks.read_bytes())

    def test_harness_checkout_doctor_passes_without_repair(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "harness"
            project.mkdir()
            archive = subprocess.run(
                ["git", "-C", str(ROOT), "archive", "--format=tar", "HEAD"],
                check=True,
                capture_output=True,
            )
            subprocess.run(["tar", "-x", "-C", str(project)], check=True, input=archive.stdout)
            subprocess.run(["git", "-C", str(project), "init", "-q"], check=True)
            subprocess.run(
                [
                    "git", "-C", str(project),
                    "-c", "user.email=test@example.com",
                    "-c", "user.name=Test User",
                    "add", "-A",
                ],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [
                    "git", "-C", str(project),
                    "-c", "user.email=test@example.com",
                    "-c", "user.name=Test User",
                    "commit", "-q", "-m", "seed",
                ],
                check=True,
                capture_output=True,
            )
            home = Path(temporary) / "home"
            data = Path(temporary) / "data"
            bin_dir = Path(temporary) / "bin"
            home.mkdir()
            data.mkdir()
            bin_dir.mkdir()
            state = data / "client-state.json"
            state.write_text('{"marketplaces":[],"plugins":[]}\n', encoding="utf-8")
            client = bin_dir / "fake-client.py"
            client.write_text(_FAKE_CLIENT, encoding="utf-8")
            client.chmod(0o755)
            for name in ("claude", "codex"):
                (bin_dir / name).symlink_to(client)
            memory = bin_dir / "memory"
            memory.write_text(_FAKE_MEMORY, encoding="utf-8")
            memory.chmod(0o755)
            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:/usr/bin:/bin"
            env["HOME"] = str(home)
            env["USERPROFILE"] = str(home)
            env["XDG_DATA_HOME"] = str(data)
            env["XDG_CONFIG_HOME"] = str(home / ".config")
            for key in (
                "CLAUDE_CODE_ENTRYPOINT",
                "CLAUDE_PLUGIN_ROOT",
                "CODEX_HOME",
                "GROK_HOOK_EVENT",
                "CURSOR_AGENT",
                "CURSOR_CONVERSATION_ID",
                "PYTEST_CURRENT_TEST",
                "PYTEST_XDIST_WORKER",
            ):
                env.pop(key, None)
            env["CE_FAKE_CLIENT_STATE"] = str(state)
            env["CE_FAKE_MEMORY"] = str(memory)
            completed = subprocess.run(
                [sys.executable, "-c", _CHILD, str(project), str(ROOT), COMMIT],
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            document = json.loads(completed.stdout)
            self.assertEqual("healthy", document["status"], json.dumps(document, sort_keys=True)[:4000])
            self.assertEqual("healthy", document["hosts"]["status"])
            self.assertNotEqual("CE_HOST_ADAPTER_DRIFT", document["hosts"].get("code"))
            self.assertEqual("healthy", document["plugins"])


_FAKE_MEMORY = r'''#!/usr/bin/env python3
import json, sys
args = sys.argv[1:]
if args[:2] == ["status", "--json"]:
    json.dump({"ok": True}, sys.stdout)
elif args[:2] == ["check", "--json"]:
    json.dump({"ok": True, "data": {"valid": True}}, sys.stdout)
raise SystemExit(0)
'''


_FAKE_CLIENT = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
state_path = Path(os.environ["CE_FAKE_CLIENT_STATE"])
client = Path(sys.argv[0]).name
args = sys.argv[1:]
state = json.loads(state_path.read_text(encoding="utf-8"))

def emit(payload):
    json.dump(payload, sys.stdout)
    raise SystemExit(0)

def paths():
    return [item for item in args if item.startswith("/")]

if args[:1] != ["plugin"]:
    emit({})
kind = args[1] if len(args) > 1 else ""
if kind == "marketplace" and len(args) > 2 and args[2] == "list":
    rows = [item for item in state["marketplaces"] if item["client"] == client]
    if client == "codex":
        emit({"marketplaces": [{"name": item["name"], "root": item["root"]} for item in rows]})
    emit([{"name": item["name"], "path": item["root"]} for item in rows])
if kind == "marketplace" and len(args) > 2 and args[2] == "add":
    root = paths()[-1]
    state["marketplaces"].append({"client": client, "name": Path(root).name, "root": root})
    state_path.write_text(json.dumps(state), encoding="utf-8")
    emit({})
if kind == "list":
    rows = []
    for item in state["plugins"]:
        if item["client"] != client:
            continue
        if client == "codex":
            rows.append({
                "pluginId": item["id"],
                "installed": True,
                "enabled": True,
                "version": item["version"],
                "source": {"path": item["source"]},
            })
        else:
            rows.append({
                "id": item["id"],
                "enabled": True,
                "version": item["version"],
                "projectPath": item["project"],
                "installPath": item["source"],
            })
    emit({"installed": rows})
if kind in {"add", "install"}:
    plugin_id = next(item for item in args[2:] if not item.startswith("-"))
    name = plugin_id.split("@", 1)[0]
    root = state["marketplaces"][-1]["root"]
    manifest = json.loads(
        (Path(root) / "plugins" / name / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    state["plugins"].append({
        "client": client,
        "id": plugin_id,
        "version": manifest["version"],
        "source": str(Path(root) / "plugins" / name),
        "project": os.getcwd(),
    })
    state_path.write_text(json.dumps(state), encoding="utf-8")
    emit({})
emit({})
'''


_CHILD = r'''
import importlib.util, json, os, sys
from pathlib import Path
project, source, commit = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
spec = importlib.util.spec_from_file_location("ce_install_child_181", source / "install.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
specification = json.loads((source / "dependencies.json").read_text(encoding="utf-8"))

def install_account(target, _specification, **_kwargs):
    receipt = {
        "schemaVersion": 2,
        "scope": "user",
        "components": {},
        "commands": {
            "memory": os.environ["CE_FAKE_MEMORY"],
            "memory-mcp": sys.executable,
            "mempalace-mcp": sys.executable,
            "node": sys.executable,
            "python3": sys.executable,
        },
    }
    target.joinpath(".chaos-engine-dependencies.json").write_text(json.dumps(receipt), encoding="utf-8")
    return receipt

controller = type("Controller", (), {
    "load_specification": staticmethod(lambda _path: specification),
    "install_account_dependencies": staticmethod(install_account),
})()
original_load = module.load_dependency_controller
module.load_dependency_controller = lambda _root: controller
module.install_with_dependencies(project, source, commit, with_maven_tools=False)
module.load_dependency_controller = original_load
module.unwire_receipt_shims(project)
module.apply_install_host_completion(project, ("cursor",))
if "repair_component" in module.__dict__:
    def _refuse(*_args, **_kwargs):
        raise AssertionError("repair is not a second install step")
    module.repair_component = _refuse
doctor = module.doctor_with_dependencies(project)
hosts = doctor.get("hosts") if isinstance(doctor.get("hosts"), dict) else {}
components = doctor.get("components") if isinstance(doctor.get("components"), dict) else {}
plugins = components.get("plugins") if isinstance(components.get("plugins"), dict) else {}
print(json.dumps({
    "status": doctor.get("status"),
    "hosts": {"status": hosts.get("status"), "code": hosts.get("code"), "detail": hosts.get("detail")},
    "components": {
        name: {"status": row.get("status"), "detail": row.get("detail"), "code": row.get("code")}
        for name, row in components.items()
        if isinstance(row, dict) and row.get("status") not in {"healthy", "compatible-legacy", "sync-advisory", "degraded"}
    },
    "plugins": plugins.get("status"),
}))
'''


if __name__ == "__main__":
    unittest.main()
