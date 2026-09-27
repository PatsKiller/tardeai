"""Web retrieval for Hermes CIO research on an options thesis gap (operator 2026-09-26).

"why not using hermes brave etc research llm if needed same research lanes": the
CIO research lane only read what the house already held. Three DELL runs cited
nothing but internal ids and answered "no authored thesis exists" -- they
restated the gap instead of filling it. This step runs before the model call and
supplies web results the model must answer from and cite by url.

Same search lanes as the governed research producer: SearXNG first (self-hosted,
free, ``free_search.search``), then the Brave router (paid, reserved/settled,
per-caller daily cap) only when SearXNG returns nothing. Scope is limited to
requests whose ``reason`` is listed in ``options_desk_settings.web_research``.
Never raises: a search failure means "no web results", never a failed research.
READ_ONLY_ADVISORY; MBI_BEHAVIOR=0.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

_ROOT = Path(__file__).resolve().parents[2]

DEFAULTS: dict[str, Any] = {
    "enabled_reasons": ["options_thesis_gap"],
    "caller": "hermes_cio_research",
    "max_queries": 6,
    "results_per_query": 3,
    "max_results": 10,
    "snippet_chars": 500,
    "brave_fallback": True,
}

# Base queries per research intent; the CIO follow-up items add their own.
INTENT_QUERIES = {
    "thesis_check": "{sym} stock outlook growth drivers {year}",
    "catalyst_map": "{sym} next earnings date {year}",
    "invalidation": "{sym} stock risks downgrade",
    "bear_case": "{sym} bear case risks analyst",
}
# Intents whose answers are dated events: SearXNG "news" first (then general).
NEWS_INTENTS = {"catalyst_map", "invalidation", "bear_case"}
# A hit must read like investment material; "DELL" alone returns the issuer's shop,
# driver downloads and support pages (2026-09-26 dry run: 6 of 10 results).
_FINANCE = re.compile(
    r"\b(stock|shares|earnings|analyst|revenue|quarter|guidance|nyse|nasdaq|investor|"
    r"price target|downgrade|upgrade|margin|fiscal|dividend|valuation|sec filing|10-k|10-q)\b",
    re.I,
)
# House schema words in CIO concerns ("catalyst.events", "authored thesis version")
# are not things the web can answer; they are dropped from the search query.
_HOUSE_JARGON = frozenset(
    "authored version stance summary evidence counter counter_evidence ids event events "
    "pre-registered invalidation_conditions verified producer thesis fields unresolved "
    "position specific dated find sourced facts resolve concern restate".split()
)
_FILLER = re.compile(
    r"\b(no|not|the|a|an|and|or|of|for|this|that|is|are|all|null|empty|with|to|on|in|what|which)\b", re.I
)


def settings(cfg: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    if cfg is None:
        try:
            import yaml

            intent = yaml.safe_load((_ROOT / "assets" / "portfolio_intent.yaml").read_text()) or {}
            cfg = (intent.get("options_desk_settings") or {}).get("web_research") or {}
        except Exception:  # noqa: BLE001
            cfg = {}
    return {k: (cfg or {}).get(k, v) for k, v in DEFAULTS.items()}


def applies(request: dict[str, Any], s: dict[str, Any]) -> bool:
    return str(request.get("reason") or "") in set(s.get("enabled_reasons") or [])


def _symbol(request: dict[str, Any]) -> str:
    subj = request.get("subject") or {}
    return str(subj.get("symbol") or request.get("symbol") or "").upper()


def _question_query(sym: str, text: str) -> str:
    t = re.sub(rf"^\s*{re.escape(sym)}\s*[:\-—]\s*", "", str(text or ""), flags=re.I)
    t = re.sub(r"^(research|find)[^:]*:\s*", "", t, flags=re.I)
    t = _FILLER.sub(" ", re.sub(r"[^A-Za-z0-9/ .$%-]", " ", t))
    words = [
        w
        for w in t.split()
        if len(w) > 2 and w.upper() != sym and "." not in w and "_" not in w and w.lower() not in _HOUSE_JARGON
    ][:7]
    return f"{sym} {' '.join(words)}".strip() if words else ""


def queries_for(request: dict[str, Any], s: dict[str, Any], *, now: Optional[datetime] = None) -> list[str]:
    sym = _symbol(request)
    if not sym:
        return []
    year = (now or datetime.now(timezone.utc)).year
    return [q for q, _ in planned_queries(request, s, now=now)]


def planned_queries(
    request: dict[str, Any], s: dict[str, Any], *, now: Optional[datetime] = None
) -> list[tuple[str, str]]:
    """(query, kind) pairs; intent templates first, then the CIO's own concerns."""
    sym = _symbol(request)
    if not sym:
        return []
    year = (now or datetime.now(timezone.utc)).year
    out: list[tuple[str, str]] = []
    qs = request.get("questions") or []
    for q in qs:
        intent = str(q.get("intent") or "")
        if intent in INTENT_QUERIES:
            out.append((INTENT_QUERIES[intent].format(sym=sym, year=year), "news" if intent in NEWS_INTENTS else "web"))
    for q in qs:
        if str(q.get("intent") or "") not in INTENT_QUERIES:
            out.append((_question_query(sym, q.get("text")), "web"))
    seen, uniq = set(), []
    for x, kind in out:
        k = x.lower()
        if x and k not in seen:
            seen.add(k)
            uniq.append((x, kind))
    return uniq[: int(s["max_queries"])]


def _canonical(url: str) -> str:
    return url.split("#", 1)[0].split("?", 1)[0].rstrip("/").lower()


