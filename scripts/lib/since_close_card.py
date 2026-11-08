"""LQ-20261107-1253 — the "Since last close" home card: a snapshot builder.

The card covers the window from the last regular-session close (16:00 ET, 13:00 on an early close) to now,
so it is the weekday-overnight, weekend and holiday recap.  It is built by a producer (scripts/since_close_snapshot.py,
scheduled by n8n) into one snapshot file; the API route only reads that file, never a request-thread LLM call.

Four parts, each degrading to a visible state rather than an empty card:
  moves    every held and watchlist name from ticker_snapshot_latest.json (last-session %, week %), held names
           sorted by $ impact
  news     news_articles since the close, is_duplicate false, top 3 per name by relevance_score; a big mover with
           none is flagged ``no_news``
  macro    market/overseas headlines + the futures/overseas quotes file when it exists, else status ``pending``
  summary  4-6 sentences from the three parts above, via an injected LLM callable, cached 15 minutes under a daily
           cap; if the LLM is unavailable the deterministic list stands and ``summary.source`` says so

Pure functions take ``now`` and the data; nothing here reads the clock, the DB or the network on its own.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

try:
    from lib.market_risk import sessions
except ImportError:  # pragma: no cover - imported as scripts.lib
    from scripts.lib.market_risk import sessions

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

SCHEMA = "since_close_card.v1"
SUMMARY_TTL = timedelta(minutes=15)
SUMMARY_DAILY_CAP = 40  # n8n runs ~12/night + weekends; flash is ~$0.0005 a call
BIG_MOVE_PCT = 3.0
NEWS_PER_NAME = 3
MACRO_LIMIT = 6

# a headline is macro when its title says so; the symbol column on these rows is junk (AHEAD, WATER ...)
MACRO_RE = re.compile(
    r"\b(futures|fed(?:eral reserve)?|fomc|powell|cpi|ppi|inflation|jobs report|payrolls|treasur(?:y|ies)|yields?|"
    r"nikkei|kospi|hang seng|shanghai|asia(?:n)? (?:markets?|stocks?)|european (?:markets?|stocks?)|europe stocks|"
    r"ftse|dax|stoxx|wall street (?:swoons?|rall(?:y|ies)|slumps?|ends?|closes?)|stock market|s&p 500|nasdaq|dow|"
    r"oil prices?|crude|dollar|week ahead|market plunge|collateral)\b",
    re.I,
)
# a brokerage-rating story about one company is not a macro headline even though it says "Wall Street Zen"
NOT_MACRO_RE = re.compile(r"\(NYSE:|\(NASDAQ:|Wall Street Zen|Wall Street Brokerages|marketbeat", re.I)


# ---------------------------------------------------------------------------- the window


def window(now: datetime) -> dict[str, Any]:
    """The last regular-session close at or before ``now`` and the label for it."""
    now_et = now.astimezone(ET)
    day = sessions.last_closed_session(now)
    cl = sessions.close_time(day)
    start = datetime.combine(day, cl, ET)
    open_now = _session_open(now_et)
    label_time = start.strftime("%-I:%M %p")
    return {
        "start": start.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "start_et": start.isoformat(),
        "session_date": day.isoformat(),
        "label": f"Since {start.strftime('%a')} {label_time}",
        "close_tag": f"{start.strftime('%a')} close",
        # 09:30-16:00 on a trading day the card shrinks to one line (it is not removed)
        "session_open": open_now,
    }


def _session_open(now_et: datetime) -> bool:
    d = now_et.date()
    if not sessions.is_trading_day(d):
        return False
    t = now_et.time()
    return time(9, 30) <= t < sessions.close_time(d)


# ---------------------------------------------------------------------------- moves


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def build_moves(snapshot: Mapping[str, Any], *, close_tag: str) -> list[dict[str, Any]]:
    """Held names first (largest $ impact first), then the watchlist (largest absolute move first)."""
    rows: list[dict[str, Any]] = []
    for sym, rec in (snapshot.get("tickers") or {}).items():
        if not isinstance(rec, Mapping):
            continue
        q = rec.get("quote") or {}
        price, pct = _num(q.get("price")), _num(q.get("change_pct"))
        if price is None or pct is None or price <= 0:
            continue
        hc = rec.get("holdings_context") or {}
        shares = _num(hc.get("shares_total")) or 0.0
        mv = _num(hc.get("market_value_total")) or 0.0
        held = shares > 0 and mv > 0
        impact = None
        if held and pct > -100:
            # market value is at the last price: the day's $ change is mv - mv / (1 + pct)
            impact = round(mv - mv / (1.0 + pct / 100.0), 2)
        perf = rec.get("performance") or {}
        rows.append(
            {
                "symbol": str(sym).upper(),
                "held": held,
                "price": price,
                "change_pct": round(pct, 2),
                "week_pct": _num(perf.get("perf_week")),
                "dollar_impact": impact,
                "market_value": round(mv, 2) if held else None,
                "close_tag": close_tag,
                "big_move": abs(pct) >= BIG_MOVE_PCT,
            }
        )
    held_rows = sorted((r for r in rows if r["held"]), key=lambda r: -abs(r["dollar_impact"] or 0.0))
    watch_rows = sorted((r for r in rows if not r["held"]), key=lambda r: -abs(r["change_pct"]))
    return held_rows + watch_rows


# ---------------------------------------------------------------------------- news


def attach_news(
    moves: list[dict[str, Any]], articles: Iterable[Mapping[str, Any]], *, per_name: int = NEWS_PER_NAME
) -> list[dict[str, Any]]:
    """Top ``per_name`` articles per symbol by relevance_score (newest breaks ties); flag a big mover with none."""
    by_sym: dict[str, list[Mapping[str, Any]]] = {}
    for a in articles:
        by_sym.setdefault(str(a.get("symbol") or "").upper(), []).append(a)
    out = []
    for m in moves:
        picked = sorted(
            by_sym.get(m["symbol"], []),
            key=lambda a: (-(_num(a.get("relevance_score")) or 0.0), -_ts(a.get("published_at"))),
        )
        seen: set[str] = set()
        news = []
        for a in picked:
            key = re.sub(r"\W+", " ", str(a.get("title") or "").lower()).strip()
            if not key or key in seen:
                continue
            seen.add(key)
            news.append(
                {
                    "title": str(a.get("title") or ""),
                    "source": str(a.get("source") or ""),
                    "url": a.get("source_url") or None,
                    "published_at": _iso(a.get("published_at")),
                    "relevance": _num(a.get("relevance_score")),
                }
            )
            if len(news) >= per_name:
                break
        out.append({**m, "news": news, "no_news": bool(m["big_move"] and not news)})
    return out


def _ts(v: Any) -> float:
    if isinstance(v, datetime):
        return v.timestamp()
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _iso(v: Any) -> str | None:
    if isinstance(v, datetime):
        return v.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return str(v) if v else None


# ---------------------------------------------------------------------------- macro


def build_macro(
    articles: Iterable[Mapping[str, Any]], futures: Mapping[str, Any] | None, *, limit: int = MACRO_LIMIT
) -> dict[str, Any]:
    """Top macro headlines and the futures/overseas block (``status: pending`` until the quotes file exists)."""
    heads, seen = [], set()
    for a in sorted(articles, key=lambda a: (-_ts(a.get("published_at")), -(_num(a.get("relevance_score")) or 0.0))):
        title = str(a.get("title") or "")
        if not MACRO_RE.search(title) or NOT_MACRO_RE.search(title) or NOT_MACRO_RE.search(str(a.get("source") or "")):
            continue
        key = re.sub(r"\W+", " ", title.lower()).strip()
        if key in seen:
            continue
        seen.add(key)
        heads.append(
            {
                "title": title,
                "source": str(a.get("source") or ""),
                "url": a.get("source_url") or None,
                "published_at": _iso(a.get("published_at")),
            }
        )
        if len(heads) >= limit:
            break
    quotes = (futures or {}).get("quotes") if isinstance(futures, Mapping) else None
    if quotes:
        fut = {"status": "available", "quotes": quotes, "as_of": futures.get("as_of")}  # type: ignore[union-attr]
    else:
        fut = {"status": "pending", "label": "futures feed pending", "quotes": []}
    return {"headlines": heads, "futures": fut}


# ---------------------------------------------------------------------------- summary


def deterministic_lines(moves: Sequence[Mapping[str, Any]], macro: Mapping[str, Any]) -> list[str]:
    """What the card shows when no LLM summary exists: facts only, from the same three parts."""
    lines = []
    held = [m for m in moves if m["held"]][:3]
    for m in held:
        lines.append(f"{m['symbol']} {m['change_pct']:+.1f}% ({m['close_tag']})" + (" — no news" if m.get("no_news") else ""))
    for m in [m for m in moves if not m["held"] and m["big_move"]][:2]:
        lines.append(f"Watchlist {m['symbol']} {m['change_pct']:+.1f}%" + (" — no news" if m.get("no_news") else ""))
    for h in (macro.get("headlines") or [])[:1]:
        lines.append(h["title"])
    return lines


def summary_input(moves: Sequence[Mapping[str, Any]], macro: Mapping[str, Any]) -> dict[str, Any]:
    """The only facts the LLM sees (items 1-3), trimmed; also the cache key's source."""
    return {
        "moves": [
            {k: m.get(k) for k in ("symbol", "held", "change_pct", "week_pct", "dollar_impact", "no_news")}
            | {"headlines": [n["title"] for n in m.get("news", [])[:2]]}
            for m in moves
            if m["held"] or m["big_move"]
        ][:14],
        "macro": [h["title"] for h in macro.get("headlines", [])[:5]],
        "futures": macro.get("futures", {}).get("status"),
    }


