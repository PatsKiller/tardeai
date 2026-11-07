"""GET /api/v2/ops/n8n-catalog: what n8n is configured to handle, by category, with the lane audit verdicts.

LQ-20261107-150 (operator 2026-11-07): the published n8n configuration catalog, rebuilt as a live tab on
Ops › Jobs & n8n. One joined, read-only payload so the phone makes one call:

* jobs and categories: the cached jobs-history projection (``scripts/lib/jobs_history.snapshot``);
* the relay live list: the effective list the relay itself uses (``n8n_relay_live_lanes.resolve``: the rendered
  ``N8N_RELAY_LIVE_LANES.json`` of the served release minus Ops Controls pauses);
* the audit verdicts: ``data/runtime/n8n_lane_audit/verdicts.json`` (schema ``n8n_lane_audit.v1``).

Mode per lane (the catalog artifact's rule):
  scheduler ``cron`` and in the relay list  -> ``both``  (n8n + cron, cutover pending)
  scheduler ``n8n`` and (in the relay list or its last run was live) -> ``live``
  scheduler ``n8n`` otherwise -> ``dry``  (dry run on n8n)
  anything else -> ``none``  (not on n8n)

A missing or unreadable store is reported in ``notes`` and yields empty rows for that source, never a 500. A lane
without a verdict is "not audited"; nothing here calls a lane working unless its verdict is PASS or PASS_IDLE.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional

ROOT = Path(__file__).resolve().parents[2]
VERDICTS_REL = "data/runtime/n8n_lane_audit/verdicts.json"
VERDICTS_SCHEMA = "n8n_lane_audit.v1"
SCHEMA = "N8nCatalog@v1"
CACHE_SECONDS = 60.0

MODES = ("live", "both", "dry", "none")
PASS_VERDICTS = frozenset({"PASS", "PASS_IDLE"})
NOT_PROVABLE = frozenset({"UNVERIFIABLE"})
#: The verdict order the audit uses; an unknown verdict string is still counted (under its own key) and is a FAIL
#: only when it starts with FAIL_.
VERDICTS = ("PASS", "PASS_IDLE", "FAIL_DATA", "FAIL_RUN", "FAIL_CONFIG", "FAIL_NO_OUTPUT", "FAIL_CONSUMER",
            "HALLUCINATION", "UNVERIFIABLE")


def verdict_class(verdict: Optional[str]) -> str:
    """``pass`` / ``fail`` / ``not_provable`` / ``not_audited``. Only PASS and PASS_IDLE are ``pass``."""
    if not verdict:
        return "not_audited"
    if verdict in PASS_VERDICTS:
        return "pass"
    if verdict in NOT_PROVABLE:
        return "not_provable"
    if verdict.startswith("FAIL") or verdict == "HALLUCINATION":
        return "fail"
    return "not_provable"


def derive_mode(row: Mapping[str, Any], relay: Optional[frozenset]) -> str:
    """The catalog mode of one jobs-history row. ``relay`` None (list unreadable) counts as an empty list."""
    sched = row.get("scheduler")
    in_relay = bool(relay) and row.get("lane_id") in relay
    if sched == "cron" and in_relay:
        return "both"
    if sched == "n8n":
        last_mode = (row.get("last_run") or {}).get("mode")
        return "live" if in_relay or last_mode == "live" else "dry"
    return "none"


def read_verdicts(path: Path) -> tuple[dict[str, dict], dict]:
    """({lane_id: verdict row}, meta). A missing / unreadable / wrong-schema file -> ({}, meta with a note)."""
    meta: dict[str, Any] = {"path": VERDICTS_REL, "state": "ok", "written_at": None, "by": None, "rows": 0, "note": None}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, {**meta, "state": "missing", "note": "No audit verdicts file yet; every lane shows 'not audited'."}
    except (OSError, ValueError) as exc:
        return {}, {**meta, "state": "unreadable",
                    "note": f"Audit verdicts could not be read ({type(exc).__name__}); every lane shows 'not audited'."}
    if not isinstance(doc, dict) or doc.get("schema") != VERDICTS_SCHEMA or not isinstance(doc.get("rows"), list):
        return {}, {**meta, "state": "malformed",
                    "note": f"Audit verdicts file is not {VERDICTS_SCHEMA}; every lane shows 'not audited'."}
    out: dict[str, dict] = {}
    for r in doc["rows"]:
        if not isinstance(r, dict) or not str(r.get("lane_id") or "").strip() or not str(r.get("verdict") or "").strip():
            continue
        out[str(r["lane_id"])] = {
            "verdict": str(r["verdict"]),
            "defect": str(r.get("defect") or "") or None,
            "fix_suggestion": str(r.get("fix_suggestion") or "") or None,
            "work_item": str(r.get("work_item") or "") or None,
            "audited_at": r.get("audited_at"),
        }
    return out, {**meta, "written_at": doc.get("written_at"), "by": doc.get("by"), "rows": len(out)}


def read_relay(root: Path, environ: Mapping[str, str]) -> tuple[Optional[frozenset], dict]:
    """The effective relay live list (what the relay itself would run live) and its provenance."""
    try:
        from scripts.lib import n8n_relay_live_lanes as RL

        res = RL.resolve(environ, root)
    except Exception as exc:  # noqa: BLE001 -- a broken relay reader is a note, never a 500
        return None, {"source": "unavailable", "lanes": None, "paused": [],
                      "note": f"Relay live list could not be read ({type(exc).__name__})."}
    lanes = res.get("lanes")
    meta = {"source": res.get("source"), "lanes": len(lanes) if lanes is not None else None,
            "paused": list(res.get("paused") or []), "note": None}
    if lanes is None:
        meta["note"] = f"Relay live list unavailable ({res.get('detail')}); no lane is counted as in the list."
    return (frozenset(lanes) if lanes is not None else None), meta


def build(snapshot: Mapping[str, Any], relay: Optional[frozenset], relay_meta: Mapping[str, Any],
          verdicts: Mapping[str, dict], verdict_meta: Mapping[str, Any]) -> dict:
    """Join one jobs-history snapshot with the relay list and the verdicts. Pure."""
    rows_in = list(snapshot.get("rows") or [])
    cats = [dict(c) for c in snapshot.get("categories") or []]
    known = {c.get("key") for c in cats}
    for key in sorted({str(r.get("category_key") or "other") for r in rows_in} - known):
        cats.append({"key": key, "label": key.replace("_", " ").capitalize(), "blurb": ""})
    paused = set(relay_meta.get("paused") or [])
    lanes: list[dict] = []
    for r in rows_in:
        lane_id = r.get("lane_id")
        mode = derive_mode(r, relay)
        v = verdicts.get(lane_id)
        lanes.append({
            "lane_id": lane_id,
            "title": r.get("title") or r.get("job") or lane_id,
            "does": r.get("does"),
            "category_key": str(r.get("category_key") or "other"),
            "scheduler": r.get("scheduler"),
            "state": r.get("state"),
            "status": r.get("status"),
            "schedule": list((r.get("cadence") or {}).get("expressions") or []),
            "timezone": (r.get("cadence") or {}).get("timezone"),
            "last_run_mode": (r.get("last_run") or {}).get("mode"),
            "mode": mode,
            "in_relay": bool(relay) and lane_id in relay,
            "paused_on_n8n": lane_id in paused,
            "verdict": v["verdict"] if v else None,
            "verdict_class": verdict_class(v["verdict"] if v else None),
            "defect": v["defect"] if v else None,
            "fix_suggestion": v["fix_suggestion"] if v else None,
            "work_item": v["work_item"] if v else None,
            "audited_at": v["audited_at"] if v else None,
        })
    # "Not on n8n" counts only jobs that still run somewhere: a retired job is not a job n8n should handle.
    countable = [x for x in lanes if not (x["mode"] == "none" and x["state"] == "RETIRED")]
    mode_counts = {m: sum(1 for x in countable if x["mode"] == m) for m in MODES}
    verdict_counts: dict[str, int] = {}
    for v in verdicts.values():
        verdict_counts[v["verdict"]] = verdict_counts.get(v["verdict"], 0) + 1
    classes = {"pass": 0, "fail": 0, "not_provable": 0}
    for v in verdicts.values():
        c = verdict_class(v["verdict"])
        if c in classes:
            classes[c] += 1
    out_cats = []
    for c in cats:
        members = [x for x in countable if x["category_key"] == c.get("key")]
        on_n8n = sorted((x for x in members if x["mode"] != "none"),
                        key=lambda x: (MODES.index(x["mode"]), str(x["title"]).lower()))
        rows_c = [r for r in rows_in if str(r.get("category_key") or "other") == c.get("key")]
        mix = {k: 0 for k in MIX_KEYS}
        for r in rows_c:
            mix[STATUS_MIX.get(r.get("status"), "not_measured")] += 1
        out_cats.append({**c, "modes": {m: sum(1 for x in members if x["mode"] == m) for m in MODES},
                         "lanes": [x["lane_id"] for x in on_n8n],
                         # Same rule as GET /api/v2/jobs-catalog status_mix, so the two pages agree.
                         "jobs": len(rows_c), "inactive": mix["inactive"], "status_mix": mix})
    audited_not_in_rows = sorted(set(verdicts) - {x["lane_id"] for x in lanes})
    notes = [n for n in (verdict_meta.get("note"), relay_meta.get("note")) if n]
    if audited_not_in_rows:
        notes.append(f"{len(audited_not_in_rows)} audited lane(s) are not in the job registry: "
                     + ", ".join(audited_not_in_rows[:10]))
    if snapshot.get("gaps"):
        notes.append("Some job stores could not be read; see the Jobs tabs for the gaps.")
    return {
        "schema": SCHEMA,
        "computed_at": snapshot.get("computed_at"),
        "stats": {"modes": mode_counts, "verdicts": verdict_counts, "audit": {**classes, "audited": len(verdicts)},
                  "retired_not_counted": len(lanes) - len(countable)},
        "categories": out_cats,
        "lanes": {x["lane_id"]: x for x in lanes if x["mode"] != "none" or x["verdict"]},
        "relay": dict(relay_meta),
        "audit": dict(verdict_meta),
        "audited_not_in_registry": audited_not_in_rows,
        "notes": notes,
        "authority": "read-only projection; nothing here changes a schedule or the live list",
    }


#: Mirrors jobs_history._MIX (GET /api/v2/jobs-catalog status_mix); a test pins the two together.
MIX_KEYS = ("failed", "missed", "late", "running", "ok", "ok_unverified", "not_measured", "inactive")
STATUS_MIX = {"failed": "failed", "missed": "missed", "late": "late", "running": "running", "ok": "ok",
              "ok_unverified": "ok_unverified", "not_measured": "not_measured", "paused": "inactive",
              "retired": "inactive", "never_scheduled": "inactive", "inactive": "inactive"}
LEDGER_DIR_REL = "data/coordination/coordinator"
LEDGER_GLOB = "LEAD-WORK-LEDGER-*.json"


def read_work_items(state: Path, refs: Iterable[str]) -> tuple[dict[str, dict], Optional[str]]:
    """ref -> {id, owner, priority, status, title} from the newest lead work ledger. A short ref ("LQ-57") resolves to
    the one ledger id ending in "-57"; an unresolved ref maps to status None. Read-only."""
    refs = sorted({r for r in refs if r})
    try:
        paths = sorted((state / LEDGER_DIR_REL).glob(LEDGER_GLOB))
    except OSError:
        paths = []
    if not paths:
        return {r: {"id": r, "owner": None, "priority": None, "status": None, "title": None} for r in refs}, \
            "No lead work ledger found: fix items show without status."
    try:
        doc = json.loads(paths[-1].read_text(encoding="utf-8"))
        items = [i for i in (doc.get("items") or []) if isinstance(i, dict) and i.get("id")]
    except (OSError, ValueError, AttributeError) as exc:
        return {r: {"id": r, "owner": None, "priority": None, "status": None, "title": None} for r in refs}, \
            f"The lead work ledger could not be read ({type(exc).__name__})."
    by_id = {str(i["id"]): i for i in items}
    out: dict[str, dict] = {}
    for r in refs:
        hit = by_id.get(r)
        if hit is None and r.startswith("LQ-") and r.count("-") == 1:
            n = r.split("-", 1)[1].lstrip("0")
            cands = [i for k, i in by_id.items() if k.startswith("LQ-") and k.rsplit("-", 1)[-1].lstrip("0") == n]
            hit = cands[0] if len(cands) == 1 else None
        out[r] = {"id": str(hit["id"]) if hit else r, "owner": hit.get("owner") if hit else None,
                  "priority": hit.get("priority") if hit else None, "status": hit.get("status") if hit else None,
                  "title": (str(hit.get("title") or "")[:200] or None) if hit else None}
    return out, None


def state_root(environ: Mapping[str, str]) -> Path:
    v = environ.get("TRADEAI_STATE_ROOT")
    return Path(v).expanduser() if v else Path.home() / "trade-ai-releases/persistent-state"


def compute(*, environ: Optional[Mapping[str, str]] = None, root: Optional[Path] = None,
            state: Optional[Path] = None, snapshot_fn: Optional[Callable[[], Mapping[str, Any]]] = None) -> dict:
    environ = os.environ if environ is None else environ
    root = Path(root or ROOT)
    explicit_state = state is not None
    state = Path(state or state_root(environ))
    if snapshot_fn is None:
        from scripts.lib import jobs_history

        def snapshot_fn():
            # No argument = the same cached projection /api/v2/jobs-history serves (no second store read).
            return jobs_history.snapshot(state_root=state) if explicit_state else jobs_history.snapshot()
    try:
        snap = snapshot_fn()
    except Exception as exc:  # noqa: BLE001 -- an unreadable jobs snapshot becomes a gap note, never a 500
        snap = {"rows": [], "categories": [], "computed_at": None,
                "gaps": [f"jobs-history unavailable ({type(exc).__name__})"]}
    relay, relay_meta = read_relay(root, environ)
    verdicts, verdict_meta = read_verdicts(state / VERDICTS_REL)
    out = build(snap, relay, relay_meta, verdicts, verdict_meta)
    out["work_items"], wnote = read_work_items(state, (v.get("work_item") for v in verdicts.values()))
    if wnote:
        out["notes"].append(wnote)
    return out


_CACHE: dict = {}
_LOCK = threading.Lock()


def get_n8n_catalog(query=None, *, ttl: float = CACHE_SECONDS, **kwargs) -> dict:
    """Cached 60 s, single-flight (concurrent callers wait for one build). A failed build is not cached."""
    key = json.dumps({k: str(v) for k, v in kwargs.items()}, sort_keys=True)
    hit = _CACHE.get(key)
    if hit and time.monotonic() - hit[0] < ttl:
        return hit[1]
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and time.monotonic() - hit[0] < ttl:
            return hit[1]
        payload = compute(**kwargs)
        _CACHE[key] = (time.monotonic(), payload)
        return payload
