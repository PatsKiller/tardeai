"""SoT Phase 6 — the Portfolio hub read path renders account state, never a bare $0.

/api/v2/overview publishes `portfolio_aggregate` through
lib.portfolio_aggregate_contract.build_portfolio_aggregate (proven by
tests/test_cc_header_truth_v2_api.py::test_overview_publishes_an_all_accounts_aggregate),
so the contract builder IS the overview's account read path. The data-broker
snapshot (lib.data_broker.portfolio_snapshot) is the other reader. Both are
exercised here over an injected holdings.json; nothing reaches the host.

Negative control: the pre-fix holdings.json shape (no `state`) renders the old
zero and the new assertion fails on it.
"""
from __future__ import annotations

import ast
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from lib.account_state import (
    STATE_LIVE,
    STATE_NO_API_MANUAL,
    STATE_SERVICE_DOWN,
    STATE_STALE,
    annotate_account_states,
    assert_never_zero_for_non_live,
)
from lib.portfolio_aggregate_contract import build_portfolio_aggregate

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 9, 13, 14, 0, tzinfo=timezone.utc)
UNIT = "unit-under-test.service"


def _iso(hours_ago: float) -> str:
    return (NOW - timedelta(hours=hours_ago)).isoformat()


def _registry():
    return {
        "live_api": {"sync_kind": "api", "sync_window_hours": 24},
        "stale_api": {"sync_kind": "api", "sync_window_hours": 24},
        "down_api": {"sync_kind": "api", "sync_window_hours": 24, "service_unit": UNIT,
                     "service_receipt": "data/runtime/unit_health.json"},
        "manual_acct": {"sync_kind": "manual", "manual_as_of": "2026-07-16"},
    }


def _legacy_book() -> dict:
    """The measured shape: two $0 accounts, indistinguishable."""
    return {
        "as_of": "2026-09-13",
        "generated_at": _iso(0.1),
        "last_repriced": _iso(0.1),
        "reprice_source": "finviz_live",
        "data_as_of": NOW.date().isoformat(),
        "data_as_of_account": "live_api",
        "holdings": [
            {"symbol": "AAA", "account": "live_api", "shares": 10, "market_value": 1000.0,
             "updated_at": _iso(2), "broker_position_as_of": NOW.date().isoformat()},
            {"symbol": "BBB", "account": "stale_api", "shares": 5, "market_value": 500.0,
             "updated_at": _iso(72)},
        ],
        "account_summaries": {
            "live_api": {"total_value": 1000.0, "holdings_count": 1},
            "stale_api": {"total_value": 500.0, "holdings_count": 1},
            "down_api": {"total_value": 0, "holdings_count": 0},                    # moomoo-shaped
            "manual_acct": {"total_value": 0, "holdings_count": 0, "source": "manual",  # fidelity-shaped
                            "as_of": "2026-07-16", "reported_total_value": 566439.39,
                            "reported_total_as_of": "2026-07-16"},
        },
        "portfolio_totals": {"total_value": 1500.0, "day_change": 0.0},
    }


def _fixed_book(tmp_path: Path, *, down_last_known: float | None = None) -> dict:
    book = _legacy_book()
    if down_last_known is not None:
        # a previous producer run had a value; the outage carried it forward
        book["account_summaries"]["down_api"]["account_state"] = {
            "last_known_value": down_last_known, "last_known_value_as_of": _iso(24 * 12),
            "last_known_value_source": "account_summaries.total_value"}
    (tmp_path / "data" / "runtime").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "runtime" / "unit_health.json").write_text(json.dumps(
        {"ok": False, "checked_at": _iso(0.2), "unit": {"state": "failed"}, "port": {"open": False}}))
    annotate_account_states(book["account_summaries"], book["holdings"], _registry(),
                            project_root=tmp_path, now=NOW, allow_shell=False)
    return book


def _aggregate(book: dict) -> dict:
    return build_portfolio_aggregate(
        aggregate_value=book["portfolio_totals"]["total_value"],
        account_summaries=book["account_summaries"],
        data_as_of=book["data_as_of"],
        data_as_of_account=book["data_as_of_account"],
        positions=book["holdings"],
        valuation_time=book["generated_at"],
        quote_observation_time=book["last_repriced"],
        quote_source=book["reprice_source"],
        now=NOW,
    )


