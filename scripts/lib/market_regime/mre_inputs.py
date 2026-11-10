"""Market-wide trend and breadth for the regime classifier, read from the Market Risk Engine (LQ-20261107-1613).

The engine (scripts/market_risk_evaluate.py) observes the market every 15 minutes from market_ohlcv_bars: its
``technical`` category grades index and sector closes against their 20/50/200-day averages, drawdowns and failed
retests; its ``breadth`` category grades sector-SPDR participation, a McClellan proxy and RSP vs SPY. The regime
classifier had no market-wide trend or breadth source and wrote ``not_measured`` for both, so its label followed the
VIX bucket alone. One source of truth (Constitution Rule 14): the collector records the engine's two observations as
``market_regime_indicators`` rows, and the classifier maps and scores them from config/market_regime_classifier.yaml.

An observation that is stale, absent, unreadable or UNKNOWN is written ``not_measured`` with its reason in
``value_text`` and never carries a value (Rule 11: unknown beats wrong).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import yaml

SCHEMA = "MarketRegimeClassifier@v1"
DEFAULT_CONFIG = Path(__file__).resolve().parents[3] / "config" / "market_regime_classifier.yaml"
NOT_MEASURED = "not_measured"
_GROUP = {"technical": "trend", "breadth": "breadth"}


class ConfigError(ValueError):
    pass


def load_config(path: Path | str | None = None) -> dict[str, Any]:
    p = Path(path or DEFAULT_CONFIG)
    try:
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except OSError as exc:
        raise ConfigError(f"{p}: unreadable ({type(exc).__name__}: {exc})") from exc
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        raise ConfigError(f"{p}: schema must be {SCHEMA}, not {doc.get('schema') if isinstance(doc, dict) else doc!r}")
    floor = doc.get("confidence_floor")
    if not isinstance(floor, (int, float)) or floor <= 0:
        raise ConfigError(f"{p}: confidence_floor must be a positive number")
    mre = doc.get("market_risk_engine") or {}
    cats = mre.get("categories")
    if not mre.get("file") or not isinstance(cats, dict) or not cats:
        raise ConfigError(f"{p}: market_risk_engine.file and .categories are required")
    if not isinstance(mre.get("max_age_minutes"), (int, float)) or mre["max_age_minutes"] <= 0:
        raise ConfigError(f"{p}: market_risk_engine.max_age_minutes must be a positive number")
    for key in cats.values():
        st = (doc.get("states") or {}).get(key)
        if not isinstance(st, dict) or not st.get("column") or not isinstance(st.get("map"), dict):
            raise ConfigError(f"{p}: states.{key} needs a column and a map")
        if not isinstance((doc.get("scores") or {}).get(key), dict):
            raise ConfigError(f"{p}: scores.{key} must be a mapping of engine state -> points")
    return doc


def read_engine_snapshot(runtime_dir: Path, cfg: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """The engine's latest snapshot, or (None, reason). Never raises."""
    p = Path(runtime_dir) / cfg["market_risk_engine"]["file"]
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, "file_missing"
    except (OSError, ValueError) as exc:
        return None, f"unreadable:{type(exc).__name__}"
    if not isinstance(doc, dict):
        return None, "unreadable:not_an_object"
    return doc, None


def _parse(ts: Any) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(ts))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else None


def collect(
    engine: dict[str, Any] | None,
    now: datetime,
    cfg: dict[str, Any],
    snapshot_id: str,
    uid: Callable[[], str],
    reason: str | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """One indicator per configured engine category, and the names of every one that is not measured."""
    mre = cfg["market_risk_engine"]
    max_age_s = float(mre["max_age_minutes"]) * 60
    cats = {}
    for c in (engine or {}).get("categories") or []:
        if isinstance(c, dict) and c.get("category"):
            cats[str(c["category"])] = c
    out: list[dict[str, Any]] = []
    missing: list[str] = []
    for cat, key in mre["categories"].items():
        base = {
            "indicator_id": uid(),
            "snapshot_id": snapshot_id,
            "indicator_key": key,
            "indicator_group": _GROUP.get(cat, cat),
            "source_key": f"market_risk_engine:{cat}",
        }
        obs = cats.get(cat)
        why = None
        age_s = None
        if engine is None:
            why = reason or "file_missing"
        elif obs is None:
            why = "no_category"
        else:
            as_of = _parse(obs.get("as_of") or engine.get("as_of"))
            state = str(obs.get("state") or "")
            if as_of is None:
                why = "no_as_of"
            else:
                age_s = max(0.0, (now - as_of).total_seconds())
                if age_s > max_age_s:
                    why = f"stale:{round(age_s / 60)}m"
                elif state not in cfg["states"][key]["map"]:
                    why = f"state:{state or 'missing'}"
        if why:
            out.append({**base, "signal": NOT_MEASURED, "value": None, "value_text": why,
                        "freshness_seconds": round(age_s) if age_s is not None else None,
                        "payload": {"as_of": (obs or {}).get("as_of"), "reason": why}})
            missing.append(f"{key}_{why}" if why.startswith("stale") else f"{key}_not_measured:{why}")
            continue
        out.append({**base, "signal": str(obs["state"]),
                    "value": float(obs["score"]) if isinstance(obs.get("score"), (int, float)) else None,
                    "value_text": str(obs.get("detail") or "")[:300] or None,
                    "freshness_seconds": round(age_s),
                    "payload": {"as_of": obs.get("as_of"), "engine_as_of": engine.get("as_of"),
                                "state": obs.get("state"), "score": obs.get("score")}})
    return out, missing


def apply(
    indicators: dict[str, dict[str, Any]], scores: dict[str, int], cfg: dict[str, Any]
) -> tuple[dict[str, str], list[str]]:
    """Add the engine states' points to ``scores`` (in place) and return ({column: state}, named gaps).

    A configured key with no row is ``no_<key>``; a ``not_measured`` row is ``<key>:<reason>``. Neither scores.
    A configured score label that is not a regime the classifier scores is named ``bad_label:<label>`` rather
    than dropped in silence: a typo in the yaml otherwise moves the label by zero points and says nothing."""
    states: dict[str, str] = {}
    gaps: list[str] = []
    for key in cfg["market_risk_engine"]["categories"].values():
        st = cfg["states"][key]
        ind = indicators.get(key)
        signal = (ind or {}).get("signal")
        if not ind:
            gaps.append(f"no_{key}")
        elif signal not in st["map"]:
            gaps.append(f"{key}:{(ind or {}).get('text') or signal or 'missing'}")
        else:
            states[st["column"]] = st["map"][signal]
            for label, pts in (cfg["scores"][key].get(signal) or {}).items():
                if label in scores:
                    scores[label] += int(pts)
                elif f"bad_label:{label}" not in gaps:
                    gaps.append(f"bad_label:{label}")
        states.setdefault(st["column"], NOT_MEASURED)
    return states, gaps
