#!/usr/bin/env python3
"""Weekly review of the AGENTS.md PreToolUse guard hook log.

    python3 scripts/report_agents_guard_hook.py                 # last 7 days, text
    python3 scripts/report_agents_guard_hook.py --days 14 --json
    python3 scripts/report_agents_guard_hook.py --log PATH

Reads ``AgentsGuardDecision@v1`` lines from
``$TRADEAI_STATE_ROOT/data/runtime/agents_guard_hook.jsonl`` (written by
scripts/hooks/agents_guard_pretooluse.py) and prints:

  * counts by rule (would-deny, log-only, allowed-by-grant, actually denied);
  * the top would-deny commands (by command SHA-256, with the redacted preview);
  * false-positive candidates — the evidence the operator reads before flipping to deny;
  * hook errors (fail-open events) and evaluation latency.

The log never holds raw commands; this report only re-prints the redacted previews.
Exit 0 always (a review aid, not a gate). docs/ops/AGENTS_GUARD_HOOK.md says how to read it.

AUTHORITY: READ_ONLY_ADVISORY.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

DECISION_SCHEMA = "AgentsGuardDecision@v1"
REPORT_SCHEMA = "AgentsGuardHookReport@v1"
LOG_RELPATH = Path("data") / "runtime" / "agents_guard_hook.jsonl"
READ_ONLY_PREFIX = re.compile(
    r"^\s*(ls|cat|head|tail|grep|rg|git (status|log|diff|show)|wc|stat|find [^|]*-print|echo|printf|jq|sed -n|awk)\b"
)
REPEAT_THRESHOLD = 3


def default_log_path() -> Path:
    root = os.environ.get("TRADEAI_STATE_ROOT") or str(Path.home() / "trade-ai-releases" / "persistent-state")
    return Path(root) / LOG_RELPATH


def _parse_ts(s: str) -> datetime | None:
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def load(path: Path, since: datetime) -> tuple[list[dict], int]:
    rows, bad = [], 0
    if not path.exists():
        return rows, bad
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except ValueError:
                bad += 1
                continue
            if not isinstance(r, dict) or r.get("schema") != DECISION_SCHEMA:
                bad += 1
                continue
            ts = _parse_ts(r.get("ts", ""))
            if ts is None or ts < since:
                continue
            rows.append(r)
    return rows, bad


def _pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    v = sorted(values)
    return round(v[min(len(v) - 1, int(q * (len(v) - 1) + 0.5))], 2)


def build(rows: list[dict], *, top: int = 15) -> dict:
    by_rule: dict[str, Counter] = defaultdict(Counter)
    cmds: dict[str, dict] = {}
    sessions_per_cmd: dict[str, set] = defaultdict(set)
    errors = []
    lat = []
    for r in rows:
        rid = r.get("rule_id", "?")
        if rid == "hook.error":
            errors.append({"ts": r.get("ts"), "reason": r.get("reason", "")[:200]})
            continue
        c = by_rule[rid]
        c["total"] += 1
        if r.get("would_deny"):
            c["would_deny"] += 1
        if r.get("denied"):
            c["denied"] += 1
        c[str(r.get("rule_action", "?"))] += 1
        if isinstance(r.get("elapsed_ms"), (int, float)):
            lat.append(float(r["elapsed_ms"]))
        if r.get("would_deny"):
            sha = r.get("command_sha256", "")
            e = cmds.setdefault(
                sha,
                {
                    "command_sha256": sha,
                    "preview": r.get("command_preview", ""),
                    "rules": Counter(),
                    "calls": set(),
                    "tool": r.get("tool"),
                },
            )
            e["rules"][rid] += 1
            e["calls"].add((r.get("session_id"), r.get("tool_use_id") or r.get("ts")))
            sessions_per_cmd[sha].add(r.get("session_id"))
    for e in cmds.values():
        e["count"] = len(e.pop("calls"))
    top_cmds = sorted(cmds.values(), key=lambda e: -e["count"])[:top]
    fp = []
    for e in cmds.values():
        why = []
        if len(sessions_per_cmd[e["command_sha256"]]) >= REPEAT_THRESHOLD:
            why.append(f"same command would-deny in {len(sessions_per_cmd[e['command_sha256']])} sessions")
        if READ_ONLY_PREFIX.match(e["preview"] or ""):
            why.append("command looks read-only")
        if e["count"] >= REPEAT_THRESHOLD * 2:
            why.append(f"repeated {e['count']}x (agent kept needing it)")
        if why:
            fp.append(
                {"command_sha256": e["command_sha256"], "preview": e["preview"], "rules": dict(e["rules"]), "why": why}
            )
    fp.sort(key=lambda x: -sum(x["rules"].values()))
    return {
        "schema": REPORT_SCHEMA,
        "decision_schema": DECISION_SCHEMA,
        "records": len(rows),
        "by_rule": {k: dict(v) for k, v in sorted(by_rule.items(), key=lambda kv: -kv[1]["total"])},
        "top_would_deny": [{**e, "rules": dict(e["rules"])} for e in top_cmds],
        "false_positive_candidates": fp[:top],
        "hook_errors": {"count": len(errors), "latest": errors[-5:]},
        "elapsed_ms": {"p50": _pct(lat, 0.5), "p95": _pct(lat, 0.95), "max": max(lat) if lat else None},
        "sessions": len({r.get("session_id") for r in rows}),
    }


def render(rep: dict, days: int, path: Path) -> str:
    out = [
        f"AGENTS.md guard hook — last {days} day(s) — {path}",
        f"records {rep['records']}  sessions {rep['sessions']}  hook errors {rep['hook_errors']['count']}  elapsed_ms {rep['elapsed_ms']}",
        "",
        "By rule (total / would_deny / denied / log-only / allowed_by_grant):",
    ]
    for rid, c in rep["by_rule"].items():
        out.append(
            f"  {rid:32s} {c.get('total', 0):5d} {c.get('would_deny', 0):5d} {c.get('denied', 0):5d} {c.get('log', 0):5d} {c.get('allowed_by_grant', 0):5d}"
        )
    out += ["", "Top would-deny commands:"]
    for e in rep["top_would_deny"]:
        out.append(f"  {e['count']:4d}  {','.join(e['rules'])}  {e['preview'][:140]}")
    out += ["", "False-positive candidates (review each before flipping to deny):"]
    for e in rep["false_positive_candidates"] or []:
        out.append(f"  {','.join(e['rules'])}  [{'; '.join(e['why'])}]  {e['preview'][:120]}")
    if not rep["false_positive_candidates"]:
        out.append("  none")
    for e in rep["hook_errors"]["latest"]:
        out.append(f"  hook.error {e['ts']} {e['reason']}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--log", type=Path, default=None)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    path = a.log or default_log_path()
    since = datetime.now(timezone.utc) - timedelta(days=a.days)
    rows, bad = load(path, since)
    rep = build(rows, top=a.top)
    rep["unparseable_lines"] = bad
    rep["log_path"] = str(path)
    print(json.dumps(rep, indent=2, sort_keys=True) if a.json else render(rep, a.days, path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
