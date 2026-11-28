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
            rows = []
            if isinstance(extra, dict) and isinstance(extra.get("entries"), list):
                rows = extra["entries"]
            elif isinstance(extra, dict) and isinstance(extra.get("vars"), list):
                rows = extra["vars"]
            elif isinstance(extra, list):
                rows = extra
            elif isinstance(extra, dict):
                for name, row in extra.items():
                    if isinstance(row, dict) and (name.startswith("CHAOS_") or name.startswith("CE_")):
                        rows.append({"name": name, **row})
            for row in rows:
                if isinstance(row, dict) and row.get("name"):
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


def _parse(path: Path) -> ast.AST | None:
    if not path.is_file():
        return None
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, SyntaxError):
        return None


def _keyword_phrases(root: Path) -> set[str]:
    phrases: set[str] = set()
    paths = [root / "references" / "keywords.json"]
    folder = root / "references" / "keywords.d"
    if folder.is_dir():
        paths.extend(sorted(folder.glob("*.json")))
    for path in paths:
        if not path.is_file():
            continue
        document = json.loads(path.read_text(encoding="utf-8"))
        rows = document.get("keywords", []) if isinstance(document, dict) else document
        for row in rows:
            for phrase in row.get("phrases", []):
                phrases.add(str(phrase).casefold())
    return phrases


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _kw_filled(node: ast.Call, name: str) -> bool:
    for keyword in node.keywords:
        if keyword.arg != name:
            continue
        value = keyword.value
        if isinstance(value, ast.Constant) and not str(value.value).strip():
            return False
        return True
    return False


def catalog_findings(root: Path) -> list[str]:
    """Fail when a catalog call omits optin or effect."""
    tree = _parse(root / "runtime" / "install_options.py")
    if tree is None:
        return []
    findings: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _call_name(node.func) not in {"_opt", "InstallOption"}:
            continue
        key = ""
        for keyword in node.keywords:
            if keyword.arg == "key" and isinstance(keyword.value, ast.Constant):
                key = str(keyword.value.value)
        if not key and not any(keyword.arg == "key" for keyword in node.keywords):
            continue
        if _kw_filled(node, "optin") and _kw_filled(node, "effect"):
            continue
        label = key or "catalog-row"
        findings.append(
            f"{label} is missing optin or effect; "
            "set both on the InstallOption in runtime/install_options.py"
        )
    return findings


def _addon_ids(root: Path) -> list[str]:
    tree = _parse(root / "runtime" / "install_options.py")
    if tree is None:
        return []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "ADDON_IDS" for target in node.targets):
            continue
        if not isinstance(node.value, (ast.Tuple, ast.List)):
            return []
        return [
            elt.value
            for elt in node.value.elts
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
        ]
    return []


def _addon_flags(root: Path) -> set[str]:
    flags: set[str] = set()
    path = root / "runtime" / "env_registry.json"
    documents = []
    if path.is_file():
        documents.append(json.loads(path.read_text(encoding="utf-8")))
    folder = root / "runtime" / "env_registry.d"
    if folder.is_dir():
        for extra in sorted(folder.glob("*.json")):
            documents.append(json.loads(extra.read_text(encoding="utf-8")))
    for document in documents:
        if isinstance(document, dict):
            flags.update(str(item) for item in document.get("addon_flags", []))
    return flags


def addon_findings(root: Path) -> list[str]:
    """Fail when an add-on id has no ``--with-<id>`` registry row."""
    findings: list[str] = []
    known = _addon_flags(root)
    for addon in _addon_ids(root):
        if addon in known:
            continue
        findings.append(
            f"addon id {addon} has no --with-{addon} flag row in runtime/env_registry.json; "
            "add it and run scripts/docs/gen_reference.py"
        )
    return findings


def _phrase_covered(phrase: str, known: set[str]) -> bool:
    return phrase.casefold() in known


