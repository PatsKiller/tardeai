"""lane_manifest — the one lane manifest (LaneManifest@v1), its validator, and the lane_registry.json shim.

LQ-20261107-1003 (Fable audit LQ-984 Q6 #2 + #14; REBUILD-SPEC-registry-runtime-truth). Verdict: REBUILD CLEAN.
Twenty-four catalog files describe lanes and disagree on 135 of 723; the runtime-truth checker matched a free-text
``scheduler.match`` in one direction only and needed a patch round per blind spot (LQ-62/115/296/385/846). This module
replaces the matching design, not the sources:

* ``build_manifest()``      one row per lane with the canonical fields (state, armed, owner, script, command relative to
                            CURRENT, schedule, market_hours_only, shadow_expires_at, output rule + empty_allowed +
                            upstream_count_field, identity key). Every other registry key is kept verbatim in
                            ``legacy`` for the shim only.
* ``registry_view()``       rebuilds the LaneRegistry@v1 document from the manifest, key order included, so the 98
                            scripts that open config/lane_registry.json and the 33 that call lib.lane_registry keep
                            getting identical answers once the registry file is rendered from the manifest.
* ``attribute_cron_line()`` binds a crontab line to a lane by an explicit key first (``TRADEAI_EFFECT_CLAIM=<lane>``
                            / ``effect_claim_cron.sh <lane>``), then by the comment-stripped match marker, then by the
                            script path; a line no lane claims is UNDECLARED, one several claim is AMBIGUOUS. Both are
                            enumerated from the HOST side, which is the reverse direction the old checker never ran.
* ``disagreements()``       every way the sources disagree, as typed findings — the generator never guesses.

Pure: no file, network, DB or subprocess access here. Callers read the sources. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

SCHEMA = "LaneManifest@v1"
SCHEMA_PATH = Path(__file__).resolve().parents[2] / "config" / "schemas" / "lane_manifest.schema.json"
STATES = ("ACTIVE", "PAUSED", "RETIRED", "NEVER_SCHEDULED")
PY_TOKEN = "{python}"  # the release interpreter of CURRENT; never the dev-tree $PY (#14)

#: Registry keys with a canonical manifest home that round-trips exactly. Everything else lives in ``legacy``.
CANONICAL_KEYS = {"lane_id": "id", "owner": "owner", "state": "state", "output_signal": "output.signal"}

_SCRIPT_RE = re.compile(r"(?<![\w/.-])((?:scripts|bin)/[\w./-]+\.(?:py|sh|mjs|js))")
_EFFECT_RE = re.compile(r"TRADEAI_EFFECT_CLAIM=([A-Za-z0-9_.:-]+)|effect_claim_cron\.sh\s+([A-Za-z0-9_.:-]+)")
_MIN_MARKER = 8
#: The shared dispatcher workflow fires every ``dispatch.mode live`` lane; registry rows call it either name.
DISPATCHER_WORKFLOWS = frozenset({"dispatcher", "tradeai-dispatcher"})  # a marker shorter than this ("run.py") would attribute half the crontab


# ── schema validation (stdlib subset of JSON Schema) ─────────────────────────────────────────────────────────────

_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}


def _type_ok(value: Any, t: Any) -> bool:
    names = t if isinstance(t, list) else [t]
    for n in names:
        if n == "integer" and isinstance(value, int) and not isinstance(value, bool):
            return True
        if n == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
            return True
        py = _TYPES.get(n)
        if py is not None and isinstance(value, py) and not (py is not bool and isinstance(value, bool)):
            return True
    return False


def _validate(value: Any, schema: Mapping[str, Any], root: Mapping[str, Any], path: str, out: list[str]) -> None:
    if "$ref" in schema:
        ref = schema["$ref"].split("/")[-1]
        schema = root["definitions"][ref]
    if "type" in schema and not _type_ok(value, schema["type"]):
        out.append(f"{path}: expected {schema['type']}, got {type(value).__name__}")
        return
    if "const" in schema and value != schema["const"]:
        out.append(f"{path}: must be {schema['const']!r}, got {value!r}")
    if "enum" in schema and value not in schema["enum"]:
        out.append(f"{path}: {value!r} not in {schema['enum']}")
    if "pattern" in schema and isinstance(value, str) and not re.search(schema["pattern"], value):
        out.append(f"{path}: {value!r} does not match {schema['pattern']}")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                out.append(f"{path}: missing {key!r}")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in props:
                    out.append(f"{path}: unexpected key {key!r}")
        for key, sub in props.items():
            if key in value:
                _validate(value[key], sub, root, f"{path}.{key}", out)
        cond = schema.get("if")
        if cond is not None:
            probe: list[str] = []
            _validate(value, cond, root, path, probe)
            if not probe and "then" in schema:
                _validate(value, schema["then"], root, path, out)
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            _validate(item, schema["items"], root, f"{path}[{i}]", out)


def load_schema(path: Optional[Path] = None) -> dict[str, Any]:
    return json.loads(Path(path or SCHEMA_PATH).read_text(encoding="utf-8"))


def validate(manifest: Mapping[str, Any], schema: Optional[Mapping[str, Any]] = None) -> list[str]:
    """Every schema violation plus the cross-row rules a schema cannot say (unique ids). Empty list = valid."""
    schema = schema or load_schema()
    out: list[str] = []
    _validate(manifest, schema, schema, "$", out)
    seen: set[str] = set()
    for lane in manifest.get("lanes") or []:
        lid = lane.get("id") if isinstance(lane, dict) else None
        if lid in seen:
            out.append(f"$.lanes: duplicate id {lid!r}")
        seen.add(lid)
    return out


def dispatchable(lane: Mapping[str, Any]) -> bool:
    """The only answer a scheduler may act on: ACTIVE and armed. RETIRED/PAUSED/NEVER_SCHEDULED never dispatch."""
    return lane.get("state") == "ACTIVE" and lane.get("armed") is True


# ── field derivation (pure) ──────────────────────────────────────────────────────────────────────────────────────


def strip_comment(marker: str) -> str:
    """``scheduler.match`` text with a trailing ``  # comment`` removed — the comment is never on the crontab line
    (REBUILD-SPEC root defect 2: hermes-research-agenda-at-45-7)."""
    return re.split(r"\s+#\s", str(marker), maxsplit=1)[0].strip()


def match_markers(scheduler: Mapping[str, Any]) -> list[str]:
    raw = scheduler.get("match")
    items = raw if isinstance(raw, (list, tuple)) else [raw]
    out = []
    for m in items:
        s = strip_comment(m) if m else ""
        if s and s not in out:
            out.append(s)
    return out


def scripts_in(text: str) -> list[str]:
    out: list[str] = []
    for m in _SCRIPT_RE.findall(str(text or "")):
        if m not in out:
            out.append(m)
    return out


def _wrapper(path: str) -> bool:
    return path.endswith(("effect_claim_cron.sh", "safe_flock.sh", "market_day_gate.sh", "cron_wrap.sh"))


def primary_script(row: Mapping[str, Any], allow: Optional[Mapping[str, Any]]) -> Optional[str]:
    candidates: list[str] = []
    if allow:
        candidates += scripts_in(" ".join(str(t) for t in allow.get("command") or []))
    sched = row.get("scheduler") or {}
    for text in (sched.get("command_text"), *match_markers(sched), row.get("exec_start"), row.get("command")):
        if isinstance(text, (list, tuple)):
            text = " ".join(map(str, text))
        candidates += scripts_in(text or "")
    for c in candidates:
        if not _wrapper(c):
            return c
    return candidates[0] if candidates else None


def release_argv(tokens: Iterable[Any]) -> list[str]:
    """Allowlist command tokens with the dev-tree ``$PY`` replaced by the release interpreter token (#14)."""
    return [PY_TOKEN if str(t) == "$PY" else str(t).replace("$PY", PY_TOKEN) for t in tokens]


def derive_command(row: Mapping[str, Any], allow: Optional[Mapping[str, Any]], script: Optional[str]
                   ) -> Optional[dict[str, Any]]:
    if allow and allow.get("command"):
        argv = release_argv(allow["command"])
        if not any("/home/" in a for a in argv):
            return {"root": "CURRENT", "argv": argv, "source": "allowlist"}
    if script:
        interp = [PY_TOKEN] if script.endswith(".py") else (["bash"] if script.endswith(".sh") else ["node"])
        sched = row.get("scheduler") or {}
        source = "registry_command_text" if sched.get("command_text") else "registry_match"
        return {"root": "CURRENT", "argv": interp + [script], "source": source}
    return None


def derive_schedule(row: Mapping[str, Any]) -> dict[str, Any]:
    sched = row.get("scheduler") or {}
    disp = row.get("dispatch") or {}
    mode = disp.get("mode")
    kind = sched.get("kind") or "none"
    expr = sched.get("expression")
    if mode == "live":
        return {"runner": "n8n", "cron": [str(c) for c in disp.get("cron") or []], "tz": disp.get("tz"),
                "unit": None, "workflow": "dispatcher", "mode": mode}
    cron: list[str] = []
    unit = workflow = None
    if kind == "cron":
        cron = [str(s) for s in sched.get("schedules") or []] or ([str(expr)] if expr else [])
    elif kind == "systemd":
        unit = str(expr) if expr else None
    elif kind == "n8n":
        workflow = str(expr) if expr else None
        cron = [str(c) for c in disp.get("cron") or []]
    elif kind == "event":
        cron = [str(sched["cadence"])] if sched.get("cadence") else []
    runner = kind if kind in ("cron", "systemd", "n8n", "event") else "none"
    return {"runner": runner, "cron": cron, "tz": disp.get("tz") or sched.get("timezone"), "unit": unit,
            "workflow": workflow, "mode": mode}


def derive_output(row: Mapping[str, Any], contract: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    eo = (contract or {}).get("expected_output") or {}
    rule = eo.get("rule")
    return {
        "signal": dict(row.get("output_signal") or {"kind": "none"}),
        "rule": rule if rule in ("min_produced", "empty_allowed", "per_window", "none") else None,
        "empty_allowed": rule == "empty_allowed",
        # LQ-1004 fills this: an empty_allowed run must cite an upstream count in its receipt.
        "upstream_count_field": eo.get("upstream_count_field"),
    }


def build_lane(row: Mapping[str, Any], allow: Optional[Mapping[str, Any]], contract: Optional[Mapping[str, Any]]
               ) -> dict[str, Any]:
    lid = str(row["lane_id"])
    state = str(row.get("state"))
    script = primary_script(row, allow)
    legacy = {k: v for k, v in row.items() if k not in CANONICAL_KEYS}
    legacy["_order"] = list(row.keys())
    market = allow.get("market_gate") if allow else None
    return {
        "id": lid,
        "state": state,
        "armed": state == "ACTIVE",
        "owner": str(row.get("owner") or ""),
        "script": script,
        "command": derive_command(row, allow, script),
        "schedule": derive_schedule(row),
        # LQ-1002 (cc-deepseek-7) owns the honoured flag; until it lands this mirrors allowlist.market_gate.
        "market_hours_only": bool(market) if isinstance(market, bool) else None,
        # LQ-1002 owns shadow expiry; nothing sets it yet.
        "shadow_expires_at": row.get("shadow_expires_at") if isinstance(row.get("shadow_expires_at"), str) else None,
        "output": derive_output(row, contract),
        "identity": {"effect_claim": lid, "match": match_markers(row.get("scheduler") or {})},
        "legacy": legacy,
    }


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_manifest(registry: Mapping[str, Any], allowlist: Mapping[str, Any], contracts: Mapping[str, Any], *,
                   generated_at: str, sources: Mapping[str, Any]) -> dict[str, Any]:
    allow = {str(e.get("lane_id")): e for e in allowlist.get("lanes") or []}
    cons = {str(c.get("id")): c for c in contracts.get("contracts") or [] if c.get("kind", "lane") == "lane"}
    header = {k: v for k, v in registry.items() if k != "lanes"}
    header["_order"] = list(registry.keys())
    return {
        "schema": SCHEMA,
        "authority": "GENERATED_CANDIDATE",
        "generated_at": generated_at,
        "sources": dict(sources),
        "registry_header": header,
        "lanes": [build_lane(r, allow.get(str(r.get("lane_id"))), cons.get(str(r.get("lane_id"))))
                  for r in registry.get("lanes") or []],
    }


# ── the registry shim ────────────────────────────────────────────────────────────────────────────────────────────


def registry_row(lane: Mapping[str, Any]) -> dict[str, Any]:
    legacy = lane["legacy"]
    canon = {"lane_id": lane["id"], "owner": lane["owner"], "state": lane["state"],
             "output_signal": lane["output"]["signal"]}
    out: dict[str, Any] = {}
    for key in legacy["_order"]:
        out[key] = canon[key] if key in canon else legacy[key]
    return out


def registry_view(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """The LaneRegistry@v1 document the 131 existing readers expect, rebuilt from the manifest (order preserved)."""
    header = manifest["registry_header"]
    out: dict[str, Any] = {}
    for key in header["_order"]:
        out[key] = [registry_row(l) for l in manifest["lanes"]] if key == "lanes" else header[key]
    return out


def render_registry(manifest: Mapping[str, Any]) -> str:
    return json.dumps(registry_view(manifest), indent=2, ensure_ascii=False) + "\n"


# ── host attribution (pure) ──────────────────────────────────────────────────────────────────────────────────────


def build_index(lanes: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    ids: set[str] = set()
    markers: dict[str, set[str]] = {}
    scripts: dict[str, set[str]] = {}
    for lane in lanes:
        lid = lane["id"]
        ids.add(lid)
        for m in lane["identity"]["match"]:
            if len(m) >= _MIN_MARKER:
                markers.setdefault(m, set()).add(lid)
        if lane.get("script"):
            scripts.setdefault(lane["script"], set()).add(lid)
    return {"ids": ids, "markers": markers, "scripts": scripts}


def _primary(line: str, index: Mapping[str, Any]) -> dict[str, Any]:
    for a, b in _EFFECT_RE.findall(line):
        key = a or b
        if key in index["ids"]:
            return {"lanes": [key], "method": "effect_claim"}
    hits = [(m, lids) for m, lids in index["markers"].items() if m in line]
    if hits:
        best = max(len(m) for m, _ in hits)
        lanes = sorted({l for m, lids in hits if len(m) == best for l in lids})
        return {"lanes": lanes, "method": "match"}
    lanes: set[str] = set()
    for s in scripts_in(line):
        if not _wrapper(s):
            lanes |= index["scripts"].get(s, set())
    if lanes:
        return {"lanes": sorted(lanes), "method": "script"}
    return {"lanes": [], "method": "none"}


def attribute_cron_line(line: str, index: Mapping[str, Any]) -> dict[str, Any]:
    """{lanes, method, chained}: effect_claim > match > script; method none = UNDECLARED, len(lanes) > 1 = AMBIGUOUS.

    ``chained`` lists, per extra script the line runs (``a.py && b.py``), the lanes that script belongs to. A line that
    runs a collector and then a RETIRED classifier fires both; attributing only the collector hid the classifier
    (Fable LQ-984 Q1.2 market-regime-classifier)."""
    att = _primary(line, index)
    owned = {s for s, lids in index["scripts"].items() if lids & set(att["lanes"])}
    chained: list[dict[str, Any]] = []
    for s in scripts_in(line):
        if _wrapper(s) or s in owned:
            continue
        by_marker = {l for m, lids in index["markers"].items() if s in m and m in line for l in lids}
        lanes = by_marker or set(index["scripts"].get(s, set()))
        lanes -= set(att["lanes"])
        if lanes:
            chained.append({"script": s, "lanes": sorted(lanes)})
    att["chained"] = chained
    return att


def active_cron_lines(text: str) -> list[str]:
    """Uncommented, non-assignment crontab lines (same rule as check_registry_runtime_truth). Pure."""
    out = []
    for line in str(text).splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        head = s.split(None, 1)[0]
        if "=" in head and not head[0].isdigit() and head[0] not in "*@":
            continue
        out.append(s)
    return out


def line_ref(line: str) -> str:
    """A stable reference to a crontab line that never prints the line (it can carry env assignments)."""
    return "cron:" + sha256_text(line)[:12]


def _norm_path(p: Any) -> str:
    s = str(p or "").strip()
    for prefix in ("~/trade-ai-releases/persistent-state/", "$STATE_ROOT/", "./"):
        if s.startswith(prefix):
            s = s[len(prefix):]
    return s.rstrip("/")


# ── disagreements (pure) ─────────────────────────────────────────────────────────────────────────────────────────

#: code -> severity. ``error`` turns the lane_truth verdict FAIL; ``warn`` is reported, never hidden.
CODES = {
    "UNDECLARED_CRON_LINE": "error",          # host line no lane claims (reverse enumeration)
    "AMBIGUOUS_CRON_LINE": "warn",            # several lanes claim one line; needs an explicit effect-claim key
    "RETIRED_STILL_ARMED": "error",           # RETIRED/PAUSED/NEVER_SCHEDULED lane still fired by a scheduler
    "N8N_LIVE_WITH_CRON_TWIN": "error",       # dispatch live on n8n AND an active crontab line runs it
    "ACTIVE_CRON_NO_LINE": "error",           # runner cron, ACTIVE, no line attributes to it
    "DEV_TREE_INTERPRETER": "warn",           # its crontab line runs the dev-tree $PY, not CURRENT (#14)
    "N8N_LIVE_NO_ALLOWLIST": "error",         # n8n dispatch live, executor may not run it
    "ALLOWLIST_NOT_IN_REGISTRY": "error",
    "OUTPUT_SIGNAL_MISMATCH": "warn",         # registry vs allowlist disagree on the output path
    "ACTIVE_NO_OUTPUT_SIGNAL": "warn",
    "RETIRED_BUT_CONTRACT": "warn",
    "CONTRACT_NOT_IN_REGISTRY": "warn",
    "NO_COMMAND": "warn",                     # ACTIVE lane with no derivable command relative to CURRENT
    "N8N_WORKFLOW_NOT_ACTIVE": "error",       # lane names an n8n workflow the n8n DB says is not active
    "N8N_ACTIVE_WORKFLOW_UNDECLARED": "warn", # active n8n workflow no lane names
    "LIVE_RUNS_FOR_UNARMED_LANE": "error",    # ledger: live RUN_DONE in the window for a lane that must not run
    "N8N_LIVE_NO_RECENT_RUN": "error",        # ledger: n8n live lane, cadence inside the window, no live RUN_DONE
    "LEDGER_LANE_UNDECLARED": "warn",         # ledger lane with live runs that the manifest does not know
}


def finding(code: str, lane: Optional[str], detail: str, **evidence: Any) -> dict[str, Any]:
    return {"code": code, "severity": CODES[code], "lane_id": lane, "detail": detail, "evidence": evidence}


def disagreements(manifest: Mapping[str, Any], *, allowlist: Mapping[str, Any], contracts: Mapping[str, Any],
                  cron_lines: Optional[list[str]] = None, n8n_active: Optional[list[dict]] = None,
                  ledger: Optional[Mapping[str, Any]] = None, window_hours: float = 168.0) -> list[dict[str, Any]]:
    """Every disagreement between the manifest and each source given. A source passed as None is not measured
    (the caller records that); it never counts as clean."""
    lanes = {l["id"]: l for l in manifest["lanes"]}
    allow = {str(e.get("lane_id")): e for e in allowlist.get("lanes") or []}
    cons = {str(c.get("id")) for c in contracts.get("contracts") or [] if c.get("kind", "lane") == "lane"}
    out: list[dict[str, Any]] = []

    for lid in sorted(set(allow) - set(lanes)):
        out.append(finding("ALLOWLIST_NOT_IN_REGISTRY", lid, "allowlist entry with no lane row"))
    for lid in sorted(cons - set(lanes)):
        out.append(finding("CONTRACT_NOT_IN_REGISTRY", lid, "health contract with no lane row"))

    for lid, lane in lanes.items():
        st, sched = lane["state"], lane["schedule"]
        if st == "RETIRED" and lid in cons:
            out.append(finding("RETIRED_BUT_CONTRACT", lid, "RETIRED lane still has a health contract"))
        if st == "ACTIVE" and lane["output"]["signal"].get("kind") in (None, "none"):
            out.append(finding("ACTIVE_NO_OUTPUT_SIGNAL", lid, "ACTIVE lane declares no output signal"))
        if st == "ACTIVE" and lane["command"] is None and sched["runner"] in ("cron", "n8n"):
            out.append(finding("NO_COMMAND", lid, "no command derivable relative to CURRENT"))
        if sched["mode"] == "live" and lid not in allow:
            out.append(finding("N8N_LIVE_NO_ALLOWLIST", lid, "dispatch.mode live but no allowlist entry"))
        a = allow.get(lid)
        if a and a.get("output_signal"):
            reg_path = _norm_path(lane["output"]["signal"].get("path"))
            al_path = _norm_path(a.get("output_signal"))
            if reg_path and al_path and reg_path != al_path:
                out.append(finding("OUTPUT_SIGNAL_MISMATCH", lid, "registry and allowlist name different outputs",
                                   registry=reg_path, allowlist=al_path))

    if cron_lines is not None:
        index = build_index(manifest["lanes"])
        by_lane: dict[str, list[str]] = {}
        for line in cron_lines:
            att = attribute_cron_line(line, index)
            ref = line_ref(line)
            if att["method"] == "none":
                out.append(finding("UNDECLARED_CRON_LINE", None, "active crontab line no lane claims", line=ref,
                                   scripts=scripts_in(line)))
                continue
            if len(att["lanes"]) > 1:
                out.append(finding("AMBIGUOUS_CRON_LINE", None, f"{len(att['lanes'])} lanes claim one line",
                                   line=ref, lanes=att["lanes"], method=att["method"]))
                continue
            lid = att["lanes"][0]
            by_lane.setdefault(lid, []).append(ref)
            for ch in att["chained"]:
                if len(ch["lanes"]) == 1:
                    by_lane.setdefault(ch["lanes"][0], []).append(ref)
                else:
                    out.append(finding("AMBIGUOUS_CRON_LINE", None, f"chained {ch['script']} claimed by "
                                       f"{len(ch['lanes'])} lanes", line=ref, lanes=ch["lanes"], method="chained"))
            if re.search(r"(?<![\w{])\$PY\b|\$\{PY\}", line):
                out.append(finding("DEV_TREE_INTERPRETER", lid, "crontab line runs the dev-tree $PY", line=ref))
        for lid, lane in lanes.items():
            refs = by_lane.get(lid, [])
            if refs and not dispatchable(lane):
                out.append(finding("RETIRED_STILL_ARMED", lid, f"state {lane['state']} but an active crontab line "
                                   "runs it", lines=refs, via="cron"))
            if refs and lane["schedule"]["mode"] == "live" and dispatchable(lane):
                out.append(finding("N8N_LIVE_WITH_CRON_TWIN", lid, "n8n dispatch live and an active crontab line",
                                   lines=refs))
            if not refs and lane["state"] == "ACTIVE" and lane["schedule"]["runner"] == "cron":
                out.append(finding("ACTIVE_CRON_NO_LINE", lid, "ACTIVE cron lane, no active crontab line claims it"))

    for lid, lane in lanes.items():
        if lane["schedule"]["mode"] == "live" and not dispatchable(lane):
            out.append(finding("RETIRED_STILL_ARMED", lid, f"state {lane['state']} but dispatch.mode live",
                               via="n8n_dispatch"))

    if n8n_active is not None:
        active_ids = {str(w.get("id")) for w in n8n_active} | {str(w.get("name")) for w in n8n_active}
        named: set[str] = set()
        dispatcher_up = bool(active_ids & DISPATCHER_WORKFLOWS)
        for lid, lane in lanes.items():
            wf = lane["schedule"]["workflow"]
            if lane["schedule"]["runner"] == "n8n" and wf:
                named |= DISPATCHER_WORKFLOWS if wf in DISPATCHER_WORKFLOWS else {wf}
                up = dispatcher_up if wf in DISPATCHER_WORKFLOWS else wf in active_ids
                if dispatchable(lane) and not up:
                    out.append(finding("N8N_WORKFLOW_NOT_ACTIVE", lid, "lane names an n8n workflow that is not active",
                                       workflow=wf))
        for w in n8n_active:
            if str(w.get("id")) not in named and str(w.get("name")) not in named:
                out.append(finding("N8N_ACTIVE_WORKFLOW_UNDECLARED", None, "active n8n workflow no lane names",
                                   workflow_id=str(w.get("id")), workflow_name=str(w.get("name"))))

    if ledger is not None:
        live = ledger.get("live_runs") or {}
        for lid, info in sorted(live.items()):
            lane = lanes.get(lid)
            if lane is None:
                out.append(finding("LEDGER_LANE_UNDECLARED", lid, "live RUN_DONE for a lane the manifest lacks",
                                   runs=info.get("count"), last=info.get("last")))
            elif not dispatchable(lane):
                out.append(finding("LIVE_RUNS_FOR_UNARMED_LANE", lid, f"state {lane['state']} but live RUN_DONE "
                                   "in the window", runs=info.get("count"), last=info.get("last")))
        for lid, lane in lanes.items():
            cad = lane["legacy"].get("expected_cadence_hours")
            if (lane["schedule"]["mode"] == "live" and dispatchable(lane) and lid not in live
                    and isinstance(cad, (int, float)) and 0 < cad <= window_hours / 2):
                out.append(finding("N8N_LIVE_NO_RECENT_RUN", lid, "n8n live lane with no live RUN_DONE in the window",
                                   cadence_hours=cad, window_hours=window_hours))
    return out


def counts_by_code(findings: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    c: dict[str, int] = {}
    for f in findings:
        c[f["code"]] = c.get(f["code"], 0) + 1
    return dict(sorted(c.items()))


def fingerprint(findings: Iterable[Mapping[str, Any]]) -> str:
    keys = sorted(f"{f['code']}|{f.get('lane_id')}|{f['evidence'].get('line') or f['evidence'].get('workflow_id') or ''}"
                  for f in findings)
    return sha256_text("\n".join(keys))[:16]
