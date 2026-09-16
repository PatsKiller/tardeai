"""The Research Escalation Circle — Phase 1: one question GUID, one lap over the free channels, the Context
Analyzer, automatic check-ins, and a lifecycle ledger. Dry run unless armed.

WHY
---
Operator, 2026-09-14: "We need to utilize everything — SearXNG, Brave, Hermes, DeepSeek, everything — and it
should be an escalation ladder or escalation circle with some intelligence around it. Also Yahoo Finance and all
the other channels." Then: "we need something that's analyzing the context coming back from that circle ...
scoring on maturity ... it decides whether to go to the next item in the circle or whether it suffices. It can't
be dumb. It should automatically queue check-ins — a week, two weeks. We're tracking everything via the GUIDs.
Make sure this is a full life cycle product."

Measured the same day (docs/architecture/RESEARCH_ESCALATION_2026-09-14.md): no quality-based escalation existed;
for operator questions Brave was off and Hermes (one DeepSeek Flash call over house evidence, no web) was the only
step that ran.

PHASE 1 (this module)
---------------------
* ``question_guid``: one UUIDv5 per operator ask (chat, message, text) -- the key for every lap, channel call,
  evidence item, verdict, answer, check-in and outcome, next to the subject GUIDs from the identity spine.
* A LAP over the FREE channels, each returning evidence items with an id, source, as_of and text:
  house (Trade-AI stores, via an injected gatherer), Yahoo Finance (quote, analyst targets, news), SEC (Form 4 /
  13F already ingested), SearXNG (self-hosted web search).
* ``score_lap``: a deterministic sufficiency/maturity score per operator sub-question from coverage, freshness,
  source independence and cross-source agreement.
* ``analyze``: the Context Analyzer. DeepSeek Flash through the governed bridge reads the lap's evidence against
  the question and returns a structured verdict (score, maturity M0-M4, decision, missing facts, next channel,
  check-in horizon). Numbers and claims may only cite evidence ids; a verdict citing an unknown id is rejected and
  the deterministic score decides. No model available -> the deterministic score decides, and says so.
* ``plan_checkin``: every answer schedules its own follow-up -- a dated catalyst -> the day after; otherwise
  7 days (fast-moving / open gaps) or 14 days (settled, quality holdings).
* ``Ledger``: append-only lifecycle rows ASKED -> GATHERING -> ANALYZED -> ANSWERED(M) -> SCHEDULED, keyed by
  question_guid; REVISITED and SETTLED are written by the check-in sweep (Phase 4).

PHASES 2-4 (not here): Brave behind the analyzer's ``climb``; Hermes over house + web evidence; the critic
cross-check and DeepSeek Pro judgment; the targeted second lap; desk wiring and "push for more".

AUTHORITY: READ_ONLY_ADVISORY. Research and notifications only; nothing sizes, orders or stops. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional
from urllib.parse import urlsplit

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA_VERDICT = "ResearchCircleVerdict@v1"
SCHEMA_LEDGER = "ResearchCircleLifecycle@v1"
LEDGER_PATH = PROJECT_ROOT / "data" / "cio" / "research_circle_ledger.jsonl"
CHECKIN_PATH = PROJECT_ROOT / "data" / "cio" / "research_circle_checkins.jsonl"
FLAG_LIVE = "RESEARCH_CIRCLE_LIVE"
QUESTION_NAMESPACE = uuid.UUID("5b0c6f2e-6a51-4f7e-9d1c-3e1a2b7c0d14")

MATURITY = ("M0", "M1", "M2", "M3", "M4")
MATURITY_MEANING = {
    "M0": "facts only, unsourced or stale",
    "M1": "sourced facts, single source",
    "M2": "cross-checked across independent sources",
    "M3": "synthesised answer that the evidence supports, no open contradiction",
    "M4": "decision-ready: cross-checked, synthesised, with a falsifier and a check-in date",
}
DECISIONS = ("sufficient", "climb", "targeted_lap", "ask_operator", "stop_bound")
#: Next channels after the free lap, cheapest first. Phase 1 only records the recommendation.
CLIMB_ORDER = ("brave", "hermes", "critic", "deepseek_pro")
SUFFICIENT_SCORE = 70

#: Operator sub-questions recognised in free text -> evidence kinds that can answer them.
NEED_PATTERNS: dict[str, re.Pattern] = {
    "price": re.compile(r"(?i)\b(price|trading at|quote|how is .* doing|right now)\b"),
    "levels": re.compile(r"(?i)\b(support|resistance|entry|levels?|stop|get back in|re-?enter)\b"),
    "analysts": re.compile(r"(?i)\b(analysts?|rating|target|upgrade|downgrade|consensus)\b"),
    "news": re.compile(r"(?i)\b(news|why is|catalyst|headline|what happened|announce|8-?k|filing)\b"),
    "volume": re.compile(r"(?i)\b(volume|rvol|more than normal|unusual activity)\b"),
    "insiders": re.compile(r"(?i)\b(insiders?|form 4|institution|13f|ownership)\b"),
    "research": re.compile(r"(?i)\b(research|outlook|thesis|dig deeper|more on|what else|should i)\b"),
}
#: Evidence kind -> needs it can satisfy.
KIND_SATISFIES = {
    "quote": {"price"}, "levels": {"levels", "price"}, "analyst": {"analysts"}, "news": {"news", "research"},
    "web": {"news", "research"}, "sec": {"insiders", "news"}, "volume": {"volume"}, "research": {"research"},
    "thesis": {"research"}, "profile": {"research"}, "catalyst": {"news", "research"},
}
#: Freshness windows (hours) per evidence kind.
FRESH_HOURS = {"quote": 24, "levels": 48, "analyst": 24 * 14, "news": 24 * 7, "web": 24 * 7, "sec": 24 * 90,
               "volume": 24, "research": 24 * 14, "thesis": 24 * 30, "profile": 24 * 120, "catalyst": 24 * 30}

# ── independence: who PUBLISHED it, not how we fetched it ────────────────────
# Until 2026-09-16 independence was keyed `e.source.split(":")[0]` -- the RETRIEVAL
# CHANNEL. Measured consequences of that one expression:
#   * `searxng:reuters.com` and `searxng:nyt.com` collapsed to the single source
#     "searxng", so six real publishers scored as one and never earned the +25.
#   * A Yahoo quote and an SEC Form 4 scored as "two independent sources" although
#     neither one can confirm or refute the other.
#   * A Brave hit and a SearXNG hit on the SAME wire story counted twice.
# The key is now the pair (publisher_host, retrieval_channel), and the +25
# corroboration bonus counts distinct PUBLISHERS -- never distinct channels.

#: Retrieval channels whose source suffix already names the publisher's domain.
_DOMAIN_SUFFIX_CHANNELS = frozenset({"searxng", "brave", "google", "bing", "ddg", "web"})

#: Canonical publisher host per retrieval channel, for items carrying no URL.
_CHANNEL_PUBLISHER = {
    "yahoo": "finance.yahoo.com",
    "sec": "sec.gov",
    "trade_ai": "house.trade_ai",
    "hermes": "house.trade_ai",
}

#: The class of claim an evidence kind makes. Two items corroborate only when they
#: assert the SAME class: a price quote and an insider filing are two publishers
#: but not two witnesses to one fact, so they are never mutual corroboration.
CLAIM_CLASS = {
    "quote": "price", "levels": "levels", "analyst": "analyst", "volume": "volume",
    "news": "narrative", "web": "narrative", "catalyst": "narrative",
    "sec": "filing", "research": "research", "thesis": "research", "profile": "research",
}


# ── identity ─────────────────────────────────────────────────────────────────

def question_guid(chat_id: str, message_id: str, text: str) -> str:
    """One stable GUID per operator ask."""
    norm = " ".join(str(text or "").lower().split())
    return str(uuid.uuid5(QUESTION_NAMESPACE, f"{chat_id}|{message_id}|{norm}"))


def register_question_on_spine(qguid: str, subject_guids: dict[str, str]) -> list[str]:
    """Put THIS `question_guid` on the subject spine, unchanged.

    One operator ask is about one or more subjects, and `subject_guids` already
    holds the resolved guid per symbol -- so no lookup and no mint happens here.
    Registered under source_table `operator_questions`, which is what
    distinguishes it from the unrelated `question_guid` in
    `due_diligence_questions.py` (different namespace, different argument
    tuple -- see scripts/check_identity_spine.py).

    Fail-safe: returns [] rather than raising. A lap must never end because a
    link could not be written.
    """
    try:
        from scripts.lib.cio_identity_spine import register_many

        return register_many(
            {"source_table": "operator_questions", "source_id": qguid,
             "subject_guid": sguid, "semantic_subject": sym}
            for sym, sguid in (subject_guids or {}).items() if sguid
        )
    except Exception:  # noqa: BLE001 -- the circle keeps turning
        return []


def detect_needs(text: str) -> list[str]:
    needs = [k for k, pat in NEED_PATTERNS.items() if pat.search(text or "")]
    return needs or ["research"]


# ── evidence ─────────────────────────────────────────────────────────────────

@dataclass
class Evidence:
    kind: str
    source: str            # "trade_ai:<store>" | "yahoo" | "sec" | "searxng:<domain>" | ...
    text: str
    as_of: Optional[str] = None
    symbol: Optional[str] = None
    url: Optional[str] = None
    value: Optional[float] = None
    channel: str = "house"  # house | provider | web_free | web_paid | model
    id: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            h = hashlib.sha1(f"{self.kind}|{self.source}|{self.url}|{self.text[:200]}|{self.as_of}".encode()).hexdigest()
            self.id = "ev_" + h[:12]


_ISO_DATE = re.compile(r"\b(20\d\d-\d\d-\d\d)\b")
_MON_DAY = re.compile(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.? (\d{1,2})\b")


def stated_date(text: str, *, now: Optional[datetime] = None) -> Optional[str]:
    """The newest date a line states (ISO, or "Sep 14" read as the latest such day not in the future). None when
    the line states no date -- an undated item is scored as stale, never stamped with today. Pure."""
    now = now or datetime.now(timezone.utc)
    found: list[date] = []
    for m in _ISO_DATE.finditer(text or ""):
        try:
            found.append(date.fromisoformat(m.group(1)))
        except ValueError:
            pass
    for m in _MON_DAY.finditer(text or ""):
        try:
            d = datetime.strptime(f"{m.group(1)} {m.group(2)} {now.year}", "%b %d %Y").date()
        except ValueError:
            continue
        found.append(d if d <= now.date() else d.replace(year=now.year - 1))
    past = [d for d in found if d <= now.date()]
    return max(past).isoformat() if past else None


def _age_hours(as_of: Optional[str], now: datetime) -> Optional[float]:
    if not as_of:
        return None
    try:
        s = str(as_of).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s) if "T" in s or " " in s else datetime.combine(date.fromisoformat(s[:10]), datetime.min.time())
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (now - dt).total_seconds() / 3600.0)
    except Exception:
        return None


def _strip_www(host: str) -> str:
    return host[4:] if host.startswith("www.") else host


def retrieval_channel(ev: "Evidence") -> str:
    """HOW the item was fetched -- searxng, brave, yahoo, sec, trade_ai. Pure.

    This is the old independence key, kept but demoted: it is one half of the
    pair, and on its own it says nothing about who published the claim.
    """
    return (str(ev.source or "").split(":")[0] or "unknown").strip().lower()


def publisher_host(ev: "Evidence") -> str:
    """WHO published the claim, as a bare host. Pure.

    The URL wins when there is one: a Reuters story reached through SearXNG, Brave
    or Yahoo is published by reuters.com in all three cases, which is exactly the
    collapse this function exists to force. With no URL, the source suffix is used
    when the channel puts a domain there, then the channel's own canonical host.

    Deliberately conservative: an unattributable item degrades to its channel host,
    which UNDER-counts independence. Over-counting is what corrupted the score.
    """
    url = str(getattr(ev, "url", "") or "")
    if url:
        try:
            netloc = urlsplit(url).netloc.split("@")[-1].split(":")[0].strip().lower()
            if netloc:
                return _strip_www(netloc)
        except ValueError:
            pass
    source = str(ev.source or "")
    channel = retrieval_channel(ev)
    suffix = source.split(":", 1)[1].strip().lower() if ":" in source else ""
    if suffix and channel in _DOMAIN_SUFFIX_CHANNELS and "." in suffix:
        return _strip_www(suffix)
    if channel in _CHANNEL_PUBLISHER:
        return _CHANNEL_PUBLISHER[channel]
    return _strip_www(suffix) if "." in suffix else (channel or "unknown")


def independence_key(ev: "Evidence") -> tuple[str, str]:
    """(publisher_host, retrieval_channel) -- the unit of independence. Pure."""
    return (publisher_host(ev), retrieval_channel(ev))


def corroborating_publishers(items: Iterable["Evidence"]) -> int:
    """Most distinct publishers asserting ONE class of claim. Pure.

    Not simply "how many publishers are in this list": publishers are grouped by
    claim class first, so a Yahoo quote plus an SEC filing returns 1, while two
    newspapers on the same story returns 2. This is the number the +25 bonus and
    every `min_sources >= 2` predicate must read.
    """
    by_class: dict[str, set[str]] = {}
    for e in items:
        by_class.setdefault(CLAIM_CLASS.get(e.kind, e.kind), set()).add(publisher_host(e))
    return max((len(pubs) for pubs in by_class.values()), default=0)


def _is_fresh(ev: "Evidence", now: datetime) -> bool:
    age = _age_hours(ev.as_of, now)
    return age is not None and age <= FRESH_HOURS.get(ev.kind, 24 * 7)


# ── the deterministic score ──────────────────────────────────────────────────

def score_lap(needs: list[str], evidence: list[Evidence], *, now: Optional[datetime] = None) -> dict[str, Any]:
    """Sufficiency 0-100 per need and overall, plus a maturity level. Pure.

    Per need: 40 if any fresh evidence answers it, +25 when a second independent PUBLISHER makes the same class
    of claim, +15 when two numeric values of the same kind agree within 2%, +20 when a house (Trade-AI) item and
    an outside item both answer it. Stale-only evidence caps a need at 20. Contradicting numbers (>10% apart)
    are listed and cap it at 50.

    `sources` is the set of publisher hosts -- NOT retrieval channels. One publisher reached through two channels
    is one source; two publishers found through one channel are two. See `publisher_host`.
    """
    now = now or datetime.now(timezone.utc)
    per_need: dict[str, dict[str, Any]] = {}
    contradictions: list[dict[str, Any]] = []
    for need in needs:
        items = [e for e in evidence if need in KIND_SATISFIES.get(e.kind, set())]
        fresh = [e for e in items if _is_fresh(e, now)]
        publishers = {publisher_host(e) for e in fresh}
        keys = {independence_key(e) for e in fresh}
        channels = {e.channel for e in fresh}
        score = 0
        contradicted = False
        # Two distinct PUBLISHERS on one class of claim. Counting retrieval channels here
        # is the defect fixed 2026-09-16: it both under-counted six publishers behind one
        # search engine and over-counted one wire story reached through two engines.
        corroborated = corroborating_publishers(fresh) >= 2
        if fresh:
            score = 40
            if corroborated:
                score += 25
            nums = [e.value for e in fresh if e.value is not None]
            if len(nums) >= 2:
                lo, hi = min(nums), max(nums)
                if lo > 0 and (hi - lo) / lo <= 0.02:
                    score += 15
                elif lo > 0 and (hi - lo) / lo > 0.10:
                    contradictions.append({"need": need, "low": lo, "high": hi,
                                           "sources": sorted({e.source for e in fresh if e.value is not None}),
                                           "publishers": sorted({publisher_host(e) for e in fresh
                                                                 if e.value is not None})})
                    contradicted = True
            if "house" in channels and channels - {"house"}:
                score += 20
            if contradicted:  # the cap applies after every bonus: disagreeing sources are never "cross-checked"
                score = min(score, 50)
        elif items:
            score = 20
        per_need[need] = {"score": min(100, score), "fresh_items": len(fresh), "sources": sorted(publishers),
                          "stale_only": bool(items and not fresh),
                          "independence_keys": sorted(f"{p}|{c}" for p, c in keys),
                          "corroborated": bool(fresh) and corroborated}
    fresh_all = [e for e in evidence if _is_fresh(e, now)]
    by_claim: dict[str, set[str]] = {}
    for e in fresh_all:
        by_claim.setdefault(CLAIM_CLASS.get(e.kind, e.kind), set()).add(publisher_host(e))
    corroboration = {
        "corroborated": corroborating_publishers(fresh_all) >= 2,
        "max_publishers_on_one_claim": corroborating_publishers(fresh_all),
        "publishers_by_claim": {k: sorted(v) for k, v in sorted(by_claim.items())},
        "independence_keys": sorted(f"{p}|{c}" for p, c in {independence_key(e) for e in fresh_all}),
    }
    overall = round(sum(v["score"] for v in per_need.values()) / max(1, len(per_need)))
    weakest = min(per_need.items(), key=lambda kv: kv[1]["score"])[0] if per_need else None
    if overall >= 85 and not contradictions:
        maturity = "M2"
    elif overall >= 55:
        maturity = "M1"
    else:
        maturity = "M0"
    return {"overall": overall, "per_need": per_need, "contradictions": contradictions,
            "weakest_need": weakest, "maturity": maturity, "corroboration": corroboration}


def deterministic_decision(score: dict[str, Any], *, lap: int, max_laps: int = 2) -> dict[str, Any]:
    """What to do when no analyzer model is available. Pure."""
    missing = [n for n, v in score["per_need"].items() if v["score"] < 40]
    if score["overall"] >= SUFFICIENT_SCORE and not score["contradictions"]:
        decision, nxt = "sufficient", None
    elif lap >= max_laps:
        decision, nxt = "stop_bound", None
    elif score["contradictions"] or "research" in missing:
        decision, nxt = "climb", "hermes"
    elif missing:
        decision, nxt = "climb", "brave"
    else:
        decision, nxt = "climb", "critic"
    return {"decision": decision, "next_channel": nxt, "missing_facts": missing}


# ── the Context Analyzer (DeepSeek Flash via the governed bridge) ─────────────

ANALYZER_SYSTEM = (
    "You are the Trade-AI research Context Analyzer. You judge whether the EVIDENCE answers the operator's "
    "QUESTION well enough to stop, or which channel to use next. Rules: (1) use ONLY the evidence items given; "
    "every claim must cite evidence ids from the list; (2) never invent numbers; (3) score each sub-question 0-100 "
    "for coverage, freshness, independence and agreement; (4) maturity: M0 facts only, M1 sourced, M2 cross-checked, "
    "M3 synthesised with no open contradiction, M4 decision-ready with a falsifier and a check-in date; "
    "(5) decision is one of sufficient | climb | targeted_lap | ask_operator | stop_bound; next_channel one of "
    "brave | hermes | critic | deepseek_pro | null; (6) checkin_days is 1-30, earlier when a dated catalyst is in "
    "the evidence. Return ONLY JSON with keys: sufficiency_score, per_need (object need->score), maturity, "
    "decision, next_channel, missing_facts (list), contradictions (list), answer_summary (<=600 chars, cite ids "
    "like [ev_...]), falsifier (string or null), checkin_days (int), checkin_reason (string)."
)


def _evidence_packet(evidence: list[Evidence], limit_chars: int = 7000) -> list[dict[str, Any]]:
    out, used = [], 0
    for e in evidence:
        row = {"id": e.id, "kind": e.kind, "source": e.source, "as_of": e.as_of, "text": e.text[:420]}
        size = len(json.dumps(row))
        if used + size > limit_chars:
            break
        out.append(row)
        used += size
    return out


def parse_verdict(raw: str, evidence: list[Evidence]) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """Parse and ground a model verdict. (verdict, rejection_reason). Pure."""
    if not raw:
        return None, "empty model response"
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None, "no JSON object in model response"
    try:
        v = json.loads(m.group(0))
    except ValueError as exc:
        return None, f"invalid JSON: {exc}"
    ids = {e.id for e in evidence}
    cited = set(re.findall(r"ev_[0-9a-f]{12}", json.dumps(v)))
    unknown = sorted(cited - ids)
    if unknown:
        return None, f"cites unknown evidence ids {unknown[:3]}"
    if v.get("decision") not in DECISIONS:
        return None, f"decision {v.get('decision')!r} not allowed"
    if v.get("maturity") not in MATURITY:
        return None, f"maturity {v.get('maturity')!r} not allowed"
    try:
        v["sufficiency_score"] = max(0, min(100, int(v.get("sufficiency_score"))))
        v["checkin_days"] = max(1, min(30, int(v.get("checkin_days") or 7)))
    except (TypeError, ValueError):
        return None, "sufficiency_score / checkin_days not integers"
    if v.get("next_channel") not in (None, *CLIMB_ORDER):
        v["next_channel"] = None
    return v, None


def analyze(question: str, needs: list[str], evidence: list[Evidence], score: dict[str, Any], *, lap: int,
            call_model: Optional[Callable[[list[dict[str, str]]], dict[str, Any]]] = None) -> dict[str, Any]:
    """The verdict for one lap: the model's when it is valid and grounded, the deterministic one otherwise."""
    fallback = deterministic_decision(score, lap=lap)
    base = {"schema": SCHEMA_VERDICT, "lap": lap, "deterministic_score": score["overall"],
            "deterministic_maturity": score["maturity"], "contradictions": score["contradictions"]}
    if call_model is None:
        return {**base, **fallback, "sufficiency_score": score["overall"], "maturity": score["maturity"],
                "analyzer": "deterministic", "analyzer_note": "no analyzer model configured"}
    messages = [{"role": "system", "content": ANALYZER_SYSTEM},
                {"role": "user", "content": json.dumps({"QUESTION": question, "SUB_QUESTIONS": needs,
                                                        "DETERMINISTIC_SCORE": score,
                                                        "EVIDENCE": _evidence_packet(evidence)})}]
    try:
        res = call_model(messages) or {}
    except Exception as exc:  # noqa: BLE001
        res = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    raw = res.get("content") or res.get("text") or ""
    verdict, why = parse_verdict(raw, evidence) if res.get("ok", bool(raw)) else (None, res.get("error") or "model call failed")
    if verdict is None:
        return {**base, **fallback, "sufficiency_score": score["overall"], "maturity": score["maturity"],
                "analyzer": "deterministic", "analyzer_note": f"model verdict rejected: {why}"}
    # The model may not declare an answer sufficient that the deterministic score rates M0 with open gaps.
    if verdict["decision"] == "sufficient" and score["overall"] < 40:
        verdict["decision"], verdict["next_channel"] = fallback["decision"], fallback["next_channel"]
        verdict["analyzer_override"] = "deterministic score < 40: not sufficient"
    return {**base, **verdict, "analyzer": res.get("model") or "deepseek-flash"}


