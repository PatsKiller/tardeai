"""White-Space Discovery — NYC Loft Law domain pack scanner (spec Part G).

Loads config/research_domains/nyc_loft_law.yaml (fail-closed pack validation),
registers its `legal_housing` domain into the research-domain registry (the
registry loader only reads the base + custom yamls, so the pack wires itself
in via ensure_domain_registered — same validator, same hard rules), and scans
news_articles + hermes_research_intelligence for the pack's term list.

Matches become Discovery Inbox candidates via inbox.upsert_candidate with
meta.research_domain pinned to the pack domain — workspace stamping
(meta_json.workspace_id = nyc_loft_law, a NON-trading workspace) comes free
from inbox enrichment + workspaces.workspace_for_domain.

Candidate-type classification (content kind, tested on synthetic texts):
  court/case-citation wording          -> CASE_LAW_CANDIDATE
  statute/rule-change wording          -> STATUTE_UPDATE_CANDIDATE
  explainer wording / big term cluster -> WEBSITE_CONTENT_CANDIDATE
  recurring topic (everything else)    -> LEGAL_TOPIC_CANDIDATE

Source policy: every source is classified primary/secondary/blocked/unlisted
against the pack's hostname suffix lists — BLOCKED sources are skipped
entirely and primary sources rank first (source_quality).

HARD RULES:
  * ALL required labels forced onto every candidate (meta.required_labels),
    on top of the registry's professional-review label + forced
    OPERATOR_REVIEW_REQUIRED (risk_level: legal);
  * NEVER auto-publish: the pack loader rejects auto_publish: true; content
    output ends at meta.content_stage = "candidate" (LLM review / citation
    check are existing/later lanes — no publishing path exists here);
  * advisory-only: no broker/execution imports anywhere in this module;
  * all DB reads go through this module's _execute seam (one statement per
    call via db_adapter) so tests monkeypatch it and the 120s
    idle-in-transaction guard can never bite.

Worker pool: importing this module registers the 'legal_domain' lane runner
(worker_pool.register_lane_runner), so the bounded pool can run the scan under
its cadence/lock/cap/do-no-harm gates.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import dedupe, domains, worker_pool

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PACK_PATH = Path(os.getenv("HERMES_LOFT_LAW_PACK_YAML")
                 or PROJECT_ROOT / "config" / "research_domains" / "nyc_loft_law.yaml")

PACK_NAME = "nyc_loft_law"
WORKSPACE_ID = "nyc_loft_law"
PRODUCER = "loft_law_discovery"
ACTOR = "ingestor:loft_law"

WINDOW_HOURS = 168          # 7-day scan window (lane cadence is daily)
SCAN_LIMIT = 300            # max rows pulled per input stream
TTL_DAYS = 60               # legal topics stay reviewable longer than spikes
EXPLAINER_CLUSTER_MIN = 3   # >= this many rows on one term = explainer-worthy

# The four labels spec Part G forces onto every candidate. The pack yaml must
# list all of them verbatim — load_pack fails closed otherwise.
REQUIRED_LABELS = (
    "Research summary only.",
    "Not legal advice.",
    "Consult a qualified NY attorney.",
    "Cite primary sources where possible.",
)

# Candidate types a loft-law pack may emit (mirrors inbox.CANDIDATE_TYPES
# members added by the white-space migration + SOURCE).
PACK_CANDIDATE_TYPES = frozenset({
    "LEGAL_TOPIC_CANDIDATE", "SOURCE_CANDIDATE", "CASE_LAW_CANDIDATE",
    "STATUTE_UPDATE_CANDIDATE", "WEBSITE_CONTENT_CANDIDATE",
})

SOURCE_QUALITY = {"primary": 1.0, "secondary": 0.6, "unlisted": 0.3}

# ── candidate-type wording heuristics (pure, unit-tested) ────────────────────

# "Chazon, LLC v. NYC Loft Board", "Matter of ... v. ..." style citations
_CASE_CITATION_RX = re.compile(
    r"\b(?:matter of\s+)?[a-z0-9][\w.,&'()-]*(?:\s+[\w.,&'()-]+){0,6}\s+v\.?\s+[a-z0-9]",
    re.IGNORECASE)
_CASE_HINTS = ("appellate division", "court of appeals", "supreme court",
               "civil court", "housing court", "article 78", "petitioner",
               "respondent", "docket", "court ruling", "court held",
               "judge ruled", "ruling", "decision and order", "appeal")
_STATUTE_HINTS = ("amendment", "amended", "bill", "enacted", "signed into law",
                  "local law", "rule change", "proposed rule", "final rule",
                  "rulemaking", "effective date", "statute", "new law",
                  "deadline extended", "expanded coverage", "sunset",
                  "legislation")
_EXPLAINER_HINTS = ("how to", "guide", "explained", "explainer", "what is",
                    "what you need to know", "faq", "step by step",
                    "step-by-step", "overview", "basics")


class LoftLawPackError(Exception):
    """Raised when the domain-pack yaml fails validation (fail closed)."""


_pack_cache: dict[str, Any] | None = None


# ── pack loading (fail closed) ───────────────────────────────────────────────

def _require_str_list(data: dict, key: str, *, ctx: str) -> list[str]:
    raw = data.get(key)
    if not isinstance(raw, list) or not raw or \
            not all(isinstance(x, str) and x.strip() for x in raw):
        raise LoftLawPackError(f"{ctx}: {key} must be a non-empty list of strings")
    return [x.strip() for x in raw]


def load_pack(path: Path | str | None = None,
              force_reload: bool = False) -> dict[str, Any]:
    """Load + validate the domain pack. Any structural problem raises
    LoftLawPackError — the scanner fails closed rather than running against a
    broken pack. Cached for the default path; explicit paths (tests) always
    load fresh."""
    global _pack_cache
    default_path = path is None
    if default_path and _pack_cache is not None and not force_reload:
        return _pack_cache

    p = Path(path) if path else PACK_PATH
    if not p.exists():
        raise LoftLawPackError(f"domain pack missing: {p}")
    import yaml
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception as e:
        raise LoftLawPackError(f"unparseable domain pack {p}: {e}") from e
    if not isinstance(data, dict):
        raise LoftLawPackError(f"domain pack {p} must be a mapping")

    if str(data.get("pack") or "").strip().lower() != PACK_NAME:
        raise LoftLawPackError(f"domain pack {p}: pack must be {PACK_NAME!r}")
    if str(data.get("workspace") or "").strip().lower() != WORKSPACE_ID:
        raise LoftLawPackError(
            f"domain pack {p}: workspace must be {WORKSPACE_ID!r} "
            f"(the non-trading loft-law workspace)")

    dom = data.get("domain")
    if not isinstance(dom, dict) or not str(dom.get("name") or "").strip():
        raise LoftLawPackError(f"domain pack {p}: domain.name is required")

    terms = _require_str_list(data, "terms", ctx=f"domain pack {p}")

    policy = data.get("source_policy")
    if not isinstance(policy, dict):
        raise LoftLawPackError(f"domain pack {p}: source_policy is required")
    src = {tier: [d.lower().lstrip(".") for d in
                  _require_str_list(policy, tier, ctx=f"domain pack {p} source_policy")]
           for tier in ("primary", "secondary", "blocked")}

    labels = _require_str_list(data, "required_labels", ctx=f"domain pack {p}")
    missing = [lbl for lbl in REQUIRED_LABELS if lbl not in labels]
    if missing:
        raise LoftLawPackError(
            f"domain pack {p}: required_labels missing mandatory label(s) {missing}")

    ctypes = [t.upper() for t in
              _require_str_list(data, "candidate_types", ctx=f"domain pack {p}")]
    bad = [t for t in ctypes if t not in PACK_CANDIDATE_TYPES]
    if bad:
        raise LoftLawPackError(
            f"domain pack {p}: unknown candidate_types {bad} "
            f"(valid: {sorted(PACK_CANDIDATE_TYPES)})")

    publishing = data.get("publishing")
    if not isinstance(publishing, dict) or publishing.get("auto_publish") is not False:
        raise LoftLawPackError(
            f"domain pack {p}: publishing.auto_publish must be exactly false "
            f"(never auto-publish — hard rule)")
    content_stage = str(publishing.get("content_stage") or "candidate").strip()

    pack = {
        "pack": PACK_NAME,
        "workspace": WORKSPACE_ID,
        "domain": dict(dom),
        "domain_name": str(dom["name"]).strip().lower(),
        "terms": terms,
        "source_policy": src,
        "required_labels": labels,
        "candidate_types": ctypes,
        "auto_publish": False,
        "content_stage": content_stage,
    }
    if default_path:
        _pack_cache = pack
    return pack


def ensure_domain_registered(pack: dict[str, Any] | None = None) -> str:
    """Merge the pack's domain into the in-process research-domain registry.

    domains.load_domains() only reads the base + custom yamls, so the pack
    registers its domain here using the SAME validator
    (domains._validate_domain) — every registry hard rule applies
    (auto_promote force-false; risk_level `legal` forces the
    professional-review label + OPERATOR_REVIEW_REQUIRED). Idempotent; returns
    the domain name."""
    pack = pack or load_pack()
    name = pack["domain_name"]
    doms = domains.load_domains()  # default-path call returns the live cache
    if name in doms:
        return name
    spec = dict(pack["domain"])
    spec.pop("name", None)
    spec.setdefault("classification_keywords", list(pack["terms"]))
    doms[name] = domains._validate_domain(name, spec, source=f"pack:{PACK_NAME}",
                                          defaults={})
    return name


# ── source policy classification (pure) ──────────────────────────────────────

def _host(url_or_domain: str) -> str:
    s = str(url_or_domain or "").strip().lower()
    if "://" in s:
        from urllib.parse import urlparse
        s = urlparse(s).netloc
    return s.split("@")[-1].split(":")[0].removeprefix("www.")


def classify_source(url_or_domain: str | None,
                    pack: dict[str, Any] | None = None) -> str:
    """primary | secondary | blocked | unlisted for a URL or bare domain.
    Hostname-suffix match (host == entry or host endswith .entry); blocked
    ALWAYS wins so a blocked host can never sneak in via a broader entry."""
    pack = pack or load_pack()
    host = _host(url_or_domain or "")
    if not host:
        return "unlisted"

    def _matches(entries: list[str]) -> bool:
        return any(host == e or host.endswith("." + e) for e in entries)

    policy = pack["source_policy"]
    if _matches(policy["blocked"]):
        return "blocked"
    if _matches(policy["primary"]):
        return "primary"
    if _matches(policy["secondary"]):
        return "secondary"
    return "unlisted"


# ── term matching + candidate-type classification (pure) ─────────────────────

def match_terms(text: str, terms: list[str] | None = None) -> list[str]:
    """Word-boundary, case-insensitive term matches (same boundary rule as
    domains._keyword_hits) preserving the pack's term order."""
    if terms is None:
        terms = load_pack()["terms"]
    hay = str(text or "").lower()
    out: list[str] = []
    for term in terms:
        t = str(term).strip().lower()
        if t and re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", hay):
            out.append(str(term))
    return out


