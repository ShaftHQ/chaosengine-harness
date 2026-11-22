"""Shared installer helpers live in runtime.common and callers re-export them."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from runtime.common import (  # noqa: E402
    file_sha256,
    is_link_or_reparse,
    python_floor_message,
    runtime_module,
    valid_branch,
)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_installer_hosts_and_dependencies_reexport_common():
    install = _load("ce_install_common", ROOT / "install.py")
    hosts = _load("ce_hosts_common", ROOT / "runtime" / "hosts.py")
    dependencies = _load("ce_dependencies_common", ROOT / "runtime" / "dependencies.py")
    bootstrap = _load("ce_bootstrap_common", ROOT / "bootstrap.py")
    assert install.runtime_module is runtime_module
    assert install.file_sha256 is file_sha256
    assert install.is_link_or_reparse is is_link_or_reparse
    assert install.valid_branch is valid_branch
    assert install.python_floor_message is python_floor_message
    assert hosts.is_link_or_reparse is is_link_or_reparse
    assert dependencies.is_link_or_reparse is is_link_or_reparse
    assert bootstrap.runtime_module is runtime_module
    assert bootstrap.valid_branch is valid_branch
    assert bootstrap.python_floor_message is python_floor_message


def test_valid_branch_and_floor_message_keep_their_rules():
    assert valid_branch("main")
    assert not valid_branch("HEAD")
    assert not valid_branch("/leading")
    message = python_floor_message((3, 10, 0))
    assert "3.11" in message
    assert "3.10.0" in message


def test_file_sha256_hashes_the_bytes(tmp_path: Path):
    target = tmp_path / "note.txt"
    target.write_bytes(b"abc")
    assert file_sha256(target) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_palace_allows_a_project_local_knowledge_graph(tmp_path: Path):
    hosts = _load("ce_hosts_kg", ROOT / "runtime" / "hosts.py")
    palace = tmp_path / "mempalace"
    palace.mkdir()
    (palace / "knowledge_graph.sqlite3").write_bytes(b"")
    status = hosts.mempalace_directory_status(palace)
    assert "unrecognized" not in status.get("detail", "")
