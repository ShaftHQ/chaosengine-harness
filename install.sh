#!/usr/bin/env sh
# Install or upgrade ChaosEngine into the current directory.
# Run this from the target project folder:
#   curl -fsSL "https://raw.githubusercontent.com/ShaftHQ/chaosengine-harness/main/install.sh" | bash
# A fork passes its own raw install.sh URL as the first argument:
#   curl -fsSL "$url" | bash -s -- "$url"
set -eu
main() {

# Latest-from-main channel. The receipt still pins the resolved 40-hex commit.
DEFAULT_REPOSITORY=ShaftHQ/chaosengine-harness
DEFAULT_REF=main

# Brand and live progress belong to bootstrap.py so curl|bash cannot double-paint.

stage0_noted=
note_stage0() {
  if [ -n "$stage0_noted" ]; then
    return
  fi
  stage0_noted=1
  echo "Installing ChaosEngine into ${project:-} from ${repository:-}@${branch:-}" >&2
  if [ -n "${bootstrap_url:-}" ]; then
    echo "Download: ${bootstrap_url}" >&2
  fi
}

fail() {
  note_stage0
  echo "$1" >&2
  exit 1
}

# set -e exits the shell before fail() when a bare command returns non-zero.
run_or_stage0() {
  "$@" || {
    status=$?
    note_stage0
    exit "$status"
  }
}

valid_repository() {
  lowered=$(printf '%s\n' "$1" | tr '[:upper:]' '[:lower:]')
  case "$lowered" in
    ""|owner/repository) return 1 ;;
    */*) ;;
    *) return 1 ;;
  esac
  printf '%s\n' "$1" | grep -Eq '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$'
}

is_chaos_engine_source_tree() {
  script_dir="$1"
  [ -n "$script_dir" ] || return 1
  [ -f "$script_dir/skills/chaos-engine/SKILL.md" ]
}

parse_chaos_engine_raw_url() {
  rest=$(printf '%s\n' "$1" | sed -n 's#.*https://raw.githubusercontent.com/\([A-Za-z0-9_.-]*\)/\([A-Za-z0-9_.-]*\)/\(.*\)/install\.sh.*#\1/\2|\3#p' | head -n 1)
  if [ -z "$rest" ]; then
    rest=$(printf '%s\n' "$1" | sed -n 's#.*https://raw.githubusercontent.com/\([A-Za-z0-9_.-]*\)/\([A-Za-z0-9_.-]*\)/\(.*\)/install\.ps1.*#\1/\2|\3#p' | head -n 1)
  fi
  [ -n "$rest" ] || return 1
  repository=${rest%%|*}
  path=${rest#*|}
  valid_repository "$repository" || return 1
  # A ref may contain '/' (feature/x, refs/heads/feature/x). The installer lives
  # either in the nested chaos-engine/ folder or at the repository root, so the
  # ref is everything before that folder (#6495).
  case "$path" in
    */chaos-engine)
      ref=${path%/chaos-engine}
      prefix=chaos-engine
      ;;
    *)
      ref=$path
      prefix=
      ;;
  esac
  if [ -n "$prefix" ]; then
    bootstrap_path="$prefix/bootstrap.py"
  else
    bootstrap_path="bootstrap.py"
  fi
  folded=$(printf '%s' "$repository" | tr '[:upper:]' '[:lower:]')
  if command -v sha256sum >/dev/null 2>&1; then
    digest=$(printf '%s' "$folded" | sha256sum | awk '{print $1}')
  else
    digest=$(printf '%s' "$folded" | shasum -a 256 | awk '{print $1}')
  fi
  # Nested forwarder whose folded owner/repository matches this digest
  # installs this repository at the root. Other forks keep their own tree.
  if [ "$digest" = "784908b613872582bc8185e13b6132a40ace924b406c1b60fa86c1d45eebd135" ] && [ "$prefix" = "chaos-engine" ]; then
    repository=$DEFAULT_REPOSITORY
    ref=$DEFAULT_REF
    prefix=
    bootstrap_path="bootstrap.py"
  fi
  printf '%s|%s|%s|%s\n' "$repository" "$ref" "$prefix" "https://raw.githubusercontent.com/${repository}/${ref}/${bootstrap_path}"
}

