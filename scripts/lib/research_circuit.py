"""Research backend circuit breaker.

READ_ONLY_ADVISORY. Stops hammering an unhealthy local provider.
Does not drop durable requests — only refuses to start new backend calls.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
STATES = ("CLOSED", "OPEN", "HALF_OPEN")


def _path() -> Path:
    env = os.environ.get("TRADEAI_CIO_DIR")
    root = Path(env) if env else Path(__file__).resolve().parents[2] / "data" / "cio"
    return root / "research_circuit.json"


def load() -> dict[str, Any]:
    p = _path()
    if not p.is_file():
        return {
            "schema": "ResearchCircuit@v1",
            "state": "CLOSED",
            "failures": 0,
            "successes": 0,
            "opened_at": None,
            "cooldown_s": 600,
            "fail_threshold": 3,
            "authority": AUTHORITY,
        }
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return load() if False else {
            "schema": "ResearchCircuit@v1", "state": "CLOSED", "failures": 0,
            "successes": 0, "authority": AUTHORITY, "cooldown_s": 600, "fail_threshold": 3,
        }


def _save(rec: dict[str, Any]) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(rec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, p)


def allow_call() -> tuple[bool, str]:
    rec = load()
    state = rec.get("state") or "CLOSED"
    if state == "CLOSED":
        return True, "closed"
    if state == "OPEN":
        opened = float(rec.get("opened_at") or 0)
        cool = float(rec.get("cooldown_s") or 600)
        if time.time() - opened >= cool:
            rec["state"] = "HALF_OPEN"
            _save(rec)
            return True, "half_open_probe"
        return False, "open_cooldown"
    return True, "half_open"


def record_success() -> dict[str, Any]:
    rec = load()
    rec["successes"] = int(rec.get("successes") or 0) + 1
    rec["failures"] = 0
    rec["state"] = "CLOSED"
    rec["last_success_at"] = time.time()
    _save(rec)
    return rec


def record_failure(reason: str = "") -> dict[str, Any]:
    rec = load()
    rec["failures"] = int(rec.get("failures") or 0) + 1
    rec["last_failure_at"] = time.time()
    rec["last_failure_reason"] = reason[:200]
    thresh = int(rec.get("fail_threshold") or 3)
    if rec["failures"] >= thresh:
        rec["state"] = "OPEN"
        rec["opened_at"] = time.time()
    _save(rec)
    return rec
