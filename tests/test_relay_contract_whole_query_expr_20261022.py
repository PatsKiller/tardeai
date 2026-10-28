"""2026-10-22: the contract probe sent a whole-query expression (`GET /path?{{ $json.query }}`) as the bare value
`contract-probe-run-…` (no key), which the relay correctly refuses as relay_bad_query. A whole-query expression is now
probed with a well-formed sample for its path (WHOLE_QUERY_EXPR_SAMPLES; empty since the retired release-train
workflow, its only user, was removed 2026-10-27).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import check_n8n_relay_contract as C  # noqa: E402


def _probe(monkeypatch, path, query):
    sent = []

    def fake_request(port, method, path_query, bearer, timeout=5.0):
        sent.append(path_query)
        return 200, {"state": "ok"}

    monkeypatch.setattr(C, "_request", fake_request)
    relay = C.ScratchRelay.__new__(C.ScratchRelay)
    relay.port, relay.bearer = 1, "x"
    ok, _ = relay.probe("GET", path, query)
    return ok, sent[0]


def test_whole_query_expression_uses_the_path_sample(monkeypatch):
    monkeypatch.setitem(C.WHOLE_QUERY_EXPR_SAMPLES, "/sample-path", "run_id=" + C.PROBE_EXPR_VALUE)
    ok, sent = _probe(monkeypatch, "/sample-path", "{{ $json.query }}")
    assert ok and sent == "/sample-path?run_id=" + C.PROBE_EXPR_VALUE


def test_no_retired_release_train_sample():
    assert "/release-train-window" not in C.WHOLE_QUERY_EXPR_SAMPLES


def test_keyed_expression_still_substitutes_the_value(monkeypatch):
    _, sent = _probe(monkeypatch, "/run-outcome", "run_id={{ encodeURIComponent($json.run_id) }}")
    assert sent == "/run-outcome?run_id=" + C.PROBE_EXPR_VALUE


def test_unknown_path_whole_query_expression_is_not_given_a_sample(monkeypatch):
    _, sent = _probe(monkeypatch, "/somewhere", "{{ $json.q }}")
    assert sent == "/somewhere?" + C.PROBE_EXPR_VALUE
