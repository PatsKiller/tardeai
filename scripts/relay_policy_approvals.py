#!/usr/bin/env python3
"""relay_policy_approvals.py -- post the operator's in-app AGENTS.md approvals to their PRs, verbatim.

The Command Center records "Approve version X" (/v3/policy) as the operator's DECIDED row in
data/governance/operator_decisions.jsonl with ``policy_token = APPROVE_AGENTS_POLICY_<X_Y_Z> <pr> <head_sha>``
(scripts/lib/operator_approvals.py). The server has no GitHub write path, so that row is RECORDED_AWAITING_RELAY.
The coordinator runs this script to post the token, and nothing else, as the PR comment the ratify tooling reads
(scripts/lib/policy_ratification.py explains the two equal paths).

It relays a row only when ALL hold: the row is a DECIDED APPROVE of kind POLICY by an authenticated tailnet operator
(hash chain verified by the ledger reader); the token parses; the PR's head is still exactly the token's commit; and
no comment on the PR already equals the token. It never writes the ledger, never edits AGENTS.md, never merges.

  python3 scripts/relay_policy_approvals.py                 # dry run (default): print what would be posted
  python3 scripts/relay_policy_approvals.py --apply [--pr N]

Ledger: --ledger, else <TRADEAI_STATE_ROOT or the persistent state>/data/governance/operator_decisions.jsonl
(scripts/lib/approval_package.governance_dir). Exit 0 ok, 1 a relay failed, 2 usage / unreadable ledger.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import operator_approvals as core  # noqa: E402
from scripts.lib import policy_ratification as ratify  # noqa: E402

REPO = "PatsKiller/tardeai"
GH_TIMEOUT_S = 30


def _gh(args: list[str], run: Callable = subprocess.run, *, parse: bool = True) -> tuple[object | None, str | None]:
    try:
        proc = run(["gh", *args], capture_output=True, text=True, timeout=GH_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, type(exc).__name__
    if proc.returncode != 0:
        return None, ((proc.stderr or "").strip().splitlines() or ["gh failed"])[0][:160]
    if not parse:
        return (proc.stdout or "").strip(), None
    try:
        return (json.loads(proc.stdout) if proc.stdout.strip() else None), None
    except ValueError:
        return None, "unparseable gh output"


def plan(rows: list[dict], *, repo: str, only_pr: int | None, run: Callable = subprocess.run) -> list[dict]:
    """One outcome per distinct approved token (latest row wins)."""
    tokens: dict[str, dict] = {}
    for r in rows:
        tok = r.get("policy_token")
        if tok and ratify.in_app_ratification([r], token=tok):
            tokens[tok] = r
    out = []
    for tok, row in tokens.items():
        parsed = ratify.parse_token(tok)
        if not parsed or (only_pr and parsed["pr"] != only_pr):
            continue
        base = {"token": tok, "pr": parsed["pr"], "ledger_hash": row.get("hash_self"), "actor": row.get("actor"),
                "decided_at": row.get("at")}
        pr, err = _gh(["api", "--method", "GET", f"repos/{repo}/pulls/{parsed['pr']}"], run)
        if not isinstance(pr, dict):
            out.append({**base, "action": "ERROR", "reason": f"pr read failed: {err}"})
            continue
        head = (pr.get("head") or {}).get("sha")
        if head != parsed["head_sha"]:
            out.append({**base, "action": "SKIP_HEAD_MOVED", "reason": f"PR head is {str(head)[:12]}; the approval names "
                        f"{parsed['head_sha'][:12]} -- the operator must approve the new head"})
            continue
        comments, err = _gh(["api", "--method", "GET", f"repos/{repo}/issues/{parsed['pr']}/comments",
                             "--paginate", "--slurp"], run)
        if not isinstance(comments, list):
            out.append({**base, "action": "ERROR", "reason": f"comment read failed: {err}"})
            continue
        flat = [c for page in comments for c in (page if isinstance(page, list) else [page])]
        if any((c.get("body") or "").strip() == tok for c in flat if isinstance(c, dict)):
            out.append({**base, "action": "ALREADY_RELAYED"})
            continue
        out.append({**base, "action": "POST"})
    return out


def main(argv: list[str] | None = None, *, run: Callable = subprocess.run) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", default=True)
    g.add_argument("--apply", action="store_true")
    ap.add_argument("--pr", type=int)
    ap.add_argument("--repo", default=REPO)
    ap.add_argument("--ledger", type=Path)
    a = ap.parse_args(argv)
    path = a.ledger
    if path is None:
        from scripts.lib.approval_package import governance_dir
        path = governance_dir() / "operator_decisions.jsonl"
    try:
        rows = core.DecisionLedger(path, approved=lambda: False).rows()  # read-only; verifies the hash chain
    except core.Refused as exc:
        print(json.dumps({"ok": False, "error": exc.code, "ledger": str(path)}))
        return 2
    failed = 0
    for item in plan(rows, repo=a.repo, only_pr=a.pr, run=run):
        if item["action"] == "POST":
            if a.apply:
                _out, err = _gh(["pr", "comment", str(item["pr"]), "--repo", a.repo, "--body", item["token"]], run, parse=False)
                item["action"] = "POSTED" if err is None else "ERROR"
                if err is None:
                    item["comment_url"] = str(_out)[:300]
                if err:
                    item["reason"] = err
            else:
                item["action"] = "WOULD_POST"
        failed += item["action"] == "ERROR"
        print(json.dumps(item, sort_keys=True))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
