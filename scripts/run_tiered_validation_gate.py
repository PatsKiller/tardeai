#!/usr/bin/env python3
"""run_tiered_validation_gate.py — the first production caller of CriticPanel.

``scripts/agent_runtime/critics.py`` shipped a correct critic panel and, measured
2026-09-16, had **zero callers outside tests**. This is the caller. It runs the three
tiers over one deterministic ticket, calibrates every lane that answered, and writes an
append-only receipt.

    python scripts/run_tiered_validation_gate.py --ticket path.json
    python scripts/run_tiered_validation_gate.py --calibrate-baselines
    python scripts/run_tiered_validation_gate.py --ticket path.json --free-lane grok
    python scripts/run_tiered_validation_gate.py --self-check --no-write

WHAT IT COSTS
-------------
Nothing, by default and by construction. Tier 0 is deterministic. Tier 1 declares
``max_cost_usd = 0.0`` per lane and the panel errors any lane that reports a cent. Tier 2
is refused unless the operator sets ``TRADEAI_TIER2_PAID_JUDGE=1`` **and** a paid judge is
wired — absent either, the receipt records ``WITHHELD_OPERATOR_GATED`` and
``paid_calls: 0``. Without ``--free-lane`` nothing reaches the network at all: the lane is
preserved as a failed lane and the verdict fails closed to INSUFFICIENT_EVIDENCE, which is
the honest answer when nobody was asked.

HOW IT REACHES PRODUCTION
-------------------------
A new cron or systemd entry is operator-only (AGENTS.md §17), so this module installs none.
It runs hourly regardless, because an entrypoint that *is* installed calls it — see
``PRODUCTION_CALLER``. Exit code 0 proves nothing (§0 rule 8); the receipt, and the lane's
row in the dormant-lane report, are the evidence.

Authority: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0. Never sizes, orders, stops or promotes.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from scripts.agent_runtime.sentinel import inspect_ticket  # noqa: E402
from scripts.lib.tiered_validation import (  # noqa: E402
    FREE_TIER1_LANES,
    TierPolicy,
    run_known_bad_probe,
    validate,
)
from scripts.lib.validator_calibration import (  # noqa: E402
    Observation,
    day_one_calibration,
    load_known_bad_probes,
    seeded_probe_due,
    summarise,
)

SCHEMA = "TieredValidationRun@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
MBI_BEHAVIOR = 0

#: Where this module actually runs, and under whose schedule.
#:
#: Deliberately NOT named ``SCHEDULED_ENTRYPOINT``. ``check_dark_contracts.py`` skips any
#: module carrying that constant *whatever it says*, and what this one said was
#: "PROPOSAL ONLY — not installed". That was a true sentence, and it was also the reason
#: nothing ever reported the problem: a module with no caller at all passed the gate
#: written to find modules with no caller. The declaration was honest; the gate it
#: satisfied was empty.
#:
#: With the bypass gone, the dark-contract gate guards this module for real — remove the
#: lane named below and ``--fail-on-new`` goes red. Installing a cron entry of its own
#: would still be operator-only (AGENTS.md §17); none was added.
PRODUCTION_CALLER = (
    "scripts/run_dormant_lane_consumers.py, lane 'tiered_validation' — that entrypoint is "
    "installed at crontab `50 * * * *`, hourly, armed 2026-09-16 under operator APPROVE "
    "(full package). Tier 0 only: no provider is configured, so no reflective lane can be "
    "called and no cost can be incurred."
)

#: The producer family this gate judges. Declared so provider separation is checkable
#: rather than assumed: a grok critic over a grok author is one opinion, twice.
DEFAULT_PRODUCER_FAMILY = "deepseek"


def _state_root() -> Path:
    """The production state root, not this checkout (data/ is absent in a worktree)."""
    try:
        from scripts.lib.canonical_store_registry import production_state_root

        return Path(production_state_root())
    except Exception:  # noqa: BLE001
        return PROJECT_ROOT


def _receipt_path() -> Path:
    cio = _state_root() / "data" / "cio"
    return (cio if cio.is_dir() else PROJECT_ROOT / "data" / "cio") / "tiered_validation.jsonl"


def free_grok_provider(*, timeout: int = 60):
    """A $0 OAuth grok lane, wired only when the operator asks for it on the CLI.

    The lane budget is 0.0 and ``CriticPanel`` errors any lane that reports a cost, so a
    provider that started billing would be refused rather than paid.
    """

    def provider(request: Mapping[str, Any]) -> Mapping[str, Any]:
        from scripts.llm_lane import generate

        prompt = (
            "You are an independent critic. Do NOT rewrite the artifact and do NOT give "
            "investment advice. Reply with JSON only: "
            '{"verdict":"PASS|CAUTION|REJECT|ABSTAIN|INSUFFICIENT_EVIDENCE",'
            '"findings":[],"evidence_refs":[]}. Cite an evidence ref for any verdict '
            "other than ABSTAIN/INSUFFICIENT_EVIDENCE.\n\nARTIFACT:\n"
            + json.dumps(dict(request), sort_keys=True, default=str)[:6000]
        )
        text = generate(
            prompt,
            lane="grok",
            model="grok-3-mini",
            timeout=timeout,
            process_id="l3_independent_critic",
            task_summary="tiered_validation_tier1",
        )
        try:
            parsed = json.loads(str(text)[str(text).find("{") : str(text).rfind("}") + 1])
        except (ValueError, TypeError):
            parsed = {"verdict": "INSUFFICIENT_EVIDENCE", "findings": ["unparseable critic reply"]}
        return {
            "provider_family": "grok-oauth",
            "model": "grok-3-mini",
            "verdict": parsed.get("verdict") or "INSUFFICIENT_EVIDENCE",
            "findings": parsed.get("findings") or [],
            "evidence_refs": parsed.get("evidence_refs") or [],
            "cost_usd": 0.0,
        }

    return provider


def self_check_ticket() -> tuple[dict[str, Any], dict[str, Any]]:
    """A deterministic, obviously-broken ticket: tier 0 must block it for free."""
    ticket = {
        "symbol": "",  # missing identity — a tier-0 block
        "state": "READY",
        "direction": "LONG",
        "as_of": datetime.now(timezone.utc).isoformat(),
        "mechanics": {"entry": 10.0, "stop": 9.5, "target": 11.0},
    }
    return ticket, {"state": "FAIL", "hard_failures": ["self_check_fixture"]}


def run_once(
    ticket: Mapping[str, Any],
    validation: Mapping[str, Any],
    *,
    providers: Mapping[str, Any] | None,
    sequence_number: int,
    ledger: Mapping[str, list[Observation]] | None = None,
) -> dict[str, Any]:
    report = inspect_ticket(dict(ticket), dict(validation))
    windows: dict[str, list[Observation]] = {k: list(v) for k, v in (ledger or {}).items()}

    # Mechanism (ii): one seeded known-bad in every twenty. Run BEFORE the real request so
    # a blind lane is already convicted when its verdict on real work is read.
    probe_rows: list[dict[str, Any]] = []
    if seeded_probe_due(sequence_number) and providers and report.release_allowed:
        probes = load_known_bad_probes()
        if probes:
            probe = probes[(sequence_number // 20 - 1) % len(probes)]
            for observation in run_known_bad_probe(probe, FREE_TIER1_LANES, providers, report):
                windows.setdefault(observation.validator_id, []).append(observation)
                probe_rows.append(
                    {
                        "probe_id": probe.probe_id,
                        "lane": observation.validator_id,
                        "verdict": observation.verdict,
                        "passed_known_bad": observation.known_bad_passed,
                    }
                )

    result = validate(
        {
            "task": "Challenge this deterministic ticket without changing its facts.",
            "ticket": dict(ticket),
            "deterministic_verdict": report.verdict,
        },
        report,
        providers=providers,
        producer_family=DEFAULT_PRODUCER_FAMILY,
        policy=TierPolicy.from_env(),
        calibration_ledger=windows,
    )
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "sequence_number": sequence_number,
        "symbol": report.symbol,
        "deterministic": {"verdict": report.verdict, "release_allowed": report.release_allowed},
        "seeded_probes": probe_rows,
        "result": result.to_dict(),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Tiered validation: deterministic → free critic → gated paid judge")
    ap.add_argument("--ticket", help='JSON file: {"ticket": {...}, "validation": {...}}')
    ap.add_argument("--self-check", action="store_true", help="run the built-in tier-0 fixture")
    ap.add_argument(
        "--calibrate-baselines",
        action="store_true",
        help="stamp the three live validators against the calibration floor",
    )
    ap.add_argument("--free-lane", choices=["grok"], help="wire the free OAuth critic (costs $0)")
    ap.add_argument("--sequence", type=int, default=1, help="validation number, for 1-in-20 seeding")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-write", action="store_true", help="compute and print; persist nothing")
    args = ap.parse_args()

    if args.calibrate_baselines:
        report = summarise(day_one_calibration().values())
        print(json.dumps(report, indent=2) if args.json else _render_calibration(report))
        payload: dict[str, Any] = {"schema": SCHEMA, "kind": "calibration_baselines", **report}
    else:
        if args.self_check:
            ticket, validation = self_check_ticket()
        elif args.ticket:
            try:
                raw = json.loads(Path(args.ticket).read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                print(f"ERROR: could not read ticket: {exc}", file=sys.stderr)
                return 2
            ticket = raw.get("ticket") or raw
            validation = raw.get("validation") or {}
        else:
            ap.error("one of --ticket, --self-check or --calibrate-baselines is required")
            return 2

        providers = {"grok_free": free_grok_provider()} if args.free_lane == "grok" else None
        try:
            payload = run_once(ticket, validation, providers=providers, sequence_number=args.sequence)
        except Exception as exc:  # noqa: BLE001 — cannot-run is exit 2, never a green 0
            print(f"ERROR: validation could not run: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(payload, indent=2, default=str) if args.json else _render_run(payload))

    if not args.no_write:
        receipt = _receipt_path()
        try:
            receipt.parent.mkdir(parents=True, exist_ok=True)
            with receipt.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, sort_keys=True, default=str) + "\n")
            print(f"\n  receipt appended: {receipt}")
        except OSError as exc:
            print(f"  receipt: could not write ({exc})", file=sys.stderr)
            return 2
    return 0


def _render_calibration(report: Mapping[str, Any]) -> str:
    lines = [
        "Validator calibration — the day-one baselines, by their own numbers",
        "=" * 70,
    ]
    for row in report.get("detail", []):
        lines.append(
            f"  {row['validator_id']:28s} {row['state']:16s} n={row['n']:<5d} disagreements={row['disagreements']}"
        )
        for reason in row.get("reasons", []):
            lines.append(f"      - {reason}")
    lines.append("-" * 70)
    lines.append(
        f"  calibrated={report.get('calibrated')} uncalibrated={report.get('uncalibrated')} "
        f"blind={report.get('blind')} not_yet_measured={report.get('not_yet_measured')}"
    )
    return "\n".join(lines)


def _render_run(payload: Mapping[str, Any]) -> str:
    result = payload.get("result", {})
    lines = [
        f"Tiered validation — {payload.get('symbol')}",
        "=" * 70,
        f"  tier reached      : {result.get('tier_reached')}",
        f"  state             : {result.get('state')}",
        f"  critic calls      : {result.get('critic_calls')}   paid calls: {result.get('paid_calls')}",
        f"  cost              : ${result.get('cost_usd')}",
        f"  tier 2            : {result.get('tier2_state')}",
        f"  blind lanes       : {result.get('blind_lanes') or 'none'}",
        f"  failed lanes      : {result.get('failed_lanes') or 'none'}",
        f"  operator action   : {result.get('operator_action')}",
    ]
    for reason in result.get("downgrade_reasons", []):
        lines.append(f"      - {reason}")
    for probe in payload.get("seeded_probes", []):
        flag = "PASSED A KNOWN-BAD (BLIND)" if probe["passed_known_bad"] else "caught"
        lines.append(f"  probe {probe['probe_id']} -> {probe['lane']}: {probe['verdict']} ({flag})")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
