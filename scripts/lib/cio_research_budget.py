"""ResearchBudget@v1 — a per-instrument daily budget, not a drain.

Slices A–C gave the desk a memory (InstrumentRecord@v1), made it read that
memory (cio_rehydrate), and gave it a ladder to route one question
(ResearchNeedDecision@v2). What none of them bounded is HOW MANY questions the
desk asks in a day. The gate answers "what should run for THIS subject"; asked
40 times it happily answers 40 times, and "drain everything eligible" is what
turned one cash question into 36 paid jobs.

This module answers the question above the gate: *which few subjects get a
decision at all today.*

    daily cap N = 5
        3  HELD
        1  SLEEVE:CASH
        1  re-entry NEAR  — else a watch READY, if there is one

Three laws, in this order:

  **the collapse law** — ONE decision per subject_key per calendar day. The
  budget is expressed in SUBJECTS, never in plans, which is why 36 open S5
  cash plans cost one slot and not 36: they are all the same subject,
  `SLEEVE:CASH`. `collapse_plans_to_subjects()` is where the fan-in happens and
  `BudgetLedger` is what stops a second run of the day re-asking.

  **prefer movement over the calendar** — a subject whose observable hash
  actually moved outranks one that is merely due, and a due subject outranks
  one that has never been looked at. A subject whose `next_eligible_at` is in
  the future is not eligible at all: that date is usually an operator defer,
  and spending a slot on it would undo the very thing Slice B exists to
  remember.

  **the dust/cash/TEST refusal** — enforced by `is_mintable()`, the same
  predicate that guards minting. Cash is `SLEEVE:CASH`, a sleeve; it is never
  a ticker.

**MBI_BEHAVIOR = 0. MBI_COGNITION = 1.** This module chooses WHICH subject the
desk thinks about today. It produces no size, no order and no delta, and it
takes no vendor hop — it does not even call the gate. It hands a short list to
whoever does.

READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from scripts.lib.cio_instrument_record import (
    CASH_SLEEVE, hash_changed, is_mintable, parse_subject_key,
)

SCHEMA = "ResearchBudget@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
FINANCIAL_ACTION = False
MBI_BEHAVIOR = 0
MBI_COGNITION = 1

# The operator's starting cap. Deliberately small: the point of a budget is
# that it binds. Raising it is a one-line operator change, not a code change.
DAILY_CAP = 5
HELD_SLOTS = 3
CASH_SLOTS = 1
REENTRY_OR_WATCH_SLOTS = 1

SLOT_HELD = "held"
SLOT_CASH = "cash"
SLOT_REENTRY_OR_WATCH = "reentry_or_watch"
SLOTS = (SLOT_HELD, SLOT_CASH, SLOT_REENTRY_OR_WATCH)

# Which record kind can fill the fifth slot, and under which status label.
# A re-entry candidate is a name the book already exited and is watching to buy
# back, so it lives on the EXIT record; a promotion candidate is a WATCH.
#
# The labels are NOT recomputed here. They are the literals the two existing
# books already publish, and this module only reads them:
#
#   re-entry  cio_investment_product.build_reentry_book (Surface A)
#             status ∈ {REENTER, NEAR, WAIT, AVOID}
#   watch     data_broker.watch_intelligence.normalize_watch_s7_status
#             status ∈ {READY, GO, NEAR, BLOCK}
#
# The operator's spec says "1 re-entry NEAR" and "1 watch READY". Each set here
# also admits the one label that is strictly STRONGER than the named one —
# REENTER for re-entry, GO for watch — because each book's own ordering already
# ranks it above: `_OPP_STATUS_PREF` puts REENTER at rank 0 and NEAR at 1, and
# `collect_watch_block_summary` counts READY and GO together as
# `ready_symbols`. Admitting only the weaker label would spend the slot on the
# weaker candidate while the better one waited, which is not what a budget is
# for. Sorting is by the book's preference, so NEAR is only picked when no
# REENTER is eligible.
REENTRY_KIND = "EXIT"
REENTRY_STATUS = "NEAR"
REENTRY_STATUSES = ("REENTER", "RE_ENTER", "NEAR")
WATCH_KIND = "WATCH"
WATCH_STATUS = "READY"
WATCH_STATUSES = ("GO", "READY")

# Eligibility ranks. Lower sorts first. These ARE the preference law.
RANK_EVENT = 0        # an observable hash moved — the answer may be wrong now
RANK_DUE = 1          # next_eligible_at has passed
RANK_NEVER = 2        # never scheduled; no prior belief to protect
RANK_INELIGIBLE = 9

RANK_REASON = {
    RANK_EVENT: "hash_changed",
    RANK_DUE: "next_eligible_at_due",
    RANK_NEVER: "never_scheduled",
}

# Observables whose movement outranks the calendar. Same list as
# cio_rehydrate.EVENT_HASHES — imported rather than re-typed would create an
# import cycle through the gate, so it is asserted equal in the tests instead.
EVENT_HASHES = ("weight", "earnings")

# Plan situation_type -> the SUBJECT it actually asks about. The whole point of
# the collapse law: every S5 cash plan, however many there are, is one question
# about one sleeve.
CASH_SITUATION_TYPES = frozenset({
    "S5_CASH_DEPLOYMENT", "S5", "S5_CASH", "cash_deployment",
})
HELD_SITUATION_TYPES = frozenset({
    "S1_POSITION_LIFECYCLE", "S6_CONCENTRATION_OR_DISPOSITION",
})
REENTRY_SITUATION_TYPES = frozenset({"S3_REENTRY_CANDIDATE"})
WATCH_SITUATION_TYPES = frozenset({"S7_WATCH_PROMOTION"})

LEDGER_RELPATH = ("data", "cio", "cio_research_budget_ledger.jsonl")


def _now(now: Optional[datetime] = None) -> datetime:
    dt = now or datetime.now(timezone.utc)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _parse(ts: Any) -> Optional[datetime]:
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def ledger_path(root: Path | str | None = None) -> Path:
    """Resolve the ledger from an EXPLICIT root, never from the CWD.

    Several CIO stores use a bare relative path and therefore silently follow
    whichever directory the process happens to start in; a tool run from the
    wrong place reports an empty book and a clean bill of health. The ledger is
    the record of what the desk already spent today, so a CWD-dependent answer
    here would let a second run re-ask every subject. Root defaults to the
    repository, not to `.`.
    """
    return Path(root or _project_root()).joinpath(*LEDGER_RELPATH)


def day_of(now: Optional[datetime] = None) -> str:
    """The calendar day the collapse law is scoped to. UTC, explicitly."""
    return _now(now).date().isoformat()


# ── the collapse law, at the input edge ───────────────────────────────────

def subject_key_for_plan(plan: dict[str, Any]) -> Optional[str]:
    """Map one plan to the SUBJECT it is really asking about.

    A plan is episodic; a subject is not. Returning `SLEEVE:CASH` for every S5
    row is not a simplification, it is the correct answer — those rows differ
    in which lot they propose, and the desk is not being asked about lots.
    """
    if not isinstance(plan, dict):
        return None
    situation = str(plan.get("situation_type") or "").strip()
    if situation in CASH_SITUATION_TYPES:
        return CASH_SLEEVE
    symbols = [str(s).strip().upper() for s in (plan.get("symbols") or []) if str(s).strip()]
    sym = symbols[0] if symbols else ""
    if not sym:
        return None
    if situation in REENTRY_SITUATION_TYPES:
        kind = REENTRY_KIND
    elif situation in WATCH_SITUATION_TYPES:
        kind = WATCH_KIND
    elif situation in HELD_SITUATION_TYPES:
        kind = "HELD"
    else:
        return None
    ok, _reason = is_mintable(kind, sym)
    if not ok:
        return None
    return f"{kind}:{sym}"


def collapse_plans_to_subjects(
    plans: Iterable[dict[str, Any]],
) -> dict[str, list[str]]:
    """subject_key -> the plan_ids that collapsed into it. Order preserved.

    This is the function the "36 S5 cash plans" test pins. It must return ONE
    `SLEEVE:CASH` entry carrying 36 plan_ids, never 36 entries.
    """
    out: dict[str, list[str]] = {}
    for plan in plans or []:
        key = subject_key_for_plan(plan)
        if not key:
            continue
        out.setdefault(key, []).append(str(plan.get("plan_id") or ""))
    return out


# ── eligibility and preference ────────────────────────────────────────────

def eligibility(
    record: dict[str, Any],
    *,
    now: Optional[datetime] = None,
    observed: Optional[dict[str, Any]] = None,
    market_value: Optional[float] = None,
) -> dict[str, Any]:
    """Rank one subject. Returns {eligible, rank, reason, subject_key}.

    A future `next_eligible_at` makes a subject INELIGIBLE rather than merely
    low-ranked. That date is how the record remembers the operator said wait,
    and a budget that outranks a defer whenever the day is quiet has quietly
    deleted the defer.
    """
    now = _now(now)
    rec = record or {}
    key = str(rec.get("subject_key") or "")
    kind, name = parse_subject_key(key)

    def out(eligible: bool, rank: int, reason: str) -> dict[str, Any]:
        return {"subject_key": key, "kind": kind, "eligible": eligible,
                "rank": rank, "reason": reason}

    if not key:
        return out(False, RANK_INELIGIBLE, "no_subject_key")

    mintable, why = is_mintable(kind, name, market_value=market_value)
    if not mintable:
        # dust / TEST / cash-as-a-ticker. Never selected, whatever else is true.
        return out(False, RANK_INELIGIBLE, f"refused:{why}")

    if rec.get("research_blocked"):
        # Slice B set this when an artifact was refused or carried execution
        # language. Re-spending a slot on it is how a desk burns a budget
        # learning nothing.
        return out(False, RANK_INELIGIBLE, "research_blocked")

    for observable in EVENT_HASHES:
        obs = (observed or {})
        if observable in obs and hash_changed(rec, observable, obs[observable]):
            return out(True, RANK_EVENT, f"hash_changed:{observable}")

    nxt = _parse(rec.get("next_eligible_at"))
    if nxt is None:
        return out(True, RANK_NEVER, RANK_REASON[RANK_NEVER])
    if now < nxt:
        return out(False, RANK_INELIGIBLE, "not_due")
    return out(True, RANK_DUE, RANK_REASON[RANK_DUE])


def _sort_key(row: dict[str, Any]) -> tuple:
    """(rank, least-recently-touched, subject_key).

    The tie-break is `updated_ts` ascending so a quiet book ROTATES: the three
    held names that got today's slots are the three most recently touched
    tomorrow, and therefore sort last. Alphabetical order would have picked the
    same three names every day forever and called it a budget.
    """
    return (int(row.get("rank", RANK_INELIGIBLE)),
            str(row.get("updated_ts") or ""),
            str(row.get("subject_key") or ""))


# ── the ledger: one decision per subject per day ──────────────────────────

class BudgetLedger:
    """Append-only record of which subjects already spent a slot, by day.

    Append-only for the same reason the record store is: the value is the
    history of what the desk chose to look at and when. A run that finds
    everything already decided is a healthy run, not a broken one.
    """

    def __init__(self, path: Path | str | None = None,
                 *, root: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else ledger_path(root)

    def rows(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        try:
            if not self.path.is_file():
                return out
            with open(self.path, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except Exception:                            # noqa: BLE001
                        continue
        except OSError:
            return out
        return out

    def decided_on(self, day: str) -> set[str]:
        """Subject keys that already had their one decision on `day`."""
        d = str(day)
        return {str(r.get("subject_key")) for r in self.rows()
                if str(r.get("day")) == d and r.get("subject_key")}

    def record(self, selection: dict[str, Any]) -> int:
        """Persist a selection. Returns the number of rows appended."""
        day = str(selection.get("day") or "")
        run_id = selection.get("run_id")
        picked = selection.get("selected") or []
        if not day or not picked:
            return 0
        already = self.decided_on(day)
        rows = [
            {"schema": SCHEMA, "authority": AUTHORITY,
             "financial_action": FINANCIAL_ACTION,
             "day": day, "run_id": run_id,
             "subject_key": row.get("subject_key"), "slot": row.get("slot"),
             "rank": row.get("rank"), "reason": row.get("reason"),
             "plan_ids": row.get("plan_ids") or [],
             "ts": selection.get("as_of")}
            for row in picked
            if row.get("subject_key") and str(row["subject_key"]) not in already
        ]
        if not rows:
            return 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")
        return len(rows)


# ── selection ─────────────────────────────────────────────────────────────

def select(
    records: Iterable[dict[str, Any]],
    *,
    now: Optional[datetime] = None,
    observed: Optional[dict[str, dict[str, Any]]] = None,
    statuses: Optional[dict[str, str]] = None,
    plan_subjects: Optional[dict[str, list[str]]] = None,
    market_values: Optional[dict[str, float]] = None,
    already_decided: Optional[Iterable[str]] = None,
    cap: int = DAILY_CAP,
    held_slots: int = HELD_SLOTS,
    run_id: Optional[str] = None,
) -> dict[str, Any]:
    """Pick at most `cap` subjects for today. Deterministic; touches nothing.

    `statuses` maps subject_key -> the surface label the re-entry book / watch
    desk already computed ("NEAR", "READY", ...). This module does not
    recompute those: two laws over one label drift apart, and the drift is
    invisible until someone diffs them by hand.

    `already_decided` is the collapse law's memory — normally
    `BudgetLedger.decided_on(day)`.
    """
    now = _now(now)
    obs = observed or {}
    stat = {str(k): str(v or "").strip().upper() for k, v in (statuses or {}).items()}
    plan_map = plan_subjects or {}
    mvs = market_values or {}
    spent = {str(s) for s in (already_decided or set())}
    cap = max(0, int(cap))
    held_slots = max(0, int(held_slots))

    ranked: list[dict[str, Any]] = []
    refused: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []

    for rec in records or []:
        if not isinstance(rec, dict):
            continue
        key = str(rec.get("subject_key") or "")
        verdict = eligibility(rec, now=now, observed=obs.get(key),
                              market_value=mvs.get(key))
        row = {
            "subject_key": key,
            "kind": verdict["kind"],
            "rank": verdict["rank"],
            "reason": verdict["reason"],
            "status": stat.get(key),
            "next_eligible_at": rec.get("next_eligible_at"),
            "updated_ts": rec.get("updated_ts"),
            "plan_ids": list(plan_map.get(key) or []),
        }
        if not verdict["eligible"]:
            (refused if verdict["reason"].startswith("refused:")
             else deferred).append(row)
            continue
        if key in spent:
            row["reason"] = "already_decided_today"
            deferred.append(row)
            continue
        ranked.append(row)

    ranked.sort(key=_sort_key)

    selected: list[dict[str, Any]] = []
    taken: set[str] = set()

    def fill(slot: str, candidates: list[dict[str, Any]], n: int) -> None:
        for row in candidates:
            if len(selected) >= cap or n <= 0:
                return
            key = row["subject_key"]
            if key in taken:
                continue
            picked = dict(row)
            picked["slot"] = slot
            selected.append(picked)
            taken.add(key)
            n -= 1

    def by_status(kind: str, order: tuple[str, ...]) -> list[dict[str, Any]]:
        """Eligible rows of `kind`, strongest published status first.

        The status ordering is the OUTER sort: a REENTER that is merely due
        beats a NEAR whose hash moved, because the two books have already
        adjudicated which candidate is the better one and this module does not
        get to second-guess that with its own freshness opinion.
        """
        rows = [r for r in ranked if r["kind"] == kind and r["status"] in order]
        rows.sort(key=lambda r: (order.index(r["status"]), _sort_key(r)))
        return rows

    held = [r for r in ranked if r["kind"] == "HELD"]
    cash = [r for r in ranked if r["subject_key"] == CASH_SLEEVE]
    reentry = by_status(REENTRY_KIND, REENTRY_STATUSES)
    watch = by_status(WATCH_KIND, WATCH_STATUSES)

    fill(SLOT_HELD, held, held_slots)
    fill(SLOT_CASH, cash, CASH_SLOTS)
    # "1 re-entry NEAR if any, else 1 watch READY if any" — an ELSE, not a
    # merge. A book with both spends the slot on the re-entry.
    fill(SLOT_REENTRY_OR_WATCH, reentry or watch, REENTRY_OR_WATCH_SLOTS)

    unselected = [r for r in ranked if r["subject_key"] not in taken]
    by_rank: dict[str, int] = {}
    for row in selected:
        r = RANK_REASON.get(int(row["rank"]), "other")
        by_rank[r] = by_rank.get(r, 0) + 1

    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "financial_action": FINANCIAL_ACTION,
        "memory_behavior_influence": MBI_BEHAVIOR,
        "memory_cognition_influence": MBI_COGNITION,
        "as_of": now.isoformat(),
        "day": day_of(now),
        "run_id": run_id,
        "cap": cap,
        "slots": {SLOT_HELD: held_slots, SLOT_CASH: CASH_SLOTS,
                  SLOT_REENTRY_OR_WATCH: REENTRY_OR_WATCH_SLOTS},
        "considered": len(list(ranked)) + len(deferred) + len(refused),
        "eligible": len(ranked),
        "selected": selected,
        "selected_count": len(selected),
        "selected_by_rank": by_rank,
        "not_selected_sample": [
            {"subject_key": r["subject_key"], "kind": r["kind"],
             "reason": "cap_reached" if r["rank"] != RANK_INELIGIBLE else r["reason"]}
            for r in unselected[:20]
        ],
        "deferred_count": len(deferred),
        "deferred_by_reason": _tally(deferred),
        "refused_count": len(refused),
        "refused_by_reason": _tally(refused),
        "note": ("selected=0 is healthy when every subject is deferred or "
                 "already decided today; a budget that finds no work is not a "
                 "failed run."),
    }


def _tally(rows: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        k = str(r.get("reason") or "unknown")
        out[k] = out.get(k, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))
