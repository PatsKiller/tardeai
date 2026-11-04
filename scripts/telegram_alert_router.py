#!/usr/bin/env python3
"""telegram_alert_router.py — Central operator alert classification and routing.

Classifies alerts into P0/P1/P2/P3 and routes to Telegram/dashboard/digest/log.
Pure functions + in-memory dedupe. No trades. No orders. No DB writes.

Loaded by telegram_alert.py to gate outbound Telegram sends.
"""
import fcntl
import hashlib
import json
import logging
import os
import re
import contextvars
import time
import uuid
import yaml
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

PROJ = Path(__file__).resolve().parent.parent
_POLICY_PATH = PROJ / "config" / "operator_alert_policy.yaml"

# A T1 recovery page (scripts/lib/recovery_notify.py) must never be downgraded to a dashboard row.
# Operator P0 2026-11-03: Recovery Watch found re-entry candidates for weeks, sent them as P2, and the
# router answered P2_DASHBOARD_ONLY + LEGACY_SHADOWED; the operator missed his largest stop-out.
# The marker is owned by recovery_notify; the literal is only the fallback when that lib is absent.
try:
    from scripts.lib.recovery_notify import (
        RECOVERY_T1_MARKER as _RECOVERY_T1_MARKER,
        case_token_for as _case_token_for,
        parse_case_token as _parse_case_token,
    )
except ImportError:  # pragma: no cover — scripts/ on sys.path variant
    try:
        from lib.recovery_notify import (  # type: ignore
            RECOVERY_T1_MARKER as _RECOVERY_T1_MARKER,
            case_token_for as _case_token_for,
            parse_case_token as _parse_case_token,
        )
    except ImportError:
        _RECOVERY_T1_MARKER = "[[RECOVERY_T1]]"

        def _case_token_for(case_key: str) -> str:  # type: ignore
            return "v1:" + str(case_key)

        def _parse_case_token(text: str):  # type: ignore
            match = re.search(r"case:(v1:)?([A-Za-z0-9_=-]+)", text or "")
            return match.group(2) if match else None

#: The per-case-per-day bound that makes the recovery T1 budget exemption safe (operator ruling,
#: 2026-11-03): a T1 page is exempt from the daily budget, but at most ONE page per case per day.
_RECOVERY_T1_PAGE_PATH = PROJ / "data" / "runtime" / "recovery_t1_pages.json"
_RECOVERY_CASE_RE = re.compile(r"\bcase:([A-Za-z0-9_.:-]+)")
#: The gates bypassed by the last recovery-T1 decision; route_alert copies them into its result so a
#: future reviewer can see the exemption was deliberate (cx-openai-2 F5).
_RECOVERY_T1_EXEMPTIONS = ("health_repeat", "rate_limit", "daily_budget")
_last_recovery_exemptions: list[str] = []
#: Public alias so the transport can ack a delivered recovery page (telegram_alert._intent_send).
RECOVERY_T1_MARKER = _RECOVERY_T1_MARKER

# B2, 2026-08-31: THESE DICTS CANNOT HOLD A CROSS-INVOCATION GUARANTEE.
#
# Every producer that reaches this module is a one-shot cron or systemd process.
# A module-level dict is empty at the start of each one, so `_dedupe_cache` was
# always empty when consulted and `mark_sent()` wrote to a dict that died
# microseconds later. The "max 2 health telegrams per day" cap was unenforceable
# for the same reason: `_health_daily_count` reset on every invocation, so the
# check passed unconditionally on a cold start.
#
# A guarantee that spans invocations, whose state does not, is not a weak
# guarantee -- it is the absence of one, wearing its name (AGENTS.md §7).
#
# The durable content-keyed store in cio_telegram_transport already exists and is
# TTL-bounded (#770), so per §13.5 these delegate to it rather than adding a third
# mechanism. The dicts remain ONLY as a same-process fast path; correctness comes
# from the durable layer.
_dedupe_cache: dict = {}
_suppression_log: list = []

# Rate limit counters: {hour_key: count}
_hourly_counts: dict = {}

# Health Agent repeat suppression
_last_health: dict = {"score": None, "status": None, "ts": 0.0}
_health_daily_count: dict = {}


# D3, 2026-09-16: durable daily send budget for the general DM.
#
# A per-day cap that spans invocations MUST be durable (AGENTS.md §7): a
# module-level counter is empty at every cron/systemd start, so a "30/day" cap
# read from one would pass unconditionally on every cold start. The budget is
# persisted to data/runtime/telegram_daily_send_budget.json, keyed by UTC day.
#
# Ops-exempt: capital-at-risk and operator-requested-action classes are never
# budgeted — a stop/protection/broker-auth alert must always page. Over budget,
# non-exempt P0 sends fall to digest (recorded + not sent), never dropped silent.
DAILY_SEND_BUDGET = 30
_BUDGET_PATH = PROJ / "data" / "runtime" / "telegram_daily_send_budget.json"

# Capital-risk / operator-requested-action signatures that are never budgeted.
_OPS_EXEMPT_PATTERN = re.compile(
    r"STOP HEALTH|ORPHANED|OVERSIZED|PROTECTION|BROKER AUTH|2FA|FLATTEN|DRAWDOWN"
    r"|GO \S|ENTRY ALERT|Material change|CIO entry|TRIGGERED"
    r"|HIGH CONVICTION ENTRY|ENTRY APPROACHING|ADD-ON ENTRY|ENTRY BLOCKED|CRITICAL STOP ALERT|STOP WARNING",
    re.IGNORECASE,
)