def deepseek_flash_caller() -> Callable[[list[dict[str, str]]], dict[str, Any]]:
    """The governed bridge (never api.deepseek.com directly). Note: use_pro is not wired in the bridge call --
    call_governed_llm sends deepseek-flash either way (measured 2026-09-14)."""
    def _call(messages: list[dict[str, str]]) -> dict[str, Any]:
        from scripts.lib.cio_plan_enrichment import call_governed_llm, load_llm_policy  # noqa: PLC0415

        out = call_governed_llm(messages, load_llm_policy(), use_pro=False, task_type="research_circle")
        if out.get("ok") and not out.get("content"):
            out["content"] = out.get("text") or ((out.get("choices") or [{}])[0].get("message") or {}).get("content")
        return out
    return _call


# ── check-ins ────────────────────────────────────────────────────────────────

_CATALYST_DATE = re.compile(r"(?i)\b(earnings|report|fda|pdufa|ex-?dividend|split|vote|hearing|deadline)\b[^.\n]{0,60}?"
                            r"\b(20\d\d-\d\d-\d\d)\b")


def plan_checkin(question: str, evidence: list[Evidence], verdict: dict[str, Any], *,
                 held: bool = False, now: Optional[datetime] = None) -> dict[str, Any]:
    """When to look again. Pure. A dated catalyst in the evidence wins; then the analyzer's days; then 7 / 14."""
    now = now or datetime.now(timezone.utc)
    upcoming: list[tuple[date, str]] = []
    for e in evidence:
        for m in _CATALYST_DATE.finditer(e.text or ""):
            try:
                d = date.fromisoformat(m.group(2))
            except ValueError:
                continue
            if d > now.date():
                upcoming.append((d, f"{m.group(1)} {d.isoformat()} ({e.id})"))
    if upcoming:
        d, why = min(upcoming)
        due = datetime.combine(d + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=13)
        return {"due_at": due.isoformat(), "days": (due.date() - now.date()).days, "reason": f"day after {why}"}
    if verdict.get("checkin_days"):
        days = int(verdict["checkin_days"])
        reason = verdict.get("checkin_reason") or "analyzer horizon"
    elif verdict.get("decision") in ("sufficient",) and held:
        days, reason = 14, "settled answer on a held name"
    else:
        days, reason = 7, "open or fast-moving question"
    due = now + timedelta(days=days)
    return {"due_at": due.replace(microsecond=0).isoformat(), "days": days, "reason": reason}


