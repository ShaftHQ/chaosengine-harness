#!/usr/bin/env python3
"""
Git pre-commit and pre-push guard against generated reports and secrets (#7177).

It checks every blob that a commit stages. A push checks the tip of the
cumulative diff, not an intermediate blob the tip has already removed:

- paths of local secret files (secrets.properties, browserstack.yml) and of the
  generated reports the project names in ``.secret-guard-paths``,
- literal values from the local secret files, raw and inside the base64 blobs of an
  single-file HTML report,
- JWT-like tokens,
- secret assignments such as ``accessKey = <value>``.

It never prints a value, and it refuses a direct push to main or master.
A false positive is fixed here or in ``.secret-guard-allow``, never with ``--no-verify``.

Usage::

    python3 secret_guard.py --staged                 # pre-commit
    python3 secret_guard.py --push < <pushed refs>    # pre-push (git passes the refs on stdin)
    python3 secret_guard.py --rev @{upstream}..HEAD   # audit a branch
    python3 secret_guard.py --exec-with-secret KEY=ENV_VAR -- <command...>  # inject secret without echo

``SECRET_GUARD_FILES`` lists the local secret files (comma separated, relative to the
repository root). The default is
``src/main/resources/properties/secrets.properties,browserstack.yml``.
``.secret-guard-allow`` at the repository root holds path globs, one per line, whose
files skip the token and assignment checks. Report paths and known values are always checked.
``.secret-guard-paths`` at the repository root, and ``SECRET_GUARD_PATHS`` (separated by
``|`` like any regex alternation), add path regexes that are blocked like report paths,
for the report names a project's own tools generate. The core knows no report tool.
"""
from __future__ import annotations

import base64
import binascii
import fnmatch
import json
import os
import re
import shutil
import subprocess  # nosec B404 - runs git or explicit wrapper command with no shell
import sys
import urllib.parse
from pathlib import Path
from typing import Iterable, Iterator, Sequence

DEFAULT_GUARDED_FILES = "src/main/resources/properties/secrets.properties,src/main/resources/secrets.properties,browserstack.yml"  # nosec B105 - file paths, not a secret
ALLOW_FILE = ".secret-guard-allow"
PATHS_FILE = ".secret-guard-paths"
PROTECTED_REFS = ("refs/heads/main", "refs/heads/master")
BLOCKED_PATH = re.compile(
    r"(?i)((^|/)secrets\.properties$|(^|/)browserstack\.yml$)"
)
TOKEN = re.compile(rb"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}")
ASSIGNMENT = re.compile(
    rb"(?i)(client_?secret|access_?key|password|api_?key|session_?id)[\"']?\s*[:=]\s*[\"']?"
    rb"([A-Za-z0-9._~+/=-]{16,})(?!\s*\()"
)
REPORT_BLOB = re.compile(rb'd\("[^"]+","([A-Za-z0-9+/=]{16,})"\)')
SECRET_LINE = re.compile(r"\s*[^#=:\s]+\s*[=:]\s*(\S{12,})")
MINIMUM_VALUE_LENGTH = 12
ZERO_SHA = re.compile(r"^0+$")


def _git_executable() -> str:
    found = shutil.which("git")
    if not found:
        raise RuntimeError("secret_guard: git is not on PATH")
    return found


def git(*args: str, data: bytes | None = None) -> bytes:
    """Run git and return its standard output."""
    return subprocess.run(  # nosec B603 - fixed git argv, no shell
        [_git_executable(), *args], input=data, capture_output=True, check=True
    ).stdout


def _contained_secret_file(root: Path, name: str) -> Path | None:
    """Return a guarded path inside ``root``, or None if it is absolute or escapes via ``..``."""
    cleaned = (name or "").strip()
    if not cleaned:
        return None
    relative = Path(cleaned)
    if relative.is_absolute():
        return None
    base = Path(root).resolve()
    try:
        resolved = (base / relative).resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    if resolved != base and base not in resolved.parents:
        return None
    return resolved


