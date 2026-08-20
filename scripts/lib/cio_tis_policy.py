"""Thesis Investment System (TIS) policy — load/save/evaluate.

Operator-editable layout + requirements for living theses, coverage SLA,
research scheduler reentry tier, and Telegram IMMEDIATE/DIGEST rules.

Authority: READ_ONLY_ADVISORY. Writes are config-only (no broker/order).
"""
from __future__ import annotations

import json
import shutil
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore

ROOT = Path(__file__).resolve().parents[2]
# Prefer config YAML when present (requires config-write grant to ship);
# defaults are embedded + optional JSON under data/cio for editable ops without YAML.
DEFAULT_POLICY_YAML = ROOT / "config" / "cio_tis_policy.yaml"
DEFAULT_POLICY_JSON = ROOT / "data" / "cio" / "cio_tis_policy_defaults.json"
OPERATOR_OVERRIDE_PATH = ROOT / "data" / "cio" / "cio_tis_policy_override.json"
BACKUP_DIR = ROOT / "data" / "cio" / "tis_policy_backups"

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "CioTisPolicy@v1"

EMBEDDED_DEFAULTS: dict[str, Any] = {
    "schema": SCHEMA,
    "title": "Thesis Investment System",
    "authority": AUTHORITY,
    "updated_at": None,
    "updated_by": None,
    "layout": [
        {
            "id": "material_universe",
            "title": "Material universe",
            "body": (
                "Living theses cover all current holdings, re-entry READY/NEAR names, "
                "and the curated Watch desk — not the full ~6k discovery blob."
            ),
        },
        {
            "id": "thesis_sla",
            "title": "Thesis coverage SLA",
            "body": (
                "Every material name should have a CURRENT symbol thesis pin. "
                "Coverage below SLA targets raises a Telegram digest (not silent)."
            ),
        },
        {
            "id": "holdings_parity",
            "title": "Holdings parity (not concentration-gated)",
            "body": (
                "Visa, Dexcom, and every other holding get the same thesis treatment as SCHD. "
                "Concentration ≥12% is a separate risk alert (S6), not a thesis eligibility gate."
            ),
        },
        {
            "id": "reentry_progress",
            "title": "Re-entry progress",
            "body": (
                "Desk READY/NEAR is visible in Command Center. Telegram pages IMMEDIATE only "
                "on capital RE_ENTER + ACT_NOW; band changes and closeness digests follow "
                "telegram.digest rules."
            ),
        },
        {
            "id": "watch_progress",
            "title": "Watch progress",
            "body": (
                "Watch promotion READY/GO/NEAR lights S7. Digests report promotion-grade debt "
                "and thesis gaps; IMMEDIATE only when policy marks a name ACT_NOW."
            ),
        },
        {
            "id": "telegram",
            "title": "Telegram CIO bot",
            "body": (
                "Dedicated @tradeai_cio_bot only. IMMEDIATE for ACT_NOW / concentration fire "
                "flips; DIGEST for SLA breaches, reentry band changes, and thesis publishes "
                "on material names. Signal-over-spam fingerprint ledger remains on."
            ),
        },
    ],
    "requirements": {
        "coverage_sla": {
            "holdings_current_pct": 100,
            "reentry_ready_near_current_pct": 100,
            "watch_desk_current_pct": 80,
        },
        "stale_days": 30,
        "concentration_fire_pct": 12.0,
        "acquisition": {
            "held_reentry_lane": True,
            "skip_until_hours_blocked_rag": 72,
            "same_run_acquire_curate_embed_synth": True,
        },
        "research_scheduler": {
            "reentry_tier": "T0-REENTRY",
            "reentry_sla_refreshes": 2,
            "reentry_sla_window_days": 1,
        },
        "telegram": {
            "enabled": True,
            "immediate": [
                "S6_CONCENTRATION_FIRE_FLIP",
                "S3_RE_ENTER_ACT_NOW",
                "S1_MATERIAL_LIFECYCLE",
                "S5_CASH_DEPLOYMENT",
                "S8_DEFENSIVE_REGIME",
            ],
            "digest": [
                "COVERAGE_SLA_BREACH",
                "REENTRY_BAND_CHANGE",
                "THESIS_PUBLISHED_MATERIAL",
                "WATCH_PROMOTION_GRADE_CHANGE",
            ],
            "digest_max_symbols": 12,
            "digest_cooldown_hours": 12,
            "max_notify_per_pass": 3,
        },
    },
    "notes": (
        "Edit requirements on the TIS LAYOUT tab. Saving writes an operator override "
        "under data/cio/ and takes effect on the next coverage/digest/scheduler pass."
    ),
}

