#!/usr/bin/env python3
"""frozen-output-monitor — the frozen-output contract for every lane that declares one (LQ-20261107-1613).

PROCESS   n8n lane ``frozen-output-monitor``, hourly, LaneRunReceipt@v2 under --apply. Contracts live in
          config/frozen_output_contracts.json (``FrozenOutputContracts@v1``, per-lane ``k``).
CONTRACT  "a lane's output fingerprint does not stay identical across its last k runs while its input fingerprint
          changes". Per lane: OK / STABLE_INPUTS (OK) / FROZEN (DEGRADED) / UNVERIFIABLE; the run verdict is the
          worst lane: DEGRADED if any lane is FROZEN, UNVERIFIABLE if no lane could be read, else OK.
HEAL      bounded and send-free. A FROZEN lane gets ONE ``rerun_with_fresh_inputs`` proposal in the receipt (the lane
          id and its window) for the dispatcher; this script never starts, stops or edits a lane, never rewrites
          the frozen rows and never changes a threshold. Escalation: one ``system_health`` warning in alert_events
          per lane per ESCALATION_COOLDOWN_H, under --apply only. Finding WHY an output froze is the lane owner's.

Dry run is the default: a read-only DB session, nothing written, nothing escalated. ``--apply`` escalates and writes
the receipt. ``--lane ID`` limits the run to one contract. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT / "scripts", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from lib import frozen_output as fo  # noqa: E402

LANE_ID = "frozen-output-monitor"
CONTRACTS = ROOT / "config" / "frozen_output_contracts.json"
ESCALATION_SOURCE = "frozen_output_monitor.py"
ESCALATION_COOLDOWN_H = 6


def load_contracts(path: Path = CONTRACTS) -> list[dict[str, Any]]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    errs = fo.validate_document(doc)
    if errs:
        raise ValueError("; ".join(errs))
    return list(doc["contracts"])


def _sql_mod():
    from psycopg2 import sql  # noqa: PLC0415

    return sql


def load_history(conn, contract: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The newest k rows of the lane's output table, oldest first, as ``{"at", "output_fp", "input_fp"}``.

    Identifiers come from the reviewed contract, are validated against a lower-case identifier pattern by
    :func:`lib.frozen_output.validate_contract`, and are quoted with psycopg2.sql.Identifier.
    """
    sql = _sql_mod()
    src = contract["source"]
    k = int(contract["k"])
    q = sql.SQL(
        "SELECT row_to_json(t)::text FROM (SELECT * FROM {tbl} WHERE {tc} > now() - make_interval(days => %s) "
        "ORDER BY {tc} DESC LIMIT %s) t"
    ).format(tbl=sql.Identifier(src["table"]), tc=sql.Identifier(src["time_column"]))
    join = src.get("input_join")
    jq = None
    if join:
        jq = sql.SQL("SELECT {kc}::text, {vc}::text FROM {tbl} WHERE {mc}::text = %s").format(
            kc=sql.Identifier(join["key_column"]), vc=sql.Identifier(join["value_column"]),
            tbl=sql.Identifier(join["table"]), mc=sql.Identifier(join["match_column"]))
    out: list[dict[str, Any]] = []
    with conn.cursor() as cur:
        cur.execute(q, (int(src.get("window_days", 14)), k))
        rows = [json.loads(r[0]) for r in cur.fetchall()]
        for row in reversed(rows):
            input_fields = list(contract["input_fields"])
            if jq is not None:
                match = fo.dig(row, join["match_from"])
                joined: Optional[dict[str, str]] = None
                if match is not None:
                    cur.execute(jq, (str(match),))
                    joined = {str(a): b for a, b in cur.fetchall()} or None
                row = {**row, "input_join": joined}
                input_fields.append("input_join")
            out.append({
                "at": row.get(src["time_column"]),
                "output_fp": fo.fingerprint(row, contract["output_fields"]),
                "input_fp": fo.fingerprint(row, input_fields, contract.get("input_exclude", ())),
            })
    return out


def _connect(read_only: bool):
    import psycopg2  # noqa: PLC0415

    kwargs: dict[str, Any] = {"dbname": os.getenv("DB_NAME", "trade_ai"), "user": os.getenv("DB_USER", "johnclaw"),
                              "host": os.getenv("DB_HOST", "/var/run/postgresql"), "connect_timeout": 10}
    if os.getenv("DB_PORT"):
        kwargs["port"] = os.getenv("DB_PORT")
    if os.getenv("DB_PASSWORD"):
        kwargs["password"] = os.getenv("DB_PASSWORD")
    if read_only:
        kwargs["options"] = "-c default_transaction_read_only=on"
    return psycopg2.connect(**kwargs)


def _recently_escalated(conn, lane_id: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM alert_events WHERE source_script = %s AND alert_type = 'system_health' "
            "AND parsed_payload->>'lane_id' = %s AND created_at > now() - make_interval(hours => %s) LIMIT 1",
            (ESCALATION_SOURCE, lane_id, ESCALATION_COOLDOWN_H))
        return cur.fetchone() is not None


