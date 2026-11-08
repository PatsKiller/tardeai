"""Render the self-heal runbook workbook from the catalog and the replay snapshot (LQ-20261107-1259).

The pages under ``docs/runbooks/self_heal/`` are **generated**. This module is the only writer of their text;
``scripts/gen_self_heal_runbook_docs.py`` is the CLI, and ``tests/test_self_heal_runbook_docs_20261108.py`` proves
that regenerating at the committed inputs reproduces the committed pages byte for byte — so a page cannot drift from
the JSON it describes.

Pure by construction: no clock (the replay snapshot carries its own ``as_of``), no I/O, no network, no DB, no
environment read. Every rendering map below is closed: an action, verify kind, precondition, tier or category that
the catalog gains without a paragraph here raises, so a new entry cannot ship a page with an empty section.

Inputs: the catalog (``config/self_heal_runbook_catalog.json``, ``SelfHealRunbookCatalog@v1``); the coverage snapshot
(``docs/runbooks/self_heal/COVERAGE.json``, ``SelfHealRunbookCoverage@v1``, written by
``scripts/ops/self_heal_runbook_replay.py``); and an ``entry id -> [fixture stem, ...]`` index of the replay corpus.

Outputs: ``<id>.md`` per entry, ``INDEX.md``, ``COVERAGE.md``. The static, hand-written files beside them
(``README.md``, ``RULINGS.md``, ``COVERAGE.json``) are never written here.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

DOCS_DIR = "docs/runbooks/self_heal"
#: Hand-written files in the directory. The generator and its test must not require these to be generated, and must
#: not report them as orphans.
STATIC_FILES = frozenset({"README.md", "RULINGS.md", "COVERAGE.json"})

#: The workbook's required headings, in order. The docs test asserts every entry page carries each one; a renderer
#: change that drops a section fails there rather than in a reviewer's eye.
SECTIONS: tuple[str, ...] = (
    "## 1. What fires it",
    "## 2. Evidence to collect",
    "## 3. Diagnosis",
    "## 4. The only action it may take",
    "## 5. Verification",
    "## 6. Rollback",
    "## 7. Budget and cooldown",
    "## 8. When to escalate, and what to send",
    "## 9. Human steps",
    "## 10. Tests",
)

#: Category letters -> the plan's names (SELFHEAL-BEST-PRACTICE-PLAN-20261108.md, section RUNBOOK CATALOG).
CATEGORY_NAMES: dict[str, str] = {
    "A": "Locks & concurrency",
    "B": "Quota / rate limit / LLM provider",
    "C": "Upstream data",
    "D": "Network / transient",
    "E": "Time / wall",
    "F": "Scheduler / n8n plane",
    "G": "Resources",
    "H": "Database",
    "I": "Config / registry drift",
    "J": "Code and data defects",
    "K": "Human-only",
}

#: What each tier means *in the engine*, not what a reader might assume. Only ``human_only`` is enforced there (the
#: action is replaced with ``escalate_finding``); the auto/auto_notify difference is the caller's notification policy.
TIER_RULES: dict[str, str] = {
    "auto": (
        "the fixer applies the action and posts nothing while the entry still has attempts. Silence is the point: "
        "these signatures are the normal path (a held lock, a lost executor), and a message per occurrence is noise. "
        "When the attempt budget is spent the engine itself switches the action to `escalate_finding` "
        "(`reason: max_attempts_reached`), so the silence is bounded."
    ),
    "auto_notify": (
        "the fixer applies the action and posts a FINDING, so an operator sees the failure even when the action "
        "works. Use this tier when the *occurrence* is information: a timeout, a refused route, an unverifiable "
        "output."
    ),
    "human_only": (
        "the engine never returns a mutating action for this entry: `plan_runbook` replaces it with "
        "`escalate_finding` (`reason: tier_human_only`) and the FINDING carries the human steps. The action field "
        "below is what a **human** runs, never what the fixer runs."
    ),
}

#: action -> (does, params, what it does not do, rollback). The action whitelist is the engine's; an action with no
#: paragraph here is a render error, by design.
ACTION_DOCS: dict[str, dict[str, str]] = {
    "noop_wait_recheck": {
        "does": (
            "records the plan and schedules the next look at `now + wait_s`. It changes nothing on the host: no file, "
            "no lock, no process, no row. It is the action for a condition that is expected to clear itself."
        ),
        "params": "`wait_s` — seconds until the next re-check (default 300).",
        "not": "does not re-run the lane, does not touch the lock, does not acknowledge the failure to anyone.",
        "rollback": "none — nothing was written. The plan's receipt is the only artifact.",
    },
    "rerun_once_via_gateway": {
        "does": (
            "records `rerun_requested` with `via: coordination_gateway` and `next_attempt_at = now + delay_s`. The "
            "runbook primitive does **not** execute the lane itself: the gateway owns the re-run, under the lane's "
            "own effect key, so a runbook re-run cannot double-write."
        ),
        "params": "`delay_s` — seconds before the gateway may re-run (default 0).",
        "not": (
            "does not call the lane, does not read or write the lane's output, does not bypass the effect-key claim. "
            "The entry's budget and the gateway's own effect key both bound the re-run."
        ),
        "rollback": (
            "none to undo — the primitive only requested a run. If the gateway ran it, that run's own effect row and "
            "receipt are the record; never delete either to 'roll back' a runbook."
        ),
    },
    "defer_until": {
        "does": (
            "records `deferred` with `next_attempt_at = now + delay_s + deterministic jitter` (bounded by `jitter_s`). "
            "The jitter spreads a rate-limited fleet so the retries do not collide on the next window."
        ),
        "params": "`delay_s` (default 300), `jitter_s` (default 60), `max_retries` (default 3, the daily budget).",
        "not": "does not change the provider's quota, the budget governor or the clock.",
        "rollback": "none — nothing was written.",
    },
    "release_stale_flock": {
        "does": (
            "**the only action that writes to the host.** With `--apply`, and only after the plan's preconditions "
            "held, it re-probes the lock non-blockingly and re-checks the path against the never-touch list; if the "
            "lock is still free it renames the file to `<name>.stale-<UTC stamp>`. The archive is why nothing is "
            "deleted."
        ),
        "params": "`lock_path`, `lock_kind` (from the evidence; the plan carries them in its `_apply` block).",
        "not": (
            "never removes a file (`os.replace` to an archive name), never touches a lock a live process holds, never "
            "acts on a kernel flock (a holder-less flock file blocks nothing), never touches a path inside the "
            "never-touch list."
        ),
        "rollback": "`mv <lock_path>.stale-<stamp> <lock_path>` — the archived name is the rollback.",
    },
    "release_stale_sqlite_wal_lock": {
        "does": (
            "reports only: it records `sqlite_lock_reported` and names the risk in the human steps. It never removes a "
            "`-wal` or `-shm` file."
        ),
        "params": "none.",
        "not": "does not remove, truncate or checkpoint a SQLite side file.",
        "rollback": "none — nothing was written.",
    },
    "open_breaker_cooldown": {
        "does": (
            "records `cooldown` with `next_attempt_at = now + cooldown_s`, so the lane is not re-attempted while the "
            "breaker is open. The breaker's own state is the authority; this primitive records the wait."
        ),
        "params": "`cooldown_s` — seconds of cooldown (default 900).",
        "not": "does not close, reset or bypass the breaker.",
        "rollback": "none — nothing was written. A breaker that should not be open is a separate finding.",
    },
    "mark_weekend_expected": {
        "does": (
            "records `expected_window_marked`: the receipt says the window is expected (weekend / market holiday / "
            "closed calendar), so a later reader does not count it as an unexplained failure."
        ),
        "params": "none.",
        "not": "does not change the calendar, the schedule or the data.",
        "rollback": "none — nothing was written; the receipt is the record.",
    },
    "escalate_finding": {
        "does": (
            "renders a deterministic FINDING (`_finding_text`) from the entry's `on_fail.title`, the plan and the "
            "human steps, and records `escalation_rendered` with the text in the receipt. This is always available: "
            "it survives a spent budget, a failed precondition and any lane."
        ),
        "params": "none.",
        "not": "does not attempt the failure again, does not page anyone, does not write outside the receipt.",
        "rollback": "none — the FINDING is information, not a mutation.",
    },
}

#: verify.kind -> what 'verified' means, the exact command, and the expected output. Commands are read-only and run
#: from the repository root; ``{lane}`` is substituted with a placeholder. ``STATE`` is the state root the executor
#: wrote to (``TRADEAI_STATE_ROOT`` or ``~/trade-ai-releases/persistent-state``).
VERIFY_DOCS: dict[str, dict[str, str]] = {
    "run_appears": {
        "means": "a later slot of the lane ran and finished (`RUN_DONE`) inside the window.",
        "command": (
            'STATE="${TRADEAI_STATE_ROOT:-$HOME/trade-ai-releases/persistent-state}"\n'
            'newest=$(ls -t "$STATE"/data/runtime/n8n_runs/d:{lane}:*.json 2>/dev/null | head -1)\n'
            'echo "$newest"\n'
            "python3 -c 'import json,sys; d=json.load(open(sys.argv[1]));"
            ' print(d.get("state"), "|", d.get("reason"))\' "$newest"'
        ),
        "expect": (
            "a receipt path whose stamp is later than the plan's `at`, and the line `RUN_DONE | …` — a state of "
            "`RUN_FAILED`/`RUN_TIMEOUT`/`RUN_REFUSED`/`RUN_SKIPPED_LOCK` means the window has not verified it yet."
        ),
    },
    "next_attempt_succeeds": {
        "means": "the re-run or the next scheduled slot completed, and no dead letter is left for the lane.",
        "command": (
            'STATE="${TRADEAI_STATE_ROOT:-$HOME/trade-ai-releases/persistent-state}"\n'
            "python3 scripts/n8n_dlq.py list --lane {lane} --json\n"
            'newest=$(ls -t "$STATE"/data/runtime/n8n_runs/d:{lane}:*.json 2>/dev/null | head -1)\n'
            'echo "$newest"'
        ),
        "expect": "`[]` from the dead-letter listing (nothing unreleased for the lane) and a receipt newer than `at`.",
    },
    "lock_absent_or_free": {
        "means": "the lock file is gone, or nothing holds it.",
        "command": 'ls -l {lock_path} 2>&1\nfuser -v {lock_path} 2>&1\nps -o pid,lstart,cmd -p {owner_pid} 2>&1',
        "expect": (
            "`No such file or directory`, or the file listed with `fuser` printing nothing (no holder) and `ps` "
            "answering `no such process`. Any pid named by `fuser` means a live holder: the lock is doing its job, "
            "do not touch it."
        ),
    },
    "freshness_restored": {
        "means": "the lane's source now has a row younger than the health contract's failed threshold.",
        "command": (
            "PGOPTIONS='-c default_transaction_read_only=on' psql -h /var/run/postgresql -d trade_ai -c \\\n"
            '  "select max(<timestamp_column>) as newest, now() - max(<timestamp_column>) as age from <lane_table>"'
        ),
        "expect": (
            "an `age` smaller than the contract's `freshness_failed_after_h` (the threshold the plan's "
            "`contract_freshness_present` check read). Substitute the lane's own table and timestamp column — the "
            "lane's health contract names them; do not invent one."
        ),
    },
    "calendar_is_closed": {
        "means": "the window really is a weekend or a market holiday, so no output was expected.",
        "command": (
            "date -u +%Y-%m-%dT%H:%MZ\n"
            'grep -n "$(date -u +%Y-%m-%d)" config/macro_calendar_overrides.json 2>&1'
        ),
        "expect": (
            "a Saturday/Sunday, or a date the calendar overrides mark closed. On a normal trading day this check "
            "fails: the runbook's premise was wrong and the failure is real."
        ),
    },
    "source_timestamp_advances": {
        "means": "the source's newest row timestamp moved past the instant of the failed run.",
        "command": (
            "PGOPTIONS='-c default_transaction_read_only=on' psql -h /var/run/postgresql -d trade_ai -c \\\n"
            '  "select max(<timestamp_column>) from <source_table>"'
        ),
        "expect": "a timestamp later than the receipt's `at`; an unchanged maximum means the source is still stale.",
    },
    "journal_shows_completion": {
        "means": "the unit's journal shows the run completing after the plan's `at`.",
        "command": "journalctl --user -u <unit> -n 40 --no-pager",
        "expect": "a completion line stamped after the plan's `at`, with no error line after it.",
    },
    "orphan_reaped": {
        "means": "the orphaned run left the `RUNNING` state and its slot was re-armed or is free.",
        "command": (
            'STATE="${TRADEAI_STATE_ROOT:-$HOME/trade-ai-releases/persistent-state}"\n'
            'sqlite3 "file:$STATE/data/governance/n8n_coordination_ledger.sqlite?mode=ro" \\\n'
            "  \"select slot_key, state, last_reason from runs where slot_key like '%{lane}%'"
            ' order by rowid desc limit 5"'
        ),
        "expect": "the newest row is not `RUNNING`, and no row still names the orphaned run as the holder.",
    },
    "breaker_state": {
        "means": "the lane's breaker is closed (or the cooldown has passed) and the lane may run again.",
        "command": (
            'STATE="${TRADEAI_STATE_ROOT:-$HOME/trade-ai-releases/persistent-state}"\n'
            "python3 scripts/n8n_dlq.py list --lane {lane} --all --json"
        ),
        "expect": "no open breaker for the lane in the listing; a breaker still `open` means the cooldown has not passed.",
    },
    "next_run_opens_db": {
        "means": "the next run of the lane opened the same database without hitting `SQLITE_BUSY`.",
        "command": (
            'STATE="${TRADEAI_STATE_ROOT:-$HOME/trade-ai-releases/persistent-state}"\n'
            'newest=$(ls -t "$STATE"/data/runtime/n8n_runs/d:{lane}:*.json 2>/dev/null | head -1)\n'
            "python3 -c 'import json,sys; d=json.load(open(sys.argv[1]));"
            ' print(d.get("state"), "|", d.get("reason"))\' "$newest"'
        ),
        "expect": (
            "a receipt newer than the plan's `at` whose state is `RUN_DONE` and whose `reason`/stderr mention no "
            "`database is locked`/`SQLITE_BUSY`. Nothing is removed to make this true: a WAL/SHM file is never "
            "deleted."
        ),
    },
    "repro_exists": {
        "means": "the failure is reproducible: a run after the plan failed the same way.",
        "command": (
            'STATE="${TRADEAI_STATE_ROOT:-$HOME/trade-ai-releases/persistent-state}"\n'
            'ls -t "$STATE"/data/runtime/n8n_runs/d:{lane}:*.json 2>/dev/null | head -3'
        ),
        "expect": "a receipt newer than the plan's `at` with the same failure state — evidence for the escalation.",
    },
    "human_verified": {
        "means": (
            "a person confirms the condition against the evidence named in the human steps. There is no command that "
            "decides it; this is where the workbook hands over rather than pretending to verify."
        ),
        "command": "(no command: the check is the human step itself)",
        "expect": (
            "the finding carries what the person concluded **and** the independent source they checked it against. "
            "An escalation without that pair is UNPROVEN by the audit standard, not verified."
        ),
    },
}

#: precondition -> (what it proves, the evidence fields it reads, how to collect them).
PRECONDITION_DOCS: dict[str, dict[str, Any]] = {
    "lane_present": {
        "proves": "the incident names a lane. Without one the engine refuses — an unattributed failure has no owner.",
        "fields": ["lane"],
        "how": "the lane id from the receipt's file name (`d:<lane>:<mode>:<stamp>.json`) or the dead letter's `lane_id`.",
    },
    "not_execution_lane": {
        "proves": "the lane is not an execution lane. No runbook action may touch one; a failure there is escalated.",
        "fields": ["lane"],
        "how": "the lane id, checked against the engine's execution-lane refusals.",
    },
    "lock_path_recorded": {
        "proves": "the lock's path is known, so the action can name what it would archive.",
        "fields": ["lock_path"],
        "how": "the absolute path the lane's lock wrapper printed in its stderr or reason.",
    },
    "owner_pid_recorded": {
        "proves": "the lock records an owner pid, so liveness can be decided instead of guessed.",
        "fields": ["owner_pid"],
        "how": "the pidfile's contents (or the lock's log line).",
    },
    "owner_pid_dead": {
        "proves": "the recorded owner is dead, so the lock is orphaned rather than held.",
        "fields": ["owner_pid", "pid_alive"],
        "how": (
            "collect `pid_alive` yourself (`kill -0 <pid>` / `ps -p <pid>`) and put it in the evidence. When the field "
            "is absent the engine probes `kill(pid, 0)`; a probe it cannot make is a refusal."
        ),
    },
    "lock_age_recorded": {
        "proves": "the lock's age is known, so 'older than the lane's own timeout' can be decided.",
        "fields": ["lock_age_s"],
        "how": "`stat -c %Y <lock_path>` against `date +%s`.",
    },
    "lock_age_gt_lane_timeout": {
        "proves": "the lock has outlived the lane's timeout, i.e. it cannot be a run still inside its budget.",
        "fields": ["lock_age_s", "lane_timeout_s (or the contract's baseline.timeout_s)"],
        "how": "the recorded age, and the lane's timeout from its health contract.",
    },
    "lock_kind_existence": {
        "proves": (
            "the lock is existence-based (a pidfile/marker), not a kernel flock. A flock is released by the kernel "
            "when its holder dies and a holder-less flock file blocks nothing, so there is nothing to archive."
        ),
        "fields": ["lock_kind"],
        "how": "how the lane acquires the lock: `safe_flock.sh` (flock) or a pidfile/marker (existence).",
    },
    "retries_under_budget": {
        "proves": "the lane has retries left today. A missing count is a refusal — 0 is a value, missing is not.",
        "fields": ["retries_today (or deferrals_today / attempts_today)"],
        "how": "the deferral/retry count for the lane's current ET day.",
    },
    "data_age_measured": {
        "proves": "the data's age is known, so 'late' is a measurement rather than an impression.",
        "fields": ["data_age_h (or data_age_s / last_ok_at)"],
        "how": "the newest row's timestamp against `now`.",
    },
    "contract_freshness_present": {
        "proves": "the lane's health contract states a freshness threshold; without one 'late' cannot be proven.",
        "fields": ["contract.baseline.freshness_failed_after_h"],
        "how": "the lane's health contract (the `n8n_health_contracts` config the lane is registered with).",
    },
    "data_is_late": {
        "proves": "the measured age exceeds the contract's threshold.",
        "fields": ["data_age_h", "contract.baseline.freshness_failed_after_h"],
        "how": "both values above; the comparison is the check.",
    },
    "rerun_not_used_today": {
        "proves": "the once-per-day re-run has not been used yet. Unlike the retry budget, a missing count reads as 0.",
        "fields": ["reruns_today"],
        "how": "the lane's re-run count for the current ET day.",
    },
}

#: Evidence the fixer always has, whatever the entry. The receipt is the incident record; these fields are read by the
#: matcher or by the budget/cooldown/rate-limit checks, so they are collected before diagnosis.
COMMON_EVIDENCE: tuple[tuple[str, str], ...] = (
    ("lane", "the incident's lane; the engine refuses without it"),
    ("signature", "the stable signature text the fixer keys the idempotency hash on"),
    ("failure_class", "the class the caller derived (the matcher's first input)"),
    ("reason / failure_kind / detail", "the matcher's reason text"),
    ("exception / stderr_tail / stdout_tail", "the wider text the `exception_regex` patterns read"),
    ("attempts", "how many times this entry already acted for this incident"),
    ("entry_last_attempt_at", "the entry's cooldown anchor"),
    ("lane_last_action_at", "the lane's hourly rate-limit anchor"),
)

#: The engine evaluates these checks before any precondition, in this order; a page states the order because the
#: first `ok: false` is the refusal and the `reason` names it.
ENGINE_CHECKS: tuple[tuple[str, str], ...] = (
    ("entry_match", "one entry matched (lowest explicit priority wins, ids break ties)"),
    ("unambiguous_match", "no other entry shares the winner's priority"),
    ("attempt_budget", "`attempts < max_attempts`; at the cap the action becomes `escalate_finding`"),
    ("entry_cooldown", "the entry has not acted within `cooldown_min`"),
    ("lane_rate_limit", "no mutating action on this lane in the last hour"),
    ("not_execution_lane", "the lane is not an execution lane (a global rail: no entry can opt out)"),
)


# ---------------------------------------------------------------- helpers


def _cell(value: Any) -> str:
    """A GFM table cell: one line, pipes escaped."""
    return " ".join(str(value).split()).replace("|", "\\|")


def _code(value: Any) -> str:
    text = str(value)
    if "`" in text:
        return f"`` {text} ``"
    return f"`{text}`"


def _pre(entry: Mapping[str, Any]) -> list[str]:
    return [p if isinstance(p, str) else str((p or {}).get("check")) for p in entry.get("preconditions") or []]


def _category_name(letter: str) -> str:
    if letter not in CATEGORY_NAMES:
        raise KeyError(f"category {letter!r} has no name in CATEGORY_NAMES")
    return CATEGORY_NAMES[letter]


def _hits_text(row: Mapping[str, Any] | None, coverage: Mapping[str, Any] | None) -> str:
    if coverage is None:
        return "no replay snapshot on this commit"
    if not row:
        return "0 failures in the window"
    return f"{row.get('hits', 0)} failure(s) on {len(row.get('lanes') or [])} lane(s)"


def _render_title(title: str, entry: Mapping[str, Any]) -> str:
    return title.replace("{max_attempts}", str(entry.get("max_attempts"))).replace("{lane}", "<lane>")


def _verify_doc(entry: Mapping[str, Any]) -> tuple[str, dict[str, str]]:
    verify = entry.get("verify") or {}
    kind = str(verify.get("kind") or "")
    if kind not in VERIFY_DOCS:
        raise KeyError(f"verify kind {kind!r} has no paragraph in VERIFY_DOCS; add one before shipping the entry")
    doc = dict(VERIFY_DOCS[kind])
    params = entry.get("params") or {}
    values = {"lane": "<lane>", "lock_path": "<lock_path>", "owner_pid": "<owner_pid>"}
    values.update({str(k): str(v) for k, v in params.items() if isinstance(v, str)})
    for key in ("command", "expect", "means"):
        for name, value in values.items():
            doc[key] = doc[key].replace("{" + name + "}", value)
    return kind, doc


# ---------------------------------------------------------------- the entry page


def render_entry(entry: Mapping[str, Any], catalog: Mapping[str, Mapping[str, Any]], *,
                 version: str, coverage: Mapping[str, Any] | None = None,
                 fixtures: Sequence[str] = ()) -> str:
    """One entry's workbook page. ``catalog`` is the id->entry mapping (for the ordering note)."""
    eid = str(entry["id"])
    letter = str(entry["category"])
    tier = str(entry["tier"])
    if tier not in TIER_RULES:
        raise KeyError(f"tier {tier!r} has no paragraph in TIER_RULES")
    action = str(entry["action"])
    if action not in ACTION_DOCS:
        raise KeyError(f"action {action!r} has no paragraph in ACTION_DOCS; add one before shipping the entry")
    adoc = ACTION_DOCS[action]
    kind, verify = _verify_doc(entry)
    params = entry.get("params") or {}
    match = entry.get("match") or {}
    pre = _pre(entry)
    for check in pre:
        if check not in PRECONDITION_DOCS:
            raise KeyError(f"precondition {check!r} has no paragraph in PRECONDITION_DOCS")
    coverage_row = ((coverage or {}).get("entries") or {}).get(eid) or None
    higher = sorted((e for e in catalog.values() if int(e["priority"]) > int(entry["priority"])),
                    key=lambda e: (int(e["priority"]), str(e["id"])))

    out: list[str] = []
    out.append(f"# {eid} — {entry['title']}")
    out.append("")
    out.append(
        f"Generated from `config/self_heal_runbook_catalog.json` v{version} (priority {entry['priority']}); "
        f"**do not edit this page** — run `python3 scripts/gen_self_heal_runbook_docs.py --write`. "
        f"Category {letter} · {_category_name(letter)}."
    )
    out.append("")
    out.append("| | |")
    out.append("| --- | --- |")
    out.append(f"| Tier | `{tier}` |")
    out.append(f"| Action | {_code(action)} |")
    out.append(f"| Attempts | {entry.get('max_attempts')} · cooldown {entry.get('cooldown_min')} min |")
    out.append(f"| Verify | `{kind}` |")
    out.append(f"| Replay | {_cell(_hits_text(coverage_row, coverage))} |")
    out.append("")

    # 1 ------------------------------------------------------------------------------------------
    out.append("## 1. What fires it")
    out.append("")
    out.append(
        "The engine selects this entry when **any** of these holds. A `failure_class` is a lowercased set "
        "membership; a reason pattern is searched in `reason`/`failure_kind`/`detail`; an exception pattern is "
        "searched in the wider text — reason, failure kind, exception, detail, title, error and the last 4 000 "
        "characters of stderr/stdout:"
    )
    out.append("")
    classes = list(match.get("failure_class") or [])
    reasons = list(match.get("reason_regex") or [])
    exceptions = list(match.get("exception_regex") or [])
    if not (classes or reasons or exceptions):
        out.append("- **nothing** — this is the catch-all. It fires only when no other entry matched, and that is why "
                   "every signature it receives needs a written reason in `COVERAGE.md`.")
    for cls in classes:
        out.append(f"- failure class {_code(cls)}")
    for rx in reasons:
        out.append(f"- reason text matches {_code('/' + rx + '/')}")
    for rx in exceptions:
        out.append(f"- exception or tail text matches {_code('/' + rx + '/')}")
    out.append("")
    ordering = (f"It is selected by explicit priority **{entry['priority']}** (lowest matching priority wins; ids "
                f"break ties).")
    if higher:
        ordering += f" Should it not match, the next entry above it is `{higher[0]['id']}` (priority {higher[0]['priority']})."
    out.append(ordering)
    out.append("")

    # 2 ------------------------------------------------------------------------------------------
    out.append("## 2. Evidence to collect")
    out.append("")
    out.append("Collect these before planning. The plan is only as good as the evidence it is evaluated on, and a "
               "missing fact is a refusal, never an assumption.")
    out.append("")
    out.append("| field | why it is read |")
    out.append("| --- | --- |")
    seen: set[str] = set()
    for field, why in COMMON_EVIDENCE:
        seen.add(field)
        out.append(f"| `{_cell(field)}` | {_cell(why)} |")
    for check in pre:
        doc = PRECONDITION_DOCS[check]
        for field in doc["fields"]:
            if field in seen:
                continue      # the common row already names it; one row per field keeps the table scannable
            seen.add(field)
            out.append(f"| `{_cell(field)}` | {_cell('precondition ' + check + ': ' + doc['proves'])} |")
    out.append("")

    # 3 ------------------------------------------------------------------------------------------
    out.append("## 3. Diagnosis")
    out.append("")
    out.append("The engine evaluates these checks in this order; the first `ok: false` is the refusal and the plan's "
               "`reason` names it:")
    out.append("")
    for name, what in ENGINE_CHECKS:
        out.append(f"- `{name}` — {what}")
    out.append("")
    if pre:
        out.append("Then this entry's own preconditions, in the catalog's order:")
        out.append("")
        for check in pre:
            doc = PRECONDITION_DOCS[check]
            out.append(f"- **`{check}`** proves {doc['proves']} Collect: {doc['how']}")
    else:
        out.append("This entry declares **no preconditions**: it fires on the signature alone. That is only safe "
                   "because its action observes (or escalates) and writes nothing.")
    out.append("")
    out.append(f"To replay this entry: `python3 -m pytest tests/test_self_heal_runbooks_lq1231_20261108.py -k "
               f"'{eid}' -q` plans a synthetic incident into it; `tests/fixtures/self_heal_runbooks/` is the replay "
               f"corpus for the signatures seen in real receipts.")
    out.append("")

    # 4 ------------------------------------------------------------------------------------------
    out.append("## 4. The only action it may take")
    out.append("")
    out.append(_code(action))
    out.append("")
    out.append(adoc["does"])
    out.append("")
    if params:
        out.append(f"**Parameters.** {adoc['params']}")
        out.append("")
        out.append("| param | value |")
        out.append("| --- | --- |")
        for key, value in params.items():
            out.append(f"| `{_cell(key)}` | `{_cell(value)}` |")
        out.append("")
    else:
        out.append(f"**Parameters.** {adoc['params']}")
        out.append("")
    out.append(f"**It does not:** {adoc['not']}")
    out.append("")
    out.append(f"**Tier.** `{tier}` — {TIER_RULES[tier]}")
    out.append("")

    # 5 ------------------------------------------------------------------------------------------
    out.append("## 5. Verification")
    out.append("")
    window = ""
    if isinstance(entry.get("verify"), Mapping) and entry["verify"].get("window_s"):
        window = f", window {entry['verify']['window_s']} s"
    out.append(f"`verify.kind = {kind}`{window}. Verified means: {verify['means']}")
    out.append("")
    out.append("```bash")
    out.extend(verify["command"].splitlines())
    out.append("```")
    out.append("")
    out.append(f"**Expected:** {verify['expect']}")
    out.append("")

    # 6 ------------------------------------------------------------------------------------------
    out.append("## 6. Rollback")
    out.append("")
    out.append(adoc["rollback"])
    out.append("")

    # 7 ------------------------------------------------------------------------------------------
    out.append("## 7. Budget and cooldown")
    out.append("")
    out.append(f"- **Attempts:** {entry.get('max_attempts')}. At the cap the engine switches the action to "
               f"`escalate_finding` with `reason: max_attempts_reached`; it does not keep trying.")
    out.append(f"- **Cooldown:** {entry.get('cooldown_min')} min between this entry's actions on one lane.")
    out.append("- **Lane rate limit:** one mutating action per lane per hour. The observing actions "
               "(`noop_wait_recheck`, `escalate_finding`, `mark_weekend_expected`, "
               "`release_stale_sqlite_wal_lock`) are not rate-limited.")
    out.append("- **Idempotency:** the plan's key hashes the entry, lane, signature and attempt. It is stable across a "
               "day and across a restart, so applying the same plan twice is the same act.")
    out.append("")

    # 8 ------------------------------------------------------------------------------------------
    out.append("## 8. When to escalate, and what to send")
    out.append("")
    out.append("Escalate when any of these is true:")
    out.append("")
    out.append(f"- the attempt budget is spent ({entry.get('max_attempts')} attempts);")
    out.append("- a precondition refuses (`reason: precondition_failed:<check>`) — the action is not safe;")
    out.append("- verification still fails at the end of its window (§5);")
    out.append("- the tier is `human_only`: the engine escalates on the first plan by design.")
    out.append("")
    title = _render_title(str((entry.get("on_fail") or {}).get("title") or ""), entry)
    out.append("The FINDING title, rendered from the catalog with the plan's values:")
    out.append("")
    out.append("```text")
    out.append(title or "(the engine's default: self-heal runbook exhausted: <entry title>)")
    out.append("```")
    out.append("")
    out.append("Send it with the receipt it was rendered from: the plan's `lane`, `signature`, `entry`, `reason`, "
               "`attempts: n/max`, `checks[]`, `idempotency_key` and the receipt path — plus what §5's command "
               "printed. A FINDING without the receipt path cannot be audited.")
    out.append("")

    # 9 ------------------------------------------------------------------------------------------
    out.append("## 9. Human steps")
    out.append("")
    steps = list(entry.get("human_steps") or [])
    if not steps:
        out.append("(none declared)")
    for i, step in enumerate(steps, 1):
        out.append(f"{i}. {step}")
    out.append("")

    # 10 -----------------------------------------------------------------------------------------
    out.append("## 10. Tests")
    out.append("")
    out.append("The catalog declares these test labels (the plan requires at least three per entry: a match, a "
               "refusal on a failed precondition, and a repeat):")
    out.append("")
    for label in entry.get("tests") or []:
        out.append(f"- `{label}`")
    out.append("")
    out.append("The mechanical evidence that they hold:")
    out.append("")
    out.append("- `tests/test_self_heal_runbooks_lq1231_20261108.py` — schema, action whitelist, priorities, "
               "per-entry match, precondition refusal, repeat determinism, rate limit, dry-run default.")
    if fixtures:
        out.append("- the replay corpus fixture(s) that assert this entry resolve here: "
                   + ", ".join(f"`{name}.json`" for name in sorted(fixtures)) + ".")
    else:
        out.append("- no corpus fixture asserts this entry yet: the corpus covers signatures seen in receipts, and "
                   "this one has not been seen in the window (its evidence is the taxonomy, not a live receipt).")
    out.append("")
    out.append("```bash")
    out.append("python3 -m pytest tests/test_self_heal_runbooks_lq1231_20261108.py "
               "tests/test_self_heal_runbook_coverage_20261108.py -q")
    out.append("```")
    out.append("")
    out.append("---")
    out.append("")
    out.append("[Workbook index](INDEX.md) · [14-day coverage](COVERAGE.md) · "
               "[rulings behind the cells](RULINGS.md)")
    out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------- the index page


