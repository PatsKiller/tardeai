"""n8n maturity B4 follow-ups (2026-10-09).

1. continuous_runner: a GO is marked "already alerted" only once its alert line built and the send was accepted;
   a trigger whose build raises is isolated (the others still send) and stays un-alerted for the next cycle.
2. canonical_store_registry.production_state_root: a TRADEAI_ROOT pointing at a release checkout never becomes the
   state root (the persistent-state marker wins).
3. continuous_runner (B4 review): a rejected send retries at most max_attempts_per_trigger_per_day times per trigger
   per day with backoff (config/trade_ai_scalp_lane.yaml alert_delivery); Telegram disabled is final; a send that
   reached at least one chat is delivered.
Notify-only: no broker/order/stop code is involved; send_telegram is stubbed.
"""
from __future__ import annotations

import json
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import continuous_runner as cr  # noqa: E402
from scripts.lib import canonical_store_registry as csr  # noqa: E402

MARKET = {"indices": {"SPY": {"change_percent": 0.4}}, "vix": {"price": 15.0}, "breadth_label": "ok"}


def _row(sym, score=60, decision="GO", rvol=2.0):
    return {"symbol": sym, "score": score, "decision": decision, "relative_volume": rvol, "top_catalyst": {}}


def _stub_send(monkeypatch, accepted=True, sent=None, enabled=True, delivered_ids=(), ids_on_package=False):
    """Stub the Telegram chokepoint (never the live one: no token store, env file or network is touched).

    ``delivered_ids`` are the provider ids the send records (a partial send: some chats got it); with
    ``ids_on_package`` they land on the ``scripts.telegram_alert`` instance, as on the comms-gateway path."""
    tg = types.ModuleType("telegram_alert")
    pkg = types.ModuleType("scripts.telegram_alert")
    for m in (tg, pkg):
        m._ids = []
        m.reset_last_message_ids = (lambda mod: (lambda: mod._ids.clear()))(m)
        m.last_message_ids = (lambda mod: (lambda: list(mod._ids)))(m)
        m._enabled = lambda: enabled

    def send_telegram(msg, *a, **k):
        if sent is not None:
            sent.append(msg)
        if not enabled:
            return False
        (pkg if ids_on_package else tg)._ids.extend(delivered_ids)
        if isinstance(accepted, Exception):
            raise accepted
        return accepted

    tg.send_telegram = send_telegram
    monkeypatch.setitem(sys.modules, "telegram_alert", tg)
    monkeypatch.setitem(sys.modules, "scripts.telegram_alert", pkg)
    al = types.ModuleType("alerting")
    al.send_whatsapp = al.send_slack = lambda msg: None
    monkeypatch.setitem(sys.modules, "alerting", al)


def _quiet_build(monkeypatch, bad=()):
    """Replace the per-trigger line builder (which calls critics/LLMs) with a cheap one that raises for ``bad``."""
    def fake(lines, t):
        lines.append("partial line that must be dropped")
        if t.get("symbol") in bad:
            raise RuntimeError("critic exploded")
        lines[-1] = f"{t['type']} {t['symbol']}"
    monkeypatch.setattr(cr, "_append_trigger_lines", fake)


def _cycle(state, scored, monkeypatch, saves, **deliver):
    """The run_live_cycle alert path: detect -> update -> unmark+save -> deliver."""
    cs: dict = {"errors": []}
    triggers = state.detect_triggers(scored, {})
    state.update(scored)
    cr._set_trigger_marks(state, triggers, alerted=False)
    saver = lambda s: saves.append(s.to_dict())  # noqa: E731
    cr._save_state_quietly(saver, state, cs, "pre_alert")
    n = cr._deliver_live_alert(state, triggers, "10:00", MARKET, cs, saver, **deliver) if triggers else 0
    return triggers, cs, n


def test_pre_alert_save_leaves_new_go_unalerted(monkeypatch):
    _stub_send(monkeypatch)
    _quiet_build(monkeypatch)
    st, saves = cr.CycleState(), []
    _cycle(st, [_row("AAA")], monkeypatch, saves)
    # first persisted snapshot (a kill during the build would leave exactly this) must not hold AAA as alerted
    assert "AAA" not in saves[0]["prev_go"]
    # the pre-send save (and in-memory state) holds it once the line built
    assert "AAA" in saves[1]["prev_go"] and "AAA" in st.prev_go