# ── lifecycle ledger ─────────────────────────────────────────────────────────

class Ledger:
    """Append-only lifecycle rows keyed by question_guid."""

    def __init__(self, path: Path = LEDGER_PATH, checkins: Path = CHECKIN_PATH, *, apply: bool = False):
        self.path, self.checkins, self.apply = Path(path), Path(checkins), apply
        self.rows: list[dict[str, Any]] = []

    def record(self, qguid: str, state: str, **fields: Any) -> dict[str, Any]:
        row = {"schema": SCHEMA_LEDGER, "question_guid": qguid, "state": state,
               "ts": datetime.now(timezone.utc).isoformat(), "authority": AUTHORITY, **fields}
        self.rows.append(row)
        if self.apply:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, default=str) + "\n")
        return row

    def schedule(self, qguid: str, checkin: dict[str, Any], **fields: Any) -> dict[str, Any]:
        row = {"schema": "ResearchCircleCheckin@v1", "question_guid": qguid, "status": "SCHEDULED",
               "ts": datetime.now(timezone.utc).isoformat(), "authority": AUTHORITY, **checkin, **fields}
        if self.apply:
            self.checkins.parent.mkdir(parents=True, exist_ok=True)
            with self.checkins.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, default=str) + "\n")
        self.record(qguid, "SCHEDULED", due_at=checkin["due_at"], reason=checkin["reason"])
        return row


