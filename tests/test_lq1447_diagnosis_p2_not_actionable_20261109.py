"""ANCHOR: LQ1447_DIAGNOSIS_P2_NOT_ACTIONABLE_20261109 — recovered digest P2s are not incidents.

LQ-20261107-1447. The 07:00Z fan-in opened 14 diagnosis digest P2s. A later live
RUN_DONE, a lane that is not due on its own cadence, or a shadow/unscheduled lane
is not promoted. An open row the same rule clears is resolved, not deleted.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import n8n_incident_fanin as fanin  # noqa: E402
from scripts.lib import incidents as L  # noqa: E402

NOW = datetime(2026, 11, 9, 7, 0, 19, tzinfo=timezone.utc)
POOL = "hermes-research-worker-pool"


def _finding(lane, event_type, at, *, key="sig"):
    return {
        "source": fanin.DIAGNOSIS_SOURCE,
        "item": f"escalate:{lane}/{lane}|{key}",
        "severity": "P2",
        "lane": lane,
        "event_type": event_type,
        "detected_at": at,
        "detail": "suggest_only",
        "reason": "suggest_only",
    }


def _lane(kind, *, stage="canary", cadence="", expression="", days=None, mode="live"):
    row = {
        "state": "ACTIVE",
        "scheduler": {"kind": kind, "stage": stage, "expression": expression or "dispatcher", "cadence": cadence},
        "dispatch": {"mode": mode},
    }
    if days is not None:
        row["active_days"] = days
    return row


def _world():
    findings = [
        _finding("aegis-brief-regenerate", "NO_OUTPUT", "2026-10-31T05:33:02+00:00"),
        _finding("build-hermes-canonical-status", "RUN_FAILED", "2026-11-07T19:18:02+00:00"),
        _finding("document-mentions-backfill", "NO_OUTPUT", "2026-11-09T00:33:01+00:00"),
        _finding("etf-analyst-enrich", "RUN_FAILED", "2026-11-07T12:03:01+00:00"),
        _finding("finviz-screener-runner", "RUN_TIMEOUT", "2026-11-06T15:33:02+00:00"),
        _finding("goal-gate-bridge", "RUN_REFUSED", "2026-11-07T06:33:01+00:00"),
        _finding("hermes-momentum-catalyst-scalp", "NO_OUTPUT", "2026-11-09T05:18:01+00:00"),
        _finding("hermes-research-agenda-at-45-7", "STALE_OUTPUT", "2026-11-08T12:48:01+00:00"),
        _finding(POOL, "RUN_REFUSED", "2026-11-07T06:18:02+00:00", key="effect"),
        _finding(POOL, "RUN_FAILED", "2026-11-09T06:18:01+00:00", key="system"),
        _finding("hermes-score-event-feeder", "NO_OUTPUT", "2026-11-09T03:48:01+00:00"),
        _finding("maturity-remeasure", "SILENT", "2026-10-28T10:48:01+00:00"),
        _finding("news-to-catalyst", "RUN_REFUSED", "2026-11-07T11:48:01+00:00"),
        _finding("watchlist-enrichment-sweep", "NO_OUTPUT", "2026-11-09T05:18:01+00:00"),
        {
            "source": "breach_detector",
            "item": "kept-lane:NO_OUTPUT",
            "severity": "P2",
            "lane": "kept-lane",
        },
    ]
    lanes = {
        "aegis-brief-regenerate": _lane("none", stage="shadow", expression="on-demand"),
        "build-hermes-canonical-status": _lane("n8n", cadence="15 */2 * * *"),
        "document-mentions-backfill": _lane("n8n", stage="cutover", cadence="25 * * * *"),
        "etf-analyst-enrich": _lane("n8n", stage="cutover", cadence="0 7 * * 6"),
        "finviz-screener-runner": _lane("n8n", stage="cutover", cadence="0 10 * * 1-5"),
        "goal-gate-bridge": _lane("n8n", cadence="35 * * * *"),
        "hermes-momentum-catalyst-scalp": _lane(
            "n8n", stage="cutover", cadence="25 6-15 * * 1-5", days=[0, 1, 2, 3, 4]
        ),
        "hermes-research-agenda-at-45-7": _lane("cron", expression="45 7 * * *"),
        POOL: _lane("n8n", cadence="5 * * * *"),
        "hermes-score-event-feeder": _lane("cron", stage="shadow", expression="*/5 * * * *", mode="dry_run"),
        "maturity-remeasure": _lane("cron", stage="shadow", expression="40 6 * * 1", mode="dry_run"),
        "news-to-catalyst": _lane("cron", expression="45 6,12,18 * * *"),
        "watchlist-enrichment-sweep": _lane("n8n", stage="cutover", cadence="*/30 9-16 * * 1-5", days=[0, 1, 2, 3, 4]),
    }
    done = {
        "build-hermes-canonical-status": "2026-11-09T05:15:35+00:00",
        "document-mentions-backfill": "2026-11-09T06:28:07+00:00",
        "etf-analyst-enrich": "2026-10-31T11:01:55+00:00",
        "finviz-screener-runner": "2026-11-05T15:24:37+00:00",
        "goal-gate-bridge": "2026-11-09T06:35:08+00:00",
        "hermes-momentum-catalyst-scalp": "2026-11-06T20:25:29+00:00",
        "hermes-research-agenda-at-45-7": "2026-11-08T12:45:23+00:00",
        POOL: "2026-11-09T05:05:05+00:00",
        "news-to-catalyst": "2026-11-08T23:46:58+00:00",
        "watchlist-enrichment-sweep": "2026-11-06T21:36:03+00:00",
        "aegis-brief-regenerate": "2026-10-12T00:30:56+00:00",
    }
    runs = {lane: [{"state": "RUN_DONE", "mode": "live", "finished_at": at}] for lane, at in done.items()}
    return findings, lanes, runs


def test_fourteen_digest_p2s_promote_only_the_live_failures():
    findings, lanes, runs = _world()
    promoted, skipped = fanin.partition_diagnosis_p2(findings, now=NOW, lanes=lanes, runs_by_lane=runs)
    diag = [f for f in promoted if f.get("source") == fanin.DIAGNOSIS_SOURCE]
    assert sorted(f["item"] for f in diag) == sorted(
        [
            "escalate:etf-analyst-enrich/etf-analyst-enrich|sig",
            "escalate:finviz-screener-runner/finviz-screener-runner|sig",
            f"escalate:{POOL}/{POOL}|system",
        ]
    )
    assert [f["item"] for f in promoted if f.get("source") == "breach_detector"] == ["kept-lane:NO_OUTPUT"]
    reasons = {f["lane"] + ":" + f["item"].rsplit("|", 1)[-1]: f["skip_reason"] for f in skipped}
    assert reasons["aegis-brief-regenerate:sig"] == "shadow_or_unscheduled"
    assert reasons["hermes-score-event-feeder:sig"] == "shadow_or_unscheduled"
    assert reasons["maturity-remeasure:sig"] == "shadow_or_unscheduled"
    assert reasons["build-hermes-canonical-status:sig"] == "later_run_done"
    assert reasons["document-mentions-backfill:sig"] == "later_run_done"
    assert reasons["goal-gate-bridge:sig"] == "later_run_done"
    assert reasons["news-to-catalyst:sig"] == "later_run_done"
    assert reasons[f"{POOL}:effect"] == "later_run_done"
    assert reasons["hermes-momentum-catalyst-scalp:sig"] == "not_due"
    assert reasons["watchlist-enrichment-sweep:sig"] == "not_due"
    assert reasons["hermes-research-agenda-at-45-7:sig"] == "not_due"
    assert len(skipped) == 11


def test_apply_resolves_a_cleared_p2_and_does_not_delete_it(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADEAI_INCIDENTS_DIR", str(tmp_path / "incidents"))
    lane = "synthetic-recovered"
    finding = _finding(lane, "RUN_FAILED", "2026-11-07T06:00:00+00:00")
    assert fanin.publish_diagnosis_p2([finding], apply=True) == 1
    skipped = [{**finding, "skip_reason": "later_run_done"}]
    assert fanin.close_cleared_diagnosis_p2(skipped, apply=False) == 0
    assert fanin.close_cleared_diagnosis_p2(skipped, apply=True) == 1
    assert fanin.close_cleared_diagnosis_p2(skipped, apply=True) == 0
    recs = list(L.load_records(L.incidents_dir()).values())
    assert len(recs) == 1
    assert recs[0]["status"] == "fixed"
    assert recs[0]["resolution"] == "auto_resolved"
    assert any("later_run_done" in n["text"] for n in recs[0]["notes"])
    events = (L.incidents_dir() / "events.jsonl").read_text(encoding="utf-8")
    kinds = [json.loads(line)["kind"] for line in events.splitlines() if line.strip()]
    assert kinds == ["open", "resolve"]


def test_a_blocked_digest_p2_is_resolved_too(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADEAI_INCIDENTS_DIR", str(tmp_path / "incidents"))
    finding = _finding("synthetic-blocked", "NO_OUTPUT", "2026-11-09T01:00:00+00:00")
    assert fanin.publish_diagnosis_p2([finding], apply=True) == 1
    rec = next(iter(L.load_records(L.incidents_dir()).values()))
    L.block(
        rec["id"],
        actor="n8n-incident-fanin",
        blocked_reason="Needs a person",
        handoff="read the digest",
        d=L.incidents_dir(),
    )
    assert fanin.close_cleared_diagnosis_p2([{**finding, "skip_reason": "not_due"}], apply=True) == 1
    after = next(iter(L.load_records(L.incidents_dir()).values()))
    assert after["status"] == "fixed"
    assert after["resolution"] == "auto_resolved"
    assert any("not_due" in note["text"] for note in after["notes"])