def secret_values(root: Path, names: Iterable[str]) -> set[bytes]:
    """Read the literal secret values from the local secret files that exist."""
    values: set[bytes] = set()
    for name in names:
        path = _contained_secret_file(root, name)
        if path is None or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if path.suffix == ".json":
            _json_values(json.loads(text or "null"), values)
            continue
        for line in text.splitlines():
            match = SECRET_LINE.match(line)
            if match:
                value = match.group(1).strip("\"'")
                if len(value) >= MINIMUM_VALUE_LENGTH:
                    values.add(value.encode())
    return values


def _json_values(node: object, values: set[bytes]) -> None:
    if isinstance(node, dict):
        for child in node.values():
            _json_values(child, values)
    elif isinstance(node, list):
        for child in node:
            _json_values(child, values)
    elif isinstance(node, str) and len(node) >= MINIMUM_VALUE_LENGTH:
        values.add(node.encode())


def allowed_globs(root: Path) -> list[str]:
    """Path globs whose files skip the token and assignment heuristics."""
    path = root / ALLOW_FILE
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]


def blocked_paths(root: Path) -> re.Pattern[str]:
    """The core report and secret-file paths plus the project's own path regexes."""
    extra = [os.environ.get("SECRET_GUARD_PATHS", "").strip()]
    path = root / PATHS_FILE
    if path.is_file():
        lines = path.read_text(encoding="utf-8").splitlines()
        extra += [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]
    extra = [pattern for pattern in extra if pattern]
    if not extra:
        return BLOCKED_PATH
    core = BLOCKED_PATH.pattern.removeprefix("(?i)")
    return re.compile("|".join([core, *(f"(?:{pattern})" for pattern in extra)]), re.IGNORECASE)


def _decoded_blobs(data: bytes) -> list[bytes]:
    blobs = [data]
    for encoded in REPORT_BLOB.findall(data):
        try:
            blobs.append(base64.b64decode(encoded + b"=" * (-len(encoded) % 4)))
        except (binascii.Error, ValueError):
            continue
    return blobs


def findings(
    path: str, data: bytes, values: set[bytes], allow: list[str], blocked: re.Pattern[str] = BLOCKED_PATH
) -> list[str]:
    """Name what is wrong with one blob, without its content."""
    found = ["generated report or secret file"] if blocked.search(path) else []
    blobs = _decoded_blobs(data)
    if any(value in blob for blob in blobs for value in values):
        found.append("known secret value")
    if any(fnmatch.fnmatch(path, pattern) for pattern in allow):
        return found
    if any(TOKEN.search(blob) for blob in blobs):
        found.append("JWT-like token")
    if any(
        re.search(rb"\d", match.group(2)) and re.search(rb"[A-Za-z]", match.group(2))
        for match in ASSIGNMENT.finditer(data)
    ):
        found.append("secret assignment")
    return found


def staged() -> Iterator[tuple[str, bytes]]:
    """Blobs added or changed in the index."""
    names = git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z").split(b"\0")
    for name in filter(None, names):
        path = name.decode()
        yield path, git("show", ":" + path)


def pushed_revisions(refs: str) -> list[str]:
    """Turn pre-push stdin into rev-list arguments; refuse a direct push to main."""
    args: list[str] = []
    for line in refs.splitlines():
        parts = line.split()
        if len(parts) != 4:
            continue
        _, local_sha, remote_ref, remote_sha = parts
        if ZERO_SHA.match(local_sha):
            continue
        if remote_ref in PROTECTED_REFS:
            raise PermissionError("secret_guard: no direct push to " + remote_ref)
        args.append(local_sha)
        if not ZERO_SHA.match(remote_sha):
            args.append("^" + remote_sha)
    # Blobs already on any remote are public; only new local commits need a scan (#7203).
    return [*args, "--not", "--remotes"] if args else args


def _known(sha: str) -> bool:
    """True when the object exists locally."""
    try:
        git("cat-file", "-e", sha + "^{commit}")
    except subprocess.CalledProcessError:
        return False
    return True


