"""The deep brief's FACT PACK — everything the follow-up may say, built without a model.

Operator 2026-10-31: "the historical facts on what normally happens in the market when X is happening. Also, use the
other data sources so we can get a clear consensus on what's happening. You should also be looking at the options
market to see how people are hedging. Everything needs to be factored in, earnings, every particular catalyst."

``build_fact_pack`` returns a ``MarketRiskFactPack@v1``:

* ``facts`` — each with a citation ``id`` (letters only, so a citation is never mistaken for a number), ``section``,
  ``label``, the display ``text`` (the only place a figure may come from), ``source`` and ``as_of``;
* ``unknown`` — what was looked for and not found, with the reason (unknown is not zero);
* ``consensus`` — each source's directional read (``risk_up`` / ``risk_down`` / ``neutral``) with a confidence, the
  agreement share and the dissenting sources;
* ``exposure`` — the position stances copied verbatim from the deterministic CIO overlay when the snapshot carries
  them (the brief cites, never creates or strengthens a stance), else the book's symbols and stop distances.

Read-only. Market data comes through the engine's ``DataReader`` (as-of correct); the other sources through
``ExtraSources`` (``PgSources`` in production: SELECT-only, every row filtered to ``created_at <= now``). No size,
order, price target, weight or stop level is ever produced (MBI_BEHAVIOR = 0).
"""

from __future__ import annotations

import math
import re
import string
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any, Callable, Iterable, Optional

import yaml

from . import base_rates as br

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = PROJECT_ROOT / "config" / "market_risk_deep_brief.yaml"
SCHEMA = "MarketRiskFactPack@v1"
SECTION_PREFIX = {
    "happening": "now",
    "next": "hist",
    "hedging": "opt",
    "catalysts": "cat",
    "consensus": "cons",
    "change": "chg",
    "exposure": "pos",
}
SECTOR_NAMES = {
    "XLK": "Technology",
    "XLC": "Communication services",
    "XLY": "Consumer discretionary",
    "XLP": "Consumer staples",
    "XLV": "Healthcare",
    "XLU": "Utilities",
    "XLE": "Energy",
    "XLF": "Financials",
    "XLI": "Industrials",
    "XLB": "Materials",
    "XLRE": "Real estate",
    "SMH": "Semiconductors",
}


def load_config(path: Path | str = CONFIG_PATH) -> dict[str, Any]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if data.get("schema") != "MarketRiskDeepBrief@v1":
        raise ValueError(f"{path}: expected schema MarketRiskDeepBrief@v1, got {data.get('schema')!r}")
    return data


def _letters(n: int) -> str:
    """0 -> a, 25 -> z, 26 -> aa: citation ids never contain digits."""
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = string.ascii_lowercase[r] + s
    return s


def _iso(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).isoformat()
    return str(v)


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _pct(x: Optional[float], nd: int = 1) -> str:
    return "n/a" if x is None else f"{x:+.{nd}f}%"


class Pack:
    def __init__(self, now: datetime):
        self.now = now
        self.facts: list[dict[str, Any]] = []
        self.unknown: list[dict[str, Any]] = []
        self._seq: dict[str, int] = {}

    def add(self, section: str, label: str, text: str, *, source: str, as_of: Any = None, **extra: Any) -> str:
        pre = SECTION_PREFIX[section]
        i = self._seq.get(pre, 0)
        self._seq[pre] = i + 1
        fid = f"{pre}-{_letters(i)}"
        self.facts.append(
            {
                "id": fid,
                "section": section,
                "label": label,
                "text": text,
                "source": source,
                "as_of": _iso(as_of),
                **extra,
            }
        )
        return fid

    def miss(self, section: str, what: str, reason: str) -> None:
        self.unknown.append({"section": section, "what": what, "reason": reason})


# ── market data through the engine's reader ────────────────────────────────────────────────────────────────────
def _closes(reader: Any, symbols: Iterable[str], now: datetime, sessions: int = 260) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    try:
        rows = reader.daily_bars(list(symbols), sessions=sessions, end=now)
    except Exception:  # noqa: BLE001 — a reader gap is an UNKNOWN in the pack, never a crash of the follow-up
        return out
    for r in rows or []:
        c = _f(r.get("close"))
        if c is not None and r.get("symbol"):
            out.setdefault(str(r["symbol"]), []).append(
                {"date": str(r.get("date")), "close": c, "as_of": r.get("as_of")}
            )
    for s in out:
        out[s].sort(key=lambda x: x["date"])
    return out


