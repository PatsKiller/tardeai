"""ResidualWebLane@v1 — the lane that executes the gate's residual rung.

WHY THIS EXISTS
---------------
`ResearchNeedDecision@v2` already routes some subjects to a residual step. It
has always been the rung after `pro`:

    skip -> reuse -> corpus_hit -> flash -> pro -> [residual] -> grok_critique

and `cio_research_templates` already carries that rung's prompt skeleton
("residual only — the questions Pro left open, JSON schema out") and its output
schema (`still_unresolved`). What has never existed is anything that RUNS it.
The rung routes and then nothing happens.

This module is that lane. It does not delete, widen or re-decide the gate: it
opens the faucet **only** for subjects the gate already routed to the residual
rung, and it adds a second, narrower legality test on top.

THE DECISION TOKEN
------------------
Reused, not invented. The gate's residual rung is the string `"openai"`
(`RESIDUAL_DECISION`), and it stays that string on the wire — renaming it would
touch `cio_research_templates._SYSTEM`, `cio_specialist_artifact.PROVIDERS`
(which raises on an unknown provider), the same-day collapse in
`cio_research_gate_report`, and a row of ban-list tests that assert the literal
"openai" is absent from unrelated modules. `residual_web` is the name of the
LANE that executes that rung — the gate names the rung, this names the executor.

ONE HOP PER SUBJECT PER DAY, N=3 SUBJECTS PER DAY
-------------------------------------------------
`DAILY_SUBJECT_BUDGET = 3`, `MAX_HOPS_PER_SUBJECT_PER_DAY = 1`. Held names whose
event hash moved are preferred; a due `SLEEVE:CASH` is the fallback. An event
hash change overrides SKIP_FRESH and nothing else — it is not a licence to
re-run a subject that already had its hop today, and an UNSET hash is not a
change (`cio_instrument_record.hash_changed`).

STUB BY DEFAULT
---------------
`run_hop(..., apply=False)` is the default and is a pure function: it imports no
network module, opens no socket, and returns `provider="stub", cost_usd=0.0`.
The live transport is imported lazily *inside* `_live_transport`, so the stub
path cannot reach a vendor even by accident. Every result carries
`paid_dispatch_entered`, read from `evidence_refresh_job`'s probe, so "no paid
call happened" is a machine-checkable integer rather than a claim.

MBI_BEHAVIOR=0. Nothing here produces a size, a delta, or an order. A narrative
that contains execution language is refused, not filtered.
READ_ONLY_ADVISORY.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from scripts.lib.cio_instrument_record import (
    CASH_SLEEVE, cc_narrative, content_hash, hash_changed, is_mintable,
    parse_subject_key,
)
from scripts.lib.cio_web_librarian import (
    admissible_for_entity_question, may_close, source_ref, summarize,
)

SCHEMA = "ResidualWebLane@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
MBI_BEHAVIOR = 0
MBI_COGNITION = 1
FINANCIAL_ACTION = False

LANE = "residual_web"

# The MODEL lane, distinct from the executor lane above. `LANE` names who runs
# the hop and is for reporting; `MODEL_LANE` names the registered provider that
# llm_lane.generate() will accept. Conflating them is not cosmetic: the first
# live hop died with
#   UNKNOWN_LANE: lane='residual_web' is not registered
# because the executor name was passed straight into generate(). Registered
# lanes are deepseek-flash / deepseek-v4-flash / deepseek-v4-pro.
MODEL_LANE = "deepseek-flash"

# The gate rung this lane executes. Reused from cio_research_gate.DECISIONS —
# see the module docstring for why this is not renamed.
RESIDUAL_DECISION = "openai"

# The registered process that already allows this lane. `hermes_external_research`
# is registered in config/llm_process_registry.json with default_mode=automated
# and daily_cost_cap_usd=0.30. We do NOT invent `grok_execution_review`, and we
# do not register a new process: an unregistered process_id fails closed by
# design and that is the property we want to keep.
PROCESS_ID = "hermes_external_research"

DAILY_SUBJECT_BUDGET = 3
MAX_HOPS_PER_SUBJECT_PER_DAY = 1

# Subject kinds this lane may speak about at all.
ELIGIBLE_KINDS = frozenset({"HELD", "EXIT", "WATCH", "SECTOR", "SLEEVE"})

# Observables whose movement overrides a cadence skip (SKIP_FRESH only).
EVENT_HASHES = ("price", "weight", "earnings", "analyst")

# How far a completed hop pushes the next look.
NEXT_LOOK_DAYS = 7
BLOCKED_NEXT_LOOK_DAYS = 1

OUTCOMES = ("VALID", "PARTIAL", "REJECT", "execution_language", "FAIL")
ATTACHING_OUTCOMES = frozenset({"VALID", "PARTIAL"})

# F1/F2 bound policy: web *search* serves this lane only. Bulk news/catalyst
# enrichment uses RSS + Finviz (see SEARCH_CALLER_CENSUS). Never fail open on
# an unreadable search budget — that property lives in scripts.lib.search_budget.
NEWS_BELONGS_ON = ("rss", "finviz")
SEARCH_API_RESERVED_FOR = LANE
WEEKDAYS_PER_MONTH_DEFAULT = 21


# Census rows are the F1 deliverable. `class` is residual-web vs legacy-bulk.
# `calls_per_run` is the pre-bound worst case from source; `bound_monthly` is
# the post-F2 projection under the policy (news/catalyst Brave → 0).
SEARCH_CALLER_CENSUS: tuple[dict[str, Any], ...] = (
    {
        "caller": "cio_residual_web",
        "provider": "searxng",
        "trigger": "gate residual rung (decision==openai) + legality",
        "schedule": "none (operator-sequenced; no cron)",
        "calls_per_run": DAILY_SUBJECT_BUDGET * MAX_HOPS_PER_SUBJECT_PER_DAY,
        "class": "residual-web",
        "empty_result_behavior": "PARTIAL + still_unresolved; never fabricate",
        "consumer": "instrument record / CC narrative via apply_hop",
        "bound_monthly": DAILY_SUBJECT_BUDGET * MAX_HOPS_PER_SUBJECT_PER_DAY * WEEKDAYS_PER_MONTH_DEFAULT,
    },
    {
        "caller": "portfolio_news",
        "provider": "brave→finviz/yahoo (F2)",
        "trigger": "llm_score >= 70 enrichment",
        "schedule": "via portfolio_orchestrator (cron DISABLED 2026-08-30)",
        "calls_per_run": 10,  # CALLER_CAPS portfolio_news
        "class": "legacy-bulk",
        "empty_result_behavior": "omit brave_context; snapshot still writes",
        "consumer": "recovery_watch_daily, analyst_report_builder, api_v2",
        "bound_monthly": 0,
    },
    {
        "caller": "catalyst_intelligence",
        "provider": "brave→finviz/yahoo (F2)",
        "trigger": "per-symbol ollama analyze enrichment",
        "schedule": "trade_ai_orchestrator Stage 6",
        "calls_per_run": 10,  # CALLER_CAPS
        "class": "legacy-bulk",
        "empty_result_behavior": "prompt without WEB NEWS line",
        "consumer": "trade_ai_orchestrator.analyze_all_catalysts",
        "bound_monthly": 0,
    },
    {
        "caller": "web_news_fetcher",
        "provider": "brave→finviz/yahoo (F2); ddg scrape fallback",
        "trigger": "on-demand fetch_web_news(symbol)",
        "schedule": "none (library); consumers invoke",
        "calls_per_run": 5,  # CALLER_CAPS
        "class": "legacy-bulk",
        "empty_result_behavior": "[] then DDG scrape; never invent",
        "consumer": "portfolio_ai_analyst, incubator_llm_screener",
        "bound_monthly": 0,
    },
    {
        "caller": "portfolio_weekly_report",
        "provider": "brave→finviz (F2)",
        "trigger": "top-5 holdings analyst commentary",
        "schedule": "Sunday via run_portfolio_weekly.sh",
        "calls_per_run": 5,
        "class": "legacy-bulk",
        "empty_result_behavior": "narrative without commentary block",
        "consumer": "weekly DOCX report",
        "bound_monthly": 0,
    },
    {
        "caller": "symbol_enrichment",
        "provider": "brave→retired; google_news_rss/finviz remain",
        "trigger": "Tier 5 A+ (score>=55), max 3/day pre-F2",
        "schedule": "30 7 * * 1-5 symbol_enrichment.py --limit 50",
        "calls_per_run": 3,
        "class": "legacy-bulk",
        "empty_result_behavior": "skip source; other tiers continue",
        "consumer": "trade_ai_orchestrator enrichment + cron",
        "bound_monthly": 0,
    },
    {
        "caller": "topic_ingestion",
        "provider": "brave (retired unless TOPIC_BRAVE_ENABLED=1)",
        "trigger": "SOURCE 4 gap-fill",
        "schedule": "45 20 * * 1-5 and 45 2 * * * topic_ingestion.py",
        "calls_per_run": 0,  # default off
        "class": "legacy-bulk",
        "empty_result_behavior": "print retired; RSS/Yahoo sources continue",
        "consumer": "news_articles → news_to_catalyst",
        "bound_monthly": 0,
    },
    {
        "caller": "aegis_social_sentiment",
        "provider": "brave→retired (reddit+stocktwits remain)",
        "trigger": "fetch_brave_social top symbols (opt-in AEGIS_BRAVE_ENABLED)",
        "schedule": "0 11,15 * * 1-5 (2×/weekday)",
        "calls_per_run": 0,  # default off Wave 3 2026-09-01
        "class": "legacy-bulk",
        "empty_result_behavior": "reddit/stocktwits-only sentiment",
        "consumer": "aegis overnight / social_sentiment store",
        "bound_monthly": 0,
    },
    {
        "caller": "aegis_transcript_discovery",
        "provider": "brave→retired (DB youtube corpus remains)",
        "trigger": "youtube + article + theme loops (opt-in AEGIS_BRAVE_ENABLED)",
        "schedule": "0 9 * * 1-5",
        "calls_per_run": 0,  # default off Wave 3 2026-09-01
        "class": "legacy-bulk",
        "empty_result_behavior": "degrade; continue other sources",
        "consumer": "aegis transcript / discovery store",
        "bound_monthly": 0,
    },
    {
        "caller": "web_research",
        "provider": "brave (on-demand)",
        "trigger": "interactive search_web / research_symbol_web",
        "schedule": "none (library)",
        "calls_per_run": "variable",
        "class": "legacy-bulk",
        "empty_result_behavior": "[] — never fabricate",
        "consumer": "agents / auto-research",
        "bound_monthly": "budgeted; not bulk news",
    },
    {
        "caller": "credential_monitor",
        "provider": "brave",
        "trigger": "key health probe",
        "schedule": "credential monitor lane",
        "calls_per_run": 1,
        "class": "legacy-bulk",
        "empty_result_behavior": "counted, never denied (deny would false-fail key)",
        "consumer": "credential_monitor status",
        "bound_monthly": "~30 (1/day)",
    },
    {
        "caller": "secret_validators",
        "provider": "brave",
        "trigger": "BRAVE_SEARCH_API_KEY validation",
        "schedule": "on demand / deploy checks",
        "calls_per_run": 1,
        "class": "legacy-bulk",
        "empty_result_behavior": "counted, never denied",
        "consumer": "secret_validators",
        "bound_monthly": "sparse",
    },
)


def projected_search_volume(
    *,
    weekdays_per_month: int = WEEKDAYS_PER_MONTH_DEFAULT,
    as_of: Optional[datetime] = None,
) -> dict[str, Any]:
    """F2 bound-policy volume with as_of. Dry-run arithmetic only — no network.

    Residual-web: N subjects × 1 hop × weekdays. News/catalyst Brave under the
    bound policy is zero (re-pointed to RSS/Finviz). Aegis social/transcript
    Brave paths are opt-in off by default (Wave 3 2026-09-01) → remaining
    legacy bulk cron projection is zero; web_research stays on-demand only.
    """
    now = _utc(as_of)
    wd = max(0, int(weekdays_per_month))
    residual_per_day = DAILY_SUBJECT_BUDGET * MAX_HOPS_PER_SUBJECT_PER_DAY
    residual_monthly = residual_per_day * wd
    news_catalyst_callers = (
        "portfolio_news", "catalyst_intelligence", "web_news_fetcher",
        "portfolio_weekly_report", "symbol_enrichment", "topic_ingestion",
    )
    aegis_repointed = ("aegis_social_sentiment", "aegis_transcript_discovery")
    news_bound = 0
    remaining_legacy = 0
    rows = []
    for row in SEARCH_CALLER_CENSUS:
        bound = row.get("bound_monthly")
        if isinstance(bound, int):
            # Recompute residual against the requested weekday count.
            if row["caller"] == "cio_residual_web":
                bound = residual_monthly
            elif row["caller"] in aegis_repointed:
                bound = 0  # AEGIS_BRAVE_ENABLED default off
            if row["caller"] in news_catalyst_callers:
                news_bound += bound
            elif row["class"] == "legacy-bulk" and isinstance(bound, int):
                remaining_legacy += bound
        rows.append({**row, "bound_monthly": bound})
    return {
        "schema": SCHEMA,
        "as_of": now.replace(microsecond=0).isoformat(),
        "policy": {
            "max_hops_per_subject_per_day": MAX_HOPS_PER_SUBJECT_PER_DAY,
            "daily_subject_budget": DAILY_SUBJECT_BUDGET,
            "news_belongs_on": list(NEWS_BELONGS_ON),
            "search_api_reserved_for": SEARCH_API_RESERVED_FOR,
            "never_fail_open": True,
            "no_cron_for_residual_web": True,
            "aegis_brave_default": "off",
        },
        "residual_web": {
            "provider": "searxng",
            "calls_per_day_cap": residual_per_day,
            "monthly_projection": residual_monthly,
            "arithmetic": (
                f"{DAILY_SUBJECT_BUDGET} subjects × {MAX_HOPS_PER_SUBJECT_PER_DAY} hop "
                f"× {wd} weekdays = {residual_monthly}"
            ),
            "cost_usd_month": 0.0,
        },
        "news_catalyst_brave_under_bound": {
            "monthly_projection": news_bound,
            "arithmetic": "all named news/catalyst Brave sites re-pointed → 0",
            "callers": list(news_catalyst_callers),
        },
        "remaining_legacy_bulk_brave": {
            "monthly_projection": remaining_legacy,
            "arithmetic": (
                f"aegis_social+transcript opt-in off → 0 cron bulk; "
                f"web_research/credential probes remain on-demand under search_budget "
                f"(never fail open). as_of weekday_count={wd}"
            ),
            "note": (
                "Wave 3 2026-09-01: aegis Brave paths gated by AEGIS_BRAVE_ENABLED; "
                "callers kept (named consumers). Not deleted."
            ),
        },
        "census": rows,
        "authority": AUTHORITY,
        "financial_action": FINANCIAL_ACTION,
        "store_writes": False,
    }


class ResidualWebRefused(RuntimeError):
    """Raised when the lane is asked to do something it may not do."""


def _utc(now: Optional[datetime] = None) -> datetime:
    return now or datetime.now(timezone.utc)


def _parse(ts: Any) -> Optional[datetime]:
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    if not ts:
        return None
    s = str(ts).replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        try:
            d = datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _has_execution_language(text: Any) -> Optional[str]:
    """The one shared matcher. Never a second word list."""
    if not text:
        return None
    try:
        from scripts.lib.execution_language import find_imperative
    except Exception:                                            # noqa: BLE001
        return None
    try:
        return find_imperative(text)
    except Exception:                                            # noqa: BLE001
        return None


def narrative_text(narrative: Any) -> str:
    """Flatten a cc_narrative to the prose a reader would actually see."""
    if not isinstance(narrative, dict):
        return str(narrative or "")
    parts = [str(narrative.get("what") or ""),
             str(narrative.get("thesis_fit") or "")]
    parts += [str(r) for r in (narrative.get("risks") or [])]
    return " ".join(p for p in parts if p).strip()


# ── legality ───────────────────────────────────────────────────────────────

def event_hash_moved(record: dict[str, Any],
                     observed: Optional[dict[str, Any]]) -> Optional[str]:
    """Which observable moved, if any. An UNSET prior hash is not a change."""
    if not observed:
        return None
    for name in EVENT_HASHES:
        if name in observed and hash_changed(record, name, observed[name]):
            return name
    return None


def legality(
    record: dict[str, Any],
    *,
    gate_decision: Optional[dict[str, Any]] = None,
    plan: Optional[dict[str, Any]] = None,
    observed: Optional[dict[str, Any]] = None,
    corpus: Optional[dict[str, Any]] = None,
    hops_today: int = 0,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Is a residual web hop legal for this subject right now?

    ALL conditions must hold. Returns a decision-shaped dict rather than a
    bool so a refusal is loggable and a quiet day is legible as a quiet day.
    """
    now = _utc(now)
    rec = record or {}
    gd = gate_decision or {}
    key = str(rec.get("subject_key") or "")
    kind, name = parse_subject_key(key)
    checks: list[dict[str, Any]] = []

    def _check(cid: str, ok: bool, detail: Any = None) -> bool:
        checks.append({"check": cid, "ok": bool(ok), "detail": detail})
        return bool(ok)

    # 1. the gate must ALREADY have routed this subject to the residual rung.
    #    This lane never promotes a subject the gate did not send.
    routed = str(gd.get("decision") or "") == RESIDUAL_DECISION
    _check("gate_routed_to_residual", routed, gd.get("decision"))

    # 2. material. The gate decision does not carry materiality forward, so the
    #    plan is the source of truth and the decision may only confirm it.
    material = bool((plan or {}).get("material")) or bool(gd.get("material"))
    _check("material", material)

    # 3. free-first miss: neither a reuse nor an A/B corpus close.
    reused = str(gd.get("decision") or "") == "reuse"
    corpus_closes = bool((corpus or gd.get("corpus") or {}).get("closes"))
    _check("free_first_miss", not reused and not corpus_closes,
           {"reused": reused, "corpus_closes": corpus_closes})

    # 4. due, OR an observable moved. The hash change overrides SKIP_FRESH only.
    moved = event_hash_moved(rec, observed)
    nxt = _parse(rec.get("next_eligible_at"))
    due = (nxt is None) or (now >= nxt)
    _check("due_or_hash_changed", due or bool(moved),
           {"due": due, "hash_moved": moved,
            "next_eligible_at": rec.get("next_eligible_at")})

    # 5. prior outcome must not be a fail-closed execution-language refusal,
    #    and the record must not be research_blocked.
    prior = str(rec.get("last_outcome") or "")
    blocked = bool(rec.get("research_blocked"))
    _check("no_execution_language_history",
           prior != "execution_language" and not blocked,
           {"last_outcome": prior, "research_blocked": blocked})

    # 6. subject kind
    _check("eligible_kind", kind in ELIGIBLE_KINDS, kind)

    # 7. not dust, not TEST, not cash-as-a-ticker. `is_mintable` already owns
    #    this vocabulary; re-listing it here is how the two would drift.
    mv = rec.get("market_value")
    if plan and mv is None:
        mv = plan.get("market_value")
    mintable, why = is_mintable(kind, name, market_value=mv)
    _check("not_dust_test_or_cash_ticker", mintable, why)

    # 8. one hop per subject per day
    _check("under_daily_subject_cap", int(hops_today) < MAX_HOPS_PER_SUBJECT_PER_DAY,
           {"hops_today": int(hops_today),
            "cap": MAX_HOPS_PER_SUBJECT_PER_DAY})

    failed = [c["check"] for c in checks if not c["ok"]]
    return {
        "schema": SCHEMA,
        "lane": LANE,
        "decision_token": RESIDUAL_DECISION,
        "subject_key": key,
        "kind": kind,
        "legal": not failed,
        "refused_by": failed[0] if failed else None,
        "failed_checks": failed,
        "checks": checks,
        "hash_moved": moved,
        "as_of": now.isoformat(),
        "authority": AUTHORITY,
        "financial_action": FINANCIAL_ACTION,
    }


