#!/usr/bin/env python3
"""n8n_cutover_wave.py — the cutover factory: cron lane -> n8n canary -> cutover, in waves (2026-10-15).

Operator directive 2026-10-15 ("N8N Cutover Decision"): every MIGRATE_N8N lane, and every STAY_HOST lane outside F07
and registry_systemd, moves to n8n under the AGENTS.md §23.21 cutover standard (fix + dry run + regression + at least
one live n8n run with the cron line still present; no soaks). This tool does the per-lane config work the same way for
every lane so a wave is one reviewed PR instead of hand edits.

Subcommands (all offline unless named; none of them calls a broker, reads a secret or sends anything):

  plan     --lanes a,b | --scope       JSON verdict per lane: READY_CANARY / ALREADY_CANARY / SKIP (+ exact reasons),
                                        tier (1 read/overwrite, 2 append, 3 send, 4 llm, 5 watchdog, 6 broker), the
                                        live cron line(s), lock, live argv and the config changes it would make.
  apply    --lanes a,b --wave N        writes the READY lanes into --code-root: registry row -> cron canary
                                        (stage canary, command_text = live line, dispatch.mode live), allowlist
                                        live_arg = the cron argv and lock = the cron flock lock, health contract stage
                                        canary, effect key armed (n8n_claim + cron_claim true) for tier >= 2.
  cutover  --lanes a,b                 registry rows -> the §23.11 dispatcher row (kind n8n, expression dispatcher,
                                        stage cutover, match kept, cadence = dispatch.cron). For the PR after the
                                        wave's cron lines were commented (the host act below).
  contract-canary --lanes a,b [--apply]  REVIEWED health contract stage shadow -> canary for lanes already at
                                        canary (registry cron canary + dispatch live + a live n8n fire);
                                        agent-reviewed contracts only, unless --operator-rereview "<words>".
  packet   --lanes a,b --wave N --out  the operator packet: README, live_lanes.txt, 01_relay_live_lanes.sh,
                                        02_effect_owners.sh, 04_comment_cron.sh, 09_rollback.sh.
  comment-cron --lanes a,b [--apply]   HOST act (cron grant): ONE crontab write commenting every live line of the
                                        lanes as `# RETIRED <date> n8n-cutover <lane> ` (the _cutover.py tag, so
                                        `_cutover.py rollback --lane` still works); backup first, read back after.

Validation for every generated row/entry is the platform's own: lane_dispatch.dispatch_eligible,
r1_class_admission (canary lock rule), validate_dispatch_block, executor validate_entry, effect_claim config loader,
and the health-contract rule (REVIEWED, no UNKNOWN, at canary). A lane that fails any of them is SKIP with the gate's
own reason string; the tool never widens a gate.

Expected-output rules (N8nExpectedOutput@v1): NOT generated until PR #1778 (with its per-lane `output_receipt: v2`
runtime gate) is on main; a rule on a lane that writes no LaneRunReceipt@v2 would turn every live run into
RUN_FAILED output_unverifiable (scripts/lib/n8n_output_verdict.py). See --with-expected-output.

AUTHORITY: READ_ONLY_ADVISORY except `apply`/`cutover` (files under --code-root) and `comment-cron --apply` (crontab).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shlex
import subprocess
import sys
import time
from datetime import date as dt_date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib import lane_dispatch as LD  # noqa: E402
from scripts.lib.cutover_lane_facts import (  # noqa: E402,F401  (moved 2026-10-16; re-exported)
    ALLOWLIST,
    APPEND_CLASSES,
    APPEND_OVERRIDE,
    BROKER_FAMILIES,
    CONTRACTS,
    DEFERRED_FAMILIES,
    DEFERRED_SOURCES,
    DISPOSITION_CSV,
    EFFECT_CLAIM_WRAPPER,
    EFFECT_KEYS,
    HELD,
    LLM_FAMILIES,
    OVERWRITE_ONLY,
    REGISTRY,
    RETRY_POLICIES,
    SCOPE_DISPOSITIONS,
    SEND_FAMILIES,
    TAG,
    TIER_APPEND,
    TIER_BROKER,
    TIER_LLM,
    TIER_NAMES,
    TIER_READ,
    TIER_SEND,
    TIER_WATCHDOG,
    WATCHDOG_FAMILIES,
    _ARGV_STOP,
    _MARKET_GATE,
    _OFFPEAK_FLAGS,
    _OFFPEAK_WRAPPER,
    _PREFIX_OK,
    _SENDER,
    is_sender_lane,
    live_lines,
    load_disposition,
    matches_of,
    scope_rows,
    tier_of,
)

NO_CONSUMER_REASON = (
    "Operator/agent CLI for the 2026-10-15 n8n cutover waves; it writes config files in a worktree and the wave "
    "packets under docs/ops/packets/n8n-cutover-wave-*-20261015/. Nothing imports it at runtime."
)



# ── loading ────────────────────────────────────────────────────────────────────────────────────

def _load(code_root: Path, rel: Path) -> Any:
    return json.loads((code_root / rel).read_text(encoding="utf-8"))


def _dump_like(path: Path, doc: Any) -> None:
    """Write JSON the way these config files are written (indent 2, utf-8, trailing newline)."""
    raw = path.read_text(encoding="utf-8")
    ensure_ascii = "\\u" in raw and not any(ord(ch) > 127 for ch in raw)
    text = json.dumps(doc, indent=2, ensure_ascii=ensure_ascii) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)




def read_crontab(path: Optional[str]) -> str:
    if path:
        return Path(path).read_text(encoding="utf-8")
    proc = subprocess.run([os.environ.get("CRONTAB_CMD", "crontab"), "-l"], capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise SystemExit(f"REFUSED: crontab -l failed: {proc.stderr.strip()[:160]}")
    return proc.stdout


# ── cron line parsing ──────────────────────────────────────────────────────────────────────────



def schedule_of(line: str) -> str:
    parts = line.split()
    return " ".join(parts[:5]) if len(parts) >= 6 and not line.startswith("@") else ""


def command_of(line: str) -> str:
    """The cron line without the schedule and without a trailing `# comment`."""
    parts = line.split(None, 5)
    body = parts[5] if len(parts) == 6 else ""
    # strip a trailing comment that is not inside quotes
    try:
        toks = shlex.split(body, comments=True, posix=True)
        del toks
    except ValueError:
        pass
    m = re.search(r"\s#\s", body)
    return body[: m.start()].rstrip() if m else body.rstrip()


def _tokens(cmd: str) -> list[str]:
    try:
        return shlex.split(cmd, posix=True)
    except ValueError:
        return cmd.split()


#: The env var that switches the effect-claim wrapper on for one lane (scripts/effect_claim_cron.sh: OFF unless it
#: equals the wrapper's LANE_ID argument).
EFFECT_CLAIM_ENV = "TRADEAI_EFFECT_CLAIM"


def _is_effect_claim_wrapper(tok: str) -> bool:
    return tok == EFFECT_CLAIM_WRAPPER or tok.endswith("/" + EFFECT_CLAIM_WRAPPER)


def parse_lane_argv(cmd: str, entry_command: list[str], lane_id: Optional[str] = None) -> dict[str, Any]:
    """Locate the allowlist command inside the cron command and return the live argv, wrappers and problems.

    The lane command is found by its script token (the first entry token ending .py/.sh); every token after the
    script up to the first shell operator is the cron argv. Tokens of the entry command that follow the script must
    be the first cron args (they are already in `command`); the rest is live_arg.

    2026-10-23 (T-20261023-f7771f): the §23.25 cron-side effect-claim wrapper is recognised, not reported as an
    unmapped wrapper. `[env] TRADEAI_EFFECT_CLAIM=<lane> bash scripts/effect_claim_cron.sh <lane> <command>` is
    cron-only: it makes the cron twin claim the same fx: key the n8n executor claims (n8n_claim), so the executor
    has nothing to reproduce. It is accepted only when it is switched ON for its own lane (env value == wrapper
    lane argument, and == `lane_id` when the caller names one); otherwise the wrapper is a pass-through `exec` and
    the line is not effect-claimed, which is a problem, never a silent pass. Every other env assignment stays
    unmapped (the executor does not reproduce it)."""
    toks = _tokens(cmd)
    problems: list[str] = []
    script = next((t for t in entry_command if t.endswith((".py", ".sh")) and "/" in t), None)
    if script is None:
        return {"problems": ["allowlist_command_has_no_script"], "live_arg": None}
    idx = next((i for i, t in enumerate(toks) if t == script or t.endswith("/" + script)), None)
    if idx is None:
        return {"problems": [f"script_not_on_cron_line:{script}"], "live_arg": None}
    args: list[str] = []
    for t in toks[idx + 1:]:
        if t in _ARGV_STOP or t.startswith(">>") or t.startswith("2>") or t.startswith(">"):
            break
        args.append(t)
    cmd_tail = entry_command[entry_command.index(script) + 1:]
    if args[: len(cmd_tail)] != cmd_tail:
        problems.append(f"allowlist_command_args_not_on_cron_line:{cmd_tail} vs {args}")
        live = None
    else:
        live = args[len(cmd_tail):]
    # wrappers before the script (back to the last shell operator segment start)
    seg_start = 0
    for i in range(idx):
        if toks[i] in ("&&", ";", "||"):
            seg_start = i + 1
    prefix = toks[seg_start:idx]
    market_gate = _MARKET_GATE in prefix or any(t.endswith("/market_day_gate.sh") for t in prefix)
    offpeak = None
    unmapped: list[str] = []
    claim_env: list[str] = []          # values of TRADEAI_EFFECT_CLAIM=... in the prefix
    claim_lanes: list[str] = []        # LANE_ID arguments of effect_claim_cron.sh in the prefix
    has_wrapper = any(_is_effect_claim_wrapper(t) for t in prefix)
    i = 0
    while i < len(prefix):
        t = prefix[i]
        if has_wrapper and t == "env":
            # `env VAR=val ... cmd`: the assignments are judged one by one below; `env` itself is inert.
            i += 1
            continue
        if has_wrapper and t.startswith(EFFECT_CLAIM_ENV + "="):
            claim_env.append(t.split("=", 1)[1])
            i += 1
            continue
        if _is_effect_claim_wrapper(t):
            claim_lanes.append(prefix[i + 1] if i + 1 < len(prefix) else "")
            i += 2
            continue
        if t.endswith("run_with_deepseek_offpeak.sh"):
            nxt = prefix[i + 1] if i + 1 < len(prefix) else ""
            offpeak = _OFFPEAK_FLAGS.get(nxt, "bulk" if nxt == "--" else None)
            if offpeak is None:
                unmapped.append(f"{t} {nxt}")
            i += 1
            while i < len(prefix) and prefix[i] != "--" and prefix[i].startswith("-"):
                i += 1
            if i < len(prefix) and prefix[i] == "--":
                i += 1
            continue
        if t.endswith("market_day_gate.sh") or _PREFIX_OK.match(t) or t.startswith("/tmp/") or t.startswith("$PY"):
            i += 1
            continue
        if re.match(r"^[A-Z_][A-Z0-9_]*=", t):
            unmapped.append(f"env:{t.split('=', 1)[0]}")
            i += 1
            continue
        unmapped.append(t)
        i += 1
    for u in unmapped:
        problems.append(f"unmapped_wrapper:{u}")
    effect_claim: Optional[str] = None
    if claim_lanes:
        wl = claim_lanes[0]
        if len(claim_lanes) > 1 or len(claim_env) > 1:
            problems.append(f"effect_claim_wrapper_repeated:lanes={claim_lanes} env={claim_env}")
        elif not wl or wl.startswith("-") or wl.startswith("$"):
            problems.append(f"effect_claim_wrapper_no_lane_arg:{wl!r}")
        elif claim_env != [wl]:
            problems.append(f"effect_claim_wrapper_off ({EFFECT_CLAIM_ENV}={claim_env[0] if claim_env else '<unset>'}"
                            f" does not switch on wrapper lane {wl!r}: the wrapper execs the command unclaimed)")
        elif lane_id is not None and wl != lane_id:
            problems.append(f"effect_claim_wrapper_lane_mismatch:{wl} (registry lane {lane_id})")
        else:
            effect_claim = wl
    if any(t.endswith("safe_flock.sh") for t in toks[:idx]):
        problems.append("cron_line_uses_safe_flock (executor live lock is flock; needs a flock -n line first)")
    return {"problems": problems, "live_arg": live, "cron_args": args, "market_gate": market_gate,
            "offpeak_gate": offpeak, "script": script, "effect_claim": effect_claim}


# ── per-lane builders ──────────────────────────────────────────────────────────────────────────

def canary_row(row: Mapping[str, Any], lines: list[tuple[int, str]], wave: str) -> dict[str, Any]:
    new = json.loads(json.dumps(row))
    sched = new.setdefault("scheduler", {})
    sched["stage"] = "canary"
    live_text = " ; ".join(command_of(ln) for _, ln in lines) if len(lines) > 1 else command_of(lines[0][1])
    old_text = sched.get("command_text")
    # Keep a recorded command_text that already names the same flock lock(s) and is (part of) the live line: earlier
    # waves recorded it with or without the schedule prefix, and both satisfy r1_canary_lock_matches.
    keep = (isinstance(old_text, str) and LD.cron_flock_locks(old_text) == LD.cron_flock_locks(live_text)
            and any(command_of(ln) in old_text or old_text in ln for _, ln in lines))
    sched["command_text"] = old_text if keep else live_text
    sched["cutover_wave"] = wave
    slots = []
    for _, ln in lines:
        s = schedule_of(ln)
        if s and s not in slots:
            slots.append(s)
    if len(slots) == 1:
        sched["expression"] = slots[0]
    block = new.get("dispatch") if isinstance(new.get("dispatch"), dict) else None
    if block is not None:
        block["mode"] = "live"
        block["cron"] = slots
    return new


def canary_entry(entry: Mapping[str, Any], parsed: Mapping[str, Any], lock: str, wave: str) -> dict[str, Any]:
    new = json.loads(json.dumps(entry))
    new["live_arg"] = list(parsed["live_arg"])
    new["lock"] = lock
    new["lock_kind"] = "flock"
    if parsed.get("market_gate"):
        new["market_gate"] = True
    if parsed.get("offpeak_gate"):
        new["offpeak_gate"] = parsed["offpeak_gate"]
    note = (f" | {wave} 2026-10-15 (n8n_cutover_wave.py): canary — live_arg = the cron line's argv "
            f"{parsed['live_arg']!r}, lock = the cron flock lock {lock} (shared: the lock proves no double run).")
    src = str(new.get("source") or "")
    if wave not in src:
        new["source"] = src + note
    return new


def armed_effect_key(lane_id: str, spec: Optional[Mapping[str, Any]], slots: list[str], wave: str,
                     tier: int) -> dict[str, Any]:
    out = dict(spec) if spec else {
        "process": lane_id,
        "input_version": "v1",
        "slot": "scheduled_minute",
        "schedule": slots[0] if len(slots) == 1 else slots,
        "slot_tz": "America/New_York",
        "effects": ["send" if tier == TIER_SEND else ("llm" if tier == TIER_LLM else "append")],
        "idempotent_today": "no: not traced; one effect per scheduled slot is enforced by this key",
        "wave": wave,
    }
    out["n8n_claim"] = True
    out["cron_claim"] = True
    return out


def contract_problems(contract: Optional[Mapping[str, Any]]) -> list[str]:
    if contract is None:
        return ["no_health_contract (generate with build_n8n_health_contracts.py and REVIEW before canary)"]
    out = []
    if contract.get("status") != "REVIEWED":
        out.append(f"health_contract_status:{contract.get('status')} (canary needs REVIEWED: DRAFT_AT_LIVE_STAGE)")
    if "UNKNOWN" in json.dumps(contract):
        out.append("health_contract_has_UNKNOWN_fields (DRAFT_AT_LIVE_STAGE)")
    return out


AGENT_REVIEWER = "agent n8n_cutover_wave.py 2026-10-15"


def agent_review(contract: Mapping[str, Any], entry: Mapping[str, Any], lock: Optional[str]
                 ) -> tuple[Optional[dict[str, Any]], str]:
    """A DRAFT contract becomes REVIEWED (agent-reviewed, the SW4 / LD-W1 precedent) only when its machine-checkable
    edges agree with the allowlist and the cron line: no UNKNOWN field, the runner edge names the allowlist script,
    the lock edge names the cron flock lock, the receipt edge names the allowlist output_signal (when one is set).
    Anything else stays DRAFT and the lane is skipped with the reason. The operator's REVIEW pass is still owed."""
    if "UNKNOWN" in json.dumps(contract):
        return None, "UNKNOWN fields"
    edges = contract.get("connects_to") or []
    names = " ".join(str(e.get("name")) for e in edges if isinstance(e, Mapping))
    script = next((t for t in entry.get("command") or [] if str(t).endswith((".py", ".sh"))), None)
    if not script or script not in names:
        return None, f"runner edge does not name {script!r}"
    if lock and not any(isinstance(e, Mapping) and e.get("kind") == "lock" and e.get("name") == lock for e in edges):
        return None, f"lock edge is not the cron lock {lock!r}"
    sig = entry.get("output_signal")
    if sig and not any(isinstance(e, Mapping) and e.get("kind") == "receipt" and str(sig) in str(e.get("name"))
                       for e in edges):
        return None, f"receipt edge does not name output_signal {sig!r}"
    new = json.loads(json.dumps(contract))
    new["status"] = "REVIEWED"
    rev = dict(new.get("review") or {})
    rev.update({"status": "REVIEWED", "reviewed_by": AGENT_REVIEWER + " (machine cross-check of runner, lock and "
                "receipt edges against config/n8n_run_allowlist.json and the live cron line; operator REVIEW pass "
                "still owed)", "reviewed_on": "2026-10-15"})
    rev.setdefault("prepared_by", "build_n8n_health_contracts.py DRAFT")
    new["review"] = rev
    return new, ""


