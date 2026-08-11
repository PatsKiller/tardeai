"""Phase 7 — final promotion gate for the Advisory Desk.

Requires **30 consecutive** green sessions plus integrity checks.
Does NOT auto-enable trading or broker credentials.

States:
  NOT_PROMOTED  — default
  ELIGIBLE      — all gates green; operator may promote
  PROMOTED      — operator confirmed; morning path treats desk as default

Promotion never:
  - sets production_activation_authorized on the agent fleet
  - grants broker / order / 2FA authority
  - auto-cuts over notification broker egress to ACTIVE
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RUNTIME = PROJECT_ROOT / "data" / "runtime"
SHADOW_DIR = RUNTIME / "advisory_shadow"
SESSIONS_PATH = SHADOW_DIR / "sessions.jsonl"
PROMOTION_PATH = SHADOW_DIR / "PROMOTION.json"
PROMOTION_LOG = SHADOW_DIR / "promotion_log.jsonl"
SCOREBOARD_PATH = SHADOW_DIR / "scoreboard.json"
ARTIFACTS_DIR = SHADOW_DIR / "artifacts"

PROMOTION_SESSIONS = 30
USEFUL_RATE_TARGET = 0.60
USEFUL_MIN_N = 5
BUDGET_USD = 0.05

# Strings that must never appear on agent authority surfaces
BANNED_AUTHORITY = (
    "broker_credential",
    "submit_order",
    "place_order",
    "rebalance.execute",
    "2fa.handle",
    "order_authority.*ALLOW",
    "broker_authority.*ALLOW",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _append_jsonl(path: Path, entry: dict[str, Any]) -> None:
    import fcntl
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(json.dumps(entry, default=str) + "\n")
        f.flush()
        fcntl.flock(f, fcntl.LOCK_UN)


def consecutive_passes(sessions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Count trailing consecutive session_pass=True from the end of the log."""
    sessions = sessions if sessions is not None else _read_jsonl(SESSIONS_PATH)
    streak = 0
    for s in reversed(sessions):
        if (s.get("gates") or {}).get("session_pass"):
            streak += 1
        else:
            break
    return {
        "consecutive_passes": streak,
        "required": PROMOTION_SESSIONS,
        "met": streak >= PROMOTION_SESSIONS,
        "total_sessions": len(sessions),
    }


def check_authority_fence() -> dict[str, Any]:
    """Verify catalog + specialist artifacts still deny broker/order/2FA."""
    issues: list[str] = []
    catalog = PROJECT_ROOT / "config" / "agent_maturity_catalog.json"
    try:
        cat = json.loads(catalog.read_text(encoding="utf-8"))
        ga = cat.get("global_authority") or {}
        for key in ("broker_authority", "order_authority", "approval_authority", "two_factor_authority"):
            val = str(ga.get(key) or cat.get(key) or "DENIED").upper()
            if val not in ("DENIED", "FALSE", "0", "NONE", ""):
                # only fail if explicitly granted
                if val in ("ALLOW", "ALLOWED", "TRUE", "GRANT", "GRANTED"):
                    issues.append(f"global_authority.{key}={val}")
        if cat.get("production_activation_authorized") is True:
            issues.append("production_activation_authorized=true (must stay false for desk-only promote)")
    except Exception as e:
        issues.append(f"catalog_unreadable:{type(e).__name__}")

    # Sample recent specialist artifacts
    if ARTIFACTS_DIR.exists():
        for p in sorted(ARTIFACTS_DIR.glob("*.json"))[-30:]:
            try:
                art = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            if art.get("authority") not in (None, "READ_ONLY_ADVISORY"):
                if art.get("authority") not in ("READ_ONLY_ADVISORY",):
                    issues.append(f"artifact {p.name} authority={art.get('authority')}")
            blob = json.dumps({k: v for k, v in art.items() if k != "denied"}, default=str)
            for banned in ("submit_order", "place_order", "broker_credential"):
                if banned in blob.lower():
                    issues.append(f"artifact {p.name} contains {banned}")

    return {
        "ok": len(issues) == 0,
        "issues": issues,
        "authority": "READ_ONLY_ADVISORY",
        "broker_credentials_on_agents": False,
    }


