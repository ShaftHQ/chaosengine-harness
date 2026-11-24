# Test environment doctor

Read-only probe of the local test host. It checks binaries, versions, env vars, browser caches, and optional loopback `/status` URLs. It does not install packages, pull images, download SDKs, or boot emulators or simulators.

## Run

`python3 scripts/ci/test_env_doctor.py`

Add `--text` for a table. JSON is the default (`--json` is the same). `--strict web|grid|mobile-android|mobile-ios|api|all` exits 1 when a required check is `absent` or `unready`, and 0 otherwise. Report mode exits 0 even when tools are absent. Bad arguments exit 2.

Defaults: Grid `http://127.0.0.1:4444/status`, Appium `http://127.0.0.1:4723/status`. Override with `--grid-url` and `--appium-url`. A non-loopback URL is refused unless you pass `--allow-remote-status`. A Grid 404 retries `/wd/hub/status`.

JSON shape: `schemaVersion` 1, `mode` (`report` or `strict`), `platform`, `checks[]` of `id`, `state`, `evidence`, `fixNext`. Strict mode adds `profile`.

## States

| State | Meaning |
| --- | --- |
| ready | The probe met the bar |
| absent | The tool, service, or device is missing |
| unready | Present but failing (version, path mismatch, status false, boot incomplete) |
| skipped | Not applicable here (`ios-sim` off macOS) |

`node` records Appium compatibility. Appium 3 is `^20.19 || ^22.12 || >=24`. Appium 4 is `^22.22.2 || ^24.15 || >=26`. Evidence shows `class=appium4`, `class=appium3`, or `class=unsupported`. A version that meets both floors is `appium4`. `unsupported` is `unready`.

`android-sdk` is `unready` when `ANDROID_HOME` and `ANDROID_SDK_ROOT` are both set and differ.

## Profiles

| Profile | Required ids |
| --- | --- |
| web | node, playwright |
| grid | docker, grid |
| mobile-android | node, java, appium, appium-drivers, android-sdk, android-accel, android-avd, android-device |
| mobile-ios | node, appium, appium-drivers, ios-sim |
| api | python, java, mvn |
| all | every id |

`skipped` does not fail `--strict`.

## Ask before install

`fixNext` is a hint. Install tools, pull images, download SDKs or system images, or boot a device only after the owner says yes. Then run the doctor again. Grid hints name pin `4.54.0-20261123`, `shm_size: 2gb`, and arm64 `node-chromium` / `node-firefox`. Appium hints name `appium@4` or `appium@3` from the Node class.