def _budget_day() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def _read_budget() -> dict:
    try:
        return json.loads(_BUDGET_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _budget_count_today() -> int:
    return int(_read_budget().get(_budget_day(), 0) or 0)


def _record_budget_send() -> None:
    # Fail-open: a budget-write failure must never block a send.
    try:
        _BUDGET_PATH.parent.mkdir(parents=True, exist_ok=True)
        doc = _read_budget()
        doc[_budget_day()] = int(doc.get(_budget_day(), 0) or 0) + 1
        tmp = _BUDGET_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc, indent=1), encoding="utf-8")
        tmp.replace(_BUDGET_PATH)
    except Exception:
        pass


def _ops_exempt(message: str) -> bool:
    # A stop about to fire / fired always pages, even past the daily P0 budget (2026-10-14 SPCX incident).
    return bool(_OPS_EXEMPT_PATTERN.search(message or "") or _STOP_FIRING_PATTERN.search(message or ""))


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
    (r"TRADE AI DATA QUALITY ALERT", "finviz_data_quality"),
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
# 2026-10-14 incident (SPCX): stop_health_check flagged NEAR_TRIGGER "about to fire" on ~$120k of SPCX stops at
# 13:50/14:00/14:10 ET and the stops filled at 14:36/14:38 — every warning went "Suppressed (P1_DIGEST)" because
# operator_alert_policy_v2.route_event (checked first) returned DIGEST, so the P0 stop patterns below never ran.
# A stop that is about to fire or has fired is always an interrupt: matched BEFORE the policy router.
# Covers every stop_health_check format: the decision card ("STOP WARNING" / "CRITICAL STOP ALERT"), the single
# line ("STOP HEALTH — NEAR_TRIGGER: ...") and the batch ("STOP HEALTH — N alert(s)" + per-row lines).
_STOP_FIRING_PATTERN = re.compile(
    r"(?:STOP HEALTH|STOP WARNING|CRITICAL STOP ALERT)[\s\S]*?"
    r"(?:NEAR[_ ]TRIGGER|\bTRIGGERED\b|about to fire|stop FILLED)",
    re.IGNORECASE,
)
_GO_PATTERN = re.compile(r"GO.Tier|🎯.*GO|Trade AI v12|Trade AI LIVE", re.IGNORECASE)
# Momentum-scalp setup alerts (from social_scalp_scanner: "GO … Social Scalp Setup" / "WAIT … Social
# Mention"). Operator wants these live; without a carve-out the WAIT ones die on suppress_wait.
_SCALP_SETUP_PATTERN = re.compile(r"Social Scalp Setup|Social Mention|Scalp Setup", re.IGNORECASE)
_SCALP_SCORE_PATTERN = re.compile(r"Score:\s*(\d+)\s*/\s*55", re.IGNORECASE)
# continuous_runner Trade AI LIVE lane: "🎯 NEW GO — SYM score=37 RVOL …" (distinct from hourly v12 digest).
_NEW_GO_SCALP_PATTERN = re.compile(r"NEW GO\b", re.IGNORECASE)
_NEW_GO_SCORE_PATTERN = re.compile(r"score=(\d+)", re.IGNORECASE)
_CRITIC_BLOCK_PATTERN = re.compile(r"Critic:\s*\*?(BLOCK|DOWNGRADE)", re.IGNORECASE)
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

    # A T1 recovery page can never be a dashboard row or a log line (operator P0 2026-11-03: Recovery
    # Watch found SCHG/BAH/RTX every run since 10-01 and answered P2_DASHBOARD_ONLY + LEGACY_SHADOWED;
    # the operator missed SPCX recovering). This check is FIRST, before the raw-JSON guard: a recovery
    # plan/summary that quotes `{"symbol": …, "rationale": …}` would otherwise match the raw-JSON rule
    # (the marker itself starts with `[`) and be logged only — the silence this marker exists to stop.
    if _RECOVERY_T1_MARKER in message:
        return "P0_INTERRUPT"

    # R18-DATA.1: raw machine JSON is never an operator investment page.
    try:
        try:
            from scripts.lib.ops_health_routing import looks_like_raw_json
        except ImportError:
            from lib.ops_health_routing import looks_like_raw_json  # type: ignore
        if looks_like_raw_json(message):
            return "P3_LOG_ONLY"
    except Exception:
        pass

    # Stop about to fire / fired → interrupt, ahead of every digest/dashboard route (2026-10-14 SPCX incident).
    if _STOP_FIRING_PATTERN.search(message):
        return "P0_INTERRUPT"

    try:
        from operator_alert_policy_v2 import classify_legacy_message, route_event
        _ev = classify_legacy_message(message, source_producer="telegram_alert_router")
        _decision = route_event(_ev)
        if _decision.route_mode == "IMMEDIATE":
            return "P0_INTERRUPT"
        if _decision.route_mode == "DIGEST":
            return "P1_DIGEST"
        if _decision.route_mode == "COMMAND_CENTER":
            return "P2_DASHBOARD_ONLY"
        if _decision.route_mode == "LOG":
            return "P3_LOG_ONLY"
    except Exception:
        pass

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

    # continuous_runner NEW GO carve-out — morning momentum-scalp Telegram (restored 2026-07-09,
    # critic-suppress fixed 2026-07-16).
    # Trade AI LIVE digests were P2 (hourly recap) which silenced the lane: GOs detected, never
    # delivered. Critic DOWNGRADE/BLOCK used to force P2 too — that hid JTAI-class morning GOs
    # entirely. Critic text stays in the message; operator must still see the GO.
    if rules.get("scalp_realtime_enabled", True) and _NEW_GO_SCALP_PATTERN.search(message):
        _sm = _NEW_GO_SCORE_PATTERN.search(message)
        min_score = int(rules.get("scalp_realtime_min_score", 18))
        if _sm is not None:
            _score = int(_sm.group(1))
            if _score < min_score:
                return "P2_DASHBOARD_ONLY"
        # score absent → still a continuous NEW_GO fire; deliver
        cm = _CRITIC_BLOCK_PATTERN.search(message)
        if cm:
            verdict = (cm.group(1) or "").upper()
            if verdict == "BLOCK" and not rules.get("scalp_send_on_critic_block", True):
                return "P2_DASHBOARD_ONLY"
            if verdict == "DOWNGRADE" and not rules.get("scalp_send_on_critic_downgrade", True):
                return "P2_DASHBOARD_ONLY"
        return "P0_INTERRUPT"

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
            if category == "finviz_data_quality":
                return "P2_DASHBOARD_ONLY"
            return "P2_DASHBOARD_ONLY"

    # Portfolio intelligence digest
    if _PORTFOLIO_INTEL.search(message):
        return "P1_DIGEST"

    # Stop batch summary (not per-symbol)
    if _STOP_PATTERN.search(message):
        return "P1_DIGEST"

    # Trade AI LIVE — dashboard only unless trade plan present, or a GO score-jump
    # (NEW GO already returned above; SCORE_JUMP updates re-surface active GOs).
    if _GO_PATTERN.search(message):
        if re.search(r"Entry.*Stop.*Target|R:R\s+\d", message):
            return "P0_INTERRUPT"
        if re.search(r"MORNING COMMAND", message, re.IGNORECASE):
            return "P1_DIGEST"
        # SCORE_JUMP / RVOL lines that explicitly tag decision GO (not WAIT/AVOID)
        if rules.get("scalp_score_jump_telegram", True) and re.search(
            r"(?:\+\d+pts|RVOL\s+\d|RVOL\s+\d+\.\d+x).*?\bGO\b|\bGO\b.*?(?:\+\d+pts|RVOL)",
            message,
            re.IGNORECASE | re.DOTALL,
        ):
            if not re.search(r"\b(?:WAIT|AVOID)\b", message, re.IGNORECASE) or re.search(
                r"\(GO\)|\[\s*GO\s*\]", message, re.IGNORECASE
            ):
                return "P0_INTERRUPT"
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
    # The durable check is the one that actually spans invocations. The dict
    # above is a same-process fast path and is empty in every cron invocation.
    return _durable_recently_sent(key, window_minutes * 60)