# ─────────────────────────── overview: portfolio_aggregate ───────────────────


def test_overview_read_path_is_the_contract_builder():
    """The AST fact this suite leans on: overview() calls build_portfolio_aggregate
    and publishes it as portfolio_aggregate. If this moves, the state rendering
    below no longer reaches the header."""
    tree = ast.parse((ROOT / "scripts" / "api_v2.py").read_bytes())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "overview")
    src = ast.dump(fn)
    assert "build_portfolio_aggregate" in src
    assert "portfolio_aggregate" in {k.value for s in ast.walk(fn) if isinstance(s, ast.Dict)
                                     for k in s.keys if isinstance(k, ast.Constant)}


def test_fixed_book_renders_every_account_state_and_no_bare_zero(tmp_path):
    agg = _aggregate(_fixed_book(tmp_path, down_last_known=512.34))
    rows = {a["account"]: a for a in agg["accounts"]}
    assert rows["live_api"]["state"] == STATE_LIVE
    assert rows["stale_api"]["state"] == STATE_STALE
    assert rows["down_api"]["state"] == STATE_SERVICE_DOWN
    assert rows["manual_acct"]["state"] == STATE_NO_API_MANUAL

    # never $0 for a non-LIVE account: last known value with its date
    assert rows["down_api"]["display_value"] == 512.34
    assert rows["down_api"]["display_basis"] == "last_known_value"
    assert rows["down_api"]["display_value_as_of"] is not None
    assert rows["manual_acct"]["display_value"] == 566439.39
    assert rows["manual_acct"]["display_value_as_of"].startswith("2026-07-16")
    assert rows["manual_acct"]["manual_as_of"] == "2026-07-16"
    # the raw total_value is untouched — the contract still publishes what the store holds
    assert rows["down_api"]["total_value"] == 0
    assert rows["down_api"]["counted_in_total"] == 0.0
    assert rows["manual_acct"]["total_value"] == 0

    for a in agg["accounts"]:
        if a["state"] != STATE_LIVE:
            assert a["display_value"] != 0 or a["display_basis"] == "last_known_value"
            assert a["state_reason"]


def test_totals_carry_excluded_accounts_by_name_with_last_value(tmp_path):
    agg = _aggregate(_fixed_book(tmp_path, down_last_known=512.34))
    ex = {e["account"]: e for e in agg["excluded_accounts"]}
    assert set(ex) == {"down_api", "manual_acct"}
    assert ex["down_api"]["state"] == STATE_SERVICE_DOWN
    assert ex["down_api"]["last_value"] == 512.34
    assert ex["down_api"]["counted_in_total"] == 0.0
    assert UNIT in ex["down_api"]["reason"]
    assert ex["manual_acct"]["state"] == STATE_NO_API_MANUAL
    assert ex["manual_acct"]["last_value"] == 566439.39
    assert ex["manual_acct"]["as_of"].startswith("2026-07-16")
    assert agg["excluded_last_value_total"] == round(512.34 + 566439.39, 2)
    # STALE is counted in the total at its stale value — listed separately, not hidden
    assert [s["account"] for s in agg["stale_accounts"]] == ["stale_api"]
    assert agg["stale_accounts"][0]["counted_in_total"] == 500.0
    assert agg["unclassified_accounts"] == []
    assert agg["account_states_present"] is True
    # the aggregate value itself is exactly what the store said: labelling changed no total
    assert agg["aggregate_value"] == 1500.0


def test_service_down_with_no_history_renders_unknown_not_zero(tmp_path):
    """First outage ever, no carried value: the honest answer is 'unknown', labelled."""
    agg = _aggregate(_fixed_book(tmp_path))
    row = next(a for a in agg["accounts"] if a["account"] == "down_api")
    assert row["state"] == STATE_SERVICE_DOWN
    assert row["display_value"] is None
    assert row["display_basis"] == "unknown"
    ex = next(e for e in agg["excluded_accounts"] if e["account"] == "down_api")
    assert ex["last_value"] is None and ex["counted_in_total"] == 0.0


