#!/usr/bin/env python3
"""Reject news/catalyst headlines that Yahoo RSS mis-tags to the wrong ticker."""
from __future__ import annotations

import re

_TICKER_RE = re.compile(r"\(([A-Z]{1,5})\)|\(NASDAQ:([A-Z]{1,5})\)|\(NYSE:([A-Z]{1,5})\)", re.I)
_WORD_RE = re.compile(r"(?<![A-Z])([A-Z]{1,5})(?![A-Z])")

# Headlines clearly about a different issuer (Yahoo RSS noise on thin tickers).
_FOREIGN_COMPANY_MARKERS = (
    "pasqal", "ionq", "rigetti", "quantum computing inc", "xanadu quantum",
)


def _company_tokens(description: str | None) -> list[str]:
    if not description:
        return []
    first = str(description).split(",")[0].strip()
    tokens = []
    if first:
        tokens.append(first.lower())
        # "Merlin, Inc." → merlin
        core = re.sub(r"\b(inc|corp|ltd|plc|co)\b\.?", "", first, flags=re.I).strip()
        if core and core.lower() != first.lower():
            tokens.append(core.lower())
    return [t for t in tokens if len(t) >= 3]


# "<name> stock hits 52-week high at 27.99 USD" — a headline stating the security's own
# 52-week extreme. Deliberately narrow: it must NOT match a price target, a deal size or a
# guidance figure, all of which legitimately differ from the quote. Measured over 21 days of
# live data this pattern fires on ~9 headlines, so the veto below is surgical, not broad.
_52W_CLAIM_RE = re.compile(
    r"(?:hits?|reach(?:es|ed)?|touch(?:es|ed)?)\s+(?:a\s+)?52[-\s]?week\s+"
    r"(high|low)\s+(?:at|of)\s+\$?\s*([0-9]{1,6}(?:\.[0-9]{1,2})?)", re.I)

#: Relative gap above which a stated 52-week extreme is treated as a different security.
_52W_TOLERANCE = 0.25


def price_contradiction(title: str, summary: str = "", *,
                        reference_52w: tuple | None = None) -> str | None:
    """Reason string when a headline's stated 52-week extreme cannot be this security.

    `reference_52w` is (our_52w_low, our_52w_high). A headline claiming "hits 52-week high at
    27.99" for a security whose own 52-week high is 19.91 is not describing that security —
    it is a different issuer whose name merely contains the ticker as a substring.

    This exists because the ticker-token test below upper-cases the text before matching, so
    "Eaton Vance Tax Advantaged Div stock" becomes "...ADVANTAGED DIV STOCK" and matches DIV
    as a standalone token. The case signal that would have distinguished "Div" from "DIV" is
    destroyed by the time the test runs. Four such headlines were attached to DIV (a $20 ETF)
    from a $27.99 Eaton Vance fund, and a research lane correctly refused to judge the holding
    as a result (2026-07-29).

    Compares against the 52-week EXTREME, not the current price: a "52-week high" headline
    legitimately quotes a level well above today's quote, so comparing to spot would falsely
    reject correctly-mapped news (verified — it flagged RDWR/Radware, a true match).
    """
    if not reference_52w:
        return None
    lo, hi = reference_52w
    m = _52W_CLAIM_RE.search(f"{title or ''} {summary or ''}")
    if not m:
        return None
    kind, raw = m.group(1).lower(), m.group(2)
    ref = hi if kind == "high" else lo
    try:
        claimed, ref = float(raw), float(ref or 0)
    except (TypeError, ValueError):
        return None
    if ref <= 0:
        return None
    if abs(claimed - ref) / ref > _52W_TOLERANCE:
        return f"price_conflict_52w_{kind}:{claimed}_vs_{round(ref, 2)}"
    return None


