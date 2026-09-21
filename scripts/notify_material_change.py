#!/usr/bin/env python3
"""notify_material_change.py — tell the operator when a tracked name moves.

Stage 2 of docs/architecture/MATERIAL_CHANGE_TO_QUESTIONS.md. Advisory only.

WHY THIS EXISTS
---------------
On 2026-09-05 three watchlist names were up 15-40% and nothing said so. Stage 1 now
detects it — AOUT at 14.93x its own average daily move — but a detector nobody reads
is the same as no detector. This is the part that closes the original complaint, and
it costs nothing: no model is called.

SIGNAL DISCIPLINE
-----------------
Notify on the CHANGE, not on the sweep. This runs on a schedule but only ever speaks
when stage 1 found something new, and each change_guid is announced exactly once. A
detector that fires every fifteen minutes trains the operator to ignore it, and a
muted alarm is worse than no alarm — this system has lost detectors that way before.

DELIVERED IS NOT THE SAME AS ACCEPTED
-------------------------------------
send_telegram returns True when the platform ACCEPTED the event, which is not proof
the operator saw it. On 2026-09-05 two adjacent rows both read LEGACY_DELIVERED and
one had been suppressed by the router. So the outcome is recorded as what was
actually observed, and a change is only marked notified when the send was accepted —
a suppressed alert stays pending rather than being silently consumed.

    python3 scripts/notify_material_change.py            # dry run, prints the message
    python3 scripts/notify_material_change.py --apply
"""
from __future__ import annotations

import argparse
import json
import re
import os
import sys
from datetime import datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

SCHEMA = "MaterialChangeNotice@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

#: ALWAYS. Operator decision 2026-09-07, overriding the market-hours default set the
#: day before: "it's Monday morning now and that has no bearing on it, I should be
#: receiving it no matter what day of the week."
#:
#: The market-hours window was wrong in practice. AOUT burst at 07:13 and SPCX at
#: 16:41 — both outside it — and 36 consecutive notifier runs reported
#: HELD_OUTSIDE_WINDOW while the operator saw nothing and reasonably concluded the
#: layer was dark. News does not wait for the opening bell, and a detector whose
#: output is invisible for sixteen hours a day is indistinguishable from one that is
#: not running.
#:
#: Set to "market" to restore weekday 09:30-16:00 gating.
NOTIFY_WINDOW = os.getenv("MATERIAL_CHANGE_NOTIFY_WINDOW", "always")
MARKET_TZ = ZoneInfo(os.getenv("MATERIAL_CHANGE_TZ", "America/New_York"))
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)

#: Never announce a change older than this. A stale alert is noise, and after a
#: weekend or an outage the backlog would otherwise arrive as a wall of text.
MAX_AGE_HOURS = int(os.getenv("MATERIAL_CHANGE_MAX_AGE_HOURS", "72"))

#: Route this notice through the comms gateway instead of the legacy chokepoint.
#: OFF by default. The gateway additionally requires COMMS_GATEWAY_MODE=CANARY
#: (or ACTIVE) and the message class to be in COMMS_GATEWAY_CANARY_CLASSES, so
#: three independent switches must agree before a single message changes path.
GATEWAY_NOTICE_FLAG = "MATERIAL_CHANGE_GATEWAY_NOTICE"


def gateway_notice_enabled(env: dict | None = None) -> bool:
    e = env if env is not None else os.environ
    return str(e.get(GATEWAY_NOTICE_FLAG, "")).strip().lower() in {"1", "true", "yes", "on"}
#: Ceiling per run, so one thrashing name cannot dominate the channel.
MAX_PER_RUN = int(os.getenv("MATERIAL_CHANGE_MAX_PER_RUN", "8"))

#: MaterialChangeNotice@v1 is a send receipt. Its consumer is the operator, who is
#: not a code path — the durable record of what was announced lives on
#: material_changes.notified_at / notify_outcome, which IS read (by this script, to
#: avoid re-announcing). Declared rather than left dark: an undeclared contract is
#: indistinguishable from one whose caller was forgotten.
NO_CONSUMER_REASON = (
    "send receipt; the durable state it stands for is material_changes.notified_at, "
    "which this script reads to guarantee each change is announced exactly once"
)

DDL = """
ALTER TABLE material_changes ADD COLUMN IF NOT EXISTS notified_at TIMESTAMPTZ;
ALTER TABLE material_changes ADD COLUMN IF NOT EXISTS notify_outcome TEXT;
"""

KIND_LABEL = {
    "price_excursion": "moved",
    "catalyst_new": "new catalyst",
    "news_burst": "news burst",
}