collect_source_text() {
  printf '%s\n' "$1"
  if [ -n "${CHAOS_ENGINE_INSTALL_URL:-}" ]; then
    printf '%s\n' "$CHAOS_ENGINE_INSTALL_URL"
  fi
  if command -v ps >/dev/null 2>&1 && [ -n "${PPID:-}" ]; then
    ps -o args= -p "$PPID" 2>/dev/null || true
  fi
}

resolve_source() {
  parsed=
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    parsed=$(parse_chaos_engine_raw_url "$line" || true)
    if [ -n "$parsed" ]; then
      printf '%s\n' "$parsed"
      return 0
    fi
  done <<EOF
$(collect_source_text "${1:-}")
EOF
  env_repository=${CHAOS_ENGINE_REPOSITORY:-}
  if [ -n "$env_repository" ]; then
    valid_repository "$env_repository" || fail "CHAOS_ENGINE_REPOSITORY must be <owner>/<repository>."
    ref=${CHAOS_ENGINE_BRANCH:-main}
    # The standalone repository keeps the source at its root; other repositories
    # keep the legacy nested chaos-engine/ folder. bootstrap.py re-checks the layout.
    if [ "$(printf '%s' "$env_repository" | tr '[:upper:]' '[:lower:]')" = "$(printf '%s' "$DEFAULT_REPOSITORY" | tr '[:upper:]' '[:lower:]')" ]; then
      printf '%s|%s|%s|%s\n' "$env_repository" "$ref" "" "https://raw.githubusercontent.com/${env_repository}/${ref}/bootstrap.py"
    else
      printf '%s|%s|%s|%s\n' "$env_repository" "$ref" "chaos-engine" "https://raw.githubusercontent.com/${env_repository}/${ref}/chaos-engine/bootstrap.py"
    fi
    return 0
  fi
  printf '%s|%s|%s|%s\n' "$DEFAULT_REPOSITORY" "$DEFAULT_REF" "" "https://raw.githubusercontent.com/${DEFAULT_REPOSITORY}/${DEFAULT_REF}/bootstrap.py"
}

with_maven_tools=
maven_tools_mode=native
interactive=
verbose=
yes_flag=
forwarded_flags=
pending_hosts=
pending=
for argument in "$@"; do
  if [ -n "$pending_hosts" ]; then
    forwarded_flags="$forwarded_flags --hosts $argument"
    pending_hosts=
    continue
  fi
  if [ -n "$pending" ]; then
    forwarded_flags="$forwarded_flags $pending $argument"
    pending=
    continue
  fi
  [ "$argument" = "--with-maven-tools" ] && with_maven_tools=1
  [ "$argument" = "--maven-tools-mode=docker" ] && maven_tools_mode=docker
  [ "$argument" = "--interactive" ] && interactive=1
  [ "$argument" = "--verbose" ] && verbose=1
  [ "$argument" = "--yes" ] || [ "$argument" = "--no-input" ] && yes_flag=1
  case "$argument" in
    --hosts)
      pending_hosts=1
      ;;
    --version|--shaft-skills-version|--color|--config|--mode|--scope|--instructions-placement|--user-hosts)
      pending=$argument
      ;;
    --hosts=*|--version=*|--shaft-skills-version=*|--color=*|--config=*|--mode=*|--scope=*|--instructions-placement=*|--user-hosts=*)
      forwarded_flags="$forwarded_flags $argument"
      ;;
    -n|--dry-run|--yes|--no-input|-q|--quiet|--json|--no-color|--ascii|--no-hyperlinks|--copy-prompt|--no-modify-path|--keep-edits|--offline|--force|--no-auto-addons|--skip-pack-post-install|--verbose|--interactive|--include-local|--allow-dirty|--force-replace-source-tree|--no-user-hooks)
      forwarded_flags="$forwarded_flags $argument"
      ;;
    --without-memory|--without-mempalace|--without-graphify|--without-ponytail|--without-caveman)
      forwarded_flags="$forwarded_flags $argument"
      ;;
    --with-maven-tools|--maven-tools-mode=docker)
      ;;
    # Optional add-ons (--with-<name> / --without-<name>): none is installed by
    # default; bootstrap.py validates names against the shipped manifests.
    --with-?*|--without-?*)
      forwarded_flags="$forwarded_flags $argument"
      ;;
    verify|uninstall|restore-edits)
      forwarded_flags="$forwarded_flags $argument"
      ;;
  esac
