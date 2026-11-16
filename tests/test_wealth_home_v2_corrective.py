"""Corrective Home business-meaning cases over representative stored schemas. Synthetic data only."""

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import pytest

SPEC = importlib.util.spec_from_file_location(
    "home_corrective_under_test", Path(__file__).resolve().parents[1] / "scripts/lib/wealth_home_v2.py"
)
home = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = home
SPEC.loader.exec_module(home)
NOW = datetime(2026, 11, 16, 1, tzinfo=timezone.utc)
STAMP = NOW.isoformat()


def position(symbol="SYN", account="fixture-account", **kwargs):
    return {
        "symbol": symbol,
        "account_id": account,
        "account_label": "Synthetic account",
        "market_value": 1000.125,
        "shares": 0.375,
        **kwargs,
    }


def source(rows=None, queue=None):
    return {
        "positions": {"rows": rows or [], "as_of": STAMP},
        "portfolio": {"quote_as_of": STAMP, "day_pl_usd": 7.25},
        "do_now": queue or {},
    }


def card(eligible):
    return {
        "schema": "HomeCioCard@v1",
        "generated_at": STAMP,
        "advice": {"ok": eligible, "reason": None if eligible else "CIO synopsis is from an earlier window"},
        "card": {
            "posture": {
                "value": "NEUTRAL — SELECTIVE",
                "source_id": "synthetic-synopsis",
                "as_of": "2026-11-15T17:00:00Z",
            },
            "buys_line": {
                "value": "Small sizes only",
                "source_id": "synthetic-synopsis",
                "as_of": "2026-11-15T17:00:00Z",
            },
            "stops_actionable": {"value": 2, "source_id": "synthetic-synopsis", "as_of": "2026-11-15T17:00:00Z"},
            "reentry": {"ready": 1, "near": 2, "tracked": 3, "as_of": "2026-11-15T17:00:00Z"},
        },
    }


@pytest.mark.parametrize("eligible", [True, False])
def test_legitimate_dated_stance_preserves_gate_and_fact_clock(eligible):
    result = home.build(cio_card=card(eligible), now=NOW)
    stance = result["today"]["stance"]
    assert stance["clock"] == "2026-11-15T17:00:00Z"
    assert stance["eligibility"] == ("current" if eligible else "historical")
    assert "NEUTRAL — SELECTIVE" in stance["notes"][0]
    assert ("historical" in stance["notes"][0]) is (not eligible)
    buys = next(f for f in stance["metrics"] if f["label"] == "Buys")
    assert buys["value"] == "Small sizes only" and buys["clock"] == stance["clock"]
    assert result["header"]["cells"]["temperature"]["secondary"][1].endswith(stance["clock"])


def test_missing_and_unsupported_stance_are_different():
    missing = home.build(now=NOW)["today"]["stance"]
    wrong = home.build(cio_card={**card(True), "schema": "Unsupported@99"}, now=NOW)["today"]["stance"]
    assert "No dated posture fact" in missing["notes"][0]
    assert "schema unsupported" in wrong["notes"][0]
    assert "NEUTRAL" not in str(wrong)


@pytest.mark.parametrize(
    "summary,expected",
    [
        ({"text": "Saved synthetic narrative", "source": "retained"}, "Saved synthetic narrative"),
        ({"lines": ["Synthetic recorded line"], "text": None}, "Synthetic recorded line"),
        ({}, "summary.text is absent"),
    ],
)
def test_brief_maps_registered_text_or_lines_not_just_timestamp(summary, expected):
    result = home.build(
        slices={"since_close": {"generated_at": STAMP, "cio_brief": {"as_of": STAMP, "summary": summary}}}, now=NOW
    )
    assert expected in " ".join(result["today"]["brief"]["notes"])


