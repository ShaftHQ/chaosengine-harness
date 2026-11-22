#!/usr/bin/env python3
"""Activate ChaosEngine and reject catastrophic shell scope.

Canonical portable core guard (ships to every install). A project's own
repository guard stays outside the core and shares no code with it.
"""

from __future__ import annotations

import ast
import contextlib
import io
import json
import os
import hashlib
import importlib.util
import posixpath
import re
import shutil
import subprocess  # nosec B404 - fixed git argv for toplevel.
import shlex
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path


def _overlay_module(name: str) -> Path:
    """Prefer runtime/<name> at the tree root; fall back to a flat file."""
    tree = Path(__file__).resolve().parents[1]
    if str(tree) not in sys.path:
        sys.path.insert(0, str(tree))
    nested = tree / "runtime" / name
    return nested if nested.is_file() else tree / name



def _load_sibling(module_name: str):
    path = Path(__file__).resolve().with_name(f"{module_name}.py")
    if not path.is_file():
        return None
    specification = importlib.util.spec_from_file_location(f"chaos_engine_{module_name}", path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"ChaosEngine {module_name} module is unavailable")
    module = importlib.util.module_from_spec(specification)
    previous = sys.modules.get(specification.name)
    sys.modules[specification.name] = module
    try:
        specification.loader.exec_module(module)
    except (Exception, KeyboardInterrupt, SystemExit):
        if previous is None:
            sys.modules.pop(specification.name, None)
        else:
            sys.modules[specification.name] = previous
        raise
    return module


_lifecycle = _load_sibling("lifecycle")
if _lifecycle is None:
    raise RuntimeError("ChaosEngine lifecycle core is unavailable")
_kernel = _load_sibling("kernel")
if _kernel is None:
    raise RuntimeError("ChaosEngine policy kernel is unavailable")
justification = _load_sibling("retrieve_justification")
reflection = _load_sibling("reflection")
if reflection is None:  # Repository adapter fallback for a source-only layout.
    repository_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repository_root))
    from scripts.agents import reflection


session_scratch = _load_sibling("session_scratch")


def _learning_session_controller():
    repository_root = Path(__file__).resolve().parents[2]
    candidate = repository_root / "scripts" / "agents" / "learning_session.py"
    if not candidate.is_file():
        return None
    if str(repository_root) not in sys.path:
        sys.path.insert(0, str(repository_root))
    try:
        from scripts.agents import learning_session
    except (ImportError, OSError, AttributeError):
        return None
    return learning_session


def _portable_learning_completion(session_id: str) -> dict | None:
    """Load portable `.chaos-engine-state/learning-session/` completion (#5625)."""
    if not isinstance(session_id, str) or not session_id.strip():
        return None
    safe = session_id.strip()[:64]
    for root in (Path.cwd(), Path(__file__).resolve().parents[2]):
        path = root / ".chaos-engine-state" / "learning-session" / f"{safe}.completion.json"
        if not path.is_file():
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError):
            continue
        if isinstance(value, dict) and value.get("kind") == "learning-session-portable-finalize":
            return value
    return None


def learning_completion_artifact(session_id: str) -> dict | None:
    """Return the immutable Learning Session completion for hooks, if present."""
    portable = _portable_learning_completion(session_id)
    if portable is not None:
        return portable
    controller = _learning_session_controller()
    if controller is None or not isinstance(session_id, str) or not session_id.strip():
        return None
    state = controller.default_state_dir()
    completed = controller.load_session_completion(state, session_id)
    if completed is not None:
        return completed
    return controller.load_runtime_completion(state, session_id)


ACTIVATION = "Follow .chaos-engine/skills/chaos-engine/SKILL.md before continuing."
ROOT_DRIVE = re.compile(r"(?i)(?:^|\s)[a-z]:\\(?:\s|$)")
ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
SHELLS = {"bash", "sh", "zsh"}
DOWNLOADERS = {"curl", "fetch", "wget"}
TERMINAL_LABELS = (
    "what happened",
    "why it happened",
    "continue doing",
    "stop doing",
    "start doing",
    "next action",
)
# Line-leading short headings from a real retrospective. The four long phrases
# above still count. "what happened" and "next action" already match the
# colon form the model writes.
_SHORT_TERMINAL_HEADINGS = {
    "why it happened": re.compile(r"(?im)^[ \t>*_-]*why\s*:"),
    "continue doing": re.compile(r"(?im)^[ \t>*_-]*continue\s*:"),
    "stop doing": re.compile(r"(?im)^[ \t>*_-]*stop\s*:"),
    "start doing": re.compile(r"(?im)^[ \t>*_-]*start\s*:"),
}
_SCOPE_DENIAL = "ChaosEngine rejected destructive broad scope."
# An actionable retrospective line is a GitHub issue. The attestation is the
# only close that carries no URL. Upstream is the ChaosEngine repository.
# Private is the repository of the project using ChaosEngine.
_TRACKING_ATTESTATION = "nothing actionable"
_ISSUE_URL = re.compile(r"https://github\.com/[^\s)]+/issues/[1-9][0-9]*", re.IGNORECASE)
_TRACKING_DEMAND = (
    "Track every actionable item remotely before this note: "
    "a ChaosEngine change is an issue on the configured upstream repository; "
    "a project-only change is an issue on this project's repository. "
    "Put each issue URL in the note. If nothing is actionable, write nothing actionable."
)




LEARNING_REQUEST = re.compile(r"(?i)\b(?:learning session|self-improve|run a retro(?:spective)?)\b")


def learning_requested(event: dict) -> bool:
    """True when the owner's prompt asks for a Learning Session."""
    prompt = event.get("prompt") or event.get("user_prompt") or ""
    return isinstance(prompt, str) and bool(LEARNING_REQUEST.search(prompt))


# #7424: owner ``/goal`` (finish-delivery) → write owner-finish-goal marker.
OWNER_GOAL_FINISH = re.compile(
    r"(?i)(?:^|\s)/goal\b|"
    r"\bfinish(?:ing)?\s+(?:the\s+)?(?:delivery|multi[- ]?pr)\b"
)
# #7443: owner names a pull request as out of scope (do not babysit / until-merged).
_OUT_OF_SCOPE_PR_URL = re.compile(
    r"https://github\.com/([^\s/]+/[^\s/]+)/pull/(\d+)",
    re.IGNORECASE,
)
_OUT_OF_SCOPE_CUE = re.compile(
    r"(?i)\b(?:out\s+of\s+scope|do\s+not\s+(?:watch|babysit|merge)|don'?t\s+watch)\b"
)
# #7797: these are owner decisions even inside a dispatch brief. "do not merge" is not.
_OWNER_SCOPE_DECISION = re.compile(
    r"(?i)\b(?:out\s+of\s+scope|do\s+not\s+(?:watch|babysit)|don'?t\s+watch)\b"
)
_DELEGATED_BRIEF = re.compile(r"(?i)\b(?:implementer|writer|dispatch|subagent)\b")
_OUT_OF_SCOPE_STATE = "out-of-scope-pull-requests.json"


def owner_goal_finish_requested(event: dict) -> bool:
    """True when the owner's prompt starts a finish-delivery ``/goal`` (#7424)."""
    prompt = event.get("prompt") or event.get("user_prompt") or ""
    return isinstance(prompt, str) and bool(OWNER_GOAL_FINISH.search(prompt))


def _task_ledger_module():
    """Load chaos-engine/task_ledger.py without requiring package install."""
    candidate = _overlay_module("task_ledger.py")
    if not candidate.is_file():
        return None
    spec = importlib.util.spec_from_file_location("chaos_engine_task_ledger_guard", candidate)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except (OSError, ImportError, SyntaxError, TypeError):
        return None
    return module


def activate_owner_finish_goal_from_prompt(event: dict) -> Path | None:
    """Write owner-finish-goal.json when ``/goal`` finish-delivery is requested (#7424)."""
    if not owner_goal_finish_requested(event):
        return None
    ledger = _task_ledger_module()
    if ledger is None or not hasattr(ledger, "write_owner_finish_goal"):
        return None
    cwd = Path(str(event.get("cwd") or Path.cwd()))
    return ledger.write_owner_finish_goal(cwd, active=True, source="/goal")


def _out_of_scope_state_path(cwd: Path) -> Path:
    return cwd / ".chaos-engine-state" / _OUT_OF_SCOPE_STATE


def remember_out_of_scope_pull_request(
    cwd: Path, number: int, *, repository: str | None = None
) -> None:
    """Record a pull request the owner named out of scope (#7443)."""
    if number is None or isinstance(number, bool) or int(number) <= 0:
        return
    path = _out_of_scope_state_path(cwd)
    entries: list[dict] = []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and isinstance(payload.get("pullRequests"), list):
            entries = [item for item in payload["pullRequests"] if isinstance(item, dict)]
    except (OSError, UnicodeError, json.JSONDecodeError):
        entries = []
    key_repo = (repository or "").strip()
    for item in entries:
        if int(item.get("pullRequest") or 0) == int(number):
            if not key_repo or str(item.get("repository") or "") == key_repo:
                return
    entries.append({"pullRequest": int(number), "repository": key_repo})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"pullRequests": entries}, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def out_of_scope_pull_request(
    cwd: Path, number: int | None, *, repository: str | None = None
) -> bool:
    """True when ``number`` is on the owner out-of-scope allowlist (#7443)."""
    if number is None or isinstance(number, bool) or int(number) <= 0:
        return False
    path = _out_of_scope_state_path(cwd)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    entries = payload.get("pullRequests")
    if not isinstance(entries, list):
        return False
    want_repo = (repository or "").strip().casefold()
    for item in entries:
        if not isinstance(item, dict):
            continue
        if int(item.get("pullRequest") or 0) != int(number):
            continue
        have = str(item.get("repository") or "").strip().casefold()
        if not want_repo or not have or have == want_repo:
            return True
    return False


def record_out_of_scope_from_prompt(event: dict) -> None:
    """Parse owner 'out of scope' + PR URL from UserPromptSubmit (#7443)."""
    prompt = event.get("prompt") or event.get("user_prompt") or ""
    if not isinstance(prompt, str) or not _OUT_OF_SCOPE_CUE.search(prompt):
        return
    # #7797: an implementer brief that says "do not merge" is not an owner allowlist entry.
    if _DELEGATED_BRIEF.search(prompt) and not _OWNER_SCOPE_DECISION.search(prompt):
        return
    cwd = Path(str(event.get("cwd") or Path.cwd()))
    for match in _OUT_OF_SCOPE_PR_URL.finditer(prompt):
        remember_out_of_scope_pull_request(
            cwd, int(match.group(2)), repository=match.group(1)
        )


def _watch_until_merged_target(command: str) -> tuple[int | None, str | None]:
    """Return (pr_number, repository) from a watch_pr_checks --until-merged command."""
    text = str(command or "")
    if "watch_pr_checks" not in text.replace("\\", "/").casefold():
        return None, None
    if "--until-merged" not in text:
        return None, None
    number = None
    pr_match = re.search(r"--pr\s+(\d+)\b", text)
    if pr_match:
        number = int(pr_match.group(1))
    repo = None
    url_match = _OUT_OF_SCOPE_PR_URL.search(text)
    if url_match:
        repo = url_match.group(1)
        if number is None:
            number = int(url_match.group(2))
    return number, repo


def until_merged_out_of_scope_reason(cwd: Path, commands: tuple[str, ...]) -> str:
    """PreToolUse: refuse --until-merged on an owner out-of-scope PR (#7443)."""
    for command in commands:
        number, repository = _watch_until_merged_target(command)
        if number is None:
            continue
        if out_of_scope_pull_request(cwd, number, repository=repository):
            label = f"{repository}#{number}" if repository else f"#{number}"
            return (
                f"Pull request {label} is on the owner out-of-scope allowlist. "
                "Do not run watch_pr_checks.py --until-merged on it (#7443)."
            )
    return ""



def learning_session_reason(session_id: str, event: dict) -> str | None:
    # #6739: Learning Session after every final delivery. delivery-complete
    # alone owes it; the completion artifact pays it (the Learning Session
    # pull request's own merge lands after that artifact and owes nothing).
    recorded = reflection.entries(session_id)
    activities = {
        item.get("activity")
        for item in recorded
        if item.get("kind") == "task-activity"
    }
    if "delivery-complete" not in activities:
        return None
    if learning_completion_artifact(session_id) is not None:
        return None
    question = (
        session_scratch.PREVENTION_QUESTION
        if session_scratch is not None
        else "what can we learn from what happened so far for our harness or memory modules to avoid such failures in the future?"
    )
    return (
        "Learning Session: delivery is complete, and a Learning Session after "
        "every final delivery is owed. "
        "Diff the session lessons against the skills and references; a lesson "
        "already shipped in this pull request or already in a skill is not new. "
        "File one spec issue and open ONE pull request (skip-release-notes, "
        "auto-merge MERGE) for the new lessons, or finalize with nothing durable. "
        "Do not write them to a local queue or into chat. Product lessons may queue. "
        "Answer this question with ## Prevention bullets: "
        f"{question} "
        "Each bullet is `tracked: https://github.com/...` (an issue or pull that "
        "records the recommendation), or the section is the single line "
        "`nothing actionable`."
    )


def outcome_target(command: str, tool_name: str, explicit: object = None) -> str:
    if isinstance(explicit, str) and explicit.strip():
        normalized = re.sub(r"\s+", " ", explicit.strip().casefold())
        return "logical-" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]
    if not command:
        return tool_name or "unknown"
    normalized = re.sub(r"\s+", " ", command.strip().casefold())
    return "command-" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]


def test_command(command: str) -> bool:
    lowered = command.casefold()
    return any(
        marker in lowered
        for marker in (" -m unittest", "pytest", "mvn test", "mvn verify", "gradle test", "npm test")
    )


def mutation_command(command: str) -> bool:
    lowered = command.casefold()
    return bool(
        re.search(r"\b(?:set-content|add-content|remove-item|new-item|out-file|touch|rm|mv|cp)\b", lowered)
        or re.search(r"\bgit\s+(?:add|commit|push|merge|rebase|reset|checkout|switch|clean)\b", lowered)
    )


def shell_tokens(command: str) -> list[str]:
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
        lexer.whitespace_split = True
        lexer.commenters = ""
        return list(lexer)
    except ValueError:
        return []


def tracker_command(command: str) -> bool:
    parsed = shell_tokens(command)
    if not parsed or any(item in {";", "&&", "||", "|", "&"} for item in parsed):
        return False
    head, arguments = command_head(parsed)
    return head == "gh" and arguments[:2] in (["issue", "comment"], ["issue", "edit"])


def git_push_command(command: str) -> bool:
    """True for one ``git push``, not a compound shell that hides it."""
    parsed = shell_tokens(command)
    if not parsed or any(item in {";", "&&", "||", "|", "&"} for item in parsed):
        return False
    head, arguments = command_head(parsed)
    return head == "git" and arguments[:1] == ["push"]


def gh_pr_command(command: str) -> bool:
    """True for a ``gh pr`` write (create, edit, merge, and the other delivery verbs)."""
    parsed = shell_tokens(command)
    if not parsed or any(item in {";", "&&", "||", "|", "&"} for item in parsed):
        return False
    head, arguments = command_head(parsed)
    return head == "gh" and len(arguments) >= 2 and arguments[0] == "pr" and arguments[1] in {
        "create", "edit", "merge", "comment", "review", "ready", "close", "reopen",
    }


def git_commit_command(command: str) -> bool:
    """True for one git commit, not a combined shell that hides the commit."""
    parsed = shell_tokens(command)
    if not parsed or any(item in {";", "&&", "||", "|", "&"} for item in parsed):
        return False
    head, arguments = command_head(parsed)
    return head == "git" and bool(arguments) and arguments[0] == "commit"


def commit_identity_pre_commit_reason(cwd: Path, commands: tuple[str, ...]) -> str:
    """PreToolUse: refuse git commit when ChaosEngine identity is out of scope (H-IDENTITY)."""
    if not any(git_commit_command(candidate) for candidate in commands):
        return ""
    module_path = _overlay_module("commit_identity.py")
    if not module_path.is_file():
        return ""
    try:
        spec = importlib.util.spec_from_file_location("chaos_engine_commit_identity_guard", module_path)
        if spec is None or spec.loader is None:
            return ""
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception:  # noqa: BLE001 - fail soft on import issues; hook must not crash
        return ""
    failures = module.pre_commit_identity_failures(cwd)
    return failures[0] if failures else ""




def _read_body_file(value: str) -> str | None:
    try:
        return Path(value).read_text(encoding="utf-8")
    except OSError:
        return None