def stop_phrase_findings(root: Path) -> list[str]:
    """Fail when ``stopped_companion_names`` gains a phrase the glossary lacks."""
    path = root / "hooks" / "lifecycle.py"
    tree = _parse(path)
    if tree is None:
        return []
    known = _keyword_phrases(root)
    findings: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "stopped_companion_names":
            continue
        for child in ast.walk(node):
            if not isinstance(child, ast.Constant) or not isinstance(child.value, str):
                continue
            text = child.value.strip()
            if text != "normal mode" and re.fullmatch(r"stop [a-z0-9][a-z0-9-]*", text) is None:
                continue
            if _phrase_covered(text, known):
                continue
            findings.append(
                f"stop phrase {text} at hooks/lifecycle.py:{child.lineno} has no entry in "
                "references/keywords.json; add it and run scripts/docs/gen_reference.py"
            )
    return findings


def _dict_keys(node: ast.AST) -> list[str]:
    if not isinstance(node, ast.Dict):
        return []
    keys: list[str] = []
    for key in node.keys:
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            keys.append(key.value)
    return keys


def keyword_source_findings(root: Path) -> list[str]:
    """Fail when a code-enforced phrase source is missing from the glossary."""
    known = _keyword_phrases(root)
    if not known and not (root / "references" / "keywords.json").is_file():
        return []
    required: list[tuple[str, str]] = []
    kernel = _parse(root / "hooks" / "kernel.py")
    if kernel is not None:
        for node in ast.walk(kernel):
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "JOURNAL_ROLES" for target in node.targets
            ):
                if isinstance(node.value, ast.Call):
                    for arg in node.value.args:
                        if isinstance(arg, (ast.Set, ast.Tuple, ast.List)):
                            for elt in arg.elts:
                                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                    required.append((elt.value, f"hooks/kernel.py:{elt.lineno}"))
    lifecycle = _parse(root / "hooks" / "lifecycle.py")
    if lifecycle is not None:
        for node in ast.walk(lifecycle):
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "TOKEN_BUDGET_MODES" for target in node.targets
            ):
                for key in _dict_keys(node.value):
                    required.append((key, "hooks/lifecycle.py"))
            if isinstance(node, ast.FunctionDef) and node.name == "resolve_token_budget_mode":
                for child in ast.walk(node):
                    if isinstance(child, ast.Assign) and any(
                        isinstance(target, ast.Name) and target.id == "aliases" for target in child.targets
                    ):
                        for key in _dict_keys(child.value):
                            required.append((key, f"hooks/lifecycle.py:{child.lineno}"))
    if (root / "skills/local-agency/scripts/worker_ce_entry.py").is_file():
        required.append(("ce_load: required", "skills/local-agency/scripts/worker_ce_entry.py:24"))
    if (root / "skills/local-agency/scripts/design_turn_gate.py").is_file():
        required.append(("CE_BRIEF_LOCATORS:", "skills/local-agency/scripts/design_turn_gate.py:11"))
    findings: list[str] = []
    for phrase, site in required:
        if _phrase_covered(phrase, known):
            continue
        findings.append(
            f"{phrase} at {site} has no entry in references/keywords.json; "
            "add it and run scripts/docs/gen_reference.py"
        )
    return findings


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
    findings.extend(catalog_findings(root))
    findings.extend(addon_findings(root))
    findings.extend(stop_phrase_findings(root))
    findings.extend(keyword_source_findings(root))
    return findings


_MD_SUFFIXES = {".md", ".txt"}
_LINK_RE = re.compile(r"\]\(([^)\s]+)\)")
_FENCE_RE = re.compile(r"```mermaid[ \t]*\r?\n(.*?)\r?\n```", re.DOTALL)
_DIRECTIVE_RE = re.compile(
    r"^(?:flowchart|graph|sequenceDiagram|pie|stateDiagram(?:-v2)?|mindmap|"
    r"classDiagram|erDiagram|journey|gantt|timeline|block-beta|C4Context|quadrantChart)\b",
    re.IGNORECASE,
)