def test_canonical_held_row_population_duplicate_accounts_missing_marks_and_watch_separation():
    # Public symbols are semantic regression names only. Every amount, quantity and account is synthetic.
    rows = [
        position("ANET"),
        position("SPCX"),
        position("NVDA"),
        position("V"),
        position("V", account="fixture-second"),
    ]
    marks = [
        {**r, "day_change": v, "day_change_pct": p, "asset_type": "EQUITY"}
        for r, v, p in zip(rows, [25, -30, None, 0.125, 0.25], [1, -2, None, 0.5, 0.5])
    ]
    document = {"holdings": marks + [dict(marks[0])], "last_repriced": STAMP, "document_source": "positions_current"}
    market = {
        "as_of": STAMP,
        "home_v007": {
            "symbols": {
                "WATCH_ONLY": {
                    "quote": {"state": "measured", "as_of": STAMP, "value": 10},
                    "day_change": {"state": "measured", "as_of": STAMP, "value": {"pct": 4}},
                }
            }
        },
        "reentry_watch": {"WATCH_ONLY": {"status": "RE_ENTER_IF"}},
    }
    result = home.build(cio=source(rows), holdings=document, market=market, now=NOW)
    movers = result["today"]["movers"]
    held = [r for r in movers["rows"] if r["scope"] == "held"]
    assert {r["symbol"] for r in held} == {"ANET", "SPCX", "NVDA", "V"}
    assert held[0]["symbol"] == "SPCX"
    v = next(r for r in held if r["symbol"] == "V")
    assert v["facts"][0]["value"] == "+$0.38"  # fractional underlying contribution is not rounded before summing
    nvda = next(r for r in held if r["symbol"] == "NVDA")
    assert nvda["facts"][0]["value"] is None
    assert all(r["clock"] is None for r in held)
    assert all("hv_query=" in r["href"] for r in held)
    watch = next(r for r in movers["rows"] if r["scope"] == "watch")
    assert watch["href"] == "/v3/watch/intelligence/WATCH_ONLY"
    assert movers["coverageEvidence"]["known_contribution_positions"] == 4
    assert movers["coverageEvidence"]["complete"] is False


def test_conflicting_duplicate_quote_is_excluded_not_selected():
    p = position()
    a = {**p, "day_change": 5}
    b = {**p, "day_change": 9}
    rows, coverage, _ = home.held_movers([p], {"holdings": [a, b]}, NOW)
    assert coverage["rejected_identities"] == 1
    assert rows[0]["facts"][0]["value"] is None


def task(identifier, category):
    return {
        "id": identifier,
        "category": category,
        "severity": "P1",
        "title": "Synthetic task group",
        "why": "Explicit owning reason",
        "action": {
            "label": "Review approvals" if category == "decide" else "Open owning desk",
            "where": "/v3/approvals",
        },
        "evidence": {"counts": {"actions": 2}} if category == "decide" else {},
    }


def test_nine_tasks_are_not_twentyfive_position_inventory_or_two_source_notices():
    items = [task("protect:" + str(i), "protect") for i in range(9)] + [task("approvals:pending", "decide")]
    result = home.build(
        cio=source([position("SYN" + str(i)) for i in range(25)], {"all_items": items, "total": 10, "as_of": STAMP}),
        market={"as_of": "2020-01-01T00:00:00Z"},
        now=NOW,
    )
    assert result["queue_total"] == result["header"]["queue_total"] == 10
    assert len(result["needs"]["protect"]["rows"]) == 9
    assert len(result["needs"]["protectionInventory"]["rows"]) == 25
    assert len(result["needs"]["decide"]["rows"]) == 1
    assert result["needs"]["fix"]["rows"] == []
    assert result["needs"]["sourceNotices"]["rows"]
    summary = {f["label"]: f["value"] for f in result["needs"]["summary"]["metrics"]}
    assert summary["Protect money"] == "9" and summary["Decide"] == "1" and summary["Fix system"] == "0"
    assert summary["Queue freshness"] == "partial"
    approval = result["needs"]["decide"]["rows"][0]
    assert approval["href"] == "/v3/approvals"
    assert any(f["label"] == "actions approval records" and f["value"] == "2" for f in approval["facts"])
    assert approval["evidence"]["individual_approval_ids_served"] is False