def _shell_statements(command: str) -> list[str]:
    """Split on ``&&``, ``||``, and ``;`` outside quotes."""
    parts: list[str] = []
    buf: list[str] = []
    quote = ""
    index = 0
    while index < len(command):
        char = command[index]
        if quote:
            buf.append(char)
            if char == quote and command[index - 1] != "\\":
                quote = ""
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            buf.append(char)
            index += 1
            continue
        if command.startswith("&&", index) or command.startswith("||", index):
            parts.append("".join(buf))
            buf = []
            index += 2
            continue
        if char == ";":
            parts.append("".join(buf))
            buf = []
            index += 1
            continue
        buf.append(char)
        index += 1
    parts.append("".join(buf))
    return [part.strip() for part in parts if part.strip()]


def _pr_body_argument(arguments: list[str]) -> str | None:
    """Body text of ``gh pr create|edit`` arguments; None when absent or unreadable."""
    body = None
    for index, item in enumerate(arguments):
        flag, _, inline = item.partition("=")
        value = inline if inline else (arguments[index + 1] if index + 1 < len(arguments) else None)
        if value is None:
            continue
        if flag in {"--body-file", "-F"}:
            body = _read_body_file(value)
        elif flag in {"--body", "-b"}:
            body = value
    return body


def _assumption_errors(body: str) -> list[str]:
    mindset = _overlay_module("harness_mindset.py")
    spec = importlib.util.spec_from_file_location("chaos_engine_pr_body_mindset", mindset)
    if not mindset.is_file() or spec is None or spec.loader is None:
        return []
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        # The guard runs only in agent sessions, so this body is agentic by definition:
        # it must carry the marker, which is what makes CI apply the plan checks.
        marker = [] if module.is_agentic(body) else [
            f"agent PR body is missing the `{module.AGENTIC_MARKER}` marker (it identifies agentic PRs)"
        ]
        return list(module.assumption_section_errors(body)) + marker + list(
            module.plan_receipt_errors(body + "\n" + module.AGENTIC_MARKER))
    except Exception:  # nosec B110 - an unavailable checker must not block PR creation.
        return []


def _pr_body_block(commands: tuple[str, ...]) -> str:
    """Check a ``gh pr create|edit`` body for the riskiest-assumption section before it ships.

    CI's PR Body guard rejects a missing or link-free section, and a rerun keeps the
    old event body, so a fix then costs a push and a full CI round trip.
    """
    for command in commands:
        for statement in _shell_statements(command):
            head, arguments = command_head(shell_tokens(statement))
            if head != "gh" or arguments[:2] not in (["pr", "create"], ["pr", "edit"]):
                continue
            body = _pr_body_argument(arguments)
            errors = _assumption_errors(body) if body is not None else []
            if errors:
                return (
                    "PR body would fail the CI PR Body guard: " + errors[0] + ". It needs `## Riskiest assumption` "
                    "(one targeted test in backticks, or N/A), `## Plan`, "
                    "`retrieve: [store] used|skipped(<reason>)` lines, and `<!-- chaos-engine:agentic -->`; then rerun."
                )
    return ""


_OPEN_PR_ACTIONS = frozenset({"create", "ready", "reopen"})
_OPEN_PR_GH_TIMEOUT_SECONDS = 10


_GH_VALUE_FLAGS = frozenset({"-R", "--repo", "-h", "--hostname"})
_OPEN_PR_PAGE = 100
_OPEN_PR_PAGE_CAP = 1000


def _open_pr_verb(arguments: list[str] | tuple[str, ...]) -> str | None:
    """Return create|ready|reopen when `pr` is the gh subcommand, after global flags."""
    tokens = list(arguments)
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in _GH_VALUE_FLAGS:
            index += 2
            continue
        if token.startswith("-"):
            index += 1
            continue
        if token != "pr":
            return None
        verb = tokens[index + 1] if index + 1 < len(tokens) else ""
        return verb if verb in _OPEN_PR_ACTIONS else None
    return None


def _open_pr_action(commands: tuple[str, ...]) -> bool:
    for command in commands:
        for statement in _shell_statements(command):
            head, arguments = command_head(shell_tokens(statement))
            if head == "gh" and _open_pr_verb(arguments):
                return True
    return False


def _open_pr_config_path(cwd: Path) -> Path | None:
    candidates = (
        cwd / "chaos-engine" / "hooks" / "open-pr-advisory.json",
        Path(__file__).resolve().with_name("open-pr-advisory.json"),
    )
    for path in candidates:
        if path.is_file():
            return path
    return None


def _positive_config_int(value: object, key: str) -> int | str:
    """Return the integer, or an error that names ``key``."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return f"open-pr-advisory.json {key} must be a positive integer"
    return value


def _open_pr_cap(cwd: Path) -> tuple[int, str]:
    """Return ``(cap, error)``. A missing file uses review WIP 2 and 1 stream."""
    path = _open_pr_config_path(cwd)
    if path is None:
        return 2, ""
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return 0, "open-pr-advisory.json is not valid UTF-8"
    except OSError:
        return 0, "open-pr-advisory.json is not valid JSON"
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        return 0, "open-pr-advisory.json is not valid JSON"
    if not isinstance(raw, dict):
        return 0, "open-pr-advisory.json must be a JSON object"
    review_wip = _positive_config_int(raw.get("reviewWip", 2), "reviewWip")
    if isinstance(review_wip, str):
        return 0, review_wip
    streams = _positive_config_int(raw.get("streams", 1), "streams")
    if isinstance(streams, str):
        return 0, streams
    return review_wip * streams, ""


def _open_pr_skip(detail: str) -> None:
    print(f"open-pr advisory skipped: {detail}", file=sys.stderr)


def _open_pr_numbers(cwd: Path) -> list[int] | None:
    """Open pull-request numbers for ``@me``, or None when ``gh`` cannot be trusted.

    Closed and merged rows are ignored. Drafts stay in ``open``. None means do not advise.
    """
    gh = shutil.which("gh")
    if not gh:
        _open_pr_skip("gh missing")
        return None
    payload: object = None
    limit = _OPEN_PR_PAGE
    while True:
        try:
            completed = subprocess.run(  # nosec B603 - absolute gh from which, fixed argv.
                [
                    gh,
                    "pr",
                    "list",
                    "--author",
                    "@me",
                    "--state",
                    "open",
                    "--limit",
                    str(limit),
                    "--json",
                    "number,state",
                ],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=_OPEN_PR_GH_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired:
            _open_pr_skip("gh timed out")
            return None
        except OSError:
            _open_pr_skip("gh unavailable")
            return None
        if completed.returncode != 0:
            _open_pr_skip(f"gh exited {completed.returncode}")
            return None
        try:
            payload = json.loads(completed.stdout or "[]")
        except json.JSONDecodeError:
            _open_pr_skip("gh returned invalid JSON")
            return None
        if not isinstance(payload, list):
            _open_pr_skip("gh returned invalid JSON")
            return None
        if len(payload) < limit or limit >= _OPEN_PR_PAGE_CAP:
            break
        limit = min(limit * 2, _OPEN_PR_PAGE_CAP)
    numbers: list[int] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        state = item.get("state")
        if isinstance(state, str) and state.casefold() not in {"open", "draft"}:
            continue
        number = item.get("number")
        if isinstance(number, bool) or not isinstance(number, int) or number <= 0:
            continue
        if number not in numbers:
            numbers.append(number)
    return numbers


def _open_pr_pretool(event: dict, event_name: str, commands: tuple[str, ...]) -> tuple[str, str | None]:
    """Return ``(deny reason, advisory)``. The advisory does not deny the command."""
    if event_name != "PreToolUse" or not _open_pr_action(commands):
        return "", None
    cwd = Path(str(event.get("cwd") or Path.cwd()))
    cap, problem = _open_pr_cap(cwd)
    if problem:
        return problem, None
    numbers = _open_pr_numbers(cwd)
    if not numbers or len(numbers) < cap:
        return "", None
    listed = ", ".join(f"#{number}" for number in numbers)
    note = (
        f"Open pull requests are at the cap ({len(numbers)} of {cap}): {listed}. "
        "Finish, merge, or combine before opening another."
    )
    return "", note


def _operation_boundary_block(commands: tuple[str, ...], project: Path) -> str:
    """Force-push, private-remote, relayed-delete, and secret checks on the real command."""
    script = Path(__file__).resolve().parents[1] / "rules" / "operation_boundary.py"
    if not script.is_file():
        return ""
    spec = importlib.util.spec_from_file_location("chaos_engine_operation_boundary", script)
    if spec is None or spec.loader is None:
        return "operation boundary failed: checker unavailable"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for command in commands:
        hits = module.command_blocks(project, command)
        if hits:
            hit = str(hits[0])
            if hit == "force-push-without-approval":
                return "operation boundary: force-push-without-approval: " + module.force_push_hint(command)
            return "operation boundary: " + hit
    return ""


_OBSERVED_TOOL_EVENTS = frozenset({"PostToolUse", "PostToolUseFailure"})


def _post_tool_boundary(project: Path, commands: tuple[str, ...], event: dict, event_name: str) -> str:
    """Record the tool's real result and scan its stdout/stderr."""
    script = Path(__file__).resolve().parents[1] / "rules" / "operation_boundary.py"
    if not script.is_file():
        return ""
    spec = importlib.util.spec_from_file_location("chaos_engine_operation_boundary_post", script)
    if spec is None or spec.loader is None:
        return "operation boundary failed: checker unavailable"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = event.get("tool_response") or event.get("toolResponse") or event.get("tool_result")
    secret = module.output_secret_block(result, project)
    if secret:
        return "operation boundary: " + secret
    problem = module.observe_commands(
        project, commands, failed=_tool_result_failed(event_name, result),
    )
    if problem:
        return "operation boundary: " + problem
    return ""


