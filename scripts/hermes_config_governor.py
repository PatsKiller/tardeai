#!/usr/bin/env python3
"""hermes_config_governor.py — Phase 5.1: Hermes proposes its own config changes
(docs/design/HERMES_MATURITY_5_DESIGN.md §5.1).

Two governance lanes:
  AUTO  (already live) — the clamped, audited loops: weight grafts inside ±0.02 steps
        (hermes_autonomous_self_tune), promotion thresholds inside declared rails
        (hermes_outcome_learning), source retire/reinstate on outcome yield. Each writes its
        own audit table. Nothing here re-implements those.
  PROPOSE (this script) — when the evidence says a RAIL ITSELF is wrong (a cap, a budget, a
        clamp), Hermes may not touch it. It files a row in config_change_proposals with
        evidence and a rollback plan, and the operator approves via the existing surface.

Detectors (nightly):
  scope_cap_pressure      cap-overflow demotes averaging high while shed names carry real
                          composite scores → propose raising total_cap
  scope_underfill         live universe persistently far below cap → propose lowering it
  weight_clamp_pressure   outcome calibration persistently wants moves ≥2x the graft clamp
                          → propose a one-time operator graft
  promotion_hard_floor    a research_type with a big sample and dire precision → propose
                          disabling its auto-promotion entirely (beyond the auto rail's 0.75)

One pending proposal per target_key at a time. Zero LLM. Advisory-only; honors HERMES_DISABLED.

  python3 scripts/hermes_config_governor.py            # dry-run
  python3 scripts/hermes_config_governor.py --apply    # file proposals
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


def _conn():
    from db_adapter import _get_conn

    return _get_conn()


def _pending(cur, target_key):
    cur.execute(
        """SELECT 1 FROM config_change_proposals
                   WHERE domain='hermes' AND target_key=%s AND status='pending'""",
        (target_key,),
    )
    return cur.fetchone() is not None


def _diff(current: dict, proposed: dict) -> dict:
    """config_change_proposals.diff is jsonb. Until 2026-10-10 this script passed the TEXT
    '<current> -> <proposed>' and every --apply run died on InvalidTextRepresentation (13/13 runs
    in logs/hermes_config_governor.log), so nothing was ever filed. Same shape as
    learning_governance.create_config_change_proposal: added / changed / removed."""
    return {
        "added": {k: v for k, v in proposed.items() if k not in current},
        "changed": {
            k: {"old": current.get(k), "new": v} for k, v in proposed.items() if k in current and current[k] != v
        },
        "removed": {k: v for k, v in current.items() if k not in proposed},
    }


def _proposal_id() -> str:
    # proposal_id is NOT NULL UNIQUE with no default; the old INSERT never reached it because the
    # diff cast failed first.
    return f"HCG_{datetime.now(timezone.utc):%Y%m%d%H%M%S}_{uuid.uuid4().hex[:8]}"


def _propose(cur, apply, *, target_key, target_path, current, proposed, reason, evidence, risk, rollback):
    if _pending(cur, target_key):
        return {"target_key": target_key, "status": "already_pending"}
    if apply:
        cur.execute(
            """INSERT INTO config_change_proposals
                       (proposal_id, domain, target_key, target_path, change_type, current_config,
                        proposed_config, diff, reason, evidence, risk_assessment, rollback_plan,
                        status, created_at, updated_at)
                       VALUES (%s, 'hermes', %s, %s, 'update', %s::jsonb, %s::jsonb, %s::jsonb, %s,
                               %s::jsonb, %s, %s, 'pending', NOW(), NOW())""",
            (
                _proposal_id(),
                target_key,
                target_path,
                json.dumps(current),
                json.dumps(proposed),
                json.dumps(_diff(current, proposed), default=str),
                reason,
                json.dumps(evidence, default=str),
                risk,
                rollback,
            ),
        )
    return {"target_key": target_key, "status": "proposed" if apply else "would_propose", "reason": reason}


def detect(cur, apply) -> list:
    import yaml

    out = []
    scope_cfg = yaml.safe_load((PROJECT_ROOT / "config" / "hermes_scope_governor.yaml").read_text())
    cap = int(scope_cfg["total_cap"])

    # ── scope cap pressure / underfill ────────────────────────────────────────
    cur.execute("""SELECT COALESCE(count(*),0), COALESCE(count(*) FILTER (
                     WHERE symbol IN (SELECT UPPER(symbol) FROM watchlist_items
                                      WHERE hermes_composite_score >= 60)), 0)
                   FROM scope_governor_audit
                   WHERE action='demote' AND reason LIKE 'total_cap%%'
                     AND created_at > NOW() - interval '7 days'""")
    shed, shed_scored = cur.fetchone()
    shed_per_day = (shed or 0) / 7.0
    if shed_per_day > 100 and (shed_scored or 0) > 0.3 * (shed or 1):
        out.append(
            _propose(
                cur,
                apply,
                target_key="hermes_scope_governor.total_cap",
                target_path="config/hermes_scope_governor.yaml:total_cap",
                current={"total_cap": cap},
                proposed={"total_cap": cap + 100},
                reason=f"cap sheds {shed_per_day:.0f} symbols/day, {shed_scored} of {shed} carried composite>=60 — real signal is being truncated",
                evidence={"shed_7d": shed, "shed_scored_7d": shed_scored, "cap": cap},
                risk="larger universe = more scoring writes (~+13%/100 symbols); no execution surface",
                rollback=f"set total_cap back to {cap} in config/hermes_scope_governor.yaml",
            )
        )
    cur.execute("""SELECT count(DISTINCT UPPER(symbol)) FROM watchlist_items
                   WHERE scope_tier IN ('S0','S1','S2') AND status IN ('active','researched')""")
    live = cur.fetchone()[0] or 0
    if live < cap * 0.5:
        out.append(
            _propose(
                cur,
                apply,
                target_key="hermes_scope_governor.total_cap_underfill",
                target_path="config/hermes_scope_governor.yaml:total_cap",
                current={"total_cap": cap},
                proposed={"total_cap": max(400, int(live * 1.3))},
                reason=f"live universe {live} is <50% of cap {cap} — budget larger than the trigger flow",
                evidence={"live": live, "cap": cap},
                risk="none material; cap is an upper bound",
                rollback=f"set total_cap back to {cap}",
            )
        )

    # ── weight clamp pressure ────────────────────────────────────────────────
    cur.execute("""SELECT factor, count(DISTINCT created_at::date) days,
                          avg(ABS(suggested_weight - current_weight)) avg_gap
                   FROM hermes_weight_calibration
                   WHERE rationale LIKE 'OUTCOME_LEDGER|eligible=1%%'
                     AND created_at > NOW() - interval '14 days'
                   GROUP BY factor
                   HAVING count(DISTINCT created_at::date) >= 7
                      AND avg(ABS(suggested_weight - current_weight)) >= 0.04""")
    for factor, days, gap in cur.fetchall():
        out.append(
            _propose(
                cur,
                apply,
                target_key=f"hermes_weights.clamp_pressure.{factor}",
                target_path="config/hermes_score_weights.yaml:weights." + factor,
                current={"note": "live weight lags outcome suggestion by >= 2x clamp"},
                proposed={"action": f"operator one-time graft toward suggestion for {factor}"},
                reason=f"outcome calibration wanted |Δ|≈{float(gap):.3f} on {factor} for {days} days — the ±0.02 clamp is the binding constraint",
                evidence={"factor": factor, "eligible_days": days, "avg_gap": float(gap)},
                risk="weight moves affect advisory ranking only",
                rollback="revert config/hermes_score_weights.yaml to prior version (versioned + audited)",
            )
        )

    # ── promotion hard floor ─────────────────────────────────────────────────
    cur.execute("""SELECT research_type, precision_measured, sample_n
                   FROM hermes_promotion_thresholds
                   WHERE sample_n >= 30 AND precision_measured < 0.25""")
    for rtype, prec, n in cur.fetchall():
        out.append(
            _propose(
                cur,
                apply,
                target_key=f"hermes_promotion.disable.{rtype}",
                target_path="hermes_promotion_thresholds (DB)",
                current={"research_type": rtype, "min_confidence": 0.75},
                proposed={
                    "research_type": rtype,
                    "min_confidence": 1.01,
                    "effect": "auto-promotion disabled; staged-for-review only",
                },
                reason=f"{rtype}: precision {float(prec):.2f} over n={n} graded promotions — worse than the 0.75-gate can fix",
                evidence={"research_type": rtype, "precision": float(prec), "n": n},
                risk="that research_type stops reaching prompts/RAG automatically",
                rollback=f"UPDATE hermes_promotion_thresholds SET min_confidence=0.75 WHERE research_type='{rtype}'",
            )
        )
    return out


def run(apply=False):
    if KILL_SWITCH.exists():
        out = {"ok": False, "reason": "HERMES_DISABLED kill switch present — config governor idle"}
        print(json.dumps(out))
        return out
    conn = _conn()
    if not apply:
        from lib.lane_last_receipt import enforce_readonly

        enforce_readonly(conn)  # dry run: the server refuses any write (AGENTS.md §6)
    cur = conn.cursor()
    proposals = detect(cur, apply)
    if apply:
        conn.commit()
    filed = [p for p in proposals if p["status"] in ("proposed", "would_propose")]
    alert_error = None
    if apply and filed:
        try:
            from db_adapter import _execute

            _execute(
                """INSERT INTO alert_events (alert_uid, alert_type, symbol, severity, source_script, raw_text, created_at)
                        VALUES (%s,'system_health',NULL,'info','hermes_config_governor',%s,NOW())
                        ON CONFLICT (alert_uid) DO NOTHING""",
                (
                    f"hermes_config_gov_{datetime.now(timezone.utc):%Y%m%d}",
                    "Hermes filed config-change proposal(s): "
                    + "; ".join(p["target_key"] for p in filed)
                    + " — review in config_change_proposals",
                ),
                fetch=None,
            )
        except Exception as exc:  # noqa: BLE001 -- the proposals are committed; the alert row is a courtesy
            alert_error = f"{type(exc).__name__}: {str(exc)[:160]}"
    out = {
        "ok": True,
        "apply": apply,
        "detectors_fired": len(proposals),
        "proposals": proposals,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    if alert_error:
        out["alert_error"] = alert_error
    if not apply:
        out["mode"] = "dry_run"
        conn.rollback()  # read-only SELECTs only; end the transaction, nothing to commit
    print(json.dumps(out, indent=2, default=str))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="file proposals (default: dry run)")
    ap.add_argument("--dry-run", action="store_true", help="detect and report only; wins over --apply")
    a = ap.parse_args(argv)
    apply = a.apply and not a.dry_run
    if not apply:
        run(apply=False)  # no receipt: a dry run writes nothing (AGENTS.md §6)
        return 0
    from lib.lane_last_receipt import now_iso, write_receipt

    started_at = now_iso()
    try:
        out = run(apply=True)
    except Exception as exc:
        write_receipt("hermes_config_governor", ok=False, started_at=started_at, error=f"{type(exc).__name__}: {exc}")
        raise
    # A kill-switch idle run is a successful no-op, not a failure; the summary says which it was.
    write_receipt(
        "hermes_config_governor",
        ok=True,
        started_at=started_at,
        summary={
            "detectors_fired": out.get("detectors_fired", 0),
            "filed": sum(1 for p in out.get("proposals") or [] if p.get("status") == "proposed"),
            "idle_reason": out.get("reason"),
            "alert_error": out.get("alert_error"),
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
