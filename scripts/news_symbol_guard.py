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

#: Sources whose feed carries an explicit PROVIDER ticker list per article (Finviz `news_export` returns
#: a `tickers` list with each item). For these the provider already linked the article to the symbol, so
#: "the headline never spells the company out" is absence of evidence, not evidence of a wrong tag — the
#: text heuristic cannot adjudicate them and must not delete them. A contradiction (52-week level, a
#: foreign issuer) still rejects. Measured 2026-11-06: the purge deleted 15 of NVIDIA's own headlines
#: ("Nvidia is the top performer in the Dow ...") because they say the company name, not the ticker.
PROVIDER_TAGGED_SOURCES = frozenset({"finviz_news"})

# Corporate-form words that never identify an issuer on their own ("NVIDIA Corporation" -> nvidia).
_CORP_SUFFIX_RE = re.compile(
    r"\b(?:incorporated|inc|corporation|corp|company|co|ltd|limited|plc|llc|lp|llp|nv|n\.v\.|sa|s\.a\.|"
    r"ag|se|holdings?|group|the|trust|fund|etf)\b\.?",
    re.I,
)
# `symbol_profiles.description_1s` is a PARAGRAPH, not a "Name, Inc." field: "NVIDIA Corporation operates as
# a data center scale AI infrastructure company in the United States ...". The issuer's name ends at the first
# clause boundary or the first predicate verb. The old first-comma split returned that whole sentence for
# NVDA/AAPL/V/SPCX, so the alias could never match the word "Nvidia"/"Apple"/"Visa" in a headline and the
# remediation purge removed every row those symbols had (2026-11-06, 23 rows archived).
_NAME_BOUNDARY_RE = re.compile(
    r"[,\;\.\:]|\s+(?:operates?|provides?|designs?|manufactures?|develops?|engages?|offers?|sells?|"
    r"is|are|was|were|has|have|owns?|holds?|acquires?|supplies?|delivers?|serves?|specializes?|"
    r"focuses?|produces?|distributes?|markets?|licenses?|invests?|leases?|maintains?|builds?|creates?|"
    r"makes?|generates?|derives?|through|together|formerly)\b",
    re.I,
)


# "<name> stock hits 52-week high at 27.99 USD": a headline stating the security's own 52-week
# extreme. Deliberately narrow; it must NOT match a price target, a deal size or guidance, all of
# which legitimately differ from the quote (PR #255, measured ~9 headlines in 21 days).
_52W_CLAIM_RE = re.compile(
    r"(?:hits?|reach(?:es|ed)?|touch(?:es|ed)?)\s+(?:a\s+)?52[-\s]?week\s+"
    r"(high|low)\s+(?:at|of)\s+\$?\s*([0-9]{1,6}(?:\.[0-9]{1,2})?)",
    re.I,
)
#: Relative gap above which a stated 52-week extreme is treated as a different security.
_52W_TOLERANCE = 0.25


def fifty_two_week_reference(cur, symbol: str) -> tuple[float, float] | None:
    """(low, high) daily close over the trailing year; close_price > 0.5 drops known corrupt bars."""
    try:
        cur.execute(
            """SELECT min(close_price), max(close_price) FROM price_cache
                WHERE symbol=%s AND price_date > current_date - 365 AND close_price > 0.5""",
            ((symbol or "").upper(),),
        )
        row = cur.fetchone()
        if row and row[0] is not None and row[1] is not None:
            return float(row[0]), float(row[1])
    except Exception:
        pass
    return None


