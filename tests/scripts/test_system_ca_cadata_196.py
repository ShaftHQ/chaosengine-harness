"""Darwin keychain PEM must be str cadata. Bytes are DER to OpenSSL."""

from __future__ import annotations

import importlib.util
import ssl
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PEM = b"-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"
KEYCHAIN = "/System/Library/Keychains/SystemRootCertificates.keychain"


def _load():
    spec = importlib.util.spec_from_file_location(
        "bootstrap_system_ca_cadata_196", ROOT / "bootstrap.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("bootstrap")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _RecordingContext:
    def __init__(self) -> None:
        self.verify_mode = ssl.CERT_REQUIRED
        self.check_hostname = True
        self.calls: list[object] = []

    def load_verify_locations(self, cafile=None, capath=None, cadata=None):
        self.calls.append(cadata)


def _drive(monkeypatch: pytest.MonkeyPatch, module, payload: bytes, context: _RecordingContext):
    monkeypatch.setattr(module.sys, "platform", "darwin")
    monkeypatch.setattr(module.ssl, "create_default_context", lambda: context)
    monkeypatch.setattr(module.os.path, "isfile", lambda path: path == KEYCHAIN)

    def check_output(*_args, **_kwargs):
        return payload

    monkeypatch.setattr(module.subprocess, "check_output", check_output)


def test_pem_bytes_reach_cadata_as_str(monkeypatch: pytest.MonkeyPatch):
    module = _load()
    context = _RecordingContext()
    _drive(monkeypatch, module, PEM, context)
    loaded = module._system_ca_context()
    assert loaded is context
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert len(context.calls) == 1
    recorded = context.calls[0]
    assert isinstance(recorded, str)
    assert "BEGIN CERTIFICATE" in recorded


def test_non_pem_bytes_are_not_passed_as_cadata(monkeypatch: pytest.MonkeyPatch):
    module = _load()
    context = _RecordingContext()
    raw = b"not a certificate"
    _drive(monkeypatch, module, raw, context)
    module._system_ca_context()
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert raw not in context.calls
    assert context.calls == []
