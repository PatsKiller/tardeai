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

PAGE, DIGEST OR COMMAND CENTER (operator decisions 2026-09-24)
--------------------------------------------------------------
The 2026-09-24 maturity review of a live notice (ROL / LTRN / KLXE / RCL / EXPE)
found it paged five names none of which the operator held or could act on, two on
quotes 30.7h and 112.6h old, with "CIO stance: don't buy" beside "CIO decision: Buy
Ready" for the same name. Each change is now ROUTED on its own facts:

  PAGE            a HELD name whose stop or target is hit, or that made a material
                  price move; or a watchlist name the CIO rates BUY_READY on a fresh
                  quote. One message per name, the point in the first line.
  DIGEST          everything else with a fresh quote — including a watchlist name
                  through its plan stop, which is "PLAN INVALIDATED — re-plan or
                  drop", never "STOP BREACHED" (that reads as an exit order for a
                  position the operator does not have). Sent once a day (--digest).
  COMMAND_CENTER  a stale quote (older than cio_entry_state.MAX_QUOTE_AGE_H), or an
                  inactive strategy with no plan. Not sent; listed by name in the
                  digest's "not shown" line and visible in the Command Center.

Delivery is verified per message: a notice the comms editor HELD is not delivered,
so its rows stay pending (telegram_alert.last_held_chunks). The router check runs on
each page's own text, never on a batch where one name's thesis prose ("paper
proposal") could suppress all the others (179 suppressed runs, 2026-09-22..24).

    python3 scripts/notify_material_change.py                  # dry run: pages
    python3 scripts/notify_material_change.py --apply
    python3 scripts/notify_material_change.py --digest          # dry run: daily digest
    python3 scripts/notify_material_change.py --digest --apply
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import os
import sys
import uuid
from datetime import datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

SCHEMA = "MaterialChangeNotice@v2"
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
#: Measured from when the detector RECORDED the change (created_at): price rows carry
#: a date-only observed_at (midnight), which silently shortened their window.
MAX_AGE_HOURS = int(os.getenv("MATERIAL_CHANGE_MAX_AGE_HOURS", "72"))

#: Route this notice through the comms gateway instead of the legacy chokepoint.
#: OFF by default. The gateway additionally requires COMMS_GATEWAY_MODE=CANARY
#: (or ACTIVE) and the message class to be in COMMS_GATEWAY_CANARY_CLASSES, so
#: three independent switches must agree before a single message changes path.
GATEWAY_NOTICE_FLAG = "MATERIAL_CHANGE_GATEWAY_NOTICE"


def gateway_notice_enabled(env: dict | None = None) -> bool:
    e = env if env is not None else os.environ
    return str(e.get(GATEWAY_NOTICE_FLAG, "")).strip().lower() in {"1", "true", "yes", "on"}


#: Ceiling on PAGES per run, so one thrashing session cannot flood the channel.
MAX_PER_RUN = int(os.getenv("MATERIAL_CHANGE_MAX_PER_RUN", "8"))
#: Rows read per run to route (pages + digest + command-center). Routing is cheap;
#: reading only MAX_PER_RUN rows ordered by magnitude starved held names.
MAX_SCAN = int(os.getenv("MATERIAL_CHANGE_MAX_SCAN", "200"))
#: A held name pages on a price move of at least this many times its normal daily
#: move. Defaults to the detector's own K, so every held price excursion pages.
PAGE_MIN_MAGNITUDE = float(os.getenv("MATERIAL_CHANGE_PAGE_MIN_MAGNITUDE", os.getenv("MATERIAL_CHANGE_K", "3.0")))
#: Page and digest chunks stay under the comms editor's footer threshold.
MAX_MESSAGE_CHARS = int(os.getenv("MATERIAL_CHANGE_MAX_MESSAGE_CHARS", "3500"))
#: An editor-held page is retried at most this many times before it falls to the digest.
MAX_HOLD_RETRIES = int(os.getenv("MATERIAL_CHANGE_MAX_HOLD_RETRIES", "3"))

ROUTE_PAGE = "PAGE"
ROUTE_DIGEST = "DIGEST"
ROUTE_CC = "COMMAND_CENTER"

#: MaterialChangeNotice@v2 is a send receipt. Its consumer is the operator, who is
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
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )


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


PENDING_COLS = [
    "change_guid",
    "symbol",
    "kind",
    "magnitude",
    "baseline",
    "observed_value",
    "observed_at",
    "universe_reason",
    "subject_guid",
    "evidence_json",
    "precedence",
    "notify_outcome",
]


