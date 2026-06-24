#!/usr/bin/env python3
"""analyst_urgent_refresh.py — off-cycle "urgent change" detector for analyst prospectuses.

Baseline refresh is weekly (cron). This runs more often (e.g. weekday mornings) and acts ONLY on a
MATERIAL change — the synthesized recommendation flipped vs the last published report, or the thesis
degraded to At risk / Broken. Those holdings are regenerated immediately (Grok + free dual-lane
oversight) and the operator is emailed a summary with the updated PDFs attached.

No material change → does nothing (silent). Read-only/advisory.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import reporting_engine as re  # noqa: E402
from report_lineage import canonical_registry_map  # noqa: E402

OPERATOR = "john@jwwhiting.com"
REPORTS = PROJECT_ROOT / "data" / "portfolios" / "reports" / "analyst"
MAX_ATTACH = int(os.getenv("URGENT_MAX_ATTACH", "6"))


def _bucket(rec: str) -> str:
    u = str(rec or "").upper().replace("_", " ").strip()
    for k in ("STRONG BUY", "ADD", "BUY", "ACCUMULATE", "TRIM", "SELL", "REDUCE", "AVOID", "HOLD", "WATCH"):
        if k in u:
            return k
    return u.split()[0] if u else "—"


def detect_urgent() -> list[dict]:
    """Holdings whose recommendation bucket changed vs the last published prospectus."""
    reg = re.load_registry()
    by_holding = canonical_registry_map(reg.get("reports") or [], "symbol_holding")
    urgent = []
    for row in re.eligible_holding_symbols():
        sym = row["symbol"]
        prev = by_holding.get(sym) or {}
        prev_rec = _bucket(prev.get("recommendation"))
        cur_rec = _bucket(re.holding_recommendation(sym))
        # only a real, published prior with a different actionable bucket counts as urgent
        if prev_rec and prev_rec != "—" and cur_rec and cur_rec != "—" and prev_rec != cur_rec:
            urgent.append({"symbol": sym, "prev": prev_rec, "now": cur_rec})
    return urgent


def _pdf_for(sym: str) -> str | None:
    for stem in (f"prospectus_{sym}_latest.pdf", f"watchlist_{sym}_latest.pdf"):
        p = REPORTS / stem
        if p.exists():
            return str(p.resolve())
    return None


def _email(changes: list[dict]) -> bool:
    body = ["Analyst prospectus URGENT refresh — a holding's recommendation changed since the last report.\n"]
    attach = []
    for c in changes:
        body.append(f"=== {c['symbol']} — recommendation changed: {c['prev']} → {c['now']} ===")
        body.append(f"Cloud oversight: {c.get('verdict')}")
        body.append((c.get("takeaway") or "")[:300])
        body.append("")
        pdf = _pdf_for(c["symbol"])
        if pdf and len(attach) < MAX_ATTACH:
            attach.append(pdf)
    body.append("— Produced by TradeAI v3.0 · Advisory, not investment advice —")
    try:
        pw = Path(os.path.expanduser("~/.openclaw/credentials/gog_keyring_password")).read_text().strip()
    except Exception:
        print("no keyring password — cannot email", flush=True)
        return False
    cmd = ["gog", "gmail", "send", "--to", OPERATOR, "-a", OPERATOR,
           "--subject", f"⚑ Analyst URGENT: {', '.join(c['symbol'] + ' ' + c['prev'] + '→' + c['now'] for c in changes[:6])}",
           "--body", "\n".join(body)]
    if attach:
        cmd += ["--attach", ",".join(attach)]
    r = subprocess.run(cmd, env={**os.environ, "GOG_KEYRING_PASSWORD": pw},
                       capture_output=True, text=True, timeout=90)
    print(f"email rc={r.returncode} attached={len(attach)}", flush=True)
    if r.returncode != 0:
        print("  stderr:", r.stderr[:300], flush=True)
    return r.returncode == 0


def main() -> int:
    urgent = detect_urgent()
    if not urgent:
        print(f"[{time.strftime('%H:%M:%S')}] no urgent recommendation changes — nothing to do", flush=True)
        return 0
    print(f"[{time.strftime('%H:%M:%S')}] {len(urgent)} urgent change(s): "
          + ", ".join(f"{u['symbol']} {u['prev']}→{u['now']}" for u in urgent), flush=True)
    for u in urgent:
        try:
            out = re.generate_report(report_type="symbol_holding", symbol=u["symbol"],
                                     sections=re.PROSPECTUS_SECTIONS, formats=["docx", "pdf"],
                                     grok_edit=True, oversight=True, engine="playwright",
                                     generation_mode="urgent")
            meta = out["report"].get("meta", {})
            u["verdict"] = (meta.get("claude_oversight") or {}).get("verdict")
            ex = next((s for s in out["report"].get("sections", []) if s.get("id") == "executive_summary"), {})
            u["takeaway"] = ex.get("content")
        except Exception as e:
            u["verdict"] = f"GEN_FAILED: {str(e)[:120]}"
    _email(urgent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
