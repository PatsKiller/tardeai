"""Shock-type classifier: what KIND of stress this is (DSN-20261031-market-risk-engine, precision).

Operator 2026-10-31: "it needs to be whether it's a pandemic or is it a certain sector related. We need that type of
intelligence." Classes: SYSTEMIC (broad liquidation, COVID-like), SECTOR (a few groups or a theme such as AI / semis),
FACTOR (growth vs value or large vs small), RATES (rates or the dollar lead), CREDIT (high-yield spreads lead), EVENT
(an earnings or FOMC cluster). Each class is a list of boolean indicators from ``config/market_risk_policy.yaml``
``shock_type:``; the class score is the share of its indicators that hold; the highest score above
``min_confidence`` wins (ties by ``priority``), else MIXED. Deterministic; every indicator carries its evidence.
"""

from __future__ import annotations

from typing import Any

from scripts.lib.market_risk import contract as c

CLASS_LABEL = {
    "SYSTEMIC": "systemic (broad liquidation)",
    "SECTOR": "sector / theme",
    "FACTOR": "factor rotation",
    "RATES": "rates / dollar",
    "CREDIT": "credit",
    "EVENT": "event cluster",
    "MIXED": "mixed / unclear",
}


def _obs_state(observations: list[dict[str, Any]], category: str) -> str:
    for o in observations or []:
        if o.get("category") == category:
            return str(o.get("state") or "UNKNOWN")
    return "UNKNOWN"


def _group(block: dict[str, Any], key: str) -> dict[str, Any]:
    for r in block.get("groups") or []:
        if r.get("key") == key:
            return r
    return {}


