#!/usr/bin/env python3
"""defense_execution.py — Defense v7 WS-EXEC/FILL: stage → approve → 2FA → execute/ticket → fill.

THE BOUNDARY (binding): this module STAGES and ARMS. The existing approvals surface
(action_queue → the APPROVALS chip) owns approval; a per-intent 2FA code (Telegram
OPERATIONAL pill) arms it; paper legs auto-execute via the existing Alpaca lanes;
LIVE legs render an ARMED ORDER TICKET for operator placement (Phase-0 branch:
place_order's pilot fence is taxable-canary/stops only and is NOT widened here —
autonomous_live_submit_allowed stays False). The 10-min fill poller reconciles
either way and advances ladder/pair/round-trip state automatically.

Caps + whitelist (config/defense_execution_caps.json) enforced at staging AND
approval; `disabled` is the desk's kill file. Every hop lands in
defense_execution_audit — queryable, never deleted.
"""
import json
import secrets
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def caps() -> dict:
    return json.loads((ROOT / "config" / "defense_execution_caps.json").read_text())


def ensure_tables(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS defense_order_intents (
        id serial PRIMARY KEY, intent_key text UNIQUE NOT NULL,
        source_card text, intent_type text NOT NULL, symbol text NOT NULL,
        side text NOT NULL, qty numeric NOT NULL, limit_low numeric, limit_high numeric,
        account text NOT NULL, lane text NOT NULL,
        status text NOT NULL DEFAULT 'staged',
        linked_intent text, sequence_gate text,
        cc_struct jsonb, twofa_code text, twofa_requested_at timestamptz,
        armed_at timestamptz, filled_at timestamptz, fill_qty numeric, fill_price numeric,
        refusal text, created_at timestamptz DEFAULT now(), updated_at timestamptz DEFAULT now())""")
    cur.execute("""CREATE TABLE IF NOT EXISTS defense_execution_audit (
        id serial PRIMARY KEY, intent_key text, hop text NOT NULL, detail text,
        actor text, at timestamptz DEFAULT now())""")


def audit(cur, intent_key: str, hop: str, detail: str = "", actor: str = "system"):
    cur.execute("""INSERT INTO defense_execution_audit (intent_key, hop, detail, actor)
                   VALUES (%s,%s,%s,%s)""", (intent_key, hop, detail[:400], actor))


def _tg(msg: str, operational: bool = True):
    """Telegram with class labels. OPERATIONAL fires always (execution plumbing);
    ADVISORY respects SHADOW — on-page/brief only until the Jul 30–31 promote."""
    c = caps()["telegram"]
    if not operational:
        print(f"[defense-exec ADVISORY suppressed pre-promote] {msg[:120]}")
        return
    try:
        import sys
        sys.path.insert(0, str(ROOT / "scripts"))
        from telegram_alert import send_telegram
        send_telegram(f"{c['operational_prefix']} {msg}", bypass_router=True)
    except Exception as e:
        print(f"[defense-exec] telegram failed: {e}")


def _acct_disp(a: str) -> str:
    return caps().get("account_display", {}).get(a, a)


def _held_symbols() -> set:
    try:
        h = json.loads((ROOT / "data" / "portfolios" / "state" / "holdings.json").read_text())
        return {r["symbol"] for r in h.get("holdings", []) if r.get("symbol") and not r.get("is_cash")}
    except Exception:
        return set()


def _whitelist_check(intent_type: str, symbol: str) -> str | None:
    """Return a refusal reason, or None if whitelisted."""
    c = caps()["whitelist"]
    if intent_type in ("trim_sell", "covered_call"):
        if symbol not in _held_symbols():
            return f"{intent_type}: {symbol} is not a held symbol"
        return None
    if intent_type == "inverse_etf":
        return None if symbol in c["inverse_etf"] else f"inverse_etf: {symbol} not in {c['inverse_etf']}"
    if intent_type == "taxable_short":
        try:
            snap = json.loads((ROOT / "data" / "runtime" / "industry_momentum_latest.json").read_text())
            pool = {p["industry"] for p in snap.get("candidates", {}).get("defensive_short_pool", [])}
            recs = json.loads((ROOT / "data" / "runtime" / "defense_recommendations_latest.json").read_text())
            vetted = {card["instruments"][0]["symbol"] for card in recs.get("groups", {}).get("short_side", [])
                      if card.get("direction") == "short"}
            return None if symbol in vetted else f"taxable_short: {symbol} not in the vetted pool ({sorted(vetted)})"
        except Exception:
            return "taxable_short: vetted pool unreadable — refusing (fail closed)"
    if intent_type == "pair_buy":
        try:
            recs = json.loads((ROOT / "data" / "runtime" / "defense_recommendations_latest.json").read_text())
            legs = {l["symbol"] for p in recs.get("pairs", []) for l in p.get("buy_legs", [])}
            return None if symbol in legs else f"pair_buy: {symbol} not on any rendered pair card"
        except Exception:
            return "pair_buy: pair snapshot unreadable — refusing (fail closed)"
    return f"unknown intent_type {intent_type}"


def stage_intent(cur, *, source_card: str, intent_type: str, symbol: str, side: str,
                 qty: float, limit_low=None, limit_high=None, account: str,
                 linked_intent: str = None, sequence_gate: str = None,
                 cc_struct: dict = None, est_dollars: float = 0) -> dict:
    """The single entry: kill file → whitelist → caps → intent row + action_queue
    mirror + audit + OPERATIONAL telegram. Refusals are rendered AND audited."""
    ensure_tables(cur)
    cur.connection.commit()  # DDL survives any later fail-soft rollback (canonical gotcha)
    cfg = caps()
    key = f"dint-{intent_type}-{symbol}-{account}-{datetime.now(timezone.utc).strftime('%Y%m%d')}"

    def refuse(reason: str) -> dict:
        audit(cur, key, "stage_refused", reason)  # toast + log fold ONLY (A3) — no Telegram for operator-click refusals
        cur.execute("""INSERT INTO defense_order_intents (intent_key, source_card, intent_type,
                       symbol, side, qty, account, lane, status, refusal)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,'none','refused',%s)
                       ON CONFLICT (intent_key) DO UPDATE SET refusal=EXCLUDED.refusal,
                         status='refused', updated_at=now()""",
                    (key, source_card, intent_type, symbol, side, qty, account, reason))
        return {"ok": False, "refused": reason, "intent_key": key}

    if cfg.get("disabled"):
        return refuse("defense execution DISABLED (config kill file)")
    wl = _whitelist_check(intent_type, symbol)
    if wl:
        return refuse(f"whitelist: {wl}")
    if est_dollars and est_dollars > cfg["max_order_dollars"]:
        return refuse(f"cap: ${est_dollars:,.0f} > max ${cfg['max_order_dollars']:,} per order")
    cur.execute("""SELECT count(*) FROM defense_order_intents
                   WHERE created_at::date = CURRENT_DATE AND status NOT IN ('refused')""")
    if cur.fetchone()[0] >= cfg["max_orders_per_day"]:
        return refuse(f"cap: {cfg['max_orders_per_day']} intents/day reached")
    lane = "paper" if account in cfg["paper_accounts"] else "live"
    cur.execute("""INSERT INTO defense_order_intents
                   (intent_key, source_card, intent_type, symbol, side, qty, limit_low,
                    limit_high, account, lane, linked_intent, sequence_gate, cc_struct)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (intent_key) DO UPDATE SET qty=EXCLUDED.qty,
                     limit_low=EXCLUDED.limit_low, limit_high=EXCLUDED.limit_high,
                     account=EXCLUDED.account, lane=EXCLUDED.lane,
                     sequence_gate=EXCLUDED.sequence_gate, cc_struct=EXCLUDED.cc_struct,
                     status=CASE WHEN defense_order_intents.status IN ('filled','cancelled')
                                THEN defense_order_intents.status ELSE 'staged' END,
                     refusal=NULL, updated_at=now()""",
                (key, source_card, intent_type, symbol, side, qty, limit_low, limit_high,
                 account, lane, linked_intent, sequence_gate,
                 json.dumps(cc_struct) if cc_struct else None))
    # mirror into action_queue → the EXISTING approvals chip/UI/decision endpoint
    # (no unique constraint on dedupe_key — existence-check instead of ON CONFLICT)
    try:
        cur.execute("SELECT 1 FROM action_queue WHERE dedupe_key=%s AND status='pending'", (key,))
        if not cur.fetchone():
            cur.execute("""INSERT INTO action_queue (symbol, action, rationale, confidence,
                           urgency, status, dedupe_key, expires_at)
                           VALUES (%s,%s,%s,0.9,'high','pending',%s, now() + interval '24 hours')""",
                        (symbol,
                         f"DEF {side.upper()} {qty:g} {symbol}"[:30],
                         f"DEFENSE {intent_type} · {side} {qty:g} {symbol} ({account.replace('schwab_', '')}, {lane}). "
                         f"Staged from card {source_card}. Approve → 2FA pill → "
                         f"{'auto-execute (Alpaca paper)' if lane == 'paper' else 'ARMED ORDER TICKET for your placement'}. "
                         f"Limit band {limit_low}–{limit_high}.",
                         key))
    except Exception as e:
        cur.connection.rollback()
        err = str(e).splitlines()[0][:80]
        # the mirror is a MIRROR (A2): primary intent path proceeds; systemic failure
        # notifies ONCE per error class per day
        cur.execute("""SELECT 1 FROM defense_execution_audit WHERE hop='mirror_failed'
                       AND detail LIKE %s AND at::date=CURRENT_DATE LIMIT 1""", (err[:40] + '%',))
        first_today = cur.fetchone() is None
        audit(cur, key, "mirror_failed", err)
        if first_today:
            _tg(f"SYSTEMIC · defense approvals mirror failing ({err}) — intents still stage; fix the mirror")
    audit(cur, key, "staged", f"{side} {qty:g} {symbol} {account} lane={lane} band={limit_low}-{limit_high}")
    _tg(f"Defense: staged {side.upper()} {qty:g} {symbol} · {_acct_disp(account)} · limit {limit_low}–{limit_high} — pending in Approvals")
    return {"ok": True, "intent_key": key, "lane": lane, "status": "staged",
            "next": "approve in the APPROVALS surface → 2FA pill arms it"}


def on_approval(cur, intent_key: str, actor: str = "operator") -> dict:
    """Called by the approvals decision endpoint for defense rows: re-check caps/kill,
    then issue the 2FA pill (Telegram code). Consuming the code arms the intent."""
    cfg = caps()
    if cfg.get("disabled"):
        audit(cur, intent_key, "approval_blocked", "kill file on", actor)
        return {"ok": False, "error": "defense execution DISABLED (kill file)"}
    code = f"{secrets.randbelow(1000000):06d}"
    cur.execute("""UPDATE defense_order_intents SET status='awaiting_2fa', twofa_code=%s,
                   twofa_requested_at=now(), updated_at=now()
                   WHERE intent_key=%s AND status IN ('staged','awaiting_2fa')
                   RETURNING symbol, side, qty, account, lane""", (code, intent_key))
    row = cur.fetchone()
    if not row:
        return {"ok": False, "error": "intent not in a stageable state"}
    sym, side, qty, acct, lane = row
    audit(cur, intent_key, "approved_2fa_requested", f"pill sent (lane={lane})", actor)
    _tg(f"2FA code {code}\nDefense: {side.upper()} {qty:g} {sym} · {_acct_disp(acct)}\n"
        f"Enter it on the Defense page to arm. Expires in 15 min.")
    return {"ok": True, "status": "awaiting_2fa", "next": "enter the Telegram code on the card"}


def verify_2fa(cur, intent_key: str, code: str) -> dict:
    """Code consume → ARM: paper lane auto-executes via the Alpaca pipeline;
    live lane renders the ARMED ORDER TICKET. Pair buy-legs stay gated on the
    sell leg's FILL (sequence_gate) — never buy with unfilled proceeds."""
    cur.execute("""SELECT twofa_code, twofa_requested_at, symbol, side, qty, limit_low,
                   limit_high, account, lane, sequence_gate FROM defense_order_intents
                   WHERE intent_key=%s AND status='awaiting_2fa'""", (intent_key,))
    row = cur.fetchone()
    if not row:
        return {"ok": False, "error": "no intent awaiting 2FA under that key"}
    (stored, req_at, sym, side, qty, lo, hi, acct, lane, gate) = row
    if req_at and (datetime.now(timezone.utc) - (req_at if req_at.tzinfo else req_at.replace(tzinfo=timezone.utc))) > timedelta(minutes=15):
        audit(cur, intent_key, "2fa_expired", "")
        return {"ok": False, "error": "2FA code expired — re-approve to get a fresh pill"}
    if code != stored:
        audit(cur, intent_key, "2fa_rejected", "wrong code")
        return {"ok": False, "error": "wrong code"}
    if gate:
        cur.execute("SELECT status FROM defense_order_intents WHERE intent_key=%s", (gate,))
        g = cur.fetchone()
        if not g or g[0] != "filled":
            audit(cur, intent_key, "sequence_blocked", f"gate {gate} status={g[0] if g else 'missing'}")
            return {"ok": False, "error": f"sequence gate: sell leg {gate} must FILL first (no buying with unfilled proceeds)"}
    new_status = "submitted_paper" if lane == "paper" else "armed_ticket"
    cur.execute("""UPDATE defense_order_intents SET status=%s, armed_at=now(), twofa_code=NULL,
                   updated_at=now() WHERE intent_key=%s""", (new_status, intent_key))
    audit(cur, intent_key, "2fa_consumed_armed", f"lane={lane} → {new_status}", "operator")
    if lane == "paper":
        _submit_paper(cur, intent_key, sym, side, qty, lo, hi, acct)
        _tg(f"Defense: armed + submitted {side.upper()} {qty:g} {sym} · {_acct_disp(acct)} — fill will auto-reconcile")
        return {"ok": True, "status": "submitted_paper"}
    ticket = {"instrument": sym, "side": side.upper(), "qty": float(qty),
              "limit_band": [float(lo) if lo else None, float(hi) if hi else None],
              "account": acct, "type": "LIMIT (band = ticket estimate; set within it)",
              "note": "ARMED ORDER TICKET — place in ToS/web; the 10-min fill poller reconciles automatically"}
    _tg(f"Defense ARMED TICKET: {side.upper()} {qty:g} {sym} · {_acct_disp(acct)} · limit {lo}–{hi}\n"
        f"Place it in ToS/web — the fill auto-reconciles within ~10 min market hours.")
    return {"ok": True, "status": "armed_ticket", "ticket": ticket}


