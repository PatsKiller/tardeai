#!/usr/bin/env python3
"""hermes_source_auto_approval.py — autonomous Gate 4 closure (no operator).

Reads source_vetting_actions_latest.json (or maturity JSON) and auto-activates/deactivates
news maturity sources when data thresholds pass. Borderline trusted-tier sources get an
LLM sanity check (grok→chatgpt→local via llm_lane). Prunes handled actions from the
vetting queue so the UI never presents an operator approval step.

Usage:
    python scripts/hermes_source_auto_approval.py [--apply] [--max-actions N] [--llm-borderline]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

MATURITY = ROOT / "data" / "runtime" / "source_maturity_latest.json"
ACTIONS = ROOT / "data" / "runtime" / "source_vetting_actions_latest.json"
AUDIT = ROOT / "data" / "runtime" / "source_auto_approval_latest.json"

CORE_MIN_SCORE = 60
CORE_AUTO_SCORE = 65
TRUSTED_MIN_SCORE = 50
TRUSTED_AUTO_SCORE = 50  # aligned with source_maturity trusted tier (score >= 50)
DEMOTE_MIN_SIGNALS = 100


def _env():
    for ln in (ROOT / ".env").read_text().splitlines():
        if "=" in ln and not ln.strip().startswith("#"):
            k, _, v = ln.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def _db():
    import psycopg2
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "trade_ai"),
        user=os.getenv("DB_USER", "trade_ai"),
        password=os.getenv("DB_PASSWORD", ""),
    )


def _load_actions() -> list[dict]:
    if not ACTIONS.exists():
        return []
    try:
        return list(json.loads(ACTIONS.read_text()).get("actions") or [])
    except Exception:
        return []


def _llm_approve_news_source(source: str, score: float, tier: str) -> tuple[bool | None, str]:
    """Free LLM lanes for borderline news-source activation."""
    try:
        import llm_lane
    except Exception:
        return None, "no-llm"
    prompt = (
        f"You are Hermes vetting a news attribution source for equity/market research.\n"
        f"SOURCE: {source}\nTIER: {tier}\nMATURITY_SCORE: {score:.1f}\n"
        "Activate only if this is a credible finance/news publisher (not spam, content farm, "
        "or unrelated). Reply ONLY JSON: {\"approve\": true|false, \"reason\": \"<=10 words\"}"
    )
    for lane in ("deepseek-flash", "grok", "chatgpt", "local"):
        try:
            if not llm_lane.available(lane):
                continue
            raw = llm_lane.generate(prompt, lane=lane, timeout=45)
            m = re.search(r"\{.*\}", raw or "", re.S)
            if not m:
                continue
            d = json.loads(m.group())
            return bool(d.get("approve")), f"LLM:{lane} {str(d.get('reason') or '')[:50]}"
        except Exception:
            continue
    return None, "llm-unavailable"


def _should_activate(action: dict, *, use_llm: bool) -> tuple[bool, str]:
    act = action.get("action")
    score = float(action.get("score") or 0)
    src = action.get("source", "")
    if act == "APPROVE_FOR_CORE_ACTIVATION":
        if action.get("outcome_proven") and score >= CORE_MIN_SCORE:
            return True, "core+outcome_proven"
        if score >= CORE_AUTO_SCORE:
            return True, f"core_score>={CORE_AUTO_SCORE}"
        return False, "core_below_threshold"
    if act == "REVIEW_FOR_ACTIVATION":
        if score >= TRUSTED_AUTO_SCORE:
            return True, f"trusted_score>={TRUSTED_AUTO_SCORE}"
        if score >= TRUSTED_MIN_SCORE and use_llm:
            ok, reason = _llm_approve_news_source(src, score, "trusted")
            if ok is True:
                return True, reason
            if ok is False:
                return False, reason
            return False, "llm_skip_borderline"
        return False, "trusted_below_threshold"
    return False, "not_activation"


def _deactivate_news_source(cur, source_name: str, *, operator: str, reason: str) -> dict:
    from hermes_source_registry import parse_maturity_notes

    cur.execute(
        "SELECT id, source_type, active, notes FROM research_sources WHERE source_name=%s",
        (source_name,),
    )
    row = cur.fetchone()
    if not row:
        return {"ok": False, "error": f"source {source_name!r} not found"}
    _id, stype, active, notes = row
    if stype != "news":
        return {"ok": False, "error": f"{source_name} is type {stype!r}, not news"}
    mat = parse_maturity_notes(notes) or {}
    mat["auto_deactivated"] = True
    mat["auto_deactivated_at"] = datetime.now(timezone.utc).isoformat()
    mat["auto_deactivated_by"] = operator
    mat["auto_deactivate_reason"] = reason[:200]
    cur.execute(
        "UPDATE research_sources SET active=false, notes=%s WHERE id=%s",
        (json.dumps(mat), _id),
    )
    try:
        import hermes_source_policy as hsp
        hsp.invalidate_cache()
    except Exception:
        pass
    return {"ok": True, "source": source_name, "active": False, "was_active": bool(active)}


def run_auto_approval(*, apply: bool, max_actions: int, use_llm: bool) -> dict:
    from hermes_source_registry import approve_news_source

    actions = _load_actions()
    if not actions and MATURITY.exists():
        mat = json.loads(MATURITY.read_text()).get("sources", [])
        c = _db()
        cur = c.cursor()
        cur.execute("SELECT source_name, active FROM research_sources")
        existing = {r[0]: r[1] for r in cur.fetchall()}
        c.close()
        for s in mat:
            src, tier, score = s["source"], s["tier"], s["maturity_score"]
            is_active = existing.get(src, False)
            if tier == "core" and not is_active:
                actions.append({
                    "source": src, "action": "APPROVE_FOR_CORE_ACTIVATION",
                    "score": score, "outcome_proven": s.get("outcome_proven"),
                })
            elif tier == "trusted" and not is_active:
                actions.append({"source": src, "action": "REVIEW_FOR_ACTIVATION", "score": score})
            elif tier == "demoted" and is_active and s.get("total_signals", 0) >= DEMOTE_MIN_SIGNALS:
                actions.append({
                    "source": src, "action": "REVIEW_FOR_DEACTIVATION_NOISE",
                    "score": score, "total_signals": s.get("total_signals"), "go_rate": s.get("go_rate"),
                })

    conn = _db()
    cur = conn.cursor()
    cur.execute("SELECT source_name, active FROM research_sources")
    active_map = {r[0]: r[1] for r in cur.fetchall()}

    activated, deactivated, skipped, remaining = [], [], [], []
    processed = 0

    for action in actions:
        if processed >= max_actions:
            remaining.append(action)
            continue
        src = action.get("source", "")
        act = action.get("action", "")

        if act == "REVIEW_FOR_DEACTIVATION_NOISE":
            if not active_map.get(src):
                skipped.append({"source": src, "action": act, "reason": "already_inactive"})
                continue
            if apply:
                res = _deactivate_news_source(
                    cur, src, operator="hermes_auto",
                    reason=f"demoted_noise signals={action.get('total_signals')} go={action.get('go_rate')}",
                )
                if res.get("ok"):
                    conn.commit()
                    deactivated.append({**action, "result": res})
                    active_map[src] = False
                else:
                    conn.rollback()
                    skipped.append({**action, "reason": res.get("error")})
            else:
                deactivated.append({**action, "dry_run": True})
            processed += 1
            continue

        if active_map.get(src):
            skipped.append({"source": src, "action": act, "reason": "already_active"})
            continue

        ok, reason = _should_activate(action, use_llm=use_llm)
        if not ok:
            remaining.append(action)
            skipped.append({"source": src, "action": act, "reason": reason})
            continue

        if apply:
            res = approve_news_source(cur, src, operator="hermes_auto")
            if res.get("ok"):
                mat = res.get("maturity") or {}
                mat["auto_approved"] = True
                mat["auto_approval_reason"] = reason
                cur.execute(
                    "UPDATE research_sources SET notes=%s WHERE source_name=%s",
                    (json.dumps(mat), src),
                )
                conn.commit()
                activated.append({**action, "approval_reason": reason, "result": res})
                active_map[src] = True
            else:
                conn.rollback()
                remaining.append(action)
                skipped.append({**action, "reason": res.get("error")})
        else:
            activated.append({**action, "approval_reason": reason, "dry_run": True})
        processed += 1

    if apply:
        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "activated": activated,
            "deactivated": deactivated,
            "skipped": skipped[:20],
            "remaining_actions": len(remaining),
        }
        AUDIT.write_text(json.dumps(payload, indent=2, default=str))
        ACTIONS.write_text(json.dumps({
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "actions": remaining,
            "note": "pending actions after hermes_source_auto_approval",
        }, indent=2))
        try:
            import hermes_source_policy as hsp
            hsp.invalidate_cache()
        except Exception:
            pass
    conn.close()

    return {
        "mode": "apply" if apply else "dry-run",
        "activated": len(activated),
        "deactivated": len(deactivated),
        "skipped": len(skipped),
        "remaining_queue": len(remaining),
        "activated_sample": activated[:6],
        "deactivated_sample": deactivated[:4],
        "skipped_sample": skipped[:6],
    }


def main():
    _env()
    parser = argparse.ArgumentParser(description="Hermes autonomous source vetting closure")
    parser.add_argument("--apply", action="store_true", help="Commit activations/deactivations")
    parser.add_argument("--max-actions", type=int, default=10)
    parser.add_argument("--llm-borderline", action="store_true", default=True,
                        help="LLM-check trusted tier scores 50-54 (default on)")
    parser.add_argument("--no-llm-borderline", action="store_true", help="Skip LLM borderline checks")
    args = parser.parse_args()
    use_llm = args.llm_borderline and not args.no_llm_borderline
    result = run_auto_approval(apply=args.apply, max_actions=args.max_actions, use_llm=use_llm)
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())