def input_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:16]


def build_summary(
    moves: Sequence[Mapping[str, Any]],
    macro: Mapping[str, Any],
    *,
    now: datetime,
    llm: Callable[[str], str] | None,
    prior: Mapping[str, Any] | None = None,
    calls_today: int = 0,
    daily_cap: int = SUMMARY_DAILY_CAP,
    carry_prior: bool = False,
) -> dict[str, Any]:
    """Cached 15 min per input hash; over the cap or on any LLM failure it returns the deterministic list."""
    payload = summary_input(moves, macro)
    h = input_hash(payload)
    now_utc = now.astimezone(UTC)
    base = {"input_hash": h, "lines": deterministic_lines(moves, macro)}
    if prior and prior.get("input_hash") == h and prior.get("text") and prior.get("generated_at"):
        if now_utc - datetime.fromisoformat(str(prior["generated_at"]).replace("Z", "+00:00")) < SUMMARY_TTL:
            return {**base, "text": prior["text"], "source": "cache", "generated_at": prior["generated_at"], "llm_called": False}
    if carry_prior and prior and prior.get("text"):
        # a non-material rebuild keeps the last words rather than spending a call or dropping to the list
        return {**base, "text": prior["text"], "source": "carried", "generated_at": prior.get("generated_at"), "llm_called": False}
    if llm is None:
        return {**base, "text": None, "source": "deterministic", "reason": "llm_unavailable", "generated_at": None, "llm_called": False}
    if calls_today >= daily_cap:
        return {**base, "text": None, "source": "deterministic", "reason": "daily_cap", "generated_at": None, "llm_called": False}
    prompt = (
        "You are writing the overnight recap for ONE investor's portfolio. Use ONLY the JSON facts below; do not "
        "add prices, events or numbers that are not in it. Write 4 to 6 plain sentences: what moved the held "
        "names and why (if a headline is given), what the watchlist shows, the market/overseas backdrop (say the "
        "futures feed is pending if it is), and one thing to look at first. No advice to trade, no sizing.\n\n"
        + json.dumps(payload, sort_keys=True, default=str)
    )
    try:
        text = (llm(prompt) or "").strip()
    except Exception as exc:  # noqa: BLE001 -- the card must still render; the reason is recorded
        return {**base, "text": None, "source": "deterministic", "reason": f"llm_error:{type(exc).__name__}", "generated_at": None, "llm_called": True}
    if not text:
        return {**base, "text": None, "source": "deterministic", "reason": "llm_empty", "generated_at": None, "llm_called": True}
    return {**base, "text": text, "source": "llm", "generated_at": now_utc.isoformat().replace("+00:00", "Z"), "llm_called": True}