# ── free channels (read-only network, no writes) ─────────────────────────────

def volume_streak(volumes: list[float], days: list[date], *, today: date, lookback: int = 50,
                  multiple: float = 1.5) -> Optional[dict[str, Any]]:
    """How long daily volume has run above normal, over COMPLETED sessions only (today's partial bar is dropped).
    Normal = the average of the `lookback` sessions before each day. Pure."""
    pairs = [(d, float(v or 0)) for d, v in zip(days, volumes)]
    if pairs and pairs[-1][0] >= today:
        pairs = pairs[:-1]
    if len(pairs) < 21:
        return None
    above: list[bool] = []
    for i in range(20, len(pairs)):
        window = [v for _, v in pairs[max(0, i - lookback):i]]
        avg = sum(window) / len(window) if window else 0
        above.append(avg > 0 and pairs[i][1] > multiple * avg)
    streak = 0
    for flag in reversed(above):
        if not flag:
            break
        streak += 1
    last20 = sum(above[-20:])
    last_day = pairs[-1][0].isoformat()
    text = (f"volume above {multiple:g}x its {lookback}-session average for the last {streak} completed session(s) "
            f"(through {last_day}); {last20} of the last 20 sessions were above that mark")
    return {"streak": streak, "above_in_last_20": last20, "last_completed": last_day, "text": text}


