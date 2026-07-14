#!/usr/bin/env python3
"""redeploy_operator_packet — version-bound operator decision packet (advisory only).

Regenerates the packet FROM THE LIVE SNAPSHOT it documents, stamped with the exact
plan version, generator/policy versions and generation time — a packet can never
again describe a version other than the one the workstation shows
(OVR-P1-PACKET-VERSION-STALE).

Usage: .venv/bin/python scripts/redeploy_operator_packet.py --event 144
Writes docs/audits/<SYM>_<event>_DECISION_PACKET_v<version>_<date>.md and refreshes
the unversioned _LATEST pointer file.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def fmt(v, nd=2):
    if v is None:
        return "—"
    try:
        return f"${float(v):,.{nd}f}"
    except (TypeError, ValueError):
        return str(v)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--event", type=int, required=True)
    args = ap.parse_args()

    from db_adapter import _get_conn
    from lib.redeploy_plan_db import list_plans_for_event

    conn = _get_conn()
    cur = conn.cursor()
    plans = list_plans_for_event(cur, args.event)
    if not plans:
        print("no plans"); return 1
    version = plans[0]["version"]
    cur.execute("""SELECT symbol, account, sold_at, net_proceeds_usd, reconciliation_status,
                          metadata->'recommendation', metadata->'pm_memo_structured',
                          metadata->'phase_b'->>'generator_version',
                          metadata->'phase_b'->>'regime_basis'
                   FROM deploy_events WHERE id=%s""", (args.event,))
    sym, account, sold_at, net, recon_status, rec, memo, gen, regime = cur.fetchone()
    prim = rec["primary"]
    primary_plan = next((p for p in plans if p["plan_archetype"] == prim["archetype"]), plans[0])
    fin = primary_plan.get("financials") or {}
    pi = primary_plan.get("plan_income") or {}
    rs = primary_plan.get("restoration_summary") or {}

    # capital ledger state
    cap_line = "capital ledger unavailable"
    try:
        from lib.redeploy_capital_book import build_capital_book
        book = build_capital_book(cur, limit=500)
        acct_cap = (book.get("account_capital") or {}).get(account) or {}
        row = next((r for r in book.get("rows") or []
                    if int(r.get("event_id") or r.get("id") or 0) == args.event), {})
        cap_line = (f"account visible cash {fmt(acct_cap.get('visible_cash_usd'))}, open claims "
                    f"{fmt(acct_cap.get('open_claims_usd'))}, allocatable "
                    f"{fmt(acct_cap.get('currently_allocatable_usd'))}"
                    + (f" — **OVERCLAIMED by {fmt(acct_cap.get('overclaim_usd'))}**"
                       if acct_cap.get("overclaimed") else "")
                    + f"; this event: `{row.get('capital_status') or 'n/a'}`")
    except Exception as e:
        cap_line = f"capital ledger error: {str(e)[:80]}"

    from lib.redeploy_oversight import governance_projection
    gov = governance_projection(cur, args.event)
    cur.execute("SELECT COUNT(*) FROM redeploy_audit_log WHERE deploy_event_id=%s", (args.event,))
    audit_n = cur.fetchone()[0]
    conn.rollback()

    now = datetime.now(timezone.utc)
    date = now.date().isoformat()
    legs_md = "\n".join(
        f"| {l['ticker']} | {l.get('role') or '—'} | {fmt(l.get('target_dollars'))} "
        f"| {l.get('target_shares') or '—'} |"
        for l in primary_plan.get("legs") or [])
    scoreboard = " · ".join(f"{k} {v}" for k, v in sorted(
        (rec.get("scoreboard") or {}).items(), key=lambda kv: -kv[1]))
    alts = "\n".join(
        f"- Plan {a['archetype']} (score {a['total_score']}): choose when {a['choose_when']}"
        for a in rec.get("alternatives") or [])
    donot = "\n".join(f"- Plan {d['archetype']}: {d['reason']}"
                      for d in rec.get("do_not_choose") or [])

    body = f"""# {sym} event #{args.event} — operator decision packet (version-bound)

**BOUND TO plan version {version}** · generated {now.isoformat()} · generator `{gen}` ·
decision policy `{(primary_plan.get('decision_score') or {}).get('decision_policy_version')}` ·
regime basis `{regime}` · **advisory only — this desk places no orders.**
If the workstation shows a different plan version, REGENERATE this packet before relying on it.

