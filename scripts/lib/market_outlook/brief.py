"""The brief (§4.4, §2.10 shape): what the operator reads, and what a dry run prints.

Every category appears with its state, its coverage and its sub-score. Every UNKNOWN appears with the reason it is
UNKNOWN — the dry run's whole job is to prove the engine says "not measured, because …" rather than a decorative zero.
"""

from __future__ import annotations

from typing import Any, Sequence

from .categories import CategoryResult
from .confidence import Confidence
from .regime import Regime
from .scoring import ScoreResult


def _fmt(v: Any, sign: bool = True) -> str:
    if v is None:
        return "  --"
    try:
        return f"{float(v):+6.2f}" if sign else f"{float(v):6.2f}"
    except (TypeError, ValueError):
        return f"{v}"


def render_text(
    *,
    record: dict[str, Any],
    categories: Sequence[CategoryResult],
    score: ScoreResult,
    confidence: Confidence,
    regime: Regime,
    levels: dict[str, dict[str, Any]],
    catalysts: Sequence[dict[str, Any]],
    triggers: Sequence[dict[str, Any]],
    policy: dict[str, Any],
    mode: str,
    dry_run: bool,
    data_as_of: str | None = None,
) -> str:
    lines: list[str] = []
    title = "MARKET OUTLOOK (DRY RUN)" if dry_run else "MARKET OUTLOOK"
    lines.append(f"{title} — {record['record_id']}  [{mode}]")
    lines.append(f"as of {record['as_of']}  ({record['session_clock']})")
    lines.append("")
    band = record.get("band") or "UNKNOWN"
    conf = record.get("confidence") or {}
    lines.append(
        f"S {_fmt(record.get('score')).strip():>7}   {band:<9}   confidence {conf.get('value')} {conf.get('band')}"
    )
    lines.append(
        "  confidence factors: "
        f"coverage {conf.get('coverage')} · freshness {conf.get('freshness')} · agreement {conf.get('agreement')} · "
        f"u_event {conf.get('u_event')} · hitrate {conf.get('hitrate')}"
    )
    if confidence.detractors:
        lines.append(
            "  largest detractors: "
            + ", ".join(f"{d['factor']} {d['value']} ({d['why']})" for d in confidence.detractors)
        )
    lines.append(
        f"  regime: VIX {regime.vix_value} {regime.vix_band or '--'} ({regime.vix_source or 'no clean feed'}) · "
        f"MRE {regime.mre_tier or '--'} {regime.mre_score if regime.mre_score is not None else ''}"
        f"{' · open episode ' + str(regime.episode_id) if regime.episode_id else ''}"
    )
    for note in regime.notes:
        lines.append(f"  regime note: {note}")
    for adj in score.adjustments:
        lines.append(f"  band: {adj}")
    if score.fomc_window:
        lines.append("  band: inside the FOMC window — a new RISK_ON is blocked")

    sc = record.get("scenarios") or {}
    lines.append("")
    lines.append("VIEW (scenario probabilities; ranges are ±1 / ±2 weekly ATR)")
    for name in ("base", "bull", "bear"):
        s = sc.get(name) or {}
        rng = s.get("spx_range") or {}
        lines.append(
            f"  {name:<5} {str(s.get('prob')):>6}   SPX "
            f"{_pct(rng.get('low_1atr'))} .. {_pct(rng.get('high_1atr'))} (2 ATR {_pct(rng.get('low_2atr'))} .. {_pct(rng.get('high_2atr'))})"
        )
    if sc.get("method"):
        lines.append(f"  method: {sc['method']}")

    lines.append("")
    lines.append("SCORECARD — 11 categories (weight prior→effective, sub-score, coverage, state)")
    for i, c in enumerate(categories, start=1):
        sub = "   --" if c.subscore is None else f"{c.subscore:+6.2f}"
        lines.append(
            f"  {i:>2} {c.key:<14} w {c.weight_prior:5.1f}→{c.weight_effective:5.1f}  C {sub}  "
            f"cov {c.coverage:4.2f}  {c.state:<9} {c.title}"
            + (f"  [{c.basis}]" if c.basis else "")
        )
        for ind in c.indicators:
            mark = "ok " if ind.available else "-- "
            val = "--" if not ind.available or ind.normalized is None else f"{ind.normalized:+.2f}"
            reason = f"  [{ind.refused_reason}]" if not ind.available and ind.refused_reason else (
                "  [stale]" if ind.stale else ""
            )
            lines.append(
                f"       {mark}{ind.key:<22} {(ind.label or '')[:24]:<24} s {val:>5}  "
                f"{ind.source or '-':<22} {ind.as_of or '-'}{reason}"
            )
            if ind.detail and not ind.available:
                lines.append(f"          {ind.detail}")

    unknown = [c for c in categories if c.state == "UNKNOWN"]
    lines.append("")
    if unknown:
        lines.append(f"UNKNOWN ({len(unknown)}) — excluded from S, renormalised out, never scored as zero:")
        for c in unknown:
            lines.append(f"  · {c.key}: {c.reason_unknown}")
    else:
        lines.append("UNKNOWN (0): every category was measured.")

    lines.append("")
    lines.append("LEVELS")
    for index, block in levels.items():
        if not block.get("support") and not block.get("resistance"):
            lines.append(f"  {index}: {block.get('reason') or 'no levels'}")
            continue
        sup = ", ".join(f"{r['level']:g} ({r['source']})" for r in block.get("support") or [])
        res = ", ".join(f"{r['level']:g} ({r['source']})" for r in block.get("resistance") or [])
        lines.append(f"  {index:<4} {block.get('basis')}  anchor {block.get('anchor')}")
        lines.append(f"        support    {sup or '--'}")
        lines.append(f"        resistance {res or '--'}")

    lines.append("")
    lines.append("CATALYSTS (next 7 days, ET)")
    if not catalysts:
        lines.append("  none scheduled on the calendar that covers this horizon")
    for c in catalysts:
        lines.append(
            f"  {c.get('date_et')} {c.get('time_et')}  {str(c.get('impact')):<4} {c.get('event'):<22} {c.get('name')}"
        )

    lines.append("")
    lines.append("WHAT WOULD CHANGE OUR VIEW")
    for t in triggers:
        lines.append(f"  · {t.get('trigger')} [threshold {t.get('threshold')}] — {t.get('status')}")

    lines.append("")
    lines.append("WHAT WE DO (template; the CIO renders it per account, the outlook never places an order)")
    act = record.get("actions_template") or {}
    lines.append(
        f"  {band}: tranches {act.get('tranche_release')} · reserve floor {act.get('reserve_floor_pct')}% · "
        f"{act.get('exposure_note')}"
    )
    lines.append(f"  MRE interplay: {act.get('mre_note')}")

    lines.append("")
    lines.append("NOT MEASURED — data as of footer")
    if data_as_of:
        lines.append(f"  data read as of {data_as_of}")
    lines.append(f"  record {record['record_id']} · policy {record['policy_version'][:12]} · engine {record['engine_commit'][:12]}")
    lines.append(f"  inputs snapshot {record['inputs_snapshot_hash'][:16]}")
    if dry_run:
        lines.append("  DRY RUN: nothing was written (no DB row, no runtime JSON, no delivery).")
    return "\n".join(lines)


def _pct(v: Any) -> str:
    if v is None:
        return "--"
    try:
        return f"{float(v):+.2f}%"
    except (TypeError, ValueError):
        return str(v)


def summary_line(record: dict[str, Any]) -> str:
    """One line for the runtime receipt / Telegram (≤ 300 chars by construction)."""
    conf = record.get("confidence") or {}
    return (
        f"OUTLOOK {record['record_id'].split(':')[1]} {record.get('band')} S {record.get('score')} "
        f"conf {conf.get('value')} {conf.get('band')}"
    )


__all__ = ["render_text", "summary_line"]
