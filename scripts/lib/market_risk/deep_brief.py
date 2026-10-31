"""The Market Risk DEEP BRIEF — the follow-up after the initial alert.

Operator 2026-10-31: "as part of the deeper analysis after the initial alert that you can use the LLM to coordinate and
to put together is the historical facts on what normally happens in the market when X is happening. Also, use the
other data sources so we can get a clear consensus on what's happening. You should also be looking at the options
market to see how people are hedging. Everything needs to be factored in, earnings, every particular catalyst."

How it stays honest:

* The FACT PACK (``deep_brief_facts.build_fact_pack``) is deterministic. The model never sees anything else.
* ``render_deterministic`` turns the pack into the brief with no model at all. It is always ready, and it is what is
  sent whenever the model is off, slow, wrong or refused.
* The model may write the first six sections. ``validate`` rejects the whole model draft unless EVERY sentence cites at
  least one fact id that exists, every number in a sentence appears in the facts it cites (zero tolerance, the repo's
  ``agent_number_grounding``), no non-ASCII digit survives NFKC, and no behaviour wording matches the curation lexicon
  (``config/market_risk_curation.yaml``). MBI_BEHAVIOR = 0.
* "Your exposure" is never written by the model: it is the CIO overlay's stances copied verbatim (or the book's
  symbols and stop distances). The brief cites stances; it never creates or strengthens one.
* Triggers: a transition INTO Orange or Red, or a shock-type change at Yellow or above. Sent as a P2 follow-up AFTER
  the initial card (the evaluator calls this only once its sends are done), once per episode transition through the
  sent-key ledger. Stored in the snapshot for the Risk page and Ask-the-CIO.
"""

from __future__ import annotations

import concurrent.futures
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from . import curation
from .deep_brief_facts import load_config

SCHEMA = "MarketRiskDeepBrief@v1"
SECTION_KEYS = ("happening", "next", "hedging", "catalysts", "consensus", "change")
TIER_RANK = {"GREEN": -1, "NONE": 0, "BLUE": 0, "YELLOW": 1, "ORANGE": 2, "RED": 3}
ADVISORY = "Advisory. No order, size or stop level is implied; the decision is yours."


def _rank(t: Any) -> int:
    return TIER_RANK.get(str(t or "NONE").upper(), 0)


def _shock(d: Optional[dict]) -> Optional[str]:
    s = (d or {}).get("shock_type")
    return str(s.get("class")) if isinstance(s, dict) and s.get("class") else None


def should_brief(doc: dict, prior: Optional[dict], cfg: dict) -> Optional[str]:
    """``"tier"`` on a transition into a trigger tier, ``"shock_type"`` on a shock change at the minimum tier, else None."""
    trig = cfg.get("triggers") or {}
    tiers = {str(t).upper() for t in trig.get("tiers") or ["ORANGE", "RED"]}
    tier = str(doc.get("tier") or "NONE").upper()
    if tier in tiers and (prior is None or _rank(prior.get("tier")) < _rank(tier)):
        return "tier"
    min_t = str(trig.get("shock_type_change_min_tier") or "YELLOW").upper()
    if _rank(tier) >= _rank(min_t) and _shock(doc) and prior is not None and _shock(prior) != _shock(doc):
        return "shock_type"
    return None


def _sections(pack: dict) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {k: [] for k in (*SECTION_KEYS, "exposure")}
    for f in pack.get("facts") or []:
        out.setdefault(f["section"], []).append(f)
    return out


def _titles(cfg: dict) -> dict[str, str]:
    names = list(cfg.get("sections") or [])
    return {k: (names[i] if i < len(names) else k) for i, k in enumerate(SECTION_KEYS)}


def exposure_block(pack: dict) -> list[str]:
    lines = ["Your exposure"]
    rows = [f for f in pack.get("facts") or [] if f["section"] == "exposure"]
    lines += [f"- {f['text']} [{f['id']}]" for f in rows] or ["- No position stances or book drivers in the snapshot."]
    return lines


