"""LQ-20261107-1839 (C1) — the alert delivery chain probe: one test per break class, synthetic fixtures only.

The repo is public, so every row here is invented.  The probe's DB layer is not exercised: these tests pin the
classification, the incident roll-up and the summary arithmetic, which are the parts a live run cannot make honest if
they are wrong.  The live run itself is quoted in READY-LQ-20261107-1839-cc-deepseek-8.md.

ANCHOR: ALERT_DELIVERY_CHAIN_PROBE_20261110
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "scripts", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import alert_delivery_chain_probe as probe  # noqa: E402

NOW = datetime(2026, 11, 10, 21, 0, tzinfo=timezone.utc)
T0 = NOW - timedelta(minutes=30)


def occ(**kw):
    """One occurrence row shaped like ``fetch`` returns it.  Nothing here comes from the database."""
    row = {
        "occurrence_id": 1,
        "alert_id": "al_synthetic",
        "incident_id": "inc_synthetic",
        "recorded_at": T0,
        "severity": "critical",
        "alert_type": "emergency_kill_or_revoke",
        "route_mode": "IMMEDIATE",
        "notify": True,
        "decision_reason": "first_occurrence",
        "intent_priority": "P1",
        "legacy_delivered": None,
        "delivery_id": None,
        "delivery_status": None,
        "delivery_reason": None,
        "delivery_msg_id": None,
        "delivery_created_at": None,
        "delivery_completed_at": None,
        "delivery_retry_count": 0,
        "digest_queued_at": None,
        "digest_claimed_at": None,
        "digest_included_at": None,
        "provider_message_id": None,
        "provider_settlement_state": None,
        "provider_settled_at": None,
        "event_ack_at": None,
    }
    row.update(kw)
    return row


def sent(msg="1001", **kw):
    """A delivery row the consumer actually sent, with a provider receipt."""
    row = occ(delivery_id=10, delivery_status="sent", delivery_msg_id=msg,
              delivery_created_at=T0, delivery_completed_at=T0 + timedelta(seconds=1),
              provider_message_id=msg, provider_settled_at=T0 + timedelta(seconds=1))
    row.update(kw)
    return row


def one(row, **kw):
    return probe.summarize([row], now=NOW, **kw)


def test_happy_path_has_all_four_timestamps():
    c = probe.classify(sent(), now=NOW)
    assert c["stage"] == "received"
    assert c["defect"] is None
    assert c["receipt"] == "1001"
    assert c["generated_at"] and c["queued_at"] and c["delivered_at"] and c["received_at"]
    assert c["ack_at"] is None, "no reader telemetry: ack stays NOT OBSERVABLE, never invented"


def test_break_not_queued():
    c = probe.classify(occ(), now=NOW)
    assert (c["stage"], c["defect"]) == ("generated", "not_queued")
    assert c["queued_at"] is None


def test_break_sent_without_a_provider_receipt():
    row = occ(delivery_id=11, delivery_status="sent", delivery_created_at=T0,
              delivery_completed_at=T0 + timedelta(seconds=1))
    c = probe.classify(row, now=NOW)
    assert (c["stage"], c["defect"]) == ("delivered", "delivered_without_receipt")
    assert c["receipt"] is None


def test_break_stuck_in_queue():
    row = occ(delivery_id=12, delivery_status="queued", delivery_created_at=NOW - timedelta(minutes=30))
    c = probe.classify(row, now=NOW)
    assert (c["stage"], c["defect"]) == ("queued", "stuck_in_queue")


def test_break_orphaned_claim():
    row = occ(delivery_id=13, delivery_status="claimed", delivery_created_at=NOW - timedelta(minutes=20))
    assert probe.classify(row, now=NOW)["defect"] == "orphaned_claim"


def test_break_send_failed():
    row = occ(delivery_id=14, delivery_status="failed", delivery_created_at=T0, delivery_retry_count=3)
    assert probe.classify(row, now=NOW)["defect"] == "send_failed:attempts=3"


def test_break_legacy_undelivered_is_queued_work_not_shadow():
    row = occ(delivery_id=15, delivery_status="suppressed", delivery_created_at=T0,
              delivery_reason="shadow_legacy_undelivered:first_occurrence")
    assert probe.classify(row, now=NOW)["defect"] == "legacy_undelivered_queued"


def test_break_held_by_editor():
    row = occ(delivery_id=16, delivery_status="suppressed", delivery_created_at=T0,
              delivery_reason="editor_held")
    assert probe.classify(row, now=NOW)["defect"] == "held_by_editor"


def test_receipt_unobservable_when_the_legacy_sender_never_reported():
    """The suppression reason is another process's claim, not a receipt: legacy_delivered absent -> NOT OBSERVABLE."""
    row = occ(delivery_id=17, delivery_status="abandoned", delivery_created_at=T0,
              delivery_reason="expired:shadow_legacy_owned_delivery|was:escalation_deadline_passed")
    c = probe.classify(row, now=NOW)
    assert (c["stage"], c["defect"]) == ("queued", "receipt_unobservable:legacy_delivery_unreported")
    assert c["receipt"] is None
    assert c["delivered_at"] is None


