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

LQ-20261107-1282 — "what has moved since Friday": a name's Friday close % is not the answer after 16:00 Friday, and
after 20:00 Sunday (overnight) or 04:00 (pre-market) the newest print is not the Friday one either. ``attach_extended``
gives every name the newest print STRICTLY after the close, read from ``market_quotes_extended`` (the Schwab
extended-hours lane, and the Alpaca SIP extended feed where it exists) with the session it printed in, and
``build_market_now`` gives the futures/cash-index row that replaces "futures feed pending". A name with no print
since the close says exactly that; a print with no dated reference to THIS close is shown as a level, never as a
percentage the store did not compute.

LQ-20261107-1283 — the feed is deduped across feeds (one story, every source that carried it) and RANKED here, not in
the browser: ``rank_feed`` scores every item from the book ($ exposed x |move since the close|), the CIO brief's
per-name action, the at-risk names, the market-event group, and sinks appraisal/13F boilerplate. The score and a
one-line reason travel with the item so the card can print ``#1 · $8.5k at risk in SPCX``.

LQ-20261107-1283 mockup v3 — ``urgency_for`` paints the heat map on the same items (red = act now, amber = watch,
green = good news for the book, none = read later) and its thresholds are stored with the snapshot as
``feed_rule.urgency`` so the glow is explainable long after the run.


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
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    from lib import cio_brief_consistency as cio_consistency
    from lib import since_close_stamp
    from lib.market_risk import sessions
except ImportError:  # pragma: no cover - imported as scripts.lib
    from scripts.lib import cio_brief_consistency as cio_consistency
    from scripts.lib import since_close_stamp
    from scripts.lib.market_risk import sessions

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

SCHEMA = "since_close_card.v1"
SUMMARY_TTL = timedelta(minutes=15)
SUMMARY_DAILY_CAP = 40  # n8n runs ~12/night + weekends; flash is ~$0.0005 a call
BIG_MOVE_PCT = 3.0
NEWS_PER_NAME = 3
MACRO_LIMIT = 6

#: Display name per ``market_quotes_extended.session`` value (LQ-20261107-1282). The authoritative copy is
#: ``scripts/lib/session_now.py`` (cc-deepseek-9's LQ-20261107-1264 amendment 1, in the fold queue); until it is on
#: live this module carries the same five names so the card can label a print without waiting. When both exist the
#: imported map wins -- one spelling, not two that drift.
FALLBACK_SESSION_LABELS = {
    "regular": "close",
    "premarket": "pre-market",
    "afterhours": "after-hours",
    "overnight": "overnight",
    "futures_open": "futures open",
}
try:  # pragma: no cover - the import path is the future state, exercised when the fold lands session_now.py
    from lib.session_now import SESSION_LABELS
except ImportError:  # pragma: no cover - the same module under the scripts.lib package path
    try:
        from scripts.lib.session_now import SESSION_LABELS
    except ImportError:  # pragma: no cover - today's live state: the helper is not on this tree yet
        SESSION_LABELS = FALLBACK_SESSION_LABELS

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


# ---------------------------------------------------------------------------- what printed since the close (LQ-1282)


def session_label(session: Any) -> str:
    """``overnight`` / ``pre-market`` / ``after-hours`` / ``futures open``; an unknown value is shown as itself."""
    raw = str(session or "").strip()
    return SESSION_LABELS.get(raw, raw)


def _print_time(bar_end: Any) -> str:
    """``Sun 6:45 PM ET`` -- the print's own instant in the operator's zone; empty when it cannot be read."""
    try:
        at = bar_end if isinstance(bar_end, datetime) else datetime.fromisoformat(str(bar_end))
    except (TypeError, ValueError):
        return ""
    if at.tzinfo is None:
        at = at.replace(tzinfo=UTC)
    et = at.astimezone(ET)
    return f"{et:%a} {et.hour % 12 or 12}:{et.minute:02d} {'AM' if et.hour < 12 else 'PM'} ET"


