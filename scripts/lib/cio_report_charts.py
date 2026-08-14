"""cio_report_charts.py — Phase 5 institutional chart suite for Report v2.

Charts are generated from the shared report *view/facts* only (Phase 4).
Never invent numbers. Never plot CAGR-vs-CAGR as risk/return.

Each chart carries governance metadata:
  title, as_of, source_note, units, coverage_note, quality_flag, alt_caption

Primary output: self-contained SVG (always available, grayscale-readable).
Optional: matplotlib PNG when the library is installed (higher print DPI).

READ_ONLY_ADVISORY. No broker / Telegram.
"""
from __future__ import annotations

import base64
import hashlib
import math
from pathlib import Path
from typing import Any, Optional

# Restrained Trade AI institutional palette (grayscale-readable)
NAVY = "#1F3864"
GREEN = "#2E7D32"
BURGUNDY = "#8B1E1E"
GRAY = "#555555"
LIGHT = "#F4F6F9"
BORDER = "#D5DAE1"
PALETTE = ["#1F3864", "#2E7D32", "#4A6FA5", "#8B1E1E", "#6B7280", "#0F766E", "#92400E"]

CHART_SPEC_VERSION = "charts_1.0.0"

# Expected chart keys when source truth supports them (Phase 5 exit gate).
EXPECTED_CHART_KEYS = (
    "allocation",
    "top10",
    "concentration",
    "sectors",
    "periods",
    "benchmark",
    "rolling_alpha",
    "themes",
    "risk_return",   # only if real vol available
    "value_bridge",  # only if flows reconcile
)