def relevant(hit: dict[str, Any]) -> bool:
    text = f"{hit.get('title') or ''} {hit.get('description') or hit.get('snippet') or hit.get('content') or ''}"
    return bool(_FINANCE.search(text))


def _brave_key(env: dict[str, str]) -> str:
    key = env.get("BRAVE_SEARCH_API_KEY", "")
    if key:
        return key
    try:  # the systemd worker does not load .env; read only this one key from it
        for raw in (_ROOT / ".env").read_text(errors="ignore").splitlines():
            if raw.strip().startswith("BRAVE_SEARCH_API_KEY="):
                return raw.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def _default_free(query: str, **kw: Any) -> Any:
    try:
        from scripts.lib import free_search
    except ImportError:  # pragma: no cover
        from lib import free_search  # type: ignore
    return free_search.search(query, **kw)


def _default_brave(query: str, **kw: Any) -> Any:
    try:
        from scripts.lib import brave_router
    except ImportError:  # pragma: no cover
        from lib import brave_router  # type: ignore
    return brave_router.search(query, **kw)


def gather(
    request: dict[str, Any],
    *,
    cfg: Optional[dict[str, Any]] = None,
    free_fn: Optional[Callable[..., Any]] = None,
    brave_fn: Optional[Callable[..., Any]] = None,
    env: Optional[dict[str, str]] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Web results for one research request, or ``{"used": False}``. Never raises."""
    s = settings(cfg)
    if not applies(request, s):
        return {"used": False, "reason": "not_enabled_for_reason"}
    env = dict(env if env is not None else os.environ)
    free_fn = free_fn or _default_free
    brave_fn = brave_fn or _default_brave
    n, cap, chars = int(s["results_per_query"]), int(s["max_results"]), int(s["snippet_chars"])
    caller = str(s["caller"])
    rid = str(request.get("research_id") or "")
    log: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for q, kind in planned_queries(request, s, now=now):
        provider, resp = "searxng", None
        try:
            resp = free_fn(q, caller=caller, kind=kind, count=n)
        except Exception as exc:  # noqa: BLE001
            log.append({"query": q, "provider": provider, "ok": False, "reason": type(exc).__name__})
        hits = list(getattr(resp, "results", None) or []) if resp is not None and getattr(resp, "ok", False) else []
        hits = [h for h in hits if isinstance(h, dict) and relevant(h)]
        if not hits and s.get("brave_fallback"):
            key = _brave_key(env)
            if key:
                try:
                    resp = brave_fn(
                        q,
                        kind=kind,
                        count=n,
                        caller=caller,
                        purpose="hermes_cio_research",
                        idempotency_key=f"hwr|{rid}|{q}",
                        enabled=True,
                        api_key=key,
                    )
                    provider = str(getattr(resp, "provider", "") or "brave")
                    hits = list(getattr(resp, "results", None) or []) if getattr(resp, "ok", False) else []
                    hits = [h for h in hits if isinstance(h, dict) and relevant(h)]
                except Exception as exc:  # noqa: BLE001
                    log.append({"query": q, "provider": "brave", "ok": False, "reason": type(exc).__name__})
        log.append(
            {
                "query": q,
                "provider": provider,
                "ok": bool(hits),
                "n": len(hits),
                "reason": None if hits else str(getattr(resp, "reason", "") or "no_results")[:120],
            }
        )
        for h in hits:
            url = str((h or {}).get("url") or "").strip()
            if not url.startswith("http") or _canonical(url) in seen or len(results) >= cap:
                continue
            seen.add(_canonical(url))
            body = h.get("description") or h.get("snippet") or h.get("content") or ""
            results.append(
                {
                    "id": f"w{len(results) + 1}",
                    "title": str(h.get("title") or "")[:200],
                    "url": url,
                    "snippet": str(body)[:chars],
                    "provider": provider,
                    "query": q,
                }
            )
    return {"used": True, "as_of": (now or datetime.now(timezone.utc)).isoformat(), "queries": log, "results": results}


PROMPT = (
    "web_results are live search results fetched for this request. Answer each question from them "
    "first, and cite every result you use by its url (not its id) in that answer's citations and in "
    "source_refs. Never cite a url that is not in web_results. Do not answer by restating that the house "
    "has no thesis or data: research the question, and say plainly what the results did not establish."
)


def ground_citations(body: dict[str, Any], web: dict[str, Any]) -> dict[str, Any]:
    """Map w-ids to urls, drop urls that were not supplied, record what was used."""
    results = (web or {}).get("results") or []
    by_id = {r["id"]: r["url"] for r in results}
    allowed = {r["url"] for r in results}

    def fix(items: Any) -> list[Any]:
        out = []
        for c in items or []:
            c = by_id.get(str(c), c)
            if isinstance(c, str) and c.startswith("http") and c not in allowed:
                continue  # a url the model was never given is a fabrication
            if c not in out:
                out.append(c)
        return out

    used: list[str] = []
    for a in body.get("answers") or []:
        if isinstance(a, dict):
            a["citations"] = fix(a.get("citations"))
            used += [c for c in a["citations"] if isinstance(c, str) and c in allowed]
    for key in ("sources", "source_refs", "evidence_links", "evidence"):
        if isinstance(body.get(key), list):
            body[key] = fix(body[key])
            used += [c for c in body[key] if isinstance(c, str) and c in allowed]
    used = list(dict.fromkeys(used))
    body["sources"] = list(dict.fromkeys(list(body.get("sources") or []) + used))[:20]
    body["source_urls"] = used
    body["web_research"] = {
        "queries": web.get("queries"),
        "supplied": len(results),
        "cited": len(used),
        "providers": sorted({r["provider"] for r in results}),
    }
    return body
