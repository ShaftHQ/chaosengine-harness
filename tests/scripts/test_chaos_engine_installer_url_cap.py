"""The #129 URL-cap rule and the recorded anonymous measurement."""

from __future__ import annotations

import importlib.util
import json
import urllib.parse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MEASURE = ROOT / "experiments" / "installer-url-cap" / "measure.py"
RESULTS = ROOT / "experiments" / "installer-url-cap" / "results.json"


def load_measure():
    spec = importlib.util.spec_from_file_location("ce_installer_url_cap", MEASURE)
    if spec is None or spec.loader is None:
        raise ImportError(MEASURE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_probe_url_has_the_requested_length():
    measure = load_measure()
    url = measure.issues_new_url(6973)
    assert len(url) == 6973
    assert url.startswith(
        "https://github.com/ShaftHQ/chaosengine-harness/issues/new?template=chaos-engine-installer.yml"
    )


def test_choose_cap_keeps_7800_only_when_it_is_under_the_boundary():
    measure = load_measure()
    kept = measure.choose_cap([], current=7800)
    assert kept["chosen"] == 7800
    under = measure.choose_cap([20000], current=7800)
    assert under["chosen"] == 7800
    assert under["cap80"] == 16000
    lowered = measure.choose_cap([6973], current=7800)
    assert lowered["boundary"] == 6973
    assert lowered["chosen"] == int(6973 * 0.8)
    assert lowered["chosen"] < 7800


def test_recorded_anonymous_probe_matches_the_cap_rule():
    measure = load_measure()
    document = json.loads(RESULTS.read_text(encoding="utf-8"))
    anonymous = document["clients"]["anonymous"]
    decision = measure.choose_cap(list(anonymous["failureLengths"]))
    assert document["decision"]["chosen"] == decision["chosen"]
    assert document["decision"]["boundary"] == decision["boundary"]
    assert document["productCapUnchanged"] == 7800
    assert document["clients"]["signed-in-browser"]["measured"] is False
    boundary = decision["boundary"]
    assert isinstance(boundary, int)
    control = int(anonymous["controlStatus"])

    def codes(length: int) -> list[int]:
        return [int(row["status"]) for row in anonymous["samples"] if int(row["length"]) == length]

    assert any(measure.length_rejected(code, control) for code in codes(boundary))
    assert codes(boundary - 1)
    assert all(code == control for code in codes(boundary - 1))
    assert decision["chosen"] == int(boundary * 0.8)


def test_failure_payload_ratio_uses_the_shipped_encoder():
    measure = load_measure()
    rows = measure.payload_ratios(measure.load_bootstrap())
    short = next(row for row in rows if row["label"] == "short")
    huge = next(row for row in rows if row["label"] == "trace-50k")
    assert measure.load_bootstrap().MAX_ISSUE_URL_CHARS == 5578
    assert short["urlChars"] > short["rawChars"]
    assert short["urlChars"] <= 5578
    assert huge["urlChars"] <= 5578
    assert huge["urlChars"] < huge["rawChars"]
    assert huge["rawChars"] > 50_000


def test_fifty_kb_trace_keeps_required_fields_under_the_cap():
    measure = load_measure()
    bootstrap = measure.load_bootstrap()
    fields = {
        key: "required-value"
        for key in bootstrap.REQUIRED_ISSUE_FORM_FIELDS
    }
    fields["install_trace_snippet"] = "T" * 50_000
    url = bootstrap.encode_issue_form_url(
        "ShaftHQ/chaosengine-harness",
        "ChaosEngine install failed",
        fields,
    )
    assert len(url) <= bootstrap.MAX_ISSUE_URL_CHARS == 5578
    decoded = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    for key in bootstrap.REQUIRED_ISSUE_FORM_FIELDS:
        assert decoded.get(key), key
    assert "…truncated…" in urllib.parse.unquote(url)