def test_unknown_vs_observed_empty_queue_and_declared_population_mismatch():
    unknown = home.build(cio=source(queue={"counts": {"protect": 0}, "state": "UNKNOWN"}), now=NOW)
    empty = home.build(cio=source(queue={"all_items": [], "total": 0, "as_of": STAMP}), now=NOW)
    partial = home.build(cio=source(queue={"items": [task("a", "fix")], "total": 20, "as_of": STAMP}), now=NOW)
    assert unknown["queue_total"] is None
    assert empty["queue_total"] == 0
    assert partial["queue_total"] == 1 and partial["needs"]["summary"]["complete"] is False


def finding(i, kind):
    return {
        "schema": "ConflictFinding@v1",
        "key": "synthetic:" + str(i),
        "revision": i + 1,
        "kind": kind,
        "tier": 2,
        "summary": "Explicit synthetic explanation " + str(i),
        "clears_when": "The owning source is reviewed",
        "rule": "U1",
        "action": "queue_review",
        "severity": "warn",
        "owner": "Synthetic engine owner",
        "subject": {"kind": "security", "id": "synthetic-guid", "label": "Synthetic issuer"},
        "sides": [
            {"source": "Engine A", "value": "Claim A", "as_of": STAMP},
            {"source": "Engine B", "value": "Claim B", "as_of": STAMP},
        ],
        "updated_at": STAMP,
    }


def test_twohundred_findings_preserve_meaning_categories_cap_and_identity():
    findings = [finding(i, "GATE" if i < 27 else "DATA_ERROR" if i < 199 else "CONFLICT") for i in range(200)]
    result = home.build(
        cio={
            "conflicts": {
                "findings": findings + [dict(findings[0])],
                "as_of": STAMP,
                "gap": {"reason": "more conflict records available", "total": 250, "shown": 200},
            }
        },
        now=NOW,
    )
    outlook = result["outlook"]
    assert [len(outlook[k]["rows"]) for k in ("gates", "dataQuality", "disagreements")] == [27, 172, 1]
    assert len({r["id"] for k in ("gates", "dataQuality", "disagreements") for r in outlook[k]["rows"]}) == 200
    row = outlook["disagreements"]["rows"][0]
    assert "Explicit synthetic explanation" in row["label"]
    assert row["detail"] == "The owning source is reviewed"
    assert any(f["label"] == "Engine A" and f["clock"] for f in row["facts"])
    assert row["href"] == "/v3/health"  # broad desk, never a falsely claimed selected finding
    assert row["links"][0]["label"] == "Open health desk"
    assert outlook["gates"]["complete"] is False
    assert outlook["gates"]["coverageEvidence"]["exact_duplicate_records"] == 1


@pytest.mark.parametrize("now", [datetime(2026, 11, 2, 2, tzinfo=timezone.utc), NOW])
def test_ny_sevendate_window_boundaries_and_far_dates(now):
    start = now.astimezone(home.sessions.ET).date()
    end = start + timedelta(days=7)
    rows = [
        {"id": str(i), "label": str(i), "event_date": d}
        for i, d in enumerate(
            [
                (start - timedelta(days=1)).isoformat(),
                start.isoformat(),
                (end - timedelta(days=1)).isoformat(),
                end.isoformat(),
                "2027-02-18",
                "2026-11-17T12:00:00",
            ]
        )
    ]
    inside, later, window = home.week_window(rows, now)
    assert [r["id"] for r in inside] == ["1", "2"]
    assert {r["id"] for r in later} == {"3", "4"}
    assert window["timezone"] == "America/New_York" and window["invalid_dates"] == 1
    assert window["to_exclusive"] == end.isoformat()


def test_existing_macro_calendar_not_replaced_by_far_context_dates():
    slices = {
        "since_close": {
            "generated_at": STAMP,
            "week_ahead": {
                "events": [
                    {
                        "date": "2026-11-16",
                        "kind": "macro",
                        "label": "Synthetic macro release",
                        "time_et": "08:30",
                        "symbols": [],
                    },
                    {
                        "date": "2027-02-18",
                        "kind": "earnings",
                        "label": "Far synthetic earnings",
                        "symbols": ["SYN"],
                        "held": True,
                    },
                ]
            },
        }
    }
    result = home.build(slices=slices, now=NOW)
    assert len(result["today"]["week"]["rows"]) == 1
    assert result["today"]["week"]["rows"][0]["event_kind"] == "macro"
    assert len(result["today"]["week"]["recordedUpcoming"]) == 1
    assert "end excluded" in result["today"]["week"]["windowLabel"]