def _happening(p: Pack, doc: dict, snap: dict, bars: dict[str, list[dict]]) -> None:
    tier = str(doc.get("tier") or "NONE")
    score = _f(doc.get("score"))
    p.add(
        "happening",
        "tier",
        f"Market risk {tier} {round(score) if score is not None else 'n/a'}/100, "
        f"{int(doc.get('confirming') or 0)} categories confirming",
        source="market_risk_engine",
        as_of=doc.get("as_of"),
    )
    for c in (doc.get("contributors") or [])[:5]:
        if isinstance(c, dict):
            pts = _f(c.get("points"))
            p.add(
                "happening",
                f"contributor {c.get('category')}",
                f"{c.get('category')}: {c.get('headline') or c.get('detail') or ''} "
                f"(+{round(pts) if pts is not None else 'n/a'} points)",
                source="market_risk_engine",
                as_of=c.get("as_of"),
            )
    shock = snap.get("shock_type") or doc.get("shock_type")
    if isinstance(shock, dict) and shock.get("class"):
        conf = _f(shock.get("confidence"))
        p.add(
            "happening",
            "shock type",
            f"Shock type {shock['class']}"
            + (f" (confidence {round(100 * conf) if conf <= 1 else round(conf)}%)" if conf is not None else ""),
            source="market_risk_engine.shock_type",
            as_of=shock.get("as_of") or doc.get("as_of"),
        )
    else:
        p.miss("happening", "shock type", "the engine snapshot carries no shock_type yet")
    sectors = snap.get("sectors") or doc.get("sectors")
    if isinstance(sectors, dict) and (sectors.get("stressed") or sectors.get("resilient")):
        for key in ("stressed", "resilient", "rotating"):
            names = [
                n
                for n in (
                    str(x.get("name") or x.get("group") or x) if isinstance(x, dict) else str(x)
                    for x in sectors.get(key) or []
                )
                if _SECTOR_NAME.match(n)  # a label, never free text with figures
            ]
            if names:
                p.add(
                    "happening",
                    f"sectors {key}",
                    f"{key.capitalize()}: {', '.join(names[:6])}",
                    source="market_risk_engine.sectors",
                    as_of=sectors.get("as_of") or doc.get("as_of"),
                )
    # Always add the raw 5-session sector moves from public closes: the evidence behind any sector statement.
    moves = []
    for etf in br.GROUPS:
        b = bars.get(etf) or []
        if len(b) >= 6:
            moves.append((b[-1]["close"] / b[-6]["close"] - 1.0, etf, b[-1]["as_of"]))
    if len(moves) >= 6:
        moves.sort()
        worst = ", ".join(f"{SECTOR_NAMES.get(e, e)} {_pct(100 * r)}" for r, e, _ in moves[:3])
        best = ", ".join(f"{SECTOR_NAMES.get(e, e)} {_pct(100 * r)}" for r, e, _ in moves[::-1][:3])
        p.add(
            "happening",
            "weakest groups 5d",
            f"Weakest 5-session groups: {worst}",
            source="daily_bars",
            as_of=moves[0][2],
        )
        p.add(
            "happening",
            "strongest groups 5d",
            f"Strongest 5-session groups: {best}",
            source="daily_bars",
            as_of=moves[-1][2],
        )
    else:
        p.miss("happening", "sector moves", "fewer than six sector ETFs have daily closes in the reader")


def _next(p: Pack, bars: dict[str, list[dict]], snap: dict, cfg: dict) -> dict[str, Any]:
    closes = {s: [x["close"] for x in v] for s, v in bars.items()}
    feats = br.features_at(closes)
    try:
        table = br.load_table()
    except (OSError, ValueError) as exc:
        p.miss("next", "base rates", f"table unavailable ({type(exc).__name__})")
        return feats
    group = None
    sectors = snap.get("sectors") if isinstance(snap.get("sectors"), dict) else {}
    for x in sectors.get("stressed") or []:
        g = (x.get("etf") or x.get("symbol")) if isinstance(x, dict) else None
        if g in br.GROUPS:
            group = g
            break
    group = group or feats.get("worst5")
    res = br.conditional(feats, min_n=int(cfg.get("min_n") or 20), group=group, table=table)
    conds = ", ".join(f"{k}={v}" for k, v in res.get("conditions", {}).items()) or "none"
    if res.get("insufficient_history"):
        p.miss("next", "base rates", f"insufficient history for conditions [{conds}] (n<{res['min_n']})")
        return feats
    n = res["n_days"]
    p.add(
        "next",
        "conditions",
        f"Matched {n} past trading days 2016-2025 on [{conds}]"
        + (f"; dropped [{', '.join(res['dropped'])}] to reach n>={res['min_n']}" if res["dropped"] else ""),
        source="base_rates_table (public daily closes, 2026 held out)",
        as_of=res.get("table_as_of"),
    )
    for sym in ("SPY", "QQQ"):
        for h in ("5d", "20d"):
            d = res[sym][h]
            if d.get("n", 0) >= res["min_n"]:
                p.add(
                    "next",
                    f"{sym} {h}",
                    f"{sym} next {h[:-1]} sessions: median {_pct(d['median_pct'], 2)}, "
                    f"10th pct {_pct(d['p10_pct'], 2)}, 90th pct {_pct(d['p90_pct'], 2)}, "
                    f"lower in {d['share_negative_pct']}% of cases (n={d['n']})",
                    source="base_rates_table",
                    as_of=res.get("table_as_of"),
                )
    if group and isinstance(res.get(group), dict):
        d = res[group]["20d"]
        if d.get("n", 0) >= res["min_n"]:
            p.add(
                "next",
                f"{group} 20d",
                f"{SECTOR_NAMES.get(group, group)} next 20 sessions: median {_pct(d['median_pct'], 2)}, "
                f"lower in {d['share_negative_pct']}% of cases (n={d['n']})",
                source="base_rates_table",
                as_of=res.get("table_as_of"),
            )
    drop = res["spy_further_5pct_drop_within_20d"]
    if drop.get("hit_rate_pct") is not None and drop["n"] >= res["min_n"]:
        p.add(
            "next",
            "further drop",
            f"A further 5% SPY drop within 20 sessions followed in {drop['hit_rate_pct']}% of cases (n={drop['n']})",
            source="base_rates_table",
            as_of=res.get("table_as_of"),
        )
    tr, rc = res["spy_sessions_to_trough_within_60d"], res["spy_sessions_to_recover"]
    if tr.get("median") is not None and tr["n"] >= res["min_n"]:
        p.add(
            "next",
            "trough timing",
            f"Median sessions to the lowest close of the next 60 sessions: {tr['median']} (n={tr['n']}). After that "
            f"low, SPY closed back at or above the starting level within 120 sessions of the start in "
            f"{rc['recovered_within_120d']} of {rc['n']} cases, a median {rc['median']} sessions after the low",
            source="base_rates_table",
            as_of=res.get("table_as_of"),
        )
    an = br.analogs(feats, table=table)
    if an:
        p.add(
            "next",
            "analogs",
            "Nearest past setups (explanation only, never scored): "
            + "; ".join(
                f"{a['date']} ({a['pattern']}, SPY next 20 sessions {_pct(a['spy_next_20d_pct'], 2)})" for a in an
            ),
            source="base_rates_table",
            as_of=res.get("table_as_of"),
        )
    return feats


