"""Jobs consumes whole canonical conflict sections; no ledger, classification or action."""
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from scripts.lib import jobs_conflict_errors as C, jobs_health as J

NOW = datetime(2026, 10, 24, 22, tzinfo=timezone.utc)


def section(**changes):
    return {"findings": [{"key": "fixture:later", "kind": "DATA_ERROR", "summary": "Canonical data needs repair",
                           "clears_when": "The authoritative producer repairs its input", "owner": "fixture owner"},
                          {"key": "fixture:first", "kind": "DATA_ERROR", "summary": "Canonical priority is retained"}],
            "headline": "Backend-selected headline",
            "gap": None, "source": "fixture canonical engine", "as_of": NOW.isoformat(), "stale": False,
            "future_field": {"must": "remain unchanged"}, **changes}


def test_whole_section_identity_values_order_and_future_fields_are_preserved(tmp_path):
    expected = section()
    before = deepcopy(expected)
    calls = []
    def provider(*, root):
        calls.append(root)
        return expected
    result = C.get_data_errors(tmp_path, provider=provider)
    assert calls == [tmp_path]
    assert result["section"] is expected and expected == before
    assert result["unavailable_reason"] is None
    assert [r["key"] for r in result["section"]["findings"]] == ["fixture:later", "fixture:first"]


@pytest.mark.parametrize("changes", [
    {"headline": None},
    {"gap": {"reason": "Canonical ledger is unavailable"}, "headline": None, "findings": []},
    {"stale": True, "gap": "Engine comparison report is stale"},
    {"findings": [{"key": "future", "kind": "ENGINE_EXTENSION", "state": "DECIDED"}]},
])
def test_consumer_never_reclassifies_or_repairs_canonical_null_gap_stale_or_findings(tmp_path, changes):
    expected = section(**changes)
    assert C.get_data_errors(tmp_path, provider=lambda **_: expected)["section"] is expected


def test_production_delegation_imports_only_the_named_canonical_export(tmp_path, monkeypatch):
    expected = section()
    imported, called = [], []
    def importer(name):
        imported.append(name)
        return SimpleNamespace(data_error_section=lambda **kw: called.append(kw) or expected)
    monkeypatch.setattr(C, "import_module", importer)
    assert C.get_data_errors(tmp_path)["section"] is expected
    assert imported == ["scripts.lib.conflicts.api"] and called == [{"root": tmp_path}]


@pytest.mark.parametrize("error", [ModuleNotFoundError("fixture missing"), AttributeError("fixture missing export")])
def test_missing_engine_is_a_gap_and_never_zero_or_clear(tmp_path, monkeypatch, error):
    def importer(name):
        raise error
    monkeypatch.setattr(C, "import_module", importer)
    result = C.get_data_errors(tmp_path)
    assert result["section"] is None and result["unavailable_reason"]
    assert "total" not in result and "headline" not in result


@pytest.mark.parametrize("error", [OSError("private-path"), ValueError("private-value"), RuntimeError("private-receipt"), TypeError("bad-contract")])
def test_reader_failure_is_visible_without_exposing_exception_details(tmp_path, error):
    def provider(**kwargs):
        raise error
    result = C.get_data_errors(tmp_path, provider=provider)
    assert result["section"] is None and result["unavailable_reason"]
    assert str(error) not in result["unavailable_reason"]


@pytest.mark.parametrize("invalid", [None, [], {}, {"findings": [], "headline": None}])
def test_incomplete_contract_cannot_be_called_no_errors(tmp_path, invalid):
    result = C.get_data_errors(tmp_path, provider=lambda **_: invalid)
    assert result["section"] is None and "incomplete" in result["unavailable_reason"]


def test_jobs_reader_keeps_engine_data_errors_separate_from_execution_counts(tmp_path, monkeypatch):
    import scripts.cron_outage_watchdog as W
    import scripts.lib.scheduler_operations as S
    expected = section()
    monkeypatch.setattr(J, "_json", lambda *a, **k: {})
    monkeypatch.setattr(W, "collect", lambda *a: {"events": [], "successes": {}, "collection_gaps": []})
    monkeypatch.setattr(S, "read_run_ledger", lambda *a: ([], True, None))
    monkeypatch.setattr(C, "get_data_errors", lambda root: {"section": expected, "unavailable_reason": None})
    result = J._load(tmp_path, tmp_path/'registry.json', NOW)
    assert result["data_errors"]["section"] is expected
    assert result["summary"]["failed"] == 0 and result["summary"]["missed"] == 0
    assert result["rows"] == []
    assert all(r.get("source") == "job_execution" for r in result["incidents"])


@pytest.mark.parametrize("query", [{"filter": "all"}, {"filter": "attention"}, {"job": "absent", "offset": 7, "limit": 1}])
def test_public_jobs_filter_and_paging_preserve_whole_data_error_observation(tmp_path, monkeypatch, query):
    expected = section()
    report = {"rows": [], "data_errors": {"section": expected, "unavailable_reason": None}}
    monkeypatch.setattr(J, "_load", lambda *args: report)
    result = J.get_jobs_health(query, state_root=tmp_path, registry_path=tmp_path / "registry.json", now=NOW)
    assert result["data_errors"] is report["data_errors"]
    assert result["data_errors"]["section"] is expected
    assert result["rows"] == [] and result["total"] == 0


def test_consumer_calls_no_writer_when_a_read_raises_assertion(tmp_path):
    def forbidden(**kwargs):
        raise AssertionError("A writer must never be called by the Jobs reader")
    with pytest.raises(AssertionError, match="writer must never"):
        C.get_data_errors(tmp_path, provider=forbidden)
