"""No-silence invariant: a T1 recovery case can never be suppressed.

Operator P0 2026-11-03 (SPEC_RECOVERY_REENTRY_ENGINE_20261103.md §3.3): Recovery Watch found re-entry
candidates for weeks, sent them with priority="P2", and the router answered P2_DASHBOARD_ONLY and the
publish path LEGACY_SHADOWED. The operator missed SPCX — his largest stop-out — recovering. This test
drives the real notify path and the real router classifier; only the Telegram transport is stubbed.

Hermetic: no DB, no network, no live Telegram, tmp state file only.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import recovery_notify as rn  # noqa: E402
import telegram_alert_router as router  # noqa: E402

COVERS = ["scripts/lib/recovery_notify.py", "scripts/telegram_alert_router.py", "scripts/telegram_alert.py"]


@pytest.fixture(autouse=True)
def _isolated_recovery_ledger(tmp_path, monkeypatch):
    """Every test writes its page ledger under tmp_path, never the real data/runtime file."""
    monkeypatch.setattr(router, "_RECOVERY_T1_PAGE_PATH", tmp_path / "recovery_t1_pages.jsonl")
    monkeypatch.setattr(router, "_RECOVERY_CLAIM_OWNERS", {}, raising=False)

POLICY = {"materiality": {"t1": {"loss_usd": 10000, "weight_pct": 3.0}}}


def _case(**kw):
    base = {
        "symbol": "SPCX",
        "price": 141.65,
        "exit_price": 137.19,
        "pct_vs_exit": 3.3,
        "realized_loss_usd": -12770,
        "pre_exit_weight_pct": 2.25,
        "state": "RECOVERING",
        "next_trigger": "reclaims 151.62 20-day mean",
        "eligibility": "IRA now; taxable 11-27",
        "plan": "restore 800 shares in two tranches",
    }
    base.update(kw)
    return base


class _Sender:
    def __init__(self):
        self.calls = []

    def __call__(self, message, **kwargs):
        self.calls.append((message, kwargs))
        return True


class _NudgeState:
    def __init__(self, path):
        self.path = path

    def due(self, keys, now, floor_minutes=120):
        # Default: the key IS due, so a bare {send: false} is NOT a verified floor.
        return list(keys)

    def note(self, keys, when):
        return {k: when.isoformat() for k in keys}

    def save(self, rows):
        return None


class _HeldNudgeState(_NudgeState):
    """A state whose key is genuinely inside the repeat floor (our own ledger says not due)."""

    def due(self, keys, now, floor_minutes=120):
        return []


def _fake_batch(monkeypatch):
    mod = types.ModuleType("lib.telegram_batch")
    mod.NudgeState = _NudgeState
    mod.batch_text = lambda *, header, items, footer=None: header + "\n" + items[0]["title"]
    mod.nudge_decision = lambda *, keys, state, now, priority="P2", floor_minutes=120: {
        "send": True, "keys": list(keys), "priority": priority}
    monkeypatch.setitem(sys.modules, "lib.telegram_batch", mod)
    return mod


# ── materiality comes from config, never from a constant in the code ─────────────────────────────────


def test_declared_tier_wins():
    assert rn.resolve_tier(_case(materiality_tier="T1"))[0] == "T1"
    assert rn.resolve_tier(_case(materiality_tier="T2"))[0] == "T2"


def test_tier_is_derived_from_the_config_thresholds():
    case = _case(realized_loss_usd=-12770, pre_exit_weight_pct=1.0)
    assert rn.resolve_tier(case, policy=POLICY)[0] == "T1"
    # The same case under a HIGHER configured T1 loss floor is T2: the number came from policy.
    higher = {"materiality": {"t1": {"loss_usd": 50000, "weight_pct": 3.0}}}
    assert rn.resolve_tier(case, policy=higher)[0] == "T2"


def test_unknown_materiality_resolves_loud():
    t, why = rn.resolve_tier({"symbol": "SPCX"})
    assert t == "T1" and "unknown" in why
    assert rn.resolve_tier({"symbol": "SPCX"}, policy={})[0] == "T1"


# ── the page itself ───────────────────────────────────────────────────────────────────────────────────


def test_t1_sends_as_p1_through_the_batch_module(monkeypatch):
    _fake_batch(monkeypatch)
    send = _Sender()
    out = rn.notify_recovery_case(_case(), policy=POLICY, sender=send, state_path="/tmp/does-not-matter.json")
    assert out["tier"] == "T1" and out["priority"] == "P1"
    assert out["sent"] is True and out["suppressed"] is False and out["path"] == "batch"
    assert len(send.calls) == 1
    _msg, kwargs = send.calls[0]
    assert kwargs.get("priority") == "P1"
    assert "P2" not in str(kwargs)


def test_t1_without_telegram_batch_falls_back_to_a_direct_p1(monkeypatch):
    # telegram_batch is not on this checkout until its own PR lands; the T1 page must still go out.
    monkeypatch.setitem(sys.modules, "lib.telegram_batch", None)
    send = _Sender()
    out = rn.notify_recovery_case(_case(), policy=POLICY, sender=send, state_path="/tmp/x.json")
    assert out["path"] == "direct" and out["sent"] is True and out["suppressed"] is False
    _msg, kwargs = send.calls[0]
    assert kwargs.get("priority") == "P1"
    assert kwargs.get("dedupe_minutes") == rn.DEFAULT_REPEAT_FLOOR_MINUTES


def test_t2_is_not_paged():
    send = _Sender()
    out = rn.notify_recovery_case(_case(materiality_tier="T2"), policy=POLICY, sender=send)
    assert out["sent"] is False and out["priority"] is None and send.calls == []


# ── the router can never downgrade a T1 recovery page ────────────────────────────────────────────────


def test_router_never_downgrades_a_t1_recovery_message():
    for case in (_case(), _case(state="RE_ENTRY_READY"), _case(next_trigger=None)):
        level = router.classify_alert(rn.build_message(case))
        assert level not in ("P2_DASHBOARD_ONLY", "P3_LOG_ONLY"), level
        assert level == "P0_INTERRUPT", level


def test_a_json_shaped_plan_cannot_demote_the_page():
    """The marker check precedes the raw-JSON guard.

    The marker starts with '[', so a recovery page whose plan/summary quotes a JSON fragment
    (`{"symbol": ..., "rationale": ...}`) satisfied looks_like_raw_json and was P3_LOG_ONLY when the
    raw-JSON guard ran first — the exact silence this marker exists to stop.
    """
    msg = rn.build_message(_case(plan='{"symbol":"SPCX","rationale":"reclaims the mean"}'))
    assert router.classify_alert(msg) == "P0_INTERRUPT"


def test_the_marker_is_on_the_first_line():
    msg = rn.build_message(_case())
    assert msg.splitlines()[0].startswith(rn.RECOVERY_T1_MARKER)
    assert rn.RECOVERY_T1_MARKER in msg


# ── cx-openai-2 whole-head BLOCK at 0a92a4cb4: F2, F3, F4, F5 ────────────────────────────────────────────

def test_nan_materiality_resolves_loud():
    """F2: NaN in both dimensions must be UNKNOWN, not a below-threshold T2."""
    import math
    send = _Sender()
    case = _case(realized_loss_usd=float("nan"), pre_exit_weight_pct=float("nan"))
    out = rn.notify_recovery_case(case, policy=POLICY, sender=send, state_path="/tmp/x.json")
    assert out["tier"] == "T1" and out["sent"] is True and send.calls, out


def test_partial_unknown_materiality_resolves_loud():
    """F2: a known dimension below threshold does not let an UNKNOWN other dimension become T2."""
    for case in (_case(realized_loss_usd=None, pre_exit_weight_pct=0.5),
                 _case(realized_loss_usd=500, pre_exit_weight_pct=None)):
        send = _Sender()
        out = rn.notify_recovery_case(case, policy=POLICY, sender=send, state_path="/tmp/x.json")
        assert out["tier"] == "T1" and send.calls, (case, out)


def test_nonfinite_policy_thresholds_are_unusable_and_resolve_loud():
    """F2: an infinite configured threshold is not a usable number."""
    policy = {"materiality": {"t1": {"loss_usd": float("inf"), "weight_pct": float("inf")}}}
    send = _Sender()
    out = rn.notify_recovery_case(_case(), policy=policy, sender=send, state_path="/tmp/x.json")
    assert out["tier"] == "T1" and send.calls, out


def test_an_unverified_negative_batch_decision_falls_through_to_direct(monkeypatch):
    """F3: {send:false, QUIET_HOURS} from a fresh state is NOT a verified repeat floor."""
    mod = types.ModuleType("lib.telegram_batch")
    mod.NudgeState = _NudgeState
    mod.batch_text = lambda *, header, items, footer=None: header + "\n" + items[0]["title"]
    mod.nudge_decision = lambda **kw: {"send": False, "reason": "QUIET_HOURS"}
    monkeypatch.setitem(sys.modules, "lib.telegram_batch", mod)
    send = _Sender()
    out = rn.notify_recovery_case(_case(), policy=POLICY, sender=send, state_path="/tmp/x.json")
    assert out["path"] == "direct" and out["sent"] is True and send.calls, out


def test_a_verified_repeat_floor_still_holds(monkeypatch):
    """F3: a genuine floor (our own ledger says not due) remains a recorded hold, not a page."""
    class HeldState(_NudgeState):
        def due(self, keys, now, floor_minutes=120):
            return []

    mod = types.ModuleType("lib.telegram_batch")
    mod.NudgeState = HeldState
    mod.batch_text = lambda *, header, items, footer=None: header + "\n" + items[0]["title"]
    mod.nudge_decision = lambda **kw: {"send": False, "reason": "repeat floor"}
    monkeypatch.setitem(sys.modules, "lib.telegram_batch", mod)
    send = _Sender()
    out = rn.notify_recovery_case(_case(), policy=POLICY, sender=send, state_path="/tmp/x.json")
    assert out["path"] == "batch" and out["sent"] is False and out["deduped_by_floor"] is True
    assert send.calls == []


def test_a_non_utf8_policy_resolves_loud(tmp_path):
    """F4: a damaged policy encoding must resolve T1, never raise."""
    bad = tmp_path / "recovery_policy.yaml"
    bad.write_bytes(b"\xff\xfe\x00broken")
    policy = rn.load_policy(bad)           # must not raise
    assert rn.resolve_tier(_case(realized_loss_usd=500, pre_exit_weight_pct=0.5), policy=policy)[0] == "T1"


def test_a_marked_t1_is_exempt_from_the_legacy_send_gates(monkeypatch, tmp_path):
    """F5: health-repeat, rate, daily budget and IGNORE filtering cannot suppress a marked T1."""
    monkeypatch.setattr(router, "_budget_count_today", lambda: 10 ** 6)
    monkeypatch.setattr(router, "_health_telegram_allowed", lambda message: False)
    monkeypatch.setattr(router, "_RECOVERY_T1_PAGE_PATH", tmp_path / "pages.json")
    assert router.should_send_telegram(rn.build_message(_case(case_id="spcx-a"))) is True
    marked_ignore = rn.build_message(_case(case_id="spcx-b", plan="escalation VERDICT IGNORE confidence 10%"))
    assert router.route_alert(marked_ignore)["send_telegram"] is True
    routed = router.route_alert(rn.build_message(_case(case_id="spcx-c")))
    assert "recovery_t1_exemptions" in routed and routed["recovery_t1_exemptions"]


def test_a_recovery_t1_pages_at_most_once_per_case_per_day(monkeypatch, tmp_path):
    """F5: the budget exemption is bounded explicitly by case id, and the bound is logged.

    ``consume=True`` is the explicit form for a caller that delivers directly after the gate; the
    DEFAULT is a preview (cc5 P1) and is covered separately below.
    """
    monkeypatch.setattr(router, "_budget_count_today", lambda: 10 ** 6)
    monkeypatch.setattr(router, "_RECOVERY_T1_PAGE_PATH", tmp_path / "pages.json")
    msg = rn.build_message(_case(case_id="spcx-20261030"))
    assert router.should_send_telegram(msg, consume=True) is True
    assert router.should_send_telegram(msg, consume=True) is False
    assert any("recovery_t1_daily_case_bound" == r.get("reason") for r in router.get_suppression_log())


def test_ordinary_alerts_still_hit_the_budget(monkeypatch, tmp_path):
    """F5 regression guard: an ordinary P0 alert is still budget-suppressed."""
    monkeypatch.setattr(router, "_budget_count_today", lambda: 10 ** 6)
    monkeypatch.setattr(router, "_RECOVERY_T1_PAGE_PATH", tmp_path / "pages.json")
    monkeypatch.setattr(router, "_ops_exempt", lambda message: False)
    monkeypatch.setattr(router, "classify_alert", lambda message: "P0_INTERRUPT")
    assert router.should_send_telegram("an ordinary system alert") is False


# ── second BLOCK round at fb6b646e3: F3, F5, F6, F2 remainder, F7 ───────────────────────────────────────

def test_two_accounts_same_symbol_and_state_are_two_cases(monkeypatch):
    """F3: the repeat key must include case identity; two accounts' cases both page."""
    _fake_batch(monkeypatch)
    send = _Sender()
    one = rn.notify_recovery_case(_case(case_id="spcx-taxable", account="schwab_taxable"),
                                  policy=POLICY, sender=send, state_path="/tmp/x.json")
    two = rn.notify_recovery_case(_case(case_id="spcx-ira", account="schwab_roth_ira"),
                                  policy=POLICY, sender=send, state_path="/tmp/x.json")
    assert one["sent"] is True and two["sent"] is True and len(send.calls) == 2


