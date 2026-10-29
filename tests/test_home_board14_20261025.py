"""Board 14 Home display shaping. Synthetic fixtures only. No broker and no live store."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from scripts.lib.home_board14 import (
    HOLDINGS_SYNC_EXPR,
    VIX_GAP_REASON,
    apply_home_board,
    cap_do_now,
    holdings_market_note,
    jobs_clock,
    questions_new_count,
    regime_since,
    releases_to_merge,
    shape_do_now,
    shape_regime,
)
from scripts.lib.w7_pages import page_payload, project_pages

NOW = datetime(2026, 10, 25, 22, 0, tzinfo=timezone.utc)  # Sunday 18:00 ET
FRIDAY_SYNC = datetime(2026, 10, 23, 20, 52, tzinfo=timezone.utc)  # Friday 16:52 ET


def test_holdings_schedule_matches_the_registry_row():
    registry = json.loads(Path("config/lane_registry.json").read_text(encoding="utf-8"))
    row = next(item for item in registry["lanes"] if item.get("lane_id") == "schwab-position-sync")
    assert row["scheduler"]["expression"] == HOLDINGS_SYNC_EXPR
    assert row["state"] == "ACTIVE"


def test_weekend_names_the_last_sync_and_the_next_fire_without_calling_it_stale():
    note = holdings_market_note(FRIDAY_SYNC.isoformat(), NOW)
    assert note["market_open"] is False
    assert note["sync_missed"] is False
    assert note["market_closed_phrase"] == "Market closed · last broker sync Fri 16:52 ET · next Mon 09:07 ET"
    assert note["sync_missed_reason"] is None


def test_a_missed_friday_slot_stays_a_gap_on_the_weekend():
    early = FRIDAY_SYNC - timedelta(hours=4)
    note = holdings_market_note(early.isoformat(), NOW)
    assert note["sync_missed"] is True
    assert note["sync_missed_reason"] == "A scheduled holdings sync was missed."
    assert note["market_closed_phrase"].startswith("Market closed · last broker sync Fri 12:52 ET")


def test_open_session_has_no_closed_phrase():
    midday = datetime(2026, 10, 21, 19, 0, tzinfo=timezone.utc)  # Wednesday 15:00 ET
    note = holdings_market_note(datetime(2026, 10, 21, 18, 52, tzinfo=timezone.utc).isoformat(), midday)
    assert note["market_open"] is True
    assert note["market_closed_phrase"] is None
    assert note["sync_missed"] is False


def test_missing_jobs_receipt_is_a_gap_and_never_all_clear(tmp_path):
    clock = jobs_clock(tmp_path / "missing.json", NOW)
    assert clock["phrase"] is None and clock["on_schedule"] is None
    assert clock["gap"]["reason"] == "Jobs monitor receipt not published"


def test_jobs_phrase_requires_an_ok_monitor_receipt(tmp_path):
    path = tmp_path / "cron_outage_watchdog_latest.json"
    path.write_text(json.dumps({
        "schema": "CronOutageWatchdog@v1", "mode": "monitor", "observed_at": NOW.isoformat(),
        "status": "OK", "missed_lane_ids": [], "coverage_gap_lane_ids": [],
    }))
    assert jobs_clock(path, NOW)["phrase"] == "all ran on schedule"
    path.write_text(json.dumps({
        "schema": "CronOutageWatchdog@v1", "mode": "monitor", "observed_at": NOW.isoformat(),
        "status": "CRIT", "missed_lane_ids": ["lane-a", "lane-b"], "coverage_gap_lane_ids": [],
    }))
    missed = jobs_clock(path, NOW)
    assert missed["phrase"] is None
    assert missed["gap"]["reason"] == "2 scheduled runs missed"
    assert "lane-a" not in json.dumps(missed)


def test_questions_gap_when_unapproved_and_count_without_question_text(tmp_path):
    refused = questions_new_count(tmp_path / "absent.jsonl", NOW, approved=False)
    assert refused["count"] is None
    assert refused["gap"]["reason"] == "My questions store is not an approved source"
    ledger = tmp_path / "cio_ask_events.jsonl"
    old = (NOW - timedelta(days=3)).isoformat()
    fresh = (NOW - timedelta(hours=2)).isoformat()
    ledger.write_text("\n".join([
        json.dumps({"kind": "ask.asked", "at": fresh, "question": "synthetic question must not leak"}),
        json.dumps({"kind": "ask.answer_version", "at": old, "answer": {"text": "old synthetic answer"}}),
        json.dumps({"kind": "ask.answer_version", "at": fresh, "answer": {"text": "new synthetic answer"}}),
    ]) + "\n")
    counted = questions_new_count(ledger, NOW, approved=True)
    assert counted["count"] == 1 and counted["gap"] is None
    assert "synthetic" not in json.dumps(counted)


def test_releases_count_comes_only_from_the_receipt(tmp_path):
    missing = releases_to_merge(tmp_path / "absent.json")
    assert missing["count"] is None
    assert missing["gap"]["reason"] == "Releases census receipt not published"
    path = tmp_path / "pr-hygiene-audit_last.json"
    path.write_text(json.dumps({"summary": {"open_prs": 4, "as_of": NOW.isoformat()}, "titles": ["must not leak"]}))
    found = releases_to_merge(path)
    assert found == {"count": 4, "as_of": NOW.isoformat(), "gap": None}


def test_no_stop_names_roll_up_and_awaiting_fill_stays_its_own_stop_row():
    section = {"items": [
        {"id": "protection:taxable_a:SYM001", "category": "protect", "title": "SYM001 · Taxable A",
         "why": "No active broker stop observed", "evidence": {"stop_state": "none", "symbol": "SYM001"},
         "money_at_risk_usd": 10},
        {"id": "protection:ira_a:SYM001", "category": "protect", "title": "SYM001 · IRA A",
         "why": "No active broker stop observed", "evidence": {"stop_state": "none", "symbol": "SYM001"}},
        {"id": "protection:roth_a:SYM002", "category": "protect", "title": "SYM002 · Roth A",
         "why": "Stop filled · awaiting holdings sync", "evidence": {"stop_state": "filled", "symbol": "SYM002"}},
        {"id": "protection:taxable_a:SYM003", "category": "protect", "title": "SYM003 · Taxable A",
         "why": "Stop awaiting activation", "evidence": {"stop_state": "pending_activation"}},
        {"id": "approvals:pending", "title": "2 approvals waiting", "why": "Review the typed approval queues"},
    ]}
    items = shape_do_now(section)["items"]
    assert [item["kind"] for item in items] == ["REVIEW", "STOP", "STOP", "REVIEW"]
    assert items[0]["id"] == "protection:no-broker-stop"
    assert items[0]["symbol"] == "1 name"
    assert items[0]["why"] == "SYM001 ×2"
    assert "money" not in items[0]
    assert items[1]["id"] == "protection:roth_a:SYM002"
    assert items[3]["id"] == "approvals:pending"
    assert all("10" not in json.dumps(item) for item in items if item["id"] == "protection:no-broker-stop")


def test_regime_since_needs_a_label_change_and_vix_gap_does_not_hide_the_label():
    same = [{"regime_label": "fixture-risk", "generated_at": NOW.isoformat()}]
    assert regime_since(same) == (None, "Regime start is not in the fetched history")
    changed_at = (NOW - timedelta(days=2)).isoformat()
    history = [
        {"regime_label": "fixture-risk", "generated_at": NOW.isoformat()},
        {"regime_label": "fixture-risk", "generated_at": changed_at},
        {"regime_label": "fixture-prior", "generated_at": (NOW - timedelta(days=9)).isoformat()},
    ]
    since, gap = regime_since(history)
    assert gap is None and since == changed_at
    shaped = shape_regime(
        {"label": "fixture-risk", "vix": None, "gap": {"reason": VIX_GAP_REASON}, "as_of": NOW.isoformat()},
        history,
    )
    assert shaped["label"] == "fixture-risk"
    assert shaped["vix"] is None
    assert shaped["gap"] is None
    assert shaped["vix_gap"]["reason"] == VIX_GAP_REASON
    assert shaped["since_label"] == "Oct 23, 2026"
    assert shaped["as_of"] == NOW.isoformat()


def test_page_payload_adds_gaps_without_writing_or_inventing_counts(tmp_path):
    (tmp_path / "data").mkdir()
    truth = {
        "portfolio": {"positions_as_of": FRIDAY_SYNC.isoformat(), "total_usd": None, "cash_usd": None,
                      "day_pl_usd": None, "as_of": NOW.isoformat(), "source": "fixture", "stale": False, "gap": None,
                      "holdings": [], "accounts": []},
        "positions": {"rows": []},
        "stops": {}, "regime": {"label": "fixture-risk", "vix": None, "gap": {"reason": VIX_GAP_REASON}},
        "approvals": {"total": None}, "cio_status": {}, "capital": {},
        "do_now": {"items": [{"id": str(i), "title": "fixture"} for i in range(3)]},
        "companies": {"by_guid": {}}, "conflicts": {"findings": []},
        "concentration_policy": {"classes": []},
    }
    result = page_payload(tmp_path, now=NOW, resolver=lambda **_kw: truth, lookthrough_inputs={
        "fund_cache": {}, "fund_symbols": set(), "proxies": {}, "theme_members": {}, "theme_targets": {}, "snapshot": {},
    })
    assert result["portfolio"]["market_closed_phrase"].endswith("next Mon 09:07 ET")
    assert result["jobs"]["phrase"] is None and result["jobs"]["gap"]["reason"]
    assert result["questions"]["count"] is None and result["releases"]["count"] is None
    assert result["regime"]["vix_gap"]["reason"] == VIX_GAP_REASON
    assert sorted(p.name for p in tmp_path.rglob("*")) == ["data"]


def test_project_pages_still_caps_untagged_items_at_seven():
    truth = {"do_now": {"items": [{"id": str(i), "title": "fixture"} for i in range(9)]},
             "portfolio": {"holdings": [], "accounts": []}, "positions": {"rows": []}, "stops": {},
             "regime": {}, "approvals": {}, "cio_status": {}, "capital": {}, "sectors": {}}
    data = project_pages(truth, fund_cache={}, fund_symbols=set(), proxies={}, theme_members={},
                         theme_targets={}, snapshot={})
    assert [item["id"] for item in data["do_now"]["items"]] == [str(i) for i in range(7)]
    assert "kind" not in data["do_now"]["items"][0]


def test_regime_history_read_is_the_only_query_and_a_failure_stays_a_gap(tmp_path):
    calls = []

    def reader(*_args, **_kwargs):
        calls.append(1)
        raise OSError("fixture reader down")

    payload = {"portfolio": {"positions_as_of": FRIDAY_SYNC.isoformat()}, "regime": {"label": "fixture-risk", "vix": 1}}
    apply_home_board(payload, root=tmp_path, now=NOW, db_query=reader)
    assert calls == [1]
    assert payload["regime"]["label"] == "fixture-risk"
    assert payload["regime"]["vix"] == 1
    assert payload["regime"]["since_gap"] == "Regime start is not in the fetched history"


def _protect(n):
    return {"id": f"protection:acct_{n}:SYM{n:03d}", "category": "protect", "title": f"SYM{n:03d} · Acct {n}",
            "why": "Stop awaiting activation", "evidence": {"stop_state": "pending_activation"}}


def test_do_now_cap_keeps_every_row_and_counts_the_hidden_ones():
    rows = [_protect(n) for n in range(1, 10)]
    capped = cap_do_now({"items": rows[:7], "all_items": rows, "total": 9})
    assert len(capped["items"]) == 7
    assert len(capped["all_items"]) == 9
    assert capped["total"] == 9 and capped["hidden_count"] == 2 and capped["limit"] == 7


def test_do_now_cap_always_shows_the_waiting_approvals_row():
    rows = [_protect(n) for n in range(1, 9)]
    approvals = {"id": "approvals:pending", "category": "decide", "title": "3 approvals waiting",
                 "why": "Review the typed approval queues"}
    capped = cap_do_now({"items": rows[:7], "all_items": rows + [approvals]})
    ids = [item["id"] for item in capped["items"]]
    assert len(ids) == 7 and ids[-1] == "approvals:pending"
    assert capped["items"][-1]["kind"] == "REVIEW"
    assert capped["hidden_count"] == 2
    assert [item["id"] for item in capped["all_items"]][-1] == "approvals:pending"


def test_do_now_cap_without_overflow_hides_nothing():
    capped = cap_do_now({"items": [_protect(1)]})
    assert capped["hidden_count"] == 0 and capped["total"] == 1 and capped["all_items"] == capped["items"]


def test_project_pages_forwards_the_full_ranked_list():
    rows = [_protect(n) for n in range(1, 11)]
    pages = project_pages({"do_now": {"items": rows[:7], "all_items": rows, "total": 10}})
    assert len(pages["do_now"]["items"]) == 7
    assert pages["do_now"]["hidden_count"] == 3
    assert len(pages["do_now"]["all_items"]) == 10
