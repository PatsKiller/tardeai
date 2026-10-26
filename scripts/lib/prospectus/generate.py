"""Prompt, governed model call, validation and the Prospectus@v1 document.

The model writes prose sections only. Every chart is built here from the same house series the facts came from,
so no chart value is model output. Text is guarded twice before it is kept: a sentence carrying a number no fact
supplies is dropped (``ungrounded_number``), and a sentence that sizes, orders, stops or weights is dropped
(MBI_BEHAVIOR=0). Both drops are logged in ``guard_log``; nothing is dropped silently.

Model routing: ``prospectus_writer`` (Claude Opus 5.5, effort high) and ``prospectus_writer_premium`` (Claude Fable
5.1, effort high, thinking parameter omitted) through ``llm_consumption.gate_and_generate`` — the governed credit
path (process caps + promotional credit book). Both processes are Anthropic-only: an unusable credit raises, and the
job is QUEUED (never a paid fallback). A premium refusal or invalid output falls back to Opus, once.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from typing import Any, Callable, Optional

from . import CHART_IDS, DELTA_SECTION_IDS, SCHEMA, SECTION_TITLES, sections_for
from .inputs import Bundle

CITE_RE = re.compile(r"\[(F\d+(?:\s*,\s*F\d+)*)\]")
ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:T[\d:.]+Z?)?\b")
SENTENCE_RE = re.compile(r"(?<=[.!?;])\s+")
CREDIT_CODES = ("ANTHROPIC_CREDIT_UNAVAILABLE", "PAUSED_TODAY", "EXHAUSTED", "EXPIRED", "UNAVAILABLE", "DISABLED",
                "NOT_CONFIGURED", "NOT_STARTED", "CREDIT_", "COST_CAP", "PROCESS_CAP", "CALL_COST_CEILING",
                "RATE_LIMITED", "OVERLOADED", "PROVIDER_DISABLED", "GOVERNANCE_UNAVAILABLE", "manual_mode",
                "DEADLINE_EXCEEDED", "TIMEOUT", "COST_PERSISTENCE_UNAVAILABLE", "NO_ROUTE_AVAILABLE")


class QueueLater(RuntimeError):
    """The credit (or a cap) is unavailable now: keep the job queued, spend nothing elsewhere."""


class GenerationFailed(RuntimeError):
    pass


def _cio_ask():
    try:
        from lib import cio_ask_research as mod  # type: ignore
    except ImportError:
        from scripts.lib import cio_ask_research as mod  # type: ignore
    return mod


# ── prompt ────────────────────────────────────────────────────────────────────────────────────────────────────
def build_prompt(bundle: Bundle, *, mode: str = "full", previous: dict | None = None, max_bytes: int = 60000,
                 section_words: str = "120-260") -> str:
    ids = sections_for(bundle.scope) if mode == "full" else tuple(
        s for s in DELTA_SECTION_IDS if s in sections_for(bundle.scope))
    facts = list(bundle.facts)
    head = [
        f"You are writing a research prospectus on {bundle.symbol} ({bundle.name}) for a single private investor. "
        f"It is a {'current holding' if bundle.scope == 'holding' else 'watch-list name'}.",
        "Write like a careful sell-side analyst writing for one reader: plain, specific, balanced, no hype.",
        "",
        "Rules:",
        "- Every number you write must be one of the FACTS values below (you may round it). Cite the fact ids in "
        "brackets right after the claim, e.g. [F3] or [F3, F7]. Do not compute new numbers; derived figures you "
        "need are already supplied as facts.",
        "- If a fact you would need is missing, say the data is not available rather than estimating.",
        "- This is advisory research. Do not tell the reader to buy, sell, size, set or move a stop, or place any "
        "order. Describe the recorded stop level only as a fact.",
        "- Refer to accounts by their names only.",
        "",
        "Return ONLY a JSON object, no prose around it:",
        '{"verdict_line": "<one sentence, at most 25 words>", "sections": [{"id": "<section id>", "title": "<title>", '
        '"body_md": "<markdown: short paragraphs and bullet lists>", "citations": ["F1", "F2"]}], "scenarios": [...], "notes": {...}}',
        "Sections, in this order: " + ", ".join(f"{s} ({SECTION_TITLES[s]})" for s in ids) + ".",
        f"Aim for {section_words} words per section"
        + ("" if section_words == "120-260" else " (a concise report: every section, no padding)")
        + "; thesis_breakers is a bullet list of observable conditions that would "
        "prove the thesis wrong. Use the macro, SEC filing, ownership, peer and relative-performance facts where they "
        "bear on the name; cite web facts (W-prefixed sources) with their fact ids like any other fact.",
        "Also return \"scenarios\": three objects {\"case\": \"bear\"|\"base\"|\"bull\", \"price_fact\": <the fact "
        "id of the analyst target low, mean or high that anchors the case>, \"probability_pct\": <integer, the three "
        "summing to 100; this is your stated judgment>, \"narrative\": <2-3 sentences citing fact ids>}. If no analyst "
        "targets are supplied, return an empty list.",
        "Also return \"notes\": {\"macro_effects\": {\"rates\", \"curve\", \"inflation\", \"labor\", \"credit\", "
        "\"dollar_oil\": <one short phrase each: headwind / tailwind / neutral for THIS name and why, citing fact ids>}, "
        "\"earnings_call\": {\"guidance\", \"demand_margin\", \"tone\", \"hard_questions\": <one or two sentences "
        "each from transcript or web facts, quoting management only when a fact carries the quote; say \"not in the "
        "sources\" otherwise>}, \"filings\": {<form>: <what changed, one sentence citing the filing fact>}}.",
    ]
    if mode == "delta" and previous:
        head += ["", "This is a weekly update. The previous verdict was: "
                 + json.dumps(previous.get("verdict_line") or "")[:400]
                 + ". Rewrite only the listed sections from the current facts and say what changed."]
    if bundle.gaps:
        head += ["", "Known data gaps: " + "; ".join(bundle.gaps)]
    tail = ["", "FACTS (id | label | value or text | source | as of):"]
    lines = []
    for f in facts:
        val = f"{f['value']}{(' ' + f['unit']) if f.get('unit') else ''}" if "value" in f else f.get("text", "")
        if f.get("unreliable"):  # quality gate SOFT_FAIL: the writer never sees the number
            val = f"NOT RELIABLE ({f['unreliable']}) - do not cite"
        lines.append(f"{f['id']} | {f['label']} | {val} | {f['source']} | {f.get('as_of') or 'n/a'}")
    prompt = "\n".join(head + tail + lines)
    while len(prompt.encode("utf-8")) > max_bytes and lines:
        lines.pop()  # facts are ordered most-important first; trim the tail (web/news) to the byte budget
        prompt = "\n".join(head + tail + lines + ["(further facts omitted for length)"])
    return prompt


# ── parsing and guards ────────────────────────────────────────────────────────────────────────────────────────
def parse_output(text: str) -> dict:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", raw)
    try:
        doc = json.loads(raw)
    except ValueError:
        match = re.search(r"\{.*\}", raw, re.S)
        if not match:
            raise GenerationFailed("OUTPUT_NOT_JSON")
        try:
            doc = json.loads(match.group(0))
        except ValueError as exc:
            raise GenerationFailed("OUTPUT_NOT_JSON") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("sections"), list):
        raise GenerationFailed("OUTPUT_SCHEMA_INVALID")
    return doc


def allowed_values(bundle: Bundle) -> list[float]:
    mod = _cio_ask()
    out: list[float] = []
    for f in bundle.facts:
        if f.get("unreliable"):
            continue  # quality gate: a sentence carrying an unreliable number is dropped like an ungrounded one
        if "value" in f:
            out += [f["value"], abs(f["value"])]
        for m in mod._NUM_TOKEN_RE.finditer(f.get("text") or ""):
            x = mod._num(m.group(1).replace(",", ""))
            if x is not None:
                out.append(x * {"k": 1e3, "m": 1e6, "b": 1e9}.get((m.group(2) or "").lower(), 1))
    return out


def guard_text(text: str, values: list[float], *, where: str, log: list[dict]) -> str:
    """Line-preserving guard: drop ungrounded-number and behavior sentences, keep markdown structure."""
    mod = _cio_ask()
    kept_lines = []
    for line in str(text or "").splitlines():
        kept = []
        for sent in SENTENCE_RE.split(line):
            if not sent.strip():
                continue
            probe = ISO_DATE_RE.sub(" ", CITE_RE.sub(" ", sent))
            probe = re.sub(r"^\s*(?:[-*]|\d{1,2}[.)])\s+", " ", probe)
            bad = mod.ungrounded_numbers(probe, values, rel_tol=0.006)
            if bad:
                log.append({"where": where, "reason": "ungrounded_number", "numbers": bad[:5], "excerpt": sent.strip()[:160]})
                continue
            if not mod.strip_behavior_text(probe, where=where, log=log).strip():
                continue
            kept.append(sent)
        if kept:
            kept_lines.append(" ".join(kept))
        elif not line.strip():
            kept_lines.append("")
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept_lines)).strip()


def validate(doc: dict, bundle: Bundle, *, mode: str = "full", previous: dict | None = None) -> tuple[list[dict], str, list[dict]]:
    """Return (sections, verdict_line, guard_log). Raises GenerationFailed when too little survives."""
    expected = sections_for(bundle.scope)
    wanted = expected if mode == "full" else tuple(s for s in DELTA_SECTION_IDS if s in expected)
    values = allowed_values(bundle)
    known = {f["id"] for f in bundle.facts}
    log: list[dict] = []
    by_id = {}
    for sec in doc.get("sections") or []:
        if isinstance(sec, dict) and sec.get("id") in wanted and isinstance(sec.get("body_md"), str):
            by_id.setdefault(sec["id"], sec)
    prev = {s["id"]: s for s in (previous or {}).get("sections") or [] if isinstance(s, dict)}
    out, empty = [], []
    for sid in expected:
        sec = by_id.get(sid)
        if sec is None and sid not in wanted and sid in prev:
            out.append(prev[sid])  # delta: unchanged section carried forward from the previous version
            continue
        body = guard_text(sec.get("body_md", "") if sec else "", values, where=sid, log=log)
        cited = set(CITE_RE.findall(body))
        ids = {i.strip() for group in cited for i in group.split(",")}
        ids |= {str(i) for i in (sec or {}).get("citations") or [] if str(i) in known}
        ids &= known
        if not body:
            empty.append(sid)
            body = "_No statement in this section survived source validation; the facts behind it are listed below._"
        out.append({"id": sid, "title": SECTION_TITLES[sid], "body_md": body,
                    "citations": [c for c in (bundle.citation(i) for i in sorted(ids, key=lambda x: int(x[1:]))) if c]})
    verdict = guard_text(str(doc.get("verdict_line") or ""), values, where="verdict_line", log=log)
    if "summary_verdict" in empty or len(empty) > 2:
        raise GenerationFailed(f"OUTPUT_UNGROUNDED: {len(empty)} empty sections")
    return out, verdict[:300], log


# ── charts (house series only) ────────────────────────────────────────────────────────────────────────────────
def build_charts(bundle: Bundle) -> list[dict]:
    s, charts = bundle.series, []
    if s.get("price_1y"):
        ann = []
        pos = s.get("position") or {}
        for level in pos.get("stops") or []:
            ann.append({"kind": "stop", "y": level, "label": "Recorded stop"})
        if pos.get("avg_cost"):
            ann.append({"kind": "entry", "y": pos["avg_cost"], "label": "Average cost"})
        tgt = s.get("analyst_targets") or {}
        if tgt.get("mean"):
            ann.append({"kind": "target", "y": tgt["mean"], "label": "Mean analyst target"})
        charts.append({"id": "price_1y", "type": "line", "title": "Price, last 12 months",
                       "series": [{"name": "Close", "points": [[d, v] for d, v in s["price_1y"]]}], "annotations": ann})
    if s.get("revenue_eps_trend"):
        charts.append({"id": "revenue_eps_trend", "type": "bar", "title": "Revenue and EPS growth (%)",
                       "series": [{"name": "Growth %", "points": [[label, v] for label, v in s["revenue_eps_trend"]]}]})
    if s.get("valuation_vs_peers"):
        rows = s["valuation_vs_peers"]
        charts.append({"id": "valuation_vs_peers", "type": "bar", "title": "Valuation vs industry median",
                       "series": [{"name": bundle.symbol, "points": [[label, mine] for label, mine, _ in rows]},
                                  {"name": "Industry median", "points": [[label, med] for label, _, med in rows]}]})
    if s.get("analyst_targets"):
        t = s["analyst_targets"]
        pts = [["Low", t["low"]], ["Mean", t.get("mean")], ["High", t["high"]]]
        ann = [{"kind": "range", "low": t["low"], "high": t["high"], "label": "Analyst range"}]
        if t.get("mean") is not None:
            ann.append({"kind": "mean", "y": t["mean"], "label": "Mean target"})
        if t.get("price"):
            ann.append({"kind": "current", "y": t["price"], "label": "Last close"})
        charts.append({"id": "analyst_targets", "type": "range", "title": "Analyst price targets",
                       "series": [{"name": "Targets", "points": [p for p in pts if p[1] is not None]}], "annotations": ann})
    pos = s.get("position") or {}
    if bundle.scope == "holding" and pos.get("market_value") is not None and pos.get("cost_basis"):
        charts.append({"id": "position_pl", "type": "bar", "title": "Position: cost vs market value ($)",
                       "series": [{"name": "Position", "points": [["Cost basis", pos["cost_basis"]],
                                                                   ["Market value", pos["market_value"]]]}],
                       "annotations": [{"kind": "note", "label": "Unrealized P/L", "y": pos.get("unrealized_pl")}]})
    rel = (bundle.blocks.get("relative_performance") or {}).get("series") or {}
    for window in ("1Y", "YTD", "3M", "3Y"):
        if rel.get(window):
            charts.append({"id": "relative_performance", "type": "line", "title": f"Relative performance, rebased to 100 ({window})",
                           "window": window, "series": rel[window], "windows": {w: rel[w] for w in rel}})
            break
    eps = (bundle.blocks.get("estimates") or {}).get("eps_surprises") or []
    if any(e.get("surprise_pct") is not None for e in eps):
        charts.append({"id": "eps_surprise", "type": "bar", "title": "EPS surprise (%)",
                       "series": [{"name": "Surprise %", "points": [[e.get("date") or "last", e["surprise_pct"]]
                                                                     for e in eps if e.get("surprise_pct") is not None]}]})
    return [c for c in charts if c["id"] in CHART_IDS]


# ── the governed call ─────────────────────────────────────────────────────────────────────────────────────────
def governed_generate(prompt: str, *, process_id: str, max_tokens: int, timeout: float,
                      manual: bool = False) -> tuple[str, dict]:
    """One call through the governed credit path. Never a direct provider call."""
    try:
        from lib import llm_consumption as lc  # type: ignore
    except ImportError:
        from scripts.lib import llm_consumption as lc  # type: ignore
    cfg = lc.get_process_config(process_id)
    lane = (cfg.get("allowed_lanes") or ["pro"])[0]
    text, prov = lc.gate_and_generate(prompt, process_id=process_id, lane=lane, max_tokens=max_tokens,
                                      timeout=int(timeout), manual_trigger=manual, return_provenance=True,
                                      task_summary=f"prospectus {process_id}")
    return str(text or ""), dict(prov or {})


def _credit_refusal(exc: BaseException) -> bool:
    text = f"{getattr(exc, 'code', '')} {getattr(exc, 'reason', '')} {exc}"
    return any(code in text for code in CREDIT_CODES)


def plan_prompt(bundle: Bundle, max_uses: int, *, max_bytes: int = 40000) -> str:
    """Turn 1 of the bounded search loop: the model names the web searches it needs (house facts first)."""
    base = build_prompt(bundle, max_bytes=max_bytes)
    return (base.split("FACTS (id |", 1)[0].split("Return ONLY a JSON object", 1)[0]
            + f"Before writing, decide what the house facts below do NOT cover that a careful analyst would need "
            f"(recent guidance, earnings-call commentary, filings, competitive or regulatory news). Return ONLY a JSON "
            f'object {{"searches": [{{"query": "<web search query>", "why": "<the gap it fills>"}}]}} with at most '
            f"{max_uses} searches, or an empty list if the house facts suffice.\n\nFACTS (id |"
            + base.split("FACTS (id |", 1)[1])


def web_loop(bundle: Bundle, *, process_id: str, cfg: dict, generate_fn: Callable, search_fn: Callable | None,
             allowance_fn: Callable[[bool], int] | None, manual: bool, now: datetime) -> dict:
    """Bounded tool loop through the governed path: plan (one model turn) → searches (governed router) → facts.

    The transport refuses tool definitions (TOOLS_UNSUPPORTED), so the loop is a two-turn protocol: this plan turn and
    the writing turn. Searches count against the job's daily paid allowance and Brave's own budget; when either is
    exhausted the prospectus is written from house data and the gap says so.
    """
    web = cfg.get("web") or {}
    max_uses = int((web.get("max_uses") or {}).get(bundle.scope, 0))
    out = {"max_uses": max_uses, "planned": [], "searches": [], "stopped": None, "plan_cost_usd": 0.0}
    if search_fn is None or max_uses <= 0:
        out["stopped"] = "web search disabled for this run"
        return out
    if allowance_fn is not None and allowance_fn(False) <= 0:
        out["stopped"] = "Brave job allowance for today is used up; written from house data"
        return out
    text, prov = generate_fn(plan_prompt(bundle, max_uses), process_id=process_id,
                             max_tokens=int(web.get("plan_max_output_tokens", 4000)),
                             timeout=float(cfg.get("timeout_s", 900)), manual=manual)
    out["plan_cost_usd"] = float(prov.get("estimated_cost_usd") or 0)
    try:
        plan = json.loads(re.search(r"\{.*\}", str(text), re.S).group(0)).get("searches") or []
    except (AttributeError, ValueError, TypeError):
        plan = []
    for item in plan[:max_uses]:
        query = str((item or {}).get("query") or "").strip()[:200] if isinstance(item, dict) else str(item)[:200]
        if not query:
            continue
        out["planned"].append(query)
        if allowance_fn is not None and allowance_fn(False) <= 0:
            out["stopped"] = "Brave job allowance for today is used up; remaining searches skipped"
            break
        res = search_fn(query, bundle.symbol) or {}
        paid = str(res.get("provider") or "").lower().startswith("brave")
        if paid and allowance_fn is not None:
            allowance_fn(True)
        row = {"query": query, "ok": bool(res.get("ok")), "provider": res.get("provider"), "reason": res.get("reason"),
               "results": 0, "at": now.isoformat()}
        if not res.get("ok"):
            out["searches"].append(row)
            if "budget" in str(res.get("reason") or "").lower() or "cap" in str(res.get("reason") or "").lower():
                out["stopped"] = f"search budget exhausted ({res.get('reason')}); written from house data"
                break
            continue
        for r in (res.get("results") or [])[:4]:
            if not str(r.get("url") or "").startswith(("http://", "https://")):
                continue
            fid = bundle.add("web", f"Web — {r.get('source') or r.get('engine') or 'search'}: {str(r.get('title') or '')[:90]}",
                             text=(r.get("title") or "") + (" — " + str(r.get("content"))[:220] if r.get("content") else ""),
                             source=f"web via governed search_router ({res.get('provider') or 'router'})",
                             as_of=r.get("published") or r.get("published_at") or now.date().isoformat(), url=r.get("url"))
            if fid:
                row["results"] += 1
        out["searches"].append(row)
    return out


def validate_scenarios(raw: Any, bundle: Bundle, *, log: list[dict]) -> dict:
    """Bear/base/bull anchored on cited analyst-target facts; probabilities are the model's stated judgment."""
    anchors = {f["id"]: f for f in bundle.facts if f["label"] in ("Analyst target low", "Analyst target mean", "Analyst target high")}
    values = allowed_values(bundle)
    rows = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or item.get("case") not in ("bear", "base", "bull"):
            continue
        fact = anchors.get(str(item.get("price_fact")))
        if fact is None:
            log.append({"where": "scenarios", "reason": "scenario price not anchored on an analyst target fact"})
            continue
        prob = item.get("probability_pct")
        prob = int(prob) if isinstance(prob, (int, float)) and 0 <= prob <= 100 else None
        rows.append({"case": item["case"], "price": fact["value"], "price_fact": fact["id"], "probability_pct": prob,
                     "narrative": guard_text(str(item.get("narrative") or ""), values, where=f"scenarios.{item['case']}", log=log)})
    probs = [r["probability_pct"] for r in rows]
    if rows and (None in probs or abs(sum(probs) - 100) > 1 or len({r["case"] for r in rows}) != len(rows)):
        log.append({"where": "scenarios", "reason": "probabilities missing or not summing to 100; cleared"})
        for r in rows:
            r["probability_pct"] = None
    order = {"bear": 0, "base": 1, "bull": 2}
    return {"cases": sorted(rows, key=lambda r: order[r["case"]]),
            "probability_basis": "the writer model's stated judgment from the cited facts; not a forecast",
            "footer": "Scenario analysis, not an order or a recommendation to trade.",
            "gaps": [] if rows else ["no scenarios: analyst targets unavailable or the writer returned none"]}


