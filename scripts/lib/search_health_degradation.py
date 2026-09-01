#!/usr/bin/env python3
"""search_health_degradation.py — stamp SearXNG pool state onto research output.

WAVE F4. The monitor (`scripts.lib.search_health`) already knows when the
engine pool is impaired — measured 2026-08-30 a ten-result answer came entirely
from one engine while duckduckgo/startpage were CAPTCHA-suspended and nothing
on the research record said so. Thinner looked like full.

This module does three things without rewriting residual-web:

  1. **Durable status** under `production_state_root()/data/runtime/
     search_health.json` so a dry reader (and CI) can report per-source state
     without probing.
  2. **Per-source report** — serving vs unresponsive (CAPTCHA / rate-limit /
     other), never inventing engine or CAPTCHA rows that were not measured.
  3. **`attach_degradation`** — thin stamp onto any research-output dict so
     `search_pool_impaired` / `search_degradation_note` / `search_sources`
     survive into the hop result (the prior live-transport stamp was dropped
     by `run_hop`).

READ_ONLY_ADVISORY. Never invents CAPTCHA data. Never spends a paid provider.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

SCHEMA = "SearchHealthDegradation@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
STATUS_REL = Path("data") / "runtime" / "search_health.json"

# Keys stamped onto research output / hop results. `run_hop` forwards these.
STAMP_KEYS: tuple[str, ...] = (
    "search_pool",
    "search_pool_impaired",
    "search_degradation_note",
    "search_sources",
    "search_captcha_suspended",
    "search_thinner_than_full",
)

_CAPTCHA_RE = re.compile(r"captcha", re.IGNORECASE)


def _state_root() -> Path:
    try:
        from scripts.lib.canonical_store_registry import production_state_root
        return Path(production_state_root())
    except Exception:
        try:
            from lib.canonical_store_registry import production_state_root  # type: ignore
            return Path(production_state_root())
        except Exception:
            return Path.home() / "trade-ai-releases" / "persistent-state"


def status_path(root: Optional[Path] = None) -> Path:
    """Durable last-known pool snapshot. Survives cron; never release-relative."""
    base = Path(root) if root is not None else _state_root()
    return base / STATUS_REL


def _utc(now: Optional[datetime] = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now


def per_source_state(pool: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
    """Serving + unresponsive engines from a *measured* pool dict.

    Returns [] when pool is missing/empty — does **not** invent CAPTCHA rows.
    """
    if not isinstance(pool, dict):
        return []
    rows: list[dict[str, Any]] = []
    for eng in pool.get("serving_engines") or []:
        rows.append({
            "engine": str(eng),
            "state": "serving",
            "reason": "",
            "captcha_suspended": False,
        })
    for u in pool.get("unresponsive_engines") or []:
        if isinstance(u, dict):
            eng = str(u.get("engine") or "")
            reason = str(u.get("reason") or "")
        elif isinstance(u, (list, tuple)) and u:
            eng = str(u[0])
            reason = str(u[1]) if len(u) > 1 else ""
        else:
            eng = str(u)
            reason = ""
        if not eng:
            continue
        rows.append({
            "engine": eng,
            "state": "unresponsive",
            "reason": reason,
            "captcha_suspended": bool(_CAPTCHA_RE.search(reason)),
        })
    return rows


def captcha_suspended_engines(pool: Optional[dict[str, Any]]) -> list[str]:
    return sorted({
        r["engine"] for r in per_source_state(pool)
        if r.get("captcha_suspended")
    })


def read_status(root: Optional[Path] = None) -> Optional[dict[str, Any]]:
    """Read durable status. Corrupt/absent → None. Never invents engines."""
    path = status_path(root)
    try:
        if not path.is_file():
            return None
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(doc, dict):
        return None
    pool = doc.get("pool")
    if pool is not None and not isinstance(pool, dict):
        return None
    return doc


def write_status(
    pool: dict[str, Any],
    *,
    root: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> Path:
    """Persist a measured pool snapshot. Caller must supply real probe data."""
    if not isinstance(pool, dict):
        raise TypeError("pool must be a measured dict — refusing to invent")
    now = _utc(now)
    path = status_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    sources = per_source_state(pool)
    doc = {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "as_of": now.replace(microsecond=0).isoformat(),
        "pool": pool,
        "sources": sources,
        "captcha_suspended": captcha_suspended_engines(pool),
        "impaired": bool(pool.get("impaired")),
        "thinner_than_full": bool(pool.get("impaired")),
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def _unavailable_stamp(*, reason: str, now: datetime) -> dict[str, Any]:
    """Honest empty stamp — no fabricated engines or CAPTCHA reasons."""
    note = f"search pool status unavailable: {reason}"
    return {
        "search_pool": {
            "schema": "SearchHealth@v1",
            "authority": AUTHORITY,
            "as_of": now.replace(microsecond=0).isoformat(),
            "impaired": None,
            "reachable": None,
            "results": None,
            "serving_engines": [],
            "engines_serving_count": 0,
            "unresponsive_engines": [],
            "degradation_note": note,
            "status_source": "unavailable",
        },
        "search_pool_impaired": None,
        "search_degradation_note": note,
        "search_sources": [],
        "search_captcha_suspended": [],
        "search_thinner_than_full": None,
    }


def degradation_stamp(
    pool: Optional[dict[str, Any]] = None,
    *,
    dry: bool = False,
    probe: bool = False,
    persist: bool = False,
    url: Optional[str] = None,
    now: Optional[datetime] = None,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    """Build the stamp fields for a research output.

    Resolution order (never invents CAPTCHA data):
      1. Explicit `pool` (caller-observed).
      2. `probe=True` → `search_health.pool_health` (optional persist).
      3. Durable status via `read_status` (dry default).
      4. Unavailable stamp — empty sources, impaired=None, honest note.
    """
    now = _utc(now)
    measured: Optional[dict[str, Any]] = pool if isinstance(pool, dict) else None
    source = "caller"

    if measured is None and probe and not dry:
        try:
            from scripts.lib.search_health import pool_health
        except Exception:
            try:
                from lib.search_health import pool_health  # type: ignore
            except Exception as e:
                return _unavailable_stamp(
                    reason=f"monitor import failed: {type(e).__name__}: {e}",
                    now=now,
                )
        try:
            measured = pool_health(url=url, now=now)
            source = "probe"
        except Exception as e:
            return _unavailable_stamp(
                reason=f"probe failed: {type(e).__name__}: {e}",
                now=now,
            )
        if persist and isinstance(measured, dict):
            try:
                write_status(measured, root=root, now=now)
            except Exception:
                pass  # stamp still returns; durable write is best-effort

    if measured is None:
        doc = read_status(root)
        if doc and isinstance(doc.get("pool"), dict):
            measured = doc["pool"]
            source = "durable"
        else:
            return _unavailable_stamp(
                reason=("dry read: no durable search_health.json"
                        if dry or not probe
                        else "no measured pool"),
                now=now,
            )

    sources = per_source_state(measured)
    captcha = captcha_suspended_engines(measured)
    impaired = measured.get("impaired")
    note = str(measured.get("degradation_note") or "")
    if captcha and "CAPTCHA" not in note.upper():
        # Surface suspensions even when the pool still meets MIN_HEALTHY_ENGINES.
        note = (note + (" " if note else "") +
                f"CAPTCHA-suspended engines: {', '.join(captcha)}.").strip()

    pool_out = dict(measured)
    pool_out["status_source"] = source
    pool_out.setdefault("as_of", now.replace(microsecond=0).isoformat())

    return {
        "search_pool": pool_out,
        "search_pool_impaired": impaired,
        "search_degradation_note": note,
        "search_sources": sources,
        "search_captcha_suspended": captcha,
        # thinner ≠ full when the monitor says the pool is impaired
        "search_thinner_than_full": bool(impaired) if impaired is not None else None,
    }


def attach_degradation(
    research_output: dict[str, Any],
    pool: Optional[dict[str, Any]] = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Stamp degradation onto `research_output` in place; return it."""
    if not isinstance(research_output, dict):
        raise TypeError("research_output must be a dict")
    stamp = degradation_stamp(pool, **kwargs)
    research_output.update(stamp)
    return research_output


