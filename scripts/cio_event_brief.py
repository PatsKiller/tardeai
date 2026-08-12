#!/usr/bin/env python3
"""cio_event_brief.py — event-driven, thesis-grounded CIO Telegram brief.

READ_ONLY_ADVISORY. Aggregates *material* events across the desk and aggregates
them into one concise, dollars-first, confirmed-and-actionable push for the
operator, grounded in the live desk@vN thesis:

  1. Advisory Desk actionable rows (TRIM/EXIT/ADD/RE_ENTER above the materiality
     floor) — the canonical verdict table.
  2. Look-through concentration breaches (V/DIVI style single-name > guideline).
  3. Theme deployment gaps (dry-powder candidates, not buy-now).
  4. Re-entry watch (desk RE_ENTER rows / closed-position recovery).

Dedupe: a content fingerprint is persisted; the brief is only sent when the
material content changed (or --force). No LLM, no broker action, no orders.

CLI:
  python cio_event_brief.py [--force] [--dry-run] [--no-send]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
RUNTIME_DIR = PROJECT_ROOT / "data" / "runtime"
FINGERPRINT_PATH = RUNTIME_DIR / "cio_event_brief_last.json"

_ACTIONABLE = {"TRIM", "EXIT", "ADD", "RE_ENTER"}


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _fmt_usd(n: Any) -> str:
    try:
        v = float(n)
    except (TypeError, ValueError):
        return "DATA_UNAVAILABLE"
    if abs(v) >= 1e6:
        return f"${v/1e6:.2f}M"
    if abs(v) >= 1e3:
        return f"${v/1e3:.0f}K"
    return f"${v:,.0f}"


def _fmt_pct(n: Any) -> str:
    try:
        return f"{float(n):.2f}%"
    except (TypeError, ValueError):
        return "DATA_UNAVAILABLE"


def _bridge() -> dict[str, Any]:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    try:
        from lib.cio_advisory_bridge import advisory_desk_context, living_thesis_context
        return {"desk": advisory_desk_context(), "thesis": living_thesis_context()}
    except Exception:
        try:
            from scripts.lib.cio_advisory_bridge import advisory_desk_context, living_thesis_context
            return {"desk": advisory_desk_context(), "thesis": living_thesis_context()}
        except Exception as e:
            return {"desk": {}, "thesis": {}, "error": str(e)}


def _lookthrough_events() -> dict[str, Any]:
    lt = _load_json(STATE_DIR / "lookthrough_themes.json")
    advisories = lt.get("advisories") or []
    gaps = lt.get("theme_gaps") or []
    top = lt.get("top_underlying") or []
    return {
        "advisories": advisories,
        "theme_gaps": gaps,
        "top_underlying": top[:6],
        "coverage_pct": lt.get("coverage_pct"),
    }


def _material_actionable(desk: dict[str, Any], *, min_mv: float = 500.0) -> list[dict[str, Any]]:
    rows = desk.get("top_actionable") or []
    out = []
    for r in rows:
        if str(r.get("verdict")) in _ACTIONABLE and float(r.get("market_value") or 0) >= min_mv:
            out.append(r)
    return out


def _build_brief(*, force: bool) -> dict[str, Any]:
    data = _bridge()
    desk = data.get("desk") or {}
    thesis = data.get("thesis") or {}
    lt = _lookthrough_events()

    pin = thesis.get("thesis_version") or "desk@?"
    stance = thesis.get("stance") or "unknown"
    thesis_sum = (thesis.get("summary") or "").strip()
    if len(thesis_sum) > 220:
        thesis_sum = thesis_sum[:220].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"

    actionable = _material_actionable(desk)
    advisories = [a for a in lt["advisories"] if a.get("severity") in ("high", "medium")][:3]
    gaps = [g for g in lt["theme_gaps"] if g.get("severity") == "high"][:3]

    lines: list[str] = []
    lines.append(f"🏦 *CIO brief* · `{pin}` · {stance} · READ_ONLY")
    if thesis_sum:
        lines.append(f"_Thesis: {thesis_sum}_")
    lines.append("────────────────")

    # 1. Cash posture
    perf = desk.get("performance") or {}
    cash_line_parts = []
    for r in (desk.get("top_actionable") or []):
        pass  # cash is an allocation row; keep posture via synthesis if present
    # Fall back to allocation row / synthesis for cash posture
    cash_note = ""
    by_class = desk.get("by_class") or {}
    alloc_rows = by_class.get("allocation", 0)
    if alloc_rows:
        cash_note = f"desk rows: {desk.get('row_count', 0)} total · {alloc_rows} allocation-gap rows reviewed"
    lines.append(f"💰 *Desk snapshot* · {desk.get('row_count', 0)} rows · "
                 f"as_of {str(desk.get('as_of') or '')[:16]}")

    # 2. Actionable desk rows (dollars-first)
    if actionable:
        lines.append("\n📍 *Actionable (confirmed)*")
        for r in actionable[:5]:
            sym = r.get("symbol")
            v = r.get("verdict")
            mv = _fmt_usd(r.get("market_value"))
            why = (r.get("rationale") or "").strip()
            lines.append(f"  • {sym} *{v}* {mv}"
                         + (f" — {why[:70]}" if why else ""))
    else:
        lines.append("\n📍 *Actionable* — none above materiality this pass")

    # 3. Look-through concentration
    if advisories:
        lines.append("\n🔍 *Look-through concentration*")
        for a in advisories:
            lines.append(f"  • {a.get('title')} — {a.get('detail','')[:90]}")

    # 4. Re-entry / recovery watch
    reentry = [r for r in (desk.get("top_actionable") or []) if str(r.get("verdict")) == "RE_ENTER"][:3]
    if reentry:
        lines.append("\n🧭 *Re-entry watch* (not buy-now)")
        for r in reentry:
            lines.append(f"  • {r.get('symbol')} RE_ENTER {_fmt_usd(r.get('market_value'))}")

    # 5. Theme gaps (deployment candidates, grounded in thesis)
    if gaps:
        lines.append("\n🧭 *Theme gaps* (dry-powder candidates — research, not deploy)")
        for g in gaps:
            lines.append(f"  • {g.get('theme')}: {g.get('current_pct')}% vs "
                         f"{g.get('target_pct')}% target (~{_fmt_usd(g.get('gap_dollars'))})")

    lines.append("────────────────")
    lines.append(f"Escalate to operator on cash ±3pp, single-name ≥ fire line, "
                 f"or a READY re-entry with confirmations complete.")
    lines.append("Full desk `/advisory` · memo `/v3/cio` · no orders/stops · READ_ONLY_ADVISORY")

    text = "\n".join(lines)

    # Fingerprint of the *material* payload only (excludes timestamp header)
    material = {
        "actionable": [(r.get("symbol"), r.get("verdict"), round(float(r.get("market_value") or 0))) for r in actionable],
        "advisories": [a.get("title") for a in advisories],
        "reentry": [r.get("symbol") for r in reentry],
        "gaps": [g.get("theme") for g in gaps],
    }
    fp = hashlib.sha256(json.dumps(material, sort_keys=True, default=str).encode()).hexdigest()[:16]

    return {
        "ok": True,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "pin": pin,
        "stance": stance,
        "actionable_count": len(actionable),
        "advisory_count": len(advisories),
        "reentry_count": len(reentry),
        "gap_count": len(gaps),
        "fingerprint": fp,
        "text": text,
    }


def _load_last() -> str:
    d = _load_json(FINGERPRINT_PATH)
    return str(d.get("fingerprint") or "")


def _save_last(brief: dict[str, Any]) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    FINGERPRINT_PATH.write_text(json.dumps({
        "fingerprint": brief["fingerprint"],
        "as_of": brief["as_of"],
        "actionable_count": brief["actionable_count"],
    }, indent=2), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Thesis-grounded CIO event brief")
    ap.add_argument("--force", action="store_true", help="send even if content unchanged")
    ap.add_argument("--dry-run", action="store_true", help="print brief, do not send")
    ap.add_argument("--no-send", action="store_true", help="build + fingerprint but do not send")
    args = ap.parse_args()

    brief = _build_brief(force=args.force)
    last = _load_last()
    changed = brief["fingerprint"] != last

    print(brief["text"])
    print(f"\n[fingerprint {brief['fingerprint']}] last={last or '(none)'} changed={changed}")

    if args.dry_run:
        print("[dry-run] not sent, not fingerprinted")
        return 0

    if not changed and not args.force:
        print("[cio_event_brief] suppressed — no material change")
        return 0

    if args.no_send:
        _save_last(brief)
        print("[cio_event_brief] fingerprinted, send suppressed via --no-send")
        return 0

    sent = False
    try:
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from telegram_alert import send_telegram
        sent = send_telegram(brief["text"])
    except Exception as e:
        print(f"[cio_event_brief] telegram send failed: {type(e).__name__}: {str(e)[:160]}")

    _save_last(brief)
    print(f"[cio_event_brief] sent={sent}")
    return 0 if sent else 0


if __name__ == "__main__":
    raise SystemExit(main())
