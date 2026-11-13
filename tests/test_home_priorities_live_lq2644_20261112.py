"""LQ-20261107-2644 (b): the server ranking behind Home's "Today's priorities". Synthetic fixtures only."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lib import home_priorities_live as hp  # noqa: E402


def inc(i, pr, blocks=False, first="2026-11-12T10:00:00+00:00", cause="why x", **kw):
    return {"incident_id": i, "priority": pr, "blocks_trading": blocks, "category": f"cat-{i}", "cause": cause,
            "first_seen_at": first, "owner": "risk", **kw}


def incidents(*items, state="OK"):
    return {"state": state, "items": list(items), "reason": None if state == "OK" else "read failed"}


def stops(*rows, status="ok", bstatus="available", read=None):
    b = {"status": bstatus, "stop_advice": list(rows)}
    if read is not None:
        b["stop_read"] = read
    return {"status": status, "cio_brief": b}


def appr(n, urgent=0):
    return {"ok": True, "data": {"count": n, "urgent_count": urgent}}


def ids(body):
    return [x["id"] for x in body["items"]]


def test_order_p0_blocking_then_p0_then_stops_then_approvals_then_p1():
    body = hp.rank(
        incidents(inc("p1", "P1"), inc("p1b", "P1", blocks=True), inc("p0", "P0"), inc("p0b", "P0", blocks=True),
                  inc("u", "UNCLASSIFIED")),
        stops({"symbol": "aa", "answer": "RAISE"}, {"symbol": "bb", "answer": "ADD_STOP"}, {"symbol": "cc", "answer": "FIX_QTY"}),
        appr(3, 1))
    assert ids(body) == ["inc-p0b", "inc-p0", "stop-ADD_STOP-BB-", "stop-FIX_QTY-CC-", "stop-RAISE-AA-", "approvals",
                         "inc-p1b", "inc-p1", "inc-u"]
    assert [x["rank"] for x in body["items"]] == list(range(1, 10))
    assert body["state"] == "OK" and body["unread"] == []


def test_oldest_first_inside_a_tier():
    body = hp.rank(incidents(inc("new", "P0", first="2026-11-12T12:00:00+00:00"), inc("old", "P0", first="2026-11-12T08:00:00+00:00")),
                   stops(), appr(0))
    assert ids(body) == ["inc-old", "inc-new"]


def test_info_and_hold_are_not_priorities():
    body = hp.rank(incidents(inc("i", "INFO")), stops({"symbol": "aa", "answer": "HOLD"}), appr(0))
    assert body["items"] == [] and body["state"] == "OK" and body["count"] == 0


def test_an_unreadable_input_is_named_and_the_state_is_partial_never_ok():
    body = hp.rank(incidents(state="UNKNOWN"), stops({"symbol": "aa", "answer": "ADD_STOP"}), appr(1))
    assert body["state"] == "PARTIAL"
    assert body["unread"][0]["input"] == "incidents"
    assert ids(body) == ["stop-ADD_STOP-AA-", "approvals"]
    assert "incidents" in body["reason"]


def test_nothing_readable_is_unknown_with_an_empty_list_not_ok():
    body = hp.rank(None, None, None)
    assert body["state"] == "UNKNOWN" and body["items"] == [] and len(body["unread"]) == 3


def test_a_raising_read_is_an_unread_entry_not_an_exception():
    def boom():
        raise RuntimeError("db down")
    body = hp.build(boom, lambda: stops(), lambda: appr(0))
    assert body["state"] == "PARTIAL" and body["unread"][0]["input"] == "incidents"


def test_stop_read_failure_is_unread():
    body = hp.rank(incidents(), stops({"symbol": "aa", "answer": "RAISE"}, read={"status": "unread"}), appr(0))
    assert body["state"] == "PARTIAL" and body["unread"][0]["input"] == "stop advice" and body["items"] == []


def test_no_snapshot_or_pending_brief_is_unread_not_all_clear():
    assert hp.rank(incidents(), {"status": "no_snapshot"}, appr(0))["unread"][0]["input"] == "stop advice"
    assert hp.rank(incidents(), stops(bstatus="pending"), appr(0))["unread"][0]["input"] == "stop advice"


def test_approvals_count_must_be_an_int():
    for bad in ({"ok": True, "data": {"count": "3"}}, {"ok": True, "data": {"count": True}}, {"ok": True, "data": {"count": -1}}, None, {}):
        assert hp.rank(incidents(), stops(), bad)["unread"][0]["input"] == "approvals", bad
    assert hp.rank(incidents(), stops(), {"count": 2})["items"][0]["count"] == 2  # un-enveloped body also accepted


def test_stale_incident_is_kept_labelled_and_does_not_change_tier():
    body = hp.rank(incidents(inc("s", "P0", stale_condition=True), inc("f", "P0", first="2026-11-12T11:00:00+00:00")), stops(), appr(0))
    assert ids(body) == ["inc-s", "inc-f"] and body["items"][0]["stale"] is True and body["items"][1]["stale"] is False


def test_unknown_cause_reads_cause_not_recorded():
    body = hp.rank(incidents(inc("a", "P0", cause="UNKNOWN")), stops(), appr(0))
    assert body["items"][0]["why"] == "cause not recorded"


def test_truncation_is_declared():
    many = [inc(f"i{n:03d}", "P1", first=f"2026-11-12T10:{n % 60:02d}:00+00:00") for n in range(hp.MAX_ITEMS + 5)]
    body = hp.rank(incidents(*many), stops(), appr(0))
    assert len(body["items"]) == hp.MAX_ITEMS and body["truncated"] is True and body["count"] == hp.MAX_ITEMS + 5


def test_stop_advice_ranks_by_severity_not_by_symbol_or_id():
    rows = [{"symbol": "AAA", "answer": "RAISE"}, {"symbol": "BBB", "answer": "FIX_QTY"},
            {"symbol": "ZZZ", "answer": "ADD_STOP"}]
    body = hp.rank(incidents(), stops(*rows), appr(0))
    assert [x["title"].split(" · ")[1] for x in body["items"]] == ["ZZZ", "BBB", "AAA"]


def test_inside_a_tier_the_oldest_incident_comes_first_and_one_with_no_start_time_comes_last():
    body = hp.rank(incidents(inc("zz-old", "P0", first="2026-11-01T10:00:00+00:00"),
                             inc("aa-new", "P0", first="2026-11-12T10:00:00+00:00"),
                             inc("mm-none", "P0", first=None)), None, None)
    assert ids(body) == ["inc-zz-old", "inc-aa-new", "inc-mm-none"]


def test_approvals_say_how_many_are_urgent_and_never_invent_an_urgent_count():
    urgent = hp.rank(incidents(), None, appr(3, urgent=2))["items"][0]
    assert urgent["count"] == 3 and urgent["urgent_count"] == 2 and urgent["why"] == "2 urgent (expire inside 2 h)"
    calm = hp.rank(incidents(), None, appr(1, urgent=0))["items"][0]
    assert calm["title"] == "1 approval waiting" and calm["why"] == "awaiting your decision"
    unknown = hp.rank(incidents(), None, {"ok": True, "data": {"count": 2}})["items"][0]
    assert unknown["urgent_count"] is None and unknown["why"] == "awaiting your decision"
