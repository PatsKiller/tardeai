#!/usr/bin/env python3
"""cio_heartbeat.py — Deterministic CIO event backstop scanner.

Runs as a one-shot bounded sweep.  Deterministic collection only — zero model
calls, zero direct action ledger writes, zero specialist delegation, zero Hermes
challenges, zero Telegram sends.

Cycle:
  1. Build CIO financial snapshot (deterministic, via Data Broker)
  2. Compare to previous snapshot; detect material changes
  3. Publish normalized domain events onto the CIO Event Bus
  4. Publish liveness evidence (system.heartbeat_ok)
  5. Report summary to stdout

Usage:
  python3 scripts/cio_heartbeat.py [--interval-minutes 30] [--max-actions 5]

The snapshot log lives at data/cio/cio_heartbeat_snapshots.jsonl.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# Project root first so `import scripts.lib...` works; scripts/ for `import lib...`
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT))

# -- Constants ----------------------------------------------------------------

DATA_DIR = PROJECT_ROOT / "data" / "cio"
SNAPSHOT_PATH = DATA_DIR / "cio_heartbeat_snapshots.jsonl"

# Domains from the CIO Data Broker (matches cio_portfolio.py's CIO_DOMAINS)
DETERMINISTIC_DOMAINS = [
    "portfolio",
    "risk",
    "watch",
    "rotation",
    "income",
    "reconciliation",
    "hermes_research",
    "investment_policy",
    "model_portfolio",
    "cost_basis",
    "transactions",
    "sectors",
    "holdings_detail",
]

# How long before a domain goes STALE (seconds)
DOMAIN_FRESHNESS: dict[str, int] = {
    "portfolio": 3600,
    "holdings": 1800,
    "risk": 3600,
    "watch": 7200,
    "reentry": 14400,
    "rotation": 28800,
    "income": 86400,
    "broker_reconciliation": 43200,
    "investment_policy": 86400,
    "model_portfolio": 86400,
    "cost_basis": 3600,
    "transactions": 3600,
    "sectors": 7200,
    "holdings_detail": 1800,
}


# -- Helpers ------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_jsonl(path: Path, entry: dict[str, Any]) -> None:
    """Append one line to a JSONL file with file locking."""
    import fcntl
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(json.dumps(entry, default=str) + "\n")
        f.flush()
        fcntl.flock(f, fcntl.LOCK_UN)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read all entries from a JSONL file."""
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries


def _last_snapshot() -> Optional[dict[str, Any]]:
    """Return the most recent heartbeat snapshot, or None."""
    entries = _read_jsonl(SNAPSHOT_PATH)
    return entries[-1] if entries else None


# -- Snapshot builder ---------------------------------------------------------


def build_snapshot() -> dict[str, Any]:
    """Build a deterministic CIO heartbeat snapshot via the Data Broker.

    Zero model calls.
    """
    snapshot_id = str(uuid.uuid4())[:8]
    collected_at = _now_iso()

    from lib.data_broker.cio_portfolio import get_cio_snapshot
    broker_snap = get_cio_snapshot(max_age_s=0)
    domains = broker_snap.get("domains", {})

    return {
        "snapshot_id": snapshot_id,
        "event_type": "CIO_HEARTBEAT_SNAPSHOT",
        "collected_at": collected_at,
        "domains": domains,
        "broker_version": broker_snap.get("version"),
        "health": broker_snap.get("health", {}),
    }


# -- Change detection ---------------------------------------------------------