def test_accepted_send_marks_and_dedupes_next_cycle(monkeypatch):
    sent: list = []
    _stub_send(monkeypatch, sent=sent)
    _quiet_build(monkeypatch)
    st, saves = cr.CycleState(), []
    _, cs, n = _cycle(st, [_row("AAA")], monkeypatch, saves)
    assert n == 1 and cs["alert_sent"] is True and cs["alerts_delivered"] == 1
    trig2, _, _ = _cycle(cr.CycleState.from_dict(saves[-1]), [_row("AAA")], monkeypatch, [])
    assert [t for t in trig2 if t["type"] == "NEW_GO"] == []
    assert len(sent) == 1


def test_build_failure_isolates_one_go_and_retries_it_next_cycle(monkeypatch):
    sent: list = []
    _stub_send(monkeypatch, sent=sent)
    _quiet_build(monkeypatch, bad={"BAD"})
    st, saves = cr.CycleState(), []
    _, cs, n = _cycle(st, [_row("BAD"), _row("OK")], monkeypatch, saves)
    assert n == 1 and cs["alerts_delivered"] == 1
    assert "OK" in st.prev_go and "BAD" not in st.prev_go
    assert "BAD" not in saves[-1]["prev_go"]
    assert "NEW_GO OK" in sent[0] and "BAD" not in sent[0] and "partial line" not in sent[0]
    assert any("BAD" in e for e in cs["errors"])
    # next cycle: the builder is healthy again -> BAD alerts, OK stays deduped
    _quiet_build(monkeypatch)
    trig2, _, n2 = _cycle(cr.CycleState.from_dict(saves[-1]), [_row("BAD"), _row("OK")], monkeypatch, [])
    assert [t["symbol"] for t in trig2 if t["type"] == "NEW_GO"] == ["BAD"] and n2 == 1


def test_whole_build_crash_marks_nothing(monkeypatch):
    _stub_send(monkeypatch)
    monkeypatch.setattr(cr, "_build_live_alert", lambda *a, **k: (_ for _ in ()).throw(ValueError("boom")))
    st, saves = cr.CycleState(), []
    _, cs, n = _cycle(st, [_row("AAA")], monkeypatch, saves)
    assert n == 0 and "AAA" not in st.prev_go and len(saves) == 1
    assert any("alert_build" in e for e in cs["errors"])


def test_rejected_or_raising_send_rolls_back_every_mark(monkeypatch):
    for outcome in (False, RuntimeError("telegram down")):
        _stub_send(monkeypatch, accepted=outcome)
        _quiet_build(monkeypatch)
        st = cr.CycleState()
        st.prev_score = {"JMP": 40}
        st.prev_go = {"JMP"}
        saves: list = []
        scored = [_row("AAA", rvol=9.0), _row("JMP", score=60)]
        trig, cs, n = _cycle(st, scored, monkeypatch, saves)
        assert {t["type"] for t in trig} >= {"NEW_GO", "RVOL_8X", "SCORE_JUMP"}
        assert n == 0 and cs["alert_sent"] is False and cs["alerts_delivered"] == 0
        assert "AAA" not in st.prev_go and "AAA" not in st.rvol8x_seen
        assert st.prev_score["JMP"] == 40
        assert saves[-1]["prev_go"] == ["JMP"] and "AAA" not in saves[-1]["rvol8x_seen"]


POLICY = {"max_attempts_per_trigger_per_day": 3, "retry_backoff_base_s": 600.0, "retry_backoff_multiplier": 2.0}
T0 = datetime(2026, 10, 9, 10, 0, tzinfo=timezone.utc)


def _roundtrip(st):
    """Persist + reload the state the way the scalp lane does between 5-minute runs (JSON file)."""
    return cr.CycleState.from_dict(json.loads(json.dumps(st.to_dict())))


def test_failed_send_is_capped_per_trigger_per_day_with_backoff(monkeypatch):
    """B4 review: a rejected send must not re-send the same GO every 5 minutes all day."""
    sent: list = []
    _stub_send(monkeypatch, accepted=False, sent=sent)
    _quiet_build(monkeypatch)
    st, minute, outcomes = cr.CycleState(), 0, []
    while minute <= 6 * 60:  # a full session of 5-minute cycles
        _, cs, n = _cycle(st, [_row("AAA")], monkeypatch, [], policy=POLICY, now=T0 + timedelta(minutes=minute))
        outcomes.append((minute, cs.get("alert_outcome")))
        st = _roundtrip(st)
        minute += 5
    sends = [m for m, o in outcomes if o in ("failed_retry", "failed_final")]
    # attempt 1 at 0, backoff 600 s -> attempt 2 at 10, backoff 1200 s -> attempt 3 (final) at 30; then never again
    assert sends == [0, 10, 30] and len(sent) == 3
    assert [o for m, o in outcomes if m in (0, 10, 30)] == ["failed_retry", "failed_retry", "failed_final"]
    assert outcomes[1] == (5, "deferred")
    assert "AAA" in st.prev_go and st.alert_attempts["NEW_GO:AAA"]["n"] == 3


