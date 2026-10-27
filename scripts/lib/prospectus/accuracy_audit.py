"""Prospectus accuracy auditor: recompute what a written prospectus says from the primary house stores.

Operator 2026-10-26: "There's still some data that's missing … we need an agent to go through and look at this …
Money is riding on this. We can't have inaccuracies."

The quality gate (``quality_gate.py``) checks a facts packet against itself before any model call. This module
goes one step further, after a report is written: it re-reads the PRIMARY stores the facts were assembled from and
recomputes every number that can be recomputed, independently of the prospectus code paths:

* position (shares, average cost, market value, unrealized P/L) — the position store (``lib.portfolio_positions``)
* stops (level and state, per account) — ``stop_last_known`` (persisted broker observations), read as Risk reads it
* prices and returns — ``ticker_prices`` (weekend rows excluded: NYSE does not trade on Saturday or Sunday)
* dividends — ``ticker_dividends`` (ex-date history) against ``ticker_dividend_data`` and the fund profile
* fundamentals and peers — the Finviz enrichment cache
* macro — ``fred_economic_series``
* realized history — ``trade_transactions`` sells against the round trips the report shows
* internal consistency — blocks that contradict each other, undated or months-old facts, empty fund/technical rows

Each defect is ``{code, severity, klass, block, field, observed, expected, detail}``:

* severity ``P1`` wrong money / position / stop / price, ``P2`` missing or stale key data, ``P3`` cosmetic;
* klass ``wrong`` / ``missing`` / ``stale`` / ``contradiction`` / ``label`` / ``render``.

READ_ONLY_ADVISORY (MBI_BEHAVIOR=0): no model, no broker call, no store write. Every reader is injectable
(``Primary``), so the tests run on synthetic data only. The CLI is ``scripts/prospectus_accuracy_audit.py``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
import json
import math
from pathlib import Path
import re
import statistics
from typing import Any, Callable, Iterable, Optional
try:
    from scripts.lib.dividend_source_trust import TRUSTED_ROW_SQL as _DIV_TRUSTED
except ImportError:  # pragma: no cover -- hub import path
    from lib.dividend_source_trust import TRUSTED_ROW_SQL as _DIV_TRUSTED  # type: ignore

SCHEMA = "ProspectusAccuracyAudit@v1"
P1, P2, P3 = "P1", "P2", "P3"

TOL = {
    "price_rel": 0.005,        # prices: 0.5 %
    "money_abs": 1.0,          # money: $1
    "shares_abs": 0.0005,
    "return_pp": 0.5,          # window returns: 0.5 percentage points
    "pl_pct_pp": 0.05,
    "mv_rel": 0.01,            # market value vs shares × the report's own mark (quote timing): 1 %
    "fundamental_max_age_days": 30,
    "technical_max_age_days": 3,
    "dividend_rel": 0.25,      # annual dividend vs trailing-12-month ex-date sum
    "realized_cover_min": 0.5,  # round trips must cover at least half the shares sold, or the gap must say so
}

def known_stop_statuses() -> set[str]:
    """Raw broker stop statuses the house state machine (cio_truth) maps; anything else shows as 'unknown'."""
    try:
        truth = _imp("lib.cio_truth", "scripts.lib.cio_truth")
        return set(truth._ACTIVE_STOP_STATES) | set(truth._PENDING_STOP_STATES) | set(truth._DEAD_STOP_STATES) | {"filled"}
    except Exception:  # noqa: BLE001
        return {"active", "working", "pending_activation", "filled", "canceled", "cancelled", "rejected", "expired",
                "replaced", "not_in_read"}


#: FRED series a prospectus macro block is expected to carry (house id → what the report calls it).
EXPECTED_MACRO = {"DGS10": "10-year Treasury yield", "DFF": "Fed funds rate"}


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _d(v: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def _dt(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        out = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        d = _d(v)
        return datetime(d.year, d.month, d.day, tzinfo=timezone.utc) if d else None
    return out if out.tzinfo else out.replace(tzinfo=timezone.utc)


def _rel(a: float, b: float) -> float:
    return abs(a - b) / max(abs(b), 1e-9)


def defect(code: str, severity: str, klass: str, message: str, *, block: str = "", field_: str = "",
           observed: Any = None, expected: Any = None, fix: str = "") -> dict:
    return {"code": code, "severity": severity, "klass": klass, "block": block, "field": field_,
            "observed": observed, "expected": expected, "message": message[:400], "fix": fix[:300]}


# ── primary readers (read-only; injectable) ─────────────────────────────────────────────────────────────────────
@dataclass
class Primary:
    """Primary-source readers. Each callable returns plain dicts/lists; ``None`` means the store was unreadable."""
    positions: Callable[[str], Optional[list[dict]]] = lambda sym: None          # [{account, shares, cost_basis}]
    stop_rows: Callable[[str], Optional[list[dict]]] = lambda sym: None          # stop_last_known rows
    closes: Callable[[str], Optional[list[tuple[str, float]]]] = lambda sym: None  # ticker_prices (date, close)
    dividends: Callable[[str], Optional[list[dict]]] = lambda sym: None          # ticker_dividends [{ex_date, amount}]
    dividend_data: Callable[[str], Optional[dict]] = lambda sym: None            # ticker_dividend_data row
    finviz: Callable[[str], Optional[dict]] = lambda sym: None                   # enrichment cache record
    fred: Callable[[str], Optional[list[tuple[str, float]]]] = lambda sid: None  # fred_economic_series
    trades: Callable[[str], Optional[list[dict]]] = lambda sym: None             # trade_transactions rows
    stop_resolver: Optional[Callable[[str, str, list], dict]] = None             # cio_truth.stop_for


def db_primary(query: Callable, state_root: Path) -> Primary:
    """Production readers over the house DB and state files (read-only SELECTs)."""
    cache: dict = {}

    def enrichment() -> dict:
        if "doc" not in cache:
            try:
                cache["doc"] = json.loads((Path(state_root) / "data/state/ticker_enrichment_cache.json").read_text())
            except (OSError, ValueError):
                cache["doc"] = None
        return cache["doc"] or {}

    def positions(sym: str) -> Optional[list[dict]]:
        try:
            pp = _imp("lib.portfolio_positions", "scripts.lib.portfolio_positions")
            doc = pp.load_store()
        except Exception:  # noqa: BLE001
            return None
        out = []
        for r in doc.get("holdings") or []:
            if str(r.get("symbol") or "").upper() != sym or pp.is_cash(r):
                continue
            sh = _f(r.get("shares", r.get("quantity")))
            if sh and sh > 0:
                out.append({"account": r.get("account") or r.get("account_id"), "shares": sh,
                            "cost_basis": _f(r.get("cost_basis"))})
        return out

    def rows(sql: str, params: tuple) -> Optional[list[dict]]:
        try:
            return [dict(r) for r in (query(sql, params, fetch="all") or [])]
        except Exception:  # noqa: BLE001
            return None

    def closes(sym: str):
        out = rows("SELECT price_date, close_price FROM ticker_prices WHERE upper(symbol) = %s "
                   "AND price_date >= %s ORDER BY price_date", (sym, date.today() - timedelta(days=1200)))
        return None if out is None else [(str(r["price_date"])[:10], float(r["close_price"])) for r in out
                                         if _f(r.get("close_price"))]

    def fred(sid: str):
        out = rows("SELECT observation_date, value FROM fred_economic_series WHERE series_id = %s "
                   "ORDER BY observation_date", (sid,))
        return None if out is None else [(str(r["observation_date"])[:10], float(r["value"])) for r in out
                                         if _f(r.get("value")) is not None]

    def resolver(account: str, sym: str, broker_rows: list) -> dict:
        truth = _imp("lib.cio_truth", "scripts.lib.cio_truth")
        return truth.stop_for(account, sym, broker_rows=broker_rows, planned=None)

    def dividend_data(sym: str):
        out = rows("SELECT * FROM ticker_dividend_data WHERE upper(symbol) = %s AND " + _DIV_TRUSTED, (sym,))
        return (out or [None])[0] if out is not None else None

    return Primary(
        positions=positions,
        stop_rows=lambda sym: rows("SELECT broker, account, symbol, order_id, stop_price, qty, status, captured_at "
                                   "FROM stop_last_known WHERE upper(symbol) = %s", (sym,)),
        closes=closes,
        dividends=lambda sym: rows("SELECT ex_date, amount FROM ticker_dividends WHERE upper(symbol) = %s "
                                   "ORDER BY ex_date DESC LIMIT 40", (sym,)),
        dividend_data=dividend_data,
        finviz=lambda sym: (enrichment().get(sym) if isinstance(enrichment().get(sym), dict) else None),
        fred=fred,
        trades=lambda sym: rows("SELECT trade_date, action, quantity, price, account FROM trade_transactions "
                                "WHERE upper(symbol) = %s ORDER BY trade_date", (sym,)),
        stop_resolver=resolver,
    )


def _imp(*names: str):
    import importlib
    last: Exception | None = None
    for name in names:
        try:
            return importlib.import_module(name)
        except ImportError as exc:
            last = exc
    raise last or ImportError(names[0])


# ── helpers over a report (a stored Prospectus@v1 document or an assembled bundle dump) ─────────────────────────
def _facts(doc: dict) -> list[dict]:
    return list(doc.get("facts") or [])


def _fact(doc: dict, label: str) -> Optional[dict]:
    return next((f for f in _facts(doc) if f.get("label") == label), None)


def _val(doc: dict, label: str) -> Optional[float]:
    f = _fact(doc, label)
    return _f((f or {}).get("value"))


def _blocks(doc: dict) -> dict:
    return doc.get("blocks") or {}


def trading_days(closes: Iterable[tuple[str, float]]) -> list[tuple[str, float]]:
    """Closes on NYSE weekdays only (a Saturday/Sunday row is a copied quote, not a session)."""
    out = []
    for d, c in closes or []:
        dd = _d(d)
        if dd and not _weekend_or_holiday(dd) and c and c > 0:
            out.append((dd.isoformat(), float(c)))
    return sorted(out)


WINDOW_DAYS = {"1W": 7, "1M": 30, "3M": 91, "1Y": 365}
WINDOWS = ("1W", "1M", "3M", "YTD", "1Y")


def window_return(s: list[tuple[str, float]], window: str) -> Optional[float]:
    """Independent recompute: YTD from the prior year's last session; other windows from the last session on or
    before (last date - calendar span), or the first session when the series begins within 4 days after that."""
    if len(s) < 2:
        return None
    if window == "YTD":
        year = s[-1][0][:4]
        prior = [c for d, c in s if d[:4] < year]
        return round((s[-1][1] / prior[-1] - 1) * 100, 2) if prior else None
    target = date.fromisoformat(s[-1][0]) - timedelta(days=WINDOW_DAYS[window])
    before = [c for d, c in s[:-1] if d <= target.isoformat()]
    if before:
        return round((s[-1][1] / before[-1] - 1) * 100, 2)
    if date.fromisoformat(s[0][0]) <= target + timedelta(days=4):
        return round((s[-1][1] / s[0][1] - 1) * 100, 2)
    return None


def _weekend_or_holiday(d: date) -> bool:
    try:
        from . import blocks
        return not blocks.is_session(d)
    except Exception:  # noqa: BLE001
        return d.weekday() >= 5


# ── checks ──────────────────────────────────────────────────────────────────────────────────────────────────────
def check_position(doc: dict, p: Primary) -> list[dict]:
    if doc.get("scope") != "holding":
        return []
    sym = doc["symbol"]
    rows = p.positions(sym)
    out: list[dict] = []
    if rows is None:
        return [defect("position_store_unreadable", P2, "missing", "position store unreadable; position not verified",
                       block="position")]
    shares = _val(doc, "Shares held (all accounts)")
    avg = _val(doc, "Average cost $")
    mv = _val(doc, "Market value $")
    upl = _val(doc, "Unrealized P/L $")
    uplp = _val(doc, "Unrealized P/L %")
    true_sh = round(sum(r["shares"] for r in rows), 6)
    known = [r for r in rows if r.get("cost_basis") is not None]
    true_cost = sum(r["cost_basis"] for r in known) if len(known) == len(rows) else None
    if shares is None:
        out.append(defect("position_shares_missing", P1, "missing", "holding without a shares fact", block="position",
                          field_="shares", expected=true_sh))
    elif abs(shares - true_sh) > TOL["shares_abs"]:
        out.append(defect("position_shares_mismatch", P1, "wrong", "shares differ from the position store",
                          block="position", field_="shares", observed=shares, expected=true_sh,
                          fix="re-read the position store at write time"))
    if true_cost is not None and true_sh:
        true_avg = true_cost / true_sh
        if avg is None:
            out.append(defect("position_avg_cost_missing", P1, "missing", "average cost missing although the store "
                              "has a basis for every account", block="position", field_="avg_cost", expected=round(true_avg, 4)))
        elif abs(avg * true_sh - true_cost) > TOL["money_abs"] + 0.0001 * true_cost:
            out.append(defect("position_avg_cost_mismatch", P1, "wrong", "average cost × shares differs from the "
                              "store's total cost basis", block="position", field_="avg_cost", observed=avg,
                              expected=round(true_avg, 4)))
    # internal arithmetic: market value vs shares × the report's own mark; P/L vs MV − cost
    mark = _val(doc, "Latest quote") or _val(doc, "Last close")
    if mv is not None and shares and mark:
        if _rel(mv, shares * mark) > TOL["mv_rel"]:
            out.append(defect("position_market_value_inconsistent", P1, "contradiction", "market value is not "
                              "shares × the report's own price", block="position", field_="market_value",
                              observed=mv, expected=round(shares * mark, 2)))
    if mv is not None and upl is not None and avg is not None and shares:
        cost = avg * shares
        if abs((mv - cost) - upl) > max(TOL["money_abs"], 0.0005 * cost):
            out.append(defect("position_pl_inconsistent", P1, "contradiction", "unrealized P/L ≠ market value − cost",
                              block="position", field_="unrealized_pl", observed=upl, expected=round(mv - cost, 2)))
        if uplp is not None and cost and abs(uplp - (mv - cost) / cost * 100) > TOL["pl_pct_pp"]:
            out.append(defect("position_pl_pct_inconsistent", P1, "contradiction", "unrealized P/L % ≠ P/L ÷ cost",
                              block="position", field_="unrealized_pl_pct", observed=uplp,
                              expected=round((mv - cost) / cost * 100, 2)))
    return out


def _stop_facts(doc: dict) -> dict[str, dict]:
    """{account label: {level, state}} from the 'Recorded protective stop level (<acct>, <source>, <state>)' facts."""
    out = {}
    for f in _facts(doc):
        m = re.match(r"Recorded protective stop level \((.+?), ([^,]+), ([^,]+)\)$", str(f.get("label") or ""))
        if m and _f(f.get("value")) is not None:
            out[m.group(1)] = {"level": _f(f["value"]), "source": m.group(2), "state": m.group(3), "id": f.get("id")}
    return out


def check_stops(doc: dict, p: Primary, *, label_fn: Callable[[str], str] = str) -> list[dict]:
    if doc.get("scope") != "holding":
        return []
    sym = doc["symbol"]
    rows = p.stop_rows(sym)
    if rows is None:
        return [defect("stop_store_unreadable", P2, "missing", "stop_last_known unreadable; stops not verified",
                       block="stop_plan")]
    out: list[dict] = []
    for st in sorted({str(r.get("status") or "").lower().replace(" ", "_") for r in rows} - known_stop_statuses()):
        out.append(defect("stop_status_unmapped", P1, "wrong", f"broker stop status {st!r} is not mapped to a house "
                          "stop state: the order shows as 'unknown'", block="stop_plan", field_="state", observed=st,
                          fix="map the status in cio_truth (_ACTIVE/_PENDING/_DEAD_STOP_STATES)"))
    facts = _stop_facts(doc)
    plan = (_blocks(doc).get("stop_plan") or {}).get("broker") or {}
    plan_accts = {a.get("account"): a for a in plan.get("accounts") or []}
    positions = p.positions(sym) or []
    resolver = p.stop_resolver
    for pos in positions:
        acct = pos["account"]
        name = label_fn(acct)
        truth = resolver(acct, sym, rows) if resolver else None
        if not truth:
            continue
        t_level, t_state = _f(truth.get("stop_price")), truth.get("stop_state")
        resting = t_state in ("active", "pending_activation")
        shown = facts.get(name)
        if resting and t_level is not None and not shown and name not in plan_accts:
            out.append(defect("stop_missing", P1, "missing", f"a resting broker stop in {name} is not in the report",
                              block="stop_plan", field_="broker.level", expected=t_level))
        if shown and t_level is not None and _rel(shown["level"], t_level) > 1e-6:
            out.append(defect("stop_level_mismatch", P1, "wrong", f"stop level for {name} differs from stop_last_known",
                              block="position", field_="stop_level", observed=shown["level"], expected=t_level))
        pa = plan_accts.get(name)
        if pa and t_level is not None and _f(pa.get("level")) is not None and _rel(_f(pa["level"]), t_level) > 1e-6:
            out.append(defect("stop_plan_level_mismatch", P1, "wrong", f"stop plan broker level for {name} differs "
                              "from stop_last_known", block="stop_plan", field_="broker.accounts.level",
                              observed=pa.get("level"), expected=t_level))
    # a filled stop dated by the snapshot capture time rather than its fill date
    mh = _blocks(doc).get("my_history") or {}
    fills = [e for e in ((mh.get("current_hold") or {}).get("while_held") or []) if e.get("kind") == "stop_fill"]
    trades = p.trades(sym) or []
    for e in fills:
        lvl = _f(re.sub(r"[^0-9.]", "", str(e.get("headline") or "").split(" at ")[-1].split(" ")[0]) or None)
        sells = [t for t in trades if "sell" in str(t.get("action") or "").lower() and lvl
                 and _f(t.get("price")) and _rel(_f(t["price"]), lvl) < 0.01]
        if sells and all(str(t.get("trade_date"))[:10] != str(e.get("date"))[:10] for t in sells):
            out.append(defect("stop_fill_date_wrong", P1, "wrong", "a filled stop is dated by the stop snapshot's "
                              "capture time, not by the fill (matching sell in trade_transactions)",
                              block="my_history", field_="current_hold.while_held.date", observed=e.get("date"),
                              expected=str(sells[-1].get("trade_date"))[:10],
                              fix="date stop fills by the matching journal sell, never by stop_last_known.captured_at"))
    # distance convention: the stop plan measures (price − stop) ÷ price; the position facts must match it
    last = _val(doc, "Last close")
    for f in _facts(doc):
        m = re.match(r"Distance from last close to stop % \((.+)\)$", str(f.get("label") or ""))
        stop = (facts.get(m.group(1)) or {}).get("level") if m else None
        if m and last and stop and _f(f.get("value")) is not None:
            want = (last - stop) / last * 100
            if abs(_f(f["value"]) - want) > 0.05:
                out.append(defect("stop_distance_convention", P3, "contradiction", "distance to stop is measured from the "
                                  "stop, not from the price (Risk and the stop plan use (price − stop) ÷ price)",
                                  block="position", field_="distance_to_stop_pct", observed=f["value"],
                                  expected=round(want, 3)))
    return out


def report_series(doc: dict) -> list[tuple[str, float]]:
    """The price series the report itself carries: an assembled bundle's ``series.price_1y``, else the stored
    document's 1Y price chart, else the subject's rebased 1Y relative-performance line."""
    ser = (doc.get("series") or {}).get("price_1y")
    if ser:
        return [(str(p[0])[:10], p[1]) for p in ser if isinstance(p, (list, tuple)) and len(p) > 1]
    for ch in doc.get("charts") or []:
        if ch.get("id") == "price_1y":
            pts = ((ch.get("series") or [{}])[0].get("points") or [])
            return [(str(p[0])[:10], p[1]) for p in pts if isinstance(p, (list, tuple)) and len(p) > 1]
    rel = ((_blocks(doc).get("relative_performance") or {}).get("series") or {}).get("1Y") or []
    mine = next((r for r in rel if r.get("name") == doc.get("symbol")), None)
    return [(str(p[0])[:10], p[1]) for p in (mine or {}).get("points") or [] if len(p) > 1]


def check_prices(doc: dict, p: Primary) -> list[dict]:
    sym = doc["symbol"]
    raw = p.closes(sym)
    if raw is None:
        return [defect("price_store_unreadable", P2, "missing", "ticker_prices unreadable", block="price")]
    out: list[dict] = []
    lc = _fact(doc, "Last close")
    asof = _d((lc or {}).get("as_of"))
    s = [x for x in trading_days(raw) if not asof or x[0] <= asof.isoformat()]
    shown = report_series(doc)
    weekend = sum(1 for d, _ in shown if _d(d) and _weekend_or_holiday(_d(d)))
    if weekend:
        out.append(defect("weekend_bars_in_series", P2, "wrong", f"{weekend} Saturday/Sunday/holiday rows in the report's "
                          "price series: bar-count windows (1W = 5 bars, 1Y = 252) and volatility are computed over "
                          "non-sessions", block="relative_performance", field_="returns", observed=weekend, expected=0,
                          fix="drop non-session rows in blocks._series"))
    if not s:
        return out
    if lc and _f(lc.get("value")) and _rel(_f(lc["value"]), s[-1][1]) > TOL["price_rel"]:
        out.append(defect("last_close_mismatch", P1, "wrong", "last close differs from ticker_prices", block="price",
                          field_="last_close", observed=lc["value"], expected=s[-1][1]))
    q = _val(doc, "Latest quote")
    if q and lc and _f(lc.get("value")) and _rel(q, _f(lc["value"])) > 0.2:
        out.append(defect("quote_close_contradiction", P1, "contradiction", "the latest quote and the last close differ "
                          "by more than 20%: one of the two price stores is wrong", block="price", field_="last_close",
                          observed=lc["value"], expected=q))
    rel = _blocks(doc).get("relative_performance") or {}
    mine = next((r for r in rel.get("returns") or [] if r.get("name") == sym), None)
    if mine:
        for w in WINDOWS:
            want, got = window_return(s, w), _f(mine.get(w))
            if want is not None and got is not None and abs(want - got) > TOL["return_pp"]:
                out.append(defect("return_window_mismatch", P1, "wrong", f"{w} return differs from a recompute over "
                                  "trading-day closes", block="relative_performance", field_=f"returns.{w}",
                                  observed=got, expected=want))
    year = s[-253:]
    if len(year) >= 240:
        for label, want in (("1-year high close", max(c for _, c in year)), ("1-year low close", min(c for _, c in year))):
            got = _val(doc, label)
            if got is not None and _rel(got, want) > TOL["price_rel"]:
                out.append(defect("range_mismatch", P1, "wrong", f"{label} differs from ticker_prices", block="price",
                                  field_=label, observed=got, expected=want))
    return out


def _ttm_dividends(rows: list[dict], end: date) -> Optional[float]:
    """Sum of ex-date amounts in the 350 days up to ``end`` (one year of payments, robust to date jitter)."""
    cut = end - timedelta(days=350)
    vals = [_f(r.get("amount")) for r in rows if _d(r.get("ex_date")) and cut < _d(r["ex_date"]) <= end]
    vals = [v for v in vals if v]
    return round(sum(vals), 4) if vals else None


def check_dividends(doc: dict, p: Primary, *, now: datetime) -> list[dict]:
    out: list[dict] = []
    sym = doc["symbol"]
    dps = _fact(doc, "Annual dividend per share")
    fund = _blocks(doc).get("fund_profile") or {}
    hist = p.dividends(sym) or []
    newest = max((_d(r.get("ex_date")) for r in hist if _d(r.get("ex_date"))), default=None)
    # the history may itself be stale: anchor the trailing year on its newest ex-date, and report staleness apart
    ttm = _ttm_dividends(hist, newest) if newest else None
    if dps and _f(dps.get("value")):
        age = (now - _dt(dps.get("as_of"))).days if _dt(dps.get("as_of")) else None
        if ttm and _rel(_f(dps["value"]), ttm) > TOL["dividend_rel"]:
            out.append(defect("dividend_annual_mismatch", P1, "wrong", "annual dividend per share disagrees with the "
                              "trailing-year ex-date history", block="options_sentiment_dividends",
                              field_="dividend.annual_per_share", observed=dps["value"], expected=ttm,
                              fix="cross-check ticker_dividend_data against ticker_dividends; withhold on disagreement"))
        elif age is not None and age > TOL["fundamental_max_age_days"]:
            out.append(defect("dividend_annual_stale", P2, "stale", f"annual dividend per share is {age} days old",
                              block="options_sentiment_dividends", field_="dividend.annual_per_share",
                              observed=dps.get("as_of")))
    if fund.get("ttm_distribution") and ttm and _rel(_f(fund["ttm_distribution"]), ttm) > TOL["dividend_rel"]:
        out.append(defect("fund_ttm_distribution_mismatch", P2, "contradiction", "fund trailing-12-month distribution "
                          "disagrees with the ex-date history", block="fund_profile", field_="ttm_distribution",
                          observed=fund["ttm_distribution"], expected=ttm))
    data = p.dividend_data(sym) or {}
    later = [x for x in (_d(fund.get("last_distribution_date")), _d(data.get("ex_div_date"))) if x and x <= now.date()]
    if newest and later and max(later) > newest:
        out.append(defect("dividend_history_stale", P2, "stale", "ticker_dividends lacks the latest ex-date another "
                          "house store records", block="my_history" if not fund else "fund_profile",
                          field_="dividend_history", observed=newest.isoformat(), expected=max(later).isoformat(),
                          fix="refresh ticker_dividends (dividend ingest)"))
    osd = (_blocks(doc).get("options_sentiment_dividends") or {}).get("dividend") or {}
    if fund.get("dividend_yield_pct") and osd and osd.get("yield_pct") is None:
        out.append(defect("dividend_yield_block_empty", P2, "missing", "the dividends tile shows no yield while the fund "
                          "profile has one", block="options_sentiment_dividends", field_="dividend.yield_pct",
                          expected=fund["dividend_yield_pct"]))
    return out


def check_fundamentals(doc: dict, p: Primary, *, now: datetime) -> list[dict]:
    """Undated or months-old fundamental_data / technical snapshot rows, and their contradictions with house data."""
    out: list[dict] = []
    facts = _facts(doc)
    undated = [f for f in facts if str(f.get("source") or "").startswith("fundamental_data") and not f.get("as_of")]
    old = [f for f in facts if str(f.get("source") or "").startswith("fundamental_data") and _dt(f.get("as_of"))
           and (now - _dt(f["as_of"])).days > TOL["fundamental_max_age_days"]]
    if undated:
        out.append(defect("fundamental_data_undated", P2, "stale", f"{len(undated)} fundamental_data facts carry no "
                          "as_of (the table's fetched_at is not passed through)", block="facts",
                          field_="fundamental_data", observed=len(undated), fix="pass fetched_at; drop rows past the "
                          "freshness limit"))
    if old:
        out.append(defect("fundamental_data_stale", P2, "stale", f"{len(old)} fundamental_data facts older than "
                          f"{TOL['fundamental_max_age_days']} days", block="facts", field_="fundamental_data",
                          observed=len(old)))
    hi = _val(doc, "1-year high close")
    for f in facts:
        lab = str(f.get("label") or "")
        if lab.startswith("52WeekHigh") and hi and _f(f.get("value")) and _rel(_f(f["value"]), hi) > 0.05:
            out.append(defect("fundamental_contradicts_price", P1, "contradiction", "a fundamental_data 52-week high "
                              "contradicts the house 1-year high", block="facts", field_=lab, observed=f["value"],
                              expected=hi))
        if lab.startswith(("50DayMA", "200DayMA", "AnalystTargetPrice", "MarketCap")) and \
                str(f.get("source") or "").endswith("(alpha_vantage)") and not f.get("as_of"):
            out.append(defect("fundamental_undated_price_level", P1, "stale", f"{lab} from alpha_vantage is shown with no "
                              "date; the row is months old", block="facts", field_=lab, observed=f.get("value")))
    snap = [f for f in facts if str(f.get("label") or "").startswith("Technical snapshot:")]
    last = _val(doc, "Last close")
    sp = next((f for f in snap if f["label"] == "Technical snapshot: price"), None)
    if sp and last and _rel(_f(sp.get("value")) or 0, last) > 0.03:
        out.append(defect("technical_snapshot_stale", P1, "contradiction", "technical snapshot price contradicts the "
                          "last close (stale snapshot)", block="facts", field_="Technical snapshot: price",
                          observed=sp.get("value"), expected=last, fix="drop snapshot rows that disagree with the close"))
    zeros = [f["label"] for f in snap if _f(f.get("value")) == 0.0 and f["label"].endswith(("target", "change_pct"))]
    if zeros:
        out.append(defect("technical_snapshot_placeholder", P3, "wrong", "technical snapshot carries placeholder zeros",
                          block="facts", field_=",".join(zeros), observed=0.0))
    if snap and not any(f.get("as_of") for f in snap):
        out.append(defect("technical_snapshot_undated", P2, "stale", "technical snapshot facts carry no as_of",
                          block="facts", field_="technical_snapshot"))
    empty_opts = [f["id"] for f in facts if f.get("kind") == "options" and re.fullmatch(r"\s*:?\s*", str(f.get("text") or ""))]
    if empty_opts:
        out.append(defect("options_thesis_empty", P3, "wrong", f"{len(empty_opts)} options-thesis facts with no text "
                          "(':')", block="facts", field_="Options thesis", observed=len(empty_opts)))
    return out


def check_finviz(doc: dict, p: Primary) -> list[dict]:
    sym = doc["symbol"]
    rec = p.finviz(sym)
    out: list[dict] = []
    cap = _fact(doc, "Market cap ($B)")
    if cap and rec and _f(cap.get("value")):
        usd = _f(rec.get("market_cap_usd"))
        want = round(usd / 1e9, 2) if usd else (_f(rec.get("market_cap_b")) or 0) / 1000.0
        if want and _rel(_f(cap["value"]), want) > 0.05 and str(cap.get("as_of") or "")[:19] == str(rec.get("cached_at") or "")[:19]:
            out.append(defect("market_cap_units", P1, "wrong", "market cap differs from the Finviz cache ($M → $B)",
                              block="facts", field_="Market cap ($B)", observed=cap["value"], expected=round(want, 2)))
    if not rec:
        return out
    same_snapshot = cap is None or str(cap.get("as_of") or "")[:19] == str(rec.get("cached_at") or "")[:19]
    if not same_snapshot:
        return out
    for key, label in (("pe", "P/E"), ("forward_pe", "Forward P/E"), ("div_yield_pct", "Dividend yield %"),
                       ("roe_pct", "ROE %"), ("beta", "Beta")):
        got, want = _val(doc, label), _f(rec.get(key))
        if got is not None and want is not None and _rel(got, want) > 0.001:
            out.append(defect("finviz_value_mismatch", P1, "wrong", f"{label} differs from the Finviz cache",
                              block="facts", field_=label, observed=got, expected=want))
    peers = (_blocks(doc).get("peer_comparison") or {}).get("rows") or []
    # the subject's cache time is on the cache's own clock: a peer row stamped later was refreshed after writing
    written = str((cap or {}).get("as_of") or rec.get("cached_at") or "")
    return out + _check_peer_rows(peers, p, written=written)


def _check_peer_rows(peers: list[dict], p: Primary, *, written: str = "") -> list[dict]:
    out = []
    for r in peers:
        if r.get("is_subject"):
            continue
        rec = p.finviz(str(r.get("symbol") or "")) or {}
        if written and str(rec.get("cached_at") or "")[:19] > written[:19]:
            continue  # the peer's cache row was refreshed after the report was written: drift, not a defect
        for key in ("forward_pe", "oper_margin_pct", "roe_pct", "perf_year_pct"):
            got, want = _f(r.get(key)), _f(rec.get(key))
            if got is not None and want is not None and _rel(got, want) > 0.001:
                out.append(defect("peer_value_mismatch", P1, "wrong", f"peer {r.get('symbol')} {key} differs from the "
                                  "Finviz cache", block="peer_comparison", field_=key, observed=got, expected=want))
    return out


def check_macro(doc: dict, p: Primary) -> list[dict]:
    out: list[dict] = []
    macro = _blocks(doc).get("macro_sensitivity") or {}
    series = macro.get("series") or {}
    for sid, row in series.items():
        pts = p.fred(sid)
        if not pts or row.get("value") is None:
            continue
        upto = [x for x in pts if x[0] <= str(row.get("as_of") or "9999")[:10]]
        if not upto:
            continue
        d, v = upto[-1]
        if d != str(row.get("as_of"))[:10] or abs(v - _f(row["value"])) > 1e-6:
            out.append(defect("fred_value_mismatch", P1, "wrong", f"FRED {sid} differs from fred_economic_series",
                              block="macro_sensitivity", field_=sid, observed=[row.get("as_of"), row.get("value")],
                              expected=[d, v]))
        if pts[-1][0] > str(row.get("as_of"))[:10]:
            out.append(defect("fred_not_latest", P2, "stale", f"FRED {sid} is not the latest observation",
                              block="macro_sensitivity", field_=sid, observed=row.get("as_of"), expected=pts[-1][0]))
    labels = " ".join(str((r or {}).get("label") or "") for r in series.values()).lower()
    for sid, label in EXPECTED_MACRO.items():
        if sid not in series and label.lower() not in labels:
            has = bool(p.fred(sid))
            out.append(defect("macro_series_missing", P2, "missing", f"{label} ({sid}) absent from the macro block"
                              + ("; the series IS in fred_economic_series (reader maps a different id)" if has
                                 else "; the series is not ingested"), block="macro_sensitivity", field_=sid,
                              fix="map DFF as Fed funds" if has else "add the series to the FRED ingest"))
    if macro.get("rate_beta_10y") is None:
        out.append(defect("rate_beta_missing", P2, "missing", "rate beta to the 10-year yield is n/a",
                          block="macro_sensitivity", field_="rate_beta_10y", fix="ingest FRED DGS10"))
    if macro.get("next_events_gap"):
        out.append(defect("macro_calendar_missing", P2, "missing", f"macro calendar: {macro['next_events_gap']}",
                          block="macro_sensitivity", field_="next_events"))
    return out


def check_history(doc: dict, p: Primary) -> list[dict]:
    mh = _blocks(doc).get("my_history") or {}
    out: list[dict] = []
    if not mh or mh.get("scope") in (None, "unavailable", "never"):
        return out
    for lot in mh.get("open_lots") or []:
        if lot.get("unrealized_usd") is None and lot.get("market_value") and lot.get("avg_cost") and lot.get("shares"):
            out.append(defect("open_lot_pl_missing", P2, "missing", f"open position in {lot.get('account')} shows no "
                              "unrealized P/L although value and cost are known", block="my_history",
                              field_="open_lots.unrealized_usd",
                              expected=round(lot["market_value"] - lot["avg_cost"] * lot["shares"], 2),
                              fix="my_history.position_rows: value_and_pl returns gain_loss"))
    trades = p.trades(doc["symbol"]) or []
    sold = sum(abs(_f(t.get("quantity")) or 0) for t in trades if str(t.get("action") or "").lower().startswith("sell"))
    tripped = sum(_f(t.get("shares")) or 0 for t in mh.get("trips") or [])
    gaps = " ".join(str(g) for g in mh.get("gaps") or [])
    if sold > 1 and tripped < TOL["realized_cover_min"] * sold and "not in the round trips" not in gaps:
        out.append(defect("realized_history_incomplete", P2, "missing", f"round trips cover {tripped:g} of {sold:g} "
                          "shares sold in the journal; the realized totals omit the rest without saying so",
                          block="my_history", field_="totals.realized_usd", observed=tripped, expected=sold,
                          fix="name the sold shares with unknown basis in the block and its gaps"))
    return out


def check_fund(doc: dict, p: Primary) -> list[dict]:
    out: list[dict] = []
    b = _blocks(doc)
    fp = b.get("fund_profile")
    lt = b.get("fund_lookthrough") or {}
    if fp is not None:
        if not fp.get("top_holdings") and lt.get("top_holdings"):
            out.append(defect("fund_top_holdings_dropped", P2, "contradiction", "fund profile says no look-through "
                              "entry while the look-through block lists top holdings", block="fund_profile",
                              field_="top_holdings", observed=0, expected=len(lt["top_holdings"]),
                              fix="read look-through rows by ticker/pct as well as symbol/weight"))
        peers = (b.get("peer_comparison") or {}).get("rows") or []
        if fp.get("peers") and not peers:
            out.append(defect("fund_peers_not_compared", P2, "missing", "fund has category peers but the peer table is "
                              "empty", block="peer_comparison", field_="rows", expected=fp.get("peers")))
    if lt.get("top_holdings") and not any(str(f.get("label") or "").startswith("Fund top holding") for f in _facts(doc)) \
            and not (fp or {}).get("top_holdings"):
        out.append(defect("fund_top_holdings_not_facts", P2, "missing", "look-through top holdings never became "
                          "citable facts", block="fund_lookthrough", field_="top_holdings"))
    sector = next((f for f in _facts(doc) if f.get("label") == "Sector"), None)
    if fp is not None and sector and str(sector.get("text") or "").lower() in {"financial", "financial services"}:
        out.append(defect("fund_sector_label", P2, "label", "a fund is labelled with the vendor sector 'Financial'",
                          block="facts", field_="Sector", observed=sector.get("text")))
    return out


def check_charts(doc: dict) -> list[dict]:
    out = []
    for ch in doc.get("charts") or []:
        series = ch.get("series") or []
        pts = [pt for s in series for pt in (s.get("points") or [])]
        if not series or not pts:
            out.append(defect("chart_empty", P2, "render", f"chart {ch.get('id')} has no data", block="charts",
                              field_=str(ch.get("id"))))
            continue
        ys = [_f(pt[1]) for pt in pts if isinstance(pt, (list, tuple)) and len(pt) > 1]
        ys = [y for y in ys if y is not None]
        if len(ys) >= 3 and max(ys) == min(ys):
            out.append(defect("chart_flat", P3, "render", f"chart {ch.get('id')} is flat", block="charts",
                              field_=str(ch.get("id"))))
        if ch.get("id") in ("relative_1y", "relative") and len(series) < 2:
            out.append(defect("chart_single_series", P3, "render", f"comparison chart {ch.get('id')} has one series",
                              block="charts", field_=str(ch.get("id"))))
    return out


def check_prose(doc: dict, settings: dict | None = None) -> list[dict]:
    """Numbers in the written sections that no fact supports (the gate's layer-3 matcher, reused)."""
    if not doc.get("sections"):
        return []
    from . import quality_gate as qg
    res = qg.post_write(doc.get("sections") or [], _facts(doc), settings=settings)
    n = int(res.get("unmatched_count") or 0)
    if not n:
        return []
    return [defect("prose_unmatched_numbers", P2 if n > 3 else P3, "contradiction", f"{n} number(s) in the prose "
                   "match no supplied fact", block="sections", field_="prose", observed=(res.get("unmatched") or [])[:6])]


def check_missing(doc: dict) -> list[dict]:
    """Every None / empty field of the institutional blocks, as one P3 inventory row each (aggregated by caller)."""
    out = []
    for name, blk in _blocks(doc).items():
        if not isinstance(blk, dict):
            continue
        for k, v in blk.items():
            if k in ("gaps", "unreliable", "basis", "facts", "advisory", "schema") or k.startswith("_"):
                continue
            if v is None or v == [] or v == {}:
                out.append(defect("field_empty", P3, "missing", f"{name}.{k} empty", block=name, field_=k))
    return out


CHECKS = ("position", "stops", "prices", "dividends", "fundamentals", "finviz", "macro", "history", "fund", "charts",
          "prose")


def audit(doc: dict, primary: Primary, *, now: datetime | None = None, label_fn: Callable[[str], str] = str,
          include_inventory: bool = False) -> dict:
    """All defects for one report. A crashing check is itself a defect, never a silent pass."""
    now = now or datetime.now(timezone.utc)
    runs: list[tuple[str, Callable[[], list[dict]]]] = [
        ("position", lambda: check_position(doc, primary)),
        ("stops", lambda: check_stops(doc, primary, label_fn=label_fn)),
        ("prices", lambda: check_prices(doc, primary)),
        ("dividends", lambda: check_dividends(doc, primary, now=now)),
        ("fundamentals", lambda: check_fundamentals(doc, primary, now=now)),
        ("finviz", lambda: check_finviz(doc, primary)),
        ("macro", lambda: check_macro(doc, primary)),
        ("history", lambda: check_history(doc, primary)),
        ("fund", lambda: check_fund(doc, primary)),
        ("charts", lambda: check_charts(doc)),
        ("prose", lambda: check_prose(doc)),
    ]
    if include_inventory:
        runs.append(("inventory", lambda: check_missing(doc)))
    found: list[dict] = []
    for name, fn in runs:
        try:
            found += fn()
        except Exception as exc:  # noqa: BLE001
            found.append(defect("check_error", P2, "missing", f"{name}: {type(exc).__name__}: {str(exc)[:160]}",
                                block=name))
    counts = {sev: sum(1 for d in found if d["severity"] == sev) for sev in (P1, P2, P3)}
    return {"schema": SCHEMA, "symbol": doc.get("symbol"), "scope": doc.get("scope"), "version": doc.get("version"),
            "checked_at": now.isoformat(), "counts": counts, "defects": found}


def summarize(results: list[dict]) -> dict:
    """Counts by severity and class, and the defect codes ranked by severity then the number of tickers affected."""
    by_code: dict[str, dict] = {}
    for r in results:
        for d in r["defects"]:
            row = by_code.setdefault(d["code"], {"code": d["code"], "severity": d["severity"], "klass": d["klass"],
                                                 "block": d["block"], "tickers": []})
            if r["symbol"] not in row["tickers"]:
                row["tickers"].append(r["symbol"])
    ranked = sorted(by_code.values(), key=lambda x: (x["severity"], -len(x["tickers"]), x["code"]))
    sev = {s: sum(1 for x in ranked if x["severity"] == s) for s in (P1, P2, P3)}
    klass: dict[str, int] = {}
    for x in ranked:
        klass[x["klass"]] = klass.get(x["klass"], 0) + 1
    return {"reports": len(results), "codes_by_severity": sev, "codes_by_class": klass, "codes": ranked}


# ── standing QA: data-gap routing, the window note, the monthly prose sample ──────────────────────────────────
#: Defect code → registry domain (config/data_source_authority.json) whose owner lane can repair the data. Codes not
#: listed are code/wiring defects: they go to the findings file and the note, never to the data-gap queue.
GAP_DOMAIN = {
    "dividend_annual_mismatch": "dividends", "dividend_annual_stale": "dividends", "dividend_history_stale": "dividends",
    "fund_ttm_distribution_mismatch": "dividends",
    "fundamental_data_undated": "fundamentals", "fundamental_data_stale": "fundamentals",
    "fundamental_undated_price_level": "fundamentals", "fundamental_contradicts_price": "fundamentals",
    "finviz_value_mismatch": "fundamentals", "peer_value_mismatch": "fundamentals",
    "technical_snapshot_stale": "technicals", "technical_snapshot_undated": "technicals",
    "quote_close_contradiction": "quote_price",
    "macro_series_missing": "macro", "rate_beta_missing": "macro", "fred_not_latest": "macro",
}
#: Defects that mean the stored report no longer matches the book (a trade or stop change since it was written):
#: the remedy is a rewrite of that report, listed in the run's ``rewrite_due`` (the window decides), not a data repair.
REWRITE_CODES = {"position_shares_mismatch", "position_avg_cost_mismatch", "stop_level_mismatch", "stop_missing",
                 "stop_plan_level_mismatch"}


def rewrite_due(results: list[dict]) -> list[dict]:
    out = []
    for r in results:
        codes = sorted({d["code"] for d in r.get("defects") or [] if d["code"] in REWRITE_CODES})
        if codes:
            out.append({"symbol": r.get("symbol"), "version": r.get("version"), "codes": codes})
    return out


def gap_requests(results: list[dict]) -> list[dict]:
    """One data-gap request per (domain, symbol) from the P1/P2 data defects of an audit run."""
    seen: dict[tuple[str, str], dict] = {}
    for r in results:
        for d in r.get("defects") or []:
            dom = GAP_DOMAIN.get(d["code"])
            if not dom or d["severity"] not in (P1, P2):
                continue
            key = (dom, str(r.get("symbol")))
            row = seen.setdefault(key, {"domain": dom, "symbol": r.get("symbol"), "codes": []})
            if d["code"] not in row["codes"]:
                row["codes"].append(d["code"])
    return list(seen.values())


def window_note(summary: dict, *, max_codes: int = 6) -> Optional[str]:
    """The P2 line for the run window's email audit; None when the run found no P1/P2 defect."""
    rows = [c for c in summary.get("codes") or [] if c["severity"] in (P1, P2)]
    if not rows:
        return None
    sev = summary.get("codes_by_severity") or {}
    head = (f"P2 prospectus accuracy: {len(rows)} defect class(es) across {summary.get('reports')} report(s) "
            f"({sev.get(P1, 0)} P1, {sev.get(P2, 0)} P2)")
    tail = "; ".join(f"{c['severity']} {c['code']} ×{len(c['tickers'])}" for c in rows[:max_codes])
    return f"{head}: {tail}" + ("; …" if len(rows) > max_codes else "")


REVIEW_PROCESS = "prospectus_accuracy_review"
REVIEW_MONTHLY_CAP_USD = 2.0
REVIEW_EST_COST_USD = 0.45     # one Opus read: ~25k input + ~2k output tokens at list price
REVIEW_SAMPLE = 3


def review_budget(ledger: dict, *, month: str, cap: float = REVIEW_MONTHLY_CAP_USD,
                  est: float = REVIEW_EST_COST_USD) -> dict:
    """{spent, remaining, allowed} for this UTC month from the review ledger ({month: [{cost_usd, ...}]})."""
    spent = round(sum(float(x.get("cost_usd") or 0) for x in (ledger.get(month) or [])), 4)
    return {"month": month, "spent_usd": spent, "cap_usd": cap, "remaining_usd": round(cap - spent, 4),
            "allowed": spent + est <= cap}


def sample_for_review(results: list[dict], docs: dict[str, dict], *, n: int = REVIEW_SAMPLE) -> list[str]:
    """Holdings first, most defects first, then the rest: the reports a human-grade read helps most."""
    ranked = sorted(results, key=lambda r: (r.get("scope") != "holding", -sum((r.get("counts") or {}).values()),
                                            str(r.get("symbol"))))
    return [r["symbol"] for r in ranked if r.get("symbol") in docs and (docs[r["symbol"]].get("sections"))][:n]


def review_prompt(doc: dict, *, max_facts: int = 160, max_chars: int = 60000) -> str:
    """Prose-vs-facts review prompt: the written sections and the facts they may cite (no account names)."""
    facts = [{k: f.get(k) for k in ("id", "label", "value", "unit", "text", "as_of") if f.get(k) is not None}
             for f in _facts(doc)[:max_facts]]
    sections = [{"id": s.get("id"), "title": s.get("title"), "text": s.get("text") or s.get("body")}
                for s in doc.get("sections") or []]
    body = json.dumps({"symbol": doc.get("symbol"), "verdict_line": doc.get("verdict_line"), "sections": sections,
                       "facts": facts}, default=str)[:max_chars]
    return ("You are auditing a research report for accuracy against its own cited facts. Read every sentence. "
            "List each statement whose number, date, direction or claim is not supported by the facts, contradicts "
            "another section, or overstates certainty. Return JSON only: {\"issues\": [{\"section\": str, "
            "\"quote\": str, \"problem\": str, \"severity\": \"P1\"|\"P2\"|\"P3\", \"fact_ids\": [str]}], "
            "\"overall\": str}. P1 = a wrong money, position, stop or price statement.\n\n" + body)


def parse_review(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        out = json.loads(m.group(0)) if m else {}
    except ValueError:
        out = {}
    issues = [i for i in (out.get("issues") or []) if isinstance(i, dict) and i.get("problem")]
    return {"issues": issues[:40], "overall": str(out.get("overall") or "")[:600], "parsed": bool(m)}
