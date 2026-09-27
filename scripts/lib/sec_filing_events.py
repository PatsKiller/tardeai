"""SEC filings as dated catalyst events (fundamentals plan F3, 2026-09-27).

Recent 8-K items and 10-Q/10-K filings from the official submissions feed become
catalyst_events rows (source sec_edgar), which the catalyst graph binds to the
registry entity as SecurityEvent@v1 nodes. A high-severity 8-K (results, M&A,
material agreement, officer change, bankruptcy) on a symbol the house tracks files a
symbol-thesis priority request so the thesis is re-synthesized with the filing in
hand. Idempotent on catalyst_events (symbol, headline). READ_ONLY_ADVISORY.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

# 8-K item -> (catalyst_type, severity, label)
ITEMS: dict[str, tuple[str, str, str]] = {
    "1.01": ("material_agreement", "high", "Entry into a material agreement"),
    "1.03": ("bankruptcy", "high", "Bankruptcy or receivership"),
    "2.01": ("merger_acquisition", "high", "Completed acquisition or disposition"),
    "2.02": ("earnings", "high", "Results of operations"),
    "2.05": ("restructuring", "medium", "Exit or restructuring costs"),
    "2.06": ("impairment", "medium", "Material impairment"),
    "4.02": ("restatement", "high", "Non-reliance on prior financials"),
    "5.02": ("executive_change", "medium", "Officer or director change"),
    "7.01": ("regulatory_disclosure", "low", "Regulation FD disclosure"),
    "8.01": ("regulatory_disclosure", "low", "Other events"),
}
PERIODIC = {"10-Q": ("filing_quarterly", "medium", "Quarterly report"),
            "10-K": ("filing_annual", "medium", "Annual report")}
HIGH = {"high"}


def events_from_filings(symbol: str, filings: list[dict[str, Any]], *, since_days: int = 45,
                        today: Optional[date] = None) -> list[dict[str, Any]]:
    today = today or date.today()
    cutoff = today - timedelta(days=since_days)
    out = []
    for f in filings:
        form = str(f.get("form") or "").upper()
        try:
            filed = date.fromisoformat(str(f.get("filing_date") or "")[:10])
        except ValueError:
            continue
        if filed < cutoff:
            continue
        entries: list[tuple[str, str, str]] = []
        if form in ("8-K", "8-K/A"):
            for item in [x.strip() for x in str(f.get("items") or "").split(",") if x.strip()]:
                if item in ITEMS:
                    entries.append(ITEMS[item] + (f"Item {item}",))  # type: ignore[arg-type]
        elif form in PERIODIC:
            entries.append(PERIODIC[form] + (form,))  # type: ignore[arg-type]
        for ctype, sev, label, tag in entries:
            out.append({
                "symbol": symbol.upper(), "catalyst_type": ctype, "severity": sev,
                "headline": f"{symbol.upper()} {form}: {label} ({tag}) filed {filed.isoformat()}",
                "description": f"SEC {form} {tag}: {label}. Accession {f.get('accession_number')}.",
                "source": "sec_edgar", "source_url": f.get("sec_url") or "", "published_at": filed.isoformat(),
            })
    return out


RELEVANT_FORMS = {"8-K", "8-K/A", "10-Q", "10-K"}


def filings_from_submissions(cik: str, submissions: dict[str, Any]) -> list[dict[str, Any]]:
    """All recent 8-K/10-Q/10-K filings from one submissions payload. The first N rows
    are mostly Form 4 and 144 for large issuers, so a fixed-size window misses them."""
    recent = ((submissions or {}).get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    col = lambda k, i: (recent.get(k) or [])[i] if i < len(recent.get(k) or []) else ""  # noqa: E731
    out = []
    for i, f in enumerate(forms):
        if str(f).upper() not in RELEVANT_FORMS:
            continue
        acc = col("accessionNumber", i)
        doc = col("primaryDocument", i)
        out.append({"form": f, "filing_date": col("filingDate", i), "accession_number": acc,
                    "items": col("items", i),
                    "sec_url": (f"https://www.sec.gov/Archives/edgar/data/{str(cik).lstrip('0')}/"
                                f"{acc.replace('-', '')}/{doc}" if acc and doc else "")})
    return out


INSERT_SQL = """INSERT INTO catalyst_events (symbol, catalyst_type, headline, description, severity, confidence,
                                             source, source_url, published_at, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                ON CONFLICT (symbol, headline) DO NOTHING"""


def insert(cur, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Insert; returns the events that were new (rowcount 1)."""
    new = []
    for e in events:
        cur.execute(INSERT_SQL, (e["symbol"], e["catalyst_type"], e["headline"][:500], e["description"],
                                 e["severity"], 0.95, e["source"], e["source_url"], e["published_at"]))
        if getattr(cur, "rowcount", 0) == 1:
            new.append(e)
    return new


def is_material(e: dict[str, Any]) -> bool:
    return e.get("severity") in HIGH