def classify_candidate_type(text: str, *, cluster_size: int = 1) -> str:
    """Content kind → candidate type (spec Part G):
      court/case-citation wording          -> CASE_LAW_CANDIDATE
      statute/rule-change wording          -> STATUTE_UPDATE_CANDIDATE
      explainer wording OR a big cluster   -> WEBSITE_CONTENT_CANDIDATE
      recurring topic (default)            -> LEGAL_TOPIC_CANDIDATE
    """
    t = str(text or "").lower()
    if _CASE_CITATION_RX.search(t) or any(h in t for h in _CASE_HINTS):
        return "CASE_LAW_CANDIDATE"
    if any(h in t for h in _STATUTE_HINTS):
        return "STATUTE_UPDATE_CANDIDATE"
    if any(h in t for h in _EXPLAINER_HINTS) or cluster_size >= EXPLAINER_CLUSTER_MIN:
        return "WEBSITE_CONTENT_CANDIDATE"
    return "LEGAL_TOPIC_CANDIDATE"


# ── DB plumbing (monkeypatchable seam, entity_spikes convention) ─────────────

def _execute(sql: str, params=None, fetch: str | None = None):
    """Single monkeypatchable DB seam — delegates to db_adapter._execute
    (one statement per call, immediate commit)."""
    from db_adapter import _execute as _db_execute
    return _db_execute(sql, params, fetch=fetch)


