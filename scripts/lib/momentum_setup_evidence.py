"""Read-only momentum facts for shared views and notification annotation.

MomentumSetupEvidence@v1 consumes cached source facts, not an execution engine.
Five source criteria are separate from SocialScout's five awareness pillars and
from source verdicts/approval. No provider, model, credential or writer is used.
"""

from __future__ import annotations

import html
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit
from zoneinfo import ZoneInfo

from .scalp_go_criteria import FALLBACK

SCHEMA = "MomentumSetupEvidence@v1"
MARKER = "Momentum evidence (advisory)"
ET = ZoneInfo("America/New_York")
AT_HEADER = "ACTIVE TRADER · SCALP ALERT"
SCOUT_NAMES = {
    "social_velocity",
    "market_confirmation",
    "catalyst_evidence",
    "structure_tradeability",
    "strategy_risk_fit",
}


def _stamp(value):
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else None
    except ValueError:
        return None


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _text(value, limit=300):
    return re.sub(r"\s+", " ", value).strip()[:limit] if isinstance(value, str) and value.strip() else None


def _url(value):
    if (
        not isinstance(value, str)
        or len(value) > 1000
        or any(c.isspace() or ord(c) < 32 or c in '<>"`\\' for c in value)
    ):
        return None
    try:
        parsed = urlsplit(value)
        return (
            value
            if parsed.scheme == "https"
            and parsed.hostname
            and not parsed.username
            and not parsed.password
            and not {key.lower() for key, _ in parse_qsl(parsed.query)}
            & {"api_key", "token", "key", "auth", "access_token", "signature", "secret", "password"}
            else None
        )
    except ValueError:
        return None


def _session_state(stamp, now):
    if stamp is None:
        return "UNKNOWN"
    if stamp > now:
        return "FUTURE"
    return "CURRENT_SESSION" if stamp.astimezone(ET).date() == now.astimezone(ET).date() else "STALE_SESSION"


def observation_lineage(row, *, source_name="CACHED_SOURCE", run_id=None, source_ref=None):
    """Public original metadata only. Composition/DB/cache times never become observation times."""
    original = row.get("lineage") if isinstance(row.get("lineage"), dict) else {}

    def value(key):
        return original.get(key) if original.get(key) is not None else row.get(key)

    raw_observed = value("observed_at")
    raw_event = value("event_at")
    observed, event = _stamp(raw_observed), _stamp(raw_event)
    session = _text(value("session_date"), 40) or _text(row.get("run_date"), 40)
    actual_run = _text(value("run_id"), 160) or _text(run_id, 160)
    if not session and actual_run:
        try:
            session = datetime.strptime(actual_run[:10], "%Y-%m-%d").date().isoformat()
        except ValueError:
            pass
    if not session and observed:
        session = observed.astimezone(ET).date().isoformat()
    result = {
        "security_guid": _text(value("security_guid"), 160),
        "event_id": _text(value("event_id"), 160),
        "run_id": actual_run,
        "run_attempt_id": _text(value("run_attempt_id"), 160),
        "session_date": session,
        "event_at": event.isoformat() if event else None,
        "observed_at": observed.isoformat() if observed else None,
        "source_ref": _text(value("source_ref"), 1000) or _text(source_ref, 1000),
        "source_sha": _text(value("source_sha"), 80),
        "source": source_name,
        "original_timestamps": {
            key: value
            if isinstance(value, str) and len(value) <= 80 and re.match(r"\d{4}-\d{2}-\d{2}", value)
            else None
            for key, value in {
                "observed_at": (original.get("original_timestamps") or {}).get("observed_at", raw_observed)
                if isinstance(original.get("original_timestamps"), dict)
                else raw_observed,
                "event_at": (original.get("original_timestamps") or {}).get("event_at", raw_event)
                if isinstance(original.get("original_timestamps"), dict)
                else raw_event,
            }.items()
        },
    }
    # This hash identifies the public observation snapshot; it never invents an event or security GUID.
    result["observation_hash"] = hashlib.sha256(
        json.dumps({**result, "decision": row.get("decision")}, sort_keys=True).encode()
    ).hexdigest()
    return result


