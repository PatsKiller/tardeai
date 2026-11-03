#!/usr/bin/env python3
"""Reopen ONE blocked incident for a retry — with its own evidence, never a bulk close (2026-11-03).

The supervisor never re-triages `blocked` incidents, so a stale agent blocker sits forever even
after its condition changes. This helper is the narrow, reversible door back: one incident per
call, an explicit evidence line recorded on the event, a dry run by default, and a refusal for
every operator-only scope (broker/order/stop/credential/secret/.env/policy/guard/SIEM/ledger/
governance) — those stay a person's decision.

    python3 scripts/incident_requeue.py --id INC-... --evidence "condition still failing: ..."   # dry
    python3 scripts/incident_requeue.py --id INC-... --evidence "..." --apply
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from lib import incidents as L  # noqa: E402

CONFIG = ROOT / "config" / "incident_runbook_actions.json"
ACTOR = "incident_requeue"
DEFAULT_REFUSED = (r"(?i)(schwab|alpaca|moomoo|broker|place_order|\borders?\b|\bstops?\b|stop[-_ ]loss|sizing|"
                   r"\bsize\b|weight|mbi|active[-_ ]?trader|execution|2fa|credential|secret|\.env\b|api[-_ ]?key|"
                   r"token|agents\.md|guard|\.githooks|mergify|siem|ledger)")


def refused_regex(config_path: Path = CONFIG) -> str:
    try:
        doc = json.loads(Path(config_path).read_text(encoding="utf-8"))
        return str((doc.get("policy") or {}).get("refused_scope_regex") or DEFAULT_REFUSED)
    except (OSError, ValueError):
        return DEFAULT_REFUSED


def _text(rec: dict) -> str:
    parts = [str(rec.get("title") or ""), str(rec.get("blocked_reason") or ""), str(rec.get("handoff") or "")]
    return " ".join(parts)


def requeue(incident_id: str, *, evidence: str, d: Path | None = None, apply: bool = False,
            config_path: Path = CONFIG) -> dict:
    """Dry by default. Returns {ok, refused?, before, after, evidence}."""
    evidence = str(evidence or "").strip()
    out: dict = {"id": incident_id, "evidence": evidence, "apply": bool(apply)}
    if len(evidence) < 12:
        return {**out, "ok": False, "refused": "evidence is required (what makes a retry justified now)"}
    d = d or L.incidents_dir()
    recs = L.fold(L.read_events(d))
    rec = recs.get(incident_id)
    if rec is None:
        return {**out, "ok": False, "refused": f"no such incident {incident_id}"}
    out["before"] = rec.get("status")
    if rec.get("status") != "blocked":
        return {**out, "ok": False, "refused": f"{incident_id} is {rec.get('status')}, not blocked"}
    rx = refused_regex(config_path)
    hit = re.search(rx, _text(rec))
    if hit:
        return {**out, "ok": False, "refused": f"operator-only scope: {hit.group(0)!r} is a person's decision"}
    out["ok"] = True
    if not apply:
        out["after"] = "open (dry run — nothing written)"
        return out
    ev = {"kind": "reopen", "incident_id": incident_id, "actor": ACTOR,
          "detail": {"evidence": evidence[:400], "requeued_by": ACTOR}}
    rec2 = L.append_event(ev, d=d)
    out["after"] = rec2.get("status")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--id", required=True)
    ap.add_argument("--evidence", required=True)
    ap.add_argument("--apply", action="store_true", help="write the reopen event (default: dry run)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    res = requeue(a.id, evidence=a.evidence, apply=a.apply)
    print(json.dumps(res, indent=1) if a.json else
          f"{res['id']}: {res.get('before')} -> {res.get('after')} ok={res['ok']}"
          + (f" refused: {res['refused']}" if res.get("refused") else ""))
    return 0 if res.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