# ---------------------------------------------------------------------------- the feed (amendment 2)


def build_feed(moves: Sequence[Mapping[str, Any]], macro: Mapping[str, Any], *, limit: int = 30) -> list[dict[str, Any]]:
    """A clean news feed, newest first: headline, source and time, the holdings it touches with $ exposure, and a
    one-line "So what" built from those numbers (no LLM per item).  The same story under two names is one item."""
    by_key: dict[str, dict[str, Any]] = {}
    total_mv = sum(m["market_value"] or 0.0 for m in moves if m["held"])
    for m in moves:
        for n in m.get("news", []):
            k = re.sub(r"\W+", " ", n["title"].lower()).strip()
            it = by_key.setdefault(k, {**n, "kind": "holding" if m["held"] else "watch", "holdings": []})
            if m["held"]:
                it["kind"] = "holding"
            it["holdings"].append(
                {"symbol": m["symbol"], "held": m["held"], "market_value": m["market_value"], "change_pct": m["change_pct"],
                 "dollar_impact": m["dollar_impact"], "close_tag": m["close_tag"]}
            )
    for h in macro.get("headlines", []):
        k = re.sub(r"\W+", " ", h["title"].lower()).strip()
        if k not in by_key:
            by_key[k] = {**h, "kind": "macro", "holdings": []}
    items = []
    for it in by_key.values():
        held = [x for x in it["holdings"] if x["held"]]
        exposure = round(sum(x["market_value"] or 0.0 for x in held), 2)
        if held:
            top = max(held, key=lambda x: x["market_value"] or 0.0)
            so = f"You hold ${exposure:,.0f} here; {top['symbol']} is {top['change_pct']:+.1f}% since {top['close_tag']}."
        elif it["holdings"]:
            w = it["holdings"][0]
            so = f"Watchlist only, no position; {w['symbol']} is {w['change_pct']:+.1f}% since {w['close_tag']}."
        else:
            so = f"Market backdrop for the whole book (${total_mv:,.0f} held)."
        items.append({**it, "exposure": exposure, "so_what": so})
    items.sort(key=lambda i: -_ts(i.get("published_at")))
    return items[:limit]


