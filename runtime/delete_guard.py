"""
#7251: refuse deletes of work that exists nowhere else.

Used by the PreToolUse hook (hooks/guard.py) and by hookless bots through
``tool.py delete-check <paths>`` or ``tool.py delete-check --command "<cmd>"``.
Inside git a target must be tracked, clean, and pushed (an upstream exists and
HEAD is not ahead). Outside git a target must be on the scratch allow-list.
When the command cannot be parsed with confidence, the guard refuses.
#7343: the owner overrides a refusal with a one-time chat code bound to the
exact path list; a hard never-touch list refuses even with a code.
#7525: verified uploaded yt files on a local/env allowlist (path + video id + sha256)
may take the owner code after live sha + oEmbed author proof; yt/meta and unverified stay locked.
oEmbed HTTP 403 means private (not a box IP block); optional CHAOS_YT_EXPECTED_AUTHORS binds channel.
Also covers raw filesystem deletes that previously bypassed the shell-word trigger:
``mv`` of a source path (including to trash/outside), ``rsync --delete*`` /
``--remove-source-files``, and ``Path(...).unlink|rmdir|rmtree`` constructor forms.
Tree ops that follow links (``find -delete``, ``rsync --delete*``, ``rm -r`` with a
trailing slash, ``shutil.rmtree`` / ``Path.rmtree``, ``mv`` of ``src/``) resolve the
realpath and apply ``path_reason`` to the target; plain ``rm`` of a symlink stays a
link-only delete. Symlink resolution failures refuse closed.
A delete-check refusal is final: do not bypass with raw ``rm``, ``unlink``,
encoded argv, or a wrapper script; the PreToolUse hook and ``block_reason``
enforce the same gate. Self-created paths may be deleted without a code only
when recorded by the tool in the HMAC-bound per-session created-paths
manifest and contained under independently derived floor roots (scoped
session dir and process-cwd real git toplevel; git env and WORKTREE hint cannot
expand floors; record refuses pre-existing paths; a write-once seal pins
started_at + preexist inventory); CE-managed
dirt is restored via ``git checkout <primary-sha> -- <paths>`` in the current
worktree only (never deleted, never other worktrees). Never-touch stays locked.
"""

from __future__ import annotations

import ast
import glob
import hashlib
import hmac
import json
import os
import re
import secrets
import stat
import shlex
from fnmatch import fnmatchcase
import tempfile
import subprocess  # nosec B404 - fixed git argv only.
import sys
import time
from pathlib import Path
from typing import Callable
import urllib.error
import urllib.request

STATE_DIR = ".chaos-engine-state"
ALLOW_FILE = "delete-allow.txt"
# Per-session created-paths manifest (scoped temp). Exact paths listed here may be
# deleted without an owner code when the HMAC verifies and the path is contained;
# never-touch still wins. Env overrides the path. HMAC key stays outside the tree.
SESSION_CREATED_MANIFEST_ENV = "CHAOS_SESSION_CREATED_MANIFEST"
SESSION_CREATED_MANIFEST_NAME = "created-paths.json"
SESSION_MANIFEST_HMAC_ENV = "CHAOS_SESSION_MANIFEST_HMAC"
SESSION_CONTAINMENT_ROOTS_ENV = "CHAOS_SESSION_CONTAINMENT_ROOTS"
SESSION_WORKTREE_ENV = "CHAOS_SESSION_WORKTREE"
SESSION_MANIFEST_SCHEMA = 3
SESSION_MANIFEST_SEAL_SUFFIX = ".seal"
SESSION_SEAL_SCHEMA = 1
SESSION_SEAL_TIME_TOLERANCE_S = 2.0
# Git env vars that redirect discovery / index / objects — never inherit into _git.
_GIT_ENV_BLOCKLIST = frozenset(
    {
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_COMMON_DIR",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_CEILING_DIRECTORIES",
        "GIT_DISCOVERY_ACROSS_FILESYSTEM",
        "GIT_NAMESPACE",
        "GIT_QUARANTINE_PATH",
        "GIT_CONFIG",
        "GIT_CONFIG_GLOBAL",
        "GIT_CONFIG_SYSTEM",
        "GIT_CONFIG_COUNT",
    }
)
_GIT_ENV_PREFIX_BLOCKLIST = ("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")
# Relative roots treated as CE-managed for primary-SHA restore (checkout, never delete).
CE_MANAGED_PREFIXES = (".chaos-engine/",)
ACK_ENV = "CHAOS_DELETE_ACK"
CODE_TTL = 1800
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
# No code unlocks these: a path segment matching a name, or a browser profile dir.
NEVER_NAMES = ("ROG*", "yt", "designer-ws.git.retired", "signed-renders")
# Old renders inside yt/ (not yt/meta/) such as clip.r3.mp4 go through the owner-code flow.
YT_RENDER = re.compile(r".+\.r\d+\.mp4")
NEVER_PATTERNS = (
    "**/.config/google-chrome*/**",
    "**/.config/chromium/**",
    "**/*chrome*-profile*/**",
    "**/.ssh/**",
    "**/.env",
    "**/.env.*",
    "**/credentials.json",
    "**/id_rsa",
    "**/id_ed25519",
)
NEVER_FILE = Path("~/.config/chaos-engine/never-delete.txt")
# #7525: exact-file allowlist of verified uploaded yt files (local/env only; not committed).
YT_VERIFIED_ENV = "CHAOS_YT_VERIFIED_DELETE"
YT_VERIFIED_FILE = Path("~/.config/chaos-engine/yt-verified-delete.txt")
YT_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
YT_SHA256 = re.compile(r"^[a-f0-9]{64}$")
YT_OEMBED = "https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={id}&format=json"
YT_OEMBED_TTL = 86400
YT_OEMBED_SOFT_TTL = 60  # network/5xx: short negative cache so outages do not lock for a day
YT_EXPECTED_AUTHORS_ENV = "CHAOS_YT_EXPECTED_AUTHORS"  # optional comma-separated oEmbed author_name values
YT_OEMBED_UA = "Mozilla/5.0 (compatible; ChaosEngine-delete-guard/2)"
_youtube_video_verifier: Callable[[str], bool] | None = None
# Generic scratch: temp, caches, build output, video render output.
DEFAULT_ALLOW = (
    str(Path(tempfile.gettempdir()).resolve() / "**"),
    "~/.cache/**",
    "**/__pycache__/**",
    "**/.pytest_cache/**",
    "**/.mypy_cache/**",
    "**/.ruff_cache/**",
    "**/node_modules/.cache/**",
    "**/.gradle/caches/**",
    "**/target/**",
    "**/build/**",
    "**/dist/**",
    "**/.next/**",
    "**/.turbo/**",
    "**/*video*/**/render/**",
    "**/*video*/**/renders/**",
    "**/*video*/**/out/**",
    "**/*video*/**/frames/**",
    "**/*video*/**/clips/**",
)
DELETE_WORD = re.compile(
    r"(?:^|[^\w.-])(?:rm|unlink|shred|rmtree|clean|mv)\b|-delete\b|--remove-source-files\b|"
    r"-exec(?:dir)?\s+\S*rm\b"
)
UNSURE = re.compile(r"\$|`|<\(|>\(")
# `{a,b}` and `{1..3}` are shell brace lists. A literal `{name}` is not.
_BRACE_EXPANSION = re.compile(r"\{[^{}]*(?:,|\.\.)[^{}]*\}")
_INDIRECT_PY_DELETES = frozenset({"remove", "unlink", "rmtree", "rmdir"})
RMTREE = re.compile(
    r"(?:shutil\.rmtree|os\.remove|os\.unlink|os\.rmdir|os\.removedirs|\.unlink|\.rmtree|\.rmdir)\s*\(\s*(?P<arg>[^)]*)\)"
)
# Path('literal').unlink() / .rmdir() / .rmtree() — path is in the constructor, not the call.
PATHLIB_DELETE = re.compile(
    r"""(?:pathlib\.)?Path\s*\(\s*(?:r|R)?(['"])(?P<path>[^'"]+)\1\s*\)\s*\.\s*(?:unlink|rmdir|rmtree)\b"""
)
PY_DELETE_HINT = re.compile(r"\b(?:remove|removedirs|unlink|rmdir|rmtree)\s*\(")
RS_DELETE = re.compile(r"^--delete(?:-|$)|^-delete$|^--remove-source-files$")
WRAPPERS = frozenset({"command", "env", "sudo", "timeout", "nice", "nohup", "exec", "builtin"})
SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ash", "ksh", "mksh"})
ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_SHELL_KEYWORDS_PREFIX = frozenset({"if", "then", "elif", "else", "do", "while", "until", "!", "{"})
_SHELL_KEYWORDS_END = frozenset({"fi", "done", "esac", "}"})
_PATH_CTORS = frozenset({"Path", "PosixPath", "WindowsPath", "PurePath", "PurePosixPath", "PureWindowsPath"})
_OS_DELETE_FUNCS = frozenset({"remove", "unlink", "rmdir", "removedirs"})
_PATH_DELETE_METHODS = frozenset({"unlink", "rmdir", "rmtree"})


class Unsure(ValueError):
    """The command deletes something the parser cannot pin down."""


_TIME_FLAG_OPTIONS = frozenset({"-p", "-v", "-a", "-q", "-l"})
_TIME_ARG_OPTIONS = frozenset({"-o", "-f"})
_TIME_LONG_FLAGS = ("--verbose", "--portability", "--append", "--quiet")
_TIME_LONG_VALUES = ("--output", "--format")
_TIME_SHORT_FLAGS = frozenset("pvaql")
_TIME_SHORT_ARGS = frozenset("of")
_STDBUF_LONG_VALUES = ("--input", "--output", "--error")
_SCRIPT_DOT_COMMANDS = frozenset({"source", "."})


def _match_long_option(arg: str, flag_opts: tuple[str, ...], value_opts: tuple[str, ...]) -> str | None:
    """Resolve a GNU ``getopt_long`` unique prefix.

    ``flag`` is a no-arg long option, or any long option written as ``--opt=val``.
    ``value`` means the next argv element is the option's value. ``None`` means
    ``arg`` is not a unique prefix of exactly one known option.
    """
    if not arg.startswith("--") or arg == "--":
        return None
    name, sep, _attached = arg[2:].partition("=")
    if not name:
        return None

    def hits(options: tuple[str, ...]) -> list[str]:
        return [opt for opt in options if opt.startswith("--") and opt[2:].startswith(name)]

    flag_hits = hits(flag_opts)
    value_hits = hits(value_opts)
    if len(flag_hits) + len(value_hits) != 1:
        return None
    if flag_hits or sep:
        return "flag"
    return "value"


def _time_short_cluster(token: str) -> str | None:
    """Classify a GNU ``time`` short cluster such as ``-pv`` or ``-o/tmp/t``."""
    if len(token) <= 2 or not token.startswith("-") or token.startswith("--"):
        return None
    body = token[1:]
    for offset, char in enumerate(body):
        if char in _TIME_SHORT_FLAGS:
            continue
        if char in _TIME_SHORT_ARGS:
            return "attached" if body[offset + 1 :] else "need-arg"
        return None
    return "flags"


def _skip_time_options(arguments: list[str], index: int) -> int:
    """Skip POSIX ``-p`` and GNU ``time`` options so the timed command is visible.

    Covers short flags ``-p``/``-v``/``-a``/``-q``/``-l``, value shorts ``-o``/``-f``
    (clusters such as ``-pv`` and attached ``-oFILE``), GNU ``getopt_long`` unique
    prefixes of ``--verbose``/``--portability``/``--append``/``--quiet`` and
    ``--output``/``--format`` (next argv element or ``--opt=val``), and ``--``.
    """
    while index < len(arguments):
        token = arguments[index]
        if token == "--":
            return index + 1
        matched = _match_long_option(token, _TIME_LONG_FLAGS, _TIME_LONG_VALUES)
        if matched == "flag":
            index += 1
            continue
        if matched == "value":
            index += 1
            if index < len(arguments):
                index += 1
            continue
        if token in _TIME_FLAG_OPTIONS:
            index += 1
            continue
        if token in _TIME_ARG_OPTIONS:
            index += 1
            if index < len(arguments):
                index += 1
            continue
        kind = _time_short_cluster(token)
        if kind in {"flags", "attached"}:
            index += 1
            continue
        if kind == "need-arg":
            index += 1
            if index < len(arguments):
                index += 1
            continue
        break
    return index


def _skip_stdbuf_options(arguments: list[str], index: int) -> int:
    """Skip ``stdbuf`` ``-i``/``-o``/``-e`` and long-option prefixes, plus each mode.

    ``--opt=MODE`` keeps the mode on the option. ``--opt MODE`` and ``-o MODE``
    take the next argv element. ``-o0`` keeps the mode attached. ``--`` ends
    option parsing so the next word is the command.
    """
    short = {"-i", "-o", "-e"}
    while index < len(arguments):
        token = arguments[index]
        if token == "--":
            return index + 1
        matched = _match_long_option(token, (), _STDBUF_LONG_VALUES)
        if matched == "flag":
            index += 1
            continue
        if matched == "value":
            index += 1
            if index < len(arguments):
                index += 1
            continue
        if token in short:
            index += 1
            if index < len(arguments):
                index += 1
            continue
        if len(token) > 2 and token[0] == "-" and not token.startswith("--") and token[1] in "ioe":
            index += 1
            continue
        break
    return index


def _head(arguments: list[str]) -> tuple[str, list[str]]:
    index = 0
    while index < len(arguments):
        item = arguments[index]
        if ENV_ASSIGNMENT.match(item):
            index += 1
            continue
        head = os.path.basename(item)
        if head == "time":
            index = _skip_time_options(arguments, index + 1)
            continue
        if head == "stdbuf":
            index = _skip_stdbuf_options(arguments, index + 1)
            continue
        if head == "busybox":
            index += 1
            if index < len(arguments) and arguments[index] == "--":
                index += 1
            continue
        if head == "coproc":
            index += 1
            # `coproc NAME { ... }` — the name is not the command. A simple
            # command's first word is the command (`coproc rm ...`).
            if (
                index + 1 < len(arguments)
                and arguments[index] not in {"{", "("}
                and not arguments[index].startswith("-")
                and arguments[index + 1] == "{"
            ):
                index += 1
            continue
        if head in WRAPPERS:
            index += 1
            while index < len(arguments) and (arguments[index].startswith("-") or ENV_ASSIGNMENT.match(arguments[index])):
                index += 1
            if head == "timeout" and index < len(arguments) and re.fullmatch(r"\d+[smhd]?", arguments[index]):
                index += 1
            continue
        return head, arguments[index + 1 :]
    return "", []


def _computed_command_head(head: str) -> bool:
    """True when the basename `_head` returns still contains `$` or a backtick.

    `$VENV/bin/python` is basename `python` and stays a normal command.
    `$x` and `$(echo rm)` do not name a command this parser can see.
    """
    return "$" in head or "`" in head


def _is_process_sub_word(word: str) -> bool:
    return word.startswith("<(") or word.startswith(">(")


def _rm_targets(arguments: list[str]) -> list[str]:
    targets, options = [], True
    for item in arguments:
        if options and item == "--":
            options = False
        elif options and item.startswith("-") and item != "-":
            continue
        else:
            targets.append(item)
    if not targets:
        raise Unsure("rm without a target")
    return targets


def _find_targets(arguments: list[str]) -> list[str]:
    deletes = "-delete" in arguments or any(
        item == "-exec" and index + 1 < len(arguments) and os.path.basename(arguments[index + 1]) in {"rm", "rmdir", "unlink", "shred"}
        for index, item in enumerate(arguments)
    ) or "-execdir" in arguments
    if not deletes:
        return []
    roots = []
    for item in arguments:
        if item.startswith(("-", "(", "!")):
            break
        roots.append(item)
    return roots or ["."]