def detect_changes(
    current: dict[str, Any],
    previous: Optional[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compare snapshots and return a list of material change descriptions."""
    changes: list[dict[str, Any]] = []
    current_domains = current.get("domains", {})
    previous_domains = previous.get("domains", {}) if previous else {}

    for domain in DETERMINISTIC_DOMAINS:
        cur = current_domains.get(domain, {})
        prev = previous_domains.get(domain, {})

        cur_state = cur.get("state", "NOT_APPLICABLE")
        prev_state = prev.get("state", "NOT_APPLICABLE")

        # Newly available domain
        if cur_state == "AVAILABLE" and prev_state != "AVAILABLE":
            changes.append({
                "domain": domain,
                "change_type": "DOMAIN_AVAILABLE",
                "previous_state": prev_state,
                "current_state": cur_state,
            })
        # Domain went stale
        elif cur_state == "DATA_UNAVAILABLE" and prev_state == "AVAILABLE":
            changes.append({
                "domain": domain,
                "change_type": "DOMAIN_WENT_STALE",
                "previous_state": prev_state,
                "current_state": cur_state,
            })
        # Data content changed
        elif cur_state == "AVAILABLE" and prev_state == "AVAILABLE":
            import hashlib
            cur_data = cur.get("data", {})
            prev_data = prev.get("data", {})
            cur_hash = hashlib.sha256(
                json.dumps(cur_data, sort_keys=True, default=str).encode()
            ).hexdigest()[:16]
            prev_hash = hashlib.sha256(
                json.dumps(prev_data, sort_keys=True, default=str).encode()
            ).hexdigest()[:16]
            if cur_hash != prev_hash:
                changes.append({
                    "domain": domain,
                    "change_type": "DATA_CHANGED",
                    "previous_hash": prev_hash,
                    "current_hash": cur_hash,
                })

    # Always report on first run (no previous snapshot)
    if previous is None:
        changes.insert(0, {
            "domain": "system",
            "change_type": "FIRST_RUN",
            "note": "Initial CIO heartbeat snapshot — establishing baseline",
        })

    return changes


# -- Behavioral finance detection (deterministic) -----------------------------


def _load_behavioral_config() -> dict[str, Any]:
    """Load behavioral detection thresholds from config."""
    cfg_path = PROJECT_ROOT / "config" / "behavioral_detection.json"
    if not cfg_path.exists():
        return {}
    try:
        return json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _detect_disposition_effect(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Rule 1: Detect long-held material losers — disposition effect signal.

    Zero model calls.  config/behavioral_detection.json for thresholds.
    """
    cfg = _load_behavioral_config()
    rule1 = cfg.get("disposition_rule1", {})
    if not rule1.get("enabled", False):
        return []

    domains = snapshot.get("domains", {})
    cost_basis_domain = domains.get("cost_basis", {})
    portfolio = domains.get("portfolio", {})

    if cost_basis_domain.get("state") != "AVAILABLE":
        return []

    total_value = portfolio.get("total_value")
    if not total_value or total_value <= 0:
        return []

    min_loss_pct = rule1.get("min_loss_pct", 0.15)
    min_loss_abs = rule1.get("min_loss_abs", 8000)
    min_holding_months = rule1.get("min_holding_months", 9)
    min_weight_pct = rule1.get("min_weight_pct", 0.025)

    findings: list[dict[str, Any]] = []

    for pos in cost_basis_domain.get("positions", []):
        symbol = pos.get("symbol", "")
        unrealized_pnl = pos.get("unrealized_pnl", 0)
        unrealized_pnl_pct = pos.get("unrealized_pnl_pct", 0)
        market_value = pos.get("market_value", 0)
        holding_months = pos.get("holding_months")

        if unrealized_pnl >= 0:
            continue

        loss_pct = abs(unrealized_pnl_pct)
        loss_abs = abs(unrealized_pnl)
        weight_pct = (market_value / total_value) * 100 if total_value > 0 else 0

        if loss_pct < (min_loss_pct * 100) and loss_abs < min_loss_abs:
            continue
        if weight_pct < (min_weight_pct * 100):
            continue
        if holding_months is not None and holding_months < min_holding_months:
            continue

        sev_cfg = rule1.get("severity", {})
        critical_loss = sev_cfg.get("critical", {}).get("min_loss_pct", 0.35)
        high_loss = sev_cfg.get("high", {}).get("min_loss_pct", 0.25)
        if loss_pct >= critical_loss * 100 or loss_abs >= 25000:
            severity = "Critical"
        elif loss_pct >= high_loss * 100:
            severity = "High"
        else:
            severity = "Medium"

        harvest_value = round(min(loss_abs, 3000) * 0.24)

        findings.append({
            "symbol": symbol,
            "bias_flag": "disposition_effect",
            "rule": "rule1_long_held_loser",
            "severity": severity,
            "loss_pct": round(loss_pct, 1),
            "loss_abs": round(loss_abs),
            "holding_months": holding_months,
            "weight_pct": round(weight_pct, 1),
            "account": pos.get("account", ""),
            "estimated_harvest_value_usd": harvest_value,
            "suggested_reframe": (
                f"If {symbol} were purchased today at current price, "
                f"would the size ({round(weight_pct, 1)}% of equity) still "
                f"match the risk budget? "
            ),
        })

    return findings


# -- Main heartbeat cycle -----------------------------------------------------


def run_heartbeat(interval_minutes: int = 30, max_actions: int = 5) -> dict[str, Any]:
    """Run one CIO heartbeat cycle.  Deterministic only — zero model calls,
    zero direct action-ledger writes, zero specialist delegation."""
    t0 = time.time()

    # 1. Build snapshot
    snapshot = build_snapshot()
    _append_jsonl(SNAPSHOT_PATH, snapshot)

    # 2. Detect changes
    all_snapshots = _read_jsonl(SNAPSHOT_PATH)
    previous = all_snapshots[-2] if len(all_snapshots) >= 2 else None
    changes = detect_changes(snapshot, previous)

    # 3. Behavioral finance detection (deterministic)
    behavioral_findings = _detect_disposition_effect(snapshot)

    # 4. Emit normalized domain events onto the CIO Event Bus
    events_emitted = 0
    try:
        from lib.cio_event_bus import CIOEventBus
        from lib.cio_semantic_event_key import (
            SemanticEventDeduplicator,
            compute_semantic_event_key,
        )

        bus = CIOEventBus()
        dedup = SemanticEventDeduplicator()

        def _emit_if_new(event_type: str, payload: dict[str, Any],
                         aggregate: dict[str, Any] | None = None,
                         **kwargs: Any) -> bool:
            """Emit event only if its semantic key has not been seen.

            The heartbeat is a recovery/backstop detector — if the primary
            publisher already emitted this event, skip it.
            """
            key = compute_semantic_event_key(
                event_type, aggregate or payload
            )
            if not dedup.check_and_mark(key):
                return False
            bus.emit(event_type, payload, semantic_event_key=key, **kwargs)
            return True

        # Portfolio material change
        port_change = next(
            (c for c in changes
             if c.get("domain") == "portfolio"
             and c.get("change_type") == "DATA_CHANGED"),
            None,
        )
        if port_change:
            if _emit_if_new("portfolio.material_change",
                            {"domain": "portfolio", "change": "DATA_CHANGED"},
                            source="cio_heartbeat"):
                events_emitted += 1

        # Risk heat change
        risk_change = next(
            (c for c in changes
             if c.get("domain") == "risk"
             and c.get("change_type") in ("DATA_CHANGED", "DOMAIN_WENT_STALE")),
            None,
        )
        if risk_change:
            if _emit_if_new("risk.heat_increased",
                            {"domain": "risk", "change": "changed"},
                            source="cio_heartbeat"):
                events_emitted += 1

        # Allocation drift
        alloc_change = next(
            (c for c in changes
             if c.get("domain") in ("model_portfolio", "allocation")),
            None,
        )
        if alloc_change:
            if _emit_if_new("allocation.drift",
                            {"domain": "model_portfolio"},
                            source="cio_heartbeat"):
                events_emitted += 1

        # Behavioral flags
        for bf in behavioral_findings:
            if _emit_if_new("behavioral.flag_raised",
                            {"symbol": bf.get("symbol", ""),
                             "rule": bf.get("rule", ""),
                             "loss_pct": bf.get("loss_pct"),
                             "holding_months": bf.get("holding_months")},
                            source="cio_heartbeat",
                            priority="HIGH"):
                events_emitted += 1

        # Domain stale
        for change in changes:
            if change.get("change_type") == "DOMAIN_WENT_STALE":
                if _emit_if_new("system.domain_stale",
                                {"domain": change.get("domain", "")},
                                source="cio_heartbeat"):
                    events_emitted += 1

        # Heartbeat OK (always emit — proves the system is alive)
        if _emit_if_new("system.heartbeat_ok",
                        {"domains": len(snapshot.get("domains", {})),
                         "changes": len(changes),
                         "behavioral_findings": len(behavioral_findings)},
                        source="cio_heartbeat", priority="LOW"):
            events_emitted += 1

    except Exception as e:
        print(f"  [cio-hb] Event bus emission failed (non-fatal): "
              f"{type(e).__name__}: {e}")

    # 5. Situation detector (Phase 2a) — after event emit; fail-soft; SHADOW
    situations_result: dict[str, Any] = {}
    try:
        from lib.cio_situation_detector import run_detector_safe, build_evidence_from_snapshot
        evidence = build_evidence_from_snapshot(snapshot)
        situations_result = run_detector_safe(evidence=evidence)
    except Exception as e:
        situations_result = {
            "errors": [f"{type(e).__name__}: {e}"],
            "plans_created": [],
        }
        print(f"  [cio-hb] Situation detector failed (non-fatal): "
              f"{type(e).__name__}: {e}")

    elapsed = time.time() - t0
    elapsed_ms = int(elapsed * 1000)

    # P5: non-material heartbeat no-op → skipped_non_material trace (fail-soft)
    try:
        plans_n = len(situations_result.get("plans_created") or [])
        material = bool(changes) or bool(behavioral_findings) or plans_n > 0
        if not material:
            try:
                from lib.cio_wake_traces import emit_closed_trace
            except Exception:
                from scripts.lib.cio_wake_traces import emit_closed_trace  # type: ignore
            emit_closed_trace(
                wake_id=f"hb_{snapshot.get('snapshot_id') or int(time.time())}",
                source="heartbeat",
                llm="skipped_non_material",
                outcome="ok",
                agent_id="alex",
                duration_ms=elapsed_ms,
            )
    except Exception:
        pass

    summary = {
        "heartbeat_id": snapshot.get("snapshot_id"),
        "collected_at": snapshot.get("collected_at"),
        "domains_collected": list(snapshot.get("domains", {}).keys()),
        "changes_detected": len(changes),
        "changes": [
            {"domain": c.get("domain"), "change_type": c.get("change_type")}
            for c in changes
        ],
        "behavioral_findings": len(behavioral_findings),
        "events_emitted": events_emitted,
        "situations": situations_result,
        "elapsed_ms": elapsed_ms,
        "mode": "shadow",
        "model_calls": 0,
        "provider_cost": 0.0,
    }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="CIO Heartbeat — deterministic event backstop scanner"
    )
    parser.add_argument("--interval-minutes", type=int, default=30)
    parser.add_argument("--max-actions", type=int, default=5)
    parser.add_argument("--once", action="store_true", default=True)
    args = parser.parse_args()

    print(f"CIO Heartbeat (deterministic) — {_now_iso()[:19]}")
    print(f"  mode=shadow  model_calls=0  provider_cost=0")

    summary = run_heartbeat(
        interval_minutes=args.interval_minutes,
        max_actions=args.max_actions,
    )

    print(f"  summary: {json.dumps(summary, default=str)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
