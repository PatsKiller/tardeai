#!/usr/bin/env python3
"""Fail when a session leaves an incident ``open`` or ``fixing`` (operator 2026-10-27: "they can't just drop and leave it").

  check_open_incidents.py --session <id> [--warn-only] [--json]

Exit 1 when the session opened or owns an unresolved incident (``blocked`` with a handoff is fine: the next step is
recorded). The claim board calls this on ``stage … pr_open`` and ``release`` as a WARNING today; enforcement is the
``INCIDENT_CHECK_ENFORCE=1`` flag (docs/ops/INCIDENT_LEDGER.md). An unreadable ledger is reported, never a pass.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.lib import incidents as L  # noqa: E402


def check(session: str, d: Path | None = None) -> dict:
    d = d or L.incidents_dir()
    rows = L.unresolved_for_session(L.load_records(d), session)
    return {"session": session, "unresolved": [{"id": r["id"], "status": r["status"], "title": r["title"]} for r in rows],
            "ok": not rows, "ledger": str(d)}


def message(res: dict) -> str:
    if res["ok"]:
        return f"incidents: none left open by {res['session']}"
    lines = [f"incidents: {len(res['unresolved'])} left unresolved by {res['session']} — fix (incident.py fix ID --ref …) "
             f"or hand off (incident.py block ID --reason … --handoff …):"]
    lines += [f"  {r['id']} [{r['status']}] {r['title'][:100]}" for r in res["unresolved"]]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--session", default=os.environ.get("AGENT_CLAIM_SESSION"))
    ap.add_argument("--warn-only", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if not a.session:
        print("--session (or AGENT_CLAIM_SESSION) is required", file=sys.stderr)
        return 2
    res = check(a.session)
    print(json.dumps(res, indent=1) if a.json else message(res))
    return 0 if res["ok"] or a.warn_only else 1


if __name__ == "__main__":
    raise SystemExit(main())