def _durable_recently_sent(key: str, ttl_seconds: float) -> bool:
    """Was this key sent within the window, according to durable state?

    B2. Delegates to the store the CIO transport already maintains, so a cron
    producer can see what a systemd producer sent. Fail-open on any error: a
    dedupe lookup that cannot run must not silently suppress a real message.
    """
    try:
        from scripts.lib.cio_telegram_transport import was_recently_sent
    except ImportError:
        try:
            from lib.cio_telegram_transport import was_recently_sent
        except ImportError:
            return False
    try:
        return bool(was_recently_sent(key, ttl=int(ttl_seconds)))
    except Exception:
        return False


def durable_mark_sent(key: str, meta: dict | None = None) -> None:
    """Record a send where the next invocation can see it.

    B2. `mark_sent()` writes to a module-level dict that does not survive the
    process. This is the half that makes the guarantee real.
    """
    try:
        from scripts.lib.cio_telegram_transport import mark_sent as _durable
    except ImportError:
        try:
            from lib.cio_telegram_transport import mark_sent as _durable
        except ImportError:
            return
    try:
        _durable(key, meta=meta or {})
    except Exception as e:
        log.warning("durable dedupe mark failed: %s", type(e).__name__)


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
    """Record that this message was sent (for dedupe tracking + the daily budget)."""
    key = build_dedupe_key(message)
    _dedupe_cache[key] = time.time()
    if _HEALTH_PATTERN.search(message):
        _mark_health_sent(message)
    # D3: count non-ops P0 sends against today's budget (durable). Ops-exempt never counts.
    if classify_alert(message) == "P0_INTERRUPT" and not _ops_exempt(message):
        _record_budget_send()


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


def _recovery_case_key(message: str) -> str:
    parsed = _parse_case_token(message)
    return parsed if parsed else build_dedupe_key(message)


#: A claim older than this without a delivery is abandoned (crash/timeout) and may be retaken.
_RECOVERY_T1_CLAIM_STALE_SECONDS = 600


def _recovery_ledger_rows() -> list[dict]:
    try:
        raw = _RECOVERY_T1_PAGE_PATH.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return []
    rows = []
    for line in raw.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        # `released` is a first-class state: the writer appends it and the reader must see it,
        # otherwise a released attempt still reads as claimed (cx-openai-2 F8).
        if isinstance(row, dict) and row.get("case") and row.get("state") in ("claimed", "delivered", "released"):
            rows.append(row)
    return rows


def _recovery_state(day: str, key: str) -> str:
    """State for this case-day. DELIVERED is terminal: no later row can un-deliver it (F5b)."""
    state = "absent"
    for row in _recovery_ledger_rows():
        if row.get("day") != day or row.get("case") != key:
            continue
        if row["state"] == "delivered":
            return "delivered"
        state = row["state"]
    return state


