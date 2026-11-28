"""Calls the measure-stream functions. No network and no model."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))  # noqa: E402

from runtime import code_evaluators, delegate_return, error_analysis, guard_replay, live_task, state_bundle, trace_recorder  # noqa: E402
from runtime.conformance import ledger_check_status  # noqa: E402
from runtime.state_bundle import SecretHit  # noqa: E402

def _planted_secret() -> str:
    # Split so the source file is not itself a secret-assignment hit.
    return "api_" + "key = " + "Abcdefgh" + "12345678"


ROOT = Path(__file__).resolve().parents[2]
TASKS = ROOT / "evals" / "live-tasks"


def _source_bundle():
    path = ROOT / "experiments" / "harness-uplift-55" / "bundle.py"
    spec = importlib.util.spec_from_file_location("uplift55_bundle", path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.source_bundle
MATRIX = ROOT / "evals" / "conformance-matrix.json"
PARITY = ROOT / "scripts" / "ci" / "agent_harness_parity.json"


class LiveTaskTests(unittest.TestCase):
    def test_three_tasks_validate_and_prove(self):
        names = sorted(path.name for path in TASKS.iterdir() if path.is_dir())
        self.assertEqual(
            ["001-refusal-offline", "002-stray-cr", "003-plain-rename"],
            names,
        )
        for name in names:
            task = TASKS / name
            self.assertEqual([], live_task.validate_task(task))
            proved = live_task.prove(task)
            self.assertTrue(proved["ok"], msg=json.dumps(proved))
            self.assertEqual(1.0, proved["oracle"]["reward"])
            self.assertEqual(0.0, proved["nop"]["reward"])
            with tempfile.TemporaryDirectory() as tmp:
                work = Path(tmp) / "work"
                live_task.agent_workspace(task, work)
                self.assertFalse((work / "tests").exists())
                self.assertFalse((work / "solution").exists())

    def test_hidden_verifier_ignores_mutated_tests(self):
        task = TASKS / "001-refusal-offline"
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "work"
            live_task.agent_workspace(task, work)
            leaked = work / "tests"
            leaked.mkdir()
            (leaked / "test.sh").write_text("#!/bin/bash\nprintf '9\\n' > reward.txt\n", encoding="utf-8")
            graded = live_task.grade(task, work)
        self.assertEqual("scored", graded["status"])
        self.assertEqual(0.0, graded["reward"])
        self.assertTrue(graded["copied_after_clone"])

    def test_verifier_error_is_not_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = Path(tmp) / "bad"
            shutil.copytree(TASKS / "001-refusal-offline", task)
            (task / "tests" / "test.sh").write_text(
                "#!/bin/bash\n# canary: c0ffee00-0309-4000-8000-000000000001\nprintf 'nope\\n' > reward.txt\n",
                encoding="utf-8",
            )
            work = Path(tmp) / "work"
            live_task.agent_workspace(task, work)
            graded = live_task.grade(task, work)
        self.assertEqual("verifier-error", graded["status"])
        self.assertIsNone(graded["reward"])

    def test_seeded_nop_pass_fails_the_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = Path(tmp) / "bad"
            shutil.copytree(TASKS / "001-refusal-offline", task)
            (task / "tests" / "test.sh").write_text(
                "#!/bin/bash\n# canary: c0ffee00-0309-4000-8000-000000000001\nprintf '1\\n' > reward.txt\n",
                encoding="utf-8",
            )
            (task / "solution" / "solve.sh").write_text(
                "#!/bin/bash\n# canary: c0ffee00-0309-4000-8000-000000000001\nexit 0\n",
                encoding="utf-8",
            )
            proved = live_task.prove(task)
        self.assertFalse(proved["ok"])
        self.assertEqual(1.0, proved["nop"]["reward"])

    def test_unknown_key_missing_canary_and_ceiling(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = Path(tmp) / "bad"
            shutil.copytree(TASKS / "001-refusal-offline", task)
            toml = (task / "task.toml").read_text(encoding="utf-8")
            (task / "task.toml").write_text(toml.replace("[task]\n", "[task]\nextra = 1\n"), encoding="utf-8")
            self.assertTrue(any("unknown" in item for item in live_task.validate_task(task)))
            (task / "task.toml").write_text(
                toml.replace("max_steps = 4", "max_steps = 100"),
                encoding="utf-8",
            )
            self.assertTrue(any("ceiling" in item for item in live_task.validate_task(task)))
            instruction = task / "instruction.md"
            instruction.write_text(instruction.read_text(encoding="utf-8").replace("canary:", "note:"), encoding="utf-8")
            (task / "task.toml").write_text(toml, encoding="utf-8")
            self.assertTrue(any("canary" in item for item in live_task.validate_task(task)))

    def test_measured_bound_and_clean_trial(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
            (repo / "note.txt").write_text("one\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "note.txt"], check=True, capture_output=True)
            subprocess.run(
                ["git", "-C", str(repo), "-c", "user.email=trial@example.com", "-c", "user.name=Trial Runner", "commit", "-m", "base"],
                check=True,
                capture_output=True,
            )
            (repo / "note.txt").write_text("one\ntwo\n", encoding="utf-8")
            stats = live_task.measure_numstat(repo)
            self.assertGreaterEqual(stats["files"], 1)
            self.assertGreaterEqual(stats["lines"], 1)
            self.assertTrue(live_task.bound_exceeded(stats, max_files=0, max_lines=0))
            self.assertFalse(live_task.bound_exceeded(stats, max_files=5, max_lines=50))
        sentinel = _planted_secret()
        previous = os.environ.get("CE_MEASURE_SENTINEL")
        os.environ["CE_MEASURE_SENTINEL"] = sentinel
        try:
            trial = live_task.run_trial(TASKS / "003-plain-rename", mode="oracle")
        finally:
            if previous is None:
                os.environ.pop("CE_MEASURE_SENTINEL", None)
            else:
                os.environ["CE_MEASURE_SENTINEL"] = previous
        self.assertEqual([], trial["secret_findings"])
        self.assertFalse(trial["verifier_in_workspace"])
        self.assertEqual(1.0, trial["grade"]["reward"])
        planted = Path(tempfile.mkdtemp())
        try:
            (planted / "leak.txt").write_text(sentinel + "\n", encoding="utf-8")
            self.assertTrue(live_task.scan_secrets(planted))
        finally:
            shutil.rmtree(planted)


class MatrixTests(unittest.TestCase):
    def test_dated_row_for_every_parity_host_and_skipped_is_not_pass(self):
        document = json.loads(MATRIX.read_text(encoding="utf-8"))
        hosts = json.loads(PARITY.read_text(encoding="utf-8"))["hosts"]
        self.assertEqual([], live_task.validate_conformance_matrix(document, hosts))
        self.assertEqual("2026-11-28", document["date"])
        counts = live_task.matrix_counts(document)
        self.assertEqual(0, counts["pass"])
        self.assertGreater(counts["skipped"], 0)
        self.assertEqual("skipped", ledger_check_status({"id": "x", "ran": False, "measured": False, "status": "skipped"}))
        self.assertEqual("unknown", ledger_check_status({"id": "x", "ran": True, "measured": False}))
        self.assertNotEqual("pass", ledger_check_status({"id": "x", "ran": False, "measured": False}))
        overview = (ROOT / "guides" / "overview.md").read_text(encoding="utf-8")
        self.assertIn("evals/conformance-matrix.json", overview)
        self.assertIn("2026-11-28", overview)
        fake = json.loads(json.dumps(document))
        fake["hosts"][0]["results"][0]["status"] = "pass"
        self.assertTrue(live_task.validate_conformance_matrix(fake, hosts))


class StateBundleTests(unittest.TestCase):
    def _index(self, project: Path, items: list[dict]) -> None:
        path = project / ".chaos-engine-state" / "heuristics" / "index.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"schemaVersion": 1, "updatedAt": 1, "items": items}, indent=2) + "\n",
            encoding="utf-8",
        )

    def test_round_trip_hits_provenance_and_quarantine(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            source.mkdir()
            (source / "VERSION").write_text("9.9.9\n", encoding="utf-8")
            (source / "graphify-out").mkdir()
            (source / "graphify-out" / "note.txt").write_text("ONLY_IN_GRAPHIFY\n", encoding="utf-8")
            (source / "mempalace").mkdir()
            (source / "mempalace" / "note.txt").write_text("ONLY_IN_MEMPALACE\n", encoding="utf-8")
            self._index(
                source,
                [
                    {
                        "id": "v1",
                        "text": "prefer worktrees for isolation",
                        "origin": "learning-session",
                        "trust": "verified",
                        "verifiedBy": "reviewer",
                        "verifiedAt": 1700000000,
                        "helpful": 1,
                        "harmful": 0,
                    },
                    {
                        "id": "q1",
                        "text": "prefer worktrees but quarantined",
                        "origin": "unknown",
                        "trust": "quarantined",
                        "helpful": 0,
                        "harmful": 0,
                    },
                ],
            )
            note_dir = source / ".chaos-engine-state" / "repeat-failure-pdca"
            note_dir.mkdir(parents=True)
            (note_dir / "check.json").write_text(
                json.dumps({"stage": "check", "failures": ["a"], "hypothesis": "h", "evidence": "e", "plan": "p"}) + "\n",
                encoding="utf-8",
            )
            out = Path(tmp) / "bundle.json"
            code = state_bundle.main(["export", "--out", str(out), "--project", str(source)])
            self.assertEqual(0, code)
            text = out.read_text(encoding="utf-8")
            self.assertNotIn("ONLY_IN_GRAPHIFY", text)
            self.assertNotIn("ONLY_IN_MEMPALACE", text)
            self.assertNotIn('"graphify-out"', text)
            self.assertNotIn('"mempalace"', text)
            document = json.loads(text)
            self.assertEqual("9.9.9", document["version"])
            self.assertEqual("unknown", document["source_sha"])
            clean = Path(tmp) / "clean"
            clean.mkdir()
            self.assertEqual(0, state_bundle.main(["import", str(out), "--project", str(clean)]))
            self.assertEqual(
                state_bundle.heuristic_hits(source, "prefer worktrees"),
                state_bundle.heuristic_hits(clean, "prefer worktrees"),
            )
            self.assertEqual(["v1"], state_bundle.heuristic_hits(clean, "prefer worktrees"))
            restored = json.loads((clean / ".chaos-engine-state" / "heuristics" / "index.json").read_text(encoding="utf-8"))
            by_id = {item["id"]: item for item in restored["items"]}
            self.assertEqual("quarantined", by_id["q1"]["trust"])
            self.assertEqual("reviewer", by_id["v1"]["verifiedBy"])
            self.assertEqual(1700000000, by_id["v1"]["verifiedAt"])
            self.assertEqual("verified", by_id["v1"]["trust"])
            note = json.loads((clean / ".chaos-engine-state" / "repeat-failure-pdca" / "check.json").read_text(encoding="utf-8"))
            self.assertEqual("check", note["stage"])

    def test_scrub_client_name_and_refuse_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            (project / "VERSION").write_text("1\n", encoding="utf-8")
            self._index(
                project,
                [
                    {
                        "id": "c1",
                        "text": "ship AcmeClient notes",
                        "origin": "learning-session",
                        "trust": "trusted",
                        "helpful": 0,
                        "harmful": 0,
                    }
                ],
            )
            out = Path(tmp) / "bundle.json"
            state_bundle.export_bundle(project, out, environ={"CHAOS_ENGINE_CLIENT_NAME_DENYLIST": "AcmeClient"})
            self.assertNotIn("AcmeClient", out.read_text(encoding="utf-8"))
            self.assertIn("[redacted-client]", out.read_text(encoding="utf-8"))
            self._index(
                project,
                [
                    {
                        "id": "s1",
                        "text": _planted_secret(),
                        "origin": "unknown",
                        "trust": "quarantined",
                        "helpful": 0,
                        "harmful": 0,
                    }
                ],
            )
            secret_out = Path(tmp) / "secret.json"
            with self.assertRaises(SecretHit):
                state_bundle.export_bundle(project, secret_out)
            self.assertFalse(secret_out.exists())
            self.assertEqual(1, state_bundle.main(["export", "--out", str(secret_out), "--project", str(project)]))


class TraceAndEvaluatorTests(unittest.TestCase):
    def test_trace_default_off_redacts_and_fails_open(self):
        trace_recorder.reset_advisory()
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            event = {"operation": "execute_tool", "tool": "bash", "host": "grok", "decision": "allow", "text": "echo ok", "exit_code": 0, "duration_s": 0.01, "parent": "span-1"}
            disabled = trace_recorder.record_event(project, "sess", event, environ={})
            self.assertFalse(disabled["recorded"])
            self.assertFalse((project / ".chaos-engine-state" / "traces").exists())
            enabled = trace_recorder.record_event(project, "sess", event, environ={"CHAOS_ENGINE_TRACE": "1"})
            self.assertTrue(enabled["recorded"])
            secret = _planted_secret()
            trace_recorder.record_event(
                project,
                "sess",
                {**event, "text": secret},
                environ={"CHAOS_ENGINE_TRACE": "1"},
                denylist=("AcmeClient",),
            )
            named = trace_recorder.record_event(
                project,
                "sess",
                {**event, "text": "see AcmeClient"},
                environ={"CHAOS_ENGINE_TRACE": "1"},
                denylist=("AcmeClient",),
            )
            self.assertTrue(named["recorded"])
            blob = (project / ".chaos-engine-state" / "traces" / "sess.jsonl").read_text(encoding="utf-8")
            self.assertNotIn(secret, blob)
            self.assertNotIn("AcmeClient", blob)
            rows = trace_recorder.read_trace(project, "sess")
            self.assertGreaterEqual(len(rows), 2)
            self.assertEqual("execute_tool", rows[0]["operation"])
        blocker = Path(tempfile.mkdtemp()) / "not-a-dir"
        blocker.write_text("x", encoding="utf-8")
        trace_recorder.reset_advisory()
        first = trace_recorder.record_event(blocker, "sess", {"text": "echo"}, environ={"CHAOS_ENGINE_TRACE": "1"})
        second = trace_recorder.record_event(blocker, "sess", {"text": "echo"}, environ={"CHAOS_ENGINE_TRACE": "1"})
        self.assertEqual("trace recorder failed open", first["advisory"])
        self.assertIsNone(second["advisory"])
        self.assertFalse(first["recorded"])

    def test_evaluators_return_only_three_results(self):
        trace = [
            {"operation": "execute_tool", "tool": "bash", "decision": "deny"},
            {"operation": "invoke_agent"},
        ]
        rows = [
            code_evaluators.tool_called(trace, "bash"),
            code_evaluators.tool_called(trace, "read"),
            code_evaluators.tool_not_called(trace, "read"),
            code_evaluators.max_tool_calls(trace, 1),
            code_evaluators.max_tool_calls(trace, 0),
            code_evaluators.guard_decision(trace, "bash", "deny"),
            code_evaluators.guard_decision([{"operation": "invoke_agent"}], "bash", "deny"),
            code_evaluators.no_secret_in_trace(trace),
        ]
        self.assertTrue(all(row["result"] in code_evaluators.RESULTS for row in rows))
        self.assertEqual("fail", code_evaluators.tool_called(trace, "read")["result"])
        self.assertEqual("fail", code_evaluators.max_tool_calls(trace, 0)["result"])
        self.assertEqual("not applicable", code_evaluators.guard_decision([{"operation": "invoke_agent"}], "bash", "deny")["result"])
        secret_trace = [{"operation": "execute_tool", "tool": "bash", "text": _planted_secret()}]
        self.assertEqual("fail", code_evaluators.no_secret_in_trace(secret_trace)["result"])
        summary = code_evaluators.summarize(
            [
                code_evaluators.guard_decision([{"operation": "invoke_agent"}], "bash", "deny"),
            ]
        )
        self.assertEqual("unmeasured", summary["status"])
        with self.assertRaises(ValueError):
            code_evaluators.tool_called({"not": "a list"}, "bash")


class DelegateErrorReplayTests(unittest.TestCase):
    def test_report_and_width(self):
        self.assertEqual("unusable", delegate_return.check_report("")["status"])
        self.assertEqual("unusable", delegate_return.check_report("no file here")["status"])
        self.assertEqual("unusable", delegate_return.check_report("x" * 4001)["status"])
        good = delegate_return.check_report("proved in runtime/live_task.py:12")
        self.assertEqual("usable", good["status"])
        first = delegate_return.adjudicate("", attempt=1)
        second = delegate_return.adjudicate("", attempt=2)
        self.assertEqual("redispatch", first["action"])
        self.assertEqual("no usable report", second["note"])
        self.assertFalse(first["finding"])
        self.assertFalse(second["finding"])
        wide = delegate_return.check_width(7)
        self.assertFalse(wide["ok"])
        self.assertIn("6", str(wide["correction"]))
        self.assertTrue(delegate_return.check_width(6)["ok"])

    def test_sample_rank_and_pin(self):
        sessions = [
            {"id": f"s{i:02d}", "error": i % 2 == 0, "tool_calls": 10 if i < 5 else 1, "denied": i % 3 == 0}
            for i in range(30)
        ]
        first = error_analysis.sample(sessions, n=30, seed=7, preset="random")
        second = error_analysis.sample(sessions, n=30, seed=7, preset="random")
        self.assertEqual(first["sessions"], second["sessions"])
        self.assertEqual(30, len(first["sessions"]))
        denied = error_analysis.sample(sessions, n=30, seed=1, preset="denied")
        self.assertTrue(denied["dropped"])
        labels = {
            sid: {"verdict": "acceptable", "critique": "", "first_failure_span": ""}
            for sid in first["sessions"]
        }
        for sid in first["sessions"][:4]:
            labels[sid] = {"verdict": "problematic", "critique": "first fail", "first_failure_span": "span-1"}
        with self.assertRaises(ValueError):
            error_analysis.build_cohort("bare", ["missing"], {}, severity=1)
        alpha = error_analysis.build_cohort("alpha", first["sessions"][:4], labels, severity=3)
        beta = error_analysis.build_cohort("beta", first["sessions"][4:14], labels, severity=2)
        ranked = error_analysis.rank([alpha, beta])
        self.assertEqual(["beta", "alpha"], [row["name"] for row in ranked])
        self.assertEqual(20, len(beta["sessions"]) * beta["severity"])
        self.assertEqual(12, len(alpha["sessions"]) * alpha["severity"])
        pinned = error_analysis.pin("alpha", "tool_not_called", {"id": "s00", "tool": "bash"}, "pr-0")
        self.assertEqual("regression", pinned["set"])
        self.assertEqual("cohort:alpha", pinned["source"])
        with self.assertRaises(ValueError):
            error_analysis.pin("alpha", "tool_called", {"text": _planted_secret()}, "pr-0")

    def test_replay_does_not_run_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            touched = Path(tmp) / "should-not-exist"

            def protocol(event, revision):
                self.assertFalse(touched.exists())
                decision = "deny" if revision == "bad" and event["id"] == "e2" else "allow"
                return {"decision": decision, "rule_id": "rule", "exit_code": 0}

            events = [
                {"id": "e1", "command": f"touch {touched}", "state_snapshot": {"ok": True}},
                {"id": "e2", "command": f"touch {touched}", "state_snapshot": {"ok": True}},
            ]
            same = guard_replay.replay(events, baseline="good", candidate="good", run_protocol=protocol)
            self.assertEqual([], same["diff"])
            self.assertTrue(same["ok"])
            flipped = guard_replay.replay(events, baseline="good", candidate="bad", run_protocol=protocol)
            self.assertEqual(["e2"], [row["id"] for row in flipped["diff"]])
            self.assertFalse(touched.exists())
            missing = guard_replay.replay(
                [{"id": "e3", "command": f"touch {touched}"}],
                baseline="good",
                candidate="good",
                run_protocol=protocol,
            )
            self.assertEqual(1, missing["unreplayable"])
            self.assertFalse(missing["ok"])
            self.assertFalse(touched.exists())


class UpliftAndLspTests(unittest.TestCase):
    def test_install_trees_do_not_consume_the_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            (project / ".agents").mkdir(parents=True)
            (project / ".agents" / "big.md").write_text("INSTALL" * 5000, encoding="utf-8")
            (project / "pom.xml").write_text("<project>test</project>\n", encoding="utf-8")
            (project / "src").mkdir()
            (project / "src" / "App.java").write_text("class App {}\n", encoding="utf-8")
            (project / "notes.txt").write_text("later\n", encoding="utf-8")
            bundle = _source_bundle()(project, limit=120_000)
        self.assertNotIn("INSTALL", bundle)
        self.assertIn("pom.xml", bundle)
        self.assertLess(bundle.index("pom.xml"), bundle.index("src/App.java"))
        self.assertLess(bundle.index("src/App.java"), bundle.index("notes.txt"))
        protocol = (ROOT / "experiments" / "harness-uplift-55" / "PROTOCOL.md").read_text(encoding="utf-8")
        self.assertIn("blocked", protocol.casefold())
        self.assertIn("null", protocol)

    def test_lsp_lite_stays_off(self):
        proof = (ROOT / "references" / "lsp-lite-host-proof.md").read_text(encoding="utf-8")
        self.assertIn("no host proved", proof.casefold())
        guard = (ROOT / "hooks" / "guard.py").read_text(encoding="utf-8")
        self.assertNotIn("lsp-lite", guard)
        self.assertNotIn("CHAOS_ENGINE_LSP", guard)
        registry = json.loads((ROOT / "runtime" / "env_registry.d" / "measure.json").read_text(encoding="utf-8"))
        self.assertIn("CHAOS_ENGINE_TRACE", registry)
        self.assertNotIn("CHAOS_ENGINE_LSP", registry)
        self.assertFalse(trace_recorder.enabled({}))


if __name__ == "__main__":
    unittest.main()