def _drop_git_options(arguments: list[str]) -> list[str]:
    kept, skip = [], False
    for item in arguments:
        if skip:
            skip = False
        elif item in {"-C", "-c", "--git-dir", "--work-tree"}:
            skip = True
        else:
            kept.append(item)
    return kept


def _git_clean_targets(arguments: list[str]) -> list[str] | None:
    words = [item for item in arguments if not item.startswith("-")]
    if not words or words[0] != "clean":
        return None
    flags = "".join(item for item in arguments if item.startswith("-") and not item.startswith("--"))
    if "n" in flags or "--dry-run" in arguments:
        return []
    if "--" in arguments:
        return arguments[arguments.index("--") + 1 :] or ["."]
    return words[1:] or ["."]


def _is_python(head: str) -> bool:
    return head == "py" or head.startswith("python")


def _python_code_from_args(arguments: list[str]) -> str | None:
    """Return the inline source string from python ``-c`` args, or None."""
    index = 0
    while index < len(arguments):
        item = arguments[index]
        if item == "-c":
            return arguments[index + 1] if index + 1 < len(arguments) else ""
        if item.startswith("-c") and len(item) > 2:
            return item[2:]
        if item in {"-m", "-", "--"}:
            return None
        if item in {"-W", "-X", "--check-hash-based-pycs"}:
            index += 2
            continue
        if item.startswith("-"):
            index += 1
            continue
        return None
    return None


def _shell_c_script(arguments: list[str]) -> str | None:
    """Return the inline script string from ``sh/bash -c`` (including combined flags like ``-ec``)."""
    index = 0
    while index < len(arguments):
        item = arguments[index]
        if item == "--":
            return None
        if item in {"-o", "+o"}:
            index += 2
            continue
        if item == "-c":
            return arguments[index + 1] if index + 1 < len(arguments) else None
        if item.startswith("-") and not item.startswith("--") and "c" in item[1:]:
            return arguments[index + 1] if index + 1 < len(arguments) else None
        if item.startswith(("-", "+")):
            index += 1
            continue
        return None
    return None


def _cd_target(arguments: list[str]) -> str:
    """First path operand to ``cd`` / ``pushd``, skipping standard flags."""
    options = True
    for item in arguments:
        if options and item == "--":
            options = False
            continue
        if options and item == "-":
            return "-"
        if options and item.startswith("-"):
            continue
        return item
    return "~"


def _needs_computed_cwd(raw_paths: list[str]) -> bool:
    """True when a delete operand is resolved against the shell's current directory.

    Absolute paths (and ``~`` paths) do not use the cwd, so a prior ``cd "$T"``
    does not make them ambiguous. Relative operands and ``$``/command
    substitutions do.
    """
    for raw in raw_paths:
        if UNSURE.search(raw):
            return True
        expanded = os.path.expanduser(raw)
        if not os.path.isabs(expanded):
            return True
    return False


def _git_effective_cwd(arguments: list[str], cwd: Path, cwd_computed: bool) -> tuple[Path, bool]:
    """Resolve ``git -C <dir>`` locally without leaking cwd changes to later commands."""
    eff_cwd, eff_computed = cwd, cwd_computed
    index = 0
    while index < len(arguments):
        item = arguments[index]
        if item == "-C" and index + 1 < len(arguments):
            target = arguments[index + 1]
            if UNSURE.search(target):
                eff_computed = True
            else:
                expanded = os.path.expanduser(target)
                if os.path.isabs(expanded):
                    eff_cwd = Path(expanded).resolve()
                    eff_computed = False
                elif eff_computed:
                    eff_computed = True
                else:
                    eff_cwd = (eff_cwd / expanded).resolve()
            index += 2
            continue
        if item in {"-c", "--git-dir", "--work-tree"}:
            index += 2
            continue
        if not item.startswith("-"):
            break
        index += 1
    return eff_cwd, eff_computed


def _ast_is_path_ctor(func: ast.AST, path_ctors: set[str], pathlib_mods: set[str]) -> bool:
    if isinstance(func, ast.Name):
        return func.id in path_ctors
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return func.value.id in pathlib_mods and func.attr in _PATH_CTORS
    return False


def _ast_literal_path(node: ast.AST, path_ctors: set[str], pathlib_mods: set[str]) -> str | None:
    """Resolve a literal string or literal Path(...) expression in Python AST."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Call) and not node.keywords and _ast_is_path_ctor(node.func, path_ctors, pathlib_mods):
        if not node.args:
            return "."
        parts: list[str] = []
        for arg in node.args:
            part = _ast_literal_path(arg, path_ctors, pathlib_mods)
            if part is None:
                return None
            parts.append(part)
        return os.path.join(*parts) if len(parts) > 1 else parts[0]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left = _ast_literal_path(node.left, path_ctors, pathlib_mods)
        right = _ast_literal_path(node.right, path_ctors, pathlib_mods)
        if left is not None and right is not None:
            return os.path.join(left, right)
    return None


def _call_path_arg(node: ast.Call) -> ast.AST | None:
    if node.args:
        return node.args[0]
    for kw in node.keywords:
        if kw.arg == "path":
            return kw.value
    return None


def _is_indirect_getattr_delete(node: ast.Call) -> bool:
    """``getattr(obj, "remove"|"unlink"|"rmtree"|"rmdir")`` hides the delete call."""
    func = node.func
    if not isinstance(func, ast.Name) or func.id != "getattr" or len(node.args) < 2:
        return False
    attr = node.args[1]
    return isinstance(attr, ast.Constant) and isinstance(attr.value, str) and attr.value in _INDIRECT_PY_DELETES


def _python_entries(segment: str) -> list[tuple[str, bool]]:
    """Return (path, follow_symlinks) for actual Python delete calls in ``segment`` via AST."""
    try:
        tree = ast.parse(segment)
    except SyntaxError as error:
        if RMTREE.search(segment) or PATHLIB_DELETE.search(segment):
            raise Unsure(f"unparsable Python delete: {error.msg}") from error
        return []

    shutil_mods: set[str] = {"shutil"}
    os_mods: set[str] = {"os"}
    pathlib_mods: set[str] = {"pathlib"}
    path_ctors: set[str] = set(_PATH_CTORS)
    direct_funcs: dict[str, bool] = {}  # local name -> follow_symlinks

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound = alias.asname or alias.name
                if alias.name == "shutil":
                    shutil_mods.add(bound)
                elif alias.name == "os":
                    os_mods.add(bound)
                elif alias.name == "pathlib":
                    pathlib_mods.add(bound)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for alias in node.names:
                bound = alias.asname or alias.name
                if mod == "shutil" and alias.name == "rmtree":
                    direct_funcs[bound] = True
                elif mod == "os" and alias.name in _OS_DELETE_FUNCS:
                    direct_funcs[bound] = False
                elif mod == "pathlib" and alias.name in _PATH_CTORS:
                    path_ctors.add(bound)

    entries: list[tuple[str, bool]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _is_indirect_getattr_delete(node):
            raise Unsure("indirect Python delete via getattr")
        func = node.func
        if isinstance(func, ast.Name) and func.id in direct_funcs:
            arg = _call_path_arg(node)
            literal = _ast_literal_path(arg, path_ctors, pathlib_mods) if arg is not None else None
            if literal is None:
                raise Unsure("non-literal path in a Python delete call")
            entries.append((literal, direct_funcs[func.id]))
            continue
        if isinstance(func, ast.Attribute):
            val, attr = func.value, func.attr
            if isinstance(val, ast.Name) and val.id in shutil_mods and attr == "rmtree":
                arg = _call_path_arg(node)
                literal = _ast_literal_path(arg, path_ctors, pathlib_mods) if arg is not None else None
                if literal is None:
                    raise Unsure("non-literal path in a Python delete call")
                entries.append((literal, True))
                continue
            if isinstance(val, ast.Name) and val.id in os_mods and attr in _OS_DELETE_FUNCS:
                arg = _call_path_arg(node)
                literal = _ast_literal_path(arg, path_ctors, pathlib_mods) if arg is not None else None
                if literal is None:
                    raise Unsure("non-literal path in a Python delete call")
                entries.append((literal, False))
                continue
            if attr in _PATH_DELETE_METHODS:
                literal = _ast_literal_path(val, path_ctors, pathlib_mods)
                if literal is None:
                    raise Unsure("non-literal path in a Python delete call")
                entries.append((literal, attr == "rmtree"))
    return entries


def _operands(arguments: list[str]) -> list[str]:
    """Non-option operands after optional ``--``."""
    targets, options = [], True
    for item in arguments:
        if options and item == "--":
            options = False
        elif options and item.startswith("-") and item != "-":
            continue
        else:
            targets.append(item)
    return targets


def _rm_recursive(arguments: list[str]) -> bool:
    for item in arguments:
        if item in {"-r", "-R", "--recursive"}:
            return True
        if item.startswith("-") and not item.startswith("--") and any(flag in item for flag in "rR"):
            return True
    return False


def _mv_entries(arguments: list[str]) -> list[tuple[str, bool]]:
    """``mv`` sources; trailing slash means move-through-contents (follow)."""
    operands = _operands(arguments)
    if len(operands) < 2:
        raise Unsure("mv without source and destination")
    return [(item, item.endswith(("/", os.sep))) for item in operands[:-1]]


def _rsync_entries(arguments: list[str]) -> list[tuple[str, bool]]:
    """``rsync --delete*`` / ``--remove-source-files`` always follow symlink operands."""
    deleteish = any(RS_DELETE.match(item) or item.startswith("--delete-") for item in arguments)
    remove_sources = "--remove-source-files" in arguments
    if not deleteish and not remove_sources:
        return []
    operands = _operands(arguments)
    if len(operands) < 2:
        raise Unsure("rsync delete without source and destination")
    sources, dest = operands[:-1], operands[-1]
    raw = [dest] if deleteish else []
    if remove_sources:
        raw = list(sources) + raw
    if not raw:
        raise Unsure("rsync delete without resolvable targets")
    return [(item, True) for item in raw]


def _resolve_follow(path: Path) -> Path:
    """Realpath for tree ops that follow links; refuse closed when resolution fails."""
    try:
        if path.is_symlink() or path.exists():
            return path.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise Unsure(f"cannot resolve symlink delete target: {path}") from error
    return path


def _expand_entries(raw: list[tuple[str, bool]], cwd: Path) -> list[tuple[Path, bool]]:
    found: list[tuple[Path, bool]] = []
    for item, follow in raw:
        for path in _expand(item, cwd):
            found.append((path, follow))
    return found


def _segment_targets(
    arguments: list[str],
    cwd: Path,
    *,
    cwd_computed: bool = False,
) -> list[tuple[Path, bool]]:
    head, rest = _head(arguments)
    if _computed_command_head(head):
        raise Unsure("computed command head")
    if head in {"rm", "unlink", "shred"}:
        targets = _rm_targets(rest)
        if cwd_computed and _needs_computed_cwd(targets):
            raise Unsure("cd to a computed path before a delete")
        recursive = _rm_recursive(rest)
        # Trailing slash + recursive: GNU rm follows the symlink and deletes contents.
        return _expand_entries(
            [(item, recursive and item.endswith(("/", os.sep))) for item in targets],
            cwd,
        )
    if head == "mv":
        entries = _mv_entries(rest)
        if cwd_computed and _needs_computed_cwd([item for item, _follow in entries]):
            raise Unsure("cd to a computed path before a delete")
        return _expand_entries(entries, cwd)
    if head == "rsync":
        entries = _rsync_entries(rest)
        if entries and cwd_computed and _needs_computed_cwd([item for item, _follow in entries]):
            raise Unsure("cd to a computed path before a delete")
        return _expand_entries(entries, cwd)
    if head == "find":
        raw = _find_targets(rest)
        if raw and cwd_computed and _needs_computed_cwd(raw):
            raise Unsure("cd to a computed path before a delete")
        # find follows a symlink start point when searching/deleting under it.
        return _expand_entries([(item, True) for item in raw], cwd)
    if head == "git":
        raw = _git_clean_targets(_drop_git_options(rest)) or []
        if raw and cwd_computed and _needs_computed_cwd(raw):
            raise Unsure("cd to a computed path before a delete")
        return _expand_entries([(item, False) for item in raw], cwd)
    if head in {"xargs", "parallel"} and DELETE_WORD.search(" ".join(rest)):
        if cwd_computed:
            raise Unsure("cd to a computed path before a delete")
        raise Unsure("xargs/parallel delete: targets come from stdin")
    if head == "eval":
        script = " ".join(rest)
        if script:
            return _command_targets(script, cwd, cwd_computed=cwd_computed)[0]
        return []
    if head in SHELLS or head in _SCRIPT_DOT_COMMANDS:
        script = _shell_c_script(rest) if head in SHELLS else None
        if script is None and any(_is_process_sub_word(word) for word in rest):
            raise Unsure("shell process substitution")
        if script is not None:
            return _command_targets(script, cwd, cwd_computed=cwd_computed)[0]
    return []


class _Heredoc:
    __slots__ = ("body", "closed", "delimiter", "quoted", "strip_tabs")

    def __init__(self, delimiter: str, strip_tabs: bool, quoted: bool) -> None:
        self.delimiter = delimiter
        self.strip_tabs = strip_tabs
        self.quoted = quoted
        self.body = ""
        self.closed = False


class _SimpleCommand:
    __slots__ = ("cmd_subs", "here_strings", "heredocs", "words")

    def __init__(self) -> None:
        self.words: list[str] = []
        self.heredocs: list[_Heredoc] = []
        self.here_strings: list[str] = []
        self.cmd_subs: list[str] = []


def _scan_single_quote(text: str, pos: int) -> tuple[str, int]:
    """Scan '...' starting at the opening quote; raises ValueError if unclosed."""
    end = text.find("'", pos + 1)
    if end == -1:
        raise ValueError("No closing quotation")
    return text[pos + 1 : end], end + 1


_ANSI_C_SIMPLE = {
    "a": "\a",
    "b": "\b",
    "e": "\x1b",
    "E": "\x1b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "v": "\v",
    "\\": "\\",
    "'": "'",
    '"': '"',
}
_ANSI_C_HEX = frozenset("0123456789abcdefABCDEF")
_ANSI_C_OCTAL = frozenset("01234567")


def _decode_ansi_c_escape(text: str, index: int) -> tuple[str, int]:
    """Decode one ANSI-C escape. ``index`` points at the character after the backslash."""
    n = len(text)
    if index >= n:
        raise ValueError("No closing quotation")
    ch = text[index]
    simple = _ANSI_C_SIMPLE.get(ch)
    if simple is not None:
        return simple, index + 1
    if ch == "x":
        end = index + 1
        limit = min(n, index + 3)
        while end < limit and text[end] in _ANSI_C_HEX:
            end += 1
        if end == index + 1:
            return "x", index + 1
        return chr(int(text[index + 1 : end], 16)), end
    if ch in {"u", "U"}:
        width = 4 if ch == "u" else 8
        end = index + 1
        limit = min(n, index + 1 + width)
        while end < limit and text[end] in _ANSI_C_HEX:
            end += 1
        if end == index + 1:
            return ch, index + 1
        code = int(text[index + 1 : end], 16)
        if code > 0x10FFFF:
            return "\ufffd", end
        try:
            return chr(code), end
        except ValueError:
            return "\ufffd", end
    if ch in _ANSI_C_OCTAL:
        end = index + 1
        limit = min(n, index + 3)
        while end < limit and text[end] in _ANSI_C_OCTAL:
            end += 1
        return chr(int(text[index:end], 8) & 0xFF), end
    return ch, index + 1


def _scan_ansi_c_quote(text: str, pos: int) -> tuple[str, int]:
    """Scan $'...' starting at '$'; raises ValueError if unclosed.

    Decodes ``\\xHH`` (1-2 hex), octal ``\\0``..``\\377`` (1-3 digits),
    ``\\uHHHH``, ``\\UHHHHHHHH``, and the standard single-character escapes.
    """
    index = pos + 2
    n = len(text)
    out: list[str] = []
    while index < n:
        ch = text[index]
        if ch == "\\":
            decoded, index = _decode_ansi_c_escape(text, index + 1)
            out.append(decoded)
            continue
        if ch == "'":
            return "".join(out), index + 1
        out.append(ch)
        index += 1
    raise ValueError("No closing quotation")


def _scan_backtick(text: str, pos: int, *, in_dquote: bool) -> tuple[str, int]:
    """Scan `...` starting at opening backtick; returns (inner_cmd, next_pos)."""
    index = pos + 1
    n = len(text)
    out: list[str] = []
    escapable = {"$", "`", "\\"} | ({'"'} if in_dquote else set())
    while index < n:
        ch = text[index]
        if ch == "\\":
            if index + 1 < n and text[index + 1] in escapable:
                out.append(text[index + 1])
                index += 2
            else:
                out.append(ch)
                index += 1
        elif ch == "`":
            return "".join(out), index + 1
        else:
            out.append(ch)
            index += 1
    raise ValueError("No closing quotation")


def _scan_balanced_paren(text: str, pos: int) -> int:
    """Given text[pos] == '(', return index right after matching ')'. Raises ValueError if unclosed."""
    depth = 0
    index = pos
    n = len(text)
    while index < n:
        ch = text[index]
        if ch == "\\":
            index += 2
            continue
        if ch == "'":
            _, index = _scan_single_quote(text, index)
            continue
        if ch == "$" and index + 1 < n and text[index + 1] == "'":
            _, index = _scan_ansi_c_quote(text, index)
            continue
        if ch == '"':
            _, index = _scan_double_quote(text, index, None)
            continue
        if ch == "`":
            _, index = _scan_backtick(text, index, in_dquote=False)
            continue
        if ch == "#" and (index == pos or text[index - 1] in " \t\n;&|("):
            nl = text.find("\n", index)
            index = n if nl == -1 else nl + 1
            continue
        if ch == "(":
            depth += 1
            index += 1
        elif ch == ")":
            depth -= 1
            index += 1
            if depth == 0:
                return index
        else:
            index += 1
    raise ValueError("Unclosed parenthesis")


def _scan_balanced_brace(text: str, pos: int, cmd_subs: list[str] | None) -> int:
    """Given text[pos:pos+2] == '${', return index right after matching '}'."""
    depth = 0
    index = pos + 1  # at '{'
    n = len(text)
    while index < n:
        ch = text[index]
        if ch == "\\":
            index += 2
            continue
        if ch == "'":
            _, index = _scan_single_quote(text, index)
            continue
        if ch == "$" and index + 1 < n and text[index + 1] == "'":
            _, index = _scan_ansi_c_quote(text, index)
            continue
        if ch == '"':
            _, index = _scan_double_quote(text, index, cmd_subs)
            continue
        if ch == "`":
            inner, index = _scan_backtick(text, index, in_dquote=False)
            if cmd_subs is not None:
                cmd_subs.append(inner)
            continue
        if ch == "$" and index + 1 < n and text[index + 1] == "(":
            end = _scan_balanced_paren(text, index + 1)
            if index + 2 < n and text[index + 2] == "(":
                _note_arith_cmd_subs(text, index, end, cmd_subs)
            elif cmd_subs is not None:
                cmd_subs.append(text[index + 2 : end - 1])
            index = end
            continue
        if ch == "{":
            depth += 1
            index += 1
        elif ch == "}":
            depth -= 1
            index += 1
            if depth == 0:
                return index
        else:
            index += 1
    raise ValueError("Unclosed parameter expansion")


def _scan_double_quote(text: str, pos: int, cmd_subs: list[str] | None) -> tuple[str, int]:
    """Scan \"...\" starting at opening quote; collects $(...) and `...` into cmd_subs."""
    index = pos + 1
    n = len(text)
    out: list[str] = []
    while index < n:
        ch = text[index]
        if ch == "\\":
            if index + 1 < n:
                nxt = text[index + 1]
                if nxt == "\n":
                    index += 2
                    continue
                if nxt in {'"', "\\", "$", "`"}:
                    out.append(nxt)
                    index += 2
                    continue
            out.append(ch)
            index += 1
            continue
        if ch == '"':
            return "".join(out), index + 1
        if ch == "`":
            inner, end = _scan_backtick(text, index, in_dquote=True)
            if cmd_subs is not None:
                cmd_subs.append(inner)
            out.append(text[index:end])
            index = end
            continue
        if ch == "$" and index + 1 < n:
            nxt = text[index + 1]
            if nxt == "(":
                end = _scan_balanced_paren(text, index + 1)
                if index + 2 < n and text[index + 2] == "(":
                    _note_arith_cmd_subs(text, index, end, cmd_subs)
                elif cmd_subs is not None:
                    cmd_subs.append(text[index + 2 : end - 1])
                out.append(text[index:end])
                index = end
                continue
            if nxt == "{":
                end = _scan_balanced_brace(text, index, cmd_subs)
                out.append(text[index:end])
                index = end
                continue
        out.append(ch)
        index += 1
    raise ValueError("No closing quotation")


