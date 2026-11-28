#!/usr/bin/env python3
"""Run the harness eval suite and report pass@k, pass^k, flakiness, and usage.

Offline unittest and pytest tasks measure wall time only. A cost that was not
measured stays null and is never added as zero.
"""

from __future__ import annotations

import argparse
import json
import subprocess  # nosec B404 - fixed unittest or pytest argv, no shell.
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_RELATIVE = Path("evals/harness-suite/manifest.json")
ALLOWED_SETS = frozenset({"capability", "regression"})
ALLOWED_AREAS = frozenset({"installer", "doctor", "entry", "hooks", "retrieve"})
ALLOWED_RUNNERS = frozenset({"unittest", "pytest"})


def load_manifest(path: Path | None = None) -> dict[str, Any]:
    target = path or (ROOT / MANIFEST_RELATIVE)
    document = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("manifest must be an object")
    return document


def _validate_thresholds(thresholds: dict[str, Any], defects: list[str]) -> None:
    for key in ("pass_at_k", "default_k", "min_tasks", "min_capability", "min_regression"):
        if key not in thresholds:
            defects.append(f"thresholds.{key} is required")
    required_pass = 1.0  # nosec B105 - pass@k gate threshold, not a credential.
    if thresholds.get("pass_at_k") != required_pass:
        defects.append("thresholds.pass_at_k must be exactly 1.0 for the PR gate")
    if thresholds.get("default_k") != 1:
        defects.append("thresholds.default_k must be 1 until nondeterministic tasks exist")


def _validate_task(
    task: dict[str, Any],
    *,
    prefix: str,
    thresholds: dict[str, Any],
    ids: set[str],
    defects: list[str],
) -> str | None:
    task_id = task.get("id")
    if not isinstance(task_id, str) or not task_id:
        defects.append(f"{prefix}.id must be a non-empty string")
    elif task_id in ids:
        defects.append(f"duplicate task id: {task_id}")
    else:
        ids.add(task_id)
    task_set = task.get("set")
    if task_set not in ALLOWED_SETS:
        defects.append(f"{prefix}.set must be capability|regression")
    if task.get("area") not in ALLOWED_AREAS:
        defects.append(f"{prefix}.area must be one of {sorted(ALLOWED_AREAS)}")
    if task.get("runner") not in ALLOWED_RUNNERS:
        defects.append(f"{prefix}.runner must be unittest|pytest")
    module = task.get("module")
    if not isinstance(module, str) or not module.startswith("tests.scripts."):
        defects.append(f"{prefix}.module must be a tests.scripts.* module")
    k = task.get("k", thresholds.get("default_k", 1))
    if not isinstance(k, int) or isinstance(k, bool) or k < 1:
        defects.append(f"{prefix}.k must be an integer >= 1")
    if task_set == "regression" and not isinstance(task.get("source_issue"), int):
        defects.append(f"{prefix}.source_issue must be an int for regression tasks")
    return task_set if isinstance(task_set, str) else None


def validate_manifest(document: dict[str, Any]) -> list[str]:
    defects: list[str] = []
    if document.get("schema_version") != 1:
        defects.append("schema_version must be 1")
    if document.get("package") != "chaos-engine":
        defects.append("package must be chaos-engine")
    thresholds = document.get("thresholds")
    if not isinstance(thresholds, dict):
        defects.append("thresholds must be an object")
        thresholds = {}
    else:
        _validate_thresholds(thresholds, defects)
    tasks = document.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        defects.append("tasks must be a non-empty list")
        return defects
    ids: set[str] = set()
    capability = 0
    regression = 0
    for index, task in enumerate(tasks):
        prefix = f"tasks[{index}]"
        if not isinstance(task, dict):
            defects.append(f"{prefix} must be an object")
            continue
        task_set = _validate_task(
            task, prefix=prefix, thresholds=thresholds, ids=ids, defects=defects
        )
        if task_set == "capability":
            capability += 1
        elif task_set == "regression":
            regression += 1
    min_tasks = thresholds.get("min_tasks", 0)
    min_capability = thresholds.get("min_capability", 0)
    min_regression = thresholds.get("min_regression", 0)
    if isinstance(min_tasks, int) and len(tasks) < min_tasks:
        defects.append(f"need at least {min_tasks} tasks, found {len(tasks)}")
    if isinstance(min_capability, int) and capability < min_capability:
        defects.append(f"need at least {min_capability} capability tasks, found {capability}")
    if isinstance(min_regression, int) and regression < min_regression:
        defects.append(f"need at least {min_regression} regression tasks, found {regression}")
    return defects


