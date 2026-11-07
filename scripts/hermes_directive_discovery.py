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

  python3 scripts/hermes_directive_discovery.py [--apply] [--dry-run] [--limit-per-directive N]

Refactor wave 2 (cron -> n8n, 2026-10-10; cron:L448 --apply):
- ``--dry-run`` wins over ``--apply`` (no flag is still a dry run) and runs on a READ ONLY session, so
  the staging INSERT/commit is refused at the server even if reached; the report is the same JSON with
  ``mode: dry_run``. No receipt.
- A real ``--apply`` run writes data/runtime/hermes_directive_discovery_last.json (LaneRunReceipt@v1,
  ok_at only on success); a DB error exits non-zero. Staging nothing is a finding, not a failure.
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
    # cond: literal ILIKE fragments, one per term (terms are params); the window is the module constant
    cur.execute(  # nosemgrep: tq-py-sql-fstring -- literal fragments + module constant; values are params
        f"""SELECT symbol, topic, thesis, confidence_score, created_at
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
    cur.execute(  # nosemgrep: tq-py-sql-fstring -- cond2 is literal ILIKE fragments; terms are params
        f"""SELECT display_name, catalyst, sector
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


def _empty_reason(report):
    """Why this run staged nothing. A bare ``staged: 0`` is the receipt saying OK about nothing.

    Until 2026-11-07 the receipt carried only the counts, so a zero run could only be reported as
    "the receipt does not say why" (lib/run_quality.py). "no_new_input" is the reviewed idle token
    from config/run_quality_idle_reasons.json — used only when every match really was already
    pending/surfaced, which is nothing new to stage. A zero caused by configuration (no directive,
    hermes disabled, every directive stale) or by no match at all is NOT idle: a sentence is
    returned instead, so the lane keeps its EMPTY grade and now names the cause.
    """
    trend = report.get("trend_directives") or 0
    disabled = report.get("hermes_disabled") or 0
    stale = report.get("skipped_stale") or 0
    matched = report.get("matched") or 0
    pending = report.get("already_pending") or 0
    over_cap = report.get("over_cap") or 0
    if trend == 0:
        return "no active trend directives exist (watch_directives status='active' AND kind='trend')"
    eligible = trend - disabled - stale
    if eligible <= 0:
        return (f"all {trend} active trend directives were ineligible: {disabled} with "
                f"hermes_enabled = false, {stale} stale or removal-flagged")
    if matched == 0:
        return (f"{eligible} hermes-enabled trend directives matched nothing in the last "
                f"{RESEARCH_WINDOW_DAYS} days of hermes_research_intelligence or intelligence_entities")
    if pending + over_cap >= matched:
        return "no_new_input"      # every match was already staged/surfaced in 24 h, or beyond the cap
    return (f"{matched} matches across {eligible} directives, none staged: {pending} already pending, "
            f"{over_cap} beyond the per-directive cap")


def run(apply=False, cap=PER_DIRECTIVE_CAP):
    conn = _conn()
    if not apply:
        from lib.lane_last_receipt import enforce_readonly

        enforce_readonly(conn)  # dry run: the server refuses any write (AGENTS.md §6)
    cur = conn.cursor()
    cur.execute("SELECT id, label, spec, hermes_enabled FROM watch_directives WHERE status='active' AND kind='trend'")
    directives = cur.fetchall()
    try:
        from research_critique_pipeline import is_removal_flagged, load_critique_snapshot
        stale_ids = set((load_critique_snapshot().get("index") or {}).get("stale_directive_ids") or [])
    except Exception:
        stale_ids = set()
    report = {"mode": "apply" if apply else "dry_run", "trend_directives": len(directives),
              "hermes_disabled": 0, "staged": 0, "skipped_stale": 0, "matched": 0,
              "already_pending": 0, "over_cap": 0, "detail": []}
    for did, label, spec, hermes_enabled in directives:
        if not hermes_enabled:
            report["hermes_disabled"] += 1
            continue
        spec = spec if isinstance(spec, dict) else json.loads(spec)
        if did in stale_ids or is_removal_flagged(spec) or spec.get("composite_verdict") == "reject":
            report["skipped_stale"] += 1
            continue
        cands = _discover_for(cur, spec)
        staged_here = 0
        for sym, (thesis, strength) in list(cands.items()):
            report["matched"] += 1
            if staged_here >= cap:
                report["over_cap"] += 1
                continue
            if _already_pending(cur, did, sym):
                report["already_pending"] += 1
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
    if report["staged"] == 0:
        report["empty_reason"] = _empty_reason(report)
    if not apply:
        conn.rollback()
        report["would_write"] = {"table": "hermes_directive_hits_staging", "rows": report["staged"]}
    print(json.dumps(report, indent=2))
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("--apply", action="store_true", help="write to staging (default: dry-run)")
    ap.add_argument("--dry-run", action="store_true", help="read-only preview; wins over --apply")
    ap.add_argument("--limit-per-directive", type=int, default=PER_DIRECTIVE_CAP)
    a = ap.parse_args(argv)
    if a.dry_run:
        print(f"DRY-RUN hermes-directive-discovery: would stage up to {a.limit_per_directive} hits per directive "
              "in hermes_directive_hits_staging plus a lane receipt; inputs NOT_MEASURED")
        return 0
    apply = a.apply and not a.dry_run
    if not apply:
        run(apply=False, cap=a.limit_per_directive)
        return 0
    from lib.lane_last_receipt import now_iso, write_receipt

    started_at = now_iso()
    try:
        report = run(apply=True, cap=a.limit_per_directive)
    except Exception as exc:
        write_receipt("hermes_directive_discovery", ok=False, started_at=started_at,
                      error=f"{type(exc).__name__}: {exc}")
        write_receipt("hermes-directive-discovery", ok=False, exit_code=1, started_at=started_at,
                      error=f"{type(exc).__name__}: {exc}")
        raise
    write_receipt("hermes-directive-discovery", ok=True, exit_code=0, started_at=started_at,
                  summary=_receipt_summary(report))
    write_receipt("hermes_directive_discovery", ok=True, started_at=started_at,
                  summary=_receipt_summary(report))
    return 0


def _receipt_summary(report):
    """The counters that explain the count, plus the reason when the count is zero.

    "matched" rather than "candidates" on purpose: run_quality reads summary count keys in
    COUNT_KEYS order and ``candidates`` / ``total`` would shadow ``staged`` as this lane's output.
    """
    keys = ("trend_directives", "hermes_disabled", "staged", "skipped_stale", "matched",
            "already_pending", "over_cap", "empty_reason")
    return {k: report[k] for k in keys if k in report}


if __name__ == "__main__":
    sys.exit(main())
