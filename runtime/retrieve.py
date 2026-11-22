#!/usr/bin/env python3
"""Zero-LLM retrieve orchestrator: one store, bounded query, used|skipped|degraded (#5624)."""

from __future__ import annotations

import argparse
import json
import os
import re
import runpy
import sqlite3
import subprocess  # nosec B404 - optional advisory store CLIs only.
import sys
from pathlib import Path
from typing import Any

STORES = ("memory", "mempalace", "graphify", "live")
RETRIEVE_MODES = ("search", "impact")
STATUS_USED = "used"
STATUS_SKIPPED = "skipped"
STATUS_DEGRADED = "degraded"
QUERY_MAX = 240
TIMEOUT_SECONDS = 8
_EMPTY_RESULT = re.compile(r"^\s*no results( found)?\b", re.I)
PALACE_BACKEND = "sqlite_exact"
BACKEND_MISMATCH_FIX = (
    "run `python3 .chaos-engine/install.py doctor --project .`, then "
    "`python3 .chaos-engine/install.py repair --project . --component mempalace`; "
    "a Graphify-only answer is not a fallback for an indexed MemPalace; "
    "rerun retrieve with `--recheck` after repair (#6212)"
)

_GRAPHIFY_HINT = re.compile(r"\b(call(s|er|ees?)?|depend|graph|import|edge)\b", re.I)
_MEMPALACE_HINT = re.compile(r"\b(history|palace|session|timeline|before)\b", re.I)
# Native memory answers only a gotcha question. It is not a justifying store (#7407).
_MEMORY_HINT = re.compile(r"\b(gotcha|bitten|constraint)\b", re.I)



_REAL_RUN = subprocess.run