def attach_extended(
    moves: Sequence[Mapping[str, Any]],
    rows: Iterable[Mapping[str, Any]],
    *,
    close_date: str,
    close_at: datetime,
    now: datetime,
) -> list[dict[str, Any]]:
    """Give each move its newest print strictly after ``close_at``, from ``market_quotes_extended``.

    The row's own ``change_pct`` is used ONLY when its ``reference_date`` is the close date this card is about: a
    pre-market print on Friday references Thursday's close, and showing that as "vs Friday" would be a different
    number wearing the same label. Everything else is a LEVEL: the price and the session, with no percentage invented.
    """
    by_sym: dict[str, list[Mapping[str, Any]]] = {}
    for r in rows:
        by_sym.setdefault(str(r.get("symbol") or "").upper(), []).append(r)
    out = []
    for m in moves:
        cands = [
            r
            for r in by_sym.get(m["symbol"], [])
            if (dt := _as_dt(r.get("bar_end"))) is not None and dt > close_at
        ]
        newest = max(cands, key=lambda r: _as_dt(r.get("bar_end")) or close_at) if cands else None
        if newest is None:
            out.append({**m, "extended": None, "extended_note": f"no print since {m['close_tag'].split()[0]}",
                        "dollar_impact_now": m.get("dollar_impact"), "move_now_pct": m["change_pct"]})
            continue
        price = _num(newest.get("price"))
        pct = _num(newest.get("change_pct"))
        ref_date = str(newest.get("reference_date") or "")[:10] or None
        uses_close = pct is not None and ref_date == close_date
        ext = {
            "state": "print" if uses_close else "level_only",
            "session": str(newest.get("session") or ""),
            "session_label": session_label(newest.get("session")),
            "price": price,
            "change_pct": round(pct, 2) if uses_close and pct is not None else None,
            "printed_at": _iso(newest.get("bar_end")),
            "printed_text": _print_time(newest.get("bar_end")),
            "reference_close": _num(newest.get("reference_close")),
            "reference_date": ref_date,
            "age_minutes": _age_minutes(newest.get("bar_end"), now),
        }
        # a level-only print has no percentage of its own, so the dollars stay Friday's: the two numbers on the chip
        # are always a matched pair (price with pct), never an extended price wearing the close's percentage.
        move_pct = ext["change_pct"] if uses_close else m["change_pct"]
        impact_now = None
        mv, friday_px = m.get("market_value"), m.get("price")
        if m["held"] and uses_close and mv and price and friday_px and move_pct is not None:
            shares = mv / friday_px
            impact_now = round(shares * price * move_pct / 100.0, 2)
        out.append({**m, "extended": ext, "extended_note": None, "move_now_pct": move_pct,
                    "dollar_impact_now": impact_now if impact_now is not None else m.get("dollar_impact")})
    return out


def _dollars_key(m: Mapping[str, Any]) -> tuple[int, float]:
    """Largest |$| first. A name whose $ move is unknown ranks AFTER every known one: it is not a name on which
    $0 moved, it is a name the feed could not price (the 0/1 lead term keeps it last in an ascending sort)."""
    d = m.get("dollar_impact_now") if m.get("dollar_impact_now") is not None else m.get("dollar_impact")
    return (0, -abs(d)) if isinstance(d, (int, float)) else (1, 0.0)


def _pct_key(m: Mapping[str, Any]) -> tuple[int, float]:
    """Largest |%| first, by the same rule: an unknown move is last, never a move of zero."""
    p = m.get("move_now_pct") if m.get("move_now_pct") is not None else m.get("change_pct")
    return (0, -abs(p)) if isinstance(p, (int, float)) else (1, 0.0)


