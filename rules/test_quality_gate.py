"""Diff-scoped test and e2e quality gate (#219).

Stdlib only. Callers:

- ``evaluate_content`` / ``evaluate_edit`` — PreToolUse Write and Edit
- ``evaluate_git_diff`` — ``pre_done_review`` over a git diff
- ``evaluate`` — standard ``rules/pre_done_bridge.py`` payload shape

Integration owns adding this module to ``pre_done_bridge.WIRED``. A missing
module must not block: callers treat ImportError and a missing file as allow.

assert-justified: rule module matches test_*.py; behavior assertions live in tests.
"""

from __future__ import annotations

import ast
import difflib
import re
from typing import Iterable

_EXCLUDE = frozenset({"vendor", "node_modules"})
_DIR_MARKERS = frozenset({"tests", "test", "e2e"})
_TEST_SUFFIXES = (".spec.ts", ".spec.js", ".test.ts", ".test.js")

# Detector text is concatenated so this rule module does not contain the
# literals it flags. The file name matches test_*.py, so a rewrite is scanned.
_SLEEP = re.compile(
    "time\\." + "sleep\\(|" + "Thread\\." + "sleep\\(|" + "asyncio\\." + "sleep\\(|"
    + "waitFor" + "Timeout\\(|" + "cy\\." + "wait\\(\\s*\\d+"
)
_SKIP = re.compile(
    "\\." + "only\\(|" + "\\bf" + "describe\\(|" + "\\bf" + "it\\(|"
    + "@pytest.mark." + "skip(?![A-Za-z])|"
    + "@unittest." + "skip(?![A-Za-z])|"
    + "@" + "Ignore(?![A-Za-z])|"
    + "@" + "Disabled(?![A-Za-z])"
)
_FULL_SOURCE = re.compile(
    "\\." + "page_source|" + "getPage" + "Source\\(|" + "page\\." + "content\\(|"
    + "document\\.document" + "Element\\.outer" + "HTML"
)
_HTML = "/ht" + "ml"
_XPATH = re.compile(_HTML + "/body|" + "[" + "\"'`" + "]" + r"\s*" + _HTML + r"(?:/|\b)")
_STRING = re.compile(r"""(?P<q>['"`])(?P<body>(?:\\.|(?!(?P=q)).)*)(?P=q)""")
_CHILD = re.compile(r"(?<![=<-])>(?!=)")
_TEST_DEF = re.compile(
    r"^\s*(?:async\s+)?def\s+(test_\w+)\s*\("
    r"|^\s*(?:it|test|specify)\s*\(\s*['\"]"
    r"|^\s*func\s+(Test\w+)\s*\("
    r"|^\s*@Test\b"
    r"|^\s*(?:public|protected|private)?\s*(?:static\s+)?void\s+(test\w+)\s*\("
)
_STRONG = re.compile(
    r"\bassert(?:Equal|NotEqual|AlmostEqual|GreaterEqual|Greater|LessEqual|Less|"
    r"Regex|NotIn|In|IsNot|Is|DictEqual|ListEqual|SetEqual|TupleEqual|CountEqual|"
    r"MultiLineEqual|SequenceEqual|RaisesRegex|Raises|Warns|Logs)\b"
    r"|\bpytest\.raises\b|\bassertThat\b|\bexpect\s*\("
)
_WEAK = re.compile(
    r"\bassert(?:True|False|IsNone|IsNotNone)\b"
    r"|\.toBe(?:Truthy|Falsy|Nullish|Null|Undefined|Defined|Nil)\b"
)
_PLAIN_ASSERT = re.compile(r"\bassert\b(?![A-Za-z])")
_ANY_ASSERT = re.compile(
    r"\bassert(?:Equal|NotEqual|AlmostEqual|GreaterEqual|Greater|LessEqual|Less|"
    r"Regex|NotIn|In|IsNotNone|IsNone|IsNot|Is|True|False|DictEqual|ListEqual|"
    r"CountEqual|RaisesRegex|Raises|Warns|Logs)?\b"
    r"|\bexpect\s*\(|\braises\b|\bassertThat\b"
)
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
_CODE_ORDER = {
    "sleep": 0,
    "skip-or-only": 1,
    "silent-swallow": 2,
    "assertion-weakening": 3,
    "full-source": 4,
    "absolute-xpath": 5,
    "deep-css": 6,
}