def _note_arith_cmd_subs(text: str, dollar_at: int, end: int, cmd_subs: list[str] | None) -> None:
    """Collect ``$(...)`` and backticks inside the body of ``$(( ... ))``."""
    if cmd_subs is None:
        return
    body_start = dollar_at + 3
    body_end = end - 2
    if body_end <= body_start:
        return
    cmd_subs.extend(_scan_heredoc_cmd_subs(text[body_start:body_end]))


def _scan_heredoc_cmd_subs(body: str) -> list[str]:
    """Extract unescaped $(...) and `...` substitutions from an unquoted heredoc body."""
    subs: list[str] = []
    index = 0
    n = len(body)
    while index < n:
        ch = body[index]
        if ch == "\\":
            index += 2
            continue
        if ch == "`":
            try:
                inner, index = _scan_backtick(body, index, in_dquote=False)
                subs.append(inner)
            except ValueError:
                index += 1
            continue
        if ch == "$" and index + 1 < n and body[index + 1] == "(":
            if index + 2 < n and body[index + 2] == "(":
                try:
                    end = _scan_balanced_paren(body, index + 1)
                except ValueError:
                    index += 3
                    continue
                _note_arith_cmd_subs(body, index, end, subs)
                index = end
                continue
            try:
                end = _scan_balanced_paren(body, index + 1)
                subs.append(body[index + 2 : end - 1])
                index = end
            except ValueError:
                index += 2
            continue
        index += 1
    return subs


def _read_shell_word(
    text: str,
    pos: int,
    cmd_subs: list[str] | None,
) -> tuple[str, int, bool]:
    """Read one shell word starting at ``pos``. Returns (value, next_pos, had_quotes)."""
    n = len(text)
    out: list[str] = []
    quoted = False
    index = pos
    while index < n:
        ch = text[index]
        if ch in " \t\n;&|()<>":
            # Process substitution <(...) or >(...) is part of a word.
            if ch in "<>" and index + 1 < n and text[index + 1] == "(":
                end = _scan_balanced_paren(text, index + 1)
                if cmd_subs is not None:
                    cmd_subs.append(text[index + 2 : end - 1])
                out.append(text[index:end])
                index = end
                continue
            # Array assignment foo=(...) stays attached to the assignment word.
            if ch == "(" and out and "".join(out).endswith("="):
                end = _scan_balanced_paren(text, index)
                out.append(text[index:end])
                index = end
                continue
            break
        if ch == "\\":
            quoted = True
            if index + 1 < n:
                if text[index + 1] == "\n":
                    index += 2
                    continue
                out.append(text[index + 1])
                index += 2
                continue
            index += 1
            continue
        if ch == "'":
            quoted = True
            val, index = _scan_single_quote(text, index)
            out.append(val)
            continue
        if ch == '"':
            quoted = True
            val, index = _scan_double_quote(text, index, cmd_subs)
            out.append(val)
            continue
        if ch == "`":
            inner, end = _scan_backtick(text, index, in_dquote=False)
            if cmd_subs is not None:
                cmd_subs.append(inner)
            out.append(text[index:end])
            index = end
            continue
        if ch == "$" and index + 1 < n:
            nxt = text[index + 1]
            if nxt == "'":
                quoted = True
                val, index = _scan_ansi_c_quote(text, index)
                out.append(val)
                continue
            if nxt == '"':
                quoted = True
                val, index = _scan_double_quote(text, index + 1, cmd_subs)
                out.append(val)
                continue
            if nxt == "(":
                end = _scan_balanced_paren(text, index + 1)
                if index + 2 < n and text[index + 2] == "(":
                    _note_arith_cmd_subs(text, index, end, cmd_subs)
                elif cmd_subs is not None:
                    cmd_subs.append(text[index + 2 : end - 1])
                out.append(text[index:end])
                index = end
                continue
            if nxt == "{":
                end = _scan_balanced_brace(text, index, cmd_subs)
                out.append(text[index:end])
                index = end
                continue
        out.append(ch)
        index += 1
    return "".join(out), index, quoted


def _read_heredoc_delimiter(text: str, pos: int) -> tuple[str, bool, int]:
    """Read a heredoc delimiter word; returns (delimiter, quoted, next_pos)."""
    n = len(text)
    while pos < n and text[pos] in " \t":
        pos += 1
    out: list[str] = []
    quoted = False
    while pos < n and text[pos] not in " \t\n;&|()<>":
        ch = text[pos]
        if ch == "'":
            quoted = True
            end = text.find("'", pos + 1)
            if end == -1 or "\n" in text[pos + 1 : end]:
                raise ValueError("No closing quotation")
            out.append(text[pos + 1 : end])
            pos = end + 1
        elif ch == '"':
            quoted = True
            pos += 1
            closed = False
            while pos < n and text[pos] != "\n":
                if text[pos] == "\\" and pos + 1 < n and text[pos + 1] in {'"', "\\"}:
                    out.append(text[pos + 1])
                    pos += 2
                elif text[pos] == '"':
                    pos += 1
                    closed = True
                    break
                else:
                    out.append(text[pos])
                    pos += 1
            if not closed:
                raise ValueError("No closing quotation")
        elif ch == "$" and pos + 1 < n and text[pos + 1] == "'":
            quoted = True
            val, pos = _scan_ansi_c_quote(text, pos)
            out.append(val)
        elif ch == "$" and pos + 1 < n and text[pos + 1] == '"':
            quoted = True
            val, pos = _scan_double_quote(text, pos + 1, None)
            out.append(val)
        elif ch == "\\":
            quoted = True
            if pos + 1 < n and text[pos + 1] != "\n":
                out.append(text[pos + 1])
                pos += 2
            else:
                pos += 1
        else:
            out.append(ch)
            pos += 1
    delim = "".join(out)
    if not delim:
        raise ValueError("missing heredoc delimiter")
    return delim, quoted, pos


def _consume_heredoc_bodies(text: str, pos: int, pending: list[_Heredoc]) -> int:
    """Consume queued heredoc bodies starting immediately after a newline."""
    n = len(text)
    for hd in pending:
        lines: list[str] = []
        while pos < n:
            nl = text.find("\n", pos)
            if nl == -1:
                line = text[pos:]
                pos = n
                has_nl = False
            else:
                line = text[pos:nl]
                pos = nl + 1
                has_nl = True
            stripped = line.lstrip("\t") if hd.strip_tabs else line
            if stripped == hd.delimiter:
                hd.closed = True
                break
            lines.append((stripped if hd.strip_tabs else line) + ("\n" if has_nl else ""))
        hd.body = "".join(lines)
    pending.clear()
    return pos


def _peek_fd_redir(text: str, pos: int) -> int | None:
    """If text[pos:] starts with optional digits followed by '<' or '>' (not '<('/'>('), return operator index."""
    n = len(text)
    idx = pos
    while idx < n and text[idx].isdigit():
        idx += 1
    if idx < n and text[idx] in "<>":
        # Do not mistake <(...) / >(...) process substitution for redirection.
        if idx == pos and idx + 1 < n and text[idx + 1] == "(":
            return None
        return idx
    return None


def _consume_function_name(text: str, pos: int, cmd_subs: list[str] | None) -> int:
    """Skip the name in ``function name`` / ``function name()`` so the body is parsed."""
    n = len(text)
    while pos < n and text[pos] in " \t":
        pos += 1
    if pos < n and text[pos] not in "\n;&|(){}<>#":
        _, pos, _ = _read_shell_word(text, pos, cmd_subs)
    return pos


def _consume_optional_coproc_name(text: str, pos: int, cmd_subs: list[str] | None) -> int:
    """Skip ``NAME`` only in ``coproc NAME { ... }``. A simple command keeps its first word."""
    n = len(text)
    while pos < n and text[pos] in " \t":
        pos += 1
    if pos >= n or text[pos] in "\n;&|(){}<>#":
        return pos
    _, next_pos, quoted = _read_shell_word(text, pos, None)
    look = next_pos
    while look < n and text[look] in " \t":
        look += 1
    if quoted or look >= n or text[look] != "{":
        return pos
    _, pos, _ = _read_shell_word(text, pos, cmd_subs)
    return pos