def _db():
    import psycopg2

    for line in (ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())
    return psycopg2.connect(
        host=os.getenv("DB_HOST"), port=os.getenv("DB_PORT"), dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"), password=os.getenv("DB_PASSWORD"))


def in_window(now: datetime | None = None) -> bool:
    """Market hours in the exchange's timezone, weekdays only.

    Outside the window a change is left PENDING, not dropped — it is announced at
    the next open. Dropping it would mean a Friday-evening move is never mentioned,
    which is the failure this whole feature exists to fix.
    """
    if NOTIFY_WINDOW == "always":
        return True
    n = (now or datetime.now(timezone.utc)).astimezone(MARKET_TZ)
    if n.weekday() >= 5:
        return False
    return MARKET_OPEN <= n.time() <= MARKET_CLOSE


def pending(cur, *, limit: int) -> list[dict]:
    cur.execute(
        """SELECT change_guid, symbol, kind, magnitude, baseline, observed_value,
                  observed_at, universe_reason, subject_guid, evidence_json
             FROM material_changes
            WHERE notified_at IS NULL
              AND observed_at > now() - (%s || ' hours')::interval
            ORDER BY magnitude DESC NULLS LAST
            LIMIT %s""", (MAX_AGE_HOURS, limit))
    cols = ["change_guid", "symbol", "kind", "magnitude", "baseline",
            "observed_value", "observed_at", "universe_reason", "subject_guid",
            "evidence_json"]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def context(cur, change: dict) -> dict:
    """WHAT HAPPENED and WHAT IT MEANS — not how many rows we hold.

    The first version of this alert reported "we hold 212 articles, 209 catalysts".
    That is internal plumbing on the operator's phone: it says nothing about the
    company, nothing about what changed, and nothing about what to do. The operator's
    verdict was correct — "what am I supposed to do with these".

    So this returns, in order of preference:
      1. the NARRATIVE the curation step already wrote — plain sentences, grounded in
         cited evidence, e.g. "shares surged 25.47% after hours on better-than-
         expected Q2 sales"
      2. the questions it decided were worth asking
      3. failing both, the actual HEADLINE that triggered it
    """
    sg = change.get("subject_guid")
    out: dict = {}

    cur.execute("""SELECT sentences FROM subject_state_narratives
                    WHERE change_guid = %s ORDER BY created_at DESC LIMIT 1""",
                (change["change_guid"],))
    row = cur.fetchone()
    if row and row[0]:
        payload = row[0] if isinstance(row[0], list) else json.loads(row[0])
        out["narrative"] = [n.get("sentence") for n in payload if n.get("sentence")]

    cur.execute("""SELECT question FROM due_diligence_questions
                    WHERE change_guid = %s ORDER BY created_at LIMIT 2""",
                (change["change_guid"],))
    out["questions"] = [r[0] for r in cur.fetchall()]

    # The raw trigger, for when curation has not run yet.
    ev = change.get("evidence_json") or {}
    if isinstance(ev, str):
        try:
            ev = json.loads(ev)
        except Exception:  # noqa: BLE001
            ev = {}
    rng = ev.get("id_range")
    if not out.get("narrative") and rng:
        cur.execute("""SELECT headline, catalyst_type FROM catalyst_events
                        WHERE id BETWEEN %s AND %s AND symbol = %s
                          AND headline IS NOT NULL
                        ORDER BY published_at DESC LIMIT 10""",
                    (rng[0], rng[1], change["symbol"]))
        picked = pick_headline([(r[0], r[1]) for r in cur.fetchall()])
        if picked:
            out["headline"], out["headline_kind"] = picked
    if not out.get("narrative") and not out.get("headline"):
        # 2026-09-15: the newest news title for the ticker was quoted as if it explained the move —
        # "Top Forgent Power Solutions (FPS) Competitors 2026 - MarketBeat", "UZX Stock Price Today".
        # Only catalysts filed around the move are considered, and web-page titles are not news.
        _safe(cur, lambda: _catalyst_near_move(cur, change, out))
    _safe(cur, lambda: _watch_context(cur, change, out))

    if sg:
        cur.execute("""SELECT max(created_at)::date FROM hermes_external_research
                        WHERE subject_guid = %s""", (sg,))
        r = cur.fetchone()
        out["last_research"] = str(r[0]) if r and r[0] else None
    return out


# Page titles that are not news: quote pages, competitor lists, "should I buy", movers roundups.
NOT_NEWS = re.compile(
    r"(?i)(stock price|price today|price and chart|stock quote|quote & history|competitors|should i buy|"
    r"stocks? to watch|trending stocks|stocks moving|top gainers|top losers|premarket movers|"
    r"stock forecast|tradingview|stock analysis|lead sub-\$1)")
UNTYPED = {"other", "news_momentum", "neutral", "technical", "stock_price_movement", "stock_price_increase", "bullish", "bearish"}
SOURCE_LABELS = {
    "ai_discovered": "AI discovery", "finviz_screener": "the Finviz screener", "paper_proposal": "a proposal",
    "operator": "you", "hermes": "Hermes research", "portfolio": "your portfolio", "pullback_macd": "the pullback screener",
    "small_cap_rotation": "small-cap rotation", "trade_ai": "Trade-AI",
}
_ENRICHMENT: dict | None = None


def pick_headline(rows: list[tuple]) -> tuple[str, str] | None:
    """(headline, kind) from newest-first (headline, catalyst_type) rows: a typed catalyst first, else real news."""
    news = [(h, t) for h, t in rows if h and not NOT_NEWS.search(h)]
    typed = [(h, t) for h, t in news if str(t or "other").lower() not in UNTYPED]
    if typed:
        return typed[0][0], "catalyst"
    if news:
        return news[0][0], "news"
    return None


def _safe(cur, fn) -> None:
    try:
        fn()
    except Exception:  # noqa: BLE001 -- extra context must never cost the alert
        try:
            cur.connection.rollback()
        except Exception:  # noqa: BLE001
            pass


def _catalyst_near_move(cur, change: dict, out: dict) -> None:
    cur.execute("""SELECT headline, catalyst_type FROM catalyst_events
                    WHERE upper(symbol) = upper(%s) AND headline IS NOT NULL
                      AND COALESCE(published_at, created_at)
                          BETWEEN %s::timestamptz - interval '3 days' AND %s::timestamptz + interval '1 day'
                    ORDER BY COALESCE(published_at, created_at) DESC LIMIT 25""",
                (change["symbol"], change.get("observed_at"), change.get("observed_at")))
    picked = pick_headline([(r[0], r[1]) for r in cur.fetchall()])
    if picked:
        out["headline"], out["headline_kind"] = picked


def _watch_context(cur, change: dict, out: dict) -> None:
    sym = str(change["symbol"]).upper()
    cur.execute("""SELECT source, provenance_reason, first_seen_at::date FROM watchlist_items
                    WHERE upper(symbol) = %s AND status <> 'removed'
                    ORDER BY CASE WHEN source = 'portfolio' THEN 0
                                  WHEN source IN ('operator', 'manual', 'telegram', 'directive') THEN 1 ELSE 2 END,
                             first_seen_at ASC LIMIT 1""", (sym,))
    r = cur.fetchone()
    if r:
        out["watch"] = {"source": r[0], "reason": r[1], "since": str(r[2]) if r[2] else None}
    cur.execute("""SELECT price, change_pct FROM watchlist_items WHERE upper(symbol) = %s AND price IS NOT NULL
                    ORDER BY last_enriched_at DESC NULLS LAST LIMIT 1""", (sym,))
    r = cur.fetchone()
    if r:
        out["price"] = float(r[0]) if r[0] is not None else None
        out["change_pct"] = float(r[1]) if r[1] is not None else None
    cur.execute("""SELECT strategy_type, active FROM ticker_strategy_classifications WHERE upper(symbol) = %s
                    ORDER BY active DESC NULLS LAST LIMIT 1""", (sym,))
    r = cur.fetchone()
    out["strategy"] = r[0] if r else None
    out["strategy_inactive"] = bool(r and r[1] is False)
    cur.execute("SELECT sector, industry FROM symbol_profiles WHERE upper(symbol) = %s LIMIT 1", (sym,))
    r = cur.fetchone()
    if r and (r[0] or r[1]):
        out["sector"] = {"sector": r[0], "industry": r[1]}
    try:
        cur.execute("""SELECT state, details FROM cio_entry_states WHERE symbol = %s
                        ORDER BY evaluated_at DESC LIMIT 1""", (sym,))
        r = cur.fetchone()
        if r:
            d = r[1] if isinstance(r[1], dict) else json.loads(r[1] or "{}")
            out["entry_state"] = {"state": r[0], **{k: d.get(k) for k in (
                "entry_low", "entry_high", "stop", "target", "rr", "distance_pct", "reasons", "price")}}
    except Exception:  # noqa: BLE001 — table absent before the entry-state lane first runs
        cur.connection.rollback()
    held = holding_for(sym)
    if held:
        out["holding"] = held
    try:
        try:
            from lib.symbol_thesis_attach import thesis_fields_for_symbol
        except ImportError:
            from scripts.lib.symbol_thesis_attach import thesis_fields_for_symbol
        t = thesis_fields_for_symbol(sym) or {}
        if t.get("has_current_symbol_thesis") or t.get("thesis_summary"):
            out["thesis"] = {"state": t.get("thesis_state"), "summary": clean_thesis(sym, t.get("thesis_summary")),
                             "last_reviewed": t.get("last_reviewed")}
    except Exception:  # noqa: BLE001 — thesis is context, never a reason to drop the notice
        pass
    cur.execute("""SELECT ideal_entry, stop_loss, target_price FROM watchlist_strategy_cards
                    WHERE upper(symbol) = %s ORDER BY updated_at DESC NULLS LAST LIMIT 1""", (sym,))
    r = cur.fetchone()
    if r and r[0] is not None:
        out["plan"] = {"entry": float(r[0]), "stop": float(r[1]) if r[1] is not None else None,
                       "target": float(r[2]) if r[2] is not None else None}
    cur.execute("""SELECT action, created_at::date FROM cio_decisions WHERE upper(symbol) = %s
                    ORDER BY created_at DESC LIMIT 1""", (sym,))
    r = cur.fetchone()
    if r:
        out["cio"] = {"action": r[0], "date": str(r[1])}
    global _ENRICHMENT
    if _ENRICHMENT is None:
        try:
            _ENRICHMENT = json.loads((Path(__file__).resolve().parent.parent / "data" / "portfolios" / "state"
                                      / "ticker_enrichment_cache.json").read_text())
        except Exception:  # noqa: BLE001
            _ENRICHMENT = {}
    try:
        from lib.finviz_csv import enrichment_market_cap_billions
        from lib.market_cap_label import cap_label, pill
    except ImportError:  # imported as scripts.notify_material_change
        from scripts.lib.finviz_csv import enrichment_market_cap_billions
        from scripts.lib.market_cap_label import cap_label, pill
    b = enrichment_market_cap_billions(_ENRICHMENT.get(sym) or {})
    if b is not None:
        out["size"] = pill(cap_label(b * 1000.0))


_HOLDINGS: dict | None = None
HOLDINGS_PATH = Path(__file__).resolve().parent.parent / "data" / "portfolios" / "state" / "holdings.json"


def _account_label(account: str) -> str:
    a = str(account or "").lower().replace("schwab_", "").replace("fidelity_", "").replace("_", " ").strip()
    return {"rollover ira": "Rollover IRA", "roth ira": "Roth IRA", "taxable": "Taxable"}.get(a, a.title() or "account")


def holding_for(symbol: str, holdings: dict | None = None) -> dict | None:
    """The position in `symbol` across accounts: shares, cost, value and P/L computed as value - cost.

    2026-09-15: the WMT notice never said the operator owns 100 shares. The stored gain_loss field
    read +$13 while market_value - cost_basis was +$228, so P/L is computed, not copied.
    """
    global _HOLDINGS
    if holdings is None:
        if _HOLDINGS is None:
            try:
                _HOLDINGS = json.loads(HOLDINGS_PATH.read_text())
            except Exception:  # noqa: BLE001
                _HOLDINGS = {}
        holdings = _HOLDINGS
    rows = [h for h in (holdings.get("holdings") or [])
            if str(h.get("symbol") or "").upper() == symbol.upper() and not h.get("is_cash")]
    if not rows:
        return None
    shares = sum(float(h.get("shares") or 0) for h in rows)
    cost = sum(float(h.get("cost_basis") or 0) for h in rows)
    value = sum(float(h.get("market_value") or 0) for h in rows)
    if shares <= 0:
        return None
    out = {"shares": shares, "accounts": sorted({_account_label(h.get("account")) for h in rows}),
           "cost_basis": cost or None, "market_value": value or None}
    if cost > 0 and value > 0:
        out["avg_cost"] = cost / shares
        out["price"] = value / shares
        out["pl_usd"] = value - cost
        out["pl_pct"] = (value - cost) / cost * 100.0
    return out


def clean_thesis(symbol: str, summary: str | None, limit: int = 140) -> str | None:
    """One readable sentence: drop the leading "SYM 1." numbering and trailing guid= tokens."""
    import re as _re
    text = str(summary or "").strip()
    if not text:
        return None
    text = _re.sub(rf"^{_re.escape(symbol)}\s+\d+\.\s*", "", text, flags=_re.I)
    text = _re.sub(r"\s*guid=\S+", "", text).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def dedupe_by_symbol(changes: list[dict]) -> list[dict]:
    """One line per SYMBOL, strongest signal wins.

    The 2026-09-07 queue listed AOUT twice (two news bursts hours apart) and SPCX
    twice. A name appearing repeatedly in one alert is not more informative — it is
    harder to read, and it crowds out the other names.
    """
    best: dict[str, dict] = {}
    for c in changes:
        sym = c["symbol"]
        cur = best.get(sym)
        if cur is None or (c.get("magnitude") or 0) > (cur.get("magnitude") or 0):
            c = dict(c)
            c["also"] = (cur or {}).get("also", 0) + (1 if cur else 0)
            best[sym] = c
        else:
            cur["also"] = cur.get("also", 0) + 1
    return sorted(best.values(),
                  key=lambda x: (-(x.get("precedence") or 0), -(x.get("magnitude") or 0)))


#: What the magnitude means, in words. "x1.2 vs usual" is noise dressed as signal.
def _signed_move(c: dict, info: dict | None = None) -> float | None:
    ev = c.get("evidence_json") or c.get("evidence") or {}
    if isinstance(ev, str):
        try:
            ev = json.loads(ev)
        except Exception:  # noqa: BLE001
            ev = {}
    if ev.get("move_pct_signed") is not None:
        return float(ev["move_pct_signed"])
    cp = (info or {}).get("change_pct")
    if cp is not None and c.get("observed_value") is not None:
        return abs(float(c["observed_value"])) * (1 if float(cp) >= 0 else -1)
    return None


def _headline_line(c: dict, info: dict | None = None) -> str:
    sym, kind = c["symbol"], c["kind"]
    mag = float(c["magnitude"] or 0)
    info = info or {}
    if kind == "price_excursion":
        signed = _signed_move(c, info)
        size = abs(float(c["observed_value"]))
        verb = "moved" if signed is None else ("up" if signed >= 0 else "down")
        tail = "".join(f" · {x}" for x in (
            f"${info['price']:,.2f}" if info.get("price") is not None else "", info.get("size") or "") if x)
        return f"{sym} — {verb} {size:.0f}%, {mag:.0f}x its normal daily range{tail}"
    if kind == "news_burst":
        return f"{sym} — unusual news volume, {mag:.0f}x normal"
    if kind == "sector_move":
        return f"{sym} — sector-wide move"
    ev = c.get("evidence") or {}
    ctype = str(ev.get("catalyst_type") or "").replace("_", " ")
    return f"{sym} — {ctype or 'new catalyst'}"


def render(changes: list[dict], ctx: dict[str, dict]) -> str:
    changes = dedupe_by_symbol(changes)
    lines = [f"Material change — {len(changes)} name(s) worth a look"]
    for c in changes:
        info = ctx.get(str(c["change_guid"]), {})
        lines.append("\n" + _headline_line(c, info))

        # WHAT HAPPENED. The narrative if we have one, else a real catalyst, else say there is none.
        if info.get("narrative"):
            for sentence in info["narrative"][:2]:
                lines.append(f"  {sentence}")
        elif info:
            lines.append(f"  {_what_line(info)}")

        # WHY IT IS IN FRONT OF YOU, WHAT IT BELONGS TO, WHAT THE CIO SAYS, WHAT IS OPEN. Never advice.
        for d in _detail_lines(c, info):
            lines.append(f"  · {d}")
    lines.append("\nAdvisory only. No position action taken or implied.")
    return "\n".join(lines)


def _what_line(info: dict) -> str | None:
    if info.get("narrative"):
        return None
    if info.get("headline"):
        prefix = "Catalyst: " if info.get("headline_kind") == "catalyst" else "News around the move (not confirmed as the cause): "
        return prefix + info["headline"][:150]
    return "No news found that explains this move."


def _provenance_line(c: dict, info: dict) -> str:
    base = _why_line(c)
    w = info.get("watch")
    if not w:
        return base
    who = SOURCE_LABELS.get(str(w.get("source") or ""), str(w.get("source") or "unknown source").replace("_", " "))
    since = f" since {w['since']}" if w.get("since") else ""
    reason = str(w.get("reason") or "").split(":", 2)[-1].strip() if w.get("reason") else ""
    reason = f" ({reason[:80]})" if reason else ""
    if info.get("holding") or str(w.get("source") or "") == "portfolio":
        return f"you hold this — on your watchlist{since} ({who})"
    if base == "you asked about this" and str(w.get("source") or "") not in ("operator", "manual", "telegram", "directive"):
        base = "on your watchlist"
    return f"{base}{since} — found by {who}{reason}"


def _strategy_line(info: dict) -> str | None:
    if "strategy" not in info and "plan" not in info:
        return None
    strat = str(info.get("strategy") or "").replace("_", " ")
    if strat and info.get("strategy_inactive"):
        head = f"Strategy: {strat} (classification inactive)"
    else:
        head = f"Strategy: {strat}" if strat else "Strategy: none assigned"
    plan, price = info.get("plan"), info.get("price")
    if not plan:
        return head + " · no entry plan"
    levels = f"plan entry ${plan['entry']:,.2f}" + (f" / stop ${plan['stop']:,.2f}" if plan.get("stop") else "") + (
        f" / target ${plan['target']:,.2f}" if plan.get("target") else "")
    if price and plan["entry"]:
        return f"{head} · {levels} · {_plan_state(plan, price)}"
    return f"{head} · {levels}"


def _plan_state(plan: dict, price: float) -> str:
    """Where price sits INSIDE the plan's own levels — not merely how far from entry.

    The previous line read `abs(dist) > 25 -> "plan is stale"`, which described two
    opposite outcomes identically. Operator-reported 2026-09-21 on HPE: entry $44.47,
    stop $40.28, target $63.32, price $61.95 — 92.7% of the way to target, and the alert
    called the plan stale. The same branch emits the same words for price $28.00, which
    is 31% THROUGH the stop. A won plan and a blown plan cannot share a sentence.

    `abs()` erased the sign, and `target`/`stop` were already in the dict, unused. Entry
    being unreachable is a real and separate fact, so it is reported as "entry missed"
    alongside what the plan is actually doing, never instead of it.
    """
    entry = float(plan["entry"])
    if entry <= 0:
        return "plan has no usable entry"
    target = plan.get("target")
    stop = plan.get("stop")
    target = float(target) if target else None
    stop = float(stop) if stop else None
    dist = (price - entry) / entry * 100.0
    # Direction comes from the plan's own geometry, so shorts read correctly too.
    short = target is not None and target < entry
    hit_stop = stop is not None and (price >= stop if short else price <= stop)
    hit_target = target is not None and (price <= target if short else price >= target)
    if hit_stop:
        return f"STOP BREACHED — price {dist:+.1f}% from entry, at or through the ${stop:,.2f} stop"
    if hit_target:
        return f"TARGET REACHED — price {dist:+.1f}% from entry, at or through the ${target:,.2f} target"
    if target is not None and target != entry:
        progress = (price - entry) / (target - entry) * 100.0
        if progress >= 0:
            missed = " — entry no longer available" if abs(dist) > 25 else ""
            return (f"working — {progress:.0f}% of the way from entry to target "
                    f"({dist:+.1f}% from entry){missed}")
        return f"below entry — price {dist:+.1f}% from entry, still above the stop"
    # No target to judge against: distance from entry is all we have, so say only that.
    if abs(dist) > 25:
        return f"entry is stale — price is {dist:+.1f}% from it, and the plan has no target"
    return f"price is {dist:+.1f}% from the entry"


def _cio_line(info: dict) -> str | None:
    if "watch" not in info and "cio" not in info:
        return None
    cio = info.get("cio")
    if not cio:
        return "CIO: no view yet"
    return f"CIO: {str(cio['action']).replace('_', ' ').title()} ({cio['date']})"


def _position_line(info: dict) -> str | None:
    h = info.get("holding")
    if not h:
        return None
    shares = f"{h['shares']:,.0f}" if float(h["shares"]).is_integer() else f"{h['shares']:,.3f}"
    where = " / ".join(h.get("accounts") or [])
    head = f"You own {shares} sh" + (f" ({where})" if where else "")
    if h.get("pl_usd") is None:
        return head
    sign = "+" if h["pl_usd"] >= 0 else "-"
    return (f"{head} · cost ${h['avg_cost']:,.2f} · now ${h['price']:,.2f} · "
            f"{sign}${abs(h['pl_usd']):,.0f} ({h['pl_pct']:+.1f}%)")


def _stance_line(info: dict) -> str | None:
    """What to do with it, as the CIO's advisory stance — never a size or an order."""
    es, cio, held = info.get("entry_state"), info.get("cio"), bool(info.get("holding"))
    cio_part = f" · CIO decision: {str(cio['action']).replace('_', ' ').title()} ({cio['date']})" if cio else ""
    if not es:
        if not info.get("watch") and not cio and not held:
            return None
        return ("CIO stance: no entry plan yet — hold, nothing to add until one exists" if held
                else "CIO stance: no entry plan yet") + cio_part
    state = str(es.get("state") or "")
    lo, hi = es.get("entry_low"), es.get("entry_high")
    zone = (f"${lo:,.2f}" if lo == hi else f"${lo:,.2f}–${hi:,.2f}") if lo is not None and hi is not None else "the plan zone"
    rr = f" · R:R {es['rr']:.1f}" if es.get("rr") is not None else ""
    dist = es.get("distance_pct")
    if state == "BUY_READY":
        text = ("add more: price is inside the entry zone " if held else "buy-ready: price is inside the entry zone ") + zone + rr
    elif state == "ENTRY_NEAR":
        text = f"getting close: price is {dist:.1f}% from the entry {zone} — wait for the zone{rr}" if dist is not None \
            else f"getting close to the entry {zone}{rr}"
    elif state == "BLOCKED":
        reasons = "; ".join(str(x) for x in (es.get("reasons") or [])[:2]) or "a plan check failed"
        text = f"don't {'add' if held else 'buy'} — blocked: {reasons}"
    else:
        where = f"price is {dist:.1f}% above the entry {zone}" if dist is not None else f"price is away from the entry {zone}"
        text = (f"hold, don't add yet — {where}{rr}" if held else f"wait — {where}{rr}")
    return f"CIO stance: {text}{cio_part}"


def _sector_thesis_line(info: dict) -> str | None:
    parts = []
    sec = info.get("sector") or {}
    if sec.get("sector") or sec.get("industry"):
        parts.append("Sector: " + " · ".join(x for x in (sec.get("sector"), sec.get("industry")) if x))
    t = info.get("thesis") or {}
    if t.get("summary"):
        parts.append(f"Thesis ({str(t.get('state') or 'on file').lower()}): {t['summary']}")
    return " · ".join(parts) or None


def _detail_lines(c: dict, info: dict) -> list[str]:
    lines = [_provenance_line(c, info)]
    for extra in (_position_line(info), _stance_line(info), _strategy_line(info), _sector_thesis_line(info)):
        if extra:
            lines.append(extra)
    lines.append(_next_line(info))
    return lines


def _why_line(c: dict) -> str:
    tier = c.get("universe_reason", "") or ""
    if "operator" in tier:
        return "you asked about this"
    return ("you hold this" if "held" in tier else
            "re-entry candidate" if "reentry" in tier else "on your watchlist")


def _next_line(info: dict) -> str:
    if info.get("questions"):
        return f"open question: {info['questions'][0]}"
    if not info.get("last_research"):
        return "never researched — questions are being generated now"
    return f"last researched {info['last_research']}"


def rich_enabled(env: dict | None = None) -> bool:
    e = env if env is not None else os.environ
    return str(e.get("TELEGRAM_RICH_ALERTS", "1")).strip().lower() not in {"0", "false", "off", "no"}


def render_rich(changes: list[dict], ctx: dict[str, dict]) -> dict:
    """The same notice as `render`, in Telegram HTML with buttons.

    Operator 2026-09-14: "no emphasis in links on everything that can go back to the command center or
    to the source". Each ticker is bold and opens its Command Center page; Finviz and Yahoo sit under
    it; what happened is quoted; one name gets its chart above the text. `render` stays the plain text
    the router check and the outbound-turn capture read.
    """
    try:
        from scripts.lib import telegram_rich as tr
    except ImportError:  # pragma: no cover - scripts/ on path
        from lib import telegram_rich as tr  # type: ignore
    changes = dedupe_by_symbol(changes)
    out = [f"⚡ <b>Material change — {len(changes)} name(s) worth a look</b>"]
    symbols: list[str] = []
    for c in changes:
        sym = str(c["symbol"]).upper()
        symbols.append(sym)
        info = ctx.get(str(c["change_guid"]), {})
        head = _headline_line(c, info)
        rest = head[len(str(c["symbol"])):] if head.startswith(str(c["symbol"])) else f" — {head}"
        out.append("")
        out.append(f"<b>{tr.link(sym, tr.cc_symbol_url(sym))}</b>{tr.esc(rest)}")
        said = info.get("narrative")[:2] if info.get("narrative") else ([_what_line(info)] if info else [])
        if said:
            out.append("<blockquote>" + "\n".join(tr.esc(x) for x in said) + "</blockquote>")
        for d in _detail_lines(c, info):
            out.append(f"· {tr.esc(d)}")
        out.append(f"{tr.link('Finviz', tr.finviz_url(sym))} · {tr.link('Yahoo', tr.yahoo_url(sym))}")
    out.append("")
    out.append("<i>Advisory only. No position action taken or implied.</i>")
    buttons = [{"text": f"📊 {s} in Command Center", "url": tr.cc_symbol_url(s)} for s in symbols[:3]]
    return {
        "text": "\n".join(out),
        "reply_markup": {"inline_keyboard": [[b] for b in buttons]} if buttons else None,
        "link_preview_options": ({"url": tr.chart_image_url(symbols[0]), "prefer_large_media": True,
                                  "show_above_text": True} if len(symbols) == 1 else {"is_disabled": True}),
    }


def route_check(message: str) -> str:
    """Would the router send THIS message, or suppress it?

    Asked BEFORE sending, on purpose. An earlier version asked afterwards by reading
    the most recent communication_deliveries row — but "most recent row" is not "the
    row for my send", and a stale SUPPRESSED row made a successful send look unknown.

    should_send_telegram() is a pure function of the message, correlated to exactly
    this text, so there is nothing to mis-attribute. A router that cannot be imported
    is treated as "will send" — that is the legacy path's own behaviour, and assuming
    suppression there would silence every alert on a partial install.
    """
    try:
        from telegram_alert_router import should_send_telegram
    except ImportError:
        return "WILL_SEND"
    return "WILL_SEND" if should_send_telegram(message) else "WOULD_SUPPRESS"


def capture_agent_turns(conn, *, message: str, rows: list[dict], gw: dict) -> int:
    """Record what this alert was about, per delivered message id.

    WHY THIS EXISTS
    ---------------
    An operator replying to an alert names its subject by position. Resolving
    that reply needs a row saying "telegram message 51574 was about WMT" — and
    no such row was ever written. Material-change notices go out through
    `deliver_notice` -> gateway; only the conversational path
    (`cio_telegram_converse._send`) ever recorded an agent turn, so alerts were
    invisible as reply parents. Measured 2026-09-11: 2 agent turns existed in
    total, none for any alert, while 39 of 108 operator turns sat unbound.

    The comms ledger cannot answer this. `provider_message_id` is stored as the
    comma-joined string "51573,51574", and both
    `find_delivery_by_provider_message_id` and
    `resolve_event_by_provider_message_id` compare it whole and read
    `provider_coordinates["message_id"]` (singular) while the adapters write
    `message_ids` (plural). Nothing splits it. `operator_conversation_turns`
    already keys on a single `message_id`, so it is the reverse map that works.

    GRAIN: one row per (message id, subject) — `persist_turn`'s documented grain,
    reached by handing it one `resolved` entry per change. A four-name digest
    delivered to two chats writes eight rows, and a reply to either chat's copy
    resolves.

    Best-effort by construction: the alert has already been delivered and the
    rows already consumed by the time this runs. An alert must never fail
    because bookkeeping did.
    """
    coords = gw.get("provider_coordinates") or {}
    mids = [str(m).strip() for m in (coords.get("message_ids") or []) if str(m).strip()]
    chats = [str(c).strip() for c in (coords.get("chat_ids") or []) if str(c).strip()]
    if not mids:
        # Fall back to the joined string. Safe HERE because this is the producer
        # side, where the value was built by a stable ",".join — unlike the
        # lookup side, which never splits it at all.
        mids = [m.strip() for m in str(gw.get("provider_message_id") or "").split(",") if m.strip()]
    if not mids:
        return 0

    resolved = [
        {"symbol": r.get("symbol"),
         "subject_guid": str(r["subject_guid"]) if r.get("subject_guid") else None,
         "issuer_guid": None,
         # The subject is carried by the alert itself, not inferred from prose.
         "identity_status": "CONFIRMED" if r.get("subject_guid") else None,
         "matched_via": "material_change",
         "matched_text": r.get("symbol")}
        for r in rows if r.get("subject_guid")
    ]
    if not resolved:
        return 0

    from scripts.lib.inbound_identity_tagger import persist_turn

    written = 0
    for i, mid in enumerate(mids):
        # message_ids[i] is the id in chat_ids[i]; a reply arrives with the chat
        # it was sent from, so the pairing has to survive or the lookup misses.
        chat = chats[i] if i < len(chats) else (chats[0] if chats else None)
        written += persist_turn(
            {"resolved": resolved, "topics": [], "unresolved_mentions": []},
            conn=conn, text=message, role="agent",
            chat_id=chat, message_id=mid, thread_id=mid, channel="telegram")
    return written


def deliver_notice(message: str, *, subject_key: str, rich: dict | None = None) -> tuple[bool, dict]:
    """Send one operator notice. Returns (accepted, gateway_report).

    Extracted from main() so the alarm can be FIRED by a test. An alarm that has
    never been observed firing is indistinguishable from no alarm, and this
    file's send had no firing test at all.

    Delivery owner: legacy by default, gateway when explicitly enabled.

    An earlier version of this docstring claimed the gateway had never carried an
    organic producer, and that every SENT row all-time was a staged proof. The
    delivery census disproves it: `agent:cio` has delivered 8 organic
    `agent_outbound` notices with real provider message ids between 2026-09-08 and
    2026-09-10. The gateway was never dead. What was dead was *this* producer, and
    for a reason no counter showed: it passed the `operator_alert` alias into a
    class allowlist that only ever matches canonical names, so every send failed
    closed before any provider I/O. Fixed by passing `ops`, the canonical class
    `agent:cio` already uses.

    This is still a real organic producer: the notice is assembled from
    material_changes the detector actually found, not from an event invented to
    move a counter.
    """
    # `rich` (render_rich) replaces the body and adds buttons + chart; `message` is the plain fallback.
    extra: dict = {}
    if rich and rich.get("text"):
        message = rich["text"]
        extra = {"reply_markup": rich.get("reply_markup"), "link_preview_options": rich.get("link_preview_options")}
    if not gateway_notice_enabled():
        from telegram_alert import send_telegram

        return bool(send_telegram(message, message_class="operator_alert", **extra)), {"attempted": False}

    from scripts.lib.comms.channel_adapters import send_via_gateway

    gw = send_via_gateway(
        "telegram",
        body=message,
        producer="notify_material_change",
        subject_key=subject_key,
        event_type="material_change_notice",
        # CANONICAL class, not the `operator_alert` alias. `telegram_class_allowed`
        # normalizes the *message* before the allowlist test but leaves the
        # *allowlist* verbatim, so an aliased class can never match a canonical
        # entry and can never match its own alias either once the ledger stores
        # the canonical form. Passing `operator_alert` here failed closed on every
        # send with `delivery_blocked_allowlist:CANARY:operator_alert` and no
        # legacy fallback, which is indistinguishable from having no producer.
        # `agent:cio` has delivered through this same gateway since 2026-09-08
        # precisely because it passes the canonical class. Match it.
        message_class="ops",
        retention_class="operational_30d",
        deliver=True,
        severity="info",
        **extra,
    )
    # SENT IS NOT SETTLED. `delivered` means the gateway owned the send and the
    # provider acknowledged it; `ok` can be true for a publish merely recorded,
    # and a reservation is not a delivery.
    accepted = bool(gw.get("delivered"))
    report = {
        "attempted": True,
        "delivered": accepted,
        "delivery_owned": bool(gw.get("delivery_owned")),
        "gateway_mode": gw.get("gateway_mode"),
        "event_id": gw.get("event_id"),
        "delivery_id": gw.get("delivery_id"),
        "errors": gw.get("errors") or ([gw["error"]] if gw.get("error") else []),
    }
    if not accepted:
        # Do NOT silently fall back to legacy. A gateway failure that quietly
        # succeeded as legacy would report SENT, consume the rows, and leave the
        # gateway counter at zero with nothing to explain why.
        print(f"gateway did not deliver ({report['errors']}) — "
              "changes left pending, no legacy fallback", file=sys.stderr)
    return accepted, report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--ignore-window", action="store_true",
                    help="operator-run only; scheduled jobs must respect the window")
    args = ap.parse_args()

    conn = _db()
    cur = conn.cursor()
    # Unconditional, including on a dry run: the columns are additive, nullable and
    # idempotent (ADD COLUMN IF NOT EXISTS), and a dry run that cannot read the same
    # shape the apply path writes is not a rehearsal of anything. Gating this behind
    # --apply made the dry run fail with UndefinedColumn on a clean install.
    # ddl_guard: skip ADD COLUMN statements already satisfied, so a scheduled run
    # takes no AccessExclusiveLock on material_changes just to assert a no-op.
    from scripts.lib.ddl_guard import apply_ddl
    apply_ddl(cur, DDL)
    conn.commit()

    open_now = args.ignore_window or in_window()
    rows = pending(cur, limit=MAX_PER_RUN)
    ctx = {str(r["change_guid"]): context(cur, r) for r in rows}

    result = {"schema": SCHEMA, "authority": AUTHORITY, "model_calls": 0,
              "pending": len(rows), "in_window": open_now,
              # None when nothing was attempted; 0 is a measured zero.
              "rows_produced": None, "outcome": None}

    if not rows:
        result["rows_produced"] = 0 if args.apply else None
        print(f"{SCHEMA}: nothing pending")
        print("RESULT: " + json.dumps(result))
        return 0

    message = render(rows, ctx)
    print(message)
    if not open_now:
        # Held, not dropped. A Friday-evening move must still be announced Monday.
        print(f"\n[held — outside the {NOTIFY_WINDOW} window; stays pending]")
        result["outcome"] = "HELD_OUTSIDE_WINDOW"
        print("RESULT: " + json.dumps(result))
        return 0
    if not args.apply:
        print("\n[dry run — nothing sent, nothing marked]")
        print("RESULT: " + json.dumps(result))
        return 0

    routed = route_check(message)
    if routed == "WOULD_SUPPRESS":
        # Do not send into a suppression, and above all do not consume the changes.
        # On the first live run the send was ACCEPTED, the router suppressed it into
        # the 8pm digest, and three changes were marked notified while the operator
        # received nothing. Consumed-and-silent is the worst outcome available here:
        # the row is gone and the silence looks normal.
        result["outcome"] = "WOULD_SUPPRESS"
        result["rows_produced"] = 0
        print("router would suppress this message — left pending, not sent",
              file=sys.stderr)
        conn.close()
        print("RESULT: " + json.dumps(result))
        return 0

    # Delivery owner: legacy by default, gateway when explicitly enabled.
    #
    # Every gateway-SETTLED row that has ever existed (3, all-time) is a staged
    # proof message asking the operator to reply "OK". Those are controlled
    # evidence and are excluded from acceptance, so the gateway has never carried
    # an organic producer. This is that producer — and it is a real one: the
    # notice below is assembled from material_changes the detector actually
    # found, not from an event invented to move a counter.
    #
    # The flag defaults OFF and rollback needs no deploy: unset it and the very
    # next 15-minute run goes back down the legacy path.
    rich = None
    if rich_enabled():
        try:
            rich = render_rich(rows, ctx)
        except Exception as exc:  # noqa: BLE001 -- formatting must never cost the notice
            print(f"[rich] layout unavailable ({type(exc).__name__}: {exc}); sending plain text", file=sys.stderr)
    accepted, gw_result = deliver_notice(message, subject_key=str(
        rows[0].get("subject_guid") or rows[0]["change_guid"]), rich=rich)
    result["gateway"] = gw_result
    result["outcome"] = "SENT" if accepted else "NOT_ACCEPTED"
    if accepted:
        cur.execute("""UPDATE material_changes
                          SET notified_at = now(), notify_outcome = %s
                        WHERE change_guid = ANY(%s::uuid[])""",
                    ("SENT", [str(r["change_guid"]) for r in rows]))
        result["rows_produced"] = cur.rowcount
        conn.commit()
        # Record what this alert was about, so a reply to it can find its
        # subject. Strictly after the send and the consume — an alert must never
        # fail because bookkeeping did.
        try:
            result["agent_turns"] = capture_agent_turns(
                conn, message=message, rows=rows, gw=gw_result)
        except Exception as exc:  # noqa: BLE001
            result["agent_turns"] = 0
            print(f"[outbound-tag] {type(exc).__name__}: {str(exc)[:160]}",
                  file=sys.stderr)
    else:
        result["rows_produced"] = 0
        print("send not accepted — changes left pending for the next run",
              file=sys.stderr)
    conn.close()
    print("RESULT: " + json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
