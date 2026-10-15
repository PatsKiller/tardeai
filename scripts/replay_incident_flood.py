#!/usr/bin/env python3
"""replay_incident_flood.py — replay the last N hours of incidents with and without the flood policy (2026-10-15).

Rebuilds, every 5 minutes over the window, the incident list the fan-in would have published, from the durable
time-stamped sources (read-only):

  * breach detector rows   data/runtime/supervisor_breaches.jsonl (append-only; the fan-in's own 48 h rule)
  * diagnoser escalations  data/runtime/n8n_failure_diagnosis_last.json (``at`` per escalation; escalations the
                           diagnoser already dropped are gone, so the diagnoser count is a LOWER bound)
  * dead letters, breakers data/governance/n8n_coordination_ledger.sqlite (dead_at / released_at; mode=ro)
  * run outcomes           the same ledger's ``runs`` (auto-resolve evidence, finished_at <= tick)
  * every other source     the current fan-in receipt (constant over the window; about 25 rows)

Then it runs the notifier's own planner (scripts/incident_notifier.plan_messages) on both lists with the live
config (daily cap, 30-minute P2 batch, quiet hours, 24 h dedupe), simulating every planned message as delivered,
and prints, per operator day, the P1 messages, the P2 batches sent and capped, and the cap usage; plus the open
incident counts before and after. The actual notifier history for the same window is printed beside it.

    python3 scripts/replay_incident_flood.py                 # last 72 h, prints a table
    python3 scripts/replay_incident_flood.py --hours 72 --json-out /tmp/x.json

Sends nothing, writes nothing under the state root (``--json-out`` is the only write). AUTHORITY: READ_ONLY_ADVISORY.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts import incident_notifier as N  # noqa: E402
from scripts import n8n_incident_fanin as F  # noqa: E402
from scripts.lib import incident_flood_policy as FP  # noqa: E402
from scripts.lib.n8n_pilot_observations import state_root  # noqa: E402

TICK_MIN = 5
REPLAYED = {"breach_detector", F.DIAGNOSIS_SOURCE, "dlq"}


def _ts(v: Any) -> Optional[datetime]:
    return FP._ts(v)


def load_sources(root: Path) -> dict[str, Any]:
    rt = root / "data" / "runtime"
    breaches = []
    for r in F._tail_jsonl(rt / "supervisor_breaches.jsonl", max_bytes=50_000_000):
        t = _ts(r.get("detected_at"))
        if t is not None:
            breaches.append((t, r))
    breaches.sort(key=lambda x: x[0])
    diag = F._load(root / F.DIAGNOSIS_RECEIPT_REL) or {}
    fanin = F._load(root / F.RECEIPT_REL) or {}
    ledger = root / F.LEDGER_REL
    dead, brk, runs = [], [], []
    if ledger.exists():
        conn = sqlite3.connect(f"{ledger.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            dead = [dict(r) for r in conn.execute("SELECT * FROM dead_letters")]
            brk = [dict(r) for r in conn.execute("SELECT * FROM breakers")]
            runs = [
                dict(r)
                for r in conn.execute(
                    "SELECT lane_id, mode, state, exit_code, finished_at FROM runs WHERE finished_at IS NOT NULL"
                )
            ]
        finally:
            conn.close()
    return {
        "breaches": breaches,
        "escalations": [e for e in diag.get("escalations") or [] if _ts(e.get("at"))],
        "static": [r for r in fanin.get("incidents") or [] if r.get("source") not in REPLAYED],
        "dead": dead,
        "breakers": brk,
        "runs": sorted(runs, key=lambda r: str(r["finished_at"])),
        "fanin_as_of": fanin.get("as_of"),
        "diag_as_of": diag.get("as_of"),
    }


def findings_at(src: dict[str, Any], t: datetime) -> list[dict[str, Any]]:
    """The fan-in's findings as of tick ``t`` (replayed sources) plus the constant ones."""
    rows = [r for (ts, r) in src["breaches"] if ts <= t]
    orig = F._tail_jsonl
    F._tail_jsonl = lambda *_a, **_k: rows  # the fan-in's breach rule, on the rows that existed at t
    try:
        out = F._breach_findings(Path("/nonexistent"), t)
    finally:
        F._tail_jsonl = orig
    for e in src["escalations"]:
        if _ts(e["at"]) <= t and str(e.get("priority")) in ("P1", "P2"):
            out.append(
                {
                    "source": F.DIAGNOSIS_SOURCE,
                    "item": f"escalate:{e.get('lane')}/{e.get('key')}",
                    "severity": str(e.get("priority")),
                    "detail": str(e.get("detail") or e.get("reason") or "")[:160],
                    "detected_at": e.get("at"),
                    "lane": e.get("lane"),
                    "event_type": e.get("event_type"),
                    "reason": e.get("reason"),
                }
            )
    for d in src["dead"]:
        da, ra = _ts(d.get("dead_at")), _ts(d.get("released_at"))
        if da and da <= t and (ra is None or ra > t):
            out.append(
                {
                    "source": "dlq",
                    "item": f"dlq:{d.get('slot_key')}",
                    "severity": "P2",
                    "detail": f"{d.get('lane_id')} {d.get('mode')} {d.get('last_state')} {d.get('last_reason')}",
                    "detected_at": d.get("dead_at"),
                    "lane": d.get("lane_id"),
                    "mode": d.get("mode"),
                }
            )
    for b in src["breakers"]:
        oa, ra = _ts(b.get("opened_at")), _ts(b.get("released_at"))
        if oa and oa <= t and (ra is None or ra > t):
            out.append(
                {
                    "source": "dlq",
                    "item": f"breaker:{b.get('lane_id')}",
                    "severity": "P2",
                    "detail": "breaker open",
                    "detected_at": b.get("opened_at"),
                }
            )
    for r in src["static"]:
        d = _ts(r.get("detected_at"))
        if d is None or d <= t:
            out.append(dict(r))
    return out


