# Environment matrix

Run `python3 scripts/ci/test_env_doctor.py` first. Ask the owner before every install, image pull, SDK download, or emulator boot. Pins below are exact. Grid, Appium, and Playwright commands are the same on Linux, macOS, and Windows when the binary is on PATH. Android acceleration and iOS differ by OS.

## Selenium Grid 4

Tag `4.54.0-20261123` on `selenium/standalone-chromium`, `selenium/hub`, `selenium/node-chromium`, and `selenium/node-firefox`.

```yaml
services:
  selenium:
    image: selenium/standalone-chromium:4.54.0-20261123
    shm_size: 2gb
    ports: ["4444:4444"]
```

Hub plus node uses that tag on `selenium/hub` and `selenium/node-chromium`. On the node set `SE_NODE_MAX_SESSIONS` and `SE_NODE_OVERRIDE_MAX_SESSIONS=true` so the cap you set is the cap Grid keeps.

Dynamic Grid mounts the Docker socket and can start containers. That socket is root-equivalent (remote code execution if a session is hostile). Keep Dynamic Grid on a trusted host.

arm64: many Chrome and Firefox node tags publish no arm64 manifest. Prefer `node-chromium` and `node-firefox` tags that publish arm64.

Probe `GET /status` (`value.ready == true`). A 404 falls back to `GET /wd/hub/status`. Grid also serves `GET /graphql`. Video: a `selenium/video` sidecar on the same network, aimed at the node.

Selenium Manager offline: `SE_OFFLINE=true` and `SE_CACHE_PATH` pointed at a cache you already filled.

## Appium 3 and 4

Node floors this doctor uses: Appium 3 `^20.19 || ^22.12 || >=24`. Appium 4 `^22.22.2 || ^24.15 || >=26`. Evidence `class=appium4` or `class=appium3`. Prefer `appium@4` when the class is appium4, else `appium@3`.

Listen on `http://127.0.0.1:4723` with base path `/` (`/status`). Use `/wd/hub` only for a legacy client that requires it.

After approval: `appium driver install uiautomator2` and `appium driver install xcuitest`, then `appium driver doctor uiautomator2`. List with `appium driver list --installed --json` or `npx --no-install appium driver list --installed --json`.

Null-package or missing tarball: [appium-driver-npm-recover](../../../references/appium-driver-npm-recover.md). Uninstall the driver, then `appium driver install --source=npm <pkg>@<ver>`. Leave the broken cache entry alone.

The `execute-driver` plugin runs client-supplied code. Leave it disabled on a shared server.

## Android SDK and AVD

Set `ANDROID_HOME` to one SDK root. When `ANDROID_SDK_ROOT` is set, use the same path. The doctor marks a mismatch `unready`.

Modern binaries, when the SDK ships them: `android sdk` and `android emulator`. Doctor probes are `android sdk --version` and `android emulator list`. Legacy binaries: `sdkmanager` and `avdmanager` on `cmdline-tools/latest/bin`. Install and AVD create use the legacy commands unless `android --help` shows the same verbs.

| OS | Accel | ABI |
| --- | --- | --- |
| Linux | KVM and `/dev/kvm`. `emulator -accel-check` exits 0 | `x86_64` on Intel/AMD; `arm64-v8a` on arm64 |
| macOS | HVF. `emulator -accel-check` exits 0 | `arm64-v8a` on Apple Silicon; `x86_64` on Intel |
| Windows | WHPX. `emulator -accel-check` exits 0 | `x86_64` |

CI image: `system-images;android-35;google_apis;<abi>`. Use `google_apis_playstore` only when the test needs Play services.

After approval, legacy create:

`sdkmanager --install "system-images;android-35;google_apis;x86_64"`

`avdmanager create avd -n ci -k "system-images;android-35;google_apis;x86_64" --device pixel`

Headless boot of a suite-owned AVD, after approval:

```bash
emulator -avd ci -no-window -no-audio -no-boot-anim -no-snapshot-save
adb wait-for-device
adb shell getprop sys.boot_completed
```

Poll until that property prints `1`. Then:

```bash
adb shell settings put global window_animation_scale 0
adb shell settings put global transition_animation_scale 0
adb shell settings put global animator_duration_scale 0
```

Stop that emulator with `adb emu kill`.

## iOS Simulator

macOS only. The doctor sets `ios-sim` to `skipped` on Linux and Windows. Install full Xcode, not Command Line Tools alone. `xcode-select -p` must point at Xcode.

```bash
xcrun simctl boot <udid>
xcrun simctl bootstatus <udid> -b
```

XCUITest WebDriverAgent needs a signing identity. The doctor does not pick a team or boot a simulator.

## Playwright and Testcontainers

After approval, `npx playwright install`. `npx playwright install --with-deps` also installs OS packages. That step fails in some root images and when the proxy reaches Node but not apt or dnf. Bake the OS libraries into the image, then install browsers without `--with-deps`. Cache directory: `PLAYWRIGHT_BROWSERS_PATH`. The doctor runs `npx --no-install playwright --version` and requires a non-empty cache.

Testcontainers is ready when `docker info` is ready. The doctor records the Docker context. Colima, OrbStack, and rootless engines need `DOCKER_HOST` on that socket. Set `TESTCONTAINERS_RYUK_DISABLED=true` when Ryuk cannot see containers.
