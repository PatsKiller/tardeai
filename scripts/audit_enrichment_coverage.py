#!/usr/bin/env python3
"""audit_enrichment_coverage.py — the agent that checks the checkers (operator order 2026-06-12:
"fix root cause, have agents check audit on a regular!").

Lane ``audit-enrichment-coverage`` (n8n dispatcher, stage shadow; cron twin weekdays 16:45 ET).

What it audits (rescoped 2026-10-22, operator-approved: "Yes, I agree with your recommendations."):
  SCOPE — the curated Watch membership, never the ``in_directive_watch`` flag (AGENTS.md §26: the CIO prospect
    record / curated Watch membership is the one watch list). Preferred: the ``cio_prospect`` projection, but only
    when it answers from the granted store (``source.kind == "store"``). Interim, until then:
    watchlist_items status='active' + held names (lib.data_broker.watch_domains.membership_held, the one held
    reader) + ACTIVE ticker directives the operator created (created_by operator/operator_audit).
  EXPECTATIONS — matched to the funded policy (config/hermes_research_budget.yaml); see lib/enrichment_coverage.py:
    technicals + analyst for every member; news_7d for held/proposed; llm_curation for held/proposed/high-rank
    (cloud tiers T0/T1); protection_advisory for held names with technicals; a failed latest synthesis.
    A held/proposed name with no articles from any source, ever, is reported and is not a gap.

The alert (``--alert``): P3 notification intent (the digest), counts first, top 10 by priority, one cause line per
surface from the lane receipts and the policy. Sent only when the gap count rises or a new (symbol, surface) gap
appears (dedupe state: data/runtime/audit-enrichment-coverage_state.json). The full gap list is never printed to the
log: a real run writes a capped manifest (data/runtime/audit-enrichment-coverage_manifest.json, ≤ 500 rows).

  python3 scripts/audit_enrichment_coverage.py [--alert] [--json] [--dry-run]

--dry-run: the same read-only audit on a READ ONLY session; prints the summary and the alert it WOULD send; never
sends, never writes the receipt, the state or the manifest. A real run writes the LaneRunReceipt
(data/runtime/audit-enrichment-coverage_last.json, ``produced_count`` = members audited; ok_at only on success).
Gaps are findings, not failure: exit 0 unless the audit itself fails. Reads the DB only; no broker. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib import enrichment_coverage as ec  # noqa: E402

LANE_ID = "audit-enrichment-coverage"
PRODUCER = "audit_enrichment_coverage"
STATE_NAME = f"{LANE_ID}_state.json"
MANIFEST_NAME = f"{LANE_ID}_manifest.json"
TICKER_SHAPE = r"^[A-Z]{1,5}$"
OUTPUT_UNIT = "curated Watch members audited"


def _runtime_dir() -> Path:
    from lib.lane_last_receipt import runtime_dir
    return runtime_dir()


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 -- missing / unreadable is "absent"
        return None


def _db_query(cur):
    """lib.data_broker-style db_query over the audit's own (possibly READ ONLY) cursor."""
    def q(sql, params=None, fetch="all"):
        cur.execute(sql) if params is None else cur.execute(sql, params)
        if fetch == "one":
            return cur.fetchone()
        if fetch == "all":
            return cur.fetchall()
        return None
    return q


def _sym(r):
    return r[0] if not isinstance(r, dict) else (r.get("symbol") or next(iter(r.values()), None))


def _col(cur, q, params=None) -> set:
    # params=None ⇒ no paramstyle processing (a literal % in LIKE would otherwise IndexError)
    cur.execute(q) if params is None else cur.execute(q, params)
    return {str(_sym(r)).upper() for r in cur.fetchall() if _sym(r)}


