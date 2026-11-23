"""Any AI client discovers ChaosEngine, including a machine with no named CLI."""

from __future__ import annotations

import importlib.util
import os
import re
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
import sys as _sys; from pathlib import Path as _Path; _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))  # noqa: E402,E702 - self-locating under python3 -I (#7197)

HOSTS = ROOT / "runtime" / "hosts.py"
_UNDOTTED_SKILL = re.compile(r"(?<!\.)chaos-engine/skills/chaos-engine/SKILL\.md")
_LEGACY_SKILL_SHIMS = (
    ".agents/skills/chaos-engine/SKILL.md",
    ".claude/skills/chaos-engine/SKILL.md",
    ".gemini/skills/chaos-engine/SKILL.md",
    ".github/skills/chaos-engine/SKILL.md",
    "plugins/chaos-engine/skills/chaos-engine/SKILL.md",
)


def load(name: str):
    specification = importlib.util.spec_from_file_location(name, HOSTS)
    if specification is None or specification.loader is None:
        raise RuntimeError("host controller test module could not be loaded")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


class UniversalClientParityTests(unittest.TestCase):
    def setUp(self):
        self.runtime_state = tempfile.TemporaryDirectory()
        self.runtime_environment = mock.patch.dict(
            os.environ,
            {
                "LOCALAPPDATA": self.runtime_state.name,
                "XDG_DATA_HOME": self.runtime_state.name,
                "CHAOSENGINE_JAVA": "",
                "CHAOSENGINE_MAVEN_TOOLS_MCP_JAR": "",
                "JAVA_HOME": "",
            },
            clear=False,
        )
        self.runtime_environment.start()

    def tearDown(self):
        self.runtime_environment.stop()
        self.runtime_state.cleanup()

    def _project(self, temporary: str) -> Path:
        project = Path(temporary) / "consumer"
        project.joinpath(".chaos-engine/skills/chaos-engine").mkdir(parents=True)
        project.joinpath(".chaos-engine/skills/chaos-engine/SKILL.md").write_text(
            "# ChaosEngine\n", encoding="utf-8"
        )
        project.joinpath(".chaos-engine/identity.md").write_text("# Identity\n", encoding="utf-8")
        return project

    def test_entry_paths_name_the_universal_baseline(self):
        module = load("chaos_engine_universal_entries")
        self.assertEqual(
            (
                "AGENTS.md",
                ".agents/skills/chaos-engine/SKILL.md",
                ".chaos-engine/skills/chaos-engine/SKILL.md",
            ),
            module.UNIVERSAL_ENTRY_PATHS,
        )
        self.assertEqual(module.UNIVERSAL_ENTRY_PATHS, module.universal_entry_paths())

    def test_fresh_install_without_named_cli_writes_the_universal_baseline(self):
        module = load("chaos_engine_universal_install")
        with tempfile.TemporaryDirectory() as temporary:
            project = self._project(temporary)
            with mock.patch.object(module.shutil, "which", return_value=None), mock.patch.object(
                module, "sync_grok_user_lean_config", return_value={"status": "skipped"}
            ):
                module.install(project, core_commit="1" * 40)

            agents = project.joinpath("AGENTS.md").read_text(encoding="utf-8")
            shim = project.joinpath(".agents/skills/chaos-engine/SKILL.md").read_text(encoding="utf-8")
            self.assertIn(".chaos-engine/skills/chaos-engine/SKILL.md", agents)
            self.assertIn(".chaos-engine/identity.md", agents)
            self.assertIn(".chaos-engine/skills/chaos-engine/SKILL.md", shim)
            self.assertIsNone(_UNDOTTED_SKILL.search(agents))
            self.assertIsNone(_UNDOTTED_SKILL.search(shim))
            self.assertNotIn("py -3", shim)
            self.assertNotIn("python3", shim)
            for relative in module.universal_entry_paths():
                self.assertTrue((project / relative).is_file(), relative)
            self.assertEqual("healthy", module.verify(project, core_commit="1" * 40)["status"])
            self.assertEqual([], module.competing_policy_errors(project))

    def test_upgrade_rewrites_legacy_source_tree_pointers_and_keeps_user_prose(self):
        module = load("chaos_engine_universal_upgrade")
        prose = "Team rule: keep the public API stable.\n"
        with tempfile.TemporaryDirectory() as temporary:
            project = self._project(temporary)
            with mock.patch.object(module, "sync_grok_user_lean_config", return_value={"status": "skipped"}):
                module.install(project, core_commit="1" * 40)
                agents_path = project / "AGENTS.md"
                legacy = agents_path.read_text(encoding="utf-8").replace(
                    ".chaos-engine/", "chaos-engine/"
                )
                agents_path.write_text(prose + legacy, encoding="utf-8")
                for relative in _LEGACY_SKILL_SHIMS:
                    path = project / relative
                    path.write_text(
                        path.read_text(encoding="utf-8").replace(".chaos-engine/", "chaos-engine/"),
                        encoding="utf-8",
                    )

                module.install(project, core_commit="2" * 40)

            text = agents_path.read_text(encoding="utf-8")
            outside = text.split(module.END, 1)[-1]
            self.assertIn(prose.strip(), outside)
            self.assertIn(".chaos-engine/skills/chaos-engine/SKILL.md", text)
            self.assertIn(".chaos-engine/identity.md", text)
            self.assertIsNone(_UNDOTTED_SKILL.search(text))
            shim = project.joinpath(".agents/skills/chaos-engine/SKILL.md").read_text(encoding="utf-8")
            self.assertIn(".chaos-engine/skills/chaos-engine/SKILL.md", shim)
            self.assertIsNone(_UNDOTTED_SKILL.search(shim))
            self.assertEqual("healthy", module.verify(project, core_commit="2" * 40)["status"])
            self.assertEqual([], module.competing_policy_errors(project))

    def test_merge_rewrites_a_source_tree_marker_and_leaves_foreign_markers(self):
        module = load("chaos_engine_universal_marker")
        module.consume_merge_handoffs()
        legacy = (
            "Owner rule stays.\n"
            "<!-- CHAOSENGINE:START -->\n"
            "Follow `chaos-engine/skills/chaos-engine/SKILL.md` and `chaos-engine/identity.md`.\n"
            "<!-- CHAOSENGINE:END -->\n"
        )
        merged = module.merge_instruction(
            legacy.encode(),
            module.agents_md_block(),
            relative="AGENTS.md",
        ).decode()
        self.assertIn("Owner rule stays.", merged)
        self.assertIn(".chaos-engine/skills/chaos-engine/SKILL.md", merged)
        self.assertIsNone(_UNDOTTED_SKILL.search(merged))
        self.assertNotIn("Follow `chaos-engine/skills/chaos-engine/SKILL.md`", merged)
        self.assertEqual([], module.consume_merge_handoffs())
        foreign = (
            "<!-- CHAOSENGINE:START -->\n"
            "This is my own note.\n"
            "<!-- CHAOSENGINE:END -->\n"
        )
        self.assertEqual(
            foreign.encode(),
            module.merge_instruction(foreign.encode(), module.agents_md_block(), relative="AGENTS.md"),
        )
        self.assertTrue(module.consume_merge_handoffs())

    def test_foreign_skill_bytes_still_raise_host_adapter_drift(self):
        module = load("chaos_engine_universal_foreign_skill")
        with tempfile.TemporaryDirectory() as temporary:
            project = self._project(temporary)
            with mock.patch.object(module, "sync_grok_user_lean_config", return_value={"status": "skipped"}):
                module.install(project, core_commit="1" * 40)
                project.joinpath(".agents/skills/chaos-engine/SKILL.md").write_text(
                    "user owned skill\n", encoding="utf-8"
                )
                with self.assertRaisesRegex(ValueError, "host adapter drift detected"):
                    module.install(project, core_commit="2" * 40)


if __name__ == "__main__":
    unittest.main()
