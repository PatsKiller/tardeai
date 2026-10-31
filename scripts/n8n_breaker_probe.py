#!/usr/bin/env python3
"""n8n breaker half-open probe: release a long-open breaker once so the lane's next slot is a probe, keep it closed
on a pass, re-open it at once (with backoff) on a failure. Every probe, release and re-open leaves a receipt.

Coordinator 2026-10-31, under the operator's "validate all stuck agents and processes fix montior and make auto
healings with claude code": ten breakers had been open for 22 h to 8 days because only a completed run can close one
and an open breaker blocks every run. Decisions: ``scripts/lib/n8n_breaker_probe.py``.

  python3 scripts/n8n_breaker_probe.py            # dry run (default): what it would do; ledger opened read-only
  python3 scripts/n8n_breaker_probe.py --apply    # act — only when config enabled is true (§25.10.2)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib import n8n_breaker_probe as BP  # noqa: E402

CONFIG_PATH = PROJECT_ROOT / "config" / "n8n_breaker_probe.json"


def load_config(path: Path | str = CONFIG_PATH) -> dict:
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    if cfg.get("schema") != "N8nBreakerProbe@v1":
        raise ValueError(f"{path}: expected schema N8nBreakerProbe@v1")
    return cfg


def state_root() -> Path:
    return Path(os.environ.get("TRADEAI_STATE_ROOT") or Path.home() / "trade-ai-releases" / "persistent-state")


def _read_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _atomic(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.tmp-{os.getpid()}")
    try:
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(obj, fh, indent=1, default=str)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def collect(led, state: dict) -> tuple[list[dict], dict]:
    """Breaker rows, and for each probing lane its finished runs requested after the probe release."""
    rows = [
        dict(r)
        | {
            "open": BP.parse_ts(r["opened_at"]) is not None
            and (not r["released_at"] or str(r["released_at"]) < str(r["opened_at"]))
        }
        for r in led._conn.execute("SELECT lane_id, opened_at, consecutive, released_at, released_by FROM breakers")
    ]
    runs: dict[str, list[dict]] = {}
    for lane, st in state.items():
        since = st.get("probing_since")
        if since:
            runs[lane] = [
                dict(r)
                for r in led._conn.execute(
                    "SELECT run_id, slot_key, state, finished_at FROM runs WHERE lane_id = ? AND requested_at >= ?"
                    " ORDER BY requested_at",
                    (lane, since),
                )
            ]
    return rows, runs


def lane_stages() -> dict[str, str] | None:
    """lane -> scheduler stage from the lane registry (live canary lanes are never probed)."""
    try:
        reg = json.loads((PROJECT_ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None  # fail closed: without the registry no canary can be told apart, so nothing is probed
    return {
        str(r.get("lane_id")): str((r.get("scheduler") or {}).get("stage") or "")
        for r in reg.get("lanes") or []
        if (r.get("scheduler") or {}).get("stage")
    }


def read_holds(path: Path) -> list[str] | None:
    """The operator hold marker {lane: reason}. Absent = no holds; present but unreadable = None (fail closed: the
    prober then starts no probe at all, review round 2)."""
    if not path.exists():
        return []
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return list(doc) if isinstance(doc, dict) else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--config", default=str(CONFIG_PATH))
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    cfg = load_config(a.config)
    root = state_root()
    ledger_path = root / cfg["ledger_rel"]
    apply = bool(a.apply) and not a.dry_run and bool(cfg.get("enabled"))
    now = datetime.now(timezone.utc)
    if not ledger_path.is_file():
        print(json.dumps({"ok": False, "why": f"no ledger at {ledger_path}"}))
        return 2
    from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerRunStore

    led = CoordinationLedger(ledger_path, read_only=not apply)
    state_p, rec_p = root / cfg["state_rel"], root / cfg["receipts_rel"]
    state = _read_json(state_p, {})
    breakers, runs = collect(led, state)
    holds = read_holds(root / cfg["holds_rel"])
    acts = BP.decide(breakers, runs, state, cfg, now, holds=holds, stages=lane_stages())
    errors: list[str] = []

    def _receipt(act: dict, error: str | None = None) -> None:
        rec_p.parent.mkdir(parents=True, exist_ok=True)
        with rec_p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(BP.receipt(act, now, applied=error is None, error=error), default=str) + "\n")

    if apply:
        store = LedgerRunStore(led)
        for act in acts:
            kind = act["action"]
            if kind not in ("probe", "gate", "pass", "fail", "timeout", "exhausted", "yield"):
                continue
            new_state = BP.next_state(state, act, now)
            if kind == "probe":  # write-ahead: a crash after the release still knows the lane is probing
                _atomic(state_p, new_state)
            try:
                if kind == "probe":
                    store.release_breaker(act["lane"], cfg["released_by"], now.timestamp())
                elif kind == "gate":  # the probe slot was requested: close the gate so no second slot runs
                    store.open_breaker(act["lane"], int(act.get("consecutive") or 1), now.timestamp())
                    row = store.breaker(act["lane"]) or {}
                    new_state = BP.next_state(state, act, now, gate_opened_at=row.get("opened_at"))
                elif kind == "pass" and act.get("gated"):  # the one slot passed: open the lane for good
                    store.release_breaker(act["lane"], cfg["released_by"], now.timestamp())
                elif kind in ("fail", "timeout") and not act.get("gated"):
                    store.open_breaker(act["lane"], int(act.get("consecutive") or 1), now.timestamp())
            except Exception as exc:  # noqa: BLE001 — receipted and returned, never swallowed
                err = f"{act['lane']}: {type(exc).__name__}: {exc}"
                errors.append(err)
                act["error"] = err
                _receipt(act, err)
                if kind == "probe":  # roll the write-ahead back: the breaker was not released
                    _atomic(state_p, state)
                continue
            _receipt(act)
            state = new_state
        _atomic(state_p, state)
        msg = BP.render(acts)
        if msg:
            try:
                from telegram_alert import send_telegram

                if not send_telegram(
                    msg,
                    priority=cfg["alert_priority"],
                    dedupe_minutes=0,
                    producer=cfg["producer"],
                    message_class=cfg["message_class"],
                ):
                    errors.append("send_telegram returned falsy")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"send: {type(exc).__name__}: {exc}")
    out = {
        "mode": "apply" if apply else "dry_run",
        "enabled": bool(cfg.get("enabled")),
        "at": now.isoformat(),
        "actions": acts,
        "errors": errors,
    }
    if a.json:
        print(json.dumps(out, indent=1, default=str))
    else:
        print(f"[breaker-probe] {out['at']} mode={out['mode']} enabled={out['enabled']}")
        for act in acts:
            print(
                f"  {act['lane']:<40} {act['action']:<9} probes={act.get('probes')} "
                f"{('open ' + str(act['open_hours']) + 'h') if act.get('open_hours') else ''}"
            )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