def _prospect_members(cur) -> tuple[dict | None, str]:
    """Membership from the cio_prospect projection when it answers from the granted store; else (None, why)."""
    try:
        from lib.data_broker import cio_prospect  # type: ignore
    except Exception:  # noqa: BLE001 -- PR #1944 not merged / projection absent
        return None, "cio_prospect projection not present"
    try:
        res = cio_prospect.get_prospects(db_query=_db_query(cur))
    except Exception as exc:  # noqa: BLE001
        return None, f"cio_prospect error {type(exc).__name__}"
    src = (res or {}).get("source") or {}
    if src.get("kind") != "store" or not res.get("ok", True):
        return None, f"cio_prospect answers from {src.get('kind') or 'nothing'}, not the granted store"
    stage_tier = {"held": "held", "proposed": "proposed", "actionable": "high_rank"}
    members: dict[str, set] = {}
    for p in res.get("prospects") or []:
        sym = str(p.get("symbol") or "").upper()
        if not sym or p.get("stage") in ("exit",):
            continue
        members.setdefault(sym, set()).add(stage_tier.get(str(p.get("stage")), "active"))
    return members, "cio_prospect store"


def resolve_members(cur) -> tuple[dict[str, set], dict]:
    """{symbol: {tiers}} for the curated Watch membership, plus how it was resolved."""
    import re

    members, why = _prospect_members(cur)
    info: dict = {"preferred": "cio_prospect", "preferred_status": why}
    if members is None:
        members = {}
        active = _col(cur, "SELECT DISTINCT symbol FROM watchlist_items WHERE status = 'active' AND symbol IS NOT NULL")
        held, held_src = set(), "unavailable"
        try:
            from lib.data_broker.watch_domains import membership_held
            held, held_src = membership_held()
        except Exception as exc:  # noqa: BLE001
            held_src = f"unavailable:{type(exc).__name__}"
        op = None
        try:
            from lib.data_broker.watch_intelligence import active_operator_ticker_symbols
            op = active_operator_ticker_symbols(_db_query(cur))
        except Exception:  # noqa: BLE001
            op = None
        for s in active:
            members.setdefault(s, set()).add("active")
        for s in held:
            members.setdefault(str(s).upper(), set()).add("held")
        for s in op or ():
            members.setdefault(s, set()).add("operator_directive")
        info.update(source="interim", active=len(active), held=len(held), held_source=held_src,
                    operator_directives=None if op is None else len(op))
        label = (f"interim: watchlist active {len(active)} + held {len(held)} ({held_src}) + operator ticker "
                 f"directives {'unreadable' if op is None else len(op)}")
    else:
        info.update(source="cio_prospect")
        label = "cio_prospect store"
    shape = re.compile(TICKER_SHAPE)
    members = {s: t for s, t in members.items() if shape.match(s)}
    if members:
        syms = sorted(members)
        proposed = _col(cur, """SELECT DISTINCT UPPER(symbol) FROM paper_trade_proposals
                                WHERE status IN ('PENDING','APPROVED') AND symbol IS NOT NULL""")
        high = _col(cur, """SELECT DISTINCT UPPER(symbol) FROM watchlist_items
                            WHERE symbol = ANY(%s) AND status <> 'removed'
                              AND ((hermes_rank IS NOT NULL AND hermes_rank <= 20)
                                   OR COALESCE(hermes_composite_score, 0) >= 70)""", (syms,))
        for s in members:
            if s in proposed:
                members[s].add("proposed")
            if s in high:
                members[s].add("high_rank")
    info["label"] = label
    return members, info