NOTE_KEYS = {"macro_effects": ("rates", "curve", "inflation", "labor", "credit", "dollar_oil"),
             "earnings_call": ("guidance", "demand_margin", "tone", "hard_questions")}


def validate_notes(raw: Any, bundle: Bundle, *, log: list[dict]) -> dict:
    """Short writer notes for the macro, earnings-call and filings blocks; guarded like the sections."""
    values = allowed_values(bundle)
    raw = raw if isinstance(raw, dict) else {}
    out: dict[str, dict] = {}
    for group, keys in NOTE_KEYS.items():
        src = raw.get(group) if isinstance(raw.get(group), dict) else {}
        out[group] = {k: (guard_text(str(src.get(k) or ""), values, where=f"notes.{group}.{k}", log=log)[:400] or None)
                      for k in keys}
    filings = raw.get("filings") if isinstance(raw.get("filings"), dict) else {}
    out["filings"] = {str(k)[:12]: guard_text(str(v), values, where=f"notes.filings.{k}", log=log)[:300]
                      for k, v in list(filings.items())[:12] if v}
    return out


def apply_notes(blocks: dict, notes: dict) -> None:
    macro = blocks.setdefault("macro_sensitivity", {"series": {}})
    macro["effects"] = notes.get("macro_effects") or {}
    call = blocks.setdefault("earnings_call", {"transcripts": [], "gaps": []})
    call.update(notes.get("earnings_call") or {})
    sec = blocks.setdefault("sec_filings", {"filings": []})
    for f in sec.get("filings") or []:
        if notes.get("filings", {}).get(f["form"]):
            f["writer_note"] = notes["filings"][f["form"]]


