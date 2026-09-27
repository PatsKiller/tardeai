"""8-K exhibit text (EX-99.1 earnings release) as dated primary evidence (2026-09-27).

The house recorded Dell's 2026-09-01 8-K only as a headline plus the cover-page url
(catalyst_events 185738), so the symbol thesis and the options CIO packet said the
"$95B AI server backlog" and "$60.9B quarterly AI orders" had no Dell primary source
while both sit in the press release filed as exhibit 99.1 of that 8-K.

This module fetches the filing's directory index, picks the EX-99.1 document
(falling back to any EX-99.*), strips it to bounded text and pulls out the sentences
that carry a dollar figure for backlog, orders, remaining performance obligation,
guidance/outlook, revenue, operating income, EPS and cash flow. Parsing is pure and
fixture-testable; the network lives only in the thin ``fetch_*`` wrappers, which reuse
the SEC User-Agent and rate limit from financial_senses.sec_companyfacts_reader.
Storage is ``sec_filing_documents`` (unique on accession + exhibit; migration
migrations/2026_09_27_sec_filing_documents.sql). READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import html as _html
import json
import re
import time
import urllib.request
from datetime import date, timedelta
from typing import Any, Callable, Optional

try:
    from scripts.lib.financial_senses.sec_companyfacts_reader import SEC_HEADERS, _RATE_SLEEP, _default_fetcher
except ImportError:  # scripts/ on sys.path
    from lib.financial_senses.sec_companyfacts_reader import SEC_HEADERS, _RATE_SLEEP, _default_fetcher  # type: ignore

SOURCE_TYPE = "sec_8k_ex99"
QUALITY = "PRIMARY_REGULATORY"
TEXT_CAP = 60_000          # chars of exhibit text kept
MAX_FACTS = 40             # fact sentences kept per document
SENTENCE_CAP = 320         # chars of one fact sentence
# 8-K items whose exhibit 99.1 is worth reading: results of operations, Reg FD.
DOCUMENT_ITEMS = ("2.02", "7.01")
DOCUMENT_FORMS = ("8-K", "8-K/A")

_TEXT_HEADERS = {"User-Agent": SEC_HEADERS["User-Agent"], "Accept": "text/html,application/xhtml+xml,*/*"}

# Exhibit file names on EDGAR: ex991.htm, exhibit991earnings8kq2fy27.htm, d1234dex991.htm,
# ex99-1.htm, ex_99_1.htm, a2026q2ex991.htm ...
_EX991 = re.compile(r"ex(?:hibit)?[^a-z0-9]{0,2}99[^a-z0-9]{0,2}1(?!\d)", re.I)
_EX99 = re.compile(r"ex(?:hibit)?[^a-z0-9]{0,2}99", re.I)
_DOC_EXT = (".htm", ".html", ".txt")

# Dollar figures: "$95 billion", "$60.9 billion", "$1.25", "$192B", "$25 million".
_MONEY = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)\s*(billion|million|thousand|bn|mm|b|m|k)?(?!\w)", re.I)
_MULT = {"billion": 1e9, "bn": 1e9, "b": 1e9, "million": 1e6, "mm": 1e6, "m": 1e6, "thousand": 1e3, "k": 1e3}

# category -> keyword regex, in priority order.
CATEGORIES: list[tuple[str, re.Pattern[str]]] = [
    ("backlog", re.compile(r"\bbacklog\b", re.I)),
    ("orders", re.compile(r"\b(?:orders?|bookings?|booked)\b", re.I)),
    ("remaining_performance_obligation", re.compile(r"remaining performance obligations?|\bRPO\b", re.I)),
    ("guidance", re.compile(r"\b(?:outlook|guidance|forecasts?|expects?|expected|raising|raised|lowering|lowered"
                            r"|reaffirm(?:s|ed|ing)?|full[- ]year|fiscal (?:year|20\d\d|FY\s?\d\d))\b", re.I)),
    ("revenue", re.compile(r"\b(?:revenues?|net sales)\b", re.I)),
    ("operating_income", re.compile(r"\boperating (?:income|margin|profit)\b", re.I)),
    ("eps", re.compile(r"\b(?:earnings|income|loss) per (?:diluted )?share\b|\bEPS\b|\bper share\b", re.I)),
    ("cash_flow", re.compile(r"\bcash flows?\b|\bfree cash flow\b", re.I)),
]
# "raising our outlook by $25 billion to $192 billion": the level is the fact, the change is context.
_BY_TO = re.compile(r"\bby\s+(\$\s?\d[\d,]*(?:\.\d+)?\s*(?:billion|million|bn|mm|b|m)?)\s+to\s+"
                    r"(\$\s?\d[\d,]*(?:\.\d+)?\s*(?:billion|million|bn|mm|b|m)?)", re.I)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"“(])")
_TAG_NL = re.compile(r"</?(?:p|div|br|tr|li|h[1-6]|table|section|blockquote)\b[^>]*>", re.I)
_DROP = re.compile(r"<(script|style|head)\b.*?</\1\s*>", re.I | re.S)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t\r\f\v ]+")
_NLS = re.compile(r"\n\s*\n+")


# ── urls ────────────────────────────────────────────────────────────────────────

def acc_nodash(accession: str) -> str:
    return str(accession or "").replace("-", "").strip()


def cik_plain(cik: Any) -> str:
    return str(cik or "").strip().lstrip("0") or "0"


def filing_dir(cik: Any, accession: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{cik_plain(cik)}/{acc_nodash(accession)}"


def index_url(cik: Any, accession: str) -> str:
    return filing_dir(cik, accession) + "/index.json"


def index_htm_url(cik: Any, accession: str) -> str:
    return f"{filing_dir(cik, accession)}/{str(accession).strip()}-index.htm"


# ── pure parsing ────────────────────────────────────────────────────────────────

def choose_exhibit(index_json: dict[str, Any]) -> Optional[str]:
    """File name of the EX-99.1 document from a filing directory index.json, else the
    first EX-99.* document, else None. EDGAR's index.json carries names only (its
    ``type`` is the icon), so the exhibit is recognised from its file name."""
    items = ((index_json or {}).get("directory") or {}).get("item") or []
    names = [str(i.get("name") or "") for i in items if isinstance(i, dict)]
    docs = [n for n in names if n.lower().endswith(_DOC_EXT) and not n.lower().endswith("-index.htm")]
    for pat in (_EX991, _EX99):
        hits = sorted((n for n in docs if pat.search(n)), key=lambda n: (len(n), n))
        if hits:
            return hits[0]
    return None


def choose_exhibit_from_index_html(index_html: str) -> Optional[str]:
    """Fallback: the accession ``-index.htm`` lists each document with its type
    (a ``<td>EX-99.1</td>`` cell next to the link). Returns the href's file name."""
    rows = re.findall(r"<tr\b.*?</tr>", index_html or "", flags=re.I | re.S)
    best: Optional[tuple[int, str]] = None
    for row in rows:
        m_type = re.search(r"EX-99(?:\.(\d+))?", row, flags=re.I)
        m_href = re.search(r'href="([^"]+\.(?:htm|html|txt))"', row, flags=re.I)
        if not (m_type and m_href):
            continue
        name = m_href.group(1).rsplit("/", 1)[-1]
        rank = 0 if (m_type.group(1) or "") == "1" else 1
        if best is None or rank < best[0]:
            best = (rank, name)
    return best[1] if best else None