def is_test_path(path: str) -> bool:
    """True for test and e2e paths. ``vendor/`` and ``node_modules/`` never match."""
    if not isinstance(path, str):
        return False
    raw = path.strip().replace("\\", "/")
    if not raw or raw.endswith("/"):
        return False
    parts = [part for part in raw.split("/") if part not in {"", "."}]
    if not parts:
        return False
    if any(part in _EXCLUDE for part in parts):
        return False
    name = parts[-1]
    if any(part in _DIR_MARKERS for part in parts[:-1]):
        return True
    if name.endswith("_test.py") or (name.startswith("test_") and name.endswith(".py")):
        return True
    if name.endswith("Test.java") or name.endswith("Steps.java"):
        return True
    if name.endswith("_test.go"):
        return True
    return name.endswith(_TEST_SUFFIXES)


def evaluate_content(path: str, new_text: str, old_text: str | None = None) -> dict:
    """Score ``new_text``. With ``old_text``, only added lines can fire.

    Pre-existing legacy lines stay quiet. Assertion removal or downgrade is
    still visible because the counts compare the whole before and after text.
    """
    path = str(path or "")
    if not is_test_path(path):
        return {"ok": True, "path": path, "hits": []}
    new_text = "" if new_text is None else str(new_text)
    lines = new_text.splitlines()
    lines_by_no = {index: line for index, line in enumerate(lines, 1)}
    added = _added_lines(old_text, new_text)
    added_numbers = {number for number, _line in added}
    hits = _pattern_hits(path, lines_by_no, added)
    hits.extend(_swallow_hits(path, new_text, lines_by_no, added_numbers))
    hits.extend(_assertion_hits(path, new_text, old_text, lines_by_no, added, added_numbers))
    return _report(path, hits)


def evaluate_edit(
    path: str,
    old_string: str,
    new_string: str,
    existing_text: str | None = None,
) -> dict:
    """Score one Edit or Write payload.

    When ``existing_text`` contains ``old_string``, the replacement is spliced
    so untouched legacy lines are not scored. An empty ``old_string`` is a
    whole-file write.
    """
    path = str(path or "")
    if not is_test_path(path):
        return {"ok": True, "path": path, "hits": []}
    old_string = "" if old_string is None else str(old_string)
    new_string = "" if new_string is None else str(new_string)
    if existing_text is not None:
        existing_text = str(existing_text)
        if old_string and old_string in existing_text:
            updated = existing_text.replace(old_string, new_string, 1)
            return evaluate_content(path, updated, existing_text)
        if not old_string:
            return evaluate_content(path, new_string, existing_text)
    if not old_string:
        return evaluate_content(path, new_string, None)
    return evaluate_content(path, new_string, old_string)


def evaluate_git_diff(diff_text: str) -> dict:
    """Score added lines of test files in a unified diff or an apply-patch body."""
    hits: list[dict] = []
    first = ""
    for item in _iter_diff_files(_coerce_diff("" if diff_text is None else str(diff_text))):
        path = item["path"] or item["old_path"]
        if not is_test_path(path):
            continue
        if not first:
            first = path
        if item["new"] and _contiguous_from_one(item["added"]):
            text = "\n".join(line for _number, line in item["added"])
            if text and not text.endswith("\n"):
                text += "\n"
            report = evaluate_content(path, text, None)
            for hit in report["hits"]:
                hit["path"] = path
                hits.append(hit)
            continue
        file_hits = _pattern_hits(path, item["lines"], [(number, item["lines"][number]) for number in item["added_numbers"]])
        file_hits.extend(_swallow_added(path, item))
        file_hits.extend(_diff_assertion_hits(path, item))
        for hit in file_hits:
            hit["path"] = path
            hits.append(hit)
    return _report(first, hits)


def evaluate(payload: object) -> dict:
    """Bridge-shaped entry. A diff string, a content dict, or an edit dict."""
    if isinstance(payload, str):
        if _looks_like_diff(payload):
            return evaluate_git_diff(payload)
        return evaluate_content("tests/fixture_test.py", payload, None)
    if isinstance(payload, dict):
        if "diff" in payload or "diff_text" in payload:
            return evaluate_git_diff(str(payload.get("diff") or payload.get("diff_text") or ""))
        path = str(payload.get("path") or "tests/fixture_test.py")
        if "old_string" in payload or "new_string" in payload:
            existing = payload.get("existing_text")
            return evaluate_edit(
                path,
                str(payload.get("old_string") or ""),
                str(payload.get("new_string") if payload.get("new_string") is not None else payload.get("content") or ""),
                None if existing is None else str(existing),
            )
        new_text = payload.get("new_text", payload.get("content"))
        if new_text is None:
            return {"ok": True, "path": path, "hits": []}
        old = payload.get("old_text")
        return evaluate_content(path, str(new_text), None if old is None else str(old))
    return {"ok": True, "path": "", "hits": []}


