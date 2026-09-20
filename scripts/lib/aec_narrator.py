"""aec_narrator.py — Telegram Narrator for Autonomous Executive Command Center.

Builds unprompted executive briefs from the shared AEC bus + memory spines.
Default is dry-run (render only). Live Telegram requires --notify and still
passes through telegram_alert.send_telegram (chokepoint).

Constitutional:
  * READ_ONLY_ADVISORY — never sizes, orders, stops, weights.
  * MBI_BEHAVIOR=0 — no behavior fields in the brief payload.
  * Anti-repeat: claim fingerprint vs learning spine.
  * Investment-language briefs defer to CIO stance gate when present.

NO_CONSUMER_REASON: aec_command_center_cycle imports render_executive_brief;
optional notify path is operator-gated (--notify) until a scheduled lane is installed.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

# G2: single spelling, no try/except fallback — see the note in aec_agent_bus.
# The only entrypoint reaching this module (aec_command_center_cycle) is
# root-only + scripts.lib, so the fallback branch was unreachable-but-loaded.
from scripts.lib import aec_agent_bus as bus
from scripts.lib import aec_memory_spines as mem

AUTHORITY = "READ_ONLY_ADVISORY"
MBI_BEHAVIOR = 0
SCHEMA = "AecNarratorBrief@v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fp(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()[:16]


def render_executive_brief(
    *,
    subject_key: str | None = None,
    recent_limit: int = 12,
) -> dict[str, Any]:
    """Compose a concise executive brief from bus + spines (no send)."""
    snap = mem.load()
    relevant = mem.retrieve_relevant(snap, subject_key=subject_key)
    recent = bus.read_recent(limit=recent_limit)
    cio = bus.topics_for("cio_agent", recent)
    adv = bus.topics_for("advisor_agent", recent)
    narr_prior = bus.topics_for("narrator_agent", recent)

    objectives = [r.get("text") or r.get("note") or r.get("kind") for r in (relevant.get("operational") or [])][:5]
    risks = [r.get("text") or r.get("kind") for r in (relevant.get("learning") or []) if "fail" in str(r).lower() or r.get("kind") == "commitment_outcome"][:5]
    thesis = [r.get("text") or r.get("note") or r.get("kind") for r in (relevant.get("strategic") or [])][:5]
    stakeholders = [r.get("name") or r.get("text") or r.get("kind") for r in (relevant.get("relationship") or [])][:5]

    lines = [
        "Trade AI — Executive Brief",
        f"as_of: {_utc_now()}",
        f"subject: {subject_key or 'PORTFOLIO'}",
        "",
        "Context",
        f"- CIO bus events (recent): {len(cio)}",
        f"- Advisor bus events (recent): {len(adv)}",
        f"- Prior narrator briefs (recent): {len(narr_prior)}",
        "",
        "Active objectives",
    ]
    if objectives:
        lines.extend(f"- {o}" for o in objectives if o)
    else:
        lines.append("- (none in operational spine)")
    lines.append("")
    lines.append("Strategic thesis touches")
    if thesis:
        lines.extend(f"- {t}" for t in thesis if t)
    else:
        lines.append("- (none in strategic spine)")
    lines.append("")
    lines.append("Risks / lessons")
    if risks:
        lines.extend(f"- {r}" for r in risks if r)
    else:
        lines.append("- (none flagged)")
    lines.append("")
    lines.append("Relationships")
    if stakeholders:
        lines.extend(f"- {s}" for s in stakeholders if s)
    else:
        lines.append("- (relationship spine empty — no approved domain sources yet)")
    lines.extend(
        [
            "",
            "Authority: READ_ONLY_ADVISORY · MBI_BEHAVIOR=0",
            "Why: closed-loop Command Center cycle; net-new only after anti-repeat check.",
        ]
    )
    body = "\n".join(lines)
    fp = _fp(body)
    repeated = mem.seen_claim(snap, fp)
    return {
        "schema": SCHEMA,
        "as_of": _utc_now(),
        "subject_key": subject_key,
        "body": body,
        "claim_fp": fp,
        "suppressed_repeat": repeated,
        "authority": AUTHORITY,
        "mbi_behavior": MBI_BEHAVIOR,
        "financial_action": False,
        "would_telegram": not repeated,
    }


def notify_executive_brief(
    brief: dict[str, Any],
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Send brief via telegram chokepoint. Default apply=False → dry-run receipt."""
    out = dict(brief)
    out["notify_attempted"] = False
    out["telegram"] = "dry_run"
    if brief.get("suppressed_repeat"):
        out["telegram"] = "suppressed_repeat"
        return out
    if not apply:
        return out
    out["notify_attempted"] = True
    try:
        from telegram_alert import send_telegram  # noqa: WPS433 — production chokepoint

        sent = send_telegram(
            brief["body"],
            bypass_router=True,
            message_class="operator_alert",
        )
        out["telegram"] = "accepted" if sent else "send_returned_false"
    except Exception as e:  # noqa: BLE001 — receipt must record failure class
        out["telegram"] = f"error:{type(e).__name__}:{e}"
    return out