def _mindset():
    path = Path(__file__).resolve().with_name("harness_mindset.py")
    if not path.is_file():
        return None
    import importlib.util

    spec = importlib.util.spec_from_file_location("chaos_engine_harness_mindset_retrieve", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_until_stalled(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
    """Run without a wall-clock cap; stores.py stops it only when it stalls (#6377)."""
    import importlib.util as _ilu

    spec = _ilu.spec_from_file_location(
        "chaos_engine_stores_watchdog", Path(__file__).with_name("stores.py")
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("stores.py watchdog is unavailable")
    module = _ilu.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.run_until_stalled(args, **kwargs)


def is_empty_result(body: str) -> bool:
    """True for a store's plain 'no results' answer (#6377)."""
    text = body.strip()
    return not text or text.casefold() in {"[]", "{}", "none"} or bool(_EMPTY_RESULT.match(text))


def project_root(start: Path | None = None) -> Path:
    here = (start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / ".chaos-engine" / "install.py").is_file() or (
            candidate / "chaos-engine" / "install.py"
        ).is_file():
            return candidate
    return here


def pick_store(query: str, store: str | None = None) -> str:
    if store:
        chosen = str(store).strip().casefold()
        if chosen not in STORES:
            raise ValueError(f"unknown-store: {store}")
        return chosen
    if _GRAPHIFY_HINT.search(query):
        return "graphify"
    if _MEMPALACE_HINT.search(query):
        return "mempalace"
    if _MEMORY_HINT.search(query):
        return "memory"
    return "graphify"


# First match wins. A second backend runs only after a miss, never after an error.
_IMPACT_RE = re.compile(r"\b(who\s+calls|callers?|calls|impact|breaks|depends|depend)\b", re.I)
_EXPLAIN_RE = re.compile(r"\b(explain|orient|overview)\b", re.I)
_HISTORY_RE = re.compile(r"\b(why|when|decided|decision|before|last\s+time|history)\b", re.I)
_DATE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
_GOTCHA_RE = re.compile(r"\b(gotcha|constraint|bitten)\b", re.I)
_EXACT_RE = re.compile(
    r"\"[^\"]+\"|'[^']+'|\b(current behavio[u]r|exact string|right now)\b",
    re.I,
)
_MISS_REASONS = frozenset(
    {
        "no-relevant-hits",
        "no-rare-token",
        "no-node",
        "ambiguous",
        "ambiguous-unparsed",
        "miss",
        "no-results",
    }
)
_CANDIDATE_ID = re.compile(r"^\s+id:\s*(\S+)\s*$", re.MULTILINE)
_RRF_K = 60
POLICY_ON_MISS = "two-store-on-miss"


def _route(
    reason: str,
    store: str,
    verb: str,
    symbols: list[str],
    fallback: str | None = None,
    fallback_verb: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    route: dict[str, Any] = {
        "reason": reason,
        "primary": store,
        "verb": verb,
        "fallback": fallback,
        "fallbackVerb": fallback_verb,
        "symbols": list(symbols),
    }
    route.update(extra)
    return route


def question_rare_tokens(query: str) -> list[str]:
    """Rare tokens after punctuation is split off, so ``FooBar?`` still counts."""
    split = _corpus_split()
    if split is None:
        return []
    cleaned = re.sub(r"[^\w./-]+", " ", query)
    return split.rare_tokens(cleaned)


def implicit_clue(query: str, gold_text: str) -> bool:
    """True when no rare question token occurs in the gold item."""
    folded = gold_text.casefold()
    return not any(token.casefold() in folded for token in question_rare_tokens(query))


def classify_scope(query: str) -> dict[str, Any]:
    """Deterministic scope table. No model call."""
    symbols = question_rare_tokens(query)
    dated = _DATE_RE.search(query)
    since = dated.group(1) if dated else None
    if symbols and _IMPACT_RE.search(query):
        return _route("symbol-impact", "graphify", "affected", symbols, "graphify", "query", depth=2)
    if len(symbols) >= 2:
        return _route("two-symbols", "graphify", "path", symbols, "graphify", "explain")
    if _EXPLAIN_RE.search(query):
        if symbols:
            return _route("explain-symbol", "graphify", "explain", symbols, "rg", "rg")
        return _route("explain-query", "graphify", "query", symbols, "rg", "rg", budget=_token_budget()[0])
    if _HISTORY_RE.search(query) or since:
        return _route(
            "history", "mempalace", "search", symbols, "memory", "query", results=_token_budget()[1], since=since
        )
    if _GOTCHA_RE.search(query):
        return _route("gotcha", "memory", "query", symbols, "mempalace", "search", results=_token_budget()[1])
    if not symbols:
        return _route("no-rare-token", "mempalace", "search", symbols, "graphify", "query", results=_token_budget()[1])
    if _EXACT_RE.search(query):
        return _route("exact-string", "rg", "rg", symbols)
    return _route("symbol-query", "graphify", "query", symbols, "rg", "rg", budget=_token_budget()[0])


def _top_graphify_candidate(text: str) -> str | None:
    found = _CANDIDATE_ID.findall(text or "")
    if found:
        return found[0]
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("Ambiguous:", "Retry", "No unique")):
            continue
        if stripped.startswith("id:"):
            return stripped.split(":", 1)[1].strip() or None
        return stripped
    return None


def _miss_receipt(store: str, query: str, reason: str) -> dict[str, Any]:
    return {
        "store": store,
        "status": STATUS_SKIPPED,
        "reason": reason,
        "query": query,
        "hits": [],
        "excerpt": "",
        "bytes": 0,
    }


def _is_miss(outcome: dict[str, Any]) -> bool:
    if outcome.get("status") == STATUS_DEGRADED:
        return False
    if str(outcome.get("reason") or "") in _MISS_REASONS:
        return True
    return outcome.get("status") == STATUS_USED and not outcome.get("hits")


def _live_hit(project: Path, hit: dict[str, Any]) -> bool:
    raw = str(hit.get("path") or "").replace("\\", "/").strip()
    if not raw or raw.startswith("/") or raw.startswith("../") or "/../" in f"/{raw}":
        return False
    path = (project / raw).resolve()
    try:
        path.relative_to(project.resolve())
    except ValueError:
        return False
    return path.is_file()


def reciprocal_rank_fusion(groups: list[list[dict[str, Any]]], *, k: int = _RRF_K) -> list[dict[str, Any]]:
    """Fuse ranked hit lists. Cap 8. Shared hits outrank a hit from one list."""
    totals: dict[tuple[str, int | None], float] = {}
    best_rank: dict[tuple[str, int | None], int] = {}
    chosen: dict[tuple[str, int | None], dict[str, Any]] = {}
    for group in groups:
        for rank, hit in enumerate(group, start=1):
            path = str(hit.get("path") or "")
            if not path:
                continue
            line = hit.get("line")
            key = (path, int(line) if isinstance(line, int) else None)
            totals[key] = totals.get(key, 0.0) + 1.0 / (k + rank)
            previous = best_rank.get(key)
            if previous is None or rank < previous:
                best_rank[key] = rank
                item: dict[str, Any] = {
                    "path": path,
                    "store": hit.get("store"),
                    "route": hit.get("route"),
                }
                if isinstance(line, int):
                    item["line"] = line
                chosen[key] = item
    ordered = sorted(totals, key=lambda item: (-totals[item], item[0], -1 if item[1] is None else item[1]))
    fused: list[dict[str, Any]] = []
    for key in ordered[:_HIT_LIMIT]:
        hit = chosen[key]
        hit["score"] = totals[key]
        fused.append(hit)
    return fused


def _tag_hits(hits: list[dict[str, Any]], store: str, reason: str) -> list[dict[str, Any]]:
    tagged: list[dict[str, Any]] = []
    for hit in hits:
        if not isinstance(hit, dict) or not hit.get("path"):
            continue
        item: dict[str, Any] = {"path": str(hit["path"]), "store": store, "route": reason}
        if hit.get("line") is not None:
            item["line"] = int(hit["line"])
        tagged.append(item)
    return tagged


def _verify_hits(project: Path, hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [hit for hit in hits if _live_hit(project, hit)]


def _justification(project: Path):
    path = Path(__file__).resolve().parents[1] / "hooks" / "retrieve_justification.py"
    if not path.is_file():
        return None
    import importlib.util

    spec = importlib.util.spec_from_file_location("chaos_engine_retrieve_justification", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_BACKEND_MISMATCH = re.compile(r"backend[-_ ]mismatch", re.IGNORECASE)


def _is_backend_mismatch(*parts: str) -> bool:
    blob = " ".join(parts)
    if _BACKEND_MISMATCH.search(blob):
        return True
    folded = blob.casefold()
    return "chroma" in folded and "mismatch" in folded


def _note_cited_usage(project: Path, mindset: Any, paths: list[str] | None = None) -> None:
    """Attach stored citations, including a basename match, onto the new usage row."""
    module = _justification(project)
    if module is None:
        return
    noted: list[str] = []
    if hasattr(module, "load_citations"):
        noted.extend(str(path) for path in module.load_citations(project))
    if hasattr(module, "cites"):
        for path in paths or []:
            if path and module.cites(project, path) and path not in noted:
                noted.append(path)
    for path in noted:
        mindset.note_path_read(project, path)


def _record_store_outcome(
    project: Path, store: str, status: str, query: str, text: str = "", reason: str = ""
) -> None:
    if store not in {"mempalace", "graphify"}:
        return
    module = _justification(project)
    if module is None:
        return
    module.record_store_outcome(project, store, status, query, text, reason)


def _citation_text(receipt: dict) -> str:
    """Paths extract_citations already parses. No new grammar."""
    parts: list[str] = []
    hits = receipt.get("hits") if isinstance(receipt.get("hits"), list) else []
    for hit in hits:
        if not isinstance(hit, dict) or not hit.get("path"):
            continue
        path = str(hit["path"])
        line = hit.get("line")
        parts.append(f"{path}:{line}" if line else path)
    excerpt = str(receipt.get("excerpt") or "")
    if excerpt:
        parts.append(excerpt)
    return "\n".join(parts)


def _commit_retrieve_receipt(root: Path, store: str, query: str, receipt: dict) -> None:
    status = str(receipt.get("status") or "")
    if status not in {STATUS_USED, STATUS_SKIPPED, STATUS_DEGRADED}:
        return
    _record_store_outcome(
        root,
        store,
        status,
        query,
        _citation_text(receipt),
        str(receipt.get("reason") or ""),
    )


def _tool_py(project: Path) -> Path | None:
    for relative in (".chaos-engine/tool.py", "chaos-engine/tool.py"):
        path = project / relative
        if path.is_file():
            return path
    return None


_HIT = re.compile(
    r"(?P<path>(?:[\w.-]+/)+[\w.-]+\.[A-Za-z0-9]+)"
    r"(?::L?(?P<colon>\d+)|\s+L(?P<space>\d+))?"
)
_HIT_LIMIT = 8
# MemPalace prints only a basename ("Source: CdpWorkers.java"); resolve unique ones to repo paths.
_SOURCE_LINE = re.compile(r"^\s*Source:\s+(?P<name>[\w.-]+\.[A-Za-z0-9]+)\s*$", re.MULTILINE)
_EXCERPT_WITH_HITS = 800


def _query_tokens(query: str) -> set[str]:
    return {token.casefold() for token in re.findall(r"[A-Za-z0-9_.-]{3,}", query or "")}


def _hit_matches_query(path: str, tokens: set[str]) -> bool:
    if not tokens:
        return False
    lowered = path.casefold()
    parts = [part for part in re.split(r"[/_.-]+", lowered) if part]
    return any(token in parts or token in lowered for token in tokens)


def _query_outside_workspace(project: Path, query: str) -> bool:
    """True when every absolute path in the query sits outside this checkout.

    An in-repo hit must not be reported as ``used`` for that query (#6312).
    A query with no absolute path is unchanged.
    """
    found = re.findall(r"(?:(?:[A-Za-z]:)?(?:/|\\)[\w .+@-]{1,80}){2,}", query or "")
    if not found:
        return False
    try:
        root = project.resolve()
    except OSError:
        return False
    saw_outside = False
    for raw in found:
        candidate = Path(raw.strip())
        if not candidate.is_absolute():
            return False
        try:
            resolved = candidate.resolve()
        except OSError:
            return False
        if resolved == root or root in resolved.parents:
            return False
        saw_outside = True
    return saw_outside


def _outside_workspace_receipt(project: Path, store: str, query: str) -> dict[str, Any] | None:
    """Explicit miss when the query is about paths this repo cannot cite (#6312)."""
    if not _query_outside_workspace(project, query):
        return None
    return {
        "store": store,
        "status": STATUS_SKIPPED,
        "reason": "unrelated-in-repo",
        "query": query,
    }


def _structured_hits(
    body: str, limit: int = _HIT_LIMIT, query: str = ""
) -> list[dict[str, object]]:
    """Repo-relative path and line. Token-sharing paths fill the slots first."""
    found: list[dict[str, object]] = []
    seen: set[tuple[str, str | None]] = set()
    for match in _HIT.finditer(body):
        path = match.group("path")
        line_text = match.group("colon") or match.group("space")
        key = (path, line_text)
        if key in seen:
            continue
        seen.add(key)
        item: dict[str, object] = {"path": path}
        if line_text:
            item["line"] = int(line_text)
        found.append(item)
        if len(found) >= 200:
            break
    tokens = _query_tokens(query)
    matched = [item for item in found if _hit_matches_query(str(item["path"]), tokens)]
    chosen = matched if matched else found
    return chosen[:limit]


_GRAPHIFY_NODE = re.compile(
    r"^NODE (?P<label>.+?) \[src=(?P<path>[^\s\]]+) loc=(?:L?(?P<line>\d+))?", re.MULTILINE
)


def _graphify_hits(body: str, query: str = "") -> list[dict[str, object]]:
    """Graphify ``NODE`` lines in Graphify's order, each with its label; else path hits."""
    found: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for match in _GRAPHIFY_NODE.finditer(body):
        path, label = match.group("path"), match.group("label").strip()
        if path.startswith(("../", "./")) or (path, label) in seen:
            continue
        seen.add((path, label))
        item: dict[str, object] = {"path": path, "label": label}
        if match.group("line"):
            item["line"] = int(match.group("line"))
        found.append(item)
        if len(found) >= 200:
            break
    return found if found else _structured_hits(body, query=query)


_LABELS_PER_FILE = 3


def _collapse_hits_by_file(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One hit per path at its best-ranked position (#7179).

    The best section keeps ``label`` and ``line``; when several sections of the
    file matched, ``labels`` lists up to three of them in rank order.
    """
    collapsed: dict[str, dict[str, Any]] = {}
    for hit in hits:
        path = str(hit.get("path") or "")
        label = hit.get("label")
        kept = collapsed.get(path)
        if kept is None:
            collapsed[path] = dict(hit)
            continue
        if not label:
            continue
        labels = kept.setdefault("labels", [kept["label"]] if kept.get("label") else [])
        if label not in labels and len(labels) < _LABELS_PER_FILE:
            labels.append(label)
    for hit in collapsed.values():
        if len(hit.get("labels", ())) < 2:
            hit.pop("labels", None)
    return list(collapsed.values())


def _graphify_texts(project: Path) -> dict[tuple[str, str], str]:
    stores = _load_stores()
    if stores is None or not hasattr(stores, "documentation_texts"):
        return {}
    try:
        return stores.documentation_texts(stores.resolve_graph_out(project))
    except OSError:
        return {}


def _source_name_hits(project: Path, body: str, limit: int = _HIT_LIMIT) -> list[dict[str, object]]:
    """Repo paths for MemPalace ``Source:`` basenames that name exactly one tracked file."""
    names = list(dict.fromkeys(match.group("name") for match in _SOURCE_LINE.finditer(body)))
    if not names:
        return []
    try:
        listed = subprocess.run(  # nosec B603 B607 - fixed git argv, no shell.
            ["git", "ls-files"], cwd=project, capture_output=True, text=True, check=False, timeout=20
        ).stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        return []
    by_name: dict[str, list[str]] = {}
    for path in listed:
        by_name.setdefault(path.rsplit("/", 1)[-1], []).append(path)
    hits = [{"path": by_name[name][0]} for name in names if len(by_name.get(name, [])) == 1]
    return hits[:limit]


def _mempalace_hits(project: Path, body: str, query: str) -> list[dict[str, object]]:
    """MemPalace names each hit's file on its ``Source:`` line; excerpt links are page text.

    A relative link inside an excerpt (``../index.md``) is not a hit and never becomes one.
    """
    sources = _source_name_hits(project, body)
    if sources:
        return sources
    return [
        hit for hit in _structured_hits(body, query=query)
        if not str(hit["path"]).startswith(("../", "./"))
    ]


_BUDGET_HINT = re.compile(
    r"raise the token budget \(CLI: --budget\)[^.]*\.?\s*"
)


def _bounded_excerpt(body: str, limit: int = 4096) -> str:
    """Return the store text the caller can use, capped so a receipt stays small."""
    body = _BUDGET_HINT.sub("", body)
    raw = body.encode("utf-8")
    if len(raw) <= limit:
        return body
    return raw[:limit].decode("utf-8", errors="ignore")



def _load_stores():
    if globals().get("_STORES_MODULE") is not None:
        return globals()["_STORES_MODULE"]
    import importlib.util as _ilu
    spec = _ilu.spec_from_file_location("chaos_engine_stores_retrieve_gate", Path(__file__).resolve().with_name("stores.py"))
    if spec is None or spec.loader is None:
        return None
    module = _ilu.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    globals()["_STORES_MODULE"] = module
    return module


def _git_common_without_process(project: Path) -> Path | None:
    """Shared git dir from `.git` / `commondir` text. Never spawns git."""
    git_path = project / ".git"
    try:
        if git_path.is_dir():
            git_dir = git_path
        elif git_path.is_file():
            line = git_path.read_text(encoding="utf-8").strip()
            if not line.startswith("gitdir:"):
                return None
            raw = Path(line.split(":", 1)[1].strip())
            git_dir = raw if raw.is_absolute() else (project / raw).resolve()
        else:
            return None
        common_file = git_dir / "commondir"
        if common_file.is_file():
            raw = Path(common_file.read_text(encoding="utf-8").strip())
            return raw.resolve() if raw.is_absolute() else (git_dir / raw).resolve()
        return git_dir.resolve()
    except OSError:
        return None


def _palace_for_gate(project: Path) -> Path | None:
    """Palace path for the corrupt-store gate, through the shared store resolver."""
    # Patched subprocess tests must not spawn git via the resolver.
    if subprocess.run is _REAL_RUN and (stores := _load_stores()) is not None:
        try:
            return stores.resolve_palace(project)
        except (OSError, RuntimeError):
            return None
    common = _git_common_without_process(project)
    if common is not None:
        return common / "chaos-engine" / "mempalace"
    return project / ".chaos-engine-state" / "mempalace"


def _corrupt_mempalace_gate(project: Path) -> dict[str, str] | None:
    """quick_check the palace before search. Corrupt → quarantine, never partial hits (#7118)."""
    stores = _load_stores()
    if stores is None:
        return None
    palace = _palace_for_gate(project)
    if palace is None:
        return None
    return stores.corrupt_palace_gate(palace)


def _graphify_seeds(query: str) -> list[str]:
    """Caller questions must not pass a bare identifier seed Graphify cannot resolve."""
    split = _corpus_split()
    if split is None:
        return []
    seeds = split.walk_seeds(query)
    if split._CALLER.search(query):
        return [seed for seed in seeds if "/" in seed or "." in seed]
    return seeds


def _skip_no_rare_before_store(store: str, query: str) -> bool:
    """Unpatched Graphify does not walk a query that has no rare token.

    A patched ``subprocess.run`` still runs so a concrete ``src=`` path is kept.
    """
    if store != "graphify" or subprocess.run is not _REAL_RUN:
        return False
    split = _corpus_split()
    if split is None or question_rare_tokens(query):
        return False
    words = query.split()
    return not (len(words) == 1 and words[0].casefold() in split.GENERIC_SEEDS)


def _keep_store_path_or_skip_no_rare(store: str, query: str, outcome: dict[str, Any]) -> dict[str, Any]:
    """A query with no rare token keeps a store path that contains a query word.

    With no such path, the result is skipped. ``failure tail`` does not need a
    Graphify index. One generic word still uses the store walk.
    """
    if store != "graphify":
        return outcome
    split = _corpus_split()
    if split is None or question_rare_tokens(query):
        return outcome
    words = query.split()
    if len(words) == 1 and words[0].casefold() in split.GENERIC_SEEDS:
        return outcome
    tokens = {token.casefold() for token in re.findall(r"[A-Za-z0-9_.-]{3,}", query)}
    hits = outcome.get("hits") if isinstance(outcome.get("hits"), list) else []
    concrete = outcome.get("status") == STATUS_USED and any(
        isinstance(hit, dict)
        and any(token in str(hit.get("path") or "").casefold() for token in tokens)
        for hit in hits
    )
    if concrete:
        return outcome
    return {
        "status": STATUS_SKIPPED,
        "reason": "no-rare-token",
        "hits": [],
        "query": query,
        "excerpt": "",
        "bytes": 0,
    }


def _split_hits(store: str, query: str, hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Graphify uses the path predicate. MemPalace requires a rare token in the path or section."""
    split = _corpus_split()
    if split is None:
        return hits
    if store == "mempalace":
        return split.drop_path_section_misses(query, hits)
    if store == "graphify":
        return split.apply_path_predicate(query, hits)
    return hits


def _store_hit_receipt(
    project: Path, store: str, query: str, completed: subprocess.CompletedProcess[str], origin_sync: bool
) -> dict[str, Any]:
    """Turn a zero-exit store command into a used, skipped, or outside-workspace receipt."""
    body = (completed.stdout or "").strip()
    if is_empty_result(body):
        return {
            "store": store,
            "status": STATUS_SKIPPED,
            "reason": "no-relevant-hits",
            "query": query,
        }
    outside = _outside_workspace_receipt(project, store, query)
    if outside is not None:
        return outside
    if store == "mempalace":
        hits = _mempalace_hits(project, body, query)
    elif store == "graphify":
        hits = _graphify_hits(body, query=query)
    else:
        hits = _structured_hits(body, query=query)
    mindset = _mindset()
    if store == "graphify" and mindset is not None:
        texts = _graphify_texts(project) if any("label" in hit for hit in hits) else {}
        hits = _collapse_hits_by_file(
            mindset.relevance_floor(hits, query, project=project, texts=texts)
        )[:_HIT_LIMIT]
        if not hits:
            return {
                "store": store,
                "status": STATUS_SKIPPED,
                "reason": "no-relevant-hits",
                "query": query,
                "hits": [],
                "bytes": 0,
            }
    if store in {"graphify", "mempalace"}:
        hits = _split_hits(store, query, hits)
        if not hits:
            return {
                "store": store,
                "status": STATUS_SKIPPED,
                "reason": "no-relevant-hits",
                "query": query,
                "hits": [],
                "bytes": 0,
            }
    if store == "memory" and not hits and mindset is not None:
        return mindset.memory_no_hit_receipt()
    excerpt_limit = _EXCERPT_WITH_HITS if hits else 4096
    if mindset is not None:
        excerpt_limit = min(excerpt_limit, mindset.store_budget_bytes(store))
    excerpt = _bounded_excerpt(_omit_duplicate_path_lines(body, hits) if hits else body, excerpt_limit)
    receipt = {
        "store": store,
        "status": STATUS_USED,
        "reason": "hits",
        "query": query,
        "hits": hits,
        "excerpt": excerpt,
        "bytes": len(excerpt.encode("utf-8")),
    }
    if origin_sync:
        receipt["originSync"] = "advisory"
    return receipt


def _run_store(
    project: Path,
    store: str,
    query: str,
    scope: dict[str, Any] | None = None,
    _reseeded: bool = False,
) -> dict[str, Any]:
    """One attempt. Graphify exit 3 reseeds once. Exit 4 is a miss, not an outage."""
    tool = _tool_py(project)
    if tool is None:
        return {
            "store": store,
            "status": STATUS_DEGRADED,
            "reason": "tool.py-absent",
            "query": query,
        }
    # Map store → advisory CLI shape (bounded; never writes).
    if store == "mempalace":
        gate = _corrupt_mempalace_gate(project)
        if gate is not None:
            return {
                "store": store,
                "status": STATUS_DEGRADED,
                "reason": "corrupt-quarantined",
                "query": query,
                "hits": [],
                "detail": gate["detail"],
                "fixNext": gate["fixNext"],
                "quarantine": gate.get("quarantine", ""),
            }
    scoped = scope or {}
    if store == "memory":
        args = [sys.executable, str(tool), "memory", "query", query]
    elif store == "mempalace":
        args = [sys.executable, str(tool), "mempalace", "search", query]
        if scoped.get("wing"):
            args.extend(["--wing", str(scoped["wing"])])
        if scoped.get("results"):
            args.extend(["--results", str(scoped["results"])])
        if scoped.get("since"):
            args.extend(["--since", str(scoped["since"])])
    else:
        verb = str(scoped.get("verb") or "query")
        symbols = [str(item) for item in scoped.get("symbols") or []]
        if _reseeded and scoped.get("symbol"):
            symbols = [str(scoped["symbol"])]
        if verb == "affected":
            symbol = symbols[0] if symbols else query
            depth = scoped.get("depth") or 2
            args = [sys.executable, str(tool), "graphify", "affected", symbol, "--depth", str(depth)]
        elif verb == "path" and len(symbols) >= 2:
            args = [sys.executable, str(tool), "graphify", "path", symbols[0], symbols[1]]
        elif verb == "explain":
            symbol = symbols[0] if symbols else query
            args = [sys.executable, str(tool), "graphify", "explain", symbol]
        else:
            args = [sys.executable, str(tool), "graphify", "query", query]
            if scoped.get("budget"):
                args.extend(["--budget", str(scoped["budget"])])
            if scoped.get("depth"):
                args.extend(["--depth", str(scoped["depth"])])
            if scoped.get("seeds"):
                seeds = [str(seed) for seed in scoped["seeds"]]
            else:
                seeds = _graphify_seeds(query)
                if seeds and [seed.casefold() for seed in seeds] == [word.casefold() for word in query.split()]:
                    seeds = []
            for seed in seeds:
                args.extend(["--seed", seed])
    env = _retrieve_env(project)
    if store == "mempalace" and (hit := _mempalace_fts_receipt(project, query)): return hit
    if store == "mempalace":
        env["MEMPALACE_BACKEND"] = PALACE_BACKEND
    try:
        # A patched subprocess.run (tests) is used as-is; the real one gets the watchdog.
        runner = run_until_stalled if subprocess.run is _REAL_RUN else subprocess.run
        completed = runner(  # nosec B603 - fixed owned tool.py only.
            args,
            cwd=project,
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "store": store,
            "status": STATUS_DEGRADED,
            "reason": "timeout",
            "query": query,
        }
    except OSError as error:
        return {
            "store": store,
            "status": STATUS_DEGRADED,
            "reason": f"os-error:{type(error).__name__}",
            "query": query,
        }
    detail = (completed.stderr or completed.stdout or "").strip().splitlines()
    tip = detail[0][:120] if detail else ""
    origin_sync = "not synchronized with origin/" in (
        (completed.stderr or "") + (completed.stdout or "")
    )
    if completed.returncode == 3 and store == "graphify":
        if not _reseeded:
            candidate = _top_graphify_candidate((completed.stderr or "") + "\n" + (completed.stdout or ""))
            if candidate:
                reseed = dict(scoped)
                reseed["symbol"] = candidate
                reseed["seeds"] = [candidate]
                reseed.setdefault("verb", "query")
                return _run_store(project, store, query, reseed, True)
        return _miss_receipt(store, query, "ambiguous")
    if completed.returncode == 4 and store == "graphify":
        return _miss_receipt(store, query, "no-node")
    if completed.returncode != 0:
        if origin_sync:
            return {
                "store": store,
                "status": STATUS_SKIPPED,
                "reason": "origin-sync",
                "originSync": "advisory",
                "storeHealth": "unchecked",
                "query": query,
            }
        mismatch = store == "mempalace" and _is_backend_mismatch(
            completed.stderr or "", completed.stdout or "", tip
        )
        degraded = {
            "store": store,
            "status": STATUS_DEGRADED,
            "reason": "backend-mismatch" if mismatch else (tip or "nonzero-exit"),
            "query": query,
            "exitCode": completed.returncode,
        }
        if mismatch:
            degraded.update(blocking=True, fixNext=BACKEND_MISMATCH_FIX)
            print(f"retrieve: MemPalace backend mismatch; {BACKEND_MISMATCH_FIX}", file=sys.stderr)
        return degraded
    return _store_hit_receipt(project, store, query, completed, origin_sync)


def _recorded_mismatch(project: Path, store: str, recheck: bool) -> dict[str, Any] | None:
    """Return the recorded MemPalace mismatch without re-running the store (#6212)."""
    if store != "mempalace":
        return None
    module = _justification(project)
    if module is None or not hasattr(module, "backend_mismatch_recorded"):
        return None
    if recheck and hasattr(module, "clear_backend_mismatch"):
        module.clear_backend_mismatch(project)
        return None
    if not module.backend_mismatch_recorded(project):
        return None
    return {
        "status": STATUS_DEGRADED,
        "reason": "backend-mismatch",
        "scheduled": False,
        "blocking": True,
        "fixNext": BACKEND_MISMATCH_FIX,
    }


def _corpus_split():
    path = Path(__file__).resolve().with_name("corpus_split.py")
    if not path.is_file():
        return None
    import importlib.util

    spec = importlib.util.spec_from_file_location("chaos_engine_corpus_split_retrieve", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def graph_freshness_field(project: Path) -> dict[str, str]:
    """Never answer from an outdated graph silently (#6409): report fresh, stale or absent."""
    try:
        fresh, detail = runpy.run_path(
            str(Path(__file__).resolve().with_name("stores.py")), run_name="_chaos_engine_stores"
        )["graph_freshness"](project)
    except (OSError, KeyError, RuntimeError, ValueError) as error:
        return {"status": "unknown", "detail": str(error)}
    if fresh:
        return {"status": "fresh", "detail": detail}
    return {
        "status": detail.split(" ", 1)[0] if detail.startswith(("stale", "absent")) else "stale",
        "detail": detail,
        "refresh": "python3 .chaos-engine/tool.py stores refresh --if-stale",
    }


def _graphify_direct(root: Path, cleaned: str, mode: str, chosen: str) -> dict[str, Any] | None:
    """Local Graphify outcome, or None when the direct read cannot answer."""
    if chosen != "graphify":
        return None
    split = _corpus_split()
    if split is None:
        return None
    try:
        if mode == "impact":
            return split.impact_graphify_outcome(root, cleaned)
        return split.direct_graphify_outcome(root, cleaned)
    except (OSError, sqlite3.Error, RuntimeError, ValueError):
        return None


def _scope_for(project: Path, step: dict[str, Any]) -> dict[str, Any]:
    scope: dict[str, Any] = {
        "verb": step.get("verb"),
        "symbols": list(step.get("symbols") or []),
        "reason": step.get("reason"),
    }
    for key in ("depth", "budget", "results", "since"):
        if step.get(key):
            scope[key] = step[key]
    if step.get("store") == "mempalace":
        stores = _load_stores()
        wing = None
        if stores is not None and hasattr(stores, "read_wing"):
            try:
                wing = stores.read_wing(project)
            except OSError:
                wing = None
        if wing:
            scope["wing"] = wing
    return scope


def _run_rg(project: Path, query: str, reason: str) -> dict[str, Any]:
    matched = re.search(r'"([^"]+)"|\'([^\']+)\'', query)
    if matched:
        needle = matched.group(1) or matched.group(2)
    elif _EXACT_RE.search(query):
        needle = query
        for prefix in ("find the exact string ", "exact string "):
            if needle.casefold().startswith(prefix):
                needle = needle[len(prefix) :]
                break
    else:
        needle = query
    mindset = _mindset()
    if mindset is None or not hasattr(mindset, "run_rg"):
        return _miss_receipt("rg", query, "no-relevant-hits")
    try:
        completed = mindset.run_rg(
            ["rg", "-n", "--no-heading", "--glob", "!.git/**", needle],
            cwd=project,
        )
    except OSError as error:
        return {
            "store": "rg",
            "status": STATUS_DEGRADED,
            "reason": f"os-error:{type(error).__name__}",
            "query": query,
        }
    if completed.returncode == 1 or is_empty_result(completed.stdout or ""):
        return _miss_receipt("rg", query, "no-relevant-hits")
    if completed.returncode != 0:
        return {
            "store": "rg",
            "status": STATUS_DEGRADED,
            "reason": (completed.stderr or "nonzero-exit").strip().splitlines()[:1][0][:120]
            if (completed.stderr or "").strip()
            else "nonzero-exit",
            "query": query,
            "exitCode": completed.returncode,
        }
    hits: list[dict[str, Any]] = []
    for line in (completed.stdout or "").splitlines():
        found = re.match(r"(?P<path>[^:]+):(?P<line>\d+):", line)
        if not found:
            continue
        path = found.group("path")
        if path.startswith("./"):
            path = path[2:]
        hits.append({"path": path, "line": int(found.group("line")), "store": "rg", "route": reason})
        if len(hits) >= _HIT_LIMIT:
            break
    kept = _verify_hits(project, hits)
    if not kept:
        return _miss_receipt("rg", query, "no-relevant-hits")
    excerpt = _bounded_excerpt(completed.stdout or "", _EXCERPT_WITH_HITS)
    return {
        "store": "rg",
        "status": STATUS_USED,
        "reason": "hits",
        "query": query,
        "hits": kept,
        "excerpt": excerpt,
        "bytes": len(excerpt.encode("utf-8")),
    }


_DOC_STOP = frozenset(
    {"how", "does", "the", "work", "what", "when", "where", "why", "did", "for", "and", "a", "an", "to", "of"}
)


def _omit_duplicate_path_lines(body: str, hits: list) -> str:
    """Drop excerpt lines whose path is already a hit, so the receipt is not a second copy."""
    paths = {str(hit.get("path") or "") for hit in hits if isinstance(hit, dict)}
    paths.discard("")
    kept = []
    for line in body.splitlines():
        head = line.split(":", 1)[0].strip()
        if head in paths:
            continue
        kept.append(line)
    return "\n".join(kept)


def _docs_hit_limit() -> int:
    """Doc result count follows the token-budget mode (4, 8, or 12)."""
    return _token_budget()[1]


def _docs_answer(project: Path, query: str) -> dict[str, Any] | None:
    """Natural language can be answered from filed docs without a rare code token.

    ``OrderService?`` is still a rare token. A docs answer is verified against
    live files and capped by the token-budget result count.
    """
    if question_rare_tokens(query):
        return None
    stores = _load_stores()
    if stores is None:
        return None
    try:
        if subprocess.run is _REAL_RUN:
            path = stores.resolve_graph_out(project) / "documentation-pages.json"
        else:
            path = project / "graphify-out" / "documentation-pages.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, RuntimeError, ValueError):
        return None
    tokens = [
        token for token in re.findall(r"[A-Za-z0-9_]+", query.casefold())
        if token not in _DOC_STOP and len(token) > 2
    ]
    if not tokens:
        return None
    pages = payload.get("pages") if isinstance(payload, dict) else None
    hits: list[dict[str, Any]] = []
    for page in pages or []:
        if not isinstance(page, dict):
            continue
        if any(token in json.dumps(page).casefold() for token in tokens):
            headings = page.get("headings") or []
            hits.append({"path": str(page.get("path") or ""), "label": str(headings[0]) if headings else ""})
    kept = _verify_hits(project, hits)[: _docs_hit_limit()]
    if not kept or not kept[0].get("path"):
        return None
    return {
        "status": STATUS_USED,
        "reason": "docs",
        "hits": kept,
        "query": query,
        "excerpt": "",
        "bytes": 0,
    }


def _mempalace_fts_receipt(project: Path, query: str) -> dict[str, Any] | None:
    """Use the palace FTS index when it hits. A miss still launches the CLI."""
    if subprocess.run is not _REAL_RUN:
        return None
    stores = _load_stores()
    if stores is None:
        return None
    try:
        database = stores.resolve_palace(project) / "sqlite_exact.sqlite3"
    except (OSError, RuntimeError):
        return None
    if not database.is_file():
        return None
    try:
        relative = fts_source_hits(database, query, project)
    except (OSError, sqlite3.Error):
        return None
    if not relative:
        return None
    hits = [{"path": path} for path in relative[:_HIT_LIMIT]]
    return {
        "status": STATUS_USED,
        "reason": "hits",
        "hits": hits,
        "query": query,
        "excerpt": "",
        "bytes": 0,
    }


def _git_text(project: Path, *args: str) -> str:
    completed = subprocess.run(  # nosec B603 - fixed git argv, no shell.
        ["git", "-c", "core.quotepath=false", *args],
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _live_store_outcome(project: Path, query: str) -> dict[str, Any]:
    """Branch delta against main or master, plus a fixed-string grep of that delta."""
    base = ""
    for name in ("main", "master"):
        if _git_text(project, "rev-parse", "--verify", "--quiet", name):
            base = name
            break
    merge_base = _git_text(project, "merge-base", base, "HEAD") if base else ""
    lag = _git_text(project, "rev-list", "--count", f"HEAD..{base}") if base else "0"
    delta = _git_text(project, "diff", "--name-only", f"{base}...HEAD") if base else ""
    names = [line for line in delta.splitlines() if line.strip()]
    hits: list[dict[str, Any]] = []
    if names and query:
        completed = subprocess.run(  # nosec B603 - fixed git grep, no shell.
            ["git", "-c", "core.quotepath=false", "grep", "-F", "-n", query, "--", *names],
            cwd=project,
            capture_output=True,
            text=True,
            check=False,
        )
        for line in (completed.stdout or "").splitlines():
            found = re.match(r"(?P<path>.+?):(?P<line>\d+):", line)
            if not found:
                continue
            hits.append(
                {
                    "path": found.group("path"),
                    "line": int(found.group("line")),
                    "branchModified": True,
                }
            )
            if len(hits) >= _HIT_LIMIT:
                break
    return {
        "status": STATUS_USED if hits else STATUS_SKIPPED,
        "reason": "hits" if hits else "no-relevant-hits",
        "hits": hits,
        "query": query,
        "excerpt": "",
        "bytes": 0,
        "freshness": {
            "base": base,
            "mergeBase": merge_base,
            "baseLag": lag,
            "branchDelta": names,
        },
    }


def _execute_step(project: Path, query: str, step: dict[str, Any]) -> dict[str, Any]:
    store = str(step["store"])
    reason = str(step.get("reason") or "")
    if store == "rg":
        return _run_rg(project, query, reason)
    if store == "graphify" and step.get("verb") in {None, "query"}:
        docs = _docs_answer(project, query)
        if docs is not None:
            return docs
        if _skip_no_rare_before_store(store, query):
            return _miss_receipt(store, query, "no-rare-token")
    outcome = _run_store(project, store, query, _scope_for(project, step))
    if store == "graphify":
        outcome = _keep_store_path_or_skip_no_rare(store, query, outcome)
    hits = outcome.get("hits") if isinstance(outcome.get("hits"), list) else []
    if hits:
        kept = _verify_hits(project, hits)
        if not kept:
            return _miss_receipt(store, query, "no-relevant-hits")
        outcome = dict(outcome)
        outcome["hits"] = kept
        outcome["status"] = STATUS_USED
    return outcome


def _step(route: dict[str, Any], which: str) -> dict[str, Any] | None:
    if which == "primary":
        return {
            "store": route["primary"],
            "verb": route.get("verb"),
            "reason": route["reason"],
            "symbols": route.get("symbols") or [],
            "depth": route.get("depth"),
            "budget": route.get("budget"),
            "results": route.get("results"),
            "since": route.get("since"),
        }
    if not route.get("fallback"):
        return None
    return {
        "store": route["fallback"],
        "verb": route.get("fallbackVerb") or route.get("verb"),
        "reason": route["reason"],
        "symbols": route.get("symbols") or [],
        "depth": route.get("depth"),
        "budget": route.get("budget"),
        "results": route.get("results") if route["fallback"] == "mempalace" else None,
        "since": route.get("since") if route["fallback"] == "mempalace" else None,
    }


def _account(root: Path, store: str, query: str, receipt: dict[str, Any], account: bool) -> None:
    mindset = _mindset()
    if (
        account
        and mindset is not None
        and receipt.get("status") in {STATUS_USED, STATUS_SKIPPED}
    ):
        hits = receipt.get("hits") if isinstance(receipt.get("hits"), list) else []
        paths = [str(hit.get("path")) for hit in hits if isinstance(hit, dict) and hit.get("path")]
        try:
            mindset.record_retrieve_usage(
                root,
                store=store,
                hit_count=len(hits),
                byte_size=int(receipt.get("bytes") or 0),
                paths=paths,
            )
            _note_cited_usage(root, mindset, paths)
        except (OSError, TypeError, ValueError):
            pass
    _commit_retrieve_receipt(root, store, query, receipt)


def _retrieve_routed(
    cleaned: str,
    root: Path,
    *,
    dry_run: bool,
    recheck: bool,
    account: bool,
) -> dict[str, Any]:
    route = classify_scope(cleaned)
    primary = _step(route, "primary")
    fallback = _step(route, "fallback")
    assert primary is not None
    receipt: dict[str, Any] = {
        "schemaVersion": 1,
        "kind": "retrieve-orchestrator",
        "store": primary["store"],
        "query": cleaned,
        "policy": POLICY_ON_MISS if fallback else "one-store-one-attempt",
        "route": {
            "reason": route["reason"],
            "primary": primary["store"],
            "fallback": None if fallback is None else fallback["store"],
        },
    }
    if dry_run:
        receipt["status"] = STATUS_SKIPPED
        receipt["reason"] = "dry-run"
        return receipt
    recorded = _recorded_mismatch(root, str(primary["store"]), recheck)
    if recorded is not None:
        receipt.update(recorded)
        return receipt
    outcome = _execute_step(root, cleaned, primary)
    groups: list[list[dict[str, Any]]] = []
    excerpts: list[str] = []
    if outcome.get("status") == STATUS_DEGRADED:
        receipt.update(outcome)
        receipt["route"] = receipt["route"]
        return receipt
    if not _is_miss(outcome):
        groups.append(_tag_hits(outcome.get("hits") or [], str(primary["store"]), route["reason"]))
        excerpts.append(str(outcome.get("excerpt") or ""))
    elif fallback is not None:
        second = _execute_step(root, cleaned, fallback)
        if second.get("status") == STATUS_DEGRADED:
            receipt.update(second)
            receipt["store"] = fallback["store"]
            return receipt
        if _is_miss(second):
            receipt.update(second)
            receipt["store"] = fallback["store"]
            if fallback["store"] == "graphify" or primary["store"] == "graphify":
                receipt["freshness"] = graph_freshness_field(root)
            _account(root, str(fallback["store"]), cleaned, receipt, account)
            return receipt
        groups.append(_tag_hits(second.get("hits") or [], str(fallback["store"]), route["reason"]))
        excerpts.append(str(second.get("excerpt") or ""))
        receipt["store"] = fallback["store"]
    else:
        receipt.update(outcome)
        _account(root, str(primary["store"]), cleaned, receipt, account)
        return receipt
    fused = reciprocal_rank_fusion(groups)
    if not fused:
        missed = _miss_receipt(str(receipt["store"]), cleaned, "no-relevant-hits")
        receipt.update(missed)
        _account(root, str(receipt["store"]), cleaned, receipt, account)
        return receipt
    excerpt = _bounded_excerpt("\n".join(part for part in excerpts if part), _EXCERPT_WITH_HITS)
    if not excerpt:
        excerpt = _bounded_excerpt(
            "\n".join(f"{hit['path']}:{hit.get('line', '')}" for hit in fused),
            _EXCERPT_WITH_HITS,
        )
    receipt.update(
        {
            "status": STATUS_USED,
            "reason": "hits",
            "hits": fused,
            "excerpt": excerpt,
            "bytes": len(excerpt.encode("utf-8")),
        }
    )
    if receipt["store"] == "graphify" or primary["store"] == "graphify":
        receipt["freshness"] = graph_freshness_field(root)
    _account(root, str(receipt["store"]), cleaned, receipt, account)
    return receipt


def retrieve(
    query: str,
    *,
    store: str | None = None,
    project: Path | None = None,
    dry_run: bool = False,
    recheck: bool = False,
    host: str | None = None,
    mode: str = "search",
    account: bool = True,
) -> dict[str, Any]:
    cleaned = " ".join(str(query).split())
    if not cleaned:
        raise ValueError("query required")
    if len(cleaned) > QUERY_MAX:
        raise ValueError(f"query exceeds {QUERY_MAX} characters")
    root = project_root(project)
    if store is None and mode != "impact":
        return _retrieve_routed(cleaned, root, dry_run=dry_run, recheck=recheck, account=account)
    chosen = "graphify" if mode == "impact" and store in {None, "graphify"} else pick_store(cleaned, store)
    receipt: dict[str, Any] = {
        "schemaVersion": 1,
        "kind": "retrieve-orchestrator",
        "store": chosen,
        "query": cleaned,
        "policy": "one-store-one-attempt",
        "route": {
            "reason": "impact-mode" if mode == "impact" and store in {None, "graphify"} else "explicit-store"
        },
    }
    if dry_run:
        receipt["status"] = STATUS_SKIPPED
        receipt["reason"] = "dry-run"
        return receipt
    recorded = _recorded_mismatch(root, chosen, recheck)
    if recorded is not None:
        receipt.update(recorded)
        return receipt
    direct = _graphify_direct(root, cleaned, mode, chosen)
    docs = _docs_answer(root, cleaned) if chosen == "graphify" else None
    if chosen == "live":
        outcome = _live_store_outcome(root, cleaned)
    elif mode == "impact" and direct is not None:
        # A contract flag is not a Graphify walk seed. Keep the local impact
        # ranking instead of the no-rare-token skip (#7824).
        outcome = direct
    elif docs is not None:
        outcome = docs
    elif _skip_no_rare_before_store(chosen, cleaned):
        outcome = {
            "status": STATUS_SKIPPED,
            "reason": "no-rare-token",
            "hits": [],
            "query": cleaned,
            "excerpt": "",
            "bytes": 0,
        }
    elif direct is not None:
        outcome = direct
    else:
        outcome = _keep_store_path_or_skip_no_rare(
            chosen, cleaned, _run_store(root, chosen, cleaned)
        )
    receipt.update(outcome)
    mindset = _mindset()
    if (
        account
        and mindset is not None
        and receipt.get("status") in {STATUS_USED, STATUS_SKIPPED}
    ):
        hits = receipt.get("hits") if isinstance(receipt.get("hits"), list) else []
        paths = [str(hit.get("path")) for hit in hits if isinstance(hit, dict) and hit.get("path")]
        try:
            mindset.record_retrieve_usage(
                root,
                store=chosen,
                hit_count=len(hits),
                byte_size=int(receipt.get("bytes") or 0),
                paths=paths,
            )
            _note_cited_usage(root, mindset, paths)
        except (OSError, TypeError, ValueError):
            # Hit accounting is best-effort and must not fail the retrieve.
            pass
    if chosen == "graphify" and subprocess.run is _REAL_RUN:
        receipt["freshness"] = graph_freshness_field(root)
    _commit_retrieve_receipt(root, chosen, cleaned, receipt)
    return receipt



def heuristics_retrieve(top: int = 3, project: Path | None = None) -> dict[str, Any]:
    """Once-per-task ERL heuristic retrieve (#5656); never SessionStart prose."""
    path = Path(__file__).resolve().with_name("heuristics.py")
    if not path.is_file():
        return {
            "schemaVersion": 1,
            "kind": "heuristics-retrieve",
            "status": STATUS_DEGRADED,
            "reason": "heuristics.py missing",
            "items": [],
        }
    import importlib.util as _ilu

    spec = _ilu.spec_from_file_location("chaos_engine_heuristics_retrieve", path)
    if spec is None or spec.loader is None:
        return {
            "schemaVersion": 1,
            "kind": "heuristics-retrieve",
            "status": STATUS_DEGRADED,
            "reason": "heuristics loader failed",
            "items": [],
        }
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    items = mod.retrieve_top(top, project)
    return {
        "schemaVersion": 1,
        "kind": "heuristics-retrieve",
        "status": STATUS_USED if items else STATUS_SKIPPED,
        "store": "heuristics",
        "top": top,
        "items": items,
        "policy": "once-per-task",
    }


_QUERY_FORM = 'tool.py retrieve --store graphify "<query>"'
_OPTION_VALUES = frozenset({"--store", "--project", "--host", "--mode", "--top", "--query"})


def _positional_indexes(argv: list[str]) -> list[int]:
    indexes: list[int] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        if token in _OPTION_VALUES:
            index += 2
            continue
        if token.startswith("-"):
            index += 1
            continue
        indexes.append(index)
        index += 1
    return indexes


def _flag_value(argv: list[str], name: str) -> str | None:
    prefix = f"{name}="
    for index, token in enumerate(argv):
        if token == name and index + 1 < len(argv):
            return argv[index + 1]
        if token.startswith(prefix):
            return token[len(prefix) :]
    return None


def _promote_leading_store(argv: list[str]) -> list[str]:
    """A store name plus a following query is ``--store``. A lone store name stays the query."""
    indexes = _positional_indexes(argv)
    if (
        len(indexes) < 2
        or argv[indexes[0]] not in STORES
        or _flag_value(argv, "--store") is not None
    ):
        return argv
    store = argv[indexes[0]]
    query = " ".join(argv[index] for index in indexes[1:])
    drop = set(indexes)
    kept = [token for index, token in enumerate(argv) if index not in drop]
    kept.extend(["--store", store, query])
    return kept


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    if raw and raw[0] == "heuristics":
        parser = argparse.ArgumentParser(description="ERL heuristic retrieve once per task")
        parser.add_argument("--top", type=int, default=3)
        parser.add_argument("--project", type=Path, default=None)
        args = parser.parse_args(raw[1:])
        try:
            receipt = heuristics_retrieve(args.top, args.project)
        except ValueError as error:
            print(str(error), file=sys.stderr)
            return 2
        print(json.dumps(receipt, sort_keys=True))
        return 0
    raw = _promote_leading_store(raw)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", nargs="?", default="")
    parser.add_argument(
        "--query",
        dest="query_flag",
        default=None,
        help="alias of the positional query",
    )
    parser.add_argument("--store", default=None)
    parser.add_argument("--project", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--host", default=os.environ.get("CHAOS_ENGINE_HOST"))
    parser.add_argument("--mode", choices=RETRIEVE_MODES, default="search")
    parser.add_argument(
        "--recheck", action="store_true", help="re-probe MemPalace after a backend repair"
    )
    args = parser.parse_args(raw)
    if args.query_flag is not None and args.query and args.query != args.query_flag:
        print(_QUERY_FORM, file=sys.stderr)
        return 2
    query = args.query_flag if args.query_flag is not None else args.query
    try:
        receipt = retrieve(
            query,
            store=args.store,
            project=args.project,
            dry_run=args.dry_run,
            recheck=args.recheck,
            host=args.host,
            mode=args.mode,
        )
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


def _token_budget() -> tuple[int, int]:
    raw = os.environ.get("CHAOS_ENGINE_TOKEN_BUDGET", "balanced").strip().casefold().replace("_", "-")
    raw = {"lean": "ultra-lean", "ultra": "ultra-lean", "default": "balanced"}.get(raw, raw)
    return {"ultra-lean": (800, 4), "balanced": (1500, 8), "deep": (2500, 12)}.get(raw, (1500, 8))


def _retrieve_env(project: Path) -> dict[str, str]:
    """Config dir follows the git common dir. Reading `.git` text never spawns git."""
    env = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "CHAOS_ENGINE_RETRIEVE": "1",
        "GRAPHIFY_QUERY_LOG_DISABLE": "1",
    }
    common = _git_common_without_process(project)
    config = (common / "chaos-engine" / "mempalace-config") if common else (project / "chaos-engine" / "mempalace-config")
    env["MEMPALACE_CONFIG_DIR"] = str(config)
    return env


def _repository_source(source: str, anchor: Path) -> str | None:
    """Repo-relative path. A store-snapshot or other checkout maps back; a stranger path does not."""
    raw = str(source or "").replace("\\", "/").strip()
    marker = "/store-snapshot/"
    if marker in raw:
        raw = raw.split(marker, 1)[1]
    if not raw or any(part == ".." for part in Path(raw).parts):
        return None
    while raw.startswith("./"):
        raw = raw[2:]
    path = Path(raw)
    if not path.is_absolute():
        return raw or None
    try:
        return path.resolve().relative_to(anchor.resolve()).as_posix()
    except (ValueError, OSError):
        stores = _load_stores()
        if stores is None:
            return None
        try:
            relative = stores.repository_relative(str(path), stores.registered_roots(anchor))
        except (OSError, RuntimeError, ValueError, TypeError):
            return None
        if not isinstance(relative, str) or not relative or relative.startswith(".git/"):
            return None
        if "/store-snapshot/" in relative.replace("\\", "/"):
            return None
        return relative


def fts_source_hits(database: Path, query: str, root: Path) -> list[str]:
    """Repo-relative source paths from the palace FTS index. Missing index is a miss."""
    uri = f"{Path(database).resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        try:
            rows = connection.execute(
                """
                SELECT json_extract(d.metadata_json, '$.source_file')
                FROM documents AS d
                JOIN docs_fts ON docs_fts.doc_id = d.id
                WHERE docs_fts MATCH ?
                ORDER BY d.id
                """,
                (query,),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        found: list[str] = []
        anchor = root.resolve()
        for (source,) in rows:
            relative = _repository_source(str(source or ""), anchor)
            if relative and relative not in found:
                found.append(relative)
        return found
    finally:
        connection.close()
