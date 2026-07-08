#!/usr/bin/env python3
"""telegram_alert_router.py — Central operator alert classification and routing.

Classifies alerts into P0/P1/P2/P3 and routes to Telegram/dashboard/digest/log.
Pure functions + in-memory dedupe. No trades. No orders. No DB writes.

Loaded by telegram_alert.py to gate outbound Telegram sends.
"""
import hashlib
import os
import re
import time
import yaml
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
_POLICY_PATH = PROJ / "config" / "operator_alert_policy.yaml"

# In-memory dedupe cache: {dedupe_key: last_sent_ts}
_dedupe_cache: dict = {}
_suppression_log: list = []

# Rate limit counters: {hour_key: count}
_hourly_counts: dict = {}

# Health Agent repeat suppression
_last_health: dict = {"score": None, "status": None, "ts": 0.0}
_health_daily_count: dict = {}


def _load_policy() -> dict:
    try:
        return yaml.safe_load(_POLICY_PATH.read_text()) if _POLICY_PATH.exists() else {}
    except Exception:
        return {}


def _policy():
    return _load_policy().get("rules", {})


# ── Classification patterns ──────────────────────────────────────────────────

_P2_PATTERNS = [
    # ALERT-FATIGUE-1: Suppress proposal noise from Telegram
    (r"ATP REVIEW ALERT", "atp_review_noise"),
    (r"STOP CROSSED.*PENDING|STOP_CROSSED_PENDING", "stop_crossed_pending"),
    (r"LARGE MOVE.*BEFORE REVIEW|LARGE_MOVE_BEFORE_REVIEW", "large_move_pending"),
    (r"Approval:\s*BLOCKED", "approval_blocked"),
    (r"Status:\s*PENDING.*Paper mode", "pending_paper_noise"),
    (r"No order submitted", "no_order_noise"),
    (r"PROPOSAL.*(?:REJECTED|DENIED|DEFERRED|EXPIRED|BLOCKED)", "proposal_rejected"),
    (r"dry.run.*(?:approved|rejected|deferred)", "dry_run_decision"),
    # WAIT/AVOID/RVOL-only
    (r"\bWAIT\b", "wait_signal"),
    (r"\bAVOID\b", "avoid_signal"),
    (r"RVOL\s+\d+\.\d+x.*(?:WAIT|AVOID)", "rvol_only"),
    (r"_No GO-tier setups this run\._", "no_go_setups"),
    # Iris/library/content
    (r"Iris Library Audit", "iris_library_audit"),
    (r"content gap", "iris_content_gap"),
    (r"Library Quality", "iris_library_quality"),
    # Raw catalyst/source telemetry
    (r"PRE.MARKET CATALYST", "premarket_catalyst_dump"),
    (r"catalyst.*source.*\d+ articles", "raw_catalyst_dump"),
    (r"source.*telemetry", "raw_telemetry"),
    # Generic critique
    (r"Trade AI Critique.*\d+/\d+ reviewed", "generic_critique_summary"),
    (r"Iris:.*reviewed.*confirmed", "generic_iris_footer"),
    # Lifecycle/catalog status
    (r"Scanner Catalog", "catalog_status"),
    (r"membership.*present.*dropped", "membership_status"),
    # Telegram hygiene P1-6
    (r"Hermes watchlist alerts", "hermes_batch"),
    (r"Investigating \d+ escalation", "escalation_investigating"),
    (r"Topic Curator:", "topic_curator"),
    (r"Incubator Promoter|Promoted:\s*\d+\s*\|\s*Skipped:", "incubator_promoter"),
    (r"Critic:\s*(?:BLOCK|DOWNGRADE)", "critic_block"),
]