def _push_pairs(refs: str) -> list[tuple[str, str]]:
    """Local and remote SHAs for a pre-push stdin. Deletes are skipped."""
    pairs: list[tuple[str, str]] = []
    for line in refs.splitlines():
        parts = line.split()
        if len(parts) != 4:
            continue
        _local_ref, local_sha, remote_ref, remote_sha = parts
        if ZERO_SHA.match(local_sha):
            continue
        if remote_ref in PROTECTED_REFS:
            raise PermissionError("secret_guard: no direct push to " + remote_ref)
        pairs.append((local_sha, remote_sha))
    return pairs


def _remote_blob_shas() -> set[str]:
    """Blob SHAs already published on any remote. An empty set means scan the tip."""
    try:
        text = git("rev-list", "--objects", "--remotes").decode()
    except subprocess.CalledProcessError:
        return set()
    shas: set[str] = set()
    for line in text.splitlines():
        sha, _, path = line.partition(" ")
        if path:
            shas.add(sha)
    return shas


def _range_blobs(local_sha: str, remote_sha: str) -> list[tuple[str, str]]:
    """Path and full blob SHA for every blob the push range will publish."""
    if not ZERO_SHA.match(remote_sha) and _known(remote_sha):
        args = [f"{remote_sha}..{local_sha}"]
    else:
        args = [local_sha, "--not", "--remotes"]
    listed: list[tuple[str, str]] = []
    for line in git("rev-list", "--objects", *args).decode().splitlines():
        sha, _, path = line.partition(" ")
        if path:
            listed.append((path, sha))
    if not listed:
        return []
    kinds = git(
        "cat-file",
        "--batch-check=%(objectname) %(objecttype)",
        data="".join(sha + "\n" for _, sha in listed).encode(),
    ).decode().split()
    blobs = {kinds[index] for index in range(0, len(kinds) - 1, 2) if kinds[index + 1] == "blob"}
    return [(path, sha) for path, sha in listed if sha in blobs]


def push_contents(refs: str) -> Iterator[tuple[str, bytes]]:
    """Blobs this push newly publishes. Blobs already on a remote are skipped.

    A secret commit that is not on any remote is part of the push, so it blocks
    even when a later commit removes the secret from the tip. A blob already
    reachable from a remote is not a new publication.
    """
    pairs = _push_pairs(refs)
    if not pairs:
        return
    already = _remote_blob_shas()
    seen: set[str] = set()
    for local_sha, remote_sha in pairs:
        for path, sha in _range_blobs(local_sha, remote_sha):
            if sha in already or sha in seen:
                continue
            seen.add(sha)
            yield path, git("cat-file", "blob", sha)


def revisions(args: list[str]) -> Iterator[tuple[str, bytes]]:
    """Blobs reachable from the given rev-list arguments, each once."""
    if not args:
        return
    # A force-push target whose old tip was never fetched is an unknown revision;
    # drop that exclusion (still bounded by --not --remotes) instead of crashing (#7298).
    args = [arg for arg in args if not arg.startswith("^") or _known(arg[1:])]
    objects = []
    for line in git("rev-list", "--objects", *args).decode().splitlines():
        sha, _, path = line.partition(" ")
        if path:
            objects.append((sha, path))
    if not objects:
        return
    kinds = git("cat-file", "--batch-check=%(objectname) %(objecttype)",
                data="".join(sha + "\n" for sha, _ in objects).encode()).decode().split()
    blob_shas = {kinds[index] for index in range(0, len(kinds) - 1, 2) if kinds[index + 1] == "blob"}
    seen: set[str] = set()
    for sha, path in objects:
        if sha in blob_shas and sha not in seen:
            seen.add(sha)
            yield path, git("cat-file", "blob", sha)


YAML_MAPPING = re.compile(r"^(\s*)([^#:\n]+?)\s*:(?:\s+(.*)|\s*)$")
ENV_VAR_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
REDACTED_BYTES = b"[REDACTED]"


