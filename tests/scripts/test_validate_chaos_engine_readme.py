"""Source-derived ChaosEngine README inventory contracts (#5307)."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import sys as _sys; from pathlib import Path as _Path; _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))  # noqa: E402,E702 - self-locating under python3 -I (#7197)
from scripts.ci import validate_chaos_engine_readme as readme_owner
from scripts.ci.validate_chaos_engine_readme import inventory_sections, validate


ROOT = Path(__file__).resolve().parents[2]


def _ignore_repo_copy(directory, contents):
    """Skip VCS, install state, and repo-root tmp directories.

    Host tests park ``TemporaryDirectory(dir=ROOT)`` on the checkout so a parent
    walk can see the repo. Parallel ``pytest -n`` deletes those directories
    while this copy is walking them.
    """
    ignored = set(
        shutil.ignore_patterns(
            ".git", "__pycache__", ".chaos-engine", ".chaos-engine-state"
        )(directory, contents)
    )
    if Path(directory).resolve() == ROOT.resolve():
        ignored.update(name for name in contents if name.startswith("tmp"))
    return ignored


def _ephemeral_copy_error(error: shutil.Error) -> bool:
    """True when every copy error is a temp directory deleted by a parallel test."""
    rows = error.args[0] if error.args else []
    if not rows:
        return False
    for row in rows:
        if not isinstance(row, tuple) or len(row) < 3:
            return False
        if not Path(str(row[0])).name.startswith("tmp"):
            return False
        if "No such file or directory" not in str(row[2]):
            return False
    return True


def copy_checkout(source: Path, destination: Path, **kwargs) -> None:
    """Copy a checkout. A vanished ``tmp*`` entry from another worker is not a failure."""
    try:
        shutil.copytree(source, destination, **kwargs)
    except shutil.Error as error:
        if not _ephemeral_copy_error(error):
            raise


def _copy_repo(destination: Path) -> None:
    copy_checkout(ROOT, destination, dirs_exist_ok=True, ignore=_ignore_repo_copy)


class ChaosEngineReadmeInventoryTest(unittest.TestCase):
    def test_write_generated_refreshes_inventory_and_second_run_is_clean(self):
        write_generated = getattr(readme_owner, "write_generated", None)
        self.assertTrue(callable(write_generated))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _copy_repo(root)
            readme = root / "docs/source-inventory.md"
            original = readme.read_text(encoding="utf-8")
            readme.write_text(
                original.replace("| uv |", "| ux |", 1),
                encoding="utf-8",
            )
            self.assertTrue(any("managed-dependencies" in error for error in validate(root)))

            write_generated(root)
            self.assertEqual([], validate(root))
            after_first = readme.read_text(encoding="utf-8")
            write_generated(root)
            self.assertEqual(after_first, readme.read_text(encoding="utf-8"))

    def test_repository_readme_matches_every_source_derived_inventory(self):
        self.assertEqual([], validate(ROOT))
        sections = inventory_sections(ROOT)

        uv_pin = json.loads((ROOT / "dependencies.json").read_text(encoding="utf-8"))["tools"]["uv"]["package"]
        self.assertIn(uv_pin, sections["managed-dependencies"])
        self.assertIn("tree-sitter-sql==0.3.11", sections["managed-dependencies"])
        for skill in (
            "chaos-engine",
            "caveman",
            "ponytail",
            "freetoken",
            "local-agency",
            "local-coding-delegate",
            "local-openai-compat",
            "omniroute",
            "work-item",
        ):
            self.assertIn(skill, sections["skills"])
        for host in ("codex", "claude", "gemini", "grok", "copilot"):
            self.assertIn(f"| {host} |", sections["hosts"])
        for event in ("SessionStart", "PreToolUse", "Stop", "SessionEnd"):
            self.assertIn(f"| {event} |", sections["lifecycle-events"])
        self.assertIn("probe_hardware.py", sections["python-libraries"])
        self.assertIn("| platform |", sections["python-libraries"])

    def test_unknown_skill_and_one_changed_inventory_byte_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _copy_repo(root)
            extra = root / "skills/untracked-capability/SKILL.md"
            extra.parent.mkdir(parents=True)
            extra.write_text(
                "---\nname: untracked-capability\ndescription: Newly declared skill.\n---\n",
                encoding="utf-8",
            )
            errors = validate(root)
            self.assertTrue(any("skills" in error for error in errors), errors)

            extra.unlink()
            extra.parent.rmdir()
            readme = root / "docs/source-inventory.md"
            content = readme.read_text(encoding="utf-8").replace("| uv |", "| ux |", 1)
            readme.write_text(content, encoding="utf-8")
            byte_errors = validate(root)
            self.assertTrue(
                any("managed-dependencies" in error for error in byte_errors),
                byte_errors,
            )

    def test_missing_mermaid_flow_is_reported(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _copy_repo(root)
            diagram = root / "guides/architecture.md"
            content = diagram.read_text(encoding="utf-8").replace(
                "accTitle: Rollback flow", "accTitle: Removed rollback flow", 1
            )
            diagram.write_text(content, encoding="utf-8")

            self.assertTrue(any("Rollback flow" in error for error in validate(root)))

    def test_root_temp_directory_is_left_out_of_the_readme_copy(self):
        """A parallel host test parks a tmp directory on the repo root.

        Copying the tree for an inventory check must not require that directory
        to still be there, and must not treat it as packaged source.
        """
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            name = Path(temporary).name
            self.assertTrue(name.startswith("tmp"), name)
            with tempfile.TemporaryDirectory() as destination:
                _copy_repo(Path(destination))
                self.assertFalse((Path(destination) / name).exists(), name)

    def test_new_packaged_python_source_cannot_disappear_from_inventory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _copy_repo(root)
            (root / "new_runtime.py").write_text(
                "import fractions\n", encoding="utf-8"
            )

            errors = validate(root)

            self.assertTrue(any("python-libraries" in error for error in errors), errors)

    def test_malformed_mermaid_edge_is_rejected_by_the_parser(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _copy_repo(root)
            diagram = root / "guides/architecture.md"
            content = diagram.read_text(encoding="utf-8").replace(
                "Intent[Write rollback intent] --> Previous[Authenticate prior core and hosts]",
                "Intent[[Write rollback intent] --> Previous[Authenticate prior core and hosts]",
                1,
            )
            diagram.write_text(content, encoding="utf-8")

            self.assertTrue(any("Mermaid syntax" in error for error in validate(root)))


if __name__ == "__main__":
    unittest.main()
