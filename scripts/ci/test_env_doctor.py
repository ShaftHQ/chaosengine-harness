#!/usr/bin/env python3
"""Read-only test-environment doctor.

Probes local binaries, versions, caches, env vars, and optional loopback
status URLs. Never installs packages, pulls images, downloads SDKs, or boots
devices. Every probe argv must pass ``command_allowed`` first.
"""

import argparse
import json
import os
import platform
import re
import shutil
import subprocess  # nosec B404 - allowlisted argv, shell is never used.
import sys
import urllib.request
from pathlib import Path

SCHEMA_VERSION = 1
DEFAULT_GRID_URL = "http://127.0.0.1:4444/status"
DEFAULT_APPIUM_URL = "http://127.0.0.1:4723/status"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
CHECK_IDS = (
    "python",
    "node",
    "java",
    "mvn",
    "docker",
    "grid",
    "appium",
    "appium-drivers",
    "android-sdk",
    "android-accel",
    "android-avd",
    "android-device",
    "ios-sim",
    "playwright",
    "testcontainers",
)
PROFILES = {
    "web": ("node", "playwright"),
    "grid": ("docker", "grid"),
    "mobile-android": (
        "node",
        "java",
        "appium",
        "appium-drivers",
        "android-sdk",
        "android-accel",
        "android-avd",
        "android-device",
    ),
    "mobile-ios": ("node", "appium", "appium-drivers", "ios-sim"),
    "api": ("python", "java", "mvn"),
    "all": CHECK_IDS,
}
_FAIL_STATES = frozenset({"absent", "unready"})
_HTTP_URL = re.compile(
    r"^(https?)://(\[[0-9A-Fa-f:.]+\]|[^:/@?#\s]+)(?::(\d+))?(/[^?#\s]*)?$"
)
_VERSION = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?")
_NULL_PACKAGE = re.compile(
    r"null[- ]package|missing tarball|cannot read properties of null",
    re.IGNORECASE,
)
_SAFE_SERIAL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_CONTEXT = re.compile(r"context=(\S+)")
_ROOTLESS = re.compile(r"rootless=(true|false)")
_EXACT = frozenset(
    {
        ("python", "--version"),
        ("python3", "--version"),
        ("node", "--version"),
        ("java", "-version"),
        ("mvn", "--version"),
        ("mvn", "-version"),
        ("docker", "info"),
        ("adb", "version"),
        ("adb", "devices"),
        ("emulator", "-version"),
        ("emulator", "-accel-check"),
        ("emulator", "-list-avds"),
        ("sdkmanager", "--version"),
        ("xcode-select", "-p"),
    }
)
GRID_FIX = (
    "After owner approval, run Selenium Grid pinned to 4.54.0-20261123 "
    "with shm_size: 2gb. On arm64 prefer node-chromium and node-firefox images."
)
NODE_FIX = (
    "Ask before installing Node. Appium 4 needs ^22.22.2 || ^24.15 || >=26. "
    "Appium 3 needs ^20.19 || ^22.12 || >=24."
)
DOCKER_FIX = "Ask before installing Docker. Image pulls wait for an explicit owner yes."
DRIVER_FIX = (
    "Ask before installing an Appium driver. A null-package npm error is handled in "
    "references/appium-driver-npm-recover.md."
)
NULL_FIX = (
    "Null-package npm error. Follow references/appium-driver-npm-recover.md: "
    "uninstall the driver, then reinstall with --source=npm at the pinned version. Ask first."
)
SDK_FIX = (
    "Ask before installing Android command-line tools. Set ANDROID_HOME. "
    "Keep ANDROID_SDK_ROOT identical when it is set. Accept `android sdk` / "
    "`android emulator` or legacy `sdkmanager` / `avdmanager`, plus adb and emulator."
)
ACCEL_FIX = (
    "emulator -accel-check must exit 0. Linux needs /dev/kvm, macOS needs HVF, "
    "Windows needs WHPX."
)
AVD_FIX = (
    "After owner approval, create a suite-owned AVD (google_apis, x86_64 or arm64-v8a). "
    "Boot it only after a separate yes."
)
DEVICE_FIX = (
    "No online device. After owner approval, boot a suite-owned AVD headless: "
    "emulator -avd <name> -no-window -no-audio -no-boot-anim -no-snapshot-save; "
    "adb wait-for-device; poll adb shell getprop sys.boot_completed until it prints 1."
)
PLAYWRIGHT_FIX = (
    "Ask before installing Playwright and its browser cache. "
    "The --with-deps OS-package step fails as root or when apt/dnf cannot see the proxy."
)
TC_HINT = (
    "Colima/OrbStack/rootless: set DOCKER_HOST and TESTCONTAINERS_RYUK_DISABLED=true "
    "when the engine is not the default socket"
)