def test_deferred_trigger_stays_unalerted_and_retries_after_backoff(monkeypatch):
    sent: list = []
    _stub_send(monkeypatch, accepted=False, sent=sent)
    _quiet_build(monkeypatch)
    st = cr.CycleState()
    _, cs, _ = _cycle(st, [_row("AAA")], monkeypatch, [], policy=POLICY, now=T0)
    assert cs["alert_outcome"] == "failed_retry" and "AAA" not in st.prev_go
    st = _roundtrip(st)
    _stub_send(monkeypatch, accepted=True, sent=sent)
    trig, cs, n = _cycle(st, [_row("AAA")], monkeypatch, [], policy=POLICY, now=T0 + timedelta(minutes=5))
    assert [t["symbol"] for t in trig] == ["AAA"] and n == 0 and cs["alerts_deferred"] == 1
    assert "AAA" not in st.prev_go and len(sent) == 1
    _, cs, n = _cycle(st, [_row("AAA")], monkeypatch, [], policy=POLICY, now=T0 + timedelta(minutes=10))
    assert n == 1 and cs["alert_outcome"] == "delivered" and "AAA" in st.prev_go
    assert "NEW_GO:AAA" not in st.alert_attempts and len(sent) == 2


def test_telegram_disabled_is_final_not_retried(monkeypatch):
    sent: list = []
    _stub_send(monkeypatch, sent=sent, enabled=False)
    _quiet_build(monkeypatch)
    st, saves = cr.CycleState(), []
    _, cs, n = _cycle(st, [_row("AAA")], monkeypatch, saves, policy=POLICY, now=T0)
    assert n == 0 and cs["alert_sent"] is False and cs["alert_outcome"] == "disabled"
    assert "AAA" in st.prev_go and "AAA" in saves[-1]["prev_go"] and st.alert_attempts == {}
    trig, _, _ = _cycle(_roundtrip(st), [_row("AAA")], monkeypatch, [], policy=POLICY,
                        now=T0 + timedelta(hours=1))
    assert trig == [] and len(sent) == 1


def test_partial_delivery_counts_as_delivered(monkeypatch):
    """One chat of two failed: the transport says False but the operator has the alert -> no duplicate."""
    for on_package in (False, True):
        sent: list = []
        _stub_send(monkeypatch, accepted=False, sent=sent, delivered_ids=("4711",), ids_on_package=on_package)
        _quiet_build(monkeypatch)
        st = cr.CycleState()
        _, cs, n = _cycle(st, [_row("AAA")], monkeypatch, [], policy=POLICY, now=T0)
        assert n == 1 and cs["alert_sent"] is True and cs["alert_outcome"] == "partial"
        assert "AAA" in st.prev_go and st.alert_attempts == {}
        trig, _, _ = _cycle(_roundtrip(st), [_row("AAA")], monkeypatch, [], policy=POLICY,
                            now=T0 + timedelta(minutes=5))
        assert trig == [] and len(sent) == 1


def test_stale_message_ids_from_an_earlier_send_do_not_count(monkeypatch):
    _stub_send(monkeypatch, accepted=False)
    sys.modules["scripts.telegram_alert"]._ids.append("old-id")  # left over from an earlier send in the process
    _quiet_build(monkeypatch)
    st = cr.CycleState()
    _, cs, n = _cycle(st, [_row("AAA")], monkeypatch, [], policy=POLICY, now=T0)
    assert n == 0 and cs["alert_outcome"] == "failed_retry" and "AAA" not in st.prev_go


def test_retry_policy_comes_from_config_and_fails_safe(tmp_path, capsys):
    pol = cr.load_alert_retry_policy(ROOT / "config" / "trade_ai_scalp_lane.yaml")
    import yaml
    raw = yaml.safe_load((ROOT / "config" / "trade_ai_scalp_lane.yaml").read_text(encoding="utf-8"))["alert_delivery"]
    assert pol["max_attempts_per_trigger_per_day"] == raw["max_attempts_per_trigger_per_day"] >= 1
    bad = tmp_path / "lane.yaml"
    bad.write_text("schema: TradeAIScalpLane@v1\n", encoding="utf-8")
    assert cr.load_alert_retry_policy(bad)["max_attempts_per_trigger_per_day"] == 1
    assert "alert_delivery policy unreadable" in capsys.readouterr().out