def render_deterministic(pack: dict, cfg: Optional[dict] = None) -> str:
    """The brief with no model: every line is a fact's own text and its citation."""
    cfg = cfg if cfg is not None else load_config()
    titles = _titles(cfg)
    secs = _sections(pack)
    lines = [f"MARKET RISK DEEP BRIEF — {pack.get('tier')} · as of {pack.get('assessment_as_of')}"]
    for key in SECTION_KEYS:
        lines.append("")
        lines.append(titles[key])
        facts = secs.get(key) or []
        lines += [f"- {f['text']} [{f['id']}]" for f in facts] or ["- Not measured (see unknowns)."]
        miss = [u for u in pack.get("unknown") or [] if u["section"] == key]
        if miss:
            lines.append("- Unknown: " + "; ".join(f"{u['what']} ({u['reason']})" for u in miss))
    lines.append("")
    lines += exposure_block(pack)
    lines += ["", ADVISORY]
    return "\n".join(lines)


def build_prompt(pack: dict, cfg: dict) -> str:
    titles = _titles(cfg)
    facts = [
        {"id": f["id"], "section": titles.get(f["section"], f["section"]), "fact": f["text"], "as_of": f.get("as_of")}
        for f in pack.get("facts") or []
        if f["section"] != "exposure"
    ]
    body = json.dumps({"facts": facts, "unknown": pack.get("unknown") or []}, default=str, indent=0)
    body = body[: int(cfg.get("max_input_chars") or 14000)]
    heads = "\n".join(f"{titles[k]}" for k in SECTION_KEYS)
    return (
        "You write the follow-up brief to a market-risk alert for one investor reading on a phone. Use ONLY the facts "
        "below. Write these six sections, each heading on its own line exactly as given, then 1 to 4 short sentences:\n"
        f"{heads}\n\n"
        "RULES (a draft that breaks any rule is thrown away and the plain fact list is sent instead):\n"
        "- End EVERY sentence with the ids of the facts it uses in square brackets, e.g. [hist-a, opt-b].\n"
        "- Every number you write must appear in a fact you cite. Do not compute, round or add numbers.\n"
        "- Describe the market. Never tell the reader to buy, sell, trim, cut, exit, hedge, raise cash, set or move a "
        "stop, size a position, or take any action. Never say should, consider or recommend.\n"
        "- Say plainly what is unknown when a fact is missing. Do not reassure and do not exaggerate.\n"
        "- Plain words, no jargon without a short gloss.\n\n"
        f"FACTS:\n{body}\n"
    )


def validate(draft: str, pack: dict, cfg: dict) -> dict[str, Any]:
    """Accept the model draft only if every sentence passes ``brief_guard`` (characters, descriptive-only, no number
    words, grounding without exemptions, citations) and the curation lexicon; ``reasons`` lists every failure."""
    from . import brief_guard

    extra = list(curation.load_config().get("behaviour_patterns") or [])
    by_id = {f["id"]: f for f in pack.get("facts") or [] if f["section"] != "exposure"}
    titles = {t.strip().lower() for t in _titles(cfg).values()}
    return brief_guard.check_text(draft, by_id, titles, extra)


def default_call_model(cfg: dict) -> Callable[[str, float], Any]:
    """The governed free-lane chain (``llm_fallback.generate_with_fallback``), never a provider client of our own."""

    def _call(prompt: str, timeout_s: float):
        try:
            from scripts.lib.llm_fallback import generate_with_fallback  # type: ignore
        except ImportError:  # pragma: no cover
            from lib.llm_fallback import generate_with_fallback  # type: ignore
        res = generate_with_fallback(
            prompt,
            lane=str(cfg.get("lane") or "grok"),
            allow_paid=bool(cfg.get("allow_paid", False)),
            process_id=str(cfg.get("process_id") or "market_risk_deep_brief"),
            timeout=float(timeout_s),
            max_tokens=int(cfg.get("max_tokens") or 1400),
        )
        return str(getattr(res, "text", "") or ""), str(getattr(res, "lane", "") or "")

    return _call


