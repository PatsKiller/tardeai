"""Append-only promotion + lesson-overlay store.

Canonical paths (under project root):
  data/cio/maturity_promotions.jsonl     — every event
  data/cio/maturity_promotions.json      — latest snapshot per promotion_id
  data/cio/maturity_lesson_overlays.json — lesson_id → governed state
  data/cio/maturity_agent_overlays.json  — agent_id → governed advisory state
"""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
from typing import Any, Optional

from scripts.lib.maturity_control.schema import content_hash, utc_now

DEFAULT_REL = Path("data") / "cio"


def resolve_root(root: Path | str | None) -> Path:
    if root:
        return Path(root)
    env = os.environ.get("TRADEAI_ROOT") or os.environ.get("MATURITY_CONTROL_ROOT")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[3]


def paths(root: Path | str | None = None) -> dict[str, Path]:
    base = resolve_root(root) / DEFAULT_REL
    return {
        "events": base / "maturity_promotions.jsonl",
        "snapshot": base / "maturity_promotions.json",
        "lessons": base / "maturity_lesson_overlays.json",
        "agents": base / "maturity_agent_overlays.json",
    }


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def append_event(event: dict[str, Any], *, root: Path | str | None = None) -> dict[str, Any]:
    rec = dict(event)
    rec.setdefault("at", utc_now())
    rec["event_hash"] = content_hash({k: rec[k] for k in rec if k != "event_hash"})
    p = paths(root)["events"]
    p.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(rec, sort_keys=True, default=str, separators=(",", ":")) + "\n"
    with p.open("a", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.write(line)
        fh.flush()
        os.fsync(fh.fileno())
        fcntl.flock(fh, fcntl.LOCK_UN)
    _refresh_snapshot(root)
    return rec


def load_events(*, root: Path | str | None = None) -> list[dict[str, Any]]:
    p = paths(root)["events"]
    if not p.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _refresh_snapshot(root: Path | str | None) -> dict[str, Any]:
    events = load_events(root=root)
    latest: dict[str, dict[str, Any]] = {}
    for ev in events:
        pid = str(ev.get("promotion_id") or "")
        if not pid:
            continue
        if ev.get("kind") in {None, "promotion", "state_change", "preflight", "sign", "activate", "restrict", "rollback"}:
            prev = latest.get(pid) or {}
            merged = dict(prev)
            if ev.get("record"):
                merged.update(ev["record"])
            else:
                for k, v in ev.items():
                    if k not in {"kind", "event_hash", "at"}:
                        merged[k] = v
            latest[pid] = merged
    snap = {
        "at": utc_now(),
        "authority": "READ_ONLY_ADVISORY",
        "auto_promotion_to_trading": False,
        "promotions": latest,
    }
    _atomic_write(paths(root)["snapshot"], json.dumps(snap, indent=2, default=str) + "\n")
    return snap


def load_snapshot(*, root: Path | str | None = None) -> dict[str, Any]:
    p = paths(root)["snapshot"]
    if not p.is_file():
        return {"promotions": {}, "auto_promotion_to_trading": False}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"promotions": {}, "auto_promotion_to_trading": False}
    return data if isinstance(data, dict) else {"promotions": {}}


def get_promotion(promotion_id: str, *, root: Path | str | None = None) -> Optional[dict[str, Any]]:
    return (load_snapshot(root=root).get("promotions") or {}).get(promotion_id)


def load_json_map(kind: str, *, root: Path | str | None = None) -> dict[str, Any]:
    p = paths(root)[kind]
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_json_map(kind: str, data: dict[str, Any], *, root: Path | str | None = None) -> None:
    _atomic_write(paths(root)[kind], json.dumps(data, indent=2, default=str) + "\n")
