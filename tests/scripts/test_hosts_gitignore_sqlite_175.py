"""Managed gitignore host bytecode and external sqlite create race (#175, #178)."""

from __future__ import annotations

import importlib.util
import sqlite3
import subprocess  # nosec B404 - fixed Git acceptance commands.
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HOSTS = ROOT / "runtime" / "hosts.py"


def load(name: str):
    specification = importlib.util.spec_from_file_location(name, HOSTS)
    if specification is None or specification.loader is None:
        raise RuntimeError("host controller test module could not be loaded")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


class ManagedGitignoreHostBytecodeTest(unittest.TestCase):
    def test_session_scratch_and_host_pycache_stay_ignored(self):
        module = load("chaos_engine_gitignore_session_scratch_175")
        block = module.gitignore_content(None).decode()
        floor = max(block.index("!.claude/**\n"), block.index("!.grok/\n"))
        for line in (
            ".grok/rules/session-scratch.md\n",
            ".claude/**/__pycache__/\n",
            ".codex/**/__pycache__/\n",
        ):
            self.assertGreater(block.index(line), floor, line)

        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            project.joinpath(".gitignore").write_text(
                "__pycache__/\n" + block, encoding="utf-8"
            )
            ignored = (
                ".grok/rules/session-scratch.md",
                ".claude/skills/x/__pycache__/a.pyc",
                ".codex/skills/x/__pycache__/a.pyc",
            )
            kept = ".claude/skills/x/skill.md"
            for relative in (*ignored, kept):
                path = project / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("payload\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q", str(project)], check=True)  # nosec B603 B607 - fixed git argv on a temp fixture.
            for relative in ignored:
                result = subprocess.run(
                    ["git", "-C", str(project), "check-ignore", "-q", "--", relative],  # nosec B603 B607 - fixed git argv on a temp fixture.
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(0, result.returncode, relative)
            kept_result = subprocess.run(
                ["git", "-C", str(project), "check-ignore", "-q", "--", kept],  # nosec B603 B607 - fixed git argv on a temp fixture.
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(1, kept_result.returncode, kept)


class ExternalSqliteCreateRaceTest(unittest.TestCase):
    def test_file_exists_keeps_the_other_sqlite_and_sidecars(self):
        module = load("chaos_engine_external_sqlite_exists_178")
        with tempfile.TemporaryDirectory() as temporary:
            palace = Path(temporary)
            database = palace / "sqlite_exact.sqlite3"
            wal = Path(f"{database}-wal")
            shm = Path(f"{database}-shm")

            def collide(path: Path) -> None:
                path.write_bytes(b"other-process")
                wal.write_bytes(b"wal")
                shm.write_bytes(b"shm")
                raise FileExistsError(path)

            with mock.patch.object(module, "_write_empty_exact_sqlite", side_effect=collide):
                module._create_missing_external_sqlite(palace)

            self.assertEqual(b"other-process", database.read_bytes())
            self.assertEqual(b"wal", wal.read_bytes())
            self.assertEqual(b"shm", shm.read_bytes())

    def test_sqlite_error_after_create_removes_the_new_file(self):
        module = load("chaos_engine_external_sqlite_error_178")
        with tempfile.TemporaryDirectory() as temporary:
            palace = Path(temporary)
            database = palace / "sqlite_exact.sqlite3"
            wal = Path(f"{database}-wal")
            shm = Path(f"{database}-shm")

            def fail(path: Path) -> None:
                path.write_bytes(b"ours")
                wal.write_bytes(b"wal")
                shm.write_bytes(b"shm")
                raise sqlite3.Error("schema failed")

            with mock.patch.object(module, "_write_empty_exact_sqlite", side_effect=fail):
                module._create_missing_external_sqlite(palace)

            self.assertFalse(database.exists())
            self.assertFalse(wal.exists())
            self.assertFalse(shm.exists())
