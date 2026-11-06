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

#: The n8n lane `agent_nudge` (config/lane_registry.json, stage shadow, dry run only) is this file's scheduled
#: entrypoint. The host cron that has run since 2026-11-02 invokes the COORDINATOR-side copy, not this one — cc3
#: (2026-11-04) blocked an earlier declaration that claimed it — and this file must not be added to a host cron:
#: promoting the lane past shadow is an operator decision.
SCHEDULED_ENTRYPOINT = "n8n lane agent_nudge (config/lane_registry.json), stage shadow, dry run only; no host cron runs this file"

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

#: FQ-093 (lead dispatch, 2026-11-04): a generic "go read the board" heartbeat makes an idle session spend a turn
#: finding out what to do, and most stop after that turn. The nudger now names the row instead: the session's first
#: `queued` item in the audit fix queue, with its page, check and acceptance. A missing or half-written queue file
#: falls back to the generic heartbeat — the nudger must never fail because another process is rewriting the queue.
QUEUE_DEFAULT = str(Path.home() / "trade-ai-releases" / "persistent-state" / "data" / "coordination"
                    / "coordinator" / "AUDIT_FIX_QUEUE.json")

#: One line, no ``\n``: ``send()`` types this with ``tmux send-keys -l`` and then a separate ``Enter``. An embedded
#: newline is a separate tmux line event, so a multi-line prompt would type without submitting (the repository's own
#: recorded multi-line trap). The sentence breaks below are source formatting only.
ROW_PROMPT = ("Heartbeat (automatic, operator mandate). Your next queue row is {id}{sev} — {page}{check}. "
              "Acceptance: {acceptance} "
              "Work it now: claim the files, fix the root cause, produce red-then-green evidence, then report the head "
              "sha to {coord}/inbox/<lead>/ and take your next row. If it no longer reproduces at the current head, "
              "close it as no_longer_reproduces with the measurement that shows it gone. Only if there is truly "
              "nothing: write one line 'idle: <reason>' to {coord}/inbox/<lead>/ and stop.")



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


def queue_row_for_session(session: str, queue_path: str | None = None) -> dict | None:
    """The session's first `queued` row in the audit fix queue, or None.

    Pure and total: an unreadable, half-written or unexpected file yields None, never an exception. The queue lists
    rows in priority order, so "first" is the row the session should work next — no re-sorting here.
    """
    path = Path(queue_path or os.environ.get("TRADEAI_AUDIT_QUEUE") or QUEUE_DEFAULT)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    items = doc.get("items") if isinstance(doc, dict) else doc
    if not isinstance(items, list):
        return None
    for item in items:
        if not isinstance(item, dict):
            continue
        if str(item.get("owner") or "") != session:
            continue
        if str(item.get("status") or "") != "queued":
            continue
        return item
    return None


def acceptance_text(row: dict | None) -> str:
    """Acceptance as one line: the dict's what/expected/actual (and evidence) or the raw string."""
    acceptance = (row or {}).get("acceptance")
    if isinstance(acceptance, dict):
        parts = []
        for key in ("what", "expected", "actual", "evidence"):
            # The queue is data another process writes: a value may carry a line break. Collapse it here so an
            # interpolated value can never reintroduce the newline the single-line send path forbids (F3, cc5).
            value = " ".join(str(acceptance.get(key) or "").split())
            if value:
                parts.append(f"{key.capitalize()}: {value}")
        return " ".join(parts)
    return " ".join(str(acceptance or "").split())


def _cap(text: str, limit: int = 600) -> str:
    """tmux types this in one keystroke burst; a very long row is truncated and the file named instead."""
    return text if len(text) <= limit else text[:limit].rstrip() + " … (full row in AUDIT_FIX_QUEUE.json)"


def row_prompt(row: dict, coord: str) -> str:
    """The nudge text for one queue row, as ONE line: `send()` types it then presses Enter.

    The row is data from another process, so every interpolated field is whitespace-collapsed here as well as in
    ``acceptance_text``: a repair that flattened only the template would let a newline back in through the values.
    """
    rid = " ".join(str(row.get("id") or "row").split())
    severity = " ".join(str(row.get("severity") or "").split())
    page = " ".join(str(row.get("page") or "no page").split())
    check = " ".join(str(row.get("check") or "").split())
    text = ROW_PROMPT.format(
        id=rid,
        sev=f" [{severity}]" if severity else "",
        page=page,
        check=f" · check {check}" if check else "",
        acceptance=_cap(acceptance_text(row)) or "the row's expected result (see AUDIT_FIX_QUEUE.json)",
        coord=coord,
    )
    return " ".join(text.split())



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


