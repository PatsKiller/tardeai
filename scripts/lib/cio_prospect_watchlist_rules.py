"""Watchlist curation rules for the CIO prospect (shadow; PROPOSES, never writes).

Rules live in ``config/cio_prospect_watchlist_rules.json`` (status PROPOSED, operator decision §17):

* **One membership** per ``security_guid`` — several candidate origins collapse into one row whose
  origin is the strongest (protected origins first) and which lists every other origin as support.
* **Ways in** — every membership names an origin and a non-empty reason; a reasonless candidate is refused.
* **Ways out** — a non-protected member whose evidence expired (``expires_at`` + grace) or which is
  invalidated (stance AVOID, thesis invalidated, a stale exit) is proposed out.
* **Size cap per stage** — over the cap, the lowest-conviction non-protected members are proposed out.
* **Operator adds / stars and held positions are never auto-dropped** — they are flagged for review.

Pure functions over plain dicts. AUTHORITY: READ_ONLY_ADVISORY; MBI_BEHAVIOR = 0 (membership is
attention, never size, order or stop). Nothing here touches ``watchlist_items``.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

RULES_PATH = Path(__file__).resolve().parents[2] / "config" / "cio_prospect_watchlist_rules.json"
PROTECTED_ORDER = ("operator_star", "operator_add", "held_position")
ORIGIN_ORDER = PROTECTED_ORDER + ("cio_curator", "cio_thesis", "reentry_desk", "scanner_verdict", "hermes",
                                  "existing_member")


def load_rules(path: Path | str | None = None) -> dict[str, Any]:
    return json.loads(Path(path or RULES_PATH).read_text(encoding="utf-8"))


def _ts(v: Any) -> Optional[datetime]:
    if not v:
        return None
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def is_protected(origin: str, rules: dict[str, Any]) -> bool:
    spec = ((rules.get("ways_in") or {}).get("origins") or {}).get(origin) or {}
    return bool(spec.get("protected"))


def membership(candidates: Iterable[dict[str, Any]], rules: dict[str, Any]) -> dict[str, Any]:
    """Collapse a security's candidate origins into ONE membership (or a refusal).

    Each candidate is ``{"origin", "reason", "at"}``. Unknown origins and empty reasons are refused
    (listed in ``refused``) — a way in always has a reason.
    """
    known = (rules.get("ways_in") or {}).get("origins") or {}
    accepted, refused = [], []
    for c in candidates:
        origin = str((c or {}).get("origin") or "")
        reason = str((c or {}).get("reason") or "").strip()
        if origin not in known:
            refused.append({**c, "refused": "unknown_origin"})
        elif not reason:
            refused.append({**c, "refused": "no_reason"})
        else:
            accepted.append({"origin": origin, "reason": reason, "at": c.get("at")})
    if not accepted:
        return {"member": False, "origin": None, "reason": None, "support": [], "refused": refused,
                "protected": False}
    accepted.sort(key=lambda c: ORIGIN_ORDER.index(c["origin"]) if c["origin"] in ORIGIN_ORDER else 99)
    head = accepted[0]
    return {
        "member": True,
        "origin": head["origin"],
        "reason": head["reason"],
        "since": head.get("at"),
        "support": accepted[1:],
        "refused": refused,
        "protected": any(is_protected(c["origin"], rules) for c in accepted),
    }


def exit_reason(prospect: dict[str, Any], rules: dict[str, Any], *, now: datetime) -> Optional[str]:
    """Why a member should leave (expiry / invalidation), or None."""
    out = rules.get("ways_out") or {}
    exp = _ts(prospect.get("expires_at"))
    grace = float(out.get("expiry_grace_hours") or 0)
    if exp is not None and now > exp + timedelta(hours=grace):
        return f"expired: evidence expired {exp.isoformat()} (+{grace:g}h grace)"
    if prospect.get("stance") == "AVOID":
        return "invalidated: stance AVOID"
    thesis = str(((prospect.get("research") or {}).get("thesis_stance")) or "").lower()
    if thesis in ("avoid", "invalidated"):
        return f"invalidated: thesis stance {thesis}"
    if prospect.get("stage") == "exit":
        changed = _ts(prospect.get("stage_changed_at"))
        keep = float(out.get("exit_retention_days") or 0)
        if changed is not None and now > changed + timedelta(days=keep):
            return f"invalidated: exit since {changed.date()} without re_entry (> {keep:g} days)"
    return None


def curate(prospects: list[dict[str, Any]], rules: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    """Apply ways-out and the per-stage size caps to prospects carrying a ``watchlist`` membership.

    Mutates nothing in place; returns ``{"decisions": {security_guid: {...}}, "by_stage": {...},
    "summary": {...}}``. Each decision is ``keep`` / ``propose_out`` / ``review`` (protected member
    that a rule would otherwise drop) with the reason.
    """
    caps = {k: v for k, v in (rules.get("size_cap_per_stage") or {}).items() if not k.startswith("_")}
    decisions: dict[str, dict[str, Any]] = {}
    for p in prospects:
        wl = p.get("watchlist") or {}
        if not wl.get("member"):
            continue
        guid = p["security_guid"]
        why = exit_reason(p, rules, now=now)
        if why and wl.get("protected"):
            decisions[guid] = {"decision": "review", "reason": f"protected ({wl.get('origin')}); {why}"}
        elif why:
            decisions[guid] = {"decision": "propose_out", "reason": why}
        else:
            decisions[guid] = {"decision": "keep", "reason": wl.get("reason")}

    by_stage: dict[str, dict[str, Any]] = {}
    for stage, cap in caps.items():
        members = [p for p in prospects if p.get("stage") == stage
                   and decisions.get(p["security_guid"], {}).get("decision") == "keep"]
        unprotected = [p for p in members if not (p.get("watchlist") or {}).get("protected")]
        over = 0 if cap is None else max(0, len(members) - int(cap))
        if over:
            unprotected.sort(key=lambda p: (float(p.get("conviction") or 0.0), str(p.get("evidence_at") or "")))
            for p in unprotected[:over]:
                decisions[p["security_guid"]] = {
                    "decision": "propose_out",
                    "reason": f"size cap: stage {stage} holds {len(members)} > cap {cap}; "
                              f"lowest conviction {float(p.get('conviction') or 0):.1f}",
                }
        by_stage[stage] = {"members": len(members), "cap": cap, "over_cap": over,
                           "protected": len(members) - len(unprotected)}
    counts: dict[str, int] = {}
    for d in decisions.values():
        counts[d["decision"]] = counts.get(d["decision"], 0) + 1
    return {"decisions": decisions, "by_stage": by_stage, "summary": counts,
            "rules_status": rules.get("status"), "writes": "none (shadow; proposes only)"}
