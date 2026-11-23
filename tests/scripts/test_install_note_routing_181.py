"""Issue 181: internal notes stay off the TTY header and in the console log."""

from __future__ import annotations

import importlib.util
import io
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
NOTE = "chaos-engine: merged missing MemPalace owned exclude_patterns into mempalace.yaml"
LACKS = "mempalace.yaml still lacks owned exclude_patterns after merge"
GRAPHIFY = "stores: graphify full extract"
INDEX_MODE = (
    "chaos-engine: MemPalace index mode=incremental "
    "reason=reusing index with 1 drawers"
)
PRUNE_SKIPPED = "chaos-engine: MemPalace prune skipped: locked"
PRUNED = (
    "chaos-engine: MemPalace pruned 4 drawers from 2 "
    "deleted or excluded sources"
)
INDEX_SKIPS = "chaos-engine: MemPalace skips 1 nested repositories: nested-repo"
MINE = "stores: mempalace mine (full tree) at " + ("a" * 12)
GRAPHIFY_CONTINUED = "chaos-engine: graphify setup continued: graph is empty"
INDEX_NOTES = (INDEX_MODE, PRUNE_SKIPPED, PRUNED, INDEX_SKIPS, MINE)


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    if spec.loader is None:
        raise RuntimeError(f"no loader for {path}")
    spec.loader.exec_module(module)
    return module


def _populate_palace(palace: Path, drawers: int = 1) -> None:
    palace.mkdir(parents=True, exist_ok=True)
    database = palace / "sqlite_exact.sqlite3"
    database.unlink(missing_ok=True)
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "CREATE TABLE documents (id INTEGER PRIMARY KEY, body TEXT)"
        )
        for index in range(drawers):
            connection.execute(
                "INSERT INTO documents (body) VALUES (?)",
                (f"drawer-{index}",),
            )
        connection.commit()
    finally:
        connection.close()


class _Reporter:
    def __init__(self) -> None:
        self.detail = None
        self.traces: list[str] = []

    def trace(self, message: str) -> None:
        self.traces.append(message)


class _Proxy:
    def __init__(self) -> None:
        self._reporter = _Reporter()
        self.written = ""

    def write(self, data) -> int:
        self.written += data
        return len(data)

    def flush(self) -> None:
        return None