def _recovery_append(day: str, key: str, state: str) -> None:
    try:
        _RECOVERY_T1_PAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(_RECOVERY_T1_PAGE_PATH, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"day": day, "case": key, "state": state,
                                 "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                 "pid": os.getpid()}, sort_keys=True) + "\n")
    except OSError as exc:  # a ledger fault must not silence a T1
        log.warning("recovery T1 ledger append failed (%s); the page is still allowed", exc)


def _recovery_claim_lock(day: str, key: str) -> Path:
    # A HASH of the case key, never a sanitised rendering: two distinct ids that both reduce to
    # "a_b" (or that share an 80-char prefix) must not share a lock (cx-openai-2 F3 encoding half).
    digest = hashlib.sha256(f"{day}\x00{key}".encode("utf-8")).hexdigest()[:32]
    return _RECOVERY_T1_PAGE_PATH.parent / f".recovery_t1_claim.{day}.{digest}.lock"


#: The lock-owner token this process holds per case-day. Release/deliver must not unlink a lock
#: that belongs to another claimant (cx3 R5-F2: a stale actor must not reopen someone else's case).
_RECOVERY_CLAIM_OWNERS: dict[str, str] = {}
#: The attempt this execution is acting for. The owner map is keyed by case/day, so a reclaimed
#: attempt overwrites the token and a STALE attempt's settle used to pop the NEWEST one and release
#: a page another attempt is delivering (cx3 R8-F2). A settle now proves it owns the generation it is
#: settling by comparing this token, not by trusting the map's current value.
_RECOVERY_ATTEMPT: "contextvars.ContextVar[str | None]" = contextvars.ContextVar(
    "recovery_attempt_owner", default=None)


def _recovery_attempt_matches(day: str, key: str) -> bool:
    """True when this execution's attempt token is the one the map currently holds.

    No token (a caller outside the claim path) keeps the pre-fix behaviour rather than becoming a
    silent no-op: the map value is then the only evidence available.
    """
    attempt = _RECOVERY_ATTEMPT.get()
    if attempt is None:
        return True
    current = _RECOVERY_CLAIM_OWNERS.get(f"{day}\x00{key}")
    return current == attempt


def _recovery_lock_owner(lock: Path) -> Optional[str]:
    """The owner token recorded in a lock file, or None when it is missing/unreadable/legacy."""
    try:
        doc = json.loads(lock.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    owner = doc.get("owner") if isinstance(doc, dict) else None
    return str(owner) if owner else None


def _recovery_reclaim_guard():
    """Serialise stale-lock reclamation and claim settlement. Returns ``(status, fd)``.

    ``status`` is one of:
    * ``ok``    — the flock is held; call ``os.close(fd)`` to release it.
    * ``busy``  — a peer holds the mutex. Stand down; do not race it.
    * ``error`` — the mutex could not be used at all (permission, a directory at the path, disk I/O).
      This is NOT contention and must never be read as "a peer is handling it": the caller proceeds
      without serialisation and logs, because a broken mutex must not silence a page (cx3 R7-F2).

    One fixed file beside the ledger: reclamation is rare (only after a crash), it is released by the
    kernel if the holder dies, and it is deliberately never unlinked — unlinking an flock file would
    let a waiter lock a deleted inode while a third process locks a new one.
    """
    path = _RECOVERY_T1_PAGE_PATH.parent / ".recovery_t1_reclaim.lock"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT, 0o600)
    except OSError as exc:
        log.warning("recovery T1 reclaim mutex unusable (%s); proceeding unserialised (fail-open)",
                    type(exc).__name__)
        return "error", None
    # Bounded blocking wait (cx3 R8-F1): failing instantly on a GLOBAL mutex let an unrelated case's
    # contention abandon THIS case's settlement, and the corrected retry was then deduped for the
    # whole lease. Wait for the mutex; a real timeout still returns "busy" so the caller can fall
    # back to its owner-check-and-release path instead of dropping the release.
    deadline = time.monotonic() + max(0.0, float(os.environ.get("TRADEAI_RECOVERY_MUTEX_WAIT_S", "2.0")))
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return "ok", fd
        except OSError as exc:
            if not (isinstance(exc, BlockingIOError) or getattr(exc, "errno", None) in (11, 13)):
                os.close(fd)
                log.warning("recovery T1 reclaim mutex flock failed (%s); proceeding unserialised (fail-open)",
                            type(exc).__name__)
                return "error", None
            if time.monotonic() >= deadline:
                os.close(fd)
                return "busy", None
            time.sleep(0.01)
    return "ok", fd  # unreachable: the loop returns on every path


def recovery_t1_state(message: str) -> str:
    return _recovery_state(_budget_day(), _recovery_case_key(message))


def recovery_t1_claim(message: str) -> bool:
    """Atomically claim today's single page for this CASE. True only for the claiming process.

    Atomic across processes via O_CREAT|O_EXCL on a per-case lock; a claim left by a crash becomes
    retakeable after ``_RECOVERY_T1_CLAIM_STALE_SECONDS``. Claiming is not delivery: only
    :func:`recovery_t1_mark_delivered` consumes the day (cx-openai-2 F5a/F5b).

    The terminal state is re-read WHILE HOLDING the lock (cx3 R5-F2). A process that saw "absent"
    before a peer claimed, delivered and released would otherwise take the freed lock and page a
    second time. The pre-lock read stays as a cheap fast path; it is never the authority.
    """
    day = _budget_day()
    key = _recovery_case_key(message)
    if _recovery_state(day, key) == "delivered":
        return False
    lock = _recovery_claim_lock(day, key)
    owner = uuid.uuid4().hex
    held = False
    for _attempt in (1, 2):
        try:
            lock.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                os.write(fd, json.dumps({"pid": os.getpid(), "owner": owner,
                                         "at": time.time()}).encode("utf-8"))
            finally:
                os.close(fd)
            held = True
            break
        except FileExistsError:
            try:
                age = time.time() - lock.stat().st_mtime
            except OSError:
                age = 0
            if age < _RECOVERY_T1_CLAIM_STALE_SECONDS:
                return False
            # Stale reclamation must be GENERATION-safe (cx3 R6-F1). Renaming the pathname alone can
            # move a lock that a peer created AFTER our stat: two processes both see the old stale
            # lock, the first replaces it, and the second's resume renames the FRESH lock away and
            # claims too. Reclamation is therefore serialised by an flock mutex and re-decided under
            # it; a peer that finds another reclaimer active does not race it.
            status, guard = _recovery_reclaim_guard()
            if status == "busy":
                return False      # a peer is reclaiming; do not race it (bounded duplicate)
            try:
                try:
                    age = time.time() - lock.stat().st_mtime
                except OSError:
                    continue          # it vanished while we waited: try to create it again
                if age < _RECOVERY_T1_CLAIM_STALE_SECONDS:
                    return False      # a fresh claimant replaced it while we waited
                graveyard = lock.with_name(f"{lock.name}.stale.{os.getpid()}.{uuid.uuid4().hex[:8]}")
                try:
                    os.rename(lock, graveyard)
                except OSError:
                    continue
                try:
                    os.unlink(graveyard)
                except OSError:
                    pass
            finally:
                if guard is not None:
                    os.close(guard)   # releases the flock
        except OSError:
            break  # cannot lock: fail-open, the page is loud
    if _recovery_state(day, key) == "delivered":       # authoritative, while we hold the lock
        if held:
            try:
                os.unlink(lock)
            except OSError:
                pass
        return False
    if held:
        _RECOVERY_CLAIM_OWNERS[f"{day}\x00{key}"] = owner
        # Bind this execution to the generation it just created, so a later settle can prove it is
        # settling ITS attempt rather than whichever attempt is newest when it happens to run.
        _RECOVERY_ATTEMPT.set(owner)
    _recovery_append(day, key, "claimed")
    return True


def recovery_t1_mark_delivered(message: str) -> None:
    day = _budget_day()
    key = _recovery_case_key(message)
    lock = _recovery_claim_lock(day, key)
    # Settlement is serialised with reclamation (cx3 R7-F1): without the same mutex, a reclaimer can
    # replace our lock between the owner read and the unlink, and we would free the FRESH claimant's
    # lock. The owner is re-read UNDER the mutex, so the decision is bound to the attempt generation.
    status, guard = _recovery_reclaim_guard()
    if status == "busy":
        # A GLOBAL mutex held by an unrelated case is not evidence that this case is being handled
        # (cx3 R8-F1). The delivery is recorded either way — delivered is terminal — and the lock is
        # only unlinked below after the owner check, which is safe without the mutex.
        log.warning("recovery T1 reclaim mutex timed out; settling delivered unserialised")
    try:
        _recovery_append(day, key, "delivered")        # delivered is terminal whoever sends
        if not _recovery_attempt_matches(day, key):
            return                                      # a stale attempt must not settle the new one
        owner = _RECOVERY_CLAIM_OWNERS.pop(f"{day}\x00{key}", None)
        lock_owner = _recovery_lock_owner(lock)
        if lock_owner is None or lock_owner == owner:
            try:
                lock.unlink()
            except OSError:
                pass
    finally:
        if guard is not None:
            os.close(guard)


def recovery_t1_release(message: str) -> None:
    """A failed attempt releases ITS claim — never another claimant's (cx3 R5-F2 / R7-F1 / F5b)."""
    day = _budget_day()
    key = _recovery_case_key(message)
    if _recovery_state(day, key) == "delivered":
        return  # delivered is terminal; a stale resumer must not re-open the day
    lock = _recovery_claim_lock(day, key)
    status, guard = _recovery_reclaim_guard()
    if status == "busy":
        # The mutex is global; an unrelated case can hold it. Falling back to the owner-check below
        # releases THIS case (a narrow race is strictly better than a never-delivered case), instead
        # of abandoning the release and letting the retry be deduped for the whole lease (cx3 R8-F1).
        log.warning("recovery T1 reclaim mutex timed out; releasing unserialised")
    try:
        # Under the mutex the owner re-read is authoritative: the lock at this path IS the generation
        # our release is settling. A stale actor that cached an older owner cannot free the fresh one.
        if not _recovery_attempt_matches(day, key):
            return  # this settle belongs to an older attempt; leave the current claim alone
        owner = _RECOVERY_CLAIM_OWNERS.pop(f"{day}\x00{key}", None)
        lock_owner = _recovery_lock_owner(lock)
        if lock_owner is not None and lock_owner != owner:
            return  # another live claimant owns this case; leave its lock and its state alone
        _recovery_append(day, key, "released")
        try:
            lock.unlink()
        except OSError:
            pass
    finally:
        if guard is not None:
            os.close(guard)


def _recovery_exemptions_for(message: str) -> list[str]:
    """Only the gates that WOULD have suppressed this message, measured side-effect-free (F6)."""
    bypassed = []
    if _HEALTH_PATTERN.search(message) and not _health_telegram_allowed(message):
        bypassed.append("health_repeat")
    rules = _policy()
    hour_key = f"{int(time.time() // 3600)}"
    if _GO_PATTERN.search(message) and _hourly_counts.get(f"go_{hour_key}", 0) >= int(
            rules.get("max_trade_ai_live_alerts_per_hour", 3)):
        bypassed.append("rate_limit")
    if not _ops_exempt(message) and _budget_count_today() >= DAILY_SEND_BUDGET:
        # The budget gate never applies to ops-exempt messages (stop/risk/auth), so naming it as a
        # bypass for one would be a false exemption (cx-openai-2 F6).
        bypassed.append("daily_budget")
    return bypassed


def should_send_telegram(message: str, *, consume: bool = False) -> bool:
    """Main gate: should this message be sent to Telegram?

    A PREVIEW by default. For a recovery T1 the daily bound is delivery-owned (cx-openai-2 F5), so a
    caller that only asks "would this send?" must not spend the claim (cc5 P1, 2026-11-03): the real
    delivery path (``route_intent`` -> ``_recovery_intent_bound``) consumes it. A caller that sends
    DIRECTLY after this gate passes ``consume=True`` and owns the ack/release.
    """
    level = classify_alert(message)

    if _RECOVERY_T1_MARKER in message:
        # Operator ruling 2026-11-03 (cx-openai-2 F5): a recovery T1 is exempt from health-repeat,
        # rate-limit and daily-budget gates, and the exemption is bounded per CASE per day with a
        # delivery-owned claim (claim now, delivered only on a confirmed send). ``consume=False``
        # (the default) is a read-only preview for route classification and for callers that hand
        # the message to the intent path, which claims atomically at the point of delivery.
        state = recovery_t1_state(message)
        if state == "delivered":
            record_suppressed(message, "recovery_t1_daily_case_bound")
            return False
        if consume:
            if not recovery_t1_claim(message):
                record_suppressed(message, "recovery_t1_daily_case_bound")
                return False
        elif state == "claimed":
            return False
        _last_recovery_exemptions[:] = _recovery_exemptions_for(message)
        return True

    if level in ("P2_DASHBOARD_ONLY", "P3_LOG_ONLY"):
        record_suppressed(message, f"level={level}")
        return False

    if _HEALTH_PATTERN.search(message) and not _health_telegram_allowed(message):
        record_suppressed(message, "health_repeat")
        return False

    if level == "P1_DIGEST":
        record_suppressed(message, "digest_queue")
        return False

    rl = apply_rate_limit(message)
    if not rl["allowed"]:
        record_suppressed(message, rl["reason"])
        return False

    # D3: durable daily budget for non-ops P0 sends. Ops-exempt classes always page.
    if level == "P0_INTERRUPT" and not _ops_exempt(message):
        if _budget_count_today() >= DAILY_SEND_BUDGET:
            record_suppressed(message, "daily_budget_exceeded")
            return False

    return True


def peek_should_send(message: str) -> bool:
    """Would this message send? A PURE READ: it never claims the recovery T1 day.

    cc5 P1 (2026-11-03): the per-case bound exists to stop a SECOND DELIVERY, not to punish a
    second question. Every preview, simulation and legacy pre-check goes through this; only the
    real delivery path (``route_intent``) and a caller that sends directly right after its gate
    (``should_send_telegram(..., consume=True)``) may claim.
    """
    return should_send_telegram(message, consume=False)


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


def _ignore_verdict_escalation(message: str) -> bool:
    """Defense v8 A5: an escalation whose VERDICT is IGNORE (esp. low-confidence) is
    ops-digest material, not a page. Actionable verdicts and high-severity conflicts
    still page. Measured monthly via the Reports alert-analytics noise review."""
    import re as _re
    if not _re.search(r"escalat", message, _re.IGNORECASE):
        return False
    if not _re.search(r"\bIGNORE\b", message):
        return False
    m = _re.search(r"(\d{1,3})\s*%", message)
    conf = int(m.group(1)) if m else 0
    return conf < 60  # low-confidence IGNORE = digest, never a 🚨


def route_alert(message: str) -> dict:
    """Classify and route an alert, returning routing decision."""
    level = classify_alert(message)
    send = peek_should_send(message)
    exemptions: list[str] = []
    if send and _RECOVERY_T1_MARKER in message:
        # Only the gates that WOULD have suppressed this message (measured side-effect-free by
        # should_send_telegram); empty when nothing would have been bypassed (cx-openai-2 F6).
        exemptions = list(_last_recovery_exemptions)
        if _ignore_verdict_escalation(message):
            exemptions.append("ignore_escalation")
    elif send and _ignore_verdict_escalation(message):
        send = False  # A5: IGNORE-verdict escalations land in the ops digest, not a page
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
        "recovery_t1_exemptions": exemptions,
    }