def render_index(catalog: Mapping[str, Mapping[str, Any]], coverage: Mapping[str, Any] | None, *,
                 version: str) -> str:
    entries = sorted(catalog.values(), key=lambda e: (str(e["category"]), int(e["priority"]), str(e["id"])))
    cov_entries = (coverage or {}).get("entries") or {}
    totals = (coverage or {}).get("totals") or {}
    out: list[str] = []
    out.append("# Self-heal runbook workbook")
    out.append("")
    out.append(
        f"Generated from `config/self_heal_runbook_catalog.json` v{version} and the replay snapshot `COVERAGE.json`. "
        f"**Do not edit any page in this directory except `README.md`, `RULINGS.md` and `COVERAGE.json`** — "
        f"regenerate with `python3 scripts/gen_self_heal_runbook_docs.py --write`."
    )
    out.append("")
    out.append("## How to use this workbook")
    out.append("")
    out.append("1. Find the signature in [COVERAGE.md](COVERAGE.md) — every failure seen in the last 14 days is a "
               "row, with the entry it plans to and its hit count.")
    out.append("2. Open that entry's page. It states the trigger, the evidence, the diagnosis order, the one action "
               "the fixer may take, and the command that proves the outcome.")
    out.append("3. If the entry is `human_only`, the page's action is **yours to run**, never the fixer's: the engine "
               "replaces it with an escalation.")
    out.append("4. If a signature is not in COVERAGE.md, do not improvise: it falls to `K05-unclassified-catch-all` "
               "and needs an entry of its own, or a written reason in the replay's `GATE_REASONS`.")
    out.append("5. [RULINGS.md](RULINGS.md) records why each disputed cell (action, tier) is what it is, so a reviewer "
               "can re-open one decision without re-reading the whole catalog.")
    out.append("")
    if coverage:
        out.append(f"**Window:** {coverage.get('window_start')} .. {coverage.get('as_of')} "
                   f"({coverage.get('window_days')} days). **{totals.get('window_failures', 0)} failures** · "
                   f"**{len(coverage.get('signatures') or [])} signatures** · "
                   f"**{len(cov_entries)} entries hit** · catch-all "
                   f"**{(coverage.get('catch_all') or {}).get('hits', 0)}**.")
    else:
        out.append("**No replay snapshot on this commit** — write one with `scripts/ops/self_heal_runbook_replay.py` "
                   "before trusting the coverage columns.")
    out.append("")

    out.append("## Entries by category")
    out.append("")
    out.append("| Cat | Name | Entries | auto | auto_notify | human_only | 14-day hits |")
    out.append("| --- | --- | --- | --- | --- | --- | --- |")
    for letter in sorted(CATEGORY_NAMES):
        rows = [e for e in entries if e["category"] == letter]
        if not rows:
            continue
        tiers = {t: sum(1 for e in rows if e["tier"] == t) for t in TIER_RULES}
        hits = sum(int((cov_entries.get(e["id"]) or {}).get("hits", 0)) for e in rows)
        out.append(f"| **{letter}** | {_category_name(letter)} | {len(rows)} | {tiers['auto']} | "
                   f"{tiers['auto_notify']} | {tiers['human_only']} | {hits} |")
    out.append("")

    out.append("## Every entry")
    out.append("")
    out.append("| Entry | Category | Tier | Action | Attempts | Cooldown | 14-day hits | Lanes |")
    out.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for entry in entries:
        eid = str(entry["id"])
        row = cov_entries.get(eid) or {}
        out.append(
            f"| [{_cell(eid)}]({eid}.md) | {entry['category']} | `{entry['tier']}` | `{entry['action']}` | "
            f"{entry.get('max_attempts')} | {entry.get('cooldown_min')} min | {row.get('hits', 0)} | "
            f"{len(row.get('lanes') or [])} |"
        )
    out.append("")

    out.append("## The action whitelist")
    out.append("")
    out.append("No other action is executable by the fixer, and mutating actions are refused on execution lanes "
               "before the catalog is consulted.")
    out.append("")
    for action in sorted(ACTION_DOCS):
        first = ACTION_DOCS[action]["does"].split(". ")[0].rstrip(".")
        out.append(f"- `{action}` — {first}.")
    out.append("")
    out.append("## Regenerating")
    out.append("")
    out.append("```bash")
    out.append("python3 scripts/ops/self_heal_runbook_replay.py --as-of <UTC instant> --window-days 14 \\")
    out.append("    --out docs/runbooks/self_heal/COVERAGE.json --check-gate")
    out.append("python3 scripts/gen_self_heal_runbook_docs.py --write")
    out.append("python3 -m pytest tests/test_self_heal_runbook_docs_20261108.py -q")
    out.append("```")
    out.append("")
    out.append("The replay is dry: it calls no action, writes no receipt and touches no lane.")
    out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------- the coverage page


