#!/usr/bin/env python3
"""
news_to_catalyst.py — Process unprocessed news_articles into catalyst_events.

Loads news_articles where no linked catalyst_event exists (matched by title/symbol),
classifies catalyst_type via keyword matching, scores using catalyst_type_weights
from DB, and creates catalyst_events rows.

CLI: python3 scripts/news_to_catalyst.py [--json]
"""
import json, os, sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"

# ── Catalyst keyword map ─────────────────────────────────────────────────────
# Each catalyst_type maps to keywords found in headlines/summaries.
CATALYST_KEYWORDS = {
    "earnings_beat":      ["beat expectations", "beats estimate", "tops estimate", "earnings beat",
                           "revenue beat", "profit beat", "exceeds expectations", "blowout quarter"],
    "earnings_miss":      ["misses estimate", "earnings miss", "revenue miss", "disappoints",
                           "falls short", "below expectations", "profit miss"],
    "guidance_raise":     ["raises guidance", "raises outlook", "ups forecast", "boosts guidance",
                           "raises full-year", "increases forecast"],
    "guidance_lower":     ["lowers guidance", "cuts outlook", "reduces forecast", "warns on",
                           "lowers full-year", "disappointing outlook"],
    "contract_win":       ["wins contract", "awarded contract", "new partnership", "strategic alliance",
                           "major deal", "billion-dollar contract", "new agreement",
                           "design review", "program milestone", "concludes design"],
    "fda_approval":       ["fda approval", "fda clears", "fda grants", "regulatory approval",
                           "drug approved", "clearance granted"],
    "merger_acquisition": ["acquisition", "merger", "takeover", "buyout", "acquires",
                           "to acquire", "deal to buy", "merge with"],
    "insider_buy":        ["insider buy", "insider purchase", "director buys", "ceo buys",
                           "officer purchases", "insider buying"],
    "analyst_upgrade":    ["upgrade", "price target raised", "price target increase",
                           "initiates with buy", "outperform"],
    "short_squeeze":      ["short squeeze", "short interest", "heavily shorted", "days to cover"],
    "geopolitical":       ["tariff", "sanctions", "trade war", "geopolitical", "embargo",
                           "trade deal", "trade agreement"],
    "dividend_increase":  ["dividend increase", "dividend hike", "raises dividend",
                           "dividend boost", "special dividend"],
    "dividend_cut":       ["dividend cut", "suspends dividend", "eliminates dividend",
                           "dividend reduction", "dividend slash"],
    "stock_split":        ["stock split", "forward split", "reverse split"],
    "buyback":            ["buyback", "share repurchase", "repurchase program",
                           "buy back shares"],
    "ceo_change":         ["ceo change", "new ceo", "ceo resigns", "ceo steps down",
                           "executive shakeup", "names new chief"],
    "sector_rotation":    ["sector rotation", "money flowing into", "rotation out of",
                           "sector shift"],
}


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="):
            pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def _classify(title: str, summary: str) -> str:
    """Return the best catalyst_type for a headline+summary, or 'other'."""
    text = f"{title} {summary or ''}".lower()
    for ctype, keywords in CATALYST_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                return ctype
    return "other"


# Hermes-bridged (and similar) titles carry an explicit "<category>: SYMBOL" prefix (e.g. "earnings: NRIX",
# "news_momentum: QTEX"). These bare categories don't match the directional keyword phrases above, so they
# used to fall through to 'other'/0.3 (flat impact 3.0). Map the prefix to a typed, NON-directional category
# + a moderate in-code weight (no schema change; no beat/miss or upgrade/downgrade assumption injected).
HERMES_PREFIX_WEIGHTS = {
    "regulatory": 0.75, "fda": 0.85, "merger": 0.75, "contract": 0.70, "partnership": 0.65,
    "guidance": 0.65, "earnings": 0.60, "dividend": 0.55, "insider": 0.55, "buyback": 0.50,
    "analyst": 0.50, "product": 0.50, "news_momentum": 0.40, "sentiment": 0.35,
}


def _prefix_type(title: str):
    """If the title is a bare '<category>: SYMBOL' Hermes-style catalyst, return (category, weight); else (None,None)."""
    if title and ":" in title:
        pfx = title.split(":", 1)[0].strip().lower().replace(" ", "_")
        if pfx in HERMES_PREFIX_WEIGHTS:
            return pfx, HERMES_PREFIX_WEIGHTS[pfx]
    return None, None


def _severity_from_weight(weight: float) -> str:
    if weight >= 0.85:
        return "high"
    if weight >= 0.55:
        return "medium"
    return "low"