# ── daily subject selection ────────────────────────────────────────────────

def select_daily(
    candidates: list[dict[str, Any]],
    *,
    budget: int = DAILY_SUBJECT_BUDGET,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Pick at most `budget` subjects for today.

    `candidates` are `{record, legality}` pairs. Preference order is the
    operator's, exactly: **a HELD name whose event hash moved, else SLEEVE:CASH
    if due**, then any other HELD, then the rest.

    The cash sleeve outranks a quiet HELD name deliberately. Letting plain HELD
    sit above it looks harmless until you run it against the real book: 15 HELD
    records with no moved hash fill a budget of 3 every single day, and
    SLEEVE:CASH — the one question the desk actually has an operator waiting on
    — is never reached. That is what the live dry run showed.

    Ordering is deterministic; ties break on subject_key so two runs on the
    same input agree.
    """
    now = _utc(now)
    legal = [c for c in candidates if (c.get("legality") or {}).get("legal")]

    def rank(c: dict[str, Any]) -> tuple:
        rec = c.get("record") or {}
        leg = c.get("legality") or {}
        key = str(rec.get("subject_key") or "")
        kind = str(rec.get("kind") or "").upper()
        moved = bool(leg.get("hash_moved"))
        if kind == "HELD" and moved:
            tier = 0
        elif key == CASH_SLEEVE:
            tier = 1
        elif kind == "HELD":
            tier = 2
        else:
            tier = 3
        return (tier, key)

    ordered = sorted(legal, key=rank)
    chosen = ordered[: max(0, int(budget))]
    return {
        "schema": SCHEMA,
        "as_of": now.isoformat(),
        "budget": int(budget),
        "considered": len(candidates),
        "legal": len(legal),
        "selected": [str((c.get("record") or {}).get("subject_key")) for c in chosen],
        "deferred": [str((c.get("record") or {}).get("subject_key"))
                     for c in ordered[len(chosen):]],
        "refused": [
            {"subject_key": str((c.get("record") or {}).get("subject_key")),
             "refused_by": (c.get("legality") or {}).get("refused_by")}
            for c in candidates if not (c.get("legality") or {}).get("legal")
        ],
        "authority": AUTHORITY,
        "financial_action": FINANCIAL_ACTION,
    }


# ── the hop ────────────────────────────────────────────────────────────────

def _paid_probe_reset() -> None:
    try:
        from scripts.lib.evidence_refresh_job import reset_paid_dispatch_probe
        reset_paid_dispatch_probe()
    except Exception:                                            # noqa: BLE001
        pass


def _paid_probe_read() -> int:
    try:
        from scripts.lib.evidence_refresh_job import paid_dispatch_entered
        return int(paid_dispatch_entered())
    except Exception:                                            # noqa: BLE001
        return 0


def _stub_transport(request: dict[str, Any]) -> dict[str, Any]:
    """The default transport. Pure function, no imports, no socket.

    It returns UNAVAILABLE rather than inventing findings: a stub that fabricates
    a plausible answer is worse than one that returns nothing, because the
    fabrication is what gets attached to the record.
    """
    return {
        "provider": "stub",
        "outcome": "PARTIAL",
        "cost_usd": 0.0,
        "answers": [],
        "still_unresolved": list(request.get("question_ids") or []),
        "source_urls": [],
        "note": ("stub transport — no vendor call was made; findings "
                 "UNAVAILABLE until the operator runs the live hop"),
    }


_STOPWORDS = frozenset("""
a an the and or of for to in on at by with from as is are was were be been being
what which who whom whose when where why how do does did done can could should
would may might will shall must show shows currently current into over under
about their there this that these those it its if then than so such
official officially source sources data figure figures report reports say says
latest recent path outlook view level levels
""".split())


def search_query_from_question(question: str, *, max_terms: int = 6) -> str:
    """Keywords, not a sentence.

    SearXNG is a keyword engine. Handed the full question "What do official
    Federal Reserve and FRED sources currently show for short-term cash
    yields...", it latched onto "do" and returned Merriam-Webster and WebMD
    pages on osteopathy. A first fix kept ten terms beginning with "official"
    and it then matched *that* word instead — dictionary pages again. Generic
    research vocabulary ("official", "sources", "latest", "path") carries no
    signal for a search engine and actively crowds out the terms that do, so it
    is dropped and the query is capped at six terms. Measured 2026-08-30
    against the live engine.
    """
    import re as _re
    words = _re.findall(r"[A-Za-z0-9][A-Za-z0-9.\-]*", str(question or ""))
    terms: list[str] = []
    for w in words:
        if w.lower() in _STOPWORDS or len(w) < 2:
            continue
        if w.lower() in {t.lower() for t in terms}:
            continue
        terms.append(w)
        if len(terms) >= max_terms:
            break
    return " ".join(terms) or str(question or "")[:120]


def _live_transport(request: dict[str, Any]) -> dict[str, Any]:
    """The live transport. NOT taken by this PR — the operator sequences it.

    Imports are deliberately local: the stub path must not so much as import a
    network module, and a top-level import here would defeat that.
    """
    from scripts.lib.searxng_client import searx_search       # noqa: PLC0415
    from llm_lane import generate                             # noqa: PLC0415

    # WAVE F4: stamp pool degradation via the thin helper (not a rewrite of
    # this transport). A thin answer that looks identical to a full one is the
    # failure this programme exists to remove — measured 2026-08-30 a ten-result
    # response came entirely from one engine with CAPTCHA-suspended peers.
    from scripts.lib.search_health_degradation import (  # noqa: PLC0415
        attach_degradation,
    )

    hits = searx_search(
        search_query_from_question(request.get("query") or request.get("question") or ""),
        limit=int(request.get("limit") or 6),
        searx_url=request.get("searx_url"),
    ) or []
    urls = [h.get("url") for h in hits if isinstance(h, dict) and h.get("url")]

    # The retrieved evidence has to reach the model, and the word "json" has to
    # appear in the prompt. Both were missing on the first live attempt: the
    # prompt was the bare question, so the search ran and its results were
    # discarded (the "web" in residual_web did nothing), and DeepSeek rejected
    # json mode with HTTP 400 because the prompt never mentioned json.
    sources = "\n".join(
        f"[{i + 1}] {str(h.get('title') or '')[:110]} — {h.get('url')}\n    "
        f"{str(h.get('content') or h.get('snippet') or '')[:280]}"
        for i, h in enumerate(hits[:6]) if isinstance(h, dict) and h.get("url")
    ) or "(no sources retrieved)"

    prompt = (
        "You are a read-only research assistant for an investment desk.\n"
        f"QUESTION: {request.get('prompt') or request.get('question')}\n\n"
        f"SOURCES:\n{sources}\n\n"
        "Answer ONLY from the sources above. Prefer official pages (SEC, IR, "
        "Federal Reserve, FRED) over commentary. If the sources do not settle "
        "the question, say so rather than inferring.\n"
        "Never tell the operator to buy, sell, add, trim, maintain or hold "
        "anything — state facts, not instructions.\n"
        "Return json with exactly these keys: answers (list of {claim, "
        "source_url}), still_unresolved (list of question ids), "
        "confidence (low|medium|high)."
    )

    text = generate(
        prompt,
        lane=str(request.get("model_lane") or MODEL_LANE),
        process_id=PROCESS_ID,
        task_summary=f"{LANE}:{request.get('subject_key')}",
        response_json=True,
    )
    # `impaired=True` means this answer is narrower than its length suggests.
    return attach_degradation(
        {
            "provider": RESIDUAL_DECISION,
            "outcome": "PARTIAL",
            "cost_usd": None,          # settled by the consumption ledger
            "answers": [],
            "still_unresolved": list(request.get("question_ids") or []),
            "source_urls": urls,
            "raw": text,
        },
        probe=True,
        persist=True,
        url=request.get("searx_url"),
    )


def run_hop(
    subject_key: str,
    *,
    question: str,
    question_ids: Optional[list[str]] = None,
    query: Optional[str] = None,
    apply: bool = False,
    transport: Optional[Callable[[dict[str, Any]], dict[str, Any]]] = None,
    refs: Optional[list[dict[str, Any]]] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Execute one residual web hop. STUB unless `apply=True`.

    `apply=False` (the default) never touches the network and always ledgers
    0.0. `apply=True` requires the caller to have already established legality
    and budget; this function does not re-decide them.
    """
    now = _utc(now)
    _paid_probe_reset()

    request = {
        "subject_key": subject_key,
        "question": question,
        "question_ids": list(question_ids or []),
        "query": query or question,
        "prompt": question,
        "lane": LANE,
        "process_id": PROCESS_ID,
    }

    if transport is None:
        transport = _live_transport if apply else _stub_transport
    resp = dict(transport(request) or {})

    # Type every URL the hop came back with. An ungraded URL never reaches the
    # record: librarian-lite is the only door.
    typed: list[dict[str, Any]] = list(refs or [])
    for url in (resp.get("source_urls") or []):
        try:
            typed.append(source_ref(url, now=now))
        except Exception:                                        # noqa: BLE001
            continue

    outcome = str(resp.get("outcome") or "FAIL")
    if outcome not in OUTCOMES:
        outcome = "FAIL"
    provider = str(resp.get("provider") or ("stub" if not apply else RESIDUAL_DECISION))
    cost = resp.get("cost_usd")
    if provider == "stub" and (cost or 0.0) != 0.0:
        raise ResidualWebRefused("a stub hop must cost 0.0")

    artifact_id = f"rw_{content_hash({'s': subject_key, 'q': question, 'd': now.date().isoformat()})}"

    # F4: forward pool-degradation stamp from the transport. Prior to F4 the
    # live transport set these keys and run_hop dropped them — thinner looked
    # like full on the hop result / CC binding.
    from scripts.lib.search_health_degradation import forward_stamp  # noqa: PLC0415

    hop = {
        "schema": SCHEMA,
        "lane": LANE,
        "decision_token": RESIDUAL_DECISION,
        "process_id": PROCESS_ID,
        "subject_key": subject_key,
        "artifact_id": artifact_id,
        "provider": provider,
        "outcome": outcome,
        "cost_usd": 0.0 if cost is None and not apply else cost,
        "applied": bool(apply),
        "question": question,
        "question_ids": list(question_ids or []),
        "still_unresolved": list(resp.get("still_unresolved") or []),
        "answers": list(resp.get("answers") or []),
        "source_refs": typed,
        "source_urls": [r.get("url") for r in typed],
        "librarian": summarize(typed, now=now),
        "note": resp.get("note"),
        "paid_dispatch_entered": _paid_probe_read(),
        "as_of": now.isoformat(),
        "authority": AUTHORITY,
        "financial_action": FINANCIAL_ACTION,
        "memory_behavior_influence": MBI_BEHAVIOR,
    }
    return forward_stamp(hop, resp)


# ── write the instrument record ────────────────────────────────────────────

def _facts_only_narrative(
    record: dict[str, Any],
    hop: dict[str, Any],
    *,
    now: datetime,
) -> dict[str, Any]:
    """Build the cc_narrative patch. FACTS ONLY — refuses execution language."""
    old = dict(record.get("cc_narrative") or {})
    refs = [r for r in (hop.get("source_refs") or []) if may_close(r, now=now)]
    cited = ", ".join(str(r.get("host")) for r in refs[:3])
    what = (f"Residual web pass {hop.get('as_of', '')[:10]}: "
            f"{len(hop.get('source_refs') or [])} source(s) typed, "
            f"{len(refs)} at a closing grade"
            + (f" ({cited})" if cited else "")
            + f"; {len(hop.get('still_unresolved') or [])} question(s) still unresolved.")
    if hop.get("note"):
        what += f" {hop['note']}."
    # F4: surface CAPTCHA / impaired pool so narrative thinner ≠ full.
    from scripts.lib.search_health_degradation import narrative_suffix  # noqa: PLC0415
    what += narrative_suffix(hop)

    narrative = cc_narrative(
        what=what,
        thesis_fit=str(old.get("thesis_fit") or ""),
        recommendation_option_id=old.get("recommendation_option_id"),
        risks=list(old.get("risks") or []),
        evidence_refs=[
            {"source_id": r.get("source_id"), "url": r.get("url"),
             "grade": r.get("grade"), "as_of": r.get("as_of"),
             "stale_after_days": r.get("stale_after_days")}
            for r in (hop.get("source_refs") or [])
        ],
        writer=f"cognition:{LANE}",
        as_of=now.isoformat(),
    )
    hit = _has_execution_language(narrative_text(narrative))
    if hit:
        raise ResidualWebRefused(
            f"narrative carries execution language ({hit!r}) — refused, not filtered")
    return narrative


def apply_hop(
    record: dict[str, Any],
    hop: dict[str, Any],
    *,
    observed: Optional[dict[str, Any]] = None,
    now: Optional[datetime] = None,
    strict: bool = True,
) -> tuple[dict[str, Any], list[str]]:
    """Write one hop's outcome onto the InstrumentRecord as COGNITION.

    VALID/PARTIAL -> artifact_id, source refs + grades, a reframed next
    question, a facts-only narrative patch, refreshed hashes, next_eligible_at.

    REJECT/execution_language -> research_blocked, NO attach, and no narrative.
    The next question must differ from the prompt just used: re-asking a prompt
    that failed closed is how a desk spends a budget learning nothing.
    """
    now = _utc(now)
    rec = dict(record)
    outcome = str(hop.get("outcome") or "FAIL")
    asked = str(hop.get("question") or "")

    hashes = {k: content_hash(v) for k, v in (observed or {}).items()}

    if outcome in ATTACHING_OUTCOMES:
        narrative = _facts_only_narrative(rec, hop, now=now)
        unresolved = list(hop.get("still_unresolved") or [])
        if unresolved:
            nxt_q = (f"Which independent source settles the still-unresolved "
                     f"question(s) {', '.join(unresolved[:3])}?")
        else:
            nxt_q = ("What new evidence would contradict the sources just "
                     "attached?")
        rec["research_blocked"] = False
        artifact_id = hop.get("artifact_id")
        nxt_at = (now + timedelta(days=NEXT_LOOK_DAYS)).isoformat()
        priority = None
    else:
        # Fail closed. No attach, no narrative, no artifact.
        rec["research_blocked"] = True
        outcome = ("execution_language"
                   if outcome == "execution_language" else "rejected")
        narrative = None
        artifact_id = None
        nxt_q = (f"Prior residual web pass was refused ({outcome}). What "
                 f"INDEPENDENT evidence would settle this without restating it?")
        nxt_at = (now + timedelta(days=BLOCKED_NEXT_LOOK_DAYS)).isoformat()
        priority = None

    # The operator's cognition law: the next question must differ from the
    # prompt just used, and from whatever the record already held.
    if nxt_q.strip() == asked.strip():
        nxt_q = nxt_q + " (reframed)"
    if nxt_q.strip() == str(rec.get("next_research_question") or "").strip():
        nxt_q = nxt_q + " (reframed)"

    from scripts.lib.cio_instrument_record import apply_cognition
    return apply_cognition(
        rec,
        next_research_question=nxt_q,
        next_eligible_at=nxt_at,
        notify_priority=priority,
        narrative=narrative,
        artifact_id=artifact_id,
        outcome=outcome,
        hashes=hashes or None,
        strict=strict,
    )


# ── notify ─────────────────────────────────────────────────────────────────

# `immediate` is deliberately absent. notify_priority may rise to `cc` or
# `digest` on a hash change; escalating further is a policy this lane does not
# own and must not invent.
NOTIFY_ON_HASH_CHANGE = "cc"
NOTIFY_DIGEST = "digest"


def notify_priority_for(
    record: dict[str, Any],
    hop: dict[str, Any],
    *,
    hash_moved: Optional[str] = None,
) -> str:
    """What this lane may raise notify_priority to. Never `immediate`."""
    current = str(record.get("notify_priority") or "none")
    if current == "immediate_candidate":
        return current                      # existing policy already allowed it
    if str(hop.get("outcome")) not in ATTACHING_OUTCOMES:
        return current
    if hash_moved:
        return NOTIFY_ON_HASH_CHANGE
    return current if current != "none" else NOTIFY_ON_HASH_CHANGE


def cc_binding(record: dict[str, Any], hop: dict[str, Any],
               *, now: Optional[datetime] = None) -> dict[str, Any]:
    """The CC block for this subject. Binds the UPDATED cc_narrative.

    `telegram_sent` is a constant False here exactly as it is in
    `cio_command_center` — this lane adds no send site.
    """
    now = _utc(now)
    binding = {
        "schema": SCHEMA,
        "lane": LANE,
        "subject_key": record.get("subject_key"),
        "cc_narrative": record.get("cc_narrative"),
        "next_research_question": record.get("next_research_question"),
        "next_eligible_at": record.get("next_eligible_at"),
        "notify_priority": record.get("notify_priority"),
        "research_blocked": bool(record.get("research_blocked")),
        "artifact_id": record.get("last_artifact_id"),
        "source_refs": hop.get("source_refs") or [],
        "librarian": hop.get("librarian"),
        "cost_usd": hop.get("cost_usd"),
        "paid_dispatch_entered": hop.get("paid_dispatch_entered"),
        "telegram_sent": False,
        "would_send": False,
        "as_of": now.isoformat(),
        "authority": AUTHORITY,
        "financial_action": FINANCIAL_ACTION,
        "memory_behavior_influence": MBI_BEHAVIOR,
    }
    # F4: CC binding carries the same stamp the hop carries.
    from scripts.lib.search_health_degradation import forward_stamp  # noqa: PLC0415
    return forward_stamp(binding, hop)


def entity_admissible_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Entity questions may use official pages, not blogs."""
    return [r for r in refs if admissible_for_entity_question(r)]