def canary_contract(contract: Mapping[str, Any], wave: str, date: str = "2026-10-15") -> dict[str, Any]:
    new = json.loads(json.dumps(contract))
    new["stage"] = "canary"
    healthy = [h for h in new.get("healthy") or [] if h.get("check") not in ("shadow_dry_run_done",)]
    if not any(h.get("check") == "canary_live_done" for h in healthy):
        healthy.insert(0, {"check": "canary_live_done",
                           "text": "every dispatcher fire of this lane ends RUN_DONE in mode live, or "
                                   "RUN_SKIPPED_LOCK while the cron twin holds the shared flock (coordination ledger)"})
    new["healthy"] = healthy
    note = f"{wave} {date}: stage canary (n8n_cutover_wave.py); cron twin present until the wave's cron act."
    new["state_note"] = (str(new.get("state_note") or "") + " | " + note).lstrip(" |")
    return new


# ── plan ───────────────────────────────────────────────────────────────────────────────────────

def plan_lane(lane_id: str, disp: Mapping[str, str], *, reg_rows: Mapping[str, Any], entries: Mapping[str, Any],
              contracts: Mapping[str, Any], effect_keys: Mapping[str, Any], crontab: str, wave: str,
              max_tier: int = TIER_BROKER, process_ids: Optional[Iterable[str]] = None,
              review_drafts: bool = False, policy: Optional[Mapping[str, Any]] = None,
              include_p1: bool = False) -> dict[str, Any]:
    v: dict[str, Any] = {"lane_id": lane_id, "row_id": disp.get("row_id"), "family_id": disp.get("family_id"),
                         "source": disp.get("source"), "disposition": disp.get("disposition"),
                         "status": "SKIP", "reasons": []}
    reasons: list[str] = v["reasons"]
    if disp.get("family_id") in DEFERRED_FAMILIES or disp.get("source") in DEFERRED_SOURCES:
        reasons.append("deferred_by_directive (F07 / registry_systemd)")
        return v
    if lane_id in HELD:
        reasons.append(HELD[lane_id])
        return v
    row = reg_rows.get(lane_id)
    if row is None:
        reasons.append("no_registry_row")
        return v
    sched = row.get("scheduler") if isinstance(row.get("scheduler"), dict) else {}
    entry = entries.get(lane_id)
    v["stage_before"] = sched.get("stage")
    v["kind_before"] = sched.get("kind")
    if sched.get("kind") == "n8n":
        v["status"] = "ALREADY_N8N"
        reasons.append(f"scheduler.kind n8n (stage {sched.get('stage')!r}): already on n8n")
        return v
    if sched.get("kind") != "cron":
        reasons.append(f"scheduler.kind {sched.get('kind')!r}: no cron line to cut over (source {disp.get('source')})")
        return v
    if row.get("state") not in (None, "ACTIVE"):
        reasons.append(f"registry_state:{row.get('state')}")
        return v
    lines, probs = live_lines(crontab, sched)
    v["cron_lines"] = [{"line": i + 1, "text": ln} for i, ln in lines]
    reasons.extend(probs)
    line_text = " ".join(ln for _, ln in lines)
    tier = tier_of(disp, row, entry, effect_keys, line_text)
    v["tier"], v["tier_name"] = tier, TIER_NAMES[tier]
    if probs:
        return v
    # 2026-10-16 (operator gate-alignment approval, AGENTS 12.0.0 §23.25): P1 lanes move last, and a sender's cron
    # twin must refuse itself once n8n owns the effect (factory finding: owner=n8n alone does not stop the cron run).
    pol = policy if policy is not None else LD.load_cutover_policy()
    if lane_id in (pol.get("p1_last") or ()):
        v["cutover_tier"] = "p1_last"
        if not include_p1:
            reasons.append("p1_last: moves after every non-P1 lane of the directive (operator 2026-10-16); "
                           "plan it with --include-p1")
    if is_sender_lane(disp, row, effect_keys, line_text) and EFFECT_CLAIM_WRAPPER not in line_text:
        reasons.append(f"sender_cron_not_effect_claimed: wrap the cron line with {EFFECT_CLAIM_WRAPPER} "
                       "(TRADEAI_EFFECT_CLAIM=<lane>) before canary so the cron twin refuses once n8n owns the effect")
    if entry is None:
        reasons.append("not_allowlisted (needs shadow onboarding first: allowlist entry with a proven write-free "
                       "--dry-run, receipt output_signal, REVIEWED contract; AGENTS onboarding steps 3-8)")
        return v
    if not isinstance(row.get("dispatch"), dict):
        reasons.append("no_dispatch_block (lane not at shadow yet)")
        return v
    locks: list[str] = []
    for _, ln in lines:
        locks.extend(LD.cron_flock_locks(command_of(ln)))
    if not locks:
        reasons.append("no_cron_flock (the cron line has no `flock -n <lock>`: a crontab edit must add it before "
                       "canary, §23.12)")
    elif len(set(locks)) > 1:
        reasons.append(f"several_cron_locks:{sorted(set(locks))}")
    lock = locks[0] if locks else None
    parsed_all = [parse_lane_argv(command_of(ln), list(entry.get("command") or []), lane_id) for _, ln in lines]
    for p in parsed_all:
        reasons.extend(p["problems"])
    lives = {json.dumps(p.get("live_arg")) for p in parsed_all}
    if len(lives) > 1:
        reasons.append(f"cron_lines_disagree_on_argv:{sorted(lives)}")
    parsed = parsed_all[0]
    if parsed.get("live_arg") is not None:
        bad = [t for t in parsed["live_arg"] if t == "--dry-run"]
        if bad:
            reasons.append("cron_line_runs_--dry-run (the live line itself is a dry run)")
    v["lock"] = lock
    v["live_arg"] = parsed.get("live_arg")
    if tier > max_tier:
        reasons.append(f"tier {tier} ({TIER_NAMES[tier]}) is after this wave's max tier {max_tier}")
    contract = contracts.get(lane_id)
    if review_drafts and contract is not None and contract.get("status") == "DRAFT":
        reviewed, why = agent_review(contract, entry, lock)
        if reviewed is not None:
            contract = reviewed
            v["contract_agent_reviewed"] = True
        else:
            reasons.append(f"health_contract_DRAFT_not_agent_reviewable:{why}")
    if not any(r.startswith("health_contract_DRAFT") for r in reasons):
        reasons.extend(contract_problems(contract))
    if reasons:
        return v
    if sched.get("stage") == "canary" and (entry.get("live_arg") == parsed["live_arg"]) and entry.get("lock") == lock:
        v["status"] = "ALREADY_CANARY"
    new_row = canary_row(row, lines, wave)
    new_entry = canary_entry(entry, parsed, lock, wave)
    # the platform's own gates, on the rows this tool would write
    from n8n_run_executor import validate_entry  # noqa: PLC0415
    bad = validate_entry(new_entry)
    if bad:
        reasons.append(f"executor_validate_entry:{bad}")
    argv_map = {lane_id: " ".join([*new_entry.get("command", []), *(new_entry.get("live_arg") or [])])}
    ok, why = LD.dispatch_eligible(new_row, allowlist_argv=argv_map)
    if not ok:
        reasons.append(f"dispatch_eligible:{why}")
    ok, why = LD.r1_class_admission(new_row, new_entry, process_ids=process_ids, allowlist_argv=argv_map)
    if not ok:
        reasons.append(f"r1_class_admission:{why}")
    klass = (new_row.get("dispatch") or {}).get("class")
    for issue in LD.validate_dispatch_block(new_row):
        # validate_dispatch_block re-runs r1_class_admission against the allowlist FILE (the old entry); the R1 answer
        # for the entry this tool writes is the explicit call above, so only non-R1 class issues are taken from here.
        if issue.code == LD.ISSUE_CLASS_NOT_PERMITTED and klass in LD.R1_ADMITTED_CLASSES:
            continue
        reasons.append(f"validate_dispatch_block:{issue.code}:{issue.detail}")
    slots = new_row["dispatch"]["cron"]
    v["slots"] = slots
    changes: dict[str, Any] = {"registry": new_row, "allowlist": new_entry}
    if v.get("contract_agent_reviewed"):
        # Only a contract this tool agent-reviewed is rewritten (stage canary). An operator-REVIEWED contract is kept
        # byte for byte: refreshing it is an operator re-review, never an agent edit (tests/test_canary_wave_20261014.py).
        changes["contract"] = canary_contract(contract, wave)
    if tier >= TIER_APPEND:
        changes["effect_key"] = armed_effect_key(lane_id, effect_keys.get(lane_id), slots, wave, tier)
    v["changes"] = changes
    if reasons:
        v["status"] = "SKIP"
        return v
    if v.get("status") != "ALREADY_CANARY":
        v["status"] = "READY_CANARY"
    return v


