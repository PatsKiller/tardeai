"""llm_route_policy.py — Command Center fleet LLM routing policy (2026-08-03).

Operator policy (authoritative):
  * DeepSeek Flash is the DEFAULT for agents, watchlist, portfolio risk-ish,
    LLM intelligence enrichment, and Hermes bulk research.
  * DeepSeek Pro (deepseek-v4 / reasoner) is OPTIONAL and restricted.

Pro (deepseek-v4) may be used ONLY when:
  1. Operator clicks DeepSeek v4 / Paid critic on MAIN ticket desk
  2. Explicit --lane deepseek-v4 / --use-pro on a CLI
  3. Premium ticket review (paid expert path)
  4. Documented CIO escalation after Flash + dual free lanes disagree or fail
  5. Monthly / meta arbitration jobs that already require heavy reasoning

Pro must NOT be the default for cron agents, watchlist CIO synthesis, Hermes
batch research, portfolio risk enrichment, or home LLM intelligence.
"""
from __future__ import annotations

from typing import Iterable

# Canonical lane ids (llm_lane.generate)
FLASH = "deepseek-flash"
PRO = "deepseek-v4"
LOCAL = "local"
GROK = "grok"
CHATGPT = "chatgpt"

DEFAULT_LANE = FLASH

# Free multi-lane critics for MAIN desk (no Pro by default)
FREE_CRITIC_LANES: tuple[str, ...] = (FLASH, LOCAL, GROK, CHATGPT)

# Process families → default lane
PROCESS_DEFAULTS: dict[str, str] = {
    "agent": FLASH,
    "watchlist_agent": FLASH,
    "watchlist_cio_synthesis": FLASH,
    "watchlist_entry_planner": FLASH,
    "portfolio_risk": FLASH,
    "portfolio_ai_analyst": FLASH,
    "holding_protection": FLASH,
    "llm_intelligence": FLASH,
    "hermes": FLASH,
    "hermes_research": FLASH,
    "hermes_external": FLASH,
    "main_desk_critics": FLASH,
    "ticket_review": FLASH,  # bulk; Pro only via operator button
}

# Cadences (documentation + runners). Host local time (ET on this box).
CADENCE: dict[str, dict] = {
    "watchlist_flash": {
        "desc": "MAIN/watchlist Flash critics once per trading day unless data unchanged",
        "schedule": "weekdays 09:30 ET",
        "lane": FLASH,
        "skip_if_fresh_hours": 20,
    },
    "portfolio_risk_flash": {
        "desc": "Portfolio risk-ish Flash enrichment",
        "schedule": "hourly 07-19 weekdays; once 10:00 weekends",
        "lane": FLASH,
    },
    "llm_intelligence_flash": {
        "desc": "Home/LLM intelligence Flash briefings",
        "schedule": "weekdays 07:20, 12:20, 16:20",
        "lane": FLASH,
    },
    "agents_flash": {
        "desc": "Watchlist agent jobs + synthesis use Flash (not Pro)",
        "schedule": "existing agent job queues (every 5–15m market hours)",
        "lane": FLASH,
    },
    "hermes_flash": {
        "desc": "Hermes bulk research prefers Flash",
        "schedule": "existing Hermes timers",
        "lane": FLASH,
    },
}


def default_lane(process_id: str | None = None) -> str:
    """Return the policy default lane for a process family."""
    if not process_id:
        return DEFAULT_LANE
    key = str(process_id).strip().lower()
    if key in PROCESS_DEFAULTS:
        return PROCESS_DEFAULTS[key]
    for prefix, lane in PROCESS_DEFAULTS.items():
        if key.startswith(prefix) or prefix in key:
            return lane
    return DEFAULT_LANE


# Processes that may use Pro without a separate force flag (still not cron bulk).
_PRO_PROCESS_ALLOW = {
    "ticket_review",           # only when operator clicked v4 (manual_trigger)
    "premium_ticket_review",
    "cio_escalation",
    "operator_manual",
    "monthly_protection_meta",
}


def allow_pro(
    process_id: str | None = None,
    *,
    manual_trigger: bool = False,
    force_pro: bool = False,
) -> bool:
    """Whether Pro may be invoked for this call.

    Cron/agent bulk never gets Pro unless force_pro=True (CLI override).
    Operator desk v4 button sets manual_trigger=True + process_id=ticket_review.
    """
    if force_pro:
        return True
    pid = (process_id or "").lower().strip()
    if manual_trigger and pid in _PRO_PROCESS_ALLOW:
        return True
    if pid in {"premium_ticket_review", "monthly_protection_meta", "cio_escalation"}:
        return True
    return False


def resolve_lane(
    requested: str | None = None,
    *,
    process_id: str | None = None,
    manual_trigger: bool = False,
    force_pro: bool = False,
) -> str:
    """Resolve the lane to call. Downgrades unauthorized Pro to Flash."""
    req = (requested or "").strip().lower() or None
    if req in {PRO, "deepseek-reasoner", "pro", "deepseek-v4-pro"}:
        if allow_pro(process_id, manual_trigger=manual_trigger, force_pro=force_pro):
            return PRO
        return FLASH
    if req in {FLASH, "deepseek", "deepseek-chat", "deepseek-v4-flash"}:
        return FLASH
    if req in {LOCAL, GROK, CHATGPT}:
        return req
    return default_lane(process_id)


def free_critic_lanes_csv() -> str:
    return ",".join(FREE_CRITIC_LANES)


def filter_pro_from_lanes(lanes: Iterable[str], *, allow: bool = False) -> list[str]:
    out = []
    for lane in lanes:
        l = str(lane).strip().lower()
        if not l:
            continue
        if l in {PRO, "deepseek-reasoner", "pro"} and not allow:
            continue
        out.append(l if l not in {"deepseek-reasoner", "pro"} else PRO)
    return out


def policy_summary() -> dict:
    return {
        "default_lane": DEFAULT_LANE,
        "pro_lane": PRO,
        "free_critic_lanes": list(FREE_CRITIC_LANES),
        "process_defaults": dict(PROCESS_DEFAULTS),
        "cadence": CADENCE,
        "pro_allowed_when": [
            "Operator DeepSeek v4 / Paid button on MAIN ticket desk",
            "CLI --lane deepseek-v4 or --use-pro",
            "Premium ticket review",
            "Documented CIO escalation after Flash + free dual lanes fail/disagree",
            "Monthly meta arbitration jobs",
        ],
    }