def pending(cur, *, limit: int) -> list[dict]:
    """Unannounced changes, strongest claim on the operator first.

    precedence (operator 100 > held 80 > reentry 70 > preferred 60 > watchlist 40,
    material_change_detector) was never selected, so the precedence sort in
    dedupe_by_symbol ran on None and held names waited behind bigger watchlist moves.
    """
    cur.execute(
        """SELECT change_guid, symbol, kind, magnitude, baseline, observed_value,
                  observed_at, universe_reason, subject_guid, evidence_json, precedence,
                  notify_outcome
             FROM material_changes
            WHERE notified_at IS NULL
              AND COALESCE(created_at, observed_at) > now() - (%s || ' hours')::interval
            ORDER BY precedence DESC NULLS LAST, magnitude DESC NULLS LAST
            LIMIT %s""",
        (MAX_AGE_HOURS, limit),
    )
    return [dict(zip(PENDING_COLS, r)) for r in cur.fetchall()]


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

    cur.execute(
        """SELECT sentences FROM subject_state_narratives
                    WHERE change_guid = %s ORDER BY created_at DESC LIMIT 1""",
        (change["change_guid"],),
    )
    row = cur.fetchone()
    if row and row[0]:
        payload = row[0] if isinstance(row[0], list) else json.loads(row[0])
        out["narrative"] = [n.get("sentence") for n in payload if n.get("sentence")]

    cur.execute(
        """SELECT question FROM due_diligence_questions
                    WHERE change_guid = %s ORDER BY created_at LIMIT 2""",
        (change["change_guid"],),
    )
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
        cur.execute(
            """SELECT headline, catalyst_type FROM catalyst_events
                        WHERE id BETWEEN %s AND %s AND symbol = %s
                          AND headline IS NOT NULL
                        ORDER BY published_at DESC LIMIT 10""",
            (rng[0], rng[1], change["symbol"]),
        )
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
        cur.execute(
            """SELECT max(created_at)::date FROM hermes_external_research
                        WHERE subject_guid = %s""",
            (sg,),
        )
        r = cur.fetchone()
        out["last_research"] = str(r[0]) if r and r[0] else None
    return out


