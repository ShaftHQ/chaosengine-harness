---
description: Use when a Windows host starts a mobile or Android emulator session with Appium. Bound every prerequisite check, fail loud on Linux-only tools, and set MSYS2 path conversion per command.
---

# Windows mobile start

Use this recipe for an Android emulator plus Appium on Windows. The same
session on Linux can use the host tools directly. A missing prerequisite is a
one-line failure, not a skip and not a hang.

## Bounded prerequisite checks

Run each check with its own timeout. Do not poll forever.

```bash
adb devices -l
# timeout 15s; a missing or unauthorized device stops the session
```

```bash
curl --max-time 10 -fsS http://127.0.0.1:4723/status
# timeout 10s; Appium must already be listening
```

```bash
java -version
mvn -version
gradle -version
# each invocation is one shot; a missing tool prints its own error and stops
```

A wrapper that waits uses a deadline, for example
`tool.py job wait <name> --timeout 60`, or a counted loop that exits when the
deadline passes. See [durable jobs](durable-jobs.md).

## Fail loud on Linux-only tools

`getent`, `pgrep`, and `systemd-run` are Linux tools. On Windows and macOS
they must fail with one line and a non-zero status. They must not be skipped,
and they must not be treated as "no memory cap" or "no process".

```bash
case "$(uname -s)" in
  Linux) ;;
  *) echo "unsupported OS for getent/pgrep/systemd-run: $(uname -s)" >&2; exit 1 ;;
esac
```

A memory cap that cannot be applied is a failed start. Do not continue
without it.

## Git Bash path conversion

Set `MSYS2_ARG_CONV_EXCL` on the one command that must keep a Unix path.
Never export it for the whole shell. `MSYS2_ARG_CONV_EXCL="*"` breaks Maven's
launcher.

```bash
MSYS2_ARG_CONV_EXCL="--base-path" appium --base-path /
```

Other commands in the same script keep the default conversion.
