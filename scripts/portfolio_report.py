"""portfolio_report.py — Portfolio Intelligence v1.2 — DOCX brief wrapper."""
from __future__ import annotations
import json, os, subprocess, tempfile
from pathlib import Path

def generate_portfolio_brief(portfolio, analysis, tax, rebalancing, risk, output_path,
                              chart_paths=None, performance=None, ai_analysis=None,
                              technical=None, stress=None, retirement=None,
                              tax_projection=None, tech_chart_paths=None,
                              perf_history=None):
    data = {
        "portfolio":       portfolio,
        "analysis":        analysis,
        "tax":             tax,
        "rebalancing":     rebalancing,
        "risk":            risk,
        "chart_paths":     chart_paths     or {},
        "performance":     performance     or {},
        "perf_history":    perf_history    or {},
        "ai_analysis":     ai_analysis     or {},
        "technical":       technical       or {},
        "stress":          stress          or {},
        "retirement":      retirement      or {},
        "tax_projection":  tax_projection  or {},
        "tech_chart_paths":{str(k): str(v) for k,v in (tech_chart_paths or {}).items()},
    }
    js_path = Path(__file__).parent / "portfolio_report.js"
    if not js_path.exists():
        print(f"  [report] portfolio_report.js not found"); return ""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tf:
        json.dump(data, tf, default=str)
        tmp = tf.name
    try:
        r = subprocess.run(["node", str(js_path), tmp, str(output_path)],
                           capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            print(f"  [report] Node error: {r.stderr[:300]}"); return ""
        print(f"  [report] Intelligence brief → {Path(output_path).name}")
        return str(output_path)
    except Exception as e:
        print(f"  [report] Error: {e}"); return ""
    finally:
        try: os.unlink(tmp)
        except: pass
