"""Operator options intents + proactive matcher (operator 2026-10-05, SPCX).

"This should be in [persistent] memory right now. And in the command center, it should be working on
pulling particular contracts that meet what I'm asking for. This should be proactive."

Pins: the intent is validated and stored on the symbol's ticker directive through the one writer
(dry run writes nothing); ranking respects strike/delta/DTE/liquidity/earnings; covered calls never
go below the operator's floor (and the generic desk generator obeys it); the matcher snapshots,
explains empty plays, and only sends a throttled digest on a material change in send mode.
Fakes only: no Schwab, no database, no Telegram.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from lib.options_intent import matcher as mt  # noqa: E402
from lib.options_intent import ranking as rk  # noqa: E402
from lib.options_intent import store  # noqa: E402


def k(side, strike, dte, bid, ask, delta, oi=500, exp=None, iv=48.0):
    exp = exp or {25: "2026-10-30", 39: "2026-11-13", 46: "2026-11-20", 802: "2028-12-15"}.get(dte, "2026-10-30")
    m = (bid + ask) / 2
    return {"side": side, "strike": strike, "dte": dte, "exp": exp, "bid": bid, "ask": ask, "mark": m, "iv": iv,
            "delta": delta, "oi": oi, "volume": 100, "two_sided": True, "spread_pct": round((ask - bid) / m * 100, 1),
            "symbol": f"SPCX {exp} {side[0].upper()}{strike}"}


PUTS = {"status": "ok", "underlying_price": 167.5, "underlying_quote_time": "2026-10-05T17:00:00+00:00",
        "expirations": [{"exp": "2026-10-30", "strikes": [
            k("put", 157.5, 25, 3.65, 3.75, -0.28), k("put", 155.0, 25, 2.98, 3.06, -0.24, oi=3192),
            k("put", 160.0, 25, 4.6, 4.7, -0.33), k("put", 150.0, 25, 1.9, 2.0, -0.17),
            k("put", 140.0, 25, 0.7, 0.9, -0.07), k("put", 145.0, 25, 1.0, 1.6, -0.12)]},
            {"exp": "2026-11-20", "strikes": [k("put", 150.0, 46, 4.5, 4.7, -0.24)]}]}
CALLS = {"status": "ok", "underlying_price": 167.5,
         "expirations": [{"exp": "2026-10-30", "strikes": [
             k("call", 185.0, 25, 2.8, 2.86, 0.24), k("call", 230.0, 25, 0.21, 0.23, 0.024, oi=1019),
             k("call", 235.0, 25, 0.18, 0.20, 0.035, oi=30)]},
             {"exp": "2026-11-20", "strikes": [k("call", 240.0, 46, 0.70, 0.76, 0.06, oi=900)]},
             {"exp": "2028-12-15", "strikes": [k("call", 100.0, 802, 88.7, 90.0, 0.86, oi=6350),
                                               k("call", 140.0, 802, 60.0, 61.0, 0.72, oi=40)]}]}

INTENT = {"symbol": "SPCX", "thesis_target": 300, "goals": ["accumulate", "income"],
          "plays": {"cash_secured_put": {"dte": [25, 45], "strike_max": 157.85, "delta": [0.15, 0.35]},
                    "covered_call": {"dte": [20, 50], "min_strike": 230, "delta": [0.03, 0.20],
                                     "accounts": {"schwab_rollover_ira": 3, "schwab_taxable": 1}},
                    "leap_call": {"min_dte": 300, "min_delta": 0.7}},
          "avoid_earnings_cross": True, "earnings_estimate": "2026-11-03", "directive_id": 17}
HOLDINGS = [{"symbol": "SPCX", "shares": 300, "account": "schwab_rollover_ira"},
            {"symbol": "SPCX", "shares": 100, "account": "schwab_taxable"}]


# ── validation + store ────────────────────────────────────────────────────────

def test_validate_rejects_bad_intents():
    with pytest.raises(ValueError):
        store.validate_intent({"symbol": "spcx!", "plays": {"cash_secured_put": {}}})
    with pytest.raises(ValueError):
        store.validate_intent({"symbol": "SPCX", "plays": {}})
    with pytest.raises(ValueError):
        store.validate_intent({"symbol": "SPCX", "plays": {"naked_call": {}}})
    with pytest.raises(ValueError):
        store.validate_intent({"symbol": "SPCX", "plays": {"cash_secured_put": {"dte": [45, 25]}}})
    ok = store.validate_intent({"symbol": "spcx", "plays": {"cash_secured_put": {"dte": "25-45"}}})
    assert ok["symbol"] == "SPCX" and ok["plays"]["cash_secured_put"]["dte"] == [25.0, 45.0] and ok["status"] == "active"


class FakeCur:
    """Just enough of a cursor for watch_directives_writer: one existing SPCX ticker directive."""

    def __init__(self, existing=True):
        self.rows = {17: {"id": 17, "label": "watch SPCX", "spec": {"symbol": "SPCX"}, "hits": 3}} if existing else {}
        self.sql = []
        self._last = None
        self.rowcount = 1

    def execute(self, sql, params=None):
        self.sql.append((sql, params))
        s = " ".join(sql.split())
        if s.startswith("SELECT wd.id, wd.label, wd.spec"):
            self._last = [dict(r) for r in self.rows.values()]
        elif s.startswith("SELECT spec FROM watch_directives WHERE id"):
            self._last = [{"spec": json.dumps(self.rows[params[0]]["spec"])}]
        elif s.startswith("SELECT count(*) AS n FROM information_schema.columns"):
            self._last = [{"n": 0}]
        elif s.startswith("UPDATE watch_directives"):
            if "spec" in s and params:
                spec = next((p for p in params if isinstance(p, str) and p.startswith("{")), None)
                if spec:
                    self.rows[17]["spec"] = json.loads(spec)
            self._last = []
        elif s.startswith("INSERT INTO watch_directives"):
            self.rows[99] = {"id": 99, "label": params[1], "spec": json.loads(params[2]), "hits": 0}
            self._last = [{"id": 99}]
        elif s.startswith("SELECT id, label, spec, status FROM watch_directives"):
            self._last = [{"id": i, "label": r["label"], "spec": r["spec"], "status": "active"}
                          for i, r in self.rows.items() if "options_intent" in (r["spec"] or {})]
        else:
            self._last = []

    def fetchone(self):
        return (self._last or [None])[0]

    def fetchall(self):
        return list(self._last or [])


def test_upsert_dry_run_writes_nothing_and_targets_the_existing_directive():
    cur = FakeCur()
    plan = store.upsert_intent(cur, INTENT, apply=False)
    assert plan["action"] == "update" and plan["directive_id"] == 17
    assert not any(s.lstrip().startswith(("UPDATE", "INSERT")) for s, _ in cur.sql)
    assert "options_intent" not in cur.rows[17]["spec"]


def test_upsert_apply_stores_intent_on_the_ticker_directive_and_loads_back():
    cur = FakeCur()
    store.upsert_intent(cur, INTENT, apply=True)
    spec = cur.rows[17]["spec"]
    assert spec["symbol"] == "SPCX" and spec["options_intent"]["thesis_target"] == 300.0
    loaded = store.load_intents(cur)
    assert loaded and loaded[0]["directive_id"] == 17 and loaded[0]["plays"]["covered_call"]["min_strike"] == 230.0


def test_upsert_without_a_directive_inserts_a_ticker_row():
    cur = FakeCur(existing=False)
    plan = store.upsert_intent(cur, INTENT, apply=True)
    assert plan["action"] == "insert" and cur.rows[99]["spec"]["options_intent"]["symbol"] == "SPCX"
    assert plan["row"]["kind"] == "ticker"           # the table's CHECK allows ticker/sector/trend only


def test_paused_intents_are_not_loaded():
    cur = FakeCur()
    store.upsert_intent(cur, INTENT, apply=True)
    store.set_intent_status(cur, "SPCX", "paused", apply=True)
    assert store.load_intents(cur) == []
    assert store.load_intents(cur, include_inactive=True)[0]["status"] == "paused"


# ── ranking ──────────────────────────────────────────────────────────────────

def test_csp_respects_strike_max_delta_liquidity_and_earnings():
    rows = rk.rank_csp(PUTS, INTENT["plays"]["cash_secured_put"], earnings_date="2026-11-03", avoid_earnings_cross=True)
    strikes = [r["strike"] for r in rows]
    assert 160.0 not in strikes                         # above the 157.85 support
    assert 140.0 not in strikes                         # delta 0.07 below the band
    assert 145.0 not in strikes                         # spread 46% — not fillable near mid
    assert all(r["exp"] < "2026-11-03" for r in rows)   # Nov 20 crosses earnings
    top = rows[0]
    assert top["strike"] == 157.5 and top["credit_per_contract"] == pytest.approx(370.0)
    assert top["collateral_per_contract"] == 15750.0 and top["breakeven"] == pytest.approx(153.8)
    assert top["delta_magnitude_pct"] == 28
    assert "assignment_odds_pct" not in top


def test_covered_calls_never_below_the_operator_floor():
    rows = rk.rank_covered_calls(CALLS, INTENT["plays"]["covered_call"], thesis_target=300,
                                 shares_by_account={"schwab_rollover_ira": 300, "schwab_taxable": 100})
    assert rows and all(r["strike"] >= 230 for r in rows)
    assert 185.0 not in [r["strike"] for r in rows]     # what the generic desk proposed on 10-05
    assert rows[0]["strike"] == 240.0 and rows[0]["contracts_available"] == 4   # 235 fails OI, 230 fails delta
    assert rows[0]["below_thesis_target"] is True


def test_cc_floor_from_keep_upside_pct():
    assert rk.cc_strike_floor({"keep_upside_pct": 30}, spot=200.0, thesis_target=None) == pytest.approx(260.0)
    assert rk.cc_strike_floor({}, spot=200.0, thesis_target=300) is None


def test_leaps_most_liquid_first():
    rows = rk.rank_leaps(CALLS, {"min_dte": 300, "min_delta": 0.7})
    assert [r["strike"] for r in rows] == [100.0, 140.0]
    assert rows[0]["time_value"] == pytest.approx(89.35 - 67.5)


# ── matcher ──────────────────────────────────────────────────────────────────

def _chain(sym, side):
    return PUTS if side == "put" else CALLS


def test_match_intent_explains_empty_plays_and_uses_desk_earnings():
    m = mt.match_intent(INTENT, chain_fn=_chain, holdings=HOLDINGS,
                        earnings_fn=lambda s: {"date": "2026-11-03", "source": "options desk earnings gate"})
    assert m["shares_by_account"] == {"schwab_rollover_ira": 300.0, "schwab_taxable": 100.0}
    assert m["plays"]["cash_secured_put"] and m["earnings"]["source"] == "options desk earnings gate"
    assert m["plays"]["covered_call"] == []             # only the Nov 20 240C fits, and it crosses earnings
    assert "expiring before earnings 2026-11-03" in m["empty_reasons"]["covered_call"]
    assert "none fit now" in mt.digest_text(m, ["x"])


def test_material_changes():
    m1 = mt.match_intent(INTENT, chain_fn=_chain, holdings=HOLDINGS)
    assert "cash secured put: first match" in mt.material_changes(None, m1)
    assert mt.material_changes(m1, m1) == []
    m2 = json.loads(json.dumps(m1))
    m2["plays"]["cash_secured_put"][0]["annualized_pct"] *= 1.2
    assert any("better by" in r for r in mt.material_changes(m1, m2))


def _run(tmp_path, monkeypatch, *, mode, apply, sent, now=1_000_000.0):
    monkeypatch.setenv("OPTIONS_INTENT_DIR", str(tmp_path))
    import options_intent_matcher as cli
    cfg = {**mt.DEFAULT_CONFIG, "mode": mode}
    return cli.run([INTENT], cfg=cfg, apply=apply, chain_fn=_chain, earnings_fn=lambda s: {},
                   holdings_list=HOLDINGS, send_fn=lambda t: sent.append(t) or True, now=now, out=lambda t: None)


def test_dry_run_writes_and_sends_nothing(tmp_path, monkeypatch):
    sent = []
    res = _run(tmp_path, monkeypatch, mode="send", apply=False, sent=sent)
    assert res["matched"] == 1 and sent == [] and not (tmp_path / "latest.json").exists()


def test_shadow_apply_snapshots_without_sending(tmp_path, monkeypatch):
    sent = []
    _run(tmp_path, monkeypatch, mode="shadow", apply=True, sent=sent)
    latest = json.loads((tmp_path / "latest.json").read_text())
    assert sent == [] and latest["SPCX"]["plays"]["cash_secured_put"]
    assert (tmp_path / "matches.jsonl").read_text().count("\n") == 1


def test_send_mode_digests_once_then_throttles_and_needs_a_change(tmp_path, monkeypatch):
    sent = []
    _run(tmp_path, monkeypatch, mode="send", apply=True, sent=sent, now=1_000_000.0)
    assert len(sent) == 1 and "OPTIONS INTENT · SPCX" in sent[0] and "NOT AN ORDER" in sent[0]
    _run(tmp_path, monkeypatch, mode="send", apply=True, sent=sent, now=1_000_000.0 + 3 * 3600)
    assert len(sent) == 1                               # nothing changed → no second digest


def test_generic_covered_call_generator_obeys_the_intent(monkeypatch):
    import options_engine as oe
    monkeypatch.setattr(oe, "_INTENT_CC_FLOORS", {"SPCX": {"covered_call": INTENT["plays"]["covered_call"],
                                                          "thesis_target": 300, "directive_id": 17}})
    assert "at or above $230" in oe._intent_blocks_covered_call("SPCX", 185.0, 167.5)
    assert oe._intent_blocks_covered_call("SPCX", 240.0, 167.5) is None
    assert oe._intent_blocks_covered_call("AAPL", 185.0, 167.5) is None


def test_no_order_or_broker_surface_in_new_code():
    for rel in ("scripts/lib/options_intent/ranking.py", "scripts/lib/options_intent/matcher.py",
                "scripts/lib/options_intent/store.py", "scripts/options_intent_matcher.py", "scripts/options_intent.py"):
        src = (ROOT / rel).read_text()
        for bad in ("place_order", "submit_order", "build_client", "unlock_trade", "/orders"):
            assert bad not in src, f"{rel} contains {bad}"



def test_intent_links_share_contract_identity_but_never_inherit_another_strategy_decision():
    from scripts.lib.options_identity import contract_guid
    registry = {"entities": []}  # Inject missing identity; exact contract attributes still join.
    match = {"symbol": "TEST", "directive_id": 17, "as_of": "2026-10-05T17:00:00Z",
             "plays": {"cash_secured_put": [{"strike": 100, "exp": "2026-11-20", "assignment_odds_pct": 28}]}}
    proposals = [{"id": "hedge", "symbol": "TEST", "strategy": "protective_put", "option_type": "put",
                  "strike": 100, "expiration": "2026-11-20", "account": "a",
                  "cio_decision": {"decision_guid": "rejected-hedge"}}]
    result = mt.link_desk_matches(match, proposals, registry=registry)
    row = result['plays']['cash_secured_put'][0]
    assert row['desk_status'] == 'NOT_STAGED'
    assert row['desk_links'][0]['relationship'] == 'same_contract_other_strategy'
    assert row['desk_links'][0]['decision_guid'] is None
    assert 'assignment_odds_pct' not in row
    assert match['plays']['cash_secured_put'][0]['assignment_odds_pct'] == 28  # no cache mutation
    proposals.append({**proposals[0], 'id': 'income', 'strategy': 'cash_secured_put'})
    linked = mt.link_desk_matches(match, proposals, registry=registry)
    assert linked['desk_link_summary'] == {'linked_matches': 1, 'unstaged_matches': 0, 'match_count': 1}
    assert len(linked['plays']['cash_secured_put'][0]['desk_links']) == 2
    assert contract_guid('TEST', 'put', 100, '2026-11-20', registry=registry) is None


def test_standing_plan_preview_cannot_overwrite_a_newer_operator_edit():
    cur = FakeCur()
    store.upsert_intent(cur, INTENT, apply=True)
    before = cur.rows[17]["spec"]["options_intent"]["updated_at"]
    store.upsert_intent(cur, {**INTENT, "thesis_target": 310}, apply=True, expected_updated_at=before)
    with pytest.raises(ValueError, match="changed since preview"):
        store.upsert_intent(cur, {**INTENT, "thesis_target": 320}, apply=True, expected_updated_at=before)
    assert cur.rows[17]["spec"]["options_intent"]["thesis_target"] == 310
    assert any("FOR UPDATE" in sql for sql, _ in cur.sql)


@pytest.mark.parametrize("changes", [
    {"thesis_target": float("nan")}, {"thesis_target": -1},
    {"plays": {"cash_secured_put": {"strike_max": float("inf")}}},
    {"plays": {"covered_call": {"dte": [0, 20]}}},
    {"plays": {"leap_call": {"min_delta": 2}}},
])
def test_standing_plan_invalid_numeric_preferences_are_refused(changes):
    with pytest.raises(ValueError):
        store.validate_intent({**INTENT, **changes})


def test_intent_summary_review_is_bound_to_plan_and_scan_without_model_calls():
    match = {"as_of": "2026-10-05T17:00:00Z", "spot": 170, "plays": {}}
    a = mt.review_packet(INTENT, match)
    assert a == mt.review_packet(INTENT, match)
    assert a["target_type"] == "options_intent" and len(a["content"]) < 8000
    assert a["target_id"] != mt.review_packet({**INTENT, "thesis_target": 310}, match)["target_id"]
    assert a["target_id"] != mt.review_packet(INTENT, {**match, "spot": 180})["target_id"]
    assert "not assignment probability" in a["content"]
    assert mt.review_packet(INTENT, None)["as_of"] is None