def test_the_batched_body_carries_the_case_key(monkeypatch):
    """F3: the router extracts case:<id> from the batch too, not only the direct body."""
    _fake_batch(monkeypatch)
    sent = []
    monkeypatch.setattr(sys.modules["lib.telegram_batch"], "batch_text",
                        lambda *, header, items, footer=None: sent.append(header) or header)
    out = rn.notify_recovery_case(_case(case_id="spcx-20261030"), policy=POLICY,
                                  sender=_Sender(), state_path="/tmp/x.json")
    assert rn.parse_case_token(sent[0]) == "spcx-20261030" and out["sent"] is True


def test_the_daily_bound_applies_on_the_intent_path(monkeypatch, tmp_path):
    """F5: route_intent — the path a P1 actually takes — owns the per-case bound."""
    from datetime import datetime, timezone
    monkeypatch.setattr(router, "_RECOVERY_T1_PAGE_PATH", tmp_path / "pages.jsonl")
    msg = rn.build_message(_case(case_id="spcx-intent"))
    first = router.route_intent(msg, "P1", dedupe_minutes=0, now=datetime(2026, 11, 3, 15, 0, tzinfo=timezone.utc))
    second = router.route_intent(msg, "P1", dedupe_minutes=0, now=datetime(2026, 11, 3, 15, 0, tzinfo=timezone.utc))
    assert first["decision"] == "DELIVER" and first["deliver"] is True
    assert second["decision"] == "DEDUPED" and second["reason"] == "recovery_t1_daily_case_bound"