def forward_stamp(
    dest: dict[str, Any],
    source: Optional[dict[str, Any]],
) -> dict[str, Any]:
    """Copy stamp keys from a transport/hop response onto a hop result.

    Missing keys are left unset (do not invent). Used by residual-web `run_hop`
    so the live-transport stamp is no longer dropped.
    """
    if not isinstance(dest, dict):
        raise TypeError("dest must be a dict")
    src = source if isinstance(source, dict) else {}
    for key in STAMP_KEYS:
        if key in src:
            dest[key] = src[key]
    return dest


def narrative_suffix(hop_or_stamp: Optional[dict[str, Any]]) -> str:
    """Facts-only clause for cc_narrative when the pool is impaired / CAPTCHA'd.

    Empty string when there is nothing measured to say — never fabricates.
    """
    if not isinstance(hop_or_stamp, dict):
        return ""
    impaired = hop_or_stamp.get("search_pool_impaired")
    captcha = hop_or_stamp.get("search_captcha_suspended") or []
    note = str(hop_or_stamp.get("search_degradation_note") or "").strip()
    if impaired is True:
        return (" Search pool impaired — this answer is thinner than a full "
                "result set of this size would imply"
                + (f" ({note})" if note else ".")).rstrip(".") + "."
    if captcha:
        return (f" SearXNG engines CAPTCHA-suspended: {', '.join(captcha)}"
                " — coverage narrower than an unimpaired pool.").rstrip(".") + "."
    return ""


