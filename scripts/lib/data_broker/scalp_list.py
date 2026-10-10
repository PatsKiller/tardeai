"""Scalp List — Data Broker read model over the shared scalp universe (market data only).

Operator decision 2026-10-10 ~17:45 ET (CONSOLIDATION_PLAN.md §D.5): register the ``scalp_list``
domain. Store ``data/trade_ai/scalp_universe_latest.json`` (``TradeAIScalpUniverse@v1``) under the
canonical state root; single writer ``scripts/run_trade_ai_scalp_live.py`` (``write_projection``,
temp file + ``replace``), cron */5 09:30-16:00 on market days. The 06:00-09:30 hot tier (§D.4) was
not adopted, so this projection describes only what that lane writes today.

What a consumer gets: screener membership and the per-symbol market fields (price, float, setup
class), with ``as_of`` / ``age_hours`` / ``stale`` and a ``BrokerReadEnvelope@v1``. The lane's own
GO/score columns are deliberately NOT passed through: this is the market-data read path, not the
scalp lane's decision record, and nothing reading it sizes, orders or stops.

Zero provider calls. Read-only: it never creates a directory or writes a file. The writer lane
(§23.3 ``trade-ai-scalp-live``) is untouched.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lib.data_broker.envelope import envelope

DOMAIN = "scalp_list"
PROJECTION = "scalp_list"
STORE_REL = "data/trade_ai/scalp_universe_latest.json"
WRITER = "scripts/run_trade_ai_scalp_live.py"
SCHEMA_EXPECTED = "TradeAIScalpUniverse@v1"
#: the per-row fields a consumer may read (market data; the lane's decision/score stay with the lane)
MARKET_FIELDS = ("symbol", "price", "float_m", "setup_class")


def _state_root(root: Path | str | None) -> Path:
    if root:
        return Path(root)
    try:
        from scripts.lib.canonical_store_registry import production_state_root  # type: ignore
    except Exception:  # noqa: BLE001
        try:
            from lib.canonical_store_registry import production_state_root  # type: ignore
        except Exception:  # noqa: BLE001
            return Path(__file__).resolve().parents[3]
    return Path(production_state_root())


def _as_utc(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.astimezone()  # naive -> host-local, as the writer's now() would be
    return dt.astimezone(timezone.utc)


def read_universe(root: Path | str | None = None) -> dict[str, Any]:
    """The raw file as a dict, read-only. Missing, unreadable or wrong schema -> {}."""
    path = _state_root(root) / STORE_REL
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("schema") != SCHEMA_EXPECTED:
        return {}
    return data


def get_scalp_list(
    *,
    root: Path | str | None = None,
    now: datetime | None = None,
    market_closed: bool | None = None,
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The current scalp universe with freshness.

    Returns ``{"ok", "provider_calls": 0, "symbols": [SYM...], "rows": [{symbol, price, float_m,
    setup_class}], "run_label", <BrokerReadEnvelope@v1>}``. The registry window applies
    (``stale_after_hours``; ``stale_after_hours_closed`` when ``market_closed``). An absent file is
    ``gap.kind = no_coverage`` with the declared ``say_so``.
    """
    ref = now or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    data = snapshot if snapshot is not None else read_universe(root)
    rows_in = data.get("rows") if isinstance(data.get("rows"), list) else []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for r in rows_in:
        if not isinstance(r, dict):
            continue
        sym = str(r.get("symbol") or "").upper().strip()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        row = {k: r.get(k) for k in MARKET_FIELDS}
        row["symbol"] = sym
        rows.append(row)
    as_of = _as_utc(data.get("as_of"))
    out: dict[str, Any] = {
        "ok": bool(data),
        "provider_calls": 0,
        "symbols": [r["symbol"] for r in rows],
        "rows": rows,
        "run_label": data.get("run_label"),
    }
    out.update(
        envelope(
            DOMAIN,
            as_of,
            now=ref,
            market_closed=market_closed,
            source={"file": STORE_REL, "writer": WRITER, "projection": PROJECTION},
        )
    )
    return out