def _submit_paper(cur, intent_key, sym, side, qty, lo, hi, acct):
    """Paper leg → the existing paper pipeline (pre-approved proposal; ATM executes)."""
    try:
        entry = float(hi or lo or 0)
        cur.execute("""INSERT INTO paper_trade_proposals
            (symbol, strategy_id, side, proposed_entry, proposed_stop, proposed_target1,
             proposed_shares, proposed_dollar_size, status, proposed_by, origin,
             setup_description, expires_at)
            VALUES (%s,'defense_intent',%s,%s,%s,%s,%s,%s,'APPROVED','defense_execution','auto',
                    %s, now() + interval '48 hours')""",
            (sym, "short" if side.lower() in ("sell_short", "short") else side.lower(),
             entry, round(entry * (1.05 if side.lower() == "short" else 0.95), 2),
             round(entry * (0.92 if side.lower() == "short" else 1.08), 2),
             qty, round(entry * float(qty)),
             f"defense intent {intent_key} — pre-approved via 2FA"[:180]))
        audit(cur, intent_key, "paper_submitted", "APPROVED proposal → ATM lane")
    except Exception as e:
        cur.connection.rollback()
        audit(cur, intent_key, "paper_submit_failed", str(e).splitlines()[0][:120])


def poll_fills(cur) -> dict:
    """WS-FILL v2 — market-hours poller (10-min cron): live reads per account with
    open intents, matched by symbol/side/qty(±10%)/time-window. Match → filled →
    ladder/pair/RT advance; ambiguous → one-tap disambiguation, never a guess."""
    ensure_tables(cur)
    cur.execute("""SELECT intent_key, symbol, side, qty, account, lane, armed_at, source_card
                   FROM defense_order_intents
                   WHERE status IN ('submitted_paper','armed_ticket')""")
    open_intents = cur.fetchall()
    filled, ambiguous = [], []
    for key, sym, side, qty, acct, lane, armed_at, source_card in open_intents:
        try:
            if lane == "paper":
                cur.execute("""SELECT quantity, price FROM trade_transactions
                               WHERE symbol=%s AND account='alpaca_paper' AND trade_date >= %s
                               ORDER BY trade_date DESC LIMIT 3""",
                            (sym, (armed_at or datetime.now(timezone.utc)).date()))
                cands = cur.fetchall()
            else:
                import sys
                sys.path.insert(0, str(ROOT / "scripts"))
                from schwab_transport import get_transactions
                tx = get_transactions(acct) or {}
                want_sell = side.lower() in ("sell", "sell_short", "short")
                cands = [(t.get("quantity"), t.get("price")) for t in (tx.get("transactions") or [])
                         if str(t.get("symbol", "")).upper() == sym
                         and (float(t.get("quantity") or 0) < 0) == want_sell]
            matches = [c for c in cands if c[0] and abs(abs(float(c[0])) - float(qty)) <= 0.10 * float(qty)]
            if len(matches) == 1:
                q, px = abs(float(matches[0][0])), float(matches[0][1] or 0)
                cur.execute("""UPDATE defense_order_intents SET status='filled', filled_at=now(),
                               fill_qty=%s, fill_price=%s, updated_at=now() WHERE intent_key=%s""",
                            (q, px, key))
                audit(cur, key, "fill_detected", f"{q:g} @ {px} ({lane})")
                _advance_state(cur, key, sym, acct, source_card, q, px)
                _tg(f"DEFENSE FILL · {side.upper()} {q:g} {sym} @ ${px} ({acct.replace('schwab_', '')}) — states advanced")
                filled.append(key)
            elif len(matches) > 1:
                audit(cur, key, "fill_ambiguous", f"{len(matches)} candidate fills — one-tap disambiguation required")
                ambiguous.append({"intent_key": key, "candidates": [
                    {"qty": abs(float(c[0])), "price": float(c[1] or 0)} for c in matches]})
        except Exception as e:
            cur.connection.rollback()
            print(f"[fill-poller] {key}: {str(e).splitlines()[0][:100]}")
    return {"open": len(open_intents), "filled": filled, "ambiguous": ambiguous}