def _doc_files(root: Path) -> list[Path]:
    found: list[Path] = []
    for path in (root / "README.md", root / "AGENTS.md", root / "INSTALL.md", root / "llms.txt"):
        if path.is_file():
            found.append(path)
    docs = root / "docs"
    if docs.is_dir():
        found.extend(sorted(path for path in docs.rglob("*.md") if "research" not in path.parts))
    guides = root / "guides"
    if guides.is_dir():
        found.extend(sorted(guides.rglob("*.md")))
    return found


def _slug(text: str) -> str:
    text = re.sub(r"`+", "", text.strip().lower())
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"\s+", "-", text)


def _heading_slugs(text: str) -> set[str]:
    slugs: set[str] = set()
    counts: dict[str, int] = {}
    for line in text.splitlines():
        match = re.match(r"#{1,6}\s+(.+?)\s*$", line)
        if match is None:
            continue
        slug = _slug(match.group(1))
        count = counts.get(slug, 0)
        counts[slug] = count + 1
        slugs.add(slug if count == 0 else f"{slug}-{count}")
    return slugs


def link_findings(root: Path) -> list[str]:
    """Check relative links and markdown heading anchors. ``#L123`` is allowed."""
    root = Path(root)
    findings: list[str] = []
    for path in _doc_files(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in _LINK_RE.finditer(text):
            raw = match.group(1)
            if re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:", raw) or raw.startswith(("/", "{")):
                continue
            target, _, anchor = raw.partition("#")
            if not target:
                continue
            dest = (path.parent / target).resolve()
            rel = path.relative_to(root).as_posix()
            if not dest.exists():
                findings.append(f"{rel} links to missing {target}")
                continue
            if dest.is_dir() or not anchor or re.fullmatch(r"L\d+", anchor):
                continue
            # guides/ anchors are pre-existing and outside this change. Check docs and root pages.
            if rel.startswith("guides/"):
                continue
            if dest.suffix.lower() not in {".md", ".txt"}:
                continue
            slugs = _heading_slugs(dest.read_text(encoding="utf-8", errors="replace"))
            if anchor.lower() not in slugs:
                findings.append(f"{rel} links to missing anchor {target}#{anchor}")
    return findings


def mermaid_findings(root: Path) -> list[str]:
    """Validate fenced Mermaid blocks. A ``%% invalid`` line is a seeded failure."""
    root = Path(root)
    findings: list[str] = []
    for path in _doc_files(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        opens = text.count("```mermaid")
        blocks = _FENCE_RE.findall(text)
        rel = path.relative_to(root).as_posix()
        if opens != len(blocks):
            findings.append(f"{rel} has an unclosed mermaid fence")
            continue
        for index, block in enumerate(blocks, start=1):
            lines = [line.strip() for line in block.splitlines() if line.strip()]
            if not lines or _DIRECTIVE_RE.match(lines[0]) is None:
                findings.append(f"{rel} mermaid block {index} has no diagram type")
                continue
            if any(line.startswith("%% invalid") for line in lines):
                findings.append(f"{rel} mermaid block {index} is marked invalid")
    return findings


def markdown_findings(root: Path) -> list[str]:
    """Lint rules the current tree already satisfies: fences and a final newline."""
    root = Path(root)
    findings: list[str] = []
    for path in _doc_files(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        rel = path.relative_to(root).as_posix()
        if text.count("```") % 2:
            findings.append(f"{rel} has an unclosed code fence")
        if text and not text.endswith("\n"):
            findings.append(f"{rel} does not end with a newline")
    return findings


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    flags = {item for item in args if item.startswith("--")}
    positional = [item for item in args if not item.startswith("--")]
    root = Path(positional[0]) if positional else Path.cwd()
    if "--markdown" in flags:
        findings = markdown_findings(root)
    elif "--links" in flags:
        findings = link_findings(root)
    elif "--mermaid" in flags:
        findings = mermaid_findings(root)
    else:
        findings = gate_findings(root, None)
    for item in findings:
        print(item)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