def yahoo_channel(symbol: str) -> list[Evidence]:
    import yfinance as yf  # noqa: PLC0415

    out: list[Evidence] = []
    t = yf.Ticker(symbol)
    try:
        fi = t.fast_info
        last = float(fi.get("lastPrice") or fi.get("last_price") or 0)
        if last > 0:
            out.append(Evidence("quote", "yahoo", f"{symbol} last price ${last:,.2f} (Yahoo Finance)",
                                as_of=datetime.now(timezone.utc).isoformat(), symbol=symbol, value=last,
                                channel="provider", url=f"https://finance.yahoo.com/quote/{symbol}"))
    except Exception:
        pass
    try:
        # Levels are computed from daily bars, never searched for: 20-day low/high, SMA20/SMA50.
        hist = t.history(period="3mo", interval="1d", auto_adjust=False)
        if hist is not None and len(hist) >= 50:
            closes, lows, highs = hist["Close"], hist["Low"], hist["High"]
            last_bar = hist.index[-1]
            sup, res = float(lows.tail(20).min()), float(highs.tail(20).max())
            sma20, sma50 = float(closes.tail(20).mean()), float(closes.tail(50).mean())
            out.append(Evidence("levels", "yahoo:daily_bars",
                                f"{symbol} computed from Yahoo daily bars: 20-day support ${sup:,.2f} · 20-day resistance "
                                f"${res:,.2f} · 60-day swing low ${float(lows.min()):,.2f} · 60-day swing high "
                                f"${float(highs.max()):,.2f} · SMA20 ${sma20:,.2f} · SMA50 ${sma50:,.2f} · last close "
                                f"${float(closes.iloc[-1]):,.2f}",
                                as_of=last_bar.isoformat(), symbol=symbol, channel="provider"))
            streak = volume_streak(list(hist["Volume"]), [d.date() for d in hist.index],
                                   today=datetime.now(timezone.utc).date())
            if streak:
                out.append(Evidence("volume", "yahoo:daily_bars", f"{symbol} {streak['text']}",
                                    as_of=streak["last_completed"], symbol=symbol, channel="provider"))
    except Exception:
        pass
    try:
        info = t.info or {}
        if info.get("targetMeanPrice"):
            out.append(Evidence("analyst", "yahoo",
                                f"{symbol} analysts: {info.get('recommendationKey')} · {info.get('numberOfAnalystOpinions')} "
                                f"analysts · mean target ${float(info['targetMeanPrice']):,.2f} (low "
                                f"${float(info.get('targetLowPrice') or 0):,.2f}, high ${float(info.get('targetHighPrice') or 0):,.2f})",
                                as_of=datetime.now(timezone.utc).date().isoformat(), symbol=symbol,
                                value=float(info["targetMeanPrice"]), channel="provider"))
        if info.get("averageVolume") and info.get("volume"):
            rv = float(info["volume"]) / float(info["averageVolume"])
            out.append(Evidence("volume", "yahoo", f"{symbol} volume {int(info['volume']):,} vs 3-month average "
                                f"{int(info['averageVolume']):,} ({rv:.2f}x)",
                                as_of=datetime.now(timezone.utc).isoformat(), symbol=symbol, value=rv, channel="provider"))
        if info.get("earningsTimestamp"):
            d = datetime.fromtimestamp(int(info["earningsTimestamp"]), tz=timezone.utc).date()
            out.append(Evidence("catalyst", "yahoo", f"{symbol} earnings report {d.isoformat()} (Yahoo calendar)",
                                as_of=datetime.now(timezone.utc).date().isoformat(), symbol=symbol, channel="provider"))
    except Exception:
        pass
    try:
        for n in (t.news or [])[:6]:
            c = n.get("content") or n
            title = c.get("title") or ""
            if not title:
                continue
            prov = (c.get("provider") or {}).get("displayName") or "Yahoo"
            url = ((c.get("canonicalUrl") or {}).get("url")) or ((c.get("clickThroughUrl") or {}).get("url"))
            out.append(Evidence("news", f"yahoo:{prov}", f"{title} — {prov}", as_of=c.get("pubDate"), symbol=symbol,
                                url=url, channel="provider"))
    except Exception:
        pass
    return out