def surface_destination(message: str) -> str:
    """Return the dashboard/page destination for a message."""
    return route_alert(message)["destination"]


# ── Notification intents: an explicit priority instead of bypass_router=True ─────────────────────────────
#
# Operator 2026-10-10 ("moving the 30 bypass senders ... do tonight"); AGENTS.md §24.1 (4.6.0, PROPOSED):
# senders emit notification intents and the gateway decides. Thirty scheduled senders passed
# bypass_router=True, which skipped classify_alert() AND every dedupe and receipt with it. The text
# classifier was the reason they bypassed (it digested GO setups and scheduled reports by their wording), so
# an intent carries its priority explicitly and the classifier is never consulted for it:
#
#   P1  delivered now. Never capped (not counted against DAILY_SEND_BUDGET, never held by it) and never
#       quiet-held — the same contract as incident_notifier's P1. The router adds what bypass lacked: a
#       content-keyed dedupe with a declared window, and a durable route receipt.
#   P2  delivered now, except during the operator's quiet window (22:00–07:00 America/New_York by default,
#       operator decision 2026-10-09 — the incident notifier's window and env vars, read here so there is one
#       window). A held P2 is archived to telegram_outbox channel 'reports_archive' (forced report_type, so it
#       is stored even when report_capture does not recognise the header); the advice digest folds that
#       archive (scripts/lib/advice_digest.collect_other). If the hold cannot be persisted, the P2 is
#       delivered instead — a failure to hold must never become a silent drop (AGENTS.md §9.1).
#
#   P3  FYI: never interrupts. Always archived to the same Reports archive under its own report type and
#       folded by the same digest (SND2, 2026-10-11: "FYI -> P3 digest"). It is what the text classifier's
#       DIGEST verdict gave these producers, now declared instead of inferred from wording. If the archive
#       write fails the P3 is delivered instead -- a digest that cannot be written must not become a drop.
#
# Not changed: classify_alert, should_send_telegram, DAILY_SEND_BUDGET and every text-routed producer.
INTENT_P1 = "P1"
INTENT_P2 = "P2"
INTENT_P3 = "P3"
INTENT_PRIORITIES = (INTENT_P1, INTENT_P2, INTENT_P3)
DEFAULT_INTENT_DEDUPE_MINUTES = 60
HELD_P2_REPORT_TYPE = "notification_intent_p2"
DIGEST_P3_REPORT_TYPE = "notification_intent_p3"
# Decision -> the Reports-archive report type a non-delivered intent is stored under for the digest.
INTENT_ARCHIVE_REPORT_TYPE = {"HELD_QUIET_HOURS": HELD_P2_REPORT_TYPE, "DIGEST": DIGEST_P3_REPORT_TYPE}
INTENT_RECEIPT_SCHEMA = "NotificationIntentRoute@v1"
INTENT_RECEIPTS_ENV = "TRADEAI_INTENT_RECEIPTS_PATH"
_INTENT_RECEIPTS_DEFAULT = PROJ / "data" / "runtime" / "notification_intent_receipts.jsonl"

