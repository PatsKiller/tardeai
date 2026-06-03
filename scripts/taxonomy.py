#!/usr/bin/env python3
"""Shared canonical taxonomy — Phase 1 foundation.

Single source of truth for content categorization across TradeAI (Iris) and Hermes.
Three axes (content, sector, lifecycle); the classifier returns at most one slug per axis.
See docs/TAXONOMY_ALIGNMENT_SCOPE.md.

This module is imported by both systems:
    from taxonomy import classify, get_categories
    classify("Fed cuts rates, semis rally", symbol="NVDA")
    # -> {"content": "macro_economics", "sector": "ai_chips", "lifecycle": "accumulation"}

CLI:
    python3 scripts/taxonomy.py --seed                 # create table + load config/taxonomy.yaml
    python3 scripts/taxonomy.py --list                 # show live categories
    python3 scripts/taxonomy.py --classify "..." [--symbol NVDA]
"""
import argparse
import json
import sys
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
YAML_PATH = PROJECT_ROOT / "config" / "taxonomy.yaml"
AXES = ("content", "sector", "lifecycle")


def _conn():
    from db_adapter import get_connection
    return get_connection()


def ensure_table():
    conn = _conn(); cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS taxonomy_categories (
            id          SERIAL PRIMARY KEY,
            axis        TEXT NOT NULL,
            slug        TEXT NOT NULL,
            label       TEXT,
            parent_slug TEXT,
            owner_agent TEXT DEFAULT 'iris',
            active      BOOLEAN DEFAULT TRUE,
            created_at  TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (axis, slug)
        )""")
    conn.commit(); conn.close()


def seed():
    """Upsert categories from config/taxonomy.yaml. Idempotent; never deletes (curator owns retire)."""
    import yaml
    ensure_table()
    doc = yaml.safe_load(YAML_PATH.read_text())
    conn = _conn(); cur = conn.cursor()
    n = 0
    for axis, body in (doc.get("axes") or {}).items():
        for cat in (body.get("categories") or []):
            cur.execute("""INSERT INTO taxonomy_categories (axis, slug, label)
                           VALUES (%s,%s,%s)
                           ON CONFLICT (axis, slug) DO UPDATE SET label=EXCLUDED.label, active=TRUE""",
                        (axis, cat["slug"], cat.get("label")))
            n += 1
    conn.commit(); conn.close()
    return n


def get_categories(axis=None):
    """Return live categories as {axis: [{slug,label}]} (or a single axis list)."""
    from db_adapter import _execute
    rows = _execute("SELECT axis, slug, label FROM taxonomy_categories WHERE active=TRUE "
                    + ("AND axis=%s " if axis else "") + "ORDER BY axis, slug",
                    (axis,) if axis else None, fetch="all") or []
    out = {}
    for r in rows:
        out.setdefault(r["axis"], []).append({"slug": r["slug"], "label": r["label"]})
    return out.get(axis, []) if axis else out


# Keyword fallback for when the shared GPU LLM is saturated (503/timeout). Coarse but useful;
# the LLM path refines. Only the most unambiguous cues per axis.
_KEYWORDS = {
    "content": [
        ("dividend_income", ("dividend", "yield", "payout", "distribution")),
        ("tax_strategy", ("tax", "irmaa", "wash sale", "harvest", "roth")),
        ("retirement_planning", ("retirement", "401k", "ira", "pension")),
        ("disability_retirement", ("ssdi", "disability")),
        ("options_income", ("covered call", "option", "premium", "csp")),
        ("etf_indexing", ("etf", "index fund", "indexing")),
        ("macro_economics", ("fed", "inflation", "rate cut", "gdp", "macro", "cpi")),
        ("catalyst_news", ("earnings", "fda", "merger", "guidance", "breaking")),
        ("technical_analysis", ("rsi", "breakout", "support", "resistance", "chart")),
    ],
    "sector": [
        ("ai_chips", ("semiconductor", "chip", "gpu", "nvidia", "amd", "tsmc")),
        ("ai_datacenter", ("datacenter", "data center", "hyperscale", "cloud capacity")),
        ("defense", ("defense", "aerospace", "military", "lockheed", "missile")),
        ("energy", ("oil", "gas", "energy", "crude", "solar")),
        ("healthcare", ("healthcare", "biotech", "pharma", "drug")),
        ("financials", ("bank", "financial", "insurance")),
        ("real_estate", ("reit", "real estate")),
    ],
    "lifecycle": [
        ("roth_conversion", ("roth conversion", "roth window")),
        ("ssdi_preservation", ("ssdi", "benefit preservation", "disability income")),
        ("tax_optimization", ("tax", "harvest", "irmaa")),
        ("income_generation", ("income", "yield", "dividend", "covered call")),
        ("retirement_distribution", ("rmd", "withdrawal", "distribution")),
        ("estate_trust", ("estate", "trust", "inheritance")),
    ],
}


def _heuristic(text, valid):
    t = (text or "").lower()
    out = {a: None for a in AXES}
    for axis, rules in _KEYWORDS.items():
        for slug, kws in rules:
            if slug in valid.get(axis, set()) and any(k in t for k in kws):
                out[axis] = slug
                break
    return out


def classify_fast(text):
    """Heuristic-only classification (no LLM). For bulk backfill where calling the saturated
    shared GPU per-row is infeasible. Returns {axis: slug_or_None}."""
    cats = get_categories()
    valid = {axis: {c["slug"] for c in cats.get(axis, [])} for axis in AXES}
    return _heuristic(text, valid)


def classify(text, symbol=None):
    """Classify text into one slug per axis using the local LLM, constrained to the live set.
    Falls back to a keyword heuristic when the (shared GPU) LLM is unavailable. Returns
    {axis: slug_or_None}; never raises."""
    cats = get_categories()
    if not cats:
        return {a: None for a in AXES}
    valid = {axis: {c["slug"] for c in cats.get(axis, [])} for axis in AXES}
    menu = "\n".join(
        f"{axis}: " + ", ".join(c["slug"] for c in cats.get(axis, [])) for axis in AXES)
    prompt = (
        "You are a strict taxonomy classifier. Given the text, pick the single best slug for each "
        "axis from ONLY these allowed slugs (or null if none fit):\n" + menu +
        f"\n\nText{' about ' + symbol if symbol else ''}:\n" + (text or "")[:1500] +
        '\n\nRespond ONLY with JSON: {"content": slug_or_null, "sector": slug_or_null, "lifecycle": slug_or_null}')
    try:
        from local_llm_config import get_local_llm_base_url, get_local_llm_model
        body = json.dumps({"model": get_local_llm_model(), "prompt": prompt,
                           "stream": False, "format": "json", "options": {"temperature": 0}}).encode()
        req = urllib.request.Request(get_local_llm_base_url().rstrip("/") + "/api/generate",
                                     data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            resp = json.loads(r.read())
        parsed = json.loads(resp.get("response", "{}"))
        result = {axis: (parsed.get(axis) if parsed.get(axis) in valid[axis] else None) for axis in AXES}
        # If the LLM produced nothing usable, fill gaps from the heuristic.
        if not any(result.values()):
            return _heuristic(text, valid)
        heur = _heuristic(text, valid)
        return {axis: (result[axis] or heur[axis]) for axis in AXES}
    except Exception:
        # LLM unavailable (saturated GPU / 503 / timeout) → keyword heuristic.
        return _heuristic(text, valid)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--classify", type=str)
    ap.add_argument("--symbol", type=str)
    args = ap.parse_args()
    if args.seed:
        print(f"seeded {seed()} categories into taxonomy_categories")
    if args.list:
        for axis, cats in get_categories().items():
            print(f"{axis} ({len(cats)}): " + ", ".join(c["slug"] for c in cats))
    if args.classify:
        print(json.dumps(classify(args.classify, args.symbol), indent=1))


if __name__ == "__main__":
    main()
