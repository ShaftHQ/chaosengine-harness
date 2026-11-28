#!/usr/bin/env python3
"""Pure ce-plan renderers: terminal, Markdown, Mermaid, HTML, walkthrough."""

from __future__ import annotations

import html
import sys
from pathlib import Path

_DIR = str(Path(__file__).resolve().parent)
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

import ce_ui  # noqa: E402
import plan_model  # noqa: E402

_UNI = {
    "done": "✓",
    "in_progress": "◉",
    "pending": "·",
    "failed": "✗",
    "skipped": "⊘",
    "blocked": "⏸",
}
_ASCII = {
    "done": "[x]",
    "in_progress": "[>]",
    "pending": "[ ]",
    "failed": "[!]",
    "skipped": "[-]",
    "blocked": "[=]",
}
_IMAGE = (".png", ".jpg", ".jpeg", ".webp", ".gif")
_CLASS = {
    "pending": "fill:#eee,stroke:#333",
    "in_progress": "fill:#adf,stroke:#333",
    "done": "fill:#ada,stroke:#333",
    "failed": "fill:#faa,stroke:#333",
    "skipped": "fill:#ddd,stroke:#333",
    "blocked": "fill:#fda,stroke:#333",
}


def fixed_caps(*, unicode: bool, width: int = 80, tty: bool = True) -> ce_ui.Capabilities:
    return ce_ui.Capabilities(
        tty=tty,
        cursor=False,
        color="",
        unicode=unicode,
        hyperlinks=False,
        width=width,
    )


def caps_for(stream=None) -> ce_ui.Capabilities:
    detected = ce_ui.detect_capabilities(stream)
    return fixed_caps(unicode=bool(detected.unicode and detected.tty), width=detected.width if detected.tty else 80, tty=bool(detected.tty))


def display_title(plan: dict) -> str:
    explanation = str(plan.get("explanation") or "").strip()
    if explanation and len(explanation) <= 80:
        return explanation
    return "Plan"


def _fit(line: str, caps: ce_ui.Capabilities) -> str:
    width = max(1, int(caps.width or 80))
    if len(line) <= width:
        return line
    ellipsis = "…" if caps.unicode else "..."
    if len(ellipsis) >= width:
        return ellipsis[:width]
    return line[: width - len(ellipsis)] + ellipsis


def render_term(plan: dict, caps: ce_ui.Capabilities | None = None) -> str:
    chosen = caps or fixed_caps(unicode=True, width=80, tty=True)
    marks = _UNI if chosen.unicode else _ASCII
    done, total = plan_model.progress(plan)
    lines = [_fit(f"Plan: {display_title(plan)}  {done}/{total} done", chosen)]
    for step in plan.get("steps") or []:
        text = step.get("activeText") if step.get("status") == "in_progress" and step.get("activeText") else step.get("title") or ""
        mark = marks.get(step.get("status") or "", marks["pending"])
        lines.append(_fit(f"{mark} {text}", chosen))
    return "\n".join(lines) + "\n"


def render_md(plan: dict, *, pr_section: bool = False) -> str:
    lines: list[str] = []
    if pr_section:
        lines.extend(["## Plan", ""])
    header = plan.get("goal") or plan.get("explanation") or ""
    if header:
        lines.extend([str(header), ""])
    for step in plan.get("steps") or []:
        box = "x" if step.get("status") == "done" else " "
        suffix = "" if step.get("status") in {"done", "pending"} else f" ({step.get('status')})"
        lines.append(f"- [{box}] {step.get('title') or ''}{suffix}")
        for item in step.get("evidence") or []:
            lines.append(f"  - [{item.get('kind')}]({item.get('ref')})")
    return "\n".join(lines) + "\n"


def _mermaid_id(step_id: str) -> str:
    cleaned = "".join(char if char.isalnum() or char == "_" else "_" for char in step_id)
    if not cleaned or cleaned[0].isdigit():
        cleaned = "s_" + cleaned
    return cleaned


def _mermaid_label(text: str) -> str:
    return (
        text.replace("&", "#amp;")
        .replace('"', "#quot;")
        .replace("<", "#lt;")
        .replace(">", "#gt;")
        .replace("[", "#lbrack;")
        .replace("]", "#rbrack;")
    )


def render_mermaid(plan: dict) -> str:
    lines = ["flowchart TD"]
    for step in plan.get("steps") or []:
        lines.append(f'  {_mermaid_id(step["id"])}["{_mermaid_label(step.get("title") or "")}"]')
    if any(step.get("dependsOn") for step in plan.get("steps") or []):
        for step in plan["steps"]:
            for dep in step.get("dependsOn") or []:
                lines.append(f"  {_mermaid_id(dep)} --> {_mermaid_id(step['id'])}")
    else:
        ids = [_mermaid_id(step["id"]) for step in plan.get("steps") or []]
        for left, right in zip(ids, ids[1:]):
            lines.append(f"  {left} --> {right}")
    for status, paint in _CLASS.items():
        lines.append(f"  classDef {status} {paint}")
    for step in plan.get("steps") or []:
        lines.append(f"  class {_mermaid_id(step['id'])} {step.get('status')}")
    return "\n".join(lines) + "\n"


def _image(ref: str) -> bool:
    path = ref.split("?", 1)[0].split("#", 1)[0].lower()
    return path.endswith(_IMAGE)