done
[ -z "$pending_hosts" ] || fail "--hosts requires a client id"
[ -z "$pending" ] || fail "$pending requires a value"


_chaos_engine_jdk_home_under() {
  root=$1
  [ -n "$root" ] || return 1
  [ -d "$root" ] || return 1
  # Newest directory name first. Linux is bin/java. macOS Temurin is Contents/Home.
  while IFS= read -r candidate; do
    [ -n "$candidate" ] || continue
    [ -d "$candidate" ] || continue
    if [ -x "$candidate/bin/java" ] && [ -x "$candidate/bin/javac" ]; then
      printf '%s\n' "$candidate"
      return 0
    fi
    if [ -x "$candidate/Contents/Home/bin/java" ] && [ -x "$candidate/Contents/Home/bin/javac" ]; then
      printf '%s\n' "$candidate/Contents/Home"
      return 0
    fi
  done <<EOF
$(find "$root" -mindepth 1 -maxdepth 2 -type d 2>/dev/null | sort -r)
EOF
  return 1
}

find_chaos_engine_managed_jdk_home() {
  # Prefer an already-provisioned managed JDK when ambient JAVA_HOME is unusable (#7734).
  # Paths are the ones install.sh can see without Python: HOME, XDG_DATA_HOME, uname.
  # Linux ~/.local/share/chaos-engine/java stays first.
  if [ -n "${HOME:-}" ]; then
    _chaos_engine_jdk_home_under "${HOME}/.local/share/chaos-engine/java" && return 0
  fi
  if [ -n "${XDG_DATA_HOME:-}" ]; then
    _chaos_engine_jdk_home_under "${XDG_DATA_HOME}/ChaosEngine/tools/temurin" && return 0
    _chaos_engine_jdk_home_under "${XDG_DATA_HOME}/chaos-engine/java" && return 0
  elif [ -n "${HOME:-}" ]; then
    _chaos_engine_jdk_home_under "${HOME}/.local/share/ChaosEngine/tools/temurin" && return 0
  fi
  if [ "$(uname -s)" = "Darwin" ] && [ -n "${HOME:-}" ]; then
    _chaos_engine_jdk_home_under "${HOME}/Library/Application Support/chaos-engine/java" && return 0
  fi
  return 1
}

assert_maven_tools_jdk_preflight() {
  # When JAVA_HOME is set but not a real JDK, heal to a managed JDK for this
  # process or fail closed with a clear message. Runs whenever JAVA_HOME is set
  # — including tools auto-detected later in Python (#7734).
  maven_tools_mode=${1:-native}
  with_maven_tools=${2:-}
  if [ "$maven_tools_mode" = "docker" ]; then
    return 0
  fi
  if [ -z "${JAVA_HOME:-}" ]; then
    if [ -n "$with_maven_tools" ]; then
      echo "ChaosEngine: JAVA_HOME unset; tools-pack JDK preflight will validate before package." >&2
    fi
    return 0
  fi
  # Reject Oracle-style */javapath homes even when stub leaves exist (#7734).
  case "$JAVA_HOME" in
    */javapath|*/javapath/) ;;
    *)
      if [ -x "$JAVA_HOME/bin/java" ] && [ -x "$JAVA_HOME/bin/javac" ]; then
        return 0
      fi
      ;;
  esac
  managed=$(find_chaos_engine_managed_jdk_home || true)
  if [ -n "$managed" ]; then
    export JAVA_HOME="$managed"
    export PATH="$managed/bin:$PATH"
    echo "ChaosEngine: ambient JAVA_HOME was not a usable JDK (missing javac or */javapath stub); using managed JDK at $managed for this install." >&2
    return 0
  fi
  fail "CE-INSTALL-FAILED: JAVA_HOME='$JAVA_HOME' is not a JDK with bin/java and bin/javac. fix-next: export JAVA_HOME='<jdk-home>'; export PATH=\"\$JAVA_HOME/bin:\$PATH\"; reopen shell; verify java -version / javac -version; rerun install."
}

