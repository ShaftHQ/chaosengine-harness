"""#266 pre-rebase tree-diff secret/.gitignore guard and guard.py R8 quote-aware tests."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess  # nosec B404 - runs git and guard scripts in temp repos only
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SECRET_GUARD = ROOT / "runtime" / "secret_guard.py"
GIT_HOOKS = ROOT / "runtime" / "git_hooks.py"
GUARD = ROOT / "hooks" / "guard.py"
DRAFT_PR = ROOT / "runtime" / "draft_skill_pr.py"
SILENT_VERIFY = ROOT / "runtime" / "silent_verify.py"
GIT = shutil.which("git") or "git"
SYNTHETIC_SECRET = "SYNTHETIC_TEST_TOKEN_999"  # nosec B105 - synthetic test token


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(
        os.environ,
        GIT_AUTHOR_NAME="t",
        GIT_AUTHOR_EMAIL="t@e",
        GIT_COMMITTER_NAME="t",
        GIT_COMMITTER_EMAIL="t@e",
        CHAOS_ENGINE_SECRET_GUARD="1",
    )
    env.pop("GIT_DIR", None)
    env.pop("GIT_WORK_TREE", None)
    return subprocess.run(  # nosec B603
        [GIT, *args], cwd=cwd, capture_output=True, text=True, env=env
    )


class PreRebaseTreeGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.secret_guard = _load(SECRET_GUARD, "ce_secret_guard_266")
        self.git_hooks = _load(GIT_HOOKS, "ce_git_hooks_266")
        self.guard = _load(GUARD, "ce_guard_266")
        self._guard_env = os.environ.get("CHAOS_ENGINE_SECRET_GUARD")
        os.environ["CHAOS_ENGINE_SECRET_GUARD"] = "1"
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name) / "repo"
        self.repo.mkdir()
        _git(self.repo, "init", "-q", "-b", "main")
        (self.repo / ".gitignore").write_text("*.log\n", encoding="utf-8")
        (self.repo / "src.txt").write_text("base\n", encoding="utf-8")
        _git(self.repo, "add", ".gitignore", "src.txt")
        _git(self.repo, "commit", "-q", "-m", "base")

    def tearDown(self) -> None:
        if self._guard_env is None:
            os.environ.pop("CHAOS_ENGINE_SECRET_GUARD", None)
        else:
            os.environ["CHAOS_ENGINE_SECRET_GUARD"] = self._guard_env
        self.temp.cleanup()

    def _run_cli(self, *args: str) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env.pop("GIT_DIR", None)
        env.pop("GIT_WORK_TREE", None)
        return subprocess.run(  # nosec B603
            [sys.executable, str(SECRET_GUARD), *args],
            cwd=self.repo,
            capture_output=True,
            text=True,
            env=env,
        )

    def _run_guard_pretool(self, command: str) -> subprocess.CompletedProcess:
        payload = json.dumps(
            {
                "hook_event_name": "PreToolUse",
                "session_id": "s2-rebase",
                "cwd": str(self.repo),
                "tool_name": "Bash",
                "tool_input": {"command": command},
            }
        )
        env = os.environ.copy()
        env.pop("GIT_DIR", None)
        env.pop("GIT_WORK_TREE", None)
        return subprocess.run(  # nosec B603
            [sys.executable, str(GUARD)],
            cwd=self.repo,
            input=payload,
            capture_output=True,
            text=True,
            env=env,
        )

    def test_pure_diff_parser_flags_gitignore_delete_rename_and_new_secrets_binaries(self) -> None:
        raw_lines = "\n".join(
            [
                "D\t.gitignore",
                "R100\tsafe.txt\tconfig/login.json",
                "A\tandroid/app-release.apk",
                "A\tios/build.ipa",
                "A\tbundle/app.aab",
                "M\texisting/secrets.properties",
                "R100\told/secrets.properties\tnew/secrets.properties",
            ]
        )
        findings = self.secret_guard.pre_rebase_findings_from_diff(raw_lines)
        self.assertEqual(
            [
                ".gitignore (deleted)",
                "config/login.json (renamed from safe.txt)",
                "android/app-release.apk (added)",
                "ios/build.ipa (added)",
                "bundle/app.aab (added)",
            ],
            findings,
        )
        renamed_gitignore = "R100\t.gitignore\t.gitignore.bak\n"
        self.assertEqual(
            [".gitignore (renamed to .gitignore.bak)"],
            self.secret_guard.pre_rebase_findings_from_diff(renamed_gitignore),
        )
        nul_diff = "D\0.gitignore\0A\0sub/Secrets.Properties\0R095\0.gitignore\0.gitignore.off\0"
        self.assertEqual(
            [
                ".gitignore (deleted)",
                "sub/Secrets.Properties (added)",
                ".gitignore (renamed to .gitignore.off)",
            ],
            self.secret_guard.pre_rebase_findings_from_diff(nul_diff),
        )

    def test_sc1_poisoned_target_exits_2_no_contents_and_pre_rebase_hook_refuses(self) -> None:
        _git(self.repo, "checkout", "-q", "-b", "feature")
        (self.repo / "feature.txt").write_text("feature work\n", encoding="utf-8")
        _git(self.repo, "add", "feature.txt")
        _git(self.repo, "commit", "-q", "-m", "feature")
        feature_head = _git(self.repo, "rev-parse", "HEAD").stdout.strip()

        _git(self.repo, "checkout", "-q", "-b", "poison", "main")
        _git(self.repo, "rm", "-q", ".gitignore")
        (self.repo / "secrets.properties").write_text(f"apiKey={SYNTHETIC_SECRET}\n", encoding="utf-8")
        _git(self.repo, "add", "secrets.properties")
        _git(self.repo, "commit", "-q", "-m", "poison")

        _git(self.repo, "checkout", "-q", "feature")
        cli = self._run_cli("--pre-rebase", "poison")
        self.assertEqual(2, cli.returncode)
        self.assertIn(".gitignore", cli.stderr)
        self.assertIn("secrets.properties", cli.stderr)
        self.assertNotIn(SYNTHETIC_SECRET, cli.stderr + cli.stdout)

        installed = self.git_hooks.install_secret_guard(self.repo, SECRET_GUARD)
        self.assertEqual("installed", installed["status"])
        self.assertIn("pre-rebase", self.git_hooks.GUARDED)
        hook_path = Path(installed["hooksPath"]) / "pre-rebase"
        self.assertTrue(os.access(hook_path, os.X_OK))

        rebased = _git(self.repo, "rebase", "poison")
        self.assertNotEqual(0, rebased.returncode)
        self.assertIn(".gitignore", rebased.stderr)
        self.assertIn("secrets.properties", rebased.stderr)
        self.assertNotIn(SYNTHETIC_SECRET, rebased.stderr + rebased.stdout)
        self.assertEqual(feature_head, _git(self.repo, "rev-parse", "HEAD").stdout.strip())
        self.assertEqual("", _git(self.repo, "status", "--porcelain").stdout.strip())

    def test_sc2_clean_target_exits_0_and_rebase_succeeds(self) -> None:
        _git(self.repo, "checkout", "-q", "-b", "feature")
        (self.repo / "feature.txt").write_text("feature work\n", encoding="utf-8")
        _git(self.repo, "add", "feature.txt")
        _git(self.repo, "commit", "-q", "-m", "feature")

        _git(self.repo, "checkout", "-q", "-b", "clean-target", "main")
        (self.repo / "src.txt").write_text("updated\n", encoding="utf-8")
        _git(self.repo, "add", "src.txt")
        _git(self.repo, "commit", "-q", "-m", "clean update")

        _git(self.repo, "checkout", "-q", "feature")
        cli = self._run_cli("--pre-rebase", "clean-target")
        self.assertEqual(0, cli.returncode, msg=cli.stderr)
        self.assertEqual("", cli.stderr)

        self.git_hooks.install_secret_guard(self.repo, SECRET_GUARD)
        rebased = _git(self.repo, "rebase", "clean-target")
        self.assertEqual(0, rebased.returncode, msg=rebased.stderr)
        self.assertEqual("", _git(self.repo, "status", "--porcelain").stdout.strip())

    def test_edge_cases_existing_secret_rename_binaries_and_login_json(self) -> None:
        # Existing secrets.properties on both trees is NOT flagged as a new add.
        (self.repo / "secrets.properties").write_text("k=old\n", encoding="utf-8")
        _git(self.repo, "add", "-f", "secrets.properties")
        _git(self.repo, "commit", "-q", "-m", "shared secret")

        _git(self.repo, "checkout", "-q", "-b", "feature")
        _git(self.repo, "checkout", "-q", "-b", "target-mod", "main")
        (self.repo / "secrets.properties").write_text("k=new\n", encoding="utf-8")
        _git(self.repo, "add", "-f", "secrets.properties")
        _git(self.repo, "commit", "-q", "-m", "modify existing secret")
        _git(self.repo, "checkout", "-q", "feature")
        self.assertEqual(0, self._run_cli("--pre-rebase", "target-mod").returncode)

        # Rename of .gitignore counts as deletion.
        _git(self.repo, "checkout", "-q", "-b", "target-rename-gi", "main")
        _git(self.repo, "mv", ".gitignore", ".gitignore.bak")
        _git(self.repo, "commit", "-q", "-m", "rename gitignore")
        _git(self.repo, "checkout", "-q", "feature")
        res = self._run_cli("--pre-rebase", "target-rename-gi")
        self.assertEqual(2, res.returncode)
        self.assertIn(".gitignore", res.stderr)

        # New binaries and login.json while .gitignore is unchanged exit 2.
        for idx, name in enumerate(("app.apk", "app.ipa", "app.aab", "config/login.json")):
            branch = f"target-bad-{idx}"
            _git(self.repo, "checkout", "-q", "-b", branch, "main")
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("payload\n", encoding="utf-8")
            _git(self.repo, "add", "-f", name)
            _git(self.repo, "commit", "-q", "-m", f"add {name}")
            _git(self.repo, "checkout", "-q", "feature")
            blocked = self._run_cli("--pre-rebase", branch)
            self.assertEqual(2, blocked.returncode, msg=name)
            self.assertIn(name, blocked.stderr)

    def test_guard_py_pretooluse_blocks_poisoned_rebase_merge_and_pull(self) -> None:
        _git(self.repo, "checkout", "-q", "-b", "feature")
        (self.repo / "feature.txt").write_text("work\n", encoding="utf-8")
        _git(self.repo, "add", "feature.txt")
        _git(self.repo, "commit", "-q", "-m", "work")

        _git(self.repo, "checkout", "-q", "-b", "poison", "main")
        _git(self.repo, "rm", "-q", ".gitignore")
        (self.repo / "login.json").write_text(f'{{"token":"{SYNTHETIC_SECRET}"}}', encoding="utf-8")
        _git(self.repo, "add", "login.json")
        _git(self.repo, "commit", "-q", "-m", "poison")

        _git(self.repo, "checkout", "-q", "-b", "clean-branch", "main")
        (self.repo / "clean.txt").write_text("ok\n", encoding="utf-8")
        _git(self.repo, "add", "clean.txt")
        _git(self.repo, "commit", "-q", "-m", "clean")

        _git(self.repo, "checkout", "-q", "feature")
        for cmd in (
            "git rebase poison",
            "git rebase --onto poison main feature",
            "git merge poison",
        ):
            with self.subTest(cmd=cmd):
                proc = self._run_guard_pretool(cmd)
                self.assertEqual(2, proc.returncode, msg=proc.stdout + proc.stderr)
                self.assertIn(".gitignore", proc.stdout)
                self.assertIn("login.json", proc.stdout)
                self.assertNotIn(SYNTHETIC_SECRET, proc.stdout + proc.stderr)

        _git(self.repo, "update-ref", "refs/remotes/origin/poison", "poison")
        pull_proc = self._run_guard_pretool("git pull --rebase origin poison")
        self.assertEqual(2, pull_proc.returncode, msg=pull_proc.stdout + pull_proc.stderr)
        self.assertIn("login.json", pull_proc.stdout)

        clean_proc = self._run_guard_pretool("git rebase clean-branch")
        self.assertEqual(0, clean_proc.returncode, msg=clean_proc.stdout + clean_proc.stderr)
        abort_proc = self._run_guard_pretool("git rebase --abort")
        self.assertEqual(0, abort_proc.returncode, msg=abort_proc.stdout + abort_proc.stderr)

    def test_guard_r8_quote_aware_and_git_add_paths(self) -> None:
        self.assertIn("git add <paths>", self.guard.STASH_R8_REASON)
        self.assertNotIn("git add -A", self.guard.STASH_R8_REASON)

        wt = Path(self.temp.name) / "wt"
        _git(self.repo, "worktree", "add", "-q", "-b", "wt-branch", str(wt))
        self.assertTrue(self.guard.shares_git_directory(wt))

        # Quoted pipe mention inside rg must NOT trigger R8 stash block.
        self.assertEqual(
            "",
            self.guard.linked_worktree_stash_reason(
                ('rg -n "foo|git stash|bar" hooks/guard.py',), wt
            ),
        )
        # Real piped / newline / chained git stash MUST still be blocked.
        for cmd in (
            "echo ok | git stash",
            "echo ok\ngit stash push -m wip",
            "true && git stash",
        ):
            with self.subTest(cmd=cmd):
                reason = self.guard.linked_worktree_stash_reason((cmd,), wt)
                self.assertIn("R8", reason)
        self.assertEqual(
            "",
            self.guard.linked_worktree_stash_reason(("git stash list",), wt),
        )

    def test_eval_parity_scripts_use_real_repo_validator(self) -> None:
        draft = _load(DRAFT_PR, "ce_draft_skill_pr_266")
        silent = _load(SILENT_VERIFY, "ce_silent_verify_266")
        self.assertTrue((ROOT / draft.EVAL_SCRIPT).is_file())
        result = draft.run_eval_parity(ROOT)
        self.assertTrue(result["ok"], msg=result)
        self.assertEqual(0, silent.verify_eval_parity())
        self.assertEqual(2, silent.verify_eval_parity(fixtures=ROOT / "evals" / "parity-fixtures.json"))


if __name__ == "__main__":
    unittest.main()