# ── third BLOCK round at 12990a369: cc5 P1 — a PREVIEW must not spend the day ──────────────────────────

def test_the_gate_is_a_preview_and_cannot_spend_the_day(monkeypatch, tmp_path):
    """cc5 P1 (2026-11-03): the default gate is a peek; the claim is delivery-owned.

    Before this fix, a caller that only asked "would this send?" claimed the day, and the real
    route then answered DEDUPED — the page was dropped after the peek had spent it.
    """
    msg = rn.build_message(_case(case_id="spcx-preview"))
    assert router.should_send_telegram(msg) is True
    assert router.should_send_telegram(msg) is True          # still a preview: no claim spent
    assert router.recovery_t1_state(msg) == "absent"
    first = router.route_intent(msg, "P1", dedupe_minutes=0)
    assert first["decision"] == "DELIVER" and first["deliver"] is True


def test_peek_never_claims_and_the_real_send_still_bounds_the_day(monkeypatch, tmp_path):
    """cc5 P1 regression, both directions: N peeks then ONE send; then a second send is deduped."""
    import telegram_alert as ta
    monkeypatch.setattr(router, "record_intent_receipt", lambda *a, **k: None)
    monkeypatch.setattr(router, "mark_intent_sent", lambda *a, **k: None)
    msg = rn.build_message(_case(case_id="spcx-peek-n"))
    for _ in range(5):
        assert router.peek_should_send(msg) is True
    assert router.recovery_t1_state(msg) == "absent"          # five questions, no claim
    send = _Sender()
    assert ta._intent_send(msg, "P1", lambda: send(msg), dedupe_minutes=0) is True
    assert len(send.calls) == 1                               # exactly one page
    assert router.recovery_t1_state(msg) == "delivered"
    assert ta._intent_send(msg, "P1", lambda: send(msg), dedupe_minutes=0) is False
    assert len(send.calls) == 1                               # the second REAL send is deduped