def test_negative_control_legacy_book_shows_the_old_zero_and_fails_the_assertion():
    agg = _aggregate(_legacy_book())
    rows = {a["account"]: a for a in agg["accounts"]}
    # pre-fix: state absent → UNCLASSIFIED, and the two $0 accounts are indistinguishable
    assert rows["down_api"]["state"] == "UNCLASSIFIED"
    assert rows["manual_acct"]["state"] == "UNCLASSIFIED"
    assert rows["down_api"]["display_value"] == 0
    assert rows["manual_acct"]["display_value"] == 0
    assert agg["excluded_accounts"] == []            # nothing was said about what was left out
    assert agg["account_states_present"] is False
    assert sorted(agg["unclassified_accounts"]) == ["down_api", "live_api", "manual_acct", "stale_api"]

    from lib.account_state import project_account_states
    with pytest.raises(AssertionError, match="UNCLASSIFIED"):
        assert_never_zero_for_non_live(project_account_states(_legacy_book()))


def test_header_truth_contract_fields_are_unchanged_by_the_state_fields(tmp_path):
    """The clocks the header-truth suites assert on must be byte-identical with
    and without state stamps — Phase 6 adds fields, it moves none."""
    legacy, fixed = _aggregate(_legacy_book()), _aggregate(_fixed_book(tmp_path))
    for k in ("contract_version", "portfolio_scope", "aggregate_value", "included_account_count",
              "position_observation_oldest", "position_observation_oldest_account",
              "position_observation_newest", "valuation_time", "quote_observation_time",
              "coverage", "freshness_state", "freshness_reason"):
        assert legacy[k] == fixed[k], k
    for a_l, a_f in zip(legacy["accounts"], fixed["accounts"]):
        for k in ("account", "total_value", "holdings_count", "position_observation_time",
                  "contributes", "holds_positions", "summary_as_of", "observation_divergence"):
            assert a_l[k] == a_f[k], f"{a_l['account']}.{k}"


# ─────────────────────────── the data-broker snapshot ────────────────────────


def test_snapshot_projects_account_states_over_injected_holdings(tmp_path, monkeypatch):
    from lib.data_broker import portfolio_snapshot as ps

    state = tmp_path / "data" / "portfolios" / "state"
    state.mkdir(parents=True)
    book = _fixed_book(tmp_path, down_last_known=512.34)
    (state / "holdings.json").write_text(json.dumps(book))
    monkeypatch.setattr(ps, "STATE_DIR", state)
    monkeypatch.setenv(ps.STATE_DIR_ENV, str(tmp_path / "state"))  # never write into the repo

    snap = ps.build_portfolio_snapshot()
    st = snap["account_states"]
    assert st["accounts"]["down_api"]["state"] == STATE_SERVICE_DOWN
    assert st["accounts"]["down_api"]["display_value"] == 512.34
    assert st["accounts"]["manual_acct"]["state"] == STATE_NO_API_MANUAL
    assert st["accounts"]["manual_acct"]["display_value"] == 566439.39
    assert [e["account"] for e in st["excluded_accounts"]] == ["down_api", "manual_acct"]
    assert_never_zero_for_non_live(st)
    # by_account rows carry the state beside the value they already carried
    assert snap["by_account"]["live_api"]["state"] == STATE_LIVE
    assert snap["by_account"]["stale_api"]["state"] == STATE_STALE
    assert snap["totals"]["total_value"] == 1500.0


def test_snapshot_over_legacy_holdings_names_the_unclassified_accounts(tmp_path, monkeypatch):
    from lib.data_broker import portfolio_snapshot as ps

    state = tmp_path / "data" / "portfolios" / "state"
    state.mkdir(parents=True)
    (state / "holdings.json").write_text(json.dumps(_legacy_book()))
    monkeypatch.setattr(ps, "STATE_DIR", state)
    monkeypatch.setenv(ps.STATE_DIR_ENV, str(tmp_path / "state"))
    snap = ps.build_portfolio_snapshot()
    assert sorted(snap["account_states"]["unclassified_accounts"]) == ["down_api", "live_api", "manual_acct", "stale_api"]
    with pytest.raises(AssertionError):
        assert_never_zero_for_non_live(snap["account_states"])
