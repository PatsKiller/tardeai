"""DailyIntelligenceHeartbeat@v1 persist + load."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from scripts.lib.autonomy_watchdog.io import append_jsonl, atomic_write_json, read_json, read_jsonl
from scripts.lib.autonomy_watchdog.model import SCHEMA, ny_date, now_utc
from scripts.lib.maturity_control.store import resolve_root


def paths(root: Path | str | None = None) -> dict[str, Path]:
    base = resolve_root(root) / "data" / "cio"
    return {
        "jsonl": base / "daily_intelligence_heartbeats.jsonl",
        "snapshot": base / "daily_intelligence_heartbeat.json",
        "watchdog_runs": base / "watchdog_runs.jsonl",
        "watchdog_state": base / "watchdog_state.json",
        "system_sends": base / "system_telegram_sends.jsonl",
    }


def build_receipt(bundle: dict[str, Any], *, now: Optional[datetime] = None) -> dict[str, Any]:
    now = now or now_utc()
    day = ny_date(now)
    rel = bundle.get("release") or {}
    auto = (bundle.get("autonomy") or {}).get("component") or {}
    senses = (bundle.get("senses") or {}).get("component") or {}
    learn = (bundle.get("learning") or {}).get("component") or {}
    mem = (bundle.get("memory") or {}).get("component") or {}
    cio = (bundle.get("cio") or {}).get("component") or {}
    fin = (bundle.get("finops") or {}).get("component") or {}
    auth = (bundle.get("authority") or {}).get("component") or {}
    host = bundle.get("host_health") or {}
    return {
        "schema": SCHEMA,
        "date": day,
        "generated_at": now.isoformat(),
        "release_sha": rel.get("release_sha") or "",
        "provenance_status": (rel.get("classification") or "UNKNOWN_RELEASE"),
        "overall": bundle.get("overall"),
        "autonomy": {
            "state": auto.get("status"),
            "wakes": (auto.get("wakes") or 0),
            "successful_work": auto.get("successful_work") or 0,
            "expected_idle": auto.get("expected_idle") or 0,
            "failures": auto.get("failures") or 0,
            "reason": auto.get("reason"),
        },
        "senses": {
            "state": senses.get("status"),
            "receipts": senses.get("receipts") or 0,
            "providers": senses.get("providers") or [],
            "capabilities": senses.get("capabilities") or [],
            "invalid_or_stale": senses.get("invalid_or_stale") or 0,
            "reason": senses.get("reason"),
        },
        "learning": {
            "state": learn.get("status"),
            "cases": learn.get("cases") or 0,
            "matured": learn.get("matured") or 0,
            "scored": learn.get("scored") or 0,
            "reflections": learn.get("reflections") or 0,
            "candidates": learn.get("candidates") or 0,
            "ratified": learn.get("ratified") or 0,
            "promotions": learn.get("promotions") or 0,
            "restrictions": learn.get("restrictions") or 0,
            "reason": learn.get("reason"),
        },
        "memory": {
            "state": mem.get("status"),
            "provider": mem.get("provider"),
            "records": mem.get("records") or 0,
            "admissions": mem.get("admissions") or 0,
            "retrievals": mem.get("retrievals") or 0,
            "contradictions": mem.get("contradictions") or 0,
            "expirations": mem.get("expirations") or 0,
            "influence_mode": mem.get("influence_mode"),
            "reason": mem.get("reason"),
        },
        "cio": {
            "state": cio.get("status"),
            "material_scans": cio.get("material_scans") or 0,
            "immediate": cio.get("immediate") or 0,
            "digest": cio.get("digest") or 0,
            "command_center_only": cio.get("command_center_only") or 0,
            "suppressed": cio.get("suppressed") or 0,
            "Telegram_financial_sends": cio.get("Telegram_financial_sends") or 0,
            "last_financial_telegram": cio.get("last_financial_telegram"),
            "silence_explained": cio.get("silence_explained"),
            "silence_copy": cio.get("silence_copy"),
            "reason": cio.get("reason"),
        },
        "finops": {
            "state": fin.get("status"),
            "events": fin.get("events") or 0,
            "invalid_events": fin.get("invalid_events") or 0,
            "reason": fin.get("reason"),
        },
        "health": {
            "overall": host.get("overall") or bundle.get("overall"),
            "degraded_components": host.get("degraded_components") or [],
            "external_dependencies": host.get("external_dependencies") or [],
            "operator_findings": host.get("operator_findings") or 0,
        },
        "authority": {
            "memory_behavior_influence": auth.get("memory_behavior_influence") or "0",
            "broker_mutations": auth.get("broker_mutations") or 0,
            "order_mutations": auth.get("order_mutations") or 0,
            "stop_mutations": auth.get("stop_mutations") or 0,
            "risk_mutations": auth.get("risk_mutations") or 0,
            "two_fa_mutations": auth.get("two_fa_mutations") or 0,
        },
        "components": bundle.get("components") or [],
        "financial_action": False,
        "authority_class": "READ_ONLY_ADVISORY",
    }


def persist_receipt(rec: dict[str, Any], *, root: Path | str | None = None) -> dict[str, Any]:
    p = paths(root)
    append_jsonl(p["jsonl"], rec)
    atomic_write_json(p["snapshot"], rec)
    return rec


def load_snapshot(root: Path | str | None = None) -> dict[str, Any]:
    return read_json(paths(root)["snapshot"])


def load_history(root: Path | str | None = None, limit_days: int = 30) -> list[dict[str, Any]]:
    rows = read_jsonl(paths(root)["jsonl"])
    by_day: dict[str, dict[str, Any]] = {}
    for rec in rows:
        day = str(rec.get("date") or "")
        if day:
            by_day[day] = rec
    days = sorted(by_day)[-limit_days:]
    return [by_day[d] for d in days]


def format_text(rec: dict[str, Any]) -> str:
    auto = rec.get("autonomy") or {}
    senses = rec.get("senses") or {}
    learn = rec.get("learning") or {}
    mem = rec.get("memory") or {}
    cio = rec.get("cio") or {}
    fin = rec.get("finops") or {}
    health = rec.get("health") or {}
    sha = str(rec.get("release_sha") or "")[:12]
    findings = int(health.get("operator_findings") or 0)
    return (
        "TRADE AI — DAILY INTELLIGENCE\n"
        f"Release {sha or 'unknown'} provenance {rec.get('provenance_status')}\n"
        f"Autonomy {auto.get('state')} — {auto.get('wakes')} wakes\n"
        f"Senses {senses.get('state')} — {senses.get('receipts')} receipts\n"
        f"Learning {learn.get('state')} — reflection {learn.get('reflections')}\n"
        f"Memory {mem.get('state')} — {mem.get('retrievals')} retrievals / {mem.get('influence_mode')}\n"
        f"CIO {cio.get('state')} — {cio.get('material_scans')} scans, "
        f"{cio.get('immediate')} immediate, {cio.get('suppressed')} suppressed\n"
        f"FinOps {fin.get('state')} — {fin.get('events')} events\n"
        f"Financial alerts today: {'none' if not cio.get('immediate') else cio.get('immediate')}\n"
        f"External/operator findings: {findings}"
    )