def _escalate_default(lane: Mapping[str, Any]) -> bool:
    from alert_event_writer import save_alert_event  # noqa: PLC0415

    return save_alert_event(
        alert_type="system_health",
        raw_text=(f"[{LANE_ID}] {lane['lane_id']} output FROZEN: identical across its last {lane['k']} runs "
                  f"({lane['window_from']} .. {lane['window_to']}) while its inputs took {lane['distinct_inputs']} "
                  f"values. The lane still succeeds; its output no longer follows its inputs."),
        severity="warning",
        source_script=ESCALATION_SOURCE,
        parsed_payload={"kind": "frozen_output", "lane_id": lane["lane_id"], "k": lane["k"],
                        "distinct_inputs": lane["distinct_inputs"], "window_from": lane["window_from"],
                        "window_to": lane["window_to"]},
    ) is not None


def run(*, apply: bool, contracts: list[dict[str, Any]], conn=None,
        escalate: Callable[[Mapping[str, Any]], bool] = _escalate_default) -> dict[str, Any]:
    started = datetime.now(timezone.utc).isoformat()
    own = conn is None
    lanes: list[dict[str, Any]] = []
    try:
        if own:
            conn = _connect(read_only=not apply)
    except Exception as exc:  # noqa: BLE001 -- no DB is a verdict, not a crash
        return {"lane_id": LANE_ID, "mode": "apply" if apply else "dry_run", "started_at": started,
                "verdict": "UNVERIFIABLE", "error": type(exc).__name__, "lanes": [], "frozen": 0,
                "escalated": [], "proposals": []}
    try:
        for c in contracts:
            try:
                ev = fo.evaluate(load_history(conn, c), int(c["k"]))
            except Exception as exc:  # noqa: BLE001 -- one unreadable contract is that lane's verdict
                conn.rollback()
                ev = {"k": c["k"], "runs": 0, "verdict": "UNVERIFIABLE", "reason": f"read_error:{type(exc).__name__}"}
            lanes.append({"lane_id": c["lane_id"], "health": fo.HEALTH[ev["verdict"]], **ev})
        frozen = [ln for ln in lanes if ln["verdict"] == "FROZEN"]
        proposals = [{"action": "rerun_with_fresh_inputs", "lane_id": ln["lane_id"], "window_to": ln["window_to"]}
                     for ln in frozen]
        escalated: list[str] = []
        suppressed: list[str] = []
        if apply:
            for ln in frozen:
                if _recently_escalated(conn, ln["lane_id"]):
                    suppressed.append(ln["lane_id"])
                elif escalate(ln):
                    escalated.append(ln["lane_id"])
            conn.commit()
    finally:
        if own:
            conn.close()
    if frozen:
        verdict = "DEGRADED"
    elif lanes and all(ln["verdict"] == "UNVERIFIABLE" for ln in lanes):
        verdict = "UNVERIFIABLE"
    else:
        verdict = "OK"
    return {"lane_id": LANE_ID, "mode": "apply" if apply else "dry_run", "started_at": started,
            "contract": "output fingerprint moves within k runs whenever the input fingerprint does",
            "verdict": verdict, "lanes": lanes, "frozen": len(frozen), "proposals": proposals,
            "escalated": escalated, "escalation_suppressed_cooldown": suppressed, "sends": 0}


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--apply", action="store_true", help="escalate and write the receipt (default: read-only dry run)")
    ap.add_argument("--lane", help="judge only this lane's contract")
    args = ap.parse_args(argv)
    contracts = load_contracts()
    if args.lane:
        contracts = [c for c in contracts if c["lane_id"] == args.lane]
    summary = run(apply=args.apply, contracts=contracts)
    print(json.dumps(summary, indent=1, sort_keys=True, default=str))
    if args.apply:
        try:
            from scripts.lib.lane_last_receipt import write_lane_receipt  # noqa: PLC0415
        except ImportError:
            from lib.lane_last_receipt import write_lane_receipt  # type: ignore[no-redef]  # noqa: PLC0415
        ok = summary["verdict"] in ("OK", "DEGRADED")
        write_lane_receipt(
            LANE_ID, ok=ok, exit_code=0 if ok else 1, started_at=summary["started_at"], script=__file__,
            summary={k: summary.get(k) for k in ("verdict", "frozen", "escalated", "proposals")}
            | {"lanes": [{k: ln.get(k) for k in ("lane_id", "verdict", "runs", "distinct_inputs")}
                         for ln in summary["lanes"]]},
            error=None if ok else summary.get("error") or "no_lane_readable",
            produced_count=len(summary["lanes"]), attempted_count=len(contracts),
            empty_reason=None if summary["lanes"] else "nothing_due",
        )
    return 0 if summary["verdict"] in ("OK", "DEGRADED") else 1


if __name__ == "__main__":
    sys.exit(main())
