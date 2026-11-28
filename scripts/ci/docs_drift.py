#!/usr/bin/env python3
"""Fail when a scanned env read has no registry or catalog entry.

Stdlib only. Silent on success. ``gate_findings`` returns one-line fix-next
strings. An empty ``changed`` list is not a diff. A diff that touches no
scanned file is skipped.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

NAME_RE = re.compile(r"^(?:CHAOS_ENGINE_|CHAOS_|CE_)[A-Z0-9_]+$")
_SHELL_RE = re.compile(
    r"\$\{?((?:CHAOS_ENGINE_|CHAOS_|CE_)[A-Z0-9_]+)"
)
_PS_RE = re.compile(
    r"\$[Ee]nv:((?:CHAOS_ENGINE_|CHAOS_|CE_)[A-Z0-9_]+)"
)
_JS_RE = re.compile(
    r"process\.env\.((?:CHAOS_ENGINE_|CHAOS_|CE_)[A-Z0-9_]+)"
)
_ENV_RECEIVERS = frozenset({"environ", "env", "_env", "environment"})
_SKIP_PARTS = frozenset({
    ".git",
    ".chaos-engine",
    ".chaos-engine-state",
    "__pycache__",
    "node_modules",
    "vendor",
    "tests",
})
_CODE_SUFFIXES = (".py", ".sh", ".ps1", ".js", ".mjs")


def _rel(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _skipped(rel: str) -> bool:
    if rel.startswith("docs/research/"):
        return True
    return any(part in _SKIP_PARTS for part in rel.split("/"))


def _interesting(rel: str) -> bool:
    """True when a diff path should run the full scan."""
    if _skipped(rel):
        return False
    if rel.endswith(_CODE_SUFFIXES):
        return True
    if rel in {
        "runtime/env_registry.json",
        "runtime/status_codes.json",
        "runtime/install_options.py",
        "references/keywords.json",
    }:
        return True
    return rel.startswith(("runtime/env_registry.d/", "references/keywords.d/"))


def _receiver_ok(node: ast.AST) -> bool:
    if isinstance(node, ast.Name) and node.id in _ENV_RECEIVERS:
        return True
    return isinstance(node, ast.Attribute) and node.attr in _ENV_RECEIVERS


def _add(found: dict[str, set[tuple[str, int]]], name: str, rel: str, line: int) -> None:
    if NAME_RE.fullmatch(name):
        found.setdefault(name, set()).add((rel, line))


class _EnvVisitor(ast.NodeVisitor):
    def __init__(self, rel: str, found: dict[str, set[tuple[str, int]]]) -> None:
        self.rel = rel
        self.found = found

    def _seq(self, node: ast.AST) -> None:
        if not isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            return
        for elt in node.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                _add(self.found, elt.value, self.rel, elt.lineno)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "get" and _receiver_ok(func.value):
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                _add(self.found, node.args[0].value, self.rel, node.args[0].lineno)
        elif isinstance(func, ast.Name) and func.id == "getenv":
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                _add(self.found, node.args[0].value, self.rel, node.args[0].lineno)
        elif isinstance(func, ast.Attribute) and func.attr == "getenv":
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                _add(self.found, node.args[0].value, self.rel, node.args[0].lineno)
        fname = ""
        if isinstance(func, ast.Name):
            fname = func.id
        elif isinstance(func, ast.Attribute):
            fname = func.attr
        if "override" in fname.lower() or fname.endswith("_env_set"):
            for arg in node.args:
                self._seq(arg)
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if _receiver_ok(node.value) and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
            _add(self.found, node.slice.value, self.rel, node.slice.lineno)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if any("ENV" in name for name in targets):
            self._pull_value(node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name) and "ENV" in node.target.id and node.value is not None:
            self._pull_value(node.value)
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        uses_env = False
        for child in ast.walk(node):
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                if child.func.attr in {"get", "getenv"} and _receiver_ok(child.func.value):
                    uses_env = True
            elif isinstance(child, ast.Subscript) and _receiver_ok(child.value):
                uses_env = True
        if uses_env:
            self._seq(node.iter)
        self.generic_visit(node)

    def _pull_value(self, node: ast.AST) -> None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            _add(self.found, node.value, self.rel, node.lineno)
        else:
            self._seq(node)

def catalog_env_names(root: Path) -> set[str]:
    """Env names declared on installer catalog rows. Missing file means none."""
    path = root / "runtime" / "install_options.py"
    if not path.is_file():
        return set()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.keyword) or node.arg != "env":
            continue
        if not isinstance(node.value, (ast.Tuple, ast.List)):
            continue
        for elt in node.value.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                names.add(elt.value)
    return names


def load_env_registry(root: Path) -> dict[str, dict]:
    """Merge ``runtime/env_registry.json`` with ``runtime/env_registry.d/*.json``."""
    path = root / "runtime" / "env_registry.json"
    entries: dict[str, dict] = {}
    if path.is_file():
        document = json.loads(path.read_text(encoding="utf-8"))
        for row in document.get("entries", []):
            entries[str(row["name"])] = row
    folder = root / "runtime" / "env_registry.d"
    if folder.is_dir():
        for extra_path in sorted(folder.glob("*.json")):
            extra = json.loads(extra_path.read_text(encoding="utf-8"))
            rows = extra.get("entries", []) if isinstance(extra, dict) else extra
            for row in rows:
                entries[str(row["name"])] = row
    return entries


def scan_env_reads(root: Path) -> dict[str, list[str]]:
    """Map each env name to sorted ``path:line`` read sites."""
    root = Path(root)
    found: dict[str, set[tuple[str, int]]] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = _rel(path, root)
        if _skipped(rel) or not rel.endswith(_CODE_SUFFIXES):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        if rel.endswith(".py"):
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue
            _EnvVisitor(rel, found).visit(tree)
            for match in _JS_RE.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                _add(found, match.group(1), rel, line)
            continue
        for match in _SHELL_RE.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            _add(found, match.group(1), rel, line)
        for match in _PS_RE.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            _add(found, match.group(1), rel, line)
        for match in _JS_RE.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            _add(found, match.group(1), rel, line)
    return {
        name: [f"{rel}:{line}" for rel, line in sorted(sites, key=lambda item: (item[0], item[1]))]
        for name, sites in sorted(found.items())
    }


def _fix_next(name: str, site: str) -> str:
    return (
        f"{name} read at {site} has no entry in runtime/env_registry.json; "
        "add it and run scripts/docs/gen_reference.py"
    )


def gate_findings(root: Path | str, changed: list[str] | None) -> list[str]:
    """Return one-line fix-next findings. Empty ``changed`` skips the scan."""
    root = Path(root)
    if changed is not None:
        normalized = [item.replace("\\", "/").removeprefix("./") for item in changed if item]
        if not normalized or not any(_interesting(item) for item in normalized):
            return []
    documented = set(load_env_registry(root))
    documented.update(catalog_env_names(root))
    findings: list[str] = []
    for name, sites in scan_env_reads(root).items():
        if name in documented or not sites:
            continue
        findings.append(_fix_next(name, sites[0]))
    return findings


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    root = Path(args[0]) if args else Path.cwd()
    findings = gate_findings(root, None)
    for item in findings:
        print(item)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