def _overlay_push_block(commands: tuple[str, ...]) -> str:
    if not any(re.search(r"\bgit\s+push\b", command) for command in commands):
        return ""
    project = Path.cwd()
    git = shutil.which("git")
    if git is not None:
        try:
            completed = subprocess.run(  # nosec B603 - absolute git from which, fixed argv.
                [git, "rev-parse", "--show-toplevel"],
                cwd=project,
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode == 0 and completed.stdout.strip():
                project = Path(completed.stdout.strip())
        except OSError:
            # Non-git cwd: keep Path.cwd() as the project root for the checker.
            pass
    script = project / "scripts/ci/overlay_pre_push.py"
    if not script.is_file():
        return ""
    spec = importlib.util.spec_from_file_location("chaos_engine_overlay_pre_push", script)
    if spec is None or spec.loader is None:
        return "overlay pre-push contract failed: checker unavailable"
    module = importlib.util.module_from_spec(spec)
    captured = io.StringIO()
    try:
        with contextlib.redirect_stdout(captured):
            spec.loader.exec_module(module)
            failures = module.overlay_pre_push_failures(project)
    except Exception as error:
        # A checker crash is a contract failure. Leaving it uncaught makes the
        # hook protocol report invalid JSON, and the same push is retried.
        detail = str(error).strip().splitlines()[0] if str(error).strip() else type(error).__name__
        return "overlay pre-push contract failed: " + type(error).__name__ + ": " + detail
    if not failures:
        return ""
    return "overlay pre-push contract failed: " + str(failures[0])


def delivery_command(command: str) -> bool:
    parsed = shell_tokens(command)
    if not parsed or any(item in {";", "&&", "||", "|", "&"} for item in parsed):
        return False
    head, arguments = command_head(parsed)
    if head == "git" and arguments[:1] == ["push"]:
        return True
    if head != "gh" or len(arguments) < 2:
        return False
    return arguments[0] in {"pr", "issue"} and arguments[1] in {
        "create", "edit", "merge", "comment", "review", "ready", "close", "reopen"
    }


def terminal_delivery_command(command: str) -> bool:
    """True only for canonical final delivery-status verification."""
    return "delivery-status" in shell_tokens(command)


def pull_request_open_command(command: str) -> bool:
    """True for opening a pull request, which owes a watch until merge."""
    parsed = shell_tokens(command)
    if not parsed or any(item in {";", "&&", "||", "|", "&"} for item in parsed):
        return False
    head, arguments = command_head(parsed)
    return head == "gh" and arguments[:2] == ["pr", "create"]


def pull_request_merged_command(command: str) -> bool:
    """True for gh pr merge, not for delivery-status."""
    return confirmed_delivery_command(command) and not terminal_delivery_command(command)


def _enables_auto_merge(arguments: list[str]) -> bool:
    """True when ``gh pr merge --auto`` only arms merge and leaves the PR open.

    ``--auto=false`` is an immediate merge. Exit 0 on an arm is not delivery.
    """
    for arg in arguments:
        if arg == "--auto":
            return True
        if arg.startswith("--auto="):
            return arg.split("=", 1)[1].casefold() not in {"false", "0", "no"}
    return False


def confirmed_delivery_command(command: str) -> bool:
    """True for merge delivery that completes a PR without waiting on delivery-status.

    Intermediate pushes, draft PR create/edit, and ``gh pr merge --auto`` stay
    off this path so Learning Session never starts while the pull request is
    open. A successful ``gh pr merge`` without ``--auto`` is confirmed delivery
    even when chaos-engine files were untouched.
    """
    if terminal_delivery_command(command):
        return True
    parsed = shell_tokens(command)
    if not parsed or any(item in {";", "&&", "||", "|", "&"} for item in parsed):
        return False
    head, arguments = command_head(parsed)
    if head != "gh" or len(arguments) < 2:
        return False
    if arguments[0] != "pr" or arguments[1] != "merge":
        return False
    return not _enables_auto_merge(arguments)


_UNREADABLE_MERGE = object()
_MERGE_VALUE_FLAGS = frozenset({
    "--repo", "-R", "--match-head-commit", "--subject", "-t",
    "--body", "-b", "--body-file", "-F", "--author-email", "-A",
})
_PR_URL = re.compile(r"github\.com/([^/]+)/([^/]+)/pull/(\d+)")
_GITHUB_NAME = re.compile(r"^[A-Za-z0-9_.-]+\Z")


def _invokes_pr_merge(parsed: list[str]) -> bool:
    current: list[str] = []
    statements = [current]
    for token in parsed:
        if token in {";", "&&", "||", "|", "&"}:
            current = []
            statements.append(current)
            continue
        current.append(token)
    for statement in statements:
        head, arguments = command_head(statement)
        if head == "gh" and arguments[:2] == ["pr", "merge"]:
            return True
    return False


def pull_request_merge_target(command: str) -> str | object | None:
    """PR number or URL for one ``gh pr merge``, including ``--auto``.

    ``None`` means this statement is not a merge. ``""`` means merge the
    pull request for the current branch. ``_UNREADABLE_MERGE`` means a merge
    is present but its target cannot be isolated, so the caller fails closed.
    """
    parsed = shell_tokens(command)
    if not parsed:
        return None
    if any(item in {";", "&&", "||", "|", "&"} for item in parsed):
        return _UNREADABLE_MERGE if _invokes_pr_merge(parsed) else None
    head, arguments = command_head(parsed)
    if head != "gh" or arguments[:2] != ["pr", "merge"]:
        return None
    index = 2
    while index < len(arguments):
        arg = arguments[index]
        if arg.startswith("-") and "=" in arg:
            index += 1
            continue
        flag = arg.split("=", 1)[0]
        if flag in _MERGE_VALUE_FLAGS:
            if index + 1 >= len(arguments) or arguments[index + 1].startswith("-"):
                return _UNREADABLE_MERGE
            index += 2
            continue
        if arg.startswith("-"):
            index += 1
            continue
        return arg
    return ""


def _check_block_reason(check: object) -> str:
    """Empty when the check finished successfully. A short reason otherwise."""
    if not isinstance(check, Mapping):
        return "a check could not be read."
    name = str(check.get("name") or check.get("context") or "a check")
    conclusion = str(check.get("conclusion") or "").strip().upper()
    status = str(check.get("status") or "").strip().upper()
    state = str(check.get("state") or "").strip().upper()
    if state == "SUCCESS" or (status == "SUCCESS" and not conclusion):
        return ""
    if status == "COMPLETED" and conclusion == "SUCCESS":
        return ""
    if (status and status != "COMPLETED") or state in {"PENDING", "EXPECTED"}:
        return name + " has not finished."
    return name + " is not successful."


_OUTSIDE_REQUIRED_CONCLUSIONS = frozenset({"SKIPPED", "NEUTRAL"})


def _check_conclusion(check: Mapping) -> str:
    return str(check.get("conclusion") or check.get("state") or "").strip().upper()


def merge_readiness_reason(snapshot: Mapping) -> str:
    """Empty when merge is allowed. A denial when checks or review threads are not ready.

    A pending check is not success. An empty check list has not finished.
    A skipped required check is not success. When at least one check is
    required, only that set is decided: ``isRequired: false`` does not block.
    When no check is required, ``SKIPPED`` and ``NEUTRAL`` with
    ``isRequired: false`` stay outside the set, and a failure, cancellation,
    or pending check still blocks. An unmarked skip still blocks, so a probe
    that cannot read ``isRequired`` does not let every skip pass.
    ``DRAFT``, ``DIRTY``, and ``BLOCKED`` deny. ``BEHIND`` does not deny by itself.
    """
    error = str(snapshot.get("error") or "").strip()
    if error:
        return "ChaosEngine refused gh pr merge: " + error
    state = str(snapshot.get("mergeStateStatus") or "").strip().upper()
    if state in {"DRAFT", "DIRTY", "BLOCKED"}:
        return "ChaosEngine refused gh pr merge: merge state is " + state + "."
    if snapshot.get("hasNextPage") is True:
        return "ChaosEngine refused gh pr merge: review threads did not fit in one page."
    unresolved = snapshot.get("unresolved")
    if isinstance(unresolved, bool) or not isinstance(unresolved, int) or unresolved < 0:
        return "ChaosEngine refused gh pr merge: review threads could not be read."
    if unresolved:
        return "ChaosEngine refused gh pr merge: review comments are still open."
    checks = snapshot.get("checks")
    if not isinstance(checks, list) or not checks:
        return "ChaosEngine refused gh pr merge: CI checks have not finished."
    required_present = any(
        isinstance(check, Mapping) and check.get("isRequired") is True for check in checks
    )
    for check in checks:
        if isinstance(check, Mapping) and check.get("isRequired") is False:
            if required_present or _check_conclusion(check) in _OUTSIDE_REQUIRED_CONCLUSIONS:
                continue
        reason = _check_block_reason(check)
        if reason:
            return "ChaosEngine refused gh pr merge: " + reason
    return ""


def _gh_json(args: list[str]) -> tuple[object | None, str]:
    gh = shutil.which("gh")
    if not gh:
        return None, "gh is missing."
    try:
        completed = subprocess.run(  # nosec B603 - absolute gh from which, fixed argv.
            [gh, *args],
            capture_output=True,
            text=True,
            timeout=_OPEN_PR_GH_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None, "gh timed out."
    except OSError:
        return None, "gh could not be started."
    if completed.returncode != 0:
        return None, "gh could not read the pull request."
    try:
        return json.loads(completed.stdout or ""), ""
    except json.JSONDecodeError:
        return None, "gh returned invalid JSON."


def checks_from_rollup_contexts(nodes: list) -> list:
    """Map GraphQL status-check nodes to the dicts ``merge_readiness_reason`` reads.

    ``isRequired`` is copied only when GitHub returned a boolean. A missing flag
    stays unmarked so the gate treats that check as required.
    """
    checks: list = []
    for node in nodes:
        if not isinstance(node, Mapping):
            checks.append(node)
            continue
        if node.get("__typename") == "StatusContext":
            item: dict = {
                "context": str(node.get("context") or ""),
                "state": str(node.get("state") or ""),
            }
        else:
            item = {
                "name": str(node.get("name") or ""),
                "status": str(node.get("status") or ""),
                "conclusion": str(node.get("conclusion") or ""),
            }
        if isinstance(node.get("isRequired"), bool):
            item["isRequired"] = node["isRequired"]
        checks.append(item)
    return checks


def _marked_required_checks(owner: str, name: str, number: str, pr_id: str) -> tuple[list | None, str]:
    """Return checks with ``isRequired`` set, or ``(None, "")`` when the query cannot be read.

    A rollup that does not fit in one page is an error. A failed query falls
    back to the unmarked REST rollup instead of allowing every skip.
    """
    if not re.fullmatch(r"[A-Za-z0-9_]+", pr_id or ""):
        return None, ""
    query = (
        "query { repository(owner: \"%s\", name: \"%s\") { pullRequest(number: %d) "
        "{ commits(last: 1) { nodes { commit { statusCheckRollup { contexts(first: 100) "
        "{ pageInfo { hasNextPage } nodes { __typename "
        "... on CheckRun { name status conclusion isRequired(pullRequestId: \"%s\") } "
        "... on StatusContext { context state isRequired(pullRequestId: \"%s\") } "
        "} } } } } } } } }"
        % (owner, name, int(number), pr_id, pr_id)
    )
    graph, graph_error = _gh_json(["api", "graphql", "-f", "query=" + query])
    if graph_error or not isinstance(graph, dict) or graph.get("errors"):
        return None, ""
    try:
        commit = graph["data"]["repository"]["pullRequest"]["commits"]["nodes"][0]["commit"]
        contexts = commit["statusCheckRollup"]["contexts"]
        page = contexts["pageInfo"]
        nodes = contexts["nodes"]
    except (KeyError, TypeError, IndexError):
        return None, ""
    if not isinstance(page, dict) or not isinstance(nodes, list):
        return None, ""
    if page.get("hasNextPage") is True:
        return None, "CI checks did not fit in one page."
    return checks_from_rollup_contexts(nodes), ""


def live_merge_probe(target: str) -> dict:
    """Read check rollup and unresolved review threads. Fail closed on any gap."""
    view = ["pr", "view", "--json", "id,statusCheckRollup,url,mergeStateStatus"]
    if target:
        view.insert(2, target)
    payload, error = _gh_json(view)
    if error:
        return {"error": error}
    if not isinstance(payload, dict):
        return {"error": "gh could not read the pull request."}
    match = _PR_URL.search(str(payload.get("url") or ""))
    if match is None:
        return {"error": "the pull request URL could not be read."}
    owner, name, number = match.group(1), match.group(2), match.group(3)
    if _GITHUB_NAME.fullmatch(owner) is None or _GITHUB_NAME.fullmatch(name) is None:
        return {"error": "the pull request URL could not be read."}
    query = (
        "query { repository(owner: \"%s\", name: \"%s\") { pullRequest(number: %d) "
        "{ reviewThreads(first: 100) { pageInfo { hasNextPage } nodes { isResolved } } } } }"
        % (owner, name, int(number))
    )
    graph, graph_error = _gh_json(["api", "graphql", "-f", "query=" + query])
    if graph_error:
        return {"error": graph_error}
    if not isinstance(graph, dict) or graph.get("errors"):
        return {"error": "review threads could not be read."}
    try:
        threads = graph["data"]["repository"]["pullRequest"]["reviewThreads"]
        page = threads["pageInfo"]
        nodes = threads["nodes"]
    except (KeyError, TypeError):
        return {"error": "review threads could not be read."}
    if not isinstance(nodes, list) or not isinstance(page, dict):
        return {"error": "review threads could not be read."}
    unresolved = 0
    for node in nodes:
        if not isinstance(node, dict) or node.get("isResolved") is not True:
            unresolved += 1
    checks = payload.get("statusCheckRollup")
    if not isinstance(checks, list):
        checks = []
    marked, mark_error = _marked_required_checks(owner, name, number, str(payload.get("id") or ""))
    if mark_error:
        return {"error": mark_error}
    if marked is not None:
        checks = marked
    return {
        "checks": checks,
        "unresolved": unresolved,
        "hasNextPage": page.get("hasNextPage") is True,
        "mergeStateStatus": str(payload.get("mergeStateStatus") or ""),
    }


def _merge_command_statements(command: str) -> list[str]:
    """Split on ``&&``, ``||``, ``;``, and newlines that are outside quotes.

    A separator inside ``--body`` must stay one merge statement. A quote-blind
    split turns that statement into fragments ``shell_tokens`` cannot read, and
    the gate then allows the merge.

    An odd run of unquoted backslashes before a newline is a continuation:
    drop that one backslash and do not split. An even run is a real separator.
    A newline inside quotes stays in that statement.
    """
    parts: list[str] = []
    buf: list[str] = []
    quote = ""
    index = 0
    while index < len(command):
        char = command[index]
        if quote:
            buf.append(char)
            if char == quote and command[index - 1] != "\\":
                quote = ""
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            buf.append(char)
            index += 1
            continue
        if command.startswith("&&", index) or command.startswith("||", index):
            parts.append("".join(buf))
            buf = []
            index += 2
            continue
        if char == "\n":
            slashes = 0
            while slashes < len(buf) and buf[-1 - slashes] == "\\":
                slashes += 1
            if slashes % 2 == 1:
                buf.pop()
                index += 1
                continue
            parts.append("".join(buf))
            buf = []
            index += 1
            continue
        if char == ";":
            parts.append("".join(buf))
            buf = []
            index += 1
            continue
        buf.append(char)
        index += 1
    parts.append("".join(buf))
    return [part.strip() for part in parts if part.strip()]


def merge_before_ready_reason(command: str, probe=None) -> str:
    """Refuse ``gh pr merge`` until the required checks are ready and review threads are resolved.

    A skipped or neutral check outside the required set does not block. A failed,
    cancelled, or pending check blocks when it is required and when no check is
    marked required. An unmarked skip blocks. An empty check list is not success.
    ``--auto`` is not an exception. On a repository with auto-merge disabled
    that flag merges immediately, so a pending check must still deny it.
    """
    reader = live_merge_probe if probe is None else probe
    parts = _merge_command_statements(command) or [command]
    saw = False
    for part in parts:
        target = pull_request_merge_target(part)
        if target is None:
            continue
        saw = True
        if target is _UNREADABLE_MERGE:
            return "ChaosEngine refused gh pr merge: the command could not be read."
        try:
            snapshot = reader(target)
        except Exception:
            # Any probe failure denies the merge. Allowing it would merge on unread checks.
            return "ChaosEngine refused gh pr merge: the pull request checks could not be read."
        if not isinstance(snapshot, Mapping):
            return "ChaosEngine refused gh pr merge: the pull request checks could not be read."
        reason = merge_readiness_reason(snapshot)
        if reason:
            return reason
    if saw:
        return ""
    if not shell_tokens(command) and re.search(r"\bgh\s+pr\s+merge\b", command):
        return "ChaosEngine refused gh pr merge: the command could not be read."
    return ""


def learning_session_finalize_command(command: str) -> bool:
    """True only for one direct terminal Learning Session finalizer."""
    parsed = shell_tokens(command)
    if not parsed or any(item in {";", "&&", "||", "|", "&"} for item in parsed):
        return False
    head, arguments = command_head(parsed)
    if head not in {"py", "python", "python3"}:
        return False
    while arguments and arguments[0] in {"-3", "-u", "-B"}:
        arguments = arguments[1:]
    if len(arguments) < 4:
        return False
    script = arguments[0].replace("\\", "/").casefold()
    portable = (
        script.endswith("scripts/agents/learning_session.py")
        or script.endswith("chaos-engine/learning_session.py")
        or script.endswith(".chaos-engine/learning_session.py")
        or script.endswith("/learning_session.py")
        and ("chaos-engine" in script or "scripts/agents" in script)
    )
    return bool(
        portable
        and arguments[1] in {"finalize", "finalize-runtime"}
        and "--session-id" in arguments[2:]
    )


def read_only_diagnostic_command(command: str) -> bool:
    parsed = shell_tokens(command)
    if not parsed or any(item in {";", "&&", "||", "|", "&"} for item in parsed):
        return False
    head, arguments = command_head(parsed)
    if head in {"rg", "grep", "get-content"}:
        return True
    if head != "git" or not arguments:
        return False
    if arguments[0] in {"status", "diff", "show", "log", "rev-parse"}:
        return True
    return arguments == ["branch", "--show-current"]


def checkpoint_reason(checkpoint: dict, session_id: str = "<session-id>") -> str:
    return reflection.recovery_message(_reflection_controller(), session_id, checkpoint)


def _reflection_controller() -> Path:
    return Path(__file__).resolve().with_name("reflection.py")


def _loads_same_reflection_controller(path: Path) -> bool:
    """True for the installed controller or an adapter that loads that file."""
    try:
        resolved = path.resolve()
    except OSError:
        return False
    controller = _reflection_controller()
    if resolved == controller:
        return True
    if resolved.name != "reflection.py":
        return False
    try:
        text = resolved.read_text(encoding="utf-8").replace("\\", "/")
    except OSError:
        return False
    return "chaos-engine/hooks/reflection.py" in text or ".chaos-engine/hooks/reflection.py" in text


def _reflection_invocation(command: str) -> tuple[Path, str] | None:
    arguments = shell_tokens(command)
    if not arguments or any(item in {";", "&&", "||", "|", "&"} for item in arguments):
        return None
    head, remaining = command_head(arguments)
    if head not in {"py", "python", "python3"}:
        return None
    script_index = 0
    while script_index < len(remaining) and remaining[script_index] in {"-3", "-u", "-B"}:
        script_index += 1
    if script_index + 1 >= len(remaining):
        return None
    supplied = Path(remaining[script_index])
    if not supplied.is_absolute():
        supplied = Path.cwd() / supplied
    operation = remaining[script_index + 1]
    if operation not in {"receipt", "trigger", "non-attempt"} or "--session-id" not in remaining:
        return None
    return supplied, operation


def reflection_recovery(command: str) -> str | None:
    invocation = _reflection_invocation(command)
    if invocation is None:
        return None
    supplied, operation = invocation
    if not _loads_same_reflection_controller(supplied):
        return None
    return operation


def denied_reflection_retry(command: str) -> bool:
    """A reflection CLI attempt whose script is not the installed controller."""
    invocation = _reflection_invocation(command)
    return invocation is not None and reflection_recovery(command) is None


def tokens(command: str) -> list[str]:
    try:
        return shlex.split(command, posix=True)
    except ValueError:
        return []


def command_head(arguments: list[str]) -> tuple[str, list[str]]:
    index = 0
    while index < len(arguments):
        item = arguments[index]
        if ENV_ASSIGNMENT.match(item):
            index += 1
            continue
        head = re.split(r"[/\\]", item.strip("\"'"))[-1].casefold()
        if head in {"command", "env", "sudo", "timeout"}:
            index += 1
            while index < len(arguments) and (
                arguments[index].startswith("-") or ENV_ASSIGNMENT.match(arguments[index])
            ):
                index += 1
            if head == "timeout" and index < len(arguments) and re.fullmatch(
                r"\d+[smhd]?", arguments[index]
            ):
                index += 1
            continue
        return head, arguments[index + 1 :]
    return "", []


def catastrophic_target(target: str) -> bool:
    normalized = posixpath.normpath(re.sub(r"/+", "/", target.replace("\\", "/")))
    if normalized in {"/", "/*", "~", "$home", "${home}"}:
        return True
    return bool(re.fullmatch(r"/(?:bin|boot|dev|etc|lib|sbin|usr|var)(?:/\*)?", normalized))


def broad_rm(command: str) -> bool:
    head, arguments = command_head(tokens(command))
    if head != "rm":
        return False
    recursive = False
    targets: list[str] = []
    for argument in arguments:
        lowered = argument.casefold()
        if lowered == "--recursive":
            recursive = True
        elif lowered.startswith("-") and not lowered.startswith("--"):
            recursive = recursive or "r" in lowered
        else:
            targets.append(lowered)
    return recursive and any(catastrophic_target(target) for target in targets)


_SEGMENT = re.compile(r"[A-Za-z0-9_.-]+\Z")
_RAW_HOST = "raw.githubusercontent.com"
_INSTALL_DIR = "chaos-engine"
_INSTALL_SCRIPT = "install.sh"


def _installer_url(url: str) -> tuple[str, str] | None:
    """Owner and repo for a raw install.sh URL, else None.

    The longer ``/chaos-engine/install.sh`` marker wins so a nested script is
    not parsed as the repository-root ``install.sh`` one-liner.
    """
    prefix = "https://" + _RAW_HOST + "/"
    if not url.startswith(prefix):
        return None
    marker = ""
    for candidate in (
        "/" + _INSTALL_DIR + "/" + _INSTALL_SCRIPT,
        "/" + _INSTALL_SCRIPT,
    ):
        if url.endswith(candidate):
            marker = candidate
            break
    if not marker:
        return None
    parts = url[len(prefix) : -len(marker)].split("/")
    if len(parts) < 3:
        return None
    owner, repo, *ref = parts
    if _SEGMENT.fullmatch(owner) is None or _SEGMENT.fullmatch(repo) is None:
        return None
    if not ref or any(
        _SEGMENT.fullmatch(part) is None or part in {".", ".."} for part in ref
    ):
        return None
    return owner, repo


# Same ids as bootstrap.INSTALL_HOST_IDS. Closed set so a host token cannot
# hide a substitution. Fail closed if the installer list grows.
_INSTALL_HOST_IDS = frozenset({
    "claude",
    "codex",
    "grok",
    "gemini",
    "copilot",
    "opencode",
    "cursor",
    "antigravity",
    "agy",
    "grok-bot",
})
_STDOUT_REDIRECT_OPS = frozenset({">", ">>", "1>", "1>>", "2>", "2>>", "&>", "&>>"})
_STDOUT_DUP = frozenset({"2>&1", "1>&2"})
_ATTACHED_STDOUT = re.compile(r"(?:&>>?|[12]?>>?)[^$`<>()|&;\s]+\Z")
_PLAIN_REDIRECT_TARGET = re.compile(r"[A-Za-z0-9_./~@+=,:-]+\Z")


def _without_trailing_stdout_redirects(argv: list[str]) -> list[str]:
    """Drop a trailing stdout redirect. Leave stdin and substitutions in place."""
    items = list(argv)
    while items:
        last = items[-1]
        if last in _STDOUT_DUP:
            items.pop()
            continue
        if _ATTACHED_STDOUT.fullmatch(last):
            items.pop()
            continue
        if (
            len(items) >= 2
            and items[-2] in _STDOUT_REDIRECT_OPS
            and _PLAIN_REDIRECT_TARGET.fullmatch(items[-1])
        ):
            items = items[:-2]
            continue
        break
    return items


def _installer_shell(shell: list[str], url: str) -> bool:
    """True for ``bash -s -- URL`` plus optional ``--hosts <id>`` and stdout redirects."""
    if len(shell) < 4 or shell[:4] != ["bash", "-s", "--", url]:
        return False
    extra = _without_trailing_stdout_redirects(shell[4:])
    if not extra:
        return True
    return len(extra) == 2 and extra[0] == "--hosts" and extra[1] in _INSTALL_HOST_IDS


def documented_installer_command(command: str) -> tuple[str, str] | None:
    """Owner and repo when one statement is ``curl -fsSL URL | bash -s -- URL``.

    The tail may be ``--hosts <install client id>`` and stdout redirects.
    Compounds are not one statement; the scope check walks those separately.
    """
    statements = [part.strip() for part in re.split(r"&&|\|\||;|\r?\n", command) if part.strip()]
    if len(statements) != 1:
        return None
    stages = [part.strip() for part in re.split(r"(?<!\|)\|(?!\|)", statements[0]) if part.strip()]
    if len(stages) != 2:
        return None
    try:
        download = shlex.split(stages[0], posix=True)
        shell = shlex.split(stages[1], posix=True)
    except ValueError:
        return None
    if len(download) != 3 or download[0] != "curl" or download[1] != "-fsSL":
        return None
    if not _installer_shell(shell, download[2]):
        return None
    return _installer_url(download[2])


def _origin_slug(project: Path) -> str:
    git = shutil.which("git")
    if git is None:
        return ""
    try:
        completed = subprocess.run(  # nosec B603 - absolute git from which, fixed argv.
            [git, "remote", "get-url", "origin"],
            cwd=project,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return ""
    if completed.returncode != 0:
        return ""
    match = re.search(
        r"github\.com[:/]([\w.-]+/[\w.-]+?)(?:\.git)?/?$",
        completed.stdout.strip(),
    )
    return match.group(1) if match else ""


# Published consumer one-liners. Plaintext slugs; both URL shapes are allowed.
_PUBLISHED_INSTALLERS = frozenset({
    "ShaftHQ/SHAFT_ENGINE".casefold(),
    "ShaftHQ/chaosengine-harness".casefold(),
})
_INSTALLER_ORIGIN_DENIAL = (
    "ChaosEngine rejected this install.sh pipe: the URL owner/repo is not "
    "this checkout's GitHub origin and is not the published consumer one-liner. "
    "Download the script, then run that file."
)


def documented_installer_for_project(command: str, project: Path) -> bool:
    """True for this checkout's GitHub origin installer, or the published consumer one-liner."""
    parsed = documented_installer_command(command)
    if parsed is None:
        return False
    owner, repo = parsed
    slug = f"{owner}/{repo}".casefold()
    if slug in _PUBLISHED_INSTALLERS:
        return True
    return slug == _origin_slug(project).casefold()


def catastrophic_posix(command: str) -> bool:
    if any(
        command_head(tokens(stage))[0] in DOWNLOADERS
        and any(command_head(tokens(later))[0] in SHELLS for later in pipeline[index + 1 :])
        for pipeline in (re.split(r"(?<!\|)\|(?!\|)", statement) for statement in re.split(r"&&|\|\||;|\r?\n", command))
        for index, stage in enumerate(pipeline)
    ):
        return True
    for segment in re.split(r"&&|\|\||;|\r?\n", command):
        head, arguments = command_head(tokens(segment))
        if head == "rm" and broad_rm(segment):
            return True
        if head == "find" and arguments and catastrophic_target(arguments[0]) and (
            "-delete" in arguments or "-exec" in arguments
        ):
            return True
        if head == "dd" and any(re.fullmatch(r"of=/dev/(?:disk|hd|mmcblk|nvme|sd|vd|xvd).+", item) for item in arguments):
            return True
        if re.fullmatch(r"mkfs(?:\.[a-z0-9]+)?", head) and any(item.startswith("/dev/") for item in arguments):
            return True
        if head == "chmod":
            values = [item for item in arguments if not item.startswith("-")]
            if len(values) >= 2 and re.fullmatch(r"[0-7]*777[0-7]*", values[0]) and catastrophic_target(values[1]):
                return True
    return bool(re.search(r": ?\(\)\s*\{", command))


def wrapped_exec_commands(source: str) -> tuple[str, ...]:
    commands: list[str] = []
    for match in re.finditer(
        r'''\btools\.exec_command\s*\(\s*\{.*?\b(?:cmd|command)\s*:\s*(?P<literal>"(?:\\.|[^"\\])*")''',
        source,
        re.DOTALL,
    ):
        try:
            command = json.loads(match.group("literal"))
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(command, str) and command:
            commands.append(command)
    return tuple(commands)


def wrapped_exec_call_count(source: str) -> int:
    return len(re.findall(r"\btools\s*\.\s*exec_command\s*\(", source))


_UNINSPECTED_PROCESS = "\x00uninspected-process"
_INDIRECTION_LIMIT = 4
_SCRIPT_CAP = 256 * 1024
_PY_LANGS = frozenset({"python", "python3", "py"})
_JS_LANGS = frozenset({"node", "deno", "nodejs"})
_SHELL_LANGS = frozenset({"bash", "sh", "zsh", "pwsh", "powershell"})
_PY_ARGV = frozenset({"run", "call", "check_call", "check_output", "Popen"})
_PY_STRING = frozenset({"system", "popen", "getoutput", "getstatusoutput"})
_PY_VECTOR = frozenset({"execv", "execve", "execvp", "execvpe"})
_PY_LISTARGS = frozenset({"execl", "execle", "execlp", "execlpe"})
_HEREDOC_START = re.compile(
    r"(?P<lang>python3|python|py|node|deno|bash|sh|zsh|pwsh|powershell)\b"
    r".*?<<-?\s*(?P<quote>['\"]?)(?P<delim>[A-Za-z_][A-Za-z0-9_]*)(?P=quote)\s*$"
)
_JS_CALL = re.compile(
    r"\b(?:execFileSync|execSync|spawnSync|execFile|execaCommandSync|execaCommand|execaSync|execa|spawn|fork|exec)\s*\("
)
_DIRECT_TOOLS_CALL = re.compile(r"\s*\.\s*[A-Za-z_$][\w$]*\s*\(")


def _mask_js_literals(source: str) -> str:
    """Blank strings and comments so an identifier scan sees code only."""
    out: list[str] = []
    index = 0
    length = len(source)
    while index < length:
        char = source[index]
        nxt = source[index + 1] if index + 1 < length else ""
        if char == "/" and nxt == "/":
            while index < length and source[index] != "\n":
                out.append(" ")
                index += 1
            continue
        if char == "/" and nxt == "*":
            while index + 1 < length and not (source[index] == "*" and source[index + 1] == "/"):
                out.append("\n" if source[index] == "\n" else " ")
                index += 1
            out.extend("  ")
            index = min(length, index + 2)
            continue
        if char in {"'", '"', "`"}:
            quote = char
            out.append(" ")
            index += 1
            while index < length:
                if source[index] == "\\":
                    out.append(" ")
                    index += 1
                    if index < length:
                        out.append(" ")
                        index += 1
                    continue
                if source[index] == quote:
                    out.append(" ")
                    index += 1
                    break
                out.append("\n" if source[index] == "\n" else " ")
                index += 1
            continue
        out.append(char)
        index += 1
    return "".join(out)


def _indirect_tools_use(source: str) -> bool:
    """True when ``tools`` or ``ALL_TOOLS`` is not a direct ``tools.name(`` call."""
    if not source:
        return False
    masked = _mask_js_literals(source)
    if re.search(r"\bALL_TOOLS\b", masked):
        return True
    for match in re.finditer(r"\btools\b", masked):
        if _DIRECT_TOOLS_CALL.match(masked[match.end() :]) is None:
            return True
    return False


def _literals_guarded(strings: list[str]) -> bool:
    folded = {item.casefold() for item in strings}
    blob = "\n".join(folded)
    if "git" in folded and folded & {"push", "reset", "merge"}:
        return True
    if "gh" in folded and "merge" in folded:
        return True
    if "rm" in folded and folded & {"-r", "-rf", "-fr", "--recursive"}:
        return True
    if re.search(r"\bgit\s+(?:push|reset|merge)\b", blob):
        return True
    if re.search(r"\bgh\s+pr\s+merge\b", blob):
        return True
    if re.search(r"\brm\s+(?:-r|-rf|-fr|--recursive)\b", blob):
        return True
    return False


def _literal_str(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _literal_argv(node: ast.AST) -> list[str] | None:
    if not isinstance(node, (ast.List, ast.Tuple)):
        return None
    items: list[str] = []
    for elt in node.elts:
        text = _literal_str(elt)
        if text is None:
            return None
        items.append(text)
    return items


def _py_call_kind(func: ast.AST) -> str | None:
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        owner, name = func.value.id, func.attr
        if owner == "subprocess" and name in _PY_ARGV:
            return "argv"
        if owner == "subprocess" and name in {"getoutput", "getstatusoutput"}:
            return "string"
        if owner == "os" and name in _PY_STRING:
            return "string"
        if owner == "os" and name in _PY_VECTOR:
            return "vector"
        if owner == "os" and name in _PY_LISTARGS:
            return "listargs"
        return None
    if isinstance(func, ast.Name) and func.id in _PY_ARGV:
        return "argv"
    return None


def _py_literal_command(node: ast.Call, kind: str) -> str | None:
    if not node.args:
        return None
    first = node.args[0]
    if kind == "string":
        return _literal_str(first)
    if kind == "argv":
        argv = _literal_argv(first)
        if argv is not None:
            return shlex.join(argv) if argv else ""
        return _literal_str(first)
    if kind == "vector" and len(node.args) >= 2:
        argv = _literal_argv(node.args[1])
        return shlex.join(argv) if argv else None
    if kind == "listargs":
        parts: list[str] = []
        for arg in node.args:
            text = _literal_str(arg)
            if text is None:
                return None
            parts.append(text)
        return shlex.join(parts) if parts else None
    return None


def _python_process_commands(source: str) -> tuple[tuple[str, ...], bool]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return (), False
    commands: list[str] = []
    hidden = False
    literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        kind = _py_call_kind(node.func)
        if kind is None:
            continue
        command = _py_literal_command(node, kind)
        if command is None:
            hidden = hidden or _literals_guarded(literals)
        elif command:
            commands.append(command)
    return tuple(commands), hidden


def _skip_js_ws(source: str, index: int) -> int:
    while index < len(source) and source[index] in " \t\r\n":
        index += 1
    return index


def _read_js_string(source: str, index: int) -> tuple[str | None, int]:
    quote = source[index]
    index += 1
    chars: list[str] = []
    while index < len(source):
        char = source[index]
        if char == "\\":
            if index + 1 >= len(source):
                return None, index + 1
            chars.append(source[index + 1])
            index += 2
            continue
        if char == quote:
            text = "".join(chars)
            if quote == "`" and "${" in text:
                return None, index + 1
            return text, index + 1
        chars.append(char)
        index += 1
    return None, index


def _read_js_array(source: str, index: int) -> tuple[list[str] | None, int]:
    index += 1
    items: list[str] = []
    while index < len(source):
        index = _skip_js_ws(source, index)
        if index < len(source) and source[index] == "]":
            return items, index + 1
        if index >= len(source) or source[index] not in "'\"`":
            return None, index
        text, index = _read_js_string(source, index)
        if text is None:
            return None, index
        items.append(text)
        index = _skip_js_ws(source, index)
        if index < len(source) and source[index] == ",":
            index += 1
    return None, index


def _read_js_value(source: str, index: int) -> tuple[object, int]:
    index = _skip_js_ws(source, index)
    if index >= len(source):
        return None, index
    char = source[index]
    if char in "'\"`":
        text, index = _read_js_string(source, index)
        return text, index
    if char == "[":
        return _read_js_array(source, index)
    return None, index


def _js_string_literals(source: str) -> list[str]:
    found: list[str] = []
    index = 0
    while index < len(source):
        if source[index] in "'\"`":
            text, index = _read_js_string(source, index)
            if text:
                found.append(text)
            continue
        index += 1
    return found


def _js_command_from(name: str, first: object, second: object) -> str | None:
    shell_names = {"execSync", "exec", "execaCommand", "execaCommandSync"}
    if name in shell_names and isinstance(first, str):
        return first
    if isinstance(first, list):
        return shlex.join(first) if first else ""
    if isinstance(first, str) and isinstance(second, list):
        return shlex.join([first, *second])
    if isinstance(first, str) and name in {"spawn", "spawnSync", "execFile", "execFileSync", "fork", "execa", "execaSync"}:
        return first
    return None


def _js_process_commands(source: str) -> tuple[tuple[str, ...], bool]:
    commands: list[str] = []
    hidden = False
    literals = _js_string_literals(source)
    for match in _JS_CALL.finditer(source):
        name = match.group(0).split("(", 1)[0]
        first, index = _read_js_value(source, match.end())
        second = None
        comma = _skip_js_ws(source, index)
        if comma < len(source) and source[comma] == ",":
            second, _index = _read_js_value(source, comma + 1)
        command = _js_command_from(name, first, second)
        if command is None:
            if _literals_guarded(literals):
                hidden = True
        elif command:
            commands.append(command)
    return tuple(commands), hidden


def _flag_value(arguments: list[str], flags: tuple[str, ...]) -> str | None:
    short_c = "-c" in flags
    index = 0
    while index < len(arguments):
        arg = arguments[index]
        if arg in flags:
            return arguments[index + 1] if index + 1 < len(arguments) else None
        for flag in flags:
            if flag.startswith("--") and arg.startswith(flag + "="):
                return arg.split("=", 1)[1]
        if (
            short_c
            and arg.startswith("-")
            and not arg.startswith("--")
            and arg not in {"-", "-c"}
            and "c" in arg[1:]
        ):
            return arguments[index + 1] if index + 1 < len(arguments) else None
        index += 1
    return None


def _positional_script(arguments: list[str], value_flags: tuple[str, ...]) -> str | None:
    index = 0
    while index < len(arguments):
        arg = arguments[index]
        if arg == "--":
            nxt = arguments[index + 1] if index + 1 < len(arguments) else ""
            return nxt or None
        if arg == "-":
            return None
        if arg.startswith("-"):
            bare = arg.split("=", 1)[0]
            if bare in value_flags and "=" not in arg:
                index += 2
                continue
            index += 1
            continue
        return arg
    return None


def _path_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _script_path(script: str, cwd: Path) -> Path | None:
    text = script.replace("\\", "/")
    path = Path(text)
    if not path.is_absolute():
        path = cwd / path
    try:
        return path.resolve()
    except OSError:
        return None


def _install_roots(cwd: Path) -> tuple[Path, ...]:
    """cwd up through the retrieve project root, and no further."""
    try:
        current = cwd.resolve()
    except OSError:
        return (cwd,)
    stop = current
    if justification is not None:
        try:
            stop = justification.project_root(cwd).resolve()
        except OSError:
            stop = current
    found: list[Path] = []
    seen: set[Path] = set()
    while current not in seen:
        seen.add(current)
        found.append(current)
        if current == stop or current.parent == current:
            break
        if stop != current and stop not in current.parents:
            break
        current = current.parent
    return tuple(found)


def _is_harness_source_tool(resolved: Path) -> bool:
    """True for this repository's root ``tool.py``, not a nested copy."""
    if resolved.name != "tool.py":
        return False
    parent = resolved.parent
    return (parent / "hooks" / "guard.py").is_file() and (parent / "runtime" / "hosts.py").is_file()


def _is_project_tool_py(script: str, cwd: Path) -> bool:
    """True for this checkout's tool.py, including a child overlay under a parent git root."""
    resolved = _script_path(script, cwd)
    if resolved is None:
        return False
    if _is_harness_source_tool(resolved):
        return True
    for root in _install_roots(cwd):
        try:
            if resolved == (root / ".chaos-engine" / "tool.py").resolve():
                return True
        except OSError:
            continue
    return False


def _read_script(script: str, cwd: Path) -> str | None:
    if not script or script == "-" or script.startswith("-"):
        return None
    path = Path(script)
    if not path.is_absolute():
        path = cwd / path
    try:
        resolved = path.resolve()
        roots = [cwd.resolve(), Path(tempfile.gettempdir()).resolve()]
    except OSError:
        return None
    for key in ("TMPDIR", "TEMP", "TMP"):
        value = os.environ.get(key, "").strip()
        if not value:
            continue
        try:
            roots.append(Path(value).resolve())
        except OSError:
            continue
    if not resolved.is_file() or not any(_path_within(resolved, root) for root in roots):
        return None
    try:
        if resolved.stat().st_size > _SCRIPT_CAP:
            return None
        return resolved.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _heredoc_segments(command: str) -> list[tuple[str, str]]:
    lines = command.splitlines()
    found: list[tuple[str, str]] = []
    index = 0
    while index < len(lines):
        match = _HEREDOC_START.search(lines[index])
        if match is None:
            index += 1
            continue
        delim = match.group("delim")
        body: list[str] = []
        index += 1
        while index < len(lines) and lines[index].strip() != delim:
            body.append(lines[index])
            index += 1
        found.append((match.group("lang"), "\n".join(body)))
        index += 1
    return found


def _code_bodies(command: str, cwd: Path) -> list[tuple[str, str, str]]:
    bodies: list[tuple[str, str, str]] = []
    heredocs = _heredoc_segments(command)
    for lang, body in heredocs:
        kind = "shell" if lang in _SHELL_LANGS else "code"
        bodies.append((lang, body, kind))
    parsed = tokens(command)
    if not parsed:
        return bodies
    head, arguments = command_head(parsed)
    lang = head.removesuffix(".exe")
    if lang not in _PY_LANGS | _JS_LANGS | _SHELL_LANGS:
        return bodies
    if lang in _PY_LANGS:
        code = _flag_value(arguments, ("-c",))
        if code is not None:
            return [*bodies, (lang, code, "code")]
        if heredocs:
            return bodies
        script = _positional_script(arguments, ("-W", "-X", "-m", "-Q"))
        if script and _is_project_tool_py(script, cwd):
            return bodies
        text = _read_script(script, cwd) if script else None
        if text is not None:
            bodies.append((lang, text, "code"))
        return bodies
    if lang == "deno":
        if arguments and arguments[0] == "eval":
            rest = arguments[2:] if len(arguments) > 1 and arguments[1] == "--" else arguments[1:]
            for arg in rest:
                if not arg.startswith("-"):
                    return [*bodies, (lang, arg, "code")]
        return bodies
    if lang in _JS_LANGS:
        code = _flag_value(arguments, ("-e", "--eval"))
        if code is not None:
            return [*bodies, (lang, code, "code")]
        if heredocs:
            return bodies
        script = _positional_script(arguments, ("-r", "--require"))
        text = _read_script(script, cwd) if script else None
        if text is not None:
            bodies.append(("node", text, "code"))
        return bodies
    code = _flag_value(arguments, ("-c", "--command", "-Command", "-C"))
    if code is not None:
        return [*bodies, (lang, code, "shell")]
    if heredocs:
        return bodies
    script = _flag_value(arguments, ("-File", "-f")) if lang in {"pwsh", "powershell"} else None
    if script is None:
        script = _positional_script(arguments, ())
    text = _read_script(script, cwd) if script else None
    if text is not None:
        bodies.append((lang, text, "shell"))
    return bodies


def _language_commands(lang: str, body: str) -> tuple[tuple[str, ...], bool]:
    if lang in _PY_LANGS:
        return _python_process_commands(body)
    if lang in _JS_LANGS:
        return _js_process_commands(body)
    return (body,) if body.strip() else (), False


def _nested_commands(command: str, cwd: Path, depth: int) -> tuple[list[str], bool]:
    if depth >= _INDIRECTION_LIMIT or not command.strip():
        return [], False
    found: list[str] = []
    hidden = False
    for lang, body, kind in _code_bodies(command, cwd):
        if kind == "shell":
            found.append(body)
            inner, nested_hidden = _nested_commands(body, cwd, depth + 1)
            found.extend(inner)
            hidden = hidden or nested_hidden
            continue
        extracted, nested_hidden = _language_commands(lang, body)
        hidden = hidden or nested_hidden
        for item in extracted:
            found.append(item)
            inner, item_hidden = _nested_commands(item, cwd, depth + 1)
            found.extend(inner)
            hidden = hidden or item_hidden
    return found, hidden


def _inspected_commands(commands: tuple[str, ...], cwd: Path) -> tuple[str, ...]:
    """Commands plus static inner commands. Nothing here is executed."""
    extra: list[str] = []
    hidden = False
    for command in commands:
        if command == _UNINSPECTED_PROCESS:
            continue
        inner, command_hidden = _nested_commands(command, cwd, 0)
        extra.extend(inner)
        hidden = hidden or command_hidden
    if hidden:
        extra.append(_UNINSPECTED_PROCESS)
    return tuple(dict.fromkeys((*commands, *extra)))


def functions_exec_source(tool_input: object) -> str:
    if isinstance(tool_input, str):
        return tool_input
    if isinstance(tool_input, dict):
        for key in ("input", "source", "code"):
            source = tool_input.get(key)
            if isinstance(source, str):
                return source
    return ""


def functions_exec_direct_command(tool_input: object) -> str:
    if isinstance(tool_input, dict):
        command = tool_input.get("cmd") or tool_input.get("command")
        if isinstance(command, str):
            return command
    return ""


def _event_commands(tool_name: str, tool_input: object) -> tuple[str, ...]:
    functions_source = functions_exec_source(tool_input)
    functions_direct = functions_exec_direct_command(tool_input)
    if tool_name == "functions.exec" and functions_direct:
        return (functions_direct,)
    if tool_name == "functions.exec" and functions_source:
        return wrapped_exec_commands(functions_source)
    if not isinstance(tool_input, dict):
        return ()
    command = str(tool_input.get("command") or tool_input.get("cmd") or "")
    return (command,) if command else ()


def _tool_result_failed(event_name: str, result: object) -> bool:
    if event_name == "PostToolUseFailure":
        return True
    return bool(
        isinstance(result, dict)
        and (
            result.get("isError") is True
            or result.get("interrupted") is True
            or str(result.get("status", "")).casefold() in {"error", "failed", "failure"}
            or result.get("exit_code", result.get("exitCode", 0)) not in {0, None}
        )
    )


def _command_is_destructive(command: str) -> bool:
    if command == _UNINSPECTED_PROCESS:
        return True
    folded = command.casefold()
    broad_remove = (
        "remove-item" in folded
        and "-recurse" in folded
        and (ROOT_DRIVE.search(command) is not None or "$home" in folded or "~" in command)
    )
    return catastrophic_posix(command) or "git reset --hard" in folded or broad_remove


STASH_READ_ONLY = frozenset({"list", "show"})
GIT_OPTIONS_WITH_VALUE = frozenset({"-c", "-C", "--git-dir", "--work-tree", "--namespace"})
STASH_R8_REASON = (
    "R8 (#6223): `git stash{sub}` mutates the stash list in the shared .git, which this "
    "checkout shares with its linked worktrees, so another session can pop or drop it. "
    "Commit to your own branch instead (`git add -A && git commit -m wip`, amend or reset "
    "later), and take baselines from a separate `git worktree add --detach <dir> <base-ref>`. "
    "Read-only `git stash list` / `git stash show` stay allowed."
)


def _stash_invocation(command: str) -> tuple[bool, str, str]:
    """Return (mutating stash, subcommand, -C directory) for one shell segment."""
    head, arguments = command_head(tokens(command))
    if head not in {"git", "git.exe"}:
        return False, "", ""
    directory = ""
    index = 0
    while index < len(arguments) and arguments[index].startswith("-"):
        option = arguments[index]
        if option in GIT_OPTIONS_WITH_VALUE and index + 1 < len(arguments):
            if option == "-C":
                directory = arguments[index + 1]
            index += 2
            continue
        index += 1
    if index >= len(arguments) or arguments[index] != "stash":
        return False, "", ""
    rest = [item for item in arguments[index + 1 :] if not item.startswith("-")]
    subcommand = rest[0].casefold() if rest else ""
    return subcommand not in STASH_READ_ONLY, subcommand, directory


def shares_git_directory(cwd: Path) -> bool:
    """True inside a linked worktree, or a main checkout that has linked worktrees."""
    for candidate in (cwd, *cwd.parents):
        marker = candidate / ".git"
        if marker.is_file():
            try:
                return "/worktrees/" in marker.read_text(encoding="utf-8").replace("\\", "/")
            except OSError:
                return False
        if marker.is_dir():
            worktrees = marker / "worktrees"
            return worktrees.is_dir() and any(worktrees.iterdir())
    return False


def _delete_guard():
    """#7251: core module one level up (installed `.chaos-engine/` and source `chaos-engine/`)."""
    path = _overlay_module("delete_guard.py")
    if not path.is_file():
        return None
    specification = importlib.util.spec_from_file_location("chaos_engine_delete_guard", path)
    if specification is None or specification.loader is None:
        return None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def delete_guard_reason(commands: tuple[str, ...], cwd: Path) -> str:
    """Refuse deletes of untracked, dirty, or unpushed work (#7251); unsure parse refuses."""
    guard = _delete_guard()
    if guard is None:
        return ""
    for command in commands:
        reason = guard.block_reason(command, cwd, cwd)
        if reason:
            return reason
    return ""


def linked_worktree_stash_reason(commands: tuple[str, ...], cwd: Path) -> str:
    for command in commands:
        for segment in re.split(r"&&|\|\||;|\||\r?\n", command):
            mutating, subcommand, directory = _stash_invocation(segment)
            if not mutating:
                continue
            target = (cwd / directory) if directory else cwd
            if shares_git_directory(target.resolve()):
                return STASH_R8_REASON.format(sub=f" {subcommand}" if subcommand else "")
    return ""


def _enhancement_disposition():
    path = _overlay_module("enhancement_disposition.py")
    if not path.is_file():
        return None
    specification = importlib.util.spec_from_file_location(
        "chaos_engine_enhancement_disposition", path
    )
    if specification is None or specification.loader is None:
        return None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def enhancement_errors(message: str) -> list[str]:
    """Shared close check. The repository stop hook delegates here."""
    module = _enhancement_disposition()
    if module is None:
        return ["enhancement disposition checker unavailable"]
    return list(module.enhancement_errors(message))


_IGNORED_STOP_REASONS = frozenset({
    "channel_closed",
    "shutdown",
    "user_canceled",
    "error",
    "max_invocations",
    "max_forced_invocations",
    "max_token_budget_exceeded",
    "terminal_custom_hook",
})


def _stop_turn_closed(event: dict) -> bool:
    """True when a Stop must not emit decision continue.

    ``fullyIdle: false`` and a terminal ``terminationReason`` close the turn.
    The termination field is checked before free-text ``reason``.
    """
    if event.get("fullyIdle") is False or event.get("fully_idle") is False:
        return True
    for key in ("terminationReason", "termination_reason"):
        raw = event.get(key)
        if isinstance(raw, str) and raw.strip().casefold() in _IGNORED_STOP_REASONS:
            return True
    reason = str(event.get("reason") or "").strip().casefold()
    return reason in _IGNORED_STOP_REASONS


def _in_flight_background(event: dict) -> bool:
    """True when Grok still has a shell, monitor, or subagent in flight.

    ``backgroundTasks`` is empty when nothing is running. A missing field is
    not in-flight work. ``fullyIdle: false`` is in-flight. Scheduled
    ``sessionCrons`` are later wakeups, not a running monitor.
    """
    if event.get("fullyIdle") is False or event.get("fully_idle") is False:
        return True
    for key in ("backgroundTasks", "background_tasks"):
        tasks = event.get(key)
        if isinstance(tasks, list) and tasks:
            return True
    return False


def _delegates_still_open(event: dict, session_id: str) -> bool:
    if session_scratch is None:
        return False
    try:
        return bool(session_scratch.open_agents(_scratch_project(event), session_id))
    except Exception:
        return False


def _terminal_note(event: dict) -> str:
    message = event.get("last_assistant_message")
    if not isinstance(message, str):
        message = event.get("lastAssistantMessage")
    return message if isinstance(message, str) else ""


def _terminal_note_accepted(message: str) -> bool:
    folded = message.casefold()
    for label in TERMINAL_LABELS:
        if label in folded:
            continue
        pattern = _SHORT_TERMINAL_HEADINGS.get(label)
        if pattern is None or pattern.search(message) is None:
            return False
    return not enhancement_errors(message)


def _activity_recorded(session_id: str, activity: str) -> bool:
    try:
        items = reflection.entries(session_id)
    except (OSError, TypeError, ValueError):
        return False
    return any(
        item.get("kind") == "task-activity" and item.get("activity") == activity
        for item in items
    )


def _terminal_reflection_reason(event: dict, session_id: str) -> str:
    """Demand the learning retrospective once, on a live Stop after one hour.

    SessionEnd still files the notes. Grok does not show a SessionEnd
    systemMessage, so the note the user reads is this turn's reply.
    A Stop while a subagent or a background task is still in flight does
    not ask (#74). ``channel_closed`` and ``shutdown`` are ignored because
    that Stop decision does not continue the turn. One demand is recorded
    for the session. A later Stop does not ask again. A valid note is still
    accepted after that demand.
    """
    if str(event.get("hook_event_name") or "") == "SubagentStop":
        return ""
    reason = str(event.get("reason") or "").strip().casefold()
    if reason in _IGNORED_STOP_REASONS:
        return ""
    if reflection.has_valid_terminal_receipt(session_id):
        return ""
    elapsed = reflection.session_elapsed_seconds(session_id)
    if elapsed is None or elapsed <= 3600:
        return ""
    if _in_flight_background(event) or _delegates_still_open(event, session_id):
        return ""
    if _terminal_note_accepted(_terminal_note(event)):
        reflection.accept_terminal_reflection(session_id)
        return ""
    if _activity_recorded(session_id, "terminal-reflection-demanded"):
        return ""
    reflection.record_activity(session_id, "terminal-reflection-demanded")
    return (
        "Terminal reflection required. This session exceeded one hour and "
        "background work has exited. Write the learning retrospective in this "
        "reply. what can we learn from what happened so far for our harness "
        "or memory modules to avoid such failures in the future? "
        "Include what happened, why it happened, continue doing, stop doing, "
        "start doing, and next action. File an actionable ChaosEngine change "
        "on the configured upstream repository before the note and cite the "
        "issue URL. Close with one ## Enhancements block. Each bullet starts "
        "with shipped:, tracked:, or rejected:. nothing actionable is the "
        "only close with no URL."
    )


_PULL_REQUEST_URL = re.compile(r"/pull/(\d+)\b")


def _open_pull_request_state_path(cwd: Path) -> Path:
    return cwd / ".chaos-engine-state" / "open-pull-request.json"


def _pull_request_number(event: dict, commands: tuple[str, ...]) -> int | None:
    response = event.get("tool_response") or event.get("toolResponse") or {}
    chunks: list[str] = []
    if isinstance(response, dict):
        chunks.extend(str(response.get(key) or "") for key in ("stdout", "output", "body"))
    elif isinstance(response, str):
        chunks.append(response)
    chunks.extend(commands)
    for chunk in chunks:
        match = _PULL_REQUEST_URL.search(chunk)
        if match:
            return int(match.group(1))
    return None



_GITHUB_PERMISSION_DENIED = "github-permission-denied"
_AUTO_MERGE_ARM = re.compile(
    r"(?:^|[\s;|&])gh\s+pr\s+merge\b[^\n]*--auto\b",
    re.IGNORECASE,
)
_FORK_WORKFLOW_APPROVE = re.compile(
    r"repos/[^\s]+/actions/runs/\d+/approve|"
    r"actions/runs/\d+/approve|"
    r"gh\s+workflow\s+run\b.*approve|"
    r"approve-fork|"
    r"actions/permissions/workflow",
    re.IGNORECASE,
)


def _merge_statement_arms_auto(statement: str) -> bool:
    """True when one ``gh pr merge`` argument is ``--auto`` or starts with ``--auto=``."""
    parsed = shell_tokens(statement)
    if not parsed or any(item in {";", "&&", "||", "|", "&"} for item in parsed):
        return False
    head, arguments = command_head(parsed)
    if head != "gh" or arguments[:2] != ["pr", "merge"]:
        return False
    return any(arg == "--auto" or arg.startswith("--auto=") for arg in arguments)


def _command_is_github_write_permission_mutation(command: str) -> bool:
    """True for auto-merge arm or fork-workflow approve mutations (#7443)."""
    text = str(command or "")
    if _AUTO_MERGE_ARM.search(text):
        return True
    if any(_merge_statement_arms_auto(part) for part in _merge_command_statements(text)):
        return True
    if _FORK_WORKFLOW_APPROVE.search(text):
        return True
    # GraphQL EnablePullRequestAutoMerge
    if "EnablePullRequestAutoMerge" in text:
        return True
    return False


def _tool_result_looks_like_http_403(result: object) -> bool:
    """True when a tool result reports HTTP 403 / permission denied."""
    chunks: list[str] = []
    if isinstance(result, dict):
        for key in ("stderr", "stdout", "output", "body", "message", "error"):
            chunks.append(str(result.get(key) or ""))
        code = result.get("exit_code", result.get("exitCode"))
        if code not in {0, None, "0"}:
            chunks.append(str(code))
    elif isinstance(result, str):
        chunks.append(result)
    blob = "\n".join(chunks).casefold()
    return (
        "403" in blob
        or "http 403" in blob
        or "permission denied" in blob
        or "resource not accessible" in blob
        or "must have write" in blob
    )


def remember_github_permission_denied(session_id: str, event: dict, commands: tuple[str, ...]) -> None:
    """Record a write-permission failure so the same mutation is not retried (#7443)."""
    if not session_id:
        return
    result = event.get("tool_response") or event.get("toolResponse") or event.get("tool_result")
    if not any(_command_is_github_write_permission_mutation(c) for c in commands):
        return
    if not _tool_result_looks_like_http_403(result):
        return
    reflection.record_activity(session_id, _GITHUB_PERMISSION_DENIED)


def github_permission_denied_reason(session_id: str, commands: tuple[str, ...]) -> str:
    """Block repeating auto-merge / fork-approve after HTTP 403 (#7443)."""
    if not any(_command_is_github_write_permission_mutation(c) for c in commands):
        return ""
    activities = {
        item.get("activity")
        for item in reflection.entries(session_id)
        if item.get("kind") == "task-activity"
    }
    if _GITHUB_PERMISSION_DENIED not in activities:
        return ""
    return (
        "GitHub returned HTTP 403 on auto-merge or fork-workflow approval. "
        "That is a permission failure, not a pending check. Stop; do not retry "
        "the same mutation. Ask a maintainer with write access."
    )


def remember_open_pull_request(cwd: Path, number: int | None, *, repository: str | None = None) -> None:
    """Persist a numbered pull request opened by gh pr create for later sessions.

    #7443: refuse to write a numberless mark — Stop must not demand until-merged
    without a pull request identity.
    """
    if number is None or isinstance(number, bool) or int(number) <= 0:
        return
    payload: dict[str, object] = {
        "active": True,
        "state": "open",
        "pullRequest": int(number),
    }
    if repository:
        payload["repository"] = repository
    path = _open_pull_request_state_path(cwd)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    except OSError:
        return


def clear_open_pull_request(cwd: Path) -> None:
    """Drop the checkout open-PR mark after gh pr merge."""
    path = _open_pull_request_state_path(cwd)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return


def _marked_pull_request_number(cwd: Path) -> int | None:
    path = _open_pull_request_state_path(cwd)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    number = payload.get("pullRequest")
    if isinstance(number, bool) or not isinstance(number, int):
        return None
    return number


def _result_stdout(result: dict) -> str:
    chunks = (result.get("stdout"), result.get("output"))
    for item in chunks:
        if isinstance(item, str) and item.strip():
            return item
    for item in chunks:
        if isinstance(item, str):
            return item
    return ""


def _integer_argument(text: str) -> int | None:
    return int(text) if text.isdigit() else None


def _flag_number(arguments: list[str], flag: str) -> int | None:
    for index, arg in enumerate(arguments):
        if arg == flag and index + 1 < len(arguments):
            return _integer_argument(arguments[index + 1])
        if arg.startswith(flag + "="):
            return _integer_argument(arg.split("=", 1)[1])
    return None


def _positional_number(arguments: list[str]) -> int | None:
    for arg in arguments:
        number = _integer_argument(arg)
        if number is not None:
            return number
    return None


def _json_state_merged(stdout: str) -> bool:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return False
    return isinstance(payload, dict) and str(payload.get("state") or "").casefold() == "merged"


def _observed_merge(command: str, stdout: str) -> tuple[int | None] | None:
    """A verified MERGED from watch --until-merged or gh pr view, not gh pr merge --auto.

    The tuple is the PR number in the command, or None when the command names none.
    A missing return means this command did not observe a merge.
    """
    parsed = shell_tokens(command)
    if not parsed or any(item in {";", "&&", "||", "|", "&"} for item in parsed):
        return None
    head, arguments = command_head(parsed)
    if head in {"py", "python", "python3"}:
        script = any(
            item.replace("\\", "/").casefold().endswith("watch_pr_checks.py") for item in arguments
        )
        merged_line = any(line.strip() == "MERGED" for line in stdout.splitlines())
        if script and "--until-merged" in arguments and merged_line:
            return (_flag_number(arguments, "--pr"),)
        return None
    if head == "gh" and arguments[:2] == ["pr", "view"] and _json_state_merged(stdout):
        return (_positional_number(arguments[2:]),)
    return None


def _record_observed_pull_request_merge(
    event: dict, commands: tuple[str, ...], session_id: str
) -> None:
    """#7370: watch or gh pr view reporting MERGED clears the open-PR Stop block."""
    result = event.get("tool_response")
    if result is None:
        result = event.get("toolResponse")
    if _tool_result_failed("PostToolUse", result) or not isinstance(result, dict):
        return
    stdout = _result_stdout(result)
    seen: tuple[int | None] | None = None
    for command in commands:
        seen = _observed_merge(command, stdout)
        if seen is not None:
            break
    if seen is None:
        return
    cwd = Path(str(event.get("cwd") or Path.cwd()))
    marked = _marked_pull_request_number(cwd)
    observed = seen[0]
    # A numbered mark clears only when this command names that same pull request.
    if marked is not None and (observed is None or marked != observed):
        return
    reflection.record_activity(session_id, "pull-request-merged")
    clear_open_pull_request(cwd)


def delivery_goal_open_pull_request(event: dict) -> bool:
    """True when this checkout still has a pull request opened by gh pr create.

    The session ledger is not required to contain ``pull-request-open``.
    A later push-only session still owes a babysit while that mark is open.
    """
    cwd = event.get("cwd")
    if not cwd:
        return False
    path = _open_pull_request_state_path(Path(str(cwd)))
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict) or payload.get("active") is not True:
        return False
    if str(payload.get("state") or "").casefold() != "open":
        return False
    # #7443: a numberless open-PR mark is not an identity — do not demand until-merged.
    number = payload.get("pullRequest")
    if not (isinstance(number, int) and not isinstance(number, bool) and number > 0):
        return False
    # #7443: owner out-of-scope allowlist — do not demand until-merged for that PR.
    repository = str(payload.get("repository") or "") or None
    return not out_of_scope_pull_request(Path(str(cwd)), number, repository=repository)


def _open_pull_request_reason(session_id: str, event: dict) -> str:
    """An open delivery PR is unfinished until gh pr merge is recorded.

    ``delivery-status`` does not clear the block. An active delivery goal
    with an open pull request counts even when this session never ran
    ``gh pr create``. #7443: only a numbered open-PR mark is an identity —
    activity alone or a numberless mark must not demand ``--until-merged``.
    """
    activities = {
        item.get("activity")
        for item in reflection.entries(session_id)
        if item.get("kind") == "task-activity"
    }
    if "pull-request-merged" in activities:
        return ""
    if not delivery_goal_open_pull_request(event):
        return ""
    return (
        "Delivery is not complete while the pull request is open. "
        "Babysit it until merged: classify the release note, then merge with "
        "gh pr merge --squash only after the reviews are done and their comments "
        "are applied. A skipped or neutral check outside the required set does not block. "
        "A failed, cancelled, or pending check blocks when it is required and when no check is marked required. "
        "An unmarked skip blocks. An empty check list is not success. "
        "A pending check is not success. Do not merge while a check is still "
        "running, including with --auto. Watch with "
        "scripts/agents/watch_pr_checks.py --until-merged. "
        "Do not stop on an open pull request."
    )


_READ_ONLY_TOOL_SUBCOMMANDS = frozenset({"entry", "ce-version", "retrieve"})


def _tool_subcommand(arguments: list[str], script: str) -> str:
    folded_script = script.replace("\\", "/")
    seen_script = False
    for arg in arguments:
        if not seen_script:
            if arg.replace("\\", "/") == folded_script:
                seen_script = True
            continue
        if arg.startswith("-"):
            continue
        return arg.casefold()
    return ""


def _read_only_project_tool_command(command: str, cwd: Path) -> bool:
    """True for entry, ce-version, or retrieve of this project's tool.py.

    A compound that is already catastrophic stays false so a denied ``rm``
    does not clear the retrieve debt.
    """
    if catastrophic_posix(command) or "git reset --hard" in command.casefold():
        return False
    parsed = tokens(command)
    if not parsed:
        return False
    head, arguments = command_head(parsed)
    lang = head.removesuffix(".exe")
    if lang not in _PY_LANGS:
        return False
    script = _positional_script(arguments, ("-W", "-X", "-m", "-Q"))
    if not script or not _is_project_tool_py(script, cwd):
        return False
    return _tool_subcommand(arguments, script) in _READ_ONLY_TOOL_SUBCOMMANDS


def _retrieve_gap_reason(event: dict, session_id: str) -> str:
    """One retrieve demand. None after a demand, a blocked project retrieve, or no debt.

    ``retrieveOwed`` is set only by a broad search. A session that has not
    searched does not owe, so Stop stays quiet.
    """
    if justification is None:
        return ""
    root = justification.project_root(Path(str(event.get("cwd") or Path.cwd())))
    if justification.retrieve_blocked(root, session_id):
        return ""
    if _activity_recorded(session_id, "retrieve-demanded"):
        return ""
    gap = justification.session_retrieve_gap(root, session_id)
    return gap or ""


def _stop_block_reason(event: dict, session_id: str) -> str:
    if _stop_turn_closed(event):
        return ""
    # An open delivery PR outranks Learning Session and the host stop retry.
    # Otherwise the turn ends when the PR is only opened.
    if event.get("hook_event_name") != "SubagentStop":
        open_reason = _open_pull_request_reason(session_id, event)
        if open_reason:
            return open_reason
    # Learning Session outranks a retrieve citation. Otherwise a delivery-complete
    # Stop ends on the retrieve command and the host retry never asks again.
    if event.get("hook_event_name") != "SubagentStop":
        loop_reason = learning_session_reason(session_id, event)
        if loop_reason:
            return loop_reason
        # An unpaid one-hour retrospective survives the host retry. Open PR
        # and Learning Session stay ahead of it. In-flight background work
        # returns no reason, so a turn can finish while a monitor is running.
        terminal = _terminal_reflection_reason(event, session_id)
        if terminal:
            return terminal
    # FR-002: a host retry skips the retrieve gap. It does not skip the checks above.
    hook_retry = bool(event.get("stop_hook_active") or event.get("stopHookActive"))
    if (
        justification is not None
        and event.get("hook_event_name") != "SubagentStop"
        and not hook_retry
    ):
        gap = _retrieve_gap_reason(event, session_id)
        if gap:
            reflection.record_activity(session_id, "retrieve-demanded")
            return gap
    if event.get("hook_event_name") == "SubagentStop":
        return ""
    if bool(event.get("stop_hook_active") or event.get("stopHookActive")):
        return ""
    return _pending_watch_claim_reason(event)


def _record_failed_result(
    event: dict, event_name: str, commands: tuple[str, ...], tool_name: str, session_id: str
) -> bool:
    result = event.get("tool_response", event.get("tool_result"))
    if event_name not in {"PostToolUse", "PostToolUseFailure"} or not _tool_result_failed(event_name, result):
        return False
    target = outcome_target(
        commands[0] if commands else "",
        tool_name,
        event.get("target") or event.get("job") or event.get("test"),
    )
    read_only = tool_name in {"Read", "Grep", "Glob", "WebSearch", "WebFetch", "Skill"} or bool(
        commands and all(read_only_diagnostic_command(command) for command in commands)
    )
    # A denied receipt adapter must not enlarge the fingerprint set the next receipt has to list.
    if commands and any(denied_reflection_retry(command) for command in commands):
        return False
    remember_github_permission_denied(session_id, event, commands)
    if session_scratch is not None and not read_only:
        root = _scratch_root(event)
        tool = str(tool_name or "")[:40]
        if root:
            with contextlib.suppress(Exception):
                session_scratch.append_note(
                    _scratch_project(event),
                    root,
                    agent=_scratch_agent(event),
                    kind="issue",
                    text=f"tool failure: {tool}" if tool else "tool failure",
                )
    reflection.record_failure(
        session_id,
        phase="tool-outcome",
        target=target,
        failure_class="interrupted" if event.get("is_interrupt") else "tool-failure",
        platform=event.get("platform") or sys.platform,
        attempted=not read_only,
        observation_id=event.get("tool_use_id") or event.get("toolUseId"),
    )
    _soft_significance_capture(
        event, event_name, failed=True, denied=False, tool_name=tool_name
    )
    checkpoint = reflection.pending_checkpoint(session_id)
    if checkpoint:
        print(json.dumps({"additionalContext": checkpoint_reason(checkpoint, session_id)}))
    return bool(checkpoint)


def _unchanged_test_requested(event: dict, commands: tuple[str, ...], tool_name: str, session_id: str) -> bool:
    active_targets = {
        item.get("target")
        for item in reflection.active_entries(session_id)
        if item.get("kind") == "task-failure"
    }
    target = event.get("target") or event.get("job") or event.get("test")
    return any(
        test_command(candidate) and outcome_target(candidate, tool_name, target) in active_targets
        for candidate in commands
    )


def _uninspectable_functions_call(
    tool_name: str, tool_input: object, functions_source: str,
    functions_direct: str, commands: tuple[str, ...],
) -> bool:
    if tool_name != "functions.exec" or functions_direct:
        return False
    if not isinstance(tool_input, (str, dict)):
        return True
    if isinstance(tool_input, dict) and not functions_source:
        return True
    if _indirect_tools_use(functions_source):
        return True
    return wrapped_exec_call_count(functions_source) != len(commands)


def _command_guard_state(
    event: dict, event_name: str, commands: tuple[str, ...], tool_name: str, tool_input: object,
    functions_source: str, functions_direct: str, session_id: str,
) -> tuple[bool, bool, str]:
    project = Path(str(event.get("cwd") or Path.cwd()))
    original = commands
    commands = _inspected_commands(commands, project)
    receipt_command = any(reflection_recovery(candidate) for candidate in commands)
    if event_name == "PostToolUse" and not receipt_command:
        _record_observed_pull_request_merge(event, commands, session_id)
    mutation = (
        tool_name in {"Write", "Edit", "apply_patch"}
        or bool(re.search(r"\btools\.(?:apply_patch|store)\s*\(", functions_source))
        or any(
        mutation_command(candidate) and not tracker_command(candidate) for candidate in commands
        )
    )
    if event_name in _OBSERVED_TOOL_EVENTS and not receipt_command:
        project = Path(str(event.get("cwd") or Path.cwd()))
        post_block = _post_tool_boundary(project, commands, event, event_name)
        if post_block:
            return receipt_command, mutation, post_block
    checkpoint = reflection.pending_checkpoint(session_id)
    unchanged_test = _unchanged_test_requested(event, commands, tool_name, session_id)
    if event_name == "PreToolUse":
        project = Path(str(event.get("cwd") or Path.cwd()))
        boundary_block = _operation_boundary_block(commands, project)
        if boundary_block:
            return receipt_command, mutation, boundary_block
    push_block = (_overlay_push_block(commands) or _pr_body_block(commands)) if event_name == "PreToolUse" else ""
    if push_block:
        return receipt_command, mutation, push_block
    if event_name == "PreToolUse":
        permission_block = github_permission_denied_reason(session_id, commands)
        if permission_block:
            return receipt_command, mutation, permission_block
        for candidate in commands:
            merge_block = merge_before_ready_reason(candidate)
            if merge_block:
                return receipt_command, mutation, merge_block
        cwd = Path(str(event.get("cwd") or Path.cwd()))
        scope_block = until_merged_out_of_scope_reason(cwd, commands)
        if scope_block:
            return receipt_command, mutation, scope_block
        identity_block = commit_identity_pre_commit_reason(cwd, commands)
        if identity_block:
            return receipt_command, mutation, identity_block
    if event_name == "PreToolUse" and checkpoint and not receipt_command and (mutation or unchanged_test):
        return receipt_command, mutation, checkpoint_reason(checkpoint, session_id)
    uninspectable = _uninspectable_functions_call(
        tool_name, tool_input, functions_source, functions_direct, original
    )
    project = Path(str(event.get("cwd") or Path.cwd()))
    reason = _destructive_scope_reason(commands, project, uninspectable)
    if reason:
        return receipt_command, mutation, reason
    return receipt_command, mutation, ""


def _denial_fragment(text: str) -> str:
    shown = " ".join(str(text).split())
    if len(shown) > 160:
        shown = shown[:157] + "..."
    return shown or "(none)"


def _scope_denial(branch: str, fragment: str) -> str:
    """Name which check fired and the text it matched."""
    return f"{_SCOPE_DENIAL} branch={branch} fragment={_denial_fragment(fragment)}"


def _visible_command(commands: tuple[str, ...]) -> str:
    for command in commands:
        if command and command != _UNINSPECTED_PROCESS:
            return command
    return "uninspected-process"


def _compound_installer_reason(command: str, project: Path) -> str | None:
    """Allow a compound whose only destructive statements are this project's installer.

    ``""`` allows. A denial string blocks. ``None`` means this is not that shape.
    """
    statements = [part.strip() for part in re.split(r"&&|\|\||;|\r?\n", command) if part.strip()]
    if len(statements) <= 1:
        return None
    saw_installer = False
    for statement in statements:
        if not _command_is_destructive(statement):
            continue
        if documented_installer_for_project(statement, project):
            saw_installer = True
            continue
        if documented_installer_command(statement) is not None:
            return _INSTALLER_ORIGIN_DENIAL
        return _scope_denial("compound", statement)
    if not saw_installer:
        return None
    return ""


def _destructive_scope_reason(commands: tuple[str, ...], project: Path, uninspectable: bool) -> str:
    if uninspectable:
        return _scope_denial("uninspectable", "functions.exec")
    for candidate in commands:
        if candidate == _UNINSPECTED_PROCESS:
            continue
        if not _command_is_destructive(candidate) or documented_installer_for_project(candidate, project):
            continue
        if documented_installer_command(candidate) is not None:
            return _INSTALLER_ORIGIN_DENIAL
        compound = _compound_installer_reason(candidate, project)
        if compound == "":
            continue
        if compound:
            return compound
        return _scope_denial("destructive", candidate)
    if _UNINSPECTED_PROCESS in commands:
        return _scope_denial("uninspected", _visible_command(commands))
    return ""


def _pending_watch_claim_reason(event: dict) -> str:
    module = _unattended_delivery()
    if module is None:
        return ""
    checkpoint = module.checkpoint_from_event(event)
    if checkpoint is None:
        return ""
    message = str(event.get("last_assistant_message") or event.get("lastAssistantMessage") or "")
    follow_up_open = bool(checkpoint.get("followUpOpen", True))
    if not module.delivery_claim_rejected(message, follow_up_open=follow_up_open):
        return ""
    return (
        "Delivery is not complete while the watch is pending. "
        "Wait on that same task id until MERGED or RED."
    )


def _unattended_delivery():
    root = Path(__file__).resolve().parents[2]
    path = root / "scripts/agents/unattended_delivery.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("chaos_engine_unattended_delivery", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _schedule_store_refresh(cwd: Path) -> None:
    """Spawn a detached store refresh when the shared cache is stale. Never blocks."""
    try:
        import runpy

        stores = runpy.run_path(
            str(_overlay_module("stores.py")),
            run_name="_chaos_engine_guard_stores",
        )
        stores["maybe_spawn_refresh"](cwd)
    except (OSError, RuntimeError, ValueError, KeyError):
        return


def _phase_ledger_triage(session_id: str) -> str | None:
    """Read triage from zero-LLM phase ledger when present (#5623)."""
    if not session_id:
        return None
    try:
        path = _overlay_module("phase_ledger.py")
        if not path.is_file():
            return None
        spec = importlib.util.spec_from_file_location("chaos_engine_phase_ledger", path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.session_triage(session_id)
    except (OSError, RuntimeError, ValueError, AttributeError):
        return None


def _research_before_mutation_reason(event_name: str, mutation: bool, session_id: str) -> str | None:
    """Triage-scaled research gate (#5623); hard for public-contract, soft for one-file."""
    if event_name != "PreToolUse" or not mutation:
        return None
    triage = _phase_ledger_triage(session_id)
    flag = str(os.environ.get("CHAOS_ENGINE_ENFORCE_RESEARCH_RECEIPT") or "").strip().casefold()
    env_on = flag in {"1", "true", "yes", "on"}
    hard = triage == "public-contract" or (env_on and triage != "one-file")
    if not hard:
        return None
    if not session_id or reflection.has_research_preflight(session_id):
        return None
    return (
        "Research receipt required before mutation "
        f"(triage={triage or 'unset'}; "
        "record via hooks/reflection.py research-preflight "
        "or phase_ledger.py record --phase research)."
    )



def _soft_significance_capture(
    event: dict,
    event_name: str,
    *,
    failed: bool = False,
    denied: bool = False,
    tool_name: str = "",
) -> None:
    """Soft fail/deny marks only — never load self-improve refs mid-turn (#5658)."""
    with contextlib.suppress(Exception):
        sig_path = _overlay_module("significance.py")
        if not sig_path.is_file():
            return
        spec = importlib.util.spec_from_file_location("ce_significance_soft", sig_path)
        if spec is None or spec.loader is None:
            return
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.soft_post_tool_capture(
            event if isinstance(event, dict) else {},
            event_name=event_name,
            failed=failed,
            denied=denied,
            tool_name=tool_name,
        )


def _record_denial_counter() -> None:
    with contextlib.suppress(Exception):
        counters_path = _overlay_module("learning_counters.py")
        if not counters_path.is_file():
            return
        spec = importlib.util.spec_from_file_location("ce_learning_counters_deny", counters_path)
        if spec is None or spec.loader is None:
            return
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.record_denial()




def _record_denial_with_significance(event: dict, event_name: str, tool_name: str = "") -> None:
    _record_denial_counter()
    _soft_significance_capture(
        event, event_name, failed=False, denied=True, tool_name=tool_name
    )


# Soft complexity reminder for hot-spot mutations. Profiles declare the
# hot-spot markers in their profile.json `complexityHint`; the core ships none.
def _complexity_hint_markers() -> tuple[tuple[str, ...], tuple[str, ...]]:
    paths: list[str] = []
    names: list[str] = []
    tree = Path(__file__).resolve().parents[1]
    declared = [*tree.glob("profiles/*/profile.json"), *tree.glob("packs/*/profile.json")]
    declared.extend(tree.parent.glob("*/ce-pack/profile.json"))
    for profile in sorted(declared):
        with contextlib.suppress(OSError, ValueError, AttributeError, TypeError):
            hint = json.loads(profile.read_text(encoding="utf-8")).get("complexityHint") or {}
            paths.extend(str(item).casefold() for item in hint.get("pathMarkers", ()))
            names.extend(str(item).casefold() for item in hint.get("nameMarkers", ()))
    return tuple(paths), tuple(names)


COMPLEXITY_GATE_HINT = (
    "Complexity gate: kind-family helpers / rule tables before "
    "fat dispatch arms; Complexity ACTION_REQUIRED == unit red. "
    "Checklist: references/complexity-gate.md"
)


def _mutation_path_blobs(tool_name: str, tool_input: object, commands: tuple[str, ...]) -> str:
    """Flatten Write/Edit/patch/shell targets for classifier-path matching."""
    chunks: list[str] = []
    if isinstance(tool_input, Mapping):
        for key in ("file_path", "filePath", "path", "notebook_path", "notebookPath"):
            value = tool_input.get(key)
            if isinstance(value, str) and value.strip():
                chunks.append(value)
        for key in ("old_string", "new_string", "content", "patch", "input", "command", "cmd"):
            value = tool_input.get(key)
            if isinstance(value, str) and value.strip():
                chunks.append(value)
    elif isinstance(tool_input, str) and tool_input.strip():
        chunks.append(tool_input)
    chunks.extend(commands)
    compact = tool_name.casefold() if tool_name else ""
    if compact:
        chunks.append(compact)
    return "\n".join(chunks).casefold()


def classifier_complexity_gate_hint(
    event_name: str,
    *,
    mutation: bool,
    tool_name: str,
    tool_input: object,
    commands: tuple[str, ...] = (),
) -> str | None:
    """Return soft checklist hint when mutating classifier / interaction surfaces."""
    if event_name != "PreToolUse" or not mutation:
        return None
    blob = _mutation_path_blobs(tool_name, tool_input, commands)
    if not blob:
        return None
    path_markers, name_markers = _complexity_hint_markers()
    path_hit = any(marker in blob for marker in path_markers)
    name_hit = any(marker in blob for marker in name_markers)
    if path_hit or name_hit:
        return COMPLEXITY_GATE_HINT
    return None


def _entry_injected(session_id: str) -> bool:
    return any(item.get("kind") == "entry-injected" for item in reflection.entries(session_id))


def _mark_entry_injected(session_id: str) -> None:
    if not session_id:
        return
    reflection.append_entry(
        session_id,
        {"schemaVersion": reflection.SCHEMA_VERSION, "kind": "entry-injected"},
    )


def _parse_hook_event(event: dict) -> tuple:
    tool_input = event.get("tool_input", {}) if isinstance(event, dict) else {}
    tool_name = str(event.get("tool_name", "")) if isinstance(event, dict) else ""
    event_name = (
        str(event.get("hook_event_name") or event.get("hookEventName") or "")
        if isinstance(event, dict)
        else ""
    )
    return (
        tool_input,
        tool_name,
        functions_exec_source(tool_input),
        functions_exec_direct_command(tool_input),
        _event_commands(tool_name, tool_input),
        event_name,
    )


def _repair_denial(reason: str, event: dict) -> str:
    """#7964: a denial that names tool.py says how to restore it when the file is gone."""
    guard = _delete_guard()
    if guard is None or not hasattr(guard, "denial_with_tool_repair"):
        return reason
    cwd = Path(str(event.get("cwd") or Path.cwd()))
    return guard.denial_with_tool_repair(reason, cwd)


def _repeat_api():
    cached = getattr(_repeat_api, "module", None)
    if cached is not None:
        return cached
    path = Path(__file__).resolve().parent / "repeat_reminder.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("chaos_engine_repeat_reminder", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _repeat_api.module = module
    return module


def _repeat_advice(event_name: str, session_id: str, tool_name: str, tool_input: object) -> str | None:
    if event_name not in {"PostToolUse", "PostToolUseFailure", "PreToolUse"}:
        return None
    module = _repeat_api()
    if module is None:
        return None
    try:
        return module.observe(
            session_id, tool_name, tool_input if isinstance(tool_input, dict) else {}
        )
    except Exception:
        return None


def _deny(event: dict, event_name: str, tool_name: str, reason: str) -> int:
    if event_name == "PreToolUse" and justification is not None:
        with contextlib.suppress(Exception):
            cwd = Path(str(event.get("cwd") or Path.cwd()))
            commands = _event_commands(tool_name, event.get("tool_input"))
            root = justification.project_root(cwd)
            justification.forget_denied_retrieve(
                root,
                _scope_session(event),
                commands,
            )
            if any(_read_only_project_tool_command(command, cwd) for command in commands):
                justification.note_retrieve_blocked(root, _scope_session(event))
    _record_denial_with_significance(event, event_name, tool_name)
    advice = None
    if event_name == "PreToolUse":
        advice = _repeat_advice(
            event_name, _scope_session(event), tool_name, event.get("tool_input")
        )
    module = _repeat_api()
    payload = (
        module.denied_with_advice(_repair_denial(reason, event), advice)
        if module is not None
        else {"decision": "block", "reason": _repair_denial(reason, event)}
    )
    print(json.dumps(payload))
    return 2


def _large_read_api():
    cached = getattr(_large_read_api, "module", None)
    if cached is not None:
        return cached
    path = Path(__file__).resolve().parents[1] / "rules" / "large_read_deny.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("chaos_engine_large_read_deny", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _large_read_api.module = module
    return module


def _large_read_reason(event: dict, tool_name: str, tool_input: object) -> str | None:
    event_name = str(event.get("hook_event_name") or event.get("hookEventName") or "")
    if event_name != "PreToolUse":
        return None
    module = _large_read_api()
    if module is None:
        return None
    cwd = event.get("cwd")
    return module.deny_reason(tool_name, tool_input, cwd=str(cwd) if cwd else None)


def _ethics_api():
    cached = getattr(_ethics_api, "module", None)
    if cached is not None:
        return cached
    path = Path(__file__).resolve().parents[1] / "rules" / "ethics_check.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("chaos_engine_ethics_check", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _ethics_api.module = module
    return module


def _ethics_pretool_reason(event: dict, commands: tuple, tool_input: object) -> str | None:
    """Deny assessment-shaped submits when the ethics receipt is missing or person-only."""
    event_name = str(event.get("hook_event_name") or event.get("hookEventName") or "")
    if event_name != "PreToolUse":
        return None
    module = _ethics_api()
    if module is None:
        return None
    cwd = Path(str(event.get("cwd") or Path.cwd()))
    return module.assessment_block_reason(
        commands,
        tool_input,
        cwd,
        tool_name=str(event.get("tool_name") or ""),
        session_id=str(event.get("session_id") or event.get("sessionId") or ""),
    )


def _stash_block(event: dict, event_name: str, tool_name: str, commands: tuple) -> int | None:
    if event_name != "PreToolUse":
        return None
    # R8 is session-independent: enforce it before identity or ledger checks.
    reason = linked_worktree_stash_reason(commands, Path(str(event.get("cwd") or Path.cwd())))
    if reason:
        return _deny(event, event_name, tool_name, reason)
    return None


def _scope_session(event: dict) -> str:
    root_session_id = str(event.get("session_id") or event.get("sessionId") or "")
    return reflection.scope_session_id(root_session_id, event.get("agent_id") or event.get("agentId"))


def _kernel_block(event: dict, event_name: str, tool_name: str, tool_input: object, commands: tuple, session_id: str, host: str):
    kernel_event = dict(event)
    kernel_event["session_id"] = session_id
    kernel_event["agent_id"] = ""
    normalized = _kernel.normalize_event(kernel_event, host)
    if event_name in {"PostToolUse", "PostToolUseFailure"} and not normalized.target_phase:
        report = _kernel.evaluate(normalized)
    else:
        journal = _kernel.EffectJournal(reflection.ledger_path(session_id).with_suffix(".kernel-v3.jsonl"))
        report = _kernel.evaluate_session(normalized, journal)
    if report.decision == "deny":
        return _deny(event, event_name, tool_name, report.reason), normalized
    if justification is not None:
        read_reason = justification.file_read_block_reason(
            project=justification.project_root(Path(str(event.get("cwd") or Path.cwd()))),
            event_name=str(normalized.name or event_name),
            tool_name=str(normalized.tool_name or tool_name),
            tool_input=tool_input if isinstance(tool_input, dict) else {},
            commands=commands,
            session_id=session_id,
        )
        if read_reason:
            return _deny(event, event_name, tool_name, read_reason), normalized
        impact_reason = justification.impact_edit_block_reason(
            project=justification.project_root(Path(str(event.get("cwd") or Path.cwd()))),
            event_name=str(normalized.name or event_name),
            tool_name=str(normalized.tool_name or tool_name),
            session_id=session_id,
            tool_input=tool_input if isinstance(tool_input, dict) else {},
        )
        if impact_reason:
            return _deny(event, event_name, tool_name, impact_reason), normalized
    research_reason = _research_before_mutation_reason(
        event_name, bool(normalized.stateful_mutation), session_id
    )
    if research_reason:
        return _deny(event, event_name, tool_name, research_reason), normalized
    return None, normalized


def _session_token(event_name: str, session_id: str):
    if event_name == "SessionStart":
        return reflection.record_session_start(session_id)
    if event_name not in {"SubagentStop", "SessionEnd"}:
        reflection.record_session_start(session_id, estimated=True)
    return None


def _prompt_entry(event: dict, event_name: str, session_id: str, host: str) -> int | None:
    if event_name != "UserPromptSubmit":
        return None
    module = _repeat_api()
    if module is not None:
        with contextlib.suppress(Exception):
            module.reset_session(session_id)
    prompt = event.get("prompt") or event.get("user_prompt") or ""
    if isinstance(prompt, str):
        _lifecycle.record_companion_opt_out(session_id, prompt)
    if learning_requested(event):
        reflection.record_activity(session_id, "learning-requested")
    # #7424: /goal finish-delivery writes the owner-finish-goal marker automatically.
    activate_owner_finish_goal_from_prompt(event)
    # #7443: owner "out of scope" + PR URL → allowlist for --until-merged refuse.
    record_out_of_scope_from_prompt(event)
    # Grok discards UserPromptSubmit context. Gemini and Copilot have no
    # subagent-start event; Claude and Codex use this only when SubagentStart
    # did not already inject for this agent scope.
    if host == "grok" or not session_id or _entry_injected(session_id):
        return None
    _mark_entry_injected(session_id)
    context = _lifecycle.session_start_context(
        reflection.record_session_start(session_id), ACTIVATION, session_id=session_id
    )
    print(json.dumps({"additionalContext": context}))
    return 0


def _mobile_retro_post_run(event: dict, commands: tuple) -> None:
    """Live post-run freeze via PostToolUse after a green test command (#7494)."""
    if not any(test_command(candidate) for candidate in commands):
        return
    event_name = str(event.get("hook_event_name") or event.get("hookEventName") or "PostToolUse")
    result = event.get("tool_response")
    if result is None:
        result = event.get("toolResponse")
    if result is None:
        result = event.get("tool_result")
    # Derive green from the real tool result; missing/failed → do not freeze.
    if result is None or _tool_result_failed(event_name, result):
        return
    root = Path(str(event.get("cwd") or Path.cwd()))
    try:
        import mobile_retro as _mr
    except ImportError:
        return
    results = _mr.find_green_results_dir(root)
    if results is None:
        return
    try:
        build_id, branch = _mr.current_build_and_branch(root)
        _mr.post_run_freeze(
            results,
            root / _mr.SNAPSHOT_REL,
            green=True,
            pin_path=root / _mr.PIN_REL,
            build_id=build_id,
            branch=branch,
        )
    except Exception:
        # Post-run freeze must never break the hook protocol.
        return



def _tool_stdout(event: dict) -> str:
    result = event.get("tool_response")
    if result is None:
        result = event.get("toolResponse")
    if isinstance(result, dict):
        return str(result.get("stdout") or "")
    return ""


def merge_queue_not_merged(event: dict, commands: tuple[str, ...]) -> bool:
    """True when ``gh pr merge`` only entered the merge queue.

    Exit 0 plus the queue warning is not a merged pull request. Empty output
    stays a confirmed merge: hosts do not always forward stdout.
    """
    if not any(pull_request_merged_command(candidate) for candidate in commands):
        return False
    text = _tool_stdout(event).casefold()
    if "merge queue" not in text:
        return False
    return "merged" not in text.replace("merge queue", "")


def _auto_checkpoint_delivery(event: dict, commands: tuple) -> None:
    """#15: a successful git push or gh pr checkpoints the open task for this root."""
    step = ""
    for command in commands:
        if git_push_command(command):
            step = "push"
            break
        if gh_pr_command(command):
            step = "pr"
            break
    if not step:
        return
    result = event.get("tool_response", event.get("tool_result"))
    if _tool_result_failed("PostToolUse", result):
        return
    ledger = _task_ledger_module()
    if ledger is None or not hasattr(ledger, "checkpoint_from_delivery"):
        return
    cwd = Path(str(event.get("cwd") or Path.cwd()))
    try:
        ledger.checkpoint_from_delivery(cwd, step)
    except (OSError, ValueError):
        return


def _post_tool_activity(event: dict, event_name: str, commands: tuple, session_id: str, receipt_command: bool, mutation: bool) -> None:
    # Spill stays off. No PostToolUse body replacement: hosts cannot prove the original bytes left the window.
    if event_name != "PostToolUse" or receipt_command:
        return
    _auto_checkpoint_delivery(event, commands)
    _mobile_retro_post_run(event, commands)
    if any(learning_session_finalize_command(candidate) for candidate in commands):
        if learning_completion_artifact(session_id) is not None:
            reflection.record_activity(session_id, "learning-session-complete")
        return
    if any(confirmed_delivery_command(candidate) for candidate in commands):
        if merge_queue_not_merged(event, commands):
            return
        reflection.record_activity(session_id, "delivery-complete")
        if any(pull_request_merged_command(candidate) for candidate in commands):
            reflection.record_activity(session_id, "pull-request-merged")
            clear_open_pull_request(Path(str(event.get("cwd") or Path.cwd())))
        return
    if not mutation and not any(delivery_command(candidate) for candidate in commands):
        return
    reflection.record_activity(session_id, "mutation")
    if any(git_commit_command(candidate) for candidate in commands):
        reflection.record_activity(session_id, "fix-commit")
    if any(pull_request_open_command(candidate) for candidate in commands):
        reflection.record_activity(session_id, "pull-request-open")
        remember_open_pull_request(
            Path(str(event.get("cwd") or Path.cwd())),
            _pull_request_number(event, commands),
        )


def _owner_gate_module():
    path = _overlay_module("owner_gate.py")
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("chaos_engine_owner_gate", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _owner_artifact_line(event: dict) -> str:
    """The owner artifact itself, never the open-PR deny essay."""
    explicit = event.get("owner_gate") or event.get("ownerGate")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    message = event.get("last_assistant_message")
    if not isinstance(message, str):
        message = event.get("lastAssistantMessage")
    if not isinstance(message, str):
        return ""
    module = _owner_gate_module()
    if module is None:
        return ""
    for line in message.splitlines():
        text = line.strip()
        if text and len(text) <= 120 and module._owner_only(text):
            return text
    return ""


def _work_besides_open_pr(event: dict, session_id: str) -> bool:
    """True when Stop still owes something other than the open pull request."""
    if event.get("hook_event_name") == "SubagentStop":
        return False
    if learning_session_reason(session_id, event):
        return True
    if _terminal_reflection_reason(event, session_id):
        return True
    hook_retry = bool(event.get("stop_hook_active") or event.get("stopHookActive"))
    if justification is not None and not hook_retry and _retrieve_gap_reason(event, session_id):
        return True
    if not hook_retry and _pending_watch_claim_reason(event):
        return True
    return False


def _owner_gate_ends_open_pr(event: dict, session_id: str) -> bool:
    """Record one unverifiable owner artifact and let that open-PR deny yield."""
    artifact = _owner_artifact_line(event)
    module = _owner_gate_module()
    if not artifact or module is None:
        return False
    state = Path(str(event.get("cwd") or Path.cwd())) / ".chaos-engine-state" / "owner-gate.json"
    try:
        decision = module.apply_owner_gate(
            state,
            blocker=artifact,
            session_can_create=False,
            only_remaining=not _work_besides_open_pr(event, session_id),
        )
    except (OSError, TypeError, ValueError):
        return False
    return bool(decision.get("end_goal"))


def _stop_block(event: dict, event_name: str, tool_name: str, session_id: str) -> int | None:
    if event_name not in {"Stop", "SubagentStop"}:
        return None
    reason = _stop_block_reason(event, session_id)
    if _owner_gate_ends_open_pr(event, session_id):
        if reason and not reason.startswith("Delivery is not complete while the pull request is open."):
            return _deny(event, event_name, tool_name, reason)
        return None
    if reason:
        return _deny(event, event_name, tool_name, reason)
    return None


def _publish_grok_load(start: Path) -> None:
    """Refresh the files Grok reads. Failures stay out of the hook result."""
    path = _overlay_module("grok_model_load.py")
    if not path.is_file():
        return
    spec = importlib.util.spec_from_file_location("chaos_engine_grok_model_load", path)
    if spec is None or spec.loader is None:
        return
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.publish_from(start)


def _unfinished_tasks(cwd: Path) -> str:
    """#8065 R3: unfinished task checkpoints for this work root on the SessionStart card."""
    ledger = _task_ledger_module()
    if ledger is None or not hasattr(ledger, "unfinished_listing"):
        return ""
    try:
        return ledger.unfinished_listing(cwd).rstrip()
    except (OSError, ValueError):
        return ""


_COMPACT_EVENTS = frozenset({"PreCompact", "PostCompact"})


def _scratch_root(event: dict) -> str:
    return str(event.get("session_id") or event.get("sessionId") or "").strip()


def _scratch_project(event: dict) -> Path:
    return Path(str(event.get("cwd") or Path.cwd()))


def _scratch_agent(event: dict) -> str:
    return str(event.get("agent_id") or event.get("agentId") or "").strip() or "root"


def _prepare_scratch(event: dict) -> None:
    """Create the shared folder once and point every later subagent at it."""
    if session_scratch is None:
        return
    root = _scratch_root(event)
    if not root:
        return
    project = _scratch_project(event)
    agent = _scratch_agent(event)
    try:
        created = session_scratch.ensure(project, root)
        if agent == "root":
            if created:
                session_scratch.append_note(
                    project, root, agent="root", kind="highlight", text="session started"
                )
        else:
            session_scratch.open_agent(project, root, agent)
            session_scratch.append_note(
                project, root, agent=agent, kind="highlight", text="subagent started"
            )
    except Exception:
        return


def _capture_scratch(event: dict, event_name: str) -> None:
    if session_scratch is None or event_name not in {"Stop", "SubagentStop"}:
        return
    root = _scratch_root(event)
    if not root:
        return
    project = _scratch_project(event)
    agent = _scratch_agent(event)
    try:
        if event_name == "SubagentStop" and agent != "root":
            session_scratch.close_agent(project, root, agent)
        session_scratch.capture_message(project, root, agent, event)
    except Exception:
        return


def _session_end_retrospective(event: dict, event_name: str) -> int | None:
    """Every SessionEnd writes the prevention report.

    Enhancement and prevention notes are filed only after the session
    exceeded one hour. A later SessionEnd files a note still missing from
    filed.txt. A pass that left nothing unfiled does not file again.
    """
    if event_name != "SessionEnd" or session_scratch is None:
        return None
    root = _scratch_root(event)
    if not root:
        return 0
    try:
        report = session_scratch.retrospective(
            _scratch_project(event),
            root,
            reflection.session_elapsed_seconds(root),
        )
    except Exception:
        return 0
    if report:
        print(json.dumps({"additionalContext": report}))
    return 0


def _session_start_output(event: dict, event_name: str, session_id: str, token) -> int | None:
    if event_name == "SessionStart":
        _prepare_scratch(event)
    if event_name in {"SessionStart", *_COMPACT_EVENTS}:
        module = _unattended_delivery()
        checkpoint = module.checkpoint_from_event(event) if module is not None else None
        if checkpoint is not None:
            prompt = module.resume_prompt(checkpoint)
            if event_name in _COMPACT_EVENTS:
                ethics = _lifecycle._locate((
                    "companions/ethics-card.md",
                    ".chaos-engine/companions/ethics-card.md",
                    "chaos-engine/companions/ethics-card.md",
                )) or ".chaos-engine/companions/ethics-card.md"
                prompt = f"{prompt}\nEthics: `{ethics}`"
            print(json.dumps({"additionalContext": prompt}))
            return 0
        if event_name in _COMPACT_EVENTS:
            locator = _lifecycle.session_start_context(token, ACTIVATION, session_id=session_id)
            print(json.dumps({"additionalContext": locator}))
            return 0
    if event_name != "SessionStart":
        return None
    with contextlib.suppress(OSError, ValueError):
        _publish_grok_load(Path(str(event.get("cwd") or Path.cwd())))
    _schedule_store_refresh(Path(str(event.get("cwd") or Path.cwd())))
    context = _lifecycle.session_start_context(token, ACTIVATION, session_id=session_id)
    drift = reflection.reflection_controller_drift(Path(str(event.get("cwd") or Path.cwd())))
    if drift:
        context = f"{context}\n\n{drift}"
    unfinished = _unfinished_tasks(Path(str(event.get("cwd") or Path.cwd())))
    if unfinished:
        context = f"{context}\n\n{unfinished}"
    if session_scratch is not None:
        with contextlib.suppress(Exception):
            follow = session_scratch.prevention_followup(Path(str(event.get("cwd") or Path.cwd())))
            if follow:
                context = f"{context}\n\n{follow}"
    print(json.dumps({"additionalContext": context}))
    _mark_entry_injected(session_id)
    return 0


def _emit_notes(
    event: dict,
    event_name: str,
    session_id: str,
    mutation: bool,
    tool_name: str,
    tool_input: object,
    commands: tuple,
    open_pr_note: str | None = None,
) -> None:
    complexity_hint = classifier_complexity_gate_hint(
        event_name, mutation=mutation, tool_name=tool_name, tool_input=tool_input, commands=commands
    )
    retrieve_note = None
    if justification is not None and event_name == "PreToolUse":
        retrieve_note = justification.broad_search_context(
            justification.project_root(Path(str(event.get("cwd") or Path.cwd()))),
            session_id,
        )
    advice = None
    if event_name in {"PostToolUse", "PostToolUseFailure"}:
        advice = _repeat_advice(event_name, session_id, tool_name, tool_input)
    if advice and session_scratch is not None:
        root = _scratch_root(event)
        if root:
            with contextlib.suppress(Exception):
                session_scratch.append_note(
                    _scratch_project(event),
                    root,
                    agent=_scratch_agent(event),
                    kind="repetition",
                    text=advice,
                )
    notes = [item for item in (retrieve_note, complexity_hint, advice, open_pr_note) if item]
    if notes:
        print(json.dumps({"additionalContext": "\n".join(notes)}))


def _run_event(event: dict, _host: str) -> int:
    tool_input, tool_name, functions_source, functions_direct, commands, event_name = _parse_hook_event(event)
    ethics_reason = _ethics_pretool_reason(event, commands, tool_input)
    if ethics_reason:
        return _deny(event, event_name, tool_name, ethics_reason)
    blocked = _stash_block(event, event_name, tool_name, commands)
    if blocked is not None:
        return blocked
    session_id = _scope_session(event)
    kernel_blocked, _normalized = _kernel_block(
        event, event_name, tool_name, tool_input, commands, session_id, _host
    )
    if kernel_blocked is not None:
        return kernel_blocked
    large_read = _large_read_reason(event, tool_name, tool_input)
    if large_read:
        return _deny(event, event_name, tool_name, large_read)
    token = _session_token(event_name, session_id)
    injected = _prompt_entry(event, event_name, session_id, _host)
    if injected is not None:
        return injected
    if _record_failed_result(event, event_name, commands, tool_name, session_id):
        return 0
    receipt_command, mutation, guard_reason = _command_guard_state(
        event, event_name, commands, tool_name, tool_input, functions_source, functions_direct, session_id
    )
    if guard_reason:
        return _deny(event, event_name, tool_name, guard_reason)
    open_pr_block, open_pr_note = _open_pr_pretool(event, event_name, commands)
    if open_pr_block:
        if "not valid UTF-8" in open_pr_block:
            print(open_pr_block, file=sys.stderr)
            return 2
        return _deny(event, event_name, tool_name, open_pr_block)
    _post_tool_activity(event, event_name, commands, session_id, receipt_command, mutation)
    _capture_scratch(event, event_name)
    stopped = _stop_block(event, event_name, tool_name, session_id)
    if stopped is not None:
        return stopped
    ended = _session_end_retrospective(event, event_name)
    if ended is not None:
        return ended
    started = _session_start_output(event, event_name, session_id, token)
    if started is not None:
        return started
    _emit_notes(event, event_name, session_id, mutation, tool_name, tool_input, commands, open_pr_note)
    return 0


def _guarded_event(event: dict, host: str) -> int:
    """#7251: the delete guard runs first on PreToolUse, session-independent like R8."""
    if isinstance(event, dict) and str(event.get("hook_event_name") or event.get("hookEventName") or "") == "PreToolUse":
        tool_input = event.get("tool_input", {})
        cwd = Path(str(event.get("cwd") or Path.cwd()))
        commands = tuple(
            command
            for command in _inspected_commands(
                _event_commands(str(event.get("tool_name", "")), tool_input), cwd
            )
            if command != _UNINSPECTED_PROCESS
        )
        reason = delete_guard_reason(commands, cwd)
        if reason:
            return _deny(event, "PreToolUse", str(event.get("tool_name", "")), reason)
    return _run_event(event, host)


def _antigravity_enter_workspace(raw: str) -> None:
    """Antigravity runs hooks with CWD in `.agents/` or `~/.gemini/config/`; switch to the workspace root."""
    if os.environ.get("CHAOS_ENGINE_HOST", "").strip().lower() != "antigravity":
        return
    try:
        current = Path.cwd()
    except OSError:
        return
    in_agents = current.name == ".agents"
    in_global_config = current.name == "config" and current.parent.name == ".gemini"
    if not (in_agents or in_global_config):
        return
    target: Path | None = None
    try:
        parsed = json.loads(raw or "{}")
    except ValueError:
        parsed = {}
    if isinstance(parsed, dict):
        raw_cwd = parsed.get("cwd")
        if isinstance(raw_cwd, str) and raw_cwd.strip() and Path(raw_cwd).is_dir():
            target = Path(raw_cwd)
        if target is None:
            workspaces = parsed.get("workspacePaths")
            if isinstance(workspaces, list):
                for entry in workspaces:
                    if isinstance(entry, str) and entry.strip() and Path(entry).is_dir():
                        target = Path(entry)
                        break
    if target is None and in_agents and (current.parent / ".chaos-engine").is_dir():
        target = current.parent
    if target is not None:
        with contextlib.suppress(OSError):
            os.chdir(target)


def main() -> int:
    raw = sys.stdin.read()
    _antigravity_enter_workspace(raw)
    callbacks = {event: _guarded_event for event in _lifecycle.LIFECYCLE_EVENTS}
    code = _lifecycle.run_hook_protocol(
        raw,
        callbacks,
        normalize=_kernel.normalize_hook_input,
        host_for_input=_kernel.detect_host,
        adapt_output=_kernel.adapt_hook_output,
    )
    # Antigravity treats any non-zero exit as fail-open and ignores the JSON.
    # The deny is the JSON body. The process exit stays 0.
    if os.environ.get("CHAOS_ENGINE_HOST", "").strip().lower() == "antigravity":
        return 0
    return code


if __name__ == "__main__":
    raise SystemExit(main())