def dry_report(
    *,
    root: Optional[Path] = None,
    now: Optional[datetime] = None,
    probe: bool = False,
) -> dict[str, Any]:
    """Operator/CI dry report: monitor lane + per-source state, no invent."""
    now = _utc(now)
    lane: dict[str, Any] = {}
    try:
        from scripts.lib.search_health import collect_search_health
        lane = collect_search_health(now=now, probe=probe)
    except Exception as e:
        lane = {"lane": "search-providers", "ok": False,
                "firing": [f"collect_failed:{type(e).__name__}"],
                "error": f"{type(e).__name__}: {e}"}

    stamp = degradation_stamp(dry=not probe, probe=probe, now=now, root=root)
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "as_of": now.replace(microsecond=0).isoformat(),
        "dry": not probe,
        "monitor": {
            "lane": lane.get("lane"),
            "ok": lane.get("ok"),
            "firing": lane.get("firing"),
            "budgets": lane.get("budgets") if not probe else None,
            "pool": lane.get("pool") if probe else None,
        },
        "per_source": stamp.get("search_sources") or [],
        "captcha_suspended": stamp.get("search_captcha_suspended") or [],
        "impaired": stamp.get("search_pool_impaired"),
        "thinner_than_full": stamp.get("search_thinner_than_full"),
        "degradation_note": stamp.get("search_degradation_note"),
        "status_path": str(status_path(root)),
        "durable_present": read_status(root) is not None,
    }


def main(argv: Optional[list[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--probe", action="store_true",
                    help="live HTTP probe (default: dry durable/lane only)")
    ap.add_argument("--persist", action="store_true",
                    help="with --probe, write durable search_health.json")
    ap.add_argument("--root", type=Path, default=None,
                    help="override state root (tests)")
    args = ap.parse_args(argv)
    if args.probe:
        stamp = degradation_stamp(probe=True, persist=args.persist, root=args.root)
        report = dry_report(root=args.root, probe=True)
        report["stamp"] = {k: stamp[k] for k in STAMP_KEYS}
    else:
        report = dry_report(root=args.root, probe=False)
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