## Event
Sold **{sym}** in `{account}` on {sold_at}; net proceeds {fmt(net)}; settlement `{recon_status}`.
Capital ledger: {cap_line}.

## System recommendation
{"**DECISIVE**" if rec.get("decisive") else "**NO DECISIVE WINNER** — " + str(rec.get("tie_policy"))}

**Primary: Plan {prim['archetype']}** — destination **Plan {prim.get('destination_archetype')}**,
implementation **{prim.get('implementation_policy')}** (score {prim['total_score']}).
{prim.get('objective')}

| Amount | Value |
|---|---|
| Ultimate target | {fmt(prim.get('ultimate_target_usd'))} |
| Implement now (stage-1) | {fmt(prim.get('implement_now_usd'))} |
| Pending future stages | {fmt(prim.get('pending_future_stages_usd'))} |
| Uncommitted cash | {fmt(prim.get('uncommitted_cash_usd'))} |
| Reserve | {fmt(prim.get('reserve_usd'))} |
| Whole-share residual | {fmt(prim.get('residual_usd'))} |

Reconciliation: legs {fmt(fin.get('executable_at_current_quote_usd'))} + reserve
{fmt(fin.get('reserve_usd'))} + residual {fmt(fin.get('whole_share_residual_usd'))}
= {fmt(fin.get('total_accounted_usd'))} vs deployable {fmt(fin.get('deployable_cash_usd'))}
→ reconciles: **{fin.get('reconciles')}**.

Income: plan {fmt(pi.get('expected_annual_income_usd'))}/yr · vs post-sale
{fmt(pi.get('income_vs_post_sale_usd'))} ({pi.get('income_vs_post_sale_note')}) · vs pre-sale
{fmt(pi.get('income_vs_pre_sale_usd'))} ({pi.get('income_vs_pre_sale_note')}).

Destination restoration: capped {rs.get('restored_pct_of_removed', '—')}% · over-restoration
{fmt(rs.get('over_restoration_usd'))} · unrestored {fmt(rs.get('unrestored_usd'))} · tracking error
{fmt(rs.get('tracking_error_usd'))}.

| Leg | Role | Dollars | Shares |
|---|---|---:|---:|
{legs_md}

## Scoreboard
{scoreboard}

Why primary: {'; '.join(prim.get('reasons') or [])}

### Alternatives
{alts}

### Do not choose
{donot or '- none flagged'}

## Governance (canonical projection — full immutable key)

| Field | Value |
|---|---|
| Plan / ID / version | {gov.get('plan_archetype')} / {gov.get('plan_id')} / v{gov.get('plan_version')} |
| Destination / policy | Plan {gov.get('destination_archetype')} / {gov.get('implementation_policy')} |
| ChatGPT lane disposition | {(gov.get('oversight_lane_dispositions') or {}).get('chatgpt', '—')} |
| Grok lane disposition | {(gov.get('oversight_lane_dispositions') or {}).get('grok', '—')} |
| Oversight aggregate | {str(gov.get('oversight_status')).upper()} (runs {gov.get('oversight_run_ids')}, policy {gov.get('oversight_policy_version')}) |
| Operator state | {gov.get('readiness_status')} |
| Event state | {gov.get('event_operator_status')} |
| Capital state | {gov.get('capital_status')} |
| Locked | {gov.get('locked_at')} by {gov.get('locked_by')} |
| Calculation snapshot | {gov.get('calculation_snapshot_id')} |
| Implementation review approved | {gov.get('implementation_review_approved')} |
| Governance consistent | {gov.get('consistent')}{' — MISMATCHES: ' + '; '.join(gov.get('mismatches') or []) if not gov.get('consistent') else ''} |

Audit lineage rows: {audit_n}. This packet SUPERSEDES any packet generated before
{gov.get('locked_at') or now.isoformat()} for this event.
"""
    if gov.get("locked") and not gov.get("consistent"):
        print("REFUSING packet: governance mismatches:", gov.get("mismatches"))
        return 1
    out_dir = ROOT / "docs" / "audits"
    versioned = out_dir / f"{sym}_{args.event}_DECISION_PACKET_v{version}_{date}.md"
    versioned.write_text(body)
    (out_dir / f"{sym}_{args.event}_DECISION_PACKET_LATEST.md").write_text(body)
    print(f"wrote {versioned.name} (+ _LATEST pointer), bound to plan version {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