def build_plan(code_root: Path, crontab: str, lanes: Optional[list[str]], wave: str,
               max_tier: int = TIER_BROKER, review_drafts: bool = False, include_p1: bool = False) -> dict[str, Any]:
    disp_rows = scope_rows(load_disposition(code_root))
    by_lane = {r["lane_id"]: r for r in disp_rows}
    reg = _load(code_root, REGISTRY)
    reg_rows = {r["lane_id"]: r for r in reg.get("lanes") or [] if isinstance(r, dict)}
    entries = {e["lane_id"]: e for e in _load(code_root, ALLOWLIST).get("lanes") or [] if isinstance(e, dict)}
    contracts = {c["id"]: c for c in _load(code_root, CONTRACTS).get("contracts") or []
                 if isinstance(c, dict) and c.get("kind") == "lane"}
    effect_keys = _load(code_root, EFFECT_KEYS).get("lanes") or {}
    process_ids = LD.load_llm_process_ids(code_root / "config" / "llm_process_registry.json")
    policy = LD.load_cutover_policy(code_root / "config" / "lane_cutover_policy.json")
    targets = lanes if lanes else sorted(by_lane)
    out = []
    for lid in targets:
        disp = by_lane.get(lid)
        if disp is None:
            out.append({"lane_id": lid, "status": "SKIP", "reasons": ["not_in_directive_scope (disposition csv)"]})
            continue
        out.append(plan_lane(lid, disp, reg_rows=reg_rows, entries=entries, contracts=contracts,
                             effect_keys=effect_keys, crontab=crontab, wave=wave, max_tier=max_tier,
                             process_ids=process_ids, review_drafts=review_drafts, policy=policy,
                             include_p1=include_p1))
    counts: dict[str, int] = {}
    for v in out:
        counts[v["status"]] = counts.get(v["status"], 0) + 1
    return {"schema": "N8nCutoverWavePlan@v1", "wave": wave, "generated_at": _now(), "counts": counts, "lanes": out}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── apply / cutover ────────────────────────────────────────────────────────────────────────────