def _rows(sql: str, params=None) -> list[dict[str, Any]]:
    return [dict(r) for r in (_execute(sql, params, fetch="all") or [])]


def _table_exists(table: str) -> bool:
    try:
        row = _execute(
            "SELECT 1 AS ok FROM information_schema.tables WHERE table_name = %s",
            (table,), fetch="one")
        return bool(row)
    except Exception:
        return False


def _ilike_filter(columns: list[str], terms: list[str]) -> tuple[str, list[str]]:
    clause = " OR ".join(f"{c} ILIKE %s" for c in columns for _ in terms)
    params = [f"%{t}%" for _ in columns for t in terms]
    return clause, params


def collect_news_rows(window_hours: int = WINDOW_HOURS,
                      terms: list[str] | None = None,
                      notes: list[str] | None = None) -> list[dict[str, Any]]:
    """Recent news_articles rows ILIKE-prefiltered on the term list."""
    if not _table_exists("news_articles"):
        if notes is not None:
            notes.append("news_articles missing — news stream skipped")
        return []
    terms = terms if terms is not None else load_pack()["terms"]
    clause, params = _ilike_filter(["title", "summary"], terms)
    rows = _rows(
        f"""SELECT COALESCE(title, '') AS title, COALESCE(summary, '') AS body,
                   COALESCE(source, 'news') AS source, source_url, created_at
            FROM news_articles
            WHERE created_at > now() - make_interval(hours => %s) AND ({clause})
            ORDER BY created_at DESC LIMIT %s""",
        tuple([max(1, int(window_hours))] + params + [SCAN_LIMIT]))
    for r in rows:
        r["stream"] = "news_articles"
    return rows