# Page titles that are not news: quote pages, competitor lists, "should I buy", movers roundups.
NOT_NEWS = re.compile(
    r"(?i)(stock price|price today|price and chart|stock quote|quote & history|competitors|should i buy|"
    r"stocks? to watch|trending stocks|stocks moving|top gainers|top losers|premarket movers|"
    r"stock forecast|tradingview|stock analysis|lead sub-\$1)"
)
UNTYPED = {
    "other",
    "news_momentum",
    "neutral",
    "technical",
    "stock_price_movement",
    "stock_price_increase",
    "bullish",
    "bearish",
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
    cur.execute(
        """SELECT headline, catalyst_type FROM catalyst_events
                    WHERE upper(symbol) = upper(%s) AND headline IS NOT NULL
                      AND COALESCE(published_at, created_at)
                          BETWEEN %s::timestamptz - interval '3 days' AND %s::timestamptz + interval '1 day'
                    ORDER BY COALESCE(published_at, created_at) DESC LIMIT 25""",
        (change["symbol"], change.get("observed_at"), change.get("observed_at")),
    )
    picked = pick_headline([(r[0], r[1]) for r in cur.fetchall()])
    if picked:
        out["headline"], out["headline_kind"] = picked


def _f(v) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _watch_context(cur, change: dict, out: dict) -> None:
    """The facts routing needs, read from the SAME sources the CIO entry runner uses.

    2026-09-24: the notice read its plan from watchlist_strategy_cards while the CIO
    evaluated watchlist_entry_plans, and read the latest cio_decisions row of ANY class
    — including the runner's own old BUY_READY rows (action_class='entry') — so a name
    could read "don't buy — blocked" and "CIO decision: Buy Ready" in one breath.
    Plan precedence and the decision filter now match cio_entry_state_runner.gather.
    """
    sym = str(change["symbol"]).upper()
    cur.execute(
        """SELECT price, change_pct, EXTRACT(EPOCH FROM (now() - last_enriched_at)) / 3600.0
                     FROM watchlist_items WHERE upper(symbol) = %s AND price IS NOT NULL
                    ORDER BY last_enriched_at DESC NULLS LAST LIMIT 1""",
        (sym,),
    )
    r = cur.fetchone()
    if r:
        out["price"] = _f(r[0])
        out["change_pct"] = _f(r[1])
        out["quote_age_h"] = _f(r[2])
    cur.execute("""SELECT count(*) FROM watchlist_items WHERE upper(symbol) = %s AND status = 'active'""", (sym,))
    r = cur.fetchone()
    out["on_watchlist"] = bool(r and r[0])
    cur.execute(
        """SELECT strategy_type, active FROM ticker_strategy_classifications WHERE upper(symbol) = %s
                    ORDER BY active DESC NULLS LAST LIMIT 1""",
        (sym,),
    )
    r = cur.fetchone()
    out["strategy"] = r[0] if r else None
    out["strategy_inactive"] = bool(r is None or r[1] is False)
    try:
        cur.execute(
            """SELECT state, details, evaluated_at::date,
                              EXTRACT(EPOCH FROM (now() - evaluated_at)) / 3600.0
                         FROM cio_entry_states WHERE symbol = %s
                        ORDER BY evaluated_at DESC LIMIT 1""",
            (sym,),
        )
        r = cur.fetchone()
        if r:
            d = r[1] if isinstance(r[1], dict) else json.loads(r[1] or "{}")
            out["entry_state"] = {
                "state": r[0],
                "date": str(r[2]) if r[2] else None,
                "age_h": _f(r[3]),
                **{
                    k: d.get(k)
                    for k in ("entry_low", "entry_high", "stop", "target", "rr", "distance_pct", "reasons", "price")
                },
            }
    except Exception:  # noqa: BLE001 — table absent before the entry-state lane first runs
        cur.connection.rollback()
    held = holding_for(sym)
    if held:
        out["holding"] = held
    plan = None
    cur.execute(
        """SELECT entry_zone_low, entry_zone_high, stop_price, target_price FROM watchlist_entry_plans
                    WHERE upper(symbol) = %s AND created_at > now() - interval '7 days'
                    ORDER BY created_at DESC LIMIT 1""",
        (sym,),
    )
    r = cur.fetchone()
    if r and (r[0] is not None or r[1] is not None):
        lo, hi = _f(r[0]), _f(r[1])
        plan = {
            "entry": lo if lo is not None else hi,
            "entry_high": hi,
            "stop": _f(r[2]),
            "target": _f(r[3]),
            "source": "entry_plan",
        }
    if plan is None:
        cur.execute(
            """SELECT ideal_entry, stop_loss, target_price FROM watchlist_strategy_cards
                        WHERE upper(symbol) = %s ORDER BY updated_at DESC NULLS LAST LIMIT 1""",
            (sym,),
        )
        r = cur.fetchone()
        if r and r[0] is not None:
            plan = {"entry": float(r[0]), "stop": _f(r[1]), "target": _f(r[2]), "source": "strategy_card"}
    if plan:
        out["plan"] = plan
    cur.execute(
        """SELECT action, created_at::date FROM cio_decisions
                    WHERE upper(symbol) = %s AND action_class IS DISTINCT FROM 'entry'
                    ORDER BY created_at DESC LIMIT 1""",
        (sym,),
    )
    r = cur.fetchone()
    if r:
        out["cio"] = {"action": r[0], "date": str(r[1])}
    global _ENRICHMENT
    if _ENRICHMENT is None:
        try:
            _ENRICHMENT = json.loads(
                (
                    Path(__file__).resolve().parent.parent
                    / "data"
                    / "portfolios"
                    / "state"
                    / "ticker_enrichment_cache.json"
                ).read_text()
            )
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
    rows = [
        h
        for h in (holdings.get("holdings") or [])
        if str(h.get("symbol") or "").upper() == symbol.upper() and not h.get("is_cash")
    ]
    if not rows:
        return None
    shares = sum(float(h.get("shares") or 0) for h in rows)
    cost = sum(float(h.get("cost_basis") or 0) for h in rows)
    value = sum(float(h.get("market_value") or 0) for h in rows)
    if shares <= 0:
        return None
    out = {
        "shares": shares,
        "accounts": sorted({_account_label(h.get("account")) for h in rows}),
        "cost_basis": cost or None,
        "market_value": value or None,
    }
    if cost > 0 and value > 0:
        out["avg_cost"] = cost / shares
        out["price"] = value / shares
        out["pl_usd"] = value - cost
        out["pl_pct"] = (value - cost) / cost * 100.0
    return out


def dedupe_by_symbol(changes: list[dict]) -> list[dict]:
    """One entry per SYMBOL, strongest signal wins; `guids` keeps every row it stands for.

    The 2026-09-07 queue listed AOUT twice (two news bursts hours apart) and SPCX
    twice. A name appearing repeatedly in one alert is not more informative — it is
    harder to read, and it crowds out the other names. Every collapsed row is still
    marked when the name is delivered, so no duplicate re-appears next run.
    """
    best: dict[str, dict] = {}
    for c in changes:
        sym = c["symbol"]
        cur = best.get(sym)
        guids = (cur or {}).get("guids", []) + [str(c.get("change_guid"))]
        if cur is None or (c.get("magnitude") or 0) > (cur.get("magnitude") or 0):
            c = dict(c)
            c["also"] = (cur or {}).get("also", 0) + (1 if cur else 0)
            c["guids"] = guids
            best[sym] = c
        else:
            cur["also"] = cur.get("also", 0) + 1
            cur["guids"] = guids
    return sorted(best.values(), key=lambda x: (-(x.get("precedence") or 0), -(x.get("magnitude") or 0)))


# ── facts ────────────────────────────────────────────────────────────────────


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


def max_quote_age_h() -> float:
    """The CIO entry check's own freshness bar — one definition of 'fresh'."""
    try:
        from lib.cio_entry_state import MAX_QUOTE_AGE_H
    except ImportError:  # imported as scripts.notify_material_change
        from scripts.lib.cio_entry_state import MAX_QUOTE_AGE_H
    return float(MAX_QUOTE_AGE_H)


def quote_is_fresh(info: dict) -> bool:
    age = info.get("quote_age_h")
    return info.get("price") is not None and age is not None and float(age) <= max_quote_age_h()


def _age_text(hours: float | None) -> str:
    if hours is None:
        return "age unknown"
    h = float(hours)
    if h < 1:
        return f"{max(1, round(h * 60))}m"
    if h < 48:
        return f"{h:.1f}h" if h < 10 else f"{h:.0f}h"
    return f"{h / 24:.1f}d"


def plan_levels(plan: dict | None, price: float | None) -> dict:
    """Where price sits inside the plan's own levels: hit_stop / hit_target / progress.

    Direction comes from the plan's own geometry (target below entry = short), so a
    won plan and a blown plan can never share a sentence (2026-09-21 HPE).
    """
    out = {"hit_stop": False, "hit_target": False, "dist_pct": None}
    if not plan or price is None or not plan.get("entry"):
        return out
    entry = float(plan["entry"])
    if entry <= 0:
        return out
    target, stop = _f(plan.get("target")), _f(plan.get("stop"))
    short = target is not None and target < entry
    out["hit_stop"] = stop is not None and (price >= stop if short else price <= stop)
    out["hit_target"] = target is not None and (price <= target if short else price >= target)
    out["dist_pct"] = (price - entry) / entry * 100.0
    return out


#: Most conservative first. A verdict lower in this order wins a disagreement.
_CONSERVATISM = [
    ({"AVOID", "SELL", "EXIT", "TRIM", "TRIM_REVIEW", "REDUCE", "HOLD_REDUCE"}, 0),
    ({"BLOCKED"}, 1),
    ({"HOLD", "WAIT", "RESEARCH_MORE", "HUMAN_REVIEW", "ADD_REVIEW", "NEUTRAL", "WATCH", "NO_GO"}, 2),
    ({"ENTRY_NEAR"}, 3),
    ({"BUY_READY", "BUY", "ADD", "ACCUMULATE", "ADD_ON_PULLBACK", "INITIATE", "GO"}, 4),
]


def _rank(action: str | None) -> int:
    a = str(action or "").upper()
    for names, rank in _CONSERVATISM:
        if a in names:
            return rank
    return 2


def _pretty(action: str | None) -> str:
    return str(action or "").replace("_", " ").upper()


def cio_verdict(info: dict) -> dict:
    """ONE CIO verdict: today's entry check reconciled with the latest CIO decision.

    The more conservative of the two is shown; when they disagree the other is named
    as superseded, with its date. Never both raw, side by side.
    """
    es, dec = info.get("entry_state") or {}, info.get("cio") or {}
    es_state, dec_action = es.get("state"), dec.get("action")
    if not es_state and not dec_action:
        return {"state": None, "text": "no stance on file", "rank": 2}
    if es_state == "BLOCKED":
        reasons = [str(x) for x in (es.get("reasons") or []) if x]
        es_text = "HOLD-OFF" + (f" ({reasons[0]})" if reasons else "")
    elif es_state == "BUY_READY":
        lo, hi = _f(es.get("entry_low")), _f(es.get("entry_high"))
        zone = (
            (f" (zone ${lo:,.2f}" + (f"–${hi:,.2f}" if hi is not None and hi != lo else "") + ")")
            if lo is not None
            else ""
        )
        es_text = "BUY READY" + zone
    elif es_state == "ENTRY_NEAR":
        d = _f(es.get("distance_pct"))
        es_text = "NEAR ENTRY" + (f" ({abs(d):.1f}% away)" if d is not None else "")
    elif es_state:
        es_text = _pretty(es_state)
    else:
        es_text = None
    # An entry state older than the freshness bar is shown WITH its age: on 2026-09-24
    # the digest paired a 32m quote with "HOLD-OFF (quote is 16.7h old)". The runner
    # writes a row only when the state CHANGES, so the age is how long the state has
    # stood — "state set", not "checked".
    es_age = _f(es.get("age_h"))
    if es_text and es_age is not None and es_age > max_quote_age_h():
        es_text += f" [state set {_age_text(es_age)} ago]"
    dec_text = f"{_pretty(dec_action)} ({dec.get('date')})" if dec_action else None
    if es_text and dec_text:
        if _rank(es_state) <= _rank(dec_action):
            same = _rank(es_state) == _rank(dec_action)
            note = "" if same else f" · decision {dec_text} superseded by the entry check"
            return {"state": es_state, "text": es_text + note, "rank": _rank(es_state)}
        return {
            "state": dec_action,
            "text": f"{_pretty(dec_action)} ({dec.get('date')}) · entry check {es_text} overridden",
            "rank": _rank(dec_action),
        }
    if es_text:
        return {"state": es_state, "text": es_text, "rank": _rank(es_state)}
    return {"state": dec_action, "text": dec_text, "rank": _rank(dec_action)}


def classify(c: dict, info: dict) -> dict:
    """Route one change to PAGE, DIGEST or COMMAND_CENTER on its structured facts.

    Operator decisions 2026-09-24: page only a HELD name (stop / target hit, or a
    material price move) or a watchlist name the CIO rates BUY_READY on a fresh quote.
    A watchlist name through its plan stop is PLAN INVALIDATED in the digest. Stale
    quotes, and inactive strategies with no plan, go to the Command Center only.
    """
    held = bool(info.get("holding"))
    fresh = quote_is_fresh(info)
    price = info.get("price")
    lv = plan_levels(info.get("plan"), price if fresh else None)
    verdict = cio_verdict(info)
    kind = c.get("kind")
    out = {"held": held, "fresh": fresh, "levels": lv, "verdict": verdict}
    if not fresh:
        out.update(
            route=ROUTE_CC if not held else ROUTE_DIGEST,
            state="STALE_QUOTE",
            why=f"quote {_age_text(info.get('quote_age_h'))} old",
        )
        return out
    if held:
        if lv["hit_stop"]:
            return {**out, "route": ROUTE_PAGE, "state": "STOP_HIT"}
        if lv["hit_target"]:
            return {**out, "route": ROUTE_PAGE, "state": "TARGET_HIT"}
        if kind == "price_excursion" and float(c.get("magnitude") or 0) >= PAGE_MIN_MAGNITUDE:
            return {**out, "route": ROUTE_PAGE, "state": "BIG_MOVE"}
        return {**out, "route": ROUTE_DIGEST, "state": "HELD_NEWS"}
    if lv["hit_stop"]:
        return {**out, "route": ROUTE_DIGEST, "state": "PLAN_INVALIDATED"}
    if verdict["state"] == "BUY_READY":
        return {**out, "route": ROUTE_PAGE, "state": "BUY_READY"}
    if info.get("strategy_inactive") and not info.get("plan"):
        return {**out, "route": ROUTE_CC, "state": "NO_PLAN", "why": "inactive strategy, no plan"}
    if lv["hit_target"]:
        return {**out, "route": ROUTE_DIGEST, "state": "TARGET_PASSED"}
    return {**out, "route": ROUTE_DIGEST, "state": "MOVE"}


# ── wording ──────────────────────────────────────────────────────────────────

#: Every notice carries "Material change" — the marker operator_alert_policy_v2 routes
#: IMMEDIATE and telegram_alert_router exempts from the daily send budget. Without it a
#: page reads as generic text and falls to the digest.
PAGE_FOOTER = "Material change · Advisory only. No position action taken or implied."

_PAGE_HEAD = {
    "STOP_HIT": ("🚨", "STOP HIT"),
    "TARGET_HIT": ("🎯", "TARGET HIT"),
    "BIG_MOVE": ("⚡", "BIG MOVE"),
    "BUY_READY": ("🟢", "BUY READY"),
}
_ACTION = {
    "STOP_HIT": "review exit — price is through your plan stop",
    "TARGET_HIT": "review taking profit — price is at or through your plan target",
    "BIG_MOVE": "review the position",
    "BUY_READY": "review entry — the CIO entry check is green on a fresh quote",
    "PLAN_INVALIDATED": "re-plan or drop",
}


def _money(v: float | None) -> str:
    return f"${float(v):,.2f}" if v is not None else "—"


def _move_text(c: dict, info: dict) -> str | None:
    """'−6.1% today (3.4× its normal daily move)' — or the news equivalent."""
    kind = c.get("kind")
    mag = _f(c.get("magnitude")) or 0.0
    if kind == "price_excursion":
        signed = _signed_move(c, info)
        size = abs(float(c.get("observed_value") or 0))
        move = f"{signed:+.1f}%" if signed is not None else f"{size:.1f}% move"
        return f"{move} ({mag:.1f}× its normal daily move)"
    if kind == "news_burst":
        return f"unusual news volume ({mag:.0f}× normal)"
    if kind == "sector_move":
        return "sector-wide move"
    ev = c.get("evidence") or c.get("evidence_json") or {}
    if isinstance(ev, str):
        try:
            ev = json.loads(ev)
        except Exception:  # noqa: BLE001
            ev = {}
    ctype = str((ev or {}).get("catalyst_type") or "").replace("_", " ")
    return ctype or "new catalyst"


def _what_text(info: dict) -> str:
    if info.get("narrative"):
        return str(info["narrative"][0])[:160]
    if info.get("headline"):
        prefix = "catalyst: " if info.get("headline_kind") == "catalyst" else "news near the move (cause unconfirmed): "
        return prefix + str(info["headline"])[:140]
    return "no news explains the move"


def _position_text(info: dict) -> str | None:
    h = info.get("holding")
    if not h:
        return None
    shares = f"{h['shares']:,.0f}" if float(h["shares"]).is_integer() else f"{h['shares']:,.3f}"
    return f"held, {shares} sh"


def page_lines(c: dict, info: dict, route: dict) -> list[str]:
    """A PAGE: the point in line 1 (phone preview), at most three more lines, one action."""
    sym = str(c["symbol"]).upper()
    icon, verb = _PAGE_HEAD[route["state"]]
    who = _position_text(info) or "watchlist, not held"
    lines = [f"{icon} {verb} — {sym} ({who})"]
    price_bits = [f"{_money(info.get('price'))} · quote {_age_text(info.get('quote_age_h'))}"]
    move = _move_text(c, info)
    if move:
        price_bits.append(move)
    h = info.get("holding") or {}
    if h.get("pl_usd") is not None:
        sign = "+" if h["pl_usd"] >= 0 else "-"
        price_bits.append(f"position {sign}${abs(h['pl_usd']):,.0f} ({h['pl_pct']:+.1f}%)")
    lines.append(" · ".join(price_bits))
    plan = info.get("plan") or {}
    lv = route.get("levels") or {}
    if route["state"] == "STOP_HIT" and plan.get("stop") is not None:
        lines[-1] += f" · stop {_money(plan['stop'])}"
    elif route["state"] == "TARGET_HIT" and plan.get("target") is not None:
        lines[-1] += f" · target {_money(plan['target'])}"
    elif plan.get("stop") is not None and lv.get("dist_pct") is not None:
        lines[-1] += f" · stop {_money(plan['stop'])}"
    lines.append(f"CIO: {route['verdict']['text']} · {_what_text(info)}")
    lines.append(f"▶ Action: {_ACTION[route['state']]}")
    return lines


def digest_line(c: dict, info: dict, route: dict) -> str:
    """One compact line per name in the daily digest."""
    sym = str(c["symbol"]).upper()
    bits = [f"{sym} {_money(info.get('price'))} ({_age_text(info.get('quote_age_h'))})"]
    move = _move_text(c, info)
    if move:
        bits.append(move)
    plan = info.get("plan") or {}
    if route["state"] == "PLAN_INVALIDATED" and plan.get("stop") is not None:
        bits.append(f"stop {_money(plan['stop'])}")
    if route["state"] == "TARGET_PASSED" and plan.get("target") is not None:
        bits.append(f"target {_money(plan['target'])} passed")
    if route.get("held"):
        bits.append(_position_text(info) or "held")
    bits.append(f"CIO: {route['verdict']['text']}")
    return "  " + " · ".join(bits)


_DIGEST_SECTIONS = [
    ("PLAN_INVALIDATED", "⛔ PLAN INVALIDATED (watchlist, not held) — re-plan or drop"),
    ("HELD_NEWS", "📌 Held — news / catalysts (no stop or target hit)"),
    ("STALE_QUOTE", "⏳ Held — quote too old to judge"),
    ("TARGET_PASSED", "🎯 Watchlist — already through the plan target (not held)"),
    ("MOVE", "📈 Other moves on your watchlist"),
]


def digest_blocks(entries: list[tuple[dict, dict, dict]], *, now: datetime | None = None) -> list[dict]:
    """The daily digest as ticker-boundary blocks: [{"text", "guids"}].

    A block is a header or one name; chunking (split_digest) never cuts inside one.
    COMMAND_CENTER entries are named in one "not shown" line, never detailed.
    """
    now = (now or datetime.now(timezone.utc)).astimezone(MARKET_TZ)
    blocks: list[dict] = [{"text": f"📋 Material change — daily digest · {now:%a %d %b · %H:%M} ET", "guids": []}]
    for state, title in _DIGEST_SECTIONS:
        rows = [(c, i, r) for c, i, r in entries if r["route"] == ROUTE_DIGEST and r["state"] == state]
        if not rows:
            continue
        blocks.append({"text": "\n" + title, "guids": []})
        for c, info, route in rows:
            blocks.append({"text": digest_line(c, info, route), "guids": list(c.get("guids") or [c["change_guid"]])})
    hidden = [(c, i, r) for c, i, r in entries if r["route"] == ROUTE_CC]
    if hidden:
        names = ", ".join(f"{str(c['symbol']).upper()} ({r.get('why') or r['state'].lower()})" for c, _i, r in hidden)
        blocks.append(
            {
                "text": f"\n🔕 Not shown: {names} → Command Center",
                "guids": [g for c, _i, _r in hidden for g in (c.get("guids") or [c["change_guid"]])],
            }
        )
    return blocks


def split_digest(blocks: list[dict], *, limit: int | None = None) -> list[dict]:
    """Chunks of whole blocks under `limit` chars, each carrying the guids it announces."""
    limit = limit or MAX_MESSAGE_CHARS
    footer = _digest_footer()
    chunks: list[dict] = []
    cur_text, cur_guids = "", []
    for b in blocks:
        piece = b["text"] if not cur_text else "\n" + b["text"]
        if cur_text and len(cur_text) + len(piece) + len(footer) + 1 > limit:
            chunks.append({"text": cur_text + "\n" + footer, "guids": cur_guids})
            cur_text, cur_guids = b["text"].lstrip("\n"), list(b["guids"])
            continue
        cur_text += piece
        cur_guids += list(b["guids"])
    if cur_text:
        chunks.append({"text": cur_text + "\n" + footer, "guids": cur_guids})
    return chunks


def _cc_watch_url() -> str:
    try:
        from scripts.lib import telegram_rich as tr
    except ImportError:  # pragma: no cover - scripts/ on path
        from lib import telegram_rich as tr  # type: ignore
    return f"{tr.cc_base()}/v3/watch/intelligence"


def _digest_footer() -> str:
    return f"Details → Command Center {_cc_watch_url()} · Advisory only."


def render(changes: list[dict], ctx: dict[str, dict]) -> str:
    """Plain text of the PAGE(s) for `changes` — what the router check and the outbound
    turn capture read. Names that do not route to a page render nothing here."""
    parts: list[str] = []
    for c in dedupe_by_symbol(changes):
        info = ctx.get(str(c["change_guid"]), {})
        route = classify(c, info)
        if route["route"] != ROUTE_PAGE:
            continue
        parts.append("\n".join(page_lines(c, info, route)))
    if not parts:
        return ""
    return "\n\n".join(parts) + "\n" + PAGE_FOOTER


def rich_enabled(env: dict | None = None) -> bool:
    e = env if env is not None else os.environ
    return str(e.get("TELEGRAM_RICH_ALERTS", "1")).strip().lower() not in {"0", "false", "off", "no"}


def render_rich(changes: list[dict], ctx: dict[str, dict]) -> dict:
    """The same PAGE in Telegram HTML: bold first line, one Command Center link, one footer.

    Operator 2026-09-24 review: per-ticker Finviz / Yahoo links, provenance, sector and
    thesis competed with the one thing that mattered. They live in the Command Center.
    """
    try:
        from scripts.lib import telegram_rich as tr
    except ImportError:  # pragma: no cover - scripts/ on path
        from lib import telegram_rich as tr  # type: ignore
    out: list[str] = []
    symbols: list[str] = []
    for c in dedupe_by_symbol(changes):
        info = ctx.get(str(c["change_guid"]), {})
        route = classify(c, info)
        if route["route"] != ROUTE_PAGE:
            continue
        sym = str(c["symbol"]).upper()
        symbols.append(sym)
        lines = page_lines(c, info, route)
        if out:
            out.append("")
        out.append(f"<b>{tr.esc(lines[0])}</b>")
        out.extend(tr.esc(x) for x in lines[1:])
        out.append(f"Details → {tr.link('Command Center', tr.cc_symbol_url(sym))}")
    if not out:
        return {"text": "", "reply_markup": None, "link_preview_options": {"is_disabled": True}}
    out.append(f"<i>{PAGE_FOOTER}</i>")
    return {
        "text": "\n".join(out),
        "reply_markup": None,
        "link_preview_options": (
            {"url": tr.chart_image_url(symbols[0]), "prefer_large_media": True, "show_above_text": False}
            if len(symbols) == 1
            else {"is_disabled": True}
        ),
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

    Asked PER PAGE (one name), on text that carries no thesis prose: on 2026-09-22..24
    one name's thesis ("RCL paper proposal for …") matched a dashboard-only rule and
    held an eight-name batch for 179 runs.
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
        {
            "symbol": r.get("symbol"),
            "subject_guid": str(r["subject_guid"]) if r.get("subject_guid") else None,
            "issuer_guid": None,
            # The subject is carried by the alert itself, not inferred from prose.
            "identity_status": "CONFIRMED" if r.get("subject_guid") else None,
            "matched_via": "material_change",
            "matched_text": r.get("symbol"),
        }
        for r in rows
        if r.get("subject_guid")
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
            conn=conn,
            text=message,
            role="agent",
            chat_id=chat,
            message_id=mid,
            thread_id=mid,
            channel="telegram",
        )
    return written


def notice_key(guids: list[str]) -> str:
    """Idempotency subject for ONE notice: the exact set of changes it announces.

    It used to be the first row's subject_guid, so an unrelated later batch that
    happened to lead with the same name reused a 09-14 event id and the ledger
    counted 16 notices for 28 real batches.
    """
    joined = ",".join(sorted(str(g) for g in guids))
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "material_change_notice:" + hashlib.sha256(joined.encode()).hexdigest()))


