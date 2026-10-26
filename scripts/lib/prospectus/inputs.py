"""Assemble a prospectus's inputs from ALL house sources (CC data broker rule: no per-process market fetch).

Operator 2026-10-26: "use ALL internal sources plus whatever external sources it needs". The house set is the full
``subject_dossier`` source set (symbol_profiles incl. EPS + next earnings, analyst view, catalyst_events, news, house
agents and final synthesis, IV, dividends, sector momentum + industry group runtime files, house research, symbol
thesis) plus the CIO record (stance, conviction, origin / lineage), the position store (positions, basis, stops +
stop state, journal trades), options theses, the Finviz enrichment cache (fundamentals, ownership, peers), the
price store (ticker + SPY/QQQ/sector ETF benchmarks, OHLC) and, for funds, the look-through holdings and sector
weights. Fresh web context is fetched later, by the model's bounded search loop (``generate.write``).

Every fact carries a citation id (F1, F2 …), its source store and ``as_of``. Derived numbers (upside to target, 1-year
change, distance to stop, P/L %, the institutional blocks) are computed here and supplied as facts, so the text never
needs arithmetic of its own. Every source attempted is recorded in ``coverage`` as used / empty / stale / failed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
import json
from pathlib import Path
import statistics
from typing import Any, Callable, Iterable, Optional

from . import blocks as bk
from . import store

VALUATION_KEYS = (("pe", "P/E"), ("forward_pe", "Forward P/E"), ("ps", "P/S"), ("pb", "P/B"), ("peg", "PEG"))
GROWTH_KEYS = (("sales_growth_past_5y_pct", "Sales growth, past 5y %"), ("eps_growth_past_5y_pct", "EPS growth, past 5y %"),
               ("eps_growth_this_y_pct", "EPS growth, this year %"), ("eps_growth_next_y_pct", "EPS growth, next year %"),
               ("eps_growth_next_5y_pct", "EPS growth, next 5y %"))
PROFILE_KEYS = (("market_cap_b", "Market cap ($B)"), ("gross_margin_pct", "Gross margin %"),
                ("oper_margin_pct", "Operating margin %"), ("profit_margin_pct", "Profit margin %"),
                ("roe_pct", "ROE %"), ("roic_pct", "ROIC %"), ("total_debt_equity", "Debt/Equity"),
                ("div_yield_pct", "Dividend yield %"), ("beta", "Beta"), ("perf_ytd_pct", "Performance YTD %"),
                ("week52_high_pct", "Distance from 52-week high %"))
#: Sources whose absence makes a prospectus "partial" (named in the gap); everything else is a recorded gap only.
KEY_SOURCES = ("price_history", "fundamentals", "dossier_profile", "cio_record")
KEY_SOURCES_HOLDING = KEY_SOURCES + ("position",)
STALE_DAYS = {"price_history": 5, "fundamentals": 14, "analyst_targets": 30, "fund_lookthrough": 120}


def _f(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out and abs(out) != float("inf") else None


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _age_days(as_of: Any, now: datetime) -> Optional[int]:
    try:
        d = datetime.fromisoformat(str(as_of).replace("Z", "+00:00")[:25])
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(str(as_of)[:10])
        except (TypeError, ValueError):
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return (now - d).days


@dataclass
class Bundle:
    symbol: str
    scope: str
    name: str
    facts: list[dict] = field(default_factory=list)
    series: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    gaps: list[str] = field(default_factory=list)
    coverage: list[dict] = field(default_factory=list)
    blocks: dict[str, Any] = field(default_factory=dict)

    def add(self, kind: str, label: str, *, value: Any = None, text: str | None = None, unit: str = "",
            source: str, as_of: Any = None, url: str | None = None) -> Optional[str]:
        num = _f(value)
        if num is None and not (text and str(text).strip()):
            return None
        fid = f"F{len(self.facts) + 1}"
        row = {"id": fid, "kind": kind, "label": label, "source": source, "as_of": _iso(as_of)}
        if num is not None:
            row["value"] = round(num, 4)
            row["unit"] = unit
        if text:
            row["text"] = str(text).strip()[:400]
        if url and str(url).startswith(("http://", "https://")):
            row["url"] = str(url)[:500]
        self.facts.append(row)
        return fid

    def values(self) -> list[float]:
        return [f["value"] for f in self.facts if "value" in f]

    def citation(self, fid: str) -> Optional[dict]:
        for f in self.facts:
            if f["id"] == fid:
                return {k: f[k] for k in ("id", "source", "as_of", "url") if f.get(k) is not None} | {"label": f["label"]}
        return None

    def cover(self, source: str, status: str, *, as_of: Any = None, detail: str = "", key: bool = False) -> None:
        self.coverage.append({"source": source, "status": status, "as_of": _iso(as_of), "detail": detail[:200],
                              "key": key})

    def fact_range(self, start: int) -> list[str]:
        return [f["id"] for f in self.facts[start:]]


class HouseSources:
    """Production readers. Each method returns plain dicts/lists; failures surface as coverage gaps, never guesses."""

    def __init__(self, state_root: Path, *, db_query: Callable | None = None, read_only: bool = False):
        self.state_root = Path(state_root)
        self.read_only = read_only  # dry runs: skip readers that refresh a cache file as a side effect
        self._db = db_query
        self._enrichment: dict | None = None
        self._bars: dict[tuple, list] = {}

    # -- plumbing
    def db(self) -> Callable:
        if self._db is None:
            from db_adapter import _execute  # type: ignore

            def query(sql, params=None, fetch="all"):
                return _execute(sql, params, fetch=fetch)
            self._db = query
        return self._db

    @staticmethod
    def _lib(name: str):
        import importlib
        try:
            return importlib.import_module(f"lib.data_broker.{name}")
        except ImportError:
            return importlib.import_module(f"scripts.lib.data_broker.{name}")

    def _json(self, rel: str) -> Any:
        try:
            return json.loads((self.state_root / rel).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    # -- universe
    def holdings(self) -> dict[str, dict]:
        """{SYM: positions_context row} across all accounts (non-cash, shares > 0)."""
        pp = _plib("portfolio_positions")
        doc = pp.load_store()
        syms = sorted({str(r.get("symbol") or "").upper() for r in doc.get("holdings") or []
                       if not pp.is_cash(r) and (_f(r.get("shares", r.get("quantity"))) or 0) > 0})
        return self._lib("positions_context").get_positions_context(self.db(), syms) if syms else {}

    def watch_symbols(self) -> list[str]:
        """The operator's Watch list ("My Watchlist": stars, personal list, ticker directives, operator adds) via
        data_broker.watch_domains.membership_operator — not the thousands of scanner-researched rows."""
        out = self._lib("watch_domains").membership_operator(lambda sql, params=None: self.db()(sql, params, fetch="all"))
        return sorted(s for s in (out.get("names") or {}) if store.norm_symbol(s))

    # -- the subject_dossier source set (reused, not re-queried)
    def dossier(self, sym: str) -> dict:
        sd = _plib("subject_dossier")
        analyst_fn = research_fn = thesis_fn = None
        try:
            desk = _plib("cio_operator_desk_loop")
            analyst_fn, research_fn = desk.subject_analyst_view, desk.subject_research
        except Exception:  # noqa: BLE001 - recorded as a gap by the caller (analyst view / research absent)
            pass
        try:
            if not self.read_only:  # symbol_thesis_attach refreshes data/cio/cio_theses_projection.json
                from scripts.lib.symbol_thesis_attach import thesis_fields_for_symbol  # noqa: PLC0415
                thesis_fn = lambda s: thesis_fields_for_symbol(s, root=self.state_root)  # noqa: E731
        except Exception:  # noqa: BLE001
            pass
        return sd.gather([sym], db_query=self.db(), runtime_dir=self.state_root / "data/runtime",
                         analyst_fn=analyst_fn, research_fn=research_fn, thesis_fn=thesis_fn).get(sym) or {}

    # -- other house stores
    def analyst(self, sym: str) -> dict:
        return self._lib("analyst_detail").get_analyst_targets(self.db(), [sym]).get(sym) or {}

    def consensus(self, syms: list[str]) -> dict[str, str]:
        rows = self._lib("analyst_detail").get_analyst_targets(self.db(), syms)
        return {k: v.get("recommendation_key") for k, v in rows.items() if v.get("recommendation_key")}

    def bars(self, sym: str, days: int = 1100) -> list[dict]:
        key = (sym, days)
        if key not in self._bars:
            self._bars[key] = self._lib("daily_bars").get_daily_bars(self.db(), sym, days=days).get("bars") or []
        return self._bars[key]

    def ohlc(self, sym: str) -> list[dict]:
        out = self._lib("ohlc_bars").get_daily_ohlc(self.db(), sym, days=60)
        return out.get("bars") if isinstance(out, dict) else (out or [])

    def catalysts(self, sym: str) -> list[dict]:
        return self._lib("catalyst_record").get_symbol_catalysts(self.db(), sym, days=120, limit=8)

    def news(self, sym: str) -> list[dict]:
        return self._lib("catalyst_record").get_symbol_news(self.db(), sym, days=45, limit=8)

    def enrichment_cache(self) -> dict:
        if self._enrichment is None:
            data = self._json("data/state/ticker_enrichment_cache.json")
            self._enrichment = data if isinstance(data, dict) else {}
        return self._enrichment

    def cio(self, sym: str) -> dict:
        return (self._lib("cio_prospect").get_prospect(sym) or {}).get("prospect") or {}

    def position_view(self, sym: str) -> dict:
        return self._lib("cio_prospect").get_position_view(sym) or {}

    def trades(self, sym: str) -> list[dict]:
        # Journal: the ledger the position store reads (trade_transactions); account names applied by the caller.
        rows = self.db()("SELECT trade_date, action, quantity, price, account FROM trade_transactions "
                         "WHERE upper(symbol) = %s ORDER BY trade_date DESC LIMIT 12", (sym,), fetch="all") or []
        return [dict(r) for r in rows]

    def options_theses(self, sym: str) -> list[dict]:
        path = self.state_root / "data/cio/options_theses.jsonl"
        out = []
        try:
            with path.open(encoding="utf-8") as fh:
                for line in fh:
                    if f'"{sym}"' not in line:
                        continue
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if str(row.get("symbol") or row.get("underlying") or "").upper() == sym:
                        out.append(row)
        except OSError:
            return []
        return out[-3:]

    def lookthrough(self, sym: str) -> dict:
        doc = self._json("data/portfolios/state/fund_lookthrough.json") or {}
        row = doc.get(sym) if isinstance(doc.get(sym), dict) else next(
            (v for v in doc.values() if isinstance(v, dict) and str(v.get("public_ticker") or "").upper() == sym), None)
        cache = self._json("data/portfolios/state/fund_holdings_cache.json") or {}
        return {"fund": row, "holdings": cache.get(sym) if isinstance(cache, dict) else None}

    def stops(self, sym: str, accounts: Iterable[str]) -> list[dict]:
        """Display-only stop levels per account (persisted observations + planned file; never a broker call)."""
        truth = _plib("cio_truth")
        planned = self._json("data/portfolios/state/stops.json") or {}
        try:
            rows = _plib("last_known_stops").load_last_known()
        except Exception:  # noqa: BLE001
            rows = []
        out = []
        for account in accounts:
            stop = truth.stop_for(account, sym, broker_rows=rows, planned=planned)
            if _f(stop.get("stop_price")) is not None:
                out.append({"account": account, **stop})
        return out

    def search(self, query: str, sym: str) -> dict:
        """One governed search (search_router: cache → free tier → paid Brave under its budget).

        ``enabled=True`` turns the routing engine on for this caller only. Without it the
        router returns ENGINE_DISABLED unless the process happens to carry
        SEARCH_ROUTING_ENGINE=1, and the 2026-10-26 first build ran 204 searches that all
        failed that way. The paid tier still needs brave_router's own BRAVE_ROUTER_LIVE arm
        and this caller's budget, so this never opens a paid socket by itself.
        """
        res = _plib("search_router").route_query(query, caller="prospectus_writer", symbol=sym, kind="news",
                                                 count=4, enabled=True)
        return {"ok": bool(res.ok), "reason": res.reason, "provider": res.provider, "cost_usd": res.cost_usd,
                "results": [r for r in (res.results or []) if isinstance(r, dict)]}


def _plib(name: str):
    import importlib
    try:
        return importlib.import_module(f"lib.{name}")
    except ImportError:
        return importlib.import_module(f"scripts.lib.{name}")


def account_name(raw: Any) -> str:
    """Account NAME only (config/account_display_names.json); never an account number."""
    return _plib("account_display").account_label(raw)


def _etf_peer_groups() -> dict:
    try:
        from . import load_config
        return load_config().get("etf_peer_groups") or {}
    except (OSError, ValueError):
        return {}


def _cohort(cache: dict, industry: str | None, sym: str) -> dict[str, float]:
    if not industry or str(industry).strip().lower() == bk.ETF_INDUSTRY:  # the Finviz ETF cohort is not a peer set
        return {}
    peers = [r for k, r in cache.items() if isinstance(r, dict) and k != sym and r.get("industry") == industry]
    out = {}
    for key, _ in VALUATION_KEYS:
        vals = [v for v in (_f(r.get(key)) for r in peers) if v is not None and v > 0]
        if len(vals) >= 3:
            out[key] = round(statistics.median(vals), 2)
    out["_n"] = len(peers)
    return out


def _call(b: Bundle, source: str, fn: Callable, *, key: bool = False, default: Any = None) -> Any:
    """Call one source and record the outcome (used / empty / failed). Staleness is recorded by the caller."""
    try:
        out = fn()
    except Exception as exc:  # noqa: BLE001 - a missing store is a recorded gap, never a crash or a guess
        b.cover(source, "failed", detail=type(exc).__name__, key=key)
        return default
    if out in (None, {}, []) or (isinstance(out, dict) and not any(v not in (None, [], {}, "") for v in out.values())):
        b.cover(source, "empty", key=key)
        return default if out is None else out
    b.cover(source, "used", key=key)
    return out


def _stale(b: Bundle, source: str, as_of: Any, now: datetime) -> None:
    age = _age_days(as_of, now)
    limit = STALE_DAYS.get(source)
    for row in reversed(b.coverage):
        if row["source"] == source:
            row["as_of"] = _iso(as_of)
            if age is not None and limit is not None and age > limit and row["status"] == "used":
                row["status"] = "stale"
                row["detail"] = f"{age} days old (limit {limit})"
            break


def assemble(sources: Any, symbol: str, scope: str, *, holding: dict | None = None, now: datetime | None = None,
             book: dict[str, float] | None = None) -> Bundle:
    """Collect every house input for one symbol, with per-source coverage and the institutional blocks."""
    now = now or datetime.now(timezone.utc)
    sym = store.norm_symbol(symbol)
    if not sym:
        raise ValueError("invalid symbol")
    b = Bundle(symbol=sym, scope=scope, name=sym)
    cache = _call(b, "fundamentals_cache", sources.enrichment_cache, default={}) or {}
    b.coverage.pop()  # the whole-universe cache is not itself a per-symbol source; recorded as "fundamentals" below
    rec = cache.get(sym) if isinstance(cache.get(sym), dict) else {}
    b.cover("fundamentals", "used" if rec else "empty", as_of=rec.get("cached_at"), key=True,
            detail="Finviz enrichment cache (data/state/ticker_enrichment_cache.json)")
    _stale(b, "fundamentals", rec.get("cached_at"), now)
    b.name = str(rec.get("company") or sym)

    d = _call(b, "dossier", lambda: sources.dossier(sym), default={}) or {}
    prof = d.get("profile") or {}
    b.cover("dossier_profile", "used" if prof else "empty", as_of=prof.get("updated_at"), key=True,
            detail="symbol_profiles via subject_dossier")
    prof_src = "symbol_profiles (subject_dossier)"
    if prof.get("description_1s"):
        b.add("company", "Business description", text=prof["description_1s"], source=prof_src, as_of=prof.get("updated_at"))
    sector = prof.get("sector") or rec.get("sector")
    industry = rec.get("industry") or prof.get("industry")
    for label, val in (("Sector", sector), ("Industry", prof.get("industry") or rec.get("industry"))):
        if val:
            b.add("company", label, text=val, source=prof_src, as_of=prof.get("updated_at"))
    eps_src = "symbol_profiles earnings fields (subject_dossier)"
    b.add("estimates", "Last reported EPS", value=prof.get("last_eps_actual"), unit="$", source=eps_src,
          as_of=prof.get("last_earnings_date"))
    b.add("estimates", "Last EPS estimate", value=prof.get("last_eps_estimate"), unit="$", source=eps_src,
          as_of=prof.get("last_earnings_date"))
    b.add("estimates", "Last EPS surprise %", value=prof.get("last_eps_surprise_pct"), unit="%", source=eps_src,
          as_of=prof.get("last_earnings_date"))
    if prof.get("next_earnings_date"):
        b.add("catalyst", "Next earnings date", text=_iso(prof["next_earnings_date"])[:10], source=prof_src,
              as_of=prof.get("earnings_updated_at") or prof.get("updated_at"))
        b.context["next_earnings_date"] = _iso(prof["next_earnings_date"])[:10]
    if prof.get("last_earnings_date"):
        b.context["last_earnings_date"] = _iso(prof["last_earnings_date"])[:10]
    for key, label in PROFILE_KEYS + GROWTH_KEYS:
        raw = bk.market_cap_billions(rec) if key == "market_cap_b" else rec.get(key)  # cache field is $M
        b.add("fundamental", label, value=raw, unit="%" if key.endswith("_pct") else "",
              source="Finviz enrichment cache", as_of=rec.get("cached_at"))

    # dossier sections: catalysts, news, house agents, synthesis, IV, dividends, sector/industry, research, thesis
    for name, rows in (("catalysts", d.get("catalysts")), ("news", d.get("news")), ("house_agents", d.get("agents")),
                       ("house_research", d.get("research"))):
        b.cover(name, "used" if rows else "empty", detail="via subject_dossier")
    for row in d.get("catalysts") or []:
        b.add("catalyst", f"Catalyst ({row.get('catalyst_type') or 'event'}, {row.get('severity') or 'n/a'})",
              text=row.get("headline"), source=f"catalyst_events / {row.get('source') or 'feed'}", as_of=row.get("at"))
    news = d.get("news") or []
    for row in news:
        b.add("news", f"News — {row.get('source') or 'feed'}", text=row.get("title"), source="news_articles",
              as_of=row.get("published_at"))
    b.context["latest_news_at"] = max((_iso(r.get("published_at")) or "" for r in news), default=None) or None
    for row in d.get("agents") or []:
        b.add("house", f"House agent {row.get('agent')}", text=f"{row.get('recommendation')} (confidence {row.get('confidence')})",
              source="watchlist_agent_results", as_of=row.get("created_at"))
    syn = d.get("synthesis") or {}
    b.cover("final_synthesis", "used" if syn else "empty")
    if syn:
        b.add("house", "House final synthesis", text=f"{syn.get('recommendation')} (confidence {syn.get('confidence')}, "
              f"safety {syn.get('decision_safety')})", source="watchlist_final_synthesis", as_of=syn.get("updated_at"))
    iv = d.get("iv") or {}
    b.cover("options_iv", "used" if iv else "empty", as_of=iv.get("snapshot_date"))
    b.add("risk", "Implied volatility %", value=iv.get("iv_pct"), unit="%", source="options_iv_history",
          as_of=iv.get("snapshot_date"))
    div = d.get("dividends") or {}
    b.add("fundamental", "Annual dividend per share", value=div.get("annual_dividend_per_share"), unit="$",
          source="ticker_dividend_data", as_of=div.get("updated_at"))
    sector_row, industry_row = d.get("sector"), d.get("industry")
    b.cover("sector_momentum", "used" if sector_row else "empty", as_of=d.get("sector_as_of"),
            detail="data/runtime/sector_momentum_latest.json")
    b.cover("industry_momentum", "used" if industry_row else "empty", as_of=d.get("industry_as_of"),
            detail="data/runtime/industry_momentum_latest.json")
    for label, row, at in (("Sector momentum", sector_row, d.get("sector_as_of")),
                           ("Industry group momentum", industry_row, d.get("industry_as_of"))):
        if isinstance(row, dict):
            b.add("momentum", label, text=json.dumps({k: v for k, v in row.items() if not isinstance(v, (list, dict))},
                                                     default=str)[:300], source="house momentum runtime file", as_of=at)
    for row in d.get("research") or []:
        b.add("research", f"House research — {row.get('research_type') or 'note'}: {row.get('topic') or ''}"[:120],
              text=row.get("summary"), source="hermes_research_intelligence (Research Intel)", as_of=row.get("as_of"))
    th = d.get("thesis") or {}
    b.cover("symbol_thesis", "used" if th else "empty")
    if th:
        b.add("thesis", "Symbol thesis", text=f"{th.get('thesis_state')}: {th.get('thesis_summary') or ''}",
              source="CIO thesis store (symbol_thesis_attach)", as_of=th.get("thesis_updated_at") or th.get("as_of"))
    av = d.get("analyst") or {}
    if av:
        b.add("analyst", "Analyst rating (house view)", text=f"{av.get('rating')} (mean {av.get('rating_mean')}, "
              f"{av.get('analysts')} analysts{', stale' if av.get('stale') else ''})",
              source=f"analyst view ({av.get('source') or 'house'})", as_of=av.get("as_of"))

    # valuation vs industry cohort
    cohort = _cohort(cache, industry, sym)
    val_series = []
    for key, label in VALUATION_KEYS:
        mine = _f(rec.get(key))
        b.add("valuation", label, value=mine, source="Finviz enrichment cache", as_of=rec.get("cached_at"))
        if key in cohort:
            b.add("valuation", f"{label}, industry median (n={cohort['_n']})", value=cohort[key],
                  source="Finviz enrichment cache (industry cohort)", as_of=rec.get("cached_at"))
        if mine is not None and key in cohort:
            val_series.append((label, mine, cohort[key]))
    if val_series:
        b.series["valuation_vs_peers"] = val_series
    growth = [(label, _f(rec.get(key))) for key, label in GROWTH_KEYS if _f(rec.get(key)) is not None]
    if growth:
        b.series["revenue_eps_trend"] = growth

    # price history (house price store) + benchmarks
    bars = [r for r in (_call(b, "price_history", lambda: sources.bars(sym), key=True, default=[]) or [])
            if _f(r.get("close")) is not None]
    price_src = "ticker_prices (data_broker.daily_bars)"
    last = _f(bars[-1]["close"]) if bars else None
    quality = bk.series_quality(bars)
    if bars:
        _stale(b, "price_history", bars[-1]["price_date"], now)
        year = quality["series"][-253:]  # clean segment only: bad bars and pre-break history never reach a fact
        b.series["price_1y"] = year
        # the raw window (before the guard) is kept for the data-quality gate only: it still reports what was dropped
        b.series["price_1y_raw"] = bk._series(bars)[-253:]
        at = bars[-1]["price_date"]
        closes = [c for _, c in year]
        b.add("price", "Last close", value=last, unit="$", source=price_src, as_of=at)
        if quality["notes"]:
            b.add("price", "Price history quality", text="; ".join(quality["notes"]), source=price_src, as_of=at)
        if len(closes) >= 240:
            b.add("price", "1-year high close", value=max(closes), unit="$", source=price_src, as_of=at)
            b.add("price", "1-year low close", value=min(closes), unit="$", source=price_src, as_of=at)
            if closes[0]:
                b.add("price", "1-year price change %", value=(last / closes[0] - 1) * 100, unit="%", source=price_src, as_of=at)
        elif closes:
            since = f"since {year[0][0]} ({len(closes)} clean sessions)"
            b.add("price", f"High close {since}", value=max(closes), unit="$", source=price_src, as_of=at)
            b.add("price", f"Low close {since}", value=min(closes), unit="$", source=price_src, as_of=at)
            b.add("price", "1-year price change %", text=f"not reliable: only {len(closes)} clean sessions since "
                  f"{year[0][0]}", source=price_src, as_of=at)
        if len(closes) >= 2 and closes[-2]:
            b.context["day_move_pct"] = round((closes[-1] / closes[-2] - 1) * 100, 2)
    etf = bk.SECTOR_ETFS.get(str(sector or "").strip().lower())
    bench_names = [n for n in (etf, *bk.BENCHMARKS) if n and n != sym]
    bench = {}
    for name in bench_names:
        rows = _call(b, f"benchmark_{name}", lambda n=name: sources.bars(n), default=[]) or []
        if rows:
            bench[name] = rows
    if not etf:
        b.cover("benchmark_sector_etf", "empty", detail=f"no house sector→ETF mapping for sector {sector!r}")

    # analyst targets
    an = _call(b, "analyst_targets", lambda: sources.analyst(sym), default={}) or {}
    _stale(b, "analyst_targets", an.get("created_at"), now)
    an_src = "yahoo_analyst_targets_history (data_broker.analyst_detail)"
    for key, label in (("target_low", "Analyst target low"), ("target_mean", "Analyst target mean"),
                       ("target_high", "Analyst target high"), ("analyst_count", "Analyst count")):
        b.add("analyst", label, value=an.get(key), unit="" if key == "analyst_count" else "$", source=an_src,
              as_of=an.get("created_at"))
    if an.get("recommendation_key"):
        b.add("analyst", "Consensus recommendation", text=str(an["recommendation_key"]), source=an_src, as_of=an.get("created_at"))
    for key, label in (("target_low", "Downside to low target %"), ("target_mean", "Upside to mean target %"),
                       ("target_high", "Upside to high target %")):
        if last and _f(an.get(key)):
            b.add("analyst", label, value=(_f(an[key]) / last - 1) * 100, unit="%", source=an_src + " + daily_bars",
                  as_of=an.get("created_at"))
    if _f(an.get("target_low")) and _f(an.get("target_high")):
        b.series["analyst_targets"] = {"low": _f(an["target_low"]), "mean": _f(an.get("target_mean")),
                                       "high": _f(an["target_high"]), "price": last}

    # CIO record: stance, conviction, origin / lineage
    cio = _call(b, "cio_record", lambda: sources.cio(sym), key=True, default={}) or {}
    cio_src = "CIO prospect (data_broker.cio_prospect)"
    for key, label in (("stance", "CIO stance"), ("stage", "CIO stage"), ("catalyst_grade", "CIO catalyst grade"),
                       ("next_trigger", "CIO next trigger"), ("whats_missing", "CIO: what is missing")):
        val = cio.get(key)
        if isinstance(val, (list, dict)):
            val = json.dumps(val, default=str)[:300]
        if val not in (None, ""):
            b.add("cio", label, text=str(val), source=cio_src, as_of=cio.get("evidence_at"))
    # ONE canonical conviction: the CIO prospect record (§26.1). The opportunity projection's score is an input to
    # that record and is not offered to the writer as a second "conviction" (domains.r_opportunity).
    conv = _f(cio.get("conviction"))
    b.add("cio", "CIO conviction (CIO prospect record, 0-100)", value=conv, source=cio_src, as_of=cio.get("evidence_at"))
    if conv is not None:
        b.blocks.setdefault("verdict_tiles", {})["verdict"] = {
            "sub": f"CIO conviction {round(conv)}/100 (CIO prospect record)", "source": "cio_prospect.conviction"}
    b.context["cio_stance"], b.context["cio_stage"] = cio.get("stance"), cio.get("stage")
    b.context["security_guid"] = cio.get("security_guid") or cio.get("subject_guid")
    view = _call(b, "cio_lineage_origin", lambda: sources.position_view(sym), default={}) or {}
    pv = view.get("position_view") or view
    for key, label in (("origin", "Origin (recommendation lineage)"), ("lifecycle", "Position lifecycle")):
        if pv.get(key):
            b.add("lineage", label, text=json.dumps(pv[key], default=str)[:300], source="CIO position view (cio_prospect)",
                  as_of=view.get("as_of"))

    # options theses
    for row in _call(b, "options_theses", lambda: sources.options_theses(sym), default=[]) or []:
        b.add("options", "Options thesis", text=f"{row.get('strategy') or ''} {row.get('thesis_state') or ''}: "
              f"{row.get('thesis_summary') or row.get('summary') or ''}", source="data/cio/options_theses.jsonl",
              as_of=row.get("created_at") or row.get("recorded_at"))

    # funds: look-through holdings and sector weights
    is_fund = bool((holding or {}).get("is_fund")) or str((holding or {}).get("asset_type") or "").lower() in {"etf", "fund", "mutual_fund"}
    lt = _call(b, "fund_lookthrough", lambda: sources.lookthrough(sym), default={}) or {}
    fund = lt.get("fund") or {}
    if fund or lt.get("holdings"):
        _stale(b, "fund_lookthrough", fund.get("fetched_date"), now)
        for sec, w in sorted((fund.get("sector_weights") or {}).items(), key=lambda kv: -(_f(kv[1]) or 0))[:8]:
            b.add("lookthrough", f"Fund sector weight: {sec} %", value=w, unit="%",
                  source=f"fund_lookthrough.json ({fund.get('data_source') or 'house'})", as_of=fund.get("fetched_date"))
        top = fund.get("top_holdings") or lt.get("holdings") or {}
        items = top.items() if isinstance(top, dict) else [(str(t.get("symbol") or t.get("name")), t.get("weight"))
                                                           for t in top if isinstance(t, dict)]
        for name, w in list(items)[:10]:
            b.add("lookthrough", f"Fund top holding: {name} %", value=w if not isinstance(w, dict) else w.get("weight"),
                  unit="%", source="fund look-through (house)", as_of=fund.get("fetched_date"))
        b.blocks["fund_lookthrough"] = {"sector_weights": fund.get("sector_weights"), "top_holdings": top,
                                        "as_of": fund.get("fetched_date")}
    elif is_fund:
        b.gaps.append("fund look-through: no holdings / sector weights in the house for this fund")

    # position (holdings only): account NAMES only, never numbers
    if scope == "holding":
        if not holding:
            b.cover("position", "empty", key=True)
        else:
            b.cover("position", "used", as_of=holding.get("as_of"), key=True,
                    detail="position store via data_broker.positions_context")
            pos_src = "position store (lib.portfolio_positions via data_broker.positions_context)"
            at = holding.get("as_of")
            names = sorted({account_name(a) for a in holding.get("accounts") or [] if a})
            b.add("position", "Accounts holding", text=", ".join(names), source=pos_src, as_of=at)
            b.add("position", "Shares held (all accounts)", value=holding.get("shares"), source=pos_src, as_of=at)
            b.add("position", "Market value $", value=holding.get("market_value"), unit="$", source=pos_src, as_of=at)
            b.add("position", "Average cost $", value=holding.get("avg_cost"), unit="$", source=pos_src, as_of=at)
            b.add("position", "Unrealized P/L $", value=holding.get("unrealized_pl"), unit="$", source=pos_src, as_of=at)
            b.add("position", "Unrealized P/L %", value=holding.get("unrealized_pl_pct"), unit="%", source=pos_src, as_of=at)
            b.add("position", "Portfolio weight %", value=holding.get("weight_pct"), unit="%", source=pos_src, as_of=at)
            stops = _call(b, "stops", lambda: sources.stops(sym, holding.get("accounts") or []), default=[]) or []
            levels = []
            for st in stops:
                label = account_name(st.get("account"))
                fid = b.add("position", f"Recorded protective stop level ({label}, {st.get('stop_source') or 'unknown'}, "
                            f"{st.get('stop_state') or 'state unknown'})", value=st.get("stop_price"), unit="$",
                            source="stop_last_known / stops.json (cio_truth.stop_for)", as_of=st.get("stop_captured_at"))
                if fid:
                    levels.append(_f(st.get("stop_price")))
                    if last:
                        b.add("position", f"Distance from last close to stop % ({label})",
                              value=(last / _f(st["stop_price"]) - 1) * 100, unit="%", source="derived: last close vs stop",
                              as_of=st.get("stop_captured_at"))
            b.context["stop_levels"] = sorted(v for v in levels if v is not None)
            b.series["position"] = {"avg_cost": _f(holding.get("avg_cost")), "stops": b.context["stop_levels"],
                                    "market_value": _f(holding.get("market_value")),
                                    "cost_basis": _f(holding.get("cost_basis")),
                                    "unrealized_pl": _f(holding.get("unrealized_pl"))}
        for row in _call(b, "journal_trades", lambda: sources.trades(sym), default=[]) or []:
            b.add("journal", f"Journal trade: {row.get('action')} ({account_name(row.get('account'))})",
                  text=f"{row.get('quantity')} @ {row.get('price')}", source="trade_transactions (journal)",
                  as_of=row.get("trade_date"))

    # institutional blocks (computed, then exposed as facts so prose can cite them)
    start = len(b.facts)
    rel = bk.relative_performance(sym, bars, bench, cache=cache, industry=industry, sector_row=sector_row,
                                  industry_row=industry_row)
    rel["sector_etf"] = etf
    for r in rel["returns"]:
        for w in bk.WINDOWS:
            b.add("relative", f"{r['name']} return {w} %", value=r[w], unit="%", source="ticker_prices (house)",
                  as_of=bars[-1]["price_date"] if bars else None)
    for w, v in rel["excess_vs_spy"].items():
        b.add("relative", f"{sym} excess vs SPY {w} %", value=v, unit="%", source="derived: ticker_prices (house)")
    if rel["rank_in_industry"]:
        rk = rel["rank_in_industry"]
        b.add("relative", "Industry rank by 1Y return", text=f"{rk['rank']} of {rk['of']} ({rk['percentile']}th percentile)",
              source="Finviz enrichment cache (industry cohort)", as_of=rec.get("cached_at"))
    b.add("relative", "Relative strength rating (0-99, 12m)", value=rel["rs_rating_12m"], source=rel["rs_basis"],
          as_of=rec.get("cached_at"))
    if bars and "SPY" not in bench:
        b.cover("benchmark_SPY", "empty", key=True, detail="SPY series missing from the house price store")
    consensus = _call(b, "peer_consensus", lambda: sources.consensus(
        [k for k, r in cache.items() if isinstance(r, dict) and r.get("industry") == industry][:60]), default={}) or {}
    peers = bk.peer_comparison(sym, cache, consensus=consensus, etf_groups=_etf_peer_groups())
    for row in peers.get("rows") or []:
        for key, label in bk.PEER_FIELDS:
            b.add("peers", f"{row['symbol']} {label}", value=row.get(key), source="Finviz enrichment cache (peer)",
                  as_of=rec.get("cached_at"))
    for key, label in bk.PEER_FIELDS:
        b.add("peers", f"Peer median {label}", value=(peers.get("median") or {}).get(key), source="derived: peer median")
    est = bk.estimates(prof)
    own = bk.ownership_flows(rec)
    for key, label in (("institutional_pct", "Institutional ownership %"), ("institutional_change_pct", "Institutional ownership change %"),
                       ("insider_own_pct", "Insider ownership %"), ("insider_change_pct", "Insider transactions %"),
                       ("short_float_pct", "Short interest, % of float"), ("days_to_cover", "Short interest, days to cover")):
        b.add("ownership", label, value=own.get(key), unit="" if key == "days_to_cover" else "%",
              source="Finviz enrichment cache", as_of=rec.get("cached_at"))
    ohlc = _call(b, "ohlc", lambda: sources.ohlc(sym), default=[]) or []
    risk = bk.risk_technicals(bars, ohlc=ohlc, spy=bench.get("SPY"), book=book, rec=rec, subject=sym)
    for key, label in (("beta_1y", "Beta (1Y vs SPY)"), ("vol_annualized_pct", "Annualized volatility %"),
                       ("max_drawdown_1y_pct", "Max drawdown 1Y %"), ("correlation_to_book", "Correlation to the book (1Y)"),
                       ("px_vs_sma50_pct", "Price vs 50-day average %"), ("px_vs_sma200_pct", "Price vs 200-day average %"),
                       ("rsi14", "RSI (14)"), ("atr20", "ATR (20)")):
        at = bars[-1]["price_date"] if bars else None
        if key in (risk.get("unreliable") or {}):  # no number reaches the writer; the reason does
            b.add("risk", label, text=f"not reliable ({risk['unreliable'][key]})", source=risk.get("basis") or "house closes", as_of=at)
            continue
        b.add("risk", label, value=risk.get(key), unit="%" if key.endswith("_pct") else "",
              source=(risk.get("basis") or "computed from house closes")
              + (f"; vs {risk['correlation_basis']}" if key == "correlation_to_book" and risk.get("correlation_basis") else ""),
              as_of=at)
    b.blocks.update({"relative_performance": rel, "peer_comparison": peers, "estimates": est,
                     "ownership_flows": own, "risk_technicals": risk})
    b.context["block_fact_ids"] = b.fact_range(start)
    for gap in rel["gaps"] + peers.get("gaps", []) + est["gaps"] + own["gaps"] + risk.get("gaps", []):
        if gap not in b.gaps:
            b.gaps.append(gap)
    b.context["assembled_at"] = now.isoformat()
    return b


def key_gaps(b: Bundle) -> list[str]:
    """Key sources that were not usable (empty / failed / stale): these make the prospectus partial."""
    keys = KEY_SOURCES_HOLDING if b.scope == "holding" else KEY_SOURCES
    out = []
    for row in b.coverage:
        if (row["source"] in keys or row["source"] == "benchmark_SPY") and row["status"] != "used":
            out.append(f"{row['source']}: {row['status']}{(' — ' + row['detail']) if row.get('detail') else ''}")
    return out


def holdings_ranked(holdings: dict[str, dict]) -> list[tuple[str, float]]:
    """Symbols by total $ value across accounts, largest first."""
    return sorted(((s, float(r.get("market_value") or 0.0)) for s, r in holdings.items()),
                  key=lambda item: (-item[1], item[0]))


def earnings_passed(next_earnings: Any, since: Any, today: date | None = None) -> bool:
    """True when a recorded earnings date falls after ``since`` and on/before today."""
    try:
        when = date.fromisoformat(str(next_earnings)[:10])
        after = date.fromisoformat(str(since)[:10])
    except (TypeError, ValueError):
        return False
    return after < when <= (today or datetime.now(timezone.utc).date())
