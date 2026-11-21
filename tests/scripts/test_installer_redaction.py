"""#130: fail-closed installer redaction and the ask-before-upstream prompt."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import socket
import unittest
import unittest.mock
import urllib.parse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    spec.loader.exec_module(module)
    return module


BOOTSTRAP = _load("chaos_engine_bootstrap_redact", ROOT / "bootstrap.py")

ASK = "Ask the user before opening or updating an upstream issue or PR, or pushing."


def _secrets() -> list[str]:
    """More than 200 secrets and home paths. Benign words are not in this list."""
    found: list[str] = []
    for index in range(30):
        suffix = f"{index:04d}"
        found.append(f"ghp_{'A' * 20}{suffix}")
        found.append(f"gho_{'B' * 20}{suffix}")
        found.append(f"github_pat_{'C' * 22}{suffix}")
    for index in range(20):
        suffix = f"{index:04d}"
        found.append(f"sk-{'D' * 24}{suffix}")
        found.append(f"xai-{'E' * 24}{suffix}")
        found.append(f"AIza{'F' * 30}{suffix}")
        found.append(f"AKIA{'G' * 12}{suffix}")
        found.append(f"glpat-{'H' * 20}{suffix}")
        found.append(f"user{index}:pass{index}word@")
    for index in range(15):
        found.append(f"/home/fuzzuser{index}/proj/file{index}")
        found.append(f"/Users/fuzzuser{index}/proj/file{index}")
        found.append(f"C:\\Users\\fuzzuser{index}\\proj\\file{index}")
        found.append(f"/mnt/c/Users/fuzzuser{index}/proj/file{index}")
        found.append(f"fuzzbearer{index}{'Z' * 16}")
    for index in range(15):
        found.append(f"envsecret{index}{'Q' * 16}")
    found.append("ClientMarkerZZZunique")
    return found


class RedactionTests(unittest.TestCase):
    def test_fuzz_secrets_absent_from_artifacts_and_url(self) -> None:
        secrets = _secrets()
        self.assertGreaterEqual(len(secrets), 200)
        env_values = [item for item in secrets if item.startswith("envsecret")]
        bearer_bodies = [item for item in secrets if item.startswith("fuzzbearer")]
        visible = [item for item in secrets if item not in bearer_bodies]
        blob = "word sk hex abc123 " + " ".join(visible)
        blob += " " + " ".join(f"Bearer {item}" for item in bearer_bodies)
        blob += " host " + socket.gethostname()
        with tempfile_project() as project:
            state = project / ".chaos-engine-state"
            state.mkdir(parents=True)
            core = project / ".chaos-engine"
            core.mkdir()
            (core / "install.py").write_text("# installer\n", encoding="utf-8")
            (state / "install-trace.json").write_text(blob, encoding="utf-8")
            error = BOOTSTRAP.InstallHealthError(
                "Verify installation",
                {
                    "status": "failed",
                    "commit": "a" * 40,
                    "components": {
                        "core": {
                            "status": "failed",
                            "taskImpact": "required",
                            "detail": blob,
                            "code": "CE_FUZZ",
                            "fixNext": "repair tools",
                        }
                    },
                },
            )
            stderr = io.StringIO()
            reporter = BOOTSTRAP.InstallReporter(stream=stderr)
            reporter.traces.append((1.0, blob))
            reporter.current_operation = "Verify installation"
            env = {
                key: value
                for key, value in os.environ.items()
                if key not in {"CHAOS_ENGINE_FILE_ISSUE", "GITHUB_TOKEN", "GH_TOKEN"}
            }
            for index, value in enumerate(env_values):
                env[f"FUZZ_{index}_TOKEN"] = value
            env["CHAOS_ENGINE_CLIENT_NAME_DENYLIST"] = "ClientMarkerZZZunique"
            env["LEAK_ME_FACT"] = "leakmarkerunique987"
            with unittest.mock.patch.dict(os.environ, env, clear=True), unittest.mock.patch.object(
                BOOTSTRAP.sys, "stderr", stderr
            ):
                BOOTSTRAP.emit_install_failure(
                    "CE-INSTALL-FAILED",
                    error,
                    "owner/repo",
                    reporter=reporter,
                    project=project,
                )
                BOOTSTRAP.write_install_trace(
                    project,
                    {"status": "failed", "note": blob},
                    [(1.0, blob)],
                )
            pieces = [stderr.getvalue()]
            for name in (
                "failure-report.txt",
                "agent-prompt.md",
                "heal-handoff.md",
                "install-console.log",
                "doctor-failure.json",
                "install-trace.json",
            ):
                pieces.append((state / name).read_text(encoding="utf-8"))
            combined = "\n".join(pieces)
            for secret in secrets:
                self.assertNotIn(secret, combined)
            self.assertNotIn(socket.gethostname(), combined)
            self.assertNotIn("leakmarkerunique987", combined)
            self.assertIn("word sk hex abc123", combined)
            self.assertIn(ASK, stderr.getvalue())
            self.assertNotIn("open or update an upstream", stderr.getvalue().casefold())
            self.assertNotIn("│", stderr.getvalue())
            prompt_file = (state / "agent-prompt.md").read_text(encoding="utf-8")
            self.assertNotIn("│", prompt_file)
            self.assertIn(prompt_file.strip("\n"), stderr.getvalue())
            handoff = (state / "heal-handoff.md").read_text(encoding="utf-8")
            self.assertIn(".chaos-engine-state/failure-report.txt", handoff)
            self.assertIn(".chaos-engine-state/agent-prompt.md", handoff)
            doctor = json.loads((state / "doctor-failure.json").read_text(encoding="utf-8"))
            self.assertNotIn("fuzzuser0", json.dumps(doctor))

    def test_prompt_asks_before_upstream(self) -> None:
        prompt = BOOTSTRAP.heal_handoff_prompt(
            "python3 .chaos-engine/install.py doctor --project . --json",
            "https://github.com/owner/repo/issues/new?template=chaos-engine-installer.yml&title=x",
        )
        self.assertIn(ASK, prompt)
        self.assertNotIn("open or update an upstream", prompt.casefold())
        self.assertIn("do not rerun it", prompt)
        self.assertIn("doctor --json", prompt)
        self.assertNotIn("issues/new?", prompt)

    def test_file_denylist_stays_out_of_the_issue_url(self) -> None:
        marker = "AcmeClientZZ"
        with tempfile_project() as project:
            state = project / ".chaos-engine-state"
            state.mkdir(parents=True)
            core = project / ".chaos-engine"
            core.mkdir()
            (core / "install.py").write_text("# installer\n", encoding="utf-8")
            (state / "client-name-denylist.txt").write_text(marker + "\n", encoding="utf-8")
            reporter = BOOTSTRAP.InstallReporter(stream=io.StringIO())
            reporter.traces.append((1.0, f"last {marker}"))
            stderr = io.StringIO()
            env = {
                key: value
                for key, value in os.environ.items()
                if key not in {"CHAOS_ENGINE_CLIENT_NAME_DENYLIST", "CHAOS_ENGINE_FILE_ISSUE"}
            }
            with unittest.mock.patch.dict(os.environ, env, clear=True), unittest.mock.patch.object(
                BOOTSTRAP.sys, "stderr", stderr
            ):
                BOOTSTRAP.emit_install_failure(
                    "CE-INSTALL-FAILED",
                    RuntimeError(f"boom at {marker} path"),
                    "owner/repo",
                    reporter=reporter,
                    project=project,
                )
            report = (state / "failure-report.txt").read_text(encoding="utf-8")
            decoded = urllib.parse.unquote(stderr.getvalue() + "\n" + report)
            handoff = (state / "heal-handoff.md").read_text(encoding="utf-8")
            self.assertNotIn(marker, decoded)
            self.assertNotIn(marker, handoff)
            self.assertIn("<redacted:client-name>", decoded)

    def test_short_secret_env_value_is_absent_from_url_and_handoff(self) -> None:
        secret = "secret1"
        with tempfile_project() as project:
            core = project / ".chaos-engine"
            core.mkdir(parents=True)
            (core / "install.py").write_text("# installer\n", encoding="utf-8")
            stderr = io.StringIO()
            env = {
                key: value
                for key, value in os.environ.items()
                if key != "CHAOS_ENGINE_FILE_ISSUE"
            }
            env["SHORT_PASSWORD"] = secret
            with unittest.mock.patch.dict(os.environ, env, clear=True), unittest.mock.patch.object(
                BOOTSTRAP.sys, "stderr", stderr
            ):
                BOOTSTRAP.emit_install_failure(
                    "CE-INSTALL-FAILED",
                    RuntimeError(f"failed with {secret}"),
                    "owner/repo",
                    project=project,
                )
            report = (project / ".chaos-engine-state" / "failure-report.txt").read_text(
                encoding="utf-8"
            )
            output = urllib.parse.unquote(stderr.getvalue() + "\n" + report)
            handoff = (project / ".chaos-engine-state" / "heal-handoff.md").read_text(
                encoding="utf-8"
            )
            self.assertNotIn(secret, output)
            self.assertNotIn(secret, handoff)
            self.assertIn("<redacted:env>", output)

    def test_redaction_failure_withholds_artifact(self) -> None:
        with tempfile_project() as project:
            state = project / ".chaos-engine-state"
            state.mkdir(parents=True)
            reporter = BOOTSTRAP.InstallReporter(stream=io.StringIO())
            reporter.traces.append((1.0, "home /home/secret/proj token=super-secret"))
            with unittest.mock.patch.object(BOOTSTRAP, "redact", side_effect=RuntimeError("boom")):
                BOOTSTRAP.write_failure_artifacts(
                    project,
                    reporter,
                    RuntimeError("home /home/secret/proj token=super-secret"),
                )
            console = (state / "install-console.log").read_text(encoding="utf-8")
            doctor = (state / "doctor-failure.json").read_text(encoding="utf-8")
            self.assertIn("redaction failed; artifact withheld", console + doctor)
            self.assertNotIn("super-secret", console + doctor)
            self.assertNotIn("/home/secret", console + doctor)

    def test_telemetry_allowlist_drops_other_keys(self) -> None:
        kept = BOOTSTRAP.telemetry_allowlist(
            {
                "os_name": "Linux",
                "HOME": "/home/someone",
                "GITHUB_TOKEN": "ghp_" + "A" * 20,
                "kernel": "6.8.0",
            }
        )
        self.assertEqual({"os_name": "Linux", "kernel": "6.8.0"}, kept)

    def test_controls_stripped_from_external_error_text(self) -> None:
        cause = BOOTSTRAP.one_line_cause(
            RuntimeError("branch\x1b[31m hidden\x00 name\x1b[0m")
        )
        self.assertNotIn("\x1b", cause)
        self.assertNotIn("\x00", cause)
        self.assertIn("hidden", cause)
        self.assertIn("name", cause)


class tempfile_project:  # noqa: N801 - small context helper, not a test.
    def __enter__(self) -> Path:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        return Path(self._tmp.name) / "project"

    def __exit__(self, *_args) -> None:
        self._tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
