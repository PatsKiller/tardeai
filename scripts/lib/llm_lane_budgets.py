"""Per-lane request budgets for in-process cloud generation.

Why this exists
---------------
Every call site used to carry its own literal timeout (25/30/40/60/70/200 s in
``scripts/``). Those numbers were chosen once, by hand, and never compared with
the measured tail of the lane they wait on, so a busy-but-healthy lane is cut by
its caller's patience and the loss is recorded as a lane failure. Measured on
the live host on 2026-11-08 (7 days, ``llm_consumption_log``):

    topic_curator               361 cuts    p95 28.4 s   max ok 39.9 s   (call sites 30 and 40)
    topic_ingestion              64 cuts    p95 20.5 s   max ok 25.0 s   (call sites 25 and 30)
    topic_research_synthesizer   17 cuts    p95 53.7 s   max ok 69.4 s   (call site 70)

The ``topic_curator`` 30 s site sat *below* the lane's own p95: 59 calls in 7
days succeeded after more than 30 s, and every call that needed more was cut.

What a budget is, and is not
----------------------------
A budget is how long a caller waits for an answer. It is not a process cap, a
spend authorization, a provider preference or a routing decision: raising it
changes no policy, lets no call happen that the router would otherwise refuse,
and costs nothing on a call that answers (the wait ends when the answer does).
It only changes whether a slow-but-successful call is recorded as a success or
lost. Lowering a budget never saves money; it discards work already paid for.

Derivation (config drives; this module never guesses)
-----------------------------------------------------
``config/llm_lane_budgets.json`` carries the measurement per lane, and the
budget is re-derivable from it alone::

    budget_s = min(cap_s, ceil_to_5s(max(p95_ms / 1000 * (1 + margin), max_ok_ms / 1000)))

Only *successful* rows measure the tail: a row cut at the old budget is censored
at that budget and would make the tail look shorter than it is. The cap exists
because a caller budget longer than the upstream's own timeout only lengthens a
wait that is already failing (the grok proxy gives its hermes child 240 s; the
proxy path is capped at 120 s, the same value LQ-750 adopted for the keepalive
probe).

Composition with LQ-750 (fold step 30)
--------------------------------------
LQ-750 sized the *keepalive probe's* budget for the same signature -- a caller
timeout below the lane's own tail -- and this module uses the same 120 s cap and
the same "measure the successful tail" rule, so the two do not disagree on
policy. They touch different call paths on purpose: ``oauth_lane_keepalive.py``
probes, it does not generate, and this module never reaches the probe.

Rollback is the config: absent file or absent lane row means the caller's
fallback (90 s, the historical default). A *malformed* file raises -- a budget
nobody can read is worse than the default, and a silent downgrade would hide it.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, Mapping

#: Default location; override with TRADEAI_LLM_LANE_BUDGETS_PATH.
DEFAULT_BUDGETS_PATH = "config/llm_lane_budgets.json"

SCHEMA = "LlmLaneBudgets@v1"

#: The historical ``generate_cloud`` default, kept as the no-config fallback on purpose: with no
#: config file this module changes no behaviour at all.
DEFAULT_FALLBACK_S = 90.0

#: Hard cap on a resolved budget, independent of the file, so a bad edit cannot buy an
#: hour-long wait. The file may lower it; it may not raise it past this.
MAX_BUDGET_S = 120.0

_GRANULARITY_S = 5.0


class LlmLaneBudgetConfigError(RuntimeError):
    """Configuration is unusable. Never downgraded to a silent fallback."""


def budgets_path(env: Mapping[str, str] | None = None) -> Path:
    e = env if env is not None else os.environ
    return Path(str(e.get("TRADEAI_LLM_LANE_BUDGETS_PATH") or DEFAULT_BUDGETS_PATH))


def ceil_to_5s(seconds: float) -> float:
    """Round a positive budget up to the next 5 s step, so the numbers stay human.

    ``budget_s = min(cap_s, ceil_to_5s(max(p95_ms / 1000 * (1 + margin), max_ok_ms / 1000)))``
    """
    if not math.isfinite(seconds) or seconds <= 0:
        raise LlmLaneBudgetConfigError(f"lane_budgets_nonpositive:{seconds!r}")
    return float(math.ceil(round(seconds / _GRANULARITY_S, 9)) * _GRANULARITY_S)


def derive_budget_s(
    p95_ms: float, max_ok_ms: float, *, margin: float, cap_s: float = MAX_BUDGET_S
) -> float:
    """Re-derive one lane's budget from its measurement. Pure; no I/O."""
    for name, value in (("p95_ms", p95_ms), ("max_ok_ms", max_ok_ms), ("margin", margin), ("cap_s", cap_s)):
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
            raise LlmLaneBudgetConfigError(f"lane_budgets_bad_number:{name}")
    if p95_ms <= 0 or max_ok_ms <= 0 or margin < 0 or cap_s <= 0:
        raise LlmLaneBudgetConfigError(f"lane_budgets_bad_range:{p95_ms},{max_ok_ms},{margin},{cap_s}")
    target = max(p95_ms / 1000.0 * (1.0 + margin), max_ok_ms / 1000.0)
    return min(float(cap_s), ceil_to_5s(target))