def public_scan_observation(row, *, run_id, run_date, run_label, source_sha=None):
    """Preserve public source facts in the existing run package, before daily DB upserts lose history."""
    aliases = {"rvol": "relative_volume", "gap_pct": "gap_percent", "change_pct": "change_percent"}
    keys = (
        "symbol",
        "security_guid",
        "event_id",
        "event_at",
        "observed_at",
        "source_ref",
        "run_attempt_id",
        "decision",
        "original_decision",
        "disqualified",
        "price",
        "float_m",
        "rvol",
        "gap_pct",
        "change_pct",
        "catalyst",
        "catalyst_source",
        "catalyst_url",
        "catalyst_published_at",
        "catalyst_verified",
        "catalyst_verification_method",
        "catalyst_verified_at",
        "catalyst_relevance",
        "catalyst_relevance_reason",
        "catalyst_confidence",
        "field_observations",
    )
    out = {key: row[key] for key in keys if key in row}
    if isinstance(out.get("field_observations"), dict):
        out["field_observations"] = {
            name: {key: fact[key] for key in ("observed_at", "source_ref", "source_sha") if key in fact}
            for name, fact in out["field_observations"].items()
            if name in {"price", "float", "rvol", "gap"} and isinstance(fact, dict)
        }
    for target, source in aliases.items():
        if target not in out and source in row:
            out[target] = row[source]
    article = row.get("top_catalyst") if isinstance(row.get("top_catalyst"), dict) else {}
    for key, sources in {
        "catalyst": ("title", "headline"),
        "catalyst_source": ("source", "provider"),
        "catalyst_url": ("source_url", "url"),
        "catalyst_published_at": ("published_at",),
    }.items():
        if key not in out:
            out[key] = next((article[k] for k in sources if article.get(k) is not None), None)
    out.update(run_id=run_id, run_date=run_date, run_label=run_label, source_sha=source_sha)
    out["lineage"] = observation_lineage(out, source_name="TRADE_AI", source_ref=out.get("source_ref"))
    return out


