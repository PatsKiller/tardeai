"""Watch quality intake gate — consequential (not visibility-only).

Used by discovery writers (finviz screeners, etc.) to refuse new `ai_discovered`
(and other non-exempt) inserts when the source's rolling 21d median α vs SPY is
below config/watch_quality_gate.json floors.

Dry-run safe: callers pass dry_run and never write. Fail-open on DB errors so a
gate outage does not freeze all discovery (logged via result.reason).
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
CFG_PATH = ROOT / "config" / "watch_quality_gate.json"

_CACHE: dict[str, Any] = {"ts": 0.0, "cfg": None, "low": None, "per_source": None}
_CACHE_TTL = 3600.0


def _default_cfg() -> dict:
    return {
        "alpha_floor_pct": -2.0,
        "min_n": 30,
        "window_days": 90,
        "enforce_intake": True,
        "block_sources_when_low_efficacy": True,
        "exempt_sources": [
            "operator", "personal_watchlist", "portfolio", "hermes",
            "pullback_macd", "trade_ai_go", "prev_traded",
        ],
        "quarantine_status": "removed",
        "quarantine_reason": "low_efficacy_source_quality_gate",
    }


def load_cfg() -> dict:
    cfg = _default_cfg()
    try:
        raw = json.loads(CFG_PATH.read_text())
        for k, v in raw.items():
            if k.startswith("_"):
                continue
            cfg[k] = v
    except Exception:
        pass
    return cfg


def low_efficacy_sources(*, force_refresh: bool = False) -> tuple[set[str], list[dict], dict]:
    """Return (low_set, per_source_rows, cfg). Cached 1h."""
    now = time.time()
    if (
        not force_refresh
        and _CACHE["low"] is not None
        and now - float(_CACHE["ts"] or 0) < _CACHE_TTL
    ):
        return set(_CACHE["low"] or set()), list(_CACHE["per_source"] or []), dict(_CACHE["cfg"] or {})

    cfg = load_cfg()
    per_source: list[dict] = []
    low: set[str] = set()
    try:
        from db_adapter import get_connection  # type: ignore
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT source_type,
                   count(*) AS emitted,
                   count(*) FILTER (WHERE alpha_21d IS NOT NULL) AS n,
                   round((percentile_cont(0.5) WITHIN GROUP (ORDER BY alpha_21d)
                     FILTER (WHERE alpha_21d IS NOT NULL))::numeric, 2) AS alpha_21d_median
            FROM watch_candidate_events
            WHERE emitted_on > CURRENT_DATE - %s
            GROUP BY source_type
            ORDER BY source_type
            """,
            (int(cfg["window_days"]),),
        )
        cols = [d[0] for d in cur.description]
        for row in cur.fetchall():
            rec = dict(zip(cols, row))
            n = int(rec.get("n") or 0)
            med = rec.get("alpha_21d_median")
            is_low = bool(
                n >= int(cfg["min_n"])
                and med is not None
                and float(med) < float(cfg["alpha_floor_pct"])
            )
            rec["low_efficacy"] = is_low
            if is_low:
                low.add(str(rec["source_type"]))
            # JSON-clean decimals
            for k, v in list(rec.items()):
                if hasattr(v, "as_tuple"):
                    rec[k] = float(v)
            per_source.append(rec)
    except Exception as e:
        _CACHE.update({"ts": now, "cfg": cfg, "low": set(), "per_source": [], "err": str(e)[:200]})
        return set(), [], cfg

    _CACHE.update({"ts": now, "cfg": cfg, "low": low, "per_source": per_source, "err": None})
    return set(low), per_source, cfg


def admit_source(source: str, *, force_refresh: bool = False) -> dict:
    """Decide whether a new watchlist row for `source` may be inserted as active.

    Returns:
      {
        "admit": bool,
        "source": str,
        "reason": str,
        "low_efficacy": bool,
        "enforce": bool,
        "alpha_21d_median": float|None,
        "n": int|None,
      }
    """
    src = (source or "").strip() or "unknown"
    low, per, cfg = low_efficacy_sources(force_refresh=force_refresh)
    enforce = bool(cfg.get("enforce_intake")) and bool(cfg.get("block_sources_when_low_efficacy", True))
    exempt = {str(x).lower() for x in (cfg.get("exempt_sources") or [])}
    rec = next((r for r in per if str(r.get("source_type")) == src), None)
    is_low = src in low
    med = float(rec["alpha_21d_median"]) if rec and rec.get("alpha_21d_median") is not None else None
    n = int(rec["n"]) if rec and rec.get("n") is not None else None

    if src.lower() in exempt:
        return {
            "admit": True, "source": src, "reason": "exempt_source",
            "low_efficacy": is_low, "enforce": enforce,
            "alpha_21d_median": med, "n": n,
        }
    if not enforce:
        return {
            "admit": True, "source": src, "reason": "enforce_disabled",
            "low_efficacy": is_low, "enforce": False,
            "alpha_21d_median": med, "n": n,
        }
    if is_low:
        return {
            "admit": False, "source": src,
            "reason": cfg.get("quarantine_reason") or "low_efficacy_source_quality_gate",
            "low_efficacy": True, "enforce": True,
            "alpha_21d_median": med, "n": n,
        }
    return {
        "admit": True, "source": src, "reason": "pass",
        "low_efficacy": False, "enforce": enforce,
        "alpha_21d_median": med, "n": n,
    }


def should_insert_ai_discovered() -> dict:
    """Convenience for finviz_screener_runner and similar."""
    return admit_source("ai_discovered")
