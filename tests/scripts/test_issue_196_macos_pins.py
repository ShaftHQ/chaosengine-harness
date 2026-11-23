"""Issue 196: MemPalace macOS x86_64 pin, and npm beside the managed Node."""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
CONTROLLER = ROOT / "runtime" / "dependencies.py"
SPECIFICATION = ROOT / "dependencies.json"

NODE_SPEC = {
    "schemaVersion": 3,
    "dependencies": {
        "node": {
            "executables": ["node", "npm", "npx"],
            "probe": ["node", "--version"],
        }
    },
}


def load_controller():
    spec = importlib.util.spec_from_file_location("chaos_engine_dependencies", CONTROLLER)
    if spec is None or spec.loader is None:
        raise RuntimeError("dependency controller test module could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _python_pin(argv: list[str]) -> str:
    return argv[argv.index("--python") + 1]


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    path.chmod(0o755)


def _version_tree(root: Path) -> tuple[Path, Path, Path]:
    """Node, npm, and npx laid out the way the account installer writes them."""
    if os.name == "nt":
        node, npm, npx = root / "node.exe", root / "npm.cmd", root / "npx.cmd"
    else:
        node, npm, npx = root / "bin" / "node", root / "bin" / "npm", root / "bin" / "npx"
    for path in (node, npm, npx):
        _touch(path)
    return node, npm, npx


def _probe_runner(*_args, **_kwargs):
    return SimpleNamespace(returncode=0, stdout="v22.21.0\n", stderr="")


class MempalaceMacosPinTest(unittest.TestCase):
    def setUp(self):
        self.module = load_controller()
        self.specification = json.loads(SPECIFICATION.read_text(encoding="utf-8"))

    def plan(self, system: str, machine: str, python: str = "3.14.10"):
        return self.module.account_tool_plan(
            Path("."),
            self.specification,
            actions={"mempalace": "installed", "graphify": "installed"},
            executables={"uv": "/user/bin/uv", "npm": "/user/bin/npm"},
            resolved_versions={"python": python},
            platform_pair=(system, machine),
        )

    def test_darwin_x86_64_pins_mempalace_to_313_and_keeps_graphify(self):
        plan = self.plan("Darwin", "x86_64")
        self.assertEqual("3.13", _python_pin(plan["mempalace"][0]))
        self.assertEqual("3.14.10", _python_pin(plan["graphify"][0]))

    def test_linux_x86_64_keeps_the_resolved_mempalace_pin(self):
        plan = self.plan("Linux", "x86_64")
        self.assertEqual("3.14.10", _python_pin(plan["mempalace"][0]))

    def test_darwin_arm64_keeps_the_resolved_mempalace_pin(self):
        plan = self.plan("Darwin", "arm64")
        self.assertEqual("3.14.10", _python_pin(plan["mempalace"][0]))

    def test_darwin_i386_pins_mempalace_to_313(self):
        plan = self.plan("Darwin", "i386")
        self.assertEqual("3.13", _python_pin(plan["mempalace"][0]))

    def test_older_resolved_pin_stays_on_darwin_x86_64(self):
        plan = self.plan("Darwin", "x86_64", python="3.13.2")
        self.assertEqual("3.13.2", _python_pin(plan["mempalace"][0]))
        self.assertEqual("3.13.2", _python_pin(plan["graphify"][0]))


class ManagedNodeNpmTest(unittest.TestCase):
    def setUp(self):
        self.module = load_controller()

    def test_discovery_records_npm_beside_the_managed_node(self):
        module = self.module
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            user = root / "user"
            managed_node, managed_npm, managed_npx = _version_tree(user / "node" / "22.21.0")
            _node13, node13_npm, node13_npx = _version_tree(root / "node13")

            def which(name, path=None):
                del path
                if name == "node":
                    return str(managed_node)
                if name == "npm":
                    return str(node13_npm)
                if name == "npx":
                    return str(node13_npx)
                return None

            with mock.patch.dict(os.environ, {
                "CHAOS_ENGINE_USER_DIR": str(user),
                "CHAOS_ENGINE_USER_PATHS": "1",
            }):
                _local, commands = module.discover_account_commands(
                    NODE_SPEC, which=which, runner=_probe_runner
                )
                text = (user / "user.properties").read_text(encoding="utf-8")

        self.assertEqual(str(managed_npm.resolve()), commands["npm"])
        self.assertEqual(str(managed_npx.resolve()), commands["npx"])
        self.assertIn(str(managed_npm.resolve()), text)
        self.assertNotIn(str(node13_npm.resolve()), text)
        self.assertNotIn(str(node13_npx.resolve()), text)

    def test_missing_managed_npm_does_not_record_the_path_npm(self):
        module = self.module
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            user = root / "user"
            managed_node, managed_npm, _managed_npx = _version_tree(user / "node" / "22.21.0")
            managed_npm.unlink()
            _node13, node13_npm, node13_npx = _version_tree(root / "node13")

            def which(name, path=None):
                del path
                if name == "node":
                    return str(managed_node)
                if name == "npm":
                    return str(node13_npm)
                if name == "npx":
                    return str(node13_npx)
                return None

            with mock.patch.dict(os.environ, {
                "CHAOS_ENGINE_USER_DIR": str(user),
                "CHAOS_ENGINE_USER_PATHS": "1",
            }):
                with self.assertRaises((RuntimeError, ValueError)):
                    module.discover_account_commands(
                        NODE_SPEC, which=which, runner=_probe_runner
                    )
                properties = user / "user.properties"
                text = properties.read_text(encoding="utf-8") if properties.exists() else ""

        self.assertNotIn(str(node13_npm.resolve()), text)
        self.assertNotIn("npm=", text)

    def test_unmanaged_node_keeps_the_path_npm(self):
        module = self.module
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            user = root / "user"
            node, npm, npx = _version_tree(root / "opt" / "node13")

            def which(name, path=None):
                del path
                return {"node": str(node), "npm": str(npm), "npx": str(npx)}.get(name)

            with mock.patch.dict(os.environ, {
                "CHAOS_ENGINE_USER_DIR": str(user),
                "CHAOS_ENGINE_USER_PATHS": "1",
            }):
                _local, commands = module.discover_account_commands(
                    NODE_SPEC, which=which, runner=_probe_runner
                )

        self.assertEqual(str(npm.resolve()), commands["npm"])
        self.assertEqual(str(npx.resolve()), commands["npx"])

    def test_fresh_install_overwrite_publishes_managed_siblings(self):
        module = self.module
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            user = root / "user"
            managed_node, managed_npm, managed_npx = _version_tree(user / "node" / "22.21.0")
            node13, node13_npm, node13_npx = _version_tree(root / "node13")
            published: dict[str, str] = {}

            def discover(specification, preferred_commands=None, which=None, runner=None):
                del specification, preferred_commands, which, runner
                commands = {
                    "node": str(node13),
                    "npm": str(node13_npm),
                    "npx": str(node13_npx),
                }
                local = {
                    "uv": {"healthy": True, "version": "0.9.0", "siblings": {"uv": "/bin/uv"}},
                    "python": {"healthy": True, "version": "3.14.10", "siblings": {"python3": "/bin/python3"}},
                    "java": {"healthy": True, "version": "25.0.1", "siblings": {"java": "/bin/java"}},
                    "node": {
                        "healthy": True,
                        "version": "13.14.0",
                        "siblings": dict(commands),
                    },
                }
                module.publish_user_tool_paths(dict(commands))
                published["path"] = "written"
                return local, commands

            with mock.patch.dict(os.environ, {
                "CHAOS_ENGINE_USER_DIR": str(user),
                "CHAOS_ENGINE_USER_PATHS": "1",
            }), mock.patch.object(
                module, "discover_account_commands", side_effect=discover
            ), mock.patch.object(
                module, "install_exact_node", return_value=str(managed_node)
            ):
                _local, commands = module._reprobe_managed_account_runtimes(
                    root,
                    NODE_SPEC,
                    {"node": {"resolvedVersion": "22.21.0"}},
                    {"node": str(node13), "npm": str(node13_npm), "npx": str(node13_npx)},
                    {},
                    {"uv": "reused", "python": "reused", "java": "reused", "node": "installed"},
                    "linux" if os.name != "nt" else "windows",
                    runner=_probe_runner,
                    opener=None,
                    which=lambda *_args, **_kwargs: None,
                )
                text = (user / "user.properties").read_text(encoding="utf-8")

        self.assertEqual("written", published["path"])
        self.assertEqual(str(managed_npm.resolve()), commands["npm"])
        self.assertEqual(str(managed_npx.resolve()), commands["npx"])
        self.assertIn(str(managed_npm.resolve()), text)
        self.assertNotIn(str(node13_npm.resolve()), text)
        self.assertNotIn(str(node13_npx.resolve()), text)


if __name__ == "__main__":
    unittest.main()