def list_sessions(cfg: dict, run=subprocess.run) -> tuple[list[str], bool]:
    """(sessions, ok). `ok` is False when `tmux ls` itself failed (F1, cc3 2026-11-04).

    A failed discovery must not read as "no sessions": a broken tmux server and a quiet machine produced the same
    attempted_count 0 / empty_reason nothing_due, so the evidence could not tell "blind" from "quiet".
    """
    proc = run(["tmux", "ls", "-F", "#S"], capture_output=True, text=True)
    ok = getattr(proc, "returncode", 1) == 0
    out = proc.stdout or ""
    return [s for s in out.split() if re.search(str(cfg["session_regex"]), s)
            and s not in (cfg.get("exclude") or []) and not refused_session(s, cfg)], ok


def capture(session: str, run=subprocess.run) -> tuple[str, bool]:
    """(screen, ok). A failed capture must never become a DECISION about the session: an empty screen has no busy
    marker, so the old code turned a broken pane into "idle" and then into nothing_due (F1, cc3 2026-11-04)."""
    proc = run(["tmux", "capture-pane", "-p", "-t", session], capture_output=True, text=True)
    return (proc.stdout or ""), getattr(proc, "returncode", 1) == 0


def send(session: str, text: str, run=subprocess.run, sleep=time.sleep) -> bool:
    """Type text then Enter. Returns True ONLY when both `tmux` calls exited 0 (F3 review, 2026-11-04).

    A non-zero rc used to be discarded, so a dead tmux pane produced a ledger line and an inflated produced_count —
    a nudge that never happened, counted as one that did.

    The text is flattened to one line first: ``send-keys -l`` treats an embedded newline as a separate tmux line
    event, so the following ``Enter`` would submit only one line of a multi-line prompt (the repository's recorded
    multi-line trap). Flattening here is defence in depth for every caller, including a malformed row (F2, cc6/cc9).
    """
    text = " ".join(str(text).split())
    typed = run(["tmux", "send-keys", "-t", session, "-l", text], capture_output=True, text=True)
    if getattr(typed, "returncode", 1) != 0:
        return False
    sleep(0.4)
    sent = run(["tmux", "send-keys", "-t", session, "Enter"], capture_output=True, text=True)
    return getattr(sent, "returncode", 1) == 0