def _held_chunks() -> list[dict]:
    try:
        from telegram_alert import last_held_chunks
    except ImportError:  # pragma: no cover - scripts/ not on path
        try:
            from scripts.telegram_alert import last_held_chunks  # type: ignore
        except ImportError:
            return []
    return list(last_held_chunks() or [])


def deliver_notice(message: str, *, subject_key: str, rich: dict | None = None) -> tuple[bool, dict]:
    """Send one operator notice. Returns (delivered, report).

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

    HELD IS NOT DELIVERED (2026-09-24). The comms editor can hold a message (a stance
    disagreement, a duplicate) and the transport still reports ok. On 09-24 12:22 the
    MDT/PSQL/VVX/ROL chunk was held and all eight rows were marked SENT anyway. A notice
    with any held chunk is reported NOT delivered, so its rows stay pending.
    """
    # `rich` (render_rich) replaces the body and adds buttons + chart; `message` is the plain fallback.
    extra: dict = {}
    if rich and rich.get("text"):
        message = rich["text"]
        extra = {"reply_markup": rich.get("reply_markup"), "link_preview_options": rich.get("link_preview_options")}
    if not gateway_notice_enabled():
        from telegram_alert import send_telegram

        accepted = bool(send_telegram(message, message_class="operator_alert", **extra))
        held = _held_chunks() if accepted else []
        report = {"attempted": False, "held": held}
        return accepted and not held, report

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
    held = list(((gw.get("provider_coordinates") or {}).get("held")) or [])
    accepted = bool(gw.get("delivered")) and not held
    report = {
        "attempted": True,
        "delivered": accepted,
        "delivery_owned": bool(gw.get("delivery_owned")),
        "gateway_mode": gw.get("gateway_mode"),
        "event_id": gw.get("event_id"),
        "delivery_id": gw.get("delivery_id"),
        "provider_coordinates": gw.get("provider_coordinates"),
        "provider_message_id": gw.get("provider_message_id"),
        "held": held,
        "errors": gw.get("errors") or ([gw["error"]] if gw.get("error") else []),
    }
    if not accepted:
        # Do NOT silently fall back to legacy. A gateway failure that quietly
        # succeeded as legacy would report SENT, consume the rows, and leave the
        # gateway counter at zero with nothing to explain why.
        print(
            f"notice not delivered (held={held}, errors={report['errors']}) — changes left pending, no legacy fallback",
            file=sys.stderr,
        )
    return accepted, report


