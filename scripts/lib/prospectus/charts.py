"""Chart rendering from Prospectus@v1 ``charts[]``: inline SVG (themeable via CSS variables) and PNG (matplotlib).

Colors are the house design tokens (apps/command-center-v3/src/styles/tokens.css, CHART_HEX in designTokens.ts).
The SVG uses CSS variables so one document follows the reader's dark or light scheme; PNGs (PDF and DOCX) use the
light palette, which prints.
"""
from __future__ import annotations

from html import escape
import io
import re
from typing import Any

TOKENS = {
    "dark": {"bg": "#0f1117", "surface": "#171923", "surface2": "#1e2130", "border": "#2d3148", "text": "#eef0f6",
             "text2": "#c9cdda", "muted": "#9ea6ba", "success": "#34d27a", "warning": "#f5b83d", "danger": "#f26d6d",
             "info": "#7db4ff", "ai": "#c4a6ff",
             "chart": ["#7db4ff", "#34d27a", "#f5b83d", "#c4a6ff", "#f26d6d", "#5fd3d3"]},
    "light": {"bg": "#ffffff", "surface": "#f6f7fb", "surface2": "#eef0f5", "border": "#d5d9e3", "text": "#0f172a",
              "text2": "#1f2937", "muted": "#3f4a5f", "success": "#137236", "warning": "#8f5106", "danger": "#b91c1c",
              "info": "#1d4ed8", "ai": "#6d28d9",
              "chart": ["#1d4ed8", "#137236", "#8f5106", "#6d28d9", "#b91c1c", "#0f766e"]},
}
LINE_KINDS = ("stop", "entry", "target", "mean", "current")
KIND_TONE = {"stop": "var(--danger)", "entry": "var(--info)", "target": "var(--success)", "mean": "var(--ai)",
             "current": "var(--warning)"}
W, H, PAD_L, PAD_R, PAD_T, PAD_B = 640, 260, 56, 16, 28, 40


def _num(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _fmt(v: float) -> str:
    a = abs(v)
    if a >= 1e9:
        return f"{v / 1e9:.1f}B"
    if a >= 1e6:
        return f"{v / 1e6:.1f}M"
    if a >= 1e4:
        return f"{v / 1e3:.0f}k"
    return f"{v:.2f}" if a < 100 else f"{v:.0f}"


def _scale(lo: float, hi: float):
    if hi == lo:
        hi, lo = hi + 1, lo - 1
    pad = (hi - lo) * 0.08
    lo, hi = lo - pad, hi + pad
    return lo, hi, (lambda y: PAD_T + (hi - y) / (hi - lo) * (H - PAD_T - PAD_B))


MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}")


def line_axis(series: list[dict]) -> tuple[list[str], list[dict]]:
    """One common x axis for every line series: the union of their x values, sorted when they are ISO dates (input
    order otherwise). Series with no numeric point are dropped (an empty series is never drawn or listed)."""
    keep = [s for s in series if any(_num(p[1]) is not None for p in s.get("points") or [] if isinstance(p, (list, tuple)) and len(p) > 1)]
    xs: list[str] = []
    seen: set[str] = set()
    for s in keep:
        for p in s.get("points") or []:
            x = str(p[0])
            if x not in seen:
                seen.add(x)
                xs.append(x)
    if xs and all(_ISO_DAY.match(x) for x in xs):
        xs.sort()
    return xs, keep


def month_label(x: str) -> str:
    """'2026-01-14' -> 'Jan 26'; anything else unchanged (trimmed)."""
    if _ISO_DAY.match(x):
        return f"{MONTHS[int(x[5:7]) - 1]} {x[2:4]}"
    return x[:10]