# Same env vars and defaults as scripts/incident_notifier.py (ENV_CLOCK / ENV_TZ); parity is test-pinned.
_QUIET_START_ENV = ("TRADEAI_INCIDENT_NOTIFIER_QUIET_START", "22:00")
_QUIET_END_ENV = ("TRADEAI_INCIDENT_NOTIFIER_QUIET_END", "07:00")
_QUIET_TZ_ENV = ("TRADEAI_INCIDENT_NOTIFIER_TZ", "America/New_York")

_intent_sent: dict = {}

# Quiet-hours exemptions by message class (operator 2026-10-31, design DSN-20261031-market-risk-engine P3-T1,
# §11 item 5): a P2 ``market_risk`` intent raised in the pre-market window is delivered, not archived. The 10-30
# selloff RCA (finding 3): the only market-level warning of the week fired at 05:52 ET and was held for the digest.
# The window, classes and priorities live in config, never here.
QUIET_EXEMPTIONS_ENV = "TRADEAI_INTENT_QUIET_EXEMPTIONS_PATH"
_QUIET_EXEMPTIONS_DEFAULT = PROJ / "config" / "notification_intent_quiet_exemptions.json"
QUIET_EXEMPTIONS_SCHEMA = "NotificationIntentQuietExemptions@v1"