def html_to_text(doc: str, *, cap: int = TEXT_CAP) -> str:
    """Strip an EDGAR HTML/iXBRL exhibit to readable text, bounded to ``cap`` chars."""
    s = _DROP.sub(" ", doc or "")
    s = _TAG_NL.sub("\n", s)
    s = _TAG.sub(" ", s)
    s = _html.unescape(s).replace(" ", " ")
    s = _WS.sub(" ", s)
    s = "\n".join(line.strip() for line in s.split("\n"))
    s = _NLS.sub("\n\n", s).strip()
    return s[:cap]


def parse_money(text: str) -> list[dict[str, Any]]:
    """Every dollar figure in ``text`` as {raw, usd, pos}."""
    out = []
    for m in _MONEY.finditer(text or ""):
        num = float(m.group(1).replace(",", ""))
        unit = (m.group(2) or "").lower()
        raw = "$" + m.group(0).strip()[1:].strip()  # "$ 6.34" -> "$6.34"
        out.append({"raw": raw, "usd": round(num * _MULT.get(unit, 1.0), 2), "pos": m.start(),
                    "scaled": bool(unit)})
    return out


def _sentences(text: str) -> list[str]:
    out = []
    for para in (text or "").split("\n"):
        for s in _SENTENCE_SPLIT.split(para.strip()):
            s = s.strip()
            if len(s) >= 20:
                out.append(s)
    return out


