"""Discover and run the category modules of the Market Risk Engine.

Each name in ``contract.CATEGORIES`` maps to ``scripts.lib.market_risk.categories.<name>`` exposing
``evaluate(ctx) -> CategoryObservation``. A module that is missing, raises, or returns the wrong shape yields an
honest ``UNKNOWN`` observation carrying the reason — the evaluation never crashes and never reads a failure as zero.
The failure is also logged so it is visible outside the assessment.
"""

from __future__ import annotations

import importlib
import dataclasses
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
        # The same contract module can load under two names (lib.* and scripts.lib.*, scripts/ on sys.path). A
        # structurally identical observation from the other copy is accepted by value; anything else is UNKNOWN.
        if type(obs).__name__ == "CategoryObservation" and dataclasses.is_dataclass(obs):
            obs = _rebuild(obs)
        else:
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
    enrich(ctx)
    return [evaluate_category(cat, ctx, evaluators.get(cat)) for cat in c.CATEGORIES]


def enrich(ctx: c.EvalContext) -> None:
    """Shared inputs several categories need, read once per evaluation through the reader (never a side fetch).
    ``index_weights`` feeds event concentration and AI earnings sensitivity; ``ai_basket`` feeds technical."""
    fn = getattr(ctx.reader, "index_weights", None)
    if "index_weights" not in ctx.extras and callable(fn):
        try:
            ctx.extras["index_weights"] = _covered_weights(ctx, fn)
        except Exception as exc:  # noqa: BLE001 — an unreadable input is reported as not measured, not raised
            log.warning("market_risk: index weights unreadable (%s: %s)", type(exc).__name__, exc)
            ctx.extras["index_weights"] = None
            ctx.extras["index_weights_error"] = f"{type(exc).__name__}"


def _rebuild(obs: object) -> c.CategoryObservation:
    d = dataclasses.asdict(obs)  # type: ignore[arg-type]
    d["evidence"] = tuple(c.Evidence(**e) for e in d.get("evidence") or ())
    return c.CategoryObservation(**d)


def _covered_weights(ctx: c.EvalContext, fn: Callable) -> dict | None:
    """Cap weights over the policy's ``event.index_universe`` (the largest index constituents). Below
    ``event.min_cap_coverage`` of that universe with a known cap, the weights are withheld: an earnings share computed
    from whichever symbols happen to carry a cap is noise (2026-10-31 integration: GSK/RYAAY outranked AAPL/MSFT
    because the mega-caps had no cap on file). Event earnings then read "not measured", never a made-up share."""
    ev = ctx.policy.get("event") or {}
    uni = [str(u).upper() for u in ev.get("index_universe") or []]
    w = fn(end=ctx.now, universe=uni or None)
    if not uni:
        return w
    got = set((w or {}).get("weights") or {})
    cov = len(got & set(uni)) / len(uni)
    floor = float(ev.get("min_cap_coverage", 0.8))
    if w is None or cov < floor:
        missing = sorted(set(uni) - got)
        ctx.extras["index_weights_note"] = (
            f"caps known for {len(got & set(uni))} of {len(uni)} largest constituents (need {floor:.0%}); "
            f"missing {', '.join(missing[:8])}{'…' if len(missing) > 8 else ''}"
        )
        return None
    return dict(w, coverage_share=round(cov, 3), universe_size=len(uni))