def _module_path(module: str) -> str:
    return "/".join(module.split(".")) + ".py"


def _run_command(argv: list[str], *, root: Path, timeout: int) -> tuple[bool, str]:
    completed = subprocess.run(  # nosec B603 - argv list, no shell.
        argv,
        cwd=root,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    output = (completed.stderr or "") + (completed.stdout or "")
    return completed.returncode == 0, output.strip()


def _run_unittest(module: str, *, root: Path, timeout: int) -> tuple[bool, str]:
    return _run_command(
        [sys.executable, "-m", "unittest", module],
        root=root,
        timeout=timeout,
    )


def _run_pytest(module: str, *, root: Path, timeout: int) -> tuple[bool, str]:
    return _run_command(
        [sys.executable, "-m", "pytest", "-q", "--tb=line", _module_path(module)],
        root=root,
        timeout=timeout,
    )


def pass_at_k(successes: list[bool]) -> float:
    """1 when any of the k attempts passed, else 0. Empty is 0."""
    if not successes:
        return 0.0
    return 1.0 if any(successes) else 0.0


def pass_pow_k(successes: list[bool]) -> float:
    """1 only when every attempt passed. Empty is 0."""
    if not successes:
        return 0.0
    return 1.0 if all(successes) else 0.0


def flakiness(successes: list[bool]) -> float:
    """pass@k minus pass^k. A task that sometimes passes and sometimes fails is 1."""
    return pass_at_k(successes) - pass_pow_k(successes)


def _blank_usage(wall_s: float | None) -> dict[str, Any]:
    return {
        "input_tokens": None,
        "output_tokens": None,
        "cost_usd": None,
        "wall_s": wall_s,
    }


def summarize_usage(usages: list[dict[str, Any]]) -> str:
    """Print unknown when any cost is null. Never treat null as zero."""
    total = len(usages)
    unmeasured = 0
    measured: list[float] = []
    for usage in usages:
        cost = usage.get("cost_usd") if isinstance(usage, dict) else None
        if cost is None:
            unmeasured += 1
            continue
        if isinstance(cost, bool) or not isinstance(cost, (int, float)):
            unmeasured += 1
            continue
        measured.append(float(cost))
    if unmeasured or not measured:
        return f"cost: unknown ({unmeasured} of {total} trials unmeasured)"
    return f"cost: {sum(measured):.6f}"


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def evaluate_task(
    task: dict[str, Any],
    *,
    root: Path,
    default_k: int,
    timeout: int,
) -> dict[str, Any]:
    k = int(task.get("k", default_k))
    runner = str(task.get("runner") or "unittest")
    run = _run_pytest if runner == "pytest" else _run_unittest
    attempts: list[dict[str, Any]] = []
    successes: list[bool] = []
    for attempt in range(k):
        started = time.monotonic()
        ok, output = run(str(task["module"]), root=root, timeout=timeout)
        elapsed = round(time.monotonic() - started, 3)
        successes.append(ok)
        supplied = task.get("usage") if attempt == 0 else None
        usage = _blank_usage(elapsed)
        if isinstance(supplied, dict):
            for key in ("input_tokens", "output_tokens", "cost_usd", "wall_s"):
                if key in supplied:
                    usage[key] = supplied[key]
            if usage["wall_s"] is None:
                usage["wall_s"] = elapsed
        attempts.append(
            {
                "attempt": attempt + 1,
                "passed": ok,
                "seconds": elapsed,
                "usage": usage,
                "tail": "\n".join(output.splitlines()[-12:]),
            }
        )
    at_k = pass_at_k(successes)
    pow_k = pass_pow_k(successes)
    return {
        "id": task["id"],
        "set": task["set"],
        "area": task["area"],
        "source_issue": task.get("source_issue"),
        "module": task["module"],
        "k": k,
        "pass_at_k": at_k,
        "pass_pow_k": pow_k,
        "flakiness": at_k - pow_k,
        "passed": at_k >= 1.0,
        "attempts": attempts,
    }


def evaluate_suite(
    document: dict[str, Any] | None = None,
    *,
    root: Path | None = None,
    timeout: int = 120,
) -> dict[str, Any]:
    root = root or ROOT
    document = document or load_manifest()
    defects = validate_manifest(document)
    if defects:
        return {
            "passed": False,
            "defects": defects,
            "results": [],
            "pass_at_k": 0.0,
            "pass_pow_k": 0.0,
            "flakiness": 0.0,
            "case_pass_rate": 0.0,
            "cost": summarize_usage([]),
        }
    thresholds = document["thresholds"]
    default_k = int(thresholds["default_k"])
    results = [
        evaluate_task(task, root=root, default_k=default_k, timeout=timeout)
        for task in document["tasks"]
    ]
    passed_count = sum(1 for row in results if row["passed"])
    total = len(results)
    case_pass_rate = (passed_count / total) if total else 0.0
    mean_pass_at_k = _mean([float(row["pass_at_k"]) for row in results])
    mean_pow = _mean([float(row["pass_pow_k"]) for row in results])
    mean_flaky = _mean([float(row["flakiness"]) for row in results])
    usages = [attempt["usage"] for row in results for attempt in row["attempts"]]
    required = float(thresholds["pass_at_k"])
    by_set = {
        name: {
            "passed": sum(1 for row in results if row["set"] == name and row["passed"]),
            "total": sum(1 for row in results if row["set"] == name),
        }
        for name in ("capability", "regression")
    }
    return {
        "passed": mean_pass_at_k >= required and passed_count == total and total > 0,
        "defects": [],
        "results": results,
        "pass_at_k": mean_pass_at_k,
        "pass_pow_k": mean_pow,
        "flakiness": mean_flaky,
        "case_pass_rate": case_pass_rate,
        "passed_count": passed_count,
        "total_count": total,
        "by_set": by_set,
        "threshold_pass_at_k": required,
        "cost": summarize_usage(usages),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / MANIFEST_RELATIVE)
    parser.add_argument("--json", action="store_true", help="print machine-readable report")
    parser.add_argument("--timeout", type=int, default=120, help="per-task timeout in seconds")
    parser.add_argument("--validate-only", action="store_true", help="validate the manifest and do not run tasks")
    args = parser.parse_args(argv)
    document = load_manifest(args.manifest)
    if args.validate_only:
        defects = validate_manifest(document)
        payload = {"passed": not defects, "defects": defects}
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        elif defects:
            print("manifest defects:")
            for defect in defects:
                print(f"  - {defect}")
        else:
            print(f"manifest ok ({len(document.get('tasks', []))} tasks)")
        return 0 if not defects else 1
    report = evaluate_suite(document, timeout=args.timeout)
    if args.json:
        printable = dict(report)
        printable.pop("results", None)
        printable["results"] = [
            {key: value for key, value in row.items() if key != "attempts"}
            | {"attempts": [{k: v for k, v in attempt.items() if k != "tail"} for attempt in row["attempts"]]}
            for row in report["results"]
        ]
        print(json.dumps(printable, indent=2, sort_keys=True))
    else:
        if report["defects"]:
            print("manifest defects:")
            for defect in report["defects"]:
                print(f"  - {defect}")
        for row in report.get("results", []):
            status = "PASS" if row["passed"] else "FAIL"
            issue = f" #{row['source_issue']}" if row.get("source_issue") else ""
            print(
                f"[{status}] {row['id']} set={row['set']} area={row['area']}"
                f"{issue} pass@{row['k']}={row['pass_at_k']:.1f}"
                f" pass^{row['k']}={row['pass_pow_k']:.1f}"
                f" flakiness={row['flakiness']:.1f}"
            )
            if not row["passed"]:
                for attempt in row["attempts"]:
                    if attempt["tail"]:
                        print(f"    attempt {attempt['attempt']}: {attempt['tail']}")
        by_set = report.get("by_set", {})
        print(
            f"pass_at_k={report['pass_at_k']:.3f} "
            f"pass_pow_k={report['pass_pow_k']:.3f} "
            f"flakiness={report['flakiness']:.3f} "
            f"case_pass_rate={report['case_pass_rate']:.3f} "
            f"({report.get('passed_count', 0)}/{report.get('total_count', 0)}) "
            f"capability={by_set.get('capability', {})} "
            f"regression={by_set.get('regression', {})} "
            f"{report['cost']}"
        )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