class Sim:
    """One notifier, simulated: every planned message is delivered unless the cap holds it."""

    def __init__(self, cfg: dict[str, Any], policy: Optional[dict[str, Any]]):
        self.cfg, self.policy = cfg, policy
        self.state = {
            "schema": N.STATE_SCHEMA,
            "notified": {},
            "last_p2_batch_at": None,
            "last_recovery_at": None,
            "sends_by_day": {},
            "p1_sends_by_day": {},
            "source_triggers_by_day": {},
        }
        self.days: dict[str, Counter] = defaultdict(Counter)
        self.p2_lines_by_source: Counter = Counter()

    def tick(self, t: datetime, findings: list[dict[str, Any]], count: bool) -> None:
        cfg, st = self.cfg, self.state
        view = {
            "as_of": t.isoformat(),
            "by_severity": dict(Counter(f["severity"] for f in findings)),
            "incidents": [
                {**f, "event_id": f"evt-{f['source']}-{f['item']}", "state": "ARTIFACT_WRITTEN"} for f in findings
            ],
        }
        open_now, acked = N.open_incidents(view, set())
        N.reconcile(open_now, set(acked), st, t, cfg)
        msgs, _batch = N.plan_messages(open_now, st, t, cfg, view, set(acked), policy=self.policy)
        day = N.local_day(t, cfg)
        p1_in_cap = True if self.policy is None else FP.p1_counts_toward_cap(self.policy)
        rec_in_cap = True if self.policy is None else FP.recoveries_count_toward_cap(self.policy)
        used = int(st["sends_by_day"].get(day, 0))
        c = self.days[day]
        for m in msgs:  # the same cap rule as incident_notifier.run()
            p1_bearing = m["kind"] == "p1" or any(i.get("severity") == "P1" for i in m["incidents"])
            off_cap = (p1_bearing and not p1_in_cap) or (m["kind"] == "recovery" and not rec_in_cap)
            if used >= cfg["daily_cap"] and not p1_bearing and not off_cap:
                if count:
                    c[f"{m['kind']}_capped"] += 1
                continue
            if not off_cap:
                used += 1
            for src, n in (m.get("budget_charge") or {}).items():
                tday = st["source_triggers_by_day"].setdefault(day, {})
                tday[src] = int(tday.get(src, 0)) + n
            if count:
                c[f"{m['kind']}_sent"] += 1
                if m["kind"] == "p2_batch":
                    p2 = [i for i in m["incidents"] if i["severity"] == "P2"]
                    c["p2_lines_delivered"] += len(p2)
                    for i in p2:
                        self.p2_lines_by_source[i["source"]] += 1
            N.apply_result(st, m, t)
        st["sends_by_day"][day] = used
        if count:
            c["cap_used"] = used
            c["cap_limit"] = cfg["daily_cap"]


