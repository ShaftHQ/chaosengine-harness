"""Verify local Codex plugins independently of unrelated marketplace latency."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import hosts  # noqa: E402


class CodexPluginVerificationScopeTest(unittest.TestCase):
    def test_slow_unrelated_marketplace_does_not_hide_installed_plugin(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            root = project / "marketplace"
            name = "chaos-engine-aabbccddeeff"
            plugin_id = f"chaos-engine@{name}"
            calls = []

            def runner(command, **options):
                calls.append(command)
                if command[1:4] == ["plugin", "marketplace", "list"]:
                    document = {"marketplaces": [{"name": name, "root": str(root)}]}
                elif command[1:3] == ["plugin", "list"]:
                    # An unrelated remote marketplace stalls the global catalog.
                    if "--marketplace" not in command:
                        raise subprocess.TimeoutExpired(command, options["timeout"])
                    self.assertEqual(name, command[command.index("--marketplace") + 1])
                    document = {"installed": [{
                        "pluginId": plugin_id, "version": "1.0.0",
                        "installed": True, "enabled": True,
                        "source": {"path": str(root / "plugins/chaos-engine")},
                    }]}
                else:
                    self.fail(f"unexpected command: {command}")
                return subprocess.CompletedProcess(command, 0, json.dumps(document), "")

            with mock.patch.object(hosts, "activation_contract", return_value=(root, name, plugin_id, "1.0.0")), mock.patch.object(
                hosts, "activation_plugins", return_value={"chaos-engine": {
                    "id": plugin_id, "version": "1.0.0",
                    "source": project / "plugins/chaos-engine",
                }}
            ), mock.patch.object(hosts, "remove_stale_marketplace_before_activation"):
                status = hosts.detected_plugin_status(
                    project, runner=runner,
                    which=lambda client: "codex" if client == "codex" else None,
                )
            self.assertEqual("healthy", status["codex"]["status"])
            self.assertEqual(2, len(calls))

    def test_listing_timeout_is_not_a_successful_empty_document(self):
        for client in ("codex", "claude"):
            with self.subTest(client=client):
                error = subprocess.TimeoutExpired(
                    [client, "plugin", "list", "--available", "--json"], 30
                )
                with self.assertRaises(subprocess.TimeoutExpired) as raised:
                    hosts.client_json(
                        client, error.cmd[1:], Path("."),
                        runner=mock.Mock(side_effect=error),
                    )
                self.assertIs(error, raised.exception)
