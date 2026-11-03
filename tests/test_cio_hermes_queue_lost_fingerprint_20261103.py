"""`requests_lost` must not count a request whose question is already in the projection.

2026-11-03: `res_c30a22ae6af8` (13:56:56Z) was reported lost while `res_cfaa3b471ead`
(13:56:54Z) carried the SAME fingerprint in `by_research_id` as `running`. The restore path
dedups on fingerprint; the health check counted the duplicate as lost and pinned the lane
critical. Hermetic: tmp ledger/projection only.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib.cio_hermes_queue_health import collect_cio_hermes_queue_health  # noqa: E402

NOW = datetime(2026, 11, 3, 16, 30, tzinfo=timezone.utc)
FP = "sha256:5876094632ebee8ad3e5d576a0890ffc496af97a7b3a79dcd07173e1d4bc320f"


@pytest.fixture(autouse=True)
def _no_env(monkeypatch):
    monkeypatch.delenv("CIO_HERMES_PROJECTION", raising=False)
    return None


def _ledger(tmp_path, projection, events):
    p = tmp_path / "hermes_research_requests.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    (tmp_path / "hermes_research_projection.json").write_text(json.dumps(projection))
    return p


def _requested(rid, fingerprint, *, minutes_ago=20, created_minutes_ago=None, updated_minutes_ago=None):
    """A HERMES_RESEARCH_REQUESTED ledger row. Real rows carry updated_ts; the event `ts` is its clock."""
    if updated_minutes_ago is None:
        updated_minutes_ago = minutes_ago
    row = {"event": "HERMES_RESEARCH_REQUESTED", "research_id": rid, "fingerprint": fingerprint,
           "ts": (NOW - timedelta(minutes=minutes_ago)).isoformat(),
           "updated_ts": (NOW - timedelta(minutes=updated_minutes_ago)).isoformat(), "status": "queued"}
    if created_minutes_ago is not None:
        row["created_ts"] = (NOW - timedelta(minutes=created_minutes_ago)).isoformat()
    return row


def test_same_fingerprint_open_entry_is_not_lost(tmp_path):
    ledger = _ledger(
        tmp_path,
        {"by_research_id": {"res_open": {"status": "running", "fingerprint": FP}},
         "by_fingerprint_open": {FP: {"research_id": "res_open"}}},
        [_requested("res_dup", FP)],
    )
    row = collect_cio_hermes_queue_health(now=NOW, path=ledger)
    assert row["lost_n"] == 0 and row["lost"] == []
    assert "requests_lost:1" not in row["firing"]
    assert row["ok"] is True


def test_completed_fingerprint_is_not_lost(tmp_path):
    """A genuine answer AFTER the request owns the question. (An undated or earlier answer does not — see the P1s.)"""
    ledger = _ledger(
        tmp_path,
        {"by_research_id": {},
         "by_fingerprint_completed": {FP: {"research_id": "res_done",
                                           "completed_ts": (NOW - timedelta(minutes=5)).isoformat()}}},
        [_requested("res_dup", FP)],
    )
    row = collect_cio_hermes_queue_health(now=NOW, path=ledger)
    assert row["lost_n"] == 0


def test_unowned_fingerprint_is_still_lost(tmp_path):
    ledger = _ledger(tmp_path, {"by_research_id": {}}, [_requested("res_lost", "sha256:deadbeef")])
    row = collect_cio_hermes_queue_health(now=NOW, path=ledger)
    assert row["lost_n"] == 1 and row["lost"] == ["res_lost"]
    assert "requests_lost:1" in row["firing"] and row["ok"] is False


def test_request_in_the_grace_window_is_not_lost(tmp_path):
    ledger = _ledger(tmp_path, {"by_research_id": {}}, [_requested("res_new", "sha256:cafe", minutes_ago=5)])
    row = collect_cio_hermes_queue_health(now=NOW, path=ledger)
    assert row["lost_n"] == 0


# ── cx-openai-4's two P1s: history must not own a question ─────────────────────────────────────────────────
def test_a_failed_owner_does_not_suppress_a_newer_missing_request(tmp_path, monkeypatch):
    """R1: a FAILED row from 30h ago with the same fingerprint cannot hide a request asked 20 minutes ago."""
    failed = {"fingerprint": FP, "status": "failed",
              "updated_ts": (NOW - timedelta(hours=30)).isoformat()}
    ledger = _ledger(tmp_path, {"by_research_id": {"res_old_failed": failed}}, [_requested("res_new", FP)])
    monkeypatch.setenv("CIO_HERMES_PROJECTION", str(tmp_path / "hermes_research_projection.json"))
    out = collect_cio_hermes_queue_health(path=ledger, now=NOW)
    assert out["lost_n"] == 1 and out["ok"] is False
    assert "res_new" in out["lost"]


def test_a_cancelled_or_superseded_owner_does_not_suppress(tmp_path, monkeypatch):
    for status in ("cancelled", "superseded", "failed"):
        proj = {"by_research_id": {"res_old": {"fingerprint": FP, "status": status,
                                               "updated_ts": (NOW - timedelta(hours=30)).isoformat()}}}
        ledger = _ledger(tmp_path, proj, [_requested("res_new", FP)])
        monkeypatch.setenv("CIO_HERMES_PROJECTION", str(tmp_path / "hermes_research_projection.json"))
        out = collect_cio_hermes_queue_health(path=ledger, now=NOW)
        assert out["lost_n"] == 1 and out["ok"] is False, status


def test_an_answer_older_than_the_request_does_not_suppress(tmp_path, monkeypatch):
    """R2: a completion 60 minutes before the request cannot own it."""
    done = {"completed_ts": (NOW - timedelta(minutes=80)).isoformat()}
    ledger = _ledger(tmp_path, {"by_research_id": {}, "by_fingerprint_completed": {FP: done}},
                     [_requested("res_new", FP, minutes_ago=20)])
    monkeypatch.setenv("CIO_HERMES_PROJECTION", str(tmp_path / "hermes_research_projection.json"))
    out = collect_cio_hermes_queue_health(path=ledger, now=NOW)
    assert out["lost_n"] == 1 and out["ok"] is False


def test_an_undated_completion_does_not_suppress(tmp_path, monkeypatch):
    ledger = _ledger(tmp_path, {"by_research_id": {}, "by_fingerprint_completed": {FP: {}}},
                     [_requested("res_new", FP, minutes_ago=20)])
    monkeypatch.setenv("CIO_HERMES_PROJECTION", str(tmp_path / "hermes_research_projection.json"))
    out = collect_cio_hermes_queue_health(path=ledger, now=NOW)
    assert out["lost_n"] == 1 and out["ok"] is False


def test_an_open_owner_and_an_answer_after_the_request_still_suppress(tmp_path, monkeypatch):
    """The two cases that must keep passing: a running duplicate, and an answer that came after the ask."""
    ledger = _ledger(tmp_path, {"by_fingerprint_open": {FP: {"status": "running"}}},
                     [_requested("res_new", FP)])
    monkeypatch.setenv("CIO_HERMES_PROJECTION", str(tmp_path / "hermes_research_projection.json"))
    assert collect_cio_hermes_queue_health(path=ledger, now=NOW)["lost_n"] == 0

    done = {"completed_ts": (NOW - timedelta(minutes=5)).isoformat()}
    ledger2 = _ledger(tmp_path, {"by_research_id": {}, "by_fingerprint_completed": {FP: done}},
                      [_requested("res_new", FP, minutes_ago=20)])
    monkeypatch.setenv("CIO_HERMES_PROJECTION", str(tmp_path / "hermes_research_projection.json"))
    assert collect_cio_hermes_queue_health(path=ledger2, now=NOW)["lost_n"] == 0


def test_a_ts_only_completion_is_not_a_valid_clock(tmp_path, monkeypatch):
    """The restore oracle never reads a bare `ts` as a completion clock, so neither may the health check."""
    ledger = _ledger(tmp_path, {"by_research_id": {},
                                "by_fingerprint_completed": {FP: {"ts": NOW.isoformat()}}},
                     [_requested("res_new", FP, minutes_ago=20)])
    monkeypatch.setenv("CIO_HERMES_PROJECTION", str(tmp_path / "hermes_research_projection.json"))
    out = collect_cio_hermes_queue_health(path=ledger, now=NOW)
    assert out["lost_n"] == 1 and out["ok"] is False


# ── cx-openai-4 WHOLE-HEAD residuals at a2a54ba03: the oracle's exact clock expressions ────────────────
def test_an_invalid_primary_completion_does_not_fall_through_to_as_of(tmp_path, monkeypatch):
    """R3: parse_ts(completed_ts or as_of or updated_ts) picks the FIRST POPULATED clock, then parses once.

    completed_ts is populated but invalid, so the oracle gets None and restores the request. Health
    must report it lost — falling through to `as_of` was a false all-clear.
    """
    done = {"completed_ts": "not-a-clock", "as_of": (NOW - timedelta(minutes=5)).isoformat()}
    ledger = _ledger(tmp_path, {"by_research_id": {}, "by_fingerprint_completed": {FP: done}},
                     [_requested("res_new", FP, minutes_ago=20)])
    monkeypatch.setenv("CIO_HERMES_PROJECTION", str(tmp_path / "hermes_research_projection.json"))
    out = collect_cio_hermes_queue_health(path=ledger, now=NOW)
    assert out["lost_n"] == 1 and out["ok"] is False
    assert "res_new" in out["lost"]


def test_two_invalid_populated_clocks_do_not_fall_through(tmp_path, monkeypatch):
    """R3: invalid completed_ts + invalid updated_ts, with no as_of, is no completion clock at all."""
    done = {"completed_ts": "not-a-clock", "updated_ts": "also-not-a-clock"}
    ledger = _ledger(tmp_path, {"by_research_id": {}, "by_fingerprint_completed": {FP: done}},
                     [_requested("res_new", FP, minutes_ago=20)])
    monkeypatch.setenv("CIO_HERMES_PROJECTION", str(tmp_path / "hermes_research_projection.json"))
    out = collect_cio_hermes_queue_health(path=ledger, now=NOW)
    assert out["lost_n"] == 1 and out["ok"] is False


def test_the_asked_clock_is_created_not_the_event_update_time(tmp_path, monkeypatch):
    """R4: the oracle asks when the request was CREATED (or last updated), never when the event fired.

    Created 40 min ago, event/update 20 min ago, answer 30 min ago: the answer came after the ask,
    so the request is genuinely owned and the health check must not alarm on it.
    """
    req = _requested("res_new", FP, minutes_ago=20, created_minutes_ago=40, updated_minutes_ago=20)
    done = {"completed_ts": (NOW - timedelta(minutes=30)).isoformat()}
    ledger = _ledger(tmp_path, {"by_research_id": {}, "by_fingerprint_completed": {FP: done}}, [req])
    monkeypatch.setenv("CIO_HERMES_PROJECTION", str(tmp_path / "hermes_research_projection.json"))
    out = collect_cio_hermes_queue_health(path=ledger, now=NOW)
    assert out["lost_n"] == 0 and out["ok"] is True


def test_the_asked_clock_falls_back_to_updated_when_created_is_absent(tmp_path, monkeypatch):
    """R4: no created_ts, updated_ts 20 min ago — still the request's own clock, not the event's."""
    req = _requested("res_new", FP, minutes_ago=20, updated_minutes_ago=20)
    done = {"completed_ts": (NOW - timedelta(minutes=15)).isoformat()}
    ledger = _ledger(tmp_path, {"by_research_id": {}, "by_fingerprint_completed": {FP: done}}, [req])
    monkeypatch.setenv("CIO_HERMES_PROJECTION", str(tmp_path / "hermes_research_projection.json"))
    assert collect_cio_hermes_queue_health(path=ledger, now=NOW)["lost_n"] == 0


def test_one_valid_duplicate_and_two_real_losses_stays_unhealthy(tmp_path, monkeypatch):
    """Suppression is per question: one owned duplicate must not hide two genuinely lost requests."""
    ledger = _ledger(
        tmp_path,
        {"by_research_id": {"res_open": {"status": "running", "fingerprint": FP}},
         "by_fingerprint_open": {FP: {"research_id": "res_open"}}},
        [_requested("res_dup", FP), _requested("res_l1", "sha256:aaaa"), _requested("res_l2", "sha256:bbbb")],
    )
    monkeypatch.setenv("CIO_HERMES_PROJECTION", str(tmp_path / "hermes_research_projection.json"))
    out = collect_cio_hermes_queue_health(path=ledger, now=NOW)
    assert out["lost_n"] == 2 and out["lost"] == ["res_l1", "res_l2"]
    assert "requests_lost:2" in out["firing"]
    assert out["ok"] is False



# ── unreadable inputs are never healthy (lead ruling, 2026-11-03) ─────────────────────────────
# cx-openai-2 and cc-deepseek-3 both found the same shape: a 0-byte/invalid/missing/directory input
# reported ok=True with lost_n 0 (or no number at all). "I could not read it" is not "nothing is lost".
DAMAGE = ("zero_byte", "invalid", "missing", "directory")


def _damage_file(path, kind):
    if kind == "zero_byte":
        path.write_bytes(b"")
    elif kind == "invalid":
        path.write_text("{not json\nnot json either\n", encoding="utf-8")
    elif kind == "directory":
        if path.exists():
            path.unlink()
        path.mkdir()
    # "missing": leave it absent


@pytest.mark.parametrize("kind", DAMAGE)
def test_an_unreadable_ledger_is_never_healthy(tmp_path, kind):
    ledger = tmp_path / "hermes_research_requests.jsonl"
    _damage_file(ledger, kind)
    (tmp_path / "hermes_research_projection.json").write_text("{}", encoding="utf-8")
    out = collect_cio_hermes_queue_health(now=NOW, path=ledger)
    assert out["ok"] is False
    assert out["ledger_state"] in {"empty", "invalid", "absent", "unreadable"}
    assert f"request_ledger_unreadable:{out['ledger_state']}" in out["firing"]
    # No number from a file we did not read.
    assert out["lost_n"] is None and out["lost"] is None


@pytest.mark.parametrize("kind", DAMAGE)
def test_an_unreadable_projection_is_never_healthy(tmp_path, kind):
    ledger = _ledger(tmp_path, {}, [_requested("res_lost", "sha256:deadbeef")])
    proj = tmp_path / "hermes_research_projection.json"
    if kind == "missing":
        proj.unlink()  # _ledger wrote it; this case is the FILE absent
    else:
        _damage_file(proj, kind)
    out = collect_cio_hermes_queue_health(now=NOW, path=ledger)
    assert out["ok"] is False
    assert out["projection_state"] in {"empty", "unparseable", "absent", "unreadable"}
    assert f"projection_unreadable:{out['projection_state']}" in out["firing"]
    assert out["lost_n"] is None and out["lost"] is None


def test_the_payload_always_carries_both_read_states(tmp_path):
    ledger = _ledger(tmp_path, {"by_research_id": {}}, [_requested("res_lost", "sha256:deadbeef")])
    out = collect_cio_hermes_queue_health(now=NOW, path=ledger)
    assert out["ledger_state"] == "ok" and out["projection_state"] == "ok"
    assert out["lost_n"] == 1, "a valid empty projection plus one unowned request is still lost"


def test_a_directory_projection_and_a_valid_ledger_report_no_count(tmp_path):
    """The exact cc3 counterexample: directory-as-projection must not become ok=True."""
    ledger = _ledger(tmp_path, {}, [])
    proj = tmp_path / "hermes_research_projection.json"
    proj.unlink()
    proj.mkdir()
    out = collect_cio_hermes_queue_health(now=NOW, path=ledger)
    assert out["ok"] is False and out["projection_state"] == "unreadable"


def test_a_projection_without_by_research_id_still_reports_the_lost_request(tmp_path):
    """The lead's matrix: a VALID document missing the index is readable, so the request is really lost."""
    ledger = _ledger(tmp_path, {"schema": "HermesProjection@v1"}, [_requested("res_lost", "sha256:deadbeef")])
    out = collect_cio_hermes_queue_health(now=NOW, path=ledger)
    assert out["projection_state"] == "ok"
    assert out["ok"] is False and out["lost_n"] == 1 and out["lost"] == ["res_lost"]