def build_setup_evidence(
    row,
    *,
    now=None,
    observed_at=None,
    criteria=None,
    criteria_source=None,
    source_name="CACHED_SOURCE",
    source_stale=False,
):
    """Pure projection; missing source facts remain UNKNOWN, never implied passes."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("evidence clock must be timezone-aware")
    row = row if isinstance(row, dict) else {}
    policy = FALLBACK if criteria is None else criteria if isinstance(criteria, dict) else {}
    lineage = observation_lineage(row, source_name=source_name)
    source_at = _stamp(lineage.get("observed_at") or observed_at)
    observed_state = _session_state(source_at, now)
    declared_date = row.get("run_id") or row.get("run_date") or row.get("session_date")
    try:
        source_day = datetime.strptime(str(declared_date)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        source_day = None
    if source_stale or row.get("stale") or row.get("cache_error"):
        observed_state = "STALE_SOURCE"
    elif source_day and source_day != now.astimezone(ET).date():
        observed_state = (
            "STALE_SESSION" if source_at is None or source_at.astimezone(ET).date() == source_day else "TIMING_CONFLICT"
        )
    text = _text(row.get("catalyst") or row.get("catalyst_headline"))
    source = _text(row.get("catalyst_source"), 120)
    original_publication = row.get("catalyst_published_at") or row.get("catalyst_at")
    published = _stamp(original_publication)
    publication_state = _session_state(published, now)
    reported = row.get("catalyst_verified") if isinstance(row.get("catalyst_verified"), bool) else None
    method = _text(row.get("catalyst_verification_method"), 120)
    publication_url = _url(row.get("catalyst_url"))
    factual = (
        "UNVERIFIED"
        if reported is False
        else "VERIFIED"
        if reported is True
        and text
        and source
        and publication_url
        and published
        and method in {"PRIMARY_PUBLICATION", "PUBLICATION_MATCH", "SOURCE_CORROBORATION"}
        else "UNKNOWN"
    )
    catalyst_status = "UNKNOWN"
    if reported is False:
        catalyst_status = "UNVERIFIED"
    elif factual == "VERIFIED" and publication_state == observed_state == "CURRENT_SESSION":
        catalyst_status = "SOURCE_VERIFIED"
    catalyst = {
        "text": text,
        "source": source,
        "url": publication_url,
        "reported_verified": reported,
        "verification_status": catalyst_status,
        "factual_verification_status": factual,
        "verification_method": method,
        "verified_at": row.get("catalyst_verified_at"),
        "relevance": row.get("catalyst_relevance")
        if isinstance(row.get("catalyst_relevance"), (str, bool, int, float))
        else None,
        "relevance_reason": _text(row.get("catalyst_relevance_reason")),
        "model_confidence": _number(row.get("catalyst_confidence")),
        "original_published_at": original_publication if isinstance(original_publication, str) else None,
        "published_at": published.isoformat() if published else None,
        "observed_at": source_at.isoformat() if source_at else None,
        "publication_state": publication_state,
        "observation_state": observed_state,
        "freshness_bound_seconds": "NOT_MEASURED",
    }
    pillars = []

    def numeric(name, label, raw, bounds, predicate, *, positive=False):
        value = _number(raw)
        limits = [_number(v) for key, v in bounds.items() if key != "unit"]
        unknown = value is None or (positive and value <= 0) or not limits or any(v is None for v in limits)
        if name == "price" and len(limits) == 2 and all(v is not None for v in limits) and limits[0] > limits[1]:
            unknown = True
        status = "UNKNOWN" if unknown else "PASSED" if predicate(value) else "FAILED"
        # Preserve stale values, but never report them as current qualifying facts.
        fields = row.get("field_observations") if isinstance(row.get("field_observations"), dict) else {}
        fact = fields.get(name) if isinstance(fields.get(name), dict) else {}
        fact_at = _stamp(fact.get("observed_at")) if fact else source_at
        if not fact and source_name == "ACTIVE_TRADER" and not lineage.get("observed_at"):
            # An advisory's publication clock is not the underlying quote clock.
            fact_at = None
        if observed_state != "CURRENT_SESSION" or _session_state(fact_at, now) != "CURRENT_SESSION":
            status = "UNKNOWN"
        pillars.append(
            {
                "id": name,
                "label": label,
                "value": value,
                "status": status,
                "threshold": bounds,
                "observed_at": fact_at.isoformat() if fact_at else None,
                "source_ref": _text(fact.get("source_ref"), 1000) or lineage["source_ref"],
            }
        )

    def policy_section(key):
        value = policy.get(key)
        return value if isinstance(value, dict) else {}

    price = policy_section("price")
    float_c = policy_section("float_m")
    rvol = policy_section("rvol")
    gap = policy_section("gap_pct")
    numeric(
        "price",
        "Price",
        row.get("price") if row.get("price") is not None else row.get("last"),
        {"min": price.get("min"), "max": price.get("max"), "unit": "USD"},
        lambda v: float(price["min"]) <= v <= float(price["max"]),
    )
    numeric(
        "float",
        "Float",
        row.get("float_m") if row.get("float_m") is not None else row.get("float_mm"),
        {"max": float_c.get("max"), "unit": "million shares"},
        lambda v: v <= float(float_c["max"]),
        positive=True,
    )
    numeric(
        "rvol",
        "RVOL",
        row.get("rvol"),
        {"min": rvol.get("min"), "unit": "multiple"},
        lambda v: v >= float(rvol["min"]),
        positive=True,
    )
    numeric(
        "gap",
        "Gap/change",
        row.get("gap_pct") if row.get("gap_pct") is not None else row.get("change_pct"),
        {"min_abs": gap.get("min_abs"), "unit": "percent"},
        lambda v: abs(v) >= float(gap["min_abs"]),
    )
    pillars.append(
        {
            "id": "catalyst",
            "label": "Verified catalyst",
            "value": reported,
            "status": "PASSED"
            if catalyst_status == "SOURCE_VERIFIED"
            else "FAILED"
            if reported is False
            else "UNKNOWN",
            "threshold": {"required": True},
            "observed_at": catalyst["observed_at"],
        }
    )
    scout_count = row.get("scout_pillar_count")
    if isinstance(scout_count, bool) or not isinstance(scout_count, int) or not 0 <= scout_count <= 5:
        scout_count = None
    scout = {
        "reported_count": scout_count,
        "reported_met": [x for x in row.get("scout_pillars_met", []) if isinstance(x, str) and x in SCOUT_NAMES]
        if isinstance(row.get("scout_pillars_met"), list)
        else None,
        "reported_missing": [x for x in row.get("scout_pillars_missing", []) if isinstance(x, str) and x in SCOUT_NAMES]
        if isinstance(row.get("scout_pillars_missing"), list)
        else None,
        "definition": "upstream_social_scout_five",
        "recomputed": False,
    }
    passes = sum(p["status"] == "PASSED" for p in pillars)
    return {
        "schema": SCHEMA,
        "source_name": source_name,
        "pillar_definition": "momentum_policy_five",
        "criteria_source": criteria_source
        or ("scripts/lib/scalp_go_criteria.py:FALLBACK" if criteria is None else "EXPLICIT_CRITERIA"),
        "policy_path": "config/finviz_momentum_scalp_screen.yaml:screen.tradeable",
        "symbol": _text(row.get("symbol"), 20),
        "lineage": lineage,
        "catalyst": catalyst,
        "pillars": pillars,
        "passed_count": passes,
        "required_count": 5,
        "all_five_proven": passes == 5,
        "source_observation_state": observed_state,
        "social_scout": scout,
        "authority": "READ_ONLY_ADVISORY",
        "execution_authority": "NONE",
        "note": "Five cached source facts; session freshness only, recency SLO not measured. Source verdict/trigger/approval unchanged; volume/score/other gates remain separate.",
    }


def _safe_line(value):
    # No HTML or Markdown control from a source headline becomes notification chrome.
    return re.sub(r"[<>*_`\[\]]", "", str(value if value is not None else "UNKNOWN")).replace("\n", " ")


def format_notification_evidence(evidence, *, include_catalyst=True):
    if not isinstance(evidence, dict):
        return f"{MARKER}: UNKNOWN — current same-symbol evidence unavailable"
    catalyst = evidence.get("catalyst") or {}
    lines = [f"{MARKER}: {evidence.get('passed_count', 0)}/5 source facts · {_safe_line(evidence.get('source_name'))}"]
    if include_catalyst:
        lines.append(f"Catalyst: {_safe_line(catalyst.get('text'))}")
        lines.append(
            f"Source: {_safe_line(catalyst.get('source'))} · {_safe_line(catalyst.get('verification_status'))}"
        )
        lines.append(
            f"Published: {_safe_line(catalyst.get('published_at'))} · observed {_safe_line(catalyst.get('observed_at'))}"
        )
        lines.append(f"Catalyst session: {_safe_line(catalyst.get('publication_state'))} · recency not measured")
    for pillar in evidence.get("pillars") or []:
        threshold = pillar.get("threshold") or {}
        rule = (
            "verified + sourced/current"
            if pillar.get("id") == "catalyst"
            else ", ".join(f"{k} {v}" for k, v in threshold.items() if k != "unit")
        )
        lines.append(
            f"{_safe_line(pillar.get('label'))}: {_safe_line(pillar.get('status'))} · {_safe_line(pillar.get('value'))} ({rule})"
        )
    scout = evidence.get("social_scout") or {}
    if scout.get("reported_count") is not None:
        lines.append(f"SocialScout: {scout['reported_count']}/5 reported upstream (different definition)")
    lines.append("Metadata only; trigger and approval unchanged.")
    return "\n".join(lines)


def _structured_subject(message):
    # Only literal symbol fields/cashtags in the first three public header lines.
    plain = html.unescape(re.sub(r"<[^>]+>", "", message))
    found = []
    for line in plain.splitlines()[:3]:
        match = re.fullmatch(r"\s*(?:Symbol|Ticker)\s*:\s*\*?\$?([A-Z][A-Z0-9.]{0,19})\*?\s*", line, re.I)
        if match:
            found.append(match.group(1).upper())
        match = re.fullmatch(r"\s*\*?\$([A-Z][A-Z0-9.]{0,19})\*?\s*", line)
        if match:
            found.append(match.group(1).upper())
        multi = re.fullmatch(r"\s*Symbols\s*:\s*(.+)", line, re.I)
        if multi:
            found.extend(s.strip().strip("$*").upper() for s in multi.group(1).split(","))
        trigger = re.match(
            r"^[^A-Za-z]*(?:TRIGGERED|ARMED|APPROACHING|PULLBACK_ZONE|EXTENDED|TRIGGER_CANCELLED|STAND_DOWN|BACK IN BUY ZONE|TRIGGER FAILED|STAND DOWN)\s*[:—·]\s*\*?\$?([A-Z][A-Z0-9.]{0,19})\*?(?=\s|$)",
            line,
        )
        if trigger:
            found.append(trigger.group(1))
    return sorted(set(found))


def _cached_snapshot():
    from .scanner_candidate_projection import read_candidate_snapshot

    state = Path.home() / "trade-ai-releases" / "persistent-state"
    if not (state / "PERSISTENT_STATE_ROOT.json").is_file():
        return None
    return read_candidate_snapshot(
        state / "data/runtime/trade_ai_cache.json", state / "data/active_trader/momentum_alerts.jsonl"
    )


def enrich_active_trader_notification(
    message, *, message_class="operator_alert", primary_symbols=None, snapshot_loader=None, now=None
):
    """Fail-soft metadata annotation; never routes, suppresses, retries or sends."""
    if not isinstance(message, str) or MARKER in message:
        return message
    plain = html.unescape(re.sub(r"<[^>]+>", "", message))
    lines = [line.strip() for line in plain.splitlines() if line.strip()]
    header = re.sub(r"^[^A-Za-z]*", "", lines[0]).upper() if lines else ""
    if message_class != "active_trader_scalp_alert" and header != AT_HEADER:
        return message
    now = now or datetime.now(timezone.utc)
    if primary_symbols is None:
        from .comms_editor import _resolve_primary_symbols

        primary_symbols = _resolve_primary_symbols(None)
    header_symbols = _structured_subject(message)
    symbols = header_symbols if primary_symbols is None else [str(s).strip().upper() for s in primary_symbols]
    if primary_symbols is not None and header_symbols and set(symbols) != set(header_symbols):
        symbols = []  # A stale explicit context cannot override the body identity.
    symbols = sorted(set(s for s in symbols if re.fullmatch(r"[A-Z][A-Z0-9.]{0,19}", s)))
    evidence = None
    if len(symbols) == 1:
        try:
            snapshot = (snapshot_loader or _cached_snapshot)()
            candidates = snapshot.get("candidates") if isinstance(snapshot, dict) else None
            matched = [r for r in candidates or [] if isinstance(r, dict) and r.get("symbol") == symbols[0]]
            if len(matched) == 1 and not matched[0].get("conflicts"):
                for source in ("trade_ai", "active_trader"):
                    observations = (matched[0].get(source) or {}).get("observations") or []
                    if not observations:
                        continue
                    candidate_evidence = observations[0].get("setup_evidence")
                    stamp = _stamp(observations[0].get("observed_at"))
                    if (
                        isinstance(candidate_evidence, dict)
                        and _session_state(stamp, now) == "CURRENT_SESSION"
                        and candidate_evidence.get("source_observation_state") == "CURRENT_SESSION"
                        and observations[0].get("freshness") != "STALE"
                    ):
                        evidence = candidate_evidence
                        break
        except (OSError, ValueError, TypeError, AttributeError):
            evidence = None
    has_catalyst = bool(re.search(r"(?mi)^\s*[^A-Za-z0-9]*catalyst\s*:", plain))
    appendix = format_notification_evidence(evidence, include_catalyst=not has_catalyst)
    if re.search(r"</?(?:b|i|a|blockquote|code)\b", message):
        appendix = html.escape(appendix)
    out = message.rstrip() + "\n\n" + appendix
    return out if len(out.encode("utf-16-le")) // 2 <= 4000 else message
