#!/usr/bin/env python3
"""Deterministic due diligence for existing trade proposals.

Unlike the legacy proposal entry-planner lane, this producer never asks a model
to author or amend entry, stop, target, size or account mechanics. It evaluates
the proposal exactly as stored against the current governed Watch packet,
account-specific capacity and normalized event state. Optional local/OAuth lanes
may critique only after the deterministic packet passes.

Default behavior is read-only and model-free. Without ``--dry-run`` the only
write is the JSON research artifact under ``data/runtime``; proposal rows and
states are never changed.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(1, str(ROOT / "scripts" / "lib"))

from research_due_diligence import content_hash
from research_due_diligence_adapters import proposal_due_diligence

ARTIFACT = ROOT / "data" / "runtime" / "proposal_due_diligence_latest.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _first(mapping: dict, names: tuple[str, ...]):
    for name in names:
        value = mapping.get(name)
        if value is not None:
            return value
    return None


def _account_context(proposal: dict) -> dict:
    return {
        "account": _first(proposal, (
            "account", "account_key", "account_id", "broker_account",
            "target_account", "account_name",
        )),
        "sizing": _first(proposal, (
            "proposed_position_size", "position_size", "size_dollars",
            "proposed_qty", "quantity", "shares", "contracts",
        )),
        "capacity": _first(proposal, (
            "account_capacity", "remaining_capacity", "risk_budget_remaining",
            "buying_power_after", "available_cash", "capacity_pct",
        )),
        "as_of": proposal.get("updated_at") or proposal.get("created_at"),
        "policy_version": proposal.get("risk_policy_version")
        or proposal.get("sizing_policy_version") or "proposal-account-context-unversioned",
    }


def _event_context(packet: dict) -> dict:
    event_state = packet.get("event_state") or {}
    event = event_state.get("earnings") if isinstance(event_state.get("earnings"), dict) else event_state
    state = str(event.get("state") or event_state.get("impact") or "UNKNOWN").upper()
    return {
        **event,
        "state": state,
        "blocks_action": bool(event.get("blocks_action"))
        or state in {"UNKNOWN", "BLOCKED", "EVENT_BLOCKED", "DATA_UNAVAILABLE"},
        "as_of": packet.get("evaluated_at") or packet.get("generated_at"),
        "policy_version": packet.get("action_policy_version") or "normalized-event-contract",
    }


def _ticket(proposal: dict) -> dict:
    entry = _first(proposal, ("proposed_entry", "entry", "limit_price"))
    stop = _first(proposal, ("proposed_stop", "stop", "stop_price"))
    target = _first(proposal, ("proposed_target1", "target", "target_price"))
    return {
        "structure": proposal.get("strategy_id") or proposal.get("strategy") or "EXISTING_PROPOSAL",
        "entry_mode": proposal.get("entry_mode") or "EXACT_STORED_PROPOSAL",
        "entry_state": proposal.get("status"),
        "entry_zone": proposal.get("entry_zone") or ([entry, entry] if entry is not None else []),
        "limit_price": entry,
        "stop_price": stop,
        "targets": [target] if target is not None else [],
        "risk_reward": proposal.get("risk_reward") or proposal.get("rr"),
        "trigger": proposal.get("trigger"),
        "invalidation": proposal.get("invalidation"),
        "mechanics_current": True,
    }


def _review_validation(diligence: dict, ticket: dict, watch_packet: dict) -> dict:
    import watch_packet_quality

    selected = watch_packet_quality.select_governing_validation(watch_packet)
    watch_validation = selected.get("validation") or {}
    levels = (diligence.get("evidence") or {}).get("proposal_levels") or {}
    return {
        "validator_version": "proposal-due-diligence-v1",
        "state": "PASS" if diligence.get("deterministic_state") == "PASS"
        else "REVIEW_REQUIRED" if diligence.get("deterministic_state") == "REVIEW_REQUIRED"
        else "FAIL",
        "hard_failures": diligence.get("hard_failures") or [],
        "warnings": diligence.get("warnings") or [],
        "recomputed": {
            "entry": levels.get("entry"),
            "stop": levels.get("stop"),
            "target": levels.get("target"),
            "risk_reward": levels.get("rr_recomputed"),
        },
        "quality_admission": watch_validation.get("quality_admission") or {},
        "ticket_hash": content_hash(ticket),
        "facts_hash": diligence.get("packet_hash"),
        "watch_validation_source": selected.get("source"),
    }


def _review_facts(packet: dict, diligence: dict) -> dict:
    snapshot = packet.get("current_input_snapshot") or packet.get("input_snapshot") or {}
    market = snapshot.get("market") or {}
    validation = _review_validation(diligence, _ticket({}), packet)
    quality_facts = (validation.get("quality_admission") or {}).get("facts_used") or {}
    return {
        "live_price": packet.get("current_price") or market.get("price"),
        "enriched_price": packet.get("price_used"),
        "live_price_as_of": packet.get("facts_as_of") or market.get("price_as_of"),
        "enriched_at": market.get("technical_as_of"),
        "atr": None,
        "rvol": market.get("rvol"),
        "float_m": quality_facts.get("float_m"),
        "fundamentals": ((packet.get("input_snapshot") or {}).get("fundamentals") or {}),
        "technical_state": packet.get("technical_state") or {},
        "deterministic_thesis": packet.get("deterministic_thesis") or {},
        "data_quality": packet.get("data_quality") or {},
        "events": packet.get("event_state") or {},
        "catalysts": [],
        "support": packet.get("support") or [],
        "resistance": packet.get("resistance") or [],
    }


def _proposals(cur, limit: int, symbols: list[str] | None) -> list[dict]:
    params = []
    where = ["status IN ('PENDING','APPROVED','APPROVED_FOR_PAPER_TEST')"]
    if symbols:
        where.append("upper(symbol) = ANY(%s)")
        params.append([symbol.upper() for symbol in symbols])
    params.append(limit)
    cur.execute(
        f"""SELECT to_jsonb(p) FROM paper_trade_proposals p
              WHERE {' AND '.join(where)}
              ORDER BY created_at DESC LIMIT %s""",
        tuple(params),
    )
    return [row[0] or {} for row in cur.fetchall()]


def _watch_packet(cur, symbol: str) -> dict:
    cur.execute(
        """SELECT packet FROM decision_packets
             WHERE upper(symbol)=%s AND superseded_by IS NULL
             ORDER BY generated_at DESC LIMIT 1""",
        (symbol.upper(),),
    )
    row = cur.fetchone()
    return row[0] if row else {}


def build_report(conn, *, limit: int = 100, symbols: list[str] | None = None,
                 review_lanes: tuple[str, ...] = ()) -> dict:
    cur = conn.cursor()
    proposals = _proposals(cur, limit, symbols)
    rows = []
    counts: Counter[str] = Counter()
    model_calls = 0
    for proposal in proposals:
        symbol = str(proposal.get("symbol") or "").upper()
        packet = _watch_packet(cur, symbol) if symbol else {}
        diligence = proposal_due_diligence(
            proposal,
            packet,
            account_context=_account_context(proposal),
            event_context=_event_context(packet),
        ) if packet else {
            "domain": "proposal",
            "subject": {"proposal_id": proposal.get("id"), "symbol": symbol},
            "deterministic_state": "BLOCKED",
            "hard_failures": ["no current governed Watch packet"],
            "warnings": [],
            "packet_hash": content_hash({"proposal": proposal, "watch_packet": None}),
            "downstream": {"proposal_research_complete": False},
            "model_oversight": {"allowed": False},
        }
        reviews = {}
        if review_lanes and diligence.get("deterministic_state") == "PASS":
            import strategy_ticket_review as reviewer
            ticket = _ticket(proposal)
            validation = _review_validation(diligence, ticket, packet)
            reviews = reviewer.run_free_reviews(
                symbol,
                ticket,
                _review_facts(packet, diligence),
                validation,
                lanes=review_lanes,
            )
            model_calls += len([
                value for key, value in reviews.items()
                if not key.startswith("_") and isinstance(value, dict)
                and value.get("verdict") != "UNAVAILABLE"
            ])
        state = diligence.get("deterministic_state") or "BLOCKED"
        counts[state] += 1
        rows.append({
            "proposal_id": proposal.get("id"),
            "symbol": symbol,
            "status": proposal.get("status"),
            "due_diligence": diligence,
            "reviews": reviews,
            "proposal_state_changed": False,
        })
    return {
        "contract": "proposal-specialized-research-v1",
        "generated_at": _now(),
        "proposal_count": len(rows),
        "states": dict(sorted(counts.items())),
        "rows": rows,
        "model_calls_completed": model_calls,
        "paid_lane_calls": 0,
        "authority": {
            "proposal_state_write": False,
            "database_write": False,
            "broker_or_order_action": False,
            "approval_or_2fa_action": False,
            "models_critique_only": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--symbols")
    parser.add_argument("--review-lanes", default="",
                        help="optional comma list: local,grok,chatgpt; default is no model calls")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.limit < 1 or args.limit > 1000:
        raise SystemExit("--limit must be between 1 and 1000")
    lanes = tuple(
        lane for lane in (part.strip() for part in args.review_lanes.split(","))
        if lane in {"local", "grok", "chatgpt"}
    )
    symbols = [part.strip().upper() for part in (args.symbols or "").split(",") if part.strip()]

    from env_bootstrap import load_env
    load_env()
    from db_adapter import _get_conn
    conn = _get_conn()
    report = build_report(conn, limit=args.limit, symbols=symbols or None, review_lanes=lanes)
    public = {key: value for key, value in report.items() if key != "rows"}
    print(json.dumps(public, indent=2, sort_keys=True, default=str))
    if not args.dry_run:
        ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
        ARTIFACT.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")
        print(f"proposal_due_diligence_artifact|{ARTIFACT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
