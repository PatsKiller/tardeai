#!/usr/bin/env python3
"""One-off remediation: ingest the zero-grounded retirement topics, then reground them.

Finds retirement topic_research rows currently grounded on 0 sources (because their
topic was never ingested → last_searched is NULL), runs topic_ingestion for each so
real on-topic news lands tagged symbol=topic_id, then resets grounded_count and reruns
the (relevance-gated) synthesizer so they pick up the fresh on-topic sources.
"""
import sys, re, json, subprocess, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from db_adapter import _execute

PY = str(ROOT / ".venv" / "bin" / "python")
THEMES = [r"\broth\b|conversion|golden window|\brmd\b|backdoor|qualified charitable",
          r"medicare|irmaa|medigap|part [bd]\b",
          r"medicaid|\bmapt\b|asset protection|spend.?down|look.?back|estate recovery|special needs|supplemental needs",
          r"estate|\btrust\b|probate|life estate|beneficiar|\bwill\b|inheritance",
          r"\bssdi\b|social security|disability|\bmagi\b|tax.?loss|tax-efficient|tax strateg|\bqcd\b|\bhsa\b|earnings test|substantial gainful",
          r"dividend income|covered call|bond ladder|tips|fixed.?income|annuit|drawdown|income sleeve|monthly income|dividend aristocrat|income strateg|bucket strateg|\bcef\b|\bpty\b|\bnav\b"]
TRADING = re.compile(r"swing|momentum|sector rotation|option|greeks|iron condor|earnings season|technical|breakout|scalp|reddit|chart|implied vol|theta|premium sell|datacenter|data center|semiconductor|ai chip|nvidia|defense|aerospace|materials sector|geopolitical|glp-1|weight.?loss|hot topics|controvers|collar|sentiment-driven|emerging sector|infrastructure buildout|hedging|catalyst|energy sector|utilities sector|consumer (defensive|staples)|healthcare rotation|trending|hype", re.I)


def zero_grounded_retirement():
    rows = _execute("SELECT id, topic, evidence_json FROM hermes_research_intelligence "
                    "WHERE research_type='topic_research' AND model_used LIKE 'synth:%%'", fetch="all") or []
    out = []
    for r in rows:
        t = r['topic'] or ''
        if TRADING.search(t) or not any(re.search(rx, t, re.I) for rx in THEMES):
            continue
        ev = r['evidence_json']; ev = ev if isinstance(ev, dict) else (json.loads(ev) if ev else {})
        if not (ev.get('grounded_on') or []):
            out.append((r['id'], t, ev.get('topic_monitor_id')))
    return out


def main():
    targets = zero_grounded_retirement()
    print(f"[remediation] {len(targets)} zero-grounded retirement topics to ingest+reground", flush=True)
    for rid, topic, tmid in targets:
        if not tmid:
            print(f"  SKIP (no topic_monitor_id): {topic[:46]}", flush=True); continue
        print(f"  INGEST {topic[:46]} (tmid={tmid}) ...", flush=True)
        t0 = time.time()
        try:
            cp = subprocess.run([PY, "scripts/topic_ingestion.py", "--topic", tmid],
                                cwd=str(ROOT), capture_output=True, text=True, timeout=420)
            tail = "\n".join((cp.stdout or "").strip().splitlines()[-2:])
            print(f"    done in {int(time.time()-t0)}s rc={cp.returncode} :: {tail[:160]}", flush=True)
        except subprocess.TimeoutExpired:
            print(f"    TIMEOUT after {int(time.time()-t0)}s (partial ingest kept)", flush=True)
        except Exception as e:
            print(f"    ERROR: {e}", flush=True)
        # reset grounded_count so the reground path re-processes this row
        _execute("UPDATE hermes_research_intelligence SET evidence_json = "
                 "jsonb_set(COALESCE(evidence_json,'{}'::jsonb),'{grounded_count}','0') WHERE id=%s",
                 (rid,), fetch=None)

    print("[remediation] regrounding ...", flush=True)
    cp = subprocess.run([PY, "scripts/topic_research_synthesizer.py", "--apply", "--reground", "--max", "30"],
                        cwd=str(ROOT), capture_output=True, text=True, timeout=900)
    for ln in (cp.stdout or "").splitlines():
        if "relevance" in ln.lower() or "grounded" in ln.lower():
            print("  " + ln, flush=True)

    # verify
    after = zero_grounded_retirement()
    print(f"[remediation] DONE. still-zero-grounded retirement topics: {len(after)} (was {len(targets)})", flush=True)
    for _, t, _ in after:
        print(f"    still 0: {t[:46]}", flush=True)


if __name__ == "__main__":
    main()
