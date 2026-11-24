"""#211: intake feasibility gate and output-secret no-echo script-read helper."""
from __future__ import annotations

import base64
import contextlib
import importlib.util
import io
import os
import subprocess  # nosec B404 - invokes the Python guard CLI on temp fixtures only
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUARD_PATH = ROOT / "runtime" / "secret_guard.py"
BOUNDARY_PATH = ROOT / "rules" / "operation_boundary.py"
BIGGER_PICTURE_PATH = ROOT / "references" / "bigger-picture-first.md"
CONSULT_FIRST_PATH = ROOT / "references" / "consult-first.md"

APP_ID = "bs://cloudapp998877665544"  # nosec B105 - synthetic test fixture
ACCESS_KEY = "SyntheticAccessKey2119988"  # nosec B105 - synthetic test fixture
YAML_TOKEN = "YamlCloudToken211776655"  # nosec B105 - synthetic test fixture
JSON_SECRET = "JsonCloudAppId211334455"  # nosec B105 - synthetic test fixture
ENV_SECRET = "EnvCloudSecret211667788"  # nosec B105 - synthetic test fixture


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReadSecretKeyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.guard = _load(GUARD_PATH, "secret_guard_211_read")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

        props_dir = self.root / "src/main/resources/properties"
        props_dir.mkdir(parents=True)
        (props_dir / "secrets.properties").write_text(
            "# comment line\n"
            f"browserstack.app={APP_ID}\n"
            f'browserStack.accessKey = "{ACCESS_KEY}"\n'
            "empty.key=\n",
            encoding="utf-8",
        )
        (self.root / "browserstack.yml").write_text(
            "# cloud config\n"
            f"userName: synthetic_user\n"
            f"accessKey: {YAML_TOKEN}  # inline note\n"
            "browserstack:\n"
            "  app: 'bs://nestedApp211000'\n",
            encoding="utf-8",
        )
        (self.root / "secrets.json").write_text(
            '{"topKey": "topSecretVal211", "cloud": {"appId": "' + JSON_SECRET + '"}}',
            encoding="utf-8",
        )
        (self.root / ".env").write_text(
            "# dotenv fixture\n"
            f'export CLOUD_SECRET="{ENV_SECRET}"\n'
            "PLAIN_ID=bs://plainEnv211\n",
            encoding="utf-8",
        )

    def test_reads_properties_yaml_json_and_env_without_echoing(self) -> None:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(APP_ID, self.guard.read_secret_key(self.root, "browserstack.app"))
            self.assertEqual(ACCESS_KEY, self.guard.read_secret_key(self.root, "browserStack.accessKey"))
            self.assertEqual(YAML_TOKEN, self.guard.read_secret_key(self.root, "accessKey"))
            self.assertEqual(
                "bs://nestedApp211000",
                self.guard.read_secret_key(self.root, "browserstack.app", files=["browserstack.yml"]),
            )
            self.assertEqual(
                JSON_SECRET,
                self.guard.read_secret_key(self.root, "cloud.appId", files=["secrets.json"]),
            )
            self.assertEqual(
                "topSecretVal211",
                self.guard.read_secret_key(self.root, "topKey", files=["secrets.json"]),
            )
            self.assertEqual(
                ENV_SECRET,
                self.guard.read_secret_key(self.root, "CLOUD_SECRET", files=[".env"]),
            )
            self.assertEqual(
                "bs://plainEnv211",
                self.guard.read_secret_key(self.root, "PLAIN_ID", files=[".env"]),
            )
        self.assertEqual("", out.getvalue())
        self.assertEqual("", err.getvalue())

    def test_missing_empty_or_invalid_inputs_return_none(self) -> None:
        (self.root / "broken.json").write_text("{not-json", encoding="utf-8")
        self.assertIsNone(self.guard.read_secret_key(self.root, "does.not.exist"))
        self.assertIsNone(self.guard.read_secret_key(self.root, ""))
        self.assertIsNone(self.guard.read_secret_key(self.root, "   "))
        self.assertIsNone(self.guard.read_secret_key(self.root, "empty.key"))
        self.assertIsNone(
            self.guard.read_secret_key(self.root, "anyKey", files=["missing.properties", "broken.json"])
        )

    def test_read_secret_key_rejects_absolute_and_parent_escape(self) -> None:
        project = self.root / "project"
        project.mkdir()
        outside = self.root / "outside.properties"
        outside.write_text(f"browserstack.app=LEAKED211OUTSIDE\n", encoding="utf-8")
        (project / "secrets.properties").write_text(
            f"browserstack.app={APP_ID}\n",
            encoding="utf-8",
        )
        self.assertIsNone(
            self.guard.read_secret_key(project, "browserstack.app", files=[str(outside)])
        )
        self.assertIsNone(
            self.guard.read_secret_key(project, "browserstack.app", files=["../outside.properties"])
        )
        self.assertIsNone(
            self.guard.read_secret_key(
                project, "browserstack.app", files=["/etc/passwd"]
            )
        )
        nested = project / "nested"
        nested.mkdir()
        self.assertEqual(
            APP_ID,
            self.guard.read_secret_key(
                project, "browserstack.app", files=["nested/../secrets.properties"]
            ),
        )
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = self.guard.exec_with_secrets(
                project,
                [("browserstack.app", "BS_APP")],
                [sys.executable, "-c", "print('ran')"],
                files=["../outside.properties"],
            )
        self.assertEqual(2, code)
        self.assertNotIn("LEAKED211OUTSIDE", out.getvalue() + err.getvalue())
        self.assertNotIn(APP_ID, out.getvalue() + err.getvalue())


class ExecWithSecretsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.guard = _load(GUARD_PATH, "secret_guard_211_exec")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        props_dir = self.root / "src/main/resources/properties"
        props_dir.mkdir(parents=True)
        (props_dir / "secrets.properties").write_text(
            f"browserstack.app={APP_ID}\n"
            f"browserStack.accessKey={ACCESS_KEY}\n",
            encoding="utf-8",
        )

    def test_exec_with_secrets_injects_env_and_redacts_accidental_echoes(self) -> None:
        script = (
            "import os, sys; "
            "app = os.environ['BS_APP']; "
            "key = os.environ['BS_KEY']; "
            "assert app.startswith('bs://') and len(app) > 10; "
            "assert len(key) > 10; "
            "print('stdout-leaked:' + app); "
            "print('stderr-leaked:' + key, file=sys.stderr); "
            "sys.exit(0)"
        )
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = self.guard.exec_with_secrets(
                self.root,
                [("browserstack.app", "BS_APP"), ("browserStack.accessKey", "BS_KEY")],
                [sys.executable, "-c", script],
            )
        self.assertEqual(0, code)
        self.assertIn("stdout-leaked:[REDACTED]", out.getvalue())
        self.assertIn("stderr-leaked:[REDACTED]", err.getvalue())
        combined = out.getvalue() + err.getvalue()
        self.assertNotIn(APP_ID, combined)
        self.assertNotIn(ACCESS_KEY, combined)

    def test_exec_with_secrets_scrubs_base64_and_url_encoded_forms(self) -> None:
        script = (
            "import base64, os, sys, urllib.parse\n"
            "app = os.environ['BS_APP']\n"
            "key = os.environ['BS_KEY']\n"
            "print(base64.b64encode(app.encode()).decode())\n"
            "print(urllib.parse.quote(app, safe=''))\n"
            "print(base64.b64encode(key.encode()).decode(), file=sys.stderr)\n"
            "print(urllib.parse.quote_plus(key), file=sys.stderr)\n"
        )
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = self.guard.exec_with_secrets(
                self.root,
                [("browserstack.app", "BS_APP"), ("browserStack.accessKey", "BS_KEY")],
                [sys.executable, "-c", script],
            )
        self.assertEqual(0, code)
        combined = out.getvalue() + err.getvalue()
        self.assertIn("[REDACTED]", out.getvalue())
        self.assertIn("[REDACTED]", err.getvalue())
        self.assertNotIn(APP_ID, combined)
        self.assertNotIn(ACCESS_KEY, combined)
        self.assertNotIn(base64.b64encode(APP_ID.encode()).decode(), combined)
        self.assertNotIn(base64.b64encode(ACCESS_KEY.encode()).decode(), combined)
        self.assertNotIn(urllib.parse.quote(APP_ID, safe=""), combined)
        self.assertNotIn(urllib.parse.quote_plus(ACCESS_KEY), combined)

    def test_exec_with_secrets_scrubs_lowercase_percent_encoding(self) -> None:
        script = (
            "import os, sys, urllib.parse\n"
            "app = os.environ['BS_APP']\n"
            "quoted = urllib.parse.quote(app, safe='')\n"
            "plus = urllib.parse.quote_plus(app)\n"
            "print(quoted.lower())\n"
            "print(plus.lower(), file=sys.stderr)\n"
            "mixed = quoted.replace('%3A', '%3a').replace('%2F', '%2f', 1)\n"
            "print(mixed)\n"
        )
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = self.guard.exec_with_secrets(
                self.root,
                [("browserstack.app", "BS_APP")],
                [sys.executable, "-c", script],
            )
        self.assertEqual(0, code)
        combined = out.getvalue() + err.getvalue()
        quoted = urllib.parse.quote(APP_ID, safe="")
        plus = urllib.parse.quote_plus(APP_ID)
        self.assertIn("[REDACTED]", combined)
        self.assertNotIn(quoted.lower(), combined)
        self.assertNotIn(plus.lower(), combined)
        self.assertNotIn("bs%3a%2f%2f", combined)
        mixed = quoted.replace("%3A", "%3a").replace("%2F", "%2f", 1)
        self.assertNotEqual(mixed, quoted)
        self.assertNotEqual(mixed.lower(), mixed)
        self.assertNotIn(mixed, combined)

    def test_exec_with_secrets_propagates_child_exit_code(self) -> None:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = self.guard.exec_with_secrets(
                self.root,
                [("browserstack.app", "BS_APP")],
                [sys.executable, "-c", "import os, sys; sys.exit(7 if os.environ.get('BS_APP') else 1)"],
            )
        self.assertEqual(7, code)

    def test_exec_with_secrets_missing_key_exits_2_without_running_child_or_leaking(self) -> None:
        marker = self.root / "ran.txt"
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = self.guard.exec_with_secrets(
                self.root,
                [("browserstack.app", "BS_APP"), ("missing.secret.key", "MISSING_VAR")],
                [sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).write_text('ran')"],
            )
        self.assertEqual(2, code)
        self.assertFalse(marker.exists())
        self.assertIn("missing.secret.key", err.getvalue())
        self.assertNotIn(APP_ID, out.getvalue() + err.getvalue())
        self.assertNotIn(ACCESS_KEY, out.getvalue() + err.getvalue())

    def test_exec_with_secrets_rejects_empty_command_or_bad_mapping(self) -> None:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(2, self.guard.exec_with_secrets(self.root, [("browserstack.app", "BS_APP")], []))
            self.assertEqual(
                2,
                self.guard.exec_with_secrets(
                    self.root, [("browserstack.app", "")], [sys.executable, "-c", "pass"]
                ),
            )

    def test_cli_exec_with_secret_injects_scrubs_and_fails_closed_on_missing_key(self) -> None:
        env = dict(os.environ)
        env["SECRET_GUARD_FILES"] = "src/main/resources/properties/secrets.properties"
        child = (
            "import os, sys; "
            "print('len=' + str(len(os.environ['CLOUD_APP_ID']))); "
            "print('raw=' + os.environ['CLOUD_APP_ID']); "
            "print('err=' + os.environ['CLOUD_KEY'], file=sys.stderr)"
        )
        ok = subprocess.run(  # nosec B603 - runs local guard CLI on temp fixture
            [
                sys.executable,
                str(GUARD_PATH),
                "--exec-with-secret",
                "browserstack.app=CLOUD_APP_ID",
                "--exec-with-secret",
                "browserStack.accessKey=CLOUD_KEY",
                "--",
                sys.executable,
                "-c",
                child,
            ],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, ok.returncode, ok.stderr)
        self.assertIn(f"len={len(APP_ID)}", ok.stdout)
        self.assertIn("raw=[REDACTED]", ok.stdout)
        self.assertIn("err=[REDACTED]", ok.stderr)
        self.assertNotIn(APP_ID, ok.stdout + ok.stderr)
        self.assertNotIn(ACCESS_KEY, ok.stdout + ok.stderr)

        missing = subprocess.run(  # nosec B603 - runs local guard CLI on temp fixture
            [
                sys.executable,
                str(GUARD_PATH),
                "--exec-with-secret",
                "no.such.key=NO_SUCH_VAR",
                "--",
                sys.executable,
                "-c",
                "print('should-not-run')",
            ],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(2, missing.returncode)
        self.assertNotIn("should-not-run", missing.stdout + missing.stderr)
        self.assertNotIn(APP_ID, missing.stdout + missing.stderr)
        self.assertNotIn(ACCESS_KEY, missing.stdout + missing.stderr)

        malformed = subprocess.run(  # nosec B603 - runs local guard CLI on temp fixture
            [sys.executable, str(GUARD_PATH), "--exec-with-secret", "badmapping", "--", sys.executable, "-c", "pass"],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(2, malformed.returncode)


class OutputSecretBlockHintTest(unittest.TestCase):
    def test_output_secret_block_keeps_withholding_and_adds_no_echo_wrapper_hint(self) -> None:
        boundary = _load(BOUNDARY_PATH, "operation_boundary_211")
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / "browserstack.yml").write_text(f"app: {APP_ID}\n", encoding="utf-8")
            blocked = boundary.output_secret_block(
                {"stdout": f"echoed {APP_ID} to terminal\n", "exit_code": 0},
                project,
            )
            clear = boundary.output_secret_block(
                {"stdout": "all tests passed\n", "exit_code": 0},
                project,
            )
        self.assertIsNotNone(blocked)
        assert blocked is not None
        self.assertIn("secret-in-output", blocked)
        self.assertIn("output withheld", blocked)
        self.assertIn("exit code 0", blocked)
        self.assertIn("secret_guard.py --exec-with-secret", blocked)
        self.assertIn("read_secret_key", blocked)
        self.assertNotIn(APP_ID, blocked)
        self.assertIsNone(clear)


class IntakeFeasibilityGateDocsTest(unittest.TestCase):
    def test_bigger_picture_first_defines_intake_feasibility_gate_and_three_options(self) -> None:
        text = BIGGER_PICTURE_PATH.read_text(encoding="utf-8")
        self.assertIn("## Intake feasibility gate", text)
        section = text.split("## Intake feasibility gate", 1)[1].split("\n## ", 1)[0]
        lowered = section.casefold()
        self.assertIn("before any code", lowered)
        self.assertIn("test account", lowered)
        self.assertIn("state-changing write", lowered)
        self.assertIn("mocks cannot reach", lowered)
        self.assertIn("consult-first.md", section)
        self.assertIn("In progress", section)
        self.assertIn("documented skip", lowered)
        self.assertIn("time-boxed spike", lowered)
        self.assertIn("suitable test account", lowered)
        self.assertIn("do not force green", lowered)
        self.assertIn("inferred", lowered)
        self.assertIn("skipped assertion", lowered)

    def test_consult_first_points_to_intake_feasibility_check(self) -> None:
        text = CONSULT_FIRST_PATH.read_text(encoding="utf-8")
        lowered = text.casefold()
        self.assertIn("intake feasibility", lowered)
        self.assertIn("bigger-picture-first.md", text)
        self.assertIn("read-only consultant", lowered)


if __name__ == "__main__":
    unittest.main()
