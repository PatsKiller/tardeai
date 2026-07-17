#!/usr/bin/env python3
"""RI v3.1 (WS-D): deterministic anti-garbage / anti-hallucination lint.

Zero LLM. Flags DEMOTE AND DISCLOSE — they never delete. Runs inside snapshot
materialization and standalone:

  python scripts/research_intelligence_qa_lint.py          # lint current feed, print distribution

Flags:
  undated_claim        — "as of mid-2026"-style vague dating in advisory prose
  off_universe_mention — unknown ticker-like token or corporate name in an
                         advisory brief (the "Beauty Farm Medical" class)
  unsourced_advisory   — implications/ticker recs with empty sources[]
  no_counter_view      — directional language with no assemblable counter-view
                         (bear case / Hermes divergence) → renders "single-view"
  duplicate_of:<id>    — ≥0.8 shingle overlap with a newer live brief
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

VAGUE_DATE_RE = re.compile(r"\bas of (mid|early|late)[- ]?\d{4}\b", re.I)
DIRECTIONAL_RE = re.compile(
    r"\b(add|trim|rotate|overweight|underweight|accumulate|reduce|buy|sell)\b", re.I)
TICKERISH_RE = re.compile(r"\b[A-Z]{2,5}\b")
# Corporate-name detector: ≥2 TitleCase words ending in a corporate-ish suffix —
# deterministic, low-FP; catches "Beauty Farm Medical & Health" without NLP
CORP_NAME_RE = re.compile(
    r"\b((?:[A-Z][a-z]{2,}\s+){1,4}(?:Inc|Corp|Corporation|Ltd|Group|Holdings|"
    r"Medical|Pharma|Bio|Biotech|Health|Technologies|Industries|Farm|Labs|"
    r"Therapeutics|Sciences)\b(?:\s*&\s*[A-Z][a-z]+)*)")

# Non-ticker ALL-CAPS vocabulary that legitimately appears in prose
CAPS_ALLOW = {
    "RSI", "ATR", "SMA", "EMA", "ETF", "ETFS", "IRA", "ROTH", "MAGI", "IRMAA",
    "SSDI", "SGA", "RMD", "MAPT", "CEF", "CEFS", "NAV", "USA", "US", "NYSE",
    "SEC", "FED", "FRED", "CMS", "SSA", "IRS", "GDP", "CPI", "PCE", "AI",
    "LLM", "API", "CEO", "CFO", "IPO", "YTD", "LT", "ST", "OK", "PE", "EPS",
    "REIT", "REITS", "VIX", "SPY", "QQQ", "OCO", "GTC", "RTH", "DCA", "MAX",
    "HIGH", "LOW", "NEAR", "STOP", "GO", "WAIT", "NOGO", "TIER", "THE", "AND",
    "FOR", "NOT", "NEW", "ALL", "ONE", "TWO", "BUY", "SELL", "HOLD", "TRIM",
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


# ── Reports v3 WS-C: deterministic preamble stripping for LLM-derived advisory prose ──────────
# The auto-research writer stored raw model output ("Okay, here's your updated advisory based on
# the DJUL research iteration #3, incorporating…") verbatim and it rendered as findings. Strip
# conversational openers at WRITE time; display gets the same helper as fallback. Deterministic
# regex only — no LLM in this path.
_PREAMBLE_SENTENCE = re.compile(
    r"^\s*(?:\*\*[^*\n]{0,60}\*\*[:\s-]*)?"                       # leading "**Updated Advisory:**" label
    r"(?:okay|ok(?:ay)?|sure|certainly|absolutely|of course|great|understood|got it|alright"
    r"|here(?:['’]s| is| are)\b|below is\b|i(?:['’]ll| will| can| have)\b|as requested\b"
    r"|based on (?:the )?(?:provided|your|this)\b|this (?:updated |is (?:an? )?)?advisor)"
    r"[^.!?\n]*[.!?:]?\s*",
    re.IGNORECASE)
_PREAMBLE_LABEL = re.compile(r"^\s*(?:#{1,4}\s*)?\*{0,2}(?:updated )?advisor[a-z ]{0,24}\*{0,2}[:\s-]+", re.IGNORECASE)
PREAMBLE_STUB = "research pending — no substantive findings yet (iter #{n})"


_META_HEADER_LINE = re.compile(
    r"^[\s#*\-–—]*(?:(?:updated|new)\s+)?advisor(?:y|ies)\b[^\n]{0,110}$"
    r"|^[^\n]{0,90}iteration\s*#\d+[^\n]{0,25}$",
    re.IGNORECASE)


def strip_preamble(text: str, max_rounds: int = 4) -> tuple[str, bool]:
    """Remove leading conversational/meta sentences, header labels, and orphan meta-header
    lines ("**Updated Advisory – X – Iteration #30**"). Returns (cleaned, stripped_anything)."""
    t = (text or "").lstrip()
    stripped = False
    for _ in range(max_rounds):
        n = _PREAMBLE_LABEL.sub("", t, count=1)
        n = _PREAMBLE_SENTENCE.sub("", n, count=1)
        first_line, _, rest = n.partition("\n")
        if _META_HEADER_LINE.match(first_line.strip()) and rest.strip():
            n = rest
        if n == t:
            break
        t = n.lstrip()
        stripped = True
    return t.strip(), stripped


def is_substantive(text: str) -> bool:
    """After stripping, does anything worth calling a finding remain?"""
    t = (text or "").strip()
    return len(t) >= 80


def clean_advisory(text: str, iteration: int | None = None) -> tuple[str, dict]:
    """WRITE-time cleaner: strip preamble; preamble-only content degrades to the honest stub.
    Returns (content_to_store, {stripped, degraded})."""
    cleaned, stripped = strip_preamble(text)
    if not is_substantive(cleaned):
        return PREAMBLE_STUB.format(n=iteration if iteration is not None else "?"), \
            {"stripped": stripped, "degraded": True}
    return cleaned, {"stripped": stripped, "degraded": False}


def _shingles(text: str, k: int = 5) -> set:
    words = _norm(text).split()
    return {" ".join(words[i:i + k]) for i in range(max(0, len(words) - k + 1))}


def _advisory_prose(item: dict) -> str:
    parts = [item.get("investment_implications") or "", item.get("sizing_guidance") or ""]
    parts += [str(p) for p in item.get("executive_summary") or []]
    parts.append(item.get("summary") or "")
    return " ".join(parts)


def _is_advisory(item: dict) -> bool:
    return bool(item.get("investment_implications") or item.get("ticker_recommendations"))


def _known_company_blob(item: dict) -> str:
    bits = []
    for t in item.get("ticker_recommendations") or []:
        for k in ("company", "sector", "industry"):
            v = t.get(k) or (t.get("identity") or {}).get(k)
            if v:
                bits.append(str(v))
    bits.append(item.get("title") or "")
    return " ".join(bits)


def lint_item(item: dict, known_symbols: set[str]) -> list[str]:
    flags: list[str] = []
    prose = _advisory_prose(item)
    advisory = _is_advisory(item)

    if VAGUE_DATE_RE.search(prose):
        flags.append("undated_claim")

    # WS-C (v3): conversational preamble stored as findings ("Okay, here's your updated
    # advisory…") — every LLM-derived writer must strip at write; this flags any that slip.
    if prose:
        _, _had_preamble = strip_preamble(prose)
        if _had_preamble:
            flags.append("preamble_leak")

    if advisory:
        # Engine Room v1 (WS-3): generator-side universe guard supersedes the post-hoc
        # off-universe check — the writer already resolved and DISCLOSED every entity,
        # so re-flagging here would double-punish a brief that is honest about its names.
        guarded = isinstance(item.get("universe_guard"), dict)
        item_syms = {str(t.get("symbol") or "").upper()
                     for t in item.get("ticker_recommendations") or []}
        if item.get("symbol"):
            item_syms.add(str(item["symbol"]).upper())
        blob = _known_company_blob(item)
        off = False
        if not guarded:
            for m in CORP_NAME_RE.finditer(prose):
                name = m.group(1)
                if name and name not in blob:
                    off = True
                    break
            if not off:
                # ticker-like tokens in the *implications* only (news quotes allowed elsewhere)
                impl = item.get("investment_implications") or ""
                for tok in TICKERISH_RE.findall(impl):
                    if tok not in CAPS_ALLOW and tok not in known_symbols and tok not in item_syms:
                        off = True
                        break
        if off:
            flags.append("off_universe_mention")

        if not (item.get("sources") or item.get("source_count")):
            flags.append("unsourced_advisory")

        directional = DIRECTIONAL_RE.search(
            (item.get("investment_implications") or "")
            + " " + ((item.get("next_action") or {}).get("label") or "" if isinstance(item.get("next_action"), dict) else "")
        )
        if directional:
            counter = item.get("bear_case")
            if not counter and item.get("score_divergence"):
                d = item["score_divergence"]
                counter = (f"Hermes composite {d.get('hermes_composite')} disagrees with "
                           f"RI tier {d.get('ri_tier')} — treat conviction as contested.")
                item["counter_view"] = counter
            elif counter:
                item.setdefault("counter_view", counter)
            if not counter:
                flags.append("no_counter_view")
    return flags


def lint_feed(items: list[dict], *, known_symbols: set[str]) -> dict:
    """Mutates items in place: quality_flags + Tier-A cap. Returns flag counts."""
    counts: dict[str, int] = {}
    for it in items:
        fl = lint_item(it, known_symbols)
        if fl:
            it["quality_flags"] = fl
            if (it.get("quality_tier") or "").upper() == "A":
                it["quality_tier"] = "B"  # flagged items cap below Tier A
            for f in fl:
                counts[f] = counts.get(f, 0) + 1

    # Near-duplicate pass (older one flagged + deprioritized)
    shingled = [(it, _shingles(_advisory_prose(it))) for it in items
                if len(_advisory_prose(it)) > 200]
    for i in range(len(shingled)):
        for j in range(i + 1, len(shingled)):
            a, sa = shingled[i]
            b, sb = shingled[j]
            if not sa or not sb:
                continue
            inter = len(sa & sb)
            if inter and inter / min(len(sa), len(sb)) >= 0.8:
                older = a if str(a.get("created_at") or "") <= str(b.get("created_at") or "") else b
                newer = b if older is a else a
                tag = f"duplicate_of:{newer.get('id')}"
                fl = older.setdefault("quality_flags", [])
                if not any(x.startswith("duplicate_of:") for x in fl):
                    fl.append(tag)
                    counts["duplicate"] = counts.get("duplicate", 0) + 1
    return counts


def known_symbol_universe(db_query) -> set[str]:
    syms: set[str] = set()
    try:
        from lib.research_intelligence import holdings_symbols
        syms |= {s.upper() for s in holdings_symbols()}
    except Exception:
        pass
    try:
        rows = db_query("SELECT DISTINCT upper(symbol) AS s FROM watchlist_items WHERE symbol IS NOT NULL") or []
        syms |= {r["s"] for r in rows if r.get("s")}
    except Exception:
        pass
    return syms


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except Exception:
        pass
    from db_adapter import _execute
    def dbq(sql, params=None, fetch="all"):
        return _execute(sql, params, fetch=fetch)
    from lib.research_intelligence import build_feed
    feed = build_feed(db_query=dbq, limit=50)
    items = feed.get("items") or []
    counts = lint_feed(items, known_symbols=known_symbol_universe(dbq))
    flagged = [i for i in items if i.get("quality_flags")]
    print(f"[qa-lint] {len(items)} briefs → {len(flagged)} flagged · counts: {counts}")
    for i in flagged[:12]:
        print(f"  {str(i.get('symbol') or '—'):6} {', '.join(i['quality_flags']):40} {str(i.get('title'))[:60]}")
    if args.json:
        print(json.dumps(counts, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