def test_preview_then_the_real_delivery_sends_once(monkeypatch, tmp_path):
    """cc5 P1 regression: peek, then the real intent path DELIVERS — one sender call, one page."""
    import telegram_alert as ta
    monkeypatch.setattr(router, "record_intent_receipt", lambda *a, **k: None)
    monkeypatch.setattr(router, "mark_intent_sent", lambda *a, **k: None)
    msg = rn.build_message(_case(case_id="spcx-preview-send"))
    assert router.peek_should_send(msg) is True              # the peek
    send = _Sender()
    delivered = ta._intent_send(msg, "P1", lambda: send(msg), dedupe_minutes=0, producer="recovery_notify")
    assert delivered is True and len(send.calls) == 1
    assert router.recovery_t1_state(msg) == "delivered"


def test_a_legacy_gate_then_an_intent_send_is_one_send(monkeypatch, tmp_path):
    """cc5 P1: send_telegram_proposal_alert's shape — gate first, then priority="P1" send.

    The second claim must not fail against the first: the preview leaves the day unspent, the
    delivery path claims it exactly once, and the operator gets one message (never zero).
    """
    import telegram_alert as ta
    monkeypatch.setattr(router, "record_intent_receipt", lambda *a, **k: None)
    monkeypatch.setattr(router, "mark_intent_sent", lambda *a, **k: None)
    msg = rn.build_message(_case(case_id="spcx-gate-then-send"))
    assert router.should_send_telegram(msg) is True
    send = _Sender()
    assert ta._intent_send(msg, "P1", lambda: send(msg), dedupe_minutes=0) is True
    assert len(send.calls) == 1
    assert router.recovery_t1_state(msg) == "delivered"


def test_an_explicit_consumer_still_owns_the_bound(monkeypatch, tmp_path):
    """The consume=True contract is unchanged for a caller that delivers directly after the gate."""
    msg = rn.build_message(_case(case_id="spcx-consume"))
    assert router.should_send_telegram(msg, consume=True) is True
    assert router.should_send_telegram(msg) is False           # in flight: the preview says not now
    assert router.should_send_telegram(msg, consume=True) is False


