#!/usr/bin/env python3
"""defense_oversight.py — Defense v8 WS-BRIEF/FREE: curate the math, seat the critics.

Tier 1 (automatic): every recommendations BUILD (hash-keyed) sends the curated brief
to BOTH free seats (ChatGPT + Grok OAuth lanes) — quota-aware, cached until the next
build; page refreshes read cache, never re-call. Verdicts are schema-strict JSON;
malformed → `unparseable` with the raw kept — never coerced. The oversight layer
INFORMS: it never blocks, never edits a card, never stages anything.
"""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

DAILY_PER_SEAT = 3  # oversight's share of each free lane's global daily quota

CONTRACT = """Respond ONLY with JSON matching:
{"cards": [{"id": "<card id>", "verdict": "CONCUR|QUALIFY|OBJECT",
            "reason": "<=40 words", "missed_risk": "<=25 words or null"}],
 "memo": {"top_concerns": ["...", "...", "..."],
          "incoherences": ["..."], "blind_spots": ["..."],
          "strongest_objection": "REQUIRED: the best case AGAINST this desk's current advice; if you have zero objections, justify why."}}"""


def _constitution() -> list:
    """The law the reviewer judges within — generated from config, never prose drift."""
    caps = json.loads((ROOT / "config" / "defense_execution_caps.json").read_text())
    rc = json.loads((ROOT / "config" / "defense_recommendations.json").read_text())
    return [
        "Advisory-only desk: cards inform; execution requires operator approval + per-order 2FA; autonomous submit is OFF.",
        f"Execution caps: ${caps['max_order_dollars']:,}/order, {caps['max_orders_per_day']}/day; whitelist: held-only trims/CCs, inverse {caps['whitelist']['inverse_etf']}, vetted short pool, rendered pair legs.",
        f"Core registry (operator-owned): core positions NEVER full-exit — trim cap {rc['core']['max_trim_pct']}%, patient {rc['core']['reentry_window_days']}-session re-entry, cleanup-exempt.",
        f"Trim composite: factor base {rc['trim_composite']['base_by_factor_count']} +GG state +concentration(cap {rc['trim_composite']['concentration_cap_pp']}pp) +stop context; bounds {rc['trim_composite']['bounds_pct']}.",
        f"Taxable shorts: SF<{rc['taxable_short']['max_short_float_pct']}%, ≥${rc['taxable_short']['min_price']}, stop≤{rc['taxable_short']['max_stop_distance_pct']}%, ≤{rc['taxable_short']['size_cap_pct_of_book']}% book, never held symbols.",
        "Wash-sale: 31d deterministic warning (any-account; IRA repurchase permanent), basis-blind until Cost Basis export, never suppresses rollback alerts.",
        "All groups SHADOW until the Jul 30-31 promote review; Telegram advisory-class suppressed until then.",
        "Accounts: Rollover IRA / Roth IRA (no shorts; inverse ETF + CC ok) · Taxable (margin verified, shorts advisory-only) · Alpaca Paper (shadow twins).",
    ]


def build_oversight_brief() -> dict:
    recs = json.loads((ROOT / "data" / "runtime" / "defense_recommendations_latest.json").read_text())
    sect = json.loads((ROOT / "data" / "runtime" / "sector_momentum_latest.json").read_text())
    cards = []
    for g, lst in recs.get("groups", {}).items():
        for c in lst:
            cards.append({
                "id": c["id"], "group": g, "title": c["title"], "direction": c["direction"],
                "rationale": c.get("trim_rationale") or c.get("size_band"),
                "ticket": [o.get("line") for o in (c.get("ticket") or {}).get("options", [])] or None,
                "factors": [f"{f['name']}={f['value']}" for f in c.get("factors", [])],
                "levels": c.get("levels"), "mode": c.get("mode"), "is_core": c.get("is_core", False),
            })
    for p in recs.get("pairs", []):
        cards.append({"id": p["id"], "group": "pair", "title": p["title"],
                      "sell": p["sell_ticket"]["line"], "buys": [l["line"] for l in p["buy_legs"]],
                      "style": p["style_rationale"], "factors": [f"{f['name']}={f['value']}" for f in p.get("factors", [])]})
    brief = {
        "constitution": _constitution(),
        "posture": {"state_line": (sect.get("market") or {}).get("state_line"),
                    "sectors": [{"s": r["sector"], "state": r["state"], "rs20": r["rs20"],
                                 "book_eff_pct": r.get("book_pct")} for r in sect.get("rows", [])],
                    "styles": [{"k": s["key"], "state": s["state"], "s20": s["s20"]}
                               for s in (sect.get("market") or {}).get("styles", [])]},
        "cards": cards,
        "in_play": {"ladders": [{"sym": l["symbol"], "t1": f"{l['t1_fraction']}% {l['t1_status']}",
                                 "tranches": [(t["tranche"], t["status"]) for t in l["tranches"]]}
                                for l in recs.get("ladders", [])],
                    "round_trips": [{"sym": t["symbol"], "status": t["status"]}
                                    for t in recs.get("round_trips", [])]},
        "known_tensions": recs.get("tensions") or ["lint ran clean — no unexplained contradictions on screen"],
        "response_contract": CONTRACT,
    }
    md = json.dumps(brief, indent=1, default=str)
    build_hash = hashlib.md5((recs.get("generated_at", "") + str(len(md))).encode()).hexdigest()[:12]
    return {"brief": brief, "markdown": md, "build_hash": build_hash,
            "token_estimate": len(md) // 4,  # chars/4 — labeled ESTIMATE (no local tokenizer)
            "generated_at": datetime.now(timezone.utc).isoformat()}