def headline_matches_symbol(
    symbol: str,
    title: str,
    summary: str = "",
    *,
    company_description: str | None = None,
    reference_52w: tuple | None = None,
) -> tuple[bool, str]:
    """Return (ok, reason). False = do not attach this headline to symbol."""
    sym = (symbol or "").upper().strip()
    if not sym or not title:
        return False, "missing_symbol_or_title"

    text = f"{title} {summary or ''}"
    upper = text.upper()

    # Hard veto, evaluated BEFORE any positive match: a contradicted 52-week extreme means
    # this is another issuer, however convincingly the ticker appears in the text.
    conflict = price_contradiction(title, summary, reference_52w=reference_52w)
    if conflict:
        return False, conflict

    for m in _FOREIGN_COMPANY_MARKERS:
        if m in text.lower() and sym not in ("PASQAL", "IONQ", "RGTI", "QUBT"):
            if sym.lower() not in text.lower() and f"({sym})" not in upper:
                return False, f"foreign_company:{m}"

    if f"({sym})" in upper or f"(NASDAQ:{sym})" in upper or f"(NYSE:{sym})" in upper:
        return True, "ticker_paren"

    # Multi-ticker roundup lists still mention our symbol.
    if re.search(rf"(?<![A-Z]){re.escape(sym)}(?![A-Z])", upper):
        return True, "ticker_token"

    for alias in _company_tokens(company_description):
        if alias in text.lower():
            return True, "company_name"

    # "Merlin (MRLN) ..." style without strict word boundary on short names
    if sym == "MRLN" and "merlin" in text.lower():
        return True, "merlin_alias"

    return False, "no_symbol_or_company_match"


def purge_mismatched_for_symbol(conn, symbol: str, *, apply: bool = True, auto_commit: bool = True) -> dict:
    """Remove news_articles + catalyst_events that fail the symbol guard."""
    sym = symbol.upper().strip()
    cur = conn.cursor()
    cur.execute(
        "SELECT description_1s FROM symbol_profiles WHERE upper(symbol)=%s LIMIT 1",
        (sym,),
    )
    row = cur.fetchone()
    desc = row[0] if row else None

    # 52-week reference so the purge applies the same price-conflict veto the ingest path
    # does; without it a re-purge would silently keep already-stored mismapped rows.
    ref_52w = None
    try:
        cur.execute(
            """SELECT min(close_price), max(close_price) FROM price_cache
                WHERE symbol=%s AND price_date > current_date - 365 AND close_price > 0.5""",
            (sym,),
        )
        r52 = cur.fetchone()
        if r52 and r52[0] is not None and r52[1] is not None:
            ref_52w = (float(r52[0]), float(r52[1]))
    except Exception:
        ref_52w = None

    cur.execute(
        "SELECT id, title, summary FROM news_articles WHERE upper(symbol)=%s",
        (sym,),
    )
    news_del, cat_del = [], []
    for nid, title, summary in cur.fetchall():
        ok, _ = headline_matches_symbol(sym, title or "", summary or "",
                                        company_description=desc, reference_52w=ref_52w)
        if ok:
            continue
        news_del.append(nid)
        if apply:
            cur.execute("DELETE FROM news_articles WHERE id=%s", (nid,))

    cur.execute(
        "SELECT id, headline, description FROM catalyst_events WHERE upper(symbol)=%s",
        (sym,),
    )
    for cid, headline, description in cur.fetchall():
        ok, _ = headline_matches_symbol(sym, headline or "", description or "",
                                        company_description=desc, reference_52w=ref_52w)
        if ok:
            continue
        cat_del.append(cid)
        if apply:
            cur.execute("DELETE FROM catalyst_events WHERE id=%s", (cid,))

    if apply and auto_commit and (news_del or cat_del):
        conn.commit()
    return {"symbol": sym, "news_removed": len(news_del), "catalyst_removed": len(cat_del)}