def _parse_shell(command: str) -> list[tuple[str, object]]:
    """Tokenize a (possibly multi-line) POSIX shell command into subshell/command events."""
    text = command.replace("\r\n", "\n")
    n = len(text)
    pos = 0
    events: list[tuple[str, object]] = []
    pending_heredocs: list[_Heredoc] = []
    current = _SimpleCommand()
    at_command_start = True

    def flush() -> None:
        nonlocal current
        if current.words or current.heredocs or current.here_strings or current.cmd_subs:
            events.append(("cmd", current))
            current = _SimpleCommand()

    while pos < n:
        ch = text[pos]
        if ch in " \t":
            pos += 1
            continue
        if ch == "\\" and pos + 1 < n and text[pos + 1] == "\n":
            pos += 2
            continue
        if ch == "\n":
            flush()
            events.append(("sep", "\n"))
            pos += 1
            if pending_heredocs:
                pos = _consume_heredoc_bodies(text, pos, pending_heredocs)
            at_command_start = True
            continue
        if ch == "#":
            nl = text.find("\n", pos)
            pos = n if nl == -1 else nl
            continue
        if text.startswith(("&&", "||", "|&", ";;", ";&"), pos):
            flush()
            if text.startswith(";;&", pos):
                sep, pos = ";;&", pos + 3
            elif text.startswith(";;", pos):
                sep, pos = ";;", pos + 2
            elif text.startswith(";&", pos):
                sep, pos = ";&", pos + 2
            elif text.startswith("|&", pos):
                sep, pos = "|&", pos + 2
            elif text.startswith("&&", pos):
                sep, pos = "&&", pos + 2
            else:
                sep, pos = "||", pos + 2
            events.append(("sep", sep))
            at_command_start = True
            continue
        if text.startswith(("&>>", "&>"), pos):
            pos += 3 if text.startswith("&>>", pos) else 2
            while pos < n and text[pos] in " \t":
                pos += 1
            if pos < n and text[pos] not in "\n;&|()<>":
                _, pos, _ = _read_shell_word(text, pos, current.cmd_subs)
            continue
        if ch in ";&|":
            flush()
            events.append(("sep", ch))
            pos += 1
            at_command_start = True
            continue
        if ch == "(":
            if text.startswith("((", pos):
                pos = _scan_balanced_paren(text, pos)
                at_command_start = False
                continue
            if not at_command_start and text.startswith("()", pos):
                # name() defines a function. The name is not executed; end the
                # command so the body is parsed as commands, not as arguments.
                current.words.clear()
                flush()
                pos += 2
                at_command_start = True
                continue
            flush()
            events.append(("subshell_enter", None))
            pos += 1
            at_command_start = True
            continue
        if ch == ")":
            flush()
            events.append(("subshell_exit", None))
            pos += 1
            at_command_start = False
            continue

        redir_idx = _peek_fd_redir(text, pos)
        if redir_idx is not None:
            if text.startswith("<<<", redir_idx):
                pos = redir_idx + 3
                while pos < n and text[pos] in " \t":
                    pos += 1
                if pos < n and text[pos] not in "\n;&|()<>":
                    val, pos, _ = _read_shell_word(text, pos, current.cmd_subs)
                    current.here_strings.append(val)
                continue
            if text.startswith("<<-", redir_idx) or text.startswith("<<", redir_idx):
                strip_tabs = text.startswith("<<-", redir_idx)
                pos = redir_idx + (3 if strip_tabs else 2)
                delim, quoted, pos = _read_heredoc_delimiter(text, pos)
                hd = _Heredoc(delimiter=delim, strip_tabs=strip_tabs, quoted=quoted)
                current.heredocs.append(hd)
                pending_heredocs.append(hd)
                continue
            # Other redirections (>, >>, <, >&, <&, >|, <>): consume operator + target word.
            if text.startswith((">>", ">&", "<&", ">|", "<>"), redir_idx):
                pos = redir_idx + 2
            else:
                pos = redir_idx + 1
            while pos < n and text[pos] in " \t":
                pos += 1
            if pos < n and text[pos] not in "\n;&|()<>":
                _, pos, _ = _read_shell_word(text, pos, current.cmd_subs)
            continue

        word, next_pos, had_quotes = _read_shell_word(text, pos, current.cmd_subs)
        if next_pos == pos:
            pos += 1
            continue
        pos = next_pos
        if at_command_start and not had_quotes:
            if word in _SHELL_KEYWORDS_PREFIX:
                continue
            if word in _SHELL_KEYWORDS_END:
                flush()
                continue
            if word == "function":
                pos = _consume_function_name(text, pos, current.cmd_subs)
                while pos < n and text[pos] in " \t":
                    pos += 1
                # `function name()` uses the same body rule as `name()`.
                if text.startswith("()", pos):
                    pos += 2
                continue
            if word == "coproc":
                pos = _consume_optional_coproc_name(text, pos, current.cmd_subs)
                continue
        current.words.append(word)
        at_command_start = False

    flush()
    return events


def _segments(line: str) -> list[list[str]]:
    events = _parse_shell(line)
    return [payload.words for kind, payload in events if kind == "cmd" and isinstance(payload, _SimpleCommand) and payload.words]


def _plan_cd(arguments: list[str], cwd: Path, cwd_computed: bool) -> tuple[str, Path, bool]:
    """Plan ``cd``/``pushd``. The kind is ``computed``, ``exists``, or ``missing``."""
    target = _cd_target(arguments)
    if target == "-" or UNSURE.search(target) or glob.has_magic(target):
        return "computed", cwd, True
    expanded = os.path.expanduser(target)
    if not os.path.isabs(expanded) and cwd_computed:
        return "computed", cwd, True
    proposed = Path(expanded).resolve() if os.path.isabs(expanded) else (cwd / expanded).resolve()
    if proposed.is_dir():
        return "exists", proposed, False
    return "missing", cwd, cwd_computed


def _commit_cd(
    plan: tuple[str, Path, bool],
    separator: str,
    cwd: Path,
    cwd_computed: bool,
) -> tuple[Path, bool]:
    """Apply ``cd``/``pushd`` only for separators the shell applies, and only if it works.

    ``;`` and newline leave the previous cwd when the target is missing, because
    ``cd`` fails and the next command still runs. ``&&`` keeps that cwd too.
    ``|``, ``|&``, ``&``, and ``||`` never change the next command's cwd.
    """
    if separator not in {";", "\n", "&&"}:
        return cwd, cwd_computed
    kind, proposed, _proposed_computed = plan
    if kind == "missing":
        return cwd, cwd_computed
    if kind == "computed":
        return cwd, True
    return proposed, False


def _piped_stdin_bodies(previous: _SimpleCommand, command: _SimpleCommand) -> list[str] | None:
    """Heredoc bodies of ``previous`` when a pipe feeds them to a shell or Python.

    The receiver is a shell in ``SHELLS`` or ``python`` (or ``env`` plus one of
    those) with no ``-c`` script and no heredoc or here-string of its own.
    """
    if command.heredocs or command.here_strings:
        return None
    head, rest = _head(command.words)
    if head in SHELLS:
        if _shell_c_script(rest) is not None:
            return None
    elif _is_python(head):
        if _python_code_from_args(rest) is not None:
            return None
    else:
        return None
    return [item.body for item in previous.heredocs]


def _command_targets(
    command: str,
    cwd: Path,
    *,
    cwd_computed: bool = False,
) -> tuple[list[tuple[Path, bool]], Path]:
    """Every (path, follow_symlinks) a shell command would delete, against a tracked cwd."""
    found: list[tuple[Path, bool]] = []
    try:
        events = _parse_shell(command)
    except ValueError as error:
        if (
            DELETE_WORD.search(command)
            or RMTREE.search(command)
            or PATHLIB_DELETE.search(command)
            or PY_DELETE_HINT.search(command)
        ):
            raise Unsure(f"unparsable delete: {error}") from error
        return found, cwd

    subshell_stack: list[
        tuple[Path, bool, _SimpleCommand | None, str | None, tuple[str, Path, bool] | None]
    ] = []
    prev_cmd: _SimpleCommand | None = None
    last_sep: str | None = None
    pending_cd: tuple[str, Path, bool] | None = None
    for kind, payload in events:
        if kind == "subshell_enter":
            subshell_stack.append((cwd, cwd_computed, prev_cmd, last_sep, pending_cd))
            prev_cmd = None
            last_sep = None
            pending_cd = None
            continue
        if kind == "subshell_exit":
            if subshell_stack:
                cwd, cwd_computed, prev_cmd, last_sep, pending_cd = subshell_stack.pop()
            continue
        if kind == "sep":
            if pending_cd is not None:
                cwd, cwd_computed = _commit_cd(pending_cd, str(payload), cwd, cwd_computed)
                pending_cd = None
            last_sep = str(payload)
            continue
        if not isinstance(payload, _SimpleCommand):
            continue
        cmd = payload
        previous = prev_cmd
        prev_cmd = cmd
        incoming = last_sep
        last_sep = None
        piped_bodies: list[str] = []
        if incoming in {"|", "|&"} and isinstance(previous, _SimpleCommand):
            bodies = _piped_stdin_bodies(previous, cmd)
            if bodies:
                piped_bodies = bodies

        # Inspect command substitutions $(...) / `...` in a subshell copy of cwd state.
        for sub_cmd in cmd.cmd_subs:
            sub_found, _ = _command_targets(sub_cmd, cwd, cwd_computed=cwd_computed)
            found.extend(sub_found)

        # Unquoted heredoc bodies still expand $(...) and `...` in POSIX shells.
        for hd in cmd.heredocs:
            if not hd.quoted:
                for sub_cmd in _scan_heredoc_cmd_subs(hd.body):
                    sub_found, _ = _command_targets(sub_cmd, cwd, cwd_computed=cwd_computed)
                    found.extend(sub_found)

        head, rest = _head(cmd.words)
        if _computed_command_head(head):
            raise Unsure("computed command head")
        if head == "eval":
            script = " ".join(rest)
            if script:
                sub_found, _ = _command_targets(script, cwd, cwd_computed=cwd_computed)
                found.extend(sub_found)
            continue
        if head in {"cd", "pushd"}:
            pending_cd = _plan_cd(rest, cwd, cwd_computed)
            continue

        if _is_python(head):
            py_sources: list[str] = []
            c_code = _python_code_from_args(rest)
            if c_code is not None:
                py_sources.append(c_code)
            py_sources.extend(hd.body for hd in cmd.heredocs)
            py_sources.extend(cmd.here_strings)
            py_sources.extend(piped_bodies)
            for py_src in py_sources:
                py_entries = _python_entries(py_src)
                if py_entries and cwd_computed and _needs_computed_cwd([item for item, _follow in py_entries]):
                    raise Unsure("cd to a computed path before a delete")
                if py_entries:
                    found.extend(_expand_entries(py_entries, cwd))
            continue

        if head in _SCRIPT_DOT_COMMANDS and any(_is_process_sub_word(word) for word in rest):
            raise Unsure("shell process substitution")

        if head in SHELLS:
            shell_scripts: list[str] = []
            c_script = _shell_c_script(rest)
            if c_script is not None:
                shell_scripts.append(c_script)
            elif any(_is_process_sub_word(word) for word in rest):
                raise Unsure("shell process substitution")
            shell_scripts.extend(hd.body for hd in cmd.heredocs)
            shell_scripts.extend(cmd.here_strings)
            shell_scripts.extend(piped_bodies)
            for script in shell_scripts:
                sub_found, _ = _command_targets(script, cwd, cwd_computed=cwd_computed)
                found.extend(sub_found)
            continue

        if head == "git":
            seg_cwd, seg_computed = _git_effective_cwd(rest, cwd, cwd_computed)
            raw = _git_clean_targets(_drop_git_options(rest)) or []
            if raw:
                if seg_computed and _needs_computed_cwd(raw):
                    raise Unsure("cd to a computed path before a delete")
                found.extend(_expand_entries([(item, False) for item in raw], seg_cwd))
            continue

        found.extend(_segment_targets(cmd.words, cwd, cwd_computed=cwd_computed))
    return found, cwd


def _expand(raw: str, cwd: Path) -> list[Path]:
    if UNSURE.search(raw):
        raise Unsure(f"computed delete target: {raw}")
    if _BRACE_EXPANSION.search(raw):
        raise Unsure(f"brace-expanded delete target: {raw}")
    expanded = os.path.expanduser(raw)
    base = expanded if os.path.isabs(expanded) else str(cwd / expanded)
    if glob.has_magic(base):
        return [Path(item).resolve() for item in glob.glob(base, recursive=True)]
    return [Path(os.path.normpath(base))]


def command_targets(command: str, cwd: Path | None = None) -> list[Path]:
    """Paths a command would delete; tree ops resolve symlink operands to their realpath."""
    entries, _ = _command_targets(command, (cwd or Path.cwd()).resolve())
    resolved: list[Path] = []
    for path, follow in entries:
        resolved.append(_resolve_follow(path) if follow else path)
    return list(dict.fromkeys(resolved))


def _git_subprocess_env() -> dict[str, str]:
    """Return os.environ without repo-redirecting GIT_* keys."""
    out: dict[str, str] = {}
    for key, value in os.environ.items():
        if key in _GIT_ENV_BLOCKLIST:
            continue
        if key.startswith(_GIT_ENV_PREFIX_BLOCKLIST):
            continue
        out[key] = value
    return out