class ReadOnlyViolation(RuntimeError):
    """A probe argv is outside the read-only allowlist."""


def _flat(text: str) -> str:
    return " ".join(text.split())


def _clip(text: str, limit: int = 180) -> str:
    flat = _flat(text)
    if len(flat) <= limit:
        return flat
    return flat[: limit - 3] + "..."


def _row(check_id: str, state: str, evidence: str, fix_next: str = "") -> dict[str, str]:
    return {
        "id": check_id,
        "state": state,
        "evidence": _clip(evidence, 300),
        "fixNext": _flat(fix_next),
    }


def parse_version(text: str) -> tuple[int, int, int] | None:
    match = _VERSION.search(text)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3) or 0)


def _caret(version: tuple[int, int, int], major: int, minor: int, patch: int) -> bool:
    """npm caret for major >= 1: >=X.Y.Z and <(X+1).0.0."""
    return (major, minor, patch) <= version < (major + 1, 0, 0)


def classify_node(text: str) -> str:
    """Return appium4, appium3, or unsupported.

    Appium 4: ^22.22.2 || ^24.15 || >=26. Appium 3: ^20.19 || ^22.12 || >=24.
    A version that satisfies both is appium4.
    """
    version = parse_version(text)
    if version is None:
        return "unsupported"
    if (
        _caret(version, 22, 22, 2)
        or _caret(version, 24, 15, 0)
        or version >= (26, 0, 0)
    ):
        return "appium4"
    if (
        _caret(version, 20, 19, 0)
        or _caret(version, 22, 12, 0)
        or version >= (24, 0, 0)
    ):
        return "appium3"
    return "unsupported"


def parse_http_url(url: str) -> tuple[str, str, str, str] | None:
    match = _HTTP_URL.fullmatch(url.strip())
    if not match:
        return None
    raw_host = match.group(2)
    if raw_host.startswith("[") and raw_host.endswith("]"):
        host = raw_host[1:-1]
    else:
        host = raw_host
    host = host.lower()
    if not host:
        return None
    return match.group(1).lower(), host, match.group(3) or "", match.group(4) or ""


def url_block_reason(url: str, allow_remote: bool) -> str:
    parsed = parse_http_url(url)
    if parsed is None:
        return "status URL must be http(s) with a host"
    host = parsed[1]
    if allow_remote or host in LOOPBACK_HOSTS:
        return ""
    return "refusing non-loopback status URL without --allow-remote-status"


def status_fallback_url(url: str) -> str:
    parsed = parse_http_url(url)
    if parsed is None:
        return url
    scheme, host, port, path = parsed
    if path.rstrip("/") == "/wd/hub/status":
        return url
    shown = f"[{host}]" if ":" in host else host
    port_bit = f":{port}" if port else ""
    return f"{scheme}://{shown}{port_bit}/wd/hub/status"


def _basename(argv0: str) -> str:
    name = os.path.basename(argv0).lower()
    if name.endswith(".exe"):
        name = name[:-4]
    return name


