"""Ticker Prospectus data-quality gate (operator-approved 2026-10-26: "build this and execute it immediately").

Goal: never spend Opus/Fable on bad data. Three layers, all READ_ONLY_ADVISORY (MBI_BEHAVIOR=0):

Layer 1 — deterministic, free, run on the assembled facts packet before ANY paid call (the web-search planning turn
included). Price-series shape (isolated jumps, first-bar outlier, pre-listing / symbol-reuse level breaks,
non-positive prices, gaps, stale last bar), units and ranges (market cap $M vs $B, beta, annualized volatility, P/E),
house vs Finviz agreement (YTD / 1Y), peer sanity (alphabetical / ETF-cohort junk, industry), source-type sanity
(transcript is an earnings call for the issuer; filings agree on one CIK) and minimum coverage.

    HARD_FAIL → no model call; status ``blocked_data`` with reasons; a data repair goes to the data-gap queue.
    SOFT_FAIL → the report is written but marked ``partial``; the writer is told which facts are not reliable and the
                blocks print "not reliable (reason)" instead of the number.

Layer 2 — one cheap read of the facts packet (not prose) by ``claude-haiku-5-5`` through the governed credit path
(process ``prospectus_fact_check``, Anthropic-only, bulk tier). When the credit is unavailable the read falls back to
the free Grok OAuth lane (process ``prospectus_fact_check_oauth``, grok only) — never DeepSeek. High-severity
anomalies become a SOFT_FAIL, or a HARD_FAIL when they confirm a layer-1 hit.

Layer 3 — deterministic post-write check: every number in a written section must match a fact the section cites
(value tolerance, $/%/B/M units). More than ``post_write_max_unmatched`` unmatched numbers → ``partial`` and a
rewrite is requested.

Where the concurrent data-defect fixes exist (``blocks.series_quality``, ``domains.transcript_rejection``) the gate
calls them; where they do not, the checks below stand on their own. The price checks run on the RAW series
(``bundle.series["price_1y_raw"]``, before the price guard drops bars), so a bad first bar or pre-listing /
symbol-reuse history is still reported. When the guard has excluded exactly those bars the finding is SOFT (the
report proceeds on the cleaned series and says "excluded N bad bar(s)"); it stays HARD when fewer than
``min_clean_sessions`` clean sessions remain. Thresholds: ``DEFAULTS`` overridden by the
optional ``config/prospectus_quality_gate.json``.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
import math
from pathlib import Path
import re
import statistics
from typing import Any, Callable, Iterable, Optional

SCHEMA = "ProspectusGate@v1"
PASS, SOFT, HARD = "pass", "soft_fail", "hard_fail"
CONFIG_REL = "config/prospectus_quality_gate.json"
PROCESS_AI = "prospectus_fact_check"
PROCESS_AI_OAUTH = "prospectus_fact_check_oauth"

DEFAULTS: dict[str, Any] = {
    "jump_factor": 3.0,               # bar/neighbour ratio above which a move is a data defect
    "revert_band": 1.5,               # an isolated jump reverts to within this ratio of the bar before it
    "gap_calendar_days": 10,          # consecutive bars further apart than this are a series gap
    "stale_soft_sessions": 3,
    "stale_hard_sessions": 10,
    "min_series_bars": 20,
    "min_clean_sessions": 20,         # a bad first bar / pre-break history the price guard drops is SOFT only while
                                      # at least this many clean sessions remain; fewer → HARD (nothing to report on)
    "beta_range": [-3.0, 5.0],
    "vol_max_pct": 200.0,
    "pe_max": 1000.0,
    "market_cap_b_max": 50000.0,      # above $50T the value is almost certainly $M recorded as $B (was $5T: two
                                      # mega-caps crossed it in 2026 and their real caps were marked not reliable)
    "market_cap_peer_ratio_max": 1000.0,
    "cross_source_abs_pp": 10.0,      # house vs Finviz performance: flag beyond max(abs pp, rel × |finviz|)
    "cross_source_rel": 0.25,
    "peer_min_rows": 3,
    "post_write_max_unmatched": 3,
    # accuracy checks (accuracy audit 2026-10-26)
    "dividend_rel_tol": 0.25,         # annual dividend $/share vs the trailing year actually paid
    "fundamental_max_age_days": 30,   # fundamental_data rows older than this (or undated) are not reliable
    "snapshot_price_rel_tol": 0.03,   # technical snapshot price vs the house last close
    "position_mv_rel_tol": 0.01,      # market value vs shares x the report's own price
    "position_pl_abs_usd": 1.0,       # unrealized P/L vs market value - cost
    "quote_close_rel_max": 0.2,       # latest quote vs last close
    "post_write_rel_tol": 0.006,
    "ai": {"enabled": True, "max_tokens": 1200, "timeout_s": 60, "max_packet_chars": 18000,
           "est_input_tokens": 5500, "est_output_tokens": 600},
}

EARNINGS_CALL_RE = re.compile(
    r"(?i)\bearnings\s+(?:call|conference)|\bconference\s+call\b|\b(?:Q[1-4]|first|second|third|fourth)\b[^\n]{0,40}"
    r"\b(?:earnings|results)\b[^\n]{0,20}\bcall\b|\bQ[1-4]\s*(?:FY)?\s*\d{2,4}\s+(?:earnings|results)\b")
CIK_RE = re.compile(r"(?:/data/|CIK=?|cik=)0*(\d{3,10})", re.I)
NUM_RE = re.compile(r"(?<![\w.])([-+−]?)\$?(\d[\d,]*(?:\.\d+)?)\s*(%|[kKmMbB](?:n|illion)?(?![a-z])|x\b|×)?")
SKIP_TOKEN_RE = re.compile(r"\b(?:Q[1-4]|FY|H[12]|10-[KQ]|8-K|S-1|13[FDG]|Form\s*\d|DEF\s*14A|424B\d|S&P\s*\d+)\S*", re.I)
CITE_RE = re.compile(r"\[(?:[FW]\d+(?:\s*,\s*[FW]\d+)*)\]")
DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:T[\d:.]+Z?)?\b")


def load_settings(root: Path | None = None) -> dict[str, Any]:
    out = json.loads(json.dumps(DEFAULTS))
    path = (root or Path(__file__).resolve().parents[3]) / CONFIG_REL
    try:
        over = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return out
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        elif not str(k).startswith("_"):
            out[k] = v
    return out


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


def _finding(code: str, severity: str, message: str, *, facts: Iterable[str] = (), blocks: Iterable[list] = (),
             repair: str | None = None, layer: int = 1) -> dict:
    return {"code": code, "severity": severity, "layer": layer, "message": message[:300], "facts": list(facts),
            "blocks": [list(p) for p in blocks], "repair_domain": repair}


# ── packets ───────────────────────────────────────────────────────────────────────────────────────────────────
def packet_from_bundle(bundle: Any, *, now: datetime | None = None) -> dict:
    """The assembled facts packet the writer will see (plus the price series and blocks it was derived from)."""
    return {"symbol": bundle.symbol, "name": bundle.name, "scope": bundle.scope, "facts": bundle.facts,
            # RAW closes (before blocks.series_quality drops bad bars) so the price checks still see them
            "series": list(bundle.series.get("price_1y_raw") or bundle.series.get("price_1y") or []),
            # the facts were built on the guard's cleaned series (inputs.assemble), so a defect it dropped is SOFT
            "series_guarded": "price_1y_raw" in bundle.series,
            "blocks": bundle.blocks,
            "coverage": list(bundle.coverage), "context": dict(bundle.context),
            "as_of": (now or datetime.now(timezone.utc)).isoformat()}


def packet_from_doc(doc: dict) -> dict:
    """Rebuild the packet from a stored Prospectus@v1 document (``--gate-only`` over existing reports)."""
    series = []
    for chart in doc.get("charts") or []:
        if chart.get("id") == "price_1y":
            series = [(p[0], p[1]) for p in ((chart.get("series") or [{}])[0].get("points") or []) if len(p) == 2]
    cov = doc.get("source_coverage") or {}
    return {"symbol": doc.get("symbol"), "name": doc.get("name"), "scope": doc.get("scope") or "watch",
            "facts": doc.get("facts") or [], "series": series, "blocks": doc.get("blocks") or {},
            "coverage": cov.get("house_sources") or [], "context": dict(doc.get("inputs_digest") or {}),
            "as_of": doc.get("generated_at") or datetime.now(timezone.utc).isoformat(),
            "web": {"searches": cov.get("web_searches") or [], "stopped": cov.get("web_stopped")}}


def _by_label(facts: list[dict], pred: Callable[[str], bool]) -> list[dict]:
    return [f for f in facts if pred(str(f.get("label") or ""))]


def _one(facts: list[dict], label: str) -> Optional[dict]:
    return next((f for f in facts if f.get("label") == label and "value" in f), None)


# ── layer 1: price series ─────────────────────────────────────────────────────────────────────────────────────
def _external_series_guard(series: list) -> Optional[dict]:
    """The price guard (``blocks.series_quality``) over ``series`` when it exists: which bars it excludes, the break it
    cuts at and how many clean sessions remain. ``check_series`` uses it to grade a guarded defect SOFT."""
    try:
        from . import blocks as bk
        fn = getattr(bk, "series_quality", None)
        if fn is None:
            return None
        out = fn([{"price_date": d, "close": c} for d, c in series])
        keys = ("excluded", "break", "raw_sessions", "clean_sessions", "clean_from")
        return {k: out.get(k) for k in keys} if isinstance(out, dict) else None
    except Exception:  # noqa: BLE001 - a guard that fails is recorded as absent
        return None


def _sessions_between(a: date, b: date) -> int:
    if b <= a:
        return 0
    n, d = 0, a
    while d < b:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def check_series(packet: dict, s: dict) -> list[dict]:
    out: list[dict] = []
    pts = [(str(d)[:10], _f(c)) for d, c in packet.get("series") or []]
    pts = [(d, c) for d, c in pts if c is not None]
    price_facts = [f["id"] for f in packet["facts"] if f.get("kind") in ("price", "relative", "risk")]
    if not pts:
        return out
    k = float(s["jump_factor"])
    # Only a fresh bundle's facts are built on the guard's cleaned series; a stored report's chart (--gate-only)
    # printed whatever it held, so a defect in it stays HARD (rewrite).
    guard = _external_series_guard(pts) if packet.get("series_guarded") else None
    dropped = {str(e.get("date"))[:10] for e in (guard or {}).get("excluded") or []}
    cut = str(((guard or {}).get("break") or {}).get("date") or "")[:10]

    def graded(code: str, message: str, dates: list[str]) -> dict:
        """HARD unless the price guard already dropped every bar in ``dates`` and enough clean sessions remain."""
        if guard is None or not dates or not all(d in dropped or (cut and d < cut) for d in dates):
            return _finding(code, HARD, message, facts=price_facts, repair="quote_price")
        n_clean = int(guard.get("clean_sessions") or 0)
        n_bad = len(dropped | {d for d, _ in pts if cut and d < cut})
        if n_clean < int(s.get("min_clean_sessions", s["min_series_bars"])):
            return _finding(code, HARD, f"{message}; the price guard excluded {n_bad} bad bar(s) but only {n_clean} "
                            "clean session(s) remain", facts=price_facts, repair="quote_price")
        f = _finding(code, SOFT, f"{message}; excluded {n_bad} bad bar(s): the report uses the cleaned series "
                     f"({n_clean} clean sessions from {guard.get('clean_from')})", repair="quote_price")
        f["guarded"] = True  # informational: no fact is unreliable (the facts come from the cleaned series)
        return f
    if any(c <= 0 for _, c in pts):
        out.append(_finding("nonpositive_price", HARD, f"{sum(c <= 0 for _, c in pts)} bar(s) with a zero or negative "
                            "close", facts=price_facts, repair="quote_price"))
    closes = [c for _, c in pts if c > 0]
    if len(closes) >= 6:
        head = statistics.median(closes[1:6])
        r = closes[0] / head if head else 1.0
        if r > k or r < 1 / k:
            out.append(graded("first_bar_outlier", f"first bar ({pts[0][0]}) is {r:.2f}x the next five bars' "
                              "median: listing-day / prior-symbol bar", [pts[0][0]]))
        tail = statistics.median(closes[-6:-1])
        r = closes[-1] / tail if tail else 1.0
        if r > k or r < 1 / k:
            out.append(_finding("last_bar_outlier", HARD, f"last bar ({pts[-1][0]}) is {r:.2f}x the prior five bars' "
                                "median", facts=price_facts, repair="quote_price"))
    isolated, breaks = [], []
    for i in range(1, len(closes) - 1):
        prev, cur, nxt = closes[i - 1], closes[i], closes[i + 1]
        r = cur / prev
        if r > k or r < 1 / k:
            if 1 / float(s["revert_band"]) <= nxt / prev <= float(s["revert_band"]):
                isolated.append(pts[i][0])
            elif i > 1:  # a level break that persists: bars before it belong to another listing / symbol
                breaks.append(pts[i][0])
    if isolated:
        out.append(_finding("isolated_price_jump", HARD, f"{len(isolated)} isolated bar(s) >{k:g}x their neighbours "
                            f"(first {isolated[0]})", facts=price_facts, repair="quote_price"))
    if breaks:
        out.append(graded("pre_listing_or_symbol_reuse", f"persistent >{k:g}x level break at {breaks[0]}: "
                          "bars before it look like another listing", [d for d, _ in pts if d < breaks[-1]]))
    gaps = []
    for (a, _), (b, _) in zip(pts, pts[1:]):
        da, db = _d(a), _d(b)
        if da and db and (db - da).days > int(s["gap_calendar_days"]):
            gaps.append(a)
    if gaps:
        out.append(_finding("series_gap", SOFT, f"{len(gaps)} gap(s) over {s['gap_calendar_days']} calendar days in "
                            f"the price series (first after {gaps[0]})",
                            facts=[f["id"] for f in packet["facts"] if f.get("kind") == "risk"],
                            blocks=[["risk_technicals", "vol_annualized_pct"], ["risk_technicals", "beta_1y"]],
                            repair="quote_price"))
    last, ref = _d(pts[-1][0]), _d(packet.get("as_of"))
    if last and ref:
        n = _sessions_between(last, ref)
        if n > int(s["stale_hard_sessions"]):
            out.append(_finding("stale_last_bar", HARD, f"last bar {pts[-1][0]} is {n} sessions old", facts=price_facts,
                                repair="quote_price"))
        elif n > int(s["stale_soft_sessions"]):
            out.append(_finding("stale_last_bar", SOFT, f"last bar {pts[-1][0]} is {n} sessions old",
                                facts=[f["id"] for f in packet["facts"] if f.get("kind") == "price"], repair="quote_price"))
    if len(pts) < int(s["min_series_bars"]):
        out.append(_finding("short_series", SOFT, f"only {len(pts)} bars: 1Y statistics are not meaningful",
                            facts=[f["id"] for f in packet["facts"] if f.get("kind") in ("risk", "relative")],
                            blocks=[["risk_technicals", k2] for k2 in ("beta_1y", "vol_annualized_pct", "max_drawdown_1y_pct")]))
    return out


# ── layer 1: units, ranges, cross-source, peers, source types, coverage ───────────────────────────────────────
def check_units(packet: dict, s: dict) -> list[dict]:
    out, facts, blocks = [], packet["facts"], packet.get("blocks") or {}
    cap = _one(facts, "Market cap ($B)")
    peers = (blocks.get("peer_comparison") or {}).get("rows") or []
    peer_caps = [_f(r.get("market_cap_b")) for r in peers if not r.get("is_subject")]
    peer_caps = [c for c in peer_caps if c and c > 0]
    cap_facts = ([cap["id"]] if cap else []) + [f["id"] for f in facts if f.get("kind") == "peers"
                                                and str(f.get("label") or "").endswith("Mkt cap ($B)")]
    cap_facts += [f["id"] for f in facts if f.get("label") == "Peer median Mkt cap ($B)"]
    if cap and cap["value"] > float(s["market_cap_b_max"]):
        out.append(_finding("market_cap_units", SOFT, "market cap labelled $B exceeds the plausible maximum: $M recorded "
                            "as $B", facts=cap_facts, blocks=[["peer_comparison", "rows", i, "market_cap_b"]
                                                               for i in range(len(peers))], repair="fundamentals"))
    elif cap and cap["value"] > 0 and len(peer_caps) >= 2:
        ratio = cap["value"] / statistics.median(peer_caps)
        lim = float(s["market_cap_peer_ratio_max"])
        if ratio > lim or ratio < 1 / lim:
            out.append(_finding("market_cap_units", SOFT, f"market cap is {ratio:.3g}x the peer median: unit mismatch "
                                "between subject and peers", facts=cap_facts,
                                blocks=[["peer_comparison", "rows", i, "market_cap_b"] for i in range(len(peers))],
                                repair="fundamentals"))
    lo, hi = s["beta_range"]
    for label, path in (("Beta", None), ("Beta (1Y vs SPY)", ["risk_technicals", "beta_1y"])):
        f = _one(facts, label)
        if f and not (float(lo) <= f["value"] <= float(hi)):
            out.append(_finding("beta_out_of_range", SOFT, f"{label} outside [{lo}, {hi}]", facts=[f["id"]],
                                blocks=[path] if path else []))
    f = _one(facts, "Annualized volatility %")
    if f and f["value"] > float(s["vol_max_pct"]):
        out.append(_finding("volatility_absurd", SOFT, f"annualized volatility above {s['vol_max_pct']:g}%",
                            facts=[f["id"]], blocks=[["risk_technicals", "vol_annualized_pct"]]))
    for label in ("P/E", "Forward P/E"):
        f = _one(facts, label)
        if f and (f["value"] <= 0 or f["value"] > float(s["pe_max"])):
            out.append(_finding("pe_absurd", SOFT, f"{label} {'non-positive' if f['value'] <= 0 else 'above ' + str(s['pe_max'])}",
                                facts=[f["id"]], repair="fundamentals"))
    nonpos = [f["id"] for f in facts if f.get("kind") == "price" and f.get("unit") == "$" and "value" in f
              and f["value"] <= 0]
    if nonpos:
        out.append(_finding("nonpositive_price", HARD, "a price fact is zero or negative", facts=nonpos, repair="quote_price"))
    return out


def check_cross_source(packet: dict, s: dict) -> list[dict]:
    out, facts, sym = [], packet["facts"], packet["symbol"]
    blocks = packet.get("blocks") or {}
    rel_rows = (blocks.get("relative_performance") or {}).get("returns") or []
    idx = next((i for i, r in enumerate(rel_rows) if r.get("name") == sym), None)
    peer_rows = (blocks.get("peer_comparison") or {}).get("rows") or []
    subj = next((i for i, r in enumerate(peer_rows) if r.get("is_subject")), None)
    pairs = [("YTD", _one(facts, f"{sym} return YTD %"), _one(facts, "Performance YTD %"),
              [["relative_performance", "returns", idx, "YTD"]] if idx is not None else []),
             ("1Y", _one(facts, "1-year price change %"), None,
              [["relative_performance", "returns", idx, "1Y"]] if idx is not None else [])]
    if subj is not None and _f(peer_rows[subj].get("perf_year_pct")) is not None:
        pairs[1] = ("1Y", pairs[1][1], {"id": None, "value": _f(peer_rows[subj]["perf_year_pct"])},
                    pairs[1][3] + [["peer_comparison", "rows", subj, "perf_year_pct"]])
    for window, house, finviz, paths in pairs:
        if not house or not finviz:
            continue
        diff = abs(house["value"] - finviz["value"])
        if diff > max(float(s["cross_source_abs_pp"]), float(s["cross_source_rel"]) * abs(finviz["value"])):
            out.append(_finding("cross_source_disagreement", SOFT, f"house {window} return and Finviz {window} "
                                f"performance differ by {diff:.1f} pp", facts=[i for i in (house["id"], finviz["id"]) if i],
                                blocks=paths, repair="quote_price"))
    return out


def check_peers(packet: dict, s: dict) -> list[dict]:
    block = (packet.get("blocks") or {}).get("peer_comparison") or {}
    rows = block.get("rows") or []
    peers = [(i, r) for i, r in enumerate(rows) if not r.get("is_subject")]
    if len(peers) < int(s["peer_min_rows"]):
        return []
    syms = [str(r.get("symbol") or "") for _, r in peers]
    no_cap = sum(1 for _, r in peers if _f(r.get("market_cap_b")) in (None, 0.0))
    alpha = syms == sorted(syms) and no_cap >= math.ceil(len(peers) * 2 / 3)
    aa = sum(1 for x in syms if x.startswith("AA")) >= 2
    etf = bool(re.search(r"(?i)exchange.traded|\betf\b|\bfund\b", str(block.get("industry") or ""))) and (
        syms == sorted(syms) or no_cap == len(peers)) and not block.get("basis")
    wrong = [r.get("symbol") for _, r in peers if r.get("industry") and block.get("industry")
             and r.get("industry") != block.get("industry")]
    code = "etf_cohort_peers" if etf else "alphabetical_peers" if (alpha or aa) else "peer_industry_mismatch" if wrong else None
    if not code:
        return []
    paths = [["peer_comparison", "rows", i, k] for i, r in peers for k in (block.get("fields") or [])]
    paths += [["peer_comparison", "median", k] for k in (block.get("fields") or [])]
    facts = [f["id"] for f in packet["facts"] if f.get("kind") == "peers"]
    msg = {"etf_cohort_peers": "peers are an alphabetical ETF cohort, not comparable funds",
           "alphabetical_peers": "peers look alphabetical (no market caps, A-first symbols), not industry comparables",
           "peer_industry_mismatch": f"peers outside the subject's industry: {', '.join(map(str, wrong[:4]))}"}[code]
    return [_finding(code, SOFT, msg, facts=facts, blocks=paths, repair="fundamentals")]


def _external_transcript_guard() -> Optional[Callable]:
    try:
        from . import domains
        return getattr(domains, "transcript_rejection", None)
    except Exception:  # noqa: BLE001
        return None


def check_sources(packet: dict, s: dict) -> list[dict]:
    out, facts, sym = [], packet["facts"], str(packet["symbol"])
    name = str(packet.get("name") or "")
    words = [w for w in re.findall(r"[A-Za-z]{3,}", name)
             if w.lower() not in {"inc", "corp", "corporation", "company", "ltd", "plc", "holdings", "group", "the",
                                  "class", "fund", "trust", "etf", "shares"}][:2]
    report = (_one(facts, "Last reported EPS") or {}).get("as_of")
    ext = _external_transcript_guard()
    bad = []
    for f in facts:
        if f.get("kind") != "earnings_call":
            continue
        title = str(f.get("label") or "")
        reason = None
        if ext is not None:
            try:
                m = re.match(r"Transcript:\s*(.*?)\s*\(([^()]*)\)\s*$", title)
                reason = ext({"title": m.group(1) if m else title, "channel_name": m.group(2) if m else None,
                              "publish_date": f.get("as_of"), "url": f.get("url"),
                              "excerpt": f.get("text")}, sym, name, report)
            except Exception:  # noqa: BLE001
                ext = None
        if ext is None:
            hay = f"{title} {f.get('text') or ''}"
            issuer = re.search(rf"\b{re.escape(sym)}\b", hay) or any(re.search(rf"(?i)\b{re.escape(w)}\b", hay) for w in words)
            if not EARNINGS_CALL_RE.search(title):
                reason = "not an earnings call (title)"
            elif not issuer:
                reason = "earnings call for another issuer"
        if reason:
            bad.append((f["id"], str(reason)))
    if bad:
        out.append(_finding("transcript_not_earnings_call", SOFT, f"{len(bad)} transcript(s) rejected: {bad[0][1]}",
                            facts=[i for i, _ in bad], blocks=[["earnings_call", "transcripts"]], repair="transcripts"))
    sec = [(f["id"], CIK_RE.search(str(f.get("url") or ""))) for f in facts if f.get("kind") == "sec" and f.get("url")]
    ciks = [(fid, m.group(1)) for fid, m in sec if m]
    want = str(packet.get("context", {}).get("cik") or "").lstrip("0") or None
    if ciks:
        major = want or statistics.mode([c for _, c in ciks])
        wrong = [fid for fid, c in ciks if c != major]
        if wrong:
            out.append(_finding("filing_cik_mismatch", SOFT, f"{len(wrong)} filing(s) under a different CIK than the "
                                "issuer's", facts=wrong, repair="sec_filing_events"))
    return out


def check_coverage(packet: dict, s: dict) -> list[dict]:
    out, facts = [], packet["facts"]
    if not packet.get("series") and not _one(facts, "Last close"):
        out.append(_finding("no_price", HARD, "no price series and no last close", repair="quote_price"))
    if packet.get("scope") == "holding":
        if not any(f.get("kind") == "position" and f.get("label") in ("Market value $", "Shares held (all accounts)")
                   for f in facts):
            out.append(_finding("no_position", HARD, "holding without a position record", repair="positions_store"))
        elif not any(f.get("kind") == "position" and "stop" in str(f.get("label") or "").lower() for f in facts):
            out.append(_finding("no_stop_state", SOFT, "holding without a recorded stop state", repair="positions_store"))
    has_analyst = any(f.get("kind") == "analyst" for f in facts)
    has_fund = any(f.get("kind") == "lookthrough" for f in facts) or bool((packet.get("blocks") or {}).get("fund_lookthrough"))
    if not has_analyst and not has_fund:
        out.append(_finding("no_analyst_or_fund_profile", SOFT, "neither analyst coverage nor a fund profile",
                            repair="fundamentals"))
    return out


def _num(f: Optional[dict]) -> Optional[float]:
    return _f((f or {}).get("value"))


def check_accuracy(packet: dict, s: dict) -> list[dict]:
    """Defect classes found by the 2026-10-26 accuracy audit (``accuracy_audit.py`` recomputes them from the primary
    stores after the fact; these are the packet-only forms, so the same defect can never reach a writer silently)."""
    out, facts = [], packet["facts"]
    blocks = packet.get("blocks") or {}
    # 1. annual dividend vs what was actually paid in the trailing year (stale vendor rows carried 3-5x the real figure)
    dps = _one(facts, "Annual dividend per share")
    ref = _one(facts, "Fund distributions, trailing 12 months ($/share)") or \
        _one(facts, "Dividends paid, trailing year to the latest ex-date ($/share)")
    if dps and ref and ref["value"] > 0 and abs(dps["value"] - ref["value"]) / ref["value"] > float(s["dividend_rel_tol"]):
        out.append(_finding("dividend_cross_source", SOFT, f"annual dividend {dps['value']:g} $/share vs {ref['value']:g} "
                            f"paid in the trailing year ({ref['label']})", facts=[dps["id"]],
                            blocks=[["options_sentiment_dividends", "dividend", "annual_per_share"]], repair="dividends"))
    # 2. stale or undated fundamental_data rows (a six-month-old 52-week high beside the house 1-year high)
    now = _d(packet.get("as_of")) or datetime.now(timezone.utc).date()
    lim = int(s["fundamental_max_age_days"])
    stale = [f["id"] for f in facts if str(f.get("source") or "").startswith("fundamental_data")
             and (not _d(f.get("as_of")) or (now - _d(f["as_of"])).days > lim)]
    if stale:
        out.append(_finding("stale_fundamental_rows", SOFT, f"{len(stale)} fundamental_data fact(s) undated or older than "
                            f"{lim} days", facts=stale, repair="fundamentals"))
    # 3. technical snapshot from another session
    last = _num(_one(facts, "Last close"))
    snap = _one(facts, "Technical snapshot: price")
    if snap and last and abs(snap["value"] / last - 1) > float(s["snapshot_price_rel_tol"]):
        ids = [f["id"] for f in facts if str(f.get("label") or "").startswith("Technical snapshot:")]
        out.append(_finding("stale_technical_snapshot", SOFT, f"technical snapshot price {snap['value']:g} vs last close "
                            f"{last:g}: the snapshot is from another session", facts=ids, repair="technicals"))
    # 4. two price stores that disagree wildly (e.g. a delisted name whose close and quote come from different feeds)
    quote = _num(_one(facts, "Latest quote"))
    if quote and last and max(quote, last) / min(quote, last) - 1 > float(s["quote_close_rel_max"]):
        out.append(_finding("quote_close_contradiction", SOFT, f"latest quote {quote:g} vs last close {last:g}",
                            facts=[f["id"] for f in facts if f.get("label") in ("Latest quote", "Last close")],
                            repair="quote_price"))
    # 5. position arithmetic (shares x price, P/L = value - cost, P/L % = P/L / cost)
    if packet.get("scope") == "holding":
        sh, mv = _num(_one(facts, "Shares held (all accounts)")), _num(_one(facts, "Market value $"))
        avg, upl = _num(_one(facts, "Average cost $")), _num(_one(facts, "Unrealized P/L $"))
        mark = quote or last
        bad = []
        if sh and mv is not None and mark and abs(mv - sh * mark) > float(s["position_mv_rel_tol"]) * max(sh * mark, 1.0):
            bad.append(f"market value {mv:,.2f} vs shares x price {sh * mark:,.2f}")
        if sh and mv is not None and avg is not None and upl is not None and \
                abs((mv - avg * sh) - upl) > max(float(s["position_pl_abs_usd"]), 0.0005 * avg * sh):
            bad.append(f"P/L {upl:,.2f} vs value - cost {mv - avg * sh:,.2f}")
        if bad:
            ids = [f["id"] for f in facts if f.get("kind") == "position" and f.get("label") in
                   ("Market value $", "Unrealized P/L $", "Unrealized P/L %")]
            out.append(_finding("position_arithmetic", SOFT, "; ".join(bad), facts=ids, repair="positions_store"))
    # 6. a stop shown twice with two levels (position facts vs the stop plan's broker rows)
    plan = {a.get("account"): _f(a.get("level")) for a in ((blocks.get("stop_plan") or {}).get("broker") or {}).get("accounts") or []}
    for f in facts:
        m = re.match(r"Recorded protective stop level \((.+?), ", str(f.get("label") or ""))
        if m and m.group(1) in plan and plan[m.group(1)] is not None and _f(f.get("value")) is not None \
                and abs(plan[m.group(1)] - f["value"]) > 1e-6:
            out.append(_finding("stop_level_contradiction", SOFT, f"stop for {m.group(1)}: {f['value']:g} in the position "
                                f"facts vs {plan[m.group(1)]:g} in the stop plan", facts=[f["id"]], repair="positions_store"))
    # 7. non-session bars in the price series (weekend / holiday quote copies distort bar-count windows)
    try:
        from .blocks import is_session
    except ImportError:  # pragma: no cover - module loaded outside the package
        is_session = None
    if is_session is not None:
        off = [d for d, _ in packet.get("series") or [] if not is_session(d)]
        if off:
            out.append(_finding("non_session_bars", SOFT, f"{len(off)} non-session (weekend/holiday) bar(s) in the price "
                                f"series, e.g. {off[0]}", blocks=[["relative_performance", "returns"]], repair="quote_price"))
    # 8. a fund profile that lost the look-through table it sits beside
    fp, lt = blocks.get("fund_profile") or {}, blocks.get("fund_lookthrough") or {}
    if blocks.get("fund_profile") is not None and not fp.get("top_holdings") and lt.get("top_holdings"):
        out.append(_finding("fund_lookthrough_dropped", SOFT, "fund profile shows no top holdings while the look-through "
                            "block lists them", blocks=[["fund_profile", "top_holdings"]], repair="fund_lookthrough"))
    # 9. open lots without P/L although value and cost are known
    for i, lot in enumerate(((blocks.get("my_history") or {}).get("open_lots") or [])):
        if lot.get("unrealized_usd") is None and lot.get("market_value") and lot.get("avg_cost") and lot.get("shares"):
            out.append(_finding("open_lot_pl_missing", SOFT, f"open position in {lot.get('account')} has no unrealized "
                                "P/L although value and cost are known", blocks=[["my_history", "open_lots", i, "unrealized_usd"]],
                                repair="positions_store"))
            break
    return out


def check_news_collisions(packet: dict, s: dict) -> list[dict]:
    """A catalyst / news fact about a DIFFERENT security that shares the ticker (operator 2026-10-27: "Xaar
    (LON:XAR)" on the US ETF XAR) is rejected from the report facts: SOFT, the facts are marked not reliable and the
    writer is told not to cite them. ``inputs.assemble`` already drops them; this is the backstop for stored reports
    (``--gate-only``) and any other path."""
    from .news_gate import collision_reason, load_collisions  # noqa: PLC0415
    cfg = load_collisions()
    sym, name = str(packet.get("symbol") or ""), packet.get("name")
    bad = [f["id"] for f in packet.get("facts") or [] if f.get("kind") in ("catalyst", "news")
           and collision_reason(f"{f.get('label') or ''} {f.get('text') or ''}", sym, {"name": name}, collisions=cfg)]
    if not bad:
        return []
    return [_finding("news_symbol_collision", SOFT, f"{len(bad)} news/catalyst item(s) are about another company "
                     f"that shares the ticker {sym}", facts=bad, repair="catalyst_news")]


CHECKS = (check_coverage, check_series, check_units, check_cross_source, check_peers, check_sources, check_accuracy,
          check_news_collisions)


def deterministic(packet: dict, settings: dict | None = None) -> dict:
    s = settings or load_settings()
    findings: list[dict] = []
    for fn in CHECKS:
        try:
            findings += fn(packet, s)
        except Exception as exc:  # noqa: BLE001 - a crashing check is itself a soft finding, never a silent pass
            findings.append(_finding("check_error", SOFT, f"{fn.__name__}: {type(exc).__name__}: {str(exc)[:120]}"))
    ext = _external_series_guard(packet.get("series") or [])
    return {"findings": findings, "external_guards": {"series_quality": ext is not None,
                                                      "transcript_rejection": _external_transcript_guard() is not None}}


# ── layer 2: cheap AI sanity read ─────────────────────────────────────────────────────────────────────────────
def ai_prompt(packet: dict, findings: list[dict], *, max_chars: int) -> str:
    pts = [(str(d)[:10], c) for d, c in packet.get("series") or []]
    closes = [c for _, c in pts if _f(c) is not None]
    series = {"bars": len(pts), "first": pts[:5], "last": pts[-5:],
              "min": min(closes) if closes else None, "max": max(closes) if closes else None}
    lines = []
    for f in packet["facts"]:
        if f.get("kind") in ("news", "house", "research", "catalyst", "cio", "lineage", "journal", "web"):
            continue
        val = f"{f['value']} {f.get('unit') or ''}".strip() if "value" in f else str(f.get("text") or "")[:120]
        lines.append(f"{f['id']} | {f.get('kind')} | {f.get('label')} | {val} | {f.get('as_of') or 'n/a'}")
    body = "\n".join(lines)
    if len(body) > max_chars:
        body = body[:max_chars] + "\n(truncated)"
    return "\n".join([
        f"You are a data-quality checker for an equity research packet on {packet['symbol']} ({packet.get('name')}), "
        f"a {packet.get('scope')} item. Do not write analysis. Find values that are implausible, inconsistent with each "
        "other, in the wrong units, stale, or from the wrong issuer or source type (e.g. a video that is not an "
        "earnings call, peers that are not comparable companies).",
        "Return ONLY JSON: {\"anomalies\": [{\"field\": \"<fact id like F12, or a short field name>\", \"value\": "
        "\"<as shown>\", \"why\": \"<one sentence>\", \"severity\": \"high\"|\"medium\"|\"low\"}]}. Use high only for "
        "a value that would mislead a reader. Return {\"anomalies\": []} when nothing is wrong.",
        "Deterministic checks already flagged: " + (", ".join(sorted({f["code"] for f in findings})) or "nothing"),
        "PRICE SERIES SUMMARY: " + json.dumps(series, default=str),
        "FACTS (id | kind | label | value | as of):", body])


def _parse_anomalies(text: str) -> list[dict]:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", raw)
    try:
        doc = json.loads(raw)
    except ValueError:
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            raise ValueError("AI_OUTPUT_NOT_JSON")
        doc = json.loads(m.group(0))
    rows = doc.get("anomalies") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        raise ValueError("AI_OUTPUT_SCHEMA_INVALID")
    out = []
    for r in rows[:30]:
        if isinstance(r, dict) and r.get("field"):
            sev = str(r.get("severity") or "low").lower()
            out.append({"field": str(r["field"])[:60], "value": str(r.get("value") or "")[:80],
                        "why": str(r.get("why") or "")[:240], "severity": sev if sev in ("high", "medium", "low") else "low"})
    return out


def governed_ai_call(prompt: str, *, max_tokens: int, timeout: float) -> tuple[str, dict]:
    """Haiku 5.5 via the Anthropic credit (anthropic-only process); free Grok OAuth when the credit is unusable.

    Never DeepSeek: the OAuth process is registered grok-only, the credit process anthropic-only.
    """
    try:
        from lib import llm_consumption as lc  # type: ignore
    except ImportError:
        from scripts.lib import llm_consumption as lc  # type: ignore
    try:
        text, prov = lc.gate_and_generate(prompt, process_id=PROCESS_AI, lane="fast", max_tokens=max_tokens,
                                          timeout=int(timeout), return_provenance=True,
                                          task_summary="prospectus fact check (packet only)")
        return str(text or ""), dict(prov or {})
    except Exception as exc:  # noqa: BLE001 - only a credit refusal moves to the free lane
        if "ANTHROPIC_CREDIT_UNAVAILABLE" not in str(exc) and "CREDIT_" not in str(exc) \
                and "NO_ROUTE_AVAILABLE" not in str(exc):
            raise
    text, prov = lc.gate_and_generate(prompt, process_id=PROCESS_AI_OAUTH, lane="grok", max_tokens=max_tokens,
                                      timeout=int(timeout), return_provenance=True,
                                      task_summary="prospectus fact check (packet only, OAuth fallback)")
    return str(text or ""), dict(prov or {}, fallback="grok_oauth")


def ai_sanity(packet: dict, findings: list[dict], *, settings: dict, ai_fn: Callable | None) -> dict:
    cfg = settings.get("ai") or {}
    if ai_fn is None or not cfg.get("enabled", True):
        return {"ran": False, "reason": "disabled" if ai_fn is None else "config disabled", "anomalies": [],
                "findings": []}
    prompt = ai_prompt(packet, findings, max_chars=int(cfg.get("max_packet_chars", 18000)))
    try:
        text, prov = ai_fn(prompt, max_tokens=int(cfg.get("max_tokens", 1200)), timeout=float(cfg.get("timeout_s", 60)))
        anomalies = _parse_anomalies(text)
    except Exception as exc:  # noqa: BLE001 - layer 2 is advisory: a failed read never blocks, it is recorded
        return {"ran": False, "reason": f"{type(exc).__name__}: {str(exc)[:160]}", "anomalies": [], "findings": []}
    hit_facts = {fid for f in findings for fid in f["facts"]}
    findings = [f for f in findings if not f.get("guarded")]  # a defect the price guard removed is not confirmable
    by_label = {str(f.get("label") or "").lower(): f["id"] for f in packet["facts"]}
    out = []
    for a in anomalies:
        if a["severity"] != "high":
            continue
        fid = a["field"] if re.fullmatch(r"F\d+", a["field"]) else by_label.get(a["field"].lower())
        confirms = fid in hit_facts if fid else any(a["field"].lower() in f["code"] for f in findings)
        out.append(_finding("ai_" + ("confirms_layer1" if confirms else "anomaly"), HARD if confirms else SOFT,
                            f"{a['field']}: {a['why']}", facts=[fid] if fid else [], layer=2))
    return {"ran": True, "model": prov.get("returned_model") or prov.get("model_id") or prov.get("requested_model_id"),
            "provider": prov.get("provider"), "fallback": prov.get("fallback"),
            "cost_usd": _f(prov.get("estimated_cost_usd")), "anomalies": anomalies, "findings": out}


def ai_cost_estimate(settings: dict | None = None, pricing: dict | None = None) -> float:
    s = (settings or load_settings()).get("ai") or {}
    p = (pricing or {}).get("claude-haiku-5-5") or {"input": "0.10", "output": "0.50"}
    return round(int(s.get("est_input_tokens", 5500)) * float(p["input"]) / 1e6
                 + int(s.get("est_output_tokens", 600)) * float(p["output"]) / 1e6, 6)


# ── verdict, application to the bundle ────────────────────────────────────────────────────────────────────────
def verdict(findings: list[dict], **layers: Any) -> dict:
    status = HARD if any(f["severity"] == HARD for f in findings) else SOFT if findings else PASS
    unreliable: dict[str, str] = {}
    for f in findings:
        if f["severity"] == SOFT:
            for fid in f["facts"]:
                unreliable.setdefault(fid, f["code"])
    return {"schema": SCHEMA, "status": status, "checked_at": datetime.now(timezone.utc).isoformat(),
            "reasons": [f"{f['code']}: {f['message']}" for f in findings], "findings": findings,
            "unreliable": unreliable, "layers": layers}


def pre_write(packet: dict, *, settings: dict | None = None, ai_fn: Callable | None = None) -> dict:
    """Layers 1 and 2 on the facts packet. Layer 2 only runs when layer 1 is not already a HARD_FAIL."""
    s = settings or load_settings()
    det = deterministic(packet, s)
    findings = list(det["findings"])
    ai = {"ran": False, "reason": "skipped: layer 1 hard fail", "anomalies": [], "findings": []}
    if not any(f["severity"] == HARD for f in findings):
        ai = ai_sanity(packet, findings, settings=s, ai_fn=ai_fn)
        findings += ai["findings"]
    return verdict(findings, deterministic={"external_guards": det["external_guards"]},
                   ai={k: v for k, v in ai.items() if k != "findings"})


def _set_path(root: Any, path: list, value: str) -> bool:
    node = root
    for key in path[:-1]:
        try:
            node = node[key]
        except (KeyError, IndexError, TypeError):
            return False
    try:
        if isinstance(node, dict) and path[-1] in node:
            node[path[-1]] = value
            return True
        if isinstance(node, list) and isinstance(path[-1], int) and path[-1] < len(node):
            node[path[-1]] = value
            return True
    except (KeyError, IndexError, TypeError):
        return False
    return False


def apply_unreliable(bundle: Any, gate: dict) -> None:
    """SOFT_FAIL: tag facts, tell the writer (gaps), and make blocks print "not reliable (reason)"."""
    soft = [f for f in gate.get("findings") or [] if f["severity"] == SOFT and not f.get("guarded")]
    guarded = [f for f in gate.get("findings") or [] if f.get("guarded")]
    if guarded:
        line = "PRICE HISTORY: " + "; ".join(f["message"] for f in guarded)
        if line[:1500] not in bundle.gaps:
            bundle.gaps.append(line[:1500])
    for f in bundle.facts:
        why = gate["unreliable"].get(f["id"])
        if why:
            f["unreliable"] = why
    for f in soft:
        text = f"not reliable ({f['code']})"
        for path in f.get("blocks") or []:
            if path and path[0] in bundle.blocks:
                block = bundle.blocks[path[0]]
                if path[-1] == "transcripts" and isinstance(block.get("transcripts"), list):
                    for t in block["transcripts"]:
                        if t.get("id") in f["facts"]:
                            t["unreliable"] = text
                    continue
                if _set_path(bundle.blocks, path, text) and isinstance(block, dict):
                    block.setdefault("unreliable", {})[".".join(map(str, path[1:]))] = f["code"]
    if soft:
        line = "DATA QUALITY: treat these facts as NOT RELIABLE and do not cite their numbers: " + "; ".join(
            f"{f['code']} ({', '.join(f['facts'][:12]) or 'no single fact'})" for f in soft)
        if line not in bundle.gaps:
            bundle.gaps.append(line[:1500])


class DataBlocked(RuntimeError):
    """Layer 1/2 HARD_FAIL: no model call. Carries the gate verdict."""

    def __init__(self, gate: dict):
        super().__init__("BLOCKED_DATA: " + "; ".join(gate.get("reasons") or [])[:400])
        self.gate = gate


def request_repairs(symbol: str, gate: dict, *, gap_fn: Callable | None = None) -> list[str]:
    """One data-gap queue row per repair domain (the gap resolver lane does the fetch, never this job)."""
    if gap_fn is None:
        def gap_fn(domain, sym, question, **kw):  # noqa: ANN001
            try:
                from lib.data_broker import gap_hook  # type: ignore
            except ImportError:
                from scripts.lib.data_broker import gap_hook  # type: ignore
            return gap_hook.enqueue_gap(domain, sym, question, **kw)
    done = []
    for domain in sorted({f["repair_domain"] for f in gate.get("findings") or [] if f.get("repair_domain")}):
        codes = sorted({f["code"] for f in gate["findings"] if f.get("repair_domain") == domain})
        try:
            gap_fn(domain, symbol, f"prospectus gate: {domain} bad for {symbol} ({', '.join(codes)})",
                   why="missing", requester="prospectus_quality_gate")
            done.append(domain)
        except Exception:  # noqa: BLE001 - never blocks; the gate verdict still records the reason
            continue
    return done


# ── layer 3: post-write numbers vs cited facts ────────────────────────────────────────────────────────────────
def _scales(unit: str | None) -> list[float]:
    u = (unit or "").lower()
    if u.startswith("b"):
        return [1e9, 1e3, 1.0]   # "$1.2B" may cite a $ fact or a market-cap fact already in $B / $M
    if u.startswith("m"):
        return [1e6, 1.0, 1e-3]
    if u.startswith("k"):
        return [1e3, 1.0]
    return [1.0]


def _numbers_raw(text: str) -> list[tuple[float, str, str]]:
    out = []
    for m in NUM_RE.finditer(text or ""):
        try:
            out.append((float(m.group(2).replace(",", "")), m.group(3) or "", m.group(0)))
        except ValueError:
            continue
    return out


def _numbers(text: str) -> list[tuple[float, str, str]]:
    probe = SKIP_TOKEN_RE.sub(" ", DATE_RE.sub(" ", CITE_RE.sub(" ", text or "")))
    probe = re.sub(r"(?m)^\s*(?:[-*]|\d{1,2}[.)])\s+", " ", probe)
    out = []
    for m in NUM_RE.finditer(probe):
        raw = m.group(2).replace(",", "")
        try:
            x = float(raw)
        except ValueError:
            continue
        unit = m.group(3) or ""
        if re.match(r"\s*-?\s*(?:day|week|month|year|quarter|session|bar)s?\b", probe[m.end():], re.I):
            continue  # "30-day", "52-week": windows, not claims
        if not unit and "$" not in m.group(0) and "." not in raw and (x <= 12 or 1990 <= x <= 2040):
            continue  # counts, horizons and years are not claims
        out.append((-x if m.group(1) in ("-", "−") else x, unit, m.group(0).strip()))
    return out


def _matches(x: float, unit: str, values: list[float], rel: float, raw: str) -> bool:
    decimals = len(raw.split(".")[1].rstrip("%$xBbMmKk× ")) if "." in raw else 0
    for scale in _scales(unit):
        y = abs(x) * scale
        for v in values:
            tol = max(rel * abs(v), 0.5 * 10 ** (-decimals) * scale, 1e-9)
            if abs(y - abs(v)) <= tol:
                return True
    return False


def _fact_values(f: dict) -> list[float]:
    """A fact's numeric value plus the numbers quoted in its text (a cited text fact may carry figures)."""
    if f.get("unreliable"):
        return []
    out = [f["value"]] if "value" in f else []
    for x, unit, _ in _numbers_raw(str(f.get("text") or "") + " " + str(f.get("label") or "")):
        out += [x * sc for sc in _scales(unit)[:1]] + ([x] if unit else [])
    return out


def post_write(sections: list[dict], facts: list[dict], *, settings: dict | None = None) -> dict:
    s = settings or load_settings()
    rel = float(s["post_write_rel_tol"])
    by_id = {f["id"]: f for f in facts}
    all_vals = [v for f in facts for v in _fact_values(f)]
    unmatched, uncited = [], []
    for sec in sections:
        cited = {c.get("id") for c in sec.get("citations") or [] if isinstance(c, dict)}
        cited |= {i.strip() for g in re.findall(r"\[([FW]\d+(?:\s*,\s*[FW]\d+)*)\]", sec.get("body_md") or "")
                  for i in g.split(",")}
        vals = [v for i in cited if i in by_id for v in _fact_values(by_id[i])]
        for x, unit, raw in _numbers(sec.get("body_md") or ""):
            if _matches(x, unit, vals, rel, raw):
                continue
            row = {"section": sec.get("id"), "number": raw}
            (uncited if _matches(x, unit, all_vals, rel, raw) else unmatched).append(row)
    limit = int(s["post_write_max_unmatched"])
    return {"unmatched": unmatched[:40], "uncited": uncited[:40], "unmatched_count": len(unmatched),
            "uncited_count": len(uncited), "limit": limit, "rewrite": len(unmatched) > limit}


# ── stored-report review (--gate-only) ────────────────────────────────────────────────────────────────────────
def review_doc(doc: dict, *, settings: dict | None = None, ai_fn: Callable | None = None) -> dict:
    """Layers 1-2 on a stored report's packet, layer 3 on its sections, plus web / partial status."""
    s = settings or load_settings()
    packet = packet_from_doc(doc)
    gate = pre_write(packet, settings=s, ai_fn=ai_fn)
    pw = post_write(doc.get("sections") or [], packet["facts"], settings=s)
    web = packet.get("web") or {}
    results = sum(int(r.get("results") or 0) for r in web.get("searches") or [])
    reasons = []
    if gate["status"] == HARD:
        reasons.append("bad_data")
    elif gate["status"] == SOFT:
        reasons.append("soft_data")
    if not results:
        reasons.append("no_web")
    if doc.get("status") == "partial":
        reasons.append("partial")
    if pw["rewrite"]:
        reasons.append("post_write_unmatched")
    return {"symbol": doc.get("symbol"), "scope": doc.get("scope"), "version": doc.get("version"),
            "gate_status": gate["status"], "codes": sorted({f["code"] for f in gate["findings"]}),
            "reasons": gate["reasons"], "post_write": {k: pw[k] for k in ("unmatched_count", "uncited_count", "rewrite")},
            "web_results": results, "report_status": doc.get("status"), "needs_rewrite": bool(reasons),
            "rewrite_reasons": reasons, "gate": gate}


def index_fields(gate: dict, post: dict | None = None) -> dict:
    """The compact per-report fields the index / API expose."""
    return {"gate_status": gate.get("status"), "gate_reasons": (gate.get("reasons") or [])[:12],
            "gate_checked_at": gate.get("checked_at"),
            "gate_post_write": {k: post.get(k) for k in ("unmatched_count", "uncited_count", "rewrite")} if post else None}