def _rated_watchlist_symbols(cur) -> list[str]:
    """Active/researched watchlist names with any CIO verdict (all tiers)."""
    import sys
    from pathlib import Path
    lib = Path(__file__).resolve().parent / "lib"
    if str(lib) not in sys.path:
        sys.path.insert(0, str(lib))
    from watchlist_priority import DAILY_PRIORITY_RATED_RECS  # noqa: E402

    rated = sorted(r.upper() for r in DAILY_PRIORITY_RATED_RECS)
    cur.execute(
        """SELECT DISTINCT UPPER(wi.symbol) AS symbol
           FROM watchlist_items wi
           WHERE wi.status IN ('active', 'researched')
             AND (
               EXISTS (
                 SELECT 1 FROM watchlist_research_cards rc
                 WHERE rc.symbol = wi.symbol
                   AND UPPER(REPLACE(REPLACE(rc.latest_recommendation, ' ', '_'), '-', '_')) = ANY(%s)
               )
               OR EXISTS (
                 SELECT 1 FROM watchlist_final_synthesis fs
                 WHERE upper(fs.symbol) = upper(wi.symbol)
                   AND UPPER(REPLACE(REPLACE(fs.recommendation, ' ', '_'), '-', '_')) = ANY(%s)
               )
             )
           ORDER BY 1""",
        (rated, rated),
    )
    return [str(r[0]).upper() for r in cur.fetchall() if r and r[0]]


def purge_mismatched_watchlist(
    conn,
    *,
    symbols: list[str] | None = None,
    apply: bool = True,
) -> dict:
    """Remove mis-tagged news/catalyst across CIO-rated watchlist symbols (all verdict tiers)."""
    cur = conn.cursor()
    sym_list = [s.upper().strip() for s in (symbols or []) if s]
    if not sym_list:
        sym_list = _rated_watchlist_symbols(cur)

    totals = {
        "symbols_scanned": len(sym_list),
        "news_removed": 0,
        "catalyst_removed": 0,
        "symbols_purged": 0,
        "by_symbol": {},
    }
    for sym in sym_list:
        r = purge_mismatched_for_symbol(conn, sym, apply=apply, auto_commit=False)
        totals["news_removed"] += r["news_removed"]
        totals["catalyst_removed"] += r["catalyst_removed"]
        if r["news_removed"] or r["catalyst_removed"]:
            totals["symbols_purged"] += 1
            totals["by_symbol"][sym] = r
    if apply and (totals["news_removed"] or totals["catalyst_removed"]):
        conn.commit()
    return totals


def count_mismatched_watchlist(conn, *, limit: int = 120) -> dict:
    """Sample latest catalyst headlines on rated symbols; count guard failures."""
    cur = conn.cursor()
    sym_list = _rated_watchlist_symbols(cur)[: max(1, limit)]
    mismatches = []
    for sym in sym_list:
        cur.execute(
            "SELECT description_1s FROM symbol_profiles WHERE upper(symbol)=%s LIMIT 1",
            (sym,),
        )
        row = cur.fetchone()
        desc = row[0] if row else None
        cur.execute(
            """SELECT headline, description FROM catalyst_events
               WHERE upper(symbol)=%s AND catalyst_type <> 'other'
               ORDER BY COALESCE(published_at, created_at) DESC NULLS LAST LIMIT 1""",
            (sym,),
        )
        cat = cur.fetchone()
        if not cat:
            continue
        headline, description = cat[0] or "", cat[1] or ""
        ok, reason = headline_matches_symbol(sym, headline, description, company_description=desc)
        if not ok:
            mismatches.append({"symbol": sym, "headline": (headline or "")[:120], "reason": reason})
    return {"scanned": len(sym_list), "mismatch_count": len(mismatches), "mismatches": mismatches[:20]}


if __name__ == "__main__":
    import argparse
    import json
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from db_adapter import get_connection  # noqa: E402

    ap = argparse.ArgumentParser(description="Purge Yahoo RSS mis-tagged news/catalyst")
    ap.add_argument("--symbol", help="Single symbol purge")
    ap.add_argument("--purge-watchlist", action="store_true", help="All CIO-rated watchlist symbols")
    ap.add_argument("--dry-run", action="store_true", help="Report only, no deletes")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    conn = get_connection()
    try:
        if args.symbol:
            out = purge_mismatched_for_symbol(conn, args.symbol.upper(), apply=not args.dry_run)
        elif args.purge_watchlist:
            out = purge_mismatched_watchlist(conn, apply=not args.dry_run)
        else:
            out = count_mismatched_watchlist(conn)
        if args.json:
            print(json.dumps(out, indent=2, default=str))
        else:
            print(out)
    finally:
        conn.close()