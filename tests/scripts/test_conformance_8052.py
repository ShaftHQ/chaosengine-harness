"""#8052 R1-R2: offline layout conformance and docs drift. No network. No model API."""

from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(path: Path, name: str):
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


class ConformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hosts = load(ROOT / "runtime" / "hosts.py", "ce_hosts_8052")
        cls.conformance = load(ROOT / "runtime" / "conformance.py", "ce_conformance_8052")

    def _write_current(self, project: Path) -> None:
        (project / "AGENTS.md").write_text(self.hosts.instruction_block(), encoding="utf-8")
        (project / "CLAUDE.md").write_bytes(self.hosts.claude_pointer_bytes())
        (project / "GEMINI.md").write_bytes(
            self.hosts.import_pointer_instruction(None, relative="GEMINI.md")
        )
        github = project / ".github"
        github.mkdir()
        (github / "copilot-instructions.md").write_text(
            self.hosts.copilot_instruction_block(), encoding="utf-8",
        )
        codex = project / ".codex"
        codex.mkdir()
        (codex / "config.toml").write_bytes(self.hosts.codex_content(None, with_mcp=False))
        (codex / "hooks.json").write_bytes(self.hosts.lifecycle_hooks_document("codex"))
        grok = project / ".grok" / "hooks"
        grok.mkdir(parents=True)
        (grok / "lifecycle.json").write_bytes(self.hosts.lifecycle_hooks_document("grok"))
        gemini = project / ".gemini"
        gemini.mkdir()
        raw = self.hosts.json_content(None, relative=".gemini/settings.json", with_mcp=False)
        merged = self.hosts.hook_content(
            self.hosts.without_chaos_hooks(raw, "Gemini"),
            self.hosts.gemini_hooks_document(),
            "Gemini",
        )
        (gemini / "settings.json").write_bytes(merged)

    def test_current_install_passes_and_pins_match_excerpts(self):
        fixture = self.conformance.load_fixture()
        self.assertIn("future", fixture)
        self.assertNotIn("golden", fixture["name"])
        for pin in fixture["pins"]:
            self.assertEqual(pin["content_sha256"], self.conformance.excerpt_hash(pin["recorded_excerpt"]))
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            self._write_current(project)
            self.assertEqual([], self.conformance.check_layout(project, fixture))

    def test_instruction_catalog_tracks_marker_policy_files(self):
        self.assertEqual(
            [],
            self.conformance.check_instruction_catalog(ROOT, self.hosts.MARKER_POLICY_FILES),
        )
        inventory = json.loads(
            (ROOT / "references" / "instruction-inventory.json").read_text(encoding="utf-8")
        )
        conflicts = json.loads(
            (ROOT / "references" / "instruction-conflicts.json").read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory() as temporary:
            tree = Path(temporary)
            refs = tree / "references"
            refs.mkdir()
            dropped = [row for row in inventory["class_i"] if row["glob"] != "AGENTS.md"]
            (refs / "instruction-inventory.json").write_text(
                json.dumps({**inventory, "class_i": dropped}),
                encoding="utf-8",
            )
            (refs / "instruction-conflicts.json").write_text(
                json.dumps(conflicts),
                encoding="utf-8",
            )
            missing_glob = self.conformance.check_instruction_catalog(
                tree, self.hosts.MARKER_POLICY_FILES
            )
            self.assertTrue(any("AGENTS.md" in item for item in missing_glob))
            kept = [row for row in conflicts["rules"] if row["id"] != "IC-06"]
            (refs / "instruction-inventory.json").write_text(
                json.dumps(inventory),
                encoding="utf-8",
            )
            (refs / "instruction-conflicts.json").write_text(
                json.dumps({**conflicts, "rules": kept}),
                encoding="utf-8",
            )
            missing_rule = self.conformance.check_instruction_catalog(
                tree, self.hosts.MARKER_POLICY_FILES
            )
            self.assertTrue(any("IC-06" in item for item in missing_rule))

    def test_wrong_filename_and_disallowed_keys_fail(self):
        fixture = self.conformance.load_fixture()
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            self._write_current(project)
            (project / "CLAUDE.md").unlink()
            (project / "CLAUDE.txt").write_text(self.hosts.instruction_block(), encoding="utf-8")
            errors = self.conformance.check_layout(project, fixture)
            self.assertTrue(any("CLAUDE.md" in item for item in errors))
            self.assertTrue(any("CLAUDE.txt" in item for item in errors))

        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            self._write_current(project)
            gemini = project / ".gemini" / "settings.json"
            document = json.loads(gemini.read_text(encoding="utf-8"))
            document["not_in_pin"] = True
            document["context"] = {"fileName": "AGENTS.md", "apiKey": "nope"}
            gemini.write_text(json.dumps(document), encoding="utf-8")
            codex = project / ".codex" / "config.toml"
            codex.write_text(codex.read_text(encoding="utf-8") + "not_in_pin = true\n", encoding="utf-8")
            grok = project / ".grok" / "hooks" / "lifecycle.json"
            hook = json.loads(grok.read_text(encoding="utf-8"))
            hook["not_in_pin"] = True
            grok.write_text(json.dumps(hook), encoding="utf-8")
            rules = project / ".cursor" / "rules"
            rules.mkdir(parents=True)
            (rules / "policy.md").write_text("ignored plain markdown\n", encoding="utf-8")
            errors = self.conformance.check_layout(project, fixture)
            self.assertTrue(any("not_in_pin" in item and "settings.json" in item for item in errors))
            self.assertTrue(any("context.apiKey" in item for item in errors))
            self.assertTrue(any("not_in_pin" in item and "config.toml" in item for item in errors))
            self.assertTrue(any("not_in_pin" in item and "lifecycle.json" in item for item in errors))
            self.assertTrue(any("plain markdown rule" in item for item in errors))

    def test_planted_hash_mismatch_is_reported_with_the_pin(self):
        pin = {
            "id": "claude",
            "url": "https://code.claude.com/docs/en/claude-md",
            "content_sha256": self.conformance.excerpt_hash("original"),
        }

        def fetch(_url: str) -> tuple[int, bytes]:
            return 200, b"changed"

        result = self.conformance.check_docs_drift([pin], fetch)[0]
        self.assertEqual("fail", result["status"])
        self.assertIn(pin["url"], result["pin"])
        self.assertIn(pin["url"], result["detail"])
        self.assertIn("update the fixture", result["detail"])

    def test_withheld_network_and_http_5xx_are_not_a_pass(self):
        pin = {
            "url": "https://geminicli.com/docs/cli/gemini-md/",
            "content_sha256": "abc",
        }

        def withheld(_url: str) -> tuple[int, bytes]:
            raise ConnectionError("network withheld")

        def unavailable(_url: str) -> tuple[int, bytes]:
            return 503, b""

        down = self.conformance.check_docs_drift([pin], withheld)[0]
        server = self.conformance.check_docs_drift([pin], unavailable)[0]
        self.assertEqual("error", down["status"])
        self.assertNotEqual("pass", down["status"])
        self.assertIn(pin["url"], down["detail"])
        self.assertEqual("skip-with-warning", server["status"])
        self.assertNotEqual("pass", server["status"])
        self.assertIn("503", server["detail"])
        self.assertIn(pin["url"], server["detail"])

    def test_five_tool_layouts_match_pinned_fixtures(self):
        fixture = self.conformance.load_fixture()
        self.assertEqual(
            ["claude", "codex", "gemini", "cursor", "grok"],
            list(fixture["tools"]),
        )
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            self._write_current(project)
            layouts = self.conformance.check_tool_layouts(project, fixture)
            for tool, errors in layouts.items():
                self.assertEqual([], errors, tool)

    def test_failed_fetch_is_not_unchanged(self):
        pin = {
            "url": "https://cursor.com/docs/rules",
            "content_sha256": "abc",
        }

        def withheld(_url: str) -> tuple[int, bytes]:
            raise ConnectionError("network withheld")

        def unavailable(_url: str) -> tuple[int, bytes]:
            return 503, b""

        for result in (
            self.conformance.check_docs_drift([pin], withheld)[0],
            self.conformance.check_docs_drift([pin], unavailable)[0],
        ):
            self.assertEqual("fetch-failed", result["classification"])
            self.assertNotEqual("unchanged", result["classification"])
            self.assertNotIn("unchanged", result["detail"])

    def test_disagreeing_published_example_fails_or_warns(self):
        fixture = self.conformance.load_fixture()
        with tempfile.TemporaryDirectory() as temporary:
            pages = Path(temporary)
            for tool, entry in (
                ("claude", "CLAUDE.txt"),
                ("codex", "AGENTS.md"),
                ("gemini", "GEMINI.md"),
                ("cursor", "AGENTS.md"),
                ("grok", "AGENTS.md"),
            ):
                (pages / f"{tool}.md").write_text(
                    f"<!-- host-doc-example: {tool}\nentry: {entry}\npaths: {entry}\n-->\n",
                    encoding="utf-8",
                )
            findings = self.conformance.published_example_findings(pages, fixture)
        self.assertTrue(any(item.startswith("fail:") and "disagrees" in item for item in findings))
        self.assertEqual([], self.conformance.published_example_findings(ROOT / "guides" / "tools", fixture))

    def test_plain_cursor_markdown_does_not_fail_other_tools(self):
        fixture = self.conformance.load_fixture()
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            self._write_current(project)
            rules = project / ".cursor" / "rules"
            rules.mkdir(parents=True)
            (rules / "policy.md").write_text("# policy\n", encoding="utf-8")
            layouts = self.conformance.check_tool_layouts(project, fixture)
        self.assertEqual([], layouts["claude"])
        self.assertEqual([], layouts["codex"])
        self.assertEqual([], layouts["gemini"])
        self.assertEqual([], layouts["grok"])
        self.assertTrue(any("policy.md" in item for item in layouts["cursor"]))

    def test_config_key_outside_the_pin_warns_for_every_tool(self):
        fixture = self.conformance.load_fixture()
        entries = {
            "claude": "AGENTS.md",
            "codex": "AGENTS.md",
            "gemini": "GEMINI.md",
            "cursor": "AGENTS.md",
            "grok": "AGENTS.md",
        }
        with tempfile.TemporaryDirectory() as temporary:
            pages = Path(temporary)
            for tool, entry in entries.items():
                (pages / f"{tool}.md").write_text(
                    f"<!-- host-doc-example: {tool}\nentry: {entry}\nconfig_keys: not_in_pin\n-->\n",
                    encoding="utf-8",
                )
            findings = self.conformance.published_example_findings(pages, fixture)
        for tool in entries:
            self.assertTrue(
                any(item.startswith("warn:") and tool in item and "not_in_pin" in item for item in findings),
                findings,
            )

    def test_hook_event_registry_matches_pins(self):
        fixture = self.conformance.load_fixture()
        pins = fixture["hook_events"]
        self.assertEqual(
            ["claude", "codex", "grok", "gemini", "copilot", "cursor", "opencode", "antigravity"],
            [pin["host"] for pin in pins],
        )
        for pin in pins:
            self.assertEqual(pin["content_sha256"], self.conformance.excerpt_hash(pin["recorded_excerpt"]))
            self.assertTrue(pin["url"])
            self.assertTrue(pin["retrieved"])
            self.assertIn(pin["fail_default"], {"fail-open", "fail-closed"})
        registry = self.conformance.production_hook_registry()
        self.assertEqual([], self.conformance.check_hook_event_registry(registry, pins))
        codex = next(pin for pin in pins if pin["host"] == "codex")
        self.assertNotIn("PostToolUseFailure", codex["native_events"])
        self.assertNotIn("PostToolUseFailure", registry["codex"])
        self.assertIn("PostToolUseFailure is not an official Codex event", codex["blocks"])
        self.assertIn("PreCompact", registry["codex"])
        self.assertIn("PostCompact", registry["grok"])
        self.assertNotIn("session_start", registry["grok"])

    def test_checker_fails_when_a_registered_name_is_missing_from_the_pin(self):
        fixture = self.conformance.load_fixture()
        pins = json.loads(json.dumps(fixture["hook_events"]))
        registry = self.conformance.production_hook_registry()
        host = "codex"
        missing = "PreCompact"
        self.assertIn(missing, registry[host])
        pin = next(item for item in pins if item["host"] == host)
        pin["native_events"] = [event for event in pin["native_events"] if event != missing]
        errors = self.conformance.check_hook_event_registry(registry, pins)
        self.assertTrue(any(host in item and missing in item and pin["url"] in item for item in errors))

    def test_unknown_event_and_unpinned_alias_name_the_pin(self):
        fixture = self.conformance.load_fixture()
        pins = fixture["hook_events"]
        url = next(pin["url"] for pin in pins if pin["host"] == "cursor")
        unknown = self.conformance.check_hook_event_registry({"cursor": {"workspaceOpen"}}, pins)
        self.assertTrue(any("cursor" in item and "workspaceOpen" in item and url in item for item in unknown))
        alias = self.conformance.check_hook_event_registry({"codex": {"PostToolUseFailure"}}, pins)
        codex_url = next(pin["url"] for pin in pins if pin["host"] == "codex")
        self.assertTrue(any("codex" in item and "PostToolUseFailure" in item and codex_url in item for item in alias))

    def test_hook_drift_review_does_not_adopt_and_a_failed_fetch_is_not_a_pass(self):
        fixture = self.conformance.load_fixture()
        pin = dict(fixture["hook_events"][0])
        before = list(pin["native_events"])

        def extra(_url: str) -> tuple[int, bytes]:
            body = pin["recorded_excerpt"] + " workspaceOpen"
            return 200, body.encode()

        def withheld(_url: str) -> tuple[int, bytes]:
            raise ConnectionError("network withheld")

        reviewed = self.conformance.check_hook_event_drift([pin], extra)[0]
        failed = self.conformance.check_hook_event_drift([pin], withheld)[0]
        self.assertEqual("drift: review", reviewed["status"])
        self.assertFalse(reviewed["adopted"])
        self.assertIn("workspaceOpen", reviewed["detail"])
        self.assertEqual(before, list(pin["native_events"]))
        self.assertEqual("error", failed["status"])
        self.assertNotEqual("pass", failed["status"])
        self.assertEqual("fetch-failed", failed["classification"])

    def test_unmeasured_golden_check_is_not_a_pass(self):
        corpus = self.conformance.load_golden_corpus()
        task = corpus["tasks"][0]
        scored = self.conformance.run_golden_task(task)
        self.assertNotEqual("pass", scored["overall"])
        self.assertIn(scored["overall"], {"unknown", "skipped"})
        planted = self.conformance.ledger_check_status({"id": "guessed", "status": "pass", "measured": False})
        self.assertNotEqual("pass", planted)
        self.assertEqual("unknown", planted)
        omitted = self.conformance.ledger_check_status({"id": "guessed", "status": "pass", "measured": True})
        self.assertNotEqual("pass", omitted)
        self.assertEqual("unknown", omitted)
        ran = self.conformance.ledger_check_status(
            {"id": "guessed", "status": "pass", "measured": True, "ran": True}
        )
        self.assertEqual("pass", ran)

    def test_host_guides_name_every_registered_event(self):
        registry = self.conformance.production_hook_registry()
        self.assertEqual([], self.conformance.check_host_guide_events(registry))
        self.assertNotIn("PostToolUseFailure", registry["codex"])
        with tempfile.TemporaryDirectory() as temporary:
            guides = Path(temporary)
            shutil.copytree(ROOT / "guides" / "tools", guides, dirs_exist_ok=True)
            guide = guides / "antigravity.md"
            self.assertTrue(guide.is_file())
            removed = next(iter(registry["antigravity"]))
            guide.write_text(guide.read_text(encoding="utf-8").replace(removed, "removed-event"), encoding="utf-8")
            errors = self.conformance.check_host_guide_events(registry, guides)
            self.assertTrue(any("antigravity" in item and removed in item for item in errors), errors)

    def test_nine_host_parity_score_keeps_grok_bot_out_of_hook_pins(self):
        self.assertEqual((9, 9), self.conformance.host_parity_score())
        registry = self.conformance.production_hook_registry()
        self.assertNotIn("grok-bot", registry)
        self.assertEqual(8, len(registry))


if __name__ == "__main__":
    unittest.main()