def _require_number(raw: Mapping[str, Any], key: str, where: str) -> float:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise LlmLaneBudgetConfigError(f"lane_budgets_bad_field:{where}.{key}")
    return float(value)


def load_lane_budgets(
    path: str | Path | None = None, *, env: Mapping[str, str] | None = None
) -> dict[str, float]:
    """Return ``{process_id: budget_s}``. An absent file means "no overrides", which is a
    legitimate state -- unlike a malformed file, which raises."""
    p = Path(path) if path is not None else budgets_path(env)
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text())
    except (OSError, ValueError) as exc:
        raise LlmLaneBudgetConfigError(f"lane_budgets_unreadable:{exc}") from exc
    if not isinstance(raw, Mapping):
        raise LlmLaneBudgetConfigError("lane_budgets_not_an_object")
    if raw.get("schema") != SCHEMA:
        raise LlmLaneBudgetConfigError(f"lane_budgets_schema:{raw.get('schema')!r}!={SCHEMA!r}")
    cap_s = _require_number(raw, "cap_s", "budgets")
    if cap_s > MAX_BUDGET_S:
        raise LlmLaneBudgetConfigError(f"lane_budgets_cap_too_high:{cap_s}>{MAX_BUDGET_S}")
    _require_number(raw, "margin", "budgets")
    _require_number(raw, "fallback_s", "budgets")
    lanes = raw.get("lanes")
    if not isinstance(lanes, Mapping):
        raise LlmLaneBudgetConfigError("lane_budgets_lanes_missing")
    out: dict[str, float] = {}
    for lane_id, row in lanes.items():
        name = str(lane_id).strip()
        if not name or not isinstance(row, Mapping):
            raise LlmLaneBudgetConfigError(f"lane_budgets_bad_lane:{lane_id!r}")
        budget = _require_number(row, "budget_s", name)
        if budget <= 0:
            raise LlmLaneBudgetConfigError(f"lane_budgets_bad_budget:{name}")
        if budget > cap_s:
            raise LlmLaneBudgetConfigError(f"lane_budgets_over_cap:{name}:{budget}>{cap_s}")
        out[name] = budget
    return out


def budget_s(
    process_id: str,
    *,
    path: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    fallback: float | None = None,
) -> float:
    """Resolve the request budget, in seconds, for ``process_id``.

    ``fallback`` (default 90 s) applies when the config has no row for the lane. It is never
    below zero and never above ``MAX_BUDGET_S``.
    """
    lane = str(process_id or "").strip()
    if not lane:
        raise LlmLaneBudgetConfigError("lane_budgets_empty_process_id")
    resolved = load_lane_budgets(path, env=env).get(lane)
    if resolved is not None:
        return resolved
    base = DEFAULT_FALLBACK_S if fallback is None else float(fallback)
    if not math.isfinite(base) or base <= 0:
        raise LlmLaneBudgetConfigError(f"lane_budgets_bad_fallback:{fallback!r}")
    return min(MAX_BUDGET_S, base)


def _main(argv: list[str] | None = None) -> int:
    import sys

    args = list(sys.argv[1:] if argv is None else argv)
    if args not in ([], ["--report"]):
        print("usage: llm_lane_budgets.py [--report]", file=sys.stderr)
        return 2
    path = budgets_path()
    try:
        raw = json.loads(Path(path).read_text())
        margin = float(raw["margin"])
        cap_s = float(raw["cap_s"])
        rows = raw["lanes"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"unreadable: {exc}", file=sys.stderr)
        return 1
    print(f"{'lane':28} {'p95_s':>7} {'max_ok_s':>9} {'derived_s':>10} {'config_s':>9}  state")
    bad = 0
    for name in sorted(rows):
        row = rows[name]
        derived = derive_budget_s(float(row["p95_ms"]), float(row["max_ok_ms"]), margin=margin, cap_s=cap_s)
        shipped = float(row["budget_s"])
        state = "ok" if derived == shipped else "DRIFT"
        bad += state == "DRIFT"
        print(
            f"{name:28} {row['p95_ms'] / 1000.0:7.2f} {row['max_ok_ms'] / 1000.0:9.2f}"
            f" {derived:10.1f} {shipped:9.1f}  {state}"
        )
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(_main())
