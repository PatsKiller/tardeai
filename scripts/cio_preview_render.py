#!/usr/bin/env python3
"""Render a Home-CIO preview HTML FROM A CIO OVERNIGHT BRIEF DOCUMENT — never from prose (LQ-20261107-1318).

The operator's complaint (2026-11-08, 20:22 ET): "why did we get two different results? why wasn't it uniform?"
The 18:00 preview had been composed by hand from data while Home rendered ``data/runtime/cio_overnight_brief/
latest.json``; the two disagreed in exactly the places a hand-written summary can drift. This script makes a preview
a RENDER of the same document Home shows, so there is one source and one set of words.

Input is a ``CIOOvernightBrief@v1`` JSON document and nothing else: ``--brief`` for a file, ``--stdin`` for a
pipe. Anything that is not that document is refused with exit 2 (a free-text preview is the defect). A dry run of
the writer belongs here too: cc-deepseek-3's hook patch makes ``--dry-run --json`` emit the full document.

  python3 scripts/cio_preview_render.py --brief data/runtime/cio_overnight_brief/latest.json --out /tmp/preview.html
  python3 scripts/cio_preview_render.py --stdin --check            # consistency gate only, exit 1 on FAIL

Deterministic: same document in, same bytes out. No network, no database, no LLM. Advisory only — the preview
repeats the CIO's words and adds none.
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import cio_brief_consistency as consistency  # noqa: E402

ET = ZoneInfo("America/New_York")
SCHEMA = consistency.SCHEMA
PROCESS = "cio_preview_render"

SYNOPSIS_ROWS: list[tuple[str, str, tuple[str, ...]]] = [
    ("book", "Book", ("book", "portfolio", "holdings")),
    ("market", "Market", ("market", "macro")),
    ("reentry", "Re-entry", ("reentry", "re_entry", "reentries")),
    ("this_week", "This week", ("this_week", "week", "week_ahead")),
    ("do_now", "Do now", ("do_now", "actions", "action")),
]
ACTION_RANK = {"ADD_STOP": 0, "FIX_QTY": 1, "RAISE": 2, "HOLD": 3, "NO_ACTION": 4}
ACTION_VERB = {"ADD_STOP": "ADD A SELL STOP", "RAISE": "EDIT THE STOP", "FIX_QTY": "EDIT THE STOP QUANTITY",
               "HOLD": "HOLD", "NO_ACTION": "NO ACTION"}
NOT_SYMBOLS = {"CPI", "PPI", "FOMC", "FED", "ETF", "ATR", "GTC", "ET", "CIO", "US", "WHO", "WHAT", "WHY"}


def _s(v: Any) -> str:
    return v.strip() if isinstance(v, str) else ""


def _esc(v: Any) -> str:
    return html.escape(_s(v) if not isinstance(v, (int, float)) else str(v))


def _pick(o: Mapping[str, Any], keys: tuple[str, ...]) -> Any:
    for k in keys:
        v = o.get(k)
        if v not in (None, ""):
            return v
    return None


def _line(v: Any) -> str:
    """The producer writes each synopsis row as a block with its one-line summary under ``line``."""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, Mapping):
        for k in ("line", "text", "summary", "label"):
            s = _s(v.get(k))
            if s:
                return s
    return ""


def _et(iso: Any) -> str:
    s = _s(iso)
    if not s:
        return ""
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return s
    d = d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d
    e = d.astimezone(ET)
    return f"{e:%a %m-%d %H:%M} ET"


def validate(doc: Any) -> list[str]:
    """Why this is not a brief document (empty list: it is one)."""
    if not isinstance(doc, Mapping):
        return ["the input is not a JSON object"]
    out: list[str] = []
    if _s(doc.get("schema")) != SCHEMA:
        out.append(f"schema is {_s(doc.get('schema')) or 'missing'!r}, expected {SCHEMA!r}")
    for key in ("run_id", "generated_at", "synopsis"):
        if not doc.get(key):
            out.append(f"{key} is missing")
    if not isinstance(doc.get("synopsis"), (Mapping, type(None))):
        out.append("synopsis is not an object")
    return out


def _rows(doc: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [r for r in (doc.get("stop_advice") or []) if isinstance(r, Mapping)]


def _kind(row: Mapping[str, Any]) -> str:
    raw = _s(_pick(row, ("answer", "verdict", "action", "recommendation"))).upper().replace("-", "_").replace(" ", "_")
    if raw.startswith("NO_") or raw in ("NONE", "NOTHING"):
        return "NO_ACTION"
    if "ADD" in raw:
        return "ADD_STOP"
    if "FIX" in raw or "QTY" in raw:
        return "FIX_QTY"
    if "RAISE" in raw or "TIGHTEN" in raw or "EDIT" in raw:
        return "RAISE"
    if "HOLD" in raw or "KEEP" in raw:
        return "HOLD"
    return "NO_ACTION"


def _price(v: Any) -> str:
    try:
        return f"${float(v):.2f}"
    except (TypeError, ValueError):
        return ""


def render(doc: Mapping[str, Any]) -> str:
    """The preview page. Every word it shows is the document's; the layout is the only thing this script adds."""
    syn = doc.get("synopsis") if isinstance(doc.get("synopsis"), Mapping) else {}
    run = consistency.run_check(doc)
    verdict = _s(_pick(syn, ("verdict", "bottom_line", "headline")))
    posture = _s(_pick(syn, ("posture", "stance")))
    tier = _s(_pick(syn, ("risk", "risk_tier")))
    if not tier:
        market = syn.get("market")
        tier = _s(_pick(market, ("tier", "level", "label"))) if isinstance(market, Mapping) else ""
    summary = doc.get("summary") if isinstance(doc.get("summary"), Mapping) else {}
    out: list[str] = []
    w = out.append
    w("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">")
    w("<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">")
    w(f"<title>CIO preview — {_esc(run['run_id'])}</title>")
    w("<style>"
      ":root{color-scheme:light dark}"
      "body{margin:0;padding:24px;font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;"
      "background:#0f1216;color:#e7ecf2;max-width:860px}"
      "h1{font-size:22px;margin:0 0 4px}h2{font-size:15px;text-transform:uppercase;letter-spacing:.06em;"
      "color:#9fb0c3;margin:22px 0 6px}"
      ".meta{font-size:12px;color:#9fb0c3;overflow-wrap:anywhere}"
      ".verdict{font-size:17px;font-weight:700;margin:10px 0}"
      ".chip{display:inline-block;padding:1px 8px;border-radius:999px;border:1px solid #43536a;font-size:12px;"
      "margin-right:6px;color:#cfe0f2}"
      ".tier-RED{border-color:#f0603a;color:#ffb39b}.tier-ORANGE{border-color:#e0a030;color:#ffd79a}"
      "table{border-collapse:collapse;width:100%}td,th{padding:4px 6px;border-bottom:1px solid #26313f;"
      "vertical-align:top;text-align:left;font-size:14px}"
      ".row{display:grid;grid-template-columns:110px 1fr;gap:8px;padding:4px 0;border-bottom:1px solid #26313f}"
      ".k{color:#9fb0c3;font-size:13px}.sym{font-weight:800}"
      ".warn{border-left:4px solid #e0a030;padding:6px 10px;margin:10px 0;background:#241d10;font-size:13px}"
      ".quiet{font-size:13px;color:#9fb0c3}.advisory{font-size:12px;color:#9fb0c3;margin-top:22px}"
      "</style></head><body>")
    w("<h1>CIO — Home preview</h1>")
    w(f"<p class=\"meta\">rendered from {_esc(SCHEMA)} · run <b>{_esc(run['run_id'])}</b> · "
      f"built {_esc(_et(doc.get('generated_at')))} · as of {_esc(_et(doc.get('as_of')))}</p>")
    if run["text"]:
        w(f"<div class=\"warn\" data-testid=\"cio-run-notice\">{_esc(run['text'])}</div>")
    if verdict:
        w(f"<p class=\"verdict\">{_esc(verdict)}</p>")
    chips: list[tuple[str, str]] = []  # (class suffix, text)
    if posture:
        chips.append(("", _esc(posture)))
    if tier:
        tone = f" tier-{_esc(tier)}" if _s(tier).upper() in ("RED", "ORANGE") else ""
        chips.append((tone, f"risk tier {_esc(tier)}"))
    if doc.get("advisory_only") is True:
        chips.append(("", "advisory only"))
    if chips:
        w("<p>" + "".join(f'<span class="chip{c}">{t}</span>' for c, t in chips) + "</p>")

    rows = []
    for _key, label, aliases in SYNOPSIS_ROWS:
        text = _line(_pick(syn, aliases))
        if text:
            rows.append(f"<div class=\"row\"><div class=\"k\">{_esc(label)}</div><div>{_esc(text)}</div></div>")
    if rows:
        w("<h2>The brief</h2>" + "".join(rows))

    stops = sorted(_rows(doc), key=lambda r: (ACTION_RANK[_kind(r)], _s(r.get("symbol"))))
    actions = [r for r in stops if _kind(r) in ("ADD_STOP", "RAISE", "FIX_QTY")]
    quiet = [r for r in stops if _kind(r) not in ("ADD_STOP", "RAISE", "FIX_QTY")]
    if stops:
        w(f"<h2>Your actions · {len(actions)} stop change{'' if len(actions) == 1 else 's'} at Schwab</h2>")
    if actions:
        w("<table><tr><th>#</th><th>Name</th><th>Account</th><th>Answer</th><th>Stop</th><th>Why</th></tr>")
        for i, r in enumerate(actions, 1):
            stop = _price(r.get("suggested_stop")) or _price(r.get("stop_now"))
            w(f"<tr><td>{i}</td><td class=\"sym\">{_esc(r.get('symbol'))}</td><td>{_esc(r.get('account'))}</td>"
              f"<td>{_esc(ACTION_VERB[_kind(r)])}</td><td>{_esc(stop)}</td><td>{_esc(r.get('reason'))}</td></tr>")
        w("</table>")
    elif stops:
        w("<p class=\"quiet\">Nothing to change at Schwab today.</p>")
    if quiet:
        # a HOLD row that carries an event renders the event, never a bare "hold": LQ-1318
        cells = []
        for r in quiet:
            event = _s(r.get("event_summary")) or _s(r.get("what_happened"))
            tail = f" — {_esc(event)}" if event else ""
            cells.append(f"{_esc(r.get('symbol'))} ({'hold' if _kind(r) == 'HOLD' else 'no action'}){tail}")
        w(f"<h2>No change needed</h2><p class=\"quiet\" data-testid=\"stops-quiet\">{' · '.join(cells)}</p>")

    if _s(summary.get("text")):
        w(f"<h2>Summary · {_esc(_s(summary.get('source')) or 'source')}</h2>")
        w(f"<p>{_esc(summary.get('text'))}</p>")

    w(f"<p class=\"advisory\">Advisory only. Rendered from the brief document itself — run {_esc(run['run_id'])}, "
      f"generated {_esc(_et(doc.get('generated_at')))}. No order is placed, sized or changed by this page.</p>")
    w("</body></html>")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--brief", type=Path, help=f"a {SCHEMA} JSON document")
    src.add_argument("--stdin", action="store_true", help="read the document from stdin")
    ap.add_argument("--out", type=Path, default=None, help="write the HTML here (default: stdout)")
    ap.add_argument("--check", action="store_true", help="run the consistency gate; exit 1 when it FAILs")
    a = ap.parse_args(argv)

    if a.stdin:
        raw = sys.stdin.read()
    else:
        try:
            raw = a.brief.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"refused: cannot read {a.brief}: {exc}", file=sys.stderr)
            return 2
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"refused: not JSON ({exc}); a preview is never free text", file=sys.stderr)
        return 2
    problems = validate(doc)
    if problems:
        print("refused: this is not a CIO overnight brief document — " + "; ".join(problems), file=sys.stderr)
        print("render only from the writer's document (cio_overnight_brief.py --dry-run --json or latest.json)",
              file=sys.stderr)
        return 2

    gate = consistency.check_brief(doc)
    if a.check:
        print(f"cio_brief_consistency {gate['state']} — run {gate['run_id']} — {len(gate['findings'])} finding(s)")
        for f in gate["findings"]:
            print(f"  {f['code']} @ {f['where']}: {f['detail']}")
        return 0 if gate["state"] == "PASS" else 1

    page = render(doc)
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(page, encoding="utf-8")
        print(f"wrote {a.out} ({len(page)} bytes) from run {gate['run_id']}")
    else:
        sys.stdout.write(page)
    return 0 if gate["state"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
