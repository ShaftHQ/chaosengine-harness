"""Installer legacy-path migration and consumer payload lean-out."""

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


def load_installer():
    spec = importlib.util.spec_from_file_location(
        "chaos_engine_installer_path_migration", ROOT / "install.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("install.py could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


INSTALL = load_installer()
EXCLUDED_CI = (
    "scripts/ci/watch_upstream_pins.py",
    "scripts/ci/installer_contract_cell.py",
    "scripts/ci/assemble_chaos_engine_plugin.py",
    "scripts/ci/ceiling_raise.py",
    "scripts/ci/check_plugin_changelog_version.py",
    "scripts/ci/sync_ce_ui.py",
    "scripts/ci/contract_http/sitecustomize.py",
)
KEPT_CI = (
    "scripts/ci/ce_version.py",
    "scripts/ci/agent_guidance_budget.json",
    "scripts/ci/overlay_pre_push.py",
    "scripts/ci/render_brand_mark.py",
    "scripts/ci/validate_agent_guidance.py",
    "scripts/ci/validate_chaos_engine_readme.py",
    "scripts/ci/harness_reachability.py",
    "scripts/ci/validate_skills.py",
    "scripts/ci/agent_harness_parity.json",
)
EXCLUDED_DETAILS = (
    "references/details/ce-lessons-2026-11-21/learn-retrospective.md",
    "references/details/ce-repeat-failure-pdca/repeat-failure-pdca.md",
)
KEPT_DETAILS = (
    "references/details/bot-entry-on-demand.md",
    "references/details/retro-spec-index.md",
    "references/details/narration-review.md",
    "references/details/work-github-playbook-promotion.md",
    "references/details/ce-rules-2026-10-31-12/mega-pr.md",
    "references/details/ce-lessons-2026-11-02/status-board.md",
)


def _healthy_overlay(project: Path) -> None:
    target = project / ".chaos-engine"
    target.mkdir()
    manifest = {
        "schemaVersion": INSTALL.SCHEMA_VERSION,
        "distribution": {"id": "portable", "policySha256": "0" * 64},
        "source": {"commit": "a" * 40, "kind": "local"},
        "files": {},
        "hostToken": "b" * 64,
    }
    (target / INSTALL.MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")


class LegacyPathMigrationTest(unittest.TestCase):
    def test_upgrade_cleans_pointers_orphans_and_a_verified_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            _healthy_overlay(project)
            before = b"USER-BEFORE chaos-engine/tool.py stays\n"
            after = b"USER-AFTER chaos-engine/identity.md stays\n"
            hash_block = b"# CHAOSENGINE:START\nchaos-engine/tool.py\n# CHAOSENGINE:END\n"
            inside = (
                b"<!-- CHAOSENGINE:START -->\n"
                b"Load chaos-engine/skills/chaos-engine/SKILL.md\n"
                b"and chaos-engine/identity.md plus chaos-engine/tool.py\n"
                b"Rules: references/ce-rules-2026-10-31-7.md\n"
                b"Already .chaos-engine/tool.py\n"
                b"<!-- CHAOSENGINE:END -->\n"
            )
            agents = project / "AGENTS.md"
            agents.write_bytes(before + hash_block + inside + after)
            claude_outside = b"leave chaos-engine/tool.py alone\n"
            (project / "CLAUDE.md").write_bytes(claude_outside)
            state = project / ".chaos-engine-state"
            state.mkdir()
            (state / "notes.txt").write_text("user-owned\n", encoding="utf-8")
            for index in range(5):
                path = state / f"orphaned-hosts-receipt-{index}.json"
                path.write_text("{}\n", encoding="utf-8")
                os.utime(path, (1_700_000_000 + index, 1_700_000_000 + index))
            anchor_old = state / "orphaned-.chaos-engine-hosts.active-old"
            anchor_new = state / "orphaned-.chaos-engine-hosts.active-new"
            anchor_old.write_bytes(b"old")
            anchor_new.write_bytes(b"new")
            os.utime(anchor_old, (1_700_000_000, 1_700_000_000))
            os.utime(anchor_new, (1_700_000_100, 1_700_000_100))
            backup = project / ".chaos-engine.backup.old"
            backup.mkdir()
            (backup / "stale.txt").write_text("stale\n", encoding="utf-8")
            target_dir = project / "backup-target"
            target_dir.mkdir()
            (target_dir / "keep.txt").write_text("keep\n", encoding="utf-8")
            link = project / ".chaos-engine-uninstall-old-backup"
            link.symlink_to(target_dir, target_is_directory=True)
            palace = state / "mempalace"
            palace.mkdir()
            (palace / "documentation-pages.json").write_bytes(b'{"pages":1}\n')
            parent_sidecar = state / "mempalace-source-revision.json"
            parent_sidecar.write_bytes(b"already\n")
            (palace / ".chaos-engine-source-revision.json").write_bytes(b"legacy\n")

            summary = INSTALL.migrate_legacy_paths(project)
            again = INSTALL.migrate_legacy_paths(project)

            text = agents.read_bytes()
            self.assertTrue(text.startswith(before))
            self.assertTrue(text.endswith(after))
            self.assertIn(hash_block, text)
            self.assertIn(b".chaos-engine/skills/chaos-engine/SKILL.md", text)
            self.assertIn(b".chaos-engine/identity.md", text)
            self.assertIn(b".chaos-engine/tool.py", text)
            self.assertIn(b".chaos-engine/references/permanent-rules.md", text)
            self.assertNotIn(b"Load chaos-engine/skills", text)
            self.assertNotIn(b"references/ce-rules-2026-10-31-7.md", text)
            self.assertEqual(claude_outside, (project / "CLAUDE.md").read_bytes())
            self.assertEqual("user-owned\n", (state / "notes.txt").read_text(encoding="utf-8"))
            remaining = sorted(path.name for path in state.glob("orphaned-hosts-receipt-*.json"))
            self.assertEqual(["orphaned-hosts-receipt-4.json"], remaining)
            self.assertFalse(anchor_old.exists())
            self.assertEqual(b"new", anchor_new.read_bytes())
            self.assertFalse(backup.exists())
            self.assertFalse(link.exists())
            self.assertFalse(link.is_symlink())
            self.assertEqual("keep\n", (target_dir / "keep.txt").read_text(encoding="utf-8"))
            self.assertEqual(b'{"pages":1}\n', (state / "mempalace-documentation-pages.json").read_bytes())
            self.assertFalse((palace / "documentation-pages.json").exists())
            self.assertEqual(b"already\n", parent_sidecar.read_bytes())
            self.assertFalse((palace / ".chaos-engine-source-revision.json").exists())
            self.assertEqual([], again["pointersRewritten"])
            self.assertEqual([], again["backupsRemoved"])
            self.assertEqual([], again["orphans"]["receiptsRemoved"])
            self.assertIn("AGENTS.md", summary["pointersRewritten"])
            self.assertEqual(4, len(summary["orphans"]["receiptsRemoved"]))

    def test_unverified_install_keeps_the_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            backup = project / ".chaos-engine.backup.old"
            backup.mkdir()
            (backup / "mine.txt").write_text("mine\n", encoding="utf-8")
            summary = INSTALL.migrate_legacy_paths(project)
            self.assertEqual([], summary["backupsRemoved"])
            self.assertEqual("mine\n", (backup / "mine.txt").read_text(encoding="utf-8"))

    def test_guided_upgrade_requests_graphify_extra_repair(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            args = SimpleNamespace(
                project=project,
                source=ROOT,
                commit="c" * 40,
                dry_run=False,
                no_input=True,
                consumer=False,
                allow_dirty=False,
                force_replace_source_tree=False,
                include_local=False,
                config_path=None,
                _user_scope=False,
                _user_scope_also=False,
            )
            with (
                mock.patch.object(INSTALL, "_apply_install_config"),
                mock.patch.object(INSTALL, "_instruction_replace", return_value=None),
                mock.patch.object(INSTALL, "_guided_pin", return_value=(ROOT, "c" * 40)),
                mock.patch.object(
                    INSTALL, "_publish_guided_overlay", return_value=project / ".chaos-engine"
                ),
                mock.patch.object(INSTALL, "_strip_retired_mcp"),
                mock.patch.object(INSTALL, "_rebind_contract_drift"),
                mock.patch.object(INSTALL, "_contract_blockers", return_value=[]),
                mock.patch.object(INSTALL, "_repair_graphify_extra_after_upgrade") as repair,
                mock.patch.object(INSTALL, "migrate_legacy_paths", return_value={}) as migrate,
            ):
                result = INSTALL._run_guided_upgrade(args)
        self.assertEqual("installed", result["status"])
        repair.assert_called_once()
        migrate.assert_called()

    def test_pytest_skips_the_live_graphify_reinstall(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            overlay = project / ".chaos-engine"
            overlay.mkdir()
            (overlay / "dependencies.json").write_text("{}\n", encoding="utf-8")
            with mock.patch.object(INSTALL, "load_dependency_controller") as loader:
                INSTALL._repair_graphify_extra_after_upgrade(project)
        loader.assert_not_called()


class ConsumerPayloadLeanTest(unittest.TestCase):
    def test_origin_only_ci_and_historical_retros_stay_out_of_the_payload(self):
        for relative in EXCLUDED_CI + EXCLUDED_DETAILS:
            self.assertTrue(INSTALL.is_origin_only(Path(relative)), relative)
            self.assertTrue((ROOT / relative).is_file(), relative)
        for relative in KEPT_CI + KEPT_DETAILS:
            self.assertFalse(INSTALL.is_origin_only(Path(relative)), relative)
            self.assertTrue((ROOT / relative).is_file(), relative)
        payload = {
            path.relative_to(ROOT).as_posix()
            for path in INSTALL.source_files(ROOT)
        }
        for relative in EXCLUDED_CI + EXCLUDED_DETAILS:
            self.assertNotIn(relative, payload)
        for relative in KEPT_CI + KEPT_DETAILS:
            self.assertIn(relative, payload)

    def test_no_shipped_markdown_links_to_excluded_payload_files(self):
        import posixpath
        import re

        link_re = re.compile(r"(?<!!)\[[^]]*\]\(([^)\s#]+)(?:#[^)]*)?\)")
        uri_re = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)
        payload = {
            path.relative_to(ROOT).as_posix()
            for path in INSTALL.source_files(ROOT)
        }
        origin_doc_prefixes = ("guides/", "docs/")
        origin_doc_files = {
            "README.md",
            "INSTALL.md",
            "CONTRIBUTING.md",
            "CHANGELOG.md",
            "ROADMAP.md",
            "SECURITY.md",
            "CODE_OF_CONDUCT.md",
            "references/harness-files.md",
        }
        broken: list[str] = []
        for relative in sorted(payload):
            if not relative.endswith(".md"):
                continue
            parts = Path(relative).parts
            if parts[:1] == ("vendor",) or "templates" in parts or relative == "AGENTS.md":
                continue
            text = (ROOT / relative).read_text(encoding="utf-8", errors="replace")
            parent = posixpath.dirname(relative)
            for match in link_re.finditer(text):
                target = match.group(1).strip().strip("<>")
                if not target or uri_re.match(target) or target.startswith("/") or "{" in target:
                    continue
                resolved = posixpath.normpath(posixpath.join(parent, target)) if parent else posixpath.normpath(target)
                if resolved.startswith("../") or resolved.startswith(".chaos-engine"):
                    continue
                if resolved.startswith(origin_doc_prefixes) or resolved in origin_doc_files:
                    continue
                disk_path = ROOT / resolved
                if disk_path.is_dir():
                    continue
                if disk_path.is_file() and resolved not in payload:
                    broken.append(f"{relative} -> {target} ({resolved})")
        self.assertEqual([], broken)


if __name__ == "__main__":
    unittest.main()