def _hedging(
    p: Pack, reader: Any, now: datetime, bars: dict[str, list[dict]], held: list[str], sources: Any, cfg: dict
):
    look = int(cfg.get("option_lookback_sessions") or 20)
    try:
        rows = reader.option_snapshots(["SPY", "QQQ"] + held, sessions=look + 1, end=now) or []
    except Exception as exc:  # noqa: BLE001
        p.miss("hedging", "index options", f"reader failed ({type(exc).__name__})")
        rows = []
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(str(r.get("symbol")), []).append(r)
    reads: dict[str, float] = {}
    for sym in ["SPY", "QQQ"] + held:
        rs = sorted(by.get(sym) or [], key=lambda r: str(r.get("as_of")))
        if not rs:
            if sym in ("SPY", "QQQ"):
                p.miss("hedging", f"{sym} options", "no option chain snapshot in the lookback")
            continue
        last, hist = rs[-1], rs[:-1][-look:]
        parts = []
        for key, label in (("pc_vol_ratio", "put/call volume"), ("pc_oi_ratio", "put/call open interest")):
            v = _f(last.get(key))
            med = median([x for x in (_f(h.get(key)) for h in hist) if x is not None] or [float("nan")])
            if v is None:
                continue
            if math.isfinite(med) and med > 0:
                parts.append(f"{label} {v:.2f} vs {med:.2f} median ({v / med:.1f}x)")
                if key == "pc_vol_ratio" and sym in ("SPY", "QQQ"):
                    reads[sym] = v / med
            else:
                parts.append(f"{label} {v:.2f}")
        iv, sk = _f(last.get("atm_iv")), _f(last.get("skew25"))
        if iv is not None:
            ivp = iv * 100 if iv < 3 else iv
            b = [x["close"] for x in bars.get(sym) or []][-21:]
            if len(b) >= 21:
                lr = [math.log(b[i] / b[i - 1]) for i in range(1, len(b))]
                mu = sum(lr) / len(lr)
                rv = math.sqrt(sum((x - mu) ** 2 for x in lr) / (len(lr) - 1)) * math.sqrt(252) * 100
                parts.append(f"ATM implied vol {ivp:.1f}% vs 20-session realized {rv:.1f}%")
            else:
                parts.append(f"ATM implied vol {ivp:.1f}%")
        if sk is not None:
            parts.append(f"25-delta skew {sk:.3f}")
        if parts:
            p.add(
                "hedging",
                f"{sym} options",
                f"{sym}: " + "; ".join(parts),
                source="option_chain_snapshots",
                as_of=last.get("as_of"),
            )
    term = {s: (bars.get(s) or [None])[-1] for s in ("^VIX9D", "^VIX", "^VIX3M", "^VVIX")}
    if term.get("^VIX") and term.get("^VIX3M"):
        v, v3 = term["^VIX"]["close"], term["^VIX3M"]["close"]
        txt = f"VIX {v:.2f} vs VIX3M {v3:.2f} (ratio {v / v3:.2f}, {'inverted' if v / v3 > 1 else 'normal'} term structure)"
        if term.get("^VIX9D"):
            txt += f"; VIX9D {term['^VIX9D']['close']:.2f}"
        if term.get("^VVIX"):
            txt += f"; VVIX {term['^VVIX']['close']:.2f}"
        p.add("hedging", "vol term structure", txt, source="daily_bars", as_of=term["^VIX"]["as_of"])
    else:
        p.miss("hedging", "VIX term structure", "VIX3M or VIX closes not in the reader")
    p.miss("hedging", "SKEW index", "no ^SKEW series in the reader")
    p.miss("hedging", "dealer gamma", "no per-strike open-interest store (option_chain_strikes is not built)")
    if held and not any(by.get(s) for s in held):
        p.miss("hedging", "held-name options", f"no chain snapshots for held names ({', '.join(held[:8])})")
    soc = _safe(lambda: sources.social(now - timedelta(hours=int(cfg.get("social_window_hours") or 72)), now))
    if soc and (soc.get("bullish") or 0) + (soc.get("bearish") or 0) > 0:
        share = soc["bullish"] / (soc["bullish"] + soc["bearish"])
        hedge = max(reads.values()) if reads else None
        p.add(
            "hedging",
            "retail vs hedging",
            f"Social bullish share {100 * share:.0f}% over {int(cfg.get('social_window_hours') or 72)}h "
            f"({soc['bullish']} bullish, {soc['bearish']} bearish)"
            + (f" while index put/call volume runs {hedge:.1f}x its median" if hedge is not None else ""),
            source="social_sentiment_history",
            as_of=soc.get("as_of"),
        )
        reads["_social_share"] = share
    else:
        p.miss("hedging", "social sentiment", "no social sentiment rows in the window")
    go = _safe(lambda: sources.scalp_go(now - timedelta(hours=24), now))
    if go and go.get("total"):
        p.add(
            "hedging",
            "scalp GO",
            f"Scalp scanner GO decisions in 24h: {go['go']} of {go['total']} scans",
            source="scalp_scan_results",
            as_of=go.get("as_of"),
        )
    return reads


