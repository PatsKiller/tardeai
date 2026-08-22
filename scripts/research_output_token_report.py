#!/usr/bin/env python3
"""M2 — report tokens actually sent vs stored rec length. No production config change.

READ_ONLY_ADVISORY. Reads llm_consumption_log + hermes_external_research.
"""
from __future__ import annotations

import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

PROCESS_ID = "hermes_external_research"
REGISTRY = ROOT / "config" / "llm_process_registry.json"
MODEL_REG = ROOT / "config" / "llm_model_registry.json"


def _pct(xs, p):
    if not xs:
        return None
    s = sorted(xs)
    i = min(len(s) - 1, max(0, int(round((p / 100.0) * (len(s) - 1)))))
    return s[i]


def _load_caps() -> dict:
    proc = json.loads(REGISTRY.read_text())
    row = next(p for p in proc.get("processes") or proc.get("items") or proc
               if (p.get("id") if isinstance(p, dict) else None) == PROCESS_ID)
    # registry is a list or {"processes": [...]}
    return row


def _process_row() -> dict:
    blob = json.loads(REGISTRY.read_text())
    rows = blob if isinstance(blob, list) else blob.get("processes") or blob.get("items") or []
    for p in rows:
        if isinstance(p, dict) and p.get("id") == PROCESS_ID:
            return p
    raise SystemExit(f"process {PROCESS_ID} not in registry")


def _flash_model_cap() -> int | None:
    blob = json.loads(MODEL_REG.read_text())
    models = blob.get("models") or blob
    if isinstance(models, dict):
        for k, v in models.items():
            if "flash" in str(k).lower() and isinstance(v, dict) and v.get("max_output_tokens"):
                return int(v["max_output_tokens"])
        # nested providers
        for v in models.values() if isinstance(models, dict) else []:
            if not isinstance(v, dict):
                continue
            inner = v.get("models") or v
            if isinstance(inner, dict):
                for kk, vv in inner.items():
                    if "flash" in str(kk).lower() and isinstance(vv, dict) and vv.get("max_output_tokens"):
                        return int(vv["max_output_tokens"])
            if isinstance(v, dict) and v.get("max_output_tokens") and "flash" in json.dumps(v).lower():
                return int(v["max_output_tokens"])
    if isinstance(blob, dict):
        for prov in (blob.get("providers") or {}).values():
            for mid, m in (prov.get("models") or {}).items():
                if "flash" in str(mid).lower() and isinstance(m, dict):
                    return int(m.get("max_output_tokens") or 0) or None
    return None


def main() -> int:
    proc = _process_row()
    cap = int(proc.get("max_output_tokens") or 0)
    model_cap = _flash_model_cap()
    from db_adapter import _get_conn
    c = _get_conn().cursor()
    c.execute(
        """SELECT tokens_in, tokens_out, response_chars, estimated_cost_usd, created_at
           FROM llm_consumption_log
           WHERE process_id = %s AND created_at::date = CURRENT_DATE
             AND coalesce(success, true) = true
           ORDER BY id""",
        (PROCESS_ID,),
    )
    cons = c.fetchall()
    c.execute(
        """SELECT length(recommendation), length(coalesce(dissent,'')),
                  length(coalesce(evidence_json::text,'')),
                  recommendation
           FROM hermes_external_research
           WHERE lane='deepseek' AND created_at::date = CURRENT_DATE
             AND coalesce(recommendation,'')<>'' AND recommendation NOT LIKE '[%%'"""
    )
    recs = c.fetchall()

    tokens_in = [int(r[0] or 0) for r in cons]
    tokens_out = [int(r[1] or 0) for r in cons]
    resp_chars = [int(r[2] or 0) for r in cons if r[2] is not None]
    costs = [float(r[3] or 0) for r in cons]
    rec_lens = [int(r[0] or 0) for r in recs]
    at_cap = sum(1 for t in tokens_out if cap and t >= cap - 8)
    at_500 = sum(1 for n in rec_lens if n >= 500)
    under_300 = sum(1 for n in rec_lens if n < 300)

    def stats(xs):
        if not xs:
            return {}
        return {
            "n": len(xs),
            "p50": _pct(xs, 50),
            "p90": _pct(xs, 90),
            "mean": round(sum(xs) / len(xs), 2),
            "max": max(xs),
            "min": min(xs),
        }

    parser_trunc = "scripts/lib/cio_agent_contract.py parse_external_research_result recommendation[:500]"
    prompt_brevity = (
        "No explicit 'be brief'. JSON contract + research_scheduler.QUESTION "
        "'Give a clear recommendation and what would change your mind.'"
    )
    report = {
        "schema": "ResearchOutputTokenReport@v1",
        "authority": "READ_ONLY_ADVISORY",
        "as_of": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "process_id": PROCESS_ID,
        "configured": {
            "process_max_output_tokens": cap,
            "caller_default_max_tokens": 1500,
            "effective_sent": min(1500, cap) if cap else 1500,
            "flash_model_max_output_tokens": model_cap,
            "parser_recommendation_slice": 500,
            "raw_fallback_slice": 4000,
            "prompt_brevity": prompt_brevity,
            "parser_path": parser_trunc,
        },
        "consumption_today": {
            "n": len(cons),
            "tokens_in": stats(tokens_in),
            "tokens_out": stats(tokens_out),
            "response_chars": stats(resp_chars),
            "estimated_cost_usd_sum": round(sum(costs), 6),
            "pct_tokens_out_at_process_cap": round(100.0 * at_cap / len(tokens_out), 1) if tokens_out else None,
            "at_cap_n": at_cap,
        },
        "stored_recommendation_today": {
            "n": len(rec_lens),
            "chars": stats(rec_lens),
            "pct_under_300": round(100.0 * under_300 / len(rec_lens), 1) if rec_lens else None,
            "pct_at_or_over_500": round(100.0 * at_500 / len(rec_lens), 1) if rec_lens else None,
            "at_500_n": at_500,
        },
        "diagnosis": (
            "If stored recs cluster at 500, the parser is the median. "
            "If tokens_out cluster at the process cap, the cap is the tail. Both can be true."
        ),
        "propose_do_not_apply": {
            "parser": "recommendation[:500] → [:4000]",
            "prompt": "recommendation field itself is the living thesis (≥8 sentences, ticker, numbered fact, invalidation, role)",
            "ceiling": f"{cap} → 4096; dollar caps unchanged",
            "estimate": (
                "Parser+prompt move median stored rec. Cap-raise unblocks the "
                f"~{at_cap} calls clustered at {cap}. Do not claim 27.5%→70% from the cap alone."
            ),
        },
        "production_unchanged": True,
    }
    out = ROOT / "data/cio/research_output_token_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
