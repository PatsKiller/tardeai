"""pdf_generator.py — Trade AI PDF report generator using ReportLab.

Sections:
  1. Cover header (run window, date, timestamp)
  2. Executive summary (counts, top movers)
  3. Delta section (what changed since last run)
  4. Full scorecard table (all scored tickers)
  5. GO-tier ticker cards (top 5 — detailed per-ticker breakdown)
  6. Catalyst tape (all headlines per ticker)
  7. ThinkorSwim export reference block
"""
from __future__ import annotations
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)


# ── Color palette ─────────────────────────────────────────────────────────────
C_BLACK       = colors.HexColor("#0D0D0D")
C_WHITE       = colors.white
C_ACCENT_BLUE = colors.HexColor("#1A73E8")
C_GO_GREEN    = colors.HexColor("#0F9D58")
C_WAIT_AMBER  = colors.HexColor("#F4B400")
C_AVOID_RED   = colors.HexColor("#DB4437")
C_BG_DARK     = colors.HexColor("#1E1E2E")
C_BG_CARD     = colors.HexColor("#2A2A3E")
C_TEXT_MUTED  = colors.HexColor("#9A9AB0")
C_TABLE_HDR   = colors.HexColor("#2C2C44")
C_TABLE_ALT   = colors.HexColor("#252535")
C_TABLE_NORM  = colors.HexColor("#1E1E2E")

DECISION_COLORS = {"GO": C_GO_GREEN, "WAIT": C_WAIT_AMBER, "AVOID": C_AVOID_RED}
GRADE_COLORS    = {"A_plus": C_GO_GREEN, "A": C_GO_GREEN, "B": C_WAIT_AMBER, "C": C_AVOID_RED, "D": C_AVOID_RED}

# ── Styles ────────────────────────────────────────────────────────────────────

def _build_styles() -> Dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    def s(name, **kw):
        return ParagraphStyle(name, **kw)

    return {
        "title": s("TitleStyle", fontName="Helvetica-Bold", fontSize=22,
                   textColor=C_WHITE, alignment=TA_CENTER, spaceAfter=6),
        "subtitle": s("SubtitleStyle", fontName="Helvetica", fontSize=10,
                      textColor=C_TEXT_MUTED, alignment=TA_CENTER, spaceAfter=16),
        "section_header": s("SectionHeader", fontName="Helvetica-Bold", fontSize=13,
                             textColor=C_ACCENT_BLUE, spaceBefore=14, spaceAfter=6),
        "ticker_name": s("TickerName", fontName="Helvetica-Bold", fontSize=14,
                         textColor=C_WHITE, spaceBefore=10, spaceAfter=2),
        "body": s("Body", fontName="Helvetica", fontSize=9,
                  textColor=C_WHITE, spaceAfter=4, leading=13),
        "body_muted": s("BodyMuted", fontName="Helvetica", fontSize=8,
                        textColor=C_TEXT_MUTED, spaceAfter=3, leading=12),
        "narrative": s("Narrative", fontName="Helvetica-Oblique", fontSize=9,
                       textColor=colors.HexColor("#D0D0E8"), spaceAfter=6,
                       leading=14, leftIndent=8),
        "pill_go":   s("PillGO",   fontName="Helvetica-Bold", fontSize=9, textColor=C_GO_GREEN),
        "pill_wait": s("PillWAIT", fontName="Helvetica-Bold", fontSize=9, textColor=C_WAIT_AMBER),
        "pill_avoid":s("PillAVOID",fontName="Helvetica-Bold", fontSize=9, textColor=C_AVOID_RED),
        "catalyst_head": s("CatHead", fontName="Helvetica-Bold", fontSize=9,
                           textColor=C_ACCENT_BLUE, spaceAfter=2),
        "catalyst_body": s("CatBody", fontName="Helvetica", fontSize=8,
                           textColor=C_TEXT_MUTED, spaceAfter=4, leading=12),
    }


