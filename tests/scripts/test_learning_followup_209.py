"""Issue #209: wrapper fetch fallback, nested-link backup guard, non-UTF-8 pointer report, doc alignment."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]


def _load_module(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


INSTALL = _load_module("chaos_engine_install_209", "install.py")
JAVA_INSTALLER = _load_module("chaos_engine_java_installer_209", "packs/java/installer.py")


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


class MavenWrapperFetchFallback209Test(unittest.TestCase):
    def _make_jdk(self, root: Path) -> Path:
        java_home = root / "jdk"
        bin_dir = java_home / "bin"
        bin_dir.mkdir(parents=True)
        java_name = "java.exe" if os.name == "nt" else "java"
        javac_name = "javac.exe" if os.name == "nt" else "javac"
        java = bin_dir / java_name
        javac = bin_dir / javac_name
        java.write_text("#!/bin/sh\n", encoding="utf-8")
        javac.write_text("#!/bin/sh\n", encoding="utf-8")
        java.chmod(0o755)
        javac.chmod(0o755)
        return java

    def _make_managed_mvn(self, root: Path) -> Path:
        mvn = root / "managed-maven" / "bin" / ("mvn.cmd" if os.name == "nt" else "mvn")
        mvn.parent.mkdir(parents=True, exist_ok=True)
        mvn.write_text("#!/bin/sh\n", encoding="utf-8")
        mvn.chmod(0o755)
        return mvn

    def _run_build(
        self,
        root: Path,
        *,
        wrapper_error: subprocess.CalledProcessError | None = None,
        managed_error: subprocess.CalledProcessError | None = None,
        include_wrapper: bool = True,
        managed_return: Path | None = None,
        module=INSTALL,
        trace: dict[str, list] | None = None,
    ):
        java = self._make_jdk(root)
        git = root / "git"
        git.write_text("#!/bin/sh\n", encoding="utf-8")
        git.chmod(0o755)
        cache = root / "cache"
        published: list[Path] = []
        build_clis: list[str] = []
        managed_calls: list[dict[str, object]] = []
        if trace is not None:
            trace["build_clis"] = build_clis
            trace["managed_calls"] = managed_calls
            trace["published"] = published
        wrapper_name = "mvnw.cmd" if os.name == "nt" else "mvnw"

        def ensure_managed_maven(spec, *, opener=None, reporter=None, confirmer=None):
            managed_calls.append(
                {"spec": spec, "opener": opener, "reporter": reporter, "confirmer": confirmer}
            )
            return managed_return

        hosts = SimpleNamespace(
            maven_tools_cache_root=lambda: cache,
            MAVEN_TOOLS_MCP_RECEIPT="install-receipt.json",
            publish_maven_tools_cache=lambda staging: published.append(staging),
            java_major=lambda _path: 25,
            java_compiler_present=lambda _path: True,
            ensure_managed_temurin_jdk=lambda *_a, **_k: None,
            ensure_managed_maven=ensure_managed_maven,
        )

        def runner(command, **kwargs):
            if "clone" in command:
                source = Path(command[-1])
                source.mkdir(parents=True, exist_ok=True)
                if include_wrapper:
                    wrapper = source / wrapper_name
                    wrapper.write_text("#!/bin/sh\n", encoding="utf-8")
                    wrapper.chmod(0o755)
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            if "rev-parse" in command:
                return SimpleNamespace(returncode=0, stdout=("a" * 40) + "\n", stderr="")
            if "package" in command:
                cli_name = Path(command[0]).name
                build_clis.append(cli_name)
                if cli_name.casefold() in {"mvnw", "mvnw.cmd"} and wrapper_error is not None:
                    raise wrapper_error
                if cli_name.casefold() not in {"mvnw", "mvnw.cmd"} and managed_error is not None:
                    raise managed_error
                built = Path(kwargs["cwd"]) / "target" / "maven-tools-mcp-3.2.0.jar"
                built.parent.mkdir(parents=True, exist_ok=True)
                built.write_bytes(b"jar-bytes")
                return SimpleNamespace(returncode=0, stdout="BUILD SUCCESS\n", stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        spec = {"dependencies": {"java": {"minimumVersion": "25.0.0"}}}
        opener = object()
        reporter = SimpleNamespace(start=lambda *_a, **_k: None, detail=lambda *_a, **_k: None)
        confirmer = lambda *_a, **_k: None

        with mock.patch.object(
            module.shutil,
            "which",
            side_effect=lambda name: str(git) if name == "git" else None,
        ):
            module._build_and_publish_maven_tools(
                hosts,
                runner,
                java,
                "3.2.0",
                "v3.2.0",
                confirmer=confirmer,
                reporter=reporter,
                specification=spec,
                opener=opener,
            )
        return build_clis, managed_calls, published, spec, opener, reporter, confirmer

    def test_wrapper_fetch_failure_falls_back_to_managed_maven_and_publishes(self):
        cases = (
            ("failed_to_fetch", "Failed to fetch https://repo.maven.apache.org/maven2/...\n", ""),
            ("wget_error", "wget: unable to resolve host address 'repo.maven.apache.org'\n", ""),
            ("curl_error", "curl: (22) The requested URL returned error: 503\n", ""),
            ("maven_wrapper_fetch", "", "Error: maven-wrapper fetch failed (HTTP 404)\n"),
        )
        for label, stderr, stdout in cases:
            with self.subTest(case=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                managed_mvn = self._make_managed_mvn(root)
                error = subprocess.CalledProcessError(
                    1, ["mvnw", "-B", "clean", "package"], output=stdout, stderr=stderr
                )
                build_clis, managed_calls, published, spec, opener, reporter, confirmer = self._run_build(
                    root,
                    wrapper_error=error,
                    managed_return=managed_mvn,
                    module=INSTALL,
                )
                expected_wrapper = "mvnw.cmd" if os.name == "nt" else "mvnw"
                expected_mvn = "mvn.cmd" if os.name == "nt" else "mvn"
                self.assertEqual([expected_wrapper, expected_mvn], build_clis)
                self.assertEqual(1, len(managed_calls))
                self.assertIs(spec, managed_calls[0]["spec"])
                self.assertIs(opener, managed_calls[0]["opener"])
                self.assertIs(reporter, managed_calls[0]["reporter"])
                self.assertIs(confirmer, managed_calls[0]["confirmer"])
                self.assertEqual(1, len(published))

    def test_non_fetch_compile_failure_still_raises_without_fallback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            managed_mvn = self._make_managed_mvn(root)
            trace: dict[str, list] = {}
            error = subprocess.CalledProcessError(
                1,
                ["mvnw", "-B", "clean", "package"],
                output="[ERROR] COMPILATION ERROR :\nFoo.java:[10,5] cannot find symbol\n",
                stderr="",
            )
            with self.assertRaises(subprocess.CalledProcessError):
                self._run_build(
                    root,
                    wrapper_error=error,
                    managed_return=managed_mvn,
                    module=INSTALL,
                    trace=trace,
                )
            self.assertEqual([], trace["managed_calls"])
            self.assertEqual(1, len(trace["build_clis"]))

    def test_java_home_failure_still_raises_value_error_without_fallback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            managed_mvn = self._make_managed_mvn(root)
            trace: dict[str, list] = {}
            error = subprocess.CalledProcessError(
                1,
                ["mvnw", "-B", "clean", "package"],
                output="",
                stderr="The JAVA_HOME environment variable is not defined correctly\n",
            )
            with self.assertRaisesRegex(ValueError, "JAVA_HOME="):
                self._run_build(
                    root,
                    wrapper_error=error,
                    managed_return=managed_mvn,
                    module=INSTALL,
                    trace=trace,
                )
            self.assertEqual([], trace["managed_calls"])
            self.assertEqual(1, len(trace["build_clis"]))

    def test_fallback_runs_only_once_when_managed_maven_also_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            managed_mvn = self._make_managed_mvn(root)
            trace: dict[str, list] = {}
            wrapper_error = subprocess.CalledProcessError(
                1, ["mvnw"], output="", stderr="Failed to fetch https://example.invalid/maven.zip\n"
            )
            managed_error = subprocess.CalledProcessError(
                1, ["mvn"], output="", stderr="Failed to fetch artifact from mirror\n"
            )
            with self.assertRaises(subprocess.CalledProcessError):
                self._run_build(
                    root,
                    wrapper_error=wrapper_error,
                    managed_error=managed_error,
                    managed_return=managed_mvn,
                    module=INSTALL,
                    trace=trace,
                )
            expected_wrapper = "mvnw.cmd" if os.name == "nt" else "mvnw"
            expected_mvn = "mvn.cmd" if os.name == "nt" else "mvn"
            self.assertEqual([expected_wrapper, expected_mvn], trace["build_clis"])
            self.assertEqual(1, len(trace["managed_calls"]))

    def test_mvnw_cmd_wrapper_is_recognized_for_fetch_fallback(self):
        self.assertTrue(JAVA_INSTALLER._is_maven_wrapper_cli(Path("/src/mvnw")))
        self.assertTrue(JAVA_INSTALLER._is_maven_wrapper_cli(Path("/src/mvnw.cmd")))
        self.assertFalse(JAVA_INSTALLER._is_maven_wrapper_cli(Path("/managed/bin/mvn")))
        self.assertFalse(JAVA_INSTALLER._is_maven_wrapper_cli(Path("/managed/bin/mvn.cmd")))

    def test_wrapper_fetch_failure_with_unavailable_managed_maven_reraises(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            trace: dict[str, list] = {}
            wrapper_error = subprocess.CalledProcessError(
                1, ["mvnw"], output="", stderr="curl: (6) Could not resolve host\n"
            )
            with self.assertRaises(subprocess.CalledProcessError):
                self._run_build(
                    root,
                    wrapper_error=wrapper_error,
                    managed_return=None,
                    module=INSTALL,
                    trace=trace,
                )
            self.assertEqual(1, len(trace["managed_calls"]))
            self.assertEqual(1, len(trace["build_clis"]))

    def test_maven_wrapper_main_class_not_found_falls_back(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            managed_mvn = self._make_managed_mvn(root)
            error = subprocess.CalledProcessError(
                1,
                ["mvnw", "-B", "clean", "package"],
                output="",
                stderr=(
                    "Error: Could not find or load main class "
                    "org.apache.maven.wrapper.MavenWrapperMain\n"
                ),
            )
            build_clis, managed_calls, published, *_rest = self._run_build(
                root,
                wrapper_error=error,
                managed_return=managed_mvn,
                module=INSTALL,
            )
            expected_wrapper = "mvnw.cmd" if os.name == "nt" else "mvnw"
            expected_mvn = "mvn.cmd" if os.name == "nt" else "mvn"
            self.assertEqual([expected_wrapper, expected_mvn], build_clis)
            self.assertEqual(1, len(managed_calls))
            self.assertEqual(1, len(published))

    def test_missing_maven_wrapper_jar_falls_back(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            managed_mvn = self._make_managed_mvn(root)
            error = subprocess.CalledProcessError(
                1,
                ["mvnw", "-B", "clean", "package"],
                output="Can't find .mvn/wrapper/maven-wrapper.jar\n",
                stderr="",
            )
            build_clis, managed_calls, published, *_rest = self._run_build(
                root,
                wrapper_error=error,
                managed_return=managed_mvn,
                module=INSTALL,
            )
            expected_wrapper = "mvnw.cmd" if os.name == "nt" else "mvnw"
            expected_mvn = "mvn.cmd" if os.name == "nt" else "mvn"
            self.assertEqual([expected_wrapper, expected_mvn], build_clis)
            self.assertEqual(1, len(managed_calls))
            self.assertEqual(1, len(published))

    def test_compile_error_mentioning_maven_wrapper_does_not_fall_back(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            managed_mvn = self._make_managed_mvn(root)
            trace: dict[str, list] = {}
            error = subprocess.CalledProcessError(
                1,
                ["mvnw", "-B", "clean", "package"],
                output=(
                    "[ERROR] COMPILATION ERROR :\n"
                    "[ERROR] /src/main/java/maven-wrapper/Foo.java:[10,5] cannot find symbol\n"
                ),
                stderr="",
            )
            with self.assertRaises(subprocess.CalledProcessError):
                self._run_build(
                    root,
                    wrapper_error=error,
                    managed_return=managed_mvn,
                    module=INSTALL,
                    trace=trace,
                )
            self.assertEqual([], trace["managed_calls"])
            self.assertEqual(1, len(trace["build_clis"]))

    def test_review3_cross_line_maven_wrapper_jar_does_not_fall_back(self):
        cases = (
            (
                "download_line",
                "Downloading https://repo.maven.apache.org/maven2/org/apache/maven/wrapper/maven-wrapper/3.2.0/maven-wrapper.jar\n"
                "[ERROR] COMPILATION ERROR :\n"
                "[ERROR] /src/main/java/Foo.java:[10,5] cannot find symbol\n",
            ),
            (
                "classpath_line",
                "[DEBUG] classpath: /repo/.mvn/wrapper/maven-wrapper.jar:/opt/java/lib.jar\n"
                "[ERROR] /src/main/java/Foo.java:[10,5] cannot find symbol\n",
            ),
            (
                "jar_then_missing",
                "Using .mvn/wrapper/maven-wrapper.jar\n"
                "[ERROR] missing symbol Foo\n",
            ),
        )
        for label, output in cases:
            with self.subTest(case=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                managed_mvn = self._make_managed_mvn(root)
                trace: dict[str, list] = {}
                self.assertFalse(JAVA_INSTALLER._is_maven_wrapper_fetch_failure(output))
                error = subprocess.CalledProcessError(
                    1,
                    ["mvnw", "-B", "clean", "package"],
                    output=output,
                    stderr="",
                )
                with self.assertRaises(subprocess.CalledProcessError):
                    self._run_build(
                        root,
                        wrapper_error=error,
                        managed_return=managed_mvn,
                        module=INSTALL,
                        trace=trace,
                    )
                self.assertEqual([], trace["managed_calls"])
                self.assertEqual(1, len(trace["build_clis"]))

    def test_review3_real_wrapper_fetch_failures_still_fall_back(self):
        cases = (
            ("same_line_missing_jar", "Can't find .mvn/wrapper/maven-wrapper.jar\n", ""),
            (
                "maven_wrapper_main",
                "",
                "Error: Could not find or load main class org.apache.maven.wrapper.MavenWrapperMain\n",
            ),
            ("failed_to_fetch", "", "Failed to fetch https://repo.maven.apache.org/maven2/...\n"),
            ("wget", "wget: unable to resolve host address 'repo.maven.apache.org'\n", ""),
        )
        for label, stdout, stderr in cases:
            with self.subTest(case=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                managed_mvn = self._make_managed_mvn(root)
                combined = (stderr + "\n" + stdout).strip()
                self.assertTrue(JAVA_INSTALLER._is_maven_wrapper_fetch_failure(combined))
                error = subprocess.CalledProcessError(
                    1,
                    ["mvnw", "-B", "clean", "package"],
                    output=stdout,
                    stderr=stderr,
                )
                build_clis, managed_calls, published, *_rest = self._run_build(
                    root,
                    wrapper_error=error,
                    managed_return=managed_mvn,
                    module=INSTALL,
                )
                expected_wrapper = "mvnw.cmd" if os.name == "nt" else "mvnw"
                expected_mvn = "mvn.cmd" if os.name == "nt" else "mvn"
                self.assertEqual([expected_wrapper, expected_mvn], build_clis)
                self.assertEqual(1, len(managed_calls))
                self.assertEqual(1, len(published))


class LegacyMigrationSafety209Test(unittest.TestCase):
    def test_nested_symlink_blocks_backup_rmtree_and_records_summary(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            _healthy_overlay(project)
            outside = project / "outside-keep"
            outside.mkdir()
            (outside / "important.txt").write_text("do-not-delete\n", encoding="utf-8")

            backup = project / ".chaos-engine.backup.old"
            nested = backup / "sub"
            nested.mkdir(parents=True)
            (backup / "keep-in-backup.txt").write_text("untouched\n", encoding="utf-8")
            (nested / "escape").symlink_to(outside, target_is_directory=True)

            summary = INSTALL.migrate_legacy_paths(project)

            self.assertTrue(backup.is_dir())
            self.assertEqual("untouched\n", (backup / "keep-in-backup.txt").read_text(encoding="utf-8"))
            self.assertEqual("do-not-delete\n", (outside / "important.txt").read_text(encoding="utf-8"))
            self.assertNotIn(".chaos-engine.backup.old", summary["backupsRemoved"])
            self.assertIn(".chaos-engine.backup.old", summary["backupsSkippedNestedLink"])

    def test_nested_reparse_junction_blocks_uninstall_backup_rmtree(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            _healthy_overlay(project)
            backup = project / ".chaos-engine-uninstall-old-backup"
            junction = backup / "nested-junction"
            junction.mkdir(parents=True)
            (junction / "inside.txt").write_text("keep\n", encoding="utf-8")

            real_check = INSTALL.is_link_or_reparse

            def fake_reparse(path: Path) -> bool:
                if Path(path) == junction:
                    return True
                return real_check(path)

            with mock.patch.object(INSTALL, "is_link_or_reparse", side_effect=fake_reparse), \
                    mock.patch.object(INSTALL.shutil, "rmtree") as rmtree:
                summary = INSTALL.migrate_legacy_paths(project)

            rmtree.assert_not_called()
            self.assertTrue(backup.is_dir())
            self.assertEqual("keep\n", (junction / "inside.txt").read_text(encoding="utf-8"))
            self.assertEqual([], summary["backupsRemoved"])
            self.assertEqual([".chaos-engine-uninstall-old-backup"], summary["backupsSkippedNestedLink"])

    def test_utf16_pointer_file_is_recorded_in_summary_and_left_untouched(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            _healthy_overlay(project)
            utf16_bytes = (
                "<!-- CHAOSENGINE:START -->\n"
                "Load chaos-engine/tool.py\n"
                "<!-- CHAOSENGINE:END -->\n"
            ).encode("utf-16")
            agents = project / "AGENTS.md"
            agents.write_bytes(utf16_bytes)

            utf16le_no_bom = (
                "<!-- CHAOSENGINE:START -->\n"
                "Load chaos-engine/tool.py\n"
                "<!-- CHAOSENGINE:END -->\n"
            ).encode("utf-16-le")
            claude = project / "CLAUDE.md"
            claude.write_bytes(utf16le_no_bom)

            gemini = project / "GEMINI.md"
            gemini.write_text(
                "<!-- CHAOSENGINE:START -->\n"
                "Load chaos-engine/tool.py\n"
                "<!-- CHAOSENGINE:END -->\n",
                encoding="utf-8",
            )

            summary = INSTALL.migrate_legacy_paths(project)

            self.assertEqual(utf16_bytes, agents.read_bytes())
            self.assertEqual(utf16le_no_bom, claude.read_bytes())
            self.assertIn(".chaos-engine/tool.py", gemini.read_text(encoding="utf-8"))
            self.assertEqual(["GEMINI.md"], summary["pointersRewritten"])
            self.assertEqual(["AGENTS.md", "CLAUDE.md"], summary["pointersSkippedNonUtf8"])
            for key in ("orphans", "palaceSidecars", "pointersRewritten", "backupsRemoved"):
                self.assertIn(key, summary)


class Followup209DocAlignmentTest(unittest.TestCase):
    def test_static_analysis_gate_never_arms_auto_merge(self):
        text = (ROOT / "references" / "static-analysis-gate.md").read_text(encoding="utf-8")
        self.assertNotIn("--disable-auto", text)
        self.assertNotIn("already armed", text)
        self.assertIn("Never arm auto-merge", text)
        self.assertIn("gh pr merge --auto", text)

    def test_delivery_cycle_notes_truncated_pr_file_list_fails_closed(self):
        lines = (ROOT / "references" / "delivery-cycle.md").read_text(encoding="utf-8").splitlines()
        line31 = lines[30]
        self.assertIn("installer-contract", line31)
        self.assertIn("truncated", line31.casefold())
        self.assertIn("fails closed", line31.casefold())


if __name__ == "__main__":
    unittest.main()