def collect_research_rows(window_hours: int = WINDOW_HOURS,
                          terms: list[str] | None = None,
                          notes: list[str] | None = None) -> list[dict[str, Any]]:
    """Recent hermes_research_intelligence rows ILIKE-prefiltered on terms."""
    if not _table_exists("hermes_research_intelligence"):
        if notes is not None:
            notes.append("hermes_research_intelligence missing — research stream skipped")
        return []
    terms = terms if terms is not None else load_pack()["terms"]
    clause, params = _ilike_filter(["topic", "summary"], terms)
    rows = _rows(
        f"""SELECT COALESCE(topic, '') AS title, COALESCE(summary, '') AS body,
                   COALESCE(source, 'hermes_research') AS source,
                   NULL AS source_url, created_at
            FROM hermes_research_intelligence
            WHERE created_at > now() - make_interval(hours => %s) AND ({clause})
            ORDER BY created_at DESC LIMIT %s""",
        tuple([max(1, int(window_hours))] + params + [SCAN_LIMIT]))
    for r in rows:
        r["stream"] = "hermes_research_intelligence"
    return rows


# ── payload building (pure over collected rows) ──────────────────────────────

def _base_meta(pack: dict[str, Any], matched: list[str],
               source_class: str) -> dict[str, Any]:
    """Meta stamped on EVERY payload: pinned domain (→ workspace stamping),
    forced labels, source-policy class, content pipeline stub stage."""
    return {
        "producer": PRODUCER,
        "research_domain": pack["domain_name"],   # pin → nyc_loft_law workspace
        "workspace_id": WORKSPACE_ID,
        "required_labels": list(pack["required_labels"]),  # ALL labels forced
        "source_policy_class": source_class,
        "source_quality": SOURCE_QUALITY.get(source_class, SOURCE_QUALITY["unlisted"]),
        "content_stage": pack["content_stage"],   # 'candidate' — never published
        "keywords": matched[:10],
        "matched_terms": matched,
    }