def apply_plan(code_root: Path, plan: Mapping[str, Any]) -> list[str]:
    ready = [v for v in plan["lanes"] if v["status"] in ("READY_CANARY", "ALREADY_CANARY") and v.get("changes")]
    if not ready:
        return []
    reg_p, al_p, c_p, fx_p = (code_root / p for p in (REGISTRY, ALLOWLIST, CONTRACTS, EFFECT_KEYS))
    reg, al, cdoc, fx = (json.loads(p.read_text(encoding="utf-8")) for p in (reg_p, al_p, c_p, fx_p))
    want = {v["lane_id"]: v["changes"] for v in ready}
    reg["lanes"] = [want[r["lane_id"]]["registry"] if isinstance(r, dict) and r.get("lane_id") in want else r
                    for r in reg["lanes"]]
    al["lanes"] = [want[e["lane_id"]]["allowlist"] if isinstance(e, dict) and e.get("lane_id") in want else e
                   for e in al["lanes"]]
    cdoc["contracts"] = [want[c["id"]]["contract"] if isinstance(c, dict) and c.get("kind") == "lane"
                         and "contract" in want.get(c.get("id"), {}) else c for c in cdoc["contracts"]]
    for lid, ch in want.items():
        if "effect_key" in ch:
            fx["lanes"][lid] = ch["effect_key"]
    for p, d in ((reg_p, reg), (al_p, al), (c_p, cdoc), (fx_p, fx)):
        _dump_like(p, d)
    return sorted(want)


def cutover_rows(code_root: Path, lanes: list[str], wave: str) -> list[str]:
    """Registry rows -> the §23.11 dispatcher row (what _cutover.py writes for --workflow-id dispatcher)."""
    reg_p = code_root / REGISTRY
    reg = json.loads(reg_p.read_text(encoding="utf-8"))
    done = []
    for r in reg["lanes"]:
        if not isinstance(r, dict) or r.get("lane_id") not in lanes:
            continue
        sched = r.get("scheduler") or {}
        if sched.get("kind") != "cron" or sched.get("stage") != "canary":
            raise SystemExit(f"REFUSED: {r['lane_id']} is not a cron canary row ({sched.get('kind')}/{sched.get('stage')})")
        slots = list((r.get("dispatch") or {}).get("cron") or [])
        new = {"kind": "n8n", "expression": LD.DISPATCHER_EXPRESSION, "match": sched.get("match"),
               "cadence": slots[0] if slots else sched.get("expression"), "stage": "cutover",
               "wave": sched.get("wave"), "cutover_wave": wave,
               "command_text": sched.get("command_text")}
        if len(slots) > 1:
            new["cadence_slots"] = slots
        r["scheduler_before_cutover"] = sched
        r["scheduler"] = {k: v for k, v in new.items() if v is not None}
        done.append(r["lane_id"])
    missing = sorted(set(lanes) - set(done))
    if missing:
        raise SystemExit(f"REFUSED: no registry row for {missing}")
    _dump_like(reg_p, reg)
    return done


RUNS_DIR = Path.home() / "trade-ai-releases/persistent-state/data/runtime/n8n_runs"


def live_fires(lane_id: str, runs_dir: Path = RUNS_DIR) -> list[str]:
    """Run ids of the dispatcher's LIVE fires of `lane_id` (n8n_runs/d:<lane>:live:<slot>.json), oldest first."""
    try:
        return sorted(p.stem for p in Path(runs_dir).glob(f"d:{lane_id}:live:*.json"))
    except OSError:
        return []


