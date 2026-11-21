"""Read-only measurement of GitHub's pre-filled issues/new URL cap (#129).

Builds ``issues/new?template=chaos-engine-installer.yml`` URLs from 4096 to
16384 encoded characters, step 256. GETs them. Never submits a form.
Records the encoded/raw ratio of real failure payloads through
``bootstrap.encode_issue_form_url``. A signed-in browser is recorded only
when this process actually has one.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
REPOSITORY = "ShaftHQ/chaosengine-harness"
CURRENT_CAP = 7800
PROBE_START = 4096
PROBE_END = 16384
PROBE_STEP = 256


def load_bootstrap():
    spec = importlib.util.spec_from_file_location("ce_bootstrap_url_cap", ROOT / "bootstrap.py")
    if spec is None or spec.loader is None:
        raise ImportError("cannot load bootstrap.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def probe_lengths() -> list[int]:
    return list(range(PROBE_START, PROBE_END + 1, PROBE_STEP))


def issues_new_url(encoded_length: int) -> str:
    base = (
        f"https://github.com/{REPOSITORY}/issues/new"
        "?template=chaos-engine-installer.yml&title=cap-probe&cause="
    )
    if encoded_length < len(base):
        raise ValueError(f"{encoded_length} is shorter than the base URL ({len(base)})")
    return base + ("a" * (encoded_length - len(base)))


def probe_status(url: str, timeout: float = 30.0) -> int:
    """GET with curl. Redirects are not followed. Nothing is submitted.

    urllib to github.com:443 timed out from this environment (IPv6). curl -4
    returns the status, so the measured client is curl.
    """
    completed = subprocess.run(
        [
            "curl",
            "-4",
            "-sS",
            "-o",
            "/dev/null",
            "-w",
            "%{http_code}",
            "--max-redirs",
            "0",
            "--connect-timeout",
            "15",
            "--max-time",
            str(int(timeout)),
            "-A",
            "chaosengine-installer-url-cap",
            url,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    text = (completed.stdout or "").strip()
    if text.isdigit():
        return int(text)
    raise RuntimeError((completed.stderr or "curl produced no status").strip())


def choose_cap(failure_lengths: list[int], current: int = CURRENT_CAP) -> dict[str, object]:
    """80% of the lowest failing length. Keep ``current`` when it is still under that."""
    if not failure_lengths:
        return {
            "boundary": None,
            "cap80": None,
            "chosen": current,
            "reason": (
                f"no 414 or other error from {PROBE_START} to {PROBE_END}; "
                f"{current} stays because a boundary above the probe puts it under the cap"
            ),
        }
    boundary = min(failure_lengths)
    cap80 = int(boundary * 0.8)
    if current <= cap80:
        return {
            "boundary": boundary,
            "cap80": cap80,
            "chosen": current,
            "reason": f"{current} is under 80% of the lowest boundary ({boundary})",
        }
    return {
        "boundary": boundary,
        "cap80": cap80,
        "chosen": cap80,
        "reason": f"lowered to 80% of the lowest boundary ({boundary})",
    }


def _fields(snippet: str) -> dict[str, str]:
    return {
        "error_code": "CE-INSTALL-FAILED",
        "cause": "download failed before the bundle check",
        "failed_phase": "Download source",
        "unhealthy": "core",
        "platform": "linux",
        "os_name": "Linux",
        "os_version": "6.8.0",
        "architecture": "x86_64",
        "python_version": "3.11.0",
        "machine": "probe",
        "doctor_details": "core missing",
        "hosts_receipt": "grok not activated",
        "core_dir": ".chaos-engine",
        "install_py": "missing",
        "install_trace": ".chaos-engine-state/install-trace.json",
        "status_command": "python3 .chaos-engine/install.py status --project . --json",
        "doctor_command": "python3 .chaos-engine/install.py doctor --project . --json",
        "install_trace_snippet": snippet,
        "console_log": "START Download source\nFAIL Download source\n",
        "doctor_json": '{"status":"broken","components":{"core":{"status":"absent"}}}\n',
        "additional": "synthetic failure payload for the URL ratio; no secrets",
    }


def payload_ratios(bootstrap) -> list[dict[str, object]]:
    rows = []
    for label, size in (("short", 200), ("trace-4k", 4096), ("trace-50k", 50_000)):
        snippet = "trace line\n" * (size // 11 + 1)
        snippet = snippet[:size]
        fields = _fields(snippet)
        raw = sum(len(value) for value in fields.values()) + len("ChaosEngine install failed")
        url = bootstrap.encode_issue_form_url(
            REPOSITORY, "ChaosEngine install failed", fields
        )
        rows.append(
            {
                "label": label,
                "rawChars": raw,
                "urlChars": len(url),
                "ratio": round(len(url) / raw, 4) if raw else None,
                "underCurrentCap": len(url) <= CURRENT_CAP,
            }
        )
    return rows


def length_rejected(status: int, control: int) -> bool:
    """A longer URL failed because of length, not because every URL fails the same way."""
    if status in {414, 431}:
        return True
    if status == control:
        return False
    return status >= 400


def probe_anonymous() -> dict[str, object]:
    control_url = issues_new_url(PROBE_START)
    control = probe_status(control_url)
    samples = [{"length": PROBE_START, "status": control}]
    failures: list[int] = []
    if length_rejected(control, control):
        # 414 on the first probe is itself the boundary.
        if control in {414, 431}:
            failures.append(PROBE_START)
        return {
            "measured": True,
            "client": "curl -4, redirects not followed",
            "controlStatus": control,
            "samples": samples,
            "failureLengths": failures,
            "exactBoundary": failures[0] if failures else None,
        }
    for length in probe_lengths():
        if length == PROBE_START:
            continue
        url = issues_new_url(length)
        if len(url) != length:
            raise RuntimeError(f"probe URL length {len(url)} != {length}")
        status = probe_status(url)
        samples.append({"length": length, "status": status})
        if status in {403, 429}:
            samples[-1]["note"] = "rate limit; probe stopped"
            break
        if length_rejected(status, control):
            failures.append(length)
            break
    exact = None
    if failures:
        grid_failure = failures[0]
        previous = max(
            (row["length"] for row in samples if row["length"] < grid_failure and row["status"] == control),
            default=grid_failure,
        )
        # One pass finds the bucket. The edge flips between 302 and 500, so the
        # boundary is the lowest length that errors in three tries while the
        # length below stays on the control status for three tries.
        low = previous
        high = grid_failure
        while low + 1 < high:
            mid = (low + high) // 2
            status = probe_status(issues_new_url(mid))
            samples.append({"length": mid, "status": status, "refined": True})
            if length_rejected(status, control):
                high = mid
            else:
                low = mid

        def three(length: int) -> list[int]:
            codes = []
            for _ in range(3):
                code = probe_status(issues_new_url(length))
                codes.append(code)
                samples.append({"length": length, "status": code, "refined": True, "repeats": 3})
            return codes

        errors = [row["length"] for row in samples if length_rejected(row["status"], control)]
        oks = [row["length"] for row in samples if row["status"] == control and row["length"] < min(errors)]
        start = max(previous, (max(oks) if oks else previous) - 1)
        for length in range(start, min(grid_failure, start + 24) + 1):
            if any(length_rejected(code, control) for code in three(length)):
                if all(code == control for code in three(length - 1)):
                    exact = length
                    failures = [length]
                    break
        # A later 302 at the edge must not hide an earlier error at a shorter URL.
        erred = sorted(
            {row["length"] for row in samples if length_rejected(row["status"], control)}
        )
        if erred:
            lowest = erred[0]
            below = [row["status"] for row in samples if row["length"] == lowest - 1]
            if below and all(code == control for code in below):
                exact = lowest
                failures = [lowest]
    for length in (7936, 8192):
        samples.append(
            {
                "length": length,
                "status": probe_status(issues_new_url(length)),
                "note": "414-check",
            }
        )
    return {
        "measured": True,
        "client": "curl -4, redirects not followed",
        "controlStatus": control,
        "samples": samples,
        "failureLengths": failures,
        "exactBoundary": exact,
    }


def write_results(document: dict[str, object]) -> None:
    (HERE / "results.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    decision = document["decision"]
    ratios = document["ratios"]
    fitting = [row["ratio"] for row in ratios if row.get("underCurrentCap") and row["ratio"] >= 1]
    anonymous = document["clients"]["anonymous"]
    by_length: dict[int, list[int]] = {}
    for row in anonymous["samples"]:
        by_length.setdefault(int(row["length"]), []).append(int(row["status"]))
    boundary = decision["boundary"]
    boundary_status = next(
        (code for code in by_length.get(int(boundary or 0), []) if code != anonymous["controlStatus"]),
        None,
    )
    first_414 = next(
        (length for length, codes in sorted(by_length.items()) if 414 in codes),
        None,
    )
    lines = [
        "# Installer URL cap measurement",
        "",
        "Issue #129. Read-only GET with `curl -4`. Redirects were not followed. Nothing was submitted.",
        "",
        f"- Anonymous client: `{anonymous['client']}`",
        f"- Control status (short URL): `{anonymous['controlStatus']}`",
        f"- Lowest failing length: `{boundary}` (HTTP `{boundary_status}`)",
        f"- First sampled HTTP 414: `{first_414}`",
        f"- 80% of that boundary: `{decision['cap80']}`",
        f"- Chosen cap: `{decision['chosen']}` ({decision['reason']})",
        f"- Product `MAX_ISSUE_URL_CHARS` left at `{document['productCapUnchanged']}` in this slice (no product code change). #134 applies the chosen cap.",
        f"- Encoded/raw ratio for payloads that still fit: `{min(fitting)}` to `{max(fitting)}`",
        "- A 50 KB trace is truncated by the current encoder before packing, so its packed ratio is not an expansion ratio. See `results.json`.",
        f"- Signed-in browser: not measured ({document['clients']['signed-in-browser']['reason']})",
        "",
        "Statuses are in `results.json`.",
        "",
    ]
    (HERE / "RESULTS.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    bootstrap = load_bootstrap()
    anonymous = probe_anonymous()
    decision = choose_cap(list(anonymous["failureLengths"]))
    document = {
        "repository": REPOSITORY,
        "probe": {"start": PROBE_START, "end": PROBE_END, "step": PROBE_STEP},
        "clients": {
            "anonymous": anonymous,
            "signed-in-browser": {
                "measured": False,
                "reason": "no signed-in browser session in this environment",
            },
        },
        "ratios": payload_ratios(bootstrap),
        "decision": decision,
        "productCapUnchanged": bootstrap.MAX_ISSUE_URL_CHARS,
    }
    write_results(document)
    print(json.dumps({"chosen": decision["chosen"], "boundary": decision["boundary"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