def _next_sessions(now: datetime, n: int, sess: Any) -> list:
    """The next ``n`` NYSE sessions starting with today's when it has not closed yet (holiday-aware)."""
    from zoneinfo import ZoneInfo

    et = now.astimezone(ZoneInfo("America/New_York"))
    d = et.date()
    out = []
    if sess.is_trading_day(d) and et.time() < sess.close_time(d):
        out.append(d)
    while len(out) < n:
        d = d + timedelta(days=1)
        if sess.is_trading_day(d):
            out.append(d)
    return out


def _safe(fn: Callable[[], Any]) -> Any:
    try:
        return fn()
    except Exception:  # noqa: BLE001 — a missing source is reported by the caller as UNKNOWN
        return None


def _catalysts(p: Pack, reader: Any, now: datetime, held: list[str], sources: Any, doc: dict, cfg: dict) -> dict:
    out: dict[str, Any] = {}
    from . import sessions as sess

    horizon_days = 16
    names = list(dict.fromkeys(held + list(cfg.get("heavyweights") or [])))
    try:
        ev = reader.earnings_calendar(start=now, end=now + timedelta(days=horizon_days), now=now) or []
    except TypeError:
        ev = reader.earnings_calendar(start=now, end=now + timedelta(days=horizon_days)) or []
    except Exception as exc:  # noqa: BLE001
        ev = []
        p.miss("catalysts", "earnings calendar", f"reader failed ({type(exc).__name__})")
    days = _next_sessions(now, max(int(x) for x in (cfg.get("lookahead_sessions") or [10])), sess)
    buckets: dict[int, list[str]] = {int(n): [] for n in (cfg.get("lookahead_sessions") or [1, 3, 5, 10])}
    from zoneinfo import ZoneInfo

    today = now.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    tonight: list[str] = []
    for r in ev:
        sym = str(r.get("symbol") or "")
        when = str(r.get("at") or r.get("date") or "")[:10]
        if not sym or sym not in names:
            continue
        if when == today and (not days or days[0].isoformat() > today):
            tonight.append(sym)  # today's session has closed: these report after today's close
            continue
        idx = next((i + 1 for i, d in enumerate(days) if d.isoformat() >= when), None) if days else None
        for n in buckets:
            if idx is not None and idx <= n:
                buckets[n].append(f"{sym} ({when})")
                break
    any_earn = bool(tonight)
    if tonight:
        p.add(
            "catalysts",
            "earnings tonight",
            f"Reporting after today's close ({today}): {', '.join(tonight)}",
            source="earnings_calendar",
            as_of=now,
        )
    for n, lst in sorted(buckets.items()):
        if lst:
            any_earn = True
            p.add(
                "catalysts",
                f"earnings {n} sessions",
                f"Earnings within {n} session{'s' if n > 1 else ''} among held and index heavyweight names: "
                + ", ".join(lst[:10]),
                source="earnings_calendar",
                as_of=now,
            )
    if not any_earn:
        p.miss("catalysts", "earnings", "no held or heavyweight earnings found in the next ten sessions")
    try:
        try:
            mac = reader.macro_calendar(start=now, end=now + timedelta(days=horizon_days), now=now) or []
        except TypeError:
            mac = reader.macro_calendar(start=now, end=now + timedelta(days=horizon_days)) or []
    except Exception:  # noqa: BLE001
        mac = []
    if mac:
        p.add(
            "catalysts",
            "macro",
            "Macro calendar: "
            + "; ".join(
                f"{m.get('name') or m.get('event')} {str(m.get('at') or m.get('date') or '')[:10]}" for m in mac[:6]
            ),
            source="macro_calendar",
            as_of=mac[0].get("as_of"),
        )
    else:
        p.miss("catalysts", "macro calendar", "no macro events in the reader for the next two weeks")
    cats = _safe(lambda: sources.catalysts(names, now - timedelta(hours=72), now)) or []
    if cats:
        top = sorted(cats, key=lambda c: -(_f(c.get("impact_score")) or _f(c.get("severity")) or 0))[:5]
        labels = cfg.get("catalyst_labels") or {}
        parts = [
            f"{c.get('symbol')} {labels.get(str(c.get('catalyst_type') or ''), 'other event')}"
            for c in top
            if _SYMBOL.match(str(c.get("symbol") or ""))
        ]
        # headlines are never rendered (review of #2410, N3: advice words, targets, $ and % ride in them); counted
        hidden = sum(1 for c in top if str(c.get("headline") or "").strip())
        p.add(
            "catalysts",
            "company catalysts",
            "Company catalysts in 72h: " + "; ".join(parts) + _withheld(hidden, "headline"),
            source="catalyst_events",
            as_of=max(str(c.get("created_at")) for c in top),
        )
    else:
        p.miss("catalysts", "company catalysts", "no catalyst_events rows for held or heavyweight names in 72h")
    mc = _safe(lambda: sources.material_changes(names, now - timedelta(hours=72), now)) or []
    if mc:
        p.add(
            "catalysts",
            "material changes",
            "Material changes in 72h: "
            + "; ".join(
                f"{m.get('symbol')} {(cfg.get('material_change_labels') or {}).get(str(m.get('kind') or ''), 'other change')}"
                for m in mc[:5]
                if _SYMBOL.match(str(m.get("symbol") or ""))
            ),
            source="material_changes",
            as_of=max(str(m.get("created_at")) for m in mc),
        )
    news = _safe(lambda: sources.news(names, now - timedelta(hours=int(cfg.get("news_window_hours") or 72)), now)) or []
    scores = [x for x in (_f(n.get("sentiment_score")) for n in news) if x is not None]
    if scores:
        out["news_tone"] = sum(scores) / len(scores)
        p.add(
            "catalysts",
            "news tone",
            f"News tone on held and heavyweight names over {int(cfg.get('news_window_hours') or 72)}h: "
            f"mean sentiment {out['news_tone']:+.2f} across {len(scores)} articles",
            source="news_articles",
            as_of=max(str(n.get("created_at")) for n in news),
        )
    else:
        p.miss("catalysts", "news tone", "no scored news for held or heavyweight names in the window")
    rev = _safe(lambda: sources.analyst_revisions(names, now)) or []
    ch = [
        _f(r.get("tgt_now")) / _f(r.get("tgt_then")) - 1.0
        for r in rev
        if _f(r.get("tgt_now")) is not None and _f(r.get("tgt_then"))
    ]
    if ch:
        out["analyst_change"] = sum(ch) / len(ch)
        p.add(
            "catalysts",
            "analyst revisions",
            f"Consensus price targets over 20 days across {len(ch)} names: mean change {_pct(100 * out['analyst_change'])}",
            source="analyst_consensus_history",
            as_of=max(str(r.get("as_of")) for r in rev),
        )
    else:
        p.miss("catalysts", "analyst revisions", "no analyst consensus history for the names")
    hz = _safe(lambda: sources.hermes_events(now - timedelta(hours=24), now))
    if hz and hz.get("total"):
        p.add(
            "catalysts",
            "hermes",
            f"Hermes advisory events in 24h: {hz['total']}"
            + (
                f" ({', '.join(f'{k} {v}' for k, v in sorted(hz.get('by_priority', {}).items()))})"
                if hz.get("by_priority")
                else ""
            ),
            source="hermes_advisory_events",
            as_of=hz.get("as_of"),
        )
    for o in doc.get("observations") or []:
        if isinstance(o, dict) and o.get("category") == "seasonal" and o.get("state") != "UNKNOWN":
            p.add(
                "catalysts",
                "seasonality",
                f"Seasonality: {o.get('headline')}",
                source="market_risk_engine",
                as_of=o.get("observed_at"),
            )
    return out


