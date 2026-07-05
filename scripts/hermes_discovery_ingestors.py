#!/usr/bin/env python3
"""hermes_discovery_ingestors.py — adapters: existing producers → Discovery Inbox.

Converts what today's producers ALREADY emit into inbox candidates. Additive
observation only: no producer is modified, and every producer's existing write
path stays intact — the inbox just watches the same outputs.

  --source  research_sources registry rows written by hermes_source_curation.py
            (web domains in candidate state → SOURCE_CANDIDATE; key-gated /
            dormant connectors → CONNECTOR_CANDIDATE)
  --trend   hermes_directive_hits_staging rows staged by
            hermes_directive_discovery.py / think_tank_prospect_discovery.py,
            grouped per directive → TREND_CANDIDATE (keywords, seed symbols,
            momentum from narrative_strength)
  --ticker  the audit-flagged shape-accepted extraction
            (intel_auto_discovery.extract_tickers_from_text) re-applied over
            recent news + Hermes research text → TICKER_CANDIDATE; real
            validation happens in inbox.upsert_candidate via validate_ticker
  --topic   recurring hermes_research_intelligence topics not yet registered in
            topic_monitor → TOPIC_CANDIDATE

Idempotency comes free from inbox.upsert_candidate (unique candidate_type +
normalized_key → seen_count bump + evidence merge). All DB reads go through
db_adapter._execute — one statement, immediate commit, no held transactions.
Advisory-only: never imports broker modules, never writes producer tables.

Scheduled mode (--scheduled) reads config/hermes_discovery_schedule.json plus
the latest scorecard's do_no_harm recommendation and runs the enabled
ingestors under caps:
  steady  → config caps as-is
  tighten → caps halved + min_recurrence_count raised by 1
  pause   → all non-operator intake skipped (logged once; NO Telegram unless a
            critical intake exception occurs — then ONE throttled send via
            telegram_alert)
Per-domain / per-day caps are enforced from today's candidate counts.
Operator-created (is_operator) candidates are NEVER blocked by caps or pause.
The scheduled run prints a JSON run report {mode, do_no_harm, caps_applied,
by_type_counts, skipped_reasons} and the suggested (NOT installed) cron line.

Usage:
  python3 scripts/hermes_discovery_ingestors.py --run [--source|--trend|--ticker|--topic]
                                                [--limit N] [--dry-run] [--json]
  python3 scripts/hermes_discovery_ingestors.py --scheduled [--dry-run] [--json]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.hermes_discovery import domains, inbox  # noqa: E402

SCHEDULE_CONFIG_PATH = PROJECT_ROOT / "config" / "hermes_discovery_schedule.json"
SCORECARD_PATH = PROJECT_ROOT / "data" / "runtime" / "hermes_discovery_scorecard.json"
ALERT_THROTTLE_PATH = PROJECT_ROOT / "data" / "runtime" / "hermes_discovery_sched_alert.json"
ALERT_THROTTLE_SECONDS = 6 * 3600  # at most one critical Telegram per 6h

SUGGESTED_CRON = (
    f"0 */2 * * * cd {PROJECT_ROOT} && flock -n /tmp/hermes_discovery_ingest.lock "
    f".venv/bin/python scripts/hermes_discovery_ingestors.py --scheduled --json "
    f">> logs/hermes_discovery_ingest.log 2>&1"
)

# risk levels counted against max_legal_tax_candidates_per_day
_SENSITIVE_RISK_LEVELS = frozenset({"tax", "legal", "planning", "medical"})


def _rows(sql: str, params=None) -> list[dict[str, Any]]:
    from db_adapter import _execute
    return [dict(r) for r in (_execute(sql, params, fetch="all") or [])]


def _clamp01(v) -> float:
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return 0.5


def _upsert_all(payloads: list[dict[str, Any]], *, actor: str,
                dry_run: bool,
                gate: Callable[[dict[str, Any]], tuple[bool, str | None]] | None = None,
                ) -> dict[str, Any]:
    """Shared upsert loop: dry-run lists the would-be candidates, live writes.

    `gate` (scheduled mode) is called per payload BEFORE any write; a
    (False, reason) verdict skips the payload and tallies skipped_reasons.
    The gate itself never blocks operator candidates (enforced in the gate).
    """
    out = {"scanned": len(payloads), "upserted": 0, "skipped": 0,
           "dry_run": bool(dry_run), "candidates": [],
           "skipped_reasons": defaultdict(int)}
    for p in payloads:
        summary = {"candidate_type": p["candidate_type"], "label": p["label"],
                   "source_domain": p.get("source_domain")}
        if gate is not None:
            allowed, reason = gate(p)
            if not allowed:
                out["skipped"] += 1
                out["skipped_reasons"][reason or "gated"] += 1
                continue
        if dry_run:
            out["candidates"].append(summary)
            continue
        row = inbox.upsert_candidate(actor=actor, **p)
        summary.update({"id": row["id"], "status": row["status"],
                        "seen_count": row["seen_count"],
                        "score": float(row["discovery_score"]) if row.get("discovery_score") is not None else None})
        out["candidates"].append(summary)
        out["upserted"] += 1
    out["skipped_reasons"] = dict(out["skipped_reasons"])
    return out


# ── (a) source curation registry → SOURCE / CONNECTOR candidates ─────────────

def ingest_sources(limit: int = 50, dry_run: bool = False,
                   gate: Callable | None = None) -> dict[str, Any]:
    """research_sources rows (the hermes_source_curation.py output registry).

    Web domains still in candidate state (not active, not retired/rejected)
    become SOURCE_CANDIDATEs carrying credibility/specialty/active state.
    Non-web connector rows that are dormant / key-gated become
    CONNECTOR_CANDIDATEs (they need an operator decision + a key to go live).
    """
    # Candidate-state rows only, filtered in SQL (the registry is dominated by
    # active/ruled-out rows, so a python-side filter over a top-N slice sees none):
    #   web:   inactive and not already ruled out by curation (retired/rejected)
    #   other: inactive key-gated/dormant connectors awaiting a key + decision
    rows = _rows(
        """SELECT id, source_type, source_name, source_url, credibility_score,
                  specialty, active, notes
           FROM research_sources
           WHERE active = FALSE AND (
                 (source_type = 'web'
                  AND COALESCE(notes, '') NOT ILIKE '%%retired%%'
                  AND COALESCE(notes, '') NOT ILIKE '%%rejected%%')
              OR (source_type <> 'web'
                  AND (COALESCE(notes, '') ILIKE '%%key%%'
                       OR COALESCE(notes, '') ILIKE '%%dormant%%')))
           ORDER BY credibility_score DESC NULLS LAST, id DESC
           LIMIT %s""", (max(1, int(limit)) * 2,))
    payloads: list[dict[str, Any]] = []
    for r in rows:
        if len(payloads) >= limit:
            break
        notes = (r.get("notes") or "")
        low_notes = notes.lower()
        specialty = r.get("specialty") or []
        meta = {"registry_id": r["id"], "source_type": r["source_type"],
                "credibility": float(r.get("credibility_score") or 0),
                "specialty": list(specialty),
                "active": bool(r.get("active")),
                "registry_state": "active" if r.get("active") else "dormant"}
        if r["source_type"] == "web":
            payloads.append(dict(
                candidate_type="SOURCE_CANDIDATE",
                label=r["source_name"],
                summary=notes[:400] or None,
                source_domain=r["source_name"],
                source_url=r.get("source_url"),
                evidence=[{"source_domain": r["source_name"],
                           "note": f"research_sources registry: {notes[:160]}"}],
                meta=meta,
                signals={"source_quality": _clamp01(float(r.get("credibility_score") or 0) / 100.0)},
            ))
        else:
            meta["key_gated"] = ("key" in low_notes) or ("dormant" in low_notes)
            payloads.append(dict(
                candidate_type="CONNECTOR_CANDIDATE",
                label=r["source_name"],
                summary=notes[:400] or None,
                source_domain=None,
                source_url=r.get("source_url"),
                evidence=[{"note": f"connector registry ({r['source_type']}): {notes[:160]}"}],
                meta=meta,
            ))
    return {"type": "source", **_upsert_all(payloads, actor="ingestor:source_curation",
                                            dry_run=dry_run, gate=gate)}


# ── (b) directive/think-tank staging → TREND candidates ──────────────────────

def ingest_trends(limit: int = 25, dry_run: bool = False,
                  days: int = 14, gate: Callable | None = None) -> dict[str, Any]:
    """hermes_directive_hits_staging (output of hermes_directive_discovery.py +
    think_tank_prospect_discovery.py) grouped per directive → TREND_CANDIDATE.

    Momentum = avg narrative_strength of recent staged hits (signals dict →
    scoring's trend_momentum component). meta.existing_directive_id lets
    promote_watch_directive reuse the directive instead of duplicating it.
    """
    rows = _rows(
        f"""SELECT d.id AS directive_id, d.label, d.spec,
                   count(*) AS hits,
                   avg(s.narrative_strength) AS momentum,
                   array_agg(DISTINCT s.symbol) AS symbols,
                   jsonb_agg(jsonb_build_object(
                       'symbol', s.symbol,
                       'thesis', LEFT(COALESCE(s.thesis, ''), 120),
                       'producer', s.source_detail->>'producer')
                       ORDER BY s.proposed_at DESC) AS evidence
            FROM hermes_directive_hits_staging s
            JOIN watch_directives d ON d.id = s.directive_id
            WHERE s.proposed_at > now() - interval '{int(days)} days'
            GROUP BY d.id, d.label, d.spec
            ORDER BY count(*) DESC LIMIT %s""", (max(1, int(limit)),))
    payloads: list[dict[str, Any]] = []
    for r in rows:
        spec = r.get("spec") or {}
        if isinstance(spec, str):
            try:
                spec = json.loads(spec)
            except Exception:
                spec = {}
        keywords = [k for k in (spec.get("keywords") or []) if k]
        evidence = list(r.get("evidence") or [])[:10]
        producers = sorted({e.get("producer") for e in evidence if e.get("producer")})
        payloads.append(dict(
            candidate_type="TREND_CANDIDATE",
            label=r["label"],
            summary=(f"{r['hits']} staged hit(s) in {days}d from "
                     f"{', '.join(producers) or 'hermes staging'}"),
            evidence=evidence,
            seed_symbols=[s for s in (r.get("symbols") or []) if s][:12],
            meta={"existing_directive_id": r["directive_id"],
                  "keywords": keywords[:10],
                  "producers": producers,
                  "staged_hits": int(r["hits"])},
            signals={"trend_momentum": _clamp01(r.get("momentum"))},
        ))
    return {"type": "trend", **_upsert_all(payloads, actor="ingestor:directive_staging",
                                           dry_run=dry_run, gate=gate)}


# ── (c) shape-accepted ticker extraction → TICKER candidates ─────────────────

def ingest_tickers(limit: int = 25, dry_run: bool = False, days: int = 2,
                   min_mentions: int = 2, gate: Callable | None = None) -> dict[str, Any]:
    """Re-applies the audit-flagged shape-accepted extractor
    (intel_auto_discovery.extract_tickers_from_text: regex + blacklist, NO
    existence check) over recent news + Hermes research text. Candidates flow
    through inbox.upsert_candidate, where validate_ticker supplies the real
    symbol_profiles verdict — fabricated tokens land in NEEDS_VALIDATION
    instead of anyone's watchlist.

    Reads via db_adapter (the producer's own psycopg2/.env connection helper is
    deliberately not used); the producer's direct-add path is left untouched.
    """
    from intel_auto_discovery import extract_tickers_from_text

    known: set[str] = set()
    for sql in ("SELECT DISTINCT symbol FROM ticker_strategy_classifications WHERE active = TRUE",
                "SELECT DISTINCT symbol FROM watchlist_items"):
        known.update((r.get("symbol") or "").upper() for r in _rows(sql))

    texts = _rows(
        f"""SELECT COALESCE(title, '') || ' ' || COALESCE(summary, '') AS text,
                   COALESCE(source, 'news') AS source
            FROM news_articles WHERE created_at > now() - interval '{int(days)} days'
            ORDER BY created_at DESC LIMIT 500""")
    texts += _rows(
        f"""SELECT COALESCE(topic, '') || ' ' || COALESCE(summary, '') AS text,
                   COALESCE(source, 'hermes_research') AS source
            FROM hermes_research_intelligence
            WHERE created_at > now() - interval '{int(days)} days'
            ORDER BY created_at DESC LIMIT 300""")

    mentions: dict[str, int] = defaultdict(int)
    sources: dict[str, set[str]] = defaultdict(set)
    snippets: dict[str, str] = {}
    for row in texts:
        text = row.get("text") or ""
        for sym in extract_tickers_from_text(text):
            sym = sym.upper()
            if sym in known:
                continue
            mentions[sym] += 1
            sources[sym].add(row.get("source") or "unknown")
            snippets.setdefault(sym, text.strip()[:160])

    ranked = sorted(mentions.items(), key=lambda kv: -kv[1])
    payloads: list[dict[str, Any]] = []
    for sym, n in ranked:
        if n < max(1, int(min_mentions)):
            continue
        if len(payloads) >= limit:
            break
        payloads.append(dict(
            candidate_type="TICKER_CANDIDATE",
            label=sym,
            summary=f"{n} mention(s) in {days}d intel/news: {snippets.get(sym, '')}",
            evidence=[{"source_domain": s, "note": f"mentioned via {s}"}
                      for s in sorted(sources[sym])[:6]],
            meta={"mentions": n,
                  "extraction": "intel_auto_discovery.extract_tickers_from_text (shape-accepted)"},
        ))
    return {"type": "ticker", **_upsert_all(payloads, actor="ingestor:ticker_extraction",
                                            dry_run=dry_run, gate=gate)}


# ── (d) recurring research topics → TOPIC candidates ─────────────────────────

def ingest_topics(limit: int = 25, dry_run: bool = False,
                  days: int = 14, gate: Callable | None = None) -> dict[str, Any]:
    """Recurring hermes_research_intelligence topics (>= 2 rows in the window)
    that are not yet in topic_monitor → TOPIC_CANDIDATE."""
    registered = {(r.get("display_name") or "").strip().lower()
                  for r in _rows("SELECT display_name FROM topic_monitor")}
    rows = _rows(
        f"""SELECT topic, count(*) AS n, max(created_at) AS last_seen,
                   array_agg(DISTINCT COALESCE(source, 'hermes')) AS sources,
                   max(COALESCE(summary, '')) AS sample_summary
            FROM hermes_research_intelligence
            WHERE topic IS NOT NULL AND length(topic) > 6
              AND created_at > now() - interval '{int(days)} days'
            GROUP BY topic HAVING count(*) >= 2
            ORDER BY count(*) DESC LIMIT %s""", (max(1, int(limit)) * 2,))
    payloads: list[dict[str, Any]] = []
    for r in rows:
        if len(payloads) >= limit:
            break
        topic = (r.get("topic") or "").strip()
        if not topic or topic.lower() in registered:
            continue
        payloads.append(dict(
            candidate_type="TOPIC_CANDIDATE",
            label=topic[:120],
            summary=(r.get("sample_summary") or "")[:300] or None,
            evidence=[{"source_domain": s, "note": f"{r['n']} research rows in {days}d"}
                      for s in (r.get("sources") or [])[:5]],
            meta={"research_rows": int(r["n"]),
                  "last_seen": str(r.get("last_seen")),
                  "keywords": [topic]},
        ))
    return {"type": "topic", **_upsert_all(payloads, actor="ingestor:research_topics",
                                           dry_run=dry_run, gate=gate)}


# ── scheduled mode (spec Parts C + L) ────────────────────────────────────────

def load_schedule_config(path: Path | str | None = None) -> dict[str, Any]:
    """Load config/hermes_discovery_schedule.json. Missing/broken → raises
    (scheduled intake fails closed rather than running uncapped)."""
    p = Path(path) if path else SCHEDULE_CONFIG_PATH
    return json.loads(p.read_text(encoding="utf-8"))


def load_scorecard_do_no_harm(path: Path | str | None = None) -> str:
    """Latest scorecard's do_no_harm recommendation; missing scorecard →
    'steady' (the scorecard is advisory; absence must not halt intake)."""
    p = Path(path) if path else SCORECARD_PATH
    try:
        card = json.loads(p.read_text(encoding="utf-8"))
        rec = str(((card.get("do_no_harm") or {}).get("recommendation")) or "steady").lower()
        return rec if rec in ("steady", "tighten", "pause") else "steady"
    except Exception:
        return "steady"


def effective_caps(cfg: dict[str, Any], do_no_harm: str) -> dict[str, Any]:
    """Pure cap arithmetic per do-no-harm state.

    steady  → config caps unchanged
    tighten → per-run / per-domain / ticker / legal-tax caps halved (floor 1),
              min_recurrence_count raised by 1
    pause   → paused=True (all non-operator intake skipped)
    """
    def _i(key, default):
        try:
            return max(0, int(cfg.get(key, default)))
        except (TypeError, ValueError):
            return default

    caps = {
        "do_no_harm": do_no_harm,
        "max_candidates_per_run": _i("max_candidates_per_run", 25),
        "max_candidates_per_domain_per_day": _i("max_candidates_per_domain_per_day", 10),
        "max_ticker_candidates_per_day": _i("max_ticker_candidates_per_day", 10),
        "max_legal_tax_candidates_per_day": _i("max_legal_tax_candidates_per_day", 5),
        "min_recurrence_count": _i("min_recurrence_count", 2),
        "paused": bool(cfg.get("paused")) or not bool(cfg.get("enabled", True)),
        "pause_reason": cfg.get("pause_reason"),
    }
    if caps["paused"] and not caps["pause_reason"]:
        caps["pause_reason"] = ("config paused" if cfg.get("paused")
                                else "config disabled" if not cfg.get("enabled", True)
                                else None)
    if do_no_harm == "tighten":
        for key in ("max_candidates_per_run", "max_candidates_per_domain_per_day",
                    "max_ticker_candidates_per_day", "max_legal_tax_candidates_per_day"):
            caps[key] = max(1, caps[key] // 2)
        caps["min_recurrence_count"] += 1
    elif do_no_harm == "pause" and cfg.get("do_no_harm_pause_respected", True):
        caps["paused"] = True
        caps["pause_reason"] = caps["pause_reason"] or "do_no_harm=pause (scorecard)"
    return caps


def _domain_counts_today() -> dict[str, Any]:
    """Today's intake counts (new rows only) grouped by research domain +
    candidate type — one statement, no held transaction."""
    counts = {"by_domain": defaultdict(int), "ticker": 0, "legal_tax": 0}
    try:
        rows = _rows(
            """SELECT COALESCE(meta_json->>'research_domain', 'custom') AS domain,
                      COALESCE(meta_json->>'domain_risk_level', '') AS risk_level,
                      candidate_type, count(*) AS n
               FROM hermes_discovery_candidates
               WHERE created_at >= date_trunc('day', now())
               GROUP BY 1, 2, 3""")
    except Exception:
        rows = []
    for r in rows:
        n = int(r.get("n") or 0)
        counts["by_domain"][r.get("domain") or "custom"] += n
        if r.get("candidate_type") == "TICKER_CANDIDATE":
            counts["ticker"] += n
        if (r.get("risk_level") or "") in _SENSITIVE_RISK_LEVELS:
            counts["legal_tax"] += n
    counts["by_domain"] = dict(counts["by_domain"])
    return counts


def make_intake_gate(caps: dict[str, Any], counts_today: dict[str, Any],
                     skipped_reasons: dict[str, int]) -> Callable[[dict], tuple[bool, str | None]]:
    """Build the per-payload gate for scheduled runs.

    Enforces (in order): pause, per-run cap, per-domain/day cap, ticker/day
    cap, legal-tax/day cap. Operator-created payloads are NEVER blocked.
    Counters include both today's DB counts and this run's admissions.
    """
    run_total = {"n": 0}
    by_domain = defaultdict(int, counts_today.get("by_domain") or {})
    counters = {"ticker": int(counts_today.get("ticker") or 0),
                "legal_tax": int(counts_today.get("legal_tax") or 0)}

    def _deny(reason: str) -> tuple[bool, str]:
        skipped_reasons[reason] = skipped_reasons.get(reason, 0) + 1
        return False, reason

    def gate(payload: dict[str, Any]) -> tuple[bool, str | None]:
        if payload.get("is_operator"):
            return True, None  # operator intake is never blocked
        if caps.get("paused"):
            return _deny("paused")
        if run_total["n"] >= caps["max_candidates_per_run"]:
            return _deny("run_cap")
        try:
            domain = domains.classify_domain(payload)
            risk = domains.domain_policy(domain)["risk_level"]
        except Exception:
            return _deny("domain_classification_failed")
        if by_domain[domain] >= caps["max_candidates_per_domain_per_day"]:
            return _deny(f"domain_cap:{domain}")
        is_ticker = (payload.get("candidate_type") or "").upper() == "TICKER_CANDIDATE"
        if is_ticker and counters["ticker"] >= caps["max_ticker_candidates_per_day"]:
            return _deny("ticker_cap")
        sensitive = risk in _SENSITIVE_RISK_LEVELS
        if sensitive and counters["legal_tax"] >= caps["max_legal_tax_candidates_per_day"]:
            return _deny("legal_tax_cap")
        run_total["n"] += 1
        by_domain[domain] += 1
        if is_ticker:
            counters["ticker"] += 1
        if sensitive:
            counters["legal_tax"] += 1
        return True, None

    return gate


def _critical_alert(message: str, *, dry_run: bool) -> bool:
    """ONE throttled Telegram for a critical scheduled-intake exception.
    Never used for pause/caps (those are silent by design); throttled to one
    send per ALERT_THROTTLE_SECONDS via a state file."""
    if dry_run:
        return False
    now = time.time()
    try:
        state = json.loads(ALERT_THROTTLE_PATH.read_text(encoding="utf-8"))
        if now - float(state.get("last_sent", 0)) < ALERT_THROTTLE_SECONDS:
            return False
    except Exception:
        pass
    try:
        from telegram_alert import send_telegram
        ok = send_telegram(f"[hermes-discovery] CRITICAL scheduled intake exception: "
                           f"{message[:300]}")
        ALERT_THROTTLE_PATH.parent.mkdir(parents=True, exist_ok=True)
        ALERT_THROTTLE_PATH.write_text(json.dumps({"last_sent": now,
                                                   "message": message[:300]}),
                                       encoding="utf-8")
        return bool(ok)
    except Exception:
        return False


def run_scheduled(*, dry_run: bool = False,
                  config_path: Path | str | None = None,
                  scorecard_path: Path | str | None = None) -> dict[str, Any]:
    """--scheduled entry point: config + do-no-harm-capped run of the enabled
    ingestors. Returns the JSON run report (spec Part L)."""
    report: dict[str, Any] = {
        "mode": "scheduled",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": bool(dry_run),
        "do_no_harm": None,
        "caps_applied": {},
        "by_type_counts": {},
        "skipped_reasons": {},
        "suggested_cron": SUGGESTED_CRON,
    }
    try:
        cfg = load_schedule_config(config_path)
        dnh = (load_scorecard_do_no_harm(scorecard_path)
               if cfg.get("do_no_harm_pause_respected", True) else "steady")
        caps = effective_caps(cfg, dnh)
    except Exception as e:  # broken config = critical: fail closed + one throttled alert
        report["error"] = f"schedule config load failed: {e}"[:300]
        report["telegram_sent"] = _critical_alert(report["error"], dry_run=dry_run)
        return report

    report["do_no_harm"] = dnh
    report["caps_applied"] = caps

    if caps["paused"]:
        # log once, skip ALL non-operator intake (our ingestors are all
        # non-operator), NO Telegram — pause is a normal, quiet state.
        print(f"[hermes-discovery] scheduled intake paused "
              f"({caps.get('pause_reason') or dnh}); skipping non-operator intake",
              file=sys.stderr)
        report["skipped_reasons"] = {"paused": 1}
        return report

    skipped: dict[str, int] = {}
    gate = make_intake_gate(caps, _domain_counts_today(), skipped)

    enabled = {name: bool(cfg.get(f"{name}_enabled", True)) for name in INGESTORS}
    kwargs_by_type: dict[str, dict[str, Any]] = {
        "ticker": {"min_mentions": caps["min_recurrence_count"]},
    }
    critical_errors: list[str] = []
    for name, fn in INGESTORS.items():
        if not enabled[name]:
            report["by_type_counts"][name] = {"enabled": False}
            continue
        try:
            res = fn(limit=caps["max_candidates_per_run"], dry_run=dry_run,
                     gate=gate, **kwargs_by_type.get(name, {}))
            report["by_type_counts"][name] = {
                "scanned": res.get("scanned", 0),
                "upserted": res.get("upserted", 0),
                "skipped": res.get("skipped", 0),
            }
        except Exception as e:  # one broken producer never blocks the others
            report["by_type_counts"][name] = {"error": str(e)[:200]}
            critical_errors.append(f"{name}: {e}")

    report["skipped_reasons"] = skipped
    if critical_errors and len(critical_errors) == sum(enabled.values()):
        # EVERY enabled ingestor failed → critical intake exception:
        # one throttled Telegram, nothing else.
        report["telegram_sent"] = _critical_alert(
            "; ".join(critical_errors)[:300], dry_run=dry_run)
    return report


# ── CLI ──────────────────────────────────────────────────────────────────────

INGESTORS = {"source": ingest_sources, "trend": ingest_trends,
             "ticker": ingest_tickers, "topic": ingest_topics}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="store_true", help="run the selected ingestors")
    ap.add_argument("--scheduled", action="store_true",
                    help="scheduled mode: config caps + scorecard do-no-harm")
    for name in ("source", "trend", "ticker", "topic"):
        ap.add_argument(f"--{name}", action="store_true",
                        help=f"run the {name} ingestor (default: all)")
    ap.add_argument("--limit", type=int, default=25, help="max candidates per ingestor")
    ap.add_argument("--dry-run", action="store_true",
                    help="list would-be candidates without writing the inbox")
    ap.add_argument("--json", action="store_true", help="JSON output")
    args = ap.parse_args()

    if args.scheduled:
        report = run_scheduled(dry_run=args.dry_run)
        print(json.dumps(report, indent=2, default=str))
        # suggested only — deliberately NOT installed by this script
        print(f"[hermes-discovery] suggested cron (not installed): {SUGGESTED_CRON}",
              file=sys.stderr)
        return 1 if report.get("error") else 0

    if not args.run:
        ap.print_help()
        return 2

    selected = [n for n in INGESTORS if getattr(args, n)] or list(INGESTORS)
    report: dict[str, Any] = {"dry_run": bool(args.dry_run), "results": {}}
    for name in selected:
        try:
            report["results"][name] = INGESTORS[name](limit=args.limit,
                                                      dry_run=args.dry_run)
        except Exception as e:  # one broken producer never blocks the others
            report["results"][name] = {"type": name, "error": str(e)[:200]}
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        for name, res in report["results"].items():
            if res.get("error"):
                print(f"[{name}] ERROR: {res['error']}")
                continue
            print(f"[{name}] scanned={res['scanned']} upserted={res['upserted']} "
                  f"dry_run={res['dry_run']}")
            for c in res["candidates"][:10]:
                extra = f" #{c['id']} {c['status']}" if "id" in c else ""
                print(f"    {c['candidate_type']} {c['label']!r}{extra}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
