"""Discover and run the category modules of the Market Risk Engine.

Each name in ``contract.CATEGORIES`` maps to ``scripts.lib.market_risk.categories.<name>`` exposing
``evaluate(ctx) -> CategoryObservation``. A module that is missing, raises, or returns the wrong shape yields an
honest ``UNKNOWN`` observation carrying the reason — the evaluation never crashes and never reads a failure as zero.
The failure is also logged so it is visible outside the assessment.
"""

from __future__ import annotations

import importlib
import logging
from typing import Callable

from scripts.lib.market_risk import contract as c

log = logging.getLogger("market_risk.registry")
PACKAGE = "scripts.lib.market_risk.categories"


def load_evaluator(category: str) -> tuple[Callable | None, str | None]:
    try:
        mod = importlib.import_module(f"{PACKAGE}.{category}")
    except ModuleNotFoundError as exc:
        if exc.name == f"{PACKAGE}.{category}":
            return None, "module not built yet"
        return None, f"import failed: {exc!r}"
    except Exception as exc:  # a broken module must not take down the other eight
        log.error("market_risk: importing category %s failed: %r", category, exc)
        return None, f"import failed: {exc!r}"
    fn = getattr(mod, "evaluate", None)
    if not callable(fn):
        return None, "module has no evaluate(ctx)"
    return fn, None


def evaluate_category(category: str, ctx: c.EvalContext, evaluator: Callable | None = None) -> c.CategoryObservation:
    fn, why = (evaluator, None) if evaluator is not None else load_evaluator(category)
    if fn is None:
        return c.unknown(category, ctx.now, why or "no evaluator")
    try:
        obs = fn(ctx)
    except Exception as exc:
        log.error("market_risk: category %s raised: %r", category, exc)
        return c.unknown(category, ctx.now, f"evaluate raised: {exc!r}"[:300])
    if not isinstance(obs, c.CategoryObservation):
        return c.unknown(category, ctx.now, f"evaluate returned {type(obs).__name__}, not CategoryObservation")
    if obs.category != category:
        return c.unknown(category, ctx.now, f"evaluate returned category {obs.category!r}")
    if obs.state not in c.STATES:
        return c.unknown(category, ctx.now, f"invalid state {obs.state!r}")
    if obs.state == "UNKNOWN" and obs.score is not None:
        return c.unknown(category, ctx.now, obs.reason_unknown or "UNKNOWN with a score")
    if obs.state != "UNKNOWN" and (obs.score is None or not 0 <= float(obs.score) <= 100):
        return c.unknown(category, ctx.now, f"score {obs.score!r} outside 0-100")
    c.assert_no_behavior_fields(obs.to_dict())
    return obs


def evaluate_all(ctx: c.EvalContext, evaluators: dict[str, Callable] | None = None) -> list[c.CategoryObservation]:
    """Run all nine categories in contract order. ``evaluators`` overrides discovery (tests, replay)."""
    evaluators = evaluators or {}
    return [evaluate_category(cat, ctx, evaluators.get(cat)) for cat in c.CATEGORIES]
