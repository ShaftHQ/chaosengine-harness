"""Read-only test_env_doctor plus the test-env-setup and mobile-testing skills."""

from __future__ import annotations

import ast
import io
import json
import os
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))  # noqa: E402 - self-locating under python3 -I
from scripts.ci import test_env_doctor as mod  # noqa: E402


ROOT = Path(__file__).resolve().parents[2]
BANNED_TOKENS = ("ShaftHQ", "SHAFT_ENGINE")
SKILL_DIRS = (
    ROOT / "skills" / "test-env-setup",
    ROOT / "skills" / "mobile-testing",
)


class _Proc:
    def __init__(self, stdout: str = "", stderr: str = "", code: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = code


class _Body:
    def __init__(self, payload: bytes, status: int = 200) -> None:
        self._payload = payload
        self.status = status
        self.code = status

    def read(self, _limit: int = 65536) -> bytes:
        return self._payload

    def __enter__(self) -> "_Body":
        return self

    def __exit__(self, *_args: object) -> bool:
        return False


def _json_body(payload: dict) -> _Body:
    return _Body(json.dumps(payload).encode())


def _frontmatter_description(text: str) -> str:
    match_end = text.find("\n---\n", 4)
    block = text[4:match_end] if text.startswith("---\n") and match_end > 0 else ""
    for line in block.splitlines():
        if line.startswith("description:"):
            return " ".join(line.split(":", 1)[1].strip().strip("'\"").split())
    return ""


def _ready_runner(argv: list[str], **_kwargs: object) -> _Proc:
    name = os.path.basename(argv[0]).lower()
    if name.endswith(".exe"):
        name = name[:-4]
    rest = tuple(argv[1:])
    if name == "node" and rest == ("--version",):
        return _Proc("v22.22.2")
    if name == "java" and rest == ("-version",):
        return _Proc("", 'openjdk version "21.0.1"')
    if name == "python3" and rest == ("--version",):
        return _Proc("Python 3.12.3")
    if name == "mvn" and rest == ("--version",):
        return _Proc("Apache Maven 3.9.9")
    if name == "docker" and rest == ("info",):
        return _Proc("Client:\n Context:    default\nServer:\n")
    if name == "adb" and rest == ("version",):
        return _Proc("Android Debug Bridge version 1.0.41")
    if name == "adb" and rest == ("devices",):
        return _Proc("List of devices attached\nemulator-5554\tdevice\n")
    if name == "adb" and rest[-3:] == ("shell", "getprop", "sys.boot_completed"):
        return _Proc("1")
    if name == "emulator" and rest == ("-version",):
        return _Proc("Android emulator version 35.2.0")
    if name == "emulator" and rest == ("-accel-check",):
        return _Proc("accel 0")
    if name == "emulator" and rest == ("-list-avds",):
        return _Proc("Pixel_7")
    if name == "sdkmanager" and rest == ("--version",):
        return _Proc("12.0")
    if name == "android" and rest == ("sdk", "--version"):
        return _Proc("android-sdk 1")
    if name == "android" and rest == ("emulator", "list"):
        return _Proc("Pixel_7")
    if name == "appium" and rest == ("driver", "list", "--installed", "--json"):
        return _Proc('{"uiautomator2": {"installed": true, "version": "4.0.0"}}')
    if name == "npx" and rest == ("--no-install", "playwright", "--version"):
        return _Proc("Version 1.49.1")
    if name == "npx" and rest == ("--no-install", "appium", "driver", "list", "--installed", "--json"):
        return _Proc('{"xcuitest": {"installed": true, "version": "7.0.0"}}')
    if name == "xcode-select" and rest == ("-p",):
        return _Proc("/Applications/Xcode.app/Contents/Developer")
    if name == "xcrun" and rest == ("simctl", "list", "devices", "available", "-j"):
        return _Proc('{"devices":{"runtime":[{"name":"iPhone 16","isAvailable":true}]}}')
    return _Proc("unexpected " + " ".join(argv), code=1)


def _statuses(argv: list[str], **kwargs: object):
    calls: list[list[str]] = []

    def runner(command: list[str], **run_kwargs: object) -> _Proc:
        calls.append(list(command))
        return _ready_runner(command, **run_kwargs)

    def urlopen(request: object, timeout: float = 3) -> _Body:
        url = getattr(request, "full_url", "")
        if ":4723" in url:
            return _json_body({"value": {"ready": True, "build": {"version": "2.11.5"}}})
        return _json_body({"value": {"ready": True, "message": "Selenium Grid ready."}})

    code, out, err = _invoke(argv, runner=runner, urlopen=urlopen, **kwargs)
    return code, out, err, calls


def _invoke(
    argv: list[str],
    *,
    system: str = "Linux",
    env: dict[str, str] | None = None,
    which_map: dict[str, str | None] | None = None,
    which_fn=None,
    runner=None,
    urlopen=None,
):
    env = {} if env is None else env

    def default_which(name: str) -> str | None:
        if which_map is None:
            return None
        return which_map.get(name)

    def default_runner(command: list[str], **_kwargs: object) -> _Proc:
        raise AssertionError("unexpected subprocess " + " ".join(command))

    def default_urlopen(request: object, timeout: float = 3) -> _Body:
        raise urllib.error.URLError("connection refused")

    stdout = io.StringIO()
    stderr = io.StringIO()
    with patch.dict(os.environ, env, clear=True), \
         patch.object(mod.shutil, "which", side_effect=which_fn or default_which), \
         patch.object(mod.platform, "system", return_value=system), \
         patch.object(mod.subprocess, "run", side_effect=runner or default_runner), \
         patch.object(mod.urllib.request, "urlopen", side_effect=urlopen or default_urlopen), \
         redirect_stdout(stdout), redirect_stderr(stderr):
        code = mod.main(argv)
    return code, stdout.getvalue(), stderr.getvalue()


def _check_map(payload: dict) -> dict[str, dict]:
    return {item["id"]: item for item in payload["checks"]}


class EnvDoctorTest(unittest.TestCase):
    def test_report_exits_0_when_all_tools_absent(self) -> None:
        calls: list[list[str]] = []

        def runner(command: list[str], **_kwargs: object) -> _Proc:
            calls.append(list(command))
            return _Proc("should-not-run", code=1)

        code, out, err = _invoke([], runner=runner)
        self.assertEqual(0, code, err)
        self.assertEqual("", err)
        self.assertEqual([], calls)
        payload = json.loads(out)
        self.assertEqual(["schemaVersion", "mode", "platform", "checks"], list(payload))
        self.assertEqual(1, payload["schemaVersion"])
        self.assertEqual("report", payload["mode"])
        self.assertEqual("Linux", payload["platform"])
        self.assertEqual(list(mod.CHECK_IDS), [item["id"] for item in payload["checks"]])
        for item in payload["checks"]:
            self.assertEqual(["id", "state", "evidence", "fixNext"], list(item))
            self.assertIn(item["state"], {"ready", "absent", "unready", "skipped"})
            expected = "skipped" if item["id"] == "ios-sim" else "absent"
            self.assertEqual(expected, item["state"], item["id"])
        states = _check_map(payload)
        self.assertIn("4.54.0-20261123", states["grid"]["fixNext"])
        self.assertIn("shm_size: 2gb", states["grid"]["fixNext"])
        self.assertIn("node-chromium", states["grid"]["fixNext"])
        self.assertIn("node-firefox", states["grid"]["fixNext"])
        self.assertIn("appium@4", states["appium"]["fixNext"])
        self.assertIn("appium@3", states["appium"]["fixNext"])
        text_code, text_out, _text_err = _invoke(["--text"], runner=runner)
        self.assertEqual(0, text_code)
        self.assertFalse(text_out.lstrip().startswith("{"))
        self.assertIn("ios-sim", text_out)
        self.assertIn("skipped", text_out)
        json_code, json_out, _json_err = _invoke(["--json"], runner=runner)
        self.assertEqual(0, json_code)
        self.assertEqual(1, json.loads(json_out)["schemaVersion"])

    def test_node_appium_class_boundaries(self) -> None:
        cases = {
            "20.19.0": ("appium3", "ready"),
            "22.22.2": ("appium4", "ready"),
            "18.0.0": ("unsupported", "unready"),
            "20.18.9": ("unsupported", "unready"),
            "22.12.0": ("appium3", "ready"),
            "22.22.1": ("appium3", "ready"),
            "24.0.0": ("appium3", "ready"),
            "24.15.0": ("appium4", "ready"),
            "25.0.0": ("appium3", "ready"),
            "26.0.0": ("appium4", "ready"),
            "21.0.0": ("unsupported", "unready"),
            "23.1.0": ("unsupported", "unready"),
        }
        for version, (kind, _state) in cases.items():
            with self.subTest(version=version):
                self.assertEqual(kind, mod.classify_node(version))
                self.assertEqual(kind, mod.classify_node(f"v{version}"))
        for version in ("20.19.0", "22.22.2", "18.0.0"):
            kind, state = cases[version]

            def runner(command: list[str], **_kwargs: object) -> _Proc:
                self.assertEqual(["--version"], command[1:])
                self.assertEqual("node", os.path.basename(command[0]))
                return _Proc(f"v{version}")

            code, out, err = _invoke(
                [],
                which_map={"node": "/usr/bin/node"},
                runner=runner,
            )
            self.assertEqual(0, code, err)
            node = _check_map(json.loads(out))["node"]
            self.assertEqual(state, node["state"], version)
            self.assertEqual(f"v{version} class={kind}", node["evidence"])

    def test_android_home_mismatch_is_unready(self) -> None:
        sdk_calls: list[list[str]] = []

        def runner(command: list[str], **_kwargs: object) -> _Proc:
            sdk_calls.append(list(command))
            return _ready_runner(command)

        code, out, err = _invoke(
            [],
            env={"ANDROID_HOME": "/opt/sdk-a", "ANDROID_SDK_ROOT": "/opt/sdk-b"},
            which_map={"adb": "/usr/bin/adb", "emulator": "/usr/bin/emulator", "sdkmanager": "/usr/bin/sdkmanager"},
            runner=runner,
        )
        self.assertEqual(0, code, err)
        sdk = _check_map(json.loads(out))["android-sdk"]
        self.assertEqual("unready", sdk["state"])
        self.assertIn("/opt/sdk-a", sdk["evidence"])
        self.assertIn("/opt/sdk-b", sdk["evidence"])
        self.assertIn("differ", sdk["evidence"])
        self.assertFalse(any(os.path.basename(item[0]) == "sdkmanager" for item in sdk_calls))

        code, out, _err = _invoke(
            [],
            env={"ANDROID_HOME": "/opt/sdk", "ANDROID_SDK_ROOT": "/opt/sdk/"},
            runner=runner,
        )
        sdk = _check_map(json.loads(out))["android-sdk"]
        self.assertEqual("unready", sdk["state"])
        self.assertNotIn("differ", sdk["evidence"])

        def legacy(command: list[str], **_kwargs: object) -> _Proc:
            return _ready_runner(command)

        code, out, err = _invoke(
            [],
            env={"ANDROID_HOME": "/opt/sdk", "ANDROID_SDK_ROOT": "/opt/sdk"},
            which_map={
                "adb": "/usr/bin/adb",
                "emulator": "/usr/bin/emulator",
                "sdkmanager": "/usr/bin/sdkmanager",
            },
            runner=legacy,
        )
        self.assertEqual(0, code, err)
        sdk = _check_map(json.loads(out))["android-sdk"]
        self.assertEqual("ready", sdk["state"])
        self.assertIn("style=legacy", sdk["evidence"])

        code, out, err = _invoke(
            [],
            which_map={"adb": "/usr/bin/adb", "emulator": "/usr/bin/emulator", "android": "/usr/bin/android"},
            runner=legacy,
        )
        self.assertEqual(0, code, err)
        sdk = _check_map(json.loads(out))["android-sdk"]
        self.assertEqual("ready", sdk["state"])
        self.assertIn("style=modern", sdk["evidence"])

    def test_grid_status_ready_fallback_and_remote_refusal(self) -> None:
        seen: list[str] = []

        def ready(request: object, timeout: float = 3) -> _Body:
            seen.append(getattr(request, "full_url", ""))
            return _json_body({"value": {"ready": True}})

        code, out, err = _invoke([], urlopen=ready)
        self.assertEqual(0, code, err)
        self.assertEqual(["http://127.0.0.1:4444/status"], [url for url in seen if ":4444" in url])
        grid = _check_map(json.loads(out))["grid"]
        self.assertEqual("ready", grid["state"])
        self.assertIn("value.ready=true via http://127.0.0.1:4444/status", grid["evidence"])

        seen.clear()

        def fallback(request: object, timeout: float = 3) -> _Body:
            url = getattr(request, "full_url", "")
            seen.append(url)
            if url.endswith("/wd/hub/status"):
                return _json_body({"value": {"ready": True}})
            raise urllib.error.HTTPError(url, 404, "missing", None, io.BytesIO(b""))

        code, out, err = _invoke([], urlopen=fallback)
        self.assertEqual(0, code, err)
        self.assertEqual(
            ["http://127.0.0.1:4444/status", "http://127.0.0.1:4444/wd/hub/status"],
            [url for url in seen if ":4444" in url],
        )
        grid = _check_map(json.loads(out))["grid"]
        self.assertEqual("ready", grid["state"])
        self.assertIn("/wd/hub/status", grid["evidence"])

        def boom(request: object, timeout: float = 3) -> _Body:
            raise AssertionError("remote status must not be fetched")

        code, out, err = _invoke(["--grid-url", "http://10.1.2.3:4444/status"], urlopen=boom)
        self.assertEqual(2, code)
        self.assertEqual("", out)
        self.assertIn("non-loopback", err)
        code, out, err = _invoke(["--appium-url", "http://example.com/status"], urlopen=boom)
        self.assertEqual(2, code)
        self.assertIn("non-loopback", err)
        code, _out, err = _invoke(["--grid-url", "ftp://127.0.0.1/status"], urlopen=boom)
        self.assertEqual(2, code)
        self.assertIn("http(s)", err)

        seen.clear()

        def remote(request: object, timeout: float = 3) -> _Body:
            seen.append(getattr(request, "full_url", ""))
            return _json_body({"value": {"ready": True, "build": {"version": "2.0.0"}}})

        code, out, err = _invoke(
            ["--allow-remote-status", "--grid-url", "http://10.1.2.3:4444/status"],
            urlopen=remote,
        )
        self.assertEqual(0, code, err)
        self.assertIn("http://10.1.2.3:4444/status", seen)
        self.assertEqual("ready", _check_map(json.loads(out))["grid"]["state"])
        self.assertEqual("", mod.url_block_reason("http://[::1]:4723/status", False))
        self.assertEqual("", mod.url_block_reason("http://localhost/status", False))
        self.assertEqual(
            "http://[::1]:4444/wd/hub/status",
            mod.status_fallback_url("http://[::1]:4444/status"),
        )

    def test_ios_sim_skipped_off_darwin_and_ready_on_darwin(self) -> None:
        def runner(command: list[str], **_kwargs: object) -> _Proc:
            raise AssertionError("ios probe on non-Darwin: " + " ".join(command))

        for system in ("Linux", "Windows"):
            with self.subTest(system=system):
                code, out, err = _invoke([], system=system, runner=runner)
                self.assertEqual(0, code, err)
                ios = _check_map(json.loads(out))["ios-sim"]
                self.assertEqual("skipped", ios["state"])
                self.assertEqual(system, json.loads(out)["platform"])

        def darwin_runner(command: list[str], **_kwargs: object) -> _Proc:
            return _ready_runner(command)

        code, out, err = _invoke(
            [],
            system="Darwin",
            which_map={"xcode-select": "/usr/bin/xcode-select", "xcrun": "/usr/bin/xcrun"},
            runner=darwin_runner,
        )
        self.assertEqual(0, code, err)
        ios = _check_map(json.loads(out))["ios-sim"]
        self.assertEqual("ready", ios["state"])
        self.assertIn("devices=1", ios["evidence"])

        def empty_sim(command: list[str], **_kwargs: object) -> _Proc:
            if os.path.basename(command[0]) == "xcrun":
                return _Proc('{"devices":{}}')
            return _ready_runner(command)

        _code, out, _err = _invoke(
            [],
            system="Darwin",
            which_map={"xcode-select": "/usr/bin/xcode-select", "xcrun": "/usr/bin/xcrun"},
            runner=empty_sim,
        )
        self.assertEqual("absent", _check_map(json.loads(out))["ios-sim"]["state"])

    def test_strict_profiles_and_bad_args(self) -> None:
        code, out, _err = _invoke(["--strict", "web"])
        self.assertEqual(1, code)
        payload = json.loads(out)
        self.assertEqual("strict", payload["mode"])
        self.assertEqual("web", payload["profile"])
        code, _out, _err = _invoke(["--strict", "mobile-android"])
        self.assertEqual(1, code)
        code, _out, _err = _invoke(["--strict", "all"])
        self.assertEqual(1, code)

        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "ms-playwright"
            cache.mkdir()
            (cache / "chromium").mkdir()
            env = {"PLAYWRIGHT_BROWSERS_PATH": str(cache)}
            which_map = {"node": "/usr/bin/node", "npx": "/usr/bin/npx"}
            code, out, err = _invoke(["--strict", "web"], env=env, which_map=which_map, runner=_ready_runner)
            self.assertEqual(0, code, err)
            states = _check_map(json.loads(out))
            self.assertEqual("ready", states["node"]["state"])
            self.assertEqual("ready", states["playwright"]["state"])
            self.assertEqual("absent", states["java"]["state"])

            code, out, err, _calls = _statuses(
                ["--strict", "mobile-android"],
                env={"ANDROID_HOME": "/opt/android-sdk", "ANDROID_SDK_ROOT": "/opt/android-sdk"},
                which_fn=lambda name: f"/usr/bin/{name}",
            )
            self.assertEqual(0, code, err)
            states = _check_map(json.loads(out))
            for check_id in mod.PROFILES["mobile-android"]:
                self.assertEqual("ready", states[check_id]["state"], check_id)

            def unbooted(command: list[str], **_kwargs: object) -> _Proc:
                if tuple(command[1:])[-3:] == ("shell", "getprop", "sys.boot_completed"):
                    return _Proc("0")
                return _ready_runner(command)

            code, out, err = _invoke(
                ["--strict", "mobile-android"],
                env={"ANDROID_HOME": "/opt/android-sdk"},
                which_map={
                    "node": "/usr/bin/node",
                    "java": "/usr/bin/java",
                    "adb": "/usr/bin/adb",
                    "emulator": "/usr/bin/emulator",
                    "sdkmanager": "/usr/bin/sdkmanager",
                    "appium": "/usr/bin/appium",
                },
                runner=unbooted,
                urlopen=lambda request, timeout=3: _json_body(
                    {"value": {"ready": True, "build": {"version": "3.0.1"}}}
                ),
            )
            self.assertEqual(1, code, err)
            self.assertEqual("unready", _check_map(json.loads(out))["android-device"]["state"])

        for argv in (["--strict"], ["--strict", "desktop"], ["--json", "--text"], ["--no-such"]):
            with self.subTest(argv=argv):
                code, _out, _err = _invoke(argv)
                self.assertEqual(2, code)

    def test_driver_null_package_and_npx_list(self) -> None:
        def null_package(command: list[str], **_kwargs: object) -> _Proc:
            return _Proc("", "Cannot read properties of null (missing tarball)", code=1)

        code, out, err = _invoke([], which_map={"appium": "/usr/bin/appium"}, runner=null_package)
        self.assertEqual(0, code, err)
        drivers = _check_map(json.loads(out))["appium-drivers"]
        self.assertEqual("unready", drivers["state"])
        self.assertIn("references/appium-driver-npm-recover.md", drivers["fixNext"])

        seen: list[list[str]] = []

        def npx_list(command: list[str], **_kwargs: object) -> _Proc:
            seen.append(list(command))
            return _Proc('{"uiautomator2":{"installed":true}}')

        _code, out, _err = _invoke([], which_map={"npx": "/usr/bin/npx"}, runner=npx_list)
        self.assertEqual(
            ["/usr/bin/npx", "--no-install", "appium", "driver", "list", "--installed", "--json"],
            seen[0],
        )
        self.assertEqual("ready", _check_map(json.loads(out))["appium-drivers"]["state"])

        def noisy_json(command: list[str], **_kwargs: object) -> _Proc:
            return _Proc('{"uiautomator2": {"installed": true, "version": "4.2.0"}}\n', "npm warn extra\n", 0)

        _code, out, _err = _invoke([], which_map={"appium": "/usr/bin/appium"}, runner=noisy_json)
        drivers = _check_map(json.loads(out))["appium-drivers"]
        self.assertEqual("ready", drivers["state"])
        self.assertIn("installed=1", drivers["evidence"])

    def test_readonly_never_invokes_mutating_commands(self) -> None:
        banned = [
            ["docker", "pull", "selenium/standalone-chromium:4.54.0-20261123"],
            ["npm", "install", "-g", "appium"],
            ["sdkmanager", "--install", "platform-tools"],
            ["appium", "driver", "install", "uiautomator2"],
            ["npx", "playwright", "install"],
            ["npx", "--no-install", "playwright", "install"],
            ["emulator", "-avd", "ci", "-no-window"],
            ["xcrun", "simctl", "boot", "ABC"],
            ["adb", "shell", "pm", "clear", "com.example"],
            ["avdmanager", "create", "avd", "-n", "ci"],
        ]
        with patch.object(mod.subprocess, "run", side_effect=AssertionError("ran")):
            for argv in banned:
                with self.subTest(argv=argv):
                    self.assertFalse(mod.command_allowed(argv))
                    with self.assertRaises(mod.ReadOnlyViolation):
                        mod.run_probe(argv, timeout=1)
        self.assertTrue(mod.command_allowed(["/usr/bin/docker", "info"]))
        self.assertTrue(mod.command_allowed(["/usr/bin/npx", "--no-install", "playwright", "--version"]))
        self.assertTrue(
            mod.command_allowed(
                ["/usr/bin/adb", "-s", "emulator-5554", "shell", "getprop", "sys.boot_completed"]
            )
        )
        self.assertFalse(
            mod.command_allowed(["/usr/bin/adb", "-s", "-rf", "shell", "getprop", "sys.boot_completed"])
        )

        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "browsers"
            cache.mkdir()
            (cache / "chromium").mkdir()
            code, out, err, calls = _statuses(
                ["--strict", "all"],
                env={
                    "PLAYWRIGHT_BROWSERS_PATH": str(cache),
                    "ANDROID_HOME": "/opt/android-sdk",
                    "ANDROID_SDK_ROOT": "/opt/android-sdk",
                },
                which_fn=lambda name: f"/usr/bin/{name}",
            )
        self.assertEqual(0, code, err + out)
        self.assertGreater(len(calls), 0)
        phrases = (
            "docker pull",
            "npm install",
            "sdkmanager --install",
            "appium driver install",
            "playwright install",
            "emulator -avd",
            "simctl boot",
            "pm clear",
            "avdmanager create",
        )
        for argv in calls:
            self.assertTrue(mod.command_allowed(argv), argv)
            text = " ".join(argv)
            for phrase in phrases:
                self.assertNotIn(phrase, text, argv)
        source = (ROOT / "scripts" / "ci" / "test_env_doctor.py").read_text(encoding="utf-8")
        self.assertNotIn("shell=True", source)
        self.assertNotIn("os.system", source)
        payload = json.loads(out)
        states = _check_map(payload)
        for check_id in mod.CHECK_IDS:
            if check_id == "ios-sim":
                self.assertEqual("skipped", states[check_id]["state"])
            else:
                self.assertEqual("ready", states[check_id]["state"], states[check_id])
        self.assertIn("Colima/OrbStack/rootless", states["testcontainers"]["evidence"])
        self.assertIn("context=default", states["docker"]["evidence"])

    def test_imports_are_stdlib_allowlist(self) -> None:
        tree = ast.parse((ROOT / "scripts" / "ci" / "test_env_doctor.py").read_text(encoding="utf-8"))
        allowed = {
            "argparse",
            "json",
            "os",
            "platform",
            "re",
            "shutil",
            "subprocess",
            "sys",
            "urllib.request",
            "pathlib",
        }
        found: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                self.assertIsNotNone(node.module)
                found.append(node.module or "")
        self.assertGreater(len(found), 0)
        for name in found:
            self.assertIn(name, allowed, name)

    def test_skill_and_doc_contracts(self) -> None:
        for folder in SKILL_DIRS:
            for path in folder.rglob("*"):
                if path.is_file():
                    text = path.read_text(encoding="utf-8")
                    for token in BANNED_TOKENS:
                        self.assertNotIn(token, text, path)
        for name in ("test-env-setup", "mobile-testing"):
            raw = (ROOT / "skills" / name / "SKILL.md").read_bytes()
            self.assertLessEqual(len(raw), 2048, name)
            self.assertLessEqual(len(raw), 2000, name)
            text = raw.decode("utf-8")
            self.assertIn(f"name: {name}", text)
            self.assertIn("license: MIT", text)
            self.assertNotIn("permissions:", text)
            description = _frontmatter_description(text)
            self.assertGreaterEqual(len(description), 90, description)
            self.assertLessEqual(len(description), 150, description)
            self.assertIn("scripts/ci/test_env_doctor.py", text)
        setup = (ROOT / "skills" / "test-env-setup" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("Iron Law 7", setup)
        self.assertIn("references/env-matrix.md", setup)
        mobile = (ROOT / "skills" / "mobile-testing" / "SKILL.md").read_text(encoding="utf-8")
        for needle in (
            "references/mobile-client-automation.md",
            "references/mobile-retro-harness.md",
            "references/appium-driver-npm-recover.md",
            "references/mobile-automation-patterns.md",
            "test-env-setup",
        ):
            self.assertIn(needle, mobile)
        doctor = (ROOT / "references" / "test-env-doctor.md").read_bytes()
        matrix = (ROOT / "skills" / "test-env-setup" / "references" / "env-matrix.md").read_bytes()
        patterns = (ROOT / "skills" / "mobile-testing" / "references" / "mobile-automation-patterns.md").read_bytes()
        self.assertLessEqual(len(doctor), int(2.5 * 1024))
        self.assertLessEqual(len(matrix), int(5.0 * 1024))
        self.assertLessEqual(len(patterns), int(3.8 * 1024))
        doctor_text = doctor.decode("utf-8")
        for needle in (
            "ready",
            "absent",
            "unready",
            "skipped",
            "--strict",
            "--allow-remote-status",
            "mobile-android",
            "mobile-ios",
            "owner",
        ):
            self.assertIn(needle, doctor_text)
        matrix_text = matrix.decode("utf-8")
        for needle in (
            "4.54.0-20261123",
            "shm_size: 2gb",
            "SE_NODE_MAX_SESSIONS",
            "SE_NODE_OVERRIDE_MAX_SESSIONS=true",
            "node-chromium",
            "node-firefox",
            "/graphql",
            "SE_OFFLINE",
            "SE_CACHE_PATH",
            "appium@3",
            "appium@4",
            "^22.22.2",
            "execute-driver",
            "references/appium-driver-npm-recover.md",
            "ANDROID_HOME",
            "ANDROID_SDK_ROOT",
            "sdkmanager",
            "avdmanager",
            "/dev/kvm",
            "HVF",
            "WHPX",
            "google_apis_playstore",
            "arm64-v8a",
            "x86_64",
            "-no-window",
            "-no-audio",
            "-no-boot-anim",
            "-no-snapshot-save",
            "sys.boot_completed",
            "window_animation_scale",
            "adb emu kill",
            "bootstatus",
            "playwright install --with-deps",
            "TESTCONTAINERS_RYUK_DISABLED",
            "DOCKER_HOST",
            "Linux",
            "macOS",
            "Windows",
        ):
            self.assertIn(needle, matrix_text, needle)
        pattern_text = patterns.decode("utf-8")
        for needle in (
            "content-desc",
            "accessibilityIdentifier",
            "UiSelector",
            "NSPredicate",
            "Class Chain",
            "XPath",
            "ignoreUnimportantViews",
            "snapshotMaxDepth",
            "android.intent.action.VIEW",
            "simctl openurl",
            "autoGrantPermissions",
            "autoAcceptAlerts",
            "noReset",
            "fullReset",
            "pm clear",
            "MASVS",
            "v2.1.0",
            "MASTG",
            "security-audit",
        ):
            self.assertIn(needle, pattern_text, needle)


if __name__ == "__main__":
    unittest.main()