def searxng_channel(query: str, *, symbol: Optional[str] = None, limit: int = 6) -> list[Evidence]:
    from scripts.lib.searxng_client import searx_search  # noqa: PLC0415

    out: list[Evidence] = []
    # News first; a specific question often has no news hit but a general one (measured 2026-09-14: 0 news, 4 general).
    hits = searx_search(query, categories="news", limit=limit) or []
    if len(hits) < 2:
        hits = hits + (searx_search(query, categories="general", limit=limit) or [])
    for h in hits:
        if not isinstance(h, dict) or not h.get("url"):
            continue
        text = f"{h.get('title')} — {h.get('snippet') or ''}"[:400]
        out.append(Evidence("web", f"searxng:{h.get('domain') or 'web'}", text,
                            as_of=h.get("published") or h.get("publishedDate") or stated_date(text),
                            symbol=symbol, url=h.get("url"), channel="web_free"))
    return out


def sec_channel(symbol: str, db_query: Callable[[str, tuple], list[dict[str, Any]]]) -> list[Evidence]:
    out: list[Evidence] = []
    for r in db_query("SELECT filer_name, transaction_type, filing_date, sec_url FROM sec_form4 WHERE symbol=%s "
                      "ORDER BY filing_date DESC LIMIT 3", (symbol,)) or []:
        out.append(Evidence("sec", "sec:form4", f"{symbol} Form 4 {r.get('filing_date')}: {r.get('filer_name')} — "
                            f"{r.get('transaction_type')}", as_of=str(r.get("filing_date")), symbol=symbol,
                            url=r.get("sec_url"), channel="provider"))
    return out


