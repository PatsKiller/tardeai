"""SoT Phase 6 — accounts: absent is not zero. Producer-side classification.

Measured defect (2026-09-13): moomoo_taxable_live read $0 because
trade-ai-lab-moomoo-opend.service was FAILED (exit 78 / EX_CONFIG) so its read
sync wrote nothing; fidelity_rollover_ira read $0 because there is no retail API
and its value is a manual entry dated 2026-07-16. Nothing distinguished them.

These tests drive the pure classifier over injected rows, then the producer
entry point (portfolio_loader.load_all_portfolios) over an injected project
root with its own account registry, receipts and an injected systemctl runner.
Nothing here touches the host: no DB, no systemctl, no data/.

Labelling only: every assertion about total_value checks it was NOT changed.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from lib.account_state import (
    ACCOUNT_STATES,
    STATE_LIVE,
    STATE_NO_API_MANUAL,
    STATE_SERVICE_DOWN,
    STATE_STALE,
    STATE_UNCLASSIFIED,
    annotate_account_states,
    classify_account_state,
    derive_last_sync,
    interpret_service_receipt,
    probe_service_unit,
    project_account_states,
    assert_never_zero_for_non_live,
    write_sync_receipt,
)

NOW = datetime(2026, 9, 13, 14, 0, tzinfo=timezone.utc)
UNIT = "unit-under-test.service"  # any unit — the code names none


def _iso(hours_ago: float) -> str:
    return (NOW - timedelta(hours=hours_ago)).isoformat()


# ─────────────────────────── the pure classifier ────────────────────────────


def test_api_account_synced_two_hours_ago_is_live():
    out = classify_account_state(sync_kind="api", last_sync_at=_iso(2), now=NOW, window_hours=24)
    assert out["state"] == STATE_LIVE
    assert out["state_as_of"] == _iso(2)
    assert "2.0h ago" in out["state_reason"]


def test_api_account_synced_three_days_ago_is_stale():
    out = classify_account_state(sync_kind="api", last_sync_at=_iso(72), now=NOW, window_hours=24)
    assert out["state"] == STATE_STALE
    assert out["state_as_of"] == _iso(72)
    assert "exceeds window 24h" in out["state_reason"]


def test_failed_unit_is_service_down_and_keeps_last_successful_sync_as_of():
    out = classify_account_state(
        sync_kind="api", last_sync_at=_iso(72), now=NOW, window_hours=24,
        service_failed=True, service_detail="unit failed (Result=exit-code, ExecMainStatus=78 EX_CONFIG)",
        service_unit=UNIT,
    )
    assert out["state"] == STATE_SERVICE_DOWN
    assert UNIT in out["state_reason"] and "EX_CONFIG" in out["state_reason"]
    # state_as_of is the last SUCCESSFUL sync, not now — the outage did not observe anything
    assert out["state_as_of"] == _iso(72)


def test_failed_unit_beats_a_fresh_looking_sync_clock():
    """Negative control on precedence: a carried row dated 1h ago must not make a
    failed service read LIVE."""
    out = classify_account_state(sync_kind="api", last_sync_at=_iso(1), now=NOW,
                                 service_failed=True, service_unit=UNIT)
    assert out["state"] == STATE_SERVICE_DOWN


def test_last_run_error_is_service_down_even_when_unit_state_unknown():
    out = classify_account_state(sync_kind="api", last_sync_at=_iso(3), now=NOW,
                                 service_failed=None, last_run_error="OpenD connect refused")
    assert out["state"] == STATE_SERVICE_DOWN
    assert "last sync run errored: OpenD connect refused" in out["state_reason"]


def test_manual_account_is_no_api_manual_with_manual_as_of():
    out = classify_account_state(sync_kind="manual", manual_as_of="2026-07-16", now=NOW)
    assert out["state"] == STATE_NO_API_MANUAL
    assert out["manual_as_of"] == "2026-07-16"
    assert out["state_as_of"].startswith("2026-07-16")
    assert "manual statement" in out["state_reason"]


def test_manual_wins_over_everything_else():
    """A manual custodian has no service to be down and no window to miss."""
    out = classify_account_state(sync_kind="manual", manual_as_of="2026-07-16", now=NOW,
                                 last_sync_at=_iso(1), service_failed=True)
    assert out["state"] == STATE_NO_API_MANUAL


def test_never_synced_api_account_is_stale_not_live():
    out = classify_account_state(sync_kind="api", last_sync_at=None, now=NOW)
    assert out["state"] == STATE_STALE
    assert out["state_as_of"] is None
    assert "never" in out["state_reason"]


def test_every_outcome_is_one_of_the_registry_states():
    cases = [
        dict(sync_kind="api", last_sync_at=_iso(2)),
        dict(sync_kind="api", last_sync_at=_iso(80)),
        dict(sync_kind="api", service_failed=True),
        dict(sync_kind="manual", manual_as_of="2026-07-16"),
        dict(sync_kind="api"),
    ]
    for c in cases:
        assert classify_account_state(now=NOW, **c)["state"] in ACCOUNT_STATES


def test_window_boundary_is_inclusive():
    assert classify_account_state(last_sync_at=_iso(24), now=NOW, window_hours=24)["state"] == STATE_LIVE
    assert classify_account_state(last_sync_at=_iso(24.01), now=NOW, window_hours=24)["state"] == STATE_STALE


# ─────────────────────────── evidence readers ───────────────────────────────


def test_service_receipt_failed_unit_is_failed():
    rec = {"ok": False, "checked_at": _iso(0.5), "unit": {"state": "failed"}, "port": {"open": False}}
    v = interpret_service_receipt(rec, now=NOW)
    assert v["failed"] is True and "failed" in v["detail"]


def test_service_receipt_data_plane_down_is_failed_even_if_unit_active():
    """OpenD binds the port before login and exits on auth failure — a listening
    port is not a serving service (opend_health.py, 2026-07-23)."""
    rec = {"ok": False, "checked_at": _iso(0.5), "unit": {"state": "active"},
           "port": {"open": True}, "quote": {"ok": False, "detail": "query rejected: not logged in"}}
    v = interpret_service_receipt(rec, now=NOW)
    assert v["failed"] is True and "not logged in" in v["detail"]


def test_service_receipt_ok_is_not_failed():
    rec = {"ok": True, "checked_at": _iso(0.5), "unit": {"state": "active"}}
    assert interpret_service_receipt(rec, now=NOW)["failed"] is False


def test_stale_or_missing_service_receipt_does_not_speak():
    assert interpret_service_receipt({}, now=NOW)["failed"] is None
    old = {"ok": False, "checked_at": _iso(30), "unit": {"state": "failed"}}
    assert interpret_service_receipt(old, now=NOW)["failed"] is None


def test_systemctl_probe_reads_failed_with_exit_status_named():
    calls = []

    def runner(args):
        calls.append(args)
        if args[0] == "is-failed":
            return 0, "failed"
        return 0, "Result=exit-code\nExecMainStatus=78\n"

    out = probe_service_unit(UNIT, runner=runner)
    assert out["failed"] is True
    assert "ExecMainStatus=78 EX_CONFIG" in out["detail"]
    assert calls[0] == ["is-failed", UNIT]


def test_systemctl_probe_active_and_unknown():
    assert probe_service_unit(UNIT, runner=lambda a: (1, "active"))["failed"] is False
    assert probe_service_unit(UNIT, runner=lambda a: (4, ""))["failed"] is None

    def boom(a):
        raise FileNotFoundError("systemctl")

    assert probe_service_unit(UNIT, runner=boom)["failed"] is None


def test_last_sync_reads_the_broker_stamp_never_the_valuation_restamp():
    """portfolio_loader.reprice_holdings rewrites as_of/updated_at to NOW on every
    repriced row. If those counted as sync clocks, every repriced account would
    read LIVE forever. Only broker_position_as_of is a sync stamp."""
    rows = [{"account": "x", "broker_position_as_of": "2026-09-04",
             "updated_at": "2026-09-13T13:00:00+00:00", "as_of": "2026-09-13"},   # restamped today
            {"account": "x", "as_of": "2026-09-13", "updated_at": "2026-09-13T13:00:00+00:00"}]
    ts, src = derive_last_sync(rows, {"as_of": "2026-07-17"})
    assert ts.startswith("2026-09-04") and src == "holdings.broker_position_as_of"
    # no broker stamp anywhere: the restamps are ignored and the summary mirror is the fallback
    ts2, src2 = derive_last_sync([rows[1]], {"as_of": "2026-07-17"})
    assert ts2.startswith("2026-07-17") and src2 == "account_summaries.as_of"
    assert derive_last_sync([rows[1]], {}) == (None, "")
    assert derive_last_sync([], {}) == (None, "")


# ─────────────────────────── the producer over a book ────────────────────────


def _registry():
    return {
        "live_api": {"display_name": "Live API", "sync_kind": "api", "sync_window_hours": 24},
        "stale_api": {"display_name": "Stale API", "sync_kind": "api", "sync_window_hours": 24},
        "down_api": {"display_name": "Down API", "sync_kind": "api", "sync_window_hours": 24,
                     "service_unit": UNIT, "service_receipt": "data/runtime/unit_health.json"},
        "manual_acct": {"display_name": "Manual", "sync_kind": "manual", "manual_as_of": "2026-07-16",
                        "closed": True, "rolled_to": "live_api"},
    }


def _book():
    return {
        "holdings": [
            {"symbol": "AAA", "account": "live_api", "shares": 10, "market_value": 1000.0,
             "updated_at": _iso(2), "broker_position_as_of": NOW.date().isoformat()},
            {"symbol": "BBB", "account": "stale_api", "shares": 5, "market_value": 500.0,
             "updated_at": _iso(72)},
            {"symbol": "CASH", "account": "down_api", "is_cash": True, "shares": 500.0,
             "market_value": 500.0, "updated_at": _iso(24 * 40)},
        ],
        "account_summaries": {
            "live_api": {"total_value": 1000.0, "holdings_count": 1},
            "stale_api": {"total_value": 500.0, "holdings_count": 1},
            "down_api": {"total_value": 500.0, "holdings_count": 1},
            "manual_acct": {"total_value": 0, "holdings_count": 0, "source": "manual",
                            "as_of": "2026-07-16", "reported_total_value": 566439.39,
                            "reported_total_as_of": "2026-07-16"},
        },
    }


def test_annotate_stamps_all_four_states_and_changes_no_balance(tmp_path):
    root = tmp_path
    (root / "data" / "runtime").mkdir(parents=True)
    (root / "data" / "runtime" / "unit_health.json").write_text(json.dumps(
        {"ok": False, "checked_at": _iso(0.2), "unit": {"state": "failed"}, "port": {"open": False}}))
    book = _book()
    before = {k: dict(v) for k, v in book["account_summaries"].items()}

    states = annotate_account_states(book["account_summaries"], book["holdings"], _registry(),
                                     project_root=root, now=NOW, allow_shell=False)

    got = {k: v["state"] for k, v in states.items()}
    assert got == {"live_api": STATE_LIVE, "stale_api": STATE_STALE,
                   "down_api": STATE_SERVICE_DOWN, "manual_acct": STATE_NO_API_MANUAL}
    s = book["account_summaries"]
    for k in s:
        assert s[k]["state"] == got[k]
        assert s[k]["state_reason"]
        assert "state_as_of" in s[k]
        # labelling only — every pre-existing field is byte-identical
        for f, v in before[k].items():
            assert s[k][f] == v, f"{k}.{f} changed"
    # the manual account carries its manual date and its last known (reported) value
    m = states["manual_acct"]
    assert m["manual_as_of"] == "2026-07-16"
    assert m["last_known_value"] == 566439.39
    assert m["registry_closed"] is True and m["registry_rolled_to"] == "live_api"
    # the down account keeps the carried cash as its last known value, dated by the row
    d = states["down_api"]
    assert d["last_known_value"] == 500.0
    assert d["evidence"]["service_receipt"]["failed"] is True
    assert d["evidence"]["systemctl"]["failed"] is None  # not probed: allow_shell=False


def test_producer_falls_back_to_systemctl_only_when_allowed_and_receipt_silent(tmp_path):
    book = _book()
    reg = _registry()
    calls: list = []

    def runner(args):
        calls.append(list(args))
        return (0, "failed") if args[0] == "is-failed" else (0, "Result=exit-code\nExecMainStatus=78\n")

    # no receipt on disk, shell allowed → systemctl consulted → SERVICE_DOWN with the cause
    st = annotate_account_states(book["account_summaries"], book["holdings"], reg,
                                 project_root=tmp_path, now=NOW, allow_shell=True, systemctl_runner=runner)
    assert st["down_api"]["state"] == STATE_SERVICE_DOWN
    assert "EX_CONFIG" in st["down_api"]["state_reason"]
    assert calls and calls[0][0] == "is-failed"

    # same book, shell NOT allowed (repricer / handler posture) → never shells; falls to STALE by clock
    calls.clear()
    book2 = _book()
    st2 = annotate_account_states(book2["account_summaries"], book2["holdings"], reg,
                                  project_root=tmp_path, now=NOW, allow_shell=False, systemctl_runner=runner)
    assert calls == []
    assert st2["down_api"]["state"] == STATE_STALE  # 40-day-old carried row; no evidence of the outage
    # only the LIVE account is not consulted at all: no service_unit declared
    assert "systemctl" not in st2["live_api"]["evidence"]


def test_sync_receipt_error_marks_service_down_without_any_unit(tmp_path):
    book = _book()
    reg = _registry()
    reg["stale_api"] = {"sync_kind": "api", "sync_window_hours": 24}  # no unit, no receipt path
    write_sync_receipt(tmp_path, "stale_api", ok=False, error="ConnectionRefusedError: [Errno 111]")
    st = annotate_account_states(book["account_summaries"], book["holdings"], reg,
                                 project_root=tmp_path, now=NOW, allow_shell=False)
    assert st["stale_api"]["state"] == STATE_SERVICE_DOWN
    assert "Errno 111" in st["stale_api"]["state_reason"]


def test_successful_sync_receipt_is_a_sync_clock(tmp_path):
    """A sync that ran 1h ago but wrote no new rows (nothing changed) is still LIVE."""
    book = _book()
    write_sync_receipt(tmp_path, "stale_api", ok=True)
    st = annotate_account_states(book["account_summaries"], book["holdings"], _registry(),
                                 project_root=tmp_path, now=datetime.now(timezone.utc), allow_shell=False)
    assert st["stale_api"]["state"] == STATE_LIVE
    assert st["stale_api"]["evidence"]["last_sync_source"] == "sync_receipt.at"


def test_unregistered_account_defaults_to_api_and_is_never_invented_as_manual(tmp_path):
    book = _book()
    st = annotate_account_states(book["account_summaries"], book["holdings"], {},
                                 project_root=tmp_path, now=NOW, allow_shell=False)
    assert st["live_api"]["state"] == STATE_LIVE
    # a $0 account with no registry entry and no rows: STALE (never synced), NOT manual, NOT live
    assert st["manual_acct"]["state"] == STATE_STALE
    assert st["manual_acct"]["last_known_value"] == 566439.39  # reported value still carried


# ─────────────────────────── end to end through the loader ───────────────────


def _write_project(tmp_path: Path, *, with_registry: bool = True) -> Path:
    root = tmp_path
    state = root / "data" / "portfolios" / "state"
    state.mkdir(parents=True)
    (root / "data" / "runtime").mkdir(parents=True)
    (root / "assets").mkdir()
    book = _book()
    # the loader classifies on the WALL clock: pin the live account's broker stamp to today
    for h in book["holdings"]:
        if h["account"] == "live_api":
            h["broker_position_as_of"] = datetime.now(timezone.utc).date().isoformat()
    book["as_of"] = "2026-09-12"
    book["portfolio_totals"] = {"total_value": 2000.0, "as_of": "2026-09-12"}
    (state / "holdings.json").write_text(json.dumps(book))
    (state / "price_cache.json").write_text(json.dumps({"AAA": {"price": 100.0}, "BBB": {"price": 100.0}}))
    (root / "data" / "runtime" / "unit_health.json").write_text(json.dumps(
        {"ok": False, "checked_at": datetime.now(timezone.utc).isoformat(),
         "unit": {"state": "failed"}, "port": {"open": False}}))
    if with_registry:
        import yaml
        (root / "assets" / "portfolio_accounts.yaml").write_text(yaml.safe_dump({"accounts": _registry()}))
    return root


def test_loader_writes_state_fields_into_account_summaries(tmp_path):
    from scripts.portfolio_loader import load_all_portfolios

    root = _write_project(tmp_path)
    out = load_all_portfolios(str(root))
    s = out["account_summaries"]
    assert s["manual_acct"]["state"] == STATE_NO_API_MANUAL
    assert s["manual_acct"]["account_state"]["manual_as_of"] == "2026-07-16"
    assert s["down_api"]["state"] == STATE_SERVICE_DOWN
    assert UNIT in s["down_api"]["state_reason"]
    assert s["live_api"]["state"] == STATE_LIVE
    # stale_api rows carry only a (restamped) updated_at — no broker stamp, no receipt:
    # never-synced → STALE, and the loader's own reprice restamp did not make it LIVE
    assert s["stale_api"]["state"] == STATE_STALE
    assert "never synced" in s["stale_api"]["state_reason"]
    # balances: repriced from the cache as before, the state stamp changed none of them
    assert s["live_api"]["total_value"] == 1000.0
    assert s["down_api"]["total_value"] == 500.0
    assert s["manual_acct"]["total_value"] == 0
    assert out["portfolio_totals"]["total_value"] == 2000.0


def test_repricer_recalc_preserves_and_refreshes_state(tmp_path, monkeypatch):
    """_recalc_totals mutates account_summaries in place every 15 minutes; the
    labels must survive it, and the refresh must never shell out."""
    import portfolio_repricer as pr

    root = _write_project(tmp_path)
    monkeypatch.setattr(pr, "__file__", str(root / "scripts" / "portfolio_repricer.py"))
    monkeypatch.setattr(pr.subprocess if hasattr(pr, "subprocess") else __import__("subprocess"), "run",
                        lambda *a, **k: pytest.fail("repricer must never shell out"))
    book = json.loads((root / "data" / "portfolios" / "state" / "holdings.json").read_text())
    annotate_account_states(book["account_summaries"], book["holdings"], _registry(),
                            project_root=root, now=NOW, allow_shell=False)
    assert book["account_summaries"]["down_api"]["state"] == STATE_SERVICE_DOWN

    pr._recalc_totals(book)

    s = book["account_summaries"]
    assert s["down_api"]["state"] == STATE_SERVICE_DOWN
    assert s["manual_acct"]["state"] == STATE_NO_API_MANUAL
    assert s["live_api"]["state"] == STATE_LIVE
    assert all("account_state" in v for v in s.values())


# ─────────────────────────── negative control: the pre-fix shape ─────────────


def test_pre_fix_shape_fails_the_never_zero_assertion():
    """holdings.json before Phase 6: no state on any account. moomoo-shaped $0 and
    fidelity-shaped $0 are indistinguishable and the invariant must REFUSE it."""
    legacy = {"account_summaries": {
        "big": {"total_value": 1158374.79, "holdings_count": 14},
        "down_shaped": {"total_value": 0, "holdings_count": 0},
        "manual_shaped": {"total_value": 0, "holdings_count": 0, "as_of": "2026-07-16"},
    }}
    proj = project_account_states(legacy)
    assert proj["unclassified_accounts"] == ["big", "down_shaped", "manual_shaped"]
    assert proj["accounts"]["down_shaped"]["display_value"] == 0  # the old zero
    assert proj["accounts"]["down_shaped"]["state"] == STATE_UNCLASSIFIED
    with pytest.raises(AssertionError):
        assert_never_zero_for_non_live(proj)


def test_fixed_shape_passes_the_never_zero_assertion(tmp_path):
    (tmp_path / "data" / "runtime").mkdir(parents=True)
    (tmp_path / "data" / "runtime" / "unit_health.json").write_text(json.dumps(
        {"ok": False, "checked_at": _iso(0.2), "unit": {"state": "failed"}}))
    book = _book()
    annotate_account_states(book["account_summaries"], book["holdings"], _registry(),
                            project_root=tmp_path, now=NOW, allow_shell=False)
    proj = project_account_states(book)
    assert_never_zero_for_non_live(proj)
    assert [e["account"] for e in proj["excluded_accounts"]] == ["down_api", "manual_acct"]
    manual = next(e for e in proj["excluded_accounts"] if e["account"] == "manual_acct")
    assert manual["last_value"] == 566439.39 and manual["as_of"].startswith("2026-07-16")
    assert manual["counted_in_total"] == 0.0  # the total carried $0 for it — said out loud
    assert proj["stale_accounts"][0]["account"] == "stale_api"