def contract_canary(code_root: Path, lanes: list[str], wave: str, *, date: str, apply: bool,
                    runs_dir: Path = RUNS_DIR, operator_rereview: Optional[str] = None) -> dict[str, Any]:
    """Health contract stage shadow -> canary for REVIEWED contracts whose lane is already at canary (2026-10-16).

    The nightly cutover controller holds a lane whose registry row is cron canary (dispatch.mode live) while its
    REVIEWED contract still records stage shadow. This is the one tool path that refreshes such a contract:
    canary_contract() (what `apply` writes for a contract it agent-reviews), nothing hand-edited. A lane moves only when
      * the registry row is kind cron, stage canary, dispatch.mode live;
      * the contract is REVIEWED, at stage shadow, with no UNKNOWN field;
      * the dispatcher has fired the lane LIVE at least once (an n8n_runs d:<lane>:live:* receipt);
      * the review was an AGENT review. An operator-REVIEWED contract is kept byte for byte: its stage refresh is an
        operator re-review (tests/test_canary_wave_20261014.py), so it is SKIP unless `operator_rereview` carries the
        operator's own words, which are recorded verbatim in review.stage_rereview.
    The review body is not re-reviewed here; only stage, the canary healthy check and state_note change."""
    cpath = code_root / CONTRACTS
    cdoc = json.loads(cpath.read_text(encoding="utf-8"))
    reg_rows = {r["lane_id"]: r for r in _load(code_root, REGISTRY).get("lanes") or [] if isinstance(r, dict)}
    by_id = {c.get("id"): i for i, c in enumerate(cdoc.get("contracts") or [])
             if isinstance(c, dict) and c.get("kind") == "lane"}
    out: list[dict[str, Any]] = []
    for lane in lanes:
        v: dict[str, Any] = {"lane_id": lane, "status": "SKIP", "reasons": []}
        out.append(v)
        row = reg_rows.get(lane) or {}
        sched = row.get("scheduler") or {}
        if sched.get("kind") != "cron" or sched.get("stage") != "canary":
            v["reasons"].append(f"registry_not_cron_canary:{sched.get('kind')}/{sched.get('stage')}")
        if (row.get("dispatch") or {}).get("mode") != "live":
            v["reasons"].append(f"dispatch_mode_{(row.get('dispatch') or {}).get('mode')}")
        idx = by_id.get(lane)
        c = cdoc["contracts"][idx] if idx is not None else None
        if c is None:
            v["reasons"].append("no_health_contract")
        else:
            if c.get("status") != "REVIEWED":
                v["reasons"].append(f"health_contract_status:{c.get('status')}")
            if c.get("stage") != "shadow":
                v["reasons"].append(f"health_contract_stage:{c.get('stage')} (only shadow -> canary)")
            if "UNKNOWN" in json.dumps(c):
                v["reasons"].append("health_contract_has_UNKNOWN_fields")
            by = str((c.get("review") or {}).get("reviewed_by") or "")
            v["reviewed_by"] = by
            if not by.lower().startswith("agent") and not operator_rereview:
                v["reasons"].append("operator_reviewed: the stage refresh is an operator re-review (pass the operator's "
                                    "words with --operator-rereview); an agent never edits it")
        fires = live_fires(lane, runs_dir)
        v["live_fires"] = fires[-3:]
        if not fires:
            v["reasons"].append("no_live_fire: the dispatcher has not fired this lane live yet (n8n_runs has no "
                                "d:<lane>:live:* receipt); wait for its next live slot")
        if v["reasons"]:
            continue
        new = canary_contract(c, wave, date)
        rev = dict(new.get("review") or {})
        rr = {"on": date, "by": "n8n_cutover_wave.py contract-canary",
              "evidence": f"registry cron canary, dispatch.mode live; live fire {fires[-1]}"}
        if operator_rereview:
            rr["operator_words"] = operator_rereview
        rev["stage_rereview"] = rr
        new["review"] = rev
        cdoc["contracts"][idx] = new
        v["status"] = "CANARY"
    if apply and any(v["status"] == "CANARY" for v in out):
        _dump_like(cpath, cdoc)
    counts: dict[str, int] = {}
    for v in out:
        counts[v["status"]] = counts.get(v["status"], 0) + 1
    return {"schema": "N8nContractCanary@v1", "wave": wave, "apply": apply, "counts": counts, "lanes": out}


# ── host act: comment the wave's cron lines in one write ───────────────────────────────────────



def comment_plan(crontab: str, reg_rows: Mapping[str, Any], lanes: list[str], date: str
                 ) -> tuple[list[dict[str, Any]], list[str]]:
    edits: list[dict[str, Any]] = []
    problems: list[str] = []
    for lid in lanes:
        row = reg_rows.get(lid)
        if row is None:
            problems.append(f"{lid}: no registry row")
            continue
        lines, probs = live_lines(crontab, row.get("scheduler") or {})
        if probs:
            problems.extend(f"{lid}: {p}" for p in probs)
            continue
        for i, ln in lines:
            edits.append({"lane_id": lid, "index": i, "before": ln, "after": TAG.format(date=date, lane=lid) + ln})
    idx = [e["index"] for e in edits]
    if len(idx) != len(set(idx)):
        problems.append("two lanes name the same crontab line")
    return edits, problems


def trading_days_between(first: "datetime", today: "dt_date") -> int:
    """DEPRECATED 2026-10-16 (kept for callers): counted every US trading DATE after `first` up to `today`, so crossing
    midnight into a session that had not happened yet counted, and the federal-holiday fallback calendar closed on
    Columbus/Veterans Day and opened on Good Friday. Now: completed NYSE sessions after `first` by the end of `today`
    (scripts/lib/nightly_cutover.completed_sessions_after)."""
    from zoneinfo import ZoneInfo  # noqa: PLC0415
    from scripts.lib.nightly_cutover import completed_sessions_after  # noqa: PLC0415
    end = datetime.combine(today, datetime.max.time(), tzinfo=ZoneInfo("America/New_York"))
    return completed_sessions_after(first, end)


def p1_overlap_problems(lanes: list[str], policy: Mapping[str, Any], *, ledger: Optional[Path] = None,
                        today: Optional["dt_date"] = None, now: Optional["datetime"] = None) -> list[str]:
    """A p1_last lane keeps its cron line until cron_overlap_trading_days COMPLETED NYSE sessions have passed after its
    FIRST live n8n RUN_DONE with exit 0 (operator 2026-10-16: "ONE COMPLETED TRADING SESSION after valid proof").
    A session counts only if it opened after the proof and has closed by `now` (default: now; `today` = the end of
    that ET day). One problem line per lane that is not yet due (or has no valid live RUN_DONE)."""
    p1 = [lid for lid in lanes if lid in (policy.get("p1_last") or ())]
    if not p1:
        return []
    from zoneinfo import ZoneInfo  # noqa: PLC0415
    from scripts.lib.nightly_cutover import completed_sessions_after  # noqa: PLC0415
    need = int(policy.get("cron_overlap_trading_days") or 1)
    et = ZoneInfo("America/New_York")
    if now is None:
        now = (datetime.combine(today, datetime.max.time(), tzinfo=et) if today is not None
               else datetime.now(timezone.utc))
    out = []
    for ev in evidence(p1, "2026-01-01", ledger or LEDGER):
        done = [r for r in ev["live_runs"] if r["state"] == "RUN_DONE" and r.get("exit") == 0]
        if not done:
            out.append(f"{ev['lane_id']}: p1_last, no live n8n RUN_DONE (exit 0) yet")
            continue
        first = datetime.fromisoformat(done[0]["finished_at"] or done[0]["requested_at"])
        if first.tzinfo is None:
            first = first.replace(tzinfo=timezone.utc)
        got = completed_sessions_after(first, now)
        if got < need:
            out.append(f"{ev['lane_id']}: p1_last, cron stays until {need} completed NYSE session(s) after the first "
                       f"live RUN_DONE ({done[0]['finished_at'] or done[0]['requested_at']}); {got} so far")
    return out