def classify(
    block: dict[str, Any] | None, observations: list[dict[str, Any]], policy: dict[str, Any]
) -> dict[str, Any]:
    cfg = (policy or {}).get("shock_type") or {}
    if not block or not block.get("sectors_measured"):
        return {
            "class": "UNKNOWN",
            "label": "not measured",
            "confidence": None,
            "evidence": [],
            "reason_unknown": "no sector data",
            "as_of": (block or {}).get("as_of"),
        }
    n = int(block.get("sectors_measured") or 0)
    down = int(block.get("sectors_down") or 0)
    frac_down = down / n if n else 0.0
    disp_z = (block.get("dispersion") or {}).get("z")
    corr_z = (block.get("correlation") or {}).get("z")
    deff = block.get("defensive") or {}
    stressed = list(block.get("stressed") or [])
    resilient = list(block.get("resilient") or [])
    factors = block.get("factors") or {}
    gv = (factors.get("growth_value") or {}).get("z")
    sl = (factors.get("small_large") or {}).get("z")
    rates = _group(block, "rates")
    dollar = _group(block, "dollar")
    sys_c = cfg.get("systemic") or {}
    sec_c = cfg.get("sector") or {}
    fac_c = cfg.get("factor") or {}

    def ind(ok: bool | None, text: str) -> dict[str, Any]:
        return {"holds": bool(ok), "known": ok is not None, "evidence": text}

    def z_le(z: Any, t: float) -> bool | None:
        return None if z is None else float(z) <= t

    def z_ge(z: Any, t: float) -> bool | None:
        return None if z is None else float(z) >= t

    classes: dict[str, list[dict[str, Any]]] = {
        "SYSTEMIC": [
            ind(
                frac_down >= float(sys_c.get("min_frac_sectors_down", 0.8)),
                f"{down} of {n} sectors down over 5 sessions",
            ),
            ind(None if deff.get("r5") is None else float(deff["r5"]) < 0, f"defensives {deff.get('r5')}% 5d"),
            ind(z_ge(corr_z, float(sys_c.get("min_corr_z", 1.0))), f"cross-sector correlation z {corr_z}"),
            ind(
                _obs_state(observations, "volatility") == "STRESS",
                f"volatility {_obs_state(observations, 'volatility')}",
            ),
        ],
        "SECTOR": [
            ind(
                0 < len(stressed) <= int(sec_c.get("max_stressed_groups", 5)),
                f"stressed: {', '.join(stressed) or 'none'}",
            ),
            ind(
                len(resilient) >= int(sec_c.get("min_resilient_sectors", 3)) or deff.get("state") == "RESILIENT",
                f"holding up: {', '.join(resilient) or 'none'}; defensives {deff.get('state')}",
            ),
            ind(z_ge(disp_z, float(sec_c.get("min_dispersion_z", 1.0))), f"sector dispersion z {disp_z}"),
            ind(frac_down < float(sys_c.get("min_frac_sectors_down", 0.8)), f"{n - down} of {n} sectors not down"),
        ],
        "FACTOR": [
            ind(
                None
                if gv is None and sl is None
                else (
                    (gv is not None and abs(float(gv)) >= float(fac_c.get("min_abs_z", 2.0)))
                    or (sl is not None and abs(float(sl)) >= float(fac_c.get("min_abs_z", 2.0)))
                ),
                f"growth-value z {gv}, small-large z {sl}",
            ),
            ind(frac_down < float(sys_c.get("min_frac_sectors_down", 0.8)), f"{down} of {n} sectors down"),
        ],
        "RATES": [
            ind(
                z_le(rates.get("z5"), float((cfg.get("rates") or {}).get("bond_stress_z", -1.5))),
                f"long bonds 5d z {rates.get('z5')}",
            ),
            ind(
                z_ge(dollar.get("z5"), float((cfg.get("rates") or {}).get("dollar_z", 1.5))),
                f"dollar 5d z {dollar.get('z5')}",
            ),
            ind(
                _obs_state(observations, "macro_credit") in ("WARN", "STRESS"),
                f"macro {_obs_state(observations, 'macro_credit')}",
            ),
        ],
        "CREDIT": [
            ind(
                z_le((factors.get("credit") or {}).get("z"), float((cfg.get("credit") or {}).get("hy_rel_z", -1.5))),
                f"high yield vs Treasuries 5d spread z {(factors.get('credit') or {}).get('z')}",
            ),
            ind(
                _obs_state(observations, "macro_credit") == "STRESS",
                f"macro/credit {_obs_state(observations, 'macro_credit')}",
            ),
        ],
        "EVENT": [
            ind(_obs_state(observations, "event") == "STRESS", f"event {_obs_state(observations, 'event')}"),
            ind(
                0 < len(stressed) <= int(sec_c.get("max_stressed_groups", 5)),
                f"stress concentrated: {', '.join(stressed) or 'none'}",
            ),
        ],
    }
    scores = {}
    for k, inds in classes.items():
        known = [i for i in inds if i["known"]]
        scores[k] = (sum(i["holds"] for i in known) / len(inds)) if known else 0.0
    prio = list(cfg.get("priority") or ["SYSTEMIC", "CREDIT", "SECTOR", "FACTOR", "RATES", "EVENT"])
    best = sorted(scores, key=lambda k: (-scores[k], prio.index(k) if k in prio else 99))
    top = best[0]
    conf = scores[top]
    cls = top if conf >= float(cfg.get("min_confidence", 0.6)) else "MIXED"
    theme = ""
    if cls in ("SECTOR", "EVENT") and stressed:
        theme = " (" + " / ".join(stressed[:3]) + ")"
    hit = int(block.get("sectors_hit") or 0)
    headline = f"Type: {cls}{theme}"
    if cls not in ("SYSTEMIC", "MIXED") and n:
        headline += f" — not systemic: {n - hit} of {n} sectors holding"
        if resilient:
            headline += ", " + " and ".join(resilient[:3]).lower() + " up"
    out = {
        "schema": "MarketRiskShockType@v1",
        "class": cls,
        "label": CLASS_LABEL.get(cls, cls.lower()),
        "confidence": round(conf, 2),
        "runner_up": {"class": best[1], "confidence": round(scores[best[1]], 2)} if len(best) > 1 else None,
        "headline": headline,
        "evidence": [i["evidence"] for i in classes.get(top, []) if i["holds"]],
        "indicators": {k: [{"holds": i["holds"], "evidence": i["evidence"]} for i in v] for k, v in classes.items()},
        "as_of": block.get("as_of"),
    }
    c.assert_no_behavior_fields(out)
    return out
