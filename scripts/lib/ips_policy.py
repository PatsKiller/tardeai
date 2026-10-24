"""Canonical concentration policy, operator2026-10-24 Addendum3/R13.

One IPS key owns class limits, fund classification thresholds and the near band.
Missing evidence is unknown. Pure display/advisory calculations; no broker,
provider, order, stop, rebalance or state writes. Named risk default reads only
the stock compatibility accessor; class-aware R13 action gates belong to W10.
"""
from __future__ import annotations

import json
import logging
import math
from copy import deepcopy
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"
IPS_FILENAME = "investment_policy_statement.json"

_warned: set[tuple[str, str]] = set()
POLICY_KEY = "constraints.concentration_policy"
CLASS_LABELS = {"broad_diversified_fund": "Broad diversified fund", "narrow_thematic_fund": "Narrow or thematic fund",
                "single_stock": "Single stock", "leveraged_inverse_fund": "Leveraged or inverse fund"}


def _constraints(config_dir: Path | None) -> tuple[dict[str, Any], Path]:
    path = (config_dir or CONFIG_DIR) / IPS_FILENAME
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, path
    c = raw.get("constraints") if isinstance(raw, dict) else None
    return (c if isinstance(c, dict) else {}), path


def _positive(c: dict[str, Any], key: str) -> float | None:
    if not isinstance(c, dict):
        return None
    try:
        v = float(c.get(key))
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and v > 0 else None


def _unavailable(path: Path, key: str) -> None:
    marker = (str(path), key)
    if marker not in _warned:
        _warned.add(marker)
        log.warning("IPS %s missing/invalid in %s; concentration limit unknown", key, path)
    return None


def ips_max_position_pct(config_dir: Path | None = None) -> float | None:
    """Compatibility stock-only reader; current policy is one class-aware key."""
    c, path = _constraints(config_dir)
    policy = c.get("concentration_policy")
    if isinstance(policy, dict):
        v = _positive(policy.get("limits_pct") or {}, "single_stock")
        return v if v is not None else _unavailable(path, POLICY_KEY)
    # Historical captured configs remain readable; there is no invented fallback.
    v = _positive(c, "max_single_position_pct")
    return v if v is not None else _unavailable(path, POLICY_KEY)


def ips_critical_position_pct(config_dir: Path | None = None) -> float | None:
    """The severe single-position tier (``constraints.critical_single_position_pct``).

    Never below the IPS max: a misconfigured critical tier cannot make the
    severe band fire before the limit itself.
    """
    c, path = _constraints(config_dir)
    if isinstance(c.get("concentration_policy"), dict):
        return ips_max_position_pct(config_dir)
    v = _positive(c, "critical_single_position_pct")
    maximum = ips_max_position_pct(config_dir)
    return max(v, maximum) if v is not None and maximum is not None else _unavailable(path, POLICY_KEY)


def _num(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError):
        return None


def concentration_policy(config_dir: Path | None = None) -> dict:
    """Operator-approved display policy; absent/invalid values remain gaps."""
    c, path = _constraints(config_dir)
    raw = c.get("concentration_policy")
    raw = raw if isinstance(raw, dict) else {}
    limits = raw.get("limits_pct")
    limits = limits if isinstance(limits, dict) else {}
    fraction = _num(raw.get("near_limit_fraction"))
    valid = bool(raw.get("approval_ref")) and fraction is not None and 0 < fraction <= 1
    valid = valid and all(_positive(limits, key) is not None for key in (*CLASS_LABELS, "lookthrough_company", "lookthrough_sector"))
    return {"classes": [{"id": key, "label": label, "limit_pct": _positive(limits, key) if valid else None,
                         "near_limit_pct": round(float(limits[key])*fraction, 4) if valid else None}
                        for key, label in CLASS_LABELS.items()],
            "lookthrough_company_limit_pct": _positive(limits, "lookthrough_company") if valid else None,
            "lookthrough_sector_limit_pct": _positive(limits, "lookthrough_sector") if valid else None,
            "near_limit_fraction": fraction if valid else None, "near_limit_pct": None,
            "source": f"config/{IPS_FILENAME}#{POLICY_KEY}", "source_label": "Operator IPS concentration policy",
            "as_of": raw.get("as_of"), "approval_ref": raw.get("approval_ref"), "scope": "whole_portfolio",
            "gap": None if valid else {"reason": "approved concentration policy unavailable"},
            "classification_rules": deepcopy(raw.get("fund_classification") or {})}