def test_an_unusable_primary_threshold_is_not_hidden_by_an_alias(monkeypatch, tmp_path):
    """cx3 R5-F1: the first PRESENT policy path decides; an alias must not rescue a null primary."""
    facts = dict(realized_loss_usd=-50, pre_exit_weight_pct=0.5)   # below the alias thresholds
    primary_null = {"materiality": {"t1": {"loss_usd": None, "weight_pct": 3.0}},
                    "tiers": {"T1": {"loss_usd": 100}}}
    tier, why = rn.resolve_tier(_case(**facts), policy=primary_null)
    assert tier == "T1" and "unusable" in why
    primary_inf = {"materiality": {"t1": {"loss_usd": float("inf"), "weight_pct": 3.0}},
                   "tiers": {"T1": {"loss_usd": 100}}}
    assert rn.resolve_tier(_case(**facts), policy=primary_inf)[0] == "T1"
    assert router.should_send_telegram(rn.build_message(_case(case_id="spcx-alias", **facts))) is True
    # control: with no primary at all the alias IS the policy and may decide T2
    alias_only = {"tiers": {"T1": {"loss_usd": 100, "weight_pct": 3.0}}}
    assert rn.resolve_tier(_case(**facts), policy=alias_only)[0] == "T2"


def test_a_resumed_claim_cannot_repage_after_a_peer_delivered(monkeypatch, tmp_path):
    """cx3 R5-F2: the terminal check must run WHILE HOLDING the lock, not only before it.

    Deterministic interleaving: A reads "absent" before the lock and pauses; B claims, invokes
    the sender, records delivered and releases; A resumes on its stale read. A must not page.
    """
    import multiprocessing as mp

    ctx = mp.get_context("fork")            # the interleaving needs the forked module state
    msg = rn.build_message(_case(case_id="spcx-resume-race"))
    real_state = router._recovery_state
    q: "mp.Queue" = ctx.Queue()
    resume = ctx.Event()

    def peer_a(seed):
        seen = {"n": 0}

        def stale(day, key):
            seen["n"] += 1
            if seen["n"] == 1:
                seed.put("a-read")          # the pre-lock read happened, with a stale view
                resume.wait(15)
                return "absent"             # resume on what it saw before the peer worked
            return real_state(day, key)

        router._recovery_state = stale
        seed.put(("a-claimed", router.recovery_t1_claim(msg)))

    proc = ctx.Process(target=peer_a, args=(q,))
    proc.start()
    try:
        assert q.get(timeout=20) == "a-read"
        assert router.recovery_t1_claim(msg) is True        # B claims
        assert router.recovery_t1_state(msg) == "claimed"
        router.recovery_t1_mark_delivered(msg)              # B delivers and frees the lock
        resume.set()
        assert q.get(timeout=20) == ("a-claimed", False), "a stale resumer re-opened a delivered case"
    finally:
        resume.set()
        proc.join(20)


# ── R6 (cx3, 2026-11-03): stale-reclamation generation race and the unpaired document claim ──────────

def test_a_stale_reclaimer_cannot_steal_a_peer_fresh_lock(monkeypatch, tmp_path):
    """cx3 R6-F1: two processes both see the OLD stale lock; exactly one may deliver.

    A reaches the stale rename and pauses. B, which cached the same stale observation, must not
    rename A's fresh lock and claim too. Both drive the REAL _intent_send path, so the metric is
    actual sender invocations: one at this head, two before the reclamation guard existed.
    """
    import json as _json
    import multiprocessing as mp
    import os as _os
    import time as _time

    import telegram_alert as ta
    ctx = mp.get_context("fork")
    msg = rn.build_message(_case(case_id="spcx-stale-race"))
    lock = router._recovery_claim_lock(router._budget_day(), router._recovery_case_key(msg))
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(_json.dumps({"pid": 424242, "owner": "crashed", "at": 0}))
    old = _time.time() - router._RECOVERY_T1_CLAIM_STALE_SECONDS - 600
    _os.utime(lock, (old, old))
    sends = tmp_path / "sends.txt"
    monkeypatch.setattr(router, "record_intent_receipt", lambda *a, **k: None)
    monkeypatch.setattr(router, "mark_intent_sent", lambda *a, **k: None)

    def _sender(message, **kwargs):                      # a counting spy, shared across processes
        with open(sends, "a", encoding="utf-8") as fh:
            fh.write(f"{_os.getpid()}\n")
        return True

    q = ctx.Queue()
    resume = ctx.Event()

    def peer_a(seed):
        real_rename = _os.rename

        def slow_rename(src, dst):
            if ".stale." in str(dst):
                seed.put("a-at-rename")
                resume.wait(20)
            return real_rename(src, dst)

        _os.rename = slow_rename
        seed.put(("a", bool(ta._intent_send(msg, "P1", lambda: _sender(msg), dedupe_minutes=0))))

    proc = ctx.Process(target=peer_a, args=(q,))
    proc.start()
    try:
        assert q.get(timeout=20) == "a-at-rename"
        b = ta._intent_send(msg, "P1", lambda: _sender(msg), dedupe_minutes=0)
        resume.set()
        a = q.get(timeout=20)
    finally:
        resume.set()
        proc.join(20)
    assert (a[1], bool(b)) == (True, False), "a stale reclaimer and its peer both delivered"
    assert len(sends.read_text(encoding="utf-8").splitlines()) == 1


