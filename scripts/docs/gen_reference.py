#!/usr/bin/env python3
"""Generate settings, keyword, and agent reference pages from registries.

Stdlib only. ``--check`` compares the committed pages and exits 1 with one
line when they drift. The agent page has no Mermaid and no images.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.harness_index import ROLES, ROUTES  # noqa: E402
from runtime.install_options import CATALOG  # noqa: E402

SETTINGS_MD = "docs/reference/settings.md"
KEYWORDS_MD = "docs/reference/keywords.md"
AGENT_MD = "docs/agents/reference.md"
LLMS = "llms.txt"
AGENT_LIMIT = 32 * 1024

_GROUPS = (
    ("Phrases you can say", {"owner-phrase"}),
    ("Roles and workflows", {"role", "workflow"}),
    ("Modes", {"mode"}),
    ("Markers and tokens agents write", {"brief-marker", "receipt-token", "pr-marker"}),
    ("Status words", {"status-token"}),
    ("Principles and rituals", {"principle", "ritual"}),
)


def _cell(value: object) -> str:
    return " ".join(str(value).replace("|", "\\|").replace("\n", " ").split())


def _default(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value in ((), [], ""):
        return "[]" if value != "" else ""
    return str(value)


def _optin(kind: str, default: object) -> str:
    if kind == "bool":
        return "opt-out" if default else "opt-in"
    return "value"


def _flags(row: object) -> str:
    flags = tuple(getattr(row, "flags", ())) + tuple(getattr(row, "enable_flags", ()))
    return ", ".join(flags)


def _load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_env_entries(root: Path) -> list[dict]:
    document = _load_json(root / "runtime" / "env_registry.json")
    by_name = {str(row["name"]): row for row in document.get("entries", [])}
    folder = root / "runtime" / "env_registry.d"
    if folder.is_dir():
        for path in sorted(folder.glob("*.json")):
            extra = json.loads(path.read_text(encoding="utf-8"))
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
                    by_name[str(row["name"])] = row
    return [by_name[name] for name in sorted(by_name)]


def load_keywords(root: Path) -> list[dict]:
    document = _load_json(root / "references" / "keywords.json")
    by_id = {str(row["id"]): row for row in document.get("keywords", [])}
    folder = root / "references" / "keywords.d"
    if folder.is_dir():
        for path in sorted(folder.glob("*.json")):
            extra = json.loads(path.read_text(encoding="utf-8"))
            rows = extra.get("keywords", []) if isinstance(extra, dict) else extra
            for row in rows:
                by_id[str(row["id"])] = row
    return [by_id[key] for key in sorted(by_id)]


def load_status_codes(root: Path) -> list[dict]:
    document = _load_json(root / "runtime" / "status_codes.json")
    rows = list(document.get("codes", []))
    return sorted(rows, key=lambda row: str(row.get("code", "")))


def _catalog_lines(root: Path) -> dict[str, int]:
    path = root / "runtime" / "install_options.py"
    lines: dict[str, int] = {}
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.keyword) or node.arg != "key":
            continue
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            lines[node.value.value] = node.lineno
    return lines


def _link(from_rel: str, target: str, anchor: str = "") -> str:
    rel = Path(os.path.relpath(target, Path(from_rel).parent)).as_posix()
    if anchor:
        if not anchor.startswith("#"):
            anchor = "#" + anchor
        return f"{rel}{anchor}"
    return rel


def _site_link(from_rel: str, site: str) -> str:
    if ":" in site and not site.startswith("http"):
        target, _, line = site.rpartition(":")
        if line.isdigit():
            return _link(from_rel, target, f"L{line}")
    return _link(from_rel, site, "L1")


def _md_link(from_rel: str, target: str) -> str:
    if "#" in target:
        path, _, anchor = target.partition("#")
        return _link(from_rel, path, anchor)
    if ":" in Path(target).name:
        return _site_link(from_rel, target)
    return _link(from_rel, target, "L1")


def _own(from_rel: str, targets: list[str]) -> str:
    if not targets:
        return ""
    href = _md_link(from_rel, targets[0])
    return f"[owner]({href})"


def _version(root: Path) -> str:
    return (root / "VERSION").read_text(encoding="utf-8").strip()


def _generator_sha() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]


def _clip(text: str, limit: int = 48) -> str:
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def render_settings(root: Path) -> str:
    lines_by_key = _catalog_lines(root)
    env_rows = load_env_entries(root)
    out: list[str] = [
        "# Settings reference",
        "",
        f"Generated from the installer catalog and `runtime/env_registry.json`. Version {_version(root)}.",
        "Do not edit this page by hand. Run `python3 scripts/docs/gen_reference.py`.",
        "",
        "## Opt-in and opt-out switches",
        "",
        "Bool catalog rows and env rows marked opt-in or opt-out. `opt-out` means the default is on.",
        "",
        "| Name | Opt | Default | Flag | Env | Effect | Source |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in CATALOG:
        if row.kind != "bool":
            continue
        optin = _optin(row.kind, row.default)
        env = ", ".join(f"`{name}`" for name in row.env) or ""
        flag = _cell(_flags(row))
        source = _own(SETTINGS_MD, [f"runtime/install_options.py:{lines_by_key.get(row.key, 1)}"])
        out.append(
            f"| `{_cell(row.key)}` | {optin} | `{_default(row.default)}` | {flag} | {env} | {_cell(row.help)} | {source} |"
        )
    for row in env_rows:
        if row.get("optin") not in {"opt-in", "opt-out"} or row.get("class") != "user":
            continue
        env = f"`{_cell(row['name'])}`"
        sites = list(row.get("read_at") or [])
        out.append(
            f"| {env} | {row.get('optin')} | `{_cell(row.get('default', 'unset'))}` |  | {env} | {_cell(row.get('effect', ''))} | {_own(SETTINGS_MD, sites)} |"
        )
    out.extend([
        "",
        "## Installer options",
        "",
        "| Key | Type | Default | Allowed values | Levels | Flag | Env | Effect | Source |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ])
    for row in CATALOG:
        allowed = ", ".join(row.choices)
        env = ", ".join(row.env)
        source = _own(SETTINGS_MD, [f"runtime/install_options.py:{lines_by_key.get(row.key, 1)}"])
        out.append(
            "| `{key}` | {kind} | `{default}` | {allowed} | {levels} | {flag} | {env} | {effect} | {source} |".format(
                key=_cell(row.key),
                kind=_cell(row.kind),
                default=_cell(_default(row.default)),
                allowed=_cell(allowed),
                levels=_cell(row.levels),
                flag=_cell(_flags(row)),
                env=_cell(env),
                effect=_cell(row.help),
                source=source,
            )
        )
    out.extend([
        "",
        "## Dynamic add-on flags",
        "",
        "These `--with-<addon>` and `--without-<addon>` flags are parsed from unknown arguments. They are not all on `install.py install --help`.",
        "",
    ])
    from runtime.install_options import ADDON_IDS

    for addon in ADDON_IDS:
        out.append(f"- `--with-{addon}` / `--without-{addon}`")
    out.extend([
        "",
        "## Environment-only variables",
        "",
        "Names read by code and not declared as a catalog env. Class `user`, then `maint`.",
        "",
        "| Name | Class | Type | Default | Values | Opt | Effect | Source |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ])
    for cls in ("user", "maint"):
        for row in env_rows:
            if row.get("class") != cls:
                continue
            sites = list(row.get("read_at") or [])
            out.append(
                "| `{name}` | {cls} | {typ} | `{default}` | {values} | {optin} | {effect} | {source} |".format(
                    name=_cell(row["name"]),
                    cls=_cell(row.get("class", "")),
                    typ=_cell(row.get("type", "")),
                    default=_cell(row.get("default", "unset")),
                    values=_cell(row.get("values", "")),
                    optin=_cell(row.get("optin", "")),
                    effect=_cell(row.get("effect", "")),
                    source=_own(SETTINGS_MD, sites),
                )
            )
    out.extend([
        "",
        "## Internal variables",
        "",
        "The harness sets these itself. They are not owner switches.",
        "",
        "| Name | Effect | Why internal | Source |",
        "| --- | --- | --- | --- |",
    ])
    for row in env_rows:
        if row.get("class") != "internal":
            continue
        sites = list(row.get("read_at") or [])
        why = "Set by the harness, not an owner switch."
        out.append(
            f"| `{_cell(row['name'])}` | {_cell(row.get('effect', ''))} | {why} | {_own(SETTINGS_MD, sites)} |"
        )
    out.append("")
    return "\n".join(out)


def _keyword_sources(row: dict) -> list[str]:
    return list(row.get("code_refs") or []) + list(row.get("prose_refs") or [])


def render_keywords(root: Path) -> str:
    rows = load_keywords(root)
    code = sum(1 for row in rows if row.get("enforced_by") == "code")
    prose = sum(1 for row in rows if row.get("enforced_by") != "code")
    out: list[str] = [
        "# Keywords glossary",
        "",
        "Generated from `references/keywords.json`. One line says what the word does. The linked file owns the rule.",
        "",
        "```mermaid",
        "pie showData",
        "    title Keywords by enforcement",
        f'    "Code" : {code}',
        f'    "Prose" : {prose}',
        "```",
        "",
        "Code means a hook or parser matches the phrase. Prose means only the linked instructions define it.",
        "",
    ]
    for title, kinds in _GROUPS:
        chosen = [row for row in rows if row.get("kind") in kinds]
        if not chosen:
            continue
        out.extend([
            f"## {title}",
            "",
            "| Keyword | What it does | Enforced by | Example | Source |",
            "| --- | --- | --- | --- | --- |",
        ])
        for row in chosen:
            phrases = ", ".join(f"`{_cell(phrase)}`" for phrase in row.get("phrases", []))
            enforced = _cell(row.get("enforced_by", ""))
            out.append(
                f"| {phrases} | {_cell(row.get('effect', ''))} | {enforced} | {_cell(row.get('example', ''))} | {_own(KEYWORDS_MD, _keyword_sources(row))} |"
            )
        out.append("")
    out.extend([
        "## Routes",
        "",
        "Loaded from `runtime/harness_index.py`. This table does not copy the router rule text.",
        "",
        "| Route | Use when | Source |",
        "| --- | --- | --- |",
    ])
    for name, path, description in ROUTES:
        out.append(
            f"| {_cell(name)} | {_cell(description)} | {_own(KEYWORDS_MD, [path])} |"
        )
    out.append("")
    roles = ", ".join(name for name, _description in ROLES)
    out.append(f"Role ids: {roles}.")
    out.append("")
    return "\n".join(out)


def _commands(root: Path) -> list[tuple[str, str, int]]:
    found: list[tuple[str, str, int]] = []
    for rel in ("install.py", "bootstrap.py"):
        path = root / rel
        if not path.is_file():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr != "add_parser":
                continue
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                found.append((rel, arg.value, arg.lineno))
    return found


def render_agent(root: Path) -> str:
    version = _version(root)
    lines_by_key = _catalog_lines(root)
    out: list[str] = [
        "# ChaosEngine agent reference",
        "",
        f"Version {version}. Generator `{_generator_sha()}`. Fetch on demand. Not always loaded.",
        "",
        "One fact per row. The owner link is the normative file.",
        "",
        "## Settings",
        "",
        "| Key | Opt | Default | Flag or env | Source |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in CATALOG:
        flag = _flags(row) or ", ".join(row.env)
        source = _own(AGENT_MD, [f"runtime/install_options.py:{lines_by_key.get(row.key, 1)}"])
        out.append(
            f"| `{_cell(row.key)}` | {_optin(row.kind, row.default)} | `{_cell(_default(row.default))}` | {_cell(flag)} | {source} |"
        )
    out.extend([
        "",
        "## Environment",
        "",
        "| Name | Class | Opt | Default | Effect | Source |",
        "| --- | --- | --- | --- | --- | --- |",
    ])
    for row in load_env_entries(root):
        sites = list(row.get("read_at") or [])[:1]
        out.append(
            "| `{name}` | {cls} | {optin} | `{default}` | {effect} | {source} |".format(
                name=_cell(row["name"]),
                cls=_cell(row.get("class", "")),
                optin=_cell(row.get("optin", "")),
                default=_cell(row.get("default", "unset")),
                effect=_cell(_clip(str(row.get("effect", "")), 42)),
                source=_own(AGENT_MD, sites),
            )
        )
    out.extend([
        "",
        "## Keywords",
        "",
        "| Phrase | Kind | Enforced by | Effect | Source |",
        "| --- | --- | --- | --- | --- |",
    ])
    for row in load_keywords(root):
        phrase = f"`{_cell(row.get('phrases', [''] )[0])}`"
        out.append(
            f"| {phrase} | {_cell(row.get('kind', ''))} | {_cell(row.get('enforced_by', ''))} | {_cell(_clip(str(row.get('effect', ''))))} | {_own(AGENT_MD, _keyword_sources(row))} |"
        )
    out.extend([
        "",
        "## Status codes",
        "",
        "| Code | Meaning | Source |",
        "| --- | --- | --- |",
    ])
    for row in load_status_codes(root):
        sites = [str(item) for item in row.get("emitted_by") or []][:1]
        out.append(
            f"| `{_cell(row.get('code', ''))}` | {_cell(_clip(str(row.get('meaning', '')), 42))} | {_own(AGENT_MD, sites)} |"
        )
    out.extend([
        "",
        "## Commands",
        "",
        "Subcommands below. Routes stay in the keywords glossary, which is generated from `runtime/harness_index.py`.",
        "",
        "| Command | Source |",
        "| --- | --- | --- |",
    ])
    for rel, name, line in _commands(root):
        out.append(f"| `{_cell(rel)} {_cell(name)}` | {_own(AGENT_MD, [f'{rel}:{line}'])} |")
    out.append("")
    text = "\n".join(out)
    if len(text.encode("utf-8")) > AGENT_LIMIT:
        raise SystemExit(f"docs/agents/reference.md is {len(text.encode('utf-8'))} bytes; limit is {AGENT_LIMIT}")
    return text


def render_llms(root: Path) -> str:
    version = _version(root)
    return "\n".join([
        "# ChaosEngine",
        "",
        f"> Portable, provider-neutral working contract for coding agents. Version {version}.",
        "",
        "## Docs",
        "",
        "- [Docs home](docs/README.md): human documentation entry",
        "- [How ChaosEngine thinks](docs/explanation/how-chaosengine-thinks.md): triage and the ethics floor",
        "",
        "## Reference",
        "",
        "- [Settings](docs/reference/settings.md): installer options, flags, and environment variables",
        "- [Keywords](docs/reference/keywords.md): owner phrases, roles, workflows, and tokens",
        "",
        "## Agents",
        "",
        "- [AGENTS.md](AGENTS.md): always-loaded entry",
        "- [Agent reference](docs/agents/reference.md): dense settings, keywords, status codes, and routes",
        "",
        "## Optional",
        "",
        "- [Install](INSTALL.md): install, upgrade, and uninstall",
        "- [Overview](guides/overview.md): operating loop",
        "",
    ])


def rendered(root: Path) -> dict[str, str]:
    return {
        SETTINGS_MD: render_settings(root),
        KEYWORDS_MD: render_keywords(root),
        AGENT_MD: render_agent(root),
        LLMS: render_llms(root),
    }


def check(root: Path) -> list[str]:
    """Return one line per drifted output. Empty means the tree matches."""
    drifted: list[str] = []
    for rel, text in rendered(root).items():
        path = root / rel
        current = path.read_text(encoding="utf-8") if path.is_file() else ""
        if current != text:
            drifted.append(f"{rel} drifted; run python3 scripts/docs/gen_reference.py")
    return drifted


def write(root: Path) -> None:
    for rel, text in rendered(root).items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    root = ROOT
    checking = "--check" in args
    if checking:
        drifted = check(root)
        for item in drifted:
            print(item)
        return 1 if drifted else 0
    write(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
