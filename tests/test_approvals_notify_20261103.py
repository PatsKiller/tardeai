"""Home v008 piece D — approvals reach Telegram as ONE batched nudge, never a message per request.

Operator spec §4: one short message per NEW request, batched, never repeated more than every 2 h;
quiet hours 22:00–07:00 where only P0 pages and everything else waits on the dashboard; and incident
escalations are one digest, not six P1s. The approvals nudge and the incident digest share
``scripts/lib/telegram_batch.py`` — these tests pin both halves of that one mechanism.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import approvals_notify as A  # noqa: E402
from scripts.lib.telegram_batch import NudgeState, batch_text, nudge_decision  # noqa: E402


def write_requests(path: Path, ids, *, kind="merge_pr", **extra):
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [{"schema": "ApprovalRequestEvent@v1", "event": "created", "id": i, "type": kind,
             "title": f"Merge #{i.rsplit('_', 1)[-1]}", "why": "the reviewed head must not move",
             "requester": "cc-deepseek-7", "created_at": "2026-11-03T12:00:00Z",
             "expires_at": "2026-11-05T12:00:00Z", "facts": {"pr": i.rsplit("_", 1)[-1]}, **extra}
            for i in ids]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


class Sent:
    def __init__(self, ok=True):
        self.calls = []
        self.ok = ok

    def __call__(self, text, *, priority="P2"):
        self.calls.append({"text": text, "priority": priority})
        return self.ok


def go(tmp_path, now, *, sent=None, requests_path=None, cfg=None):
    cfg_path = tmp_path / "approvals_notify.json"
    cfg_path.write_text(json.dumps(cfg or {"repeat_floor_minutes": 120, "priority": "P2"}), encoding="utf-8")
    return A.run(requests_path=requests_path or tmp_path / "requests.jsonl",
                 state_dir=tmp_path / "state", config_path=cfg_path,
                 now=now, dry_run=sent is None, notify=sent)


# ------------------------------------------------------------------ one message per run
def test_six_new_requests_produce_exactly_one_message(tmp_path):
    write_requests(tmp_path / "requests.jsonl", [f"apr_251{i}" for i in range(6)])
    sent = Sent()
    receipt = go(tmp_path, "2026-11-03T13:00:00Z", sent=sent)

    assert len(sent.calls) == 1, sent.calls                       # six requests, ONE nudge
    msg = sent.calls[0]["text"]
    assert msg.startswith("6 decisions need you")
    assert msg.count("•") == 6
    assert all(f"apr_251{i}" not in msg for i in range(6))        # titles, not internal ids
    assert msg.count("Merge #251") == 6
    assert "Approve or decline on Home" in msg
    assert sent.calls[0]["priority"] == "P2"
    assert receipt["send"] is True and len(receipt["keys"]) == 6


def test_the_same_open_requests_are_not_repeated_within_two_hours(tmp_path):
    write_requests(tmp_path / "requests.jsonl", ["apr_2518"])
    sent = Sent()
    go(tmp_path, "2026-11-03T13:00:00Z", sent=sent)
    receipt = go(tmp_path, "2026-11-03T14:59:00Z", sent=sent)

    assert len(sent.calls) == 1
    assert receipt["send"] is False and receipt["reason"] == "nothing due"


def test_a_still_open_request_is_re_nudged_after_two_hours(tmp_path):
    write_requests(tmp_path / "requests.jsonl", ["apr_2518"])
    sent = Sent()
    go(tmp_path, "2026-11-03T13:00:00Z", sent=sent)
    go(tmp_path, "2026-11-03T15:01:00Z", sent=sent)

    assert len(sent.calls) == 2
    assert sent.calls[1]["text"].startswith("1 decision needs you")


def test_a_new_request_joins_the_batch_even_when_the_old_one_is_not_due(tmp_path):
    write_requests(tmp_path / "requests.jsonl", ["apr_2518"])
    sent = Sent()
    go(tmp_path, "2026-11-03T13:00:00Z", sent=sent)             # apr_2518 nudged
    write_requests(tmp_path / "requests.jsonl", ["apr_2518"])
    with (tmp_path / "requests.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"event": "created", "id": "apr_2600", "type": "merge_pr",
                             "title": "Merge #2600", "why": "release train", "requester": "cc-deepseek-7",
                             "created_at": "2026-11-03T13:30:00Z", "expires_at": "2026-11-04T13:30:00Z"}) + "\n")
    go(tmp_path, "2026-11-03T13:30:00Z", sent=sent)

    assert len(sent.calls) == 2
    assert "Merge #2600" in sent.calls[1]["text"]
    assert "Merge #2518" not in sent.calls[1]["text"]           # the old one is not due yet


# ------------------------------------------------------------------ quiet hours
def test_quiet_hours_hold_everything_and_0745_sends_one_catch_up(tmp_path):
    write_requests(tmp_path / "requests.jsonl", [f"apr_25{i}" for i in range(6)])
    sent = Sent()
    # 23:30 ET = 04:30Z next day: inside the 22:00–07:00 operator window.
    receipt = go(tmp_path, "2026-11-04T04:30:00Z", sent=sent)

    assert sent.calls == []
    assert receipt["reason"].startswith("quiet hours")

    go(tmp_path, "2026-11-04T12:45:00Z", sent=sent)             # 07:45 ET: one message, all six
    assert len(sent.calls) == 1
    assert sent.calls[0]["text"].startswith("6 decisions need you")


def test_a_zero_page_priority_never_overrides_the_quiet_window(tmp_path):
    state = NudgeState(tmp_path / "nudge_state.json")
    from datetime import datetime
    d = nudge_decision(keys=["apr_1"], state=state, now=datetime.fromisoformat("2026-11-04T04:30:00+00:00"),
                       priority="P2", quiet=True)
    assert d["send"] is False and d.get("held") is True
    d1 = nudge_decision(keys=["apr_1"], state=state, now=datetime.fromisoformat("2026-11-04T04:30:00+00:00"),
                        priority="P1", quiet=True)
    assert d1["send"] is True and d1["priority"] == "P1"


# ------------------------------------------------------------------ what is never nudged
def test_resolved_expired_and_future_requests_are_not_nudged(tmp_path):
    p = tmp_path / "requests.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(r) for r in [
        {"event": "created", "id": "apr_open", "type": "merge_pr", "title": "Merge #1",
         "expires_at": "2026-11-04T00:00:00Z"},
        {"event": "resolved", "id": "apr_done", "type": "merge_pr", "title": "Merge #2"},
        {"event": "created", "id": "apr_expired", "type": "merge_pr", "title": "Merge #3",
         "expires_at": "2026-11-03T11:00:00Z"},
    ]) + "\n", encoding="utf-8")
    sent = Sent()
    receipt = go(tmp_path, "2026-11-03T13:00:00Z", sent=sent, requests_path=p)

    assert receipt["keys"] == ["apr_open"]
    assert len(sent.calls) == 1 and "Merge #1" in sent.calls[0]["text"]


def test_a_failed_send_consumes_nothing_so_the_next_cycle_retries(tmp_path):
    write_requests(tmp_path / "requests.jsonl", ["apr_2518"])
    bad, good = Sent(ok=False), Sent()
    first = go(tmp_path, "2026-11-03T13:00:00Z", sent=bad)
    second = go(tmp_path, "2026-11-03T13:01:00Z", sent=good)

    assert first["send"] is False and first["reason"].startswith("send failed")
    assert second["send"] is True and "Merge #2518" in good.calls[0]["text"]


def test_dry_run_sends_nothing(tmp_path):
    write_requests(tmp_path / "requests.jsonl", ["apr_2518"])
    receipt = go(tmp_path, "2026-11-03T13:00:00Z")
    assert receipt["send"] is False and "would send" in receipt["reason"]
    assert not (tmp_path / "state" / "nudge_state.json").exists()


# ------------------------------------------------------------------ the ONE shared mechanism
def test_the_incident_digest_uses_the_same_batch_helper():
    import inspect
    from scripts.lib import incident_supervisor as S

    src = inspect.getsource(S._batch_text)
    assert "_batch_message(" in src, "the incident digest must call the shared batch_text helper"
    here = batch_text(header="[P2] Incident supervisor — 2 escalation(s) this run (batched once per run)",
                      items=[{"title": "abc — ingest missed", "detail": "runbook · unresolved 120 min",
                              "next": "restart the unit", "link": "https://cc/incidents/abc"},
                             {"title": "def — writer stuck", "detail": "code_defect · unresolved 120 min",
                              "next": "open a fix request", "link": "https://cc/incidents/def"}],
                      footer="This batch contains an operator-only decision; no agent may act on it.")
    assert here.count("•") == 2 and here.count("Next:") == 2
    assert here.rstrip().endswith("no agent may act on it.")
