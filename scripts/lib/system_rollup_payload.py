"""Bounded payloads for the nightly system rollup (system_rollup_daily).

Storage audit 2026-10-09 (#5): the Reports `trends` panel embedded the FULL payload of the
last 14 system_rollup_daily rows, and the nightly snapshot stored every panel including
`trends`. Each day's row therefore nested the previous days' rows and doubled in size
(3.9 KB on 07-17, 39 MB compressed on 07-31). From 2026-08-01 every INSERT failed with
ProgramLimitExceeded (jsonb > 256 MB): no rollup row, no Daily System Digest, no ai_reports
row, no Telegram line, for ~70 days, and Postgres logged the ~230 MB statement every night.

Rules enforced here (pure, no DB, no network):
  * history carries COMPACT per-day summaries only: scalar headline values, never a payload;
  * the stored payload never contains the `trends` panel (it is derived from stored rows);
  * the serialized payload has a hard byte cap; exceeding it raises a typed refusal.
"""

from __future__ import annotations

import json
import os
from decimal import Decimal
from typing import Any, Iterable, Mapping

SCHEMA = "SystemRollupDaily@v2"
REFUSAL_CODE = "ROLLUP_PAYLOAD_TOO_LARGE"

# Panels never stored: they are projections of system_rollup_daily itself. Storing them is
# what made the payload recursive.
EXCLUDED_PANELS = ("trends",)

# Headline keys the Reports sparklines and the digest read (system_rollup_snapshot._headlines).
HEADLINE_KEYS = (
    "pipelines_run",
    "pipeline_failures",
    "agent_analyses",
    "proposals",
    "paper_closed",
    "paper_pnl",
    "alerts_raw",
    "research_items",
    "reports_generated",
    "directive_hits",
    "health_score",
)

MAX_PAYLOAD_ENV = "TRADEAI_SYSTEM_ROLLUP_MAX_PAYLOAD_BYTES"
# 1 MiB: two orders of magnitude above a healthy day's payload, two below the 256 MB jsonb limit.
DEFAULT_MAX_PAYLOAD_BYTES = 1_048_576
_MAX_TEXT = 64


class RollupPayloadRefused(RuntimeError):
    """Typed refusal: the serialized rollup payload exceeds the configured byte cap."""

    code = REFUSAL_CODE

    def __init__(self, payload_bytes: int, cap_bytes: int, largest_panels: list[tuple[str, int]]):
        self.payload_bytes = int(payload_bytes)
        self.cap_bytes = int(cap_bytes)
        self.largest_panels = list(largest_panels)
        super().__init__(
            f"{REFUSAL_CODE}: payload {self.payload_bytes} B > cap {self.cap_bytes} B "
            f"(largest panels: {self.largest_panels})"
        )

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "payload_bytes": self.payload_bytes,
            "cap_bytes": self.cap_bytes,
            "largest_panels": [{"panel": n, "bytes": b} for n, b in self.largest_panels],
        }


def max_payload_bytes(env: Mapping[str, str] | None = None) -> int:
    """Byte cap for one stored payload. Env override; a non-positive or bad value uses the default."""
    raw = (env if env is not None else os.environ).get(MAX_PAYLOAD_ENV)
    try:
        val = int(str(raw).strip()) if raw not in (None, "") else DEFAULT_MAX_PAYLOAD_BYTES
    except ValueError:
        return DEFAULT_MAX_PAYLOAD_BYTES
    return val if val > 0 else DEFAULT_MAX_PAYLOAD_BYTES


def _scalar(v: Any) -> Any:
    """A headline value as a JSON scalar. Containers are dropped (None): history never nests."""
    if v is None or isinstance(v, bool):
        return v
    if isinstance(v, int):
        return v
    if isinstance(v, (float, Decimal)):
        f = float(v)
        return int(f) if f.is_integer() and abs(f) < 2**53 else round(f, 4)
    if isinstance(v, (dict, list, tuple, set)):
        return None
    return str(v)[:_MAX_TEXT]


def compact_headlines(headlines: Any) -> dict:
    """Known headline keys only, scalar values only."""
    if isinstance(headlines, str):
        try:
            headlines = json.loads(headlines)
        except ValueError:
            headlines = {}
    if not isinstance(headlines, Mapping):
        headlines = {}
    return {k: _scalar(headlines.get(k)) for k in HEADLINE_KEYS}


def compact_trend_rows(rows: Iterable[Mapping[str, Any]] | None) -> dict:
    """The Reports `trends` panel: one compact summary per stored day.

    Each input row needs `day` and either `headlines` (preferred: the SQL selects
    payload->'headlines') or a legacy `payload` dict. Output keeps the shape the UI reads
    (`rows[].payload.headlines.<key>`) and never carries any other part of a stored payload.
    """
    out = []
    for r in rows or []:
        hl = r.get("headlines") if "headlines" in r else (r.get("payload") or {}).get("headlines")
        out.append({"day": str(r.get("day")), "payload": {"headlines": compact_headlines(hl)}})
    return {"days": len(out), "rows": out, "shape": "headlines_only"}


def build_stored_payload(headlines: Mapping[str, Any], panels: Mapping[str, Any]) -> dict:
    """The row stored in system_rollup_daily: headlines + non-derived panels, no trends."""
    kept = {k: v for k, v in (panels or {}).items() if k not in EXCLUDED_PANELS}
    return {
        "schema": SCHEMA,
        "headlines": compact_headlines(headlines),
        "panels": kept,
        "excluded_panels": list(EXCLUDED_PANELS),
    }


def _dumps(obj: Any) -> str:
    return json.dumps(obj, default=str, separators=(",", ":"))


def serialize_with_cap(payload: Mapping[str, Any], cap_bytes: int | None = None) -> tuple[str, int]:
    """Serialize the payload; raise RollupPayloadRefused when it exceeds the cap."""
    cap = int(cap_bytes) if cap_bytes is not None else max_payload_bytes()
    text = _dumps(payload)
    size = len(text.encode("utf-8"))
    if size > cap:
        panels = payload.get("panels") or {}
        sizes = sorted(
            ((str(n), len(_dumps(p).encode("utf-8"))) for n, p in panels.items()),
            key=lambda t: t[1],
            reverse=True,
        )
        raise RollupPayloadRefused(size, cap, sizes[:5])
    return text, size
