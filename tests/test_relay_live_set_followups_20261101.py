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


# ── (round 4) an unreadable live set is INDETERMINATE: hold, refuse, page once; never "unchanged" ──────────────

from scripts.lib import n8n_relay_live_lanes as RLL  # noqa: E402
from tests.test_relay_live_source_oneway_20261031 import _root  # noqa: E402

BAD_OVERRIDES = {"zero_byte": "", "malformed_json": "{not json", "wrong_schema": "[1, 2, 3]"}


@pytest.fixture()
def one_lane_change(tmp_path: Path):
    """A real one-lane change: served drops the live arg of one lane that the new release serves."""
    state = tmp_path / "state"
    state.mkdir()
    env = {"TRADEAI_STATE_ROOT": str(state)}
    probe = _root(tmp_path, "probe")
    lane = sorted(RLL.resolve(env, probe)["lanes"])[0]
    served = _root(tmp_path, "served", drop_live_arg=lane)
    new = _root(tmp_path, "new", build="b" * 40)
    rep = G.compute(new, served, env)
    assert rep["changed"] is True and rep["added"] == [lane] and rep["indeterminate"] is False
    return {"new": new, "served": served, "env": env, "state": state, "lane": lane, "report": rep}


def _break_overrides(state: Path, text: str) -> None:
    p = state / RLL.OVERRIDE_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


@pytest.mark.parametrize("kind", sorted(BAD_OVERRIDES))
def test_unreadable_overrides_make_the_diff_indeterminate_and_the_gate_refuses(one_lane_change, kind) -> None:
    c = one_lane_change
    _break_overrides(c["state"], BAD_OVERRIDES[kind])
    rep = G.compute(c["new"], c["served"], c["env"])
    assert rep["indeterminate"] is True
    assert set(rep["indeterminate_reasons"]) == {"new", "served"}
    assert G.gate(rep, rows={}) == (False, "indeterminate")
    # Even a grant naming this exact diff_id does not pass an unknown live set.
    row = {"r@g": {"tier": "release-write", "status": "active", "expires": NOW + 3600, "grant_id": "g",
                   "reason": f"relay-live-set:{rep['diff_id']}"}}
    assert G.gate(rep, rows=row) == (False, "indeterminate")


def test_both_resolvers_failing_is_indeterminate(monkeypatch, one_lane_change) -> None:
    c = one_lane_change
    monkeypatch.setattr(G, "effective", lambda root, environ: {
        "lanes": None, "source": "resolver_failed", "detail": "own resolver failed: timeout", "paused": [],
        "resolver": "own_failed"})
    rep = G.compute(c["new"], c["served"], c["env"])
    assert rep["changed"] is False  # what used to pass the gate as "unchanged"
    assert rep["indeterminate"] is True and G.gate(rep, rows={}) == (False, "indeterminate")


def test_one_side_failing_closed_with_an_empty_list_is_indeterminate(monkeypatch, one_lane_change) -> None:
    c = one_lane_change
    real = G.effective

    def eff(root, environ):
        if Path(root) == c["served"]:
            return {"lanes": [], "source": "registry_render", "detail": "override_unreadable: fail closed, no lane live",
                    "paused": [], "resolver": "own"}
        return real(root, environ)

    monkeypatch.setattr(G, "effective", eff)
    rep = G.compute(c["new"], c["served"], c["env"])
    assert rep["indeterminate"] is True and list(rep["indeterminate_reasons"]) == ["served"]
    assert G.gate(rep, rows={}) == (False, "indeterminate")