def instrument_class(position: dict, *, evidence=None, policy=None) -> dict:
    """Classify measured instrument facts; a top-holdings sample proves no total.

    A caller supplies persisted full-fund statistics with source/as_of and
    coverage_complete=True. No provider, ticker-specific rule or cache repair.
    """
    evidence = evidence if isinstance(evidence, dict) else position.get("fund_holdings_evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    policy = policy or concentration_policy()
    kind = str(position.get("asset_type") or position.get("security_type") or "").lower().replace(" ", "_")
    is_fund = position.get("is_fund") is True or evidence.get("is_fund") is True or kind in {"etf", "fund", "mutual_fund", "mutualfund", "closed_end_fund", "interval_fund"}
    result = {"classification": None, "classification_label": "Not measured", "source": evidence.get("source") or position.get("source"),
              "as_of": evidence.get("as_of") or position.get("as_of"), "gap": None}
    def finish(name=None, reason=None):
        return {**result, "classification": name, "classification_label": CLASS_LABELS.get(name, "Not measured"),
                "gap": {"reason": reason} if reason else None}
    if kind in {"stock", "equity", "common_stock"} and not is_fund:
        return finish("single_stock")
    if not is_fund:
        return finish(reason="instrument classification unavailable")
    if evidence.get("is_leveraged") is True or evidence.get("is_inverse") is True:
        if not evidence.get("source") or not evidence.get("as_of"):
            return finish(reason="dated leverage or inverse metadata unavailable")
        return finish("leveraged_inverse_fund")
    if evidence.get("is_leveraged") is not False or evidence.get("is_inverse") is not False:
        return finish(reason="fund leverage or inverse metadata unavailable")
    if evidence.get("coverage_complete") is not True or evidence.get("sample_only") is True or not evidence.get("source") or not evidence.get("as_of"):
        return finish(reason="complete dated fund holdings statistics unavailable; samples do not establish a holding count")
    count, largest, top10 = (_num(evidence.get(k)) for k in ("holding_count", "largest_holding_pct", "top10_weight_pct"))
    rules = policy.get("classification_rules") or {}
    if count is None or count <= 0 or count != int(count) or largest is None or not 0 <= largest <= 100 or top10 is None or not largest <= top10 <= 100:
        return finish(reason="fund holding count or concentration statistics unavailable")
    try:
        narrow_count = float(rules["narrow_holdings_lt"])
        narrow_top10 = float(rules["narrow_top10_gt_pct"])
        broad_count = float(rules["broad_min_holdings"])
        broad_largest = float(rules["broad_largest_holding_lt_pct"])
    except (KeyError, ValueError, TypeError):
        return finish(reason="approved fund classification rules unavailable")
    if count < narrow_count or top10 > narrow_top10:
        return finish("narrow_thematic_fund")
    if narrow_count <= count < broad_count:
        override = evidence.get("operator_classification")
        if override is not None:
            if not isinstance(override, dict) or override.get("classification") not in {"broad_diversified_fund", "narrow_thematic_fund"} or not all(override.get(k) for k in ("approval_ref", "as_of", "source")):
                return finish(reason="dated operator fund classification unavailable")
            result.update({"operator_classification": deepcopy(override)})
            return finish(override["classification"])
        return finish(rules.get("midrange_class"))
    if count >= broad_count and largest < broad_largest:
        return finish("broad_diversified_fund")
    return finish(reason="fund does not match an approved measured class; operator classification needed")


def concentration_for_position(position: dict, *, weight_pct=None, evidence=None, config_dir=None) -> dict:
    policy = concentration_policy(config_dir)
    classification = instrument_class(position, evidence=evidence, policy=policy)
    cls = next((r for r in policy["classes"] if r["id"] == classification["classification"]), {})
    limit, near, weight = cls.get("limit_pct"), cls.get("near_limit_pct"), _num(weight_pct)
    gap = policy["gap"] or classification["gap"]
    if weight is None:
        gap = gap or {"reason": "whole-portfolio position weight unavailable"}
    status = "unknown" if gap or limit is None else "breach" if weight > limit else "near_limit" if weight >= near else "ok"
    return {**classification, "instrument_class": classification["classification"], "weight_pct": weight,
            "limit_pct": limit, "near_limit_pct": near, "limit_key": f"{POLICY_KEY}.limits_pct.{classification['classification']}",
            "status": status, "status_label": {"unknown": "Not measured", "breach": "Above limit", "near_limit": "Near limit", "ok": "Within limit"}[status],
            "classification_source": classification["source"], "policy_as_of": policy["as_of"],
            "source": policy["source"], "approval_ref": policy["approval_ref"], "gap": gap}


def policy_for_security(security_guid, *, document, fund_evidence=None, config_dir=None) -> dict:
    """One GUID's whole-book weight and instrument evidence for W10/W7."""
    rows = [r for r in document.get("positions", {}).get("rows", []) if r.get("security_guid") == security_guid and security_guid]
    total = _num(document.get("portfolio", {}).get("total_usd"))
    values = [_num(r.get("market_value")) for r in rows]
    weight = 100*sum(values)/total if rows and total and all(v is not None for v in values) else None
    position = dict(rows[0]) if rows else {}
    if len({(r.get("asset_type"), r.get("is_fund")) for r in rows}) > 1:
        position["asset_type"] = None
        position["is_fund"] = None
        position["fund_holdings_evidence"] = None
        fund_evidence = None
    return concentration_for_position(position, weight_pct=weight, evidence=fund_evidence, config_dir=config_dir)


def apply_concentration(document: dict, *, evidence_by_guid=None, config_dir=None) -> dict:
    """Pure CIO display composition; callers never calculate their own caps."""
    out = deepcopy(document)
    out["concentration_policy"] = concentration_policy(config_dir)
    evidence_by_guid = evidence_by_guid or {}
    positions = out.get("positions") or {}
    by_symbol = {}
    for row in positions.get("rows") or []:
        if row.get("security_guid"):
            by_symbol.setdefault(row.get("symbol"), set()).add(row["security_guid"])
    for row in [*(positions.get("concentration") or []), *([positions["largest_name"]] if positions.get("largest_name") else [])]:
        guids = by_symbol.get(row.get("symbol")) or set()
        guid = next(iter(guids)) if len(guids) == 1 else None
        assessment = policy_for_security(guid, document=out, fund_evidence=evidence_by_guid.get(guid), config_dir=config_dir)
        row.update(assessment)
    for row in positions.get("rows") or []:
        row["concentration_policy"] = policy_for_security(row.get("security_guid"), document=out,
            fund_evidence=evidence_by_guid.get(row.get("security_guid")), config_dir=config_dir)
    capital = out.get("capital")
    if isinstance(capital, dict):
        capital["legacy_alert_level_pct"] = capital.get("alert_level_pct")
        capital["alert_level_pct"] = None
        capital["policy_max_pct"] = next((r["limit_pct"] for r in out["concentration_policy"]["classes"] if r["id"] == "single_stock"), None)
    return out