def ensure_tables(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS oversight_reviews (
        id serial PRIMARY KEY, build_hash text NOT NULL, seat text NOT NULL,
        status text NOT NULL, verdicts jsonb, memo jsonb, raw text,
        latency_ms int, created_at timestamptz DEFAULT now(),
        UNIQUE (build_hash, seat))""")


def _parse_strict(raw: str):
    try:
        txt = raw.strip()
        if txt.startswith("```"):
            txt = txt.split("```")[1].lstrip("json").strip()
        d = json.loads(txt)
        assert isinstance(d.get("cards"), list) and isinstance(d.get("memo"), dict)
        for c in d["cards"]:
            assert c.get("verdict") in ("CONCUR", "QUALIFY", "OBJECT")
        return d
    except Exception:
        return None


def run_free_critiques(cur, force: bool = False) -> dict:
    """Tier 1 — both free seats critique the current build. Cached by build_hash."""
    ensure_tables(cur)
    cur.connection.commit()
    art = build_oversight_brief()
    bh = art["build_hash"]
    out = {"build_hash": bh, "token_estimate": art["token_estimate"], "seats": {}}
    import time
    from llm_lane import available, generate
    prompt = ("You are an independent risk overseer for a retirement-scale defensive trading desk. "
              "Judge WITHIN the constitution. Be adversarial where warranted.\n\n"
              + art["markdown"] + "\n\n" + CONTRACT)
    for seat, lane in (("chatgpt", "chatgpt"), ("grok", "grok")):
        cur.execute("SELECT status FROM oversight_reviews WHERE build_hash=%s AND seat=%s", (bh, seat))
        if cur.fetchone() and not force:
            out["seats"][seat] = "cached"
            continue
        cur.execute("""SELECT count(*) FROM oversight_reviews WHERE seat=%s
                       AND created_at::date=CURRENT_DATE AND status='ok'""", (seat,))
        if cur.fetchone()[0] >= DAILY_PER_SEAT:
            cur.execute("""INSERT INTO oversight_reviews (build_hash, seat, status, raw)
                           VALUES (%s,%s,'quota','oversight daily share exhausted; resets 00:00')
                           ON CONFLICT (build_hash, seat) DO NOTHING""", (bh, seat))
            out["seats"][seat] = "quota"
            continue
        if not available(lane):
            cur.execute("""INSERT INTO oversight_reviews (build_hash, seat, status, raw)
                           VALUES (%s,%s,'unavailable','lane not authenticated/reachable')
                           ON CONFLICT (build_hash, seat) DO NOTHING""", (bh, seat))
            out["seats"][seat] = "unavailable"
            continue
        t0 = time.time()
        try:
            raw = generate(prompt, lane=lane, timeout=150)
            raw = raw if isinstance(raw, str) else json.dumps(raw)
        except Exception as e:
            raw = f"__error__ {e}"
        ms = int((time.time() - t0) * 1000)
        parsed = _parse_strict(raw) if not raw.startswith("__error__") else None
        status = "ok" if parsed else ("unavailable" if raw.startswith("__error__") else "unparseable")
        cur.execute("""INSERT INTO oversight_reviews (build_hash, seat, status, verdicts, memo, raw, latency_ms)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (build_hash, seat) DO UPDATE SET status=EXCLUDED.status,
                         verdicts=EXCLUDED.verdicts, memo=EXCLUDED.memo, raw=EXCLUDED.raw,
                         latency_ms=EXCLUDED.latency_ms""",
                    (bh, seat, status,
                     json.dumps(parsed["cards"]) if parsed else None,
                     json.dumps(parsed["memo"]) if parsed else None,
                     raw[:8000], ms))
        cur.connection.commit()
        out["seats"][seat] = status
    return out


def latest_reviews(cur) -> dict:
    """Current build's verdicts for the pill row + memo panel."""
    ensure_tables(cur)
    cur.connection.commit()
    bh = build_oversight_brief()["build_hash"]
    cur.execute("""SELECT seat, status, verdicts, memo, created_at FROM oversight_reviews
                   WHERE build_hash=%s""", (bh,))
    seats = {}
    for seat, status, verdicts, memo, at in cur.fetchall():
        seats[seat] = {"status": status,
                       "verdicts": verdicts if isinstance(verdicts, list) else (json.loads(verdicts) if verdicts else []),
                       "memo": memo if isinstance(memo, dict) else (json.loads(memo) if memo else None),
                       "at": str(at)[:16]}
    return {"build_hash": bh, "seats": seats}


def paid_preview(cur) -> dict:
    """The ⚖ modal's numbers — REAL token estimate of the actual brief, per-seat cost,
    monthly budget remaining. No send."""
    ensure_tables(cur)
    cur.execute("ALTER TABLE oversight_reviews ADD COLUMN IF NOT EXISTS cost_est numeric")
    cur.connection.commit()
    import os
    pc = json.loads((ROOT / "config" / "defense_recommendations.json").read_text())["oversight_paid"]
    art = build_oversight_brief()
    model = os.environ.get("LLM_CRITICAL_CLOUD") or pc["model"]
    in_cost = art["token_estimate"] / 1e6 * pc["input_per_mtok_usd"]
    out_cost = pc["est_output_tokens"] / 1e6 * pc["output_per_mtok_usd"]
    cur.execute("""SELECT COALESCE(sum(cost_est),0) FROM oversight_reviews
                   WHERE seat='paid' AND date_trunc('month', created_at)=date_trunc('month', now())""")
    spent = float(cur.fetchone()[0])
    return {"ok": True, "build_hash": art["build_hash"], "model": model,
            "input_tokens_est": art["token_estimate"], "output_tokens_est": pc["est_output_tokens"],
            "cost_est_usd": round(in_cost + out_cost, 3),
            "monthly_budget_usd": pc["monthly_budget_usd"],
            "budget_remaining_usd": round(pc["monthly_budget_usd"] - spent, 2),
            "weekly_paid_review": pc.get("weekly_paid_review", False)}


def run_paid_review(cur) -> dict:
    """Tier 2 — the metered seat. Budget-gated at send; result fills pill ④ + the memo
    panel's paid column. Same contract, same strict parsing."""
    import os
    import time
    import urllib.request
    import urllib.error
    pv = paid_preview(cur)
    if pv["cost_est_usd"] > pv["budget_remaining_usd"]:
        return {"ok": False, "error": f"monthly oversight budget: ${pv['budget_remaining_usd']} left < ${pv['cost_est_usd']} est"}
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return {"ok": False, "error": "ANTHROPIC_API_KEY not set"}
    art = build_oversight_brief()
    prompt = ("You are the PAID senior seat on an oversight panel for a retirement-scale defensive "
              "trading desk. Two free seats have already reviewed; be the adjudicator: judge WITHIN "
              "the constitution, be adversarial where warranted, and prioritize what the free seats "
              "would plausibly miss.\n\n" + art["markdown"] + "\n\n" + CONTRACT)
    body = json.dumps({"model": pv["model"], "max_tokens": 3000,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            resp = json.loads(r.read().decode())
        raw = "".join(b.get("text", "") for b in resp.get("content", []))
    except urllib.error.HTTPError as e:
        raw = f"__error__ HTTP {e.code}: {e.read().decode()[:300]}"
    except Exception as e:
        raw = f"__error__ {e}"
    ms = int((time.time() - t0) * 1000)
    parsed = _parse_strict(raw) if not raw.startswith("__error__") else None
    status = "ok" if parsed else ("unavailable" if raw.startswith("__error__") else "unparseable")
    cur.execute("""INSERT INTO oversight_reviews (build_hash, seat, status, verdicts, memo, raw,
                   latency_ms, cost_est)
                   VALUES (%s,'paid',%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (build_hash, seat) DO UPDATE SET status=EXCLUDED.status,
                     verdicts=EXCLUDED.verdicts, memo=EXCLUDED.memo, raw=EXCLUDED.raw,
                     latency_ms=EXCLUDED.latency_ms, cost_est=EXCLUDED.cost_est""",
                (art["build_hash"], status,
                 json.dumps(parsed["cards"]) if parsed else None,
                 json.dumps(parsed["memo"]) if parsed else None,
                 raw[:8000], ms, pv["cost_est_usd"]))
    cur.connection.commit()
    return {"ok": status == "ok", "status": status, "model": pv["model"],
            "cost_est_usd": pv["cost_est_usd"], "latency_ms": ms}


def card_objections(cur, source_card: str) -> list:
    """Latest reviews' OBJECT verdicts for a card — the staging interlock reads this."""
    lr = latest_reviews(cur)
    out = []
    for seat, d in lr.get("seats", {}).items():
        for v in d.get("verdicts") or []:
            if v.get("id") == source_card and v.get("verdict") == "OBJECT":
                out.append({"seat": seat, "reason": v.get("reason", "")})
    return out
