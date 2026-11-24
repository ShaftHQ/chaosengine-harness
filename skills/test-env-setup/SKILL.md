---
name: test-env-setup
description: "Use when a web, grid, mobile, or API test host needs tools: run the read-only doctor and ask before any install, pull, SDK download, or boot."
license: MIT
---

# Test environment setup

On demand. Load this file only when a test host needs setup.

## 1. Doctor first

Run `python3 .chaos-engine/scripts/ci/test_env_doctor.py` before you suggest or run any setup command. Read states in [test-env-doctor](../../references/test-env-doctor.md). `ready` needs nothing. `absent` and `unready` need a fix. `skipped` does not apply on this OS.

## 2. Ask before change

Iron Law 7: get an explicit yes from the owner before installing a tool, pulling a Docker image, downloading an SDK or AVD image, or booting an emulator or simulator. A `fixNext` line is not approval.

## 3. OS commands

Load [env-matrix](references/env-matrix.md) for the pinned Linux, macOS, and Windows commands. Run only the rows the owner approved. Run the doctor again and report the new states.
