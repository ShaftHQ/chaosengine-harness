"""Filed installer issues carry the redacted evidence. TLS retries the OS store."""

from __future__ import annotations

import importlib.util
import io
import json
import ssl
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location(
        "bootstrap_issue_evidence", ROOT / "bootstrap.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("bootstrap")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class IssueEvidenceTest(unittest.TestCase):
    def test_markdown_contains_the_full_redacted_trace(self):
        module = _load()
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            state = project / ".chaos-engine-state"
            state.mkdir(parents=True)
            secret = "/home/person/project token=super-secret"
            trace = {"result": {"status": "failed"}, "trace": [[1.0, secret], [2.0, "FAIL Resolve source"]]}
            (state / "install-trace.json").write_text(json.dumps(trace), encoding="utf-8")
            fields = module.installer_issue_fields(
                "CE-INSTALL-FAILED",
                urllib.error.URLError(
                    "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: "
                    "unable to get local issuer certificate"
                ),
                None,
                project,
                "not available",
                "not available",
            )
        body = module.issue_form_markdown(fields)
        self.assertIn("FAIL Resolve source", body)
        self.assertIn("<home>/project", body)
        self.assertNotIn("/home/person", body)
        self.assertNotIn("super-secret", body)
        snippet = body.split("### Install trace snippet", 1)[1]
        self.assertIn('"<home>/project token=<redacted>"', snippet)
        self.assertIn("CERTIFICATE_VERIFY_FAILED", body)
        self.assertIn("openssl:", body)
        self.assertNotIn("attach", body.casefold())

    def test_certificate_failure_retries_once_with_a_verifying_context(self):
        module = _load()
        calls = []

        def urlopen(request, timeout=None, context=None):
            calls.append(context)
            if context is None:
                raise urllib.error.URLError(
                    ssl.SSLCertVerificationError("CERTIFICATE_VERIFY_FAILED")
                )
            self.assertEqual(ssl.CERT_REQUIRED, context.verify_mode)
            self.assertTrue(context.check_hostname)
            return io.BytesIO(b"ok")

        context = ssl.create_default_context()
        with mock.patch.object(module.urllib.request, "urlopen", urlopen), mock.patch.object(
            module, "_system_ca_context", return_value=context
        ):
            opened = module._open_request(module.urllib.request.urlopen, "https://example.test", 5)
        self.assertEqual(b"ok", opened.read())
        self.assertEqual([None, context], calls)

    def test_other_url_errors_do_not_retry(self):
        module = _load()
        calls = []

        def urlopen(request, timeout=None, context=None):
            calls.append(context)
            raise urllib.error.URLError("timed out")

        with mock.patch.object(module.urllib.request, "urlopen", urlopen):
            with self.assertRaises(urllib.error.URLError):
                module._open_request(module.urllib.request.urlopen, "https://example.test", 5)
        self.assertEqual([None], calls)

    def test_a_caller_opener_is_not_replaced(self):
        module = _load()

        def opener(*_args, **_kwargs):
            raise urllib.error.URLError(
                ssl.SSLCertVerificationError("CERTIFICATE_VERIFY_FAILED")
            )

        with self.assertRaises(urllib.error.URLError):
            module._open_request(opener, "https://example.test", 5)