def _git(cwd: Path, *argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(  # nosec B603 B607 - fixed git argv.
        ["git", "-C", str(cwd), *argv],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
        env=_git_subprocess_env(),
    )


def _existing(path: Path) -> Path:
    while not path.exists() and path != path.parent:
        path = path.parent
    return path if path.is_dir() else path.parent


def _patterns(project: Path | None) -> list[str]:
    patterns = list(DEFAULT_ALLOW)
    for root in {project, Path.home()} - {None}:
        allow = Path(root) / STATE_DIR / ALLOW_FILE
        if allow.is_file():
            patterns += [line.strip() for line in allow.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")]
    return [os.path.expanduser(item) for item in patterns]


def _pattern_regex(pattern: str) -> re.Pattern:
    """`**/` spans any directories, `*` stays inside one segment; a trailing `/**` also matches the dir."""
    out, index = "", 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            out, index = out + "(?:.*/)?", index + 3
        elif pattern.startswith("/**", index) and index + 3 == len(pattern):
            out, index = out + "(?:/.*)?", index + 3
        elif pattern.startswith("**", index):
            out, index = out + ".*", index + 2
        elif pattern[index] == "*":
            out, index = out + "[^/]*", index + 1
        elif pattern[index] == "?":
            out, index = out + "[^/]", index + 1
        else:
            out, index = out + re.escape(pattern[index]), index + 1
    return re.compile(out + r"\Z")


def allow_listed(path: Path, project: Path | None = None) -> bool:
    text = str(path).replace("\\", "/")
    return any(_pattern_regex(pattern.replace("\\", "/")).match(text) for pattern in _patterns(project))


def _blob_bytes(top: Path, rev: str, relative: str) -> bytes | None:
    proc = subprocess.run(  # nosec B603 B607 - fixed git show of one rev
        ["git", "-C", str(top), "show", f"{rev}:{relative}"],
        capture_output=True,
        check=False,
        timeout=30,
        env=_git_subprocess_env(),
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def _bytes_match_rev(path: Path, top: Path, rev: str) -> bool:
    try:
        relative = path.resolve().relative_to(top.resolve()).as_posix()
        data = path.read_bytes()
    except (OSError, ValueError):
        return False
    blob = _blob_bytes(top, rev, relative)
    return blob is not None and blob == data


def _remote_default_rev(top: Path) -> str | None:
    """Remote default from ``refs/remotes/origin/HEAD``. No hard-coded branch name."""
    proc = _git(top, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD")
    if proc.returncode != 0:
        return None
    ref = proc.stdout.strip()
    return ref or None


def _recreatable_untracked(path: Path, top: Path, rev: str | None) -> bool:
    revs = ["HEAD"]
    if rev and rev not in revs:
        revs.append(rev)
    remote = _remote_default_rev(top)
    if remote and remote not in revs:
        revs.append(remote)
    return any(_bytes_match_rev(path, top, item) for item in revs)


def _git_reason(path: Path, top: Path, rev: str | None = None) -> str:
    status = _git(top, "status", "--porcelain", "--ignored", "--untracked-files=all", "--", str(path))
    if status.returncode != 0:
        return "git status failed"
    dirty = [line for line in status.stdout.splitlines() if line.strip()]
    if dirty:
        if all(line.startswith("??") for line in dirty) and _recreatable_untracked(path, top, rev):
            return ""
        return f"{len(dirty)} untracked/modified/ignored file(s), e.g. {dirty[0][3:]}"
    if _git(top, "rev-parse", "--abbrev-ref", "@{u}").returncode != 0:
        return "branch has no upstream (nothing pushed)"
    ahead = _git(top, "rev-list", "--count", "@{u}..HEAD").stdout.strip()
    if ahead not in {"", "0"}:
        return f"branch is {ahead} commit(s) ahead of its upstream"
    if top == path or top.is_relative_to(path):
        refs = _git(top, "for-each-ref", "--format=%(refname:short) %(upstream:track) %(upstream)", "refs/heads")
        for line in refs.stdout.splitlines():
            parts = line.split()
            if len(parts) < 2 or "ahead" in line:
                return f"local branch {parts[0]} is unpushed"
        if _git(top, "stash", "list").stdout.strip():
            return "repo has stash entries"
    return ""



def session_manifest_path(explicit: Path | None = None) -> Path | None:
    """Return the per-session created-paths manifest path, or None if unset."""
    if explicit is not None:
        return Path(explicit)
    raw = os.environ.get(SESSION_CREATED_MANIFEST_ENV, "").strip()
    if not raw:
        return None
    return Path(os.path.expanduser(raw))


def _session_hmac_key_path(manifest: Path) -> Path:
    """Per-manifest HMAC key file outside any checkout (XDG config)."""
    digest = hashlib.sha256(str(manifest.resolve()).encode("utf-8")).hexdigest()[:24]
    from runtime.user_paths import config_dir, legacy_config_dir, prefer_existing

    root = prefer_existing(config_dir(), legacy_config_dir())
    return root / "session-manifest-hmac-keys" / f"{digest}.hmac-key"


def _read_session_hmac_key(manifest: Path) -> bytes | None:
    """Return the per-session HMAC key, or None when unset (forge-closed on load)."""
    raw = os.environ.get(SESSION_MANIFEST_HMAC_ENV, "").strip()
    if raw:
        return raw.encode("utf-8")
    store = _session_hmac_key_path(manifest)
    if store.is_file():
        return store.read_bytes()
    return None


def _load_or_create_session_hmac_key(manifest: Path) -> bytes:
    """Return the per-session HMAC key; create one outside the tree when missing."""
    existing = _read_session_hmac_key(manifest)
    if existing is not None:
        return existing
    store = _session_hmac_key_path(manifest)
    store.parent.mkdir(parents=True, exist_ok=True)
    hmac_key = secrets.token_bytes(32)
    store.write_bytes(hmac_key)
    store.chmod(0o600)
    return hmac_key


def _manifest_hmac_payload(
    roots: list[str],
    paths: list[str],
    *,
    started_at: str = "",
    preexist_paths: list[str] | None = None,
    preexist_inodes: list[str] | None = None,
    proofs: list[str] | None = None,
) -> bytes:
    body = (
        f"schema={SESSION_MANIFEST_SCHEMA}\n"
        f"started_at={started_at}\n"
        + "roots=" + "\0".join(sorted(roots))
        + "\npaths=" + "\0".join(sorted(paths))
        + "\npreexist_paths=" + "\0".join(sorted(preexist_paths or []))
        + "\npreexist_inodes=" + "\0".join(sorted(preexist_inodes or []))
        + "\nproofs=" + "\0".join(sorted(proofs or []))
    )
    return body.encode("utf-8")


def _sign_manifest(
    hmac_key: bytes,
    roots: list[str],
    paths: list[str],
    *,
    started_at: str = "",
    preexist_paths: list[str] | None = None,
    preexist_inodes: list[str] | None = None,
    proofs: list[str] | None = None,
) -> str:
    return hmac.new(
        hmac_key,
        _manifest_hmac_payload(
            roots,
            paths,
            started_at=started_at,
            preexist_paths=preexist_paths,
            preexist_inodes=preexist_inodes,
            proofs=proofs,
        ),
        hashlib.sha256,
    ).hexdigest()


def _verify_manifest_hmac(
    hmac_key: bytes,
    roots: list[str],
    paths: list[str],
    supplied: str,
    *,
    started_at: str = "",
    preexist_paths: list[str] | None = None,
    preexist_inodes: list[str] | None = None,
    proofs: list[str] | None = None,
) -> bool:
    if not supplied or not isinstance(supplied, str):
        return False
    expected = _sign_manifest(
        hmac_key,
        roots,
        paths,
        started_at=started_at,
        preexist_paths=preexist_paths,
        preexist_inodes=preexist_inodes,
        proofs=proofs,
    )
    return hmac.compare_digest(expected, supplied.strip().lower())


def _session_seal_path(manifest: Path) -> Path:
    """Sibling write-once seal next to the session manifest."""
    return Path(str(manifest) + SESSION_MANIFEST_SEAL_SUFFIX)


def _seal_inventory_digest(
    started_at: str,
    preexist_paths: list[str],
    preexist_inodes: list[str],
) -> str:
    body = (
        f"started_at={started_at}\n"
        + "preexist_paths="
        + "\0".join(sorted(preexist_paths))
        + "\npreexist_inodes="
        + "\0".join(sorted(preexist_inodes))
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _write_session_seal(
    manifest: Path,
    *,
    started_at: str,
    preexist_paths: list[str],
    preexist_inodes: list[str],
) -> None:
    """
    Create a write-once seal (O_CREAT|O_EXCL, mode 0444) pinning init inventory.
    """
    seal = _session_seal_path(manifest)
    st = manifest.stat()
    payload = {
        "schema": SESSION_SEAL_SCHEMA,
        "inventory_sha256": _seal_inventory_digest(
            started_at, preexist_paths, preexist_inodes
        ),
        "manifest_inode": int(st.st_ino),
        "floor_entry_count": len(preexist_paths),
    }
    raw = (json.dumps(payload, indent=2, sort_keys=True) + chr(10)).encode("utf-8")
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    fd = os.open(str(seal), flags, 0o444)
    try:
        os.write(fd, raw)
    finally:
        os.close(fd)
    os.chmod(str(seal), 0o444)


def _load_seal_dict(seal: Path) -> dict | None:
    try:
        raw = seal.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _session_seal_ok(
    manifest: Path,
    *,
    started_at: str,
    preexist_paths: list[str],
    preexist_inodes: list[str],
) -> bool:
    """
    Fail closed when seal missing, changed, mismatched, or inventory laundered.
    """
    seal = _session_seal_path(manifest)
    if not seal.is_file():
        return False
    data = _load_seal_dict(seal)
    if data is None:
        return False
    if data.get("schema") != SESSION_SEAL_SCHEMA:
        return False
    expected = data.get("inventory_sha256")
    if not isinstance(expected, str) or not expected:
        return False
    digest = _seal_inventory_digest(started_at, preexist_paths, preexist_inodes)
    if not hmac.compare_digest(expected.strip().lower(), digest.lower()):
        return False
    try:
        mst = manifest.stat()
        sst = seal.stat()
    except OSError:
        return False
    inode = data.get("manifest_inode")
    if not isinstance(inode, int) or inode != int(mst.st_ino):
        return False
    floor_count = data.get("floor_entry_count")
    if not isinstance(floor_count, int) or floor_count < 0:
        return False
    if floor_count > 0 and len(preexist_paths) == 0:
        return False
    try:
        started_f = float(started_at)
    except (TypeError, ValueError):
        return False
    # started_at must not predate seal ctime/mtime (small skew).
    seal_floor = max(float(sst.st_mtime), float(sst.st_ctime)) - SESSION_SEAL_TIME_TOLERANCE_S
    if started_f < seal_floor:
        return False
    return True


def _inode_token(st: os.stat_result) -> str:
    return f"{st.st_dev}:{st.st_ino}"


def _birth_or_ctime_ns(st: os.stat_result) -> int:
    birth = getattr(st, "st_birthtime", None)
    if birth is not None:
        try:
            return int(float(birth) * 1_000_000_000)
        except (TypeError, ValueError, OSError):
            # Birthtime present but unusable; fall through to ctime.
            pass
    return int(getattr(st, "st_ctime_ns", int(st.st_ctime * 1_000_000_000)))


def _proof_token(real: Path, st: os.stat_result) -> str:
    return f"{real}|{_inode_token(st)}|{_birth_or_ctime_ns(st)}"


def _record_preexist_entry(
    entry: os.DirEntry,
    paths: set[str],
    inodes: set[str],
    stack: list[Path],
) -> None:
    """Add one scandir entry to the preexist inventory or descend into dirs."""
    if entry.is_symlink():
        return
    if entry.is_dir(follow_symlinks=False):
        stack.append(Path(entry.path))
        return
    if not entry.is_file(follow_symlinks=False):
        return
    st = entry.stat(follow_symlinks=False)
    paths.add(str(Path(os.path.realpath(entry.path))))
    inodes.add(_inode_token(st))


def _walk_preexist_root(real_root: Path, paths: set[str], inodes: set[str], cap: int) -> None:
    """DFS walk one containment root into path/inode sets (capped)."""
    stack = [real_root]
    while stack and len(paths) < cap:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    if len(paths) >= cap:
                        break
                    try:
                        _record_preexist_entry(entry, paths, inodes, stack)
                    except OSError:
                        # Unreadable entry; skip and keep scanning.
                        continue
        except OSError:
            # Unreadable directory; skip remainder of this branch.
            continue


def _snapshot_preexist(roots: list[Path]) -> tuple[list[str], list[str]]:
    """
    Inventory existing real paths + inodes under floors at session start.

    Fail-closed bound: capped walk; errors skip that root's remainder.
    """
    paths: set[str] = set()
    inodes: set[str] = set()
    cap = 50_000
    for root in roots:
        if len(paths) >= cap:
            break
        try:
            real_root = Path(os.path.realpath(root))
        except OSError:
            continue
        if not real_root.is_dir():
            continue
        _walk_preexist_root(real_root, paths, inodes, cap)
    return sorted(paths), sorted(inodes)


def _load_manifest_dict(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _realpath_root(path: Path) -> Path | None:
    try:
        return Path(os.path.realpath(path))
    except OSError:
        return None


def _is_acceptable_containment_root(root: Path) -> bool:
    """Return False for ``/``, near-root dirs, ``$HOME``, and never-touch paths."""
    resolved = _realpath_root(root)
    if resolved is None:
        return False
    # Depth < 3 => filesystem root or a single top-level dir (/, /etc, /home, /tmp).
    if len(resolved.parts) < 3:
        return False
    try:
        home = _realpath_root(Path.home())
        if home is not None and resolved == home:
            return False
    except OSError:
        # HOME unresolvable: skip the home equality check only.
        pass
    if never_touch(resolved):
        return False
    return True


def _discover_git_toplevel(hint: Path | None = None) -> Path | None:
    """
    Real ``git rev-parse --show-toplevel`` from hint and process cwd only.

    ``CHAOS_SESSION_WORKTREE`` is never probed here — it must not expand floors.
    Git env redirects are scrubbed inside ``_git``.
    """
    probes: list[Path] = []
    if hint is not None:
        probes.append(hint)
    probes.append(Path.cwd())
    seen: set[str] = set()
    for probe in probes:
        key = str(probe)
        if key in seen:
            continue
        seen.add(key)
        try:
            cwd = _existing(probe)
        except OSError:
            continue
        result = _git(cwd, "rev-parse", "--show-toplevel")
        if result.returncode != 0:
            continue
        top_raw = result.stdout.strip()
        if not top_raw:
            continue
        top = _realpath_root(Path(top_raw))
        if top is None or not _is_acceptable_containment_root(top):
            continue
        return top
    return None


def _scoped_session_floor(manifest: Path) -> Path | None:
    """
    Return the scoped temp dir for this manifest.

    Uses ``…/chaos-engine-sessions/<id>`` when present, else an acceptable
    manifest parent (never ``/`` or ``$HOME``).
    """
    parent = _realpath_root(manifest.parent)
    if parent is None:
        return None
    parts = parent.parts
    for index, part in enumerate(parts):
        if part != "chaos-engine-sessions" or index + 1 >= len(parts):
            continue
        candidate = Path(parts[0]).joinpath(*parts[1 : index + 2])
        resolved = _realpath_root(candidate)
        if resolved is not None and _is_acceptable_containment_root(resolved):
            return resolved
    if _is_acceptable_containment_root(parent):
        return parent
    return None


def _floor_containment_roots(manifest: Path) -> list[Path]:
    """
    Independently derived max roots.

    A floor must sit inside the scoped manifest floor, or be the process cwd's
    real git toplevel. ``CHAOS_SESSION_WORKTREE`` never adds a floor.
    """
    floors: list[Path] = []
    seen: set[str] = set()
    scoped = _scoped_session_floor(manifest)
    if scoped is not None:
        floors.append(scoped)
        seen.add(str(scoped))
    # Process cwd real toplevel only (git env scrubbed; WORKTREE env not probed).
    cwd_top = _discover_git_toplevel()
    if cwd_top is not None and str(cwd_top) not in seen:
        floors.append(cwd_top)
    return floors


def _root_under_floors(root: Path, floors: list[Path]) -> bool:
    if not floors:
        return False
    return any(_is_under_root(root, floor) for floor in floors)


def _signed_roots_within_floors(root_strs: list[str], floors: list[Path]) -> bool:
    """False when any signed JSON root escapes the live floor (policy forge)."""
    if not root_strs:
        return True
    if not floors:
        return False
    for item in root_strs:
        resolved = _realpath_root(Path(os.path.expanduser(item.strip())))
        if resolved is None:
            return False
        if not _is_acceptable_containment_root(resolved):
            return False
        if not _root_under_floors(resolved, floors):
            return False
    return True


def _resolve_containment_roots(
    *,
    manifest: Path,
    explicit_roots: list[Path] | None = None,
    data_roots: list | None = None,
) -> list[Path]:
    """
    Roots that may contain allowlisted session-created paths.

    Floor roots come only from the scoped manifest dir and a real git toplevel.
    Env / explicit / JSON candidates are untrusted: kept only when acceptable and
    under those floors. ``CHAOS_SESSION_WORKTREE`` is never a root and never a discover probe.
    """
    floors = _floor_containment_roots(manifest)
    candidates: list[Path] = []
    if explicit_roots:
        candidates.extend(Path(r) for r in explicit_roots)
    env_raw = os.environ.get(SESSION_CONTAINMENT_ROOTS_ENV, "").strip()
    if env_raw:
        for part in env_raw.split(os.pathsep):
            part = part.strip()
            if part:
                candidates.append(Path(os.path.expanduser(part)))
    # Intentionally ignore SESSION_WORKTREE_ENV (never a root; never expands floors).
    if data_roots:
        for item in data_roots:
            if isinstance(item, str) and item.strip():
                candidates.append(Path(os.path.expanduser(item.strip())))
    out: list[Path] = list(floors)
    seen: set[str] = {str(item) for item in floors}
    for root in candidates:
        resolved = _realpath_root(root)
        if resolved is None:
            continue
        if not _is_acceptable_containment_root(resolved):
            continue
        if not _root_under_floors(resolved, floors):
            continue
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        out.append(resolved)
    return out


def _is_under_root(real: Path, root: Path) -> bool:
    try:
        real.relative_to(root)
        return True
    except ValueError:
        return False


def _path_escape_or_symlink_reason(path: Path, roots: list[Path]) -> str:
    """
    Non-empty when path is a symlink, escapes containment, or cannot be resolved."""
    try:
        expanded = Path(os.path.expanduser(str(path)))
    except OSError:
        return "unresolvable path"
    # Reject symlink leafs and any symlink in the recorded path chain.
    probe = expanded if expanded.is_absolute() else Path.cwd() / expanded
    try:
        # Walk parents for symlinks; also reject the leaf when it is a symlink.
        if probe.is_symlink():
            return "symlink refused"
        for parent in [probe, *probe.parents]:
            if parent.is_symlink():
                return "symlink refused"
            if parent == parent.anchor or parent == Path(parent.anchor):
                break
    except OSError:
        return "unresolvable path"
    try:
        real = Path(os.path.realpath(probe))
    except OSError:
        return "unresolvable path"
    if not any(_is_under_root(real, root) for root in roots):
        return "outside session containment"
    return ""


def _str_list(raw) -> list[str] | None:
    if not isinstance(raw, list):
        return None
    return [item for item in raw if isinstance(item, str) and item.strip()]


def _verified_manifest_fields(path: Path) -> tuple[list[str], list[str], list[str], list[str], list[str]] | None:
    """
    Return (roots, paths, preexist_paths, preexist_inodes, proofs) when HMAC+schema ok.
    """
    data = _load_manifest_dict(path)
    if data is None:
        return None
    path_strs = _str_list(data.get("paths"))
    root_strs = _str_list(data.get("roots"))
    preexist_paths = _str_list(data.get("preexist_paths"))
    preexist_inodes = _str_list(data.get("preexist_inodes"))
    proofs = _str_list(data.get("proofs"))
    started_at = data.get("started_at")
    supplied = data.get("hmac")
    if None in (path_strs, root_strs, preexist_paths, preexist_inodes, proofs):
        return None
    if not isinstance(started_at, (int, float, str)):
        return None
    try:
        hmac_key = _read_session_hmac_key(path)
    except OSError:
        return None
    if hmac_key is None:
        return None
    if not _verify_manifest_hmac(
        hmac_key,
        root_strs,
        path_strs,
        supplied if isinstance(supplied, str) else "",
        started_at=str(started_at),
        preexist_paths=preexist_paths,
        preexist_inodes=preexist_inodes,
        proofs=proofs,
    ):
        return None
    if not _session_seal_ok(
        path,
        started_at=str(started_at),
        preexist_paths=preexist_paths,
        preexist_inodes=preexist_inodes,
    ):
        return None
    return root_strs, path_strs, preexist_paths, preexist_inodes, proofs


def _proof_map(proofs: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in proofs:
        if "|" not in item:
            continue
        out[item.split("|", 1)[0]] = item
    return out


def _proven_session_paths(
    path_strs: list[str],
    roots: list[Path],
    preexist_paths: set[str],
    preexist_inodes: set[str],
    proof_by_path: dict[str, str],
) -> set[str]:
    out: set[str] = set()
    for item in path_strs:
        candidate = Path(os.path.expanduser(item.strip()))
        if _path_escape_or_symlink_reason(candidate, roots):
            continue
        try:
            real = Path(os.path.realpath(candidate))
            st = real.stat()
        except OSError:
            continue
        real_s = str(real)
        if real_s in preexist_paths or _inode_token(st) in preexist_inodes:
            continue
        expected = proof_by_path.get(real_s)
        if expected is None or expected != _proof_token(real, st):
            continue
        out.add(real_s)
    return out


def load_session_created_paths(manifest: Path | None = None) -> set[str]:
    """
    Absolute realpath strings recorded as self-created by this session.

    Forge-closed: missing/invalid HMAC yields an empty set. Signed JSON ``roots``
    that escape the live floor fail the whole load. Paths that escape containment
    or are symlinks are dropped. Containment is never expanded from JSON alone.
    Pre-existing inventory and per-path proofs must verify or the entry is dropped.
    """
    path = session_manifest_path(manifest)
    if path is None or not path.is_file():
        return set()
    fields = _verified_manifest_fields(path)
    if fields is None:
        return set()
    root_strs, path_strs, preexist_paths, preexist_inodes, proofs = fields
    floors = _floor_containment_roots(path)
    if not _signed_roots_within_floors(root_strs, floors):
        return set()
    roots = _resolve_containment_roots(manifest=path, data_roots=None)
    return _proven_session_paths(
        path_strs,
        roots,
        set(preexist_paths),
        set(preexist_inodes),
        _proof_map(proofs),
    )


def init_session_created_manifest(
    *,
    manifest: Path | None = None,
    roots: list | None = None,
) -> Path:
    """
    Create an empty HMAC manifest with session-start inventory.

    Call before creating session files, then ``record_session_created_paths``.
    Idempotent when an existing manifest verifies.
    """
    path = session_manifest_path(manifest)
    if path is None:
        path = (
            Path(tempfile.gettempdir())
            / "chaos-engine-sessions"
            / str(os.getpid())
            / SESSION_CREATED_MANIFEST_NAME
        )
        os.environ[SESSION_CREATED_MANIFEST_ENV] = str(path)
    path = Path(path)
    if path.is_file():
        data = _load_manifest_dict(path)
        if data is not None:
            try:
                hmac_key = _read_session_hmac_key(path)
            except OSError:
                hmac_key = None
            roots_raw = data.get("roots") if isinstance(data.get("roots"), list) else []
            paths_raw = data.get("paths") if isinstance(data.get("paths"), list) else []
            pre_p = data.get("preexist_paths") if isinstance(data.get("preexist_paths"), list) else []
            pre_i = data.get("preexist_inodes") if isinstance(data.get("preexist_inodes"), list) else []
            proofs = data.get("proofs") if isinstance(data.get("proofs"), list) else []
            started_at = data.get("started_at")
            if (
                hmac_key is not None
                and isinstance(started_at, (int, float, str))
                and _verify_manifest_hmac(
                    hmac_key,
                    [x for x in roots_raw if isinstance(x, str)],
                    [x for x in paths_raw if isinstance(x, str)],
                    data.get("hmac") if isinstance(data.get("hmac"), str) else "",
                    started_at=str(started_at),
                    preexist_paths=[x for x in pre_p if isinstance(x, str)],
                    preexist_inodes=[x for x in pre_i if isinstance(x, str)],
                    proofs=[x for x in proofs if isinstance(x, str)],
                )
                and _session_seal_ok(
                    path,
                    started_at=str(started_at),
                    preexist_paths=[x for x in pre_p if isinstance(x, str)],
                    preexist_inodes=[x for x in pre_i if isinstance(x, str)],
                )
            ):
                return path
    explicit_roots = [Path(r) for r in (roots or [])]
    containment = _resolve_containment_roots(manifest=path, explicit_roots=explicit_roots or None)
    preexist_paths, preexist_inodes = _snapshot_preexist(containment)
    started_at = time.time()
    root_strs = sorted({str(r) for r in containment})
    path_strs: list[str] = []
    proof_strs: list[str] = []
    hmac_key = _load_or_create_session_hmac_key(path)
    payload = {
        "schema": SESSION_MANIFEST_SCHEMA,
        "started_at": started_at,
        "roots": root_strs,
        "paths": path_strs,
        "preexist_paths": preexist_paths,
        "preexist_inodes": preexist_inodes,
        "proofs": proof_strs,
        "hmac": _sign_manifest(
            hmac_key,
            root_strs,
            path_strs,
            started_at=str(started_at),
            preexist_paths=preexist_paths,
            preexist_inodes=preexist_inodes,
            proofs=proof_strs,
        ),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + chr(10), encoding="utf-8")
    path.chmod(0o600)
    _write_session_seal(
        path,
        started_at=str(started_at),
        preexist_paths=preexist_paths,
        preexist_inodes=preexist_inodes,
    )
    return path


def _refuse_or_proof_new_path(
    candidate: Path,
    *,
    containment: list[Path],
    preexist_path_set: set[str],
    preexist_inode_set: set[str],
    started_ns: int,
) -> tuple[str, str]:
    """
    Return (realpath, proof_token) or raise PermissionError.
    """
    reason = _path_escape_or_symlink_reason(candidate, containment)
    if reason:
        raise PermissionError(f"session-manifest refused `{candidate}`: {reason}")
    try:
        real = Path(os.path.realpath(candidate))
        st = real.stat()
    except OSError as exc:
        raise PermissionError(f"session-manifest refused `{candidate}`: unresolvable path") from exc
    hit = never_touch(real)
    if hit:
        raise PermissionError(f"session-manifest refused `{candidate}`: {hit}")
    real_s = str(real)
    if real_s in preexist_path_set or _inode_token(st) in preexist_inode_set:
        raise PermissionError(
            f"session-manifest refused `{candidate}`: pre-existing before session start"
        )
    # Fail closed: birth/ctime must not predate session start (1s skew).
    if _birth_or_ctime_ns(st) < started_ns - 1_000_000_000:
        raise PermissionError(
            f"session-manifest refused `{candidate}`: pre-existing before session start"
        )
    return real_s, _proof_token(real, st)



def _ensure_session_manifest_path(manifest: Path | None) -> Path:
    path = session_manifest_path(manifest)
    if path is not None:
        return Path(path)
    path = (
        Path(tempfile.gettempdir())
        / "chaos-engine-sessions"
        / str(os.getpid())
        / SESSION_CREATED_MANIFEST_NAME
    )
    os.environ[SESSION_CREATED_MANIFEST_ENV] = str(path)
    return Path(path)


def _inventory_from_manifest(path: Path, data: dict) -> tuple[object, float, int, list[str], list[str]]:
    """Return started_at, started_f, started_ns, preexist_paths, preexist_inodes after seal check."""
    started_at = data.get("started_at")
    if not isinstance(started_at, (int, float, str)):
        raise PermissionError("session-manifest refused: missing started_at")
    try:
        started_f = float(started_at)
    except (TypeError, ValueError) as exc:
        raise PermissionError("session-manifest refused: bad started_at") from exc
    pre_p = data.get("preexist_paths") if isinstance(data.get("preexist_paths"), list) else None
    pre_i = data.get("preexist_inodes") if isinstance(data.get("preexist_inodes"), list) else None
    if pre_p is None or pre_i is None:
        raise PermissionError("session-manifest refused: missing session-start inventory")
    preexist_paths = [x for x in pre_p if isinstance(x, str) and x.strip()]
    preexist_inodes = [x for x in pre_i if isinstance(x, str) and x.strip()]
    if not _session_seal_ok(
        path,
        started_at=str(started_at),
        preexist_paths=preexist_paths,
        preexist_inodes=preexist_inodes,
    ):
        raise PermissionError("session-manifest refused: seal missing or mismatched")
    try:
        started_ns = int(started_f * 1_000_000_000)
    except (OverflowError, ValueError) as exc:
        raise PermissionError("session-manifest refused: bad started_at") from exc
    return started_at, started_f, started_ns, preexist_paths, preexist_inodes


def _retain_prior_session_entries(
    path: Path, containment: list[Path]
) -> tuple[set[str], dict[str, str]]:
    accepted: set[str] = set()
    proof_by_path: dict[str, str] = {}
    for prior in load_session_created_paths(path):
        if _path_escape_or_symlink_reason(Path(prior), containment):
            continue
        try:
            real = Path(prior)
            st = real.stat()
        except OSError:
            continue
        token = _proof_token(real, st)
        accepted.add(str(real))
        proof_by_path[str(real)] = token
    return accepted, proof_by_path


def _persist_session_manifest(
    path: Path,
    *,
    started_at: object,
    started_f: float,
    containment: list[Path],
    accepted: set[str],
    proof_by_path: dict[str, str],
    preexist_path_set: set[str],
    preexist_inode_set: set[str],
) -> Path:
    root_strs = sorted({str(r) for r in containment})
    path_strs = sorted(accepted)
    proof_strs = sorted(proof_by_path[p] for p in path_strs if p in proof_by_path)
    hmac_key = _load_or_create_session_hmac_key(path)
    started_store = started_at if isinstance(started_at, (int, float)) else started_f
    pre_paths_sorted = sorted(preexist_path_set)
    pre_inodes_sorted = sorted(preexist_inode_set)
    payload = {
        "schema": SESSION_MANIFEST_SCHEMA,
        "started_at": started_store,
        "roots": root_strs,
        "paths": path_strs,
        "preexist_paths": pre_paths_sorted,
        "preexist_inodes": pre_inodes_sorted,
        "proofs": proof_strs,
        "hmac": _sign_manifest(
            hmac_key,
            root_strs,
            path_strs,
            started_at=str(started_store),
            preexist_paths=pre_paths_sorted,
            preexist_inodes=pre_inodes_sorted,
            proofs=proof_strs,
        ),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + chr(10), encoding="utf-8")
    path.chmod(0o600)
    return path


def record_session_created_paths(
    paths: list,
    *,
    manifest: Path | None = None,
    roots: list | None = None,
) -> Path:
    """
    Append contained absolute paths to the HMAC-bound session manifest.

    Tool-only writer. Rejects symlinks, traversal, absolute paths outside
    the session scoped dir / worktree containment roots, and any path that
    existed before the session started (inventory / inode / birth-or-ctime).
    Creates parent dirs. Initializes the session-start inventory when missing.
    """
    path = _ensure_session_manifest_path(manifest)
    explicit_roots = [Path(r) for r in (roots or [])]
    if not path.is_file():
        init_session_created_manifest(manifest=path, roots=explicit_roots or None)
    data = _load_manifest_dict(path)
    if data is None:
        raise PermissionError("session-manifest refused: unreadable manifest")
    containment = _resolve_containment_roots(manifest=path, explicit_roots=explicit_roots or None)
    started_at, started_f, started_ns, preexist_paths, preexist_inodes = _inventory_from_manifest(
        path, data
    )
    preexist_path_set = set(preexist_paths)
    preexist_inode_set = set(preexist_inodes)
    accepted, proof_by_path = _retain_prior_session_entries(path, containment)
    for item in paths:
        real_s, token = _refuse_or_proof_new_path(
            Path(os.path.expanduser(str(item))),
            containment=containment,
            preexist_path_set=preexist_path_set,
            preexist_inode_set=preexist_inode_set,
            started_ns=started_ns,
        )
        accepted.add(real_s)
        proof_by_path[real_s] = token
    return _persist_session_manifest(
        path,
        started_at=started_at,
        started_f=started_f,
        containment=containment,
        accepted=accepted,
        proof_by_path=proof_by_path,
        preexist_path_set=preexist_path_set,
        preexist_inode_set=preexist_inode_set,
    )




def session_created_allows(path: Path, *, manifest: Path | None = None) -> bool:
    """
    True when ``path`` is an exact HMAC-verified, contained, session-proven entry.

    Re-checks live floor containment, never-touch, and create-proof at delete
    time, not only at record time. Unproven allowlist entries do not skip
    ``_git_reason``.
    """
    allowed = load_session_created_paths(manifest)
    if not allowed:
        return False
    try:
        real_path = Path(os.path.realpath(path))
        real = str(real_path)
    except OSError:
        return False
    if Path(path).is_symlink():
        return False
    if real not in allowed:
        return False
    manifest_path = session_manifest_path(manifest)
    if manifest_path is None:
        return False
    floors = _floor_containment_roots(manifest_path)
    if _path_escape_or_symlink_reason(real_path, floors):
        return False
    if never_touch(real_path):
        return False
    # Proof must still match live inode/ctime (load already checked; re-check).
    try:
        st = real_path.stat()
    except OSError:
        return False
    data = _load_manifest_dict(manifest_path)
    if data is None:
        return False
    proofs_raw = data.get("proofs") if isinstance(data.get("proofs"), list) else []
    expected = None
    for item in proofs_raw:
        if isinstance(item, str) and item.startswith(real + "|"):
            expected = item
            break
    if expected is None or expected != _proof_token(real_path, st):
        return False
    return True


def restore_ce_managed_to_primary(
    paths: list,
    *,
    session: Path,
    primary: Path | None = None,
) -> tuple[str, list[str]]:
    """
    Restore CE-managed paths via ``git checkout <primary-sha> -- <paths>``.

    Only paths under ``session/.chaos-engine/``. Never deletes. Never touches
    other worktrees. Returns ``(refusal_or_empty, restored_relpaths)``.
    """
    session = Path(session).resolve()
    session_ce = session / ".chaos-engine"
    if not session_ce.is_dir():
        return f"no .chaos-engine under session `{session}`", []
    if primary is None:
        raw = os.environ.get("CHAOS_ENGINE_PRIMARY", "").strip()
        primary = Path(raw) if raw else None
    if primary is None:
        return "CHAOS_ENGINE_PRIMARY unset", []
    primary = Path(primary).resolve()
    if primary == session:
        return "primary and session are the same checkout; refuse cross-ambiguity", []
    sha = _git(primary, "rev-parse", "HEAD")
    if sha.returncode != 0 or not sha.stdout.strip():
        return f"cannot read primary SHA at `{primary}`", []
    primary_sha = sha.stdout.strip()
    rels: list[str] = []
    for item in paths:
        abs_path = Path(os.path.abspath(os.path.expanduser(str(item))))
        try:
            rel = abs_path.resolve().relative_to(session)
        except ValueError:
            return f"`{abs_path}` is outside session worktree `{session}`", []
        if not str(rel).replace("\\", "/").startswith(".chaos-engine/"):
            return f"`{abs_path}` is not under session .chaos-engine/", []
        # Refuse if the same relative path would be applied against another worktree root.
        if abs_path.resolve().parts[: len(session.parts)] != session.parts:
            return f"`{abs_path}` escapes session worktree", []
        hit = never_touch(abs_path)
        if hit:
            return f"`{abs_path}` is {hit}", []
        rels.append(rel.as_posix())
    if not rels:
        return "no CE-managed paths", []
    git = _git(session, "checkout", primary_sha, "--", *rels)
    if git.returncode != 0:
        detail = (git.stderr or git.stdout or "checkout failed").strip().splitlines()
        return f"git checkout failed: {detail[-1] if detail else 'unknown'}", []
    return "", rels


def ce_managed_revert_allows(path: Path, *, primary: Path | None = None) -> bool:
    """
    Deprecated delete allowlist — always False.

    CE-managed dirt must be restored via ``restore_ce_managed_to_primary``
    (git checkout), never deleted through delete-check.
    """
    return False


def path_reason(path: Path, project: Path | None = None, rev: str | None = None) -> str:
    """
    Empty string when deleting ``path`` loses nothing; else the refusal reason.

    Never-touch and protected checks run first so callers of ``path_reason``
    alone cannot bypass them via a forged session manifest.
    """
    hit = never_touch(path)
    if hit:
        return hit
    if allow_listed(path, project):
        return ""
    if session_created_allows(path):
        return ""
    if not path.exists() and not path.is_symlink():
        return ""
    if path.is_symlink():
        # Link-only deletes (plain rm/unlink/mv of the symlink inode). Tree ops
        # that follow links resolve via command_targets before path_reason runs.
        return ""
    probe = _existing(path)
    top = _git(probe, "rev-parse", "--show-toplevel")
    if top.returncode != 0:
        return "outside git and not on the delete allow-list"
    return _git_reason(path, Path(top.stdout.strip()).resolve(), rev)


def _ack_store() -> Path:
    from runtime.user_paths import legacy_state_dir, prefer_existing, state_dir

    return prefer_existing(state_dir(), legacy_state_dir()) / "delete-acks.json"


def _log(entry: dict) -> None:
    log = _ack_store().with_name("delete-overrides.jsonl")
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"at": int(time.time()), **entry}, sort_keys=True) + "\n")


def _never_rules() -> tuple[list[str], list[str]]:
    names, patterns = list(NEVER_NAMES), list(NEVER_PATTERNS)
    extra = NEVER_FILE.expanduser()
    if extra.is_file():
        for line in extra.read_text(encoding="utf-8").splitlines():
            item = line.strip()
            if item and not item.startswith("#"):
                (patterns if ("/" in item or "\\" in item) else names).append(os.path.expanduser(item))
    return names, patterns


def _yt_render(path: Path, part: str) -> bool:
    """An old ``*.rN.mp4`` render under yt/ but outside yt/meta/."""
    after = path.parts[path.parts.index(part) + 1 :]
    return bool(after) and "meta" not in after and YT_RENDER.fullmatch(path.name) is not None


def set_youtube_video_verifier(fn: Callable[[str], bool] | None) -> None:
    """Tests inject a verifier; production uses oEmbed (+ cache)."""
    global _youtube_video_verifier
    _youtube_video_verifier = fn


def _oembed_cache_path() -> Path:
    return _ack_store().with_name("yt-oembed-cache.json")


def _load_oembed_cache() -> dict:
    store = _oembed_cache_path()
    try:
        data = json.loads(store.read_text(encoding="utf-8")) if store.is_file() else {}
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}


def _save_oembed_cache(cache: dict) -> None:
    store = _oembed_cache_path()
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps(cache, sort_keys=True), encoding="utf-8")
    store.chmod(0o600)


def _expected_oembed_authors() -> frozenset[str] | None:
    """Optional channel bind: non-empty CHAOS_YT_EXPECTED_AUTHORS → require oEmbed author_name match."""
    raw = os.environ.get(YT_EXPECTED_AUTHORS_ENV, "")
    if not raw or not raw.strip():
        return None
    names = frozenset(part.strip() for part in raw.split(",") if part.strip())
    return names or None


def _oembed_author_ok(author: str) -> bool:
    expected = _expected_oembed_authors()
    if expected is None:
        return bool(author)
    return author in expected


def _parse_oembed_proof(body: bytes) -> tuple[bool, str]:
    """Positive proof: JSON with non-empty author_name (and optional expected-authors match)."""
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return False, ""
    if not isinstance(payload, dict):
        return False, ""
    author = payload.get("author_name")
    if not isinstance(author, str):
        return False, ""
    author = author.strip()
    if not author:
        return False, ""
    return _oembed_author_ok(author), author


def _oembed_cache_hit_result(entry: object, now: float) -> bool | None:
    """Return cached bool on a valid hit; None = miss. Never raises on poison/malformation.

    Positive hits re-validate stored author (non-empty str) against the current
    CHAOS_YT_EXPECTED_AUTHORS bind. Bare ok:true is never trusted alone.
    """
    if not isinstance(entry, dict):
        return None
    expires = entry.get("expires", 0)
    if not isinstance(expires, (int, float)):
        return None
    if expires < now:
        return None
    ok = entry.get("ok")
    if not isinstance(ok, bool):
        return None
    if ok is False:
        return False
    author = entry.get("author")
    if not isinstance(author, str):
        return None
    author = author.strip()
    if not author:
        return False
    return _oembed_author_ok(author)


def _default_youtube_video_exists(video_id: str) -> bool:
    """True only on oEmbed HTTP 200 + JSON author_name proof (optional expected-authors bind).

    HTTP 403/401 from oEmbed means private/unlisted-private (not a box IP block): stay locked.
    Network/5xx use a short negative cache so a brief outage does not lock for a day.
    Warm positive cache hits re-apply author proof and the current expected-authors bind;
    malformed cache entries are treated as misses and never raise into never_touch.
    """
    cache = _load_oembed_cache()
    entry = cache.get(video_id)
    now = time.time()
    hit = _oembed_cache_hit_result(entry, now)
    if hit is not None:
        return hit
    ok = False
    ttl = YT_OEMBED_TTL
    status: int | None = None
    author = ""
    try:
        request = urllib.request.Request(
            YT_OEMBED.format(id=video_id),
            headers={"User-Agent": YT_OEMBED_UA, "Accept": "application/json"},
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=10) as response:  # nosec B310 - fixed YouTube oEmbed URL.
            status = int(getattr(response, "status", 200) or 200)
            body = response.read()
        if status == 200:
            ok, author = _parse_oembed_proof(body)
        else:
            ok = False
            ttl = YT_OEMBED_SOFT_TTL if status >= 500 else YT_OEMBED_TTL
    except urllib.error.HTTPError as error:
        status = int(error.code)
        ok = False
        # 4xx (incl. 403 private) is definitive; 5xx is soft.
        ttl = YT_OEMBED_SOFT_TTL if status >= 500 else YT_OEMBED_TTL
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        ok = False
        ttl = YT_OEMBED_SOFT_TTL
    cache[video_id] = {
        "ok": ok,
        "expires": now + ttl,
        "checked": int(now),
        "status": status,
        "author": author[:80],
        "ttl": ttl,
    }
    _save_oembed_cache(cache)
    return ok


def youtube_video_exists(video_id: str) -> bool:
    if _youtube_video_verifier is not None:
        return bool(_youtube_video_verifier(video_id))
    return _default_youtube_video_exists(video_id)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _owner_only_file(path: Path) -> bool:
    try:
        info = os.stat(path)
    except OSError:
        return False
    if not stat.S_ISREG(info.st_mode):
        return False
    if info.st_uid != os.getuid():
        return False
    return (info.st_mode & 0o777) == 0o600


def _symlink_in_path(path: Path) -> bool:
    """True if any existing component of path is a symlink (lstat)."""
    abs_path = Path(os.path.abspath(os.path.expanduser(path)))
    abs_path = Path(os.path.normpath(abs_path))
    current = Path(abs_path.anchor) if abs_path.anchor else Path("/")
    parts = abs_path.parts[1:] if abs_path.is_absolute() else abs_path.parts
    for part in parts:
        current = current / part
        try:
            if stat.S_ISLNK(os.lstat(current).st_mode):
                return True
        except OSError:
            return False
    return False


def _normalized_abs(path: Path | str) -> Path:
    return Path(os.path.normpath(os.path.abspath(os.path.expanduser(str(path)))))


def _safe_listed_realpath(raw: str) -> str | None:
    """Normalize an allowlist path; reject '..', globs, dirs, escapes, and symlink components."""
    if glob.has_magic(raw) or raw.endswith(("/", os.sep)):
        return None
    expanded = Path(os.path.expanduser(raw))
    if ".." in expanded.parts:
        return None
    abs_path = _normalized_abs(expanded)
    if ".." in abs_path.parts or not abs_path.suffix:
        return None
    if _symlink_in_path(abs_path):
        return None
    if abs_path.exists() and (abs_path.is_dir() or abs_path.is_symlink()):
        return None
    real = Path(os.path.realpath(abs_path))
    if str(real) != str(abs_path):
        return None
    if "yt" not in real.parts:
        return None
    after = real.parts[real.parts.index("yt") + 1 :]
    if not after or "meta" in after:
        return None
    return str(real)


def _yt_verified_path() -> Path | None:
    """Env override (owner-only 0600) or default config when present and owner-only."""
    override = os.environ.get(YT_VERIFIED_ENV, "").strip()
    if override:
        candidate = Path(os.path.expanduser(override))
        if not _owner_only_file(candidate):
            _log({"yt_verified_source": "env-rejected", "path": str(candidate), "reason": "not-owner-only-0600"})
            return None
        _log({"yt_verified_source": "env", "path": str(candidate)})
        return candidate
    default = YT_VERIFIED_FILE.expanduser()
    if not default.is_file():
        return None
    if not _owner_only_file(default):
        _log({"yt_verified_source": "default-rejected", "path": str(default), "reason": "not-owner-only-0600"})
        return None
    _log({"yt_verified_source": "default", "path": str(default)})
    return default


def _load_yt_verified() -> dict[str, dict[str, str]]:
    """realpath -> {video_id, sha256}. Globs, dirs, escapes, and bad proofs are skipped."""
    config = _yt_verified_path()
    if config is None:
        return {}
    out: dict[str, dict[str, str]] = {}
    for line in config.read_text(encoding="utf-8").splitlines():
        item = line.strip()
        if not item or item.startswith("#"):
            continue
        parts = item.split()
        if len(parts) != 3:
            continue
        raw, video_id, digest = parts
        if not YT_VIDEO_ID.fullmatch(video_id) or not YT_SHA256.fullmatch(digest):
            continue
        real = _safe_listed_realpath(raw)
        if real is None:
            continue
        out[real] = {"video_id": video_id, "sha256": digest}
    return out


def _yt_containment_ok(real: Path) -> bool:
    if "yt" not in real.parts:
        return False
    after = real.parts[real.parts.index("yt") + 1 :]
    return bool(after) and "meta" not in after


def _yt_verified_uploaded(path: Path, part: str | None = None) -> bool:
    """#7525: allowlisted yt file with matching sha256 + oEmbed author proof; contained; re-checked live."""
    del part
    if ".." in Path(os.path.expanduser(str(path))).parts:
        return False
    if _symlink_in_path(path):
        return False
    abs_norm = _normalized_abs(path)
    if ".." in abs_norm.parts:
        return False
    try:
        real = Path(os.path.realpath(abs_norm))
    except OSError:
        return False
    if str(real) != str(abs_norm):
        return False
    if not _yt_containment_ok(real):
        return False
    if not real.is_file() or real.is_symlink():
        return False
    entries = _load_yt_verified()
    entry = entries.get(str(real))
    if entry is None:
        return False
    try:
        if _file_sha256(real) != entry["sha256"]:
            return False
    except OSError:
        return False
    return bool(youtube_video_exists(entry["video_id"]))


def never_touch(path: Path) -> str:
    """Non-empty when no code may unlock deleting ``path`` (itself, inside, or directly containing a protected dir)."""
    names, patterns = _never_rules()
    for part in path.parts:
        hit = next((name for name in names if fnmatchcase(part, name)), "")
        if hit == "yt" and (_yt_render(path, part) or _yt_verified_uploaded(path, part)):
            continue
        if hit:
            return f"never-touch `{hit}`"
    text = str(path).replace("\\", "/")
    hit = next((item for item in patterns if _pattern_regex(item.replace("\\", "/")).match(text)), "")
    if hit:
        return f"never-touch `{hit}`"
    if path.is_dir() and not path.is_symlink():
        for depth in ("", "*/"):
            for name in names:
                if any(path.glob(depth + name)):
                    return f"contains never-touch `{name}`"
        if any((path / ".config").glob("google-chrome*")) or (path / ".config" / "chromium").exists():
            return "contains a browser profile"
    return ""


def _paths_digest(paths: list[Path]) -> str:
    return hashlib.sha256("\n".join(sorted({str(path) for path in paths})).encode("utf-8")).hexdigest()


def _code_digest(code: str) -> str:
    return hashlib.sha256(code.strip().upper().encode("utf-8")).hexdigest()


def _iso_utc(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def _load_all_codes() -> dict[str, dict[str, object]]:
    store = _ack_store()
    try:
        codes = json.loads(store.read_text(encoding="utf-8")) if store.is_file() else {}
    except ValueError:
        codes = {}
    if not isinstance(codes, dict):
        return {}
    cutoff = time.time() - 86400
    return {
        key: value
        for key, value in codes.items()
        if isinstance(value, dict)
        and isinstance(value.get("expires", 0), (int, float))
        and float(value.get("expires", 0)) >= cutoff
        and "paths" in value
    }


def _load_codes() -> dict:
    now = time.time()
    return {
        key: value
        for key, value in _load_all_codes().items()
        if not value.get("used") and float(value.get("expires", 0)) >= now
    }


def _save_codes(codes: dict) -> None:
    store = _ack_store()
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps(codes, sort_keys=True), encoding="utf-8")
    store.chmod(0o600)


def request_code(paths: list[Path], ttl: float = CODE_TTL) -> str:
    """Mint a one-time code for exactly ``paths``; the bot shows it to the owner in chat."""
    if not paths:
        raise PermissionError("no paths")
    for path in paths:
        hit = never_touch(path)
        if hit:
            raise PermissionError(f"`{path}` is {hit}; no code unlocks it")
    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))
    codes = _load_all_codes()
    codes[_code_digest(code)] = {
        "paths": _paths_digest(paths),
        "count": len(set(paths)),
        "expires": time.time() + ttl,
        "used": False,
    }
    _save_codes(codes)
    _log({"issued": True, "paths": _paths_digest(paths)[:12], "count": len(set(paths))})
    return code