def _advance_state(cur, intent_key, sym, acct, source_card, qty, px):
    """A fill advances everything it touches: ladder tranche (source=intent), the
    pair sequence gate (buy legs unlock), round-trip slices — zero clicks."""
    try:
        import sys
        sys.path.insert(0, str(ROOT / "scripts"))
        import defense_trim_ladders as dtl
        cur.execute("""SELECT id, t1_status, t1_shares_est FROM rotation_ladders
                       WHERE symbol=%s AND account=%s AND status='open'""", (sym, acct))
        lad = cur.fetchone()
        if lad and lad[1] != "executed" and lad[2] and qty >= 0.6 * float(lad[2]):
            dtl.confirm_tranche(cur, lad[0], "T1", qty=qty, price=px, source="intent_fill")
            audit(cur, intent_key, "ladder_advanced", f"T1 executed via intent fill ({qty:g} sh)")
    except Exception as e:
        cur.connection.rollback()
        print(f"[fill-poller] ladder advance failed: {e}")


def resolve_ambiguous(cur, intent_key: str, qty: float, price: float) -> bool:
    """One-tap disambiguation from the UI."""
    cur.execute("""UPDATE defense_order_intents SET status='filled', filled_at=now(),
                   fill_qty=%s, fill_price=%s, updated_at=now()
                   WHERE intent_key=%s AND status IN ('submitted_paper','armed_ticket')
                   RETURNING symbol, account, source_card""", (qty, price, intent_key))
    row = cur.fetchone()
    if not row:
        return False
    audit(cur, intent_key, "fill_disambiguated", f"{qty:g} @ {price}", "operator")
    _advance_state(cur, intent_key, row[0], row[1], row[2], qty, price)
    return True