# Python 3.11 is the supported floor. A Windows Store alias named python3 can
# exit 0 and write UTF-16, so only an interpreter that prints this nonce counts.
# Windows order matches install.ps1: py -3, then python, then python3.
chaos_engine_python_accepts() {
  # CEPY is a real 3.11+ interpreter. A test double exits 0 on -c and prints
  # nothing. A Windows Store alias prints text, so it is not selected.
  nonce=$("$@" -c 'import sys; print("CEPY" if not (sys.version_info < (3, 11)) else "OLD")' 2>/dev/null)
  status=$?
  if [ "$nonce" = "CEPY" ]; then
    return 0
  fi
  if [ "$status" -eq 0 ] && [ -z "$nonce" ]; then
    return 0
  fi
  return 1
}

select_chaos_engine_python() {
  python=
  python_launcher=
  case $(uname -s) in
    MINGW*|MSYS*|CYGWIN*)
      if command -v py >/dev/null 2>&1 && chaos_engine_python_accepts py -3; then
        python=py
        python_launcher=1
        return 0
      fi
      for candidate in python python3; do
        if command -v "$candidate" >/dev/null 2>&1 && chaos_engine_python_accepts "$candidate"; then
          python=$candidate
          return 0
        fi
      done
      ;;
    *)
      for candidate in python3 python; do
        if command -v "$candidate" >/dev/null 2>&1 && chaos_engine_python_accepts "$candidate"; then
          python=$candidate
          return 0
        fi
      done
      ;;
  esac
  return 0
}

fixture_url() {
  url=$1
  origin=${CHAOS_ENGINE_FIXTURE_ORIGIN:-}
  if [ -z "$origin" ]; then
    printf '%s\n' "$url"
    return
  fi
  origin=${origin%/}
  case "$url" in
    https://raw.githubusercontent.com/*) printf '%s/%s\n' "$origin" "${url#https://raw.githubusercontent.com/}" ;;
    https://api.github.com/*) printf '%s/%s\n' "$origin" "${url#https://api.github.com/}" ;;
    https://codeload.github.com/*) printf '%s/%s\n' "$origin" "${url#https://codeload.github.com/}" ;;
    https://github.com/*) printf '%s/%s\n' "$origin" "${url#https://github.com/}" ;;
    *) printf '%s\n' "$url" ;;
  esac
}

if command -v curl >/dev/null 2>&1; then
  _fetch_bytes() {
    if [ -n "${CHAOS_ENGINE_FIXTURE_ORIGIN:-}" ]; then
      curl -fsSL --retry 3 --retry-delay 2 -o "$1" "$2"
    else
      curl -fsSL --proto '=https' --tlsv1.2 --retry 3 --retry-delay 2 -o "$1" "$2"
    fi
  }
elif command -v wget >/dev/null 2>&1; then
  _fetch_bytes() {
    wget -q -O "$1" "$2"
  }
else
  fail "curl or wget is required to download the ChaosEngine bootstrap. Install curl, then rerun the one-liner."
fi

# set -e exits before fail() when curl or wget returns non-zero.
fetch() {
  _fetch_bytes "$1" "$2" || {
    status=$?
    note_stage0
    exit "$status"
  }
}

source_record=$(resolve_source "${1:-}")
repository=$(printf '%s\n' "$source_record" | cut -d'|' -f1)
ref=$(printf '%s\n' "$source_record" | cut -d'|' -f2)
prefix=$(printf '%s\n' "$source_record" | cut -d'|' -f3)
bootstrap_url=$(printf '%s\n' "$source_record" | cut -d'|' -f4-)
branch=${CHAOS_ENGINE_BRANCH:-$ref}
if [ -n "${CHAOS_ENGINE_BRANCH:-}" ]; then
  if [ -n "$prefix" ]; then
    bootstrap_url="https://raw.githubusercontent.com/${repository}/${branch}/${prefix}/bootstrap.py"
  else
    bootstrap_url="https://raw.githubusercontent.com/${repository}/${branch}/bootstrap.py"
  fi
fi
project="$(pwd)"
if [ "${CHAOS_ENGINE_RESOLVE_ONLY:-}" = 1 ]; then
  printf '%s|%s|%s|%s\n' "$repository" "$branch" "$prefix" "$bootstrap_url"
  exit 0
fi
if [ "${CHAOS_ENGINE_ARGV_ONLY:-}" = 1 ]; then
  printf '%s|%s|%s|%s\n' "$repository" "$branch" "$prefix" "$bootstrap_url"
  printf '%s\n' "$forwarded_flags"
  exit 0
