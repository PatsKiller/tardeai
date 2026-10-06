#!/usr/bin/env python3
"""Evidence-only options journal repair. Default is a read-only inventory.

--apply replays explicit manual order references through the existing fill writer
and existing projection outbox. It never contacts a broker, sends 2FA, guesses a
strategy from dates/symbols, or modifies ambiguous legacy journal rows.
"""
import argparse
import json


def replay(query, project, *, apply=False):
    rows = query("""SELECT id, symbol, account, broker, options_proposal_id, adjusted_params
        FROM manual_execution_log WHERE execution_type='option' ORDER BY id""", fetch="all") or []
    result = {"dry_run": not apply, "eligible": [], "review_required": [], "projected": []}
    for row in rows:
        params = row.get("adjusted_params") or {}
        if isinstance(params, str):
            params = json.loads(params)
        if not row.get("options_proposal_id") or not params.get("options_evidence_ref") or not params.get("options_fills"):
            result["review_required"].append({"manual_execution_id": row["id"], "reason": "Missing exact strategy/fill evidence; original row retained"})
            continue
        result["eligible"].append(row["id"])
        if apply:
            try:
                receipt = project(row)
            except Exception as exc:
                receipt = {"ok": False, "error": str(exc)[:200]}
            result["projected" if receipt.get("ok") else "review_required"].append({"manual_execution_id": row["id"], **receipt})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    from db_adapter import _execute, _get_conn
    from manual_execution_tracker import project_manual_options_entry
    report = replay(_execute, project_manual_options_entry, apply=args.apply)
    if args.apply:
        from options_fill_evidence import process_projection_outbox
        conn = _get_conn()
        report["journal_projection"] = process_projection_outbox(conn.cursor(), conn)
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