@pytest.mark.parametrize("breakage", ["zero_byte", "malformed_json", "resolver_failed"])
def test_a_held_promote_keeps_holding_when_the_recompute_is_indeterminate(monkeypatch, tmp_path: Path,
                                                                         one_lane_change, breakage) -> None:
    c = one_lane_change
    if breakage == "resolver_failed":
        monkeypatch.setattr(G, "effective", lambda root, environ: {
            "lanes": None, "source": "resolver_failed", "detail": "timeout", "paused": [], "resolver": "own_failed"})
    else:
        _break_overrides(c["state"], BAD_OVERRIDES[breakage])
    releases = tmp_path / "releases"
    releases.mkdir()
    (releases / "CURRENT").symlink_to(c["served"])
    monkeypatch.setattr(DM, "DEFAULT_RELEASES", releases)
    monkeypatch.setattr(G, "host_env", lambda path: dict(c["env"]))
    monkeypatch.setattr(DM, "hold_acknowledged", lambda did, since=None: pytest.fail("an unknown set is not acked"))
    sd = tmp_path / "rw"
    did = c["report"]["diff_id"]
    DM._save_hold(sd, {"status": "held", "main_sha": "s1", "diff_id": did, "held_at": "2026-11-01T03:00:00Z",
                       "release": str(c["new"])})
    for _ in range(3):
        held = DM.hold_blocks(sd, "s1")
        assert held is not None and held["diff_id"] == did
    hold = DM.load_hold(sd)
    assert hold["status"] == "held" and hold["last_recompute"] == "indeterminate"
    assert "previous_diff_ids" not in hold


def test_the_gate_cli_refuses_and_pages_once_on_indeterminate(monkeypatch, one_lane_change) -> None:
    import scripts.relay_live_set_gate as CLI

    c = one_lane_change
    _break_overrides(c["state"], "")
    pages = []
    monkeypatch.setattr(CLI.G, "notify", lambda report, state, event="promote", sender=None:
                        pages.append(event) or {"accepted": True})
    monkeypatch.setenv("TRADE_AI_CI", "0")
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(c["state"]))
    argv = ["--release", str(c["new"]), "--served", str(c["served"]), "--host-file", str(c["state"] / "no.env")]
    assert CLI.main(["gate", *argv]) == 3
    assert CLI.main(["diff", *argv, "--notify"]) == 0
    assert pages == ["indeterminate", "indeterminate"]  # one marker key: notify's two-phase marker pages it once


def test_indeterminate_page_names_no_path_and_no_command() -> None:
    rep = dict(REPORT, indeterminate=True, indeterminate_reasons={"served": "override_unreadable: fail closed"})
    text = G.message(rep, event="promote")
    assert "UNKNOWN" in text and "abcdef0123456789" in text and "/" not in text.replace("n/a", "")


def test_indeterminate_pages_once_through_the_real_marker(tmp_path: Path) -> None:
    rep = dict(REPORT, indeterminate=True, indeterminate_reasons={"new": "x"})
    send = _Sender(True, True)
    assert G.notify(rep, tmp_path, event="indeterminate", sender=send)["accepted"] is True
    assert G.notify(rep, tmp_path, event="indeterminate", sender=send)["skipped"] == "already_paged"
    assert send.calls == 1


@pytest.mark.parametrize(
    "eff,unknown",
    [
        ({"lanes": None, "source": "registry_render", "detail": "render_missing; key unset"}, True),
        ({"lanes": [], "source": "resolver_failed", "detail": "x"}, True),
        ({"lanes": [], "source": "registry_render", "detail": "override_unreadable: fail closed, no lane live"}, True),
        ({"lanes": [], "source": "registry_render", "detail": "override_malformed: fail closed, no lane live"}, True),
        ({"lanes": ["a"], "source": "host_env_fallback", "detail": "render_unreadable"}, True),
        ({"lanes": ["a"], "source": "host_env_fallback", "detail": "render_malformed"}, True),
        ({"lanes": [], "source": "registry_render", "detail": "ok"}, False),  # a real empty set is known
        ({"lanes": ["a"], "source": "host_env_legacy", "detail": "AGENTS.md 20.4.0 not ACTIVE"}, False),
    ],
)
def test_indeterminate_reason(eff, unknown) -> None:
    assert (G.indeterminate_reason(eff) is not None) is unknown
