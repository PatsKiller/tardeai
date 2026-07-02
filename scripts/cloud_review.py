#!/usr/bin/env python3
"""cloud_review.py — reusable ADVISORY "free-OAuth cloud models review what the local LLM (gemma) produced".

Any Trade AI / Hermes task where the local LLM makes a judgment can call review() to get INDEPENDENT second
opinions from the free OAuth lanes — ChatGPT (openai-codex proxy :8646) AND Grok (xAI proxy :8645) — each
returning AGREE / CAUTION / DISAGREE + concerns + corrections, plus a consensus. Free OAuth, no API key, no
paid API, NO broker/order/stop action. Never blocks the caller; a lane that is down is simply skipped
(available:false). Each lane's review is persisted to llm_feedback_observations (the learning loop).

    from cloud_review import review, available
    r = review("aegis_thesis", local_output="AAPL thesis WEAKENING because ...",
               context={"symbol":"AAPL","rsi":71}, symbol="AAPL", source="aegis_synthesis")
    # r = {ok, lanes:{chatgpt:{verdict,assessment,concerns,corrections,ok}, grok:{...}},
    #      consensus:{verdict, agree, disagree, caution, lanes_ok}}
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from cio_agent_contract import build_cloud_review_json_schema, parse_cloud_review_result

sys.path.insert(0, str(Path(__file__).resolve().parent))
ROOT = Path(__file__).resolve().parent.parent

LANE_MODEL = {"chatgpt": "gpt-5.4", "grok": "grok-3-mini"}
DEFAULT_LANES = ("chatgpt", "grok")


def available(lane=None):
    try:
        import llm_lane
        if lane:
            return bool(llm_lane.available(lane))
        return any(llm_lane.available(ln) for ln in DEFAULT_LANES)
    except Exception:
        return False


def _build_prompt(task, local_output, context):
    ctx = ""
    if context:
        try:
            ctx = "\n\nContext (facts the local model was given):\n" + json.dumps(context, indent=2, default=str)[:3500]
        except Exception:
            ctx = "\n\nContext: " + str(context)[:1500]
    return (
        "You are an INDEPENDENT reviewer checking the work of a smaller LOCAL model (gemma) inside a personal "
        "PAPER-trading research system. ADVISORY ONLY — never tell the user to place/buy/sell/route an order, "
        "and never invent a number, price, or analyst figure that is not given.\n\n"
        f"Task the local model performed: {task}\n\n"
        "What the LOCAL model concluded:\n\"\"\"\n" + str(local_output)[:4000] + "\n\"\"\"" + ctx + "\n\n"
        "Review it as a second opinion. Is the local model's conclusion sound given the facts, or is it "
        "over/under-reacting, missing context, or internally inconsistent?\n"
        + build_cloud_review_json_schema()
    )


def _parse(raw):
    obj = parse_cloud_review_result(raw)
    if obj:
        return {"verdict": obj.get("verdict", "UNKNOWN"), "assessment": obj.get("assessment", ""),
                "concerns": obj.get("concerns", []), "corrections": obj.get("corrections", []),
                "evidence": obj.get("evidence", []), "data_i_doubt": obj.get("data_i_doubt"),
                "agent_contract": obj.get("agent_contract")}
    txt = str(raw or "").strip()
    m = re.search(r"\{.*\}", txt, re.DOTALL)
    if m:
        try:
            legacy = json.loads(m.group(0))
        except Exception:
            legacy = None
    else:
        legacy = None
    if isinstance(legacy, dict):
        v = str(legacy.get("verdict", "")).upper()
        verdict = next((x for x in ("DISAGREE", "CAUTION", "AGREE") if x in v), "UNKNOWN")
        return {"verdict": verdict, "assessment": str(legacy.get("assessment", ""))[:600],
                "concerns": [str(c)[:240] for c in (legacy.get("concerns") or [])][:8],
                "corrections": [str(c)[:240] for c in (legacy.get("corrections") or [])][:8]}
    up = txt.upper()
    verdict = next((x for x in ("DISAGREE", "CAUTION", "AGREE") if x in up), "UNKNOWN")
    return {"verdict": verdict, "assessment": txt[:600], "concerns": [], "corrections": []}


def _persist(task, source, symbol, local_output, lane, out):
    from db_adapter import _get_conn
    conn = _get_conn()
    cur = conn.cursor()
    meta = {"task": task, "symbol": symbol, "lane": lane, "verdict": out.get("verdict"),
            "concerns": out.get("concerns"), "corrections": out.get("corrections"),
            "local_output_preview": str(local_output)[:500]}
    cur.execute("""INSERT INTO llm_feedback_observations
        (source_table, workflow, model_role, model_name, decision_action, human_review_label, notes, metadata_json)
        VALUES (%s,'cloud_review','reviewer',%s,%s,%s,%s,%s)""",
                (source[:60], f"{lane}:{out.get('model', LANE_MODEL.get(lane, ''))}",
                 f"review_{(out.get('verdict') or 'unknown').lower()}",
                 (out.get("verdict") or "UNKNOWN"),
                 ((symbol + ": ") if symbol else "") + (out.get("assessment") or "")[:400],
                 json.dumps(meta)[:4000]))
    conn.commit()


def _review_one(lane, task, local_output, context, timeout):
    out = {"ok": False, "available": False, "verdict": "UNKNOWN", "lane": lane, "model": LANE_MODEL.get(lane)}
    try:
        import llm_lane
        if not llm_lane.available(lane):
            out["error"] = f"{lane} lane unavailable"
            return out
        raw = llm_lane.generate(_build_prompt(task, local_output, context), lane=lane,
                                timeout=timeout, model=LANE_MODEL.get(lane))
        out.update(ok=True, available=True, raw=str(raw)[:6000], **_parse(raw))
    except Exception as e:
        out["error"] = str(e)[:200]
    return out


def review(task, local_output, context=None, *, lanes=DEFAULT_LANES, timeout=180,
           persist=True, symbol=None, source=None):
    """Free-OAuth cloud lanes review the local LLM's output. Returns per-lane verdicts + consensus. Never
    raises (advisory). Lanes that are down are skipped."""
    result = {"ok": False, "task": task, "lanes": {}}
    for lane in lanes:
        r = _review_one(lane, task, local_output, context, timeout)
        result["lanes"][lane] = r
        if r.get("ok") and persist:
            try:
                _persist(task, source or task, symbol, local_output, lane, r)
            except Exception:
                pass
    oks = [r for r in result["lanes"].values() if r.get("ok")]
    result["ok"] = bool(oks)
    verdicts = [r["verdict"] for r in oks]
    result["consensus"] = {
        "lanes_ok": len(oks),
        "agree": verdicts.count("AGREE"), "caution": verdicts.count("CAUTION"),
        "disagree": verdicts.count("DISAGREE"),
        # worst-case wins: any DISAGREE -> DISAGREE; else any CAUTION -> CAUTION; else AGREE
        "verdict": ("DISAGREE" if "DISAGREE" in verdicts else
                    "CAUTION" if "CAUTION" in verdicts else
                    "AGREE" if "AGREE" in verdicts else "UNKNOWN"),
    }
    return result


if __name__ == "__main__":
    r = review("smoke_test", "The stock is a strong buy because RSI is 71 (overbought is bullish).",
               context={"rsi": 71, "note": "RSI 70+ is typically OVERbought, not bullish"}, persist=False)
    print(json.dumps(r, indent=2, default=str))