def _document_env(monkeypatch, tmp_path, *, token="tok", ok=True):
    import telegram_alert as ta
    sent: list = []

    def _send_document(**kwargs):
        sent.append(kwargs)
        return {"ok": ok, "status_code": 200 if ok else 500}

    monkeypatch.setattr(ta, "_enabled", lambda: True)
    monkeypatch.setattr(ta, "_token", lambda: token)
    monkeypatch.setattr(ta, "_chat_ids", lambda: ["1"])
    monkeypatch.setattr(ta, "send_document", _send_document)
    monkeypatch.setattr(ta, "_comms_gateway_owns", lambda mc: False)
    monkeypatch.setattr(ta, "_best_effort_comms_publish", lambda *a, **k: None)
    monkeypatch.setattr(ta, "reset_last_message_ids", lambda: None)
    monkeypatch.setattr(router, "mark_sent", lambda *a, **k: None)
    monkeypatch.setitem(sys.modules, "report_capture", types.SimpleNamespace(capture=lambda *a, **k: None))
    path = tmp_path / "doc.txt"
    path.write_text("x", encoding="utf-8")
    return ta, sent, path


def test_a_document_caption_settles_its_claim_on_success(monkeypatch, tmp_path):
    """cx3 R6-F2: a direct document send confirms delivery, so the day is consumed exactly once."""
    ta, sent, path = _document_env(monkeypatch, tmp_path)
    msg = rn.build_message(_case(case_id="spcx-doc-ok"))
    assert ta.send_telegram_document(str(path), caption=msg, bypass_router=False) is True
    assert len(sent) == 1
    assert router.recovery_t1_state(msg) == "delivered"
    assert ta.send_telegram_document(str(path), caption=msg, bypass_router=False) is False
    assert len(sent) == 1                              # the retry does not reach the transport


def test_an_unconfigured_document_does_not_spend_the_day(monkeypatch, tmp_path):
    """cx3 R6-F2: prerequisites are checked BEFORE the claim, so a corrected retry still sends."""
    ta, sent, path = _document_env(monkeypatch, tmp_path, token=None)
    msg = rn.build_message(_case(case_id="spcx-doc-unconfigured"))
    assert ta.send_telegram_document(str(path), caption=msg, bypass_router=False) is False
    assert sent == [] and router.recovery_t1_state(msg) == "absent"
    monkeypatch.setattr(ta, "_token", lambda: "tok")
    assert ta.send_telegram_document(str(path), caption=msg, bypass_router=False) is True
    assert len(sent) == 1 and router.recovery_t1_state(msg) == "delivered"


def test_a_failed_document_releases_the_claim_for_the_retry(monkeypatch, tmp_path):
    """cx3 R6-F2: a transport failure releases the claim; the corrected retry is not deduped."""
    ta, sent, path = _document_env(monkeypatch, tmp_path, ok=False)
    msg = rn.build_message(_case(case_id="spcx-doc-fail"))
    assert ta.send_telegram_document(str(path), caption=msg, bypass_router=False) is False
    assert len(sent) == 1 and router.recovery_t1_state(msg) == "released"
    monkeypatch.setattr(ta, "send_document", lambda **kw: {"ok": True})
    assert ta.send_telegram_document(str(path), caption=msg, bypass_router=False) is True
    assert router.recovery_t1_state(msg) == "delivered"


def test_a_release_cannot_reopen_another_claimants_case(monkeypatch, tmp_path):
    """cx3 R5-F2: release is bound to ownership; a process without the claim cannot free it."""
    msg = rn.build_message(_case(case_id="spcx-owner"))
    assert router.recovery_t1_claim(msg) is True
    lock = router._recovery_claim_lock(router._budget_day(), router._recovery_case_key(msg))
    router._RECOVERY_CLAIM_OWNERS.clear()            # this caller holds no claim on the case
    router.recovery_t1_release(msg)
    assert lock.exists()                              # the live claimant's lock is untouched
    assert router.recovery_t1_state(msg) == "claimed"