def price_contradiction(title: str, summary: str = "", *, reference_52w: tuple | None = None) -> str | None:
    """Reason string when a headline's stated 52-week extreme cannot be this security.

    The ticker-token test upper-cases text first, so "Eaton Vance Tax Advantaged Div stock"
    matched DIV (a $20 ETF) and four $27.99 Eaton Vance headlines were attached to it
    (2026-07-29). Compares to our 52-week EXTREME, not spot: a "52-week high" headline
    legitimately quotes a level above today's price (spot comparison wrongly rejected RDWR).
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


def _company_tokens(description: str | None) -> list[str]:
    """Lower-case names a headline may use for the issuer, from its profile description.

    "Space Exploration Technologies Corp. provides ..." -> "space exploration technologies";
    "NVIDIA Corporation operates as ..." -> "nvidia"; "Netflix, Inc. provides ..." -> "netflix".
    A single-word result also yields itself as the alias, which is what a headline actually writes
    ("Nvidia is the top performer"); a multi-word one is used whole, so a generic first word like
    "space" or "united" cannot match an unrelated headline.
    """
    if not description:
        return []
    text = str(description).strip()
    if not text:
        return []
    head = _NAME_BOUNDARY_RE.split(text, maxsplit=1)[0].strip()
    out: list[str] = []

    def add(name: str) -> None:
        cleaned = " ".join(_CORP_SUFFIX_RE.sub(" ", name).split()).strip(" .'-–")
        if len(cleaned) < 3:
            return
        if cleaned.lower() not in out:
            out.append(cleaned.lower())
        words = cleaned.split()
        if len(words) == 1 and len(words[0]) >= 4 and words[0].lower() not in out:
            out.append(words[0].lower())

    add(head)
    # The legacy "<Name>, Inc. <description>" spelling: the comma clause IS the name — but only when it is
    # a NAME. On a paragraph field the first comma can be arbitrary ("... company in the United States,
    # Japan, Taiwan ..."), and adding that clause put the whole sentence in the alias list.
    first_comma = text.split(",")[0].strip()
    if first_comma and first_comma != head and len(first_comma.split()) <= 4 and len(first_comma) <= 40:
        add(first_comma)
    return [t for t in out if len(t) >= 3]


def headline_matches_symbol(
    symbol: str,
    title: str,
    summary: str = "",
    *,
    company_description: str | None = None,
    reference_52w: tuple | None = None,
    provider_tagged: bool = False,
) -> tuple[bool, str]:
    """Return (ok, reason). False = do not attach this headline to symbol.

    ``reference_52w`` (our 52-week low, high) enables a hard veto evaluated before any positive
    match: a contradicted 52-week extreme means another issuer, however the ticker appears.

    ``provider_tagged`` says the feed itself listed this ticker for the article (see
    ``PROVIDER_TAGGED_SOURCES``). No textual match then reads as "cannot tell", not "wrong tag": the
    row is kept (``provider_tag``) unless a contradiction rejects it. Passing False keeps the strict
    Yahoo-RSS behaviour.
    """
    sym = (symbol or "").upper().strip()
    if not sym or not title:
        return False, "missing_symbol_or_title"

    conflict = price_contradiction(title, summary, reference_52w=reference_52w)
    if conflict:
        return False, conflict

    text = f"{title} {summary or ''}"
    upper = text.upper()

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

    if provider_tagged:
        # The provider supplied the ticker; nothing in the text contradicts it (every veto ran above).
        return True, "provider_tag"
    return False, "no_symbol_or_company_match"


def _archived_delete(conn, table: str, ids: list, *, key: str, label: str) -> int:
    """2026-10-21 (operator D3.3, registry-owned retention): archive-first through the shared helper
    (lib.retention_archive.managed_purge: jsonl.gz + sha256 manifest + tripwire, re-read and count-checked,
    then the delete of exactly those rows). Each verified batch commits on its own; a failed verify rolls back
    and raises, so nothing is deleted unarchived."""
    if not ids:
        return 0
    try:
        from lib.retention_archive import managed_purge
    except ImportError:  # imported with scripts/lib, not scripts/, on sys.path
        from retention_archive import managed_purge
    r = managed_purge(conn, table=table, where_sql=f"t.{key} = ANY(%s)", params=(list(ids),),
                      label=label, writer="news_symbol_guard", apply=True, archive=True)
    return int(r.get("deleted") or 0)


def purge_mismatched_for_symbol(conn, symbol: str, *, apply: bool = True, auto_commit: bool = True) -> dict:
    """Remove news_articles + catalyst_events that fail the symbol guard (archived first, 2026-10-21)."""
    sym = symbol.upper().strip()
    cur = conn.cursor()
    cur.execute(
        "SELECT description_1s FROM symbol_profiles WHERE upper(symbol)=%s LIMIT 1",
        (sym,),
    )
    row = cur.fetchone()
    desc = row[0] if row else None

    cur.execute(
        "SELECT id, title, summary, source FROM news_articles WHERE upper(symbol)=%s",
        (sym,),
    )
    news_del, cat_del = [], []
    for nid, title, summary, source in cur.fetchall():
        ok, _ = headline_matches_symbol(sym, title or "", summary or "", company_description=desc,
                                        provider_tagged=(source or "") in PROVIDER_TAGGED_SOURCES)
        if ok:
            continue
        news_del.append(nid)

    cur.execute(
        "SELECT id, headline, description, source FROM catalyst_events WHERE upper(symbol)=%s",
        (sym,),
    )
    for cid, headline, description, source in cur.fetchall():
        ok, _ = headline_matches_symbol(sym, headline or "", description or "", company_description=desc,
                                        provider_tagged=(source or "") in PROVIDER_TAGGED_SOURCES)
        if ok:
            continue
        cat_del.append(cid)

    if apply and (news_del or cat_del):
        # Archive-first (2026-10-21). catalyst_symbol_impact.catalyst_event_id references catalyst_events.id
        # without ON DELETE CASCADE. Deleting the parent first raised ForeignKeyViolation on every
        # auto-remediation run (2,447 times by 2026-09-26) and the mismatch finding never cleared. Children first.
        # The archived batches commit as they verify, so ``auto_commit`` no longer defers these deletes.
        _archived_delete(conn, "news_articles", news_del, key="id", label="symbol_guard_news")
        if cat_del:
            _archived_delete(conn, "catalyst_symbol_impact", _impact_ids(cur, cat_del), key="id",
                             label="symbol_guard_impact")
            _archived_delete(conn, "catalyst_events", cat_del, key="id", label="symbol_guard_catalyst")
        if auto_commit:
            conn.commit()
    return {"symbol": sym, "news_removed": len(news_del), "catalyst_removed": len(cat_del)}


def _impact_ids(cur, catalyst_ids: list) -> list:
    """catalyst_symbol_impact rows of these catalyst events (archived and deleted before their parents)."""
    cur.execute("SELECT id FROM catalyst_symbol_impact WHERE catalyst_event_id = ANY(%s)", (list(catalyst_ids),))
    return [r[0] for r in cur.fetchall()]


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
            """SELECT headline, description, source FROM catalyst_events
               WHERE upper(symbol)=%s AND catalyst_type <> 'other'
               ORDER BY COALESCE(published_at, created_at) DESC NULLS LAST LIMIT 1""",
            (sym,),
        )
        cat = cur.fetchone()
        if not cat:
            continue
        headline, description, source = cat[0] or "", cat[1] or "", cat[2] or ""
        ok, reason = headline_matches_symbol(sym, headline, description, company_description=desc,
                                             provider_tagged=source in PROVIDER_TAGGED_SOURCES)
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