DIRS = ("risk_up", "risk_down", "neutral")


def _consensus(p: Pack, doc: dict, reads: dict, cat: dict, snap: dict, cfg: dict) -> dict:
    c = cfg.get("consensus") or {}
    obs = {o.get("category"): o for o in doc.get("observations") or [] if isinstance(o, dict)}
    votes: list[dict] = []

    def cat_vote(src: str, category: str) -> None:
        o = obs.get(category)
        if not o or o.get("state") in (None, "UNKNOWN"):
            p.miss("consensus", src, f"{category} not measured")
            return
        st = o["state"]
        d = "risk_up" if st in ("WARN", "STRESS") else "risk_down" if st == "IMPROVING" else "neutral"
        votes.append(
            {"source": src, "direction": d, "confidence": 0.8 if st == "STRESS" else 0.5, "basis": f"{category} {st}"}
        )

    tier = str(doc.get("tier") or "NONE").upper()
    rank = {"GREEN": -1, "NONE": 0, "BLUE": 0, "YELLOW": 1, "ORANGE": 2, "RED": 3}.get(tier, 0)
    votes.append(
        {
            "source": "engine",
            "direction": "risk_up" if rank >= 1 else "risk_down" if rank < 0 else "neutral",
            "confidence": min(1.0, (_f(doc.get("score")) or 0) / 100),
            "basis": f"tier {tier}",
        }
    )
    hedge = max([v for k, v in reads.items() if not k.startswith("_")] or [0.0])
    if reads and any(not k.startswith("_") for k in reads):
        warn = float(c.get("pc_vol_warn_factor") or 1.5)
        votes.append(
            {
                "source": "options",
                "direction": "risk_up" if hedge >= warn else "neutral",
                "confidence": 0.8 if hedge >= 2 * warn else 0.5,
                "basis": f"index put/call volume {hedge:.1f}x median",
            }
        )
    else:
        p.miss("consensus", "options", "no index put/call history")
    cat_vote("breadth", "breadth")
    cat_vote("credit", "macro_credit")
    nt = cat.get("news_tone")
    if nt is not None:
        band = float(c.get("news_tone_band") or 0.1)
        votes.append(
            {
                "source": "news",
                "direction": "risk_up" if nt <= -band else "risk_down" if nt >= band else "neutral",
                "confidence": 0.4,
                "basis": f"mean sentiment {nt:+.2f}",
            }
        )
    ac = cat.get("analyst_change")
    if ac is not None:
        band = float(c.get("analyst_target_band") or 0.02)
        votes.append(
            {
                "source": "analysts",
                "direction": "risk_up" if ac <= -band else "risk_down" if ac >= band else "neutral",
                "confidence": 0.4,
                "basis": f"price targets {_pct(100 * ac)}",
            }
        )
    ss = reads.get("_social_share")
    if ss is not None:
        votes.append(
            {
                "source": "social",
                "direction": "risk_down" if ss >= float(c.get("social_bullish_hi") or 0.6) else "neutral",
                "confidence": 0.3,
                "basis": f"bullish share {100 * ss:.0f}%",
            }
        )
    cio = snap.get("cio") if isinstance(snap.get("cio"), dict) else None
    if cio and cio.get("posture"):
        # Allowlist (review of #2410 round 3, B3): the posture is CIO free text from another store, like the stance
        # reasons fixed under B1. Only a name from the fixed `posture_names` vocabulary is rendered or read; anything
        # else ("Trim half above one ninety") is withheld and votes neutral.
        raw = re.sub(r"[\s-]+", "_", str(cio["posture"]).strip().upper())
        known = {str(x).upper() for x in c.get("posture_names") or []}
        post = raw.replace("_", " ") if raw in known else "unrecognised (1 detail withheld)"
        defensive = {str(x).upper() for x in c.get("posture_risk_up") or []}
        votes.append(
            {
                "source": "cio",
                "direction": "risk_up" if raw in known and raw in defensive else "neutral",
                "confidence": 0.5,
                "basis": f"CIO posture {post}",
            }
        )
    else:
        p.miss("consensus", "cio", "the snapshot carries no CIO posture")
    weight = {d: sum(v["confidence"] for v in votes if v["direction"] == d) for d in DIRS}
    total = sum(weight.values()) or 1.0
    major = max(DIRS, key=lambda d: (weight[d], d == "neutral"))
    opposite = {"risk_up": "risk_down", "risk_down": "risk_up"}.get(major)
    dissent = [v["source"] for v in votes if opposite and v["direction"] == opposite]
    agreement = round(100 * weight[major] / total)
    readable = {"risk_up": "risk rising", "risk_down": "risk easing", "neutral": "no clear direction"}
    p.add(
        "consensus",
        "agreement",
        f"{len(votes)} sources read: {agreement}% of the weight says {readable[major]}"
        + (f"; dissenting: {', '.join(dissent)}" if dissent else "; no source dissents"),
        source="deep_brief_consensus",
        as_of=p.now,
    )
    for v in votes:
        p.add(
            "consensus",
            f"vote {v['source']}",
            f"{v['source']}: {readable[v['direction']]} ({v['basis']})",
            source="deep_brief_consensus",
            as_of=p.now,
        )
    return {"votes": votes, "majority": major, "agreement_pct": agreement, "dissent": dissent}