_P2_SYSTEM_PATTERNS = [
    # Health agent noise — suppress repeated retries/staleness
    (r"RETRY_EXHAUSTED|retry.*exhausted|max retries", "retry_exhausted_noise"),
    (r"SAFE_FLOCK.*PARSE|malformed.*JSONL|safe_flock", "safe_flock_noise"),
    (r"ESCALATION_DEDUPED|escalation.*dedup", "escalation_deduped"),
    (r"maria.?research.*stale", "maria_research_stale"),
    (r"OUTPUT_INVALID.*atm_auto_approver", "atm_output_invalid"),
    (r"LLM.*analysis.*complete|LLM.*reviewed|analysis complete", "llm_analysis_complete"),
    (r"(?:fixed|resolved|recovered).*(?:already|again|still)", "false_fixed_claim"),
    (r"LOCKTIMEOUT|lock.?timeout", "lock_timeout"),
    # After-hours stop alerts → morning review only
    (r"after.hours.*stop|stop.*after.hours|overnight.*stop", "afterhours_stop"),
    # Routine catalyst / research complete
    (r"catalyst.*research.*complete|research.*catalyst.*done", "catalyst_research_complete"),
    (r"no.catalyst.found|no clear catalyst", "no_catalyst_noise"),
]

_P3_PATTERNS = [
    (r"sync done.*uploaded.*unchanged.*failed", "drive_sync_success"),
    (r"cron.*success\b", "cron_success"),
    (r"\[db_adapter\].*connection", "db_wrapper_status"),
    (r"SYNC_STATUS.*uploaded", "drive_sync_status"),
    (r"DEBUG|debug", "debug_message"),
]

_P0_PATTERNS = [
    (r"OPTIONS POSITION MONITOR.*(?:OUTCOME READY|ORPHAN|CONSIDER_CLOSE)", "options_position_action"),
    (r"OPTIONS POSITION MONITOR.*ALPACA PAPER FILLED", "options_position_filled"),
    (r"Paper Proposal:", "paper_proposal"),
    (r"APPROVAL.READY|approve/reject|/ptapprove|/ptreject", "proposal_actionable"),
    (r"STOP_TRIGGERED\s*—|STOP TRIGGERED\s*—", "stop_symbol"),
    (r"execution.*fail|order.*fail|broker.*fail", "execution_failure"),
    (r"STOP.*(?:HIT|TRIGGERED).*action.required", "stop_action_required"),
    (r"SIEM\s+P[01]:", "siem_critical"),
    (r"STALELOCK|SYSTEM HEALTH:.*STALE", "stale_lock"),
    (r"Remediation ineffective \(needs operator\)", "health_remediation_failed"),
    (r"URGENT|CRITICAL", "urgent_system"),
    (r"position.*unprotected|margin.*call", "position_risk"),
]

_STOP_PATTERN = re.compile(r"STOP.*(TRIGGERED|HIT|alert)", re.IGNORECASE)
_GO_PATTERN = re.compile(r"GO.Tier|🎯.*GO|Trade AI v12|Trade AI LIVE", re.IGNORECASE)
# Momentum-scalp setup alerts (from social_scalp_scanner: "GO … Social Scalp Setup" / "WAIT … Social
# Mention"). Operator wants these live; without a carve-out the WAIT ones die on suppress_wait.
_SCALP_SETUP_PATTERN = re.compile(r"Social Scalp Setup|Social Mention|Scalp Setup", re.IGNORECASE)
_SCALP_SCORE_PATTERN = re.compile(r"Score:\s*(\d+)\s*/\s*55", re.IGNORECASE)
_HEALTH_PATTERN = re.compile(r"Health Agent:\s*(\w+)\s*—\s*(\d+)/100", re.IGNORECASE)
_PORTFOLIO_INTEL = re.compile(r"PORTFOLIO INTELLIGENCE", re.IGNORECASE)


def _parse_health(message: str) -> tuple[str | None, int | None]:
    m = _HEALTH_PATTERN.search(message)
    if not m:
        return None, None
    try:
        return m.group(1).lower(), int(m.group(2))
    except (ValueError, IndexError):
        return m.group(1).lower(), None