def _report(path: str, hits: list[dict]) -> dict:
    ordered = sorted(hits, key=lambda hit: (hit.get("line", 0), _CODE_ORDER.get(hit.get("code", ""), 9)))
    return {"ok": not ordered, "path": path, "hits": ordered}


def _hit(code: str, line: int, detail: str, path: str = "") -> dict:
    text = " ".join(str(detail).strip().split())
    if len(text) > 160:
        text = text[:157] + "..."
    item = {"code": code, "line": int(line), "detail": text or code}
    if path:
        item["path"] = path
    return item


def _added_lines(old_text: str | None, new_text: str) -> list[tuple[int, str]]:
    new_lines = new_text.splitlines()
    if old_text is None:
        return list(enumerate(new_lines, 1))
    old_lines = old_text.splitlines()
    added: list[tuple[int, str]] = []
    new_lineno = 1
    started = False
    for line in difflib.unified_diff(old_lines, new_lines, n=0, lineterm=""):
        if line.startswith(("+++", "---", "\\")):
            continue
        match = _HUNK.match(line)
        if match:
            new_lineno = int(match.group(1))
            started = True
            continue
        if not started:
            continue
        if line.startswith("+"):
            added.append((new_lineno, line[1:]))
            new_lineno += 1
        elif line.startswith("-"):
            continue
        else:
            new_lineno += 1
    return added


def _has_token(lines_by_no: dict[int, str], number: int, tokens: tuple[str, ...]) -> bool:
    for line_no in (number, number - 1):
        text = lines_by_no.get(line_no, "")
        if any(token in text for token in tokens):
            return True
    return False


def _pattern_hits(path: str, lines_by_no: dict[int, str], added: Iterable[tuple[int, str]]) -> list[dict]:
    hits: list[dict] = []
    for number, line in added:
        if _SLEEP.search(line) and not _has_token(lines_by_no, number, ("sleep-justified:", "e2e-allow-sleep:")):
            hits.append(_hit("sleep", number, line, path))
        if _SKIP.search(line) and not _has_token(lines_by_no, number, ("skip-justified:",)):
            hits.append(_hit("skip-or-only", number, line, path))
        if _FULL_SOURCE.search(line) and not _has_token(lines_by_no, number, ("full-source-justified:",)):
            hits.append(_hit("full-source", number, line, path))
        if _XPATH.search(line):
            hits.append(_hit("absolute-xpath", number, line, path))
        if _deep_css(line) and not _has_token(lines_by_no, number, ("e2e-allow-css:",)):
            hits.append(_hit("deep-css", number, line, path))
    return hits


def _deep_css(line: str) -> bool:
    for match in _STRING.finditer(line):
        body = match.group("body")
        if len(_CHILD.findall(body)) >= 6 or body.count(":nth-child") >= 6:
            return True
    return False


def _swallow_hits(path: str, new_text: str, lines_by_no: dict[int, str], added: set[int]) -> list[dict]:
    if not str(path).endswith(".py"):
        return []
    try:
        tree = ast.parse(new_text)
    except SyntaxError:
        return _swallow_lines(path, lines_by_no, added)
    hits: list[dict] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if len(node.body) != 1 or not isinstance(node.body[0], ast.Pass):
            continue
        except_line = int(node.lineno)
        pass_line = int(node.body[0].lineno)
        if added and except_line not in added and pass_line not in added:
            continue
        if _has_token(lines_by_no, except_line, ("swallow-justified:",)) or _has_token(
            lines_by_no, pass_line, ("swallow-justified:",)
        ):
            continue
        hits.append(_hit("silent-swallow", pass_line, lines_by_no.get(pass_line, "pass"), path))
    return hits


