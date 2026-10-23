"""Ops -> Controls, n8n lanes tab: what each lane actually did, and whether it may climb the ladder.

Operator 2026-10-22 on /v3/system/ops-controls: "Why do some of these say live? Some of them say dry runs. I don't
know if the last one was success or failure. This is not a real dashboard... When is everything going live?"

This module joins three read-only sources per lane and returns display fields; it decides and changes nothing.

* **Outcomes** — the n8n coordination ledger (sqlite, opened ``mode=ro`` with ``PRAGMA query_only``): ``run_outcomes``
  (the async run-outcome callback, one row per terminal run since 2026-10-15), ``runs`` (fallback for older history
  and the RunReceipt of the last live success), ``dead_letters`` and ``breakers``. Every query is per lane and rides an
  index (``run_outcomes_lane (lane_id, recorded_at)``, ``runs_lane_state (lane_id, state)``, the ``runs`` primary key,
  ``dead_letters_lane``); ``breakers`` is one row per lane. No query scans a whole table and no row set is unbounded:
  this server was OOM-killed on 2026-10-22 by unbounded reads (#1963).
* **Schedule** — the registry ``dispatch.cron`` (else the n8n ``scheduler.cadence``, else a cron ``expression``) in
  ``dispatch.tz`` through ``scripts/lib/cron_schedule.py``: the next fire, and the last fire the lane should already
  have answered (STALE).
* **Promotion readiness** — the documented ladder only, no invented threshold:
  shadow -> canary: ``N8N_ONBOARDING_STANDARD.md`` steps 3, 5, 8, 9 and rule 5 (a workflow without a REVIEWED health
  contract does not leave shadow; a clean ``dry_run`` RUN_DONE after any failure, no number of shadow days; the cron
  line's ``flock`` lock equals the allowlist lock, §23.12 / §2 rule 4). canary -> cutover: AGENTS.md §23.21 (16.0.0,
  ACTIVE) (1) defect fixed, (2) latest dry_run RUN_DONE, (3) lane regression tests (owed in the cutover PR, not
  measurable here), (4) >= 1 successful ``live`` n8n run with the cron line present under the shared lock and its
  output_signal advanced; a ``RUN_SKIPPED_LOCK`` is not that run. BLOCKED = registry not ACTIVE, an operator hold, the
  never-list (``lane_dispatch.dispatch_eligible``), an allowlist ``blocked_reasons`` entry, no allowlist entry, or a
  health contract that is missing / not REVIEWED / carries UNKNOWN fields.

Promotions are operator decisions (a reviewed registry PR, §23.11); this only produces the evidence.
AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0. No broker, no send, no write.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional

from scripts.lib import cron_schedule as CS
from scripts.lib import lane_dispatch as LD

DEFAULT_LEDGER = "~/trade-ai-releases/persistent-state/data/governance/n8n_coordination_ledger.sqlite"
CACHE_TTL_S = 60.0
MAX_LANES = 400  # registry has ~120 n8n rows; a bound, not a target
STALE_GRACE = timedelta(minutes=45)  # a slot is "missed" only this long after it was due (queue + timeout headroom)
DEFAULT_TZ = CS.DEFAULT_TZ
TERMINAL = ("RUN_DONE", "RUN_FAILED", "RUN_TIMEOUT", "RUN_SKIPPED_LOCK", "RUN_REFUSED")
OUTCOME = {
    "RUN_DONE": "SUCCESS",
    "RUN_FAILED": "FAILED",
    "RUN_TIMEOUT": "TIMEOUT",
    "RUN_SKIPPED_LOCK": "SKIPPED",
    "RUN_REFUSED": "REFUSED",
}
FAIL = frozenset({"FAILED", "TIMEOUT", "REFUSED"})
ALLOWLIST_REL = Path("config") / "n8n_run_allowlist.json"
CONTRACTS_REL = Path("config") / "n8n_health_contracts.json"
CUTOVER_POLICY_REL = Path("config") / "lane_cutover_policy.json"

# Verdicts (UI mirrors these strings; docs/ops/OPS_CONTROLS.md "n8n lanes tab").
OK, FAILING, STALE, NEVER_RAN, OFF = "OK", "FAILING", "STALE", "NEVER_RAN", "OFF"
READY_CANARY, READY_CUTOVER, NOT_READY, BLOCKED, CUT_OVER, N_A = (
    "READY_FOR_CANARY",
    "READY_FOR_CUTOVER",
    "NOT_READY",
    "BLOCKED",
    "CUT_OVER",
    "N_A",
)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if dt else None


def _ts(v: Any) -> Optional[datetime]:
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


# ── ledger (read-only, bounded) ─────────────────────────────────────────────────────────────────────────────────


@dataclass
class LaneLedger:
    last: Optional[dict] = None  # latest terminal run, any mode
    last_success: Optional[dict] = None
    last_dry: Optional[dict] = None  # latest terminal dry_run
    last_live: Optional[dict] = None  # latest terminal live
    last_live_success: Optional[dict] = None
    live_output_advanced: Optional[bool] = None  # RunReceipt of last_live_success: output_signal mtime after > before
    runs_7d: dict = field(default_factory=lambda: {"dry_run": 0, "live": 0})
    outcomes_7d: dict = field(default_factory=dict)  # {"SUCCESS": n, "FAILED": n, ...}
    failures_24h: int = 0
    failures_7d: int = 0
    dead_letters_open: int = 0
    dead_letter_last: Optional[dict] = None
    breaker_open: bool = False


def _row(r: tuple, source: str) -> dict:
    run_id, mode, state, exit_code, reason, at = r
    return {
        "run_id": run_id,
        "mode": mode,
        "state": state,
        "outcome": OUTCOME.get(state, str(state or "").replace("RUN_", "")),
        "exit_code": exit_code,
        "reason": (str(reason)[:200] if reason else None),
        "at": at,
        "source": source,
    }


_O_COLS = "run_id, mode, run_state, exit_code, reason, coalesce(finished_at, recorded_at)"
_R_COLS = "run_id, mode, state, exit_code, NULL, coalesce(finished_at, requested_at)"


#: Ledger run-key namespaces: d = dispatcher slot, f / e = forced fires (n8n_due.slot_key, coordination/run).
RUN_KEY_PREFIXES = ("d", "f", "e")
SCAN_CAP = 500  # rows an older-history lookup may walk per lane (run_outcomes / runs), newest first


def _last(
    c: sqlite3.Connection,
    lane: str,
    *,
    mode: Optional[str] = None,
    state: Optional[str] = None,
    before: Optional[str] = None,
) -> Optional[dict]:
    """Newest terminal run for the lane (optionally one mode / one state), bounded:
    1. run_outcomes, newest SCAN_CAP rows of the lane (index run_outcomes_lane), optionally older than ``before``;
    2. runs, by the run-key prefixes ``d|f|e:<lane>:<mode>:`` on the primary key (slot keys sort by time), newest
       SCAN_CAP keys per prefix — history from before the run-outcome callback existed (2026-10-15).
    Never an unbounded walk: a lane with no match inside the caps reads as "not found"."""
    inner, a = "SELECT * FROM run_outcomes WHERE lane_id=?", [lane]
    if before:
        inner, a = inner + " AND recorded_at < ?", a + [before]
    q = f"SELECT {_O_COLS} FROM ({inner} ORDER BY recorded_at DESC LIMIT {SCAN_CAP}) WHERE 1=1"
    if mode:
        q, a = q + " AND mode=?", a + [mode]
    if state:
        q, a = q + " AND run_state=?", a + [state]
    r = c.execute(q + " ORDER BY recorded_at DESC LIMIT 1", a).fetchone()
    if r:
        return _row(r, "run_outcomes")
    states = [state] if state else list(TERMINAL)
    best = None
    for pre, m in [(p, m) for p in RUN_KEY_PREFIXES for m in ([mode] if mode else ["dry_run", "live"])]:
        lo = f"{pre}:{lane}:{m}:"
        hi = lo[:-1] + ";"  # ';' sorts right after ':'
        q = (
            f"SELECT {_R_COLS} FROM (SELECT * FROM runs WHERE run_id >= ? AND run_id < ? ORDER BY run_id DESC "
            f"LIMIT {SCAN_CAP}) WHERE state IN ({','.join('?' * len(states))}) ORDER BY run_id DESC LIMIT 1"
        )
        r = c.execute(q, [lo, hi, *states]).fetchone()
        if r:
            best = _newer(best, _row(r, "runs"))
    return best


def _at(c: sqlite3.Connection, lane: str, recorded_at: str) -> Optional[dict]:
    r = c.execute(
        f"SELECT {_O_COLS} FROM run_outcomes WHERE lane_id=? AND recorded_at=? LIMIT 1", (lane, recorded_at)
    ).fetchone()
    return _row(r, "run_outcomes") if r else None


def _newer(a: Optional[dict], b: Optional[dict]) -> Optional[dict]:
    if not a or not b:
        return a or b
    return (
        a
        if (_ts(a["at"]) or datetime.min.replace(tzinfo=timezone.utc))
        >= (_ts(b["at"]) or datetime.min.replace(tzinfo=timezone.utc))
        else b
    )


def _output_advanced(c: sqlite3.Connection, run_id: str) -> Optional[bool]:
    r = c.execute("SELECT receipt_json FROM runs WHERE run_id=?", (run_id,)).fetchone()  # primary key
    if not r or not r[0]:
        return None
    try:
        rec = json.loads(r[0])
    except ValueError:
        return None
    before, after = rec.get("output_signal_mtime_before"), rec.get("output_signal_mtime_after")
    if not isinstance(after, (int, float)):
        return None
    return after > (before if isinstance(before, (int, float)) else 0)


def connect_ro(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(str(path))
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2.0)
    c.execute("PRAGMA query_only=1")
    return c


def read_ledger(path: Path, lane_ids: Iterable[str], now: datetime) -> dict[str, LaneLedger]:
    lanes = list(dict.fromkeys(lane_ids))[:MAX_LANES]
    # run_outcomes stores ISO text with a +00:00 offset; compare in the same text form
    d7 = (now - timedelta(days=7)).astimezone(timezone.utc).isoformat()
    d1 = (now - timedelta(days=1)).astimezone(timezone.utc).isoformat()
    out: dict[str, LaneLedger] = {}
    c = connect_ro(path)
    try:
        breakers = {
            r[0]: r
            for r in c.execute(
                "SELECT lane_id, opened_at, released_at FROM breakers LIMIT ?", (MAX_LANES * 4,)
            ).fetchall()
        }
        for lane in lanes:
            L = LaneLedger()
            newest: dict[tuple[str, str], str] = {}  # (mode, run_state) -> newest recorded_at in the 7-day window
            for mode, st, n, n24, mx in c.execute(
                "SELECT mode, run_state, count(*), sum(recorded_at >= ?), max(recorded_at) FROM run_outcomes "
                "WHERE lane_id=? AND recorded_at >= ? GROUP BY mode, run_state",
                (d1, lane, d7),
            ):
                oc = OUTCOME.get(st, str(st).replace("RUN_", ""))
                L.outcomes_7d[oc] = L.outcomes_7d.get(oc, 0) + n
                mk = mode if mode in ("dry_run", "live") else "other"
                L.runs_7d[mk] = L.runs_7d.get(mk, 0) + n
                if oc in FAIL:
                    L.failures_7d += n
                    L.failures_24h += int(n24 or 0)
                newest[(str(mode), str(st))] = mx

            def pick(mode: Optional[str] = None, state: Optional[str] = None) -> Optional[dict]:
                ts = [
                    v
                    for (m, st), v in newest.items()
                    if (mode is None or m == mode)
                    and (state is None or st == state)
                    and (state is not None or st in TERMINAL)
                ]
                if ts:
                    return _at(c, lane, max(ts))
                return _last(c, lane, mode=mode, state=state, before=d7)

            L.last = pick()
            if L.last:
                L.last_success = L.last if L.last["outcome"] == "SUCCESS" else pick(state="RUN_DONE")
                L.last_dry = pick(mode="dry_run")
                L.last_live = pick(mode="live")
                L.last_live_success = (
                    L.last_live
                    if L.last_live and L.last_live["outcome"] == "SUCCESS"
                    else pick(mode="live", state="RUN_DONE")
                )
                if L.last_live_success:
                    L.live_output_advanced = _output_advanced(c, L.last_live_success["run_id"])
            dl = c.execute(
                "SELECT dead_at, last_state, last_reason FROM dead_letters WHERE lane_id=? "
                "AND released_at IS NULL ORDER BY dead_at DESC LIMIT 20",
                (lane,),
            ).fetchall()
            L.dead_letters_open = len(dl)
            if dl:
                L.dead_letter_last = {"at": dl[0][0], "state": dl[0][1], "reason": (dl[0][2] or "")[:200] or None}
            b = breakers.get(lane)
            if b and b[1] and (not b[2] or str(b[2]) < str(b[1])):
                L.breaker_open = True
            out[lane] = L
    finally:
        c.close()
    return out


# ── schedule ────────────────────────────────────────────────────────────────────────────────────────────────────


def cron_exprs(row: Mapping[str, Any]) -> tuple[list[str], str]:
    s, d = row.get("scheduler") or {}, row.get("dispatch") or {}
    cands: list[str] = []
    if isinstance(d.get("cron"), list):
        cands = [str(x) for x in d["cron"]]
    elif isinstance(d.get("cron"), str):
        cands = [d["cron"]]
    if not cands:
        cands = [str(x) for x in (s.get("cadence"), s.get("expression")) if x]
    good = []
    for e in cands:
        try:
            CS.parse(e)
        except (ValueError, TypeError, IndexError):
            continue
        good.append(e)
    return good, str(d.get("tz") or DEFAULT_TZ)


def next_fire(exprs: list[str], tz: str, now: datetime) -> Optional[datetime]:
    best = None
    for e in exprs:
        for span in (timedelta(hours=2), timedelta(days=2), timedelta(days=8)):
            try:
                f = CS.fires_between(e, now, now + span, tz)
            except ValueError:
                break
            if f:
                best = f[0].at if best is None or f[0].at < best else best
                break
    return best


def last_due(exprs: list[str], tz: str, at: datetime) -> Optional[datetime]:
    best = None
    for e in exprs:
        try:
            f = CS.last_fire_at_or_before(e, at, tz)
        except ValueError:
            continue
        if f is not None and (best is None or f.at > best):
            best = f.at
    return best


# ── per-lane verdicts (pure) ────────────────────────────────────────────────────────────────────────────────────


def effective_mode(row: Mapping[str, Any], on_live_list: Optional[bool]) -> str:
    """What a fire of this lane actually does today: off | dry_run | live | unknown. The stage clamps the mode
    (shadow -> dry_run, lane_stage_clamp); a live row not on the relay live list is posted as dry_run
    (n8n_due._relay_dispatch_mode)."""
    s, d = row.get("scheduler") or {}, row.get("dispatch") or {}
    if row.get("state") not in (None, "ACTIVE") or d.get("mode") == "off":
        return "off"
    if s.get("stage") == "shadow" or d.get("mode") == "dry_run":
        return "dry_run"
    if on_live_list is None:
        return "unknown"
    return "live" if on_live_list else "dry_run"


def health(row: Mapping[str, Any], L: Optional[LaneLedger], eff: str, now: datetime) -> tuple[str, Optional[str]]:
    if eff == "off":
        return OFF, f"registry state {row.get('state')}" if row.get("state") not in (
            None,
            "ACTIVE",
        ) else "dispatch mode off"
    if L is None or L.last is None:
        return NEVER_RAN, "no run of this lane in the n8n coordination ledger"
    last = L.last
    if last["outcome"] in FAIL:
        return FAILING, f"last run {last['outcome']}" + (f": {last['reason']}" if last.get("reason") else "")
    succ_at = _ts((L.last_success or {}).get("at"))
    if (
        L.dead_letters_open
        and L.dead_letter_last
        and (succ_at is None or (_ts(L.dead_letter_last["at"]) or now) > succ_at)
    ):
        return (
            FAILING,
            f"dead-lettered slot not released ({L.dead_letter_last.get('reason') or L.dead_letter_last.get('state')})",
        )
    if L.breaker_open:
        return FAILING, "circuit breaker open (3 consecutive failures) and not released"
    last_at = _ts(last["at"])
    exprs, tz = cron_exprs(row)
    if exprs and last_at:
        due = last_due(exprs, tz, now - STALE_GRACE)
        if due and last_at < due - timedelta(minutes=1):
            return STALE, f"no run since {_iso(last_at)}; the slot due {_iso(due)} has no run"
    elif last_at:
        cad = row.get("expected_cadence_hours")
        if (
            isinstance(cad, (int, float))
            and cad > 0
            and now - last_at > max(timedelta(hours=2 * cad), timedelta(hours=1))
        ):
            return STALE, f"no run since {_iso(last_at)} (expected every {cad} h)"
    return OK, None


def contract_problem(contract: Optional[Mapping[str, Any]]) -> Optional[str]:
    if contract is None:
        return "no health contract (config/n8n_health_contracts.json; onboarding step 3)"
    if contract.get("status") != "REVIEWED":
        return (
            f"health contract {contract.get('status') or 'unset'}: the owner's REVIEW is owed — a workflow without a "
            "REVIEWED contract does not leave shadow (onboarding rule 5)"
        )
    if "UNKNOWN" in json.dumps(contract):
        return "health contract has UNKNOWN fields (DRAFT_AT_LIVE_STAGE)"
    return None


def cron_facts(row: Mapping[str, Any], crontab: Optional[str], entry: Optional[Mapping[str, Any]]) -> dict:
    """The lane's active cron line(s) read exactly the way the cutover factory reads them
    (cutover_lane_facts.live_lines, n8n_cutover_wave.command_of / parse_lane_argv, lane_dispatch.cron_flock_locks):
    {lines, lock, problems, argv_problems, line_text}. Read-only."""
    from scripts.lib import cutover_lane_facts as F  # noqa: PLC0415

    out: dict[str, Any] = {"lines": 0, "lock": None, "problems": [], "argv_problems": [], "line_text": ""}
    if crontab is None:
        out["problems"].append("crontab unreadable here, so the cron line and its lock are not measured")
        return out
    lines, probs = F.live_lines(crontab, row.get("scheduler") or {})
    out["lines"] = len(lines)
    out["problems"].extend(probs)
    if not lines:
        return out
    from scripts.n8n_cutover_wave import command_of, parse_lane_argv  # noqa: PLC0415

    cmds = [command_of(ln) for _, ln in lines]
    out["line_text"] = " ".join(ln for _, ln in lines)
    locks = sorted({lk for c in cmds for lk in LD.cron_flock_locks(c)})
    if not locks:
        out["problems"].append(
            "the cron line has no `flock -n <lock>` (safe_flock.sh is not enough): a crontab edit "
            "must add one before canary (§23.12)"
        )
    elif len(locks) > 1:
        out["problems"].append(f"several cron locks {locks}")
    else:
        out["lock"] = locks[0]
    if entry is not None:
        for c in cmds:
            out["argv_problems"].extend(parse_lane_argv(c, list(entry.get("command") or [])).get("problems") or [])
    return out


def risk_tier(
    row: Mapping[str, Any],
    entry: Optional[Mapping[str, Any]],
    disp: Mapping[str, str],
    effect_keys: Mapping[str, Any],
    line_text: str,
) -> tuple[int, str, bool]:
    """(tier, name, sender) from the cutover factory's own classifier (cutover_lane_facts.tier_of / is_sender_lane):
    1 read/overwrite < 2 append < 3 send < 4 llm < 5 watchdog < 6 broker."""
    from scripts.lib import cutover_lane_facts as F  # noqa: PLC0415

    t = F.tier_of(disp, row, entry, effect_keys, line_text)
    return t, F.TIER_NAMES[t], F.is_sender_lane(disp, row, effect_keys, line_text)


def readiness(
    row: Mapping[str, Any],
    *,
    entry: Optional[Mapping[str, Any]],
    contract: Optional[Mapping[str, Any]],
    on_live_list: Optional[bool],
    L: Optional[LaneLedger],
    crontab: Optional[str],
    policy: Mapping[str, Any],
    blocked_reasons: Mapping[str, Any],
    disp: Optional[Mapping[str, str]] = None,
    effect_keys: Optional[Mapping[str, Any]] = None,
) -> dict:
    from scripts.lib import cutover_lane_facts as F  # noqa: PLC0415

    lane = str(row.get("lane_id") or "")
    s = row.get("scheduler") or {}
    stage, kind = s.get("stage"), s.get("kind")
    res: dict[str, Any] = {
        "verdict": N_A,
        "target": None,
        "missing": [],
        "blocked_by": [],
        "evidence": [],
        "owed": [],
        "p1_last": lane in (policy.get("p1_last") or ()),
    }
    cf = cron_facts(row, crontab, entry) if kind == "cron" and stage in ("shadow", "canary") else None
    line_text = (cf or {}).get("line_text") or str(s.get("command_text") or "")
    try:
        tier, tier_name, sender = risk_tier(row, entry, disp or {}, effect_keys or {}, line_text)
    except Exception:  # noqa: BLE001 — a classifier failure never reads as low risk
        tier, tier_name, sender = 0, "unknown", False
    res["risk_tier"], res["risk_tier_name"], res["sender"] = tier, tier_name, sender
    if stage == "cutover":
        res["verdict"] = CUT_OVER
        res["owed"].append("natural-schedule evidence after cutover is monitored, not awaited (§23.12)")
        return res
    if stage not in ("shadow", "canary"):
        return res
    res["target"] = "canary" if stage == "shadow" else "cutover"
    blk = res["blocked_by"]
    if row.get("state") not in (None, "ACTIVE"):
        blk.append(f"registry state {row.get('state')}")
    hold = (policy.get("holds") or {}).get(lane)
    if hold:
        blk.append(f"operator hold: {hold[:160]}")
    if lane in F.HELD:
        blk.append(F.HELD[lane][:200])
    if (disp or {}).get("family_id") in F.DEFERRED_FAMILIES or (disp or {}).get("source") in F.DEFERRED_SOURCES:
        blk.append("deferred by directive (F07 / registry_systemd stays on the host)")
    if lane in (blocked_reasons or {}):
        blk.append(f"allowlist blocked_reasons: {str(blocked_reasons[lane])[:160]}")
    argv = {}
    if entry:
        argv = {
            lane: " ".join(
                str(t)
                for t in [*(entry.get("command") or []), *(entry.get("live_arg") or entry.get("dry_run_arg") or [])]
            )
        }
    try:
        ok, why = LD.dispatch_eligible(row, allowlist_argv=argv, cutover_policy=policy)
    except Exception as exc:  # noqa: BLE001 — an unreadable row is never "eligible"
        ok, why = False, f"eligibility check failed: {type(exc).__name__}"
    if not ok and not hold:
        blk.append(f"never-list / dispatch gate: {why}")
    if entry is None:
        blk.append("no run-allowlist entry (config/n8n_run_allowlist.json; onboarding step 5)")
    cp = contract_problem(contract)
    if cp:
        blk.append(cp)
    if res["p1_last"]:
        res["evidence"].append(
            "P1 lane: moves after every non-P1 lane and keeps its cron line one trading day after "
            "the first live RUN_DONE (config/lane_cutover_policy.json p1_last)"
        )
    miss, ev = res["missing"], res["evidence"]
    dry = L.last_dry if L else None
    if dry is None:
        miss.append("no n8n dry_run fire in the ledger (onboarding step 8 / §23.21 (2))")
    elif dry["outcome"] != "SUCCESS":
        miss.append(
            f"latest dry_run fire is {dry['outcome']}"
            + (f" ({dry['reason']})" if dry.get("reason") else "")
            + " — fix it, then one clean dry_run fire"
        )
    else:
        ev.append(f"latest dry_run fire RUN_DONE {dry['at']} ({dry['run_id']})")
    if stage == "shadow":
        if cf is not None:
            miss.extend(cf["problems"])
            if cf["lock"] and entry is not None and entry.get("lock") != cf["lock"]:
                miss.append(f"allowlist lock {entry.get('lock')!r} is not the cron line's lock {cf['lock']!r} (§23.12)")
            elif cf["lock"]:
                ev.append(f"cron line flock lock {cf['lock']} == allowlist lock")
            if cf["argv_problems"]:
                miss.append(
                    "the cutover factory cannot derive live_arg from the cron line (n8n_cutover_wave "
                    "parse_lane_argv): " + "; ".join(sorted(set(cf["argv_problems"])))[:300]
                )
            if sender and "effect_claim_cron.sh" not in cf["line_text"]:
                miss.append(
                    "sender lane: wrap the cron line with scripts/effect_claim_cron.sh (TRADEAI_EFFECT_CLAIM=<lane>) "
                    "before canary so the cron twin refuses once n8n owns the effect (§23.25)"
                )
        verdict = READY_CANARY
    else:
        if on_live_list is False:
            miss.append(
                "not on the relay live list, so its canary slots are posted as dry_run: no live proof yet (§23.21 (4))"
            )
        elif on_live_list is None:
            miss.append("relay live list unreadable here")
        live, ls = (L.last_live if L else None), (L.last_live_success if L else None)
        if ls is None:
            miss.append("no successful live n8n run yet — RUN_SKIPPED_LOCK does not count (§23.21 (4), §23.12)")
        else:
            ev.append(f"live RUN_DONE {ls['at']} ({ls['run_id']})")
            if L and L.live_output_advanced is False:
                miss.append("the last live RUN_DONE did not advance its output_signal (§0 rule 8)")
            elif L and L.live_output_advanced is None:
                miss.append("output_signal advance of the last live RUN_DONE not recorded in its RunReceipt")
            else:
                ev.append("output_signal advanced on that run")
        if live and live["outcome"] in FAIL:
            miss.append(
                f"latest live run {live['outcome']}"
                + (f" ({live['reason']})" if live.get("reason") else "")
                + " — defect fixed + a clean live run first (§23.21 (1))"
            )
        if cf is not None:
            if entry is not None:
                ok2, why2 = LD.r1_canary_lock_matches(row, entry)
                (ev if ok2 else miss).append(("shared lock: " if ok2 else "") + why2)
            if cf["lines"] == 0 and crontab is not None:
                miss.extend(p + " — §23.21 (4) needs the live run with the cron line present" for p in cf["problems"])
        res["owed"].append("lane regression tests under TRADE_AI_CI=1, quoted in the cutover PR (§23.21 (3))")
        res["owed"].append(
            "one `cron` grant per wave naming the lane; effect key armed for append/send/llm lanes "
            "(n8n_cutover_wave.py; §23.23 (4))"
        )
        verdict = READY_CUTOVER
    res["verdict"] = BLOCKED if blk else NOT_READY if miss else verdict
    return res


def _pub(r: Optional[dict]) -> Optional[dict]:
    return {k: r.get(k) for k in ("run_id", "mode", "outcome", "exit_code", "reason", "at")} if r else None


def lane_outcome(row: Mapping[str, Any], L: Optional[LaneLedger], eff: str, now: datetime) -> dict:
    exprs, tz = cron_exprs(row)
    nf = next_fire(exprs, tz, now) if exprs and eff != "off" else None
    h, why = health(row, L, eff, now)
    return {
        "effective_mode": eff,
        "health": h,
        "health_reason": why,
        "last_run": _pub(L.last) if L else None,
        "last_run_at": (L.last or {}).get("at") if L else None,
        "last_outcome": (L.last or {}).get("outcome") if L else None,
        "last_success_at": (L.last_success or {}).get("at") if L else None,
        "last_live_success_at": (L.last_live_success or {}).get("at") if L else None,
        "failures_24h": L.failures_24h if L else 0,
        "failures_7d": L.failures_7d if L else 0,
        "runs_7d": dict(L.runs_7d) if L else {"dry_run": 0, "live": 0},
        "outcomes_7d": dict(L.outcomes_7d) if L else {},
        "dead_letters_open": L.dead_letters_open if L else 0,
        "breaker_open": bool(L and L.breaker_open),
        "next_run_at": _iso(nf),
        "schedule": exprs,
        "tz": tz,
    }


SUMMARY_KEYS = ("live_healthy", "live_failing", "rehearsing", "ready_to_promote", "never_ran", "off", "cut_over")


def summarize(rows: list[dict]) -> dict:
    out = {k: 0 for k in SUMMARY_KEYS}
    for r in rows:
        o, rd = r.get("outcome") or {}, r.get("readiness") or {}
        eff, h = o.get("effective_mode"), o.get("health")
        if eff == "live" and h == OK:
            out["live_healthy"] += 1
        elif eff == "live" and h in (FAILING, STALE):
            out["live_failing"] += 1
        if eff == "dry_run":
            out["rehearsing"] += 1
        if rd.get("verdict") in (READY_CANARY, READY_CUTOVER):
            out["ready_to_promote"] += 1
        if h == NEVER_RAN:
            out["never_ran"] += 1
        if eff == "off":
            out["off"] += 1
        if rd.get("verdict") == CUT_OVER:
            out["cut_over"] += 1
    return out


# ── assembly + 60 s cache ───────────────────────────────────────────────────────────────────────────────────────


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def config_maps(code_root: Path) -> tuple[dict, dict, dict, dict]:
    al = _load(code_root / ALLOWLIST_REL) or {}
    entries = {e.get("lane_id"): e for e in (al.get("lanes") or []) if isinstance(e, dict)}
    hc = _load(code_root / CONTRACTS_REL) or {}
    contracts = {c.get("id"): c for c in (hc.get("contracts") or []) if isinstance(c, dict)}
    policy = LD.load_cutover_policy(code_root / CUTOVER_POLICY_REL)
    return entries, contracts, policy, (al.get("blocked_reasons") or {})


def factory_maps(code_root: Path) -> tuple[dict, dict]:
    """(disposition row by lane, effect keys by lane); empty when the files are absent (tests, older checkouts)."""
    from scripts.lib import cutover_lane_facts as F  # noqa: PLC0415

    try:
        disp = {}
        for r in F.load_disposition(code_root):
            disp.setdefault(r.get("lane_id") or "", r)
    except (OSError, ValueError):
        disp = {}
    ek = (_load(code_root / F.EFFECT_KEYS) or {}).get("lanes") or {}
    return disp, (ek if isinstance(ek, dict) else {})


def enrich(
    rows: list[dict],
    registry_rows: Mapping[str, Mapping[str, Any]],
    *,
    code_root: Path,
    ledger_path: Path,
    crontab: Callable[[], str],
    now: datetime,
) -> dict:
    """Add ``outcome`` and ``readiness`` to each n8n_view row in place; return the section-level extras."""
    entries, contracts, policy, blocked = config_maps(code_root)
    disp, effect_keys = factory_maps(code_root)
    try:
        ledger = read_ledger(ledger_path, [r["lane_id"] for r in rows], now)
        led_state, led_reason = "OK", None
    except Exception as exc:  # noqa: BLE001 — unreadable is UNAVAILABLE, never "never ran"
        ledger, led_state, led_reason = None, "UNAVAILABLE", f"{type(exc).__name__}: {str(exc)[:160]}"
    try:
        tab: Optional[str] = crontab()
    except Exception:  # noqa: BLE001 — lock proof then reads "not measured"
        tab = None
    for r in rows:
        reg = registry_rows.get(r["lane_id"]) or {}
        eff = effective_mode(reg, r.get("on_live_list"))
        L = ledger.get(r["lane_id"]) if ledger is not None else None
        if ledger is None:
            r["outcome"] = {"effective_mode": eff, "health": "UNKNOWN", "health_reason": led_reason}
        else:
            r["outcome"] = lane_outcome(reg, L, eff, now)
        r["readiness"] = readiness(
            reg,
            entry=entries.get(r["lane_id"]),
            contract=contracts.get(r["lane_id"]),
            on_live_list=r.get("on_live_list"),
            L=L if ledger is not None else None,
            crontab=tab,
            policy=policy,
            blocked_reasons=blocked,
            disp=disp.get(r["lane_id"]),
            effect_keys=effect_keys,
        )
        if ledger is None and r["readiness"]["verdict"] in (READY_CANARY, READY_CUTOVER, NOT_READY):
            r["readiness"]["verdict"] = NOT_READY
            r["readiness"]["missing"].insert(0, "coordination ledger unreadable: run evidence not measured")
    return {
        "outcomes_state": led_state,
        "outcomes_reason": led_reason,
        "ledger_path": str(ledger_path),
        "crontab_read": tab is not None,
        "summary": summarize(rows),
        "outcomes_as_of": _iso(now),
        "cache_ttl_s": int(CACHE_TTL_S),
    }


_CACHE: dict[tuple, tuple[float, Any]] = {}
_LOCK = threading.Lock()


def cached(
    key: tuple, fn: Callable[[], Any], *, ttl: float = CACHE_TTL_S, clock: Callable[[], float] = time.monotonic
) -> Any:
    """One computation per key per ``ttl`` seconds (the page polls; the ledger is ~200 MB)."""
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and clock() - hit[0] < ttl:
            return hit[1]
    val = fn()
    with _LOCK:
        _CACHE[key] = (clock(), val)
        if len(_CACHE) > 16:  # bounded: tests and one server use a handful of keys
            for k in sorted(_CACHE, key=lambda k: _CACHE[k][0])[:-16]:
                _CACHE.pop(k, None)
    return val