# ── Helper builders ───────────────────────────────────────────────────────────

def _hr(story, color=C_ACCENT_BLUE, thickness=0.5):
    story.append(HRFlowable(width="100%", thickness=thickness, color=color, spaceAfter=6))

def _section(story, title: str, styles: Dict):
    story.append(Spacer(1, 8))
    story.append(Paragraph(title, styles["section_header"]))
    _hr(story)

def _decision_pill(decision: str, styles: Dict) -> Paragraph:
    style_key = f"pill_{decision}" if decision in ("GO", "WAIT") else "pill_avoid"
    label = f"[ {decision} ]"
    return Paragraph(label, styles.get(style_key, styles["body"]))

def _score_bar_text(score: int, max_score: int = 50) -> str:
    filled = round(score / max_score * 20)
    bar = "█" * filled + "░" * (20 - filled)
    return f"{bar}  {score}/{max_score}"

def _criteria_bar(criteria_met: int, criteria_total: int) -> str:
    filled = round(criteria_met / criteria_total * 15) if criteria_total else 0
    bar = "●" * filled + "○" * (15 - filled)
    return f"{bar}  {criteria_met}/{criteria_total} criteria"


# ── Scorecard table ───────────────────────────────────────────────────────────

def _build_scorecard_table(scored: List[Dict[str, Any]], styles: Dict) -> Table:
    headers = ["Symbol", "Score", "Grade", "Decision", "RVOL", "Price", "Chg%", "Gap%", "Float M", "Criteria", "Catalyst"]
    rows = [headers]
    for t in scored:
        top = t.get("top_catalyst") or {}
        cat_snippet = (top.get("title") or "—")[:45]
        rows.append([
            t["symbol"],
            str(t["score"]),
            t["grade"],
            t["decision"],
            f"{t.get('relative_volume', 0):.1f}x",
            f"${t.get('price', 0):.2f}",
            f"{t.get('change_percent', 0):+.1f}%",
            f"{t.get('gap_percent', 0):+.1f}%",
            f"{t.get('float_m', 0):.1f}M",
            f"{t.get('criteria_met', 0)}/{t.get('criteria_total', 9)}",
            cat_snippet,
        ])

    col_widths = [0.6*inch, 0.45*inch, 0.55*inch, 0.6*inch, 0.55*inch,
                  0.6*inch, 0.55*inch, 0.55*inch, 0.6*inch, 0.6*inch, 2.3*inch]

    tbl = Table(rows, colWidths=col_widths, repeatRows=1)
    style_cmds = [
        ("BACKGROUND",    (0,0), (-1,0),  C_TABLE_HDR),
        ("TEXTCOLOR",     (0,0), (-1,0),  C_ACCENT_BLUE),
        ("FONTNAME",      (0,0), (-1,0),  "Helvetica-Bold"),
        ("FONTSIZE",      (0,0), (-1,-1), 7.5),
        ("ALIGN",         (0,0), (-1,-1), "CENTER"),
        ("ALIGN",         (-1,0),(-1,-1), "LEFT"),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [C_TABLE_NORM, C_TABLE_ALT]),
        ("TEXTCOLOR",     (0,1), (-1,-1), C_WHITE),
        ("GRID",          (0,0), (-1,-1), 0.25, colors.HexColor("#3A3A5E")),
        ("TOPPADDING",    (0,0), (-1,-1), 3),
        ("BOTTOMPADDING", (0,0), (-1,-1), 3),
    ]
    # Colour decision column
    for i, row in enumerate(rows[1:], start=1):
        decision = row[3]
        c = DECISION_COLORS.get(decision, C_TEXT_MUTED)
        style_cmds.append(("TEXTCOLOR", (3, i), (3, i), c))
        style_cmds.append(("FONTNAME",  (3, i), (3, i), "Helvetica-Bold"))
    tbl.setStyle(TableStyle(style_cmds))
    return tbl


# ── Per-ticker GO card ────────────────────────────────────────────────────────