def test_receipt_unobservable_when_the_legacy_sender_reports_itself():
    row = occ(delivery_id=18, delivery_status="suppressed", delivery_created_at=T0,
              delivery_reason="shadow_legacy_owns_delivery:dedupe_window_elapsed", legacy_delivered=True)
    c = probe.classify(row, now=NOW)
    assert (c["stage"], c["defect"]) == ("delivered", "receipt_unobservable:legacy_self_report")
    assert c["receipt"] is None


def test_proven_undelivered_when_the_legacy_sender_reports_failure():
    row = occ(delivery_id=19, delivery_status="abandoned", delivery_created_at=T0,
              delivery_reason="expired:shadow_legacy_owned_delivery|was:first_occurrence", legacy_delivered=False)
    assert probe.classify(row, now=NOW)["defect"] == "not_delivered:legacy_reported_failure"


def test_a_matched_provider_receipt_closes_a_shadow_row():
    row = occ(delivery_id=20, delivery_status="suppressed", delivery_created_at=T0,
              delivery_reason="shadow_legacy_owns_delivery:first_occurrence",
              provider_message_id="67094", provider_settled_at=T0 + timedelta(seconds=1))
    c = probe.classify(row, now=NOW)
    assert (c["stage"], c["defect"], c["receipt"]) == ("received", None, "67094")


def test_digest_never_claimed_is_a_break():
    row = occ(route_mode="DIGEST", digest_queued_at=T0)
    assert probe.classify(row, now=NOW)["defect"] == "digest_never_claimed"


def test_digest_included_is_delivered_but_the_receipt_belongs_to_the_batch():
    row = occ(route_mode="DIGEST", digest_queued_at=T0, digest_claimed_at=T0 + timedelta(minutes=1),
              digest_included_at=T0 + timedelta(minutes=2))
    c = probe.classify(row, now=NOW)
    assert (c["stage"], c["defect"]) == ("delivered", "receipt_unobservable")
    assert c["receipt"] is None
    assert c["delivered_at"] is not None


def test_router_declined_is_named_and_covered_by_its_incident():
    a = sent(occurrence_id=1)
    b = occ(occurrence_id=2, notify=False, decision_reason="duplicate_within_dedupe_window",
            recorded_at=T0 + timedelta(minutes=5))
    s = probe.summarize([a, b], now=NOW)
    declined = [c for c in s["chains"] if not c["notify"]]
    assert declined[0]["defect"] == "router_declined:duplicate_within_dedupe_window"
    assert declined[0]["incident_evidence_class"] == "evidenced"
    assert s["incidents"]["delivered_evidenced"] == 1


def test_router_declined_but_a_provider_receipt_exists_names_the_contradiction():
    """The sender acted against the router.  Hiding the receipt behind 'declined' would lose the one fact that matters."""
    row = occ(notify=False, decision_reason="duplicate_within_dedupe_window",
              provider_message_id="67095,67096", provider_settled_at=T0 + timedelta(seconds=1))
    c = probe.classify(row, now=NOW)
    assert (c["stage"], c["receipt"]) == ("received", "67095,67096")
    assert c["defect"] == "router_declined_but_sent:duplicate_within_dedupe_window"


def test_no_push_route_is_named():
    c = probe.classify(occ(route_mode="COMMAND_CENTER"), now=NOW)
    assert c["defect"] == "no_push_route:COMMAND_CENTER"