class InstallNoteRouting181Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dependencies = load(
            "ce_dependencies_note_181", ROOT / "runtime" / "dependencies.py"
        )
        cls.stores = load("ce_stores_note_181", ROOT / "runtime" / "stores.py")

    def test_exclude_note_uses_step_detail_when_a_reporter_is_active(self):
        proxy = _Proxy()
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            command = self.dependencies.mempalace_project_cli("/tools/mempalace", "mine", project)
            with mock.patch.object(
                self.dependencies, "project_setup_plan", return_value=[command]
            ), mock.patch.object(
                self.dependencies, "apply_owned_mempalace_excludes", return_value=True
            ), mock.patch.object(
                self.dependencies, "_run_transient_mempalace_mine"
            ), mock.patch.object(sys, "stderr", proxy):
                self.dependencies._run_account_mempalace_setup(
                    project,
                    {"mempalace": "/tools/mempalace"},
                    runner=lambda *_args, **_kwargs: None,
                    local={},
                    background_mine=False,
                    mine_spawner=None,
                )
        self.assertEqual(NOTE, proxy._reporter.detail)
        self.assertIn(NOTE, proxy._reporter.traces)
        self.assertNotIn(NOTE, proxy.written)

    def test_exclude_note_stays_on_stderr_without_a_reporter(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            command = self.dependencies.mempalace_project_cli("/tools/mempalace", "mine", project)
            captured = io.StringIO()
            with mock.patch.object(
                self.dependencies, "project_setup_plan", return_value=[command]
            ), mock.patch.object(
                self.dependencies, "apply_owned_mempalace_excludes", return_value=True
            ), mock.patch.object(
                self.dependencies, "_run_transient_mempalace_mine"
            ), mock.patch.object(sys, "stderr", captured):
                self.dependencies._run_account_mempalace_setup(
                    project,
                    {"mempalace": "/tools/mempalace"},
                    runner=lambda *_args, **_kwargs: None,
                    local={},
                    background_mine=False,
                    mine_spawner=None,
                )
        self.assertIn(NOTE, captured.getvalue())

    def test_nested_exclude_lack_uses_step_detail_when_a_reporter_is_active(self):
        proxy = _Proxy()
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / "mempalace.yaml").write_text("wing: x\n", encoding="utf-8")
            with mock.patch.object(
                self.dependencies,
                "_stores_namespace",
                return_value={"nested_repository_roots": lambda _project: ["other"]},
            ), mock.patch.object(
                self.dependencies, "apply_owned_mempalace_excludes", return_value=False
            ), mock.patch.object(
                self.dependencies, "missing_owned_mempalace_excludes", return_value=["owned"]
            ), mock.patch.object(sys, "stderr", proxy):
                self.dependencies.apply_nested_repository_excludes(project)
        self.assertIn(LACKS, str(proxy._reporter.detail))
        self.assertTrue(any(LACKS in line for line in proxy._reporter.traces))
        self.assertNotIn(LACKS, proxy.written)

    def test_graphify_extract_uses_step_detail_when_a_reporter_is_active(self):
        proxy = _Proxy()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with mock.patch.object(self.stores, "_store_tool", return_value="graphify"), \
                    mock.patch.object(self.stores, "_seed_incremental_graph", return_value=False), \
                    mock.patch.object(self.stores, "resolve_graph_out", return_value=root / "graphify-out"), \
                    mock.patch.object(sys, "stderr", proxy):
                with self.assertRaises(RuntimeError):
                    self.stores._refresh_graphify(
                        root,
                        snapshot=root,
                        scratch=root,
                        revision="a" * 40,
                        invoke=lambda *_args, **_kwargs: None,
                    )
        self.assertEqual(GRAPHIFY, proxy._reporter.detail)
        self.assertIn(GRAPHIFY, proxy._reporter.traces)
        self.assertNotIn(GRAPHIFY, proxy.written)

    def test_graphify_extract_stays_on_stderr_without_a_reporter(self):
        captured = io.StringIO()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with mock.patch.object(self.stores, "_store_tool", return_value="graphify"), \
                    mock.patch.object(self.stores, "_seed_incremental_graph", return_value=False), \
                    mock.patch.object(self.stores, "resolve_graph_out", return_value=root / "graphify-out"), \
                    mock.patch.object(sys, "stderr", captured):
                with self.assertRaises(RuntimeError):
                    self.stores._refresh_graphify(
                        root,
                        snapshot=root,
                        scratch=root,
                        revision="a" * 40,
                        invoke=lambda *_args, **_kwargs: None,
                    )
        self.assertIn(GRAPHIFY, captured.getvalue())

    def _emit_mempalace_index_notes(self, stderr) -> tuple[str, ...]:
        """Call the real note sites. Patch mine, prune, decision, the home palace path, and the tool lookup."""
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            nested = project / "nested-repo"
            nested.mkdir()
            (nested / ".git").mkdir()
            command = ["/tools/mempalace", "mine", "."]
            with mock.patch.dict(os.environ):
                os.environ.pop("CHAOS_ENGINE_MEMPALACE", None)
                os.environ.pop("SHAFT_MEMPALACE", None)
                os.environ["GIT_CEILING_DIRECTORIES"] = str(project.parent)
                relocated = project / ".git" / "chaos-engine" / "mempalace"
                _populate_palace(relocated, drawers=1)
                reused = (
                    f"chaos-engine: MemPalace index reused from {relocated} "
                    "(state location moved)"
                )
                with mock.patch.object(
                    self.dependencies,
                    "mempalace_mine_decision",
                    return_value=("incremental", "reusing index with 1 drawers"),
                ), mock.patch.object(sys, "stderr", stderr):
                    self.dependencies.adopt_relocated_mempalace_palace(project)
                    with mock.patch.object(
                        self.dependencies,
                        "prune_mempalace_drawers",
                        side_effect=OSError("locked"),
                    ):
                        self.dependencies.prepare_mempalace_mine(project, command)
                    with mock.patch.object(
                        self.dependencies,
                        "prune_mempalace_drawers",
                        return_value=(2, 4),
                    ):
                        self.dependencies.prepare_mempalace_mine(project, command)
                    with mock.patch.object(self.stores, "_store_tool", return_value="mempalace"):
                        self.stores._refresh_mempalace(
                            project,
                            snapshot=project,
                            primary=project,
                            revision="a" * 40,
                            invoke=lambda _command, _cwd: 0,
                        )
                    with mock.patch.object(
                        self.dependencies,
                        "default_mempalace_palace",
                        return_value=project / "empty-home-palace",
                    ):
                        log_path = self.dependencies.mempalace_index_paths(project)[1]
                        self.dependencies.start_background_mempalace_mine(
                            command,
                            project,
                            spawner=lambda *_args, **_kwargs: None,
                        )
                    background = (
                        "chaos-engine: MemPalace index running in the background; progress: "
                        f"{log_path}"
                    )
                    self.dependencies._run_project_setup_command(
                        [str(project / "graphify"), "extract"],
                        project,
                        runner=lambda argv, **_kwargs: subprocess.CompletedProcess(
                            argv, 1, "", "graph is empty\n"
                        ),
                    )
        return (reused, *INDEX_NOTES, background, GRAPHIFY_CONTINUED)

    def test_adopt_relocated_palace_emits_no_note_when_empty_or_target_populated(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            with mock.patch.dict(os.environ):
                os.environ.pop("CHAOS_ENGINE_MEMPALACE", None)
                os.environ.pop("SHAFT_MEMPALACE", None)
                os.environ["GIT_CEILING_DIRECTORIES"] = str(project.parent)
                relocated = project / ".git" / "chaos-engine" / "mempalace"
                target = project / ".chaos-engine-state" / "mempalace"
                _populate_palace(relocated, drawers=0)
                captured = io.StringIO()
                with mock.patch.object(sys, "stderr", captured):
                    self.assertIsNone(
                        self.dependencies.adopt_relocated_mempalace_palace(project)
                    )
                self.assertEqual("", captured.getvalue())

                _populate_palace(relocated, drawers=2)
                _populate_palace(target, drawers=1)
                captured = io.StringIO()
                with mock.patch.object(sys, "stderr", captured):
                    self.assertIsNone(
                        self.dependencies.adopt_relocated_mempalace_palace(project)
                    )
                self.assertEqual("", captured.getvalue())
                self.assertEqual(1, self.stores.palace_drawer_count(target))

                flush_out = io.StringIO()
                with mock.patch.object(sys, "stderr", flush_out):
                    self.dependencies._stderr_note("flushed note", flush=True)
                self.assertEqual("flushed note\n", flush_out.getvalue())

    def test_mempalace_index_notes_use_step_detail_when_a_reporter_is_active(self):
        proxy = _Proxy()
        notes = self._emit_mempalace_index_notes(proxy)
        for note in notes:
            self.assertIn(note, proxy._reporter.traces)
            self.assertNotIn(note, proxy.written)

    def test_mempalace_index_notes_stay_on_stderr_without_a_reporter(self):
        captured = io.StringIO()
        notes = self._emit_mempalace_index_notes(captured)
        for note in notes:
            self.assertIn(note, captured.getvalue())


if __name__ == "__main__":
    unittest.main()
