"""AXTI 10:20 ET incident replay (live-proof 2026-09-28, LP-DEF-01/02/04) on a FIXED clock.

Incident packet: data/runtime/buy_ready_packets/AXTI.json, saved 2026-09-28T14:20:23Z by cio_entry_state_runner
on CURRENT = a328a8817 (chain 14:20:04Z, earnings 2026-10-29 = 31 d, debit call vertical 75/95 at 109 DTE).
Its earnings block for the vertical reads {"in_blackout": false, "symbol": "AXTI", "strategy": "debit_spread"}:
the alternatives module MAPPED debit_call_vertical -> "debit_spread" before calling the gate, and that mapped
value was outside the four-id BLOCKING set of a328a8817. PR #1336 (14:47Z) added it; this campaign's gate
also aliases producer ids, fails closed on unknown ids and stamps gate_version / evaluated_at.

Proves: (a) the OLD release (verbatim fixture of a328a8817's gate) qualified the mapped value and blocked
long_call with the exact strings in the packet; (b) the candidate gate refuses the same input with
EARNINGS_BLACKOUT through the REAL alternatives builder; (c) unknown event data and unknown strategy ids fail
closed; (d) the stored 10:20 packet is served as STALE_PRE_FIX with every unit un-qualified and the original
kept; (e) preflight recomputes a cached pre-fix verdict instead of trusting it."""
from __future__ import annotations

import ast
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "scripts", ROOT / "scripts" / "lib", ROOT / "tests", ROOT / "tests" / "fixtures"):
    sys.path.insert(0, str(p))

import options_desk_enterprise as ode  # noqa: E402
import buy_ready_options_alternatives as boa  # noqa: E402
import earnings_gate_a328a8817 as old_gate  # noqa: E402
from test_buy_ready_options_20260924 import _bs, _liq_ok  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "axti_buy_ready_packet_20260928T1420Z.json"
INCIDENT_DATE = date(2026, 9, 28)
INCIDENT_NOW = datetime(2026, 9, 28, 14, 20, 4, tzinfo=timezone.utc)   # the packet's chain_as_of
EARNINGS = "2026-10-29"
AXTI_PLAN = {"symbol": "AXTI", "price": 73.32, "entry_low": 62.0, "entry_high": 66.0, "stop": 58.5, "target": 96.5}


def _packet():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def axti_chain(spot=73.32, iv=0.70, dtes=(39, 109, 480)):
    exps = []
    for dte in dtes:
        rows = []
        for k in range(40, 125, 5):
            for right in ("call", "put"):
                px, delta = _bs(spot, float(k), iv, dte, right)
                px = max(px, 0.05)
                half = max(0.05, px * 0.01)
                rows.append({"exp": f"D{dte}", "strike": float(k), "side": right, "bid": round(px - half, 2),
                             "ask": round(px + half, 2), "last": round(px, 2), "iv": iv * 100,
                             "delta": round(delta, 3), "oi": 900, "volume": 120, "dte": dte})
        exps.append({"exp": f"D{dte}", "dte": dte, "strikes": rows})
    return {"symbol": "AXTI", "underlying": spot, "expirations": exps}


def _cal(monkeypatch, value=EARNINGS, module=ode):
    monkeypatch.setattr(module, "earnings_calendar", lambda syms: {s.upper(): value for s in syms})


def _gate_on_incident_clock(sym, *, dte, strategy):
    return ode.earnings_blackout_check(sym, dte=dte, strategy=strategy, as_of=INCIDENT_DATE)


# ── (a) the old release, verbatim, on the incident clock ─────────────────────────────────────

def test_old_release_qualified_the_mapped_value_debit_spread(monkeypatch):
    _cal(monkeypatch, module=old_gate)
    pkt = _packet()
    units = {u["strategy"]: u for u in pkt["options_alternatives"]["alternatives"]}
    old = old_gate.earnings_blackout_check("AXTI", dte=109, strategy="debit_spread", today=INCIDENT_DATE)
    assert old == units["debit_call_vertical"]["earnings"] == {"in_blackout": False, "symbol": "AXTI", "strategy": "debit_spread"}
    # the raw id would ALSO have passed the old gate (same allow-by-omission branch) — but it was not what was passed
    assert old_gate.earnings_blackout_check("AXTI", dte=109, strategy="debit_call_vertical", today=INCIDENT_DATE)["in_blackout"] is False
    blocked = old_gate.earnings_blackout_check("AXTI", dte=109, strategy="long_call", today=INCIDENT_DATE)
    assert blocked["in_blackout"] is True and blocked["reason"] == units["long_call"]["earnings"]["reason"]
    assert blocked["days_to_earnings"] == 31 == units["long_call"]["earnings"]["days_to_earnings"]
    assert units["debit_call_vertical"]["qualified"] is True and pkt["options_alternatives"]["status"] == "OK"


