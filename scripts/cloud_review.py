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
        from lib.oauth_lane_status import lane_available, lanes_available
        if lane:
            return lane_available(str(lane).lower())
        la = lanes_available()
        return any(la.get(ln) for ln in DEFAULT_LANES)
    except Exception:
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
                                timeout=timeout, model=LANE_MODEL.get(lane),
                                process_id="cloud_review",
                                task_summary=f"cloud_review:{task[:80]}")
        out.update(ok=True, available=True, raw=str(raw)[:6000], **_parse(raw))
    except Exception as e:
        out["error"] = str(e)[:200]
    return out


def _free_oauth_bottleneck_rollover_cfg() -> dict:
    """Load free-OAuth → DeepSeek Flash rollover policy from Hermes budget YAML.

    Default: enabled (hybrid). Fail closed (no Pro) if config missing/malformed.
    """
    try:
        import yaml  # type: ignore
        path = ROOT / "config" / "hermes_research_budget.yaml"
        if not path.exists():
            return {"enabled": True, "lane": "deepseek-flash", "model": "deepseek-v4-flash"}
        pol = yaml.safe_load(path.read_text()) or {}
        cfg = ((pol.get("cloud_unavailable") or {}).get("free_oauth_bottleneck_rollover")
               or {})
        if not isinstance(cfg, dict):
            return {"enabled": True, "lane": "deepseek-flash", "model": "deepseek-v4-flash"}
        return cfg
    except Exception:
        return {"enabled": True, "lane": "deepseek-flash", "model": "deepseek-v4-flash"}


def _deepseek_flash_rollover_review(task, local_output, context, timeout, *, reason: str) -> dict:
    """Explicit paid rollover when free-OAuth bottlenecks. FAST / deepseek-v4-flash only.

    Uses llm_lane deepseek-flash (credential: deepseek_tradeai / Bitwarden).
    Never Pro / PRO_THINK / PRO_MAX. Failures return ok=False (advisory).
    """
    out = {
        "ok": False,
        "available": False,
        "verdict": "UNKNOWN",
        "lane": "deepseek-flash",
        "model": "deepseek-v4-flash",
        "rollover": True,
        "rollover_reason": reason,
        "policy": "FAST",
    }
    cfg = _free_oauth_bottleneck_rollover_cfg()
    if cfg.get("enabled") is False:
        out["error"] = "deepseek_rollover_disabled"
        return out
    if cfg.get("never_pro") is False:
        # Safety: ignore attempts to enable Pro via config
        pass
    model = str(cfg.get("model") or "deepseek-v4-flash")
    lane = str(cfg.get("lane") or "deepseek-flash")
    if model != "deepseek-v4-flash" or lane not in ("deepseek-flash", "deepseek-v4-flash", "fast"):
        out["error"] = f"deepseek_rollover_forbidden_model lane={lane} model={model}"
        return out
    try:
        import llm_lane
        if not llm_lane.available("deepseek-flash"):
            out["error"] = "deepseek-flash lane unavailable (not ready or no credential)"
            return out
        raw = llm_lane.generate(
            _build_prompt(task, local_output, context),
            lane="deepseek-flash",
            timeout=min(int(timeout or 180), 180),
            model="deepseek-v4-flash",
            process_id="hermes_external_research",
            task_summary=f"free_oauth_bottleneck_rollover:{task[:60]}",
        )
        out.update(ok=True, available=True, raw=str(raw)[:6000], **_parse(raw))
    except Exception as e:
        out["error"] = str(e)[:240]
    return out


def review(task, local_output, context=None, *, lanes=DEFAULT_LANES, timeout=180,
           persist=True, symbol=None, source=None,
           allow_deepseek_rollover: bool = True):
    """Free-OAuth cloud lanes review the local LLM's output.

    Hybrid: ChatGPT + Grok first. If free-OAuth bottlenecks (zero successful
    lanes) and allow_deepseek_rollover=True, attempt one DeepSeek V4 Flash
    FAST call (paid, cost-gated via llm_lane / deepseek_tradeai). Never Pro.
    Never raises (advisory). Lanes that are down are skipped.
    """
    result = {
        "ok": False,
        "task": task,
        "lanes": {},
        "free_oauth_bottleneck": False,
        "deepseek_rollover_used": False,
    }
    free_lanes = tuple(ln for ln in lanes if ln in DEFAULT_LANES) or DEFAULT_LANES
    for lane in free_lanes:
        r = _review_one(lane, task, local_output, context, timeout)
        result["lanes"][lane] = r
        if r.get("ok") and persist:
            try:
                _persist(task, source or task, symbol, local_output, lane, r)
            except Exception:
                pass
    oks = [r for r in result["lanes"].values() if r.get("ok")]
    # Free-OAuth bottleneck → optional DeepSeek Flash rollover
    if not oks and allow_deepseek_rollover:
        free_any = any(result["lanes"].get(ln, {}).get("available") for ln in free_lanes)
        reason = ("free_oauth_zero_ok_lanes" if free_any or result["lanes"]
                  else "free_oauth_unavailable")
        result["free_oauth_bottleneck"] = True
        ds = _deepseek_flash_rollover_review(
            task, local_output, context, timeout, reason=reason)
        result["lanes"]["deepseek-flash"] = ds
        if ds.get("ok"):
            result["deepseek_rollover_used"] = True
            if persist:
                try:
                    _persist(task, source or task, symbol, local_output,
                             "deepseek-flash", ds)
                except Exception:
                    pass
            oks = [ds]
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
        "deepseek_rollover_used": result["deepseek_rollover_used"],
        "free_oauth_bottleneck": result["free_oauth_bottleneck"],
    }
    return result


if __name__ == "__main__":
    r = review("smoke_test", "The stock is a strong buy because RSI is 71 (overbought is bullish).",
               context={"rsi": 71, "note": "RSI 70+ is typically OVERbought, not bullish"}, persist=False)
    print(json.dumps(r, indent=2, default=str))