def load_quiet_exemptions() -> list[dict]:
    """The reviewed exemption rows (schema-checked). Unreadable or malformed config means no exemption, logged."""
    path = Path(os.environ.get(QUIET_EXEMPTIONS_ENV) or _QUIET_EXEMPTIONS_DEFAULT)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        log.warning("quiet exemptions unreadable (%s) at %s — no exemption applies", type(e).__name__, path)
        return []
    if not isinstance(doc, dict) or doc.get("schema") != QUIET_EXEMPTIONS_SCHEMA:
        log.warning("quiet exemptions rejected: schema is not %s at %s — no exemption applies",
                    QUIET_EXEMPTIONS_SCHEMA, path)
        return []
    rows = []
    for r in doc.get("exemptions") or []:
        if isinstance(r, dict) and r.get("id") and r.get("message_classes") and isinstance(r.get("window"), dict):
            rows.append(r)
        else:
            log.warning("quiet exemption row rejected (shape) at %s: %r", path, str(r)[:120])
    return rows


def _hhmm_strict(text) -> int | None:
    """Minutes after midnight for a strict HH:MM (00:00-23:59), else None. No default: a bad bound never widens."""
    try:
        h, m = (int(x) for x in str(text).strip().split(":"))
    except ValueError:
        return None
    return h * 60 + m if 0 <= h < 24 and 0 <= m < 60 else None


def quiet_exemption_for(message_class: str | None, priority: str, now=None) -> str | None:
    """The id of the exemption that lets this intent through the quiet window right now, else None."""
    from datetime import datetime as _dt, timezone as _tz
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    mc = str(message_class or "").strip()
    if not mc:
        return None
    for row in load_quiet_exemptions():
        if mc not in [str(x) for x in row.get("message_classes") or []]:
            continue
        if priority not in [str(x).upper() for x in row.get("priorities") or [INTENT_P2]]:
            continue
        win = row["window"]
        start, end = _hhmm_strict(win.get("start")), _hhmm_strict(win.get("end"))
        if start is None or end is None or start == end:
            log.warning("quiet exemption %s skipped: window bounds %r-%r are not strict HH:MM",
                        row.get("id"), win.get("start"), win.get("end"))
            continue
        default_tz = str(os.environ.get(_QUIET_TZ_ENV[0]) or _QUIET_TZ_ENV[1]).strip()
        try:
            tz = ZoneInfo(str(win.get("tz") or default_tz))
        except (ZoneInfoNotFoundError, ValueError):
            try:
                tz = ZoneInfo(default_tz)
            except (ZoneInfoNotFoundError, ValueError):
                tz = ZoneInfo(_QUIET_TZ_ENV[1])
        t = (now or _dt.now(_tz.utc)).astimezone(tz)
        m = t.hour * 60 + t.minute
        inside = (start <= m < end) if start < end else (m >= start or m < end)
        if inside:
            return str(row["id"])
    return None