def comment_cron(lanes: list[str], code_root: Path, *, apply: bool, backup_dir: Path, date: str,
                 crontab_path: Optional[str] = None, ledger: Optional[Path] = None,
                 today: Optional["dt_date"] = None) -> dict[str, Any]:
    reg_rows = {r["lane_id"]: r for r in _load(code_root, REGISTRY).get("lanes") or [] if isinstance(r, dict)}
    text = read_crontab(crontab_path)
    edits, problems = comment_plan(text, reg_rows, lanes, date)
    policy = LD.load_cutover_policy(code_root / "config" / "lane_cutover_policy.json")
    problems.extend(p1_overlap_problems(lanes, policy, ledger=ledger, today=today))
    rc: dict[str, Any] = {"schema": "N8nWaveCronAct@v1", "at": _now(), "apply": apply, "lanes": lanes,
                          "edits": edits, "problems": problems, "backup": None, "read_back_ok": None}
    if problems or not apply:
        return rc
    backup_dir.mkdir(parents=True, exist_ok=True)
    bk = backup_dir / f"crontab-{time.strftime('%Y%m%dT%H%M%S')}-pre-n8n-wave-{'-'.join(lanes)[:60]}.txt"
    bk.write_text(text, encoding="utf-8")
    rc["backup"] = str(bk)
    lines = text.splitlines()
    for e in edits:
        lines[e["index"]] = e["after"]
    new = "\n".join(lines) + "\n"
    proc = subprocess.run([os.environ.get("CRONTAB_CMD", "crontab"), "-"], input=new, capture_output=True,
                          text=True, timeout=30)
    if proc.returncode != 0:
        rc["problems"].append(f"crontab - rejected: {proc.stderr.strip()[:200]}")
        return rc
    after = read_crontab(None).splitlines()
    rc["read_back_ok"] = all(e["after"] in after for e in edits) and len(after) == len(lines)
    return rc


FLOCK_TAG = "  # n8n-cutover {wave} flock-added 2026-10-15"


def flock_line(line: str, script: str, lock: str) -> tuple[Optional[str], str]:
    """The cron line with `flock -n <lock> ` inserted at the start of the shell segment that runs `script`, or
    (None, reason). Refuses a line that already has a flock, a script inside quotes (bash -c "..."), or a script that
    is not on the line exactly once."""
    if LD.cron_flock_locks(command_of(line)):
        return None, "line already has a flock"
    hits = [m.start() for m in re.finditer(re.escape(script), line)]
    if len(hits) != 1:
        return None, f"script {script!r} appears {len(hits)} times"
    pos = hits[0]
    if line[:pos].count('"') % 2 or line[:pos].count("'") % 2:
        return None, "script is inside a quoted string (bash -c)"
    sched_end = len(" ".join(line.split()[:5]))
    head = line[:pos]
    cut = max(head.rfind("&& "), head.rfind("; "))
    start = cut + 3 if cut >= 0 and head[cut] == "&" else (cut + 2 if cut >= 0 else sched_end + 1)
    if start <= sched_end:
        start = sched_end + 1
    while start < len(line) and line[start] == " ":
        start += 1
    seg = line[start:pos]
    if re.match(r"^[A-Z_][A-Z0-9_]*=", seg):
        return None, "segment starts with an env assignment (flock would treat it as the command)"
    return line[:start] + f"flock -n {lock} " + line[start:], ""


def add_flock(lanes: list[str], code_root: Path, *, apply: bool, backup_dir: Path, wave: str,
              crontab_path: Optional[str] = None) -> dict[str, Any]:
    """HOST act (cron grant): give each lane's live cron line(s) the allowlist lock as `flock -n`, in ONE crontab
    write (backup first, read back after). This is the §23.12 prerequisite for canary: the cron line and the n8n
    live run must share one lock. Behaviour of the cron run is unchanged except that an overlapping run now skips."""
    reg_rows = {r["lane_id"]: r for r in _load(code_root, REGISTRY).get("lanes") or [] if isinstance(r, dict)}
    entries = {e["lane_id"]: e for e in _load(code_root, ALLOWLIST).get("lanes") or [] if isinstance(e, dict)}
    text = read_crontab(crontab_path)
    lines = text.splitlines()
    edits: list[dict[str, Any]] = []
    problems: list[str] = []
    for lid in lanes:
        row, entry = reg_rows.get(lid), entries.get(lid)
        if row is None or entry is None:
            problems.append(f"{lid}: no registry row or allowlist entry")
            continue
        lock = entry.get("lock")
        script = next((t for t in entry.get("command") or [] if str(t).endswith((".py", ".sh")) and "/" in str(t)), None)
        if not lock or not script:
            problems.append(f"{lid}: allowlist entry has no lock or no script")
            continue
        found, probs = live_lines(text, row.get("scheduler") or {})
        if probs:
            problems.extend(f"{lid}: {p}" for p in probs)
            continue
        for i, ln in found:
            new, why = flock_line(ln, script, lock)
            if new is None:
                problems.append(f"{lid}: L{i + 1}: {why}")
                continue
            edits.append({"lane_id": lid, "index": i, "before": ln, "after": new})
    rc: dict[str, Any] = {"schema": "N8nWaveFlockAct@v1", "at": _now(), "apply": apply, "wave": wave,
                          "edits": edits, "problems": problems, "backup": None, "read_back_ok": None}
    if not apply or not edits:
        return rc
    backup_dir.mkdir(parents=True, exist_ok=True)
    bk = backup_dir / f"crontab-{time.strftime('%Y%m%dT%H%M%S')}-pre-n8n-{wave}-flock.txt"
    bk.write_text(text, encoding="utf-8")
    rc["backup"] = str(bk)
    for e in edits:
        lines[e["index"]] = e["after"]
    new = "\n".join(lines) + "\n"
    proc = subprocess.run([os.environ.get("CRONTAB_CMD", "crontab"), "-"], input=new, capture_output=True,
                          text=True, timeout=30)
    if proc.returncode != 0:
        rc["problems"].append(f"crontab - rejected: {proc.stderr.strip()[:200]}")
        return rc
    after = read_crontab(None).splitlines()
    rc["read_back_ok"] = all(e["after"] in after for e in edits) and len(after) == len(lines)
    return rc


# ── packet ─────────────────────────────────────────────────────────────────────────────────────

def write_packet(out: Path, plan: Mapping[str, Any], wave: str) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    ready = [v for v in plan["lanes"] if v["status"] in ("READY_CANARY", "ALREADY_CANARY")]
    skipped = [v for v in plan["lanes"] if v["status"] not in ("READY_CANARY", "ALREADY_CANARY")]
    keyed = [v["lane_id"] for v in ready if "effect_key" in (v.get("changes") or {})]
    lanes = [v["lane_id"] for v in ready]
    files: list[Path] = []

    def w(name: str, text: str, mode: int = 0o644) -> None:
        p = out / name
        p.write_text(text, encoding="utf-8")
        os.chmod(p, mode)
        files.append(p)

    w("lanes.json", json.dumps({"wave": wave, "ready": lanes, "effect_keyed": keyed,
                                "plan": [{k: v.get(k) for k in ("lane_id", "row_id", "family_id", "tier_name", "status",
                                                                 "lock", "live_arg", "slots", "cron_lines", "reasons")}
                                         for v in plan["lanes"]]}, indent=2) + "\n")
    w("01_relay_live_lanes.sh", RELAY_SH.replace("@LANES@", " ".join(lanes)).replace("@WAVE@", wave), 0o755)
    w("02_effect_owners.sh", OWNERS_SH.replace("@LANES@", " ".join(keyed)).replace("@WAVE@", wave), 0o755)
    w("04_comment_cron.sh", COMMENT_SH.replace("@LANES@", ",".join(lanes)).replace("@WAVE@", wave), 0o755)
    w("09_rollback.sh", ROLLBACK_SH.replace("@LANES@", " ".join(lanes)).replace("@KEYED@", " ".join(keyed))
      .replace("@WAVE@", wave), 0o755)
    rows = "\n".join(
        f"| `{v['lane_id']}` | {v.get('family_id') or '-'} | {v.get('tier_name')} | "
        f"{', '.join('L%d' % c['line'] for c in v.get('cron_lines') or [])} | `{' '.join(v.get('slots') or [])}` | "
        f"`{v.get('lock')}` | `{json.dumps(v.get('live_arg'))}` | {'yes' if v['lane_id'] in keyed else '-'} |"
        for v in ready)
    skips = "\n".join(f"| `{v['lane_id']}` | {v.get('family_id') or '-'} | {'; '.join(v.get('reasons') or [])} |"
                      for v in skipped)
    w("README.md", README_MD.replace("@WAVE@", wave).replace("@ROWS@", rows).replace("@SKIPS@", skips or "| - | - | - |")
      .replace("@N@", str(len(lanes))).replace("@K@", str(len(keyed))))
    return files