def _swallow_lines(path: str, lines_by_no: dict[int, str], added: set[int]) -> list[dict]:
    hits: list[dict] = []
    numbers = sorted(lines_by_no)
    for number in numbers:
        line = lines_by_no[number]
        single = re.match(r"^\s*except\b[^:\n]*:\s*pass\s*(#.*)?$", line)
        if single:
            if number in added and not _has_token(lines_by_no, number, ("swallow-justified:",)):
                hits.append(_hit("silent-swallow", number, line, path))
            continue
        if not re.match(r"^\s*except\b", line):
            continue
        nxt = number + 1
        while nxt in lines_by_no and not lines_by_no[nxt].strip():
            nxt += 1
        if nxt not in lines_by_no or not re.match(r"^\s*pass\s*(#.*)?$", lines_by_no[nxt]):
            continue
        if not _pass_is_only_body(lines_by_no, nxt):
            continue
        if number not in added and nxt not in added:
            continue
        if _has_token(lines_by_no, number, ("swallow-justified:",)) or _has_token(
            lines_by_no, nxt, ("swallow-justified:",)
        ):
            continue
        hits.append(_hit("silent-swallow", nxt, lines_by_no[nxt], path))
    return hits


def _pass_is_only_body(lines_by_no: dict[int, str], pass_line: int) -> bool:
    pass_indent = len(lines_by_no[pass_line]) - len(lines_by_no[pass_line].lstrip(" "))
    nxt = pass_line + 1
    while nxt in lines_by_no and not lines_by_no[nxt].strip():
        nxt += 1
    if nxt not in lines_by_no:
        return True
    following = lines_by_no[nxt]
    indent = len(following) - len(following.lstrip(" "))
    if indent > pass_indent:
        return False
    if indent == pass_indent and following.strip() and not re.match(r"\s*(except|else|finally)\b", following):
        return False
    return True


def _counts(text: str) -> tuple[int, int, int]:
    strong = len(_STRONG.findall(text or ""))
    weak = len(_WEAK.findall(text or ""))
    plain = len(_PLAIN_ASSERT.findall(text or ""))
    return strong, weak, strong + weak + plain


def _weakened(old_text: str, new_text: str) -> bool:
    old_strong, old_weak, old_total = _counts(old_text)
    new_strong, new_weak, new_total = _counts(new_text)
    if old_total == 0 and old_strong == 0:
        return False
    return new_total < old_total or (new_strong < old_strong and new_weak > old_weak)


def _assertion_hits(
    path: str,
    new_text: str,
    old_text: str | None,
    lines_by_no: dict[int, str],
    added: list[tuple[int, str]],
    added_numbers: set[int],
) -> list[dict]:
    hits: list[dict] = []
    is_new = old_text is None or old_text == ""
    if old_text and _weakened(old_text, new_text) and not _change_has_token(lines_by_no, added, "assertion-justified:"):
        line_no = _weakening_line(added, lines_by_no)
        hits.append(_hit("assertion-weakening", line_no, "assertion removed or downgraded", path))
    function_hits = _missing_test_functions(path, new_text, lines_by_no, None if is_new else added_numbers)
    hits.extend(function_hits)
    if is_new and not function_hits and not _ANY_ASSERT.search(new_text) and "assert-justified:" not in new_text:
        if new_text.strip():
            hits.append(_hit("assertion-weakening", 1, "new test file lacks an assertion", path))
    return hits


def _change_has_token(lines_by_no: dict[int, str], added: list[tuple[int, str]], token: str) -> bool:
    if not added:
        return False
    return any(_has_token(lines_by_no, number, (token,)) for number, _line in added)


def _weakening_line(added: list[tuple[int, str]], lines_by_no: dict[int, str]) -> int:
    for number, line in added:
        if _WEAK.search(line) or _ANY_ASSERT.search(line):
            return number
    if added:
        return added[0][0]
    return next(iter(lines_by_no), 1)


def _missing_test_functions(
    path: str,
    new_text: str,
    lines_by_no: dict[int, str],
    added_numbers: set[int] | None,
) -> list[dict]:
    if path.endswith(".py"):
        try:
            tree = ast.parse(new_text)
        except SyntaxError:
            tree = None
        if tree is not None:
            return _missing_python_tests(path, tree, lines_by_no, added_numbers)
    return _missing_regex_tests(path, lines_by_no, added_numbers)