def _guarded_file_names(files: Iterable[str] | None = None) -> list[str]:
    source = (
        os.environ.get("SECRET_GUARD_FILES", DEFAULT_GUARDED_FILES).split(",")
        if files is None
        else files
    )
    return [name.strip() for name in source if name and name.strip()]


def _strip_scalar_value(raw: str, *, allow_inline_comment: bool) -> str:
    """Extract a scalar string value without printing or expanding it."""
    text = raw.strip()
    if not text:
        return ""
    if text[0] in {"'", '"'}:
        quote = text[0]
        chars: list[str] = []
        index = 1
        while index < len(text):
            ch = text[index]
            if quote == '"' and ch == "\\" and index + 1 < len(text):
                chars.append(text[index + 1])
                index += 2
                continue
            if ch == quote:
                return "".join(chars)
            chars.append(ch)
            index += 1
        return text.strip(quote)
    if allow_inline_comment:
        for index, ch in enumerate(text):
            if ch == "#" and index > 0 and text[index - 1] in " \t":
                return text[:index].rstrip()
    return text


def _json_scalar(node: object) -> str | None:
    if isinstance(node, str):
        return node if node else None
    if isinstance(node, (int, float)) and not isinstance(node, bool):
        return str(node)
    return None


def _json_find_key(node: object, key: str) -> str | None:
    if isinstance(node, dict):
        if key in node:
            found = _json_scalar(node[key])
            if found is not None:
                return found
        for child in node.values():
            found = _json_find_key(child, key)
            if found is not None:
                return found
    elif isinstance(node, list):
        for child in node:
            found = _json_find_key(child, key)
            if found is not None:
                return found
    return None


def _read_json_key(text: str, key: str) -> str | None:
    try:
        data = json.loads(text or "null")
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict):
        if key in data:
            found = _json_scalar(data[key])
            if found is not None:
                return found
        if "." in key:
            current: object = data
            for segment in key.split("."):
                if isinstance(current, dict) and segment in current:
                    current = current[segment]
                else:
                    current = None
                    break
            found = _json_scalar(current)
            if found is not None:
                return found
    return _json_find_key(data, key)


def _read_yaml_key(text: str, key: str) -> str | None:
    stack: list[tuple[int, str]] = []
    leaf_match: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if stripped.startswith("-"):
            while stack and stack[-1][0] >= indent:
                stack.pop()
            continue
        match = YAML_MAPPING.match(line)
        if not match:
            continue
        name = match.group(2).strip().strip("\"'")
        raw_val = (match.group(3) or "").strip()
        while stack and stack[-1][0] >= indent:
            stack.pop()
        if not raw_val or raw_val.startswith("#"):
            stack.append((indent, name))
            continue
        value = _strip_scalar_value(raw_val, allow_inline_comment=True)
        if not value:
            continue
        dotted = ".".join([*(part for _, part in stack), name])
        if dotted == key:
            return value
        if leaf_match is None and "." not in key and name == key:
            leaf_match = value
    return leaf_match


def _read_kv_key(text: str, key: str, *, env_style: bool) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or (not env_style and stripped.startswith("!")):
            continue
        if env_style and stripped.startswith("export "):
            stripped = stripped[len("export "):].lstrip()
        if env_style:
            if "=" not in stripped:
                continue
            name, raw_val = stripped.split("=", 1)
        else:
            eq_idx = stripped.find("=")
            colon_idx = stripped.find(":")
            positions = [idx for idx in (eq_idx, colon_idx) if idx >= 0]
            if not positions:
                continue
            split_at = min(positions)
            name, raw_val = stripped[:split_at], stripped[split_at + 1 :]
        if name.strip() == key:
            value = _strip_scalar_value(raw_val, allow_inline_comment=env_style)
            return value if value else None
    return None