def verify_code(code: str, paths: list[Path], *, consume: bool = True) -> str:
    """'' when ``code`` matches ``paths`` (and is spent when ``consume=True``); else why it was rejected."""
    if not code:
        return "no code"
    codes = _load_all_codes()
    digest = _code_digest(code)
    entry = codes.get(digest)
    if entry is None:
        return "code unknown"
    if entry.get("used"):
        return "code already used"
    expires = float(entry.get("expires", 0))
    if expires < time.time():
        return f"code expired at {_iso_utc(expires)}"
    if entry.get("paths") != _paths_digest(paths):
        return "code was issued for a different path list"
    if consume:
        entry["used"] = True
        _save_codes(codes)
        _log({"used": True, "codeDigest": digest, "paths": [str(path) for path in paths]})
    return ""


def consume_code(code: str, paths: list[Path]) -> str:
    """'' when ``code`` matches ``paths`` (then it is spent); else why it was rejected."""
    return verify_code(code, paths, consume=True)


def _checkout_rev(command: str) -> str | None:
    """Rev named by ``git switch`` or ``git checkout``.

    ``switch -c <name> <start>`` and ``checkout -b <name> <start>`` keep the
    start point. A new branch name does not hold the bytes being recreated.
    """
    match = re.search(
        r"\bgit\s+(?:switch|checkout)\s+(?:-\S+\s+)*(\S+)(?:\s+(\S+))?",
        command or "",
    )
    if match is None:
        return None
    first, second = match.group(1), match.group(2)
    if first.startswith("-"):
        return None
    if second and not second.startswith("-"):
        return second
    return first