def _hold_count(outcome: str | None) -> int:
    m = re.match(r"^HELD_BY_EDITOR:(\d+)", str(outcome or ""))
    return int(m.group(1)) if m else 0


def _mark(cur, guids: list[str], outcome: str) -> int:
    cur.execute(
        """UPDATE material_changes
                      SET notified_at = now(), notify_outcome = %s
                    WHERE change_guid = ANY(%s::uuid[]) AND notified_at IS NULL""",
        (outcome, [str(g) for g in guids]),
    )
    return cur.rowcount


def _note(cur, guids: list[str], outcome: str) -> None:
    """Record where a still-pending change stands, without consuming it."""
    cur.execute(
        """UPDATE material_changes SET notify_outcome = %s
                    WHERE change_guid = ANY(%s::uuid[]) AND notified_at IS NULL
                      AND notify_outcome IS DISTINCT FROM %s""",
        (outcome, [str(g) for g in guids], outcome),
    )


def route_all(cur, rows: list[dict]) -> list[tuple[dict, dict, dict]]:
    """(change, info, route) per SYMBOL, strongest claim first."""
    ctx = {str(r["change_guid"]): context(cur, r) for r in rows}
    out = []
    for c in dedupe_by_symbol(rows):
        info = ctx.get(str(c["change_guid"]), {})
        route = classify(c, info)
        if route["route"] == ROUTE_PAGE and _hold_count(c.get("notify_outcome")) >= MAX_HOLD_RETRIES:
            # A page the editor keeps holding falls to the digest rather than retrying forever.
            route = {
                **route,
                "route": ROUTE_DIGEST,
                "state": "HELD_NEWS" if route["held"] else "MOVE",
                "why": "page held by the comms editor",
            }
        out.append((c, info, route))
    return out


