"""Host-side watch of the n8n alerting path (operator 2026-10-10, "Yes to everything").

The incident router is every generic workflow's errorWorkflow and the only caller of POST /event, and it has no error
workflow of its own, so its own failures (and an n8n outage) never reach /event. scripts/lib/n8n_alert_path_watch.py
reads only the relay log on the host and raises P1 `tradeai-incident-router:error|stalled` and
`n8n-schedule:due_refused|stalled`; scripts/incident_notifier.py (host cron) runs it on every pass, including when
the n8n-dispatched fan-in receipt is stale or missing, so the P1 path does not depend on n8n. The relay now logs the
/due lane filter (`lanes`) so the incident router's calls are attributable.

Hermetic: relay logs under tmp_path, loopback relay with a fake transport, pure notifier runs with a capture
sender; no live state root, no n8n, no DB, no send.

COVERS = ["scripts/lib/n8n_alert_path_watch.py", "scripts/incident_notifier.py", "scripts/n8n_run_relay.py"]
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import incident_notifier as N  # noqa: E402
from scripts import n8n_incident_fanin as fanin  # noqa: E402
from scripts import n8n_run_relay as R  # noqa: E402
from scripts.lib import n8n_alert_path_watch as W  # noqa: E402

NOW = datetime(2026, 10, 10, 23, 0, tzinfo=timezone.utc)
ROUTER = sorted(W.INCIDENT_ROUTER_LANES)
ENV: dict = {}


def _log(root: Path, rows: list[dict]) -> Path:
    p = root / W.RELAY_LOG_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return p


def _due(at: datetime, source: str = "schedule", lanes=None, state: str = "OK", reason=None, attributed=True) -> dict:
    row = {"at": at.isoformat(), "op": "due", "state": state, "reason": reason, "source": source}
    if attributed:
        row["lanes"] = list(lanes or [])
    return row


def _minutes(n: int, end: datetime = NOW, **kw) -> list[dict]:
    """One dispatcher + one incident-router /due per minute for n minutes ending at `end` (attributed relay)."""
    out = []
    for m in range(n, 0, -1):
        at = end - timedelta(minutes=m)
        out += [_due(at, **kw), _due(at, lanes=ROUTER, **kw)]
    return out


def _items(found):
    return sorted(f["item"] for f in found)


# ── the watch ──────────────────────────────────────────────────────────────────────────────────────

def test_healthy_cadence_raises_nothing(tmp_path):
    _log(tmp_path, _minutes(30))
    found, note = W.findings(tmp_path, NOW, ENV)
    assert found == [] and note.startswith("ok:0:router_last=2026-10-10T22:59")


def test_router_stopped_while_dispatcher_runs_is_a_p1_stall(tmp_path):
    _log(tmp_path, _minutes(30, end=NOW - timedelta(minutes=20)))
    _log(tmp_path, [_due(NOW - timedelta(minutes=m)) for m in range(20, 0, -1)])   # dispatcher only
    found, _ = W.findings(tmp_path, NOW, ENV)
    assert _items(found) == ["tradeai-incident-router:stalled"]
    f = found[0]
    assert f["severity"] == "P1" and f["source"] == "n8n_alert_path" and "silent 21 min" in f["detail"]
    assert f["detected_at"] == "2026-10-10T00:00:00+00:00"                          # stable per UTC day


def test_n8n_stopped_altogether_is_two_p1s(tmp_path):
    _log(tmp_path, _minutes(30, end=NOW - timedelta(minutes=45)))
    found, _ = W.findings(tmp_path, NOW, ENV)
    assert _items(found) == ["n8n-schedule:stalled", "tradeai-incident-router:stalled"]


def test_router_due_refused_is_a_p1_error_but_the_dispatchers_is_not_this_watch(tmp_path):
    rows = _minutes(10)
    rows.append(_due(NOW - timedelta(minutes=3), lanes=ROUTER, state="REFUSED", reason="relay_gateway_unreachable"))
    rows.append(_due(NOW - timedelta(minutes=2), state="REFUSED", reason="relay_gateway_unreachable"))  # dispatcher
    _log(tmp_path, rows)
    found, _ = W.findings(tmp_path, NOW, ENV)
    assert _items(found) == ["tradeai-incident-router:error"]     # dispatcher errors travel via /event (gap 11)
    assert "/due REFUSED relay_gateway_unreachable" in found[0]["detail"]


def test_event_refusal_is_the_incident_routers_own_error(tmp_path):
    rows = _minutes(10) + [{"at": (NOW - timedelta(minutes=1)).isoformat(), "state": "REFUSED",
                            "reason": "relay_bad_bearer", "op": "event"},
                           {"at": (NOW - timedelta(minutes=1)).isoformat(), "op": "event", "state": "ACCEPTED"}]
    _log(tmp_path, rows)
    found, _ = W.findings(tmp_path, NOW, ENV)
    assert _items(found) == ["tradeai-incident-router:error"]
    assert "1 failed relay call(s)" in found[0]["detail"] and "/event REFUSED relay_bad_bearer" in found[0]["detail"]


def test_errors_older_than_the_window_clear(tmp_path):
    rows = _minutes(40) + [_due(NOW - timedelta(minutes=20), lanes=ROUTER, state="REFUSED", reason="x")]
    _log(tmp_path, rows)
    assert W.findings(tmp_path, NOW, ENV)[0] == []


def test_relay_without_lane_attribution_falls_back_to_schedule_signals(tmp_path):
    """Today's served relay (before this change) logs no `lanes`: no router attribution, so no false router stall,
    and a refused source=schedule /due is the P1 `n8n-schedule:due_refused`."""
    rows = [_due(NOW - timedelta(minutes=m), attributed=False) for m in range(30, 0, -1)]
    rows.append(_due(NOW - timedelta(minutes=4), state="REFUSED", reason="relay_gateway_unreachable", attributed=False))
    rows.append(_due(NOW - timedelta(minutes=4), source="event", state="REFUSED", reason="x", attributed=False))
    _log(tmp_path, rows)
    found, note = W.findings(tmp_path, NOW, ENV)
    assert _items(found) == ["n8n-schedule:due_refused"] and note.endswith("attributed_due_rows=0")


def test_never_seen_is_a_note_not_a_stall_and_old_rows_are_ignored(tmp_path):
    _log(tmp_path, _minutes(5, end=NOW - timedelta(hours=30)))
    found, note = W.findings(tmp_path, NOW, ENV)
    assert found == [] and "router_last=None" in note and "schedule_last=None" in note


def test_missing_log_opt_out_and_bad_env(tmp_path):
    assert W.findings(tmp_path, NOW, ENV) == ([], "relay_log:absent")
    _log(tmp_path, _minutes(30, end=NOW - timedelta(minutes=45)))
    assert W.findings(tmp_path, NOW, {"TRADEAI_ALERT_PATH_WATCH": "0"}) == ([], "unavailable:disabled_by_env")
    assert len(W.findings(tmp_path, NOW, {"TRADEAI_ALERT_PATH_STALL_MIN": "junk"})[0]) == 2
    assert W.findings(tmp_path, NOW, {"TRADEAI_ALERT_PATH_STALL_MIN": "60"})[0] == []


def test_router_lane_filter_matches_the_workflow():
    doc = json.loads((ROOT / "docs/implementation/n8n-maturity/workflows/tradeai-incident-router.json").read_text())
    urls = [n["parameters"]["url"] for n in doc["nodes"] if n["type"] == "n8n-nodes-base.httpRequest"
            and "/due?" in n["parameters"].get("url", "")]
    assert len(urls) == 1
    lanes = {x for v in parse_qs(urls[0].split("?", 1)[1])["lane"] for x in v.split(",")}
    assert lanes == W.INCIDENT_ROUTER_LANES
    others = [p for p in (ROOT / "docs/implementation/n8n-maturity/workflows").glob("tradeai-*.json")
              if p.name != "tradeai-incident-router.json"]
    assert others and all("n8n-incident-fanin" not in p.read_text() for p in others)   # only the router asks


def test_notifier_and_watch_agree_on_the_source_name():
    assert N.ALERT_PATH_SOURCE == W.SOURCE


# ── the relay logs the lane filter ─────────────────────────────────────────────────────────────────

def _relay(tmp_path, transport):
    env = {"TRADEAI_N8N_RELAY_BEARER": "b" * 40, "TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N": "k" * 40,
           "TRADEAI_STATE_ROOT": str(tmp_path), "TRADEAI_N8N_GATEWAY_URL": "http://127.0.0.1:9"}
    return R.Relay(environ=env, allowlist=frozenset(), transport=transport)


def test_relay_due_lines_carry_lanes(tmp_path):
    ok = _relay(tmp_path, lambda url, payload: (200, {"schema": "DueResponse@v1", "ok": True, "items": []}))
    assert ok.due("Bearer " + "b" * 40, "source=schedule&limit=40&lane=n8n-incident-fanin,incident-notifier")[0] == 200
    assert ok.due("Bearer " + "b" * 40, "source=schedule&limit=40")[0] == 200

    def down(url, payload):
        raise OSError("refused")

    bad = _relay(tmp_path, down)
    assert bad.due("Bearer " + "b" * 40, "source=schedule&limit=40&lane=n8n-incident-fanin,incident-notifier")[0] == 502
    rows = [json.loads(x) for x in (tmp_path / W.RELAY_LOG_REL).read_text().splitlines()]
    router = ["n8n-incident-fanin", "incident-notifier"]
    assert [(r["state"], r["lanes"]) for r in rows] == [("OK", router), ("OK", []), ("REFUSED", router)]
    found, _ = W.findings(tmp_path, datetime.now(timezone.utc), ENV)
    assert _items(found) == ["tradeai-incident-router:error"]


# ── the notifier sends it from host cron, with or without a fresh fan-in ───────────────────────────

class Capture:
    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, text, **kw):
        self.calls.append({"text": text, **kw})
        return {"ok": True, "message_id": len(self.calls)}


def _fanin(root: Path, rows: list[dict], as_of: datetime) -> None:
    p = root / N.FANIN_RECEIPT_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"schema": "N8nIncidentFanin@v1", "mode": "apply", "as_of": as_of.isoformat(),
                             "open": len(rows), "by_severity": {}, "incidents": rows}))


def _run(root, now, sender, live=True):
    return N.run(live=live, root=root, now=now, env={"TRADEAI_SERVED_SHA": "t"}, sender=sender,
                 ledger_path=root / "no_ledger.sqlite")


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for v in ("TRADEAI_ALERT_PATH_WATCH", "TRADEAI_ALERT_PATH_STALL_MIN", "TRADEAI_ALERT_PATH_ERROR_MIN",
              "TRADEAI_ALERT_PATH_SEEN_H"):
        monkeypatch.delenv(v, raising=False)


def test_stale_fanin_still_sends_the_alert_path_p1_and_declares_no_fanin_recovery(tmp_path):
    """n8n is down: the fan-in (n8n-dispatched) is stale, so before this change the notifier sent nothing at all."""
    _log(tmp_path, _minutes(30, end=NOW - timedelta(minutes=45)))
    _fanin(tmp_path, [{"source": "db_hygiene", "item": "T:1", "severity": "P1", "detail": "x",
                       "detected_at": NOW.isoformat(), "event_id": "e1", "state": "ARTIFACT_WRITTEN"}],
           as_of=NOW - timedelta(hours=2))
    first = Capture()
    rec = _run(tmp_path, NOW - timedelta(hours=2) + timedelta(minutes=1), first)      # fresh fan-in: P1 db_hygiene
    assert rec["status"] == "OK" and len(first.calls) == 1
    cap = Capture()
    rec = _run(tmp_path, NOW, cap)
    assert rec["status"] == "HOST_ONLY:STALE" and rec["fanin"]["status"] == "STALE"
    assert [m["kind"] for m in rec["messages"]] == ["p1"] and len(cap.calls) == 1
    assert "n8n_alert_path n8n-schedule:stalled" in cap.calls[0]["text"]
    assert "tradeai-incident-router:stalled" in cap.calls[0]["text"]
    state = json.loads((tmp_path / N.STATE_REL).read_text())
    db = state["notified"][N.incident_key("db_hygiene", "T:1")]
    assert db["open"] is True                       # the fan-in incident is NOT declared recovered from stale input
    again = Capture()
    assert _run(tmp_path, NOW + timedelta(minutes=5), again)["messages"] == [] and again.calls == []   # deduped


def test_alert_path_recovers_once_cadence_returns_even_with_a_stale_fanin(tmp_path):
    _log(tmp_path, _minutes(30, end=NOW - timedelta(minutes=45)))
    _run(tmp_path, NOW, Capture())
    _log(tmp_path, _minutes(3, end=NOW + timedelta(hours=2)))
    cap = Capture()
    rec = _run(tmp_path, NOW + timedelta(hours=2), cap)
    assert [m["kind"] for m in rec["messages"]] == ["recovery"] and "RECOVERED" in cap.calls[0]["text"]


def test_no_relay_log_and_no_fanin_keeps_the_old_no_input_behaviour(tmp_path):
    rec = _run(tmp_path, NOW, Capture())
    assert rec["status"] == "NO_INPUT:MISSING" and rec["messages"] == []
    assert rec["alert_path"]["note"] == "relay_log:absent"


def test_fresh_fanin_merges_alert_path_rows_with_its_own(tmp_path):
    _log(tmp_path, _minutes(10) + [_due(NOW - timedelta(minutes=1), lanes=ROUTER, state="REFUSED", reason="x")])
    _fanin(tmp_path, [{"source": "db_hygiene", "item": "T:1", "severity": "P2", "detail": "x",
                       "detected_at": NOW.isoformat(), "event_id": "e1", "state": "ARTIFACT_WRITTEN"}], as_of=NOW)
    cap = Capture()
    rec = _run(tmp_path, NOW, cap)
    assert rec["status"] == "OK" and rec["alert_path"]["open"] == ["tradeai-incident-router:error"]
    assert [m["kind"] for m in rec["messages"]][0] == "p1"
    assert "tradeai-incident-router:error" in cap.calls[0]["text"]


def test_dry_run_plans_the_p1_and_writes_no_state(tmp_path):
    _log(tmp_path, _minutes(30, end=NOW - timedelta(minutes=45)))
    rec = N.run(live=False, root=tmp_path, now=NOW, env={"TRADEAI_SERVED_SHA": "t"},
                previewer=lambda text, **kw: {"would_send": False, "reason": "ci"},
                ledger_path=tmp_path / "no_ledger.sqlite")
    assert [(m["kind"], m["status"]) for m in rec["messages"]] == [("p1", "DRY_RUN")]
    assert not (tmp_path / N.STATE_REL).exists()


def test_fanin_also_carries_the_alert_path_for_the_siem(tmp_path, monkeypatch):
    _log(tmp_path, _minutes(30, end=NOW - timedelta(minutes=45)))
    found = fanin._alert_path_findings(tmp_path, NOW)
    assert _items(found) == ["n8n-schedule:stalled", "tradeai-incident-router:stalled"]
    assert fanin.NOTES["alert_path_source"].startswith("ok:2:")
