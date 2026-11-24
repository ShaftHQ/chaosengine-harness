"""Install SHAFT skills with the per-file plan, cache, and kept-edits rules."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import urllib.error
import urllib.parse
from pathlib import Path

import bootstrap


def _load_detect():
    path = Path(__file__).resolve().parent / "detect.py"
    spec = importlib.util.spec_from_file_location("ce_shaft_detect", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"CE-INSTALL-FAILED: missing {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


detect = _load_detect()

REPOSITORY = "ShaftHQ/SHAFT_ENGINE"
TREE_PREFIX = "shaft-skills"
USER = detect.USER
CORE = detect.CORE
ADDON_JSON = {
    USER: {
        "schemaVersion": 1,
        "kind": "addon",
        "name": USER,
        "description": "SHAFT skills for a project that depends on SHAFT_ENGINE.",
        "useWhen": "The project declares an io.github.shafthq SHAFT dependency.",
        "requires": [],
    },
    CORE: {
        "schemaVersion": 1,
        "kind": "addon",
        "name": CORE,
        "description": "SHAFT skills for a checkout of ShaftHQ/SHAFT_ENGINE.",
        "useWhen": "This directory is the SHAFT_ENGINE repository.",
        "requires": [USER],
        "distribution": "repository",
    },
}


def _origin(url: str) -> str:
    origin = os.environ.get("CHAOS_ENGINE_SHAFT_FIXTURE_ORIGIN", "").strip().rstrip("/")
    if not origin:
        return url
    for prefix in (
        "https://raw.githubusercontent.com",
        "https://api.github.com",
        "https://codeload.github.com",
        "https://github.com",
    ):
        if url.startswith(prefix):
            return origin + url[len(prefix) :]
    return url


def _read(opener, url: str) -> bytes:
    """Fetch one SHAFT URL.

    ``CHAOS_ENGINE_SHAFT_FIXTURE_ORIGIN`` redirects this pack's downloads.
    The harness fixture origin must not capture them when that variable is
    unset, so a local-clone harness install can still pin skills from GitHub.
    """
    if os.environ.get("CHAOS_ENGINE_SHAFT_FIXTURE_ORIGIN", "").strip():
        return bootstrap._read_url_bytes(opener, _origin(url))
    return bootstrap._read_url_bytes(opener, url, rewrite=False)


def _json(opener, url: str) -> dict:
    document = json.loads(_read(opener, url).decode("utf-8"))
    if not isinstance(document, dict):
        raise ValueError("CE-INSTALL-FAILED: SHAFT response is invalid")
    return document


def _refuse(ref: str) -> None:
    if ref in {"", "latest", "main"} or detect.TAG.fullmatch(ref):
        if ref and not bootstrap.valid_branch(ref):
            raise ValueError(f"CE-INSTALL-FAILED: unsafe shaft ref {ref}")
        return
    raise ValueError(f"CE-INSTALL-FAILED: unsafe shaft ref {ref}")


def _refused_version(version: str) -> bool:
    """Path traversal and a dotted ``10.4.x`` ref are refused. SNAPSHOT and ranges are not."""
    if not version:
        return False
    if ".." in version or "\\" in version or version.startswith(("/", "-")) or "//" in version:
        return True
    return re.fullmatch(r"\d+\.\d+\.x", version, flags=re.IGNORECASE) is not None


def _latest_tag(opener) -> str:
    document = _json(opener, f"https://api.github.com/repos/{REPOSITORY}/releases/latest")
    tag = str(document.get("tag_name") or "").lstrip("v")
    _refuse(tag)
    if not detect.TAG.fullmatch(tag):
        raise ValueError("CE-INSTALL-FAILED: releases/latest is not a SHAFT tag")
    return tag


def _warn_latest(version: str, tag: str) -> None:
    print(
        f"warning: SHAFT version {version} is not a release tag; using {tag}. "
        "Override with --shaft-skills-version.",
        flush=True,
    )


def _stored(project: Path) -> dict:
    path = project / ".chaos-engine" / "addons" / USER / "receipt.json"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return document if isinstance(document, dict) else {}


def doctor_note(project: Path) -> dict[str, str] | None:
    """Warn on a user-project version mismatch, or when skills were never installed.

    Kind ``none`` and ``core`` stay quiet. A denied user project
    (``--without-shaft-engine-users``) stays quiet when the receipt tag is
    missing. A known version that differs from the receipt tag still warns.
    """
    info = detect.detect(Path(project))
    if info.get("kind") != "user":
        return None
    version = str(info.get("version") or "")
    installed = str(_stored(Path(project)).get("tag") or "")
    if detect._known(version) and installed and installed != version:
        warning = f"SHAFT project version {version} differs from installed skills {installed}"
        fix = "fix-next: rerun the install one-liner or pass --shaft-skills-version " + version
        return {"warning": warning, "fixNext": fix}
    if installed or detect.USER in detect.denied(Path(project)):
        return None
    warning = (
        "SHAFT skills are not installed. "
        "Run the installer or pass --with-shaft-engine-users."
    )
    fix = "fix-next: rerun the installer or pass --with-shaft-engine-users"
    return {"warning": warning, "fixNext": fix}


def resolve_pin(project: Path, info: dict[str, object], opener, override: str) -> tuple[str, str]:
    """Return ``(tag, commit)``. Unknown versions reuse releases/latest until they change."""
    version = str(info.get("version") or "")
    chosen = (override or os.environ.get("CHAOS_ENGINE_SHAFT_SKILLS_VERSION") or "").strip()
    if chosen:
        if chosen == "latest":
            tag = _latest_tag(opener)
        else:
            _refuse(chosen)
            tag = chosen
    elif detect._known(version):
        _refuse(version)
        tag = version
    else:
        if _refused_version(version):
            raise ValueError(f"CE-INSTALL-FAILED: unsafe shaft ref {version}")
        receipt = _stored(project)
        if receipt.get("version") == version and detect.TAG.fullmatch(str(receipt.get("tag") or "")):
            tag = str(receipt["tag"])
        else:
            tag = _latest_tag(opener)
            _warn_latest(version or "(missing)", tag)
    if tag != "main":
        try:
            _refuse(tag)
        except ValueError:
            raise
    commit = _commit_for(opener, tag)
    if commit is None:
        fallback = _latest_tag(opener)
        _warn_latest(tag, fallback)
        commit = _commit_for(opener, fallback)
        if commit is None:
            raise ValueError(f"CE-INSTALL-FAILED: SHAFT tag {tag} does not resolve")
        tag = fallback
    return tag, commit


def _commit_for(opener, tag: str) -> str | None:
    if tag == "main":
        url = f"https://api.github.com/repos/{REPOSITORY}/git/ref/heads/main"
    else:
        url = f"https://api.github.com/repos/{REPOSITORY}/git/ref/tags/{urllib.parse.quote(tag, safe='')}"
    try:
        document = _json(opener, url)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise
    obj = document.get("object")
    if not isinstance(obj, dict):
        raise ValueError("CE-INSTALL-FAILED: SHAFT ref is invalid")
    sha = str(obj.get("sha") or "")
    kind = str(obj.get("type") or "")
    if kind == "tag":
        peeled = _json(opener, f"https://api.github.com/repos/{REPOSITORY}/git/tags/{sha}")
        inner = peeled.get("object")
        sha = str(inner.get("sha") or "") if isinstance(inner, dict) else ""
    if bootstrap.COMMIT.fullmatch(sha) is None:
        raise ValueError("CE-INSTALL-FAILED: SHAFT commit is invalid")
    return sha


def _tree(opener, sha: str) -> list[dict]:
    if "recursive=1" in sha:
        raise ValueError("CE-INSTALL-FAILED: recursive root listing is not used")
    url = f"https://api.github.com/repos/{REPOSITORY}/git/trees/{sha}"
    document = _json(opener, url)
    tree = document.get("tree")
    if document.get("truncated") is True or not isinstance(tree, list):
        raise ValueError("CE-INSTALL-FAILED: SHAFT tree listing is incomplete")
    rows = []
    for entry in tree:
        if isinstance(entry, dict):
            rows.append(entry)
    return rows


def _walk(opener, sha: str, prefix: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for entry in _tree(opener, sha):
        name = str(entry.get("path") or "")
        if not name or name in {".", ".."} or "/" in name:
            raise ValueError(f"CE-INSTALL-FAILED: unsafe shaft path {name}")
        relative = f"{prefix}/{name}" if prefix else name
        kind = entry.get("type")
        child = str(entry.get("sha") or "")
        if kind == "tree":
            found.extend(_walk(opener, child, relative))
        elif kind == "blob":
            found.append((relative, child))
        else:
            raise ValueError(f"CE-INSTALL-FAILED: unsupported shaft entry {relative}")
    return found


# The consumer offer lives beside the generated addon manifest, not in the skill tree.
USER_POST_INSTALL = "ce-addons/shaft-engine-users/post-install.json"


def _classify(relative: str, *, core: bool) -> tuple[str, str] | None:
    """Return ``(addon, installed path)``. Core checkouts do not get the consumer offer."""
    if relative == USER_POST_INSTALL:
        if core:
            return None
        return USER, "post-install.json"
    name = _addon_for(relative)
    if name is None:
        return None
    return name, relative


def _addon_for(relative: str) -> str | None:
    if relative.endswith("/post-install.json") or relative == "post-install.json":
        return None
    if relative.startswith("ce-addons/") or relative.startswith("scripts/") or relative.startswith("shaft-upgrader/"):
        return None
    if relative.startswith("ce-pack/"):
        return CORE
    name = relative.split("/", 1)[0]
    if name.startswith("shaft-") or relative.startswith("references/"):
        return USER
    return None


def _local_rows(project: Path) -> list[tuple[str, str, bytes]]:
    root = project / TREE_PREFIX
    rows = []
    if not root.is_dir():
        return rows
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            if path.is_symlink():
                raise ValueError(f"CE-INSTALL-FAILED: link: {path}")
            continue
        relative = path.relative_to(root).as_posix()
        if _addon_for(relative) is None:
            continue
        rows.append((relative, "", path.read_bytes()))
    return rows


def _remote_rows(opener, commit: str) -> list[tuple[str, str]]:
    root = _tree(opener, commit)
    skills = next((entry for entry in root if entry.get("path") == TREE_PREFIX and entry.get("type") == "tree"), None)
    if skills is None:
        raise ValueError("CE-INSTALL-FAILED: shaft-skills tree is missing")
    return _walk(opener, str(skills.get("sha") or ""), "")


def _installed_index(project: Path, name: str) -> tuple[dict[str, str], dict[str, str]]:
    root = project / ".chaos-engine" / "addons" / name
    receipt = _stored(project) if name == USER else {}
    files = receipt.get("files") if isinstance(receipt.get("files"), dict) else {}
    base = {str(key): str(value) for key, value in files.items()}
    local: dict[str, str] = {}
    if not root.is_dir():
        return base, local
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"CE-INSTALL-FAILED: link: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative in {"addon.json", "receipt.json"}:
            continue
        local[relative] = bootstrap.payload_sha256(path.read_bytes())
    return base, local


def _shaft_cache(blob_sha: str) -> Path:
    return bootstrap.core_blob_cache_root().parent / f"shaft-{blob_sha}"


def _cached_shaft(blob_sha: str) -> bytes | None:
    path = _shaft_cache(blob_sha)
    try:
        if path.is_file() and not path.is_symlink():
            content = path.read_bytes()
        else:
            return None
    except OSError:
        return None
    if bootstrap.git_blob_sha1(content) == blob_sha or bootstrap.git_blob_sha1(bootstrap.normalize_payload(content)) == blob_sha:
        return content
    return None


def _store_shaft(blob_sha: str, content: bytes) -> None:
    path = _shaft_cache(blob_sha)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(content)
    os.replace(temporary, path)


def _matches_blob(content: bytes, blob_sha: str) -> bool:
    return blob_sha in {
        bootstrap.git_blob_sha1(content),
        bootstrap.git_blob_sha1(bootstrap.normalize_payload(content)),
    }


def _fetch_blob(opener, commit: str, relative: str, blob_sha: str, *, offline: bool) -> tuple[bytes, bool]:
    cached = _cached_shaft(blob_sha)
    if cached is not None:
        return cached, False
    if offline:
        raise urllib.error.URLError(f"offline cache miss: {relative}")
    url = f"https://raw.githubusercontent.com/{REPOSITORY}/{commit}/{TREE_PREFIX}/{relative}"
    content = _read(opener, url)
    if not _matches_blob(content, blob_sha):
        raise ValueError(f"CE-INSTALL-FAILED: blob hash mismatch: {relative}")
    _store_shaft(blob_sha, content)
    bootstrap.store_cached_blob(bootstrap.payload_sha256(content), content)
    return content, True


def _copy_previous(project: Path, source: Path, names: tuple[str, ...]) -> None:
    for name in names:
        root = project / ".chaos-engine" / "addons" / name
        if not root.is_dir():
            continue
        destination = source / "addons" / name
        if destination.exists():
            shutil.rmtree(destination)
        destination.mkdir(parents=True, exist_ok=True)
        for path in sorted(root.rglob("*")):
            if path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def _keep_edited(project: Path, names: tuple[str, ...]) -> None:
    stamp = bootstrap.time.strftime("%Y%m%dT%H%M%SZ", bootstrap.time.gmtime())
    for name in names:
        base, local = _installed_index(project, name)
        root = project / ".chaos-engine" / "addons" / name
        for relative, digest in local.items():
            if base.get(relative) in {None, digest}:
                continue
            source_path = root / relative
            if source_path.is_file():
                bootstrap._copy_kept(project, stamp, f"addons/{name}/{relative}", source_path)


def _write_addon(source: Path, name: str, files: dict[str, bytes], receipt: dict[str, object]) -> None:
    root = source / "addons" / name
    root.mkdir(parents=True, exist_ok=True)
    for relative, content in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(bootstrap.normalize_payload(content))
    (root / "addon.json").write_text(json.dumps(ADDON_JSON[name], indent=2) + "\n", encoding="utf-8")
    if name == USER:
        (root / "receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _quiet() -> bool:
    return os.environ.get("CHAOS_ENGINE_QUIET") == "1"


def prepare(project: Path, source: Path, opener, *, requested: set[str] | None = None, removed: set[str] | None = None) -> dict[str, object]:
    """Put selected SHAFT add-ons into ``source/addons`` before the core publish."""
    project = Path(project)
    source = Path(source)
    prepare.downloads = 0  # type: ignore[attr-defined]
    requested = detect._canon(requested)
    removed = detect._canon(removed)
    # The catalog must see both add-ons to refuse this pair. Do not remember it.
    refused = USER in removed and CORE in requested
    if not refused:
        detect.record_flags(project, requested, removed)
    explicit = requested & set(detect.NAMES)
    if not refused and (USER in removed or (USER in detect.denied(project) and USER not in requested)):
        _keep_edited(project, detect.NAMES)
        return {"status": "opt-out", "downloads": 0}
    if detect.no_auto() and not explicit:
        _copy_previous(project, source, detect.NAMES)
        return {"status": "disabled", "downloads": 0}
    info = detect.detect(project)
    if info["kind"] == "none" and not explicit:
        if (project / ".chaos-engine" / "addons" / USER).is_dir():
            _keep_edited(project, detect.NAMES)
        return {"status": "absent", "downloads": 0}
    dry_run = os.environ.get("CHAOS_ENGINE_DRY_RUN") == "1"
    offline = os.environ.get("CHAOS_ENGINE_OFFLINE") == "1"
    try:
        return _install_into(project, source, opener, info, dry_run=dry_run, offline=offline)
    except ValueError as error:
        if str(error).startswith("CE-INSTALL-FAILED"):
            raise
        print(f"warning: SHAFT skills were not updated ({error}). The previous add-on tree was kept.", flush=True)
        _copy_previous(project, source, detect.NAMES)
        return {"status": "kept", "downloads": 0}
    except (OSError, urllib.error.URLError) as error:
        print(f"warning: SHAFT skills were not updated ({error}). The previous add-on tree was kept.", flush=True)
        _copy_previous(project, source, detect.NAMES)
        return {"status": "kept", "downloads": int(getattr(prepare, "downloads", 0))}


def _install_into(project, source, opener, info, *, dry_run: bool, offline: bool) -> dict[str, object]:
    override = (os.environ.get("CHAOS_ENGINE_SHAFT_SKILLS_VERSION") or "").strip()
    local = info["kind"] == "core"
    if local:
        tag, commit = "local", "local"
        listed = _local_rows(project)
    else:
        tag, commit = resolve_pin(project, info, opener, override)
        listed = [(relative, blob, b"") for relative, blob in _remote_rows(opener, commit)]
    grouped: dict[str, list[tuple[str, str, bytes, str]]] = {USER: [], CORE: []}
    core = info["kind"] == "core"
    for relative, blob, content in listed:
        mapped = _classify(relative, core=core)
        if mapped is None:
            continue
        name, stored = mapped
        if not core and name == CORE:
            continue
        grouped[name].append((stored, blob, content, relative))
    user_count = len(grouped[USER])
    origin = str(info.get("detectedFrom") or "pom.xml")
    if dry_run:
        if not _quiet():
            print(f"SHAFT {tag} from {origin} → {USER} @ {tag} ({user_count} files)", flush=True)
        return {"status": "dry-run", "downloads": 0, "tag": tag, "files": user_count}
    downloads = 0
    written: dict[str, dict[str, bytes]] = {}
    user_counts = {"updated": 0, "unchanged": 0}
    indexes: dict[str, dict[str, str]] = {}
    for name, entries in grouped.items():
        if not entries:
            continue
        base_map, installed_sha = _installed_index(project, name)
        payloads: dict[str, bytes] = {}
        remote_files: dict[str, dict[str, object]] = {}
        compare_local: dict[str, str] = {}
        for stored, blob, content, remote_relative in entries:
            installed_path = project / ".chaos-engine" / "addons" / name / stored
            if local:
                payloads[stored] = content
                digest = bootstrap.payload_sha256(content)
                compare_local[stored] = digest
            else:
                current = b""
                matched = False
                if installed_path.is_file() and not installed_path.is_symlink():
                    current = installed_path.read_bytes()
                    matched = _matches_blob(current, blob)
                if matched:
                    payloads[stored] = current
                else:
                    fetched, hit = _fetch_blob(opener, commit, remote_relative, blob, offline=offline)
                    payloads[stored] = fetched
                    if hit:
                        downloads += 1
                digest = bootstrap.payload_sha256(payloads[stored])
            remote_files[stored] = {"sha256": digest, "gitBlobSha1": blob or "0" * 40, "mode": "100644"}
            indexes.setdefault(name, {})[stored] = digest
        if local:
            # Working-tree bytes are the install. A difference from the installed copy is an edit.
            actions = bootstrap.plan_file_actions(remote_files, installed_sha, compare_local)
        else:
            # Receipt hashes are the base. On-disk hashes are the local edit.
            actions = bootstrap.plan_file_actions(remote_files, base_map, installed_sha)
        edited = [str(row["path"]) for row in actions if row["action"] == "edited"]
        if os.environ.get("CHAOS_ENGINE_KEEP_EDITS") == "1" and edited:
            raise bootstrap.SyncKeepEdits([f"addons/{name}/{path}" for path in edited])
        if os.environ.get("CHAOS_ENGINE_FORCE") != "1":
            stamp = bootstrap.time.strftime("%Y%m%dT%H%M%SZ", bootstrap.time.gmtime())
            for path in edited:
                installed_path = project / ".chaos-engine" / "addons" / name / path
                if installed_path.is_file() and not installed_path.is_symlink():
                    bootstrap._copy_kept(project, stamp, f"addons/{name}/{path}", installed_path)
        counts = bootstrap.sync_counts(actions)
        if name == USER:
            user_counts = counts
        written[name] = payloads
    prepare.downloads = downloads  # type: ignore[attr-defined]
    receipt = {
        "version": str(info.get("version") or tag),
        "tag": tag,
        "commit": commit,
        "detectedFrom": origin,
        "files": indexes.get(USER, {}),
    }
    for name, files in written.items():
        _write_addon(source, name, files, receipt)
    if not _quiet():
        print(
            f"SHAFT skills {tag} ({origin}): {user_counts['updated']} updated, {user_counts['unchanged']} unchanged",
            flush=True,
        )
    return {"status": "installed", "downloads": downloads, "tag": tag, "files": user_count, "receipt": receipt}