def classify_alert(message: str) -> str:
    """Classify message into P0_INTERRUPT, P1_DIGEST, P2_DASHBOARD_ONLY, P3_LOG_ONLY."""
    if not message:
        return "P3_LOG_ONLY"

    # Check P0 first (highest priority)
    for pattern, _ in _P0_PATTERNS:
        if re.search(pattern, message, re.IGNORECASE):
            return "P0_INTERRUPT"

    # Check P3 (lowest priority — logs only)
    for pattern, _ in _P3_PATTERNS:
        if re.search(pattern, message, re.IGNORECASE):
            return "P3_LOG_ONLY"

    # Health Agent — score/status aware
    if _HEALTH_PATTERN.search(message):
        status, score = _parse_health(message)
        rules = _policy()
        if status == "unhealthy":
            return "P1_DIGEST"
        if status == "degraded":
            max_score = rules.get("health_telegram_max_score", 80)
            if score is not None and score < max_score:
                return "P1_DIGEST"
            return "P2_DASHBOARD_ONLY"
        return "P2_DASHBOARD_ONLY"

    # ── Momentum-scalp setup carve-out (operator wants GO/WAIT scalp setups in REAL TIME) ──
    # The scanner's social-only + route gates downgrade most setups to WAIT, which suppress_wait
    # would then swallow — so the operator saw nothing after ~2026-07-01. Surface scalp setups live
    # above a score floor (GO clears it inherently; meaningful WAIT does too), before the WAIT sink.
    # Tunables (config/operator_alert_policy.yaml → rules): scalp_realtime_enabled, scalp_realtime_min_score.
    rules = _policy()
    if rules.get("scalp_realtime_enabled", True) and _SCALP_SETUP_PATTERN.search(message):
        _sm = _SCALP_SCORE_PATTERN.search(message)
        _score = int(_sm.group(1)) if _sm else 0
        if _score >= int(rules.get("scalp_realtime_min_score", 25)):
            return "P0_INTERRUPT"
        return "P2_DASHBOARD_ONLY"   # below floor → dashboard, not a phone buzz

    # Check P2 system noise (health agent, retries, staleness, LLM complete)
    for pattern, _ in _P2_SYSTEM_PATTERNS:
        if re.search(pattern, message, re.IGNORECASE):
            return "P2_DASHBOARD_ONLY"

    # Check P2 (dashboard only)
    rules = _policy()
    for pattern, category in _P2_PATTERNS:
        if re.search(pattern, message, re.IGNORECASE):
            if category == "hermes_batch" and not rules.get("suppress_hermes_telegram", True):
                return "P1_DIGEST"
            if category == "escalation_investigating" and not rules.get("suppress_escalation_investigating", True):
                return "P1_DIGEST"
            if category == "incubator_promoter" and not rules.get("suppress_incubator_promoter", True):
                return "P1_DIGEST"
            if category == "topic_curator" and not rules.get("suppress_topic_curator", True):
                return "P1_DIGEST"
            if category == "wait_signal" and rules.get("suppress_wait", True):
                return "P2_DASHBOARD_ONLY"
            if category == "avoid_signal" and rules.get("suppress_avoid", True):
                return "P2_DASHBOARD_ONLY"
            if category == "rvol_only" and rules.get("suppress_rvol_only", True):
                return "P2_DASHBOARD_ONLY"
            if category in ("iris_library_audit", "iris_content_gap", "iris_library_quality"):
                if rules.get("suppress_iris_content_gap_telegram", True):
                    return "P2_DASHBOARD_ONLY"
            if category == "generic_critique_summary":
                if rules.get("suppress_generic_critique_summary", True):
                    return "P2_DASHBOARD_ONLY"
            if category == "raw_catalyst_dump":
                if rules.get("suppress_raw_catalyst_dump", True):
                    return "P2_DASHBOARD_ONLY"
            return "P2_DASHBOARD_ONLY"

    # Portfolio intelligence digest
    if _PORTFOLIO_INTEL.search(message):
        return "P1_DIGEST"

    # Stop batch summary (not per-symbol)
    if _STOP_PATTERN.search(message):
        return "P1_DIGEST"

    # Trade AI LIVE — dashboard only unless trade plan present
    if _GO_PATTERN.search(message):
        if re.search(r"Entry.*Stop.*Target|R:R\s+\d", message):
            return "P0_INTERRUPT"
        if re.search(r"MORNING COMMAND", message, re.IGNORECASE):
            return "P1_DIGEST"
        return "P2_DASHBOARD_ONLY"

    # Aegis/morning brief
    if re.search(r"Aegis|Morning Brief|morning brief|MORNING COMMAND", message, re.IGNORECASE):
        return "P1_DIGEST"

    # Default: P1 digest (not silent, but not interrupting)
    return "P1_DIGEST"