def sort_by_now(moves: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Held names by |$ move| in the NEWEST print (so the weekend's biggest mover is first, not Friday's); a name with
    no print since the close falls back to its Friday dollars. Watchlist names follow, by the same rule."""
    held = sorted((m for m in moves if m["held"]), key=_dollars_key)
    watch = sorted((m for m in moves if not m["held"]), key=_pct_key)
    return held + watch


def _as_dt(v: Any) -> datetime | None:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=UTC)
    try:
        d = datetime.fromisoformat(str(v))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def _age_minutes(v: Any, now: datetime) -> float | None:
    d = _as_dt(v)
    if d is None:
        return None
    return round((now - d).total_seconds() / 60.0, 1)


#: symbols the futures/cash-index row may carry, in the order the card draws them. A symbol absent from the store is
#: absent from the row (never a zero), and the block says what is missing.
FUTURES_ORDER = ("/ES", "/NQ", "/RTY", "/YM")
INDEX_ORDER = ("$SPX", "$COMPX", "$DJI", "$RUT", "$NDX", "$VIX")

#: What the card calls each root when the config carries no label. ``config/market_risk_offhours_quotes.yaml``
#: ``schwab.labels`` owns these names and overrides every entry here; on live that block is still in the fold queue, so
#: without these defaults the row would say "/ES" to the operator. Display only.
DEFAULT_LABELS = {
    "/ES": "S&P 500 futures",
    "/NQ": "Nasdaq 100 futures",
    "/RTY": "Russell 2000 futures",
    "/YM": "Dow futures",
    "$SPX": "S&P 500",
    "$COMPX": "Nasdaq Composite",
    "$DJI": "Dow Jones",
    "$RUT": "Russell 2000",
    "$NDX": "Nasdaq 100",
    "$VIX": "VIX",
}


def load_labels(path: Path | None = None) -> dict[str, str]:
    """Display names: the config's ``schwab.labels`` over ``DEFAULT_LABELS``. A missing or unreadable file is not an
    error -- the defaults cover every symbol the row can carry, and a symbol with no name is shown as itself."""
    labels = dict(DEFAULT_LABELS)
    try:
        import yaml  # noqa: PLC0415 -- a display-only dependency; the builder works without it

        p = Path(path) if path else Path(__file__).resolve().parents[2] / "config" / "market_risk_offhours_quotes.yaml"
        doc = yaml.safe_load(p.read_text()) or {}
        labels.update({str(k): str(v) for k, v in ((doc.get("schwab") or {}).get("labels") or {}).items() if v})
    except (OSError, ValueError, ImportError, AttributeError):  # noqa: BLE001 -- a label is cosmetic, the level is not
        pass
    return labels


#: Overseas cash indices have no provider on this host. Rather than invent a level, the row says when each one opens,
#: in ET. (label, exchange timezone, local open hour, minute)
OVERSEAS_OPEN = (
    ("Nikkei 225", "Asia/Tokyo", 9, 0),
    ("Hang Seng", "Asia/Hong_Kong", 9, 30),
    ("DAX", "Europe/Berlin", 9, 0),
    ("FTSE 100", "Europe/London", 8, 0),
)


def _next_open_et(now: datetime, zone: str, hour: int, minute: int) -> datetime | None:
    """The next weekday cash open of an overseas exchange, converted to ET. None when the tz database has no zone."""
    try:
        z = ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError):  # a host without tzdata: no open time is known, so no row is drawn
        return None
    start = now.astimezone(z).date()
    for d in range(8):
        day = start + timedelta(days=d)
        if day.weekday() >= 5:
            continue
        opened = datetime.combine(day, time(hour, minute), tzinfo=z)
        if opened > now:
            return opened.astimezone(ET)
    return None


def build_market_now(
    rows: Iterable[Mapping[str, Any]], *, close_date: str, close_at: datetime, now: datetime,
    labels: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """The "Futures / overseas" row: the newest print after the close for each futures root and cash index, with the
    arrow ONLY where the provider dated a reference to this close. Overseas cash indices have no provider on this
    host (the Schwab feed is the US quotes service); that is said, never replaced by a guess."""
    lab = {**DEFAULT_LABELS, **dict(labels or {})}
    by_sym: dict[str, Mapping[str, Any]] = {}
    for r in rows:
        sym = str(r.get("symbol") or "").upper()
        dt = _as_dt(r.get("bar_end"))
        if dt is None or dt <= close_at:
            continue
        cur = by_sym.get(sym)
        if cur is None or (_as_dt(cur.get("bar_end")) or close_at) < dt:
            by_sym[sym] = r

    def row(sym: str) -> dict[str, Any] | None:
        r = by_sym.get(sym)
        if r is None:
            return None
        pct = _num(r.get("change_pct"))
        dated = str(r.get("reference_date") or "")[:10] == close_date
        return {
            "symbol": sym,
            "label": lab.get(sym) or sym,
            "level": _num(r.get("price")),
            "change_pct": round(pct, 2) if (pct is not None and dated) else None,
            "level_only": not (pct is not None and dated),
            "session": str(r.get("session") or ""),
            "session_label": session_label(r.get("session")),
            "printed_at": _iso(r.get("bar_end")),
            "printed_text": _print_time(r.get("bar_end")),
            "reference_date": str(r.get("reference_date") or "")[:10] or None,
        }

    futures = [x for s in FUTURES_ORDER if (x := row(s))]
    indices = [x for s in INDEX_ORDER if (x := row(s))]
    as_of = max((x["printed_at"] for x in futures + indices if x["printed_at"]), default=None)
    present = {x["symbol"] for x in futures + indices}
    missing = [s for s in FUTURES_ORDER + INDEX_ORDER if s not in present]
    overseas_rows = []
    for label, zone, hh, mm in OVERSEAS_OPEN:
        opens = _next_open_et(now, zone, hh, mm)
        if opens is None:
            continue
        overseas_rows.append({
            "label": label, "status": "no_feed", "opens_at": opens.isoformat(),
            "opens_text": f"opens {opens.strftime('%a %-I:%M %p')} ET",
        })
    return {
        "status": "available" if (futures or indices) else "pending",
        "as_of": as_of,
        "as_of_text": _print_time(as_of),
        "futures": futures,
        "indices": indices,
        "missing": missing,
        "overseas": {
            "status": "no_feed",
            "label": "Overseas cash indices: no direct feed on this host — Asia/Europe moves appear as headlines below.",
            "rows": overseas_rows,
        },
    }


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


#: Headlines that are appraisal or proxy boilerplate, not news an investor acts on: 13F "acquired by", "fair value
#: estimate", a price-target lift, a "should you buy" listicle. They are kept (they are true) and ranked last.
LOW_VALUE_RE = re.compile(
    r"(13f|acquired by|acquires? \d|fair value|price target|target price|should you (buy|sell)|stock split|"
    r"is it time to|here'?s what|what to know|analysts? (raise|lower|cut|boost)|upgraded? to|downgraded? to)",
    re.I,
)
#: the market-event group the operator reads first: semis and big tech move the whole book.
MARKET_GROUP_RE = re.compile(r"(semis?|semiconductor|chip|nvidia|nasdaq|big tech|tech (?:stocks?|shares?)|ai capex)", re.I)

FEED_LIMIT = 30


def _title_key(title: Any) -> str:
    """A comparison key that survives a publisher suffix: ``Story - Yahoo Finance`` and ``Story | Reuters`` are the
    same key, so one story from two feeds is one item."""
    t = re.sub(r"\s*[|\-–—]\s*[^|\-–—]{2,40}$", "", str(title or ""))
    return re.sub(r"\W+", " ", t.lower()).strip()


def _tokens(title: Any) -> set[str]:
    return {w for w in _title_key(title).split() if len(w) > 2}


def merge_duplicates(items: Sequence[Mapping[str, Any]], *, threshold: float = 0.85) -> list[dict[str, Any]]:
    """Fold items that are the same story under different feed wording. Two titles merge when their significant-word
    sets overlap by at least ``threshold`` (Jaccard) AND they touch the same symbols; the earlier item keeps the
    identity and gains every other feed's name in ``sources``. Deterministic: order of input decides the survivor."""
    out: list[dict[str, Any]] = []
    for it in items:
        it = {**it, "sources": list(it.get("sources") or [it.get("source")])}
        mine, syms = _tokens(it.get("title")), {h["symbol"] for h in it.get("holdings", [])}
        for kept in out:
            theirs = _tokens(kept.get("title"))
            theirs_syms = {h["symbol"] for h in kept.get("holdings", [])}
            union = mine | theirs
            same_story = bool(union) and len(mine & theirs) / len(union) >= threshold
            if not same_story or (syms and theirs_syms and not (syms & theirs_syms)):
                continue
            for s in it["sources"]:
                if s and s not in kept["sources"]:
                    kept["sources"].append(s)
            for h in it.get("holdings", []):
                if all(x["symbol"] != h["symbol"] for x in kept["holdings"]):
                    kept["holdings"].append(h)
            kept["kind"] = "holding" if (kept["kind"] == "holding" or it.get("kind") == "holding") else kept["kind"]
            break
        else:
            out.append(it)
    return out


def _biggest_holding(held: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    """The largest holding by |market value|. An unpriced holding ranks below every priced one instead of being read
    as a holding worth $0 — the caller names this symbol to the operator."""
    def key(h: Mapping[str, Any]) -> tuple[int, float]:
        mv = h.get("market_value")
        return (1, abs(mv)) if isinstance(mv, (int, float)) else (0, 0.0)
    return max(held, key=key)


def rank_feed(
    items: list[dict[str, Any]], *, cio_actions: Mapping[str, str] | None = None, at_risk: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """Score every item, explain the score in one line, and number the list. The CIO brief is the verdict owner: a
    held name it names an action for outranks a bigger dollar move on a name it says nothing about.

    score = min(60, round($ the book moved on this story))   -- held $ exposed x |move since the close|
          + 30 if the CIO brief names an action for a held name here
          + 15 if a held name here is at or through its stop
          + 10 if the story is market-wide and in the semis/big-tech group
          +  5 if it is market-wide at all (the backdrop for the whole book)
          +  8 if it is a watchlist name moving 3% or more
          - 40 if it is appraisal/13F/price-target boilerplate
    """
    cio_actions = dict(cio_actions or {})
    risk = {s.upper() for s in at_risk}
    scored = []
    for it in items:
        held = [h for h in it.get("holdings", []) if h.get("held")]
        moved: list[float] = []
        for h in held:
            mv = h.get("market_value")
            pct = h.get("move_now_pct") if h.get("move_now_pct") is not None else h.get("change_pct")
            if mv is None or pct is None:
                continue  # an unpriced name cannot rank; it is not a name on which $0 moved
            moved.append(abs(mv * pct / 100.0))
        dollars = sum(moved)
        score = min(60.0, round(dollars))
        why: list[str] = []
        cio_hit = next((s for s in (h["symbol"] for h in held) if s in cio_actions), None)
        risk_hit = next((s for s in (h["symbol"] for h in held) if s in risk), None)
        if cio_hit:
            score += 30
            why.append(f"CIO: {cio_hit} {cio_actions[cio_hit]}")
        elif risk_hit:
            score += 15
            why.append(f"{risk_hit} at its stop")
        elif held:
            top = _biggest_holding(held)
            why.append(f"{top['symbol']} {_pct_short(top.get('move_now_pct') if top.get('move_now_pct') is not None else top.get('change_pct'))} since the close")
        if not held and it.get("kind") == "macro":
            if MARKET_GROUP_RE.search(str(it.get("title") or "")):
                score += 10
                why.append("market-wide · semis/tech")
            else:
                score += 5
                why.append("market-wide")
        watches = [h for h in it.get("holdings", [])
                   if not h.get("held") and h.get("change_pct") is not None and abs(h["change_pct"]) >= BIG_MOVE_PCT]
        if not held and watches:
            score += 8
            why.append(f"watchlist {watches[0]['symbol']} {_pct_short(watches[0].get('change_pct'))}")
        if LOW_VALUE_RE.search(str(it.get("title") or "")):
            score -= 40
            why.append("appraisal/13F boilerplate")
        if dollars >= 1:
            why.insert(0, f"${dollars:,.0f} moved")
        scored.append({**it, "score": round(score, 1), "why": " · ".join(why) or "background"})
    scored.sort(key=lambda i: (-i["score"], -_ts(i.get("published_at"))))
    return [{**it, "rank": n} for n, it in enumerate(scored, start=1)]


#: Stored in the snapshot as ``feed_rule.score``: the one-line form of what ``rank_feed`` does, so the order the
#: operator sees is explainable without reading this file.
RANK_RULE = (
    "min(60, $ moved on held names since the close) + 30 CIO brief action + 15 at-risk name + 10 market-wide "
    "semis/tech + 5 market-wide + 8 watchlist move >= 3% - 40 appraisal/13F boilerplate; ties newest story first"
)


def _pct_short(v: Any) -> str:
    n = _num(v)
    return "—" if n is None else f"{n:+.1f}%"


# ---------------------------------------------------------------------------- the heat-map glow (mockup v3)
#: The glow is a TRIAGE aid, computed here and stored with the item; the browser only paints what it is told.
#: Thresholds, not vibes: a held name 3% down since the close is urgent; 1% down is not.
URGENCY_DOWN_PCT = -3.0         # red: a held name this far down since the close
URGENCY_WATCH_DROP_PCT = -10.0  # red: a watchlist name this far down, position or not
URGENCY_UP_PCT = 3.0            # green: a held name this far up since the close
WEAK_WEEK_PCT = -5.0            # amber: a held name this far down on the week

#: Stored verbatim in the snapshot (``feed_rule.urgency``) so a reader a month later can see what a glow meant.
URGENCY_RULE = {
    "red": f"a held name {abs(URGENCY_DOWN_PCT):.0f}% or more down since the close, a watchlist name "
           f"{abs(URGENCY_WATCH_DROP_PCT):.0f}% or more down, or a downgrade/cut in the headline",
    "amber": f"an insider sale, or a held name {abs(WEAK_WEEK_PCT):.0f}% or more down on the week",
    "green": f"a held name {URGENCY_UP_PCT:.0f}% or more up since the close",
    "none": "no glow: read when you have time. 13F / fair-value / price-target boilerplate never glows.",
}
INSIDER_RE = re.compile(r"(\binsider\b|\bform 4\b|plans to sell|intends to sell|to sell \d|sold .{1,40}shares)", re.I)
DOWNGRADE_RE = re.compile(r"(downgrad\w*|\bcut\b.{0,24}\b(rating|to)\b|slashed)", re.I)


def _pos_move(h: Mapping[str, Any]) -> float | None:
    """The move to show for a name: its newest print since the close when one exists, else the close's."""
    return _num(h.get("move_now_pct")) if h.get("move_now_pct") is not None else _num(h.get("change_pct"))


def urgency_for(item: Mapping[str, Any]) -> tuple[str | None, str | None]:
    """(level, why) for one feed item. Levels are exclusive, red > amber > green, and boilerplate never glows."""
    title = str(item.get("title") or "")
    if LOW_VALUE_RE.search(title):
        return None, None
    held = [h for h in item.get("holdings", []) if h.get("held")]
    watch = [h for h in item.get("holdings", []) if not h.get("held")]
    moved = [(_pos_move(h), h) for h in held]
    down = min(((p, h) for p, h in moved if p is not None), key=lambda x: x[0], default=None)
    up = max(((p, h) for p, h in moved if p is not None), key=lambda x: x[0], default=None)
    if down and down[0] <= URGENCY_DOWN_PCT:
        return "red", f"held {down[1]['symbol']} {_pct_short(down[0])} since the close"
    if DOWNGRADE_RE.search(title):
        return "red", "downgrade / cut"
    dropped = [(_num(h.get("change_pct")), h) for h in watch if _num(h.get("change_pct")) is not None]
    worst_watch = min(dropped, key=lambda x: x[0], default=None)
    if worst_watch and worst_watch[0] <= URGENCY_WATCH_DROP_PCT:
        return "red", f"watchlist {worst_watch[1]['symbol']} {_pct_short(worst_watch[0])}"
    if INSIDER_RE.search(title):
        return "amber", "insider sale"
    week = [(_num(h.get("week_pct")), h) for h in held if _num(h.get("week_pct")) is not None]
    worst_week = min(week, key=lambda x: x[0], default=None)
    if worst_week and worst_week[0] <= WEAK_WEEK_PCT:
        return "amber", f"held {worst_week[1]['symbol']} {_pct_short(worst_week[0])} on the week"
    if up and up[0] >= URGENCY_UP_PCT:
        return "green", f"held {up[1]['symbol']} {_pct_short(up[0])} since the close"
    return None, None


def build_feed(
    moves: Sequence[Mapping[str, Any]], macro: Mapping[str, Any], *, limit: int = FEED_LIMIT,
    cio_actions: Mapping[str, str] | None = None, at_risk: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """A clean news feed, most important first (LQ-20261107-1283): headline, every source that carried it, the
    holdings it touches with their $ move since the close, a one-line "So what" built from those numbers (no LLM per
    item), and the rank with its reason. The same story under two feed names is one item."""
    by_key: dict[str, dict[str, Any]] = {}
    total_mv = sum(m["market_value"] or 0.0 for m in moves if m["held"])
    for m in moves:
        for n in m.get("news", []):
            k = _title_key(n["title"])
            it = by_key.setdefault(k, {**n, "kind": "holding" if m["held"] else "watch", "holdings": [], "sources": []})
            if m["held"]:
                it["kind"] = "holding"
            src = str(n.get("source") or "")
            if src and src not in it["sources"]:
                it["sources"].append(src)
            it["holdings"].append(
                {"symbol": m["symbol"], "held": m["held"], "market_value": m["market_value"], "change_pct": m["change_pct"],
                 "week_pct": m.get("week_pct"), "dollar_impact": m["dollar_impact"], "close_tag": m["close_tag"],
                 "move_now_pct": m.get("move_now_pct"), "dollar_impact_now": m.get("dollar_impact_now"),
                 "extended_label": (m.get("extended") or {}).get("session_label") if m.get("extended") else None}
            )
    for h in macro.get("headlines", []):
        k = _title_key(h["title"])
        if k not in by_key:
            by_key[k] = {**h, "kind": "macro", "holdings": [], "sources": [h.get("source")] if h.get("source") else []}
    items = []
    for it in merge_duplicates(list(by_key.values())):
        held = [x for x in it["holdings"] if x["held"]]
        exposure = round(sum(x["market_value"] or 0.0 for x in held), 2)
        if held:
            top = _biggest_holding(held)
            moved = top.get("move_now_pct") if top.get("move_now_pct") is not None else top.get("change_pct")
            basis = f"{top['extended_label']}" if top.get("extended_label") and top.get("move_now_pct") is not None else top["close_tag"]
            so = f"You hold ${exposure:,.0f} here; {top['symbol']} is {_pct_short(moved)} since {basis}."
        elif it["holdings"]:
            w = it["holdings"][0]
            so = f"Watchlist only, no position; {w['symbol']} is {_pct_short(w['change_pct'])} since {w['close_tag']}."
        else:
            so = f"Market backdrop for the whole book (${total_mv:,.0f} held)."
        level, why_glow = urgency_for(it)
        items.append({**it, "exposure": exposure, "so_what": so, "urgency": level, "urgency_why": why_glow})
    ranked = rank_feed(items, cio_actions=cio_actions, at_risk=at_risk)
    return ranked[:limit]


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
    ahead.  Absent or unreadable -> ``pending``; the card says so and the feed still renders.

    LQ-20261107-1318: the block also carries ``run`` — the brief's ``run_id`` and whether every run-scoped piece
    (synopsis, each stop_advice row) comes from that same run. The card embeds a COPY of the brief, so a copy
    assembled from two builds could disagree with itself; the UI draws ``run.text`` instead of trusting the copy.
    """
    if not brief:
        return {"status": "pending", "label": "CIO brief pending"}
    return {
        "status": "available",
        **{k: v for k, v in brief.items() if k != "status"},
        "run": cio_consistency.run_check(brief),
    }


#: The answers that ask the operator to DO something. HOLD and NO_ACTION are answers too, and they do not raise a name
#: in the feed ranking: "nothing to do here" is not a reason to read a story first.
CIO_ACTIONABLE = ("RAISE", "ADD_STOP", "FIX_QTY")


def _cio_actions(brief: Mapping[str, Any] | None) -> dict[str, str]:
    """{symbol: answer} for the held names the CIO brief asks an action on, read from its ``stop_advice[]`` (LQ-1257's
    per-account rows). No brief, no rows, or only HOLD/NO_ACTION: an empty map, and the ranking falls back to dollars."""
    out: dict[str, str] = {}
    for row in (brief or {}).get("stop_advice") or []:
        if not isinstance(row, Mapping):
            continue
        sym, ans = str(row.get("symbol") or "").upper(), str(row.get("answer") or "").upper()
        if sym and ans in CIO_ACTIONABLE:
            out.setdefault(sym, ans)
    return out


def _at_risk(brief: Mapping[str, Any] | None) -> list[str]:
    """Held names the brief says anything about at all (its rows are the names it examined on price/structure), in the
    brief's own order. Used as the ranking's second tier, under an explicit action and over a bare dollar move."""
    seen: list[str] = []
    for row in (brief or {}).get("stop_advice") or []:
        if isinstance(row, Mapping):
            sym = str(row.get("symbol") or "").upper()
            if sym and sym not in seen and str(row.get("answer") or "").upper() != "NO_ACTION":
                seen.append(sym)
    return seen



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
    """What --if-changed compares: every held/watch article id since the window start (not just the top 3 shown), each
    held move bucketed to 1%, and -- LQ-20261107-1282 -- the newest EXTENDED print on each held name (its instant and
    its 1-dp change). Without the prints a weekend card would go quiet exactly when the operator is watching for the
    Sunday-night futures open: the Friday percentages do not move, so nothing else in this signature would."""
    names = {m["symbol"]: m["held"] for m in moves}
    seen = sorted({(_akey(a), str(a.get("symbol") or "").upper()) for a in articles if str(a.get("symbol") or "").upper() in names})
    held_pct = {m["symbol"]: round(m["change_pct"]) for m in moves if m["held"]}
    exact = {m["symbol"]: m["change_pct"] for m in moves if m["held"]}
    prints = {
        m["symbol"]: [
            # the PRINT's own change, not move_now_pct: for a name with no print that field carries the close's
            # percentage, and a signature built from it could not tell "no print" from "printed flat".
            round((m.get("extended") or {}).get("change_pct"), 1) if (m.get("extended") or {}).get("change_pct") is not None else None,
            ((m.get("extended") or {}).get("printed_at")),
        ]
        for m in moves
        if m["held"]
    }
    sig = hashlib.sha256(
        json.dumps([seen, sorted(held_pct.items()), sorted(prints.items())], sort_keys=True, default=str).encode()
    ).hexdigest()[:16]
    return {"signature": sig, "articles": [{"k": k, "s": sym} for k, sym in seen], "held_pct": held_pct,
            "held_exact": exact, "prints": prints}


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
    # LQ-20261107-1282: a NEW extended print on a held name that crosses the material line. The crossing test (the
    # prior print was under 3%) is what stops every 15-minute print from spending a summary call for the same move.
    old_prints = prior.get("prints") or {}
    for m in moves:
        ext = m.get("extended") or {}
        if not m["held"] or ext.get("change_pct") is None:
            continue
        prior_row = old_prints.get(m["symbol"]) or [None, None]
        was = prior_row[0]
        # an UNKNOWN prior move cannot vouch that this one is quiet, so it does not suppress the crossing alert
        if prior_row[1] != ext.get("printed_at") and abs(ext["change_pct"]) >= MATERIAL_MOVE_PCT and (was is None or abs(was) < MATERIAL_MOVE_PCT):
            return {"changed": True, "material": True, "kind": "move", "symbol": m["symbol"],
                    "reason": f"{m['symbol']} {ext['change_pct']:+.1f}% {ext.get('session_label') or 'extended'}"}
    return {"changed": True, "material": False, "reason": "minor change", "kind": "minor"}


def newest_print_since(rows: Iterable[Mapping[str, Any]], symbols: Iterable[str], *, after: datetime) -> dict[str, Any] | None:
    """The newest extended print on one of ``symbols`` strictly after ``after``, or None (LQ-20261107-1304).

    Unlike :func:`attach_extended` this does not care whether the row carries a usable percentage: a print with an
    unreadable ``change_pct`` is still a print the card has not shown, and the trigger is the ROW CLOCK, never a
    dollar or percentage value -- an unpriced name must not read as "nothing moved".
    """
    want = {str(s).upper() for s in symbols}
    best: tuple[datetime, str, Mapping[str, Any]] | None = None
    for r in rows:
        sym = str(r.get("symbol") or "").upper()
        if sym not in want:
            continue
        at = _as_dt(r.get("bar_end"))
        if at is None or at <= after:
            continue
        if best is None or at > best[0]:
            best = (at, sym, r)
    if best is None:
        return None
    at, sym, row = best
    return {
        "symbol": sym,
        "bar_end": _iso(at),
        "printed_text": _print_time(at),
        "session_label": session_label(row.get("session")),
    }


def new_print_decision(
    prior: Mapping[str, Any] | None, moves: Sequence[Mapping[str, Any]], extended_rows: Iterable[Mapping[str, Any]]
) -> dict[str, Any]:
    """LQ-20261107-1304: rebuild (non-material) when a held/watch name printed after the snapshot was built.

    ``change_state()`` carries the newest print of each HELD name, so a held print usually rebuilds through the
    signature -- but a watchlist name's print does not move it, and neither does a held print whose rounded
    percentage repeats. Without this rule such a print sat in ``market_quotes_extended`` until the next forced
    rebuild, which is exactly the "no print since Friday" the operator reported. The rule is measured against the
    snapshot's OWN ``generated_at``: a rebuild never re-fires for the print it just showed.
    """
    gen = _as_dt((prior or {}).get("generated_at"))
    if gen is None:
        # an unreadable prior clock cannot vouch that no print has landed since: rebuild to establish one (cheap --
        # a print changes numbers, never the words, so no model call follows). Every snapshot this module writes
        # carries generated_at, so this is the legacy/hand-made case, and it self-heals on the next write.
        return {"changed": True, "material": False, "kind": "print", "symbol": None,
                "reason": "rebuilt to establish the prior clock"}
    hit = newest_print_since(extended_rows, [m["symbol"] for m in moves], after=gen)
    if hit is None:
        return {"changed": False, "material": False, "reason": "no new print", "kind": "none"}
    label = hit["session_label"] or "extended"
    return {"changed": True, "material": False, "kind": "print", "symbol": hit["symbol"],
            "reason": f"new {hit['symbol']} print {hit['printed_text']} {label}".strip()}


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
    source_clocks: Mapping[str, Any] | None = None,
    extended_rows: Iterable[Mapping[str, Any]] = (),
    index_labels: Mapping[str, str] | None = None,
) -> dict[str, Any] | None:
    """The whole card.  With ``if_changed`` returns None when nothing material moved since ``prior`` (no write, no LLM
    call).  A rebuild that is not material keeps the prior summary text; only a material one may spend a call."""
    win = window(now)
    close_at = datetime.fromisoformat(win["start"].replace("Z", "+00:00"))
    moves = attach_news(build_moves(ticker_snapshot, close_tag=win["close_tag"]), articles)
    moves = sort_by_now(attach_extended(moves, extended_rows, close_date=win["session_date"], close_at=close_at, now=now))
    state = change_state(moves, articles)
    if if_changed:
        decision = detect_change((prior or {}).get("change_state"), state, moves, articles)
        if not decision["changed"]:
            # LQ-20261107-1304: a print on a name the signature does not carry (a watchlist name, or a held print
            # repeating its rounded percentage) still makes the card stale -- rebuild it, without a model call.
            decision = new_print_decision(prior, moves, extended_rows)
        if not decision["changed"]:
            return None
    else:
        decision = {"changed": True, "material": True, "reason": "scheduled", "kind": "scheduled"}
    macro = build_macro(articles, futures)
    now_block = build_market_now(extended_rows, close_date=win["session_date"], close_at=close_at, now=now, labels=index_labels)
    if now_block["status"] == "available":
        # the futures/overseas block stops saying "pending" the moment the store has a print after the close
        macro["futures"] = {"status": "available", "quotes": now_block["futures"] + now_block["indices"], "as_of": now_block["as_of"]}
    macro["now"] = now_block
    cio_blk = cio_brief_block(cio_brief)
    summary = build_summary(
        moves, macro, now=now, llm=llm if decision["material"] else None,
        prior=(prior or {}).get("summary") if prior else None, calls_today=calls_today, carry_prior=not decision["material"],
    )
    feed = build_feed(moves, macro, cio_actions=_cio_actions(cio_brief), at_risk=_at_risk(cio_brief))
    if decision["kind"] in ("news", "move", "first", "print"):
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
        "cio_brief": cio_blk,
        "stamp": since_close_stamp.build_stamp(now=now, window=win, clocks={**(source_clocks or {}), "cio_brief": since_close_stamp.cio_clock(cio_brief)}),
        "feed": feed,
        "feed_rule": {"score": RANK_RULE, "urgency": URGENCY_RULE},
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


EXTENDED_SQL = """
SELECT upper(symbol) AS symbol, session, session_date, bar_start, bar_end, price,
       reference_close, reference_date, reference_basis, change_pct, feed
FROM market_quotes_extended
WHERE bar_end > %(since)s
  AND (upper(symbol) = ANY(%(symbols)s) OR symbol LIKE ANY(%(special)s))
ORDER BY bar_end DESC
LIMIT 5000
"""


def fetch_extended(conn: Any, *, symbols: Sequence[str], since: datetime) -> list[dict[str, Any]]:
    """Prints after the close (read-only SELECT): the held/watchlist names plus every futures root and cash index the
    extended-hours lane stores. ``sip`` and ``schwab`` rows are both returned; the newest print wins per symbol, which
    is the operator's question ("what moved"), not a provenance question."""
    with conn.cursor() as cur:
        cur.execute(EXTENDED_SQL, {"since": since, "symbols": [s.upper() for s in symbols], "special": ["/%", "$%"]})
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        v = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    return v if isinstance(v, dict) else None