def test_applicability_does_not_silently_adjudicate_mutual_fund_policy_disagreement():
    p = position("FUND", protection_state="UNKNOWN", stop_captured_at="2020-01-01T00:00:00Z", stop_price=10)
    result = home.build(cio=source([p]), holdings={"holdings": [{**p, "asset_type": "MUTUAL_FUND"}]}, now=NOW)
    row = result["needs"]["protectionInventory"]["rows"][0]
    assert "Applicability differs" in row["facts"][0]["value"]
    assert any(f["label"] == "Canonical order verdict" and f["value"] == "UNKNOWN" for f in row["facts"])
    assert not any(f["value"] == "Not applicable" for f in row["facts"])
    exempt = home.build(cio=source([position(protection_state="EXEMPT")]), now=NOW)
    assert exempt["today"]["stops"]["rows"][0]["facts"][0]["value"] == "Not applicable"


def test_reentry_never_asserts_stop_execution_and_stages_keep_engine_wording():
    market = {
        "as_of": STAMP,
        "reentry_watch": {
            "SYN": {"status": "RE_ENTER_IF", "exit_date": "2026-11-13", "as_of": "2026-11-13", "met": 2, "of": 5}
        },
    }
    row = home.build(market=market, now=NOW)["needs"]["reentry"]
    assert row["title"] == "Re-entry watch"
    assert any(f["label"] == "Exit cause" and f["value"] is None for f in row["rows"][0]["facts"])
    assert row["rows"][0]["clock"] is None


def test_stale_projection_does_not_repeat_warning_on_static_or_independently_clocked_facts():
    result = home.build(cio=source(), market={"as_of": STAMP, "tier": "YELLOW", "score": 41.8408}, now=NOW)
    result["_product"] = {"status": "UNKNOWN", "greyed": True}
    served = home.serve(result, now=NOW + timedelta(seconds=1))
    assert "not current" in served["today"]["tiles"]["qualifier"]
    assert all("qualifier" not in f or "not current" not in f["qualifier"] for f in served["today"]["tiles"]["metrics"])
    assert served["header"]["cells"]["temperature"]["display"] == "YELLOW · 41.8"
    assert served["contract_revision"] == served["header"]["contract_revision"] == "home-corrective@v1"


def test_clock_diagnostics_keep_real_future_error_and_venue_session_separate():
    future = home.source_meta("Synthetic", NOW + timedelta(minutes=1), now=NOW)
    assert future["verdict"] == "unknown" and future["clock_delta_s"] == -60
    assert "future" in future["reason"]
    assert home.source_meta("Synthetic", NOW + timedelta(seconds=4), now=NOW)["verdict"] == "known"
    assert future["evaluated_at"] == home.iso(NOW)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.invalid/x",
        "/api/v2/mutate",
        "//example.invalid/v3/health",
        "/v3/trading?tab=Orders",
        "/wealth/ops/health",
    ],
)
def test_review_allowlist_refuses_unknown_or_mutating_destinations(url):
    assert home.owner_href(url) is None


def test_health_review_destination_and_protection_fractional_details():
    p = position(
        "SYN",
        protection_state="PROTECTED",
        broker_protected=True,
        stop_source="Synthetic read",
        stop_captured_at=STAMP,
        stop_price=12,
        resting_loss_qty=0.125,
        resting_coverage_shortfall_qty=0.25,
    )
    result = home.build(
        cio=source([p]),
        stop_stale_after_s=3600,
        health={"captured_at": STAMP, "findings": [{"severity": "CRITICAL"} for _ in range(6)]},
        now=NOW,
    )
    assert result["header"]["cells"]["health"]["href"] == "/v3/health"
    row = result["today"]["stops"]["rows"][0]
    assert row["state"] == "amber" and row["facts"][0]["value"] == "Partial resting coverage"
    assert any(f["label"] == "Uncovered shares" and f["value"] == "0.25" for f in row["facts"])
    assert "hv_account=" in row["href"] and "hv_query=SYN" in row["href"]


