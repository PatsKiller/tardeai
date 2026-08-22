#!/usr/bin/env python3
"""M2 sandbox: 20 symbols, raised ceiling + substantive prompt. Does NOT change production.

Writes data/cio/sandbox/output_ceiling_20.json only. --no-store on the researcher.
Trigger sandbox_m2. Cron still 1024 / stock prompt.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROMPT = ROOT / "scripts/sandbox_prompt_substantive.txt"
OUT = ROOT / "data/cio/sandbox/output_ceiling_20.json"
RESEARCHER = ROOT / "scripts/hermes_external_researcher.py"
CURRENT = Path("/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT")


def _pick_symbols(n: int = 20) -> list[str]:
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "scripts"))
    os.chdir(str(ROOT))
    from research_scheduler import load_universe
    from scripts.lib.cio_held_thesis_coverage import build_held_coverage_report
    from db_adapter import _get_conn
    from scripts.lib.thesis_substantiveness import grade_text

    uni = load_universe(root=CURRENT)
    live = build_held_coverage_report(root=CURRENT)
    needs = set(live.get("needs_coverage") or []) | set(live.get("needs_substance") or [])
    t0 = [s for s, v in uni.items() if v.get("tier") == "T0-HOLD"]
    c = _get_conn().cursor()
    c.execute(
        """SELECT DISTINCT ON (upper(symbol)) upper(symbol), recommendation
           FROM hermes_external_research
           WHERE lane='deepseek' AND created_at::date >= CURRENT_DATE - 1
             AND coalesce(recommendation,'')<>'' AND recommendation NOT LIKE '[%%'
           ORDER BY upper(symbol), created_at DESC"""
    )
    recs = {r[0]: r[1] or "" for r in c.fetchall()}
    ranked = []
    for s in t0:
        g = grade_text(s, recs.get(s) or "")
        ranked.append((0 if s in needs else 1, 0 if g["coverage_state"] != "CURRENT" else 1, s))
    ranked.sort()
    out = [s for _, _, s in ranked[:n]]
    if len(out) < n:
        extra = [s for s in sorted(uni) if s not in out]
        out.extend(extra[: n - len(out)])
    return out[:n]


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="call DeepSeek (default: pick symbols dry)")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--max-output-tokens", type=int, default=4096)
    args = ap.parse_args()
    symbols = _pick_symbols(args.n)
    report = {
        "schema": "OutputCeilingSandbox@v1",
        "authority": "READ_ONLY_ADVISORY",
        "as_of": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "n": len(symbols),
        "symbols": symbols,
        "max_output_tokens": args.max_output_tokens,
        "prompt_file": str(PROMPT),
        "production_cap_unchanged": 1024,
        "no_store": True,
        "rows": [],
    }
    if not args.apply:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({k: report[k] for k in report if k != "rows"}, indent=2))
        print("dry-run; re-run with --apply to call the model")
        return 0

    sys.path.insert(0, str(ROOT))
    from scripts.lib.thesis_substantiveness import grade_text, join_research_text
    from research_scheduler import QUESTION

    for i, sym in enumerate(symbols, 1):
        kind = "holding"
        q = QUESTION.format(sym=sym, kind=kind)
        cmd = [
            sys.executable, str(RESEARCHER),
            "--lane", "deepseek",
            "--symbol", sym,
            "--question", q,
            "--trigger", "holdings",
            "--apply",
            "--no-store",
            "--max-output-tokens", str(args.max_output_tokens),
            "--prompt-file", str(PROMPT),
        ]
        env = os.environ.copy()
        env["LLM_GLOBAL_DAILY_USD_CAP"] = env.get("LLM_GLOBAL_DAILY_USD_CAP") or "0.50"
        env["HERMES_SANDBOX_OUTPUT_CEILING"] = "1"
        print(f"[{i}/{len(symbols)}] {sym}", flush=True)
        p = subprocess.run(cmd, cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=180)
        blob = {}
        out = (p.stdout or "") + "\n" + (p.stderr or "")
        dec = json.JSONDecoder()
        idx = 0
        last = None
        while True:
            i = out.find("{", idx)
            if i < 0:
                break
            try:
                obj, end = dec.raw_decode(out, i)
                if isinstance(obj, dict):
                    last = obj
                idx = end
            except json.JSONDecodeError:
                idx = i + 1
        if last:
            blob = last
        else:
            blob = {
                "empty": True,
                "rc": p.returncode,
                "stdout_tail": (p.stdout or "")[-500:],
                "stderr_tail": (p.stderr or "")[-400:],
            }
        rec = str(blob.get("recommendation") or "")
        raw = str(blob.get("raw") or "")
        joined = join_research_text(rec, blob.get("dissent"), blob.get("evidence"))
        g = grade_text(sym, rec)
        gj = grade_text(sym, joined)
        gr = grade_text(sym, raw) if raw else g
        report["rows"].append({
            "symbol": sym,
            "rc": p.returncode,
            "raw_chars": blob.get("raw_chars") or len(raw),
            "rec_chars": blob.get("rec_chars") or len(rec),
            "joined_chars": len(joined),
            "grade_rec": g.get("grade"),
            "state_rec": g.get("coverage_state"),
            "grade_joined": gj.get("grade"),
            "state_joined": gj.get("coverage_state"),
            "grade_raw": gr.get("grade"),
            "state_raw": gr.get("coverage_state"),
            "status": blob.get("status"),
        })
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(report, indent=2) + "\n")

    rows = report["rows"]
    n = len(rows) or 1
    report["pass_rec"] = round(100.0 * sum(1 for r in rows if r["state_rec"] == "CURRENT") / n, 1)
    report["pass_joined"] = round(100.0 * sum(1 for r in rows if r["state_joined"] == "CURRENT") / n, 1)
    report["pass_raw"] = round(100.0 * sum(1 for r in rows if r.get("state_raw") == "CURRENT") / n, 1)
    report["thin_rec"] = round(100.0 * sum(1 for r in rows if r["state_rec"] == "THIN") / n, 1)
    report["sent_n"] = sum(1 for r in rows if r.get("status") == "sent")
    OUT.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in report if k != "rows"}, indent=2))
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
