"""The Market Risk DEEP BRIEF — the follow-up after the initial alert.

Operator 2026-10-31: "as part of the deeper analysis after the initial alert that you can use the LLM to coordinate and
to put together is the historical facts on what normally happens in the market when X is happening. Also, use the
other data sources so we can get a clear consensus on what's happening. You should also be looking at the options
market to see how people are hedging. Everything needs to be factored in, earnings, every particular catalyst."

How it stays honest (rebuilt after review of #2393, item 3):

* The FACT PACK (``deep_brief_facts.build_fact_pack``) is deterministic; every fact carries its rendered text.
* ``render_deterministic`` is the brief with no model at all, always ready.
* The model never writes prose. It may only COORDINATE: for each section it returns an ordered list of
  ``{"t": template_id, "f": fact_id}`` picks (JSON). ``TEMPLATES`` is a fixed bank of lead-ins, each allowed only in
  its own sections; the system renders ``template.format(text=fact["text"])`` — every value, sign and unit is the
  fact's own deterministic text. An answer is refused if a template is not in the bank or not allowed in that section,
  a fact does not exist or belongs to another section, a section it includes is incomplete, or the JSON is malformed
  or too deeply nested; any refusal sends the deterministic brief. Free text from the model is never sent.
* "Your exposure" is never chosen by the model; stance text is sanitised (``deep_brief_facts._exposure``).
* The model runs in a DAEMON thread with a hard timeout: a slow lane can never hold the evaluator past it (item 2).
* Delivery goes through the outbox (``alerts.outbox_put``, kind ``deep_brief``), queued with the initial card,
  drained only after that card is ``sent``, retried like any card (item 1). Model writing is OFF by default
  (``enabled: false`` + ``disabled_until`` in config/market_risk_deep_brief.yaml) until it passes review.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from typing import Any, Callable, Optional

from .deep_brief_facts import load_config

SCHEMA = "MarketRiskDeepBrief@v1"
SECTION_KEYS = ("happening", "next", "hedging", "catalysts", "consensus", "change")
TIER_RANK = {"GREEN": -1, "NONE": 0, "BLUE": 0, "YELLOW": 1, "ORANGE": 2, "RED": 3}
ADVISORY = "Advisory. No order, size or stop level is implied; the decision is yours."
#: the ONLY wording the model can cause to appear; ``{text}`` is the fact's deterministic text. Each lead-in is tied
#: to the sections where it is true ("Historically:" never labels a hedging fact) — review of #2410, N4.
TEMPLATES: dict[str, str] = {
    "plain": "{text}",
    "lead": "Main driver: {text}",
    "also": "Also: {text}",
    "history": "Historically: {text}",
    "hedge": "Hedging: {text}",
    "ahead": "Ahead: {text}",
    "agree": "Sources: {text}",
    "watch": "Would change the picture: {text}",
}
TEMPLATE_SECTIONS: dict[str, frozenset] = {
    "plain": frozenset(SECTION_KEYS),
    "also": frozenset(SECTION_KEYS),
    "lead": frozenset({"happening"}),
    "history": frozenset({"next"}),
    "hedge": frozenset({"hedging"}),
    "ahead": frozenset({"catalysts"}),
    "agree": frozenset({"consensus"}),
    "watch": frozenset({"change"}),
}


def _rank(t: Any) -> int:
    return TIER_RANK.get(str(t or "NONE").upper(), 0)


def _shock(d: Optional[dict]) -> Optional[str]:
    s = (d or {}).get("shock_type")
    return str(s.get("class")) if isinstance(s, dict) and s.get("class") else None


def should_brief(doc: dict, prior: Optional[dict], cfg: dict) -> Optional[str]:
    """``"tier"`` on a transition into a trigger tier, ``"shock_type"`` on a shock change at the minimum tier, else None."""
    # Carried-only data never escalates and never pages (operator's hold-not-escalate, #2425); a follow-up brief on it
    # would be a page about information the engine has explicitly not confirmed.
    if (doc.get("hysteresis") or {}).get("carried_only"):
        return None
    trig = cfg.get("triggers") or {}
    tiers = {str(t).upper() for t in trig.get("tiers") or ["ORANGE", "RED"]}
    tier = str(doc.get("tier") or "NONE").upper()
    if tier in tiers and (prior is None or _rank(prior.get("tier")) < _rank(tier)):
        return "tier"
    min_t = str(trig.get("shock_type_change_min_tier") or "YELLOW").upper()
    if _rank(tier) >= _rank(min_t) and _shock(doc) and prior is not None and _shock(prior) != _shock(doc):
        return "shock_type"
    return None


def outbox_entry(
    doc: dict,
    prior: Optional[dict],
    *,
    episode_id: Optional[str],
    initial_intent: Optional[dict],
    cfg: Optional[dict] = None,
) -> Optional[dict]:
    """The outbox entry for a brief this cycle owes (None when no trigger fired). The text is built at drain time;
    ``after_key`` holds it until the initial card is sent. Deterministic key: once per episode transition."""
    cfg = cfg if cfg is not None else load_config()
    why = should_brief(doc, prior, cfg)
    if not why:
        return None
    d = cfg.get("delivery") or {}
    key = f"market_risk:deep_brief:{episode_id or str(doc.get('as_of'))[:10]}:{doc.get('tier')}:{_shock(doc) or 'na'}"
    return {
        "key": key,
        "text": "",
        "kind": "deep_brief",
        "episode_id": None,  # not an episode card: no record_send, no ACK semantics
        "intent": {
            "priority": str(d.get("priority") or "P2"),
            "dedupe_minutes": int(d.get("dedupe_minutes") or 720),
            "dedupe_key": key,
            "tier": doc.get("tier"),
            "transition": f"deep_brief:{why}",
            "after_key": (initial_intent or {}).get("dedupe_key"),
            "episode": episode_id,
        },
    }


UNSENT = ("pending", "claimed", "failed")


def _was_sent(rec: dict) -> bool:
    """A card the transport accepted: ``sent``, or superseded AFTER it was sent (a torn episode store retires a sent
    card's bookkeeping, not the fact that it went out — review of #2410, N2)."""
    return rec.get("status") == "sent" or bool(rec.get("sent_at"))


def drain_gate(ent: dict, doc: dict, ledger_keys: dict, cfg: Optional[dict] = None) -> tuple[str, str]:
    """``("send" | "wait" | "retire", reason)`` for a queued brief at drain time. Pure; the evaluator acts on it.

    * retire when the market has fallen out of the trigger: a tier brief needs the current tier to still be a trigger
      tier, a shock-type brief needs the current tier at or above the shock minimum (N1 — no "DEEP BRIEF — BLUE");
    * retire when its own initial card was superseded without ever being sent;
    * wait while ANY card of its episode is unsent (B2: a shock-type brief has no initial card of its own, and an
      earlier ORANGE card of the same episode may still be retrying), or while its own initial card is unsent;
    * otherwise send."""
    cfg = cfg if cfg is not None else load_config()
    intent = ent.get("intent") or {}
    trig = cfg.get("triggers") or {}
    tier = str(doc.get("tier") or "NONE").upper()
    why = str(intent.get("transition") or "")
    if why.endswith(":shock_type"):
        if _rank(tier) < _rank(str(trig.get("shock_type_change_min_tier") or "YELLOW").upper()):
            return "retire", f"tier {tier} is below the shock-type brief minimum"
    elif tier not in {str(t).upper() for t in trig.get("tiers") or ["ORANGE", "RED"]}:
        return "retire", f"tier {tier} is no longer a brief trigger tier"
    after = intent.get("after_key")
    if after:
        rec = ledger_keys.get(after) or {}
        if rec.get("status") == "superseded" and not _was_sent(rec):
            return "retire", "its initial card was superseded unsent"
        if not _was_sent(rec):
            return "wait", "its initial card is not sent yet"
    ep = intent.get("episode")
    if ep:
        for k, rec in ledger_keys.items():
            if k == ent.get("key") or rec.get("kind") == "deep_brief" or rec.get("episode_id") != ep:
                continue
            if rec.get("status") in UNSENT:
                return "wait", f"card {k} of this episode is not sent yet"
    # A first-reading card is not tied to an episode (a bootstrap opens none, the hold-not-escalate path), so the
    # episode check above can let a brief overtake the very card it follows. Hold while any unsent non-brief card of
    # this tier is outstanding; cards of other tiers and episodes do not block it.
    for k, rec in ledger_keys.items():
        if k == ent.get("key") or rec.get("kind") == "deep_brief" or rec.get("status") not in UNSENT:
            continue
        if str((rec.get("intent") or {}).get("tier") or "").upper() == tier:
            return "wait", f"card {k} of this tier is not sent yet"
    return "send", "ok"


def _sections(pack: dict) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {k: [] for k in (*SECTION_KEYS, "exposure")}
    for f in pack.get("facts") or []:
        out.setdefault(f["section"], []).append(f)
    return out


def _titles(cfg: dict) -> dict[str, str]:
    names = list(cfg.get("sections") or [])
    return {k: (names[i] if i < len(names) else k) for i, k in enumerate(SECTION_KEYS)}


def _header(pack: dict) -> str:
    return f"MARKET RISK DEEP BRIEF — {pack.get('tier')} · as of {pack.get('assessment_as_of')}"


def exposure_block(pack: dict) -> list[str]:
    lines = ["Your exposure"]
    rows = [f for f in pack.get("facts") or [] if f["section"] == "exposure"]
    lines += [f"- {f['text']} [{f['id']}]" for f in rows] or ["- No position stances or book drivers in the snapshot."]
    return lines


def _unknown_line(pack: dict, key: str) -> Optional[str]:
    miss = [u for u in pack.get("unknown") or [] if u["section"] == key]
    return ("- Unknown: " + "; ".join(f"{u['what']} ({u['reason']})" for u in miss)) if miss else None


def render_deterministic(pack: dict, cfg: Optional[dict] = None) -> str:
    """The brief with no model: every line is a fact's own text and its citation."""
    cfg = cfg if cfg is not None else load_config()
    titles = _titles(cfg)
    secs = _sections(pack)
    lines = [_header(pack)]
    for key in SECTION_KEYS:
        lines += ["", titles[key]]
        lines += [f"- {f['text']} [{f['id']}]" for f in secs.get(key) or []] or ["- Not measured (see unknowns)."]
        u = _unknown_line(pack, key)
        if u:
            lines.append(u)
    lines.append("")
    lines += exposure_block(pack)
    lines += ["", ADVISORY]
    return "\n".join(lines)


def build_prompt(pack: dict, cfg: dict) -> str:
    titles = _titles(cfg)
    facts = [
        {"id": f["id"], "section": f["section"], "fact": f["text"]}
        for f in pack.get("facts") or []
        if f["section"] in SECTION_KEYS
    ]
    body = json.dumps({"facts": facts}, default=str)[: int(cfg.get("max_input_chars") or 14000)]
    return (
        "You coordinate a follow-up market-risk brief. You do NOT write sentences. For each section you include, list "
        "EVERY fact of that section exactly once, in the order a reader should see them, each with one template id "
        "allowed for that section.\n"
        f"Sections: {json.dumps({k: titles[k] for k in SECTION_KEYS})}\n"
        f"Template ids: {json.dumps(TEMPLATES)}\n"
        f"Allowed sections per template: {json.dumps({k: sorted(v) for k, v in TEMPLATE_SECTIONS.items()})}\n"
        'Answer with JSON only, e.g. {"happening": [{"t": "lead", "f": "now-b"}], "next": [{"t": "history", "f": "hist-c"}]}. '
        "Lead with what matters most for risk; leave out repeats.\n\n"
        f"FACTS:\n{body}\n"
    )


def parse_picks(answer: str, pack: dict) -> dict[str, Any]:
    """Validate the model's picks. Returns ``{ok, picks, reasons}``; any reason refuses the whole answer."""
    reasons: list[str] = []
    by_id = {f["id"]: f for f in pack.get("facts") or []}
    raw = str(answer or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`").split("\n", 1)[-1] if "\n" in raw else ""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError, RecursionError):  # RecursionError: deeply nested JSON (review of #2410, N4)
        return {"ok": False, "picks": {}, "reasons": ["not JSON"]}
    if not isinstance(data, dict):
        return {"ok": False, "picks": {}, "reasons": ["not a JSON object"]}
    picks: dict[str, list[tuple[str, str]]] = {}
    for sec, items in data.items():
        if sec not in SECTION_KEYS:
            reasons.append(f"unknown section {str(sec)[:30]!r}")
            continue
        if not isinstance(items, list):
            reasons.append(f"section {sec}: not a list")
            continue
        seen: set[str] = set()
        for it in items:
            if not isinstance(it, dict) or set(it) - {"t", "f"}:
                reasons.append(f"section {sec}: pick must be exactly {{t, f}}")
                continue
            t, f = str(it.get("t")), str(it.get("f"))
            if t not in TEMPLATES:
                reasons.append(f"unknown template {t[:20]!r}")
            elif sec not in TEMPLATE_SECTIONS[t]:
                reasons.append(f"template {t} is not allowed in {sec}")
            elif f not in by_id:
                reasons.append(f"unknown fact {f[:20]!r}")
            elif by_id[f]["section"] != sec:
                reasons.append(f"fact {f} belongs to {by_id[f]['section']}, not {sec}")
            elif f in seen:
                reasons.append(f"fact {f} picked twice")
            else:
                seen.add(f)
                picks.setdefault(sec, []).append((t, f))
    for sec, chosen in picks.items():  # the model orders and labels a section; it never drops part of one (N4)
        want = {f["id"] for f in pack.get("facts") or [] if f["section"] == sec}
        missing = want - {f for _, f in chosen}
        if missing:
            reasons.append(f"section {sec}: omits {sorted(missing)[:5]}")
    if not any(picks.values()):
        reasons.append("no picks")
    return {"ok": not reasons, "picks": picks, "reasons": reasons}


def render_picks(pack: dict, picks: dict[str, list[tuple[str, str]]], cfg: dict) -> str:
    """System rendering of validated picks: template lead-in + the fact's own text + citation. Sections the model left
    empty fall back to their deterministic lines, so nothing measured is silently dropped."""
    titles = _titles(cfg)
    by_id = {f["id"]: f for f in pack.get("facts") or []}
    secs = _sections(pack)
    lines = [_header(pack)]
    for key in SECTION_KEYS:
        lines += ["", titles[key]]
        chosen = picks.get(key) or []
        if chosen:
            lines += [f"- {TEMPLATES[t].format(text=by_id[f]['text'])} [{f}]" for t, f in chosen]
        else:
            lines += [f"- {f['text']} [{f['id']}]" for f in secs.get(key) or []] or ["- Not measured (see unknowns)."]
        u = _unknown_line(pack, key)
        if u:
            lines.append(u)
    lines.append("")
    lines += exposure_block(pack)
    lines += ["", ADVISORY]
    return "\n".join(lines)


def default_call_model(cfg: Optional[dict] = None) -> Callable[[str, float], Any]:
    """The governed free-lane chain (``llm_fallback.generate_with_fallback``), never a provider client of our own."""
    cfg = cfg if cfg is not None else load_config()

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
            max_tokens=int(cfg.get("max_tokens") or 600),
        )
        return str(getattr(res, "text", "") or ""), str(getattr(res, "lane", "") or "")

    return _call


def _call_with_deadline(call_model: Callable[[str, float], Any], prompt: str, timeout_s: float) -> tuple[str, Any]:
    """Run the model in a DAEMON thread and wait at most ``timeout_s``. A hung lane is abandoned, never joined at
    interpreter exit, so it can never hold the evaluator (review of #2393, item 2)."""
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["ans"] = call_model(prompt, timeout_s)
        except Exception as exc:  # noqa: BLE001 — returned to the caller as the reason; the deterministic brief is sent
            box["err"] = exc

    th = threading.Thread(target=run, name="deep-brief-model", daemon=True)
    th.start()
    th.join(timeout_s)
    if th.is_alive():
        return "timeout", None
    if "err" in box:
        return "error", box["err"]
    return "ok", box.get("ans")


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
    timeout_s = float(cfg.get("timeout_s") or 20)
    status, ans = _call_with_deadline(call_model, build_prompt(pack, cfg), timeout_s)
    if status == "timeout":
        return done(base, False, f"timeout after {timeout_s:g}s")
    if status == "error":
        return done(base, False, f"lane failure: {type(ans).__name__}: {ans}"[:240])
    lane = str(cfg.get("lane") or "grok")
    if isinstance(ans, tuple):
        ans, lane = ans[0], (ans[1] or lane)
    v = parse_picks(str(ans or ""), pack)
    if not v["ok"]:
        return done(base, False, "model picks rejected", lane, validation={k: v[k] for k in ("ok", "reasons")})
    return done(
        render_picks(pack, v["picks"], cfg), True, "template picks", lane, validation={"ok": True, "reasons": []}
    )


def build(
    now: datetime,
    reader: Any,
    doc: dict,
    *,
    snapshot: Optional[dict] = None,
    sources: Any = None,
    call_model: Any = None,
    cfg: Optional[dict] = None,
) -> tuple[dict, dict]:
    """(brief, pack) for the current assessment. Read-only; the model only when enabled and given."""
    from .deep_brief_facts import build_fact_pack

    cfg = cfg if cfg is not None else load_config()
    pack = build_fact_pack(now, reader, doc, snapshot=snapshot, sources=sources, cfg=cfg)
    return write(pack, call_model=call_model, cfg=cfg), pack


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