# ── (b) the candidate refuses the same input ─────────────────────────────────────────────────

def test_candidate_refuses_the_mapped_and_the_raw_id_with_earnings_blackout(monkeypatch):
    _cal(monkeypatch)
    for strategy in ("debit_spread", "debit_call_vertical"):
        r = _gate_on_incident_clock("AXTI", dte=109, strategy=strategy)
        assert r["in_blackout"] is True and r["trigger"] == "expires_after_earnings", r
        assert r["strategy"] == "debit_spread" and r["strategy_raw"] == strategy
        assert r["gate_version"] == ode.EARNINGS_GATE_VERSION and r["as_of"] == "2026-09-28" and r["replay"] is True
        assert r["evaluated_at"] and not r["evaluated_at"].startswith("2026-09-28T00:00:00")   # wall clock, never faked
        assert ode.earnings_verdict_status(r, max_age_s=10**9)[1].startswith("REPLAY_VERDICT")  # never reusable live
        assert r["event_date"] == EARNINGS and r["days_to_earnings"] == 31 and r["dte"] == 109


def test_candidate_alternatives_builder_disqualifies_every_unit_through_the_real_gate(monkeypatch):
    _cal(monkeypatch)
    out = boa.build_alternatives(AXTI_PLAN, axti_chain(), held=False, liquidity_fn=_liq_ok, blackout_fn=_gate_on_incident_clock,
                                 chain_source="fixture", chain_as_of=INCIDENT_NOW.isoformat())
    names = {a["strategy"] for a in out["alternatives"]}
    assert "debit_call_vertical" in names, (names, out["skipped"])
    assert out["status"] == "NONE_QUALIFIED" and out["gate_version"] == ode.EARNINGS_GATE_VERSION and out["generated_at"]
    for a in out["alternatives"]:
        assert a["qualified"] is False and any(d.startswith("EARNINGS_BLACKOUT") for d in a["disqualified_by"]), a["strategy"]
        assert a["event_date"] == EARNINGS and a["expiration"] and a["dte"] and a["gate_version"] == ode.EARNINGS_GATE_VERSION
        assert a["disqualification_reason"] and "EARNINGS_BLACKOUT" in a["disqualification_reason"]
    vert = next(a for a in out["alternatives"] if a["strategy"] == "debit_call_vertical")
    assert vert["strategy_gate"] == "debit_spread" and vert["earnings"]["strategy_raw"] == "debit_call_vertical"


# ── (c) unknown event data / unknown strategy ids fail closed ───────────────────────────────

def test_unknown_event_data_and_unknown_strategy_fail_closed(monkeypatch):
    _cal(monkeypatch, value=ode.EARNINGS_UNKNOWN)
    r = _gate_on_incident_clock("AXTI", dte=109, strategy="debit_spread")
    assert r["in_blackout"] is True and r["refusal_code"] == "EARNINGS_TIMESTAMP_UNKNOWN" and r["gate_version"]
    _cal(monkeypatch, value="2026-13-45")
    r = _gate_on_incident_clock("AXTI", dte=109, strategy="debit_spread")
    assert r["in_blackout"] is True and r["refusal_code"] == "EARNINGS_TIMESTAMP_INVALID"
    _cal(monkeypatch)
    r = _gate_on_incident_clock("AXTI", dte=109, strategy="iron_condor_experimental")
    assert r["in_blackout"] is True and r["trigger"] == "unknown_strategy" and r["strategy_raw"] == "iron_condor_experimental"
    # the hedge exemption stays explicit
    assert _gate_on_incident_clock("AXTI", dte=109, strategy="protective_put")["in_blackout"] is False


# ── (d) the stored 10:20 packet is served as STALE_PRE_FIX, the original kept ───────────────

def test_incident_packet_is_served_stale_pre_fix_with_every_unit_unqualified():
    pkt = _packet()
    stale = boa.staleness(pkt["options_alternatives"], now=INCIDENT_NOW + timedelta(hours=2))
    assert stale and stale["code"] == boa.STALE_PRE_FIX and stale["gate_version_cached"] is None
    view = boa.packet_view(pkt, now=INCIDENT_NOW + timedelta(hours=2))
    assert view["status"] == boa.STALE_PRE_FIX and view["as_of"] == "2026-09-28T14:20:04+00:00" and view["saved_at"] == pkt["saved_at"]
    alts = view["packet"]["options_alternatives"]
    assert alts["status"] == boa.STALE_PRE_FIX and alts["superseded"] is True
    assert alts["original"] == {"status": "OK", "qualified": ["debit_call_vertical"]}
    for a in alts["alternatives"]:
        assert a["qualified"] is False and a["disqualified_by"][0].startswith("STALE_PRE_FIX (")
    # the source packet was not mutated (evidence is immutable; the view is a copy)
    assert pkt["options_alternatives"]["alternatives"][0]["qualified"] is True