def run(as_json: bool = False, *, single_symbol: str | None = None):
    conn = _get_conn()
    cur = conn.cursor()

    # Load catalyst_type_weights from DB
    cur.execute("SELECT catalyst_type, base_weight FROM catalyst_type_weights")
    weights = {row[0]: float(row[1]) for row in cur.fetchall()}

    sym_filter = ""
    params: list = []
    if single_symbol:
        sym_filter = " AND upper(n.symbol) = %s"
        params.append(single_symbol.upper().strip())

    # Find news articles with no linked catalyst event (by matching symbol + title)
    cur.execute(f"""
        SELECT n.id, n.symbol, n.strategy_type, n.title, n.summary,
               n.source, n.source_url, n.published_at
        FROM news_articles n
        LEFT JOIN catalyst_events ce
            ON ce.symbol = n.symbol AND ce.headline = n.title
        WHERE ce.id IS NULL{sym_filter}
        ORDER BY n.published_at DESC NULLS LAST
        LIMIT {50 if single_symbol else 500}
    """, params)
    rows = cur.fetchall()

    # World-class hybrid classifier (deterministic + local-LLM residual, outcome-calibrated). LLM is budgeted
    # per run so the 10-min cron stays safe; deterministic handles the bulk, LLM only the hardest residual.
    try:
        import sys as _sysc
        _sysc.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from catalyst_classifier import classify as _cc
    except Exception:
        _cc = None
    LLM_BUDGET = int(os.environ.get("CATALYST_LLM_BUDGET", "25"))
    # E1/E2: research-directive slugs and non-universe tokens must never mint
    # catalyst_events rows (and therefore never reach identity resolution).
    try:
        from lib.hermes_discovery.symbol_validation import (
            gate_catalyst_symbol,
            is_research_directive_slug,
        )
    except Exception:
        try:
            from hermes_discovery.symbol_validation import (  # type: ignore
                gate_catalyst_symbol,
                is_research_directive_slug,
            )
        except Exception:
            gate_catalyst_symbol = None  # type: ignore
            is_research_directive_slug = None  # type: ignore

    created = []
    skipped = {"research_directive_slug": 0, "not_in_ticker_universe": 0}
    for nid, symbol, strategy_type, title, summary, source, source_url, published_at in rows:
        # Filter BEFORE classify/LLM spend — junk must not reach identity later.
        if is_research_directive_slug is not None and is_research_directive_slug(symbol):
            skipped["research_directive_slug"] += 1
            continue
        if gate_catalyst_symbol is not None:
            ok, reason = gate_catalyst_symbol(symbol)
            if not ok:
                skipped["not_in_ticker_universe"] += 1
                continue

        if _cc:
            cls = _cc(title, summary, symbol, source=source, allow_llm=(LLM_BUDGET > 0))
            if cls.get("method") == "llm":
                LLM_BUDGET -= 1
            ctype, severity = cls["catalyst_type"], cls["severity"]
            confidence, impact = cls["confidence"], cls["impact_score"]
            payload = {"news_article_id": nid, "classifier": cls["method"], "direction": cls["direction"],
                       "confidence": confidence, "calibration_mult": cls.get("calibration_mult", 1.0),
                       "rationale": cls.get("rationale", "")}
        else:  # fallback to legacy prefix/keyword if module import fails
            ptype, pweight = _prefix_type(title)
            ctype, weight = (ptype, pweight) if ptype else (_classify(title, summary), weights.get(_classify(title, summary), 0.3))
            severity, confidence, impact = _severity_from_weight(weight), round(weight, 2), round(weight * 10, 1)
            payload = {"news_article_id": nid, "classifier": "legacy"}

        cur.execute("""
            INSERT INTO catalyst_events
                (symbol, strategy_type, catalyst_type, headline, description,
                 severity, confidence, impact_score, source, source_url, published_at,
                 raw_payload)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (symbol, headline) DO NOTHING
            RETURNING id
        """, (
            symbol, strategy_type, ctype, title, summary,
            severity, confidence, impact,
            source or "news_to_catalyst", source_url, published_at,
            json.dumps(payload)
        ))
        _row = cur.fetchone()
        # Commit per article: the next iteration's LLM classification can run 60s+, and an
        # open transaction idling through it is killed at the 120s idle-in-transaction
        # timeout — losing every insert in the batch (2026-07-04 audit, residual offender).
        conn.commit()
        if _row is None:
            continue  # (symbol, headline) already present (race with news_ingestion inline) — skip
        new_id = _row[0]
        created.append({
            "catalyst_id": new_id, "news_id": nid, "symbol": symbol,
            "catalyst_type": ctype, "severity": severity, "impact_score": impact,
        })

    conn.commit()
    cur.close()
    conn.close()

    if as_json:
        print(json.dumps({
            "created": len(created),
            "skipped": skipped,
            "catalysts": created,
        }, default=str))
    else:
        print(f"[news_to_catalyst] Created {len(created)} catalyst events from unprocessed news.")
        print(f"[news_to_catalyst] Skipped research_directive_slug={skipped['research_directive_slug']} "
              f"not_in_ticker_universe={skipped['not_in_ticker_universe']}")
        for c in created[:20]:
            print(f"  {c['symbol']:>8} | {c['catalyst_type']:<20} | sev={c['severity']:<6} | score={c['impact_score']}")
        if len(created) > 20:
            print(f"  ... and {len(created) - 20} more")


if __name__ == "__main__":
    _sym = None
    for i, arg in enumerate(sys.argv):
        if arg == "--symbol" and i + 1 < len(sys.argv):
            _sym = sys.argv[i + 1]
            break
    run(as_json="--json" in sys.argv, single_symbol=_sym)