def ledger_line(session: str, detail: str, cfg: dict) -> str:
    return json.dumps({"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                       "by": cfg.get("ledger_by") or "agent-nudger",
                       "territory": "agents", "kind": cfg.get("ledger_kind") or "nudge",
                       "subject": session, "detail": detail, "operator_quote": None})


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Agent nudger (P1, shadow-safe): dry run is the default.")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="type into tmux (default: dry run)")
    #: Explicit dry-run flag (P2). The n8n executor's shadow step requires a NON-EMPTY dry_run_arg
    #: (scripts/lib/lane_dispatch.py, "the shadow step needs a real dry run"), so the lane names its
    #: dry run rather than relying on the bare-command default. Behaviour is identical to no flag.
    mode.add_argument("--dry-run", action="store_true", help="explicit dry run (the default; required as the lane's dry_run_arg)")
    ap.add_argument("--config")
    ap.add_argument("--state")
    ap.add_argument("--ledger")
    ap.add_argument("--coord-dir", help="directory named in the heartbeat prompt (WORKERS.md/BOARD.md)")
    ap.add_argument("--queue", help="audit fix queue JSON whose rows are named in the nudge "
                                    f"(default: $TRADEAI_AUDIT_QUEUE or {QUEUE_DEFAULT})")
    a = ap.parse_args(argv)
    started_at = datetime.now(timezone.utc).isoformat()
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
    would_type: list[tuple[str, str]] = []
    sessions, discovery_ok = list_sessions(cfg)
    wanted = 0
    failed = 0
    blind = 0
    inspected = 0
    for s in sessions:
        rec = state.get(s, {})
        screen, observed = capture(s)
        if not observed:
            # Not inspected, not counted, and not turned into a verdict. The session stays in state untouched so the
            # next healthy run decides with the same evidence plus whatever the pane shows then.
            blind += 1
            out.append(f"{s:16} {'BLIND':8} capture failed; not inspected")
            continue
        inspected += 1
        d = decide(screen, rec, now, cfg)
        action = d["action"]
        # FQ-093: name the session's next queue row in the nudge instead of a generic "go read the board".
        row = queue_row_for_session(s, a.queue) if action == "NUDGE" else None
        nudge_text = row_prompt(row, coord) if row else PROMPT.format(coord=coord)
        row_note = (f"next queue row {row.get('id')} ({row.get('page')})" if row else "no queued row for this session")
        detail = {"RESUME": "vendor error on screen; resume prompt sent",
                  "ENTER": "unsent text in the input box; Enter pressed",
                  "NUDGE": f"idle {d['idle_for']:.0f} min, no busy marker; nudge sent · {row_note}"}.get(action)
        if detail is None:
            pass
        elif not a.apply:
            wanted += 1
            plan.append(ledger_line(s, detail, cfg))          # shown as "would:" — nothing is typed or written
            # CX1 (codex-cloud 2026-11-05): the ledger detail names only the row id and page; the ACCEPTANCE text
            # exists only inside the message. AGENTS.md §6 requires a dry run to report the message it would send,
            # and a preview that does not vary with the acceptance cannot be reviewed before permitting keystrokes.
            would_type.append((s, {"NUDGE": nudge_text, "RESUME": RESUME, "ENTER": "<Enter>"}.get(action, "")))
        elif action == "RESUME":
            if send(s, RESUME, run=subprocess.run):
                rec["nudged_at"] = now
            else:
                failed += 1
        elif action == "ENTER":
            # tmux resolves from PATH on purpose; the session name passed the config regex and the refusal list
            entered = subprocess.run(["tmux", "send-keys", "-t", s, "Enter"],  # noqa: S603, S607
                                     capture_output=True, text=True)
            if getattr(entered, "returncode", 1) == 0:
                rec["nudged_at"] = now
            else:
                failed += 1
        else:
            if send(s, nudge_text, run=subprocess.run):
                rec["nudged_at"] = now
            else:
                failed += 1
        if detail is not None and a.apply and rec.get("nudged_at") == now:
            wanted += 1
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
        for session, message in would_type:
            print(f"would type to {session}: {message}")
    # LaneOutput@v1 (scripts/lib/lane_output.py): ONE bounded line on stderr in every mode, so the executor can bind a
    # run to what it produced and the contract's expected_output rule has something executable to read. A dry run
    # reports what it WOULD have typed; `nothing_due` is the honest empty reason when no session needed a nudge.
    try:
        from scripts.lib.lane_output import emit as _emit_lane_output, output_block as _lane_output_block
    except ImportError:  # scripts/ on sys.path (cron / direct execution)
        from lib.lane_output import emit as _emit_lane_output, output_block as _lane_output_block  # type: ignore
    produced = wanted   # dry: what it WOULD type; live: what it TYPED (a refused tmux send is not a nudge).
    skipped = {"send_failed": failed} if failed else {}
    if not discovery_ok or blind:
        # The contract lists dependency_unavailable among its fatal skip reasons; before this the producer could never
        # emit it, so the rule and the code disagreed. A blind run says so instead of reporting a quiet one.
        skipped["dependency_unavailable"] = 1 if not discovery_ok else blind
        empty_reason = "dependency_unavailable" if not produced else None
    else:
        empty_reason = None if produced else "nothing_due"
    block = _lane_output_block(produced=produced, attempted=inspected, unit="agent nudges typed",
                               skipped=skipped, empty_reason=empty_reason)
    _emit_lane_output("agent_nudge", "live" if a.apply else "dry_run", block, started_at=started_at)
    degraded = (not discovery_ok) or blind
    if a.apply:
        # A LIVE run writes LaneRunReceipt@v2 plus the immutable per-attempt receipt that
        # scripts/n8n_run_executor.py::apply_output_verdict reads. Without it the contract's rule is declared and never
        # evaluated (the `declared_not_enforced` path) — a rule that only fails in a test. Never written in dry run:
        # a dry run has no receipt by definition (`dry_run_exempt`).
        try:
            try:
                from scripts.lib.lane_last_receipt import write_lane_receipt as _write_receipt
            except ImportError:  # scripts/ on sys.path
                from lib.lane_last_receipt import write_lane_receipt as _write_receipt  # type: ignore
            # A blind run is NOT ok (F2, cc3/cx-openai-2 2026-11-04): the producer said dependency_unavailable and the
            # settlement must agree with it.
            _write_receipt("agent_nudge", ok=not degraded, started_at=started_at, script="scripts/agent_nudger.py",
                           produced_count=produced, attempted_count=len(sessions), skipped_reasons=skipped,
                           empty_reason=empty_reason,
                           summary={"sessions": len(sessions), "send_failed": failed})
        except Exception as exc:  # noqa: BLE001 -- the run's own result comes first
            print(f"[agent_nudge] lane receipt write failed: {type(exc).__name__}", file=sys.stderr)
    # F2 (cc3 + cx-openai-2, 2026-11-04): exit 0 said RUN_DONE even when the producer had just reported
    # dependency_unavailable — the executor settled a blind run as a successful shadow run. A run that could not
    # OBSERVE did not succeed. 2 is the lane's "ran, could not observe" code; a genuine quiet run stays 0.
    return 2 if degraded else 0


if __name__ == "__main__":
    raise SystemExit(main())