def read_secret_key(
    root: Path, key: str, *, files: Iterable[str] | None = None
) -> str | None:
    """Read a secret-like key from local guarded files without printing it."""
    target = (key or "").strip()
    if not target:
        return None
    base = Path(root)
    for name in _guarded_file_names(files):
        path = _contained_secret_file(base, name)
        if path is None or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        suffix = path.suffix.lower()
        if suffix == ".json":
            value = _read_json_key(text, target)
        elif suffix in {".yml", ".yaml"}:
            value = _read_yaml_key(text, target)
        elif suffix == ".env" or path.name == ".env" or path.name.startswith(".env."):
            value = _read_kv_key(text, target, env_style=True)
        else:
            value = _read_kv_key(text, target, env_style=False)
        if value is not None:
            return value
    return None


def _secret_byte_forms(secret: bytes) -> list[bytes]:
    """Raw secret plus base64 and URL-encoded forms that must not leak on output."""
    if not secret:
        return []
    forms: list[bytes] = [secret]
    standard = base64.b64encode(secret)
    urlsafe = base64.urlsafe_b64encode(secret)
    for item in (standard, urlsafe, standard.rstrip(b"="), urlsafe.rstrip(b"=")):
        if item and item not in forms:
            forms.append(item)
    try:
        text = secret.decode("utf-8")
    except UnicodeDecodeError:
        return forms
    for encoded in (
        urllib.parse.quote(text, safe=""),
        urllib.parse.quote_plus(text, safe=""),
        urllib.parse.quote(text),
        urllib.parse.quote_plus(text),
    ):
        raw = encoded.encode("ascii", errors="ignore")
        if raw and raw not in forms:
            forms.append(raw)
        if "%" in encoded:
            lowered = encoded.lower().encode("ascii", errors="ignore")
            if lowered and lowered not in forms:
                forms.append(lowered)
    return forms


def _percent_hex_class(byte: int) -> bytes:
    char = chr(byte)
    if char.isalpha():
        return b"[" + char.upper().encode("ascii") + char.lower().encode("ascii") + b"]"
    return re.escape(bytes((byte,)))


def _percent_casefold_pattern(encoded: bytes) -> re.Pattern[bytes] | None:
    """Match ``encoded`` with any hex-digit case in ``%HH`` escapes."""
    if not re.search(rb"%[0-9A-Fa-f]{2}", encoded):
        return None
    parts: list[bytes] = []
    index = 0
    length = len(encoded)
    while index < length:
        if (
            encoded[index] == 0x25
            and index + 3 <= length
            and chr(encoded[index + 1]) in "0123456789ABCDEFabcdef"
            and chr(encoded[index + 2]) in "0123456789ABCDEFabcdef"
        ):
            parts.append(b"%" + _percent_hex_class(encoded[index + 1]) + _percent_hex_class(encoded[index + 2]))
            index += 3
            continue
        parts.append(re.escape(encoded[index : index + 1]))
        index += 1
    return re.compile(b"".join(parts))


def _scrub_bytes(data: bytes, secrets: Sequence[bytes]) -> bytes:
    if not data or not secrets:
        return data
    scrubbed = data
    for secret in secrets:
        if not secret:
            continue
        if secret in scrubbed:
            scrubbed = scrubbed.replace(secret, REDACTED_BYTES)
        pattern = _percent_casefold_pattern(secret)
        if pattern is not None:
            scrubbed = pattern.sub(REDACTED_BYTES, scrubbed)
    return scrubbed


def _write_stream(stream: object, data: bytes) -> None:
    if not data:
        return
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        buffer.write(data)
        buffer.flush()
    else:
        stream.write(data.decode("utf-8", errors="replace"))  # type: ignore[attr-defined]
        stream.flush()  # type: ignore[attr-defined]