def _only_delete_segments(command: str, cwd: Path) -> bool:
    """True when every shell segment in ``command`` is a cd/pushd or a recognized delete segment."""
    if UNSURE.search(command):
        return False
    try:
        events = _parse_shell(command)
    except ValueError:
        return False
    if not events:
        return False
    has_delete = False
    for kind, payload in events:
        if kind == "sep":
            continue
        if kind != "cmd" or not isinstance(payload, _SimpleCommand):
            return False
        if payload.cmd_subs or not payload.words:
            return False
        arguments = payload.words
        head, rest = _head(arguments)
        if head in {"cd", "pushd"}:
            target = _cd_target(rest)
            if target == "-" or UNSURE.search(target):
                return False
            cwd = (cwd / os.path.expanduser(target)).resolve()
            continue
        if head in SHELLS:
            script = _shell_c_script(rest)
            if script is None or payload.heredocs or payload.here_strings:
                return False
            if not _only_delete_segments(script, cwd):
                return False
            has_delete = True
            continue
        if _is_python(head):
            # Owner-code runs the string with shell=True; another call is not a pure delete.
            sources: list[str] = []
            c_code = _python_code_from_args(rest)
            if c_code is not None:
                sources.append(c_code)
            sources.extend(hd.body for hd in payload.heredocs)
            sources.extend(payload.here_strings)
            if not sources:
                return False
            for src in sources:
                if re.search(r"\bos\.system\b|\bsubprocess\b|\bos\.popen\b|\beval\s*\(|\bexec\s*\(", src):
                    return False
                try:
                    if not _python_entries(src):
                        return False
                except Unsure:
                    return False
            has_delete = True
            continue
        # find -exec/-ok runs an extra command even when -delete is also present.
        if head == "find" and any(item in {"-exec", "-execdir", "-ok", "-okdir"} for item in arguments):
            return False
        try:
            targets = _segment_targets(arguments, cwd)
        except Unsure:
            return False
        if not targets:
            return False
        has_delete = True
    return has_delete