# ---------------------------------------------------------------------------- week ahead


def build_week_ahead(
    *,
    now: datetime,
    macro_calendar: Mapping[str, Any] | None,
    earnings: Mapping[str, Any] | None,
    ex_divs: Iterable[Mapping[str, Any]],
    held: Iterable[str],
    watch: Iterable[str],
    days: int = 8,
) -> dict[str, Any]:
    """CPI/PPI/jobs and FOMC from the macro calendar, earnings for held and watch names, ex-dividend dates, over the
    next ``days`` calendar days (ET).  Fed speakers have no feed: the strip says so instead of omitting them."""
    today = now.astimezone(ET).date()
    end = today + timedelta(days=days)
    held, watch = {s.upper() for s in held}, {s.upper() for s in watch}
    out: list[dict[str, Any]] = []

    def inside(d: str | None) -> bool:
        try:
            return bool(d) and today <= datetime.fromisoformat(str(d)).date() <= end
        except ValueError:
            return False

    for day, rec in sorted(((macro_calendar or {}).get("dates") or {}).items()):
        if not inside(day):
            continue
        for ev in rec.get("events", []):
            out.append({"date": day, "kind": "macro", "label": ev.get("name") or ev.get("event"), "time_et": ev.get("time_et"), "symbols": []})
    for day in (macro_calendar or {}).get("fomc_decisions", []):
        if inside(day):
            out.append({"date": day, "kind": "fomc", "label": "FOMC decision", "time_et": "14:00", "symbols": []})
    for sym, rec in (earnings or {}).items():
        sym = str(sym).upper()
        if (sym in held or sym in watch) and isinstance(rec, Mapping) and inside(rec.get("earnings_date")):
            out.append({"date": rec["earnings_date"], "kind": "earnings", "label": f"{sym} earnings", "time_et": None, "symbols": [sym], "held": sym in held})
    for r in ex_divs:
        sym = str(r.get("symbol") or "").upper()
        if (sym in held or sym in watch) and inside(str(r.get("ex_date"))):
            out.append({"date": str(r["ex_date"]), "kind": "ex_div", "label": f"{sym} ex-dividend", "time_et": None, "symbols": [sym], "held": sym in held})
    out.sort(key=lambda e: (e["date"], e["kind"], e["label"] or ""))
    return {"from": today.isoformat(), "to": end.isoformat(), "events": out, "fed_speakers": "no feed — not listed"}


def fetch_ex_divs(conn: Any, *, today: datetime, days: int = 8) -> list[dict[str, Any]]:
    d0 = today.astimezone(ET).date()
    with conn.cursor() as cur:
        cur.execute("SELECT symbol, ex_date FROM ticker_dividends WHERE ex_date BETWEEN %s AND %s", (d0, d0 + timedelta(days=days)))
        return [{"symbol": r[0], "ex_date": r[1].isoformat()} for r in cur.fetchall()]


