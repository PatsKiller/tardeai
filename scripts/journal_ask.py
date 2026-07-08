#!/usr/bin/env python3
"""journal_ask.py — natural-language Q&A over the trade journal (2026-06-15).

"Why do I lose on Thursdays?", "Best session for my scalps?", "Which strategy should I cut?" —
answered from the operator's REAL journal analytics (journal_analytics_engine) via the free Grok
lane (local-gemma fallback). Read-only; the engine does pure SELECTs.
"""
from __future__ import annotations
import json, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except Exception:
    pass


def gather_context(account=None, days=180) -> dict:
    import journal_analytics_engine as eng
    a = eng.run(account, days)
    # compact: drop the per-trade equity points (keep the summary), keep the breakdowns
    eq = dict(a["equity_curve"]); eq.pop("points", None)
    return {
        "filters": a["filters"],
        "overall": a["overall"],
        "equity": eq,
        "by_day_of_week": a["time_analysis"]["by_day_of_week"],
        "by_session": a["time_analysis"]["by_session"],
        "by_hour": a["time_analysis"]["by_hour"],
        "by_strategy": a["setup_breakdown"]["by_strategy"],
        "by_setup": a["setup_breakdown"]["by_setup"],
        "by_emotion": a["setup_breakdown"]["by_emotion"],
        "top_mistakes": a["setup_breakdown"]["top_mistakes"],
        "r_distribution": a["r_distribution"],
    }


def ask(question: str, account=None, days=180, lane: str | None = None, manual_trigger: bool = False) -> dict:
    ctx = gather_context(account, days)
    try:
        import llm_lane
        use = (lane or "").strip().lower() or None
        if use not in ("grok", "chatgpt", "local"):
            use = "grok" if llm_lane.available("grok") else "local"
        prompt = (
            "You are a sharp, honest trading-journal coach. Answer the trader's question using ONLY the "
            "journal analytics below — cite the actual numbers (win rate, net P&L, R, trade counts) and "
            "give ONE concrete, actionable takeaway. If the data is too thin to answer (small sample, "
            "missing reviews), say so plainly rather than inventing. Be specific and concise (4-7 "
            "sentences). Flag any edge or leak you see (e.g. a losing day-of-week or session).\n\n"
            f"QUESTION: {question}\n\nJOURNAL ANALYTICS (account={ctx['filters']['account']}, "
            f"last {ctx['filters']['days']}d):\n{json.dumps(ctx, indent=2, default=str)}")
        gen_kw = dict(lane=use, timeout=90)
        if use in ("grok", "chatgpt"):
            gen_kw.update(process_id="journal_ask", task_summary=question[:120],
                          manual_trigger=bool(manual_trigger or lane))
        out = llm_lane.generate(prompt, **gen_kw)
        answer = out if (out and not str(out).startswith("LLM error")) else "(LLM unavailable — try again)"
        model = {"grok": "grok-oauth", "chatgpt": "chatgpt-oauth"}.get(use, "local")
    except Exception as e:
        err = str(e)
        if "ManualRequired" in type(e).__name__ or "manual_mode" in err:
            return {"question": question, "ok": False, "manual_required": True,
                    "error": "journal_ask is Manual — pick ▶ Grok or ▶ ChatGPT", "context": ctx}
        answer, model = f"(error: {err[:80]})", "none"
    return {"question": question, "answer": str(answer).strip(), "model": model, "lane": use, "context": ctx}


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "What is my biggest edge and my biggest leak?"
    print(json.dumps(ask(q), indent=2, default=str))