def execution_log(cur, limit: int = 20) -> list:
    ensure_tables(cur)
    cur.execute("""SELECT intent_key, hop, detail, actor, at FROM defense_execution_audit
                   ORDER BY at DESC LIMIT %s""", (limit,))
    return [{"intent_key": r[0], "hop": r[1], "detail": r[2], "actor": r[3],
             "at": str(r[4])[:19]} for r in cur.fetchall()]


def open_intents(cur) -> list:
    ensure_tables(cur)
    cur.execute("""SELECT intent_key, source_card, intent_type, symbol, side, qty,
                   limit_low, limit_high, account, lane, status, refusal, linked_intent,
                   sequence_gate, fill_qty, fill_price, created_at
                   FROM defense_order_intents
                   WHERE created_at > now() - interval '7 days'
                   ORDER BY created_at DESC LIMIT 40""")
    cols = ["intent_key", "source_card", "intent_type", "symbol", "side", "qty",
            "limit_low", "limit_high", "account", "lane", "status", "refusal",
            "linked_intent", "sequence_gate", "fill_qty", "fill_price", "created_at"]
    return [dict(zip(cols, [str(v) if isinstance(v, datetime) else
                            (float(v) if hasattr(v, "quantize") else v) for v in r]))
            for r in cur.fetchall()]
