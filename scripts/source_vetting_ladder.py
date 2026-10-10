#!/usr/bin/env python3
"""source_vetting_ladder.py — Gate 4 of Hermes source maturity. Guarded discovery→vetting ladder.

Reads data/runtime/source_maturity_latest.json and:
  1. Registers any maturity-scored source NOT in research_sources as a CANDIDATE (active=false).
  2. Persists maturity tier into research_sources.notes (JSON).
  3. Emits a vetting action queue for hermes_source_auto_approval.py (autonomous closure — no operator UI).

When invoked with --apply (cron default), chains hermes_source_auto_approval immediately after writing
the queue so eligible sources activate in the same daily maturity tick.

--dry-run reads on a READ ONLY session and returns BEFORE apply_plan() (INSERT/UPDATE research_sources,
the actions file, the policy-cache invalidation and hermes_source_auto_approval) is reachable; it
reports the registrations, tier updates and vetting actions it would make. A real run writes
data/runtime/source_vetting_ladder_last.json (LaneRunReceipt@v1; ok_at only on success) and exits 1 on
failure. data/runtime resolves through lib.persistent_state_root (AGENTS.md §9.4).
"""
import os, sys, json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def _runtime_dir() -> Path:
    try:
        from lib.persistent_state_root import resolve_durable_dir

        return resolve_durable_dir("data/runtime", ROOT)
    except Exception:  # noqa: BLE001 -- helper unavailable: the checkout path (release symlinks it)
        return ROOT / "data" / "runtime"


MATURITY = _runtime_dir() / "source_maturity_latest.json"
ACTIONS = _runtime_dir() / "source_vetting_actions_latest.json"
RECEIPT_NAME = "source_vetting_ladder"
if (ROOT / ".env").exists():  # absent in a bare checkout/test tree; the served release symlinks it
    for ln in (ROOT / ".env").read_text().splitlines():
        if "=" in ln and not ln.strip().startswith("#"):
            k, _, v = ln.partition("="); os.environ.setdefault(k.strip(), v.strip().strip("'\""))
import psycopg2


def _db():
    return psycopg2.connect(host=os.getenv("DB_HOST", "localhost"), port=os.getenv("DB_PORT", "5432"),
                            dbname=os.getenv("DB_NAME", "trade_ai"), user=os.getenv("DB_USER", "trade_ai"),
                            password=os.getenv("DB_PASSWORD"))


def plan(mat, existing):
    """Pure: what the ladder would write. `existing` = {source_name: {"active", "notes"}}."""
    inserts, updates, actions = [], [], []
    for s in mat:
        src, tier, score = s["source"], s["tier"], s["maturity_score"]
        note_obj = {"maturity_tier": tier, "maturity_score": score, "go_rate": s["go_rate"],
                    "outcome_proven": s["outcome_proven"], "rated_at": datetime.now(timezone.utc).isoformat()}
        if src not in existing:
            inserts.append((src, round(score / 100.0, 3), json.dumps(note_obj)))
        else:
            updates.append((json.dumps(note_obj), src))
        # operator action queue (no auto-activation/deactivation)
        is_active = existing.get(src, {}).get("active", False)
        if tier == "core" and not is_active:
            actions.append({"source": src, "action": "APPROVE_FOR_CORE_ACTIVATION", "score": score, "outcome_proven": s["outcome_proven"]})
        elif tier == "trusted" and not is_active:
            actions.append({"source": src, "action": "REVIEW_FOR_ACTIVATION", "score": score})
        elif tier == "demoted" and is_active and s["total_signals"] >= 100:
            actions.append({"source": src, "action": "REVIEW_FOR_DEACTIVATION_NOISE", "score": score, "total_signals": s["total_signals"], "go_rate": s["go_rate"]})
    return {"inserts": inserts, "updates": updates, "actions": actions}


def apply_plan(c, p):
    """The only writer. Never called by a dry run."""
    cur = c.cursor()
    for src, cred, notes in p["inserts"]:
        cur.execute("""INSERT INTO research_sources (source_type, source_name, credibility_score, active, notes, created_at)
                       VALUES ('news', %s, %s, false, %s, now()) ON CONFLICT DO NOTHING""",
                    (src, cred, notes))
    for notes, src in p["updates"]:
        cur.execute("UPDATE research_sources SET notes=%s WHERE source_name=%s", (notes, src))
    c.commit()
    ACTIONS.write_text(json.dumps({"updated_at": datetime.now(timezone.utc).isoformat(), "actions": p["actions"]}, indent=2))
    try:
        import hermes_source_policy as hsp
        hsp.invalidate_cache()
    except Exception:
        pass
    auto_result = None
    if p["actions"]:
        try:
            sys.path.insert(0, str(ROOT / "scripts"))
            from hermes_source_auto_approval import run_auto_approval
            auto_result = run_auto_approval(apply=True, max_actions=15, use_llm=True)
        except Exception as e:
            auto_result = {"error": str(e)[:120]}
    return auto_result


def run(dry_run=False, maturity=None):
    """`maturity`: an in-memory source_maturity document (the chain's dry run passes the one it just
    computed, since a dry source_maturity writes no file); default reads MATURITY."""
    mat = (maturity if maturity is not None else json.loads(MATURITY.read_text())).get("sources", [])
    c = _db()
    try:
        if dry_run:
            c.set_session(readonly=True)
        cur = c.cursor()
        cur.execute("SELECT source_name, active, COALESCE(notes,'') FROM research_sources")
        existing = {r[0]: {"active": r[1], "notes": r[2]} for r in cur.fetchall()}
        p = plan(mat, existing)
        auto_result = None if dry_run else apply_plan(c, p)
    finally:
        c.close()
    actions = p["actions"]
    report = {"registered_new_candidates": len(p["inserts"]), "tier_updates": len(p["updates"]),
              "vetting_actions": len(actions), "action_sample": actions[:8],
              "auto_approval": auto_result}
    if dry_run:
        report.update(dry_run=True, would_write=[str(ACTIONS)],
                      would_run_auto_approval=bool(actions))
    print(json.dumps(report, indent=2, default=str))
    return report


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--dry-run" in argv:
        run(dry_run=True)
        return 0
    from lib.lane_last_receipt import now_iso, write_receipt

    started = now_iso()
    try:
        rep = run()
    except Exception as exc:  # noqa: BLE001 -- recorded in the receipt, then a non-zero exit
        write_receipt(RECEIPT_NAME, ok=False, error=f"{type(exc).__name__}: {exc}", started_at=started)
        print(f"source_vetting_ladder FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    write_receipt(RECEIPT_NAME, ok=True, started_at=started,
                  summary={k: rep[k] for k in ("registered_new_candidates", "tier_updates", "vetting_actions")})
    return 0


if __name__ == "__main__":
    sys.exit(main())
