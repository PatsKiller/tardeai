"""Per-lane guaranteed floors inside the shared daily LLM budget.

Why this exists
---------------
The global daily cap is one undifferentiated pool, claimed first-come
first-served. Measured on the live host on 2026-09-11 (ET day):

    advisory_desk_opinion     1019 calls   $0.83435
    hermes_external_research   164 calls   $0.30519
    watchlist_cio_synthesis      4 calls   $0.00518
    watchlist_maria_narrative    34 calls  $0.00159
    advisory_desk_synthesis       1 call   $0.00020
                                           -------
                                           $1.14651   against a $1.50 cap

From 20:00Z onward every hourly L3 judgment refused `budget_cap` and the
governed research producer refused `BUDGET_REFUSED:CALLER_DAILY_CAP`, so the
two lanes the maturity ladder is built on were starved by a high-frequency
advisory lane that had already spent its own process cap's worth. The per
process caps do not prevent this: they sum to $15.48 against a $1.50 global
pool, a 10x oversubscription, so they constrain nobody and the pool is a race.

What a floor is, and is not
---------------------------
A floor is budget that OTHER lanes may not consume. It is not an entitlement
to spend: a lane still obeys its own process cap and the global cap. Holding
a floor for lane L means every other lane's available headroom is reduced by
whatever part of L's floor L has not yet used.

    available_to(P) = global_cap
                    - spent_globally
                    - sum over L != P of max(0, floor(L) - spent(L))

So an unused floor withholds budget, a fully-consumed floor withholds nothing,
and a lane with no floor is exactly as constrained as it is today. With no
floors configured this module changes no behaviour at all, which is the
rollback: empty the config.

Floors are deliberately NOT a priority scheme. Nothing here can let a lane
exceed the global cap, and nothing here can raise a process cap. Reserving
more than the global cap in total is a configuration error, refused loudly
rather than silently rescaled -- a silently rescaled floor is a floor nobody
can reason about.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping

#: Default location; override with TRADEAI_LLM_LANE_FLOORS_PATH.
DEFAULT_FLOORS_PATH = "config/llm_lane_floors.json"

SCHEMA = "LlmLaneFloors@v1"


class LaneFloorConfigError(RuntimeError):
    """Configuration is unusable. Never downgraded to 'no floors'."""


def floors_path(env: Mapping[str, str] | None = None) -> Path:
    e = env if env is not None else os.environ
    return Path(str(e.get("TRADEAI_LLM_LANE_FLOORS_PATH") or DEFAULT_FLOORS_PATH))


def load_lane_floors(
    path: str | Path | None = None, *, env: Mapping[str, str] | None = None
) -> dict[str, float]:
    """Return {process_id: floor_usd}. Absent file means no floors, which is
    the shipped default and a legitimate state -- unlike a malformed file."""
    p = Path(path) if path is not None else floors_path(env)
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise LaneFloorConfigError(f"lane_floors_unreadable:{exc}") from exc
    if not isinstance(raw, Mapping):
        raise LaneFloorConfigError("lane_floors_not_object")
    if str(raw.get("schema") or "") != SCHEMA:
        raise LaneFloorConfigError(f"lane_floors_schema_mismatch:{raw.get('schema')!r}")
    floors_raw = raw.get("floors")
    if not isinstance(floors_raw, Mapping):
        raise LaneFloorConfigError("lane_floors_missing_floors_object")
    out: dict[str, float] = {}
    for key, value in floors_raw.items():
        pid = str(key).strip()
        if not pid:
            raise LaneFloorConfigError("lane_floors_empty_process_id")
        try:
            amount = float(value)
        except (TypeError, ValueError) as exc:
            raise LaneFloorConfigError(f"lane_floor_not_numeric:{pid}") from exc
        if amount < 0:
            raise LaneFloorConfigError(f"lane_floor_negative:{pid}")
        # A zero floor is meaningless but harmless; drop it so it cannot be
        # mistaken for "reserved nothing on purpose" versus "not configured".
        if amount > 0:
            out[pid] = amount
    return out


def withheld_for_other_lanes(
    *,
    process_id: str,
    floors: Mapping[str, float],
    spent_by_lane: Callable[[str], float],
) -> float:
    """Budget that other lanes' unconsumed floors keep out of P's reach."""
    total = 0.0
    for lane, floor in floors.items():
        if lane == process_id:
            continue
        remaining = float(floor) - float(spent_by_lane(lane) or 0.0)
        if remaining > 0:
            total += remaining
    return total


def validate_floors_against_cap(floors: Mapping[str, float], global_cap: float) -> None:
    """Refuse a configuration that reserves more than exists.

    Silently clamping would produce floors that do not hold, which is worse
    than no floors: an operator would read the config and believe a lane was
    protected when it was not.
    """
    total = sum(float(v) for v in floors.values())
    if total > float(global_cap):
        raise LaneFloorConfigError(
            f"lane_floors_exceed_global_cap: reserved={total:.4f} global_cap={float(global_cap):.4f}"
        )


def available_under_global_cap(
    *,
    process_id: str,
    global_cap: float,
    spent_globally: float,
    floors: Mapping[str, float],
    spent_by_lane: Callable[[str], float],
) -> float:
    """Headroom this lane may still claim from the shared pool.

    Returns a non-negative number. Callers compare their projected spend
    against it; they must NOT treat it as an allowance to ignore the process
    cap, which is enforced separately and first.
    """
    if not floors:
        return max(0.0, float(global_cap) - float(spent_globally))
    validate_floors_against_cap(floors, global_cap)
    withheld = withheld_for_other_lanes(
        process_id=process_id, floors=floors, spent_by_lane=spent_by_lane
    )
    return max(0.0, float(global_cap) - float(spent_globally) - withheld)


def explain(
    *,
    process_id: str,
    global_cap: float,
    spent_globally: float,
    floors: Mapping[str, float],
    spent_by_lane: Callable[[str], float],
) -> dict[str, Any]:
    """Structured reason, for the durable refusal record.

    A refusal that says only 'budget_cap' cannot be told apart from a refusal
    caused by another lane's protected floor, and those call for opposite
    operator responses.
    """
    withheld = (
        withheld_for_other_lanes(
            process_id=process_id, floors=floors, spent_by_lane=spent_by_lane
        )
        if floors
        else 0.0
    )
    own_floor = float(floors.get(process_id, 0.0)) if floors else 0.0
    own_spent = float(spent_by_lane(process_id) or 0.0)
    return {
        "process_id": process_id,
        "global_cap_usd": float(global_cap),
        "spent_globally_usd": float(spent_globally),
        "withheld_by_other_lane_floors_usd": withheld,
        "available_usd": max(0.0, float(global_cap) - float(spent_globally) - withheld),
        "own_floor_usd": own_floor,
        "own_floor_remaining_usd": max(0.0, own_floor - own_spent),
        "floors_configured": sorted(floors.keys()) if floors else [],
    }