def month_ticks(xs: list[str], want: int = 6) -> list[int]:
    """Evenly spaced tick indexes on month boundaries (first point of a month), at most ``want`` of them."""
    if not xs:
        return []
    if not all(_ISO_DAY.match(x) for x in xs):
        n = len(xs)
        return sorted({0, n // 2, n - 1}) if n > 2 else list(range(n))
    starts = [i for i, x in enumerate(xs) if i == 0 or x[:7] != xs[i - 1][:7]]
    if len(starts) > 2 and starts[1] - starts[0] < (len(xs) / len(starts)) / 2:
        starts = starts[1:]  # a stub first month would crowd the next label
    step = max(1, -(-len(starts) // want))
    return starts[::step]


def svg(chart: dict) -> str:
    """One chart as inline SVG. Strokes/fills reference --chart-N and token variables."""
    kind, series = chart.get("type"), chart.get("series") or []
    anns = [a for a in chart.get("annotations") or [] if _num(a.get("y")) is not None and a.get("kind") in LINE_KINDS]
    ys = [_num(p[1]) for s in series for p in s.get("points") or [] if _num(p[1]) is not None]
    ys += [_num(a["y"]) for a in anns]
    if not ys:
        return ""
    lo, hi, ty = _scale(min(ys + ([0.0] if kind == "bar" else [])), max(ys + ([0.0] if kind == "bar" else [])))
    out = [f'<svg class="pc-chart" viewBox="0 0 {W} {H}" role="img" aria-label="{escape(chart.get("title", ""))}" '
           f'xmlns="http://www.w3.org/2000/svg">']
    for i in range(5):  # gridlines + y labels
        y = lo + (hi - lo) * i / 4
        yy = ty(y)
        out.append(f'<line x1="{PAD_L}" x2="{W - PAD_R}" y1="{yy:.1f}" y2="{yy:.1f}" class="pc-grid"/>'
                   f'<text x="{PAD_L - 6}" y="{yy + 4:.1f}" class="pc-axis" text-anchor="end">{_fmt(y)}</text>')
    plot_w = W - PAD_L - PAD_R
    if kind == "line":
        xs, series = line_axis(series)
        pos = {x: i for i, x in enumerate(xs)}
        step = plot_w / max(1, len(xs) - 1)
        for si, s in enumerate(series):
            pts = [p for p in s.get("points") or [] if _num(p[1]) is not None and str(p[0]) in pos]
            pts.sort(key=lambda p: pos[str(p[0])])
            if len(pts) < 2:
                continue
            path = " ".join(f"{'M' if i == 0 else 'L'}{PAD_L + pos[str(p[0])] * step:.1f},{ty(_num(p[1])):.1f}" for i, p in enumerate(pts))
            out.append(f'<path d="{path}" fill="none" stroke="var(--chart-{si % 6 + 1})" stroke-width="2"/>')
        for idx in month_ticks(xs):
            out.append(f'<text x="{PAD_L + idx * step:.1f}" y="{H - 14}" class="pc-axis" text-anchor="middle">'
                       f'{escape(month_label(xs[idx]))}</text>')
    else:
        labels = []
        for s in series:
            for p in s.get("points") or []:
                if str(p[0]) not in labels:
                    labels.append(str(p[0]))
        group = plot_w / max(1, len(labels))
        bw = group * 0.7 / max(1, len(series))
        zero = ty(max(lo, min(0.0, hi))) if kind == "bar" else None
        for si, s in enumerate(series):
            vals = {str(p[0]): _num(p[1]) for p in s.get("points") or []}
            for li, label in enumerate(labels):
                v = vals.get(label)
                if v is None:
                    continue
                x = PAD_L + li * group + group * 0.15 + si * bw
                if kind == "range":
                    out.append(f'<circle cx="{x + bw / 2:.1f}" cy="{ty(v):.1f}" r="6" fill="var(--chart-{li % 6 + 1})"/>'
                               f'<text x="{x + bw / 2:.1f}" y="{ty(v) - 10:.1f}" class="pc-val" text-anchor="middle">{_fmt(v)}</text>')
                else:
                    top, bottom = sorted((ty(v), zero))
                    tone = f"var(--chart-{si % 6 + 1})" if len(series) > 1 else ("var(--danger)" if v < 0 else "var(--chart-1)")
                    out.append(f'<rect x="{x:.1f}" y="{top:.1f}" width="{bw:.1f}" height="{max(1.0, bottom - top):.1f}" '
                               f'rx="2" fill="{tone}"/><text x="{x + bw / 2:.1f}" y="{top - 4:.1f}" class="pc-val" '
                               f'text-anchor="middle">{_fmt(v)}</text>')
            if si == 0:
                for li, label in enumerate(labels):
                    out.append(f'<text x="{PAD_L + li * group + group / 2:.1f}" y="{H - 14}" class="pc-axis" '
                               f'text-anchor="middle">{escape(label[:18])}</text>')
        if kind == "range" and len(labels) >= 2:
            ys_r = [v for v in (_num(p[1]) for p in series[0]["points"]) if v is not None]
            out.insert(1, f'<line x1="{PAD_L}" x2="{W - PAD_R}" y1="{ty(min(ys_r)):.1f}" y2="{ty(max(ys_r)):.1f}" '
                          f'class="pc-range"/>')
    for a in anns:
        yy = ty(_num(a["y"]))
        tone = KIND_TONE.get(a.get("kind"), "var(--muted)")
        out.append(f'<line x1="{PAD_L}" x2="{W - PAD_R}" y1="{yy:.1f}" y2="{yy:.1f}" stroke="{tone}" '
                   f'stroke-dasharray="6 4" stroke-width="1.5"/><text x="{W - PAD_R - 4}" y="{yy - 4:.1f}" '
                   f'class="pc-ann" fill="{tone}" text-anchor="end">{escape(str(a.get("label", "")))} {_fmt(_num(a["y"]))}</text>')
    if len(series) > 1:  # legend: same colors as the lines, packed left to right
        x = PAD_L
        for si, s in enumerate(series):
            label = str(s.get("name", ""))[:20]
            out.append(f'<rect x="{x}" y="8" width="10" height="10" rx="2" fill="var(--chart-{si % 6 + 1})"/>'
                       f'<text x="{x + 14}" y="17" class="pc-axis">{escape(label)}</text>')
            x += 26 + 6 * len(label)
    out.append("</svg>")
    return "".join(out)


def png(chart: dict, *, theme: str = "light") -> bytes | None:
    """One chart as PNG bytes via matplotlib (Agg). None when matplotlib is unavailable or the chart is empty."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None
    t = TOKENS[theme]
    series = chart.get("series") or []
    fig, ax = plt.subplots(figsize=(6.4, 2.6), dpi=150)
    fig.patch.set_facecolor(t["bg"])
    ax.set_facecolor(t["bg"])
    for spine in ax.spines.values():
        spine.set_color(t["border"])
    ax.tick_params(colors=t["muted"], labelsize=7)
    ax.grid(True, color=t["border"], linewidth=0.5, alpha=0.7)
    ax.set_title(chart.get("title", ""), color=t["text"], fontsize=9, loc="left")
    drawn = False
    if chart.get("type") == "line":
        xs, series = line_axis(series)
        pos = {x: i for i, x in enumerate(xs)}
        for si, s in enumerate(series):
            pts = sorted((p for p in s.get("points") or [] if _num(p[1]) is not None and str(p[0]) in pos), key=lambda p: pos[str(p[0])])
            if pts:
                ax.plot([pos[str(p[0])] for p in pts], [_num(p[1]) for p in pts], color=t["chart"][si % 6], linewidth=1.6, label=s.get("name"))
                drawn = True
        ticks = month_ticks(xs)
        ax.set_xticks(ticks, [month_label(xs[k]) for k in ticks])
    else:
        labels = []
        for s in series:
            for p in s.get("points") or []:
                if str(p[0]) not in labels:
                    labels.append(str(p[0]))
        width = 0.7 / max(1, len(series))
        for si, s in enumerate(series):
            vals = {str(p[0]): _num(p[1]) for p in s.get("points") or []}
            xs = [i for i, lab in enumerate(labels) if vals.get(lab) is not None]
            vs = [vals[labels[i]] for i in xs]
            if not xs:
                continue
            if chart.get("type") == "range":
                ax.plot(xs, vs, color=t["border"], linewidth=1)
                ax.scatter(xs, vs, color=[t["chart"][i % 6] for i in xs], zorder=3)
            else:
                colors = [t["danger"] if v < 0 and len(series) == 1 else t["chart"][si % 6] for v in vs]
                ax.bar([x + si * width - 0.35 + width / 2 for x in xs], vs, width=width, color=colors, label=s.get("name"))
            drawn = True
        ax.set_xticks(range(len(labels)), [lab[:18] for lab in labels], rotation=0)
    for a in chart.get("annotations") or []:
        y = _num(a.get("y"))
        if y is not None and a.get("kind") in LINE_KINDS:
            color = t[KIND_TONE.get(a.get("kind"), "var(--muted)")[6:-1]]
            ax.axhline(y, color=color, linestyle="--", linewidth=1)
            ax.annotate(f"{a.get('label', '')} {_fmt(y)}", xy=(1, y), xycoords=("axes fraction", "data"),
                        ha="right", va="bottom", fontsize=7, color=color)
    if len(series) > 1:
        ax.legend(fontsize=7, facecolor=t["bg"], edgecolor=t["border"], labelcolor=t["text2"])
    if not drawn:
        plt.close(fig)
        return None
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", facecolor=t["bg"])
    plt.close(fig)
    return buf.getvalue()