@pytest.mark.parametrize(
    "different",
    [
        {"protection_state": "GAP"},
        {"stop_captured_at": "2020-01-01T00:00:00Z"},
        {"stop_source": "Other stored proof"},
        {"resting_coverage_shortfall_qty": 0.125},
    ],
)
def test_duplicate_current_protection_proofs_cannot_first_win(different):
    p = position(
        protection_state="PROTECTED",
        broker_protected=True,
        stop_source="Synthetic read",
        stop_captured_at=STAMP,
        stop_price=12,
        resting_coverage_shortfall_qty=0,
    )
    rows, rejected = home.unique_positions([p, {**p, **different}, p])
    assert rows == [] and rejected == ["conflicting position identity"]
    rendered = home.build(cio=source([p, {**p, **different}, p]), stop_stale_after_s=3600, now=NOW)
    assert rendered["today"]["stops"]["rows"] == []
    assert "Rejected 1 ambiguous" in " ".join(rendered["today"]["stops"]["notes"])


def test_partial_account_inputs_count_independently_and_withhold_aggregate():
    a = position(account="fixture-a")
    b = position(account="fixture-b")
    movers, coverage, _ = home.held_movers(
        [a, b], {"holdings": [{**a, "day_change": 0.125, "day_change_pct": 1}, {**b, "day_change": None}]}, NOW
    )
    assert coverage["known_contribution_positions"] == 1
    assert coverage["stored_estimate_total"] is None and not coverage["complete"]
    assert movers[0]["facts"][0]["value"] is None and movers[0]["facts"][1]["value"] is None
    assert movers[0]["facts"][2]["value"] == "1 / 2"


def test_missing_conflict_source_never_claims_complete_population():
    result = home.build(now=NOW)
    assert result["outlook"]["disagreements"]["complete"] is False


