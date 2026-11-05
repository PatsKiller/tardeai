"""Prospectus NEWS relevance gate — deterministic and free (operator 2026-10-27: "Implement these fixes … I need this
to execute quickly").

Problems it closes (measured on the 2026-10-26 build): the old ``material_news`` trigger fired on ANY new catalyst row
since the report (no importance, no relevance); ticker collisions reached the report ("Berenberg … Xaar (LON:XAR)" on
the US ETF XAR); the CIO never read news against the prospectus; the page showed nothing after it was written.

Every item since the report (typed ``catalyst_events`` rows and ``news_articles`` headlines, already read by
``inputs.HouseSources``) passes, in order:

1. **issuer match** — SEC-feed items are the issuer's by construction (CIK feed); a foreign-listing marker for the
   ticker (``LON:XAR``, ``(LSE: XAR)``, ``XAR.L``) or a company named in ``config/prospectus_symbol_collisions.json``
   ``exclude`` without the issuer's own name is a ``collision``; the issuer's name / alias, ``(NYSE: SYM)`` /
   ``(NASDAQ: SYM)`` or ``$SYM`` is ``relevant``; anything else is ``uncertain``.
2. **dedupe** — syndicated copies (normalised title within 48 h) collapse to the earliest; the rest are ``duplicate``.
3. **materiality** — the existing catalyst grade/type: SEC 8-K / 10-Q / 10-K types, earnings, guidance, up/downgrade,
   M&A, dividend change, at severity >= medium. A headline without a typed row is ``uncertain`` when it reads like
   one of those, else ``not_material``.

Uncertain items go to the cheap Haiku classifier (``news_note.classify``; Anthropic credit only; never DeepSeek). The
verdict per item is ``accepted`` (relevant AND material) or ``rejected`` with one reason from ``REASONS``.

READ_ONLY_ADVISORY (MBI_BEHAVIOR=0): this module reads text and labels it; nothing sizes, orders, stops or weights.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable

CONFIG_REL = "config/prospectus_symbol_collisions.json"
DEDUPE_HOURS = 48
REASONS = ("collision", "duplicate", "not_material", "not_relevant", "classifier_unavailable", "cio_no_impact",
           "coalesced", "note_cap", "no_report")
SEVERITY_RANK = {"low": 1, "info": 1, "medium": 2, "warning": 2, "warn": 2, "high": 3, "critical": 4}
# catalyst_type values (sec_filing_events.ITEMS / PERIODIC, news_to_catalyst.CATALYST_KEYWORDS, Hermes prefixes)
# that are material at severity >= medium.
MATERIAL_TYPES = frozenset({
    "earnings", "earnings_beat", "earnings_miss", "guidance", "guidance_raise", "guidance_lower",
    "analyst_upgrade", "analyst_downgrade", "analyst", "merger_acquisition", "merger", "material_agreement",
    "bankruptcy", "restatement", "restructuring", "impairment", "executive_change", "ceo_change",
    "filing_quarterly", "filing_annual", "dividend", "dividend_increase", "dividend_cut", "fda", "fda_approval",
    "regulatory", "dilution", "buyback", "stock_split"})
SEC_TYPES = frozenset({"material_agreement", "bankruptcy", "merger_acquisition", "earnings", "restructuring",
                       "impairment", "restatement", "executive_change", "regulatory_disclosure", "filing_quarterly",
                       "filing_annual"})
#: Types whose material item asks for a FULL rewrite (the rest are delta): earnings.
FULL_TYPES = frozenset({"earnings", "earnings_beat", "earnings_miss", "filing_quarterly", "filing_annual"})
MATERIAL_WORDS = re.compile(
    r"(?i)\b(8-K|10-Q|10-K|earnings|results|quarter(?:ly)? (?:profit|loss|revenue)|guidance|outlook|forecast|"
    r"upgrade[sd]?|downgrade[sd]?|price target|initiat\w+ (?:coverage|at)|acquir\w+|acquisition|merger|takeover|"
    r"buyout|dividend|split|buyback|repurchase|bankrupt\w*|restat\w+|ceo|cfo|resign\w*|offering|dilution|"
    r"fda|approval|lawsuit|investigation|recall|contract award|awarded)\b")
_PUNCT = re.compile(r"[^a-z0-9 ]+")
_NAME_STOP = {"inc", "corp", "corporation", "company", "co", "ltd", "plc", "holdings", "holding", "group", "the",
              "class", "fund", "trust", "etf", "shares", "sa", "nv", "ag", "lp", "llc", "spdr", "ishares", "s&p",
              "and", "of", "&", "a", "b"}


def load_collisions(root: Path | None = None) -> dict:
    base = Path(root) if root is not None else Path(__file__).resolve().parents[3]
    try:
        doc = json.loads((base / CONFIG_REL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        doc = {}
    doc.setdefault("symbols", {})
    doc.setdefault("foreign_exchange_prefixes", ["LON", "LSE", "TSX", "ASX", "HKEX", "FRA", "ETR", "EPA"])
    doc.setdefault("foreign_suffixes", ["L", "TO", "AX", "HK", "DE", "PA"])
    return doc


def _dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        out = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return out if out.tzinfo else out.replace(tzinfo=timezone.utc)


def norm_title(title: Any) -> str:
    """Syndication key: lower-case, trailing " - Publisher" dropped, punctuation stripped, whitespace collapsed."""
    t = " ".join(str(title or "").lower().split())
    head, sep, tail = t.rpartition(" - ")
    if sep and head and len(tail) <= 40:
        t = head
    return " ".join(_PUNCT.sub(" ", t).split())[:160]


def item_id(item: dict) -> str:
    raw = f"{norm_title(item.get('title'))}|{str(item.get('at') or '')[:10]}|{item.get('kind')}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def name_words(name: Any) -> list[str]:
    """The distinctive words of an issuer name ("Acme Robotics Inc." -> ["acme", "robotics"])."""
    return [w for w in re.findall(r"[a-z][a-z0-9]{2,}", str(name or "").lower()) if w not in _NAME_STOP][:3]


def _mentions_issuer(text: str, sym: str, identity: dict, entry: dict) -> bool:
    low = text.lower()
    names = [identity.get("name"), entry.get("issuer"), *(entry.get("issuer_aliases") or []),
             *(identity.get("aliases") or [])]
    for n in names:
        words = name_words(n)
        if words and all(re.search(rf"\b{re.escape(w)}\b", low) for w in words[:2]):
            return True
    if re.search(rf"(?i)\((?:NYSE(?:\s*ARCA|\s*American)?|NASDAQ|NYSEARCA|AMEX|BATS|CBOE|OTC\w*)\s*:\s*{re.escape(sym)}\)", text):
        return True
    if re.search(rf"\${re.escape(sym)}\b", text):
        return True
    cik = str(identity.get("cik") or "").lstrip("0")
    return bool(cik) and bool(re.search(rf"(?:CIK|cik)\D{{0,3}}0*{cik}\b", text))


def collision_reason(text: Any, symbol: str, identity: dict | None = None, *, collisions: dict | None = None) -> str | None:
    """Why ``text`` is about a DIFFERENT security that shares the ticker, or None.

    A foreign-listing marker for the ticker, or a company in the symbol's ``exclude`` list, is a collision unless the
    text also names the issuer the house means."""
    text = str(text or "")
    sym = str(symbol or "").upper()
    if not text or not sym:
        return None
    cfg = collisions if collisions is not None else load_collisions()
    entry = (cfg.get("symbols") or {}).get(sym) or {}
    identity = identity or {}
    names_issuer = _mentions_issuer(text, sym, identity, entry)
    s = re.escape(sym)
    prefixes = "|".join(re.escape(p) for p in cfg.get("foreign_exchange_prefixes") or [])
    suffixes = "|".join(re.escape(p) for p in cfg.get("foreign_suffixes") or [])
    marker = None
    if prefixes and re.search(rf"(?i)\b(?:{prefixes})\s*:\s*{s}\b", text):
        marker = "foreign listing prefix"
    elif re.search(rf"(?i)\(\s*(?:LSE|London Stock Exchange|AIM)\b[^)]*\b{s}\b", text):
        marker = "London listing"
    elif suffixes and re.search(rf"\b{s}\.(?:{suffixes})\b", text):
        marker = "foreign listing suffix"
    own_exchange = str(identity.get("exchange") or "").upper()
    if marker and not (own_exchange and own_exchange in text.upper() and names_issuer):
        return f"collision: {marker} for {sym}"
    for ex in entry.get("exclude") or []:
        nm = str(ex.get("name") or "")
        if nm and re.search(rf"(?i)\b{re.escape(nm)}\b", text) and not names_issuer:
            return f"collision: names {nm} ({ex.get('why') or 'a different company'})"
    return None


def relevance(item: dict, symbol: str, identity: dict | None = None, *, collisions: dict | None = None) -> tuple[str, str]:
    """('relevant' | 'collision' | 'uncertain', why)."""
    cfg = collisions if collisions is not None else load_collisions()
    sym = str(symbol or "").upper()
    text = f"{item.get('title') or ''} {item.get('summary') or ''}"
    why = collision_reason(text, sym, identity, collisions=cfg)
    if why:
        return "collision", why
    if item.get("source") == "sec_edgar" or item.get("catalyst_type") in SEC_TYPES and "sec" in str(item.get("source") or "").lower():
        return "relevant", "SEC filing feed (issuer CIK)"
    if _mentions_issuer(text, sym, identity or {}, (cfg.get("symbols") or {}).get(sym) or {}):
        return "relevant", "names the issuer"
    return "uncertain", "ticker only; issuer not named"


def materiality(item: dict) -> tuple[bool | None, str]:
    """(True | False | None=uncertain, why) from the existing catalyst grade/type."""
    ctype = str(item.get("catalyst_type") or "").lower()
    sev = SEVERITY_RANK.get(str(item.get("severity") or "").lower(), 0)
    if ctype:
        if ctype in MATERIAL_TYPES and sev >= 2:
            return True, f"{ctype} ({item.get('severity')})"
        if ctype in MATERIAL_TYPES:
            return False, f"{ctype} below medium ({item.get('severity') or 'n/a'})"
        return False, f"type {ctype} is not a material type"
    if re.search(r"(?i)\bdowngrade", str(item.get("title") or "")):
        return None, "reads like a downgrade (untyped headline)"
    if MATERIAL_WORDS.search(str(item.get("title") or "")):
        return None, "untyped headline with a material keyword"
    return False, "untyped headline, no material keyword"


def normalise(catalysts: Iterable[dict] | None, news: Iterable[dict] | None) -> list[dict]:
    """One list of items from the two existing readers (typed catalysts first, so a typed copy wins the dedupe)."""
    out = []
    for c in catalysts or []:
        if not isinstance(c, dict):
            continue
        src = str(c.get("source") or "")
        kind = "filing" if c.get("catalyst_type") in SEC_TYPES and ("sec" in src.lower() or "8-K" in str(c.get("headline") or "")
                                                                   or "10-" in str(c.get("headline") or "")) else "catalyst"
        out.append({"kind": kind, "title": c.get("headline") or c.get("title"), "source": src or "catalyst_events",
                    "url": c.get("source_url") or c.get("url"), "at": c.get("at") or c.get("published_at"),
                    "catalyst_type": c.get("catalyst_type"), "severity": c.get("severity")})
    for n in news or []:
        if not isinstance(n, dict):
            continue
        out.append({"kind": "headline", "title": n.get("title"), "source": n.get("source") or "news_articles",
                    "url": n.get("url") or n.get("source_url"), "at": n.get("published_at") or n.get("at"),
                    "catalyst_type": None, "severity": None})
    for it in out:
        it["id"] = item_id(it)
    return [it for it in out if str(it.get("title") or "").strip()]


def dedupe(items: list[dict], *, hours: int = DEDUPE_HOURS) -> tuple[list[dict], list[dict]]:
    """(kept, duplicates): the same normalised title within ``hours`` collapses to the earliest copy (a typed
    catalyst copy is preferred at the same instant)."""
    order = sorted(items, key=lambda i: (_dt(i.get("at")) or datetime.max.replace(tzinfo=timezone.utc),
                                         0 if i.get("kind") != "headline" else 1))
    kept: list[dict] = []
    dups: list[dict] = []
    seen: dict[str, datetime] = {}
    for it in order:
        key = norm_title(it.get("title"))
        at = _dt(it.get("at")) or datetime.min.replace(tzinfo=timezone.utc)
        first = seen.get(key)
        if first is not None and abs((at - first).total_seconds()) <= hours * 3600:
            dups.append(dict(it, duplicate_of=key))
            continue
        seen.setdefault(key, at)
        kept.append(it)
    return kept, dups


def review(symbol: str, items: list[dict], *, since: datetime | None, identity: dict | None = None,
           collisions: dict | None = None, known: dict | None = None) -> list[dict]:
    """Gate every item newer than ``since``. Returns rows ``{..item, relevant, material, verdict, reason, why}`` where
    verdict is ``accepted`` | ``rejected`` | ``uncertain`` (needs the classifier). Items already in ``known`` (the
    symbol's news log, by id) keep their recorded verdict and are not re-judged."""
    cfg = collisions if collisions is not None else load_collisions()
    known = known or {}
    fresh = [i for i in items if since is None or (_dt(i.get("at")) or since) > since]
    kept, dups = dedupe(fresh)
    out = []
    for d in dups:
        out.append(dict(d, relevant=None, material=None, verdict="rejected", reason="duplicate",
                        why="syndicated copy within 48h"))
    for it in kept:
        if it["id"] in known and known[it["id"]].get("verdict") in ("accepted", "rejected") \
                and not known[it["id"]].get("retry"):
            out.append(dict(known[it["id"]]))
            continue
        rel, rwhy = relevance(it, symbol, identity, collisions=cfg)
        if rel == "collision":
            out.append(dict(it, relevant=False, material=None, verdict="rejected", reason="collision", why=rwhy))
            continue
        mat, mwhy = materiality(it)
        row = dict(it, relevant=True if rel == "relevant" else None, material=mat, why=f"{rwhy}; {mwhy}")
        if mat is False:
            row.update(verdict="rejected", reason="not_material")
        elif rel == "relevant" and mat is True:
            row.update(verdict="accepted", reason=None)
        else:
            row.update(verdict="uncertain", reason=None)
        out.append(row)
    return sorted(out, key=lambda r: str(r.get("at") or ""), reverse=True)


def apply_classification(rows: list[dict], labels: dict[str, dict] | None) -> list[dict]:
    """Fold the classifier's ``{id: {relevant, material, why}}`` into the uncertain rows; an uncertain row without a
    label is rejected ``classifier_unavailable`` (it is retried at the next window)."""
    labels = labels or {}
    for r in rows:
        if r.get("verdict") != "uncertain":
            continue
        lab = labels.get(r["id"])
        if not isinstance(lab, dict):
            r.update(verdict="rejected", reason="classifier_unavailable", retry=True)
            continue
        relevant = bool(lab.get("relevant")) if r.get("relevant") is None else bool(r["relevant"])
        material = bool(lab.get("material")) if r.get("material") is None else bool(r["material"])
        r.update(relevant=relevant, material=material, classified_by="haiku",
                 why=f"{r.get('why')}; classifier: {str(lab.get('why') or '')[:160]}")
        if not relevant:
            r.update(verdict="rejected", reason="not_relevant")
        elif not material:
            r.update(verdict="rejected", reason="not_material")
        else:
            r.update(verdict="accepted", reason=None)
    return rows


def filter_facts(rows: Iterable[dict], symbol: str, name: str | None, *, text_key: str,
                 collisions: dict | None = None) -> tuple[list[dict], list[dict]]:
    """(kept, dropped) — drop collision rows before they become report facts (inputs.assemble)."""
    cfg = collisions if collisions is not None else load_collisions()
    kept, dropped = [], []
    for r in rows or []:
        why = collision_reason((r or {}).get(text_key), symbol, {"name": name}, collisions=cfg)
        (dropped if why else kept).append(dict(r, collision=why) if why else r)
    return kept, dropped


def since(timestamp: Any) -> datetime | None:
    return _dt(timestamp)


def window_cutoff(now: datetime, days: int = 45) -> datetime:
    return now - timedelta(days=days)