def build_payloads(rows: list[dict[str, Any]], *,
                   pack: dict[str, Any] | None = None,
                   limit: int = 25,
                   skipped: dict[str, int] | None = None) -> list[dict[str, Any]]:
    """Collected rows → inbox.upsert_candidate keyword payloads.

    Per row: term-match (no match → skip), source classified against the pack
    policy (BLOCKED → skipped entirely). Case-law / statute rows become
    individual candidates; the rest cluster per lead term into a recurring
    LEGAL_TOPIC (or WEBSITE_CONTENT when explainer-worthy). Primary sources
    rank first (source_quality desc). Everything is OPERATOR_REVIEW_REQUIRED.
    """
    pack = pack or load_pack()

    def _skip(reason: str) -> None:
        if skipped is not None:
            skipped[reason] = skipped.get(reason, 0) + 1

    singles: list[dict[str, Any]] = []
    clusters: dict[str, dict[str, Any]] = {}

    for row in rows:
        title = str(row.get("title") or "").strip()
        text = f"{title} {row.get('body') or ''}".strip()
        matched = match_terms(text, pack["terms"])
        if not matched:
            _skip("no_term_match")
            continue
        source_ref = row.get("source_url") or row.get("source")
        source_class = classify_source(source_ref, pack)
        if source_class == "blocked":
            _skip("blocked_source")
            continue
        entry = {
            "title": title or matched[0],
            "text": text,
            "matched": matched,
            "source": str(row.get("source") or "unknown"),
            "source_url": row.get("source_url"),
            "source_class": source_class,
            "stream": str(row.get("stream") or "unknown"),
        }
        kind = classify_candidate_type(text)
        if kind in ("CASE_LAW_CANDIDATE", "STATUTE_UPDATE_CANDIDATE"):
            entry["candidate_type"] = kind
            singles.append(entry)
        else:
            cluster = clusters.setdefault(matched[0], {"rows": [], "term": matched[0]})
            cluster["rows"].append(entry)

    payloads: list[dict[str, Any]] = []

    for e in singles:
        meta = _base_meta(pack, e["matched"], e["source_class"])
        meta["stream"] = e["stream"]
        payloads.append(dict(
            candidate_type=e["candidate_type"],
            label=e["title"][:160],
            summary=e["text"][:300],
            source_domain=_host(e["source_url"] or e["source"]) or None,
            source_url=e["source_url"],
            evidence=[{"source_domain": _host(e["source_url"] or e["source"]),
                       "url": e["source_url"],
                       "note": f"{e['stream']} match: {', '.join(e['matched'][:5])} "
                               f"[{e['source_class']} source]"}],
            meta=meta,
            safe_action_level="OPERATOR_REVIEW_REQUIRED",
            ttl_days=TTL_DAYS,
        ))

    for term, cluster in clusters.items():
        rows_c = cluster["rows"]
        size = len(rows_c)
        best_class = max(rows_c, key=lambda r: SOURCE_QUALITY.get(
            r["source_class"], 0.0))["source_class"]
        joined = " ".join(r["text"] for r in rows_c)
        ctype = classify_candidate_type(joined, cluster_size=size)
        matched_all: list[str] = []
        for r in rows_c:
            for m in r["matched"]:
                if m not in matched_all:
                    matched_all.append(m)
        meta = _base_meta(pack, matched_all, best_class)
        meta["recurrence_count"] = size
        meta["streams"] = sorted({r["stream"] for r in rows_c})
        label = (f"NYC Loft Law explainer: {term}"
                 if ctype == "WEBSITE_CONTENT_CANDIDATE"
                 else f"NYC Loft Law topic: {term}")
        first_url = next((r["source_url"] for r in rows_c if r["source_url"]), None)
        payloads.append(dict(
            candidate_type=ctype,
            label=label[:160],
            summary=(f"{size} recent mention(s) of '{term}' across "
                     f"{len(meta['streams'])} stream(s). "
                     f"{rows_c[0]['title']}")[:300],
            source_domain=_host(first_url or rows_c[0]["source"]) or None,
            source_url=first_url,
            evidence=[{"source_domain": _host(r["source_url"] or r["source"]),
                       "url": r["source_url"],
                       "note": f"{r['stream']}: {r['title'][:120]} "
                               f"[{r['source_class']} source]"}
                      for r in rows_c[:6]],
            meta=meta,
            safe_action_level="OPERATOR_REVIEW_REQUIRED",
            ttl_days=TTL_DAYS,
        ))

    # primary-first ranking, then recurrence — the operator sees the highest
    # quality sourcing at the top and the run cap trims from the bottom.
    payloads.sort(key=lambda p: (-p["meta"]["source_quality"],
                                 -int(p["meta"].get("recurrence_count") or 1)))
    cap = max(1, int(limit))
    if len(payloads) > cap:
        _skip("run_cap")
        payloads = payloads[:cap]
    return payloads