def test_a_failed_delivery_does_not_consume_the_day(monkeypatch, tmp_path):
    """F5: claim -> failed send -> release -> the next attempt is allowed."""
    monkeypatch.setattr(router, "_RECOVERY_T1_PAGE_PATH", tmp_path / "pages.jsonl")
    msg = rn.build_message(_case(case_id="spcx-retry"))
    assert router.recovery_t1_claim(msg) is True
    assert router.recovery_t1_claim(msg) is False          # in flight
    router.recovery_t1_release(msg)                        # transport failed
    assert router.recovery_t1_claim(msg) is True           # retry allowed
    router.recovery_t1_mark_delivered(msg)
    assert router.recovery_t1_claim(msg) is False          # delivered consumes the day


def test_the_claim_is_atomic_across_processes(monkeypatch, tmp_path):
    """F5a: two synchronized processes must not both win the same case-day."""
    import multiprocessing

    monkeypatch.setattr(router, "_RECOVERY_T1_PAGE_PATH", tmp_path / "pages.jsonl")

    def worker(start, q):
        start.wait()
        q.put(router.recovery_t1_claim(rn.build_message(_case(case_id="spcx-race"))))

    ctx = multiprocessing.get_context("fork")
    start = ctx.Event()
    q = ctx.Queue()
    procs = [ctx.Process(target=worker, args=(start, q)) for _ in range(2)]
    for p in procs:
        p.start()
    start.set()
    results = [q.get(timeout=10) for _ in procs]
    for p in procs:
        p.join(timeout=10)
    assert sorted(results) == [False, True], results


def test_exemptions_name_only_the_gates_that_would_bite(monkeypatch, tmp_path):
    """F6: an empty list when nothing would have suppressed; only actual gates otherwise."""
    monkeypatch.setattr(router, "_RECOVERY_T1_PAGE_PATH", tmp_path / "pages.jsonl")
    monkeypatch.setattr(router, "_budget_count_today", lambda: 0)
    plain = rn.build_message(_case(case_id="spcx-plain"))
    assert router.route_alert(plain)["recovery_t1_exemptions"] == []
    monkeypatch.setattr(router, "_budget_count_today", lambda: 10 ** 6)
    busy = rn.build_message(_case(case_id="spcx-busy"))
    assert router.route_alert(busy)["recovery_t1_exemptions"] == ["daily_budget"]


def test_one_unusable_threshold_does_not_delete_its_dimension():
    """F2 remainder: loss threshold inf must not let a small weight decide T2."""
    policy = {"materiality": {"t1": {"loss_usd": float("inf"), "weight_pct": 20}}}
    send = _Sender()
    out = rn.notify_recovery_case(_case(realized_loss_usd=250, pre_exit_weight_pct=1.0),
                                  policy=policy, sender=send, state_path="/tmp/x.json")
    assert out["tier"] == "T1" and send.calls, out


def test_a_huge_integer_materiality_resolves_loud():
    """F7: a JSON-legal 10**1000 integer must not raise before the page."""
    send = _Sender()
    out = rn.notify_recovery_case(_case(realized_loss_usd=10 ** 1000, pre_exit_weight_pct=1.0),
                                  policy=POLICY, sender=send, state_path="/tmp/x.json")
    assert out["tier"] == "T1" and send.calls, out


def test_the_marker_wins_with_an_empty_plan_and_with_tier_words():
    """The marker is an authority signal, not gated by the tier path or by message content."""
    for extra in ({"plan": ""}, {"plan": None}, {"plan": "T3 — small, do not page"}, {"state": "T2"}):
        level = router.classify_alert(rn.build_message(_case(**extra)))
        assert level == "P0_INTERRUPT", (extra, level)


def test_a_transport_that_returns_false_is_recorded_not_treated_as_success(monkeypatch, caplog):
    monkeypatch.setitem(sys.modules, "lib.telegram_batch", None)   # direct path
    calls = []

    def send(message, **kwargs):
        calls.append((message, kwargs))
        return False

    caplog.set_level("WARNING", logger="scripts.lib.recovery_notify")
    out = rn.notify_recovery_case(_case(), policy=POLICY, sender=send, state_path="/tmp/x.json")
    assert calls and out["sent"] is False and out["suppressed"] is False and out["priority"] == "P1"
    assert "not accepted by the direct transport" in caplog.text


def test_a_consumed_dedupe_key_is_recorded_as_a_floor_hold(monkeypatch, caplog):
    _fake_batch(monkeypatch)
    monkeypatch.setattr(sys.modules["lib.telegram_batch"], "NudgeState", _HeldNudgeState)
    monkeypatch.setattr(sys.modules["lib.telegram_batch"], "nudge_decision",
                        lambda **kw: {"send": False, "reason": "nothing due", "keys": []})
    send = _Sender()
    caplog.set_level("WARNING", logger="scripts.lib.recovery_notify")
    out = rn.notify_recovery_case(_case(), policy=POLICY, sender=send, state_path="/tmp/x.json")
    assert out["sent"] is False and out["deduped_by_floor"] is True and send.calls == []
    assert "held by the verified repeat floor" in caplog.text