def build_dedupe_key(message: str) -> str:
    """Build a deduplication key from message content."""
    sym_match = re.search(r"\*(\w{1,5})\*", message) or re.search(
        r"STOP_TRIGGERED\s*—\s*(\w+)", message, re.IGNORECASE
    )
    symbol = sym_match.group(1) if sym_match else ""

    status, score = _parse_health(message)
    if status is not None:
        return f"health_{status}_{score}"

    if _PORTFOLIO_INTEL.search(message):
        return "portfolio_intelligence"

    if re.search(r"Paper Proposal:\s*(\w+)", message, re.IGNORECASE):
        m = re.search(r"Paper Proposal:\s*(\w+)", message, re.IGNORECASE)
        return f"paper_proposal_{m.group(1) if m else 'x'}"

    if _STOP_PATTERN.search(message):
        return f"stop_{symbol}" if symbol else "stop_batch"
    if _GO_PATTERN.search(message):
        m = re.search(r"NEW GO\s*—\s*(\w+)", message, re.IGNORECASE)
        sym = m.group(1) if m else symbol
        return f"go_{sym or 'live'}"
    if re.search(r"Aegis|Morning Brief|MORNING COMMAND", message, re.IGNORECASE):
        return "morning_command"

    if "OPTIONS POSITION MONITOR" in message:
        label_m = re.search(
            r"OPTIONS POSITION MONITOR.*—\s*([A-Z_ ]+)", message, re.IGNORECASE)
        label = (label_m.group(1).strip().replace(" ", "_") if label_m else "advisory")
        return f"options_pos_{symbol or 'x'}_{label[:32].lower()}"

    normalized = re.sub(r"\d{4}-\d{2}-\d{2}|\d{2}:\d{2}|\d+\.\d+%", "", message)
    return hashlib.md5(normalized[:200].encode()).hexdigest()[:12]


def is_deduplicated(message: str, window_minutes: int = None) -> bool:
    """Check if this message was recently sent within the dedupe window."""
    key = build_dedupe_key(message)
    rules = _policy()

    if window_minutes is None:
        if key.startswith("health_"):
            window_minutes = rules.get("suppress_health_repeat_minutes", 240)
        elif key == "portfolio_intelligence":
            window_minutes = rules.get("portfolio_intelligence_dedupe_minutes", 360)
        elif "stop" in key:
            window_minutes = rules.get("stop_trigger_dedupe_minutes", 390)
        elif key.startswith("go_"):
            window_minutes = rules.get("go_signal_dedupe_minutes", 120)
        elif key.startswith("options_pos_"):
            window_minutes = rules.get("options_position_dedupe_minutes", 60)
        else:
            window_minutes = 60

    now = time.time()
    last_sent = _dedupe_cache.get(key, 0)
    if now - last_sent < window_minutes * 60:
        return True
    return False


def _health_telegram_allowed(message: str) -> bool:
    """Extra gate for Health Agent: only send on material score/status change."""
    rules = _policy()
    status, score = _parse_health(message)
    if status is None:
        return True

    day_key = time.strftime("%Y-%m-%d")
    if _health_daily_count.get(day_key, 0) >= rules.get("max_health_telegram_per_day", 2):
        return False

    now = time.time()
    repeat_mins = rules.get("suppress_health_repeat_minutes", 240)
    if (
        _last_health.get("score") == score
        and _last_health.get("status") == status
        and now - _last_health.get("ts", 0) < repeat_mins * 60
    ):
        return False

    last_score = _last_health.get("score")
    min_delta = rules.get("health_telegram_min_delta", 5)
    if status == "degraded" and last_score is not None and score is not None:
        if abs(score - last_score) < min_delta:
            return False

    return True