# ── run entry point + lane runner ────────────────────────────────────────────

def run_discovery(*, dry_run: bool = False, limit: int = 25,
                  window_hours: int = WINDOW_HOURS,
                  pack_path: Path | str | None = None) -> dict[str, Any]:
    """Full loft-law pass. Returns the JSON run report; live mode writes
    candidates exclusively through inbox.upsert_candidate (candidates only —
    no promotion, no publishing)."""
    pack = load_pack(pack_path)
    ensure_domain_registered(pack)
    notes: list[str] = []
    skipped: dict[str, int] = {}

    rows = (collect_news_rows(window_hours, pack["terms"], notes)
            + collect_research_rows(window_hours, pack["terms"], notes))
    payloads = build_payloads(rows, pack=pack, limit=limit, skipped=skipped)

    by_type: dict[str, int] = {}
    by_source_class: dict[str, int] = {}
    candidates: list[dict[str, Any]] = []
    upserted = 0
    for p in payloads:
        by_type[p["candidate_type"]] = by_type.get(p["candidate_type"], 0) + 1
        sc = p["meta"]["source_policy_class"]
        by_source_class[sc] = by_source_class.get(sc, 0) + 1
        summary = {"candidate_type": p["candidate_type"], "label": p["label"],
                   "source_policy_class": sc,
                   "matched_terms": p["meta"]["matched_terms"][:5]}
        if not dry_run:
            from . import inbox
            row = inbox.upsert_candidate(actor=ACTOR, **p)
            summary.update({
                "id": row.get("id"), "status": row.get("status"),
                "seen_count": row.get("seen_count"),
                "workspace_id": (row.get("meta_json") or {}).get("workspace_id"),
            })
            upserted += 1
        candidates.append(summary)

    return {
        "mode": "loft_law",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": bool(dry_run),
        "pack": pack["pack"],
        "domain": pack["domain_name"],
        "workspace": pack["workspace"],
        "window_hours": int(window_hours),
        "scanned_rows": len(rows),
        "payloads": len(payloads),
        "would_upsert": len(payloads) if dry_run else None,
        "upserted": upserted,
        "by_type": by_type,
        "by_source_class": by_source_class,
        "skipped_reasons": skipped,
        "notes": notes,
        "candidates": candidates,
    }


def _lane_runner(lane_cfg: dict[str, Any], *, dry_run: bool) -> list[dict[str, Any]]:
    """'legal_domain' worker-pool lane runner — READ-ONLY payload producer.

    The pool owns all writes (gated, candidates-only); this runner just scans
    and builds. Lane cap re-applied downstream by the pool; the pack cap here
    keeps the scan itself bounded."""
    pack = load_pack()
    ensure_domain_registered(pack)
    notes: list[str] = []
    rows = (collect_news_rows(WINDOW_HOURS, pack["terms"], notes)
            + collect_research_rows(WINDOW_HOURS, pack["terms"], notes))
    return build_payloads(rows, pack=pack,
                          limit=int(lane_cfg.get("max_candidates_per_run") or 25))


worker_pool.register_lane_runner("legal_domain", _lane_runner, replace=True)


# test/support hook
def _reset_pack_cache() -> None:
    global _pack_cache
    _pack_cache = None
