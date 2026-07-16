"""Watch Desk v2 (B1/B4): creation-time family gate for watch directives.

The 07-01 cleanup (489 → ~150 active-class) regrew to 387 in 15 days because
creation-time dedup was exact-label only and lived in one producer. This gate
is the single fence every trend-directive creator consults BEFORE insert:

  - same canonical family + active survivor exists → do NOT create; attach the
    incoming label/rationale as an alias enriching the survivor's spec
  - active-trend cap reached (config, not code) → status='proposed' (never
    auto-archive actives to make room; scope-governor S2 alignment)

Never deletes; only aliases and proposes.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

CONFIG_PATH = ROOT / "config" / "watch_directive_governance.json"
DEFAULTS = {"active_trend_cap": 150, "gate_enabled": True}


def _cfg() -> dict:
    try:
        return {**DEFAULTS, **json.loads(CONFIG_PATH.read_text(encoding="utf-8"))}
    except Exception:
        return dict(DEFAULTS)


def family_gate(label: str, kind: str = "trend") -> dict[str, Any]:
    """Consult before any trend-directive INSERT.

    Returns {allow, survivor_id, survivor_label, propose, reason}.
      allow=False  → do not insert; call attach_alias(survivor_id, ...)
      propose=True → insert with status='proposed' (cap reached)
    Fail-open: any error returns allow=True so producers never crash on the gate.
    """
    out = {"allow": True, "survivor_id": None, "survivor_label": None,
           "propose": False, "reason": None}
    if kind != "trend":
        return out
    cfg = _cfg()
    if not cfg.get("gate_enabled", True):
        return out
    try:
        from db_adapter import _execute
        from watch_directive_canonical import canonical_family
        fam = canonical_family(label)
        if fam:
            rows = _execute(
                """SELECT wd.id, wd.label,
                          (SELECT count(*) FROM watch_directive_hits h WHERE h.directive_id = wd.id) AS hits
                   FROM watch_directives wd
                   WHERE wd.kind = 'trend' AND wd.status = 'active'""",
                fetch="all",
            ) or []
            candidates = [r for r in rows if canonical_family(r["label"]) == fam]
            if candidates:
                surv = max(candidates, key=lambda r: r.get("hits") or 0)
                out.update(allow=False, survivor_id=surv["id"], survivor_label=surv["label"],
                           reason=f"family '{fam}' already active as #{surv['id']} '{surv['label']}'")
                return out
        cap = int(cfg.get("active_trend_cap") or 0)
        if cap:
            n = _execute("SELECT count(*) AS n FROM watch_directives WHERE kind='trend' AND status='active'",
                         fetch="one") or {"n": 0}
            if int(n["n"]) >= cap:
                out.update(propose=True,
                           reason=f"active trend cap {cap} reached ({n['n']}) — insert as status='proposed'")
    except Exception:
        return {"allow": True, "survivor_id": None, "survivor_label": None,
                "propose": False, "reason": "gate error — fail-open"}
    return out


def attach_alias(survivor_id: int, label: str, *, rationale: str | None = None,
                 keywords: list | None = None, created_by: str = "") -> bool:
    """Enrich the surviving directive instead of creating a near-dup:
    append to spec.aliases[], merge any new keywords, refresh last_confirmed_at."""
    try:
        from db_adapter import _execute
        row = _execute("SELECT spec FROM watch_directives WHERE id=%s", (survivor_id,), fetch="one")
        spec = row["spec"] if row else {}
        if isinstance(spec, str):
            spec = json.loads(spec or "{}")
        spec = spec or {}
        aliases = spec.get("aliases") or []
        if label not in aliases:
            aliases.append(label)
        spec["aliases"] = aliases[:40]
        if keywords:
            kw = list(dict.fromkeys((spec.get("keywords") or []) + list(keywords)))
            spec["keywords"] = kw[:60]
        notes = spec.get("alias_notes") or []
        if rationale:
            notes.append({"from": created_by or "unknown", "alias": label,
                          "rationale": str(rationale)[:300]})
        spec["alias_notes"] = notes[-20:]
        _execute("""UPDATE watch_directives
                    SET spec=%s::jsonb, last_confirmed_at=NOW(), updated_at=NOW()
                    WHERE id=%s""",
                 (json.dumps(spec, default=str), survivor_id), fetch=None)
        return True
    except Exception:
        return False
