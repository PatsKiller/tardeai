"""Suggestion company-fact scope uses the existing writer and stored ranking.
ANCHOR: WATCH_SYSTEM_SUGGESTS_20261027. Synthetic disposable state only.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
for folder in (ROOT, ROOT / "scripts"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from scripts.lib import cio_company_population as population

NOW = datetime(2026, 10, 27, 18, tzinfo=timezone.utc)


def test_stored_calendar_keeps_capture_clock_when_report_is_rebuilt(tmp_path):
    from datetime import timedelta
    from scripts.lib.data_broker.street_detail import extended, dividends
    from scripts.lib.prospectus.street import catalyst_calendar, Closes

    observed = NOW - timedelta(days=3)

    def db(sql, _params, **_kwargs):
        if "data->'extended'" in sql:
            assert "created_at" in sql
            return [
                {
                    "snapshot_date": "2026-10-24",
                    "created_at": observed,
                    "extended": {"earnings_dates": [{"index": "2026-11-04T08:00:00-05:00"}]},
                }
            ]
        if "ticker_dividend_data" in sql:
            return [{"ex_div_date": "2026-11-06", "updated_at": observed}]
        return []

    raw = {"extended": extended(db, "ZZAA"), "dividends": dividends(db, "ZZAA")}
    ctx = {"symbol": "ZZAA", "name": "Fictional Instruments", "profile": {}}
    first = catalyst_calendar(raw, ctx, Closes([]), now=NOW, root=tmp_path, fund=False, eps_hist=[])
    rebuilt = catalyst_calendar(
        raw, ctx, Closes([]), now=NOW + timedelta(days=1), root=tmp_path, fund=False, eps_hist=[]
    )
    issuer = lambda cal: [e for e in cal["forward"] if e["kind"] != "macro"]
    assert len(issuer(first)) == 2
    assert [e["source_observed_at"] for e in issuer(first)] == [observed.isoformat()] * 2
    assert issuer(rebuilt) == issuer(first)
    assert issuer(first)[1]["estimated"] is False


def test_calendar_missing_capture_clock_never_borrows_report_or_event_time(tmp_path):
    from scripts.lib.prospectus.street import catalyst_calendar, Closes

    calendar = catalyst_calendar(
        {},
        {"symbol": "ZZAA", "name": "Fictional Instruments", "next_earnings_date": "2026-11-04"},
        Closes([]),
        now=NOW,
        root=tmp_path,
        fund=False,
        eps_hist=[],
    )
    earnings = next(e for e in calendar["forward"] if e["kind"] == "earnings")
    assert earnings["source_observed_at"] is None


def test_population_retains_legacy_groups_and_adds_suggestions():
    old = {"my_watchlist": ["ZZAA"], "held": ["ZZBB"], "formerly_held": []}
    assert "suggested" not in population.symbols_from(old)
    out = population.symbols_from({**old, "suggested": ["zzcc", "ZZCC"]})
    assert out["suggested"] == ["ZZCC"] and out["held"] == ["ZZBB"]


def test_suggestions_follow_house_ranking_exclusions_and_bound(tmp_path, monkeypatch):
    path = tmp_path / "data/cio/cio_opportunity_projection.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {"as_of": NOW.isoformat(), "items": {f"ZZ{i:02}": {"rank": i + 1, "conviction": 90 - i} for i in range(50)}}
        )
    )
    from lib.data_broker.watch_curation import eligible_opportunities, suggest
    from lib.site_payload_reads import read_curation
    from lib.data_broker import watch_prospects, watch_curation

    items = json.loads(path.read_text())["items"]
    rows = {s: {**watch_prospects.no_record_row(s), "stage": "forming"} for s in items}
    rows["ZZ03"]["stage"] = "expired"
    rows["ZZ04"]["expires_at"] = "not-a-clock"
    eligible = eligible_opportunities(items, rows.__getitem__, now=NOW)
    selected = suggest(eligible, n=30, held={"ZZ00"}, mine={"ZZ01": {}}, dismissed={"ZZ02": {}})

    def reader(**kwargs):
        assert kwargs["max_n"] == 30 and kwargs["root"] == tmp_path
        return [r["symbol"] for r in selected["members"]]

    result, gaps = population.suggested_symbols(tmp_path, now=NOW, reader=reader)
    assert len(result) == 30 and not gaps
    assert result[0] == "ZZ05" and not {"ZZ00", "ZZ01", "ZZ02", "ZZ03", "ZZ04"}.intersection(result)
    composition = {
        "now": NOW,
        "payload": {},
        "row_for": rows.__getitem__,
        "opps": items,
        "operator": {"ZZ01": {}},
        "held": {"ZZ00"},
        "proj_meta": {},
    }
    monkeypatch.setattr(watch_prospects, "gather", lambda query: composition)
    monkeypatch.setattr(watch_curation, "read_dismissed", lambda **kw: ({"ZZ02": {}}, "ok"))
    page = read_curation(
        {"view": "suggests", "n": 30, "limit": 30},
        stance_resolver=lambda *a, **k: {"gap": {"reason": "fixture"}, "conflicts": []},
        section_reader=lambda *a: {},
        review_reader=lambda *a: {},
    )
    assert [r["symbol"] for r in page["suggests"]["rows"]] == result


def test_unavailable_ranking_or_dismissal_is_a_gap_not_empty_success(tmp_path):
    result, gaps = population.suggested_symbols(tmp_path, now=NOW)
    assert result == [] and gaps[0]["reason"] == "suggestion_reader_not_supplied"
    path = tmp_path / "data/cio/cio_opportunity_projection.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"items": {"ZZAA": {"rank": 1}}}))

    def broken(*_args):
        raise OSError("fixture")

    result, gaps = population.suggested_symbols(tmp_path, reader=broken, now=NOW)
    assert not result and gaps[0]["reason"] == "suggestion_selection_unavailable"


def test_production_reader_refuses_fixture_root_before_any_broker_call(tmp_path, monkeypatch):
    from scripts.lib.data_broker.watch_curation import read_suggestion_targets
    from scripts.lib import site_payload_reads
    import pytest

    monkeypatch.setattr(site_payload_reads, "read_curation", lambda *a, **k: pytest.fail("fixture reached production"))
    with pytest.raises(ValueError, match="state_root_mismatch"):
        read_suggestion_targets(root=tmp_path, now=NOW)


@pytest.mark.parametrize("gap", [None, "ranking", "dismissals", "held", "truncated"])
def test_production_adapter_validates_real_broker_source_statuses(tmp_path, monkeypatch, gap):
    from scripts.lib.data_broker.watch_curation import read_suggestion_targets
    from scripts.lib import site_payload_reads, canonical_store_registry
    from lib import watchlist_intelligence

    monkeypatch.setattr(canonical_store_registry, "production_state_root", lambda: tmp_path)
    monkeypatch.setattr(watchlist_intelligence, "PROJECT_ROOT", tmp_path)
    payload = {
        "ok": True,
        "provider_calls": 0,
        "ranking": {"count": 1, "as_of": NOW.isoformat()},
        "held": {"source": "synthetic stored snapshot"},
        "suggests": {"dismissed_status": "ok", "eligible": 1, "rows": [{"symbol": "ZZAA"}]},
    }
    if gap == "ranking":
        payload["ranking"] = {}
    elif gap == "dismissals":
        payload["suggests"]["dismissed_status"] = "error:OSError"
    elif gap == "held":
        payload["held"]["source"] = "unavailable"
    elif gap == "truncated":
        payload["suggests"]["rows"] = []
    monkeypatch.setattr(site_payload_reads, "read_curation", lambda *_a, **_k: payload)
    if gap:
        with pytest.raises(ValueError, match="suggestion_"):
            read_suggestion_targets(root=tmp_path, now=NOW)
    else:
        assert read_suggestion_targets(root=tmp_path, now=NOW) == ["ZZAA"]


def test_missing_suggestion_source_cannot_be_complete(tmp_path, monkeypatch):
    monkeypatch.setattr(population.facts, "collect_inputs", lambda *a, **k: {"errors": []})
    monkeypatch.setattr(population, "stored_catalysts", lambda *a: {})
    capture = {
        "my_watchlist": [],
        "held": [],
        "formerly_held": [],
        "suggested": [],
        "profiles": {},
        "catalyst_events": {"status": "ok", "rows": {}},
        "gaps": [{"scope": "suggested", "reason": "selection_unavailable"}],
    }
    out = population.populate(tmp_path, capture, now=NOW)
    assert out["ok"] is False and out["quality_status"] == "PARTIAL"


def calendar_doc():
    return {
        "status": "STORED",
        "symbol": "ZZAA",
        "name": "Fictional Instruments Inc.",
        "version": "synthetic-version",
        "observed_at": NOW.isoformat(),
        "forward": [
            {"date": "2026-11-02", "kind": "earnings", "label": "Earnings", "source": "stored issuer calendar"},
            {"date": "2026-11-03", "kind": "macro", "label": "Market event", "source": "macro calendar"},
            {
                "date": "2026-11-04",
                "kind": "ex_dividend",
                "label": "Ex-dividend (estimated)",
                "source": "stored dividend history",
            },
        ],
    }


def test_calendar_reuses_stored_issuer_events_and_retains_estimation():
    from scripts.lib.data_broker.watch_company_calendar import facts_for

    out, gap = facts_for(calendar_doc(), "ZZAA", "synthetic-guid", {"value": "Fictional Instruments"}, now=NOW)
    assert not gap and len(out) == 2
    assert out[0]["event_at"] == "2026-11-02" and out[0]["observed_at"] == NOW.isoformat()
    assert "macro" not in {r["catalyst_type"] for r in out}
    assert out[1]["estimated"] is True and "(estimated)" in out[1]["headline"]
    assert all(r["source_ref"] == "prospectus:ZZAA:synthetic-version" for r in out)


def test_calendar_refuses_wrong_issuer_and_never_borrows_report_generation_time():
    from scripts.lib.data_broker.watch_company_calendar import facts_for

    d = calendar_doc()
    assert (
        facts_for(d, "ZZAA", "guid", {"value": "Other fictional issuer"}, now=NOW)[1]
        == "calendar_company_identity_unverified"
    )
    d["observed_at"] = None
    d["report_generated_at"] = NOW.isoformat()
    out, gap = facts_for(d, "ZZAA", "guid", {"value": "Fictional Instruments"}, now=NOW)
    assert not out and gap == "calendar_source_time_unavailable"


def test_calendar_old_source_is_not_refreshed_by_current_report_timestamp():
    from scripts.lib.data_broker.watch_company_calendar import facts_for

    d = calendar_doc()
    d["observed_at"] = "2020-01-01T18:00:00Z"
    d["report_generated_at"] = NOW.isoformat()
    out, gap = facts_for(d, "ZZAA", "guid", {"value": "Fictional Instruments"}, now=NOW)
    assert not out and gap == "calendar_source_stale"


def test_calendar_snapshot_excludes_portfolio_and_prose(tmp_path):
    from scripts.lib.prospectus import store
    from scripts.lib.data_broker.watch_company_calendar import snapshot

    source = {
        "symbol": "ZZAA",
        "name": "Fictional Instruments",
        "generated_at": NOW.isoformat(),
        "version": "20261027-180000",
        "private_portfolio": "SYNTHETIC_MUST_NOT_ESCAPE",
        "sections": [{"body_md": "SYNTHETIC_MUST_NOT_ESCAPE"}],
        "blocks": {"catalyst_calendar": {"forward": calendar_doc()["forward"], "source_observed_at": NOW.isoformat()}},
    }
    version = store.stamp(NOW)
    store.write_version(store.base_dir(tmp_path), "ZZAA", version, source, {})
    doc = snapshot(tmp_path, ["ZZAA"])["ZZAA"]
    assert doc["status"] == "STORED" and "SYNTHETIC_MUST_NOT_ESCAPE" not in str(doc)
    assert doc["observed_at"] == NOW.isoformat()
