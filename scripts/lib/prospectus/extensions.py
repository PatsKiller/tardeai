"""Personal and fund-aware prospectus extensions — the single entry point the assembler, writer and renderer call.

* ``attach``      — after ``domains.full_assemble``: the fund category / sector ETF / fund profile / house scenarios /
                    measured macro effect (``etf_profile``) and the operator's own history (``my_history``).
* ``prompt_lines``— extra writer instructions (the "My history" notes), appended to the prompt head.
* ``finalize``    — after the writer's output is validated: the guarded my_history writer note, the house scenario
                    range when the writer had no analyst target to anchor on, and the measured macro effect where the
                    writer left an effect empty.
* ``top_tables`` / ``bottom_tables`` / ``docx_top`` — the my_history and fund-profile tables for HTML / PDF / DOCX,
                    in the same table shape as ``tables.py``.

Each step is wrapped: a failure here is a recorded gap and never fails a prospectus. READ_ONLY_ADVISORY.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Optional

from . import etf_profile, my_history
from .tables import fmt


def attach(sources: Any, bundle: Any, *, cfg: dict | None = None, holding: dict | None = None,
           now: datetime | None = None, bars: list | None = None) -> None:
    from datetime import timezone
    now = now or datetime.now(timezone.utc)
    bars = list(bars or [])
    try:
        etf_profile.attach(sources, bundle, bars=bars, holding=holding, now=now)
    except Exception as exc:  # noqa: BLE001
        bundle.gaps.append(f"fund profile / house scenarios / macro effect not computed: {type(exc).__name__}")
    reader = my_history.reader_for(sources)
    if reader is None:
        bundle.blocks["my_history"] = {"schema": my_history.SCHEMA, "symbol": bundle.symbol, "scope": "unavailable",
                                       "gaps": ["no history reader for this source"]}
        return
    last = None
    for b in reversed(bars):
        if isinstance(b, dict) and b.get("close") is not None:
            last = b.get("close")
            break
    try:
        block = my_history.build(reader, bundle, holding=holding, now=now, last_close=last,
                                 cfg=(cfg or {}).get("my_history") or {})
        bundle.blocks["my_history"] = block
        bundle.cover("my_history", "used" if block.get("scope") in ("held", "previously_traded") else "empty",
                     detail="position store + trade_transactions + Rec Intelligence lifecycle + catalyst_events")
    except Exception as exc:  # noqa: BLE001
        bundle.blocks["my_history"] = {"schema": my_history.SCHEMA, "symbol": bundle.symbol, "scope": "unavailable",
                                       "gaps": [f"my history not built: {type(exc).__name__}: {str(exc)[:120]}"]}
        bundle.cover("my_history", "failed", detail=type(exc).__name__)


def prompt_lines(bundle: Any) -> list[str]:
    try:
        return my_history.prompt_lines(bundle)
    except Exception:  # noqa: BLE001
        return []


def finalize(blocks: dict, parsed: dict | None, bundle: Any, log: list[dict]) -> dict:
    """Called by ``generate.write`` once the writer output is validated; mutates and returns ``blocks``."""
    from .generate import allowed_values, guard_text
    values = allowed_values(bundle)

    def guard(text: str, where: str) -> str:
        return guard_text(text, values, where=where, log=log)

    try:
        my_history.apply_writer_note(blocks, parsed or {}, guard)
    except Exception as exc:  # noqa: BLE001
        log.append({"where": "notes.my_history", "reason": f"not applied: {type(exc).__name__}"})
    house = bundle.blocks.get("scenarios_house")
    sc = blocks.get("scenarios") or {}
    if house and not sc.get("cases"):
        blocks["scenarios"] = dict(house, gaps=list(house.get("gaps") or []) + [g for g in sc.get("gaps") or []
                                                                             if "analyst targets" not in g])
    blocks.pop("scenarios_house", None)
    macro = blocks.get("macro_sensitivity") or {}
    sens = macro.get("sensitivity") or {}
    effects = macro.setdefault("effects", {})
    for sid, row in sens.items():
        key = row.get("group")
        if key in ("rates", "inflation") and not effects.get(key) and row.get("effect"):
            effects[key] = f"measured — {row['effect']}"
    return blocks


# ── tables (HTML / PDF / DOCX share them) ─────────────────────────────────────────────────────────────────────────
def _money(v: Any) -> str:
    return fmt(v, "$")


ORIGIN_LABEL = {"watchlist": "Watch list", "directive": "Your directive", "proposal": "Proposal", "scan": "Screener",
                "screener": "Screener", "hermes_research": "Research", "research": "Research", "cio": "CIO",
                "cio_decision": "CIO", "claude_challenger": "Challenger review"}


def _origin(src: Any) -> str:
    return ORIGIN_LABEL.get(str(src), str(src).replace("_", " ")) if src else "Direct / manual"


def _num(v: Any, unit: str = "") -> str:
    if isinstance(v, float) and v.is_integer() and unit != "%":
        v = int(v)
    if isinstance(v, int) and not isinstance(v, bool) and unit != "%":
        return f"{v:,}"
    return fmt(v, unit)


def _signed_money(v: Any) -> str:
    if not isinstance(v, (int, float)):
        return "n/a"
    return f"{'+' if v >= 0 else '−'}${abs(v):,.2f}"


def history_tables(doc: dict) -> list[dict]:
    mh = (doc.get("blocks") or {}).get("my_history") or {}
    if mh.get("scope") not in ("held", "previously_traded"):
        return []
    sym = doc.get("symbol") or mh.get("symbol") or ""
    out = []
    tot = mh.get("totals") or {}
    lots = mh.get("open_lots") or []
    kpis = []
    if tot:
        kpis += [("Lifetime realized P/L", _signed_money(tot.get("realized_usd"))),
                 ("Round trips · won / lost", f"{tot.get('trips')} · {tot.get('wins')} / {tot.get('losses')}"),
                 ("Average win · average loss", f"{_signed_money(tot.get('avg_win_usd'))} · {_signed_money(tot.get('avg_loss_usd'))}"),
                 ("Best · worst trip", f"trip {(tot.get('best') or {}).get('trip')} {_signed_money((tot.get('best') or {}).get('realized_usd'))}"
                                      f" · trip {(tot.get('worst') or {}).get('trip')} {_signed_money((tot.get('worst') or {}).get('realized_usd'))}")]
    upl = [x["unrealized_usd"] for x in lots if isinstance(x.get("unrealized_usd"), (int, float))]
    if upl:
        kpis.insert(0, ("Open unrealized P/L", _signed_money(sum(upl))))
    held = [(x["shares"], x["avg_cost"]) for x in lots if isinstance(x.get("shares"), (int, float))
            and isinstance(x.get("avg_cost"), (int, float))]
    if held and sum(sh for sh, _ in held) > 0:
        sh = sum(sh for sh, _ in held)
        kpis.insert(0, ("Average cost (all accounts)", f"{_money(sum(a * c for a, c in held) / sh)} · {_num(sh)} sh"))
    wn = (mh.get("writer_note") or {}).get("summary")
    rows = [[x.get("account"), _num(x.get("shares")), _money(x.get("avg_cost")), _signed_money(x.get("unrealized_usd"))
             + (f" ({fmt(x.get('unrealized_pct'), '±%')})" if x.get("unrealized_pct") is not None else ""),
             f"{x['holding_days']}d" if x.get("holding_days") is not None else "n/a",
             (x.get("term") or "n/a") + ("" if x.get("lot_dating") == "fifo_reconciled" else " (dates unreconciled)"),
             x.get("tax_character") or "n/a"] for x in lots]
    out.append({"id": "my_history", "title": f"My history · your position in {sym}",
                "columns": ["Account", "Shares", "Avg cost", "Unrealized", "Held", "Term", "Tax"], "rows": rows
                or [["No open position", "", "", "", "", "", ""]], "kpis": kpis,
                "note": (wn + " " if wn else "") + "Accounts by name only. " + "; ".join((mh.get("gaps") or [])[:3])})
    trips = mh.get("trips") or []
    if trips:
        trows = []
        for t in trips:
            flags = []
            if (t.get("wash_sale") or {}).get("flag"):
                flags.append("wash-sale window")
            if t.get("stopped_out"):
                flags.append("stopped out")
            trows.append([str(t["trip"]), t.get("account"),
                          f"{t.get('entry_date') or 'n/a'} {_money(t.get('entry_price'))} → {t.get('exit_date') or 'n/a'} "
                          f"{_money(t.get('exit_price'))} · {_num(t.get('shares'))} sh · "
                          + (f"{t['hold_days']}d" if t.get("hold_days") is not None else "n/a"),
                          _signed_money(t.get("realized_usd")) + (f" ({fmt(t.get('realized_pct'), '±%')})" if t.get("realized_pct") is not None else ""),
                          fmt(t.get("r_multiple")),
                          " → ".join(_origin(x) for x in t.get("sources_before_entry") or []) or _origin(t.get("origin")),
                          ", ".join(flags) or ""])
        out.append({"id": "my_history_trips", "title": f"My round trips in {sym}",
                    "columns": ["Trip", "Account", "Entry → exit · shares · hold", "Realized", "R", "Why you got in", "Flags"],
                    "rows": trows, "note": (mh.get("tax") or {}).get("note") or ""})
    ev_rows = []
    windows = [(f"Trip {t['trip']}", t.get("while_held") or []) for t in trips]
    if mh.get("current_hold"):
        windows.append(("Now", mh["current_hold"].get("while_held") or []))
    for who, events in windows:
        for e in events:
            react = " / ".join(fmt(e.get(k), "±%") for k in ("next_day_pct", "five_day_pct"))
            what = e.get("headline") or (f"day move {fmt(e.get('move_pct'), '±%')}" if e.get("move_pct") is not None else e.get("kind"))
            ev_rows.append([who, e.get("date"), str(e.get("type") or e.get("kind") or "").replace("_", " "), what, react])
    if ev_rows:
        out.append({"id": "my_history_events", "title": "What happened while you held it",
                    "columns": ["Holding", "Date", "Event", "What", "Day-of / 5-session"], "rows": ev_rows[:40],
                    "note": (mh.get("method") or {}).get("reactions") or ""})
    stats = (mh.get("lessons") or {}).get("stats") or []
    notes = (mh.get("lessons") or {}).get("journal_notes") or []
    if stats or notes:
        lrows = [[s["label"], _num(s.get("value"), s.get("unit") or ""), s.get("n")] for s in stats]
        lrows += [[f"Journal lesson (trip {n['trip']})", n["lesson"], ""] for n in notes[:6]]
        wl = (mh.get("writer_note") or {}).get("lessons")
        out.append({"id": "my_history_lessons", "title": "Lessons from your trades", "columns": ["Pattern", "Value", "Trips"],
                    "rows": lrows, "note": (wl + " " if wl else "") + "Patterns in past trades, not advice."})
    return out


def fund_tables(doc: dict) -> list[dict]:
    fp = (doc.get("blocks") or {}).get("fund_profile") or {}
    if not fp:
        return []
    rows = [["Category", f"{fp.get('category') or 'n/a'} ({fp.get('category_basis') or 'n/a'})"],
            ["Sector exposure · sector ETF", f"{fp.get('sector') or 'broad'} · {fp.get('sector_etf') or 'none'}"],
            ["Peer funds", ", ".join(fp.get("peers") or []) or "n/a"],
            ["Expense ratio", fmt(fp.get("expense_ratio_pct"), "%") if fp.get("expense_ratio_pct") is None else f"{fp['expense_ratio_pct']:.2f}%"],
            ["Assets under management", fmt(fp.get("aum_usd"), "$")],
            ["Distribution yield · trailing 12m", f"{fmt(fp.get('dividend_yield_pct'), '%')} · {fmt(fp.get('ttm_distribution'), '$')}"],
            ["Last distribution · cadence · next (est.)", f"{fmt(fp.get('last_distribution'), '$')} on {fp.get('last_distribution_date') or 'n/a'}"
                                                         f" · {fp.get('distribution_cadence') or 'n/a'} · {fp.get('next_distribution_est') or 'n/a'}"],
            ["Analyst look-through upside", fmt(fp.get("analyst_look_through_pct"), "±%") + (f" ({fp.get('analyst_basis')})" if fp.get("analyst_basis") else "")]]
    for h in (fp.get("top_holdings") or [])[:10]:
        rows.append([f"Top holding: {h['name']}", fmt(h.get("weight_pct"), "%")])
    hist = fp.get("dividend_history") or []
    if hist:
        rows.append(["Distribution history", "; ".join(f"{h['ex_date']} {fmt(h['amount'], '$')}" for h in hist[:8])])
    return [{"id": "fund_profile", "title": "Fund profile", "columns": ["Measure", "Value"], "rows": rows,
             "note": "; ".join(fp.get("gaps") or [])}]


def top_tables(doc: dict) -> list[dict]:
    """Right after the verdict / header: the operator's own history."""
    try:
        return history_tables(doc)
    except Exception:  # noqa: BLE001 - a render problem here never breaks the document
        return []


def bottom_tables(doc: dict) -> list[dict]:
    try:
        return fund_tables(doc)
    except Exception:  # noqa: BLE001
        return []


def docx_tables(d: Any, tables: list[dict], *, muted_rgb: Optional[Callable] = None) -> None:
    """Write tables into a python-docx Document (same shape as render.docx's add_table)."""
    from docx.shared import Pt  # noqa: PLC0415
    for t in tables:
        d.add_heading(t["title"], level=1)
        for k, v in t.get("kpis") or []:
            kp = d.add_paragraph(f"{k}: {v}")
            for run in kp.runs:
                run.font.size = Pt(9)
        tbl = d.add_table(rows=1, cols=len(t["columns"]))
        tbl.style = "Light Grid Accent 1"
        for cell, label in zip(tbl.rows[0].cells, t["columns"]):
            cell.text = str(label)
        for row in t["rows"]:
            for cell, val in zip(tbl.add_row().cells, row):
                cell.text = "" if val is None else str(val)
        if t.get("note"):
            np_ = d.add_paragraph(t["note"])
            for run in np_.runs:
                run.font.size = Pt(8)
