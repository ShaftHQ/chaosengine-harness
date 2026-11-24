"""Read-only SHAFT project detector. Never runs Maven or Gradle."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

NAMES = ("shaft-engine-users", "shaft-core-developers")
USER = "shaft-engine-users"
CORE = "shaft-core-developers"
DENIALS = ".chaos-engine-state/addon-denials.json"
TAG = re.compile(r"^\d+\.\d+\.\d{8}$")
COORD = re.compile(
    r"io\.github\.shafthq\s*:\s*([A-Za-z0-9_.*-]+)(?:\s*:\s*([^\"'\s,)\]]+))?",
    re.IGNORECASE,
)
_TAG = re.compile(r"<([A-Za-z0-9_.-]+)>\s*([^<]*?)\s*</\1>", re.S)


def descriptor() -> dict[str, object]:
    path = Path(__file__).resolve().parent / "source.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("CE-INSTALL-FAILED: shaft source descriptor is invalid")
    return document


def no_auto(environ: dict[str, str] | None = None) -> bool:
    source = os.environ if environ is None else environ
    return str(source.get("CHAOS_ENGINE_NO_AUTO_ADDONS", "")).strip() == "1"


def _canon(names: set[str] | None) -> set[str]:
    aliases = {name.replace("-", ""): name for name in NAMES}
    found: set[str] = set()
    for name in names or ():
        found.add(name if name in NAMES else aliases.get(name.replace("-", ""), name))
    return found


def denials_path(project: Path) -> Path:
    return Path(project) / DENIALS


def denied(project: Path) -> set[str]:
    path = denials_path(project)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return set()
    values = document.get("denied") if isinstance(document, dict) else None
    if not isinstance(values, list):
        return set()
    return {item for item in values if item in NAMES}


def record_flags(project: Path, requested: set[str] | None, removed: set[str] | None) -> None:
    """Remember --without until a later --with. The file lives outside the payload."""
    requested, removed = _canon(requested), _canon(removed)
    current = denied(project)
    if USER in removed:
        current.add(USER)
    if USER in requested or CORE in requested:
        current.discard(USER)
    path = denials_path(project)
    if not current and not path.is_file():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"denied": sorted(current)}, indent=2) + "\n", encoding="utf-8")


def _strip_xml_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


def _strip_line_comments(text: str, *, hash_comment: bool = False) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    kept = []
    for line in text.splitlines():
        if hash_comment:
            line = line.split("#", 1)[0]
        else:
            line = re.sub(r"//.*", "", line)
        kept.append(line)
    return "\n".join(kept)


def _tag(block: str, name: str) -> str:
    match = re.search(rf"<{name}>\s*([^<]*?)\s*</{name}>", block, re.S)
    return match.group(1).strip() if match else ""


def _own_artifact(text: str) -> str:
    without_parent = re.sub(r"<parent\b[^>]*>.*?</parent>", "", text, flags=re.S)
    return _tag(without_parent, "artifactId")


def _properties(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for block in re.findall(r"<properties\b[^>]*>(.*?)</properties>", text, flags=re.S):
        for match in _TAG.finditer(block):
            found[match.group(1)] = match.group(2).strip()
    return found


def _modules(text: str) -> list[str]:
    found = []
    for block in re.findall(r"<modules\b[^>]*>(.*?)</modules>", text, flags=re.S):
        found.extend(re.findall(r"<module>\s*([^<]+?)\s*</module>", block))
    return found


def _dependencies(text: str) -> list[tuple[str, str, str]]:
    rows = []
    for block in re.findall(r"<dependency\b[^>]*>(.*?)</dependency>", text, flags=re.S):
        rows.append((_tag(block, "groupId"), _tag(block, "artifactId"), _tag(block, "version")))
    return rows


def iter_poms(project: Path) -> list[tuple[Path, str]]:
    """Root POM plus module POMs through depth 3, at most 50 files. Depth 4 is not read."""
    project = Path(project)
    found: list[tuple[Path, str]] = []

    def add(path: Path, depth: int, props: dict[str, str]) -> None:
        if len(found) >= 50 or depth > 3 or not path.is_file():
            return
        try:
            text = _strip_xml_comments(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            return
        found.append((path, text))
        inherited = dict(props)
        inherited.update(_properties(text))
        for module in _modules(text):
            add(path.parent / module / "pom.xml", depth + 1, inherited)

    add(project / "pom.xml", 1, {})
    return found


def _artifact_matches(artifact: str, rules: dict[str, object]) -> bool:
    if artifact in {str(item) for item in rules.get("artifactIds", [])}:
        return True
    return any(artifact.startswith(str(prefix)) for prefix in rules.get("artifactPrefixes", []))


def _resolve_token(token: str, props: dict[str, str]) -> str:
    match = re.fullmatch(r"\$\{([^}]+)\}", token or "")
    if match is None:
        return token
    return props.get(match.group(1), "")


def _known(token: str) -> bool:
    return token in {"latest", "main"} or TAG.fullmatch(token or "") is not None


def detect(project: Path) -> dict[str, object]:
    """Return kind core|user|none, the winning version, where it was found, and add-on names."""
    project = Path(project)
    rules = descriptor()
    if _is_core(project, rules):
        return {
            "kind": "core",
            "version": "local",
            "detectedFrom": "shaft-skills",
            "addons": list(NAMES),
            "distribution": "repository",
        }
    candidates: list[tuple[int, str, str]] = []
    props: dict[str, str] = {}
    for path, text in iter_poms(project):
        props.update(_properties(text))
        # Parent files on disk contribute properties too.
        props.update(_parent_properties(path, text))
        for group, artifact, version in _dependencies(text):
            if group not in {str(item) for item in rules.get("groupIds", [])}:
                continue
            if not _artifact_matches(artifact, rules):
                continue
            resolved = _resolve_token(version, props)
            rank = 0 if _known(resolved) else 1
            candidates.append((rank, resolved or version, path.name))
    for path in (
        project / "build.gradle",
        project / "build.gradle.kts",
        project / "gradle" / "libs.versions.toml",
    ):
        if not path.is_file():
            continue
        text = _strip_line_comments(
            path.read_text(encoding="utf-8", errors="replace"),
            hash_comment=path.suffix == ".toml",
        )
        versions = _toml_versions(text) if path.suffix == ".toml" else {}
        for match in COORD.finditer(text):
            artifact, version = match.group(1), (match.group(2) or "").strip().strip('"').strip("'")
            if not _artifact_matches(artifact, rules):
                continue
            if version in versions:
                version = versions[version]
            rank = 0 if _known(version) else 1
            candidates.append((rank, version, path.relative_to(project).as_posix()))
        if path.suffix == ".toml":
            for line in text.splitlines():
                if "io.github.shafthq" not in line.lower():
                    continue
                ref_match = re.search(r'version\.ref\s*=\s*"([^"]+)"', line)
                if ref_match is None:
                    continue
                version = versions.get(ref_match.group(1), "")
                if not version:
                    continue
                rank = 0 if _known(version) else 1
                candidates.append((rank, version, path.relative_to(project).as_posix()))
    if not candidates:
        return {"kind": "none", "version": "", "detectedFrom": "", "addons": [], "distribution": ""}
    candidates.sort(key=lambda item: (item[0], 0 if _known(item[1]) else 1))
    _rank, version, origin = candidates[0]
    return {
        "kind": "user",
        "version": version,
        "detectedFrom": origin,
        "addons": [USER],
        "distribution": "portable",
    }


def _toml_versions(text: str) -> dict[str, str]:
    versions: dict[str, str] = {}
    in_versions = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_versions = stripped == "[versions]"
            continue
        if in_versions and "=" in stripped:
            key, _, value = stripped.partition("=")
            versions[key.strip()] = value.strip().strip('"').strip("'")
    return versions


def _parent_properties(path: Path, text: str) -> dict[str, str]:
    props: dict[str, str] = {}
    for block in re.findall(r"<parent\b[^>]*>(.*?)</parent>", text, flags=re.S):
        relative = _tag(block, "relativePath") or "../pom.xml"
        parent = (path.parent / relative).resolve()
        if parent.is_dir():
            parent = parent / "pom.xml"
        if not parent.is_file():
            continue
        try:
            parent_text = _strip_xml_comments(parent.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        props.update(_properties(parent_text))
    return props


def _is_core(project: Path, rules: dict[str, object]) -> bool:
    profile = project / "shaft-skills" / "ce-pack" / "profile.json"
    entry = project / "shaft-skills" / "ce-pack" / "entrypoint.md"
    if profile.is_file() and entry.is_file():
        try:
            document = json.loads(profile.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            document = {}
        if isinstance(document, dict) and document.get("repository") == rules.get("coreRepository"):
            return True
    pom = project / "pom.xml"
    if not pom.is_file():
        return False
    text = _strip_xml_comments(pom.read_text(encoding="utf-8", errors="replace"))
    own = _own_artifact(text)
    return own in {str(item) for item in rules.get("coreArtifactIds", [])}


def shaft_auto(project: Path, found: set[str]) -> tuple[set[str], set[str]]:
    """Add-ons reidentify should select or drop. Denial and --no-auto-addons win."""
    if no_auto():
        return set(), set()
    if USER in denied(project):
        return set(), set(NAMES) & found
    info = detect(project)
    wanted = set(info["addons"]) & found
    if info["kind"] == "none":
        return set(), set(NAMES) & found
    return wanted, (set(NAMES) & found) - wanted


def apply_identity(
    project: Path,
    found: dict[str, dict[str, object]],
    select: set[str],
    drop: set[str],
    removed: set[str],
    requested: set[str],
) -> tuple[set[str], set[str], set[str]]:
    names = set(found)
    requested, removed = _canon(requested), _canon(removed)
    # Keeping the core add-on while removing the user add-on it requires is refused
    # by the catalog. Do not rewrite that into a silent drop, and do not remember it.
    if USER in removed and CORE in requested:
        return set(select), set(drop), removed
    record_flags(project, requested, removed)
    if USER in removed:
        removed = set(removed) | set(NAMES)
        if detect(project)["kind"] == "core":
            print(
                "ChaosEngine: --without-shaft-engine-users also drops shaft-core-developers",
                flush=True,
            )
        # The drop is already applied. Leaving the names in `removed` makes
        # resolve fail closed when this checkout has not materialized them.
        return set(select) - set(NAMES), set(drop) | (set(NAMES) & names), set(removed) - set(NAMES)
    extra_select, extra_drop = shaft_auto(project, names)
    return set(select) | extra_select, set(drop) | extra_drop, removed


def names_to_drop(project: Path) -> set[str]:
    if no_auto():
        return set()
    if USER in denied(project):
        return set(NAMES)
    if detect(project)["kind"] == "none":
        return set(NAMES)
    return set(NAMES) - set(detect(project)["addons"])


def doctor_note(project: Path) -> dict[str, str] | None:
    """Warn on a user-project version mismatch, or when skills were never installed.

    Kind ``none`` and ``core`` stay quiet. A denied user project stays quiet
    when the receipt tag is missing. A known version that differs from the
    receipt tag still warns. ``install.py`` loads this function.
    """
    info = detect(Path(project))
    if info.get("kind") != "user":
        return None
    version = str(info.get("version") or "")
    installed = str(_receipt(Path(project)).get("tag") or "")
    if _known(version) and installed and installed != version:
        warning = f"SHAFT project version {version} differs from installed skills {installed}"
        fix = "fix-next: rerun the install one-liner or pass --shaft-skills-version " + version
        return {"warning": warning, "fixNext": fix}
    if installed or USER in denied(Path(project)):
        return None
    warning = (
        "SHAFT skills are not installed. "
        "Run the installer or pass --with-shaft-engine-users."
    )
    fix = "fix-next: rerun the installer or pass --with-shaft-engine-users"
    return {"warning": warning, "fixNext": fix}


def _receipt(project: Path) -> dict[str, object]:
    path = Path(project) / ".chaos-engine" / "addons" / USER / "receipt.json"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return document if isinstance(document, dict) else {}