def _change(p: Pack, doc: dict) -> None:
    if doc.get("deescalates_if"):
        p.add(
            "change",
            "de-escalation",
            f"De-escalates if {doc['deescalates_if']}",
            source="market_risk_engine",
            as_of=doc.get("as_of"),
        )
    calm = [
        o.get("category") for o in doc.get("observations") or [] if isinstance(o, dict) and o.get("state") == "CALM"
    ]
    if calm:
        p.add(
            "change",
            "not yet stressed",
            "Categories still calm (a turn to stress here would widen the picture): " + ", ".join(calm),
            source="market_risk_engine",
            as_of=doc.get("as_of"),
        )


_SYMBOL = re.compile(r"^[A-Z][A-Z0-9._-]{0,9}$")
_SECTOR_NAME = re.compile(r"^[A-Za-z][A-Za-z &/-]{0,39}$")


def _withheld(n: int, what: str = "detail") -> str:
    return f" ({n} {what}{'s' if n > 1 else ''} withheld)" if n else ""


def _exposure(p: Pack, doc: dict, snap: dict, cfg: dict) -> list[dict]:
    stances = snap.get("stances") or snap.get("positions_stances") or doc.get("stances")
    out: list[dict] = []
    if isinstance(stances, list) and stances:
        for s in stances[:12]:
            if not isinstance(s, dict) or not _SYMBOL.match(str(s.get("symbol") or "")):
                continue
            # Allowlist (review of #2410, B1): the stance NAME from a fixed vocabulary and nothing else. Free-text
            # reasons and re-entry conditions are never rendered — "Half position until earnings clear" or "Price back
            # above one ninety-five" carry sizing or levels no filter can be trusted to catch. They are counted.
            stance = str(s.get("stance") or "").upper()
            known = {str(x).upper() for x in cfg.get("stance_names") or []}
            withheld = len([r for r in (s.get("reasons") or []) if str(r).strip()]) + int(bool(s.get("re_enter_if")))
            if stance not in known:
                stance, withheld = "unrecognised", withheld + 1
            text = f"{s['symbol']}: CIO stance {stance}{_withheld(withheld)}"
            p.add(
                "exposure",
                f"stance {s['symbol']}",
                text,
                source="cio_overlay",
                as_of=s.get("as_of") or snap.get("as_of"),
            )
            out.append({"symbol": s["symbol"], "stance": stance})
        return out
    port = doc.get("portfolio") if isinstance(doc.get("portfolio"), dict) else {}
    drivers = [d for d in port.get("drivers") or [] if isinstance(d, dict) and d.get("symbol")]
    if drivers:
        p.add(
            "exposure",
            "book drivers",
            "Positions driving book vulnerability: "
            + ", ".join(
                f"{d['symbol']}"
                + (
                    f" (stop {abs(_f(d['stop_distance_pct'])):.1f}% away)"
                    if _f(d.get("stop_distance_pct")) is not None
                    else ""
                )
                for d in drivers[:8]
            ),
            source="market_risk_engine.portfolio",
            as_of=port.get("as_of"),
        )
    p.miss("exposure", "position stances", "the CIO overlay has not published stances in the snapshot yet")
    return out