def render_coverage(coverage: Mapping[str, Any]) -> str:
    totals = coverage.get("totals") or {}
    sigs = list(coverage.get("signatures") or [])
    entries = coverage.get("entries") or {}
    catch_all = coverage.get("catch_all") or {}
    catalog = coverage.get("catalog") or {}
    receipt_failures = int(totals.get("window_failures", 0)) - int(totals.get("dead_letters", 0))
    out: list[str] = []
    out.append("# 14-day failure coverage — every real signature to one catalog entry")
    out.append("")
    out.append(
        f"Generated from `COVERAGE.json` (`{coverage.get('schema')}`), written by "
        f"`scripts/ops/self_heal_runbook_replay.py` against the catalog v{catalog.get('version', '?')}. **Do not "
        f"edit** — re-run the replay."
    )
    out.append("")
    out.append("| | |")
    out.append("| --- | --- |")
    out.append(f"| Window | {coverage.get('window_start')} .. {coverage.get('as_of')} "
               f"({coverage.get('window_days')} days) |")
    out.append(f"| Receipts scanned | {totals.get('receipts_scanned', 0)} |")
    out.append(f"| Failures | **{totals.get('window_failures', 0)}** ({receipt_failures} receipt failures + "
               f"{totals.get('dead_letters', 0)} dead letters) |")
    out.append(f"| Signatures | {len(sigs)} |")
    out.append(f"| Entries hit | {len(entries)} of {catalog.get('entries', '?')} |")
    out.append(f"| Catch-all | **{catch_all.get('hits', 0)}** hit(s), "
               f"{len(catch_all.get('missing_reason') or [])} without a written reason |")
    out.append("")
    out.append("## The rule")
    out.append("")
    out.append(str(coverage.get("rule") or ""))
    out.append("")
    out.append("A signature is the failure state plus the normalized last stderr line — timestamps, paths, hex, long "
               "tokens, digits and **symbols** are collapsed — or the receipt's `reason` when there is no stderr. The "
               "same text is what the fixer keys an incident on, so 'covered' means 'this exact signature plans to an "
               "entry', not 'a similar one does'.")
    out.append("")

    out.append("## Per signature")
    out.append("")
    if not sigs:
        out.append("(no failures in the window)")
    else:
        out.append("`plans` lists what the engine answered for every occurrence of the signature, with its hit "
                   "count. A signature with more than one plan is not a defect: the *class* is derived from other "
                   "receipt fields (a dead letter carries only `exit_1`), so ONE short text can be several defects.")
        out.append("")
        out.append("| hits | class | signature | source | plans (entry · action · tier) |")
        out.append("| --- | --- | --- | --- | --- |")
        for row in sigs:
            sources = ", ".join(f"{k} {v}" for k, v in (row.get("sources") or {}).items())
            plans = row.get("plans") or [{"entry": row.get("entry"), "action": row.get("action"),
                                          "tier": row.get("tier"), "hits": row.get("hits")}]
            rendered = "; ".join(f"{p['entry']} · {p['action']} · {p['tier']} ({p['hits']})" for p in plans)
            out.append(f"| {row.get('hits')} | `{_cell(row.get('failure_class'))}` | "
                       f"`{_cell(row.get('signature'))}` | {_cell(sources)} | {_cell(rendered)} |")
    out.append("")

    out.append("## Per entry")
    out.append("")
    out.append("| Entry | hits | lanes | signatures |")
    out.append("| --- | --- | --- | --- |")
    for eid in sorted(entries, key=lambda k: (-int((entries[k] or {}).get("hits", 0)), k)):
        row = entries[eid] or {}
        out.append(f"| [{_cell(eid)}]({_cell(eid)}.md) | {row.get('hits', 0)} | {len(row.get('lanes') or [])} | "
                   f"{len(row.get('signatures') or [])} |")
    out.append("")

    out.append("## Catch-all")
    out.append("")
    if not catch_all.get("hits"):
        out.append("**Zero.** Every failure signature in the window plans to an entry of its own. That is the "
                   "catalog's hard requirement; `--check-gate` exits 3 if it ever stops being true.")
    else:
        out.append("Each signature below reaches `K05-unclassified-catch-all`. It must either get an entry of its "
                   "own or a written reason in the replay's `GATE_REASONS`; an unexplained row fails the gate.")
        out.append("")
        out.append("| hits | signature | written reason |")
        out.append("| --- | --- | --- |")
        for row in catch_all.get("signatures") or []:
            out.append(f"| {row.get('hits')} | `{_cell(row.get('signature'))}` | "
                       f"{_cell(row.get('reason_written') or '**MISSING**')} |")
    out.append("")

    out.append("## What this replay cannot see")
    out.append("")
    out.append("- **Only what the receipts and dead letters recorded.** A lane that failed before it wrote a receipt "
               "is invisible here; the mining taxonomy covers the wider 30-day window.")
    out.append("- **Only the last stderr line.** A failure whose distinguishing text is an earlier line is counted "
               "under the last one; the mining taxonomy has the same limit.")
    out.append("- **Classification, not success.** A hit proves an entry answers the signature. It does not prove the "
               "entry's action would have worked — only a graded run does that, and none may run while the self-heal "
               "freeze holds.")
    out.append("- **Lanes without failures** contribute nothing; an entry at 0 hits is unexercised, not dead.")
    out.append("")
    out.append("## Reproduce")
    out.append("")
    out.append("```bash")
    out.append(f"python3 scripts/ops/self_heal_runbook_replay.py --as-of {coverage.get('as_of')} "
               f"--window-days {coverage.get('window_days')} \\")
    out.append("    --out docs/runbooks/self_heal/COVERAGE.json --check-gate")
    out.append("```")
    out.append("")
    out.append("[Workbook index](INDEX.md)")
    out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------- the whole set


def render_all(catalog_doc: Mapping[str, Any], coverage: Mapping[str, Any] | None, *,
               fixtures_by_entry: Mapping[str, Iterable[str]] | None = None) -> dict[str, str]:
    """Every generated file as ``{relative path under docs/runbooks/self_heal: text}``.

    ``catalog_doc`` is the whole catalog document (``version`` + ``runbooks``), so a page's header names the catalog
    it was rendered from.
    """
    entries = {str(e["id"]): e for e in catalog_doc.get("runbooks") or []}
    version = str(catalog_doc.get("version") or "unknown")
    files: dict[str, str] = {}
    for eid, entry in entries.items():
        files[f"{eid}.md"] = render_entry(
            entry, entries, version=version, coverage=coverage,
            fixtures=(fixtures_by_entry or {}).get(eid, ()),
        )
    files["INDEX.md"] = render_index(entries, coverage, version=version)
    if coverage is not None:
        files["COVERAGE.md"] = render_coverage(coverage)
    return files