RELAY_SH = r"""#!/usr/bin/env bash
# @WAVE@ step 1 (config-write + service grants): add this wave's lanes to the relay/gateway live list, restart the relay.
#   bash 01_relay_live_lanes.sh            dry run: prints the new list
#   bash 01_relay_live_lanes.sh --apply    backup, write, read back, restart tradeai-n8n-run-relay
# Run ONLY after `readlink -f ~/trade-ai-releases/portfolio-server/CURRENT` names a release that contains this wave.
set -euo pipefail
F=${LIVE_LANES_ENV:-$HOME/.config/tradeai/n8n-live-lanes.env}
ADD="@LANES@"
CUR=$(sed -n 's/^TRADEAI_N8N_RELAY_LIVE_LANES=//p' "$F")
NEW=$(printf '%s\n' $CUR $ADD | awk 'NF && !seen[$0]++' | paste -sd' ')
echo "before: $CUR"; echo "after : $NEW"
[[ "${1:-}" == "--apply" ]] || { echo "DRY RUN — nothing written"; exit 0; }
cp -p "$F" "$F.bak-$(date -u +%Y%m%dT%H%M%SZ)-@WAVE@"
printf 'TRADEAI_N8N_RELAY_LIVE_LANES=%s\n' "$NEW" > "$F.tmp" && chmod 600 "$F.tmp" && mv "$F.tmp" "$F"
grep -c . "$F" >/dev/null; for l in $ADD; do grep -qw -- "$l" "$F" || { echo "READ-BACK FAILED: $l"; exit 1; }; done
systemctl --user restart tradeai-n8n-run-relay.service
sleep 2; systemctl --user is-active tradeai-n8n-run-relay.service
echo "read back OK; relay restarted"
"""

OWNERS_SH = r"""#!/usr/bin/env bash
# @WAVE@ step 2 (cron grant as TRADEAI_FABRIC_GRANT): effect-key owner rows -> n8n for the keyed lanes, so the n8n
# executor's claim (n8n_claim true) is admitted and a cron line wrapped by effect_claim_cron.sh (cron_claim true) is
# fenced. Without an owner row every live run of a keyed lane is refused effect_no_owner (fail closed).
#   bash 02_effect_owners.sh [--apply]
set -euo pipefail
SERVED=${SERVED:-$(readlink -f "$HOME/trade-ai-releases/portfolio-server/CURRENT")}
PY=${PY:-$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python}
for lane in @LANES@; do
  proc=$("$PY" "$SERVED/scripts/lib/effect_claim.py" lane-spec --lane "$lane" 2>/dev/null | cut -f1 || true)
  [[ -n "$proc" ]] || proc=$lane
  cur=$("$PY" "$SERVED/scripts/lib/effect_claim.py" show --process "$proc" | "$PY" -c 'import json,sys; o=json.load(sys.stdin).get("owner"); print("none none" if not o else "%s %s" % (o["owner"], o["epoch"]))')
  read -r owner epoch <<<"$cur"
  if [[ "$owner" == "n8n" ]]; then echo "  $proc already n8n (epoch $epoch)"; continue; fi
  ARGS=(set-owner --process "$proc" --owner n8n --by "operator:${TRADEAI_FABRIC_GRANT:-dry}" --note "@WAVE@ canary")
  [[ "$epoch" != "none" ]] && ARGS+=(--expect-epoch "$epoch")
  if [[ "${1:-}" != "--apply" ]]; then echo "  DRY RUN: effect_claim.py ${ARGS[*]}"; continue; fi
  [[ -n "${TRADEAI_FABRIC_GRANT:-}" ]] || { echo "REFUSED: TRADEAI_FABRIC_GRANT not set"; exit 1; }
  "$PY" "$SERVED/scripts/lib/effect_claim.py" "${ARGS[@]}"
done
"""

COMMENT_SH = r"""#!/usr/bin/env bash
# @WAVE@ step 4 (cron grant): after EVERY lane below has >= 1 live n8n RUN_DONE (03 evidence), comment all of the wave's
# cron lines in ONE crontab write: `# RETIRED <date> n8n-cutover <lane> <line>`. Backup first, read back after.
#   bash 04_comment_cron.sh            dry run (prints the edits)
#   bash 04_comment_cron.sh --apply
set -euo pipefail
REPO=${REPO:-$(cd "$(dirname "$0")/../../../.." && pwd)}
PY=${PY:-$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python}
LANES=${LANES:-@LANES@}
"$PY" "$REPO/scripts/n8n_cutover_wave.py" comment-cron --code-root "$REPO" --lanes "$LANES" ${1:+$1}
"""

ROLLBACK_SH = r"""#!/usr/bin/env bash
# @WAVE@ rollback. Each step is independent; run the ones that were applied, newest first.
#   R1 cron lines back : python3 scripts/pipelines/cutover/_cutover.py rollback --lane <lane> --apply   (per lane;
#                        uncomments exactly the `n8n-cutover <lane>` tagged lines) — or restore the 04 backup file.
#   R2 effect owners   : effect_claim.py set-owner --process <p> --owner cron --expect-epoch <e>  (keyed: @KEYED@)
#   R3 relay live list : restore ~/.config/tradeai/n8n-live-lanes.env.bak-*-@WAVE@ and restart tradeai-n8n-run-relay
#   R4 registry        : revert the wave PR (rows back to shadow / dry_run) and promote; or dispatch.mode off.
# Lanes: @LANES@
echo "read the header; nothing is run automatically"
"""

README_MD = """# n8n cutover @WAVE@ (2026-10-15): operator packet

Generated by `scripts/n8n_cutover_wave.py` (the cutover factory). Operator directive 2026-10-15 "N8N Cutover
Decision"; standard AGENTS.md §23.21: fix + dry run + regression + at least one live n8n run with the cron line
present (shared flock), then comment the cron line. No soaks.

**@N@ lanes move to canary** (registry `stage: canary`, `dispatch.mode: live`; allowlist `live_arg` = the cron argv,
lock = the cron line's `flock -n` lock). @K@ of them get an armed effect key (`n8n_claim` + `cron_claim` true).

| Lane | Family | Tier | Cron line | Slots (ET) | Shared lock | live_arg | Effect key |
|---|---|---|---|---|---|---|---|
@ROWS@

## Steps (after the wave PR is merged and its release is CURRENT)

1. `TRADEAI_FABRIC_GRANT=<cron grant> bash 02_effect_owners.sh --apply` FIRST, for the keyed lanes (owner -> n8n).
   Harmless before step 2 (no cron line claims; dry runs never claim). Done the other way round, every keyed live
   fire between the two steps is RUN_REFUSED `effect_no_owner`.
2. `bash 01_relay_live_lanes.sh --apply` (config-write + service): adds the lanes to `TRADEAI_N8N_RELAY_LIVE_LANES`,
   restarts the relay, reads back. Until then the dispatcher's live requests for these lanes are refused
   `relay_live_lanes` (no effect; the cron line still does the work). Do it right after the release is CURRENT.
3. Live run: the dispatcher's natural slot (`d:` key, server-validated, effect-key compatible) is the live n8n run with
   the cron line present; the shared flock makes one of the two `RUN_SKIPPED_LOCK` / exit 1. A forced run outside the
   slot is NOT used: the gateway refuses a free-form live key (`run_key_namespace_refused`) and a keyed lane needs the
   slot. Evidence: `python3 scripts/n8n_cutover_wave.py evidence --lanes <...>` (read-only ledger query): a `live`
   `RUN_DONE` (or the cron twin held the lock and the next slot is RUN_DONE), receipt `output_signal` advanced, and
   for keyed lanes an `effect` block `claimed: true`.
4. `bash 04_comment_cron.sh --apply` (cron grant) once every lane in the batch has its live evidence: one crontab write,
   backup + read-back.
5. The next wave's PR flips these rows to the §23.11 dispatcher row (`n8n_cutover_wave.py cutover`).

## Skipped (exact reason from the gate that refused)

| Lane | Family | Reason |
|---|---|---|
@SKIPS@

## Rollback

`09_rollback.sh` lists R1-R4. Nothing is deleted anywhere.
"""


