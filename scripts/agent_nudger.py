#!/usr/bin/env python3
"""Repo-owned agent nudger — P1 of the nudger→n8n migration (2026-11-03).

Source of truth: docs/ops/NUDGER_N8N_MIGRATION_PROPOSAL_20261103.md.

This is a faithful port of the coordinator-side ``agent_nudger.py`` that has been running from a host
timer: screen-only BUSY/IDLE detection, a fixed prompt, per-session cooldowns, one ledger line per nudge.
The port exists so the behaviour can be reviewed, tested and then run as an n8n executor lane. It changes
nothing live: no timer, workflow or allowlist entry is touched by this file, and dry run is the default.

Two deliberate differences from the live script:
* **A built-in refusal list.** A session whose NAME matches broker/order/execution terms is never captured
  into a prompt and never typed at, even if the config's refusal list is empty (the config list is unioned
  with the built-in one, never a replacement).
* **Paths come from the caller** (``--state``/``--ledger``/``--config`` or the environment), so a shadow run
  cannot touch the live coordinator state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "NudgerConfig@v1"
DEFAULT_REFUSED = r"(?i)(broker|place_order|\borders?\b|execution|\bmbi\b|alpaca|schwab|moomoo)"

DEFAULTS: dict = {
    "session_regex": r"^(cc-deepseek|cc-anthropic|cx-|cu-|codex$)",
    "exclude": ["codex"],
    "idle_minutes": 4,
    "min_gap_minutes": 10,
    "busy_regex": r"esc to interrupt|Working \(|Thinking|Generating|Running…|to interrupt\)",
    "stall_regex": r"model is at capacity|try a different model|Overloaded|overloaded_error|API Error: 5\d\d|rate limit",
    "stall_gap_minutes": 3,
    "unsent_regex": r"^\s*[❯›] (?!Ask Codex to do anything)(\S.*)$",
    "refused_regex": "",
    "refused_paths": ["/scripts/lib/incident_supervisor.py", "/broker", "/order"],
    "ledger_kind": "nudge",
    "ledger_by": "agent-nudger",
}

RESUME = ("Your last step stopped on a temporary model/API error. Resume your assigned task from where it stopped. "
          "If it is done, report to your coordinator's inbox and take the next PRIORITY QUEUE item.")
PROMPT = ("Heartbeat (automatic, operator mandate): re-read {coord}/WORKERS.md (coordinators: ONBOARDING.md) if you "
          "have not this hour. If you have a task in progress, CONTINUE it now. If it is done, report to your "
          "coordinator's inbox, then read your inbox and the PRIORITY QUEUE in {coord}/BOARD.md and START the next "
          "item. Coordinators: also send the next instruction to every idle worker. Only if there is truly nothing: "
          "write one line 'idle: <reason>' to {coord}/inbox/<lead>/ and stop.")


def load_cfg(path: str | None) -> dict:
    cfg = dict(DEFAULTS)
    if path:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        if str(doc.get("schema") or SCHEMA) != SCHEMA:
            raise SystemExit(f"agent_nudger: config schema {doc.get('schema')!r} is not {SCHEMA}")
        cfg.update({k: v for k, v in doc.items() if k not in ("schema", "_why")})
    return cfg


def refused_regex(cfg: dict) -> str:
    """The built-in list can never be dropped by a config that omits those terms."""
    extra = str(cfg.get("refused_regex") or "")

    def bare(rx: str) -> str:
        return rx[4:] if rx.startswith("(?i)") else rx

    return f"(?i)({bare(DEFAULT_REFUSED)})|({bare(extra)})" if extra else DEFAULT_REFUSED


def refused_session(name: str, cfg: dict) -> bool:
    return bool(re.search(refused_regex(cfg), name))


def tail_of(screen: str, lines: int = 12) -> str:
    return "\n".join([ln for ln in screen.splitlines() if ln.strip()][-lines:])


def decide(screen: str, rec: dict, now: float, cfg: dict) -> dict:
    """Pure decision: no tmux, no writes. Mirrors the live script's order of checks exactly."""
    tail = tail_of(screen)
    h = hashlib.sha256(tail.encode()).hexdigest()
    if rec.get("hash") != h:
        rec["hash"], rec["changed_at"] = h, now
    busy = bool(re.search(str(cfg["busy_regex"]), tail))
    idle_for = (now - float(rec.get("changed_at", now))) / 60
    since_nudge = (now - float(rec.get("nudged_at", 0))) / 60
    last_lines = [ln for ln in screen.splitlines() if ln.strip() and not ln.strip().startswith("─")][-6:]
    joined = "\n".join(last_lines)
    stalled = (not busy) and bool(re.search(str(cfg["stall_regex"]), joined))
    unsent = (not busy) and any(re.match(str(cfg["unsent_regex"]), ln) for ln in last_lines)
    action = "busy" if busy else ("wait" if idle_for < cfg["idle_minutes"] else
                                  ("cooldown" if since_nudge < cfg["min_gap_minutes"] else "NUDGE"))
    if stalled and since_nudge >= cfg["stall_gap_minutes"]:
        action = "RESUME"
    elif unsent and idle_for >= 2 and since_nudge >= cfg["stall_gap_minutes"]:
        action = "ENTER"
    return {"action": action, "hash": h, "idle_for": idle_for, "since_nudge": since_nudge,
            "stalled": stalled, "unsent": unsent, "tail": tail}


