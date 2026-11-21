"""Layered installer config: one flag table, precedence, and no default change."""

from __future__ import annotations

import argparse
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


INSTALL = load(ROOT / "install.py", "install_config_install")
BOOTSTRAP = load(ROOT / "bootstrap.py", "install_config_bootstrap")
CONFIG = load(ROOT / "runtime" / "install_config.py", "install_config_runtime")


def _flags(parser) -> set[str]:
    found: set[str] = set()
    for action in parser._actions:
        found.update(action.option_strings)
    return found


class FlagParityTests(unittest.TestCase):
    def test_parsers_differ_only_by_repository(self):
        bootstrap = _flags(BOOTSTRAP.parser())
        install_parser = INSTALL.parser()
        install = next(
            action.choices["install"]
            for action in install_parser._actions
            if getattr(action, "choices", None) and "install" in action.choices
        )
        self.assertEqual(bootstrap - _flags(install), {"--repository"})
        self.assertIn("--project", bootstrap)
        self.assertIn("--project", _flags(install))
        self.assertIn("--without-icm-architect", bootstrap)
        self.assertIn("--scope", bootstrap)
        self.assertIn("--mode", bootstrap)

    def test_unset_choice_is_not_a_cli_value(self):
        args = BOOTSTRAP.parser().parse_args(["--repository", "ShaftHQ/chaosengine-harness"])
        self.assertIsNone(args.maven_tools_mode)
        self.assertIsNone(getattr(args, "channel", None))
        self.assertIsNone(getattr(args, "scope", None))
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            resolved = CONFIG.resolve_config(
                project,
                args=args,
                environ={"CHAOS_ENGINE_CONFIG_HOME": str(project / "absent")},
            )
        self.assertEqual(resolved.sources["source.channel"], "default")
        self.assertEqual(resolved.sources["install.scope"], "default")
        self.assertEqual(resolved.sources["mcp.maven_tools.mode"], "default")

    def test_without_icm_architect_reaches_the_bundle(self):
        install_parser = INSTALL.parser()
        install = next(
            action.choices["install"]
            for action in install_parser._actions
            if getattr(action, "choices", None) and "install" in action.choices
        )
        args = install.parse_args(["--without-icm-architect"])
        bundle = INSTALL.bundle_from_install_args(args)
        self.assertFalse(bundle["icm-architect"])

    def test_copied_bootstrap_parses_without_icm_architect(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "bootstrap.py"
            target.write_bytes((ROOT / "bootstrap.py").read_bytes())
            copied = load(target, "copied_bootstrap_config")
            args = copied.parser().parse_args(
                ["--repository", "ShaftHQ/chaosengine-harness", "--without-icm-architect"]
            )
        self.assertTrue(args.without_icm_architect)

    def test_upgrade_persists_a_configured_component_opt_out(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            project.mkdir()
            (project / ".chaos-engine.toml").write_text(
                "schema = 1\n[components]\nmempalace = false\n",
                encoding="utf-8",
            )
            INSTALL.write_bundle_options(project, {"mempalace": True})
            args = argparse.Namespace(
                project=project,
                instructions_mode=None,
                scope=None,
                source=ROOT,
                commit="a" * 40,
                dry_run=False,
                no_input=True,
                consumer=False,
                allow_dirty=False,
                force_replace_source_tree=False,
                include_local=False,
                config_path=None,
                user_hosts=None,
                no_user_hooks=False,
            )
            isolated = os.environ.copy()
            isolated["CHAOS_ENGINE_CONFIG_HOME"] = str(root / "config")
            with (
                mock.patch.dict(os.environ, isolated, clear=True),
                mock.patch.object(INSTALL, "_publish_guided_overlay", return_value=project / ".chaos-engine"),
                mock.patch.object(INSTALL, "_contract_blockers", return_value=[]),
                mock.patch.object(INSTALL, "_rebind_contract_drift"),
                mock.patch.object(INSTALL, "_strip_retired_mcp"),
            ):
                result = INSTALL._run_guided_upgrade(args)
            self.assertEqual("installed", result["status"])
            document = json.loads(
                (project / ".chaos-engine-state" / "bundle-options.json").read_text(encoding="utf-8")
            )
            self.assertIs(False, document["enabled"]["mempalace"])


class PrecedenceTests(unittest.TestCase):
    def test_flag_beats_env_beats_local_beats_project_beats_user(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            project = root / "project"
            home.mkdir()
            project.mkdir()
            (home / "config.toml").write_text(
                'schema = 1\nhosts.enabled = ["claude"]\n',
                encoding="utf-8",
            )
            (project / ".chaos-engine.toml").write_text(
                'schema = 1\nhosts.enabled = ["codex"]\n',
                encoding="utf-8",
            )
            (project / ".chaos-engine.local.toml").write_text(
                'schema = 1\nhosts.enabled = ["grok"]\n',
                encoding="utf-8",
            )
            environ = {
                "CHAOS_ENGINE_CONFIG_HOME": str(home),
                "CHAOS_ENGINE_HOST": "gemini",
            }
            resolved = CONFIG.resolve_config(project, environ=environ)
            self.assertEqual(resolved.values["hosts.enabled"], ("gemini",))
            self.assertTrue(str(resolved.sources["hosts.enabled"]).startswith("env:"))
            parser = BOOTSTRAP.parser()
            args = parser.parse_args(["--repository", "ShaftHQ/chaosengine-harness", "--hosts", "cursor"])
            flagged = CONFIG.resolve_config(
                project,
                args=args,
                environ={"CHAOS_ENGINE_CONFIG_HOME": str(home)},
            )
            self.assertEqual(flagged.values["hosts.enabled"], ("cursor",))
            self.assertEqual(flagged.sources["hosts.enabled"], "cli")
            both = CONFIG.resolve_config(project, args=args, environ=environ)
            self.assertEqual(both.values["hosts.enabled"], ("cursor",))
            self.assertEqual(both.sources["hosts.enabled"], "cli")

    def test_copied_bootstrap_flag_beats_env(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "bootstrap.py"
            target.write_bytes((ROOT / "bootstrap.py").read_bytes())
            copied = load(target, "copied_bootstrap_flag_beats_env")
            project = root / "project"
            project.mkdir()
            args = copied.parser().parse_args(
                [
                    "--repository",
                    "ShaftHQ/chaosengine-harness",
                    "--project",
                    str(project),
                    "--hosts",
                    "cursor",
                ]
            )
            previous = sys.modules.get("ce_install_config")
            for name in (
                "ce_user_paths",
                "ce_install_options",
                "ce_install_config",
                "runtime.user_paths",
                "runtime.install_options",
            ):
                sys.modules.pop(name, None)
            _options, config = copied._load_install_catalog()
            self.assertIsNot(config, previous)
            resolved = config.resolve_config(
                project,
                args=args,
                environ={
                    "CHAOS_ENGINE_HOST": "gemini",
                    "CHAOS_ENGINE_CONFIG_HOME": str(root / "absent"),
                },
            )
        self.assertEqual(resolved.values["hosts.enabled"], ("cursor",))
        self.assertEqual(resolved.sources["hosts.enabled"], "cli")

    def test_replace_from_a_file_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            path = project / ".chaos-engine.toml"
            path.write_text('schema = 1\n[instructions]\nmode = "replace"\n', encoding="utf-8")
            with self.assertRaises(CONFIG.ConfigError) as raised:
                CONFIG.resolve_config(project, environ={})
        self.assertEqual(raised.exception.code, "CE_CONFIG_REPLACE_FROM_FILE")

    def test_secret_key_is_refused_and_known_token_key_stays(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            path = project / ".chaos-engine.toml"
            path.write_text('schema = 1\napi_token = "nope"\n', encoding="utf-8")
            with self.assertRaises(CONFIG.ConfigError) as raised:
                CONFIG.resolve_config(project, environ={})
            self.assertEqual(raised.exception.code, "CE_CONFIG_SECRET")
            path.write_text("schema = 1\n", encoding="utf-8")
            home = project / "home"
            home.mkdir()
            (home / "config.toml").write_text(
                "schema = 1\n[network]\nuse_gh_token = false\n",
                encoding="utf-8",
            )
            resolved = CONFIG.resolve_config(
                project,
                environ={"CHAOS_ENGINE_CONFIG_HOME": str(home)},
            )
            self.assertFalse(resolved.values["network.use_gh_token"])
            self.assertEqual("user", resolved.sources["network.use_gh_token"])

    def test_config_set_keeps_crlf_and_bom(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.toml"
            path.write_bytes(b"\xef\xbb\xbfschema = 1\r\n[hosts]\r\nenabled = [\"claude\"]\r\n")
            CONFIG.config_set(path, "components.mempalace", "false")
            raw = path.read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        self.assertIn(b"\r\n", raw)
        self.assertIn(b"mempalace = false", raw)

    def test_show_json_names_sources_and_validate_rejects_a_bad_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            project.mkdir()
            (project / ".chaos-engine.toml").write_text(
                'schema = 1\nhosts.enabled = ["claude"]\n',
                encoding="utf-8",
            )
            show = argparse.Namespace(
                config_command="show",
                project=project,
                config_path=None,
                json=True,
            )
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                self.assertEqual(0, CONFIG.run_config_command(show))
            document = __import__("json").loads(stdout.getvalue())
            hosts = next(row for row in document["keys"] if row["key"] == "hosts.enabled")
            self.assertEqual(["claude"], hosts["value"])
            self.assertEqual("project", hosts["source"])
            bad = project / "broken.toml"
            bad.write_text("schema = [\n", encoding="utf-8")
            validate = argparse.Namespace(
                config_command="validate",
                project=project,
                config_path=None,
                json=False,
                file=bad,
            )
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                self.assertEqual(1, CONFIG.run_config_command(validate))
            self.assertIn("CE_CONFIG_INVALID", stderr.getvalue())

    def test_cli_only_key_in_a_file_warns_and_is_ignored(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / ".chaos-engine.toml").write_text(
                "schema = 1\ndry_run = true\n",
                encoding="utf-8",
            )
            resolved = CONFIG.resolve_config(project, environ={})
        self.assertEqual("default", resolved.sources["dry_run"])
        self.assertFalse(resolved.values["dry_run"])
        self.assertTrue(any("dry_run" in warning for warning in resolved.warnings))

    def test_every_catalog_key_is_documented_and_layered(self):
        text = (ROOT / "docs" / "configuration.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("ChaosEngine sends no usage data.", text)
        self.assertIn("ChaosEngine sends no usage data.", readme)
        for row in CONFIG.CATALOG:
            if row.cli_only:
                continue
            with self.subTest(key=row.key):
                self.assertIn(f"`{row.key}`", text)
                self._assert_layers(row)

    def _env_raw(self, row) -> str:
        if row.env_kind in {"bool", "bool-default-true", "bool-invert", "consumer", "keep-edits"}:
            return "1"
        return self._raw(row, 0)

    def _raw(self, row, index: int) -> str:
        if row.kind == "bool":
            return "false" if index == 0 else "true"
        if row.kind == "int":
            if row.key == "locks.project_wait_seconds":
                return str(30 + index)
            if row.key == "hooks.guard_wait_ms":
                return str(1000 + index)
            return str(3 + index)
        if row.kind == "choice":
            choices = list(row.choices) or [str(row.default)]
            if row.key == "instructions.mode":
                return "merge"
            return str(choices[index % len(choices)])
        if row.kind == "list":
            if row.choices:
                return str(row.choices[index % len(row.choices)])
            return f"item{index}"
        if row.kind == "path":
            return f"/tmp/ce-config-{index}"
        return f"configured-{index}"

    def test_project_file_cannot_set_install_scope(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            home = root / "home"
            project.mkdir()
            home.mkdir()
            (project / ".chaos-engine.toml").write_text(
                'schema = 1\n[install]\nscope = "user"\n',
                encoding="utf-8",
            )
            blocked = CONFIG.resolve_config(
                project,
                environ={"CHAOS_ENGINE_CONFIG_HOME": str(home)},
            )
            self.assertEqual("project", blocked.values["install.scope"])
            self.assertEqual("default", blocked.sources["install.scope"])
            self.assertTrue(
                any("install.scope" in item and " in project;" in item for item in blocked.warnings)
            )
            (home / "config.toml").write_text(
                'schema = 1\n[install]\nscope = "user"\n',
                encoding="utf-8",
            )
            allowed = CONFIG.resolve_config(
                project,
                environ={"CHAOS_ENGINE_CONFIG_HOME": str(home)},
            )
            self.assertEqual("user", allowed.values["install.scope"])
            self.assertEqual("user", allowed.sources["install.scope"])

    def _assert_layers(self, row):
        letters = set(row.levels)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            project = root / "project"
            home.mkdir()
            project.mkdir()
            user = home / "config.toml"
            CONFIG.config_set(user, row.key, self._raw(row, 0))
            user_resolved = CONFIG.resolve_config(
                project,
                environ={"CHAOS_ENGINE_CONFIG_HOME": str(home)},
            )
            if "U" in letters:
                self.assertEqual("user", user_resolved.sources[row.key])
            else:
                self.assertNotEqual("user", user_resolved.sources[row.key])
                self.assertTrue(
                    any(row.key in item and " in user;" in item for item in user_resolved.warnings),
                    user_resolved.warnings,
                )
            project_file = project / ".chaos-engine.toml"
            CONFIG.config_set(project_file, row.key, self._raw(row, 1))
            project_resolved = CONFIG.resolve_config(
                project,
                environ={"CHAOS_ENGINE_CONFIG_HOME": str(home)},
            )
            if "P" in letters:
                self.assertEqual("project", project_resolved.sources[row.key])
            else:
                self.assertNotEqual("project", project_resolved.sources[row.key])
                self.assertTrue(
                    any(row.key in item and " in project;" in item for item in project_resolved.warnings),
                    project_resolved.warnings,
                )
            if row.env:
                env_name = row.env[0]
                environ = {
                    "CHAOS_ENGINE_CONFIG_HOME": str(home),
                    env_name: self._env_raw(row),
                }
                env_resolved = CONFIG.resolve_config(project, environ=environ)
                self.assertTrue(env_resolved.sources[row.key].startswith("env:"))
            if not row.flags:
                return
            flag = row.flags[0]
            argv = ["--repository", "ShaftHQ/chaosengine-harness", flag]
            if row.action not in {"store_true", "secret_guard_off"}:
                argv.append(self._raw(row, 0))
            args = BOOTSTRAP.parser().parse_args(argv)
            flagged = CONFIG.resolve_config(
                project,
                args=args,
                environ={"CHAOS_ENGINE_CONFIG_HOME": str(home)},
            )
            self.assertEqual("cli", flagged.sources[row.key])


class PathAllowlistTests(unittest.TestCase):
    def test_no_new_path_home_outside_user_paths(self):
        allow = {
            "runtime/backups_watch.py:return Path(os.environ.get(\"XDG_STATE_HOME\") or Path.home() / \".local/state\") / \"chaos-engine\"",
            "runtime/delete_guard.py:for root in {project, Path.home()} - {None}:",
            "runtime/delete_guard.py:Path(os.environ.get(\"XDG_CONFIG_HOME\") or Path.home() / \".config\")",
            "runtime/delete_guard.py:home = _realpath_root(Path.home())",
            "runtime/delete_guard.py:return Path(os.environ.get(\"XDG_STATE_HOME\") or Path.home() / \".local/state\") / \"chaos-engine\" / \"delete-acks.json\"",
            "runtime/dependencies.py:return Path.home() / \".local/share/uv/tools\"",
            "runtime/dependencies.py:base = Path(os.environ.get(\"LOCALAPPDATA\") or Path.home() / \"AppData/Local\")",
            "runtime/dependencies.py:base = Path.home() / \"Library/Application Support\"",
            "runtime/dependencies.py:base = Path(os.environ.get(\"XDG_DATA_HOME\") or Path.home() / \".local/share\")",
            "runtime/dependencies.py:legacy = Path.home() / \".local\" / \"share\" / \"chaos-engine\" / kind",
            "runtime/dependencies.py:lexical_home = home or Path.home()",
            "runtime/dependencies.py:root = bin_dir if bin_dir is not None else Path.home() / \".local/bin\"",
            "runtime/dependencies.py:tools = tools_root if tools_root is not None else Path.home() / \".local/share/uv/tools\"",
            "runtime/dependencies.py:home = Path.home()",
            "runtime/dependencies.py:return Path.home() / \".mempalace\" / \"palace\"",
            "runtime/dependencies.py:prefix = Path.home() / \".local\"",
            "runtime/dependencies.py:base = Path(os.environ.get(\"LOCALAPPDATA\") or Path.home() / \"AppData/Local\") / \"chaos-engine\"",
            "runtime/dependencies.py:base = Path.home() / \"Library/Caches/chaos-engine\"",
            "runtime/dependencies.py:base = Path(os.environ.get(\"XDG_CACHE_HOME\") or Path.home() / \".cache\") / \"chaos-engine\"",
            "runtime/grok_lean_config.py:root = Path.home() if home is None else home",
            "runtime/harness_mindset.py:candidates.append(Path.home() / \".cache\")",
            "runtime/learning_session.py:root = Path(xdg) if xdg else Path.home() / \".config\"",
            "runtime/learn_traces.py:collect_p.add_argument(\"--home\", type=Path, default=Path.home())",
            "runtime/learn_traces.py:learn_p.add_argument(\"--home\", type=Path, default=Path.home())",
            "runtime/learn_traces_mrv.py:collect_fn(home or Path.home(), run_dir)",
            "runtime/mcp_policy.py:root = home or Path.home()",
            "runtime/stores.py:base = Path(xdg).expanduser() if xdg else Path.home() / \".local\" / \"share\"",
            "runtime/stores.py:chroma = Path.home() / \".mempalace\" / \"palace\" / \"chroma.sqlite3\"",
            "runtime/stores.py:root = (home or Path.home()).resolve()",
            "runtime/task_ledger.py:base = os.environ.get(\"XDG_STATE_HOME\") or str(Path.home() / \".local\" / \"state\")",
            "install.py:candidates.append((Path(home) if home else Path.home() / \".codex\") / \"config.toml\")",
            "install.py:replacements = ((str(project.resolve()), \"<project>\"), (str(Path.home()), \"<home>\"))",
            "install.py:home = Path.home()",
        }
        hits = set()
        for path in (ROOT / "runtime").rglob("*.py"):
            if path.name == "user_paths.py":
                continue
            rel = path.relative_to(ROOT).as_posix()
            for line in path.read_text(encoding="utf-8").splitlines():
                if "Path.home()" in line:
                    hits.add(f"{rel}:{line.strip()}")
        for line in (ROOT / "install.py").read_text(encoding="utf-8").splitlines():
            if "Path.home()" in line:
                hits.add(f"install.py:{line.strip()}")
        self.assertLessEqual(hits, allow)


if __name__ == "__main__":
    unittest.main()
