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
    (r"APPROVAL.READY|approve/reject|/ptapprove|/ptreject", "proposal_actionable"),
    (r"execution.*fail|order.*fail|broker.*fail", "execution_failure"),
    (r"STOP.*(?:HIT|TRIGGERED).*action.required", "stop_action_required"),
    (r"URGENT|CRITICAL", "urgent_system"),
    (r"position.*unprotected|margin.*call", "position_risk"),
]

_STOP_PATTERN = re.compile(r"STOP.*(TRIGGERED|HIT|alert)", re.IGNORECASE)
_GO_PATTERN = re.compile(r"GO.Tier|🎯.*GO|Trade AI v12|Trade AI LIVE", re.IGNORECASE)


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

    # Check P2 system noise (health agent, retries, staleness, LLM complete)
    for pattern, _ in _P2_SYSTEM_PATTERNS:
        if re.search(pattern, message, re.IGNORECASE):
            return "P2_DASHBOARD_ONLY"

    # Check P2 (dashboard only)
    rules = _policy()
    for pattern, category in _P2_PATTERNS:
        if re.search(pattern, message, re.IGNORECASE):
            # Some P2 categories have policy overrides
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

    # Stop triggers: dedupe-aware
    if _STOP_PATTERN.search(message):
        return "P1_DIGEST"  # Stops go to digest unless explicitly actionable (P0 already caught)

    # Trade AI LIVE messages with GO tickers
    if _GO_PATTERN.search(message):
        # Only P0 if it contains actionable trade plan
        if re.search(r"Entry.*Stop.*Target|R:R\s+\d", message):
            return "P0_INTERRUPT"
        return "P1_DIGEST"  # GO without trade plan goes to digest

    # Aegis/morning brief
    if re.search(r"Aegis|Morning Brief|morning brief", message, re.IGNORECASE):
        return "P1_DIGEST"

    # Default: P1 digest (not silent, but not interrupting)
    return "P1_DIGEST"


def build_dedupe_key(message: str) -> str:
    """Build a deduplication key from message content."""
    # Extract symbol if present
    sym_match = re.search(r"\*(\w{1,5})\*", message)
    symbol = sym_match.group(1) if sym_match else ""

    # Extract alert type
    if _STOP_PATTERN.search(message):
        return f"stop_{symbol}"
    if _GO_PATTERN.search(message):
        return f"go_{symbol}"
    if re.search(r"Aegis|Morning Brief", message, re.IGNORECASE):
        return "aegis_brief"

    # Generic hash for other messages
    normalized = re.sub(r"\d{4}-\d{2}-\d{2}|\d{2}:\d{2}|\d+\.\d+%", "", message)
    return hashlib.md5(normalized[:200].encode()).hexdigest()[:12]


def is_deduplicated(message: str, window_minutes: int = None) -> bool:
    """Check if this message was recently sent within the dedupe window."""
    key = build_dedupe_key(message)
    rules = _policy()

    if window_minutes is None:
        if "stop" in key:
            window_minutes = rules.get("stop_trigger_dedupe_minutes", 390)
        elif "go_" in key:
            window_minutes = rules.get("go_signal_dedupe_minutes", 120)
        else:
            window_minutes = 60

    now = time.time()
    last_sent = _dedupe_cache.get(key, 0)
    if now - last_sent < window_minutes * 60:
        return True
    return False


def mark_sent(message: str):
    """Record that this message was sent (for dedupe tracking)."""
    key = build_dedupe_key(message)
    _dedupe_cache[key] = time.time()


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

    # P2 and P3 never go to Telegram
    if level in ("P2_DASHBOARD_ONLY", "P3_LOG_ONLY"):
        record_suppressed(message, f"level={level}")
        return False

    # P1 digest: only send if not deduplicated
    if level == "P1_DIGEST":
        if is_deduplicated(message):
            record_suppressed(message, "deduplicated")
            return False

    # Rate limit check
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
    # Keep only last 500 entries in memory
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

    # Determine dashboard destination
    dest = "log"
    if re.search(r"propos|approv", message, re.IGNORECASE):
        dest = destinations.get("proposals", "/v3/trading")
    elif re.search(r"stop|risk|position", message, re.IGNORECASE):
        dest = destinations.get("risk", "/v3/risk")
    elif re.search(r"journal|lesson|closed trade", message, re.IGNORECASE):
        dest = destinations.get("journal", "/v3/journal")
    elif re.search(r"Iris|library|content gap", message, re.IGNORECASE):
        dest = destinations.get("iris_library", "/v3/intelligence")
    elif re.search(r"scanner|GO|WAIT|AVOID|Trade AI", message, re.IGNORECASE):
        dest = destinations.get("trade_ai_scanner", "/v3/trading")
    elif re.search(r"governance|system|health", message, re.IGNORECASE):
        dest = destinations.get("system_health", "/v3/system")

    return {
        "level": level,
        "send_telegram": send,
        "destination": dest,
        "dedupe_key": build_dedupe_key(message),
    }


def surface_destination(message: str) -> str:
    """Return the dashboard/page destination for a message."""
    return route_alert(message)["destination"]