def run_pages(cur, conn, entries: list[tuple[dict, dict, dict]], *, apply: bool, result: dict) -> None:
    pages = [e for e in entries if e[2]["route"] == ROUTE_PAGE][:MAX_PER_RUN]
    result["pages"] = len(pages)
    result["page_outcomes"] = {}
    sent_rows = 0
    for c, info, route in pages:
        sym = str(c["symbol"]).upper()
        guids = list(c.get("guids") or [c["change_guid"]])
        one = {str(c["change_guid"]): info}
        message = render([c], one)
        print(message)
        if not apply:
            continue
        if route_check(message) == "WOULD_SUPPRESS":
            # Do not send into a suppression, and above all do not consume the change.
            # On the first live run the send was ACCEPTED, the router suppressed it into
            # the 8pm digest, and three changes were marked notified while the operator
            # received nothing. Consumed-and-silent is the worst outcome available here.
            result["page_outcomes"][sym] = "WOULD_SUPPRESS"
            _note(cur, guids, "WOULD_SUPPRESS")
            conn.commit()
            continue
        rich = None
        if rich_enabled():
            try:
                rich = render_rich([c], one)
            except Exception as exc:  # noqa: BLE001 -- formatting must never cost the notice
                print(f"[rich] layout unavailable ({type(exc).__name__}: {exc}); sending plain text", file=sys.stderr)
        accepted, gw_result = deliver_notice(message, subject_key=notice_key(guids), rich=rich)
        if accepted:
            sent_rows += _mark(cur, guids, "SENT")
            conn.commit()
            result["page_outcomes"][sym] = "SENT"
            try:
                result.setdefault("agent_turns", 0)
                result["agent_turns"] += capture_agent_turns(conn, message=message, rows=[c], gw=gw_result)
            except Exception as exc:  # noqa: BLE001
                print(f"[outbound-tag] {type(exc).__name__}: {str(exc)[:160]}", file=sys.stderr)
        else:
            held = gw_result.get("held") or []
            outcome = (
                (
                    f"HELD_BY_EDITOR:{_hold_count(c.get('notify_outcome')) + 1}:"
                    f"{(held[0] or {}).get('reason') if held else ''}"
                )
                if held
                else "NOT_ACCEPTED"
            )
            _note(cur, guids, outcome[:200])
            conn.commit()
            result["page_outcomes"][sym] = outcome
    result["rows_produced"] = sent_rows if apply else None