def gather_evidence(cur, members) -> tuple[dict, dict]:
    """The evidence sets lib.enrichment_coverage.evaluate reads, plus facts for the cause lines."""
    syms = sorted(members)
    ev: dict = {}
    ev["tech_ok"] = _col(cur, """SELECT DISTINCT symbol FROM ticker_snapshot_daily
                                 WHERE rsi IS NOT NULL AND snapshot_date > CURRENT_DATE - 3 AND symbol = ANY(%s)""",
                         (syms,))
    ev["tech_exempt"] = _col(cur, """SELECT DISTINCT symbol FROM ticker_snapshot_daily
                                     WHERE (data->>'delisted_or_no_data')::bool IS TRUE AND symbol = ANY(%s)""",
                             (syms,))
    facts: dict = {"news_cap": os.environ.get("NEWS_INGEST_MAX", "60"), "pills_as_of": "unknown"}
    pills = _read_json(_runtime_dir() / "pro_analyst_pills_latest.json") \
        or _read_json(PROJECT_ROOT / "data" / "runtime" / "pro_analyst_pills_latest.json") or {}
    ev["analyst_ok"] = {str(p.get("symbol") or "").upper() for p in pills.get("pills", []) if isinstance(p, dict)}
    facts["pills_as_of"] = pills.get("generated_at") or pills.get("as_of") or "unknown"
    if _table_exists(cur, "news_articles"):
        ev["news_7d_ok"] = _col(cur, """SELECT DISTINCT symbol FROM news_articles
                                        WHERE published_at > now() - interval '7 days' AND symbol = ANY(%s)""",
                                (syms,))
        ev["news_ever"] = _col(cur, "SELECT DISTINCT symbol FROM news_articles WHERE symbol = ANY(%s)", (syms,))
        ev["news_measured"] = True
    else:
        ev["news_measured"] = False
    ev["llm_ok"] = _col(cur, """SELECT DISTINCT symbol FROM hermes_external_research
                                WHERE created_at > now() - interval '14 days' AND status='sent' AND symbol = ANY(%s)""",
                        (syms,))
    # latest agent synthesis is a dead-model failure ("LLM error: All providers failed") — never left unretried
    ev["synth_err"] = _col(cur, """SELECT symbol FROM (
                                     SELECT DISTINCT ON (symbol) symbol, synthesis_narrative
                                     FROM watchlist_final_synthesis WHERE symbol = ANY(%s)
                                     ORDER BY symbol, created_at DESC) s
                                   WHERE synthesis_narrative LIKE 'LLM error%%'""", (syms,))
    ev["prot_ok"] = _col(cur, """SELECT DISTINCT symbol FROM hermes_research_intelligence
                                 WHERE research_type='protection_advisory' AND created_at > now() - interval '7 days'
                                   AND symbol = ANY(%s)""", (syms,))
    return ev, facts


def lane_receipts() -> dict:
    rt = _runtime_dir()
    ids = {r for src in ec.CAUSE_SOURCES.values() for r in src.get("receipts", [])}
    return {r: _read_json(rt / f"{r}_last.json") for r in sorted(ids)}


def run(alert=False, as_json=False, dry_run=False):
    from db_adapter import _get_conn
    conn = _get_conn()
    if dry_run:
        from lib.lane_last_receipt import enforce_readonly
        enforce_readonly(conn)
    cur = conn.cursor()
    members, info = resolve_members(cur)
    ev, facts = gather_evidence(cur, members) if members else ({}, {})
    result = ec.evaluate(members, ev)
    causes = ec.cause_lines(result["surface_counts"], lane_receipts(), facts)
    rt = _runtime_dir()
    prev = _read_json(rt / STATE_NAME)
    decision = ec.alert_decision(prev, result["gaps"])
    manifest_rel = f"data/runtime/{MANIFEST_NAME}"
    report = {
        "members": len(members), "membership": info, "symbols_with_gaps": len(result["gaps"]),
        "surface_counts": result["surface_counts"],
        "no_articles_any_source": len(result["no_articles_any_source"]),
        "top": result["gaps"][:ec.TOP_N], "causes": causes,
        "alert_decision": {k: decision[k] for k in ("send", "reason", "count", "previous_count", "new_entries")},
        "manifest": manifest_rel,
    }
    # The summary only — the full list goes to the capped manifest, never to the log (it was 5.1 MB).
    print(json.dumps(report, indent=None if as_json else 1, default=str))
    msg = ec.message(members=members, result=result, decision=decision, causes=causes,
                     membership_source=info.get("label", "?"), manifest_rel=manifest_rel)
    if dry_run:
        # Returns BEFORE any send or write is reachable (AGENTS.md §6). With --json the report stays the only
        # stdout line; the preview goes to stderr.
        out = sys.stderr if as_json else sys.stdout
        if alert and decision["send"]:
            print(f"DRY RUN: would send P3 alert ({len(result['gaps'])} members with gaps; "
                  f"reason {decision['reason']}):", file=out)
            print(msg, file=out)
        else:
            why = decision["reason"] if alert else "--alert not set"
            print(f"DRY RUN: no alert would be sent ({why})", file=out)
        print(f"DRY RUN: nothing sent; no receipt, state or manifest written (would write {manifest_rel})", file=out)
        _emit_output("dry_run", len(members), empty_reason="dry_run")
        report["_dry_run"] = True
        return report
    from lib.atomic_json_store import atomic_write_json
    atomic_write_json(rt / MANIFEST_NAME, ec.manifest(members=members, result=result, decision=decision,
                                                       causes=causes, membership_source=info.get("label", "?")),
                      indent=1)
    sent = False
    if alert and decision["send"]:
        sent = _alert(msg, len(result["gaps"]))
    atomic_write_json(rt / STATE_NAME, ec.new_state(result["gaps"], decision, alerted=sent, prev=prev), indent=1)
    report["alert_sent"] = sent
    return report