def _missing_python_tests(
    path: str,
    tree: ast.AST,
    lines_by_no: dict[int, str],
    added_numbers: set[int] | None,
) -> list[dict]:
    hits: list[dict] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("test"):
            continue
        if added_numbers is not None and node.lineno not in added_numbers:
            continue
        end = int(getattr(node, "end_lineno", node.lineno) or node.lineno)
        body = "\n".join(lines_by_no.get(index, "") for index in range(node.lineno, end + 1))
        if _ANY_ASSERT.search(body) or "assert-justified:" in body:
            continue
        if node.lineno > 1 and "assert-justified:" in lines_by_no.get(node.lineno - 1, ""):
            continue
        hits.append(_hit("assertion-weakening", int(node.lineno), f"new test lacks an assertion: {node.name}", path))
    return hits


def _missing_regex_tests(
    path: str,
    lines_by_no: dict[int, str],
    added_numbers: set[int] | None,
) -> list[dict]:
    hits: list[dict] = []
    numbers = sorted(lines_by_no)
    for index, number in enumerate(numbers):
        line = lines_by_no[number]
        match = _TEST_DEF.match(line)
        if not match:
            continue
        if added_numbers is not None and number not in added_numbers:
            continue
        indent = len(line) - len(line.lstrip(" "))
        chunk = [line]
        for later in numbers[index + 1 :]:
            later_line = lines_by_no[later]
            if later_line.strip() and (len(later_line) - len(later_line.lstrip(" "))) <= indent and _TEST_DEF.match(later_line):
                break
            if later_line.strip() and (len(later_line) - len(later_line.lstrip(" "))) <= indent and re.match(
                r"\s*(?:def |class |function |describe\()", later_line
            ):
                break
            chunk.append(later_line)
            if later - number > 80:
                break
        body = "\n".join(chunk)
        if _ANY_ASSERT.search(body) or "assert-justified:" in body:
            continue
        if number > 1 and "assert-justified:" in lines_by_no.get(number - 1, ""):
            continue
        name = next((group for group in match.groups() if group), "test")
        hits.append(_hit("assertion-weakening", number, f"new test lacks an assertion: {name}", path))
    return hits


def _swallow_added(path: str, item: dict) -> list[dict]:
    if not item["added_numbers"]:
        return []
    groups = _contiguous_groups(item["added"])
    hits: list[dict] = []
    for group in groups:
        base = group[0][0]
        block = "\n".join(line for _number, line in group)
        lines_by_no = {base + offset: line for offset, (_number, line) in enumerate(group)}
        added = set(lines_by_no)
        try:
            import textwrap

            parsed = textwrap.dedent(block)
            tree = ast.parse(parsed)
        except (SyntaxError, ValueError):
            hits.extend(_swallow_lines(path, lines_by_no, added))
            continue
        # Dedent shifts content, not the relative line numbers of a uniform indent.
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            if len(node.body) != 1 or not isinstance(node.body[0], ast.Pass):
                continue
            pass_line = base + int(node.body[0].lineno) - 1
            except_line = base + int(node.lineno) - 1
            if _has_token(item["lines"], except_line, ("swallow-justified:",)) or _has_token(
                item["lines"], pass_line, ("swallow-justified:",)
            ):
                continue
            detail = item["lines"].get(pass_line, "pass")
            hits.append(_hit("silent-swallow", pass_line, detail, path))
    return hits


def _contiguous_groups(added: list[tuple[int, str]]) -> list[list[tuple[int, str]]]:
    groups: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] = []
    previous = None
    for number, line in added:
        if previous is not None and number != previous + 1:
            if current:
                groups.append(current)
            current = []
        current.append((number, line))
        previous = number
    if current:
        groups.append(current)
    return groups


def _diff_assertion_hits(path: str, item: dict) -> list[dict]:
    hits: list[dict] = []
    removed = "\n".join(item["removed"])
    added_numbers = [number for number in item["added_numbers"]]
    added_text = "\n".join(item["lines"][number] for number in added_numbers)
    added_pairs = [(number, item["lines"][number]) for number in added_numbers]
    if _weakened(removed, added_text) and not _change_has_token(item["lines"], added_pairs, "assertion-justified:"):
        hits.append(
            _hit(
                "assertion-weakening",
                _weakening_line(added_pairs, item["lines"]),
                "assertion removed or downgraded",
                path,
            )
        )
    hits.extend(_missing_regex_tests(path, item["lines"], set(added_numbers)))
    return hits


