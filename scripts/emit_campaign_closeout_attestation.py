#!/usr/bin/env python3
"""Phase 5 — release discipline. Emit the campaign's terminal marker, fail-closed.

READ_ONLY_ADVISORY. Runs read-only probes, states a disposition per backlog item,
and chooses one of three terminal markers. Grants nothing and authorizes no
deployment.

    python scripts/emit_campaign_closeout_attestation.py            # print
    python scripts/emit_campaign_closeout_attestation.py --json     # machine form
    python scripts/emit_campaign_closeout_attestation.py --out PATH # write it

Exit code is 0 when the attestation is produced, whatever it says. The marker is
the output, not the exit status — a BLOCKED closeout is a successful run of this
tool, and treating it as a failure is how a real BLOCKED gets retried until it
turns green.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.lib.campaign_closeout import (  # noqa: E402
    Item,
    build_attestation,
    probe_guard_remote_approval,
    probe_provider_limits_not_invented,
    probe_serving_sha_agreement,
    probe_single_search_ledger,
)

CAMPAIGN = "pre-persistent-agent-truth-closeout-20260905"


def collect(root: Path) -> list[Item]:
    """The backlog, each item with a measured disposition.

    Items whose evidence lives off this box are recorded UNMEASURED rather than
    omitted. Omitting them would let the marker go green on a shorter list,
    which is the failure this whole campaign has been about.
    """
    items: list[Item] = []

    d, e = probe_serving_sha_agreement(root)
    items.append(Item("P0_serving_sha_attestation", "P0",
                      "the serving build is tied to an exact source commit", d, e))

    d, e = probe_single_search_ledger(root)
    items.append(Item("P0_research_single_ledger", "P0",
                      "search spend is counted in exactly one place", d, e))

    d, e = probe_provider_limits_not_invented(root)
    items.append(Item("P0_provider_limits_observed", "P0",
                      "no provider plan is asserted from a comment", d, e))

    d, e = probe_guard_remote_approval(root)
    items.append(Item("SUP_remote_approval_controls", "SUP",
                      "remote approval cannot be self-granted by an agent", d, e))

    # ── measured elsewhere in this campaign, and honestly not closed ─────────
    items.append(Item(
        "P0_inbound_persist_before_process", "P0",
        "inbound persist-before-process is proven by durable rows",
        "OPEN",
        "communication_inbound_checkpoint holds 0 rows: the migration is applied "
        "and the poller is live, but the path has never been exercised. The DB "
        "checkpoint is 0 while .telegram_callback_offset holds 113864091, so "
        "replay of approve/reject callbacks is not denied by claim_update."))

    items.append(Item(
        "P1_delivery_reconciliation", "P1",
        "every delivery has an evidenced terminal disposition",
        "PARTIAL",
        "measured 2026-09-05: 26 RESERVED / 23 LEGACY_DELIVERED / 8 SENT of 57. "
        "Only 2 rows carry real provider evidence. 18 rows settled during the "
        "session by idempotency collision, not by evidence. 5 genuine operator "
        "alerts remain UNKNOWN with no honest terminal available."))

    items.append(Item(
        "P1_brave_september_count", "P1",
        "the September Brave figure is reconciled against the provider",
        "OPEN",
        "the DIVERGENCE is closed — one counter now, validated by 20 dry-run "
        "properties. The NUMBER is not: L3 reports 60 and is the counter to "
        "trust (flocked, atomic), but the provider-billed figure is unmeasurable "
        "from this host. Requires the operator's Brave dashboard."))

    items.append(Item(
        "P1_drive_truth_index", "P1",
        "the Drive corpus has a current truth index with supersession",
        "UNMEASURED",
        "requires Drive access, which this host does not have in this session. "
        "Not assessed rather than assumed."))

    items.append(Item(
        "P2_non_telegram_channels_dark", "P2",
        "email/slack/whatsapp are truthfully dark",
        "CLOSED",
        "channel_adapters.py:274 `deliver: bool = False` by default and the "
        "module is documented record-only at :4; send_via_gateway has non-test "
        "callers in exactly one file."))

    items.append(Item(
        "P2_cost_basis_exceptions", "P2",
        "FCNTX and SCHD cost-basis exceptions are adjudicated",
        "OPEN",
        "unchanged this campaign; still requires statement adjudication."))

    return items


def render(att: dict) -> str:
    lines = [
        "=" * 78,
        f"CAMPAIGN CLOSEOUT — {att['campaign']}",
        f"generated {att['generated_at']}",
        "=" * 78,
        "",
        f"  MARKER: {att['marker']}",
        f"  {att['marker_reason']}",
        "",
        "  " + "  ".join(f"{k}={v}" for k, v in sorted(att["counts"].items())),
        "",
        "-" * 78,
    ]
    for it in att["items"]:
        flag = "BLOCKS" if it["blocks_ready"] else "  ok  "
        lines.append(f"[{flag}] {it['priority']:>3}  {it['key']}")
        lines.append(f"         claim: {it['claim']}")
        lines.append(f"         {it['disposition']}: {it['evidence']}")
        lines.append("")
    lines.append("-" * 78)
    lines.append(att["authority"])
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--out", help="write the attestation to this path")
    ap.add_argument("--rolled-back", action="store_true",
                    help="operator states the campaign's changes were reverted. "
                         "Never inferred: 'unproven' and 'undone' are different.")
    args = ap.parse_args()

    att = build_attestation(CAMPAIGN, collect(ROOT), rolled_back=args.rolled_back)
    text = json.dumps(att, indent=1) if args.json else render(att)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"\nwritten: {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