# ── one lap ──────────────────────────────────────────────────────────────────

@dataclass
class LapResult:
    question_guid: str
    lap: int
    needs: list[str]
    evidence: list[Evidence]
    score: dict[str, Any]
    verdict: dict[str, Any]
    checkin: Optional[dict[str, Any]] = None
    channel_errors: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["evidence"] = [asdict(e) for e in self.evidence]
        return d


def run_lap(question: str, *, chat_id: str, message_id: str, symbols: list[str], subject_guids: dict[str, str],
            channels: dict[str, Callable[[], list[Evidence]]], ledger: Ledger, lap: int = 1,
            call_model: Optional[Callable[[list[dict[str, str]]], dict[str, Any]]] = None,
            held: bool = False, prior_evidence: Iterable[Evidence] = (), max_laps: int = 2) -> LapResult:
    """Run one lap over the given channels (plus what earlier laps found), analyze it, and schedule the check-in
    when the answer stands or the lap bound is reached."""
    qguid = question_guid(chat_id, message_id, question)
    needs = detect_needs(question)
    if lap == 1:
        ledger.record(qguid, "ASKED", question=question[:500], symbols=symbols, subject_guids=subject_guids, needs=needs)
        if ledger.apply:
            # The operator's question becomes joinable to the gaps and goals
            # about the same subject. Only on a real run: a dry lap must leave
            # no trace, here as everywhere else in this module.
            register_question_on_spine(qguid, subject_guids)
    ledger.record(qguid, "GATHERING", lap=lap, channels=sorted(channels))
    evidence: list[Evidence] = list(prior_evidence)
    errors: dict[str, str] = {}
    for name, fn in channels.items():
        try:
            evidence.extend(fn() or [])
        except Exception as exc:  # noqa: BLE001 -- one channel failing never ends the lap
            errors[name] = f"{type(exc).__name__}: {exc}"[:200]
    seen: set[str] = set()
    evidence = [e for e in evidence if not (e.id in seen or seen.add(e.id))]
    prior_ids = {e.id for e in prior_evidence}
    new_ids = [e.id for e in evidence if e.id not in prior_ids]
    score = score_lap(needs, evidence)
    if lap > 1 and not new_ids:
        # A lap that found nothing new ends the circle: re-asking the model over the same evidence spends a call to
        # repeat itself (measured 2026-09-14: lap 2 on HPE, 24 -> 24 items, identical verdict).
        verdict = {**deterministic_decision(score, lap=max_laps, max_laps=max_laps), "schema": SCHEMA_VERDICT,
                   "lap": lap, "sufficiency_score": score["overall"], "maturity": score["maturity"],
                   "deterministic_score": score["overall"], "contradictions": score["contradictions"],
                   "analyzer": "deterministic", "analyzer_note": "targeted lap found no new evidence"}
    else:
        verdict = analyze(question, needs, evidence, score, lap=lap, call_model=call_model)
    ledger.record(qguid, "ANALYZED", lap=lap, score=score["overall"], maturity=verdict.get("maturity"),
                  decision=verdict.get("decision"), next_channel=verdict.get("next_channel"),
                  analyzer=verdict.get("analyzer"), evidence_ids=[e.id for e in evidence],
                  channel_errors=errors)
    checkin = None
    if verdict.get("decision") in ("sufficient", "stop_bound", "ask_operator") or lap >= max_laps:
        state = "ANSWERED" if verdict.get("decision") == "sufficient" else "ANSWERED_PARTIAL"
        ledger.record(qguid, state, lap=lap, maturity=verdict.get("maturity"),
                      missing_facts=verdict.get("missing_facts") or [])
        checkin = plan_checkin(question, evidence, verdict, held=held)
        ledger.schedule(qguid, checkin, symbols=symbols, subject_guids=subject_guids, question=question[:300])
    return LapResult(qguid, lap, needs, evidence, score, verdict, checkin, errors)


