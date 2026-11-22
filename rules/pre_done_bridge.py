"""Call one shipped function in each rules/*.py module from pre-done and done.

RETIRED maps a module name to why it stays on disk but is not a gate.
Empty means every module is wired. Do not delete a module tests still import.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# Retirement records live in this registry. None are retired: each module is wired.
RETIRED: dict[str, str] = {}

WIRED = (
    "avatar_likeness_gate",
    "cms_block_identity",
    "design_fix_loop",
    "ethics_check",
    "gate_proven_red",
    "large_read_deny",
    "lessons_2026_11_01",
    "lessons_2026_11_02",
    "lessons_2026_11_06",
    "lessons_l82_l92",
    "lessons_repeat_failure_pdca",
    "mega_pr",
    "memory_full_dump",
    "no_probe_live",
    "operation_boundary",
    "orchestrator_pre_publish",
    "preview_at_real_width",
    "public_facts",
    "remote_credential_guard",
    "verify_dropped",
    "web_ui_gate",
)

_CACHE: dict[str, object] = {}


def load_module(name: str):
    cached = _CACHE.get(name)
    if cached is not None:
        return cached
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"ce_rule_{name}", path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    _CACHE[name] = module
    return module


def _evaluate(module, payload):
    return module.evaluate(payload)


def _ethics(module, payload):
    blocked = module.blocks_submit(payload if isinstance(payload, dict) else None)
    return {"ok": not blocked, "hits": ["blocks-submit"] if blocked else []}


def _proven(module, payload):
    def green(_obs):
        return {"ok": True, "hits": []}

    try:
        module.prove_red(green, payload)
    except AssertionError as error:
        return {"ok": False, "hits": ["gate-not-red"], "error": str(error)}
    return {"ok": True, "hits": []}


def _large(module, payload):
    body = payload if isinstance(payload, dict) else {}
    reason = module.deny_reason(body.get("tool_name"), body.get("tool_input"), body.get("cwd"))
    return {"ok": reason is None, "hits": [] if reason is None else [reason]}


def _worker(module, payload):
    return module.evaluate_worker_budget(payload if isinstance(payload, dict) else {})


def _board(module, payload):
    return module.evaluate_status_board(payload if isinstance(payload, dict) else {})


def _delegation(module, payload):
    return module.evaluate_delegation_cycle(payload if isinstance(payload, dict) else {})


def _compose(module, payload):
    return module.evaluate_evidence_compose(payload if isinstance(payload, str) else "")


def _repeat(module, payload):
    return module.evaluate_repeat_failure_pdca(payload if isinstance(payload, dict) else {})


def _memory(module, payload):
    text = payload if isinstance(payload, str) else ""
    truncated = module.looks_truncated(text)
    return {"ok": not truncated, "hits": ["truncated-memory"] if truncated else []}


def _boundary(module, payload):
    hits = module.secret_failures(payload if isinstance(payload, str) else "")
    return {"ok": not hits, "hits": list(hits)}


def _remote(module, payload):
    reason = module.url_embeds_credentials(payload if isinstance(payload, str) else "")
    return {"ok": reason is None, "hits": [] if reason is None else [reason]}


_CALLERS = {
    "avatar_likeness_gate": _evaluate,
    "cms_block_identity": _evaluate,
    "design_fix_loop": _evaluate,
    "ethics_check": _ethics,
    "gate_proven_red": _proven,
    "large_read_deny": _large,
    "lessons_2026_11_01": _worker,
    "lessons_2026_11_02": _board,
    "lessons_2026_11_06": _delegation,
    "lessons_l82_l92": _compose,
    "lessons_repeat_failure_pdca": _repeat,
    "mega_pr": _evaluate,
    "memory_full_dump": _memory,
    "no_probe_live": _evaluate,
    "operation_boundary": _boundary,
    "orchestrator_pre_publish": _evaluate,
    "preview_at_real_width": _evaluate,
    "public_facts": _evaluate,
    "remote_credential_guard": _remote,
    "verify_dropped": _evaluate,
    "web_ui_gate": _evaluate,
}


def invoke(name: str, payload: object) -> dict:
    """Call the shipped function for one rule module."""
    if name in RETIRED:
        return {"ok": True, "hits": [], "retired": RETIRED[name]}
    module = load_module(name)
    result = _CALLERS[name](module, payload)
    if not isinstance(result, dict):
        return {"ok": False, "hits": ["bad-result"]}
    hits = list(result.get("hits") or [])
    body = {"ok": bool(result.get("ok")), "hits": hits}
    for key, value in result.items():
        if key not in body:
            body[key] = value
    return body