def test_summary_percentages_and_stage_counts():
    s = probe.summarize([sent(occurrence_id=1, incident_id="inc_a"), occ(occurrence_id=2, incident_id="inc_b")],
                        now=NOW)
    assert s["occurrences"] == {"total": 2, "notify_true": 2, "router_declined": 0}
    assert s["incidents"]["push_channel"] == 2
    assert s["incidents"]["delivered_evidenced"] == 1
    assert s["incidents"]["no_observable_receipt"] == 1
    assert s["incidents"]["pct_fully_delivered_evidenced"] == 50.0
    assert s["stages"] == {"generated": 2, "queued": 1, "delivered": 1, "received": 1, "acknowledged": 0}


def test_self_report_only_never_counts_as_delivered_evidenced():
    row = occ(delivery_id=21, delivery_status="suppressed", delivery_created_at=T0,
              delivery_reason="shadow_legacy_owns_delivery:first_occurrence", legacy_delivered=True)
    s = probe.summarize([row], now=NOW)
    assert s["incidents"]["delivered_evidenced"] == 0
    assert s["incidents"]["delivered_self_report_only"] == 1
    assert s["incidents"]["no_observable_receipt"] == 1
    assert s["incidents"]["pct_fully_delivered_evidenced"] == 0.0


def test_break_classes_carry_a_real_example():
    s = probe.summarize([occ(occurrence_id=7, incident_id="inc_x")], now=NOW)
    classes = {b["class"]: b for b in s["break_classes"]}
    assert classes["not_queued"]["occurrences"] == 1
    assert classes["not_queued"]["example"]["occurrence_id"] == 7


def test_percentile_is_nearest_rank_and_never_invents_zero():
    assert probe.percentile([], 50) is None
    assert probe.percentile([5], 95) == 5
    assert probe.percentile([1, 2, 3, 4, 5], 50) == 3
    assert probe.percentile([1, 2, 3, 4, 5], 95) == 5


def test_no_database_is_unverifiable_not_ok():
    class Broken:
        def cursor(self):
            raise RuntimeError("synthetic: no DB")

    out = probe.run(conn=Broken())
    assert out["verdict"] == "UNVERIFIABLE"
    assert "RuntimeError" in out["error"]


def test_verdict_names_the_failing_criterion():
    # One incident with a receipt, one without: C1's four-timestamp test is not met.
    s = probe.run(conn=_Stub([sent(occurrence_id=1, incident_id="inc_a"),
                              occ(occurrence_id=2, incident_id="inc_b")]))
    assert s["verdict"] == "BROKEN"


class _Stub:
    """A connection that is also its own cursor: answers the probe's five queries in order with synthetic rows."""

    def __init__(self, occurrences, digest=(0, 0, 0, None), digest_all=(0, 0, None, None), ledger=(), v2=()):
        self.queue = [occurrences, v2, [dict(zip(("queued_rows", "claimed", "included", "oldest_open"), digest))],
                      [dict(zip(("rows", "included", "oldest", "newest"), digest_all))], list(ledger)]
        self._rows = []
        self.description = None

    def execute(self, *_a, **_kw):
        rows = self.queue.pop(0)
        if rows and not isinstance(rows[0], dict):
            raise AssertionError("stub rows must be dicts")
        self._rows = rows
        keys = list(rows[0].keys()) if rows else []
        self.description = [(k,) for k in keys]

    def fetchall(self):
        return [tuple(r.get(k) for k in (d[0] for d in self.description)) for r in self._rows]

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


def test_run_wires_every_section():
    out = probe.run(conn=_Stub([sent()], v2=[], ledger=[
        {"severity": "critical", "rows": 2, "with_message_id": 0, "with_sent_at": 0, "acknowledged": 0}]))
    for key in ("comms_v2", "digest_queue", "ledger_alert_events", "latency_by_channel"):
        assert key in out
    assert out["ledger_alert_events"]["recorded_without_send"] == 2
    assert out["comms_v2"]["events"] == 0


def test_queue_bounds_match_the_hygiene_lane():
    """Two modules, one contract: a probe that calls a row stuck under a bound the lane does not enforce is a lie."""
    import alert_delivery_queue_hygiene as hyg

    assert probe.QUEUE_MAX_AGE_MIN == hyg.QUEUE_MAX_AGE_MIN
    assert probe.CONSUMER_CLAIM_TTL_MIN == hyg.CONSUMER_CLAIM_TTL_MIN