def run_digest(cur, conn, entries: list[tuple[dict, dict, dict]], *, apply: bool, result: dict) -> None:
    listed = [e for e in entries if e[2]["route"] in (ROUTE_DIGEST, ROUTE_CC)]
    result["digest_names"] = len(listed)
    if not listed:
        result["rows_produced"] = 0 if apply else None
        print(f"{SCHEMA}: nothing for the digest")
        return
    chunks = split_digest(digest_blocks(listed))
    sent_rows = 0
    result["digest_chunks"] = len(chunks)
    for i, ch in enumerate(chunks):
        print(ch["text"])
        if not apply:
            continue
        accepted, _gw = deliver_notice(ch["text"], subject_key=notice_key(ch["guids"] or [f"digest-header-{i}"]))
        if accepted:
            sent_rows += _mark(cur, ch["guids"], "DIGEST_SENT")
        else:
            _note(cur, ch["guids"], "DIGEST_NOT_DELIVERED")
        conn.commit()
    result["rows_produced"] = sent_rows if apply else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--digest", action="store_true", help="send the once-a-day digest of everything that did not page")
    ap.add_argument(
        "--ignore-window", action="store_true", help="operator-run only; scheduled jobs must respect the window"
    )
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

    open_now = args.ignore_window or args.digest or in_window()
    rows = pending(cur, limit=MAX_SCAN)

    result = {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "model_calls": 0,
        "mode": "digest" if args.digest else "pages",
        "pending": len(rows),
        "in_window": open_now,
        # None when nothing was attempted; 0 is a measured zero.
        "rows_produced": None,
        "outcome": None,
    }

    if not rows:
        result["rows_produced"] = 0 if args.apply else None
        print(f"{SCHEMA}: nothing pending")
        print("RESULT: " + json.dumps(result))
        return 0

    entries = route_all(cur, rows)
    conn.commit()
    result["routes"] = {k: sum(1 for e in entries if e[2]["route"] == k) for k in (ROUTE_PAGE, ROUTE_DIGEST, ROUTE_CC)}
    if not open_now:
        # Held, not dropped. A Friday-evening move must still be announced Monday.
        print(f"\n[held — outside the {NOTIFY_WINDOW} window; stays pending]")
        result["outcome"] = "HELD_OUTSIDE_WINDOW"
        print("RESULT: " + json.dumps(result))
        return 0
    if args.digest:
        run_digest(cur, conn, entries, apply=args.apply, result=result)
    else:
        run_pages(cur, conn, entries, apply=args.apply, result=result)
    if not args.apply:
        print("\n[dry run — nothing sent, nothing marked]")
        result["rows_produced"] = None
    result["outcome"] = "DONE" if args.apply else "DRY_RUN"
    conn.close()
    print("RESULT: " + json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