def _hhmm(text: str, default: str) -> int:
    for candidate in (text, default):
        try:
            h, m = (int(x) for x in str(candidate).strip().split(":"))
        except ValueError:
            continue
        if 0 <= h < 24 and 0 <= m < 60:
            return h * 60 + m
    return 0


def intent_in_quiet_hours(now=None) -> bool:
    """True inside the operator's quiet window. Wall clock in the configured tz; start > end wraps midnight."""
    from datetime import datetime as _dt, timezone as _tz
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    start = _hhmm(os.environ.get(_QUIET_START_ENV[0]) or "", _QUIET_START_ENV[1])
    end = _hhmm(os.environ.get(_QUIET_END_ENV[0]) or "", _QUIET_END_ENV[1])
    tz_name = str(os.environ.get(_QUIET_TZ_ENV[0]) or _QUIET_TZ_ENV[1]).strip()
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        tz = ZoneInfo(_QUIET_TZ_ENV[1])
    t = (now or _dt.now(_tz.utc)).astimezone(tz)
    m = t.hour * 60 + t.minute
    if start == end:
        return False
    return (start <= m < end) if start < end else (m >= start or m < end)


def intent_dedupe_key(message: str) -> str:
    """The whole normalised body, hashed. Exact content only: a P1 that differs in any word is never deduped."""
    norm = " ".join((message or "").split())
    return "intent:" + hashlib.sha256(norm.encode("utf-8")).hexdigest()[:24]


def _intent_receipts_path() -> Path:
    return Path(os.environ.get(INTENT_RECEIPTS_ENV) or _INTENT_RECEIPTS_DEFAULT)


def record_intent_receipt(route: dict, *, delivered, archived=None) -> None:
    """Append the route decision and its outcome. Best-effort: a receipt failure never blocks a send."""
    row = {"schema": INTENT_RECEIPT_SCHEMA, "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           **{k: route.get(k) for k in ("priority", "decision", "dedupe_key", "window_minutes", "producer",
                                        "quiet_exemption")},
           "delivered": delivered, "archived_report_type": archived,
           "preview": str(route.get("preview") or "")[:80]}
    try:
        p = _intent_receipts_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
    except Exception as e:
        log.warning("intent receipt write failed: %s", type(e).__name__)


def route_intent(message: str, priority: str, *, dedupe_minutes: int | None = None,
                 producer: str | None = None, now=None, message_class: str | None = None) -> dict:
    """Decide one notification intent. Pure apart from reading the durable dedupe store.

    Returns {priority, decision, deliver, dedupe_key, window_minutes, producer, preview}; decision is one of
    DELIVER, DEDUPED (same body inside the window — already delivered), HELD_QUIET_HOURS (P2 only),
    DIGEST (P3 only: archived for the digest, never an interrupt).
    ``dedupe_minutes=0`` turns dedupe off for a producer that already keeps its own send ledger.
    ``message_class`` lets a reviewed quiet-hours exemption (config/notification_intent_quiet_exemptions.json)
    deliver a P2 inside the quiet window; the route then carries ``quiet_exemption``.
    """
    pr = str(priority or "").strip().upper()
    if pr not in INTENT_PRIORITIES:
        raise ValueError(f"notification intent priority must be one of {INTENT_PRIORITIES}, got {priority!r}")
    window = DEFAULT_INTENT_DEDUPE_MINUTES if dedupe_minutes is None else max(0, int(dedupe_minutes))
    key = intent_dedupe_key(message)
    route = {"priority": pr, "dedupe_key": key, "window_minutes": window, "producer": producer,
             "preview": (message or "")[:80]}
    if window and (time.time() - _intent_sent.get(key, 0) < window * 60
                   or _durable_recently_sent(key, window * 60)):
        return {**route, "decision": "DEDUPED", "deliver": False}
    if pr == INTENT_P3:
        return {**route, "decision": "DIGEST", "deliver": False}
    if pr == INTENT_P2 and intent_in_quiet_hours(now):
        exemption = quiet_exemption_for(message_class, pr, now)
        if exemption:
            blocked = _recovery_intent_bound(message, route)
            if blocked is not None:
                return blocked
            return {**route, "decision": "DELIVER", "deliver": True, "quiet_exemption": exemption}
        return {**route, "decision": "HELD_QUIET_HOURS", "deliver": False}
    blocked = _recovery_intent_bound(message, route)
    if blocked is not None:
        return blocked
    return {**route, "decision": "DELIVER", "deliver": True}


def _recovery_intent_bound(message: str, route: dict) -> dict | None:
    """The delivery-owned per-case bound, applied where the page actually goes (cx-openai-2 F5)."""
    if _RECOVERY_T1_MARKER not in message:
        return None
    if recovery_t1_claim(message):
        return None
    record_suppressed(message, "recovery_t1_daily_case_bound")
    return {**route, "decision": "DEDUPED", "deliver": False, "window_minutes": 0,
            "reason": "recovery_t1_daily_case_bound"}


def intent_archive_report_type(route: dict) -> str:
    """The Reports-archive type a held or digested intent is stored under.

    A P3 carries its producer (``notification_intent_p3:<producer>``) because the digest groups by report
    type: one bucket for every FYI producer would fold forty senders into a single line.
    """
    base = INTENT_ARCHIVE_REPORT_TYPE[route["decision"]]
    producer = str(route.get("producer") or "").strip()
    return f"{base}:{producer}" if route["decision"] == "DIGEST" and producer else base


def mark_intent_sent(route: dict) -> None:
    """After a confirmed transport send: make the dedupe window real across processes."""
    key = route.get("dedupe_key")
    if not key or not route.get("window_minutes"):
        return
    _intent_sent[key] = time.time()
    durable_mark_sent(key, meta={"priority": route.get("priority"), "producer": route.get("producer")})
