#!/usr/bin/env python3
"""tool.py plan: local plan commands. No network and no model calls."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_DIR = str(Path(__file__).resolve().parent)
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

import plan_gate  # noqa: E402
import plan_model  # noqa: E402
import plan_render  # noqa: E402

USAGE = """\
usage: tool.py plan new TASK (--from plan.json | --from-md checklist.md) [--goal TEXT] [--triage TEXT]
       tool.py plan show TASK [--format term|md|mermaid|html|json] [--out PATH] [--pr-section]
       tool.py plan step TASK STEP --status STATUS [--evidence KIND:REF]... [--note TEXT]
       tool.py plan edit TASK (--add TITLE [--after ID] | --remove ID | --move ID --after ID | --retitle ID TEXT)
       tool.py plan approve TASK [--comment STEP:TEXT]... [--code CODE] [--ref TEXT]
       tool.py plan approve TASK --request-code
       tool.py plan stop TASK
       tool.py plan gate TASK
       tool.py plan watch TASK
       tool.py plan walkthrough TASK [--format md|html] [--out PATH]

exit 0 ok, 1 validation, 2 usage, 4 awaiting, 5 stopped, 6 no plan
"""


def _need(task: str) -> dict | None:
    plan = plan_model.load(task)
    if plan is None:
        print("plan: no plan", file=sys.stderr)
    return plan


def _write(text: str, out: str | None) -> int:
    if not out:
        sys.stdout.write(text)
        return 0
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return 0


def _create(task: str, source: str, markdown: str, goal: str, triage: str) -> int:
    if plan_model.plan_path(task).is_file():
        raise plan_model.PlanError(["plan exists"])
    if markdown:
        explanation, steps = plan_model.parse_markdown(Path(markdown).read_text(encoding="utf-8"))
        plan = plan_model.fresh_plan(task, steps, goal=goal, explanation=explanation, triage=triage)
    else:
        payload = json.loads(Path(source).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise plan_model.PlanError(["plan must be an object"])
        payload["schema"] = plan_model.SCHEMA
        payload["task"] = task
        if goal:
            payload["goal"] = goal
        steps = payload.get("steps") or []
        count = len(steps) if isinstance(steps, list) else 0
        required = triage.strip().casefold() == "public-contract" or count >= 3
        payload["revision"] = 1
        payload["approval"] = plan_model._approval_for(required)
        payload["walkthrough"] = None
        plan = plan_model.normalize(payload)
    plan_model.save(plan)
    plan_model.seed_ledger(plan)
    return 0


def _comments(specs: list[str], plan: dict) -> list[dict]:
    comments = []
    known = {step["id"] for step in plan["steps"]}
    for spec in specs:
        if ":" not in spec:
            raise plan_model.PlanError([f"comment must be STEP:TEXT: {spec}"])
        step, text = spec.split(":", 1)
        step, text = step.strip(), text.strip()
        if not step or not text:
            raise plan_model.PlanError(["comment must be STEP:TEXT"])
        if step not in known:
            raise plan_model.PlanError([f"unknown step: {step}"])
        comments.append({"step": step, "text": plan_model.collapse(text)})
    return comments


def watch_task(
    task: str,
    *,
    is_tty: bool = False,
    poll_s: float = 1.0,
    sleep=time.sleep,
    out=None,
    on_wait=None,
    max_loops: int | None = None,
    caps=None,
) -> int:
    sink = out if out is not None else sys.stdout
    chosen = caps or plan_render.fixed_caps(unicode=False, width=80, tty=is_tty)
    previous = None
    loops = 0
    while True:
        plan = plan_model.load(task)
        if plan is None:
            print("plan: no plan", file=sys.stderr)
            return 6
        signature = tuple((step["id"], step["status"], step.get("activeText") or "") for step in plan["steps"])
        if signature != previous:
            done, total = plan_model.progress(plan)
            if is_tty:
                sink.write("\033[2J\033[H")
                sink.write(plan_render.render_term(plan, chosen))
            elif previous is None:
                sink.write(f"{done}/{total} done\n")
            else:
                prior = {item[0]: item for item in previous}
                for item in signature:
                    if prior.get(item[0]) != item:
                        sink.write(f"{item[0]} {item[1]} {done}/{total} done\n")
            sink.flush()
            previous = signature
        if all(step["status"] in plan_model.TERMINAL_STATUSES for step in plan["steps"]):
            return 0
        if max_loops is not None and loops >= max_loops:
            return 0
        loops += 1
        if on_wait is not None:
            on_wait()
        try:
            sleep(poll_s)
        except KeyboardInterrupt:
            return 0


def _cmd_new(ns: argparse.Namespace) -> int:
    if bool(ns.source) == bool(ns.markdown):
        print(USAGE, end="", file=sys.stderr)
        return 2
    return _create(ns.task, ns.source or "", ns.markdown or "", ns.goal or "", ns.triage or "")


def _cmd_show(ns: argparse.Namespace) -> int:
    plan = _need(ns.task)
    if plan is None:
        return 6
    text = plan_render.render(plan, ns.format, caps=plan_render.caps_for(sys.stdout), pr_section=ns.pr_section)
    return _write(text, ns.out)


def _cmd_step(ns: argparse.Namespace) -> int:
    plan = _need(ns.task)
    if plan is None:
        return 6
    plan_model.set_status(
        plan,
        ns.step,
        ns.status,
        evidence=list(ns.evidence or []),
        note=ns.note,
        root=Path.cwd(),
    )
    plan_model.save(plan)
    return 0


def _cmd_edit(ns: argparse.Namespace) -> int:
    plan = _need(ns.task)
    if plan is None:
        return 6
    ops = [ns.add, ns.remove, ns.move, ns.retitle]
    if sum(item is not None for item in ops) != 1:
        print(USAGE, end="", file=sys.stderr)
        return 2
    if ns.move is not None and not ns.after:
        print("plan: move needs --after", file=sys.stderr)
        return 2
    if ns.add is not None:
        plan_model.add_step(plan, " ".join(ns.add), after=ns.after or "")
    elif ns.remove is not None:
        plan_model.remove_step(plan, ns.remove)
    elif ns.move is not None:
        plan_model.move_step(plan, ns.move, ns.after)
    else:
        if len(ns.retitle) < 2:
            print("plan: retitle needs ID and TEXT", file=sys.stderr)
            return 2
        plan_model.retitle_step(plan, ns.retitle[0], " ".join(ns.retitle[1:]))
    plan_model.save(plan)
    return 0


def _cmd_approve(ns: argparse.Namespace) -> int:
    if not ns.task:
        print(USAGE, end="", file=sys.stderr)
        return 2
    plan = _need(ns.task)
    if plan is None:
        return 6
    if ns.request_code:
        code = plan_gate.request_approval_code(ns.task, int(plan["revision"]))
        print(
            f"plan-approve-code: {code} (one use, {plan_gate.CODE_TTL // 60} min, "
            f"task {ns.task} revision {plan['revision']}). "
            "Ask the owner to paste it back. A code relayed by an agent is not approval."
        )
        return 0
    comments = _comments(list(ns.comment or []), plan) if ns.comment else None
    code, message = plan_gate.approve(ns.task, code=ns.code or "", ref=ns.ref or "", comments=comments)
    if code != 0:
        print(f"plan: {message}", file=sys.stderr)
    return code


def _cmd_stop(ns: argparse.Namespace) -> int:
    code, message = plan_gate.stop(ns.task)
    if code != 0:
        print(f"plan: {message}", file=sys.stderr)
    return code


def _cmd_gate(ns: argparse.Namespace) -> int:
    code = plan_gate.gate(ns.task)
    labels = {0: "approved", 4: "awaiting", 5: "stopped", 6: "no plan"}
    print(labels.get(code, str(code)))
    return code


def _cmd_watch(ns: argparse.Namespace) -> int:
    tty = bool(getattr(sys.stdout, "isatty", lambda: False)())
    return watch_task(ns.task, is_tty=tty, caps=plan_render.caps_for(sys.stdout), poll_s=1.0)


def _cmd_walk(ns: argparse.Namespace) -> int:
    plan = _need(ns.task)
    if plan is None:
        return 6
    root = Path.cwd()
    if ns.format == "html":
        text = plan_render.render_walkthrough_html(plan, root)
        default = "walkthrough.html"
    else:
        text = plan_render.render_walkthrough_md(plan, root)
        default = "walkthrough.md"
    target = ns.out or default
    code = _write(text, target)
    plan["walkthrough"] = target
    plan_model.save(plan)
    return code


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tool.py plan", add_help=True)
    sub = parser.add_subparsers(dest="command", required=True)
    new = sub.add_parser("new")
    new.add_argument("task")
    new.add_argument("--from", dest="source")
    new.add_argument("--from-md", dest="markdown")
    new.add_argument("--goal", default="")
    new.add_argument("--triage", default="")
    new.set_defaults(func=_cmd_new)
    show = sub.add_parser("show")
    show.add_argument("task")
    show.add_argument("--format", default="term", choices=("term", "md", "mermaid", "html", "json"))
    show.add_argument("--out")
    show.add_argument("--pr-section", action="store_true")
    show.set_defaults(func=_cmd_show)
    step = sub.add_parser("step")
    step.add_argument("task")
    step.add_argument("step")
    step.add_argument("--status", required=True)
    step.add_argument("--evidence", action="append", default=[])
    step.add_argument("--note", default=None)
    step.set_defaults(func=_cmd_step)
    edit = sub.add_parser("edit")
    edit.add_argument("task")
    edit.add_argument("--add", nargs="+")
    edit.add_argument("--remove")
    edit.add_argument("--move")
    edit.add_argument("--after", default="")
    edit.add_argument("--retitle", nargs="+")
    edit.set_defaults(func=_cmd_edit)
    approve = sub.add_parser("approve")
    approve.add_argument("task")
    approve.add_argument("--comment", action="append", default=[])
    approve.add_argument("--code", default="")
    approve.add_argument("--ref", default="")
    approve.add_argument("--request-code", action="store_true")
    approve.set_defaults(func=_cmd_approve)
    stop = sub.add_parser("stop")
    stop.add_argument("task")
    stop.set_defaults(func=_cmd_stop)
    gate = sub.add_parser("gate")
    gate.add_argument("task")
    gate.set_defaults(func=_cmd_gate)
    watch = sub.add_parser("watch")
    watch.add_argument("task")
    watch.set_defaults(func=_cmd_watch)
    walk = sub.add_parser("walkthrough")
    walk.add_argument("task")
    walk.add_argument("--format", default="md", choices=("md", "html"))
    walk.add_argument("--out")
    walk.set_defaults(func=_cmd_walk)
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(USAGE, end="", file=sys.stderr)
        return 2
    if argv[0] in {"-h", "--help", "help"}:
        print(USAGE, end="")
        return 0
    parser = _parser()
    try:
        ns = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2
    try:
        return int(ns.func(ns))
    except plan_model.PlanError as exc:
        for item in exc.errors:
            print(f"plan: {item}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"plan: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"plan: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
