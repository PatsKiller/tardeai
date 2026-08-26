"""One watchdog cycle: collect, persist, optional SYSTEM telegram."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from scripts.lib.autonomy_watchdog.collectors import collect_all
from scripts.lib.autonomy_watchdog.heartbeat import (
    build_receipt,
    format_text,
    load_snapshot,
    paths,
    persist_receipt,
)
from scripts.lib.autonomy_watchdog.io import append_jsonl, atomic_write_json, read_json
from scripts.lib.autonomy_watchdog.model import FAILED, HEALTHY, now_utc
from scripts.lib.autonomy_watchdog import telegram_system as TG


CRITICAL_TRANSITIONS = {
    (HEALTHY, "DEGRADED"),
    (HEALTHY, FAILED),
    ("DEGRADED", FAILED),
}


def _run_record(status: str, err: str = "", started: Optional[str] = None, now: Optional[datetime] = None) -> dict[str, Any]:
    n = now or now_utc()
    return {
        "watchdog_last_started": started or n.isoformat(),
        "watchdog_last_completed": n.isoformat(),
        "status": status,
        "error": err,
        "authority": "READ_ONLY_ADVISORY",
        "financial_action": False,
    }


def _transitions(prev: dict[str, Any], comps: list[dict[str, Any]]) -> list[dict[str, str]]:
    old = {c.get("component"): c.get("status") for c in (prev.get("components") or []) if isinstance(c, dict)}
    out = []
    for c in comps:
        name = c.get("component")
        cur = c.get("status")
        was = old.get(name)
        if not name or not cur or was == cur or was is None:
            continue
        if (was, cur) in CRITICAL_TRANSITIONS:
            out.append({"component": name, "from": was, "to": cur, "kind": f"{name}_{was}_to_{cur}"})
        elif was == FAILED and cur in {HEALTHY, "EXPECTED_IDLE", "DEGRADED"}:
            out.append({"component": name, "from": was, "to": cur, "kind": f"{name}_RECOVERED"})
        elif name == "authority" and cur == FAILED:
            out.append({"component": name, "from": was or "?", "to": cur, "kind": "authority_violation"})
        elif name == "release" and cur == FAILED:
            out.append({"component": name, "from": was or "?", "to": cur, "kind": "provenance_mismatch"})
    return out


def run_cycle(
    *,
    root=None,
    env=None,
    now: Optional[datetime] = None,
    dry_run: bool = False,
    send_telegram: bool = True,
    telegram_canary: bool = False,
) -> dict[str, Any]:
    started = (now or now_utc()).isoformat()
    try:
        bundle = collect_all(root=root, now=now, env=env)
        rec = build_receipt(bundle, now=now)
        if not dry_run:
            persist_receipt(rec, root=root)
        prev = read_json(paths(root)["watchdog_state"])
        transitions = _transitions(prev, rec.get("components") or [])
        telegram: dict[str, Any] = {"daily": None, "canary": None, "alerts": []}
        if telegram_canary:
            telegram["canary"] = TG.send_canary(root=root, env=env, now=now) if not dry_run else {"dry_run": True}
        if send_telegram and not dry_run:
            telegram["daily"] = TG.send_daily(format_text(rec), root=root, env=env, now=now)
            for tr in transitions:
                telegram["alerts"].append(
                    TG.send_alert(
                        tr["kind"],
                        f"{tr['component']}: {tr['from']} -> {tr['to']}",
                        root=root, env=env, now=now,
                    )
                )
        elif dry_run:
            telegram["daily"] = {"dry_run": True, "would_send": TG.after_daily_window(now), "identity": TG.daily_identity(now)}
        state = {
            "at": rec["generated_at"],
            "overall": rec.get("overall"),
            "components": rec.get("components"),
            "last_daily_identity": TG.daily_identity(now),
        }
        if not dry_run:
            atomic_write_json(paths(root)["watchdog_state"], state)
            append_jsonl(paths(root)["watchdog_runs"], _run_record("ok", started=started, now=now))
        return {
            "ok": True,
            "dry_run": dry_run,
            "receipt": rec,
            "telegram": telegram,
            "transitions": transitions,
            "watchdog": _run_record("ok", started=started, now=now),
            "authority": "READ_ONLY_ADVISORY",
            "financial_action": False,
        }
    except Exception as e:
        err = f"{type(e).__name__}:{e}"[:200]
        if not dry_run:
            append_jsonl(paths(root)["watchdog_runs"], _run_record("error", err, started=started, now=now))
        return {"ok": False, "error": err, "dry_run": dry_run, "financial_action": False}


def api_payload(*, root=None) -> dict[str, Any]:
    from scripts.lib.autonomy_watchdog.heartbeat import load_history
    snap = load_snapshot(root)
    hist = load_history(root, 30)
    runs = read_json(paths(root)["watchdog_state"])
    sends = []
    try:
        from scripts.lib.autonomy_watchdog.io import read_jsonl
        sends = [s for s in read_jsonl(paths(root)["system_sends"]) if s.get("kind") in {"daily_heartbeat", "canary", "alert"}][-20:]
    except Exception:
        sends = []
    last_daily = next((s for s in reversed(sends) if s.get("kind") == "daily_heartbeat" and s.get("ok")), None)
    last_sys = next((s for s in reversed(sends) if s.get("ok")), None)
    return {
        "ok": True,
        "schema": "DailyIntelligenceHeartbeat@v1",
        "today": snap,
        "components": (snap.get("components") if snap else []) or [],
        "history": hist,
        "watchdog_state": runs,
        "last_system_telegram": last_sys,
        "last_daily_system_telegram": last_daily,
        "system_channel": TG.configured(),
        "authority": "READ_ONLY_ADVISORY",
        "mutation": False,
        "financial_action": False,
    }