def test_a_batch_delivery_that_raises_is_loud_not_empty_success(monkeypatch):
    """If both transports raise, the caller must see the exception — never a quiet result."""
    _fake_batch(monkeypatch)

    def boom(message, **kwargs):
        raise RuntimeError("transport down")

    with pytest.raises(RuntimeError, match="transport down"):
        rn.notify_recovery_case(_case(), policy=POLICY, sender=boom, state_path="/tmp/x.json")


def test_a_p1_intent_is_delivered_even_in_quiet_hours():
    """The transport contract the page relies on: P1 is never held or capped."""
    from datetime import datetime, timezone

    quiet = datetime(2026, 11, 3, 8, 0, tzinfo=timezone.utc)  # 03:00 America/New_York
    route = router.route_intent(rn.build_message(_case()), "P1", dedupe_minutes=0,
                                producer="recovery_notify", now=quiet)
    assert route["decision"] == "DELIVER" and route["deliver"] is True


# ── round 4 at 0657f8c0a: F3 encoding, F5 durability edges, F6 ops-exempt, F8 reader, F2 null ─────────

def test_case_ids_that_would_sanitise_alike_get_distinct_locks(monkeypatch):
    """F3: 'a/b' and 'a_b' must not share a claim lock (old sanitisation collapsed them)."""
    msg_a = rn.build_message(_case(case_id="a/b"))
    msg_b = rn.build_message(_case(case_id="a_b"))
    assert rn.parse_case_token(msg_a) == "a/b" and rn.parse_case_token(msg_b) == "a_b"
    assert router.recovery_t1_claim(msg_a) is True
    assert router.recovery_t1_claim(msg_b) is True


def test_a_long_case_id_survives_the_message_round_trip():
    """F3: the old parser truncated outside its class and the lock name cut at 80 chars."""
    long_id = "case-" + "x" * 300 + "/with spaces:and:colons"
    msg = rn.build_message(_case(case_id=long_id))
    assert rn.parse_case_token(msg) == long_id
    assert router.recovery_t1_claim(msg) is True


def test_a_transport_exception_releases_the_claim_and_allows_retry(monkeypatch):
    """F5a: send_fn raising must release the claim, not strand it and block the fallback."""
    import telegram_alert
    monkeypatch.setattr(telegram_alert, "_intent_router", lambda: router)
    msg = rn.build_message(_case(case_id="spcx-transport-raise"))

    def boom():
        raise RuntimeError("transport down")

    with pytest.raises(RuntimeError, match="transport down"):
        telegram_alert._intent_send(msg, "P1", boom, dedupe_minutes=0, producer="recovery_notify")
    assert router.recovery_t1_state(msg) != "claimed"
    assert router.recovery_t1_claim(msg) is True


def test_a_delivered_case_cannot_be_reclaimed_or_released(monkeypatch):
    """F5b: delivered is terminal across a resume; a stale process releasing must not re-open it."""
    msg = rn.build_message(_case(case_id="spcx-delivered"))
    assert router.recovery_t1_claim(msg) is True
    router.recovery_t1_mark_delivered(msg)
    router.recovery_t1_release(msg)          # a stale resumer's release
    assert router.recovery_t1_state(msg) == "delivered"
    assert router.recovery_t1_claim(msg) is False


def test_a_released_attempt_is_visible_to_the_reader(monkeypatch):
    """F8: the reader must see `released`, not keep reading the earlier `claimed`."""
    msg = rn.build_message(_case(case_id="spcx-reader"))
    assert router.recovery_t1_claim(msg) is True
    router.recovery_t1_release(msg)
    assert router.recovery_t1_state(msg) == "released"
    assert router.route_intent(msg, "P1", dedupe_minutes=0)["decision"] == "DELIVER"


def test_ops_exempt_messages_do_not_name_the_budget_gate(monkeypatch):
    """F6: the budget gate never applies to an ops-exempt message, so it is not a bypass."""
    monkeypatch.setattr(router, "_budget_count_today", lambda: 10 ** 6)
    monkeypatch.setattr(router, "_ops_exempt", lambda message: True)
    assert router.route_alert(rn.build_message(_case(case_id="spcx-ops-exempt")))["recovery_t1_exemptions"] == []


def test_a_present_but_null_threshold_is_not_absent():
    """F2: a configured null is a configured dimension without a number -> loud T1."""
    policy = {"materiality": {"t1": {"loss_usd": None, "weight_pct": 20}}}
    send = _Sender()
    out = rn.notify_recovery_case(_case(realized_loss_usd=250, pre_exit_weight_pct=1.0),
                                  policy=policy, sender=send, state_path="/tmp/x.json")
    assert out["tier"] == "T1" and send.calls, out