def check_alert_integrity() -> dict[str, Any]:
    """Prove existing alert producers / paths still exist (structure, not live fire)."""
    checks: list[dict[str, Any]] = []
    required = [
        PROJECT_ROOT / "scripts" / "telegram_alert.py",
        PROJECT_ROOT / "scripts" / "telegram_alert_router.py",
        PROJECT_ROOT / "scripts" / "morning_command_digest.py",
        PROJECT_ROOT / "scripts" / "alert_outbox.py",
    ]
    for p in required:
        checks.append({"path": str(p.relative_to(PROJECT_ROOT)), "exists": p.exists()})

    # Morning digest still has non-advisory sections
    morning = (PROJECT_ROOT / "scripts" / "morning_command_digest.py").read_text(encoding="utf-8")
    for sec in ("portfolio", "stops", "health", "advisory"):
        checks.append({"section": sec, "present": f'("{sec}"' in morning or f"'{sec}'" in morning})

    # Broker must not auto-cutover
    proof_path = RUNTIME / "advisory_notif_broker" / "egress_cutover_proof.json"
    broker_ok = True
    broker_detail = "no_proof_yet"
    if proof_path.exists():
        try:
            proof = json.loads(proof_path.read_text(encoding="utf-8"))
            broker_detail = proof.get("egress_cutover")
            # ACTIVE auto cutover would be a failure of the gate design
            if str(broker_detail).upper() == "ACTIVE":
                broker_ok = False
        except Exception:
            broker_ok = False
            broker_detail = "proof_unreadable"
    checks.append({"broker_egress_not_auto_active": broker_ok, "egress_cutover": broker_detail})

    # send_telegram still defined and hooks broker without replacing delivery
    ta = (PROJECT_ROOT / "scripts" / "telegram_alert.py").read_text(encoding="utf-8")
    checks.append({
        "send_telegram_present": "def send_telegram" in ta,
        "broker_hook_shadow": "wrap_send_hook" in ta,
        "legacy_delivery_intact": "publish_operator_message" in ta or "_legacy_send" in ta,
    })

    ok = all(
        c.get("exists", True) is not False
        and c.get("present", True) is not False
        and c.get("broker_egress_not_auto_active", True) is not False
        and c.get("send_telegram_present", True) is not False
        and c.get("legacy_delivery_intact", True) is not False
        for c in checks
    )
    return {"ok": ok, "checks": checks}