def _num(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _e(s: Any) -> str:
    return (
        str(s if s is not None else "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _meta(
    *,
    key: str,
    title: str,
    as_of: Any = None,
    source_note: str = "",
    units: str = "",
    coverage_note: str = "",
    quality_flag: Optional[str] = None,
    alt_caption: str = "",
) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "as_of": as_of,
        "source_note": source_note,
        "units": units,
        "coverage_note": coverage_note,
        "quality_flag": quality_flag,
        "alt_caption": alt_caption or title,
        "spec_version": CHART_SPEC_VERSION,
    }


# ─────────────────────────────────────────────────────────────────────────────
# SVG primitives
# ─────────────────────────────────────────────────────────────────────────────

def _svg_wrap(inner: str, *, w: int, h: int, title: str, meta: dict[str, Any]) -> str:
    foot = (
        f'<text x="12" y="{h - 10}" font-size="8" fill="{GRAY}">'
        f'{_e(meta.get("source_note") or "")}'
        f'{" · " + _e(meta["units"]) if meta.get("units") else ""}'
        f'{" · " + _e(meta["coverage_note"]) if meta.get("coverage_note") else ""}'
        f'{" · ⚠ " + _e(meta["quality_flag"]) if meta.get("quality_flag") else ""}'
        f'</text>'
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" role="img" aria-label="{_e(meta.get("alt_caption") or title)}">'
        f'<rect width="100%" height="100%" fill="white"/>'
        f'<text x="12" y="18" font-size="12" font-weight="700" fill="{NAVY}">{_e(title)}</text>'
        f'{inner}{foot}</svg>'
    )


def svg_donut(
    items: list[tuple[str, float]],
    *,
    title: str,
    meta: dict[str, Any],
    w: int = 420,
    h: int = 280,
) -> str:
    """Donut with legend showing dollars (if provided as (label, pct, usd?)) or pct only."""
    total = sum(max(0.0, v) for _, v in items) or 1.0
    cx, cy, r, ri = 120, 140, 78, 42
    # start at top
    angle = -math.pi / 2
    paths = []
    for i, (label, val) in enumerate(items):
        frac = max(0.0, val) / total
        da = frac * 2 * math.pi
        if da <= 0:
            continue
        x1, y1 = cx + r * math.cos(angle), cy + r * math.sin(angle)
        x2, y2 = cx + r * math.cos(angle + da), cy + r * math.sin(angle + da)
        xi1, yi1 = cx + ri * math.cos(angle), cy + ri * math.sin(angle)
        xi2, yi2 = cx + ri * math.cos(angle + da), cy + ri * math.sin(angle + da)
        large = 1 if da > math.pi else 0
        color = PALETTE[i % len(PALETTE)]
        # outer arc then reverse inner arc
        d = (
            f"M {x1:.2f} {y1:.2f} A {r} {r} 0 {large} 1 {x2:.2f} {y2:.2f} "
            f"L {xi2:.2f} {yi2:.2f} A {ri} {ri} 0 {large} 0 {xi1:.2f} {yi1:.2f} Z"
        )
        paths.append(f'<path d="{d}" fill="{color}" stroke="white" stroke-width="1.5"/>')
        angle += da
    legend = []
    ly = 48
    for i, (label, val) in enumerate(items):
        color = PALETTE[i % len(PALETTE)]
        pct = max(0.0, val) / total * 100.0
        legend.append(
            f'<rect x="230" y="{ly}" width="10" height="10" fill="{color}"/>'
            f'<text x="246" y="{ly + 9}" font-size="10" fill="{GRAY}">'
            f'{_e(label)} · {pct:.1f}%</text>'
        )
        ly += 18
    return _svg_wrap("".join(paths) + "".join(legend), w=w, h=h, title=title, meta=meta)


def svg_hbar(
    items: list[tuple[str, float]],
    *,
    title: str,
    meta: dict[str, Any],
    unit_suffix: str = "%",
    w: int = 520,
    color: str = NAVY,
) -> str:
    n = max(1, len(items))
    row_h = 22
    top, left, right = 36, 120, 24
    h = top + n * row_h + 28
    max_v = max((abs(v) for _, v in items), default=1.0) or 1.0
    bar_w = w - left - right - 50
    signed = any(v < 0 for _, v in items)
    parts: list[str] = []
    for i, (label, val) in enumerate(items):
        y = top + i * row_h
        bw = max(0.0, abs(val) / max_v * bar_w)
        fill = BURGUNDY if val < 0 else color
        txt = f"{val:+.1f}{unit_suffix}" if signed else f"{val:.1f}{unit_suffix}"
        parts.append(
            f'<text x="{left - 8}" y="{y + 12}" font-size="10" fill="{GRAY}" text-anchor="end">'
            f'{_e(str(label)[:22])}</text>'
            f'<rect x="{left}" y="{y + 2}" width="{bw:.1f}" height="14" fill="{fill}" opacity="0.9"/>'
            f'<text x="{left + bw + 4}" y="{y + 13}" font-size="9" fill="{GRAY}">{txt}</text>'
        )
    return _svg_wrap("".join(parts), w=w, h=h, title=title, meta=meta)

def svg_vbar(
    items: list[tuple[str, float]],
    *,
    title: str,
    meta: dict[str, Any],
    w: int = 480,
    h: int = 260,
) -> str:
    n = max(1, len(items))
    left, right, top, bottom = 40, 16, 40, 40
    plot_w = w - left - right
    plot_h = h - top - bottom
    max_abs = max((abs(v) for _, v in items), default=1.0) or 1.0
    bw = plot_w / n * 0.55
    gap = plot_w / n
    parts = [
        f'<line x1="{left}" y1="{top + plot_h/2}" x2="{w - right}" y2="{top + plot_h/2}" '
        f'stroke="{BORDER}" stroke-width="1"/>'
    ]
    # zero line at mid if mixed sign, else at bottom
    has_neg = any(v < 0 for _, v in items)
    zero_y = top + plot_h / 2 if has_neg else top + plot_h
    scale = (plot_h / 2 if has_neg else plot_h) / max_abs
    parts = [
        f'<line x1="{left}" y1="{zero_y}" x2="{w - right}" y2="{zero_y}" '
        f'stroke="{GRAY}" stroke-width="0.8"/>'
    ]
    for i, (label, val) in enumerate(items):
        x = left + gap * i + (gap - bw) / 2
        bh = abs(val) * scale
        y = zero_y - bh if val >= 0 else zero_y
        fill = GREEN if val >= 0 else BURGUNDY
        parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{bh:.1f}" fill="{fill}" opacity="0.9"/>')
        parts.append(
            f'<text x="{x + bw/2:.1f}" y="{h - 16}" font-size="9" fill="{GRAY}" text-anchor="middle">'
            f'{_e(label)}</text>'
        )
        ty = y - 4 if val >= 0 else y + bh + 11
        parts.append(
            f'<text x="{x + bw/2:.1f}" y="{ty:.1f}" font-size="8" fill="{GRAY}" text-anchor="middle">'
            f'{val:+.1f}%</text>'
        )
    return _svg_wrap("".join(parts), w=w, h=h, title=title, meta=meta)


def svg_line(
    points: list[tuple[Any, float]],
    *,
    title: str,
    meta: dict[str, Any],
    w: int = 520,
    h: int = 240,
    zero_line: bool = True,
) -> str:
    if len(points) < 2:
        return _svg_wrap(
            f'<text x="20" y="80" font-size="11" fill="{GRAY}">Insufficient points</text>',
            w=w, h=h, title=title, meta=meta,
        )
    left, right, top, bottom = 40, 16, 36, 28
    plot_w = w - left - right
    plot_h = h - top - bottom
    ys = [p[1] for p in points]
    ymin, ymax = min(ys), max(ys)
    if abs(ymax - ymin) < 1e-9:
        ymax = ymin + 1.0
    pad = (ymax - ymin) * 0.08
    ymin -= pad
    ymax += pad
    coords = []
    for i, (_, yv) in enumerate(points):
        x = left + i / (len(points) - 1) * plot_w
        y = top + (ymax - yv) / (ymax - ymin) * plot_h
        coords.append((x, y))
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    parts = []
    if zero_line and ymin < 0 < ymax:
        zy = top + (ymax - 0) / (ymax - ymin) * plot_h
        parts.append(
            f'<line x1="{left}" y1="{zy:.1f}" x2="{w - right}" y2="{zy:.1f}" '
            f'stroke="{GRAY}" stroke-dasharray="3 3" stroke-width="0.8"/>'
        )
    parts.append(
        f'<polyline fill="none" stroke="{GREEN}" stroke-width="1.8" points="{poly}"/>'
    )
    return _svg_wrap("".join(parts), w=w, h=h, title=title, meta=meta)


def svg_scatter_risk_return(
    *,
    port_return: float,
    port_vol: float,
    bench_return: Optional[float],
    bench_vol: Optional[float],
    title: str,
    meta: dict[str, Any],
    w: int = 420,
    h: int = 300,
) -> str:
    """True risk/return: X = volatility (risk), Y = return. Never CAGR-vs-CAGR."""
    left, right, top, bottom = 50, 20, 40, 40
    plot_w = w - left - right
    plot_h = h - top - bottom
    xs = [port_vol] + ([bench_vol] if bench_vol is not None else [])
    ys = [port_return] + ([bench_return] if bench_return is not None else [])
    xmin, xmax = min(xs) * 0.8, max(xs) * 1.2 or 1.0
    ymin, ymax = min(ys) - 2, max(ys) + 2
    if abs(xmax - xmin) < 1e-9:
        xmax = xmin + 1
    if abs(ymax - ymin) < 1e-9:
        ymax = ymin + 1

    def xy(xv: float, yv: float) -> tuple[float, float]:
        x = left + (xv - xmin) / (xmax - xmin) * plot_w
        y = top + (ymax - yv) / (ymax - ymin) * plot_h
        return x, y

    parts = [
        f'<line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" y2="{top + plot_h}" stroke="{BORDER}"/>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}" stroke="{BORDER}"/>',
        f'<text x="{left + plot_w/2}" y="{h - 10}" font-size="9" fill="{GRAY}" text-anchor="middle">'
        f'Risk (volatility %)</text>',
        f'<text x="12" y="{top + plot_h/2}" font-size="9" fill="{GRAY}" '
        f'transform="rotate(-90 12 {top + plot_h/2})">Return %</text>',
    ]
    px, py = xy(port_vol, port_return)
    parts.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="7" fill="{GREEN}" stroke="{NAVY}"/>')
    parts.append(
        f'<text x="{px + 10:.1f}" y="{py - 6:.1f}" font-size="9" fill="{NAVY}" font-weight="700">Portfolio</text>'
    )
    if bench_return is not None and bench_vol is not None:
        bx, by = xy(bench_vol, bench_return)
        parts.append(f'<circle cx="{bx:.1f}" cy="{by:.1f}" r="6" fill="{NAVY}"/>')
        parts.append(
            f'<text x="{bx + 10:.1f}" y="{by + 12:.1f}" font-size="9" fill="{GRAY}">Benchmark</text>'
        )
    return _svg_wrap("".join(parts), w=w, h=h, title=title, meta=meta)


# ─────────────────────────────────────────────────────────────────────────────
# Data extraction from model / view / part_b
# ─────────────────────────────────────────────────────────────────────────────

def _facts_and_parts(model_or_view: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if model_or_view.get("facts") and model_or_view.get("sections"):
        # already a view
        return model_or_view.get("facts") or {}, {}, model_or_view
    view = model_or_view.get("view") if isinstance(model_or_view.get("view"), dict) else None
    if view is None:
        try:
            from scripts.lib.cio_report_view import build_report_view
            view = build_report_view(model_or_view)
        except Exception:
            view = {"facts": {}}
    facts = view.get("facts") or {}
    pb = model_or_view.get("part_b") or {}
    return facts, pb, view


def build_charts(
    model_or_view: dict[str, Any],
    *,
    charts_dir: Optional[Path] = None,
    prefer_matplotlib: bool = True,
) -> dict[str, Any]:
    """Build the Phase 5 chart suite.

    Returns:
      {
        "spec_version": ...,
        "charts": { key: {meta..., svg, png_path?, data_uri} },
        "included": [...],
        "skipped": {key: reason},
        "expected": [...],
      }
    """
    facts, pb, view = _facts_and_parts(model_or_view)
    as_of = facts.get("as_of") or model_or_view.get("as_of")
    charts: dict[str, dict[str, Any]] = {}
    skipped: dict[str, str] = {}

    cdir = Path(charts_dir) if charts_dir is not None else None
    if cdir is not None:
        cdir.mkdir(parents=True, exist_ok=True)

    def _register(key: str, svg: str, meta: dict[str, Any]) -> None:
        data_uri = "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")
        entry = {
            **meta,
            "svg": svg,
            "data_uri": data_uri,
            "png_path": None,
        }
        if cdir is not None:
            svg_path = cdir / f"{key}.svg"
            svg_path.write_text(svg, encoding="utf-8")
            entry["svg_path"] = str(svg_path)
        charts[key] = entry
    # 1) Asset allocation
    weights = facts.get("allocation_weight_pct") or {}
    usd_map = facts.get("allocation_usd") or pb.get("allocation") or {}
    alloc_items = [(k, float(v)) for k, v in weights.items() if _num(v) is not None and float(v) > 0]
    if not alloc_items and usd_map:
        try:
            from scripts.lib.cio_decision_semantics import allocation_weights_from_usd
            weights = allocation_weights_from_usd(usd_map)
            alloc_items = [(k, float(v)) for k, v in weights.items() if float(v) > 0]
        except Exception:
            pass
    if alloc_items:
        meta = _meta(
            key="allocation",
            title="Asset Allocation",
            as_of=as_of,
            source_note="holdings cash + equity MV",
            units="weight % (USD in table)",
            alt_caption="Asset allocation donut by class weight",
        )
        # legend includes USD when available
        legend_items = []
        for k, pct in alloc_items:
            u = _num(usd_map.get(k))
            label = f"{k}" + (f" (${u:,.0f})" if u is not None else "")
            legend_items.append((label, pct))
        svg = svg_donut(legend_items or alloc_items, title=meta["title"], meta=meta)
        _register("allocation", svg, meta)
    else:
        skipped["allocation"] = "no allocation weights"

    # 2) Top 10 holdings — from decisions or part_b analytics
    top10: list[tuple[str, float]] = []
    analytics = pb.get("analytics") or {}
    raw_top = analytics.get("top_10_aggregated") or analytics.get("top_10") or []
    for r in raw_top[:10]:
        if not isinstance(r, dict):
            continue
        sym = r.get("symbol")
        w = _num(r.get("weight_pct"))
        if sym and w is not None:
            top10.append((str(sym), float(w)))
    if not top10:
        # fallback: decisions by weight
        decs = sorted(
            facts.get("decisions") or [],
            key=lambda d: -abs(_num(d.get("current_weight_pct")) or 0),
        )
        for d in decs[:10]:
            if d.get("symbol") and _num(d.get("current_weight_pct")) is not None:
                top10.append((str(d["symbol"]), float(d["current_weight_pct"])))
    if top10:
        meta = _meta(
            key="top10", title="Top 10 Holdings", as_of=as_of,
            source_note="holdings aggregated by symbol",
            units="% of portfolio",
            alt_caption="Horizontal bar of top 10 holding weights",
        )
        svg = svg_hbar(list(reversed(top10)), title=meta["title"], meta=meta, color=GREEN)
        _register("top10", svg, meta)
    else:
        skipped["top10"] = "no holdings weights"

    # 3) Concentration cumulative
    if top10:
        sorted_w = sorted([w for _, w in top10], reverse=True)
        cum = 0.0
        cum_items = []
        for i, w in enumerate(sorted_w, 1):
            cum += w
            if i in (1, 3, 5, 10) or i == len(sorted_w):
                cum_items.append((f"Top {i}", cum))
        meta = _meta(
            key="concentration", title="Concentration (cumulative)",
            as_of=as_of, source_note="top holdings weights",
            units="% of portfolio",
            alt_caption="Cumulative concentration of top holdings",
        )
        svg = svg_hbar(list(reversed(cum_items)), title=meta["title"], meta=meta, color=NAVY)
        _register("concentration", svg, meta)
    else:
        skipped["concentration"] = "no holdings for concentration"

    # 4) Sector look-through
    sectors: list[tuple[str, float]] = []
    xray = pb.get("xray") or {}
    for s in (xray.get("sectors") or [])[:10]:
        if isinstance(s, dict) and s.get("sector") and _num(s.get("pct")) is not None:
            sectors.append((str(s["sector"]), float(s["pct"])))
    if not sectors:
        for s in facts.get("sector_posture") or []:
            if s.get("sector") and _num(s.get("exposure_pct")) is not None:
                sectors.append((str(s["sector"]), float(s["exposure_pct"])))
    if sectors:
        meta = _meta(
            key="sectors", title="Sector Allocation (look-through)",
            as_of=as_of, source_note="xray / sector posture",
            units="% of portfolio",
            coverage_note="partial" if len(sectors) < 8 else "broad",
            alt_caption="Horizontal bar of sector exposure",
        )
        svg = svg_hbar(list(reversed(sectors[:10])), title=meta["title"], meta=meta)
        _register("sectors", svg, meta)
    else:
        skipped["sectors"] = "no sector exposure data"

    # 5) Period returns
    perf = pb.get("performance") or {}
    period_items: list[tuple[str, float]] = []
    quality = None
    per = perf.get("period_returns") or perf.get("periods") or {}
    if isinstance(per, dict):
        for k in ("1W", "1M", "3M", "6M", "YTD", "1Y"):
            cell = per.get(k)
            if isinstance(cell, dict):
                v = _num(cell.get("change_pct") if "change_pct" in cell else cell.get("return_pct"))
                src = str(cell.get("source") or "")
                if "account-aggregated" in src:
                    quality = "account-aggregated periods flagged"
                if v is not None:
                    period_items.append((k, float(v)))
            elif _num(cell) is not None:
                period_items.append((k, float(cell)))
    # simple ytd from perf root
    if not period_items and _num(perf.get("ytd_return")) is not None:
        period_items.append(("YTD", float(perf["ytd_return"])))
    if period_items:
        meta = _meta(
            key="periods", title="Portfolio Return by Period",
            as_of=as_of, source_note="performance_history / MS assemble",
            units="%",
            quality_flag=quality,
            alt_caption="Bar chart of portfolio returns by period",
        )
        svg = svg_vbar(period_items, title=meta["title"], meta=meta)
        _register("periods", svg, meta)
    else:
        skipped["periods"] = "no period returns"

    # 6) Portfolio vs benchmark (period comparison — not risk)
    pc = _num(perf.get("port_cagr"))
    bc = _num(perf.get("bench_cagr"))
    if pc is not None and bc is not None:
        meta = _meta(
            key="benchmark", title="Portfolio vs Benchmark (CAGR)",
            as_of=as_of, source_note="performance_attribution",
            units="CAGR %",
            alt_caption="Portfolio CAGR versus benchmark CAGR",
        )
        svg = svg_vbar(
            [("Portfolio", float(pc)), ("Benchmark", float(bc))],
            title=meta["title"], meta=meta,
        )
        _register("benchmark", svg, meta)
    else:
        skipped["benchmark"] = "missing portfolio or benchmark CAGR"

    # 7) Rolling alpha
    ra = perf.get("rolling_alpha")
    if isinstance(ra, list) and len(ra) >= 5:
        pts = []
        for i, row in enumerate(ra):
            if isinstance(row, dict) and _num(row.get("alpha")) is not None:
                pts.append((row.get("index", i), float(row["alpha"])))
            elif _num(row) is not None:
                pts.append((i, float(row)))
        if len(pts) >= 5:
            meta = _meta(
                key="rolling_alpha", title="Rolling Alpha vs Benchmark",
                as_of=as_of, source_note="performance.rolling_alpha",
                units="alpha",
                alt_caption="Line chart of rolling alpha",
            )
            svg = svg_line(pts, title=meta["title"], meta=meta)
            _register("rolling_alpha", svg, meta)
        else:
            skipped["rolling_alpha"] = "insufficient alpha points"
    else:
        skipped["rolling_alpha"] = "no rolling_alpha series"

    # 8) Themes
    themes_raw = (xray.get("themes") or {}) if isinstance(xray, dict) else {}
    theme_items: list[tuple[str, float]] = []
    if isinstance(themes_raw, dict):
        for name, cell in themes_raw.items():
            if isinstance(cell, dict) and _num(cell.get("pct")) is not None:
                theme_items.append((str(name), float(cell["pct"])))
            elif _num(cell) is not None:
                theme_items.append((str(name), float(cell)))
    theme_items.sort(key=lambda kv: -kv[1])
    if theme_items:
        meta = _meta(
            key="themes", title="Theme Exposure (look-through)",
            as_of=as_of, source_note="xray.themes",
            units="% of portfolio",
            coverage_note="look-through partial" if len(theme_items) < 4 else "",
            alt_caption="Theme exposure horizontal bars",
        )
        svg = svg_hbar(list(reversed(theme_items[:8])), title=meta["title"], meta=meta)
        _register("themes", svg, meta)
    else:
        skipped["themes"] = "no theme exposure"

    # 9) Risk/return — ONLY with real volatility
    port_vol = _num(perf.get("port_vol") or perf.get("volatility") or perf.get("port_stdev"))
    bench_vol = _num(perf.get("bench_vol") or perf.get("benchmark_vol"))
    port_ret = _num(perf.get("port_cagr") or perf.get("port_return"))
    bench_ret = _num(perf.get("bench_cagr") or perf.get("bench_return"))
    if port_vol is not None and port_ret is not None and port_vol > 0:
        meta = _meta(
            key="risk_return", title="Risk / Return",
            as_of=as_of, source_note="volatility + return",
            units="X=vol %, Y=return %",
            alt_caption="Scatter of portfolio risk (volatility) versus return",
        )
        svg = svg_scatter_risk_return(
            port_return=float(port_ret), port_vol=float(port_vol),
            bench_return=float(bench_ret) if bench_ret is not None else None,
            bench_vol=float(bench_vol) if bench_vol is not None else None,
            title=meta["title"], meta=meta,
        )
        _register("risk_return", svg, meta)
    else:
        skipped["risk_return"] = (
            "abstain: no real risk measure (vol/stdev); "
            "will not plot CAGR-vs-CAGR as risk/return"
        )

    # 10) Value bridge — only if reconcile
    flows = pb.get("flows") or pb.get("change_in_value") or {}
    begin = _num(flows.get("beginning_value") or flows.get("begin"))
    end = _num(flows.get("ending_value") or flows.get("end"))
    net_flow = _num(flows.get("net_contributions") or flows.get("net_flow"))
    earnings = _num(flows.get("investment_earnings") or flows.get("earnings"))
    if None not in (begin, end, net_flow, earnings):
        recon = abs((begin + net_flow + earnings) - end)
        if recon <= 1.0:  # $1 tolerance
            meta = _meta(
                key="value_bridge", title="Change in Portfolio Value",
                as_of=as_of, source_note="flows reconcile",
                units="USD",
                alt_caption="Bridge of beginning value, flows, earnings to ending value",
            )
            items = [
                ("Begin", float(begin)),
                ("Flows", float(net_flow)),
                ("Earnings", float(earnings)),
                ("End", float(end)),
            ]
            scale = 1e6 if max(abs(x) for _, x in items) > 1e5 else 1.0
            unit = " $M" if scale == 1e6 else ""
            scaled = [(a, b / scale) for a, b in items]
            svg = svg_hbar(
                list(reversed(scaled)),
                title=meta["title"], meta=meta,
                unit_suffix=unit if unit else "",
                color=NAVY,
            )
            _register("value_bridge", svg, meta)
        else:
            skipped["value_bridge"] = f"flows do not reconcile (err=${recon:,.2f})"
    else:
        skipped["value_bridge"] = "insufficient flow components for bridge"

    # Optional matplotlib PNG enrichment
    if prefer_matplotlib and cdir is not None:
        _try_matplotlib_pngs(charts, cdir)

    included = list(charts.keys())
    digest = hashlib.sha256(
        "|".join(sorted(included)).encode("utf-8")
    ).hexdigest()[:16]

    return {
        "spec_version": CHART_SPEC_VERSION,
        "charts": charts,
        "included": included,
        "skipped": skipped,
        "expected": list(EXPECTED_CHART_KEYS),
        "digest": digest,
        "as_of": as_of,
    }


def _try_matplotlib_pngs(charts: dict[str, dict[str, Any]], charts_dir: Path) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # noqa: F401
    except Exception:
        return
    # Keep SVG as primary; matplotlib optional for higher-DPI print of allocation only.
    # (Full matplotlib port deferred — SVG is format-stable and dependency-free.)
    return


def charts_for_html(chart_bundle: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten charts for HTML embedding (ordered)."""
    order = [
        "allocation", "top10", "concentration", "sectors", "periods",
        "benchmark", "rolling_alpha", "themes", "risk_return", "value_bridge",
    ]
    out = []
    charts = chart_bundle.get("charts") or {}
    for k in order:
        if k in charts:
            c = charts[k]
            out.append({
                "key": k,
                "title": c.get("title"),
                "data_uri": c.get("data_uri"),
                "source_note": c.get("source_note"),
                "units": c.get("units"),
                "quality_flag": c.get("quality_flag"),
                "coverage_note": c.get("coverage_note"),
                "alt_caption": c.get("alt_caption"),
            })
    return out