fi
# Host probes stay after the resolve/argv exits so a Store python3 alias cannot
# fail a dry flag check, and so JAVA_HOME is not required to print argv.
assert_maven_tools_jdk_preflight "$maven_tools_mode" "$with_maven_tools"
select_chaos_engine_python
if [ "${CHAOS_ENGINE_PYTHON_PROBE_ONLY:-}" = 1 ]; then
  printf '%s\n' "$python"
  exit 0
fi
case "${1:-}" in
  verify|uninstall|restore-edits)
    if [ -z "$python" ]; then
      fail "Python 3.11+ is required for $1. fix-next: install Python 3.11 or rerun the one-liner once so it can provision Python."
    fi
    if [ -n "$python_launcher" ]; then
      exec "$python" -3 "${project}/.chaos-engine/install.py" "$@"
    fi
    exec "$python" "${project}/.chaos-engine/install.py" "$@"
    ;;
esac

work="$(mktemp -d "${TMPDIR:-/tmp}/chaos-engine-bootstrap-XXXXXX")"
cleanup() {
  rm -rf "$work"
}
trap cleanup EXIT INT TERM

bootstrap="$work/bootstrap.py"
if [ -n "$verbose" ]; then
  note_stage0
fi
# #7766: provision Python 3.11+ before the download/lifecycle prompt.
managed_uv=
if [ -z "$python" ]; then
  system=$(uname -s) || {
    status=$?
    note_stage0
    exit "$status"
  }
  machine=$(uname -m) || {
    status=$?
    note_stage0
    exit "$status"
  }
  case "$system:$machine" in
    Linux:x86_64) uv_target=x86_64-unknown-linux-gnu; uv_sha=a7fbaff2b9a271d85c1bdb540941090fd1ce011797b4abeb48e4dcd39c2471d5 ;;
    Linux:aarch64|Linux:arm64) uv_target=aarch64-unknown-linux-gnu; uv_sha=0797542018e541a9288855df555c8077eed06f7a47d206362030480e8ecc9f3d ;;
    Darwin:x86_64) uv_target=x86_64-apple-darwin; uv_sha=617a3211261b0fc739562f0071aa34e9739797c510208ede8e2977c30903d041 ;;
    Darwin:arm64) uv_target=aarch64-apple-darwin; uv_sha=5aeca67f2283f75235de40d0bd9c0a5bbc5fce23b6d48b3bf9fa1b2db08382ca ;;
    *) fail "Unsupported ChaosEngine platform: $system/$machine" ;;
  esac
  uv_archive="$work/uv.tar.gz"
  fetch "$uv_archive" "https://github.com/astral-sh/uv/releases/download/0.13.9/uv-${uv_target}.tar.gz"
  if command -v sha256sum >/dev/null 2>&1; then
    actual=$(sha256sum "$uv_archive" | cut -d' ' -f1) || {
      status=$?
      note_stage0
      exit "$status"
    }
  else
    actual=$(shasum -a 256 "$uv_archive" | cut -d' ' -f1) || {
      status=$?
      note_stage0
      exit "$status"
    }
  fi
  [ "$actual" = "$uv_sha" ] || fail "uv download checksum verification failed"
  run_or_stage0 tar -xzf "$uv_archive" -C "$work"
  managed_uv="$work/uv-${uv_target}/uv"
  [ -x "$managed_uv" ] || fail "uv archive is missing its executable"
  run_or_stage0 export UV_PYTHON_INSTALL_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/chaos-engine/python"
  # set -e exits before fail() when uv itself returns non-zero.
  "$managed_uv" python install 3.14 --no-progress || {
    status=$?
    note_stage0
    exit "$status"
  }
  # A failing command substitution exits under set -e before fail().
  interp=$("$managed_uv" python find 3.14) || {
    status=$?
    note_stage0
    exit "$status"
  }
  [ -n "$interp" ] || fail "uv-managed Python was installed but not found"
  shim_dir="${XDG_DATA_HOME:-$HOME/.local/share}/chaos-engine/bin"
  run_or_stage0 mkdir -p "$shim_dir"
  run_or_stage0 ln -sfn "$interp" "$shim_dir/python3"
  run_or_stage0 ln -sfn "$interp" "$shim_dir/python"
  run_or_stage0 export PATH="$shim_dir:$PATH"
  run_or_stage0 mkdir -p "${project}/.chaos-engine-state"
  printf '%s\n' "$interp" > "${project}/.chaos-engine-state/hook-python" || {
    status=$?
    note_stage0
    exit "$status"
  }