def _delete_check_cli_args(command: str) -> list[str] | None:
    """Return CLI arguments when ``command`` is a single tool.py delete-check / delete_guard.py invocation."""
    if "\n" in command.strip() or UNSURE.search(command):
        return None
    try:
        segments = _segments(command)
    except ValueError:
        return None
    if len(segments) != 1:
        return None
    head, rest = _head(segments[0])
    if head.startswith("python"):
        idx = 0
        while idx < len(rest) and rest[idx].startswith("-"):
            idx += 1
        if idx >= len(rest):
            return None
        script = os.path.basename(rest[idx])
        tail = rest[idx + 1 :]
    else:
        script = head
        tail = rest
    if script == "tool.py" and tail[:1] == ["delete-check"]:
        return tail[1:]
    if script == "delete_guard.py":
        return tail
    return None


def check(
    command: str | list[Path],
    cwd: Path | None = None,
    project: Path | None = None,
    code: str | None = None,
    *,
    consume: bool = True,
) -> tuple[str, list[str]]:
    """(refusal or '', warnings). A matching owner code turns git/allow-list refusals into warnings."""
    if isinstance(command, (list, tuple)):
        if not command:
            return ("Delete guard (#7251): refused: no delete targets.", []) if code is not None else ("", [])
        command = _rm([str(item) for item in command])
    # Parse before the visible-delete regex. Quote-split and ANSI-C command
    # names (r'm', $'r\x6d') never contain the raw word. The regex still fails
    # closed inside command_targets when an unparsable command shows a delete word.
    try:
        targets = command_targets(command, cwd)
    except Unsure as error:
        return f"Delete guard (#7251): refused, cannot tell what this deletes ({error}). Name literal paths and run `tool.py delete-check <paths>`.", []
    if code is not None and not targets:
        return "Delete guard (#7251): refused: no delete targets.", []
    for target in targets:
        hit = never_touch(target)
        if hit:
            return f"Delete guard (#7343): refused `{target}`: {hit}. No code unlocks it.", []
    rev = _checkout_rev(command)
    reasons = [(target, reason) for target in targets for reason in [path_reason(target, project, rev)] if reason]
    if not reasons:
        if code is None:
            return "", []
        rejected = verify_code(code, targets, consume=consume)
        if not rejected:
            return "", [f"`{target}`: (owner code accepted)" for target in targets]
        target = targets[0]
        return (
            f"Delete guard (#7251): refused `{target}`: owner code rejected: {rejected}. "
            f"Run `tool.py delete-check --request-code <same paths>` and ask the owner to paste the code back in chat."
        ), []
    effective_code = code if code is not None else os.environ.get(ACK_ENV, "")
    rejected = verify_code(effective_code, targets, consume=consume) if effective_code else "no code"
    if not rejected:
        return "", [f"`{target}`: {reason} (owner code accepted)" for target, reason in reasons]
    target, reason = reasons[0]
    hint = f"owner code rejected: {rejected}. " if effective_code else ""
    return (
        f"Delete guard (#7251): refused `{target}`: {reason}. {hint}Commit and push it, back it up, "
        f"add a scratch pattern to {STATE_DIR}/{ALLOW_FILE}, or run `tool.py delete-check --request-code <same paths>` "
        f"and ask the owner to paste the code back in chat."
    ), []


TOOL_REPAIR_COMMAND = "python3 .chaos-engine/install.py repair --project ."


def _overlay_dir(start: Path) -> Path | None:
    """The installed overlay at ``start`` or the nearest parent that has one."""
    current = start.resolve()
    for candidate in (current, *current.parents):
        overlay = candidate / ".chaos-engine"
        if overlay.is_dir():
            return overlay
    return None


def denial_with_tool_repair(reason: str, project: Path | None) -> str:
    """Point a tool.py denial at repair when that installed file is already gone (#7964)."""
    if not reason or "tool.py" not in reason or TOOL_REPAIR_COMMAND in reason:
        return reason
    overlay = _overlay_dir(Path(project) if project is not None else Path.cwd())
    if overlay is None or (overlay / "tool.py").is_file():
        return reason
    return f"{reason} .chaos-engine/tool.py is missing. Run `{TOOL_REPAIR_COMMAND}`."


def block_reason(command: str, cwd: Path | None = None, project: Path | None = None) -> str:
    """Hook entry point: '' to allow, else a refusal message."""
    cli_args = _delete_check_cli_args(command)
    if cli_args is not None:
        if "--code" not in cli_args:
            return ""
        if cli_args[:1] == ["--code"] and len(cli_args) >= 2:
            code, rest = cli_args[1], cli_args[2:]
            if rest[:1] == ["--command"] and len(rest) == 2:
                inner_cmd = rest[1]
                base_cwd = (cwd or Path.cwd()).resolve()
                if not _only_delete_segments(inner_cmd, base_cwd):
                    return denial_with_tool_repair(
                        "Delete guard (#7251): refused: --command with --code must contain only delete commands.",
                        project or cwd,
                    )
                reason, _ = check(inner_cmd, cwd=cwd, project=project, code=code, consume=False)
                return denial_with_tool_repair(reason, project or cwd) if reason else ""
            if rest and not rest[0].startswith("--"):
                reason, _ = check([Path(p) for p in rest], cwd=cwd, project=project, code=code, consume=False)
                return denial_with_tool_repair(reason, project or cwd) if reason else ""
        return denial_with_tool_repair(
            "Delete guard (#7251): refused: invalid tool.py delete-check --code invocation.",
            project or cwd,
        )
    return denial_with_tool_repair(check(command, cwd, project)[0], project or cwd)


def doctor_check(root: Path) -> tuple[str, str]:
    """`delete-guard` row: the hook calls this module and tool.py exposes delete-check."""
    hook = root / "hooks" / "guard.py"
    tool = root / "tool.py"
    if not hook.is_file() or "delete_guard" not in hook.read_text(encoding="utf-8"):
        return "fail", "hook not wired"
    if not tool.is_file():
        label = ".chaos-engine/tool.py" if root.name == ".chaos-engine" else "tool.py"
        return "fail", f"{label} missing"
    if "delete-check" not in tool.read_text(encoding="utf-8"):
        return "fail", "tool.py delete-check missing"
    return "pass", ""


def _workspaces(project: Path) -> list[Path]:
    listed = project / STATE_DIR / "backup-workspaces.txt"
    extra = os.environ.get("CHAOS_BACKUP_WORKSPACES", "")
    paths = [project]
    if listed.is_file():
        paths += [Path(line.strip()).expanduser() for line in listed.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")]
    paths += [Path(item).expanduser() for item in extra.split(os.pathsep) if item]
    return [path for path in dict.fromkeys(paths) if path.is_dir()]


CONSUMER_MARKER = ".chaos-engine-state/consumer-mode"


def _is_chaos_engine_rel(rel: str) -> bool:
    """True for harness paths that should not trigger backup-remote alone."""
    normalized = rel.replace("\\", "/")
    prefixes = (
        ".chaos-engine",
        ".chaos-engine-state",
        ".memory",
        ".mempalace",
        "graphify-out",
        ".graphifyignore",
        "mempalace.yaml",
    )
    for prefix in prefixes:
        if normalized == prefix or normalized.startswith(prefix + "/"):
            return True
    return False


def _only_chaos_engine_dirt(porcelain: str) -> bool:
    """True when every porcelain path is harness/CE state (uncommitted CE tree)."""
    lines = [line for line in porcelain.splitlines() if line.strip()]
    if not lines:
        return False
    for line in lines:
        rel = line[3:] if len(line) > 3 else line
        rel = rel.strip().strip('"')
        if " -> " in rel:
            rel = rel.split(" -> ", 1)[-1]
        if not _is_chaos_engine_rel(rel):
            return False
    return True


def _is_linked_worktree(path: Path) -> bool:
    result = _git(path, "rev-parse", "--path-format=absolute", "--git-dir", "--git-common-dir")
    if result.returncode != 0:
        return False
    lines = result.stdout.strip().splitlines()
    if len(lines) != 2:
        return False
    return Path(lines[0]).resolve() != Path(lines[1]).resolve()


def backup_remote_issue(path: Path) -> str:
    if _git(path, "rev-parse", "--show-toplevel").returncode != 0:
        return "not in git"
    # Consumer mode (#6237) and CE-only dirt are silent: the harness hides its
    # own state on purpose. Warn only for real unpushed work or non-CE dirt.
    consumer = (path / CONSUMER_MARKER).is_file()
    if not _git(path, "remote").stdout.strip():
        return "no remote"
    if _git(path, "rev-parse", "--abbrev-ref", "@{u}").returncode != 0:
        return "no upstream"
    if _git(path, "rev-list", "--count", "@{u}..HEAD").stdout.strip() not in {"", "0"}:
        return "unpushed commits"
    porcelain = _git(path, "status", "--porcelain", "--untracked-files=normal").stdout.strip()
    if porcelain:
        if _only_chaos_engine_dirt(porcelain):
            return ""
        if consumer:
            # Consumer exclude hides .chaos-engine / .memory; non-CE dirt still warns.
            return "uncommitted files"
        return "uncommitted files"
    return ""


def backup_remote_status(project: Path) -> tuple[str, str]:
    """Advisory only: never fails doctor."""
    issues = []
    for path in _workspaces(project):
        issue = backup_remote_issue(path)
        if issue:
            issues.append(f"{path.name}: {issue}")
    if not issues:
        return "pass", ""
    return "warn", "; ".join(issues[:3]) + (f" (+{len(issues) - 3})" if len(issues) > 3 else "") + "; push or back up"


def _rm(paths: list[str]) -> str:
    return "rm -rf -- " + " ".join(shlex.quote(item) for item in paths)


def main(arguments: list[str] | None = None) -> int:
    if arguments is None:
        arguments = sys.argv[1:]
    code = None
    if arguments[:1] == ["--restore-ce"] and len(arguments) >= 2:
        session = Path(os.environ.get(SESSION_WORKTREE_ENV) or Path.cwd()).resolve()
        reason, restored = restore_ce_managed_to_primary(arguments[1:], session=session)
        if reason:
            print(f"ce-restore: refused: {reason}", file=sys.stderr)
            return 1
        print("ce-restore: restored " + ", ".join(restored))
        return 0
    if arguments[:1] == ["--code"] and len(arguments) >= 2:
        code, arguments = arguments[1], arguments[2:]
    if arguments[:1] == ["--request-code"] and len(arguments) >= 2 and code is None:
        try:
            paths = list(dict.fromkeys(command_targets(_rm(arguments[1:]), Path.cwd())))
            code = request_code(paths)
        except (PermissionError, Unsure) as error:
            print(f"delete-code: refused: {error}", file=sys.stderr)
            return 2
        expires_iso = _iso_utc(float(_load_all_codes()[_code_digest(code)]["expires"]))
        print(
            f"delete-code: {code} (one use, {CODE_TTL // 60} min, expires {expires_iso}, {len(paths)} path(s)). "
            "Show it to the owner; after they paste it back run: "
            "tool.py delete-check --code <code> --command 'rm -rf -- <same paths>'"
        )
        return 0
    is_command_mode = arguments[:1] == ["--command"] and len(arguments) == 2
    if is_command_mode:
        cmd = arguments[1]
        if code is not None and not _only_delete_segments(cmd, Path.cwd()):
            print(
                "Delete guard (#7251): refused: --command with --code must contain only delete commands.",
                file=sys.stderr,
            )
            return 1
        reason, warnings = check(cmd, Path.cwd(), Path.cwd(), code)
    elif arguments and not arguments[0].startswith("--"):
        reason, warnings = check(_rm(arguments), Path.cwd(), Path.cwd(), code)
    else:
        print("usage: tool.py delete-check [--code CODE] <paths...> | [--code CODE] --command '<cmd>' | --request-code <paths...> | --restore-ce <CE-paths...>", file=sys.stderr)
        return 2
    if reason:
        print(reason, file=sys.stderr)
        print("code required: yes", file=sys.stderr)
        literal = " ".join(arguments)
        print(f"next: tool.py delete-check --request-code {literal}", file=sys.stderr)
        return 1
    for warning in warnings:
        print(f"delete-check: warning: {warning}", file=sys.stderr)
    if code is not None and is_command_mode:
        completed = subprocess.run(cmd, shell=True, cwd=Path.cwd(), check=False)  # nosec B602
        if completed.returncode != 0:
            return completed.returncode
    print("delete-check: allowed")
    print("code required: no")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