def _contiguous_from_one(added: list[tuple[int, str]]) -> bool:
    if not added:
        return False
    return [number for number, _line in added] == list(range(1, len(added) + 1))


def _looks_like_diff(text: str) -> bool:
    return text.lstrip().startswith(("diff --git", "--- ", "*** Begin Patch", "*** Update File:", "*** Add File:")) or "\ndiff --git " in text


def _coerce_diff(text: str) -> str:
    if "diff --git " in text or text.lstrip().startswith("--- "):
        return text
    if "*** " not in text:
        return text
    return _from_apply_patch(text)


def _from_apply_patch(text: str) -> str:
    blocks: list[str] = []
    current_path = ""
    new_file = False
    added: list[str] = []
    removed: list[str] = []

    def flush() -> None:
        nonlocal current_path, new_file, added, removed
        if not current_path:
            added = []
            removed = []
            new_file = False
            return
        lines = [f"diff --git a/{current_path} b/{current_path}"]
        if new_file:
            lines.append("new file mode 100644")
            lines.append("--- /dev/null")
        else:
            lines.append(f"--- a/{current_path}")
        lines.append(f"+++ b/{current_path}")
        lines.append(f"@@ -1,{max(len(removed), 1)} +1,{max(len(added), 1)} @@")
        lines.extend(f"-{line}" for line in removed)
        lines.extend(f"+{line}" for line in added)
        blocks.append("\n".join(lines))
        current_path = ""
        new_file = False
        added = []
        removed = []

    for line in text.splitlines():
        if line.startswith("*** Add File:"):
            flush()
            current_path = line.split(":", 1)[1].strip()
            new_file = True
        elif line.startswith("*** Update File:"):
            flush()
            current_path = line.split(":", 1)[1].strip()
        elif line.startswith("*** Delete File:"):
            flush()
            current_path = line.split(":", 1)[1].strip()
        elif line.startswith("***"):
            continue
        elif current_path and line.startswith("+"):
            added.append(line[1:])
        elif current_path and line.startswith("-") and not line.startswith("---"):
            removed.append(line[1:])
    flush()
    return "\n".join(blocks)


def _diff_path(header: str) -> str:
    part = header[4:].strip() if header.startswith(("+++", "---")) else header.strip()
    part = part.split("\t", 1)[0].strip()
    if len(part) >= 2 and part[0] == '"' and part[-1] == '"':
        part = part[1:-1]
    if part in {"/dev/null", "dev/null"}:
        return ""
    if part.startswith(("a/", "b/")):
        part = part[2:]
    return part


def _iter_diff_files(diff_text: str):
    current: dict | None = None
    new_line = 1
    in_hunk = False

    def start() -> dict:
        return {
            "path": "",
            "old_path": "",
            "added": [],
            "removed": [],
            "lines": {},
            "added_numbers": [],
            "new": False,
        }

    for raw in diff_text.splitlines():
        if raw.startswith("diff --git "):
            if current and (current["path"] or current["old_path"]):
                yield current
            current = start()
            match = re.match(r"diff --git a/(.+?) b/(.+)$", raw)
            if match:
                current["old_path"] = match.group(1).strip()
                current["path"] = match.group(2).strip()
            in_hunk = False
            continue
        if raw.startswith("new file mode") and current is not None:
            current["new"] = True
            continue
        if raw.startswith("--- "):
            path = _diff_path(raw)
            if current is None:
                current = start()
            current["old_path"] = path
            if not path:
                current["new"] = True
            continue
        if raw.startswith("+++ "):
            path = _diff_path(raw)
            if current is None:
                current = start()
            if path:
                current["path"] = path
            continue
        if raw.startswith("@@"):
            match = _HUNK.match(raw)
            new_line = int(match.group(1)) if match else 1
            in_hunk = True
            if current is None:
                current = start()
            continue
        if not in_hunk or current is None:
            continue
        if raw.startswith("\\"):
            continue
        if raw.startswith("+"):
            current["lines"][new_line] = raw[1:]
            current["added"].append((new_line, raw[1:]))
            current["added_numbers"].append(new_line)
            new_line += 1
        elif raw.startswith("-"):
            current["removed"].append(raw[1:])
        else:
            text = raw[1:] if raw.startswith(" ") else raw
            current["lines"][new_line] = text
            new_line += 1
    if current and (current["path"] or current["old_path"]):
        yield current