def source_coverage(bundle: Bundle, web: dict) -> dict:
    registry = list(bundle.context.get("registry_coverage") or [])
    for row in registry:
        if row["domain"] == "web_search":
            n = sum(s.get("results", 0) for s in web.get("searches") or [])
            row.update(status="used" if n else ("empty" if web.get("searches") else "not_applicable"),
                       reason=web.get("stopped") or f"{len(web.get('searches') or [])} searches, {n} results")
    from .inputs import key_gaps
    gaps = key_gaps(bundle)
    return {"domains": registry, "house_sources": bundle.coverage, "web_searches": web.get("searches") or [],
            "web_planned": web.get("planned") or [], "web_stopped": web.get("stopped"), "key_gaps": gaps,
            "counts": {s: sum(1 for r in registry if r["status"] == s)
                       for s in ("used", "stale", "empty", "failed", "not_applicable")}}


GEN_CONFIG_REL = "config/prospectus_generation.json"
GEN_DEFAULTS = {"holding": {"effort": "high", "max_output_tokens": 16000, "batch": False, "section_words": "120-260",
                            "expected_output_tokens": 9000},
                "watch": {"effort": "high", "max_output_tokens": 16000, "batch": False, "section_words": "120-260",
                          "expected_output_tokens": 9000}}