_PER_SHARE = re.compile(r"per (?:diluted )?share|\bEPS\b", re.I)
_LOWER_WORD = re.compile(r"\b[a-z]{3,}\b")


def _narrative(sent: str) -> bool:
    """Prose, not a financial-table row ("Net revenue $ 46,971 $ 29,776 58%")."""
    return len(_LOWER_WORD.findall(sent)) >= 2


def _nearest(figs: list[dict[str, Any]], pos: int) -> dict[str, Any]:
    return min(figs, key=lambda f: abs(f["pos"] - pos))


def extract_facts(text: str, *, max_facts: int = MAX_FACTS) -> list[dict[str, Any]]:
    """Fact sentences that carry a dollar figure and one of the tracked categories.

    One record per (sentence, category) so a release sentence that books orders,
    recognises revenue and reports backlog yields three dated facts, each with the
    figure nearest its keyword (``amount_usd``) and every figure in the sentence
    (``figures``). Guidance prefers the target of a "by $X to $Y" phrase."""
    facts: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for sent in _sentences(text):
        figs = parse_money(sent)
        if not figs or not _narrative(sent):
            continue
        by_to = _BY_TO.search(sent)
        for cat, pat in CATEGORIES:
            m = pat.search(sent)
            if not m:
                continue
            key = (cat, sent[:120].lower())
            if key in seen:
                continue
            seen.add(key)
            chosen = _nearest(figs, m.start())
            if by_to and chosen["pos"] == _nearest(figs, by_to.start(1))["pos"]:
                chosen = _nearest(figs, by_to.start(2))  # the level, not the change
            # A per-share figure is small and unscaled; every other category needs a scaled
            # figure ("$95 billion") or a per-share context -- a bare "$ 46,971" is a table
            # cell in millions and would be read as $46,971.
            if cat == "eps":
                if chosen["scaled"]:
                    continue
            elif not chosen["scaled"] and not _PER_SHARE.search(sent):
                continue
            facts.append({
                "category": cat,
                "sentence": sent[:SENTENCE_CAP],
                "amount_usd": chosen["usd"],
                "amount_raw": chosen["raw"],
                "figures": [f["raw"] for f in figs],
            })
            if len(facts) >= max_facts:
                return facts
    return facts