def command_allowed(argv: list[str]) -> bool:
    """True only for version, list, status, and boot-completed probes."""
    if not argv or not argv[0]:
        return False
    name = _basename(argv[0])
    rest = tuple(argv[1:])
    if (name, *rest) in _EXACT:
        return True
    if (
        name == "adb"
        and len(rest) == 5
        and rest[0] == "-s"
        and rest[2:] == ("shell", "getprop", "sys.boot_completed")
        and _SAFE_SERIAL.fullmatch(rest[1])
    ):
        return True
    if name == "appium" and rest == ("driver", "list", "--installed", "--json"):
        return True
    if name == "npx" and rest == ("--no-install", "appium", "driver", "list", "--installed", "--json"):
        return True
    if name == "npx" and rest == ("--no-install", "playwright", "--version"):
        return True
    if name == "android" and rest in {("sdk", "--version"), ("emulator", "list")}:
        return True
    if name == "avdmanager" and rest == ("list", "avd"):
        return True
    if name == "xcrun" and rest == ("simctl", "list", "devices", "available", "-j"):
        return True
    return False


def run_probe(argv: list[str], timeout: float) -> tuple[int, str]:
    if not command_allowed(argv):
        raise ReadOnlyViolation("refused read-only probe: " + " ".join(argv))
    try:
        completed = subprocess.run(  # nosec B603 - allowlisted read-only argv, shell is never used.
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {timeout:g}s"
    except OSError as exc:
        return 127, f"{exc.__class__.__name__}: {exc}"
    output = "\n".join(part for part in (completed.stdout or "", completed.stderr or "") if part)
    return int(completed.returncode), output.strip()


def http_get(url: str, timeout: float = 3.0) -> tuple[int | None, bytes, str]:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310 - loopback unless --allow-remote-status
            status = getattr(response, "status", None)
            if status is None:
                status = getattr(response, "code", 200)
            return int(status), response.read(65536), ""
    except Exception as exc:
        code = getattr(exc, "code", None)
        if isinstance(code, int):
            reader = getattr(exc, "read", None)
            raw = reader(65536) if callable(reader) else b""
            if isinstance(raw, str):
                raw = raw.encode("utf-8", "replace")
            return code, raw or b"", ""
        return None, b"", f"{exc.__class__.__name__}: {exc}"


def parse_json_bytes(body: bytes) -> object | None:
    if not body:
        return None
    try:
        return json.loads(body.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        return None


def parse_embedded_json(text: str) -> object | None:
    """Parse the first JSON value. Trailing warnings must not fail the probe."""
    starts = [index for index in (text.find("{"), text.find("[")) if index >= 0]
    if not starts:
        return None
    try:
        payload, _end = json.JSONDecoder().raw_decode(text[min(starts):])
    except json.JSONDecodeError:
        return None
    return payload


def norm_path(value: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.expanduser(value.strip())))


def sdk_root_choice() -> tuple[str, str, str, bool]:
    """Return ANDROID_HOME, ANDROID_SDK_ROOT, the chosen root, and mismatch."""
    home = os.environ.get("ANDROID_HOME", "").strip()
    root = os.environ.get("ANDROID_SDK_ROOT", "").strip()
    mismatch = bool(home and root and norm_path(home) != norm_path(root))
    chosen = "" if mismatch else (home or root)
    return home, root, chosen, mismatch


def sdk_bin_dirs(sdk_root: str) -> list[Path]:
    root = Path(sdk_root)
    return [
        root / "platform-tools",
        root / "emulator",
        root / "cmdline-tools" / "latest" / "bin",
        root / "cmdline-tools" / "bin",
        root / "tools" / "bin",
        root / "tools",
    ]


def which(name: str, sdk_root: str = "") -> str | None:
    found = shutil.which(name)
    if found:
        return found
    if not sdk_root:
        return None
    for directory in sdk_bin_dirs(sdk_root):
        for candidate in (directory / name, directory / f"{name}.exe"):
            if candidate.is_file():
                return str(candidate)
    return None


def check_version_tool(check_id: str, names: tuple[str, ...], args: tuple[str, ...], fix: str) -> dict[str, str]:
    last = ""
    seen = False
    for name in names:
        path = which(name)
        if not path:
            continue
        seen = True
        code, output = run_probe([path, *args], timeout=8)
        if code == 0 and output.strip():
            return _row(check_id, "ready", _clip(output, 160), "")
        last = f"{name} exited {code}: {_clip(output)}"
    if not seen:
        return _row(check_id, "absent", f"{' or '.join(names)} not on PATH", fix)
    return _row(check_id, "unready", last or "version probe failed", fix)


def check_python() -> dict[str, str]:
    return check_version_tool("python", ("python3", "python"), ("--version",), "Ask before installing Python 3.11 or newer.")


def check_java() -> dict[str, str]:
    return check_version_tool("java", ("java",), ("-version",), "Ask before installing a JDK on PATH.")


def check_mvn() -> dict[str, str]:
    return check_version_tool("mvn", ("mvn",), ("--version",), "Ask before installing Maven.")


def check_node() -> dict[str, str]:
    path = which("node")
    if not path:
        return _row("node", "absent", "node not on PATH", NODE_FIX)
    code, output = run_probe([path, "--version"], timeout=8)
    if code != 0:
        return _row("node", "unready", f"node --version exited {code}: {_clip(output)}", NODE_FIX)
    version = parse_version(output)
    kind = classify_node(output)
    shown = f"v{version[0]}.{version[1]}.{version[2]}" if version else _clip(output, 40)
    evidence = f"{shown} class={kind}"
    if kind == "unsupported":
        return _row("node", "unready", evidence, NODE_FIX)
    return _row("node", "ready", evidence, "")


def node_kind(check: dict[str, str]) -> str:
    if "class=appium4" in check["evidence"]:
        return "appium4"
    if "class=appium3" in check["evidence"]:
        return "appium3"
    return "unsupported"


def appium_fix(kind: str) -> str:
    if kind == "appium4":
        package = "appium@4"
    elif kind == "appium3":
        package = "appium@3"
    else:
        package = (
            "appium@4 (Node must meet ^22.22.2 || ^24.15 || >=26) or "
            "appium@3 (Node must meet ^20.19 || ^22.12 || >=24)"
        )
    return f"Ask before installing {package}. Keep the server base path at /."


def check_docker() -> dict[str, str]:
    path = which("docker")
    if not path:
        return _row("docker", "absent", "docker not on PATH", DOCKER_FIX)
    code, output = run_probe([path, "info"], timeout=3)
    if code == 124:
        return _row("docker", "unready", "docker info timeout after 3s", DOCKER_FIX)
    context, rootless = parse_docker_info(output)
    evidence = f"context={context} rootless={str(rootless).lower()}"
    if code != 0:
        return _row("docker", "unready", f"exit {code} {evidence} {_clip(output)}", DOCKER_FIX)
    return _row("docker", "ready", evidence, "")


def parse_docker_info(output: str) -> tuple[str, bool]:
    context = "unknown"
    rootless = "rootless" in output.casefold()
    host = os.environ.get("DOCKER_HOST", "")
    if "rootless" in host.casefold():
        rootless = True
    for line in output.splitlines():
        if "Context:" in line:
            parsed = line.split("Context:", 1)[1].strip()
            if parsed:
                context = parsed.split()[0]
            break
    return context, rootless


def testcontainers_hint(context: str, rootless: bool) -> str:
    host = os.environ.get("DOCKER_HOST", "")
    blob = f"{context} {host}".casefold()
    detected: list[str] = []
    if "colima" in blob:
        detected.append("Colima")
    if "orbstack" in blob:
        detected.append("OrbStack")
    if rootless or "rootless" in blob:
        detected.append("rootless")
    prefix = f"detected {'/'.join(detected)}; " if detected else ""
    return prefix + TC_HINT


def check_testcontainers(docker: dict[str, str]) -> dict[str, str]:
    context = "unknown"
    rootless = False
    match = _CONTEXT.search(docker["evidence"])
    if match:
        context = match.group(1)
    rootless_match = _ROOTLESS.search(docker["evidence"])
    if rootless_match:
        rootless = rootless_match.group(1) == "true"
    hint = testcontainers_hint(context, rootless)
    if docker["state"] == "ready":
        return _row("testcontainers", "ready", f"context={context}; {hint}", "")
    if docker["state"] == "absent":
        return _row("testcontainers", "absent", f"docker absent; {hint}", DOCKER_FIX)
    return _row("testcontainers", "unready", f"docker {docker['state']}; context={context}; {hint}", DOCKER_FIX)


def check_grid(url: str) -> dict[str, str]:
    status, body, err = http_get(url)
    used = url
    if status == 404:
        fallback = status_fallback_url(url)
        if fallback != url:
            status, body, err = http_get(fallback)
            used = fallback
    if status is None:
        return _row("grid", "absent", f"no response from {used}: {_clip(err)}", GRID_FIX)
    payload = parse_json_bytes(body)
    value = payload.get("value") if isinstance(payload, dict) else None
    ready = isinstance(value, dict) and value.get("ready") is True
    if ready:
        return _row("grid", "ready", f"value.ready=true via {used}", "")
    return _row("grid", "unready", f"HTTP {status} from {used} value.ready is not true", GRID_FIX)


def check_appium(url: str, kind: str) -> dict[str, str]:
    fix = appium_fix(kind)
    status, body, err = http_get(url)
    if status is None:
        return _row("appium", "absent", f"no response from {url}: {_clip(err)}", fix)
    payload = parse_json_bytes(body)
    value = payload.get("value") if isinstance(payload, dict) else None
    version = ""
    ready_flag = None
    if isinstance(value, dict):
        ready_flag = value.get("ready")
        build = value.get("build")
        if isinstance(build, dict) and build.get("version"):
            version = str(build["version"])
    if status == 200 and version and ready_flag is not False:
        return _row("appium", "ready", f"version={version}", "")
    return _row("appium", "unready", f"HTTP {status} from {url} version={version or 'missing'}", fix)


def driver_count(payload: object) -> int:
    if isinstance(payload, list):
        return len(payload)
    if not isinstance(payload, dict):
        return 0
    total = 0
    for key, value in payload.items():
        if str(key).startswith("$"):
            continue
        if isinstance(value, dict):
            if value.get("installed") is False:
                continue
            total += 1
        elif isinstance(value, list):
            total += len(value)
    return total


def check_appium_drivers() -> dict[str, str]:
    appium = which("appium")
    npx = which("npx")
    if appium:
        argv = [appium, "driver", "list", "--installed", "--json"]
    elif npx:
        argv = [npx, "--no-install", "appium", "driver", "list", "--installed", "--json"]
    else:
        return _row("appium-drivers", "absent", "appium and npx not on PATH", DRIVER_FIX)
    code, output = run_probe(argv, timeout=15)
    if _NULL_PACKAGE.search(output):
        return _row("appium-drivers", "unready", f"null-package: {_clip(output)}", NULL_FIX)
    payload = parse_embedded_json(output)
    if code == 0 and payload is not None:
        count = driver_count(payload)
        if count >= 1:
            return _row("appium-drivers", "ready", f"installed={count}", "")
        return _row("appium-drivers", "absent", "driver list empty", DRIVER_FIX)
    return _row("appium-drivers", "unready", f"exit {code}: {_clip(output)}", DRIVER_FIX)


def check_android_sdk() -> dict[str, str]:
    home, root, chosen, mismatch = sdk_root_choice()
    if mismatch:
        return _row(
            "android-sdk",
            "unready",
            f"ANDROID_HOME={home} ANDROID_SDK_ROOT={root} differ",
            "Set ANDROID_HOME and ANDROID_SDK_ROOT to the same SDK root.",
        )
    adb = which("adb", chosen)
    emulator = which("emulator", chosen)
    android = which("android", chosen)
    sdkmanager = which("sdkmanager", chosen)
    avdmanager = which("avdmanager", chosen)
    styles: list[str] = []
    if android:
        code, output = run_probe([android, "sdk", "--version"], timeout=10)
        if code == 0 and output.strip():
            styles.append("modern")
        else:
            code, output = run_probe([android, "emulator", "list"], timeout=10)
            if code == 0:
                styles.append("modern")
    if sdkmanager:
        code, output = run_probe([sdkmanager, "--version"], timeout=10)
        if code == 0 and output.strip():
            styles.append("legacy")
    elif avdmanager:
        code, _output = run_probe([avdmanager, "list", "avd"], timeout=10)
        if code == 0:
            styles.append("legacy")
    adb_ok = False
    emu_ok = False
    if adb:
        code, output = run_probe([adb, "version"], timeout=8)
        adb_ok = code == 0 and bool(output.strip())
    if emulator:
        code, output = run_probe([emulator, "-version"], timeout=8)
        emu_ok = code == 0 and bool(output.strip())
    evidence = f"sdk={chosen or 'unset'} adb={adb_ok} emulator={emu_ok} style={','.join(styles) or 'none'}"
    present = any((chosen, adb, emulator, android, sdkmanager, avdmanager))
    if adb_ok and emu_ok and styles:
        return _row("android-sdk", "ready", evidence, "")
    if present:
        return _row("android-sdk", "unready", evidence, SDK_FIX)
    return _row("android-sdk", "absent", evidence, SDK_FIX)


def accel_note() -> str:
    system = platform.system()
    if system == "Linux":
        kvm = "present" if os.path.exists("/dev/kvm") else "missing"
        return f"/dev/kvm={kvm}"
    if system == "Darwin":
        return "accel=HVF"
    if system == "Windows":
        return "accel=WHPX"
    return ""


def check_android_accel() -> dict[str, str]:
    _home, _root, chosen, _mismatch = sdk_root_choice()
    emulator = which("emulator", chosen)
    if not emulator:
        return _row("android-accel", "absent", "emulator not on PATH", ACCEL_FIX)
    code, output = run_probe([emulator, "-accel-check"], timeout=8)
    note = accel_note()
    if code == 0:
        return _row("android-accel", "ready", f"exit 0 {_clip(output)} {note}", "")
    return _row("android-accel", "unready", f"exit {code} {_clip(output)} {note}", ACCEL_FIX)


def avd_names(text: str) -> list[str]:
    names: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        lower = line.casefold()
        if lower.startswith(("list of", "available ", "error", "usage", "warning", "info:", "the following", "parsing")):
            continue
        if lower.startswith("name:"):
            name = line.split(":", 1)[1].strip()
            if name:
                names.append(name)
            continue
        if " " not in line and not line.startswith("-") and not line.endswith(":"):
            names.append(line)
    return names


def check_android_avd() -> dict[str, str]:
    _home, _root, chosen, _mismatch = sdk_root_choice()
    android = which("android", chosen)
    emulator = which("emulator", chosen)
    if android:
        code, output = run_probe([android, "emulator", "list"], timeout=10)
        if code == 0:
            names = avd_names(output)
            if names:
                return _row("android-avd", "ready", f"avds={len(names)} via android emulator list", "")
    if emulator:
        code, output = run_probe([emulator, "-list-avds"], timeout=10)
        if code != 0:
            return _row("android-avd", "unready", f"emulator -list-avds exited {code}: {_clip(output)}", AVD_FIX)
        names = avd_names(output)
        if names:
            return _row("android-avd", "ready", f"avds={len(names)} via emulator -list-avds", "")
        return _row("android-avd", "absent", "emulator -list-avds returned no AVD", AVD_FIX)
    if android:
        return _row("android-avd", "unready", "android emulator list returned no AVD", AVD_FIX)
    return _row("android-avd", "absent", "android and emulator not on PATH", AVD_FIX)


def online_serials(text: str) -> list[str]:
    found: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.lower().startswith("list of devices"):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device" and _SAFE_SERIAL.fullmatch(parts[0]):
            found.append(parts[0])
    return found


def check_android_device() -> dict[str, str]:
    _home, _root, chosen, _mismatch = sdk_root_choice()
    adb = which("adb", chosen)
    if not adb:
        return _row("android-device", "absent", "adb not on PATH", DEVICE_FIX)
    code, output = run_probe([adb, "devices"], timeout=8)
    if code != 0:
        return _row("android-device", "unready", f"adb devices exited {code}: {_clip(output)}", DEVICE_FIX)
    serials = online_serials(output)
    if not serials:
        return _row("android-device", "absent", "adb devices has no online device", DEVICE_FIX)
    booted: list[str] = []
    pending: list[str] = []
    for serial in serials[:5]:
        probe_code, probe_out = run_probe(
            [adb, "-s", serial, "shell", "getprop", "sys.boot_completed"],
            timeout=8,
        )
        if probe_code == 0 and probe_out.strip() == "1":
            booted.append(serial)
        else:
            pending.append(serial)
    if booted:
        return _row("android-device", "ready", f"boot_completed=1 serials={','.join(booted)}", "")
    return _row(
        "android-device",
        "unready",
        f"online but boot incomplete: {','.join(pending)}",
        DEVICE_FIX,
    )


def sim_device_count(payload: object) -> int:
    if not isinstance(payload, dict):
        return 0
    devices = payload.get("devices")
    if not isinstance(devices, dict):
        return 0
    total = 0
    for entries in devices.values():
        if isinstance(entries, list):
            total += len(entries)
    return total


def check_ios_sim() -> dict[str, str]:
    if platform.system() != "Darwin":
        return _row("ios-sim", "skipped", "ios-sim is checked on Darwin only", "")
    xcode = which("xcode-select")
    xcrun = which("xcrun")
    if not xcode or not xcrun:
        return _row("ios-sim", "absent", "xcode-select or xcrun not on PATH", "Install full Xcode after owner approval.")
    code, output = run_probe([xcode, "-p"], timeout=8)
    if code != 0 or not output.strip():
        return _row("ios-sim", "absent", f"xcode-select -p exited {code}: {_clip(output)}", "Select a full Xcode after owner approval.")
    developer = _clip(output, 120)
    sim_code, sim_out = run_probe([xcrun, "simctl", "list", "devices", "available", "-j"], timeout=15)
    if sim_code != 0:
        return _row("ios-sim", "unready", f"xcode={developer} simctl exited {sim_code}", "Ask before booting a simulator.")
    count = sim_device_count(parse_embedded_json(sim_out))
    if count >= 1:
        return _row("ios-sim", "ready", f"xcode={developer} devices={count}", "")
    return _row("ios-sim", "absent", f"xcode={developer} devices=0", "Ask before creating a simulator.")


def playwright_cache_dir() -> Path:
    override = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()
    if override and override != "0":
        return Path(override)
    system = platform.system()
    home = Path.home()
    if system == "Darwin":
        return home / "Library" / "Caches" / "ms-playwright"
    if system == "Windows":
        local = os.environ.get("LOCALAPPDATA", "").strip()
        base = Path(local) if local else home / "AppData" / "Local"
        return base / "ms-playwright"
    return home / ".cache" / "ms-playwright"


def cache_nonempty(path: Path) -> bool:
    if not path.is_dir():
        return False
    for _child in path.iterdir():
        return True
    return False


def check_playwright() -> dict[str, str]:
    npx = which("npx")
    if not npx:
        return _row("playwright", "absent", "npx not on PATH", PLAYWRIGHT_FIX)
    code, output = run_probe([npx, "--no-install", "playwright", "--version"], timeout=15)
    if code != 0:
        return _row("playwright", "absent", f"playwright CLI missing: {_clip(output)}", PLAYWRIGHT_FIX)
    cache = playwright_cache_dir()
    if cache_nonempty(cache):
        return _row("playwright", "ready", f"version={_clip(output, 80)} cache={cache}", "")
    return _row("playwright", "unready", f"version={_clip(output, 80)} cache empty at {cache}", PLAYWRIGHT_FIX)


def collect_checks(grid_url: str, appium_url: str) -> list[dict[str, str]]:
    node = check_node()
    kind = node_kind(node)
    docker = check_docker()
    return [
        check_python(),
        node,
        check_java(),
        check_mvn(),
        docker,
        check_grid(grid_url),
        check_appium(appium_url, kind),
        check_appium_drivers(),
        check_android_sdk(),
        check_android_accel(),
        check_android_avd(),
        check_android_device(),
        check_ios_sim(),
        check_playwright(),
        check_testcontainers(docker),
    ]


def build_report(grid_url: str, appium_url: str, profile: str | None) -> dict[str, object]:
    report: dict[str, object] = {
        "schemaVersion": SCHEMA_VERSION,
        "mode": "strict" if profile else "report",
        "platform": platform.system(),
    }
    if profile:
        report["profile"] = profile
    report["checks"] = collect_checks(grid_url, appium_url)
    return report


def render_text(report: dict[str, object]) -> str:
    header = f"schemaVersion={report['schemaVersion']} mode={report['mode']} platform={report['platform']}"
    if "profile" in report:
        header += f" profile={report['profile']}"
    lines = [header, f"{'id':<18} {'state':<10} evidence"]
    checks = report["checks"]
    if isinstance(checks, list):
        for check in checks:
            lines.append(f"{check['id']:<18} {check['state']:<10} {check['evidence']}")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="test_env_doctor", description="Read-only test environment doctor.")
    parser.add_argument("--json", action="store_true", help="Write JSON to stdout (default).")
    parser.add_argument("--text", action="store_true", help="Write a concise table to stdout.")
    parser.add_argument(
        "--strict",
        metavar="PROFILE",
        choices=tuple(PROFILES),
        help="Exit 1 when a required check is absent or unready.",
    )
    parser.add_argument("--grid-url", default=DEFAULT_GRID_URL)
    parser.add_argument("--appium-url", default=DEFAULT_APPIUM_URL)
    parser.add_argument(
        "--allow-remote-status",
        action="store_true",
        help="Permit a non-loopback status URL.",
    )
    return parser


def exit_code(report: dict[str, object], profile: str | None) -> int:
    if not profile:
        return 0
    required = set(PROFILES[profile])
    checks = report["checks"]
    if not isinstance(checks, list):
        return 1
    for check in checks:
        if check["id"] in required and check["state"] in _FAIL_STATES:
            return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        return code if isinstance(code, int) else 2
    if args.json and args.text:
        print("error: choose either --json or --text", file=sys.stderr)
        return 2
    for label, url in (("grid", args.grid_url), ("appium", args.appium_url)):
        reason = url_block_reason(url, args.allow_remote_status)
        if reason:
            print(f"error: {label} URL: {reason}", file=sys.stderr)
            return 2
    report = build_report(args.grid_url, args.appium_url, args.strict)
    if args.text:
        sys.stdout.write(render_text(report))
    else:
        json.dump(report, sys.stdout, indent=2)
        sys.stdout.write("\n")
    return exit_code(report, args.strict)


if __name__ == "__main__":
    sys.exit(main())