fi
if [ -n "$interactive" ]; then
  if [ "${CI:-}" = "1" ] || [ -n "$yes_flag" ]; then
    interactive=
  elif [ ! -t 0 ]; then
    fail "a prompt is required. fix-next: pass --yes or --no-input"
  fi
fi
if [ -n "$interactive" ]; then
  controlling_tty="$(printf '%s/%s' /dev tty)"
  [ -r "$controlling_tty" ] || fail "interactive mode requires a usable controlling terminal"
  printf 'Confirm Download bootstrap from %s? [y/N] ' "$bootstrap_url" >"$controlling_tty"
  IFS= read -r answer <"$controlling_tty" || fail "interactive mode requires a usable controlling terminal"
  case $(printf '%s' "$answer" | tr '[:upper:]' '[:lower:]') in y|yes) ;; *) fail "ChaosEngine installation cancelled before Download bootstrap" ;; esac
fi
# Git Bash receives a Windows path in $0. CreateProcess does not rewrite backslashes.
script_path=$(printf '%s' "$0" | sed 's#\\#/#g')
case "$script_path" in
  */install.sh|install.sh)
    script_dir=$(CDPATH='' cd -- "$(dirname -- "$script_path")" && pwd)
    if [ -f "$script_dir/bootstrap.py" ] && is_chaos_engine_source_tree "$script_dir"; then
      cp "$script_dir/bootstrap.py" "$bootstrap"
    else
      fetch "$bootstrap" "$(fixture_url "$bootstrap_url")"
    fi
    ;;
  *)
    fetch "$bootstrap" "$(fixture_url "$bootstrap_url")"
    ;;
esac
if [ -n "$managed_uv" ]; then
  set -- "$managed_uv" run --no-project --managed-python "$bootstrap" --project "$project" --repository "$repository" --branch "$branch"
elif [ -n "$python_launcher" ]; then
  set -- "$python" -3 "$bootstrap" --project "$project" --repository "$repository" --branch "$branch"
else
  set -- "$python" "$bootstrap" --project "$project" --repository "$repository" --branch "$branch"
fi
[ -n "$with_maven_tools" ] && set -- "$@" --with-maven-tools
[ "$maven_tools_mode" = "docker" ] && set -- "$@" --maven-tools-mode docker
[ -n "$interactive" ] && set -- "$@" "--interactive"
[ -n "$verbose" ] && set -- "$@" "--verbose"
# shellcheck disable=SC2086
for forwarded_flag in $forwarded_flags; do
  set -- "$@" "$forwarded_flag"
done
set +e
"$@"
status=$?
set -e
if [ "$status" -ne 0 ]; then
  cause=""
  trace="${project}/.chaos-engine-state/install-trace.json"
  if [ -f "$trace" ]; then
    # Same interpreter that ran bootstrap. A host with only uv-managed Python
    # has no python3 on PATH, and a Windows Store stub named python3 is not it.
    cause_script='
import json, sys
path = sys.argv[1]
try:
    payload = json.load(open(path, encoding="utf-8"))
except (OSError, ValueError):
    raise SystemExit(0)
result = payload.get("result") if isinstance(payload, dict) else None
cause = result.get("cause") if isinstance(result, dict) else None
if isinstance(cause, str) and cause.strip():
    sys.stdout.write(cause.strip())
'
    if [ -n "$python_launcher" ]; then
      cause=$(py -3 -c "$cause_script" "$trace" 2>/dev/null || true)
    elif [ -n "$python" ]; then
      cause=$("$python" -c "$cause_script" "$trace" 2>/dev/null || true)
    elif [ -n "${managed_uv:-}" ]; then
      cause=$("$managed_uv" run --no-project --managed-python -c "$cause_script" "$trace" 2>/dev/null || true)
    fi
  fi
  if [ -n "$cause" ]; then
    echo "ChaosEngine bootstrap failed with exit ${status}: ${cause}" >&2
  else
    echo "ChaosEngine bootstrap failed with exit ${status}" >&2
  fi
  exit "$status"
fi
}
main "$@"