def actual_history(root: Path, start: datetime, end: datetime, cfg: dict[str, Any]) -> dict[str, Counter]:
    out: dict[str, Counter] = defaultdict(Counter)
    for r in F._tail_jsonl(root / N.HISTORY_REL, max_bytes=50_000_000):
        t = _ts(r.get("as_of"))
        if t is None or not (start <= t <= end) or r.get("mode") != "live":
            continue
        day = N.local_day(t, cfg)
        for m in r.get("messages") or []:
            out[day][f"{m.get('kind')}_{str(m.get('status')).lower()}"] += 1
        cap = r.get("cap") or {}
        out[day]["cap_used"] = max(out[day]["cap_used"], int(cap.get("used") or 0))
    return out


def replay(root: Path, *, hours: float, warmup_hours: float, end: Optional[datetime] = None) -> dict[str, Any]:
    src = load_sources(root)
    end = end or _ts(src["fanin_as_of"]) or datetime.now(timezone.utc)
    start = end - timedelta(hours=hours)
    t = start - timedelta(hours=warmup_hours)
    cfg = N.config_from_env({})
    policy = {**FP.load_policy({}), "mode": "enforce"}
    before, after = Sim(cfg, None), Sim(cfg, policy)
    run_rows = src["runs"]
    succ_rows: list[dict[str, Any]] = []
    ri = 0
    distinct_b: set[str] = set()
    distinct_a: set[str] = set()
    distinct_src_b: Counter = Counter()
    distinct_src_a: Counter = Counter()
    peak_b = peak_a = 0
    last_b: list[dict[str, Any]] = []
    last_a: dict[str, Any] = {}
    rules: Counter = Counter()
    while t <= end:
        while ri < len(run_rows) and str(run_rows[ri]["finished_at"]) <= t.isoformat():
            r = run_rows[ri]
            if r["state"] == "RUN_DONE" and int(r.get("exit_code") or 0) == 0:
                succ_rows.append(r)
            ri += 1
        fb = findings_at(src, t)
        res = FP.apply_fanin_policy(fb, policy, successes=FP.successes_from_rows(succ_rows))
        fa = res["findings"]
        count = t >= start
        before.tick(t, fb, count)
        after.tick(t, fa, count)
        if count:
            for f in fb:
                k = f"{f['source']}|{f['item']}"
                if k not in distinct_b:
                    distinct_b.add(k)
                    distinct_src_b[f["source"]] += 1
            for f in fa:
                k = f"{f['source']}|{f['item']}"
                if k not in distinct_a:
                    distinct_a.add(k)
                    distinct_src_a[f["source"]] += 1
            peak_b, peak_a = max(peak_b, len(fb)), max(peak_a, len(fa))
        last_b, last_a = fb, res
        t += timedelta(minutes=TICK_MIN)
    rules.update({k: len(last_a[k]) for k in ("dropped", "auto_resolved", "collapsed", "demoted", "protected")})
    p1_protected_b = sorted(
        f"{f['source']}|{f['item']}" for f in last_b if f["severity"] in ("P0", "P1") and FP.is_protected(f, policy)
    )
    p1_protected_a = {f"{f['source']}|{f['item']}" for f in last_a["findings"] if f["severity"] in ("P0", "P1")}
    return {
        "window": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "hours": hours,
            "warmup_hours": warmup_hours,
            "tick_min": TICK_MIN,
        },
        "policy": {"config": policy.get("config_path"), "note": policy.get("config_note")},
        "notifier_config": cfg,
        "open_at_end": {"before": FP._counts(last_b), "after": last_a["after"]},
        "peak_open": {"before": peak_b, "after": peak_a},
        "distinct_incidents": {
            "before": len(distinct_b),
            "after": len(distinct_a),
            "before_by_source": dict(distinct_src_b.most_common()),
            "after_by_source": dict(distinct_src_a.most_common()),
        },
        "rules_at_end": dict(rules),
        "protected_p1_at_end": {"n": len(p1_protected_b), "all_kept": all(k in p1_protected_a for k in p1_protected_b)},
        "notifier_by_day": {
            "before": {d: dict(c) for d, c in sorted(before.days.items())},
            "after": {d: dict(c) for d, c in sorted(after.days.items())},
        },
        "p2_lines_by_source": {
            "before": dict(before.p2_lines_by_source.most_common()),
            "after": dict(after.p2_lines_by_source.most_common()),
        },
        "actual_history": {d: dict(c) for d, c in sorted(actual_history(root, start, end, cfg).items())},
        "caveats": [
            "diagnoser escalations already dropped by the diagnoser are absent: the diagnoser 'before' is a lower bound",
            "sources other than breach_detector, n8n_failure_diagnosis and dlq are held at the current fan-in receipt",
            "every planned message is simulated as delivered (no editor holds, no FAILED sends)",
            "the simulation starts with an empty notifier state warmup_hours before the window",
        ],
    }


