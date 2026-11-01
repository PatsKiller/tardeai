"""ANCHOR: RELAY_LIVE_SET_FOLLOWUPS_20261101

Round-3 follow-ups to the relay live-set gate (#2424):
  * a page that was not accepted no longer suppresses that diff_id's page forever (two-phase marker, nothing deleted);
  * the poller recomputes a held diff each tick, so a stale hold clears and a changed delta moves the hold;
  * acknowledgement semantics: expired and replaced grants count when their window reached the hold, revoked never.
Hermetic: temp state roots, injected senders, no network, no real prepare/promote.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from scripts.lib import deploy_on_main as DM
from scripts.lib import relay_live_set_gate as G

REPORT = {"diff_id": "abcdef0123456789", "new_build": "d" * 40, "added": ["x"], "removed": [], "changed": True}


def _files(state: Path) -> list[str]:
    base = state / G.PAGED_REL
    return sorted(p.name for p in base.iterdir()) if base.is_dir() else []


class _Sender:
    def __init__(self, *outcomes):
        self.outcomes, self.calls = list(outcomes), 0

    def __call__(self, text, **kw):
        self.calls += 1
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


# ── (1) two-phase page marker ─────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("failure", [RuntimeError("telegram down"), False])
def test_a_send_that_is_not_accepted_leaves_the_diff_pageable(tmp_path: Path, failure) -> None:
    send = _Sender(failure, True, True)
    first = G.notify(REPORT, tmp_path, sender=send)
    assert first["accepted"] is False and first["retry"] == "next_prepare"
    assert not (tmp_path / G.PAGED_REL / "abcdef0123456789-promote.json").exists()
    assert any(".send_failed-" in n for n in _files(tmp_path))
    second = G.notify(REPORT, tmp_path, sender=send)
    assert second["accepted"] is True
    third = G.notify(REPORT, tmp_path, sender=send)
    assert third == {"accepted": False, "skipped": "already_paged", "marker": second["marker"]}
    assert send.calls == 2


def test_the_paged_marker_exists_only_after_an_accepted_send(tmp_path: Path) -> None:
    seen = {}

    def sender(text, **kw):
        seen["paged_during_send"] = (tmp_path / G.PAGED_REL / "abcdef0123456789-promote.json").exists()
        seen["claim_during_send"] = (tmp_path / G.PAGED_REL / "abcdef0123456789-promote.sending").exists()
        return True

    assert G.notify(REPORT, tmp_path, sender=sender)["accepted"] is True
    assert seen == {"paged_during_send": False, "claim_during_send": True}
    assert _files(tmp_path) == ["abcdef0123456789-promote.json"]


def test_a_fresh_sending_claim_blocks_a_concurrent_send(tmp_path: Path) -> None:
    base = tmp_path / G.PAGED_REL
    base.mkdir(parents=True)
    (base / "abcdef0123456789-promote.sending").write_text("{}\n", encoding="utf-8")
    send = _Sender(True)
    assert G.notify(REPORT, tmp_path, sender=send)["skipped"] == "send_in_progress"
    assert send.calls == 0


def test_a_stale_sending_claim_is_taken_over_not_deleted(tmp_path: Path) -> None:
    base = tmp_path / G.PAGED_REL
    base.mkdir(parents=True)
    claim = base / "abcdef0123456789-promote.sending"
    claim.write_text("{}\n", encoding="utf-8")
    old = time.time() - G.SENDING_STALE_S - 5
    os.utime(claim, (old, old))
    send = _Sender(True)
    assert G.notify(REPORT, tmp_path, sender=send)["accepted"] is True
    assert send.calls == 1


def test_markers_are_never_deleted_across_failures_and_retries(tmp_path: Path) -> None:
    send = _Sender(RuntimeError("x"), False, True)
    counts = []
    for _ in range(4):
        G.notify(REPORT, tmp_path, sender=send)
        counts.append(len(_files(tmp_path)))
    assert counts == sorted(counts)  # the record of every attempt survives
    assert sum(".send_failed-" in n for n in _files(tmp_path)) == 2


def test_a_new_diff_id_pages_even_with_old_markers_present(tmp_path: Path) -> None:
    G.notify(REPORT, tmp_path, sender=_Sender(True))
    other = dict(REPORT, diff_id="1111111111111111")
    assert G.notify(other, tmp_path, sender=_Sender(True))["accepted"] is True


# ── (3) acknowledgement semantics ─────────────────────────────────────────────────────────────────────────────

NOW = int(time.time())
HELD = NOW - 3600


def _row(status="active", expires=NOW + 3600, reason="relay-live-set:abcdef0123456789", tier="release-write"):
    return {"r@g": {"tier": tier, "status": status, "expires": expires, "reason": reason, "grant_id": "g"}}


@pytest.mark.parametrize(
    "row,since,acked",
    [
        (_row(), HELD, True),
        (_row(status="active", expires=NOW - 60), HELD, True),       # expired after the hold: counts
        (_row(status="active", expires=HELD - 60), HELD, False),     # window ended before the hold: does not
        (_row(status="replaced", expires=NOW + 3600), HELD, True),   # superseded via --replace: counts
        (_row(status="replaced", expires=HELD - 60), HELD, False),
        (_row(status="revoked"), HELD, False),                        # revoked never counts
        (_row(status="revoked"), None, False),
        (_row(status="active", expires=NOW - 86400 * 30), None, True),  # promote gate (no hold time): content hash binds
        (_row(reason="relay-live-set:1111111111111111"), HELD, False),
        (_row(tier="git-push"), HELD, False),
        (_row(expires="garbage"), HELD, False),
    ],
)
def test_acknowledgement_semantics(row, since, acked) -> None:
    assert G.is_acked(REPORT, row, since=since) is acked


# ── (2) held diff recomputed each tick ────────────────────────────────────────────────────────────────────────

def _hold(sd: Path, **extra) -> None:
    DM._save_hold(sd, {"status": "held", "main_sha": "s1", "diff_id": "abcdef0123456789",
                       "held_at": "2026-11-01T02:00:00Z", "release": "/r/new", **extra})


def test_a_stale_hold_clears_when_the_change_disappears(monkeypatch, tmp_path: Path) -> None:
    _hold(tmp_path)
    monkeypatch.setattr(DM, "hold_recompute", lambda hold: {"changed": False, "diff_id": "ffffffffffffffff"})
    monkeypatch.setattr(DM, "hold_acknowledged", lambda did, since=None: pytest.fail("no ack needed"))
    assert DM.hold_blocks(tmp_path, "s1") is None
    hold = DM.load_hold(tmp_path)
    assert hold["status"] == "cleared_no_change" and hold["diff_id"] == "abcdef0123456789"  # rewritten, kept


def test_a_changed_delta_moves_the_hold_to_the_new_diff_id(monkeypatch, tmp_path: Path) -> None:
    _hold(tmp_path)
    asked = []
    monkeypatch.setattr(DM, "hold_recompute", lambda hold: {"changed": True, "diff_id": "2222222222222222"})
    monkeypatch.setattr(DM, "hold_acknowledged",
                        lambda did, since=None: asked.append((did, since)) or ({"grant_id": "g"} if did == "abcdef0123456789" else None))
    held = DM.hold_blocks(tmp_path, "s1")
    assert held is not None and held["diff_id"] == "2222222222222222"
    assert held["previous_diff_ids"] == ["abcdef0123456789"]
    assert asked == [("2222222222222222", DM._epoch("2026-11-01T02:00:00Z"))]  # the old ack no longer applies
    assert DM.load_hold(tmp_path)["status"] == "held"


def test_an_unrecomputable_hold_keeps_holding(monkeypatch, tmp_path: Path) -> None:
    _hold(tmp_path)
    monkeypatch.setattr(DM, "hold_recompute", lambda hold: None)
    monkeypatch.setattr(DM, "hold_acknowledged", lambda did, since=None: None)
    assert DM.hold_blocks(tmp_path, "s1")["diff_id"] == "abcdef0123456789"


def test_the_hold_time_is_passed_as_since(monkeypatch, tmp_path: Path) -> None:
    _hold(tmp_path)
    got = {}
    monkeypatch.setattr(DM, "hold_recompute", lambda hold: None)
    monkeypatch.setattr(DM, "hold_acknowledged", lambda did, since=None: got.update(since=since) or None)
    DM.hold_blocks(tmp_path, "s1")
    assert got["since"] == DM._epoch("2026-11-01T02:00:00Z") and got["since"] > 0


def test_hold_recompute_without_a_release_or_with_a_failing_compute_is_none(monkeypatch, tmp_path: Path) -> None:
    assert DM.hold_recompute({"release": ""}) is None
    assert DM.hold_recompute({"release": str(tmp_path / "gone")}) is None
    monkeypatch.setattr(G, "compute", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    assert DM.hold_recompute({"release": str(tmp_path)}) is None


def test_hold_recompute_uses_the_gate_against_current(monkeypatch, tmp_path: Path) -> None:
    seen = {}
    monkeypatch.setattr(G, "host_env", lambda path: {"k": "v"})
    monkeypatch.setattr(G, "compute", lambda new, served, env: seen.update(new=new, served=served, env=env) or {"changed": True})
    monkeypatch.setattr(DM, "DEFAULT_RELEASES", tmp_path)
    (tmp_path / "CURRENT").mkdir()
    assert DM.hold_recompute({"release": str(tmp_path)}) == {"changed": True}
    assert seen == {"new": tmp_path, "served": (tmp_path / "CURRENT").resolve(), "env": {"k": "v"}}


def test_the_held_release_is_parsed_from_the_deploy_die_line() -> None:
    log = ("RELAY_LIVE_SET_HELD diff_id=0123456789abcdef: x\nERROR: relay live set would change and the operator has "
           "not acknowledged this diff_id — promote held (/home/u/rel/abc-main/N8N_RELAY_LIVE_SET_DIFF.json)")
    assert DM.held_release(log) == "/home/u/rel/abc-main"
    assert DM.held_release("no die line") == ""