def list_sessions(cfg: dict, run=subprocess.run) -> list[str]:
    out = run(["tmux", "ls", "-F", "#S"], capture_output=True, text=True).stdout
    return [s for s in out.split() if re.search(str(cfg["session_regex"]), s)
            and s not in (cfg.get("exclude") or []) and not refused_session(s, cfg)]


def capture(session: str, run=subprocess.run) -> str:
    return run(["tmux", "capture-pane", "-p", "-t", session], capture_output=True, text=True).stdout


def send(session: str, text: str, run=subprocess.run, sleep=time.sleep) -> None:
    run(["tmux", "send-keys", "-t", session, "-l", text], capture_output=True, text=True)
    sleep(0.4)
    run(["tmux", "send-keys", "-t", session, "Enter"], capture_output=True, text=True)


def ledger_line(session: str, detail: str, cfg: dict) -> str:
    return json.dumps({"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                       "by": cfg.get("ledger_by") or "agent-nudger",
                       "territory": "agents", "kind": cfg.get("ledger_kind") or "nudge",
                       "subject": session, "detail": detail, "operator_quote": None})


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Agent nudger (P1, shadow-safe): dry run is the default.")
    ap.add_argument("--apply", action="store_true", help="type into tmux (default: dry run)")
    ap.add_argument("--config")
    ap.add_argument("--state")
    ap.add_argument("--ledger")
    ap.add_argument("--coord-dir", help="directory named in the heartbeat prompt (WORKERS.md/BOARD.md)")
    a = ap.parse_args(argv)
    cfg = load_cfg(a.config)
    coord = a.coord_dir or os.environ.get("TRADEAI_COORD_DIR") or str(Path.home() / "trade-ai-releases"
                                                                     / "persistent-state" / "data" / "coordination"
                                                                     / "coordinator")
    state_path = Path(a.state or os.environ.get("TRADEAI_NUDGER_STATE")
                      or (Path(os.environ.get("TRADEAI_STATE_ROOT") or (Path.home() / "trade-ai-releases"
                                                                        / "persistent-state"))
                          / "data" / "coordination" / "agent_nudger" / "state.json"))
    ledger_path = Path(a.ledger or os.environ.get("TRADEAI_NUDGER_LEDGER")
                       or state_path.with_name("ledger.jsonl"))
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    now = time.time()
    out, plan = [], []
    for s in list_sessions(cfg):
        rec = state.get(s, {})
        d = decide(capture(s), rec, now, cfg)
        action = d["action"]
        detail = {"RESUME": "vendor error on screen; resume prompt sent",
                  "ENTER": "unsent text in the input box; Enter pressed",
                  "NUDGE": f"idle {d['idle_for']:.0f} min, no busy marker; heartbeat prompt sent"}.get(action)
        if detail is None:
            pass
        elif not a.apply:
            plan.append(ledger_line(s, detail, cfg))          # shown as "would:" — nothing is typed or written
        elif action == "RESUME":
            send(s, RESUME, run=subprocess.run)
            rec["nudged_at"] = now
        elif action == "ENTER":
            # tmux resolves from PATH on purpose; the session name passed the config regex and the refusal list
            subprocess.run(["tmux", "send-keys", "-t", s, "Enter"],  # noqa: S603, S607
                           capture_output=True, text=True)
            rec["nudged_at"] = now
        else:
            send(s, PROMPT.format(coord=coord), run=subprocess.run)
            rec["nudged_at"] = now
        if detail is not None and a.apply:
            ledger_path.parent.mkdir(parents=True, exist_ok=True)
            with open(ledger_path, "a", encoding="utf-8") as fh:
                fh.write(ledger_line(s, detail, cfg) + "\n")
        state[s] = rec
        out.append(f"{s:16} {action:8} idle={d['idle_for']:4.0f}m since_nudge={min(d['since_nudge'], 9999):5.0f}m")
    if a.apply:
        tmp = state_path.with_suffix(".tmp")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, state_path)
    print(("APPLY" if a.apply else "DRY RUN") + f" @ {time.strftime('%H:%M:%S')}\n" + "\n".join(out))
    if not a.apply:
        for ln in plan:
            print("would: " + ln)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