def generation_config(root: Any = None) -> dict:
    """Per-scope generation settings (config/prospectus_generation.json); defaults are the pre-2026-10-26 behaviour."""
    from pathlib import Path
    path = Path(root or Path(__file__).resolve().parents[3]) / GEN_CONFIG_REL
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        doc = {}
    out = {"generation": {k: dict(v) for k, v in GEN_DEFAULTS.items()}, "batch": dict(doc.get("batch") or {})}
    for scope, row in (doc.get("generation") or {}).items():
        out["generation"].setdefault(scope, {}).update(row or {})
    return out


def scope_settings(scope: str, gen: dict | None = None) -> dict:
    gen = gen or generation_config()
    return dict(gen["generation"].get("holding" if scope == "holding" else "watch") or GEN_DEFAULTS["watch"])


def run_gate(bundle: Bundle, *, now: datetime, ai_fn: Any) -> tuple[dict, dict]:
    """The data-quality gate: raises ``DataBlocked`` on HARD_FAIL, tags unreliable facts on SOFT_FAIL."""
    from . import quality_gate as qg
    settings = qg.load_settings()
    gate = qg.pre_write(qg.packet_from_bundle(bundle, now=now), settings=settings, ai_fn=ai_fn)
    if gate["status"] == qg.HARD:
        raise qg.DataBlocked(gate)
    if gate["status"] == qg.SOFT:
        qg.apply_unreliable(bundle, gate)
    return gate, settings