def _html_evidence(item: dict) -> str:
    ref = str(item.get("ref") or "")
    kind = html.escape(str(item.get("kind") or ""))
    href = html.escape(ref, quote=True)
    if ref.startswith(("http://", "https://")):
        return f'<a href="{href}">{kind}</a>'
    if _image(ref):
        return f'<img src="{href}" alt="{kind}">'
    return f'<a href="{href}">{kind}</a>'


def _html_shell(title: str, body: str) -> str:
    safe = html.escape(title)
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        f"<title>{safe}</title>\n"
        "<style>\n"
        "body{font-family:sans-serif;margin:1rem}\n"
        ".bar{background:#ddd;height:8px}\n"
        ".fill{background:#333;height:8px}\n"
        "</style>\n"
        "</head>\n"
        "<body>\n"
        f"{body}\n"
        "</body>\n"
        "</html>\n"
    )


def render_html(plan: dict) -> str:
    done, total = plan_model.progress(plan)
    percent = 0 if not total else round(100 * done / total)
    title = display_title(plan)
    chunks = [
        f"<h1>{html.escape(title)}</h1>",
        f"<p>{done}/{total} done</p>",
        f'<div class="bar"><div class="fill" style="width:{percent}%"></div></div>',
        "<ol>",
    ]
    for step in plan.get("steps") or []:
        chunks.append(
            f'<li data-status="{html.escape(str(step.get("status") or ""), quote=True)}">{html.escape(step.get("title") or "")}'
        )
        if step.get("status") == "in_progress" and step.get("activeText"):
            chunks.append(f"<em>{html.escape(step['activeText'])}</em>")
        for item in step.get("evidence") or []:
            chunks.append(_html_evidence(item))
        chunks.append("</li>")
    chunks.append("</ol>")
    return _html_shell(title, "\n".join(chunks))


def render_json(plan: dict) -> str:
    import json

    return json.dumps(plan, indent=2, sort_keys=True) + "\n"


def render(plan: dict, fmt: str, *, caps: ce_ui.Capabilities | None = None, pr_section: bool = False) -> str:
    chosen = fmt.strip().casefold()
    if chosen == "term":
        return render_term(plan, caps)
    if chosen == "md":
        return render_md(plan, pr_section=pr_section)
    if chosen == "mermaid":
        return render_mermaid(plan)
    if chosen == "html":
        return render_html(plan)
    if chosen == "json":
        return render_json(plan)
    raise plan_model.PlanError([f"unknown format: {fmt}"])


def render_walkthrough_md(plan: dict, root: Path | None = None) -> str:
    lines = ["# Walkthrough", "", "## Goal", "", str(plan.get("goal") or plan.get("explanation") or "Plan"), "", "## Steps", ""]
    for step in plan.get("steps") or []:
        lines.append(f"- {step['id']} {step.get('status')}: {step.get('title') or ''}")
    lines.extend(["", "## Changes made", ""])
    lines.extend(plan_model.changes_lines(plan) or ["not available"])
    lines.extend(["", "## Validation results", ""])
    for step in plan.get("steps") or []:
        lines.append(f"- {step['id']} {step.get('title') or ''}")
        evidence = step.get("evidence") or []
        if not evidence:
            lines.append("  - none")
            continue
        for item in evidence:
            mark = plan_model.evidence_mark(item, root)
            suffix = f" exit {item['exit']}" if "exit" in item else ""
            if mark:
                suffix += f" {mark}"
            lines.append(f"  - {item.get('kind')}: [{item.get('ref')}]({item.get('ref')}){suffix}")
    lines.extend(["", "## Open items", ""])
    lines.extend(plan_model.open_items(plan) or ["none"])
    lines.append("")
    return "\n".join(lines)


def render_walkthrough_html(plan: dict, root: Path | None = None) -> str:
    body = ["<h1>Walkthrough</h1>", "<h2>Goal</h2>", f"<p>{html.escape(str(plan.get('goal') or plan.get('explanation') or 'Plan'))}</p>", "<h2>Steps</h2>", "<ul>"]
    for step in plan.get("steps") or []:
        body.append(f"<li>{html.escape(step['id'])} {html.escape(str(step.get('status') or ''))}: {html.escape(step.get('title') or '')}</li>")
    body.extend(["</ul>", "<h2>Changes made</h2>", "<ul>"])
    changes = plan_model.changes_lines(plan) or ["not available"]
    body.extend(f"<li>{html.escape(line)}</li>" for line in changes)
    body.extend(["</ul>", "<h2>Validation results</h2>", "<ul>"])
    for step in plan.get("steps") or []:
        body.append(f"<li>{html.escape(step['id'])} {html.escape(step.get('title') or '')}")
        evidence = step.get("evidence") or []
        if not evidence:
            body.append("<p>none</p></li>")
            continue
        for item in evidence:
            mark = plan_model.evidence_mark(item, root)
            suffix = f" exit {item['exit']}" if "exit" in item else ""
            if mark:
                suffix += f" {mark}"
            body.append(_html_evidence(item) + html.escape(suffix))
        body.append("</li>")
    body.extend(["</ul>", "<h2>Open items</h2>", "<ul>"])
    opened = plan_model.open_items(plan) or ["none"]
    body.extend(f"<li>{html.escape(line)}</li>" for line in opened)
    body.append("</ul>")
    return _html_shell("Walkthrough", "\n".join(body))


def resume_block(plan: dict, caps: ce_ui.Capabilities | None = None) -> str:
    lines = [render_term(plan, caps).rstrip("\n")]
    for comment in (plan.get("approval") or {}).get("comments") or []:
        lines.append(f"comment {comment.get('step')}: {comment.get('text')}")
    return "\n".join(lines) + "\n"
