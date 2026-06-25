#!/usr/bin/env python3
"""source_vetting_ladder.py — Gate 4 of Hermes source maturity. Guarded discovery→vetting ladder.

Reads data/runtime/source_maturity_latest.json and:
  1. Registers any maturity-scored source NOT in research_sources as a CANDIDATE (active=false).
  2. Persists maturity tier into research_sources.notes (JSON).
  3. Emits a vetting action queue for hermes_source_auto_approval.py (autonomous closure — no operator UI).

When invoked with --apply (cron default), chains hermes_source_auto_approval immediately after writing
the queue so eligible sources activate in the same daily maturity tick.
"""
import os, sys, json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MATURITY = ROOT / "data" / "runtime" / "source_maturity_latest.json"
ACTIONS = ROOT / "data" / "runtime" / "source_vetting_actions_latest.json"
for ln in (ROOT / ".env").read_text().splitlines():
    if "=" in ln and not ln.strip().startswith("#"):
        k, _, v = ln.partition("="); os.environ.setdefault(k.strip(), v.strip().strip("'\""))
import psycopg2


def _db():
    return psycopg2.connect(host=os.getenv("DB_HOST", "localhost"), port=os.getenv("DB_PORT", "5432"),
                            dbname=os.getenv("DB_NAME", "trade_ai"), user=os.getenv("DB_USER", "trade_ai"),
                            password=os.getenv("DB_PASSWORD"))


def main():
    dry = "--dry-run" in sys.argv
    mat = json.loads(MATURITY.read_text()).get("sources", [])
    c = _db(); cur = c.cursor()
    cur.execute("SELECT source_name, active, COALESCE(notes,'') FROM research_sources")
    existing = {r[0]: {"active": r[1], "notes": r[2]} for r in cur.fetchall()}

    registered, tiered, actions = 0, 0, []
    for s in mat:
        src, tier, score = s["source"], s["tier"], s["maturity_score"]
        note_obj = {"maturity_tier": tier, "maturity_score": score, "go_rate": s["go_rate"],
                    "outcome_proven": s["outcome_proven"], "rated_at": datetime.now(timezone.utc).isoformat()}
        if src not in existing:
            if not dry:
                cur.execute("""INSERT INTO research_sources (source_type, source_name, credibility_score, active, notes, created_at)
                               VALUES ('news', %s, %s, false, %s, now()) ON CONFLICT DO NOTHING""",
                            (src, round(score / 100.0, 3), json.dumps(note_obj)))
            registered += 1
        else:
            if not dry:
                cur.execute("UPDATE research_sources SET notes=%s WHERE source_name=%s", (json.dumps(note_obj), src))
            tiered += 1
        # operator action queue (no auto-activation/deactivation)
        is_active = existing.get(src, {}).get("active", False)
        if tier == "core" and not is_active:
            actions.append({"source": src, "action": "APPROVE_FOR_CORE_ACTIVATION", "score": score, "outcome_proven": s["outcome_proven"]})
        elif tier == "trusted" and not is_active:
            actions.append({"source": src, "action": "REVIEW_FOR_ACTIVATION", "score": score})
        elif tier == "demoted" and is_active and s["total_signals"] >= 100:
            actions.append({"source": src, "action": "REVIEW_FOR_DEACTIVATION_NOISE", "score": score, "total_signals": s["total_signals"], "go_rate": s["go_rate"]})
    if not dry:
        c.commit()
        ACTIONS.write_text(json.dumps({"updated_at": datetime.now(timezone.utc).isoformat(), "actions": actions}, indent=2))
        try:
            import hermes_source_policy as hsp
            hsp.invalidate_cache()
        except Exception:
            pass
    auto_result = None
    if not dry and actions:
        try:
            sys.path.insert(0, str(ROOT / "scripts"))
            from hermes_source_auto_approval import run_auto_approval
            auto_result = run_auto_approval(apply=True, max_actions=15, use_llm=True)
        except Exception as e:
            auto_result = {"error": str(e)[:120]}
    c.close()
    print(json.dumps({"registered_new_candidates": registered, "tier_updates": tiered,
                      "vetting_actions": len(actions), "action_sample": actions[:8],
                      "auto_approval": auto_result}, indent=2, default=str))


if __name__ == "__main__":
    main()
