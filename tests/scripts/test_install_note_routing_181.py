"""Issue 181: internal notes stay off the TTY header and in the console log."""

from __future__ import annotations

import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
NOTE = "chaos-engine: merged missing MemPalace owned exclude_patterns into mempalace.yaml"
LACKS = "mempalace.yaml still lacks owned exclude_patterns after merge"
GRAPHIFY = "stores: graphify full extract"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    if spec.loader is None:
        raise RuntimeError(f"no loader for {path}")
    spec.loader.exec_module(module)
    return module


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


if __name__ == "__main__":
    unittest.main()