def write(pack: dict, *, call_model: Optional[Callable[[str, float], Any]] = None, cfg: Optional[dict] = None) -> dict:
    """``{schema, text, curated, lane, reason, validation}`` — ``text`` is always sendable."""
    cfg = cfg if cfg is not None else load_config()
    base = render_deterministic(pack, cfg)

    def done(text: str, curated: bool, reason: str, lane: Optional[str] = None, **extra: Any) -> dict:
        return {"schema": SCHEMA, "text": text, "curated": curated, "lane": lane, "reason": reason, **extra}

    if not cfg.get("enabled", False):
        return done(base, False, "deep brief model disabled")
    if call_model is None:
        return done(base, False, "no model call in this mode")
    timeout_s = float(cfg.get("timeout_s") or 45)
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    fut = pool.submit(call_model, build_prompt(pack, cfg), timeout_s)
    try:
        ans = fut.result(timeout=timeout_s)
    except concurrent.futures.TimeoutError:
        pool.shutdown(wait=False, cancel_futures=True)
        return done(base, False, f"timeout after {timeout_s:g}s")
    except Exception as exc:  # noqa: BLE001 — any lane failure sends the deterministic brief
        pool.shutdown(wait=False, cancel_futures=True)
        return done(base, False, f"lane failure: {type(exc).__name__}: {exc}"[:240])
    pool.shutdown(wait=False)
    lane = str(cfg.get("lane") or "grok")
    if isinstance(ans, tuple):
        ans, lane = ans[0], (ans[1] or lane)
    draft = str(ans or "").strip()
    v = validate(draft, pack, cfg)
    if not v["ok"]:
        return done(base, False, "model draft rejected", lane, validation=v)
    from . import brief_guard

    text = "\n".join(
        [
            f"MARKET RISK DEEP BRIEF — {pack.get('tier')} · as of {pack.get('assessment_as_of')}",
            "",
            brief_guard.clean(draft)[0],
            "",
        ]
        + exposure_block(pack)
        + ["", ADVISORY]
    )
    return done(text, True, "grounded", lane, validation=v)


def follow_up(
    doc: dict,
    prior: Optional[dict],
    *,
    now: datetime,
    reader: Any,
    policy: dict,
    apply: bool,
    ledger: Optional[Path],
    episode_id: Optional[str] = None,
    snapshot: Optional[dict] = None,
    sources: Any = None,
    call_model: Any = None,
    cfg: Optional[dict] = None,
) -> Optional[dict]:
    """Called by the evaluator AFTER the initial cards. None when no trigger fired; otherwise the brief, the send
    result (dry run: what would be sent) and the fact pack. A dry run never calls a model unless one is injected."""
    from . import alerts
    from .deep_brief_facts import build_fact_pack

    cfg = cfg if cfg is not None else load_config()
    why = should_brief(doc, prior, cfg)
    if not why:
        return None
    pack = build_fact_pack(now, reader, doc, snapshot=snapshot, sources=sources, cfg=cfg)
    model = call_model if call_model is not None else (default_call_model(cfg) if apply else None)
    brief = write(pack, call_model=model, cfg=cfg)
    d = cfg.get("delivery") or {}
    key = f"market_risk:deep_brief:{episode_id or str(doc.get('as_of'))[:10]}:{doc.get('tier')}:{_shock(doc) or 'na'}"
    intent = {
        "priority": str(d.get("priority") or "P2"),
        "dedupe_minutes": int(d.get("dedupe_minutes") or 720),
        "dedupe_key": key,
        "tier": doc.get("tier"),
        "transition": f"deep_brief:{why}",
    }
    res = alerts.deliver(brief["text"], intent, policy, dry_run=not apply, now=now, ledger=ledger)
    return {
        "schema": SCHEMA,
        "trigger": why,
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "brief": brief,
        "send": res,
        "pack": pack,
    }


def snapshot_block(result: dict) -> dict:
    """What the snapshot (Risk page, Ask-the-CIO) keeps: the text, how it was written, the citations and unknowns."""
    pack = result.get("pack") or {}
    return {
        "schema": SCHEMA,
        "generated_at": result.get("generated_at"),
        "trigger": result.get("trigger"),
        "text": (result.get("brief") or {}).get("text"),
        "curated": (result.get("brief") or {}).get("curated"),
        "reason": (result.get("brief") or {}).get("reason"),
        "facts": [{k: f.get(k) for k in ("id", "section", "text", "source", "as_of")} for f in pack.get("facts") or []],
        "unknown": pack.get("unknown") or [],
        "consensus": {k: (pack.get("consensus") or {}).get(k) for k in ("majority", "agreement_pct", "dissent")},
    }
