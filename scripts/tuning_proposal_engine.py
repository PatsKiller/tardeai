#!/usr/bin/env python3
"""tuning_proposal_engine.py — Defense v9 WS-D: proposals, NEVER adjustments.

Nightly after outcomes reconcile. May PROPOSE a config change only when evidence
clears pre-set bars (min-n≥20 evaluable, bounded ±20% of current — hard). The
engine NEVER writes config; a qualifying proposal renders in Governance with its
full evidence table attached (no table, no card) and expires in 14d unactioned.
All dispositions logged — the operator's judgment is on the record too.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

BARS = {"min_n": 20, "min_effect_pct": 60, "max_change_pct": 20}


def propose(cur, *, proposal_key, config_path, current, proposed, evidence: dict) -> dict:
    """The ONLY entry — bars enforced here, hard."""
    if evidence.get("n", 0) < BARS["min_n"]:
        return {"ok": False, "silent": True,
                "why": f"n={evidence.get('n', 0)} < {BARS['min_n']} — NOT YET PROPOSABLE"}
    try:
        cur_f, prop_f = float(current), float(proposed)
        if cur_f and abs(prop_f - cur_f) / abs(cur_f) * 100 > BARS["max_change_pct"]:
            return {"ok": False, "refused": f"proposed change exceeds ±{BARS['max_change_pct']}% bound"}
    except (TypeError, ValueError):
        return {"ok": False, "refused": "non-numeric values need operator-manual handling"}
    if not evidence.get("table"):
        return {"ok": False, "refused": "no evidence table, no card (field-guard)"}
    cur.execute("""INSERT INTO tuning_proposals (proposal_key, config_path, current_value,
                   proposed_value, evidence)
                   VALUES (%s,%s,%s,%s,%s) ON CONFLICT (proposal_key) DO NOTHING""",
                (proposal_key, config_path, str(current), str(proposed), json.dumps(evidence)))
    return {"ok": True}


def nightly(cur) -> dict:
    """Scan candidate tunings; today's thin data → zero proposals is CORRECT."""
    import defense_adjudication as adj
    adj.ensure_tables(cur)
    cur.connection.commit()
    results = []
    # candidate: GG EXTENDED threshold vs mean-reversion — needs exit_advisory_outcomes
    cur.execute("SELECT count(*) FROM exit_advisory_outcomes")
    n = cur.fetchone()[0]
    results.append({"candidate": "gg_extended_threshold",
                    "n": n, "status": f"n={n} < {BARS['min_n']} — silent" if n < BARS["min_n"] else "evaluable"})
    # candidate: trim-fraction factor base vs round-trip outcomes
    cur.execute("SELECT count(*) FROM round_trip_outcomes")
    n2 = cur.fetchone()[0]
    results.append({"candidate": "trim_factor_base",
                    "n": n2, "status": f"n={n2} < {BARS['min_n']} — silent" if n2 < BARS["min_n"] else "evaluable"})
    cur.execute("UPDATE tuning_proposals SET status='expired' WHERE status='open' AND expires_at < now()")
    return {"candidates": results, "proposals_open":
            (cur.execute("SELECT count(*) FROM tuning_proposals WHERE status='open'"), cur.fetchone()[0])[1]}


if __name__ == "__main__":
    from db_adapter import _get_conn
    c = _get_conn()
    print(json.dumps(nightly(c.cursor()), indent=1))
    c.commit()