def max_tokens_for(bundle: Bundle, cfg: dict, mode: str, gen: dict | None = None) -> int:
    if mode == "delta":
        return int(cfg.get("delta_max_output_tokens", 6000))
    return int(scope_settings(bundle.scope, gen).get("max_output_tokens") or cfg.get("max_output_tokens", 16000))


def writer_prompt(bundle: Bundle, cfg: dict, *, mode: str, previous: dict | None, gen: dict | None = None) -> str:
    words = str(scope_settings(bundle.scope, gen).get("section_words") or "120-260")
    return build_prompt(bundle, mode=mode, previous=previous, max_bytes=int(cfg.get("max_prompt_bytes", 60000)),
                        section_words=words)


def finish_doc(bundle: Bundle, text: str, prov: dict, *, gate: dict, settings: dict, web: dict, mode: str,
               previous: dict | None, now: datetime, version: str, process_id: str,
               fallback: Optional[dict] = None, batch: Optional[dict] = None) -> dict:
    """Parse, guard and assemble one Prospectus@v1 document from the writer's text (sync or batch)."""
    from . import quality_gate as qg
    if str(prov.get("finish_reason") or "") == "refusal":
        raise GenerationFailed("REFUSAL")
    parsed = parse_output(text)
    sections, verdict, log = validate(parsed, bundle, mode=mode, previous=previous)
    scenarios = validate_scenarios(parsed.get("scenarios"), bundle, log=log)
    notes = validate_notes(parsed.get("notes"), bundle, log=log)
    usage = prov.get("usage") or {}
    coverage = source_coverage(bundle, web)
    cost = prov.get("estimated_cost_usd")
    if cost is not None:
        cost = round(float(cost) + float(web.get("plan_cost_usd") or 0)
                     + float((gate["layers"].get("ai") or {}).get("cost_usd") or 0), 6)
    post = qg.post_write(sections, bundle.facts, settings=settings)
    gate["layers"]["post_write"] = post
    gate["rewrite_requested"] = bool(post["rewrite"])
    if post["rewrite"]:
        gate["status"] = qg.SOFT
        gate["reasons"].append(f"post_write_unmatched: {post['unmatched_count']} number(s) match no cited fact "
                               f"(limit {post['limit']})")
    partial = list(coverage["key_gaps"]) + [f"data quality: {r}" for r in gate["reasons"]]
    blocks = dict(bundle.blocks)
    blocks["scenarios"] = scenarios
    apply_notes(blocks, notes)
    doc = {
        "schema": SCHEMA, "symbol": bundle.symbol, "name": bundle.name, "scope": bundle.scope,
        "version": version, "generated_at": now.isoformat(), "mode": mode,
        "status": "partial" if partial else "ready", "partial_gaps": partial, "gate": gate,
        "model": prov.get("returned_model") or prov.get("requested_model_id") or prov.get("model_id"),
        "process_id": process_id, "provider": prov.get("provider"), "cost_usd": cost,
        "usage": {"input_tokens": usage.get("prompt_tokens"), "output_tokens": usage.get("completion_tokens")},
        "verdict_line": verdict, "sections": sections, "charts": build_charts(bundle), "blocks": blocks,
        "source_coverage": coverage, "facts": bundle.facts, "gaps": bundle.gaps, "guard_log": log,
        "fallback": fallback,
        "inputs_digest": {k: bundle.context.get(k) for k in ("cio_stance", "cio_stage", "stop_levels", "next_earnings_date",
                                                             "latest_news_at", "day_move_pct")},
        "advisory": "READ_ONLY_ADVISORY: research only; no sizing, orders, stops or weights. Analysis, not an order.",
    }
    if batch:
        doc["batch"] = batch
    return doc