def cio_brief_block(brief: Mapping[str, Any] | None) -> dict[str, Any]:
    """The CIO brief (LQ-1257) passed through as written: summary, risk tier, per-holding advisory actions, week
    ahead.  Absent or unreadable -> ``pending``; the card says so and the feed still renders."""
    if not brief:
        return {"status": "pending", "label": "CIO brief pending"}
    return {"status": "available", **{k: v for k, v in brief.items() if k != "status"}}



# ---------------------------------------------------------------------------- intraday: "Today so far" and change detection (LQ-1260)

MATERIAL_MOVE_PCT = 3.0


def session_open_et(now: datetime) -> datetime:
    return datetime.combine(now.astimezone(ET).date(), time(9, 30), ET)


def build_today(now: datetime, moves: Sequence[Mapping[str, Any]], feed: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """Only while the regular session is open: held moves and the feed items published since 09:30 ET.  The quote
    snapshot carries no open price, so the move is against the prior close and the section says so."""
    if not _session_open(now.astimezone(ET)):
        return None
    since = session_open_et(now).timestamp()
    return {
        "label": "Today so far",
        "basis": "move vs prior close (the quote feed carries no open price)",
        "since": session_open_et(now).astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "moves": [m for m in moves if m["held"] or m["big_move"]],
        "news": [i for i in feed if _ts(i.get("published_at")) >= since and i.get("kind") != "macro"],
    }


def _akey(a: Mapping[str, Any]) -> str:
    return hashlib.sha1(
        f"{str(a.get('symbol') or '').upper()}|{re.sub(chr(92) + 'W+', ' ', str(a.get('title') or '').lower()).strip()}|{_iso(a.get('published_at'))}".encode()
    ).hexdigest()[:12]


def change_state(moves: Sequence[Mapping[str, Any]], articles: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """What --if-changed compares: every held/watch article id since the window start (not just the top 3 shown) and
    each held move bucketed to 1%."""
    names = {m["symbol"]: m["held"] for m in moves}
    seen = sorted({(_akey(a), str(a.get("symbol") or "").upper()) for a in articles if str(a.get("symbol") or "").upper() in names})
    held_pct = {m["symbol"]: round(m["change_pct"]) for m in moves if m["held"]}
    exact = {m["symbol"]: m["change_pct"] for m in moves if m["held"]}
    sig = hashlib.sha256(json.dumps([seen, sorted(held_pct.items())], sort_keys=True).encode()).hexdigest()[:16]
    return {"signature": sig, "articles": [{"k": k, "s": sym} for k, sym in seen], "held_pct": held_pct, "held_exact": exact}


def detect_change(
    prior: Mapping[str, Any] | None, cur: Mapping[str, Any], moves: Sequence[Mapping[str, Any]], articles: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """``{changed, material, reason, kind, symbol, headline}``.  Material = a NEW article on a held name, or a held
    name crossing +/-3% since the last build.  A change that is neither (watchlist news, a 1% bucket step) rebuilds
    the data but never spends an LLM call."""
    if not prior or not prior.get("signature"):
        return {"changed": True, "material": True, "reason": "first build", "kind": "first"}
    if prior["signature"] == cur["signature"]:
        return {"changed": False, "material": False, "reason": "unchanged", "kind": "none"}
    held = {m["symbol"] for m in moves if m["held"]}
    old_keys = {x["k"] for x in prior.get("articles", [])}
    for a in sorted(articles, key=lambda a: -_ts(a.get("published_at"))):
        sym = str(a.get("symbol") or "").upper()
        if sym in held and _akey(a) not in old_keys:
            return {"changed": True, "material": True, "kind": "news", "symbol": sym, "headline": str(a.get("title") or ""),
                    "reason": f"new {sym} article"}
    old = prior.get("held_exact") or {}
    for m in moves:
        if m["held"] and abs(m["change_pct"]) >= MATERIAL_MOVE_PCT and abs(old.get(m["symbol"], 0.0)) < MATERIAL_MOVE_PCT:
            return {"changed": True, "material": True, "kind": "move", "symbol": m["symbol"], "reason": f"{m['symbol']} {m['change_pct']:+.1f}%"}
    return {"changed": True, "material": False, "reason": "minor change", "kind": "minor"}


# ---------------------------------------------------------------------------- the snapshot


def build_snapshot(
    *,
    now: datetime,
    ticker_snapshot: Mapping[str, Any],
    articles: Sequence[Mapping[str, Any]],
    futures: Mapping[str, Any] | None,
    llm: Callable[[str], str] | None,
    prior: Mapping[str, Any] | None = None,
    calls_today: int = 0,
    macro_calendar: Mapping[str, Any] | None = None,
    earnings: Mapping[str, Any] | None = None,
    ex_divs: Iterable[Mapping[str, Any]] = (),
    cio_brief: Mapping[str, Any] | None = None,
    if_changed: bool = False,
) -> dict[str, Any] | None:
    """The whole card.  With ``if_changed`` returns None when nothing material moved since ``prior`` (no write, no LLM
    call).  A rebuild that is not material keeps the prior summary text; only a material one may spend a call."""
    win = window(now)
    moves = attach_news(build_moves(ticker_snapshot, close_tag=win["close_tag"]), articles)
    state = change_state(moves, articles)
    if if_changed:
        decision = detect_change((prior or {}).get("change_state"), state, moves, articles)
        if not decision["changed"]:
            return None
    else:
        decision = {"changed": True, "material": True, "reason": "scheduled", "kind": "scheduled"}
    macro = build_macro(articles, futures)
    summary = build_summary(
        moves, macro, now=now, llm=llm if decision["material"] else None,
        prior=(prior or {}).get("summary") if prior else None, calls_today=calls_today, carry_prior=not decision["material"],
    )
    feed = build_feed(moves, macro)
    if decision["kind"] in ("news", "move", "first"):
        updated = {
            "at": now.astimezone(UTC).isoformat().replace("+00:00", "Z"), "at_et": now.astimezone(ET).strftime("%H:%M ET"),
            "reason": decision["reason"], "kind": decision["kind"], "symbol": decision.get("symbol"), "headline": decision.get("headline"),
        }
    else:
        updated = (prior or {}).get("updated")
    return {
        "schema": SCHEMA,
        "generated_at": now.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "window": win,
        "quotes_as_of": (ticker_snapshot.get("_meta") or {}).get("generated_at"),
        "updated": updated,
        "change_state": state,
        "today": build_today(now, moves, feed),
        "cio_brief": cio_brief_block(cio_brief),
        "feed": feed,
        "week_ahead": build_week_ahead(
            now=now, macro_calendar=macro_calendar, earnings=earnings, ex_divs=ex_divs,
            held=[m["symbol"] for m in moves if m["held"]], watch=[m["symbol"] for m in moves if not m["held"]],
        ),
        "moves": moves,
        "macro": macro,
        "summary": summary,
    }


def freshness(snapshot: Mapping[str, Any], *, now: datetime, max_age: timedelta = timedelta(hours=3)) -> dict[str, Any]:
    """The route's verdict on a stored snapshot: age, and ``stale`` when it is older than ``max_age`` or names a
    window that is no longer the current one (a Monday snapshot read on Tuesday after the 16:00 close)."""
    gen = snapshot.get("generated_at")
    age = None
    if gen:
        age = (now.astimezone(UTC) - datetime.fromisoformat(str(gen).replace("Z", "+00:00"))).total_seconds()
    cur = window(now)["session_date"]
    wrong_window = (snapshot.get("window") or {}).get("session_date") != cur
    return {"age_seconds": age, "stale": age is None or age > max_age.total_seconds() or wrong_window, "window_current": not wrong_window}


# ---------------------------------------------------------------------------- the DB read (read-only)

NEWS_SQL = """
SELECT symbol, title, source, source_url, published_at, relevance_score
FROM news_articles
WHERE published_at >= %(since)s AND published_at <= %(until)s AND COALESCE(is_duplicate, false) = false
  AND (upper(symbol) = ANY(%(symbols)s) OR title ~* %(macro)s)
ORDER BY published_at DESC
LIMIT 3000
"""


def fetch_articles(conn: Any, *, since: datetime, until: datetime, symbols: Sequence[str]) -> list[dict[str, Any]]:
    """Held/watchlist/stopped-out names plus macro-looking titles since the close (read-only SELECT)."""
    with conn.cursor() as cur:
        cur.execute(NEWS_SQL, {"since": since, "until": until, "symbols": [s.upper() for s in symbols], "macro": MACRO_RE.pattern})
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        v = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    return v if isinstance(v, dict) else None