def test_failsafe_policy_gives_up_after_one_failed_send(monkeypatch):
    sent: list = []
    _stub_send(monkeypatch, accepted=False, sent=sent)
    _quiet_build(monkeypatch)
    st = cr.CycleState()
    _, cs, _ = _cycle(st, [_row("AAA")], monkeypatch, [], policy=dict(cr._ALERT_POLICY_FAILSAFE), now=T0)
    assert cs["alert_outcome"] == "failed_final" and "AAA" in st.prev_go
    assert any("giving up" in e for e in cs["errors"])


def test_halt_and_resume_marks_roll_back():
    st = cr.CycleState()
    st.halted_seen = {"R"}
    trig = [{"type": "HALT", "symbol": "H"}, {"type": "RESUMED", "symbol": "R"}]
    cr._set_trigger_marks(st, trig, alerted=True)
    assert st.halted_seen == {"H"}
    cr._set_trigger_marks(st, trig, alerted=False)
    assert st.halted_seen == {"R"}


def test_build_live_alert_survives_a_malformed_market_and_keeps_good_triggers(monkeypatch):
    _quiet_build(monkeypatch, bad={"X"})
    failed: list = []
    msg = cr._build_live_alert([{"type": "NEW_GO", "symbol": "X"}, {"type": "HALT", "symbol": "Y"}], "10:00",
                               {"indices": {"SPY": {"change_percent": None}}}, failed=failed)
    assert "HALT Y" in msg and "X" not in msg.split("\n", 2)[2]
    assert [t["symbol"] for t in failed] == ["X"]


def test_real_line_builder_still_renders_halt_and_score_jump():
    lines: list = []
    cr._append_trigger_lines(lines, {"type": "HALT", "symbol": "H", "reason": "LUDP"})
    cr._append_trigger_lines(lines, {"type": "SCORE_JUMP", "symbol": "J", "delta": 9, "prev": 40, "score": 49,
                                     "decision": "GO"})
    assert "*HALT*" in lines[0] and "LUDP" in lines[0] and "40→49" in lines[1]


# ── production_state_root ─────────────────────────────────────────────────────────────────────────────────────


def _home(monkeypatch, tmp_path, marker=True):
    monkeypatch.setattr(csr.Path, "home", classmethod(lambda cls: tmp_path))
    for k in ("TRADEAI_STATE_ROOT", "TRADEAI_ROOT", "TRADEAI_PERSISTENT_STATE_ROOT"):
        monkeypatch.delenv(k, raising=False)
    persistent = tmp_path / "trade-ai-releases" / "persistent-state"
    persistent.mkdir(parents=True)
    if marker:
        (persistent / "PERSISTENT_STATE_ROOT.json").write_text("{}")
    rel = tmp_path / "trade-ai-releases" / "portfolio-server" / "abc123"
    rel.mkdir(parents=True)
    (tmp_path / "trade-ai-releases" / "portfolio-server" / "CURRENT").symlink_to(rel)
    return persistent, rel


def test_release_dir_tradeai_root_is_ignored_and_marker_wins(monkeypatch, tmp_path):
    persistent, rel = _home(monkeypatch, tmp_path)
    for code_root in (rel, rel / "scripts", rel.parent / "CURRENT"):
        monkeypatch.setenv("TRADEAI_ROOT", str(code_root))
        assert csr.is_release_dir(code_root)
        assert csr.production_state_root() == persistent


def test_non_release_tradeai_root_and_explicit_state_root_still_honoured(monkeypatch, tmp_path):
    persistent, rel = _home(monkeypatch, tmp_path)
    lab = tmp_path / "lab"
    monkeypatch.setenv("TRADEAI_ROOT", str(lab))
    assert not csr.is_release_dir(lab)
    assert csr.production_state_root() == lab
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    assert csr.production_state_root() == tmp_path / "state"
    assert csr.production_state_root(tmp_path / "explicit") == tmp_path / "explicit"
    # the release tree itself is not "a release"
    assert not csr.is_release_dir(rel.parent)


def test_release_dir_tradeai_root_without_marker_falls_back_to_persistent_env(monkeypatch, tmp_path):
    _persistent, rel = _home(monkeypatch, tmp_path, marker=False)
    monkeypatch.setenv("TRADEAI_ROOT", str(rel))
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(tmp_path / "ps"))
    assert csr.production_state_root() == tmp_path / "ps"