# Hard bounds so a bad edit cannot disable all advisement or demand impossible rates.
_SLA_BOUNDS = {
    "holdings_current_pct": (50, 100),
    "reentry_ready_near_current_pct": (50, 100),
    "watch_desk_current_pct": (0, 100),
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    if yaml is None:
        raise RuntimeError("PyYAML required to load cio_tis_policy.yaml")
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError("cio_tis_policy must be a mapping")
    return data


def _deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(base)
    for k, v in (over or {}).items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = deepcopy(v)
    return out


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def load_tis_policy(
    *,
    root: Path | None = None,
    include_override: bool = True,
) -> dict[str, Any]:
    """Load embedded defaults ← optional JSON/YAML defaults ← operator override."""
    root = Path(root or ROOT)
    base = deepcopy(EMBEDDED_DEFAULTS)
    # Optional shipped files (JSON preferred when config-write is locked)
    jpath = root / "data" / "cio" / "cio_tis_policy_defaults.json"
    ypath = root / "config" / "cio_tis_policy.yaml"
    file_defaults = _load_json(jpath)
    if not file_defaults and ypath.exists():
        try:
            file_defaults = _load_yaml(ypath)
        except Exception:
            file_defaults = {}
    if file_defaults:
        base = _deep_merge(base, file_defaults)
    if include_override:
        op = root / "data" / "cio" / "cio_tis_policy_override.json"
        over = _load_json(op)
        if over:
            if "requirements" in over or "layout" in over:
                base = _deep_merge(base, {
                    k: over[k]
                    for k in ("layout", "requirements", "notes", "title", "updated_at", "updated_by")
                    if k in over
                })
            else:
                base = _deep_merge(base, over)
    base.setdefault("schema", SCHEMA)
    base.setdefault("authority", AUTHORITY)
    base["source"] = {
        "embedded": True,
        "defaults_json": str(jpath),
        "defaults_yaml": str(ypath),
        "override": str(root / "data" / "cio" / "cio_tis_policy_override.json"),
        "override_present": (root / "data" / "cio" / "cio_tis_policy_override.json").exists(),
    }
    return base


def validate_tis_policy(policy: dict[str, Any]) -> tuple[bool, list[str]]:
    errs: list[str] = []
    if not isinstance(policy, dict):
        return False, ["policy must be an object"]
    req = policy.get("requirements") or {}
    if not isinstance(req, dict):
        errs.append("requirements must be an object")
        return False, errs
    sla = req.get("coverage_sla") or {}
    if isinstance(sla, dict):
        for key, (lo, hi) in _SLA_BOUNDS.items():
            if key not in sla:
                continue
            try:
                v = float(sla[key])
            except (TypeError, ValueError):
                errs.append(f"coverage_sla.{key} must be numeric")
                continue
            if v < lo or v > hi:
                errs.append(f"coverage_sla.{key} must be in [{lo}, {hi}]")
    stale = req.get("stale_days")
    if stale is not None:
        try:
            sd = int(stale)
            if sd < 1 or sd > 365:
                errs.append("stale_days must be 1..365")
        except (TypeError, ValueError):
            errs.append("stale_days must be an integer")
    tg = req.get("telegram") or {}
    if isinstance(tg, dict) and "enabled" in tg and not isinstance(tg["enabled"], bool):
        errs.append("telegram.enabled must be boolean")
    layout = policy.get("layout")
    if layout is not None and not isinstance(layout, list):
        errs.append("layout must be a list")
    return (len(errs) == 0), errs


def save_tis_policy(
    patch: dict[str, Any],
    *,
    root: Path | None = None,
    updated_by: str = "operator",
) -> dict[str, Any]:
    """Merge patch into override JSON (keeps shipped YAML as defaults).

    Accepts full policy or partial {layout, requirements, notes}.
    """
    root = Path(root or ROOT)
    current = load_tis_policy(root=root, include_override=True)
    # Strip non-editable runtime keys
    for k in ("source",):
        current.pop(k, None)
        patch = {kk: vv for kk, vv in patch.items() if kk != "source"}

    merged = _deep_merge(current, patch)
    merged["schema"] = SCHEMA
    merged["authority"] = AUTHORITY
    merged["updated_at"] = _now()
    merged["updated_by"] = str(updated_by or "operator")[:120]

    ok, errs = validate_tis_policy(merged)
    if not ok:
        return {"ok": False, "errors": errs, "authority": AUTHORITY}

    override_path = root / "data" / "cio" / "cio_tis_policy_override.json"
    backup_dir = root / "data" / "cio" / "tis_policy_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    if override_path.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        shutil.copy2(override_path, backup_dir / f"cio_tis_policy_override_{stamp}.json")

    # Persist only editable surface (not full deep-merge of yaml comments)
    persist = {
        "schema": SCHEMA,
        "title": merged.get("title") or "Thesis Investment System",
        "authority": AUTHORITY,
        "updated_at": merged["updated_at"],
        "updated_by": merged["updated_by"],
        "layout": merged.get("layout") or [],
        "requirements": merged.get("requirements") or {},
        "notes": merged.get("notes") or "",
    }
    override_path.parent.mkdir(parents=True, exist_ok=True)
    override_path.write_text(json.dumps(persist, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    return {"ok": True, "policy": load_tis_policy(root=root), "authority": AUTHORITY}


def coverage_sla_targets(policy: Optional[dict[str, Any]] = None) -> dict[str, float]:
    pol = policy or load_tis_policy()
    sla = ((pol.get("requirements") or {}).get("coverage_sla") or {})
    return {
        "holdings_current_pct": float(sla.get("holdings_current_pct", 100)),
        "reentry_ready_near_current_pct": float(sla.get("reentry_ready_near_current_pct", 100)),
        "watch_desk_current_pct": float(sla.get("watch_desk_current_pct", 80)),
    }


def stale_days(policy: Optional[dict[str, Any]] = None) -> int:
    pol = policy or load_tis_policy()
    try:
        return int(((pol.get("requirements") or {}).get("stale_days")) or 30)
    except (TypeError, ValueError):
        return 30


def telegram_rules(policy: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    pol = policy or load_tis_policy()
    tg = ((pol.get("requirements") or {}).get("telegram") or {})
    return {
        "enabled": bool(tg.get("enabled", True)),
        "immediate": list(tg.get("immediate") or []),
        "digest": list(tg.get("digest") or []),
        "digest_max_symbols": int(tg.get("digest_max_symbols") or 12),
        "digest_cooldown_hours": int(tg.get("digest_cooldown_hours") or 12),
        "max_notify_per_pass": int(tg.get("max_notify_per_pass") or 3),
    }


def evaluate_coverage_sla(
    report: dict[str, Any],
    *,
    policy: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Compute SLA buckets from a coverage report. Thesis parity is NOT weight-gated."""
    pol = policy or load_tis_policy()
    targets = coverage_sla_targets(pol)
    rows = list(report.get("rows") or [])

    def _is_ticker(sym: str) -> bool:
        s = str(sym or "").strip().upper()
        if not s or len(s) > 5:
            return False
        if s[0].isdigit():
            return False
        return s[0].isalpha() and all(c.isalnum() or c in ".-" for c in s)

    held = [
        r for r in rows
        if "HELD" in set(r.get("memberships") or []) and _is_ticker(r.get("symbol") or "")
    ]
    reentry_rn = [
        r for r in rows
        if _is_ticker(r.get("symbol") or "")
        and any(x in str(r.get("reentry_state") or "").upper() for x in ("READY", "NEAR", "GO", "IN_ZONE"))
    ]
    # Curated watch desk only — OPPORTUNITY / material watch, NOT full discovery WATCHLIST
    watch = [
        r for r in rows
        if _is_ticker(r.get("symbol") or "")
        and (
            "OPPORTUNITY" in set(r.get("memberships") or [])
            or (
                "WATCHLIST" in set(r.get("memberships") or [])
                and r.get("opportunity_rank") is not None
            )
            or (
                "WATCHLIST" in set(r.get("memberships") or [])
                and "HELD" not in set(r.get("memberships") or [])
                and r.get("material")
                and "REENTRY" not in set(r.get("memberships") or [])
            )
        )
    ]
    if not watch:
        watch = [
            r for r in rows
            if _is_ticker(r.get("symbol") or "")
            and r.get("material")
            and "WATCHLIST" in set(r.get("memberships") or [])
            and "HELD" not in set(r.get("memberships") or [])
        ]

    def _pct_current(bucket: list[dict[str, Any]]) -> tuple[float, int, int]:
        if not bucket:
            return 100.0, 0, 0
        cur = sum(1 for r in bucket if r.get("coverage_state") == "CURRENT")
        return round(100.0 * cur / len(bucket), 1), cur, len(bucket)

    h_pct, h_cur, h_n = _pct_current(held)
    r_pct, r_cur, r_n = _pct_current(reentry_rn)
    w_pct, w_cur, w_n = _pct_current(watch)

    breaches = []
    if h_n and h_pct < targets["holdings_current_pct"]:
        breaches.append({
            "bucket": "holdings",
            "actual_pct": h_pct,
            "target_pct": targets["holdings_current_pct"],
            "missing": [r["symbol"] for r in held if r.get("coverage_state") != "CURRENT"][:40],
        })
    if r_n and r_pct < targets["reentry_ready_near_current_pct"]:
        breaches.append({
            "bucket": "reentry_ready_near",
            "actual_pct": r_pct,
            "target_pct": targets["reentry_ready_near_current_pct"],
            "missing": [r["symbol"] for r in reentry_rn if r.get("coverage_state") != "CURRENT"][:40],
        })
    if w_n and w_pct < targets["watch_desk_current_pct"]:
        breaches.append({
            "bucket": "watch_desk",
            "actual_pct": w_pct,
            "target_pct": targets["watch_desk_current_pct"],
            "missing": [r["symbol"] for r in watch if r.get("coverage_state") != "CURRENT"][:40],
        })

    return {
        "as_of": _now(),
        "authority": AUTHORITY,
        "targets": targets,
        "buckets": {
            "holdings": {"current_pct": h_pct, "current_n": h_cur, "n": h_n, "ok": h_pct >= targets["holdings_current_pct"] or h_n == 0},
            "reentry_ready_near": {"current_pct": r_pct, "current_n": r_cur, "n": r_n, "ok": r_pct >= targets["reentry_ready_near_current_pct"] or r_n == 0},
            "watch_desk": {"current_pct": w_pct, "current_n": w_cur, "n": w_n, "ok": w_pct >= targets["watch_desk_current_pct"] or w_n == 0},
        },
        "breaches": breaches,
        "sla_ok": len(breaches) == 0,
        "note": "Thesis SLA is membership-based; concentration fire % does not gate thesis eligibility. Watch bucket excludes discovery-only names.",
    }