def _emit_output(mode, members, empty_reason=None):
    try:
        from lib.lane_output import emit, output_block
        emit(LANE_ID, mode, output_block(produced=0 if mode == "dry_run" else members, attempted=members,
                                         empty_reason=empty_reason, unit=OUTPUT_UNIT))
    except Exception:  # noqa: BLE001 -- evidence printing never fails the run
        pass


def _table_exists(cur, name):
    cur.execute("SELECT 1 FROM information_schema.tables WHERE table_name=%s", (name,))
    return cur.fetchone() is not None


def _alert(msg, n_gaps) -> bool:
    """P3 notification intent through the send_telegram chokepoint (no raw Bot API): the digest, never a page."""
    ok = False
    try:
        from telegram_alert import send_telegram
        ok = bool(send_telegram(msg, priority="P3", producer=PRODUCER))
        try:
            from lib.comms import CommunicationEvent, publish_communication
            publish_communication(CommunicationEvent(
                direction="OUTBOUND", event_type="alert", message_class="ops",
                producer=PRODUCER,
                subject_key="ops:enrichment_coverage",
                retention_class="operational", severity="info",
                sanitized_body=msg[:500], short_summary=msg[:120],
            ))
        except Exception:
            # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
            pass
        if ok:
            print(f"alert accepted (P3 digest; {n_gaps} members with gaps)")
    except Exception:
        # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
        pass
    return ok


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--alert", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--dry-run", action="store_true",
                    help="audit + print the would-be alert; no send, no receipt, no state, no manifest")
    a = ap.parse_args(argv)
    if a.dry_run:
        run(alert=a.alert, as_json=a.json, dry_run=True)
        return 0
    started = datetime.now(timezone.utc)
    from lib.lane_last_receipt import write_lane_receipt
    try:
        report = run(alert=a.alert, as_json=a.json)
    except Exception as exc:
        write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started,
                           summary={"error_type": type(exc).__name__})
        raise
    members = int(report["members"])
    write_lane_receipt(
        LANE_ID, ok=True, exit_code=0, started_at=started,
        summary={"members": members, "membership_source": report["membership"].get("source"),
                 "symbols_with_gaps": report["symbols_with_gaps"], "surface_counts": report["surface_counts"],
                 "alert_requested": bool(a.alert), "alert_decision": report["alert_decision"]["reason"],
                 "alert_sent": bool(report.get("alert_sent"))},
        produced_count=members, attempted_count=members,
        empty_reason=None if members else "no_new_input",
        output_evidence=[{"kind": "manifest", "path": report["manifest"]}],
    )
    _emit_output("live", members, empty_reason=None if members else "no_new_input")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