def held_symbols(doc: dict, snap: dict) -> list[str]:
    syms = [
        str(d.get("symbol"))
        for d in ((doc.get("portfolio") or {}).get("drivers") or [])
        if isinstance(d, dict) and d.get("symbol")
    ]
    syms += [str(s.get("symbol")) for s in (snap.get("stances") or []) if isinstance(s, dict) and s.get("symbol")]
    return list(dict.fromkeys(syms))


def build_fact_pack(
    now: datetime,
    reader: Any,
    doc: dict,
    *,
    snapshot: Optional[dict] = None,
    sources: Any = None,
    cfg: Optional[dict] = None,
) -> dict[str, Any]:
    """Every fact the deep brief may state, each cited, with what is missing listed. Deterministic and read-only."""
    cfg = cfg if cfg is not None else load_config()
    snap = snapshot if isinstance(snapshot, dict) else {}
    sources = sources if sources is not None else NullSources()
    p = Pack(now)
    held = held_symbols(doc, snap)
    bars = _closes(reader, ("SPY", "QQQ", "SOXX", "SMH", "^VIX", "^VIX9D", "^VIX3M", "^VVIX") + br.SECTOR_ETFS, now)
    _happening(p, doc, snap, bars)
    feats = _next(p, bars, snap, cfg)
    reads = _hedging(p, reader, now, bars, held, sources, cfg) or {}
    cat = _catalysts(p, reader, now, held, sources, doc, cfg)
    cons = _consensus(p, doc, reads, cat, snap, cfg)
    _change(p, doc)
    exposure = _exposure(p, doc, snap, cfg)
    return {
        "schema": SCHEMA,
        "as_of": now.isoformat(),
        "tier": doc.get("tier"),
        "assessment_as_of": doc.get("as_of"),
        "features": {k: v for k, v in feats.items() if not isinstance(v, float) or math.isfinite(v)},
        "facts": p.facts,
        "unknown": p.unknown,
        "consensus": cons,
        "exposure": exposure,
    }


