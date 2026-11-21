"""Instruction merge placement and confirmed replace (#116)."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, path: Path):
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


HOSTS = _load("instruction_mode_hosts", ROOT / "runtime" / "hosts.py")
MODE = _load("instruction_mode_runtime", ROOT / "runtime" / "instruction_mode.py")


class InventoryDriftTests(unittest.TestCase):
    def test_inventory_and_conflict_ids_stay_in_the_reference_files(self):
        inventory = json.loads((ROOT / "references" / "instruction-inventory.json").read_text(encoding="utf-8"))
        conflicts = json.loads((ROOT / "references" / "instruction-conflicts.json").read_text(encoding="utf-8"))
        globs = [row["glob"] for row in inventory["class_i"]]
        self.assertIn("AGENTS.md", globs)
        self.assertIn(".claude/settings.json", globs)
        self.assertIn("hooks", inventory["json_drop_keys"])
        ids = {row["id"] for row in conflicts["rules"]}
        for required in ("IC-01", "IC-02", "IC-03", "IC-04", "IC-05", "IC-06", "IC-07", "IC-10"):
            self.assertIn(required, ids)


def _git(project: Path, *args: str) -> None:
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=Mohab.MohieElDeen@outlook.com",
            "-c",
            "user.name=Mohab Mohie",
            "-C",
            str(project),
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
    )


class PlacementTests(unittest.TestCase):
    def test_block_is_first_and_a_second_merge_is_identical(self):
        block = HOSTS.instruction_block()
        first = HOSTS.merge_instruction(b"Keep me\n", block, relative="AGENTS.md")
        second = HOSTS.merge_instruction(first, block, relative="AGENTS.md")
        self.assertEqual(first, second)
        text = first.decode()
        self.assertLess(text.index(HOSTS.START), text.index("Keep me"))
        self.assertIn("primary harness", text)
        self.assertLessEqual(text.count("\n"), 12)

    def test_front_matter_bom_and_crlf_stay(self):
        block = HOSTS.instruction_block()
        front = HOSTS.merge_instruction(b"---\ntitle: x\n---\nKeep\n", block, relative="AGENTS.md")
        self.assertTrue(front.startswith(b"---\n"))
        self.assertLess(front.index(HOSTS.START.encode()), front.index(b"Keep"))
        bom = HOSTS.merge_instruction(b"\xef\xbb\xbfKeep\n", block, relative="AGENTS.md")
        self.assertTrue(bom.startswith(b"\xef\xbb\xbf"))
        self.assertIn(b"Keep\n", bom)
        crlf = HOSTS.merge_instruction(b"Keep\r\nme\r\n", block, relative="AGENTS.md")
        self.assertIn(b"Keep\r\nme\r\n", crlf)

    def test_bottom_still_appends(self):
        merged = HOSTS.merge_instruction(
            b"Keep\n",
            HOSTS.instruction_block(),
            relative="AGENTS.md",
            placement="bottom",
        )
        self.assertLess(merged.index(b"Keep"), merged.index(HOSTS.START.encode()))


class ConflictTests(unittest.TestCase):
    def test_rules_flag_a_seed_and_ignore_fences(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / "AGENTS.md").write_text(
                "Please force push to main.\n\n```\ngit reset --hard\n```\n",
                encoding="utf-8",
            )
            found = {item["id"] for item in MODE.conflicts(project)}
            self.assertIn("IC-02", found)
            self.assertNotIn("IC-05", found)
            (project / "AGENTS.md").write_text("Build with pytest.\n", encoding="utf-8")
            self.assertEqual([], MODE.conflicts(project))

    def test_owned_primary_block_is_not_ic06(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / "AGENTS.md").write_text(
                HOSTS.instruction_block() + "Build with pytest.\n",
                encoding="utf-8",
            )
            self.assertNotIn("IC-06", {item["id"] for item in MODE.conflicts(project)})
            (project / "AGENTS.md").write_text(
                HOSTS.instruction_block() + "Another file is the primary harness.\n",
                encoding="utf-8",
            )
            self.assertIn("IC-06", {item["id"] for item in MODE.conflicts(project)})


class ReplaceTests(unittest.TestCase):
    def _repo(self) -> Path:
        project = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(project)], check=False))
        _git(project, "init", "-q")
        (project / "AGENTS.md").write_text("User rule\n", encoding="utf-8")
        (project / "CLAUDE.local.md").write_text("personal\n", encoding="utf-8")
        (project / ".gitignore").write_text(".chaos-engine-state/\n", encoding="utf-8")
        _git(project, "add", "AGENTS.md", "CLAUDE.local.md", ".gitignore")
        _git(project, "commit", "-q", "-m", "seed")
        return project

    def test_replace_needs_yes_and_dry_run_writes_nothing(self):
        project = self._repo()
        before = (project / "AGENTS.md").read_bytes()
        with self.assertRaises(MODE.ReplaceRefusal) as raised:
            MODE.begin_replace(
                project,
                yes=False,
                dry_run=False,
                consumer=False,
                scope="project",
                allow_dirty=False,
                force_source=False,
                include_local=False,
            )
        self.assertEqual(raised.exception.code, "CE_MODE_REPLACE_NEEDS_YES")
        self.assertEqual(before, (project / "AGENTS.md").read_bytes())
        plan = MODE.begin_replace(
            project,
            yes=False,
            dry_run=True,
            consumer=False,
            scope="project",
            allow_dirty=False,
            force_source=False,
            include_local=False,
        )
        self.assertEqual(plan["status"], "dry-run")
        self.assertIn("AGENTS.md", plan["delete"])
        self.assertNotIn("CLAUDE.local.md", plan["delete"])
        self.assertEqual(before, (project / "AGENTS.md").read_bytes())

    def test_replace_and_restore_round_trip(self):
        project = self._repo()
        outcome = MODE.begin_replace(
            project,
            yes=True,
            dry_run=False,
            consumer=False,
            scope="project",
            allow_dirty=False,
            force_source=False,
            include_local=False,
        )
        self.assertFalse((project / "AGENTS.md").exists())
        self.assertEqual("personal\n", (project / "CLAUDE.local.md").read_text(encoding="utf-8"))
        (project / "AGENTS.md").write_text(HOSTS.instruction_block(), encoding="utf-8")
        MODE.note_created(project, str(outcome["stamp"]), ["AGENTS.md"])
        MODE.restore(project, str(outcome["stamp"]))
        self.assertEqual(b"User rule\n", (project / "AGENTS.md").read_bytes())
        status = subprocess.run(
            ["git", "-C", str(project), "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual("", status.stdout)

    def test_refusals_and_delete_guard_write_nothing(self):
        project = self._repo()
        original = (project / "AGENTS.md").read_bytes()
        with self.assertRaises(MODE.ReplaceRefusal) as consumer:
            MODE.begin_replace(project, yes=True, dry_run=False, consumer=True, scope="project", allow_dirty=False, force_source=False, include_local=False)
        self.assertEqual("CE_MODE_CONSUMER_CONFLICT", consumer.exception.code)
        with self.assertRaises(MODE.ReplaceRefusal) as scoped:
            MODE.begin_replace(project, yes=True, dry_run=False, consumer=False, scope="user", allow_dirty=False, force_source=False, include_local=False)
        self.assertEqual("CE_MODE_SCOPE_CONFLICT", scoped.exception.code)
        (project / "AGENTS.md").write_text("dirty\n", encoding="utf-8")
        with self.assertRaises(MODE.ReplaceRefusal) as dirty:
            MODE.begin_replace(project, yes=True, dry_run=False, consumer=False, scope="project", allow_dirty=False, force_source=False, include_local=False)
        self.assertEqual("CE_MODE_REPLACE_DIRTY", dirty.exception.code)
        (project / "AGENTS.md").write_bytes(original)
        nested = project / "yt"
        nested.mkdir()
        (nested / "AGENTS.md").write_text("protected\n", encoding="utf-8")
        with self.assertRaises(MODE.ReplaceRefusal) as guarded:
            MODE.begin_replace(project, yes=True, dry_run=False, consumer=False, scope="project", allow_dirty=True, force_source=False, include_local=False)
        self.assertTrue(guarded.exception.code.startswith("CE_DELETE_GUARD"))
        self.assertTrue((nested / "AGENTS.md").is_file())
        self.assertEqual(original, (project / "AGENTS.md").read_bytes())

    def test_source_trees_are_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / "runtime").mkdir()
            (project / "runtime" / "hosts.py").write_text("x\n", encoding="utf-8")
            (project / "install.py").write_text("x\n", encoding="utf-8")
            (project / "AGENTS.md").write_text("source\n", encoding="utf-8")
            with self.assertRaises(MODE.ReplaceRefusal) as raised:
                MODE.begin_replace(project, yes=True, dry_run=False, consumer=False, scope="project", allow_dirty=False, force_source=False, include_local=False)
            self.assertEqual("CE_MODE_REPLACE_SOURCE_TREE", raised.exception.code)
            self.assertTrue((project / "AGENTS.md").is_file())
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            _git(project, "init", "-q")
            _git(project, "remote", "add", "origin", "https://github.com/ShaftHQ/SHAFT_ENGINE.git")
            (project / "AGENTS.md").write_text("shaft\n", encoding="utf-8")
            with self.assertRaises(MODE.ReplaceRefusal) as raised:
                MODE.begin_replace(project, yes=True, dry_run=False, consumer=False, scope="project", allow_dirty=False, force_source=False, include_local=False)
            self.assertEqual("CE_MODE_REPLACE_SOURCE_TREE", raised.exception.code)


class CliTests(unittest.TestCase):
    def test_install_py_refuses_unconfirmed_replace(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / "AGENTS.md").write_text("stay\n", encoding="utf-8")
            env = os.environ.copy()
            for key in list(env):
                if key.startswith("CHAOS_ENGINE_"):
                    env.pop(key)
            env["CHAOS_ENGINE_CONFIG_HOME"] = str(project / "absent-config")
            completed = subprocess.run(
                [
                    "python3",
                    str(ROOT / "install.py"),
                    "install",
                    "--project",
                    str(project),
                    "--mode",
                    "replace",
                    "--source",
                    str(ROOT),
                    "--commit",
                    "a" * 40,
                    "--skip-tools",
                ],
                cwd=project,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(2, completed.returncode)
            self.assertIn("CE_MODE_REPLACE_NEEDS_YES", completed.stderr)
            self.assertEqual("stay\n", (project / "AGENTS.md").read_text(encoding="utf-8"))
            help_text = subprocess.run(
                ["python3", str(ROOT / "install.py"), "install", "--help"],
                capture_output=True,
                text=True,
                check=False,
            ).stdout
            self.assertIn("--mode", help_text)
            self.assertIn("--scope", help_text)


if __name__ == "__main__":
    unittest.main()