def _build_ticker_card(ticker: Dict[str, Any], styles: Dict, story: List) -> None:
    sym = ticker["symbol"]
    company = ticker.get("company", "")
    score = ticker["score"]
    grade = ticker["grade"]
    decision = ticker["decision"]

    # Header line
    hdr = f"{sym}"
    if company:
        hdr += f"  ·  {company}"
    story.append(Paragraph(hdr, styles["ticker_name"]))

    # Score bar + decision pill on same line via table
    score_bar = _score_bar_text(score)
    criteria_bar = _criteria_bar(ticker.get("criteria_met", 0), ticker.get("criteria_total", 9))
    pill_style = "pill_go" if decision == "GO" else ("pill_wait" if decision == "WAIT" else "pill_avoid")
    meta_rows = [
        [Paragraph(f"Score: {score_bar}", styles["body"]),
         Paragraph(f"{grade}  {decision}", styles[pill_style])],
        [Paragraph(criteria_bar, styles["body_muted"]), Paragraph("")],
    ]
    meta_tbl = Table(meta_rows, colWidths=[4.5*inch, 1.5*inch])
    meta_tbl.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING", (0,0), (-1,-1), 0),
        ("RIGHTPADDING", (0,0), (-1,-1), 0),
    ]))
    story.append(meta_tbl)

    # Market data row
    md_data = [
        ["Price", "Change", "Gap", "RVOL", "Float", "Volume"],
        [
            f"${ticker.get('price', 0):.2f}",
            f"{ticker.get('change_percent', 0):+.1f}%",
            f"{ticker.get('gap_percent', 0):+.1f}%",
            f"{ticker.get('relative_volume', 0):.1f}x",
            f"{ticker.get('float_m', 0):.1f}M",
            f"{int(ticker.get('volume', 0)):,}",
        ],
    ]
    md_tbl = Table(md_data, colWidths=[1*inch]*6)
    md_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,0), C_TABLE_HDR),
        ("TEXTCOLOR",     (0,0), (-1,0), C_TEXT_MUTED),
        ("FONTNAME",      (0,0), (-1,0), "Helvetica"),
        ("FONTSIZE",      (0,0), (-1,-1), 8),
        ("ALIGN",         (0,0), (-1,-1), "CENTER"),
        ("TEXTCOLOR",     (0,1), (-1,1), C_WHITE),
        ("FONTNAME",      (0,1), (-1,1), "Helvetica-Bold"),
        ("GRID",          (0,0), (-1,-1), 0.25, colors.HexColor("#3A3A5E")),
        ("TOPPADDING",    (0,0), (-1,-1), 3),
        ("BOTTOMPADDING", (0,0), (-1,-1), 3),
    ]))
    story.append(md_tbl)
    story.append(Spacer(1, 4))

    # Pillar breakdown
    pb = ticker.get("pillar_breakdown", {})
    pillar_names = {"catalyst": "Catalyst", "relative_volume": "RVOL",
                    "price_action": "Price Action", "float": "Float", "price_range": "Price Range"}
    max_pts = {"catalyst": 15, "relative_volume": 12, "price_action": 10, "float": 8, "price_range": 5}
    pillar_rows = [["Pillar", "Score", "Bar"]]
    for key, label in pillar_names.items():
        pts = pb.get(key, 0)
        maxp = max_pts[key]
        filled = round(pts / maxp * 10) if maxp else 0
        bar = "█" * filled + "░" * (10 - filled)
        pillar_rows.append([label, f"{pts}/{maxp}", bar])

    p_tbl = Table(pillar_rows, colWidths=[1.5*inch, 0.7*inch, 1.8*inch])
    p_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,0), C_TABLE_HDR),
        ("TEXTCOLOR",     (0,0), (-1,0), C_TEXT_MUTED),
        ("FONTNAME",      (0,0), (-1,0), "Helvetica"),
        ("FONTSIZE",      (0,0), (-1,-1), 8),
        ("ALIGN",         (0,0), (0,-1), "LEFT"),
        ("ALIGN",         (1,0), (2,-1), "CENTER"),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [C_TABLE_NORM, C_TABLE_ALT]),
        ("TEXTCOLOR",     (0,1), (-1,-1), C_WHITE),
        ("FONTNAME",      (2,1), (2,-1), "Courier"),
        ("TEXTCOLOR",     (2,1), (2,-1), C_GO_GREEN),
        ("GRID",          (0,0), (-1,-1), 0.25, colors.HexColor("#3A3A5E")),
        ("TOPPADDING",    (0,0), (-1,-1), 2),
        ("BOTTOMPADDING", (0,0), (-1,-1), 2),
    ]))
    story.append(p_tbl)
    story.append(Spacer(1, 4))

    # LLM narrative
    narrative = ticker.get("llm_narrative", "")
    if narrative:
        story.append(Paragraph(narrative, styles["narrative"]))

    # Top catalyst
    top = ticker.get("top_catalyst") or {}
    if top.get("title"):
        age = top.get("hours_old", "?")
        source = top.get("source", "?")
        impact = top.get("impact_tier", "")
        story.append(Paragraph(
            f"🔥 Catalyst ({age:.1f}h ago · {source} · {impact.replace('_', ' ').title()})",
            styles["catalyst_head"]
        ))
        story.append(Paragraph(top["title"], styles["body"]))
        if top.get("summary"):
            story.append(Paragraph(top["summary"][:200], styles["body_muted"]))

    story.append(Spacer(1, 8))
    _hr(story, color=colors.HexColor("#3A3A5E"), thickness=0.3)