def test_collect_reuses_one_stored_market_read_and_one_injected_document_reader(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from scripts.lib.cc_products import cio_pages_route as cr, product_route as pr
    from scripts.lib import holdings_document

    calls = []
    documents = []

    def query(sql, params=None, fetch="all"):
        assert "SELECT" in sql and "cc_product_current" in sql
        calls.append(params)
        return [{"body": b"{}"}]

    def cio_reader(*, fetch_row, now):
        fetch_row("cio.pages", "global")
        return {**source([position()]), "_product": {"status": "OK"}}

    def market_reader(*, fetch_row, now):
        fetch_row("market_risk.latest", "global")
        return {"as_of": STAMP, "tier": "GREEN", "score": 42.5, "_product": {"status": "OK"}}

    def card_reader(*, fetch_row, now):
        fetch_row("market_risk.latest", "global")
        return card(False)

    def document_reader(*, store, db_query):
        documents.append((store, db_query))
        return {
            "document_source": "positions_current",
            "holdings": [{**position(), "day_change": 0.125, "day_change_pct": 0.25, "asset_type": "EQUITY"}],
        }

    monkeypatch.setattr(cr, "serve_cio_pages", cio_reader)
    monkeypatch.setattr(pr, "serve_market_risk_latest", market_reader)
    monkeypatch.setattr(pr, "serve_home_cio_card", card_reader)
    monkeypatch.setattr(holdings_document, "load_document", document_reader)
    ctx = SimpleNamespace(db_query_raising=query, db_query=query, portfolio_state_dir=tmp_path)
    output = home.collect(ctx, {}, now=NOW)
    assert calls == [("cio.pages", "global"), ("market_risk.latest", "global")]
    assert documents == [(tmp_path / "holdings.json", query)]
    assert output["today"]["stance"]["eligibility"] == "historical"
    assert output["today"]["movers"]["coverageEvidence"]["matched_account_positions"] == 1
    assert output["today"]["movers"]["rows"][0]["facts"][0]["value"] == "+$0.12"
    # Read path only ages stored output. It cannot reach the producer or document reader.
    monkeypatch.setattr(home, "collect", lambda *_a, **_k: pytest.fail("GET ran producer"))
    monkeypatch.setattr(holdings_document, "load_document", lambda **_k: pytest.fail("GET read holdings document"))
    served = home.serve(output, now=NOW + timedelta(seconds=1), header_only=True)
    assert served["contract_revision"] == "home-corrective@v1"


def test_pending_activation_overrides_retained_protected_verdict():
    p = position(
        protection_state="PROTECTED",
        broker_protected=True,
        stop_state="pending_activation",
        stop_source="Synthetic read",
        stop_captured_at=STAMP,
        stop_price=12,
    )
    result = home.build(cio=source([p]), stop_stale_after_s=3600, now=NOW)
    row = result["today"]["stops"]["rows"][0]
    assert row["state"] == "amber"
    assert row["facts"][0]["value"] == "Pending activation"
    assert row["facts"][1]["value"] == "PROTECTED"  # retained source contradiction is visible


def test_expired_home_relabels_current_stance_and_advice_as_historical():
    output = home.build(cio_card=card(True), now=NOW)
    output["_product"] = {"status": "UNKNOWN", "greyed": True}
    result = home.serve(output, now=NOW + timedelta(seconds=1))
    stance = result["today"]["stance"]
    assert stance["eligibility"] == "historical" and stance["title"] == "Last available CIO stance"
    assert "historical, not currently eligible" in stance["notes"][0]
    assert "Current eligible" not in str(stance)
    buys = next(f for f in stance["metrics"] if f["label"] == "Buys")
    assert buys["value"] == "Small sizes only" and "Historical only" in buys["qualifier"]
    assert result["header"]["cells"]["temperature"]["secondary"][0].startswith("Last stance:")


def test_cio_legacy_summary_string_keeps_own_clock_and_market_summary_separate():
    since = {
        "generated_at": STAMP,
        "cio_brief": {"generated_at": "2026-11-10T17:00:00Z", "summary": "Synthetic CIO narrative string"},
        "summary": {"text": "Different newer market-context narrative", "generated_at": STAMP},
    }
    result = home.build(slices={"since_close": since}, now=NOW)
    brief = result["today"]["brief"]
    assert brief["notes"][1] == "Synthetic CIO narrative string"
    assert brief["clock"] == "2026-11-10T17:00:00Z" and brief["source"] == "Saved CIO brief"
    since["cio_brief"] = {"generated_at": "2026-11-10T17:00:00Z", "summary": None}
    fallback = home.build(slices={"since_close": since}, now=NOW)["today"]["brief"]
    assert fallback["notes"][1] == "Different newer market-context narrative"
    assert fallback["source"] == "Saved market-context summary" and fallback["clock"] == home.iso(NOW)


def test_saved_cio_summary_without_own_clock_cannot_borrow_market_build():
    since = {"generated_at": STAMP, "cio_brief": {"summary": "Synthetic undated CIO narrative"}}
    brief = home.build(slices={"since_close": since}, now=NOW)["today"]["brief"]
    assert brief["notes"][1] == "Synthetic undated CIO narrative"
    assert brief["clock"] is None and brief["verdict"] == "unknown"


@pytest.mark.parametrize(
    "url",
    [
        "/v3/risk",
        "/v3/trading?tab=Proposals",
        "/v3/portfolio?tab=Redeploy",
        "/v3/system",
        "/v3/coordination",
        "/v3/agents",
        "/v3/intelligence?tab=research",
    ],
)
def test_registered_retained_queue_owners_preserve_review_destination(url):
    assert home.owner_href(url) == url
    item = {**task("synthetic-task", "decide"), "action": {"where": url, "label": "Review owning desk"}}
    result = home.build(cio=source(queue={"as_of": STAMP, "all_items": [item], "total": 1}), now=NOW)
    assert result["needs"]["decide"]["rows"][0]["href"] == url


@pytest.mark.parametrize(
    "url",
    [
        "/v3/trading?tab=Orders",
        "/v3/risk/mutate",
        "/v3/intelligence?tab=research&action=run",
        "/v3/portfolio?tab=Execute",
        "/v3/system?reauth=1",
    ],
)
def test_owner_review_routes_do_not_expand_to_arbitrary_queries_or_subpaths(url):
    assert home.owner_href(url) is None
