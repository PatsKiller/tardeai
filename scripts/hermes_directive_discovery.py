#!/usr/bin/env python3
"""hermes_directive_discovery.py — the Hermes side of Watch Directives (the producer).

For each ACTIVE *trend* directive, match its keywords against Hermes's existing research
(hermes_research_intelligence: symbol+topic/summary/thesis/tags) + intelligence_entities
(description/catalyst/sector/industry/tags), and stage candidate symbols into
hermes_directive_hits_staging. The app-role drain (watch_directives_service --apply) then runs each
through the governed promotion engine (tier+divergence governor → classify Bucket-2/3 → watchpool).

FIREWALL: this writes ONLY the hermes staging table (the Hermes lane) — never watch_directives,
watch_directive_hits, watchlist_items, or strategy_watchpool. It SURFACES Hermes research as proposed
leads; promotion stays inside promote_directive_lead. Advisory; no execution.

  python3 scripts/hermes_directive_discovery.py [--apply] [--limit-per-directive N]
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

STOP = {"the", "and", "for", "with", "from", "into", "play", "theme", "trend", "stocks", "names"}
RESEARCH_WINDOW_DAYS = 45
PER_DIRECTIVE_CAP = 15


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _terms(keywords):
    """Precise match terms: full multi-word PHRASES (e.g. 'AI datacenter', 'data center') matched as
    phrases, and distinctive single words (e.g. 'colocation', 'hyperscale'). We deliberately do NOT
    split multi-word keywords into generic components ('data', 'center', 'infrastructure') — that
    matched mutual funds / Visa / ETFs incidentally. Phrase-precise keeps Hermes leads on-theme."""
    out = []
    for kw in (keywords or []):
        kw = (kw or "").strip()
        if not kw:
            continue
        if len(kw.split()) == 1:
            if len(kw) > 3 and kw.lower() not in STOP:   # colocation, datacenter, hyperscale, semiconductor
                out.append(kw)
        else:
            out.append(kw)   # 'AI datacenter', 'data center', 'AI infrastructure' — phrase only
    return list(dict.fromkeys(out))


def _discover_for(cur, spec):
    """Return {symbol: (thesis, strength)} candidates for a trend directive's spec."""
    keywords = spec.get("keywords") or []
    seeds = [str(s).upper() for s in (spec.get("seed_symbols") or [])]
    cands = {s: ("operator seed symbol", 1.0) for s in seeds}
    terms = _terms(keywords)
    if not terms:
        return cands

    # 1) Hermes research (the authoritative Hermes lane)
    hri_text = ("(COALESCE(topic,'')||' '||COALESCE(summary,'')||' '||COALESCE(thesis,'')||' '||"
                "COALESCE(array_to_string(tags,' '),'')||' '||COALESCE(array_to_string(strategy_tags,' '),''))")
    cond = " OR ".join([f"{hri_text} ILIKE %s" for _ in terms])
    cur.execute(f"""SELECT symbol, topic, thesis, confidence_score, created_at
                    FROM hermes_research_intelligence
                    WHERE symbol IS NOT NULL AND created_at > now() - interval '{RESEARCH_WINDOW_DAYS} days'
                      AND ({cond})
                    ORDER BY created_at DESC LIMIT 60""", [f"%{t}%" for t in terms])
    for r in cur.fetchall():
        sym = (r[0] or "").upper()
        if sym and sym not in cands:
            cands[sym] = ((r[1] or r[2] or "hermes research match")[:120], float(r[3] or 0.5))

    # 2) intelligence_entities (ticker entities w/ catalyst/sector/desc keyword match)
    ie_text = ("(COALESCE(description,'')||' '||COALESCE(catalyst,'')||' '||COALESCE(sector,'')||' '||"
               "COALESCE(industry,'')||' '||COALESCE(array_to_string(tags,' '),''))")
    cond2 = " OR ".join([f"{ie_text} ILIKE %s" for _ in terms])
    cur.execute(f"""SELECT display_name, catalyst, sector
                    FROM intelligence_entities
                    WHERE display_name ~ '^[A-Z]{{1,5}}$' AND ({cond2})
                    LIMIT 40""", [f"%{t}%" for t in terms])
    for r in cur.fetchall():
        sym = (r[0] or "").upper()
        if sym and sym not in cands:
            cands[sym] = ((r[1] or f"intelligence: {r[2] or ''}").strip()[:120] or "intelligence match", 0.5)
    return cands


def _already_pending(cur, did, sym):
    cur.execute("SELECT 1 FROM hermes_directive_hits_staging WHERE directive_id=%s AND symbol=%s AND drained=false LIMIT 1", (did, sym))
    if cur.fetchone():
        return True
    cur.execute("""SELECT 1 FROM watch_directive_hits WHERE directive_id=%s AND symbol=%s
                   AND surfaced_at > now()-interval '24 hours' LIMIT 1""", (did, sym))
    return cur.fetchone() is not None


def run(apply=False, cap=PER_DIRECTIVE_CAP):
    conn = _conn(); cur = conn.cursor()
    cur.execute("SELECT id, label, spec, hermes_enabled FROM watch_directives WHERE status='active' AND kind='trend'")
    directives = cur.fetchall()
    try:
        from research_critique_pipeline import is_removal_flagged, load_critique_snapshot
        stale_ids = set((load_critique_snapshot().get("index") or {}).get("stale_directive_ids") or [])
    except Exception:
        stale_ids = set()
    report = {"trend_directives": len(directives), "staged": 0, "skipped_stale": 0, "detail": []}
    for did, label, spec, hermes_enabled in directives:
        if not hermes_enabled:
            continue
        spec = spec if isinstance(spec, dict) else json.loads(spec)
        if did in stale_ids or is_removal_flagged(spec) or spec.get("composite_verdict") == "reject":
            report["skipped_stale"] += 1
            continue
        cands = _discover_for(cur, spec)
        staged_here = 0
        for sym, (thesis, strength) in list(cands.items()):
            if staged_here >= cap:
                break
            if _already_pending(cur, did, sym):
                continue
            if apply:
                cur.execute("""INSERT INTO hermes_directive_hits_staging
                                 (directive_id, symbol, thesis, narrative_strength, source_detail)
                               VALUES (%s, %s, %s, %s, %s::jsonb)""",
                            (did, sym, thesis, strength, json.dumps({"producer": "hermes_directive_discovery",
                                                                     "keywords": spec.get("keywords")})))
            staged_here += 1
            report["staged"] += 1
            report["detail"].append({"directive": label, "symbol": sym, "thesis": thesis[:60]})
        if apply:
            conn.commit()
    print(json.dumps(report, indent=2))
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write to staging (default: dry-run)")
    ap.add_argument("--limit-per-directive", type=int, default=PER_DIRECTIVE_CAP)
    a = ap.parse_args()
    run(apply=a.apply, cap=a.limit_per_directive)


if __name__ == "__main__":
    main()
