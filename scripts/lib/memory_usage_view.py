"""Memory usage view for the Command Center Memory panel (LQ-20261107-1819).

Reads real retrieval use (memory_consumption_receipts.jsonl, retrieval_receipts.jsonl), bounded,
fail closed: a missing/unreadable source reports status "unreadable" with a reason, never a count of 0.
Each source carries path, mtime, newest receipt time and age. Malformed rows and future-dated rows are
counted, not used. Window / row cap / skew come from config/memory_usage_view.json (env overrides).
READ_ONLY_ADVISORY. Never calls a provider, never writes.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from scripts.lib.jsonl_bounded import tail_jsonl_lines
from scripts.lib.memory_consumption_receipt import SCHEMA as CONSUMPTION_SCHEMA, summarize

RETRIEVAL_SCHEMA = "RetrievalReceipt@v1"
_CFG = Path(__file__).resolve().parents[2] / "config" / "memory_usage_view.json"
_DEFAULTS = {"window_hours": 24, "max_rows": 20000, "future_skew_seconds": 300}


def load_config(env: dict | None = None) -> dict[str, int]:
    env = os.environ if env is None else env
    cfg = dict(_DEFAULTS)
    try:
        raw = json.loads(_CFG.read_text(encoding="utf-8"))
        for k in cfg:
            if isinstance(raw.get(k), (int, float)) and raw[k] > 0:
                cfg[k] = int(raw[k])
    except (OSError, ValueError):
        pass
    for k, e in (("window_hours", "TRADEAI_MEMORY_USAGE_HOURS"), ("max_rows", "TRADEAI_MEMORY_USAGE_MAX_ROWS"),
                 ("future_skew_seconds", "TRADEAI_MEMORY_USAGE_SKEW_S")):
        try:
            v = int(env.get(e) or 0)
            if v > 0:
                cfg[k] = v
        except ValueError:
            pass
    return cfg


def _parse(ts: Any) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _read_source(path: Path, stamp: str, schema: str, now: datetime, cfg: dict) -> dict[str, Any]:
    """{status OK|UNREADABLE, rows, + integrity counters}. Opens the file first so OSError is not swallowed."""
    src: dict[str, Any] = {"file": path.name, "path": str(path)}
    try:
        st = path.stat()
        with path.open("rb") as fh:
            fh.read(1)
    except OSError as exc:
        src.update(status="UNREADABLE", reason=f"{type(exc).__name__}: {exc.strerror or exc}", rows=[])
        return src
    since = now - timedelta(hours=cfg["window_hours"])
    upper = now + timedelta(seconds=cfg["future_skew_seconds"])
    lines = tail_jsonl_lines(path, cfg["max_rows"])
    rows, malformed, future, newest, oldest_read = [], 0, 0, None, None
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            malformed += 1
            continue
        if not isinstance(r, dict) or r.get("schema") != schema:
            malformed += 1
            continue
        t = _parse(r.get(stamp))
        if t is None:
            malformed += 1
            continue
        if t > upper:
            future += 1
            continue
        oldest_read = t if oldest_read is None or t < oldest_read else oldest_read
        newest = t if newest is None or t > newest else newest
        if t >= since:
            rows.append(r)
    src.update(
        status="OK", rows=rows, malformed=malformed, future_dated=future,
        mtime=datetime.fromtimestamp(st.st_mtime, timezone.utc).replace(microsecond=0).isoformat(),
        newest_receipt_at=newest.replace(microsecond=0).isoformat() if newest else None,
        age_s=int((now - newest).total_seconds()) if newest else None,
        # the tail ended while still inside the window -> older in-window rows may exist unread
        truncated=bool(len(lines) >= cfg["max_rows"] and oldest_read is not None and oldest_read >= since),
        rows_read=len(lines),
    )
    return src


def _public(src: dict[str, Any], **extra: Any) -> dict[str, Any]:
    out = {k: v for k, v in src.items() if k != "rows"}
    out.update(extra)
    return out


def usage_window(cio_dir: Path | str, *, now: datetime | None = None, env: dict | None = None) -> dict[str, Any]:
    cio = Path(cio_dir)
    now = now or datetime.now(timezone.utc)
    cfg = load_config(env)
    cons = _read_source(cio / "memory_consumption_receipts.jsonl", "consumed_at", CONSUMPTION_SCHEMA, now, cfg)
    lad = _read_source(cio / "retrieval_receipts.jsonl", "created_at", RETRIEVAL_SCHEMA, now, cfg)
    out: dict[str, Any] = {
        "window_hours": cfg["window_hours"], "max_rows": cfg["max_rows"], "future_skew_seconds": cfg["future_skew_seconds"],
        "as_of": now.replace(microsecond=0).isoformat(), "memory_behavior_influence": "0",
        "order_assumption": "tail read assumes newest rows are last in file; non-monotonic files can hide older in-window rows",
    }
    problems = []
    if cons["status"] == "OK":
        rows = cons["rows"]
        ids: set[str] = set()
        for r in rows:
            for k in ("memory_ids_supporting", "memory_ids_counter"):
                v = r.get(k)
                ids.update(str(i) for i in v) if isinstance(v, list) else None
        s = summarize(rows)
        out["consumption"] = _public(cons, receipts=len(rows), by_consumer=s["by_consumer"], distinct_memory_ids=len(ids))
        out["consumption_receipts"] = len(rows)
        out["by_consumer"] = s["by_consumer"]
        out["distinct_memory_ids"] = len(ids)
    else:
        out["consumption"] = _public(cons)
        out["consumption_receipts"] = None
        problems.append(f"{cons['file']}: {cons['reason']}")
    if lad["status"] == "OK":
        decisions: dict[str, int] = {}
        used = 0
        bad = 0
        for r in lad["rows"]:
            decisions[str(r.get("decision"))] = decisions.get(str(r.get("decision")), 0) + 1
            es = r.get("evidence_stages")
            refs = es.get("used_refs") if isinstance(es, dict) else None
            if isinstance(refs, list):
                used += len(refs)
            elif es is not None:
                bad += 1
        lad["malformed"] += bad
        out["ladder"] = _public(lad, receipts=len(lad["rows"]), decisions=decisions, used_refs=used)
        out["ladder_receipts"] = len(lad["rows"])
        out["ladder_decisions"] = decisions
        out["ladder_used_refs"] = used
    else:
        out["ladder"] = _public(lad)
        out["ladder_receipts"] = None
        out["ladder_used_refs"] = None
        problems.append(f"{lad['file']}: {lad['reason']}")
    out["error"] = "cannot be read: " + "; ".join(problems) if problems else None
    return out