# ── Catalyst tape ─────────────────────────────────────────────────────────────

def _build_catalyst_tape(scored: List[Dict[str, Any]], styles: Dict, story: List) -> None:
    _section(story, "Catalyst Tape — All Headlines", styles)
    for t in scored:
        catalysts = t.get("catalysts", [])
        if not catalysts:
            continue
        story.append(Paragraph(f"{t['symbol']}  ·  {t.get('company', '')}", styles["body"]))
        for cat in catalysts[:6]:
            age = cat.get("hours_old", 0)
            src = cat.get("source", "?")
            impact = cat.get("impact_tier", "low_impact").replace("_", " ").title()
            story.append(Paragraph(
                f"  [{impact}  {age:.1f}h  {src}]  {cat.get('title', '')}",
                styles["catalyst_body"]
            ))
        story.append(Spacer(1, 4))


# ── Main build ────────────────────────────────────────────────────────────────

def generate_pdf(
    scored_tickers: List[Dict[str, Any]],
    delta: Dict[str, Any],
    output_dir: Path,
    run_label: str,
    date_str: str,
    market_snapshot: Dict[str, Any] | None = None,
    calendar: Dict[str, Any] | None = None,
    options_summary: Dict[str, Any] | None = None,
) -> str:
    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = output_dir / f"trade_ai_{date_str}_{run_label}.pdf"
    styles = _build_styles()

    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=letter,
        rightMargin=0.5*inch, leftMargin=0.5*inch,
        topMargin=0.6*inch, bottomMargin=0.5*inch,
    )

    story = []
    market_snapshot = market_snapshot or {}
    calendar        = calendar or {}
    options_summary = options_summary or {}

    # ── Cover ──────────────────────────────────────────────────────────────
    story.append(Spacer(1, 0.2*inch))
    story.append(Paragraph("⚡ TRADE AI v10", styles["title"]))
    story.append(Paragraph(
        f"Run Window: {run_label}  ·  Date: {date_str}  ·  Generated: {datetime.now().strftime('%H:%M:%S ET')}",
        styles["subtitle"]
    ))
    _hr(story)

    # ── v11 Market Context Page ────────────────────────────────────────────
    if market_snapshot:
        _section(story, "Market Context", styles)

        # Index row: SPY / QQQ / IWM / VIX
        indices = market_snapshot.get("indices", {})
        vix     = market_snapshot.get("vix", {})
        breadth = market_snapshot.get("breadth_label", "Neutral")
        leader  = market_snapshot.get("sector_leader", {})
        laggard = market_snapshot.get("sector_laggard", {})

        idx_data = [["Index", "Price", "Change", "Trend"]]
        for sym in ["SPY", "QQQ", "IWM"]:
            d = indices.get(sym, {})
            pct = d.get("change_percent", 0)
            arr = d.get("trend_arrow", "→")
            idx_data.append([sym, f"${d.get('price',0):.2f}",
                             f"{pct:+.2f}%", arr])
        vix_pct = vix.get("change_percent", 0)
        idx_data.append(["VIX", f"{vix.get('price',0):.1f}",
                         f"{vix_pct:+.2f}% ({vix.get('direction','flat')})",
                         vix.get("trend_arrow", "→")])

        idx_tbl = Table(idx_data, colWidths=[0.8*inch, 0.9*inch, 1.5*inch, 0.6*inch])
        idx_tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,0), C_TABLE_HDR),
            ("TEXTCOLOR",     (0,0), (-1,0), C_ACCENT_BLUE),
            ("FONTNAME",      (0,0), (-1,0), "Helvetica-Bold"),
            ("FONTSIZE",      (0,0), (-1,-1), 9),
            ("ALIGN",         (0,0), (-1,-1), "CENTER"),
            ("ROWBACKGROUNDS",(0,1), (-1,-1), [C_TABLE_NORM, C_TABLE_ALT]),
            ("TEXTCOLOR",     (0,1), (-1,-1), C_WHITE),
            ("GRID",          (0,0), (-1,-1), 0.25, colors.HexColor("#3A3A5E")),
            ("TOPPADDING",    (0,0), (-1,-1), 3),
            ("BOTTOMPADDING", (0,0), (-1,-1), 3),
        ]))
        story.append(idx_tbl)
        story.append(Spacer(1, 6))

        # Breadth + leader/laggard line
        b_color = C_GO_GREEN if breadth == "Bullish" else (C_AVOID_RED if breadth == "Bearish" else C_WAIT_AMBER)
        story.append(Paragraph(
            f"Breadth: <font color='#{b_color.hexval()[2:]}' face='Helvetica-Bold'>{breadth}</font>"
            f"  ·  Leader: {leader.get('symbol','—')} {leader.get('change_percent',0):+.2f}%"
            f"  ·  Laggard: {laggard.get('symbol','—')} {laggard.get('change_percent',0):+.2f}%",
            styles["body"]
        ))
        story.append(Spacer(1, 6))

        # Sector heatmap table (2 rows of 5-6 tiles)
        sectors = market_snapshot.get("sectors", [])
        if sectors:
            tier_bg = {
                "strong-up":   colors.HexColor("#0d6e3f"),
                "up":          colors.HexColor("#1a9e5c"),
                "flat":        colors.HexColor("#3a3a5e"),
                "down":        colors.HexColor("#c0392b"),
                "strong-down": colors.HexColor("#7b0d0d"),
            }
            # Build 2-row table: 6 in row 1, 5 in row 2
            def _tile(s):
                pct = s.get("change_percent", 0)
                arr = s.get("trend_arrow", "→")
                sym = s["symbol"]
                return f"{sym}\n{pct:+.2f}% {arr}"
            row1 = [_tile(s) for s in sectors[:6]]
            row2 = [_tile(s) for s in sectors[6:]] + [""] * (6 - len(sectors[6:]))
            hm_data = [row1, row2]
            hm_tbl = Table(hm_data, colWidths=[1.15*inch]*6)
            hm_style = [
                ("FONTNAME",      (0,0), (-1,-1), "Helvetica-Bold"),
                ("FONTSIZE",      (0,0), (-1,-1), 7.5),
                ("ALIGN",         (0,0), (-1,-1), "CENTER"),
                ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
                ("TOPPADDING",    (0,0), (-1,-1), 5),
                ("BOTTOMPADDING", (0,0), (-1,-1), 5),
                ("TEXTCOLOR",     (0,0), (-1,-1), C_WHITE),
                ("GRID",          (0,0), (-1,-1), 0.5, colors.HexColor("#1E1E2E")),
            ]
            for row_i, sector_row in enumerate([sectors[:6], sectors[6:]]):
                for col_i, s in enumerate(sector_row):
                    bg = tier_bg.get(s.get("color_tier","flat"), colors.HexColor("#3a3a5e"))
                    hm_style.append(("BACKGROUND", (col_i, row_i), (col_i, row_i), bg))
            hm_tbl.setStyle(TableStyle(hm_style))
            story.append(hm_tbl)
            story.append(Spacer(1, 6))

        # Options summary line
        if options_summary.get("total_sweeps", 0) > 0:
            story.append(Paragraph(
                f"Options Flow: {options_summary.get('total_sweeps',0)} sweep(s)  ·  "
                f"{options_summary.get('bullish_count',0)} bullish / {options_summary.get('bearish_count',0)} bearish  ·  "
                f"{options_summary.get('total_premium','$0')} total premium",
                styles["body_muted"]
            ))

        # Calendar high-impact events
        hi_events = calendar.get("high_impact_events", [])
        wl_earn   = calendar.get("watchlist_earnings", [])
        if hi_events:
            story.append(Spacer(1, 4))
            cal_rows = [["Time", "Event", "Impact", "Forecast", "Prior"]]
            for e in hi_events[:5]:
                cal_rows.append([
                    e.get("date","")[-8:] if len(e.get("date","")) > 8 else e.get("date",""),
                    e.get("event","")[:50],
                    e.get("impact",""),
                    str(e.get("forecast","—")),
                    str(e.get("previous","—")),
                ])
            cal_tbl = Table(cal_rows, colWidths=[0.7*inch, 3.0*inch, 0.8*inch, 0.9*inch, 0.9*inch])
            cal_tbl.setStyle(TableStyle([
                ("BACKGROUND",    (0,0), (-1,0), C_TABLE_HDR),
                ("TEXTCOLOR",     (0,0), (-1,0), C_ACCENT_BLUE),
                ("FONTNAME",      (0,0), (-1,0), "Helvetica-Bold"),
                ("FONTSIZE",      (0,0), (-1,-1), 8),
                ("ALIGN",         (0,0), (-1,-1), "LEFT"),
                ("ROWBACKGROUNDS",(0,1), (-1,-1), [C_TABLE_NORM, C_TABLE_ALT]),
                ("TEXTCOLOR",     (0,1), (-1,-1), C_WHITE),
                ("GRID",          (0,0), (-1,-1), 0.25, colors.HexColor("#3A3A5E")),
                ("TOPPADDING",    (0,0), (-1,-1), 3),
                ("BOTTOMPADDING", (0,0), (-1,-1), 3),
            ]))
            story.append(cal_tbl)
        if wl_earn:
            story.append(Paragraph(
                f"⚠ Watchlist earnings today/tomorrow: {', '.join(wl_earn)}",
                styles["body"]
            ))

    # ── Executive summary ──────────────────────────────────────────────────
    go_list    = [t for t in scored_tickers if t.get("decision") == "GO"]
    wait_list  = [t for t in scored_tickers if t.get("decision") == "WAIT"]
    new_tickers = delta.get("new_tickers", [])
    events      = delta.get("events", [])

    _section(story, "Executive Summary", styles)
    summary_data = [
        ["Metric", "Value"],
        ["Total Tickers Scanned",    str(len(scored_tickers))],
        ["GO-Tier (≥40)",            str(len(go_list))],
        ["WAIT-Tier (30–39)",        str(len(wait_list))],
        ["New Tickers This Run",     str(len(new_tickers))],
        ["Delta Events",             str(len(events))],
        ["Top Score",                str(scored_tickers[0]["score"]) + f" ({scored_tickers[0]['symbol']})" if scored_tickers else "—"],
    ]
    s_tbl = Table(summary_data, colWidths=[3*inch, 2.5*inch])
    s_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,0), C_TABLE_HDR),
        ("TEXTCOLOR",     (0,0), (-1,0), C_TEXT_MUTED),
        ("FONTNAME",      (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",      (0,0), (-1,-1), 9),
        ("ALIGN",         (0,0), (-1,-1), "LEFT"),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [C_TABLE_NORM, C_TABLE_ALT]),
        ("TEXTCOLOR",     (0,1), (-1,-1), C_WHITE),
        ("GRID",          (0,0), (-1,-1), 0.25, colors.HexColor("#3A3A5E")),
        ("TOPPADDING",    (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ("LEFTPADDING",   (0,0), (-1,-1), 8),
    ]))
    story.append(s_tbl)

    # ── Delta section ──────────────────────────────────────────────────────
    if events:
        _section(story, "What Changed Since Last Run", styles)
        for evt in events[:25]:
            etype = evt.get("event", "")
            sym   = evt.get("symbol", "")
            if etype == "NEW_TICKER":
                line = f"🆕 NEW  {sym}  —  First appearance  ·  Score: {evt.get('score')}  ·  {evt.get('decision')}"
            elif etype == "GRADE_UP":
                line = f"📈 UP   {sym}  —  Score {evt.get('prev_score')} → {evt.get('score')} (+{evt.get('score_delta')})"
            elif etype == "GRADE_DOWN":
                line = f"📉 DOWN {sym}  —  Score {evt.get('prev_score')} → {evt.get('score')} ({evt.get('score_delta')})"
            elif etype == "NEW_CATALYST":
                titles = ", ".join((evt.get("titles") or [])[:2])
                line = f"🔥 CAT  {sym}  —  {evt.get('count')} new catalyst(s): {titles[:80]}"
            elif etype == "RVOL_THRESHOLD_CROSS":
                line = f"🚀 RVOL {sym}  —  Crossed {evt.get('threshold')}x threshold  (now {evt.get('rvol'):.1f}x)"
            elif etype == "NEW_CRITERIA_MET":
                line = f"✅ CRIT {sym}  —  New criteria met: {', '.join(evt.get('new_criteria', []))}"
            elif etype == "TICKER_FADED":
                line = f"👻 FADE {sym}  —  Dropped out of screeners  (was score {evt.get('last_score')})"
            else:
                line = f"• {etype}  {sym}"
            story.append(Paragraph(line, styles["body"]))

    # ── Scorecard table ────────────────────────────────────────────────────
    story.append(PageBreak())
    _section(story, "Full Scorecard", styles)
    story.append(_build_scorecard_table(scored_tickers, styles))

    # ── GO-tier cards (top 5) ──────────────────────────────────────────────
    if go_list:
        story.append(PageBreak())
        _section(story, f"GO-Tier Picks — Top {min(5, len(go_list))}", styles)
        for ticker in go_list[:5]:
            _build_ticker_card(ticker, styles, story)

    # ── Catalyst tape ──────────────────────────────────────────────────────
    tickers_with_cats = [t for t in scored_tickers if t.get("catalysts")]
    if tickers_with_cats:
        story.append(PageBreak())
        _build_catalyst_tape(tickers_with_cats, styles, story)

    # ── TOS export reference ───────────────────────────────────────────────
    _section(story, "ThinkorSwim Export", styles)
    tos_symbols = " ".join(t["symbol"] for t in go_list[:20])
    story.append(Paragraph(
        f"GO-tier symbols for manual TOS import:  {tos_symbols or '—'}",
        styles["body_muted"]
    ))
    story.append(Paragraph(
        f"Import the .tst file in: Charts → Watchlists → Import Watchlist",
        styles["body_muted"]
    ))

    doc.build(story)
    return str(pdf_path)