def exec_with_secrets(
    root: Path,
    mappings: Sequence[tuple[str, str]],
    argv: Sequence[str],
    *,
    files: Iterable[str] | None = None,
) -> int:
    """Run a child command with secret keys injected via env and scrubbed output."""
    if not argv or not mappings:
        print("secret_guard: --exec-with-secret requires at least one KEY=ENV_VAR and a command", file=sys.stderr)
        return 2
    base = Path(root)
    guarded = _guarded_file_names(files)
    resolved: list[tuple[str, str]] = []
    for key, env_var in mappings:
        clean_key = (key or "").strip()
        clean_env = (env_var or "").strip()
        if not clean_key or not ENV_VAR_NAME.match(clean_env):
            print("secret_guard: invalid KEY=ENV_VAR mapping", file=sys.stderr)
            return 2
        value = read_secret_key(base, clean_key, files=guarded)
        if value is None:
            print(f"secret_guard: secret key not found: {clean_key}", file=sys.stderr)
            return 2
        resolved.append((clean_env, value))

    env = dict(os.environ)
    scrub_set: set[bytes] = set(secret_values(base, guarded))
    for env_var, value in resolved:
        env[env_var] = value
        for form in _secret_byte_forms(value.encode("utf-8")):
            scrub_set.add(form)
    ordered_secrets = sorted(scrub_set, key=len, reverse=True)

    try:
        completed = subprocess.run(  # nosec B603 - explicit argv without shell; output is scrubbed
            list(argv), env=env, capture_output=True, check=False
        )
    except OSError as exc:
        message = _scrub_bytes(f"secret_guard: failed to execute command: {exc}\n".encode("utf-8"), ordered_secrets)
        _write_stream(sys.stderr, message)
        return 127

    _write_stream(sys.stdout, _scrub_bytes(completed.stdout, ordered_secrets))
    _write_stream(sys.stderr, _scrub_bytes(completed.stderr, ordered_secrets))
    return completed.returncode


def _parse_exec_with_secret_argv(argv: Sequence[str]) -> tuple[list[tuple[str, str]], list[str]] | None:
    mappings: list[tuple[str, str]] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--":
            command = list(argv[index + 1 :])
            return (mappings, command) if mappings and command else None
        if token == "--exec-with-secret":
            if index + 1 >= len(argv):
                return None
            spec = argv[index + 1]
            index += 2
        elif token.startswith("--exec-with-secret="):
            spec = token.split("=", 1)[1]
            index += 1
        else:
            return None
        key, sep, env_var = spec.partition("=")
        if sep != "=" or not key.strip() or not ENV_VAR_NAME.match(env_var.strip()):
            return None
        mappings.append((key.strip(), env_var.strip()))
    return None


def _resolve_root() -> Path:
    try:
        return Path(git("rev-parse", "--show-toplevel").decode().strip())
    except (subprocess.CalledProcessError, RuntimeError, OSError):
        return Path.cwd()


def main(argv: list[str], stdin: str = "") -> int:
    """Run the guard; return the process exit code."""
    if argv[:1] and (argv[0] == "--exec-with-secret" or argv[0].startswith("--exec-with-secret=")):
        parsed = _parse_exec_with_secret_argv(argv)
        if parsed is None:
            print(
                "secret_guard: usage: secret_guard.py --exec-with-secret KEY=ENV_VAR [--exec-with-secret ...] -- <command...>",
                file=sys.stderr,
            )
            return 2
        mappings, command = parsed
        return exec_with_secrets(_resolve_root(), mappings, command)

    root = Path(git("rev-parse", "--show-toplevel").decode().strip())
    try:
        if argv[:1] == ["--push"]:
            items: Iterable[tuple[str, bytes]] = push_contents(stdin)
        elif argv[:1] == ["--rev"]:
            items = revisions(argv[1:])
        else:
            items = staged()
    except PermissionError as refused:
        print(str(refused), file=sys.stderr)
        return 1
    values = secret_values(root, os.environ.get("SECRET_GUARD_FILES", DEFAULT_GUARDED_FILES).split(","))
    allow = allowed_globs(root)
    paths = blocked_paths(root)
    blocked = [f"{path}: {', '.join(found)}" for path, data in items
               for found in [findings(path, data, values, allow, paths)] if found]
    if blocked:
        print("secret_guard BLOCKED (values not shown):\n  " + "\n  ".join(blocked), file=sys.stderr)
        print("Fix the files, or a false positive in the guard or .secret-guard-allow. Never use --no-verify.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], sys.stdin.read() if sys.argv[1:2] == ["--push"] else ""))