def check_lessons_gate() -> dict[str, Any]:
    try:
        from lib.advisory.kb_lessons import stats
        st = stats()
        return {
            "ok": int(st.get("ratified_n") or 0) >= 10,
            "ratified_n": st.get("ratified_n"),
            "required": 10,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def check_budget_streak(sessions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    sessions = sessions if sessions is not None else _read_jsonl(SESSIONS_PATH)
    # last N consecutive that passed must all be in budget
    streak_sessions = []
    for s in reversed(sessions):
        if (s.get("gates") or {}).get("session_pass"):
            streak_sessions.append(s)
            if len(streak_sessions) >= PROMOTION_SESSIONS:
                break
        else:
            break
    over = [
        s.get("session_id")
        for s in streak_sessions
        if float((s.get("gates") or {}).get("spend_usd") or 0) > BUDGET_USD + 1e-9
    ]
    return {
        "ok": len(over) == 0 and len(streak_sessions) > 0,
        "streak_len": len(streak_sessions),
        "over_budget_sessions": over,
        "budget_usd": BUDGET_USD,
    }


def evaluate_promotion() -> dict[str, Any]:
    """Full Phase 7 gate evaluation."""
    from lib.advisory.shadow_session import _useful_rate, rebuild_scoreboard

    sessions = _read_jsonl(SESSIONS_PATH)
    streak = consecutive_passes(sessions)
    useful = _useful_rate()
    authority = check_authority_fence()
    alerts = check_alert_integrity()
    lessons = check_lessons_gate()
    budget = check_budget_streak(sessions)
    scoreboard = rebuild_scoreboard()

    # Invariants/plausibility across consecutive streak
    streak_sessions = []
    for s in reversed(sessions):
        if (s.get("gates") or {}).get("session_pass"):
            streak_sessions.append(s)
            if len(streak_sessions) >= PROMOTION_SESSIONS:
                break
        else:
            break
    inv_ok = all((s.get("gates") or {}).get("invariants_green") for s in streak_sessions) if streak_sessions else False
    plaus_ok = all((s.get("gates") or {}).get("plausibility_pass") for s in streak_sessions) if streak_sessions else False
    val_ok = all((s.get("gates") or {}).get("validation_ok") for s in streak_sessions) if streak_sessions else False

    gates = {
        "consecutive_30": streak,
        "useful_rate": {
            "ok": bool(useful.get("meets_60pct")),
            **useful,
            "required": USEFUL_RATE_TARGET,
            "min_n": USEFUL_MIN_N,
        },
        "indefensible_zero": {
            "ok": int(useful.get("indefensible_wrong_fact") or 0) == 0,
            "count": useful.get("indefensible_wrong_fact"),
        },
        "budget": budget,
        "invariants_green_streak": {"ok": inv_ok, "n": len(streak_sessions)},
        "plausibility_green_streak": {"ok": plaus_ok, "n": len(streak_sessions)},
        "validation_green_streak": {"ok": val_ok, "n": len(streak_sessions)},
        "authority_fence": authority,
        "alert_integrity": alerts,
        "lessons": lessons,
        "phase5_shadow": {
            "ok": bool(scoreboard.get("phase5_ready")) or streak["consecutive_passes"] >= 20,
            "phase5_ready": scoreboard.get("phase5_ready"),
            "sessions_passed": scoreboard.get("sessions_passed"),
        },
    }

    all_ok = all(
        bool(g.get("ok") if isinstance(g, dict) and "ok" in g else g.get("met"))
        for g in (
            gates["consecutive_30"],
            gates["useful_rate"],
            gates["indefensible_zero"],
            gates["budget"],
            gates["invariants_green_streak"],
            gates["plausibility_green_streak"],
            gates["validation_green_streak"],
            gates["authority_fence"],
            gates["alert_integrity"],
            gates["lessons"],
        )
    )

    current = load_promotion_state()
    status = current.get("status") or "NOT_PROMOTED"
    if status != "PROMOTED":
        status = "ELIGIBLE" if all_ok else "NOT_PROMOTED"

    result = {
        "ts": _now_iso(),
        "status": status,
        "eligible": all_ok and status != "PROMOTED",
        "promoted": status == "PROMOTED",
        "all_gates_green": all_ok,
        "gates": gates,
        "morning_path_default": status == "PROMOTED",
        "notes": (
            "Operator must run `advisory_promotion.py promote --confirm` to set PROMOTED. "
            "This never enables broker execution or agent fleet production_activation."
        ),
    }
    # Persist evaluation (not operator promote)
    if status != "PROMOTED":
        _write_promotion({
            **result,
            "status": status,
            "updated_at": _now_iso(),
        })
    else:
        # refresh gates but keep promoted stamp
        prev = load_promotion_state()
        _write_promotion({
            **result,
            "status": "PROMOTED",
            "promoted_at": prev.get("promoted_at"),
            "promoted_by": prev.get("promoted_by"),
            "updated_at": _now_iso(),
        })
    return result


def load_promotion_state() -> dict[str, Any]:
    if PROMOTION_PATH.exists():
        try:
            return json.loads(PROMOTION_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"status": "NOT_PROMOTED", "promoted": False, "morning_path_default": False}


def _write_promotion(state: dict[str, Any]) -> None:
    PROMOTION_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROMOTION_PATH.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")


def promote(*, operator: str = "operator", confirm: bool = False, force: bool = False) -> dict[str, Any]:
    """Operator-confirmed promotion. force=True skips eligibility (dangerous; still no broker)."""
    ev = evaluate_promotion()
    if not confirm:
        return {
            "ok": False,
            "error": "refused: pass --confirm to promote",
            "evaluation": ev,
        }
    if not ev.get("all_gates_green") and not force:
        return {
            "ok": False,
            "error": "gates not green; use --force only with operator override",
            "evaluation": ev,
        }
    state = {
        "status": "PROMOTED",
        "promoted": True,
        "eligible": False,
        "all_gates_green": ev.get("all_gates_green"),
        "morning_path_default": True,
        "promoted_at": _now_iso(),
        "promoted_by": operator,
        "force": bool(force),
        "gates_snapshot": {
            "consecutive_passes": (ev.get("gates") or {}).get("consecutive_30"),
            "useful_rate": (ev.get("gates") or {}).get("useful_rate"),
        },
        "authority": "READ_ONLY_ADVISORY",
        "broker_enabled": False,
        "notes": (
            "Desk is default morning advisory path. "
            "Live Flash still requires ADVISORY_DESK_V1 env / shadow env. "
            "No broker credentials granted."
        ),
        "ts": _now_iso(),
    }
    _write_promotion(state)
    _append_jsonl(PROMOTION_LOG, {"event": "PROMOTED", **state})
    return {"ok": True, "state": state}


def demote(*, operator: str = "operator", reason: str = "") -> dict[str, Any]:
    state = {
        "status": "NOT_PROMOTED",
        "promoted": False,
        "morning_path_default": False,
        "demoted_at": _now_iso(),
        "demoted_by": operator,
        "reason": reason,
        "ts": _now_iso(),
    }
    _write_promotion(state)
    _append_jsonl(PROMOTION_LOG, {"event": "DEMOTED", **state})
    return {"ok": True, "state": state}


def is_morning_path_default() -> bool:
    return bool(load_promotion_state().get("morning_path_default") or load_promotion_state().get("promoted"))
