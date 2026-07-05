"""Universal Research Discovery Layer — tag-lift discovery (spec Part F).

Reads OUTCOME evidence (which research tags/sources actually produced useful,
graded outcomes) and folds it back into discovery as (a) bounded score-weight
deltas on existing candidates and (b) — with enough useful outcomes — new
TREND/TOPIC candidates surfacing an outperforming tag.

HARD RULES (tested):
  * advisory candidates + bounded weight deltas ONLY — never promotes, never
    transitions status, never touches trading thresholds or execution (no
    broker/execution/promotion imports anywhere in this module);
  * every weight delta flows through feedback.apply_weight_delta, per-run
    delta clamped to ±MAX_RUN_DELTA (0.1) and cumulatively hard-bounded to
    ±feedback.MAX_ABS_DELTA (0.3) — tag lift tilts scoring, never dominates;
  * candidate creation gate: useful_outcome_count >= tag_lift_min_outcomes
    (config, default 5); dedupe against active directives/topics (covered
    set) and against existing candidates (skip + upsert idempotency).

Inputs — ALL read defensively; anything missing is skipped with a note in the
run report, never an exception:
  state/hermes/outcome_bus.json                 current by_tag stats (lift,
      precision, n) — prior window comes from the newest DIFFERENT run in
      state/hermes/outcome_bus_history/
  data/runtime/hermes_discovery_outcome_feed.json   optional per-tag/source
      useful/false outcome counts (by_tag / by_source maps, or an
      outcomes[] event list)
  hermes_discovery_feedback (DB)                operator feedback joined to
      candidates → per-source/per-trend useful/false counts, current vs
      prior WINDOW_DAYS
  data/runtime/hermes_learning_scorecard.json + hermes_discovery_scorecard.json
      context only (hit rates surfaced in the report)

lift_ratio = current_lift / prior_lift (epsilon-guarded, clamped to
[0, LIFT_RATIO_CAP]); no prior window → lift_ratio None + note.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import dedupe, feedback, inbox
from .entity_spikes import _payload_domain, covered_keys

PROJECT_ROOT = Path(__file__).resolve().parents[3]
BUS_PATH = Path(os.getenv("TRADE_AI_OUTCOME_BUS_JSON")
                or PROJECT_ROOT / "state" / "hermes" / "outcome_bus.json")
BUS_HISTORY_DIR = Path(os.getenv("TRADE_AI_OUTCOME_BUS_HISTORY_DIR")
                       or PROJECT_ROOT / "state" / "hermes" / "outcome_bus_history")
FEED_PATH = Path(os.getenv("TRADE_AI_DISCOVERY_OUTCOME_FEED_JSON")
                 or PROJECT_ROOT / "data" / "runtime" / "hermes_discovery_outcome_feed.json")
LEARNING_SCORECARD_PATH = PROJECT_ROOT / "data" / "runtime" / "hermes_learning_scorecard.json"
DISCOVERY_SCORECARD_PATH = PROJECT_ROOT / "data" / "runtime" / "hermes_discovery_scorecard.json"
SCHEDULE_CONFIG_PATH = Path(os.getenv("HERMES_DISCOVERY_SCHEDULE_JSON")
                            or PROJECT_ROOT / "config" / "hermes_discovery_schedule.json")

TAG_LIFT_VERSION = "tag-lift-v1"
PRODUCER = "tag_lift_discovery"
ACTOR = "ingestor:tag_lift"

WINDOW_DAYS = 7            # feedback current/prior window
LIFT_RATIO_CAP = 10.0
DELTA_PER_LIFT = 0.05      # weight delta per 1.0 of (lift_ratio - 1)
DELTA_PER_OUTCOME = 0.02   # weight delta per net useful outcome
MAX_RUN_DELTA = 0.10       # per-run clamp; feedback.MAX_ABS_DELTA caps cumulative
MIN_DELTA = 0.005          # below this a delta is noise — skip
MIN_CREATE_LIFT_RATIO = 1.2  # tag must actually be lifting to justify a candidate
TAG_TTL_DAYS = 30

_USEFUL_TYPES = frozenset({"useful", "approved"})
_FALSE_TYPES = frozenset({"noise", "rejected", "blocked"})


# ── plumbing ─────────────────────────────────────────────────────────────────

def _execute(sql: str, params=None, fetch: str | None = None):
    """Single monkeypatchable DB seam — delegates to db_adapter._execute."""
    from db_adapter import _execute as _db_execute
    return _db_execute(sql, params, fetch=fetch)


def _rows(sql: str, params=None) -> list[dict[str, Any]]:
    return [dict(r) for r in (_execute(sql, params, fetch="all") or [])]


def _read_json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


def _clamp_run_delta(v: float) -> float:
    """Per-run clamp, then the absolute hard bound (belt and braces —
    apply_weight_delta clamps the cumulative value again)."""
    v = max(-MAX_RUN_DELTA, min(MAX_RUN_DELTA, float(v)))
    return max(-feedback.MAX_ABS_DELTA, min(feedback.MAX_ABS_DELTA, v))


def load_tag_lift_config(path: Path | str | None = None) -> dict[str, Any]:
    p = Path(path) if path else SCHEDULE_CONFIG_PATH
    cfg: dict[str, Any] = {}
    try:
        cfg = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(cfg, dict):
            cfg = {}
    except Exception:
        cfg = {}

    def _i(key: str, default: int) -> int:
        try:
            return max(1, int(cfg.get(key, default)))
        except (TypeError, ValueError):
            return default

    return {
        "tag_lift_min_outcomes": _i("tag_lift_min_outcomes", 5),
        "max_candidates_per_run": _i("max_candidates_per_run", 25),
        "tag_lift_enabled": bool(cfg.get("tag_lift_enabled", False)),
    }


# ── defensive input loaders ──────────────────────────────────────────────────

def load_outcome_bus(path: Path | str | None = None,
                     notes: list[str] | None = None) -> dict[str, Any] | None:
    data = _read_json(Path(path) if path else BUS_PATH)
    if not isinstance(data, dict) or not isinstance(data.get("by_tag"), dict):
        if notes is not None:
            notes.append("outcome_bus.json missing/unreadable — bus stream skipped")
        return None
    return data


def load_prior_outcome_bus(current_run_id: str | None,
                           history_dir: Path | str | None = None,
                           notes: list[str] | None = None) -> dict[str, Any] | None:
    """Newest history snapshot with a DIFFERENT run_id — the prior window."""
    d = Path(history_dir) if history_dir else BUS_HISTORY_DIR
    try:
        files = sorted(d.glob("outcome_bus_*.json"), reverse=True)
    except Exception:
        files = []
    for f in files:
        data = _read_json(f)
        if not isinstance(data, dict) or not isinstance(data.get("by_tag"), dict):
            continue
        if current_run_id and data.get("run_id") == current_run_id:
            continue
        return data
    if notes is not None:
        notes.append("no prior outcome_bus snapshot — lift_ratio unavailable for bus tags")
    return None


def load_outcome_feed(path: Path | str | None = None,
                      notes: list[str] | None = None) -> dict[str, dict[str, dict[str, int]]]:
    """Normalize the optional discovery outcome feed to
    {"by_tag": {tag: {"useful": n, "false": n}}, "by_source": {...}}.

    Accepted shapes: by_tag/by_source maps with useful/false (or
    useful_outcome_count/false_outcome_count) ints, or an outcomes[] event
    list with {tag|source_domain, useful: bool}. Missing/foreign shapes →
    empty maps + a note.
    """
    out: dict[str, dict[str, dict[str, int]]] = {"by_tag": {}, "by_source": {}}
    data = _read_json(Path(path) if path else FEED_PATH)
    if not isinstance(data, dict):
        if notes is not None:
            notes.append("hermes_discovery_outcome_feed.json missing — feed stream skipped")
        return out

    def _counts(v: Any) -> dict[str, int] | None:
        if not isinstance(v, dict):
            return None
        try:
            return {"useful": int(v.get("useful", v.get("useful_outcome_count", 0)) or 0),
                    "false": int(v.get("false", v.get("false_outcome_count", 0)) or 0)}
        except (TypeError, ValueError):
            return None

    for bucket, key in (("by_tag", "by_tag"), ("by_source", "by_source")):
        src = data.get(key)
        if isinstance(src, dict):
            for name, v in src.items():
                c = _counts(v)
                if c and str(name).strip():
                    out[bucket][str(name).strip().lower()] = c
    for ev in (data.get("outcomes") or []) if isinstance(data.get("outcomes"), list) else []:
        if not isinstance(ev, dict):
            continue
        slot = "useful" if ev.get("useful") else "false"
        for bucket, field in (("by_tag", "tag"), ("by_source", "source_domain")):
            name = str(ev.get(field) or "").strip().lower()
            if name:
                entry = out[bucket].setdefault(name, {"useful": 0, "false": 0})
                entry[slot] += 1
    return out


def fetch_feedback_counts(window_days: int = WINDOW_DAYS,
                          notes: list[str] | None = None) -> dict[str, dict[tuple[str, str], dict[str, int]]]:
    """hermes_discovery_feedback joined to candidates → per-key useful/false
    counts for the current and prior windows. Keys: ("source", domain) and
    ("trend", normalized_key). DB trouble → empty + note."""
    d = max(1, int(window_days))
    out: dict[str, dict[tuple[str, str], dict[str, int]]] = {"current": {}, "prior": {}}
    windows = {
        "current": f"f.created_at > now() - interval '{d} days'",
        "prior": (f"f.created_at <= now() - interval '{d} days' "
                  f"AND f.created_at > now() - interval '{2 * d} days'"),
    }
    for window, clause in windows.items():
        try:
            rows = _rows(
                f"""SELECT c.candidate_type, c.normalized_key, c.source_domain,
                           f.feedback_type, count(*) AS n
                    FROM hermes_discovery_feedback f
                    JOIN hermes_discovery_candidates c ON c.id = f.candidate_id
                    WHERE {clause}
                    GROUP BY 1, 2, 3, 4""")
        except Exception as e:
            if notes is not None:
                notes.append(f"hermes_discovery_feedback unavailable ({window}): {e}")
            continue
        for r in rows:
            ftype = str(r.get("feedback_type") or "").lower()
            slot = ("useful" if ftype in _USEFUL_TYPES
                    else "false" if ftype in _FALSE_TYPES else None)
            if slot is None:
                continue
            n = int(r.get("n") or 0)
            keys = []
            if r.get("source_domain"):
                keys.append(("source", str(r["source_domain"]).lower()))
            if r.get("candidate_type") == "TREND_CANDIDATE" and r.get("normalized_key"):
                keys.append(("trend", str(r["normalized_key"]).lower()))
            for key in keys:
                entry = out[window].setdefault(key, {"useful": 0, "false": 0})
                entry[slot] += n
        # noqa: one statement per _execute call; loop issues 2 statements total
    return out


def load_scorecard_context() -> dict[str, Any]:
    """Read-only hit-rate context from the learning + discovery scorecards."""
    ctx: dict[str, Any] = {}
    learning = _read_json(LEARNING_SCORECARD_PATH)
    if isinstance(learning, dict):
        ctx["learning_outcome_hit_rate"] = learning.get("outcome_hit_rate")
        ctx["learning_useful_research_hit_rate"] = learning.get("useful_research_hit_rate")
    else:
        ctx["learning_scorecard"] = "missing"
    discovery = _read_json(DISCOVERY_SCORECARD_PATH)
    if isinstance(discovery, dict):
        ctx["discovery_do_no_harm"] = (discovery.get("do_no_harm") or {}).get("recommendation")
    else:
        ctx["discovery_scorecard"] = "missing"
    return ctx


# ── pure computation core (unit-testable without DB/files) ───────────────────

def compute_tag_lift(current_bus: dict[str, Any] | None,
                     prior_bus: dict[str, Any] | None,
                     feed: dict[str, dict[str, dict[str, int]]] | None = None,
                     ) -> list[dict[str, Any]]:
    """Per-tag lift entries (tag_lift_json rows).

    Bus tags: lift_ratio = current.lift / prior.lift (epsilon-guarded, capped);
    useful_outcome_count ≈ round(n * precision) — the graded-useful share of
    the tag's outcome sample. Feed counts overlay/extend the bus tags.
    """
    entries: dict[str, dict[str, Any]] = {}
    eps = 1e-6

    cur_tags = (current_bus or {}).get("by_tag") or {}
    prior_tags = (prior_bus or {}).get("by_tag") or {}
    for tag, cur in cur_tags.items():
        if not isinstance(cur, dict):
            continue
        tag_l = str(tag).strip().lower()
        n = int(cur.get("n") or 0)
        precision = cur.get("precision")
        useful = int(round(n * float(precision))) if precision is not None else 0
        prior = prior_tags.get(tag) if isinstance(prior_tags.get(tag), dict) else None
        lift_ratio, notes = None, []
        if prior is not None and cur.get("lift") is not None and prior.get("lift") is not None:
            lift_ratio = round(min(LIFT_RATIO_CAP,
                                   max(0.0, (float(cur["lift"]) + eps)
                                       / (float(prior["lift"]) + eps))), 4)
        else:
            notes.append("no_prior_window")
        entries[tag_l] = {
            "version": TAG_LIFT_VERSION,
            "tag": tag_l,
            "normalized_key": dedupe.normalize_key(tag_l),
            "stream": "outcome_bus",
            "current": {"n": n, "lift": cur.get("lift"), "precision": precision},
            "prior": ({"n": int(prior.get("n") or 0), "lift": prior.get("lift"),
                       "precision": prior.get("precision")} if prior else None),
            "lift_ratio": lift_ratio,
            "useful_outcome_count": useful,
            "false_outcome_count": max(0, n - useful),
            "flagged": bool(cur.get("flagged")),
            "notes": notes,
        }

    for tag, counts in ((feed or {}).get("by_tag") or {}).items():
        tag_l = str(tag).strip().lower()
        entry = entries.get(tag_l)
        if entry is None:
            entry = entries[tag_l] = {
                "version": TAG_LIFT_VERSION,
                "tag": tag_l,
                "normalized_key": dedupe.normalize_key(tag_l),
                "stream": "outcome_feed",
                "current": None, "prior": None, "lift_ratio": None,
                "useful_outcome_count": 0, "false_outcome_count": 0,
                "flagged": False, "notes": ["feed_only"],
            }
        entry["useful_outcome_count"] += int(counts.get("useful") or 0)
        entry["false_outcome_count"] += int(counts.get("false") or 0)

    return sorted(entries.values(),
                  key=lambda e: (-(e["lift_ratio"] or 0.0), -e["useful_outcome_count"]))


def plan_actions(entries: list[dict[str, Any]],
                 feedback_counts: dict[str, dict[tuple[str, str], dict[str, int]]],
                 feed: dict[str, dict[str, dict[str, int]]], *,
                 existing_trend_keys: set[str],
                 covered: set[str],
                 min_outcomes: int = 5,
                 max_candidates: int = 25,
                 skipped: dict[str, int] | None = None) -> dict[str, list[dict[str, Any]]]:
    """Pure planner: tag entries + feedback counts → bounded weight-delta
    actions and gated candidate payload plans. NO side effects here."""
    def _skip(reason: str) -> None:
        if skipped is not None:
            skipped[reason] = skipped.get(reason, 0) + 1

    deltas: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []

    # (a) boost/penalize EXISTING candidates whose normalized_key matches a
    # lifting/sagging tag (trend_deltas feed scoring's trend_momentum).
    for e in entries:
        key = e.get("normalized_key") or ""
        if not key or e.get("lift_ratio") is None:
            continue
        if key not in existing_trend_keys:
            continue
        delta = _clamp_run_delta((float(e["lift_ratio"]) - 1.0) * DELTA_PER_LIFT)
        if abs(delta) < MIN_DELTA:
            _skip("delta_negligible")
            continue
        deltas.append({"kind": "trend", "trend_key": key, "delta": round(delta, 6),
                       "reason": f"tag {e['tag']} lift_ratio {e['lift_ratio']}"})

    # (b) operator-feedback outcomes → source/trend deltas (net useful).
    for (kind, key), counts in (feedback_counts.get("current") or {}).items():
        net = int(counts.get("useful") or 0) - int(counts.get("false") or 0)
        delta = _clamp_run_delta(net * DELTA_PER_OUTCOME)
        if abs(delta) < MIN_DELTA:
            _skip("delta_negligible")
            continue
        deltas.append({"kind": kind,
                       "source_domain": key if kind == "source" else None,
                       "trend_key": key if kind == "trend" else None,
                       "delta": round(delta, 6),
                       "reason": f"feedback net {net:+d} useful in {WINDOW_DAYS}d"})

    # (c) source-level feed outcomes → source deltas.
    for source, counts in ((feed or {}).get("by_source") or {}).items():
        net = int(counts.get("useful") or 0) - int(counts.get("false") or 0)
        delta = _clamp_run_delta(net * DELTA_PER_OUTCOME)
        if abs(delta) < MIN_DELTA:
            _skip("delta_negligible")
            continue
        deltas.append({"kind": "source", "source_domain": source, "trend_key": None,
                       "delta": round(delta, 6),
                       "reason": f"outcome feed net {net:+d} useful"})

    # (d) NEW candidates — hard sample gate + coverage/existing dedupe.
    for e in entries:
        if len(candidates) >= max(1, int(max_candidates)):
            _skip("run_cap")
            break
        if int(e.get("useful_outcome_count") or 0) < max(1, int(min_outcomes)):
            _skip("below_min_outcomes")
            continue
        ratio = e.get("lift_ratio")
        if ratio is not None and float(ratio) < MIN_CREATE_LIFT_RATIO:
            _skip("lift_ratio_below_create_floor")
            continue
        key = e.get("normalized_key") or ""
        if not key:
            _skip("empty_key")
            continue
        if key in covered:
            _skip("covered_by_directive_or_topic")
            continue
        if key in existing_trend_keys:
            _skip("already_candidate")
            continue
        ctype = "TREND_CANDIDATE" if e.get("stream") == "outcome_bus" else "TOPIC_CANDIDATE"
        useful, false = e["useful_outcome_count"], e["false_outcome_count"]
        precision = (e.get("current") or {}).get("precision") if e.get("current") else None
        alignment = (float(precision) if precision is not None
                     else useful / max(1, useful + false))
        momentum = (min(1.0, max(0.0, float(ratio)) / (2.0 * MIN_CREATE_LIFT_RATIO))
                    if ratio is not None else 0.5)
        candidates.append(dict(
            candidate_type=ctype,
            label=f"Research tag outperforming: {e['tag']}"[:120],
            summary=(f"Tag '{e['tag']}' shows outcome lift"
                     f"{f' ratio {ratio}x' if ratio is not None else ''} with "
                     f"{useful} useful vs {false} false/noise outcomes."),
            evidence=[{"source_domain": "outcome_bus" if e.get("stream") == "outcome_bus"
                       else "hermes_discovery_outcome_feed",
                       "note": (f"useful={useful} false={false} "
                                f"lift_ratio={ratio}")}],
            meta={"producer": PRODUCER,
                  "keywords": [e["tag"]],
                  "tag_lift_json": e},
            safe_action_level="OPERATOR_REVIEW_REQUIRED",
            ttl_days=TAG_TTL_DAYS,
            signals={"trend_momentum": round(momentum, 4),
                     "outcome_bus_alignment": round(min(1.0, max(0.0, alignment)), 4)},
        ))
    return {"weight_deltas": deltas, "candidates": candidates}


# ── DB helpers ───────────────────────────────────────────────────────────────

def existing_candidate_keys(notes: list[str] | None = None) -> set[str]:
    """normalized_keys of live (non-terminal) candidates — the boost targets
    and the creation-dedupe set."""
    try:
        rows = _rows(
            """SELECT normalized_key FROM hermes_discovery_candidates
               WHERE status NOT IN ('REJECTED', 'BLOCKED', 'ARCHIVED_COLD')
               LIMIT 5000""")
        return {str(r["normalized_key"]).lower() for r in rows if r.get("normalized_key")}
    except Exception as e:
        if notes is not None:
            notes.append(f"existing candidates unavailable: {e}")
        return set()


# ── run entry point ──────────────────────────────────────────────────────────

def run_discovery(*, dry_run: bool = False,
                  bus_path: Path | str | None = None,
                  history_dir: Path | str | None = None,
                  feed_path: Path | str | None = None,
                  config_path: Path | str | None = None) -> dict[str, Any]:
    """Full tag-lift pass. Dry-run computes and reports everything with ZERO
    writes (no upserts, no weight-file mutation); live mode applies deltas via
    feedback.apply_weight_delta and creates candidates via inbox.upsert_candidate."""
    cfg = load_tag_lift_config(config_path)
    notes: list[str] = []
    skipped: dict[str, int] = {}

    bus = load_outcome_bus(bus_path, notes)
    prior_bus = load_prior_outcome_bus((bus or {}).get("run_id"), history_dir, notes) \
        if bus else None
    feed = load_outcome_feed(feed_path, notes)
    fb_counts = fetch_feedback_counts(WINDOW_DAYS, notes)

    entries = compute_tag_lift(bus, prior_bus, feed)
    plan = plan_actions(
        entries, fb_counts, feed,
        existing_trend_keys=existing_candidate_keys(notes),
        covered=covered_keys(notes),
        min_outcomes=cfg["tag_lift_min_outcomes"],
        max_candidates=cfg["max_candidates_per_run"],
        skipped=skipped)

    applied_deltas = 0
    if not dry_run:
        for d in plan["weight_deltas"]:
            try:
                feedback.apply_weight_delta(source_domain=d.get("source_domain"),
                                            trend_key=d.get("trend_key"),
                                            delta=float(d["delta"]))
                applied_deltas += 1
            except Exception as e:
                notes.append(f"weight delta skipped ({d.get('reason')}): {e}")

    by_type: dict[str, int] = {}
    by_domain: dict[str, int] = {}
    candidates: list[dict[str, Any]] = []
    upserted = 0
    for p in plan["candidates"]:
        domain = _payload_domain(p)
        by_type[p["candidate_type"]] = by_type.get(p["candidate_type"], 0) + 1
        by_domain[domain] = by_domain.get(domain, 0) + 1
        summary = {"candidate_type": p["candidate_type"], "label": p["label"],
                   "domain": domain,
                   "tag_lift_json": p["meta"]["tag_lift_json"],
                   "signals": p["signals"]}
        if not dry_run:
            row = inbox.upsert_candidate(actor=ACTOR, **p)
            summary.update({
                "id": row.get("id"), "status": row.get("status"),
                "seen_count": row.get("seen_count"),
                "research_domain": (row.get("meta_json") or {}).get("research_domain"),
                "score": (float(row["discovery_score"])
                          if row.get("discovery_score") is not None else None),
            })
            upserted += 1
        candidates.append(summary)

    return {
        "mode": "tag_lift",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": bool(dry_run),
        "enabled_in_schedule": cfg["tag_lift_enabled"],
        "thresholds": {
            "tag_lift_min_outcomes": cfg["tag_lift_min_outcomes"],
            "window_days": WINDOW_DAYS,
            "min_create_lift_ratio": MIN_CREATE_LIFT_RATIO,
            "max_run_delta": MAX_RUN_DELTA,
            "max_abs_delta": feedback.MAX_ABS_DELTA,
        },
        "inputs": {
            "outcome_bus_run_id": (bus or {}).get("run_id"),
            "prior_bus_run_id": (prior_bus or {}).get("run_id"),
            "feed_tags": len(feed.get("by_tag") or {}),
            "feed_sources": len(feed.get("by_source") or {}),
            "feedback_keys_current": len(fb_counts.get("current") or {}),
            "scorecards": load_scorecard_context(),
        },
        "tags_analyzed": len(entries),
        "weight_deltas_planned": len(plan["weight_deltas"]),
        "weight_deltas_applied": applied_deltas,
        "candidates_planned": len(plan["candidates"]),
        "upserted": upserted,
        "by_type": by_type,
        "by_domain": by_domain,
        "skipped_reasons": skipped,
        "notes": notes,
        "weight_deltas": plan["weight_deltas"],
        "candidates": candidates,
        "tag_lift": entries,
    }