def test_fresh_block_is_current_then_ages_out_or_is_superseded_by_a_gate_bump(monkeypatch):
    _cal(monkeypatch)
    out = boa.build_alternatives(AXTI_PLAN, axti_chain(), held=False, liquidity_fn=_liq_ok, blackout_fn=_gate_on_incident_clock,
                                 chain_as_of=INCIDENT_NOW.isoformat())
    gen = datetime.fromisoformat(out["generated_at"])
    assert boa.staleness(out, now=gen + timedelta(minutes=5), max_age_s=21600) is None
    assert boa.staleness(out, now=gen + timedelta(hours=7), max_age_s=21600)["code"] == "STALE_CHAIN"
    assert boa.staleness(out, now=gen + timedelta(minutes=5), max_age_s=21600, current_gate_version="9999.9")["code"] == boa.STALE_PRE_FIX
    assert boa.staleness(dict(out, generated_at=None, chain_as_of=None), now=gen, max_age_s=21600)["code"] == "STALE_UNKNOWN_AGE"


def test_api_packet_route_uses_the_view_not_the_file():
    src = (ROOT / "scripts" / "api_v2.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "_buy_ready_packet")
    body = ast.get_source_segment(src, fn)
    assert "packet_view(packet)" in body and "PACKET_UNVERIFIED" in body and '"status": "OK", "saved_at"' not in body


# ── (e) preflight recomputes a cached pre-fix verdict ───────────────────────────────────────

def test_verdict_status_fails_closed_on_missing_old_or_stale_stamps():
    now = INCIDENT_NOW
    assert ode.earnings_verdict_status(None, now=now, max_age_s=100)[1] == "NO_VERDICT"
    assert ode.earnings_verdict_status({"in_blackout": False, "strategy": "debit_spread"}, now=now, max_age_s=100)[1].startswith("STALE_PRE_FIX")
    assert ode.earnings_verdict_status({"gate_version": "2026-09-28.1", "evaluated_at": now.isoformat()}, now=now, max_age_s=100)[1].startswith("STALE_PRE_FIX")
    assert ode.earnings_verdict_status({"gate_version": ode.EARNINGS_GATE_VERSION}, now=now, max_age_s=100)[1].startswith("STALE_UNKNOWN_AGE")
    good = {"gate_version": ode.EARNINGS_GATE_VERSION, "evaluated_at": (now - timedelta(seconds=50)).isoformat()}
    assert ode.earnings_verdict_status(good, now=now, max_age_s=100) == (True, "CURRENT")
    assert ode.earnings_verdict_status(good, now=now + timedelta(seconds=100), max_age_s=100)[1].startswith("STALE_VERDICT")


def test_preflight_recomputes_the_cached_pre_fix_verdict(monkeypatch):
    _cal(monkeypatch)
    monkeypatch.setattr(ode, "date", type("D", (date,), {"today": classmethod(lambda cls: INCIDENT_DATE)}))
    pkt = _packet()
    cached = next(u for u in pkt["options_alternatives"]["alternatives"] if u["strategy"] == "debit_call_vertical")["earnings"]
    proposal = {"symbol": "AXTI", "strategy": "debit_spread", "dte": 109, "contracts": 1,
                "enterprise": {"earnings": cached, "liquidity": {"pass": True, "issues": []}}}
    blocks = ode.evaluate_hard_risk_blocks(proposal, mode="preflight", cfg=ode.load_desk_config())
    earn = [b for b in blocks if "earnings" in str(b.get("code", ""))]
    assert earn, blocks
    assert earn[0].get("cached_verdict_superseded", "").startswith("STALE_PRE_FIX") or "STALE_PRE_FIX" in json.dumps(earn[0])


# ── reviewer 2026-09-28 findings 1, 3, 4, 7 ──────────────────────────────────────────────────

def test_no_gate_or_broken_gate_disqualifies_at_build_time():
    """Finding 1: `blackout_fn=None` used to yield in_blackout None -> qualified True before any view ran."""
    out = boa.build_alternatives(AXTI_PLAN, axti_chain(), held=False, liquidity_fn=_liq_ok, blackout_fn=None,
                                 chain_as_of=INCIDENT_NOW.isoformat())
    assert out["alternatives"] and not any(a["qualified"] for a in out["alternatives"])
    assert all(a["earnings"]["trigger"] == "gate_unavailable" for a in out["alternatives"])

    def broken(sym, *, dte, strategy):
        raise RuntimeError("calendar down")
    out = boa.build_alternatives(AXTI_PLAN, axti_chain(), held=False, liquidity_fn=_liq_ok, blackout_fn=broken)
    assert not any(a["qualified"] for a in out["alternatives"]) and all(a["earnings"]["trigger"] == "gate_error" for a in out["alternatives"])

    def no_verdict(sym, *, dte, strategy):
        return {"in_blackout": None}
    out = boa.build_alternatives(AXTI_PLAN, axti_chain(), held=False, liquidity_fn=_liq_ok, blackout_fn=no_verdict)
    assert not any(a["qualified"] for a in out["alternatives"])


def test_gate_vocabulary_fingerprint_is_pinned_to_the_version():
    """Finding 4: editing BLOCKING / NON_BLOCKING / ALIASES without bumping EARNINGS_GATE_VERSION fails here."""
    assert ode.earnings_gate_vocab_fingerprint() == ode.EARNINGS_GATE_VOCAB_SHA, (
        "the earnings-gate vocabulary changed: bump EARNINGS_GATE_VERSION and set EARNINGS_GATE_VOCAB_SHA to "
        + ode.earnings_gate_vocab_fingerprint())
    assert ode.EARNINGS_GATE_VERSION == "2026-09-28.2"


def test_old_gate_fixture_matches_a328a8817_when_history_is_available():
    """Finding 3: the fixture's verbatim claim is machine-checked against git history when the object exists
    (skipped on a shallow clone)."""
    import subprocess
    import pytest
    r = subprocess.run(["git", "-C", str(ROOT), "show", "a328a8817:scripts/options_desk_enterprise.py"], capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip("a328a8817 not in this clone's history")
    old_src = r.stdout
    assert 'BLOCKING_STRATEGIES = frozenset({"covered_call", "cash_secured_put", "credit_spread", "long_call"})' in old_src
    assert 'EARNINGS_UNKNOWN = "UNKNOWN"' in old_src and old_gate.EARNINGS_UNKNOWN == "UNKNOWN"
    old_fn = next(n for n in ast.walk(ast.parse(old_src)) if isinstance(n, ast.FunctionDef) and n.name == "earnings_blackout_check")
    fix_src = (ROOT / "tests" / "fixtures" / "earnings_gate_a328a8817.py").read_text(encoding="utf-8")
    fix_fn = next(n for n in ast.walk(ast.parse(fix_src)) if isinstance(n, ast.FunctionDef) and n.name == "earnings_blackout_check")

    def decision_lines(fn):
        # the body statements after the docstring, with the injected `today` line normalised back
        out = []
        for st in fn.body[1:]:
            txt = ast.unparse(st)
            out.append(txt.replace("today = today or date.today()", "today = date.today()"))
        return out
    assert decision_lines(fix_fn) == decision_lines(old_fn)


def test_preflight_keeps_a_stale_block_verdict_blocking(monkeypatch):
    """Finding 7: a stale verdict that says BLOCK still blocks (re-stamped), even if the live gate would now clear."""
    _cal(monkeypatch, value="")   # live gate: no scheduled event -> would clear
    stale_block = {"in_blackout": True, "symbol": "AXTI", "strategy": "long_call", "next_earnings": "2026-10-29",
                   "days_to_earnings": 31, "blackout_days": 14, "reason": "Earnings 2026-10-29 in 31d — inside 14d blackout"}
    proposal = {"symbol": "AXTI", "strategy": "long_call", "dte": 109, "contracts": 1,
                "enterprise": {"earnings": stale_block, "liquidity": {"pass": True, "issues": []}}}
    blocks = ode.evaluate_hard_risk_blocks(proposal, mode="preflight", cfg=ode.load_desk_config())
    earn = [b for b in blocks if b.get("code") == "earnings_blackout"]
    assert earn and "STALE_PRE_FIX" in json.dumps(earn[0])


def test_preflight_recomputes_when_the_cached_verdict_is_for_another_strategy_or_dte(monkeypatch):
    """Finding 5: a CURRENT verdict for a different strategy/dte is not reused."""
    _cal(monkeypatch)
    monkeypatch.setattr(ode, "date", type("D", (date,), {"today": classmethod(lambda cls: INCIDENT_DATE)}))
    current_other = ode.earnings_blackout_check("AXTI", dte=7, strategy="protective_put")   # clear, CURRENT, but for a hedge at 7 DTE
    assert current_other["in_blackout"] is False
    proposal = {"symbol": "AXTI", "strategy": "debit_spread", "dte": 109, "contracts": 1,
                "enterprise": {"earnings": current_other, "liquidity": {"pass": True, "issues": []}}}
    blocks = ode.evaluate_hard_risk_blocks(proposal, mode="preflight", cfg=ode.load_desk_config())
    earn = [b for b in blocks if b.get("code") == "earnings_blackout"]
    assert earn and "PROPOSAL_MISMATCH" in json.dumps(earn[0])
