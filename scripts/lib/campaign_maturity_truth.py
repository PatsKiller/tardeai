"""Live Command Center maturity truth for campaign m2-canary surfaces.

Supersedes the stale ``maturity_score_latest.json`` (2026-06-28) projection for
``GET /api/v3/control-plane/maturity`` without deleting historical files.

Evidence classes (mutually exclusive per hop, explicit zeroes required):
  implemented | configured | scheduled | attempted | consumed | delivered |
  settled | outcome_observed | behavior_changing | fixture | controlled_canary |
  organic | absent

Rules:
- CANARY configuration is never delivery ownership.
- Fixture / controlled-canary is never organic.
- Stale historical score bodies are marked superseded, not served as live.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from scripts.lib.delivery_provenance_quarantine import exclude_quarantined

SCHEMA = "CampaignMaturityTruth@v1"
HISTORICAL_SUPERSEDED = "data/runtime/maturity_score_latest.json"
EVIDENCE_CLASSES = (
    "implemented",
    "configured",
    "scheduled",
    "attempted",
    "consumed",
    "delivered",
    "settled",
    "outcome_observed",
    "behavior_changing",
    "fixture",
    "controlled_canary",
    "organic",
    "absent",
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso_age_hours(ts: str | None) -> float | None:
    if not ts:
        return None
    try:
        raw = str(ts).replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return round((datetime.now(timezone.utc) - dt).total_seconds() / 3600.0, 3)
    except Exception:
        return None


def _served_root() -> Path:
    current = Path("/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT")
    try:
        return Path(os.path.realpath(current))
    except OSError:
        return Path(__file__).resolve().parents[2]


def _read_sha(root: Path) -> str | None:
    for name in ("SOURCE_COMMIT", "BUILD_SHA"):
        p = root / name
        try:
            v = p.read_text().strip()
            if v:
                return v
        except OSError:
            pass
    for key in ("TRADEAI_CC_DEPLOYED_SHA", "SOURCE_COMMIT", "BUILD_SHA"):
        v = os.environ.get(key)
        if v:
            return v
    return None


def _flag_sources() -> dict[str, str]:
    flags = {
        "PERSISTENT_WAKE_ENABLED": "unset",
        "PERSISTENT_WAKE_SCHEDULE_ENABLED": "unset",
        "COMMS_GATEWAY_MODE": "unset",
    }
    paths = [
        _served_root() / ".env",
        Path("/run/user/1000/tradeai/env"),
    ]
    dropin = Path.home() / ".config/systemd/user/portfolio-server.service.d"
    if dropin.exists():
        paths.extend(sorted(dropin.glob("*.conf")))
    for path in paths:
        if not path.exists():
            continue
        try:
            txt = path.read_text()
        except OSError:
            continue
        for k in list(flags):
            m = re.search(rf"^(?:Environment=)?{k}=(.*)$", txt, re.M)
            if m:
                flags[k] = m.group(1).strip().strip('"').strip("'")
    return flags


def _crontab_has_persistent_wake() -> bool:
    try:
        import subprocess

        out = subprocess.run(
            ["crontab", "-l"], capture_output=True, text=True, timeout=5
        ).stdout
    except Exception:
        return False
    return bool(re.search(r"run_persistent_wake", out or ""))


def _jsonl_wakes(root: Path) -> list[dict[str, Any]]:
    path = root / "data/persistent_wake/state/wakes.jsonl"
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    except OSError:
        return []
    return rows


def _coords(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("provider_coordinates")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            obj = json.loads(raw)
        except ValueError:
            return {}
        return obj if isinstance(obj, dict) else {}
    return {}


def count_delivery_maturity_numerators(
    rows: Iterable[dict[str, Any]], *, path: str | None = None
) -> dict[str, int]:
    """Maturity numerators over delivery rows — quarantined ids dropped via exclude_quarantined."""
    kept = exclude_quarantined(rows, path=path)
    gw = 0
    leg = 0
    pmid = 0
    for row in kept:
        owner = str(_coords(row).get("delivery_owner") or "").strip()
        if owner == "gateway":
            gw += 1
        elif owner == "legacy":
            leg += 1
        if row.get("provider_message_id"):
            pmid += 1
    return {
        "delivery_owner_gateway": gw,
        "delivery_owner_legacy": leg,
        "deliveries_with_pmid": pmid,
        "kept_n": len(kept),
    }


def _db_snapshot() -> dict[str, Any]:
    """Best-effort read-only counts. Missing DB ⇒ explicit zeroes + unavailable."""
    out: dict[str, Any] = {
        "available": False,
        "acr_total": 0,
        "acr_usable": 0,
        "delivery_owner_gateway": 0,
        "delivery_owner_legacy": 0,
        "deliveries_with_pmid": 0,
        "inbound_with_usable_receipt": 0,
        "shadow_proposals": 0,
        "error": None,
    }
    try:
        env: dict[str, str] = {}
        env_path = _served_root() / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip().startswith("DB_"):
                    env[k.strip()] = v.strip().strip('"').strip("'")
        if not env.get("DB_HOST"):
            out["error"] = "DB_HOST unset"
            return out
        import psycopg2

        conn = psycopg2.connect(
            host=env.get("DB_HOST"),
            port=env.get("DB_PORT") or 5432,
            dbname=env.get("DB_NAME"),
            user=env.get("DB_USER"),
            password=env.get("DB_PASSWORD"),
            connect_timeout=5,
        )
        conn.set_session(readonly=True, autocommit=True)
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM communication_agent_consumption_receipts")
        out["acr_total"] = int(cur.fetchone()[0])
        cur.execute(
            """
            SELECT count(*) FROM communication_agent_consumption_receipts
            WHERE coalesce(policy_decision, '') NOT LIKE 'TOMBSTONED%%'
            """
        )
        out["acr_usable"] = int(cur.fetchone()[0])
        # Fetch delivery rows and drop quarantined provider ids (e.g. wamid.test_1)
        # via exclude_quarantined before maturity numerators.
        cur.execute(
            """
            SELECT delivery_id, provider_message_id, provider_coordinates, channel
              FROM communication_deliveries
            """
        )
        cols = [d[0] for d in cur.description]
        delivery_rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        counts = count_delivery_maturity_numerators(delivery_rows)
        out["delivery_owner_gateway"] = int(counts["delivery_owner_gateway"])
        out["delivery_owner_legacy"] = int(counts["delivery_owner_legacy"])
        out["deliveries_with_pmid"] = int(counts["deliveries_with_pmid"])
        cur.execute(
            """
            SELECT count(*) FROM communication_events e
            JOIN communication_agent_consumption_receipts r
              ON r.event_id::text = e.event_id::text
            WHERE e.direction = 'INBOUND'
              AND coalesce(r.policy_decision, '') NOT LIKE 'TOMBSTONED%%'
            """
        )
        out["inbound_with_usable_receipt"] = int(cur.fetchone()[0])
        try:
            cur.execute("SELECT count(*) FROM agent_weight_shadow_proposals")
            out["shadow_proposals"] = int(cur.fetchone()[0])
        except Exception:
            conn.rollback()
            out["shadow_proposals"] = 0
        conn.close()
        out["available"] = True
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def _classify_wakes(wakes: list[dict[str, Any]]) -> dict[str, Any]:
    organic = 0
    controlled = 0
    fixture = 0
    attempted = 0
    effect_nonzero = 0
    for w in wakes:
        attempted += 1
        reason = str(w.get("wake_reason") or "").lower()
        purpose = str(w.get("purpose") or "").lower()
        blob = json.dumps(w, default=str).lower()
        ds = w.get("decision_summary") or {}
        if isinstance(ds, str):
            try:
                ds = json.loads(ds)
            except ValueError:
                ds = {}
        ek = str((ds or {}).get("effect_kind") or "none")
        if ek not in {"", "none", "None"}:
            effect_nonzero += 1
        if "litmus" in purpose or "fixture" in blob or "due_diligence_proof" in purpose:
            fixture += 1
            continue
        # Stage-2 grant / hand invocation pattern: same produced second + schedule slot
        # without proving unattended cron. Without producer provenance, treat
        # schedule_slot wakes as controlled_canary unless organic marker present.
        prov = w.get("provenance") if isinstance(w.get("provenance"), dict) else {}
        trigger = str((prov or {}).get("trigger") or w.get("trigger") or "").lower()
        if trigger in {"cron", "schedule", "unattended"} or (
            "organic" in blob and "controlled" not in blob
        ):
            organic += 1
        elif "schedul" in reason or w.get("schedule_slot_utc"):
            controlled += 1
        else:
            controlled += 1
    return {
        "attempted": attempted,
        "organic": organic,
        "controlled_canary": controlled,
        "fixture": fixture,
        "effect_kind_nonzero": effect_nonzero,
    }


def _dimension(
    *,
    dimension: str,
    evidence_class: str,
    count: int,
    proof_refs: list[str],
    limiting_factor: str,
    next_proof: str,
    notes: str = "",
    source_store: str = "",
    evidence_timestamp: str | None = None,
) -> dict[str, Any]:
    assert evidence_class in EVIDENCE_CLASSES, evidence_class
    return {
        "dimension": dimension,
        "evidence_class": evidence_class,
        "count": int(count),
        "explicit_zero": int(count) == 0,
        "proof_refs": proof_refs,
        "limiting_factor": limiting_factor,
        "next_proof": next_proof,
        "notes": notes,
        "source_store": source_store,
        "evidence_timestamp": evidence_timestamp,
        "staleness_hours": _iso_age_hours(evidence_timestamp),
        # UI historically rendered a score column — keep absent/null so the page
        # cannot invent a certification average from live truth rows.
        "score": None,
    }


def build_maturity_truth(*, root: Path | None = None) -> dict[str, Any]:
    """Return control-plane maturity ``data`` payload (items + metadata)."""
    root = root or _served_root()
    as_of = _now()
    served_sha = _read_sha(root)
    flags = _flag_sources()
    scheduled = _crontab_has_persistent_wake()
    wakes = _jsonl_wakes(root)
    wake_cls = _classify_wakes(wakes)
    db = _db_snapshot()
    selector = (root / "scripts/lib/wake_subject_selector.py").exists()
    wake_cli = (root / "scripts/run_persistent_wake.py").exists()

    gateway_mode = flags.get("COMMS_GATEWAY_MODE", "unset")
    wake_flags_on = (
        flags.get("PERSISTENT_WAKE_ENABLED") == "1"
        and flags.get("PERSISTENT_WAKE_SCHEDULE_ENABLED") == "1"
    )

    # Historical body — supersede, do not rewrite.
    hist_path = Path("/home/johnclaw/trade-ai-releases/persistent-state") / HISTORICAL_SUPERSEDED
    if not hist_path.exists():
        hist_path = root / "data/runtime/maturity_score_latest.json"
    hist_generated = None
    if hist_path.exists():
        try:
            hist = json.loads(hist_path.read_text())
            hist_generated = hist.get("generated_at")
        except Exception:
            hist_generated = None

    items = [
        _dimension(
            dimension="persistent_wake_implemented",
            evidence_class="implemented" if (selector and wake_cli) else "absent",
            count=int(selector) + int(wake_cli),
            proof_refs=["scripts/lib/wake_subject_selector.py", "scripts/run_persistent_wake.py"],
            limiting_factor="" if (selector and wake_cli) else "entrypoint_or_selector_missing",
            next_proof="keep entrypoint+selector on served SHA",
            source_store=str(root),
            evidence_timestamp=as_of,
        ),
        _dimension(
            dimension="persistent_wake_configured",
            evidence_class="configured" if wake_flags_on else "absent",
            count=int(wake_flags_on),
            proof_refs=["PERSISTENT_WAKE_ENABLED", "PERSISTENT_WAKE_SCHEDULE_ENABLED"],
            limiting_factor="" if wake_flags_on else "flags_unset",
            next_proof="both wake flags must be 1",
            notes=json.dumps(flags),
            source_store="/run/user/1000/tradeai/env+systemd drop-ins",
            evidence_timestamp=as_of,
        ),
        _dimension(
            dimension="persistent_wake_scheduled",
            evidence_class="scheduled" if scheduled else "absent",
            count=int(scheduled),
            proof_refs=["crontab:run_persistent_wake"],
            limiting_factor="" if scheduled else "no_crontab_line",
            next_proof="hourly unattended cron must fire",
            source_store="user crontab",
            evidence_timestamp=as_of,
        ),
        _dimension(
            dimension="persistent_wake_attempted",
            evidence_class="attempted" if wake_cls["attempted"] else "absent",
            count=wake_cls["attempted"],
            proof_refs=["data/persistent_wake/state/wakes.jsonl"],
            limiting_factor="" if wake_cls["attempted"] else "no_wake_rows",
            next_proof="unattended cron cycles",
            source_store="data/persistent_wake/state/wakes.jsonl",
            evidence_timestamp=(wakes[-1].get("produced_at") if wakes else None),
        ),
        _dimension(
            dimension="persistent_wake_organic",
            evidence_class="organic" if wake_cls["organic"] else "absent",
            count=wake_cls["organic"],
            proof_refs=["provenance.trigger=unattended|cron"],
            limiting_factor="no_organic_marker_on_jsonl_wakes"
            if wake_cls["attempted"] and not wake_cls["organic"]
            else ("no_wakes" if not wake_cls["attempted"] else ""),
            next_proof="cron-fired wakes with unattended provenance",
            notes=f"controlled_canary={wake_cls['controlled_canary']} fixture={wake_cls['fixture']}",
            source_store="data/persistent_wake/state/wakes.jsonl",
            evidence_timestamp=as_of,
        ),
        _dimension(
            dimension="persistent_wake_controlled_canary",
            evidence_class="controlled_canary" if wake_cls["controlled_canary"] else "absent",
            count=wake_cls["controlled_canary"],
            proof_refs=["stage2_grant_or_schedule_slot_without_organic_marker"],
            limiting_factor="",
            next_proof="do not count toward organic CM3",
            source_store="data/persistent_wake/state/wakes.jsonl",
            evidence_timestamp=as_of,
        ),
        _dimension(
            dimension="research_consumed_effect_nonzero",
            evidence_class="consumed" if wake_cls["effect_kind_nonzero"] else "absent",
            count=wake_cls["effect_kind_nonzero"],
            proof_refs=["decision_summary.effect_kind"],
            limiting_factor="effect_kind_none_or_missing",
            next_proof="wake with effect_kind != none and resolvable effect_ref",
            source_store="data/persistent_wake/state/wakes.jsonl",
            evidence_timestamp=as_of,
        ),
        _dimension(
            dimension="comms_gateway_configured",
            evidence_class="configured" if gateway_mode.upper() == "CANARY" else "absent",
            count=1 if gateway_mode.upper() == "CANARY" else 0,
            proof_refs=["COMMS_GATEWAY_MODE"],
            limiting_factor="" if gateway_mode.upper() == "CANARY" else f"mode={gateway_mode}",
            next_proof="configuration ≠ delivery ownership",
            notes="CANARY configuration is NOT delivery ownership",
            source_store="systemd drop-in 32-comms-gateway-mode.conf",
            evidence_timestamp=as_of,
        ),
        _dimension(
            dimension="comms_delivery_owner_gateway",
            evidence_class="delivered" if db["delivery_owner_gateway"] else "absent",
            count=db["delivery_owner_gateway"],
            proof_refs=["communication_deliveries.provider_coordinates.delivery_owner"],
            limiting_factor="owner_gateway_zero"
            if db["available"] and db["delivery_owner_gateway"] == 0
            else (db.get("error") or ""),
            next_proof="gateway-owned row with provider_message_id",
            notes=f"legacy={db['delivery_owner_legacy']} pmid={db['deliveries_with_pmid']} "
            f"(CANARY config must not be read as ownership)",
            source_store="postgresql:communication_deliveries",
            evidence_timestamp=as_of if db["available"] else None,
        ),
        _dimension(
            dimension="comms_provider_settled",
            evidence_class="settled" if db["deliveries_with_pmid"] else "absent",
            count=db["deliveries_with_pmid"],
            proof_refs=["communication_deliveries.provider_message_id"],
            limiting_factor="pmid_zero_or_unowned",
            next_proof="gateway owner + non-null PMID + SETTLED/SENT",
            source_store="postgresql:communication_deliveries",
            evidence_timestamp=as_of if db["available"] else None,
        ),
        _dimension(
            dimension="comms_agent_consumption_usable",
            evidence_class="consumed" if db["acr_usable"] else "absent",
            count=db["acr_usable"],
            proof_refs=["communication_agent_consumption_receipts"],
            limiting_factor="all_tombstoned_or_zero",
            next_proof="untombstoned receipt for real event_id",
            notes=f"acr_total={db['acr_total']} (tombstones excluded from usable)",
            source_store="postgresql:communication_agent_consumption_receipts",
            evidence_timestamp=as_of if db["available"] else None,
        ),
        _dimension(
            dimension="comms_inbound_consumed",
            evidence_class="consumed" if db["inbound_with_usable_receipt"] else "absent",
            count=db["inbound_with_usable_receipt"],
            proof_refs=["inbound event join usable receipt"],
            limiting_factor="no_inbound_usable_receipt",
            next_proof="real inbound → receipt → wake",
            source_store="postgresql:communication_events+receipts",
            evidence_timestamp=as_of if db["available"] else None,
        ),
        _dimension(
            dimension="shadow_belief_proposals",
            evidence_class="outcome_observed" if db["shadow_proposals"] else "absent",
            count=db["shadow_proposals"],
            proof_refs=["agent_weight_shadow_proposals"],
            limiting_factor="zero_shadow_rows",
            next_proof="shadow proposal then later unattended behavior change",
            source_store="postgresql:agent_weight_shadow_proposals",
            evidence_timestamp=as_of if db["available"] else None,
        ),
        _dimension(
            dimension="behavior_changing",
            evidence_class="absent",
            count=0,
            proof_refs=["MBI_BEHAVIOR=0"],
            limiting_factor="behavior_writes_refused_by_policy",
            next_proof="never claim CM4 without later unattended behavior delta",
            notes="Explicit zero — belief/cognition must not mutate live financial behavior",
            source_store="scripts/lib/cio_instrument_record.py",
            evidence_timestamp=as_of,
        ),
    ]

    return {
        "schema": SCHEMA,
        "ok": True,
        "generated_at": as_of,
        "served_sha": served_sha,
        "evidence_timestamp": as_of,
        "source_store": "scripts.lib.campaign_maturity_truth.build_maturity_truth",
        "staleness_hours": 0.0,
        "overall_is_not_a_certification": True,
        "computes_maturity": False,
        "historical_body_superseded": {
            "path": str(hist_path) if hist_path.exists() else HISTORICAL_SUPERSEDED,
            "generated_at": hist_generated,
            "staleness_hours": _iso_age_hours(hist_generated),
            "disposition": "SUPERSEDED_NOT_DELETED",
            "reason": "Stale 2026-06 score body must not be served as live maturity truth",
        },
        "items": items,
        "limiting_dimension": next(
            (i["dimension"] for i in items if i["count"] == 0 and i["dimension"] in {
                "persistent_wake_organic",
                "research_consumed_effect_nonzero",
                "comms_delivery_owner_gateway",
                "comms_agent_consumption_usable",
            }),
            items[0]["dimension"] if items else None,
        ),
        "db_probe": {"available": db["available"], "error": db.get("error")},
        "note": (
            "Live runtime evidence. Explicit zeroes included. "
            "CANARY configuration ≠ gateway delivery ownership. "
            "Controlled canary ≠ organic."
        ),
    }


__all__ = [
    "build_maturity_truth",
    "count_delivery_maturity_numerators",
    "SCHEMA",
    "EVIDENCE_CLASSES",
    "HISTORICAL_SUPERSEDED",
]
