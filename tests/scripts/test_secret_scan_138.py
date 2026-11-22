"""#138: a token expression is not a password, and a deleted line does not stay red."""

from __future__ import annotations

import importlib.util
import subprocess  # nosec B404 - git init on a temp fixture only
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CREDENTIAL = 'password = "p@ssw0rd-value"'  # nosec B105 - synthetic test value


def _load(name: str):
    path = ROOT / "rules" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"ce_{name}_138", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(  # nosec B603 B607 - fixed git argv on a temp fixture, no shell
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=Tester", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


class SecretAssignmentTest(unittest.TestCase):
    def setUp(self):
        self.rules = _load("lessons_2026_11_06")

    def test_token_expression_is_not_a_password(self):
        result = self.rules.evaluate_secrets_text("token = entry[1:]\n", kind="commit")
        self.assertNotIn("password-in-commit", result["hits"])

    def test_token_colon_does_not_capture_the_next_line(self):
        text = 'if not token or "/" in token:\ncontinue\n'
        result = self.rules.evaluate_secrets_text(text, kind="commit")
        self.assertNotIn("password-in-commit", result["hits"])

    def test_credential_looking_value_still_matches(self):
        result = self.rules.evaluate_secrets_text(CREDENTIAL + "\n", kind="commit")
        self.assertIn("password-in-commit", result["hits"])
        numbered = self.rules.evaluate_secrets_text("password = hunter2\n", kind="commit")
        self.assertIn("password-in-commit", numbered["hits"])

    def test_alphabetic_password_and_token_literals_still_match(self):
        for line in (
            "password = letmein\n",
            "token = supersecret\n",
            "PASSWORD=supersecret\n",
            "token = superSecret\n",
            'password = "letmein"\n',
        ):
            result = self.rules.evaluate_secrets_text(line, kind="commit")
            self.assertIn("password-in-commit", result["hits"], line)

    def test_ordinary_identifiers_are_not_secrets(self):
        for line in (
            "password = None\n",
            "password = self\n",
            "token = response\n",
            "token = entry\n",
        ):
            result = self.rules.evaluate_secrets_text(line, kind="commit")
            self.assertNotIn("password-in-commit", result["hits"], line)

    def test_the_rule_source_does_not_contain_a_secret_assignment(self):
        source = (ROOT / "rules" / "lessons_2026_11_06.py").read_text(encoding="utf-8")
        result = self.rules.evaluate_secrets_text(source, kind="commit")
        self.assertNotIn("password-in-commit", result["hits"])


class RemovedCommitLineTest(unittest.TestCase):
    def test_add_then_delete_does_not_stay_red(self):
        boundary = _load("operation_boundary")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _git(root, "init", "-q", "-b", "main")
            source = root / "src" / "Main.java"
            source.parent.mkdir(parents=True)
            source.write_text("class Main {}\n", encoding="utf-8")
            _git(root, "add", "src/Main.java")
            _git(root, "commit", "-q", "-m", "init")
            source.write_text(
                "class Main {\n    " + CREDENTIAL + ";\n}\n",
                encoding="utf-8",
            )
            _git(root, "add", "src/Main.java")
            _git(root, "commit", "-q", "-m", "add secret")
            self.assertIn("password-in-commit", boundary.committed_secret_failures(root))
            source.write_text("class Main {}\n", encoding="utf-8")
            _git(root, "add", "src/Main.java")
            _git(root, "commit", "-q", "-m", "remove secret")
            self.assertEqual([], boundary.committed_secret_failures(root))


if __name__ == "__main__":
    unittest.main()