def _print(r: dict[str, Any]) -> None:
    w = r["window"]
    print(f"Incident-flood replay {w['start'][:16]}Z -> {w['end'][:16]}Z ({w['hours']} h, {w['tick_min']}-min ticks)")
    ob, oa = r["open_at_end"]["before"], r["open_at_end"]["after"]
    print(f"open at end      before {ob['open']:5d} {ob['by_severity']}")
    print(f"                 after  {oa['open']:5d} {oa['by_severity']}")
    print(f"peak open        before {r['peak_open']['before']:5d}   after {r['peak_open']['after']:5d}")
    d = r["distinct_incidents"]
    print(f"distinct (72 h)  before {d['before']:5d}   after {d['after']:5d}")
    print(f"  before by source {d['before_by_source']}")
    print(f"  after  by source {d['after_by_source']}")
    print(f"rules at end     {r['rules_at_end']}")
    print(f"protected P0/P1 at end: {r['protected_p1_at_end']}")
    cap = r["notifier_config"]["daily_cap"]
    print(f"\nnotifier per operator day (cap {cap}/day)        p1  p2sent p2capped recov  cap_used  p2_lines")
    for label in ("before", "after"):
        for day, c in r["notifier_by_day"][label].items():
            print(
                f"  {label:6s} {day}                       {c.get('p1_sent', 0):4d} {c.get('p2_batch_sent', 0):6d}"
                f" {c.get('p2_batch_capped', 0):8d} {c.get('recovery_sent', 0):5d} {c.get('cap_used', 0):6d}/{cap}"
                f" {c.get('p2_lines_delivered', 0):8d}"
            )
    for day, c in r["actual_history"].items():
        print(f"  actual {day}  {c}")
    print(f"\nP2 lines delivered by source  before {r['p2_lines_by_source']['before']}")
    print(f"                              after  {r['p2_lines_by_source']['after']}")
    for c in r["caveats"]:
        print(f"caveat: {c}")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--hours", type=float, default=72)
    ap.add_argument("--warmup-hours", type=float, default=12)
    ap.add_argument("--root", default=None, help="state root (default: TRADEAI_STATE_ROOT or the persistent state)")
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args(argv)
    r = replay(Path(args.root) if args.root else state_root(), hours=args.hours, warmup_hours=args.warmup_hours)
    _print(r)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(r, indent=1, default=str) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