def targeted_queries(symbol: str, missing_facts: Iterable[str], *, limit: int = 2) -> list[str]:
    """Turn the analyzer's missing facts into short search queries (evidence ids and quotes stripped). Pure."""
    out: list[str] = []
    for fact in missing_facts:
        words = re.sub(r"\[?ev_[0-9a-f]{12}\]?|['\"—()\[\]]", " ", str(fact)).split()
        words = [w for w in words if w.lower() not in {"no", "not", "the", "a", "an", "to", "of", "is", "only", "beyond"}]
        q = " ".join([symbol, *words[:9]])
        if q not in out:
            out.append(q)
        if len(out) >= limit:
            break
    return out


def run_circle(question: str, *, chat_id: str, message_id: str, symbols: list[str], subject_guids: dict[str, str],
               channels: dict[str, Callable[[], list[Evidence]]], ledger: Ledger,
               targeted: Optional[Callable[[str], list[Evidence]]] = None,
               call_model: Optional[Callable[[list[dict[str, str]]], dict[str, Any]]] = None,
               held: bool = False, max_laps: int = 2) -> list[LapResult]:
    """Lap 1 over every free channel; while the analyzer says climb / targeted_lap and the bound allows, one more lap
    whose channels are searches built from the missing facts, over everything found so far. Phase 1 stays on the
    free channels: a recommended Brave / Hermes / critic / Pro step is recorded, not taken."""
    laps = [run_lap(question, chat_id=chat_id, message_id=message_id, symbols=symbols, subject_guids=subject_guids,
                    channels=channels, ledger=ledger, lap=1, call_model=call_model, held=held, max_laps=max_laps)]
    while (laps[-1].verdict.get("decision") in ("climb", "targeted_lap") and laps[-1].lap < max_laps
           and targeted is not None and symbols):
        queries = targeted_queries(symbols[0], laps[-1].verdict.get("missing_facts") or [])
        if not queries:
            break
        lap_channels = {f"targeted:{q}": (lambda q=q: targeted(q)) for q in queries}
        laps.append(run_lap(question, chat_id=chat_id, message_id=message_id, symbols=symbols,
                            subject_guids=subject_guids, channels=lap_channels, ledger=ledger, lap=laps[-1].lap + 1,
                            call_model=call_model, held=held, prior_evidence=laps[-1].evidence, max_laps=max_laps))
    return laps


__all__ = ["CLAIM_CLASS", "CLIMB_ORDER", "DECISIONS", "Evidence", "LapResult", "Ledger", "MATURITY",
           "MATURITY_MEANING", "analyze", "corroborating_publishers", "deepseek_flash_caller", "detect_needs",
           "deterministic_decision", "independence_key", "parse_verdict", "plan_checkin", "publisher_host",
           "question_guid", "retrieval_channel", "run_lap", "score_lap", "searxng_channel", "sec_channel",
           "yahoo_channel"]