def write(bundle: Bundle, *, processes: dict, premium: bool, mode: str = "full", previous: dict | None = None,
          cfg: dict, generate_fn: Callable[..., tuple[str, dict]] = governed_generate, manual: bool = False,
          now: datetime | None = None, version: str, search_fn: Callable | None = None,
          allowance_fn: Callable[[bool], int] | None = None, ai_fn: Any = "auto") -> dict:
    """Produce one validated Prospectus@v1 document, or raise QueueLater / GenerationFailed / DataBlocked.

    The data-quality gate (``quality_gate``) runs first, before the web-search planning turn or any other paid call:
    a HARD_FAIL raises ``DataBlocked`` (no model call); a SOFT_FAIL tags the unreliable facts and blocks.
    ``ai_fn="auto"`` uses the governed Haiku read in production and skips it when the writer is stubbed.
    """
    now = now or datetime.now(timezone.utc)
    if ai_fn == "auto":
        from . import quality_gate as qg
        ai_fn = qg.governed_ai_call if generate_fn is governed_generate else None
    gate, settings = run_gate(bundle, now=now, ai_fn=ai_fn)
    gen = generation_config()
    max_tokens = max_tokens_for(bundle, cfg, mode, gen)
    order = [processes["premium"], processes["standard"]] if premium else [processes["standard"]]
    fallback: Optional[dict] = None
    last_error: Optional[str] = None
    web: dict = {"searches": [], "planned": [], "stopped": "not run", "plan_cost_usd": 0.0}
    web_done = False
    for process_id in order:
        try:
            if not web_done:
                web = web_loop(bundle, process_id=process_id, cfg=cfg, generate_fn=generate_fn, search_fn=search_fn,
                               allowance_fn=allowance_fn, manual=manual, now=now)
                web_done = True
            prompt = writer_prompt(bundle, cfg, mode=mode, previous=previous, gen=gen)
            text, prov = generate_fn(prompt, process_id=process_id, max_tokens=max_tokens,
                                     timeout=float(cfg.get("timeout_s", 900)), manual=manual)
            return finish_doc(bundle, text, prov, gate=gate, settings=settings, web=web, mode=mode, previous=previous,
                              now=now, version=version, process_id=process_id, fallback=fallback)
        except Exception as exc:  # noqa: BLE001 - classified below
            if _credit_refusal(exc) and not isinstance(exc, GenerationFailed):
                raise QueueLater(str(exc)[:200]) from exc
            last_error = f"{type(exc).__name__}: {str(exc)[:200]}"
            if process_id == processes["premium"] and len(order) > 1:
                fallback = {"from": process_id, "to": processes["standard"], "reason": last_error}
                continue
            raise GenerationFailed(last_error) from exc
    raise GenerationFailed(last_error or "NO_MODEL_RESULT")