def document_record(*, symbol: str, cik: Any, accession: str, form: str, items: str, exhibit: str,
                    filing_date: str, doc_url: str, text: str,
                    facts: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
    return {
        "symbol": str(symbol or "").upper(), "cik": str(cik or "").strip().zfill(10),
        "accession": str(accession or "").strip(), "form": str(form or "").upper(), "items": str(items or ""),
        "exhibit": exhibit, "filing_date": str(filing_date or "")[:10], "doc_url": doc_url,
        "text": (text or "")[:TEXT_CAP], "facts": facts if facts is not None else extract_facts(text),
    }


def filings_needing_documents(filings: list[dict[str, Any]], *, since_days: int = 45,
                              today: Optional[date] = None) -> list[dict[str, Any]]:
    """8-K rows with Item 2.02 / 7.01 inside the window (same window as the events)."""
    today = today or date.today()
    cutoff = today - timedelta(days=since_days)
    out = []
    for f in filings:
        if str(f.get("form") or "").upper() not in DOCUMENT_FORMS:
            continue
        try:
            filed = date.fromisoformat(str(f.get("filing_date") or "")[:10])
        except ValueError:
            continue
        if filed < cutoff:
            continue
        items = {x.strip() for x in str(f.get("items") or "").split(",") if x.strip()}
        if items & set(DOCUMENT_ITEMS) and f.get("accession_number"):
            out.append(f)
    return out


# ── network (thin) ──────────────────────────────────────────────────────────────

def _default_text_fetcher(url: str, timeout: float = 20.0) -> str:
    time.sleep(_RATE_SLEEP)
    req = urllib.request.Request(url, headers=_TEXT_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def fetch_exhibit(cik: Any, accession: str, *, fetch_json: Optional[Callable[[str], dict]] = None,
                  fetch_text: Optional[Callable[[str], str]] = None) -> Optional[dict[str, Any]]:
    """{exhibit, doc_url, html, text, facts} for the filing's EX-99.1 (or EX-99.*), or None."""
    fetch_json = fetch_json or _default_fetcher
    fetch_text = fetch_text or _default_text_fetcher
    name = None
    try:
        name = choose_exhibit(fetch_json(index_url(cik, accession)))
    except Exception:  # noqa: BLE001 — fall through to the -index.htm listing
        name = None
    if not name:
        try:
            name = choose_exhibit_from_index_html(fetch_text(index_htm_url(cik, accession)))
        except Exception:  # noqa: BLE001
            name = None
    if not name:
        return None
    doc_url = f"{filing_dir(cik, accession)}/{name}"
    raw = fetch_text(doc_url)
    text = html_to_text(raw)
    return {"exhibit": exhibit_label(name), "doc_url": doc_url, "html": raw, "text": text,
            "facts": extract_facts(text)}


def exhibit_label(name: str) -> str:
    m = re.search(r"99[^a-z0-9]{0,2}(\d+)", name or "", flags=re.I)
    return f"EX-99.{m.group(1)}" if m else "EX-99"


def fetch_documents_for_filings(symbol: str, cik: Any, filings: list[dict[str, Any]], *,
                                since_days: int = 45, today: Optional[date] = None,
                                skip: Optional[Callable[[str, str], bool]] = None,
                                fetch_json: Optional[Callable[[str], dict]] = None,
                                fetch_text: Optional[Callable[[str], str]] = None,
                                max_docs: int = 3) -> list[dict[str, Any]]:
    """Document records for the in-window 8-K 2.02/7.01 filings. ``skip(accession, exhibit)``
    lets the caller avoid refetching stored documents (idempotent on accession+exhibit)."""
    out = []
    for f in filings_needing_documents(filings, since_days=since_days, today=today):
        acc = str(f["accession_number"])
        if skip and skip(acc, "EX-99.1"):
            continue
        got = fetch_exhibit(cik, acc, fetch_json=fetch_json, fetch_text=fetch_text)
        if not got:
            continue
        if skip and got["exhibit"] != "EX-99.1" and skip(acc, got["exhibit"]):
            continue
        out.append(document_record(symbol=symbol, cik=cik, accession=acc, form=f.get("form") or "8-K",
                                   items=f.get("items") or "", exhibit=got["exhibit"],
                                   filing_date=f.get("filing_date") or "", doc_url=got["doc_url"],
                                   text=got["text"], facts=got["facts"]))
        if len(out) >= max_docs:
            break
    return out


# ── storage ─────────────────────────────────────────────────────────────────────

TABLE = "sec_filing_documents"
EXISTS_SQL = f"SELECT 1 FROM {TABLE} WHERE accession=%s AND exhibit=%s LIMIT 1"
UPSERT_SQL = f"""INSERT INTO {TABLE} (symbol, cik, accession, form, items, exhibit, filing_date, doc_url, text, facts, created_at)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,NOW())
                 ON CONFLICT (accession, exhibit) DO UPDATE
                 SET facts=EXCLUDED.facts, text=EXCLUDED.text, doc_url=EXCLUDED.doc_url, symbol=EXCLUDED.symbol"""
SELECT_SQL = f"""SELECT symbol, cik, accession, form, items, exhibit, filing_date, doc_url, facts
                 FROM {TABLE} WHERE symbol=%s ORDER BY filing_date DESC, accession DESC LIMIT %s"""


def stored(cur, accession: str, exhibit: str) -> bool:
    cur.execute(EXISTS_SQL, (accession, exhibit))
    return bool(cur.fetchone())


def upsert(cur, rec: dict[str, Any]) -> None:
    cur.execute(UPSERT_SQL, (rec["symbol"], rec["cik"], rec["accession"], rec["form"], rec["items"],
                             rec["exhibit"], rec["filing_date"] or None, rec["doc_url"], rec["text"],
                             json.dumps(rec["facts"], default=str)))


def load_documents(symbol: str, *, cur=None, execute: Optional[Callable[..., Any]] = None,
                   limit: int = 3) -> list[dict[str, Any]]:
    """Newest stored documents for a symbol via a cursor or a db_adapter-style
    ``execute(sql, params, fetch='all')``."""
    sym = str(symbol or "").upper()
    if cur is not None:
        cur.execute(SELECT_SQL, (sym, limit))
        rows = cur.fetchall() or []
    elif execute is not None:
        rows = execute(SELECT_SQL, (sym, limit), fetch="all") or []
    else:
        return []
    out = []
    for r in rows:
        r = dict(r)
        facts = r.get("facts")
        if isinstance(facts, str):
            try:
                facts = json.loads(facts)
            except ValueError:
                facts = []
        r["facts"] = facts or []
        out.append(r)
    return out


# ── read side ───────────────────────────────────────────────────────────────────

def fact_line(symbol: str, rec: dict[str, Any], fact: dict[str, Any]) -> str:
    """One dated sentence for a prompt: the figure, the sentence, the filing."""
    return (f"{str(symbol).upper()} {rec.get('form') or '8-K'} {rec.get('exhibit') or 'EX-99'} filed "
            f"{str(rec.get('filing_date') or '')[:10]} ({fact.get('category')} {fact.get('amount_raw') or ''}): "
            f"{fact.get('sentence') or ''}")


def primary_disclosures(symbol: str, records: list[dict[str, Any]], *, max_facts: int = 12) -> list[dict[str, Any]]:
    """Dated, linked disclosures for the CIO packet from stored documents (newest first)."""
    out = []
    for rec in records:
        for f in rec.get("facts") or []:
            out.append({
                "date": str(rec.get("filing_date") or "")[:10],
                "form": f"{rec.get('form') or '8-K'} {rec.get('exhibit') or 'EX-99'}",
                "category": f.get("category"),
                "amount": f.get("amount_raw"),
                "fact": f.get("sentence"),
                "url": rec.get("doc_url"),
                "accession": rec.get("accession"),
            })
            if len(out) >= max_facts:
                return out
    return out


def load_primary_disclosures(symbol: str, *, execute: Optional[Callable[..., Any]] = None,
                             limit: int = 3, max_facts: int = 12) -> list[dict[str, Any]]:
    """Disclosures straight from the database; [] on any failure (table absent, no DB)."""
    try:
        if execute is None:
            try:
                from db_adapter import _execute as execute  # type: ignore
            except ImportError:
                from scripts.db_adapter import _execute as execute  # type: ignore
        return primary_disclosures(symbol, load_documents(symbol, execute=execute, limit=limit), max_facts=max_facts)
    except Exception:  # noqa: BLE001
        return []


RPO_NOTE = ("Remaining performance obligation (RPO) from the 10-Q is a company-wide contracted-revenue "
            "metric; it is NOT the AI server backlog, which is disclosed separately in the earnings release. "
            "Never present RPO as the AI server backlog.")


def rpo_note(fundamental_lines: list[str], disclosures: list[dict[str, Any]]) -> Optional[str]:
    """The note when both an RPO line and a backlog disclosure are present."""
    has_rpo = any(re.search(r"remaining performance obligation|\bRPO\b", str(x), re.I) for x in fundamental_lines or [])
    has_backlog = any(d.get("category") == "backlog" for d in disclosures or [])
    return RPO_NOTE if has_rpo and has_backlog else None
