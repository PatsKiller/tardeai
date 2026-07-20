#!/usr/bin/env python3
"""hermes_score_event_feeder.py — the event lane of Phase 1 (docs/design/HERMES_MATURITY_5_DESIGN.md §1.2).

Work happens when information changes, not when the clock ticks: fresh catalysts, news, Finviz
screener entries, directive hits, and new proposals enqueue an immediate rescore for that symbol
in hermes_score_event_queue — regardless of scope tier. An archived (S3) symbol with a fresh
event is reactivated to S1 (audited), which the old 4.1k clock sweep could never do despite
48 runs/day.

Cursorless: each run scans a window of 2x the cron cadence; the one-pending-event-per-symbol
unique index makes overlapping scans a no-op. Only symbols already in the watchlist universe
are enqueued (the scorer can't score anything else). Advisory-only; honors HERMES_DISABLED.

  python3 scripts/hermes_score_event_feeder.py            # dry-run
  python3 scripts/hermes_score_event_feeder.py --apply
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

KILL_SWITCH = PROJECT_ROOT / "data" / "runtime" / "HERMES_DISABLED"
CFG_FILE = PROJECT_ROOT / "config" / "hermes_scope_governor.yaml"

# source name -> (SQL yielding (symbol, ref) fresh within %s minutes)
SOURCE_SQL = {
    "catalyst": """SELECT DISTINCT UPPER(symbol), 'catalyst_events:' || MAX(id::text)
                   FROM catalyst_events WHERE created_at > NOW() - make_interval(mins => %s)
                   GROUP BY UPPER(symbol)""",
    "news": """SELECT DISTINCT UPPER(symbol), 'news_articles'
               FROM news_articles WHERE symbol IS NOT NULL
                 AND created_at > NOW() - make_interval(mins => %s)
               GROUP BY UPPER(symbol)""",
    # SHADOW screens must NOT feed scoring. They run purely to accumulate
    # evidence; letting their membership raise a Hermes score would give a
    # research-only list live influence, which is the whole thing shadow mode
    # exists to prevent. Gated on the screen's own proposal_eligible flag
    # (Phase 1.2, 2026-07-20) — the DB additionally CHECK-constrains a SHADOW
    # screen to proposal_eligible=false, so this cannot be bypassed by data.
    "finviz": """SELECT DISTINCT UPPER(m.symbol), 'screener:' || MAX(m.screener_id::text)
                 FROM screener_symbol_membership m
                 JOIN finviz_screeners f ON f.screener_id = m.screener_id
                 WHERE m.first_seen_in_screener_at > NOW() - make_interval(mins => %s)
                   AND f.proposal_eligible = true
                   AND f.research_mode <> 'SHADOW'
                 GROUP BY UPPER(m.symbol)""",
    # first-EVER hit for the (directive, symbol) pair only — discovery restages existing hits
    # every 30 min (bumping surfaced_at), and treating restages as events reflooded the live
    # tiers with the exact inflation Phase 1 exists to stop (274 fake events per 20-min window).
    "directive_hit": """SELECT DISTINCT UPPER(h.symbol), 'directive:' || MAX(h.directive_id::text)
                        FROM watch_directive_hits h
                        WHERE h.surfaced_at > NOW() - make_interval(mins => %s)
                          AND NOT EXISTS (
                            SELECT 1 FROM watch_directive_hits h0
                            WHERE h0.directive_id = h.directive_id
                              AND UPPER(h0.symbol) = UPPER(h.symbol)
                              AND h0.surfaced_at <= NOW() - make_interval(mins => %s))
                        GROUP BY UPPER(h.symbol)""",
    "proposal": """SELECT DISTINCT UPPER(symbol), 'proposal:' || MAX(id::text)
                   FROM paper_trade_proposals
                   WHERE created_at > NOW() - make_interval(mins => %s)
                   GROUP BY UPPER(symbol)""",
}


def _cfg():
    import yaml
    return yaml.safe_load(CFG_FILE.read_text())


def _feedback_cfg() -> dict:
    """S3 reactivation policy from outcome feedback config (conservative multi-factor)."""
    try:
        import yaml
        p = PROJECT_ROOT / "config" / "hermes_outcome_feedback.yaml"
        return (yaml.safe_load(p.read_text()) or {}).get("s3_reactivation") or {}
    except Exception:
        return {}


def _load_outcome_bus():
    try:
        sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "lib"))
        from lib.hermes_outcome_bus.bus import load_outcome_bus, governor_feedback_index
        bus = load_outcome_bus()
        return bus, governor_feedback_index(bus)
    except Exception:
        return {}, {}


def _reactivation_factors(cur, sym: str, etype: str, policy: dict, gov_idx: dict) -> tuple[int, list[str]]:
    """Count evidence factors for S3→S1. Requires min_factors (default 2) — no bare news inflation."""
    factors: list[str] = []
    primary = set(policy.get("primary_event_types") or ["catalyst", "proposal", "directive_hit"])
    low_trust = set(policy.get("low_trust_event_types") or ["news", "finviz"])

    if etype in primary:
        factors.append(f"primary_event:{etype}")
    elif etype in low_trust:
        factors.append(f"low_trust_only:{etype}")  # counts as 0.5 — needs strong second factor

    rvol_thr = float(policy.get("rvol_threshold", 3.0))
    gap_thr = float(policy.get("gap_pct_threshold", 8.0))
    try:
        cur.execute("""SELECT rvol, gap_pct FROM trade_ai_scans
                       WHERE UPPER(symbol)=%s AND run_date::date = CURRENT_DATE
                       ORDER BY rvol DESC NULLS LAST LIMIT 1""", (sym,))
        row = cur.fetchone()
        if row:
            rvol, gap = row[0], row[1]
            if rvol is not None and float(rvol) >= rvol_thr:
                factors.append(f"rvol>={rvol_thr}")
            if gap is not None and abs(float(gap)) >= gap_thr:
                factors.append(f"gap>={gap_thr}%")
    except Exception:
        pass

    comp_min = float(policy.get("composite_min", 70))
    try:
        cur.execute("""SELECT MAX(hermes_composite_score) FROM watchlist_items
                       WHERE UPPER(symbol)=%s AND status IN ('active','researched')""", (sym,))
        comp = cur.fetchone()[0]
        if comp is not None and float(comp) >= comp_min:
            factors.append(f"composite>={comp_min}")
    except Exception:
        pass

    allow_actions = set(policy.get("outcome_allowlist_actions") or ["promote_eligible"])
    fb = gov_idx.get(sym.upper()) or {}
    if str(fb.get("action") or "") in allow_actions:
        factors.append(f"outcome_bus:{fb.get('action')}")

    # Low-trust alone never sufficient: require at least one non-low-trust factor beyond the event
    if etype in low_trust and etype not in primary:
        non_event = [f for f in factors if not f.startswith("low_trust")]
        if len(non_event) < 1:
            return 0, factors

    min_f = int(policy.get("min_factors", 2))
    score = len(factors)
    if etype in low_trust and score < min_f + 1:
        score = max(0, score - 1)  # penalize low-trust paths
    return score, factors


def _s3_reactivation_eligible(cur, sym: str, etype: str, policy: dict, gov_idx: dict) -> tuple[bool, str]:
    if not policy.get("requires_multi_factor", True):
        return True, "policy_disabled"
    score, factors = _reactivation_factors(cur, sym, etype, policy, gov_idx)
    min_f = int(policy.get("min_factors", 2))
    if score >= min_f:
        return True, "|".join(factors)
    return False, f"insufficient_factors({score}<{min_f}):{','.join(factors)}"


def run(apply: bool = False) -> dict:
    if KILL_SWITCH.exists():
        out = {"ok": False, "reason": "HERMES_DISABLED kill switch present — feeder idle"}
        try:
            sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "lib"))
            from lib.hermes_scope_governor.heartbeat import FEEDER_HEARTBEAT, write_heartbeat
            write_heartbeat(FEEDER_HEARTBEAT, out)
        except Exception:
            pass
        print(json.dumps(out))
        return out
    from db_adapter import _get_conn
    cfg = _cfg()["event_feeder"]
    window = int(cfg["scan_minutes"])
    sources = list(cfg["sources"])
    conn = _get_conn()
    cur = conn.cursor()
    run_id = f"ev_{uuid.uuid4().hex[:10]}"

    cur.execute("""SELECT DISTINCT UPPER(symbol) FROM watchlist_items
                   WHERE status IN ('active','researched')""")
    universe = {r[0] for r in cur.fetchall()}

    found: dict[str, tuple[str, str]] = {}       # symbol -> (event_type, ref)
    for src in sources:
        sql = SOURCE_SQL.get(src)
        if not sql:
            continue
        cur.execute(sql, (window, window) if sql.count("%s") == 2 else (window,))
        for sym, ref in cur.fetchall():
            if sym in universe and sym not in found:
                found[sym] = (src, ref)

    policy = _feedback_cfg()
    _bus, gov_idx = _load_outcome_bus()

    enqueued = reactivated = 0
    skipped_s3 = 0
    if apply and found:
        for sym, (etype, ref) in found.items():
            cur.execute("""INSERT INTO hermes_score_event_queue (symbol, event_type, source_ref)
                           VALUES (%s,%s,%s)
                           ON CONFLICT (symbol) WHERE processed_at IS NULL DO NOTHING""",
                        (sym, etype, ref))
            enqueued += cur.rowcount
        # S3 -> S1: conservative multi-factor reactivation (prevents event-lane scope inflation)
        cur.execute("""SELECT DISTINCT UPPER(symbol) FROM watchlist_items
                       WHERE scope_tier='S3' AND UPPER(symbol) = ANY(%s)
                         AND status IN ('active','researched')""", (list(found.keys()),))
        for (sym,) in cur.fetchall():
            etype, ref = found[sym]
            ok, evidence = _s3_reactivation_eligible(cur, sym, etype, policy, gov_idx)
            if not ok:
                skipped_s3 += 1
                cur.execute("""INSERT INTO scope_governor_audit (run_id, symbol, action, from_tier, to_tier, reason)
                               VALUES (%s,%s,'skip_reactivate','S3','S3',%s)""",
                            (run_id, sym, f"event:{etype}:{evidence}"))
                continue
            cur.execute("""UPDATE watchlist_items
                           SET scope_tier='S1', trigger_source=%s, last_trigger_at=NOW(), updated_at=NOW()
                           WHERE UPPER(symbol)=%s AND status IN ('active','researched')""",
                        (f"event:{etype}", sym))
            cur.execute("""INSERT INTO scope_governor_audit (run_id, symbol, action, from_tier, to_tier, reason)
                           VALUES (%s,%s,'reactivate','S3','S1',%s)""",
                        (run_id, sym, f"event:{etype}:{ref}|{evidence}"))
            reactivated += 1
        conn.commit()

    by_type = {}
    for _s, (t, _r) in found.items():
        by_type[t] = by_type.get(t, 0) + 1
    out = {"ok": True, "apply": apply, "run_id": run_id, "window_minutes": window,
           "events_found": len(found), "by_type": by_type,
           "enqueued": enqueued, "reactivated_s3_to_s1": reactivated,
           "skipped_s3_reactivation": skipped_s3 if apply else 0,
           "s3_policy": policy.get("version", "v1"),
           "sample": [f"{s}<-{t}" for s, (t, _r) in list(found.items())[:10]],
           "ts": datetime.now(timezone.utc).isoformat()}
    try:
        sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "lib"))
        from lib.hermes_scope_governor.heartbeat import FEEDER_HEARTBEAT, write_heartbeat
        write_heartbeat(FEEDER_HEARTBEAT, out)
    except Exception:
        pass
    print(json.dumps(out, indent=2))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    run(apply=args.apply)


if __name__ == "__main__":
    main()