# ── the other sources ─────────────────────────────────────────────────────────────────────────────────────────
class NullSources:
    """No extra sources (tests, replays without a DB): every method returns nothing and the pack says UNKNOWN."""

    def social(self, start, end):
        return None

    def scalp_go(self, start, end):
        return None

    def news(self, symbols, start, end):
        return []

    def catalysts(self, symbols, start, end):
        return []

    def material_changes(self, symbols, start, end):
        return []

    def analyst_revisions(self, symbols, end):
        return []

    def hermes_events(self, start, end):
        return None


class PgSources:
    """SELECT-only reads of the existing stores; every row filtered to ``created_at <= end`` so a replay never sees
    what was written later. Reuses the engine reader's read-only connection when one is given."""

    def __init__(self, pg_reader: Any = None):
        if pg_reader is None:
            from .reader import PgReader

            pg_reader = PgReader()
        self._r = pg_reader

    def _rows(self, sql: str, params: list) -> list[dict]:
        return self._r._rows(sql, params)  # noqa: SLF001 — same read-only session as the engine reader

    def social(self, start, end):
        r = self._rows(
            "SELECT COALESCE(SUM(bullish_count),0) AS bullish, COALESCE(SUM(bearish_count),0) AS bearish, "
            "MAX(observed_at) AS as_of FROM social_sentiment_history WHERE observed_at > %s AND observed_at <= %s",
            [start, end],
        )
        row = r[0] if r else {}
        return {
            "bullish": int(row.get("bullish") or 0),
            "bearish": int(row.get("bearish") or 0),
            "as_of": _iso(row.get("as_of")),
        }

    def scalp_go(self, start, end):
        r = self._rows(
            "SELECT COUNT(*) FILTER (WHERE upper(decision)='GO') AS go, COUNT(*) AS total, MAX(scanned_at) AS as_of "
            "FROM scalp_scan_results WHERE scanned_at > %s AND scanned_at <= %s",
            [start, end],
        )
        row = r[0] if r else {}
        return {"go": int(row.get("go") or 0), "total": int(row.get("total") or 0), "as_of": _iso(row.get("as_of"))}

    def news(self, symbols, start, end):
        if not symbols:
            return []
        return self._rows(
            "SELECT symbol, COALESCE(sentiment_score, CASE lower(sentiment) WHEN 'positive' THEN 1.0 "
            "WHEN 'negative' THEN -1.0 WHEN 'neutral' THEN 0.0 END) AS sentiment_score, published_at, created_at "
            "FROM news_articles WHERE symbol = ANY(%s) AND published_at > %s AND created_at <= %s "
            "AND COALESCE(is_duplicate,false) = false AND (sentiment_score IS NOT NULL OR sentiment IS NOT NULL) "
            "ORDER BY published_at DESC LIMIT 500",
            [list(symbols), start, end],
        )

    def catalysts(self, symbols, start, end):
        if not symbols:
            return []
        return self._rows(
            "SELECT symbol, catalyst_type, headline, severity, impact_score, published_at, created_at FROM catalyst_events "
            "WHERE symbol = ANY(%s) AND published_at > %s AND created_at <= %s ORDER BY published_at DESC LIMIT 100",
            [list(symbols), start, end],
        )

    def material_changes(self, symbols, start, end):
        if not symbols:
            return []
        return self._rows(
            "SELECT symbol, kind, magnitude, observed_at, authority, created_at FROM material_changes "
            "WHERE symbol = ANY(%s) AND observed_at > %s AND created_at <= %s ORDER BY observed_at DESC LIMIT 50",
            [list(symbols), start, end],
        )

    def analyst_revisions(self, symbols, end):
        """Mean consensus price-target change over 20 days (recommendation scores are mostly empty in the store)."""
        if not symbols:
            return []
        now_rows = self._rows(
            "SELECT DISTINCT ON (symbol) symbol, target_price AS tgt_now, snapshot_date AS as_of FROM analyst_consensus_history "
            "WHERE symbol = ANY(%s) AND created_at <= %s AND target_price IS NOT NULL ORDER BY symbol, snapshot_date DESC",
            [list(symbols), end],
        )
        then = {
            r["symbol"]: r["tgt_then"]
            for r in self._rows(
                "SELECT DISTINCT ON (symbol) symbol, target_price AS tgt_then FROM analyst_consensus_history "
                "WHERE symbol = ANY(%s) AND created_at <= %s AND snapshot_date <= (%s::date - 20) "
                "AND target_price IS NOT NULL ORDER BY symbol, snapshot_date DESC",
                [list(symbols), end, end],
            )
        }
        return [
            dict(r, tgt_then=then[r["symbol"]], as_of=_iso(r.get("as_of"))) for r in now_rows if then.get(r["symbol"])
        ]

    def hermes_events(self, start, end):
        rows = self._rows(
            "SELECT priority, COUNT(*) AS n, MAX(created_at) AS as_of FROM hermes_advisory_events "
            "WHERE created_at > %s AND created_at <= %s GROUP BY priority",
            [start, end],
        )
        return {
            "total": sum(int(r["n"]) for r in rows),
            "by_priority": {str(r["priority"]): int(r["n"]) for r in rows},
            "as_of": max((_iso(r["as_of"]) or "" for r in rows), default=None),
        }