def _mark_health_sent(message: str):
    status, score = _parse_health(message)
    day_key = time.strftime("%Y-%m-%d")
    _health_daily_count[day_key] = _health_daily_count.get(day_key, 0) + 1
    _last_health.update({"score": score, "status": status, "ts": time.time()})


def mark_sent(message: str):
    """Record that this message was sent (for dedupe tracking)."""
    key = build_dedupe_key(message)
    _dedupe_cache[key] = time.time()
    if _HEALTH_PATTERN.search(message):
        _mark_health_sent(message)


def apply_rate_limit(message: str) -> dict:
    """Check if sending would exceed rate limits."""
    rules = _policy()
    hour_key = f"{int(time.time() // 3600)}"

    if _GO_PATTERN.search(message):
        max_per_hour = rules.get("max_trade_ai_live_alerts_per_hour", 3)
        go_key = f"go_{hour_key}"
        current = _hourly_counts.get(go_key, 0)
        if current >= max_per_hour:
            return {"allowed": False, "reason": f"GO alerts exceed {max_per_hour}/hour limit"}
        _hourly_counts[go_key] = current + 1

    return {"allowed": True, "reason": "ok"}


def should_send_telegram(message: str) -> bool:
    """Main gate: should this message be sent to Telegram?"""
    level = classify_alert(message)

    if level in ("P2_DASHBOARD_ONLY", "P3_LOG_ONLY"):
        record_suppressed(message, f"level={level}")
        return False

    if _HEALTH_PATTERN.search(message) and not _health_telegram_allowed(message):
        record_suppressed(message, "health_repeat")
        return False

    if level == "P1_DIGEST":
        if is_deduplicated(message):
            record_suppressed(message, "deduplicated")
            return False

    rl = apply_rate_limit(message)
    if not rl["allowed"]:
        record_suppressed(message, rl["reason"])
        return False

    return True


def record_suppressed(message: str, reason: str):
    """Record a suppressed alert for audit purposes."""
    _suppression_log.append({
        "ts": time.time(),
        "reason": reason,
        "level": classify_alert(message),
        "preview": message[:100],
    })
    if len(_suppression_log) > 500:
        _suppression_log.pop(0)


def get_suppression_log() -> list:
    """Return recent suppression log for audit."""
    return list(_suppression_log)


def route_alert(message: str) -> dict:
    """Classify and route an alert, returning routing decision."""
    level = classify_alert(message)
    send = should_send_telegram(message)
    policy = _load_policy()
    destinations = policy.get("destinations", {})

    dest = destinations.get("reports", "/v3/reports")
    if re.search(r"propos|approv|Paper Proposal", message, re.IGNORECASE):
        dest = destinations.get("proposals", "/v3/trading")
    elif re.search(r"stop|risk|position", message, re.IGNORECASE):
        dest = destinations.get("risk", "/v3/risk")
    elif re.search(r"journal|lesson|closed trade", message, re.IGNORECASE):
        dest = destinations.get("journal", "/v3/journal")
    elif re.search(r"Hermes watchlist", message, re.IGNORECASE):
        dest = destinations.get("hermes", "/v3/watch")
    elif re.search(r"Iris|library|content gap", message, re.IGNORECASE):
        dest = destinations.get("iris_library", "/v3/intelligence")
    elif re.search(r"scanner|GO|WAIT|AVOID|Trade AI", message, re.IGNORECASE):
        dest = destinations.get("trade_ai_scanner", "/v3/trading")
    elif re.search(r"governance|system|health|SIEM|escalation", message, re.IGNORECASE):
        dest = destinations.get("system_health", "/v3/health")

    return {
        "level": level,
        "send_telegram": send,
        "destination": dest,
        "dedupe_key": build_dedupe_key(message),
    }


def surface_destination(message: str) -> str:
    """Return the dashboard/page destination for a message."""
    return route_alert(message)["destination"]