# ── evidence (read-only ledger) ────────────────────────────────────────────────────────────────

LEDGER = Path.home() / "trade-ai-releases/persistent-state/data/governance/n8n_coordination_ledger.sqlite"


def evidence(lanes: list[str], since: str, ledger: Path = LEDGER) -> list[dict[str, Any]]:
    import sqlite3  # noqa: PLC0415

    c = sqlite3.connect(f"file:{ledger}?mode=ro", uri=True)
    out = []
    for lid in lanes:
        rows = c.execute(
            "SELECT run_id, mode, state, requested_at, finished_at, exit_code, receipt_json FROM runs "
            "WHERE lane_id=? AND requested_at>=? AND mode='live' ORDER BY requested_at", (lid, since)).fetchall()
        runs = []
        for run_id, mode, state, req, fin, code, rj in rows:
            try:
                r = json.loads(rj or "{}")
            except ValueError:
                r = {}
            eff = r.get("effect") or {}
            runs.append({"run_id": run_id, "state": state, "requested_at": req, "finished_at": fin, "exit": code,
                         "reason": r.get("reason"), "effect_claimed": eff.get("claimed"), "effect_reason": eff.get("reason"),
                         "output_signal_advanced": (r.get("output_signal_mtime_after") or 0)
                         > (r.get("output_signal_mtime_before") or 0)})
        ok = any(x["state"] == "RUN_DONE" for x in runs)
        out.append({"lane_id": lid, "live_runs": runs, "live_done": ok})
    return out


# ── CLI ────────────────────────────────────────────────────────────────────────────────────────

def _lanes_arg(s: Optional[str]) -> Optional[list[str]]:
    if not s:
        return None
    return [x for x in re.split(r"[\s,]+", s) if x]


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "apply", "packet"):
        p = sub.add_parser(name)
        p.add_argument("--code-root", default=str(ROOT))
        p.add_argument("--crontab", help="read this crontab copy instead of `crontab -l`")
        p.add_argument("--lanes", help="comma/space separated lane ids (default: the whole directive scope)")
        p.add_argument("--wave", default="CW0")
        p.add_argument("--max-tier", type=int, default=TIER_BROKER)
        p.add_argument("--json", action="store_true")
        p.add_argument("--include-p1", action="store_true",
                       help="plan the p1_last lanes too (they move after every non-P1 lane; operator 2026-10-16)")
        p.add_argument("--review-drafts", action="store_true",
                       help="agent-review DRAFT contracts whose runner/lock/receipt edges machine-check (agent_review)")
        if name == "packet":
            p.add_argument("--out", required=True)
    p = sub.add_parser("cutover")
    p.add_argument("--code-root", default=str(ROOT))
    p.add_argument("--lanes", required=True)
    p.add_argument("--wave", default="CW0")
    p = sub.add_parser("contract-canary")
    p.add_argument("--code-root", default=str(ROOT))
    p.add_argument("--lanes", required=True)
    p.add_argument("--wave", default="CH0")
    p.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    p.add_argument("--runs-dir", default=str(RUNS_DIR))
    p.add_argument("--operator-rereview", default=None,
                   help="the operator's own words authorising the stage refresh of operator-REVIEWED contracts")
    p.add_argument("--apply", action="store_true")
    p = sub.add_parser("comment-cron")
    p.add_argument("--code-root", default=str(ROOT))
    p.add_argument("--lanes", required=True)
    p.add_argument("--crontab")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--backup-dir", default=str(Path.home() / ".local/state/tradeai/backups"))
    p.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    p = sub.add_parser("add-flock")
    p.add_argument("--code-root", default=str(ROOT))
    p.add_argument("--lanes", required=True)
    p.add_argument("--crontab")
    p.add_argument("--wave", default="CW0")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--backup-dir", default=str(Path.home() / ".local/state/tradeai/backups"))
    p = sub.add_parser("evidence")
    p.add_argument("--lanes", required=True)
    p.add_argument("--since", required=True, help="ISO time; ledger requested_at >= this")
    p.add_argument("--ledger", default=str(LEDGER))
    a = ap.parse_args(argv)
    if a.cmd == "evidence":
        print(json.dumps(evidence(_lanes_arg(a.lanes) or [], a.since, Path(a.ledger)), indent=2))
        return 0
    code_root = Path(a.code_root)
    if a.cmd == "cutover":
        done = cutover_rows(code_root, _lanes_arg(a.lanes) or [], a.wave)
        print(f"cutover rows written: {len(done)} {done}")
        return 0
    if a.cmd == "contract-canary":
        rc = contract_canary(code_root, _lanes_arg(a.lanes) or [], a.wave, date=a.date, apply=a.apply,
                             runs_dir=Path(a.runs_dir), operator_rereview=a.operator_rereview)
        for v in rc["lanes"]:
            print(f"{v['status']:<7} {v['lane_id']:<40} {'; '.join(v['reasons'])[:200] or (v.get('live_fires') or [''])[-1]}")
        print(json.dumps(rc["counts"]))
        return 0
    if a.cmd == "add-flock":
        rc = add_flock(_lanes_arg(a.lanes) or [], code_root, apply=a.apply, backup_dir=Path(a.backup_dir),
                       wave=a.wave, crontab_path=a.crontab)
        for e in rc["edits"]:
            print(f"  L{e['index'] + 1} {e['lane_id']}: {e['after'][:200]}")
        for pr in rc["problems"]:
            print(f"  PROBLEM {pr}")
        print(json.dumps({k: rc[k] for k in ("apply", "backup", "read_back_ok")}))
        return 0 if rc["edits"] or not rc["problems"] else 1
    if a.cmd == "comment-cron":
        rc = comment_cron(_lanes_arg(a.lanes) or [], code_root, apply=a.apply, backup_dir=Path(a.backup_dir),
                          date=a.date, crontab_path=a.crontab)
        for e in rc["edits"]:
            print(f"  L{e['index'] + 1} {e['lane_id']}: {e['after'][:160]}")
        for pr in rc["problems"]:
            print(f"  PROBLEM {pr}")
        print(json.dumps({k: rc[k] for k in ("apply", "backup", "read_back_ok")}))
        return 1 if rc["problems"] else 0
    plan = build_plan(code_root, read_crontab(a.crontab), _lanes_arg(a.lanes), a.wave, a.max_tier,
                      review_drafts=a.review_drafts, include_p1=a.include_p1)
    if a.cmd == "plan":
        if a.json:
            print(json.dumps(plan, indent=2))
        else:
            for v in plan["lanes"]:
                print(f"{v['status']:<15} {v['lane_id']:<44} {v.get('family_id') or '-':<5} "
                      f"{v.get('tier_name') or '-':<15} {'; '.join(v.get('reasons') or [])[:220]}")
            print(json.dumps(plan["counts"]))
        return 0
    if a.cmd == "apply":
        done = apply_plan(code_root, plan)
        print(f"applied {len(done)} lanes: {done}")
        skipped = [v for v in plan["lanes"] if v["lane_id"] not in done]
        for v in skipped:
            print(f"  SKIP {v['lane_id']}: {'; '.join(v.get('reasons') or [])}")
        return 0
    files = write_packet(Path(a.out), plan, a.wave)
    print("\n".join(str(f) for f in files))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
