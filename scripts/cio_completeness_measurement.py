#!/usr/bin/env python3
"""Measure CIO produced-vs-surfaced completeness without manufacturing runtime proof.

Schema: CIOCompletenessMeasurement@v2

produced (enumerated, not labelled by hand)
    route:<path>        every CIO-family backend GET route the census parsed from
                        the api_v2 dispatch (alias spellings collapse to one item)
    capability:<name>   every capability-coverage row from the operator evidence
    schema:<Name@vN>    every contract schema literal defined in scripts/lib/cio_*.py

operator_visible
    route       consumed by a rendered component (census consumer mapping: the
                import closure of the routed CIO/Advisory/Agents/Hermes/RI pages)
    capability  the operator-evidence route is consumed by a component that
                renders capability rows
    schema      emitted by the handler (or its first delegated lib function) of a
                consumed route

produced_not_surfaced = produced - operator_visible, NAMED.  It is reported as
measured; nothing is tuned to reach zero.

surfaced_not_runtime_proven
    surfaced capability rows whose runtime state is not LIVE, with the label the
    UI renders for them (the CoverageRow shows the state verbatim), plus
    research artifacts not USED_IN_JUDGMENT.  Surfaced routes and schemas have no
    runtime capture in this measurement and are listed separately as
    surfaced_runtime_unmeasured (never counted as LIVE).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
NO_CONSUMER_REASON = "Source-side acceptance artifact; live release consumption is intentionally not claimed."
SCHEMA = "CIOCompletenessMeasurement@v2"
DEFAULT_ARTIFACT = Path("docs/_evidence/cio_completion/completeness_20261002.json")
sys.path.insert(0, str(ROOT))

from scripts.cio_api_contract_census import build_census  # noqa: E402

SCHEMA_DEF_RE = re.compile(
    r"(?:^[A-Z_][A-Z0-9_]*SCHEMA[A-Z0-9_]*\s*=\s*|[\"'](?:schema|schema_version|contract)[\"']\s*:\s*)[\"']([A-Z][A-Za-z0-9]+@v\d+)[\"']",
    re.MULTILINE,
)
OPERATOR_EVIDENCE_ROUTE = "/api/v3/cio/operator-evidence"
CIO_FAMILY = "CIO"


def produced_schemas(root: Path) -> dict[str, list[str]]:
    """schema -> defining files (scripts/lib/cio_*.py)."""
    out: dict[str, list[str]] = {}
    for path in sorted((root / "scripts" / "lib").glob("cio_*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for name in sorted(set(SCHEMA_DEF_RE.findall(text))):
            out.setdefault(name, []).append(str(path.relative_to(root)))
    return out


def _capability_rows(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    return list(((evidence.get("blocks") or {}).get("capability_coverage") or {}).get("rows") or [])


def build_measurement(
    *,
    now: Optional[str] = None,
    root: Path | str | None = None,
    census: Optional[dict[str, Any]] = None,
    evidence: Optional[dict[str, Any]] = None,
    schemas: Optional[dict[str, list[str]]] = None,
) -> dict[str, Any]:
    root = Path(root) if root else ROOT
    composed = now or datetime.now(timezone.utc).isoformat()
    census = census if census is not None else build_census(root)
    if evidence is None:
        from scripts.lib.cio_operator_evidence import build_operator_evidence

        evidence = build_operator_evidence(now=composed)
    schemas = schemas if schemas is not None else produced_schemas(root)

    endpoints = [e for e in census.get("endpoints") or [] if e.get("method", "GET") == "GET"]
    backend = census.get("backend_routes") or []

    # ── produced ──────────────────────────────────────────────────────────────
    produced: dict[str, dict[str, Any]] = {}
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in backend:
        if r.get("family") != CIO_FAMILY or r.get("kind") == "PREFIX" or r.get("method") == "POST":
            continue
        groups.setdefault(r.get("dispatch_ref") or r["route"], []).append(r)
    for ref, rows in groups.items():
        # canonical spelling = first one the dispatch lists (rows keep census order)
        canonical = rows[0]
        name = canonical["route"].rstrip("/") + ("/*" if canonical.get("kind") == "SUBPREFIX" else "")
        key = f"route:{name}"
        if key in produced:
            key = f"{key}#{str(canonical.get('producer') or ref).split('::')[-1]}"
        produced[key] = {
            "kind": "route", "route": canonical["route"], "aliases": sorted({r["route"] for r in rows} - {canonical["route"]}),
            "producer": canonical.get("producer"), "dispatch_ref": ref,
        }
    cap_rows = _capability_rows(evidence)
    for row in cap_rows:
        produced[f"capability:{row.get('capability')}"] = {
            "kind": "capability", "state": str(row.get("state") or row.get("current_status") or "UNKNOWN"),
            "producer": row.get("contract") or row.get("producer"),
        }
    for name, files in schemas.items():
        produced[f"schema:{name}"] = {"kind": "schema", "defined_in": files}

    # ── operator visible ──────────────────────────────────────────────────────
    consumed_refs = {e.get("dispatch_ref") for e in endpoints if e.get("dispatch_ref") and e.get("match") not in ("NO_HANDLER",)}
    consumed_routes = {e.get("route") for e in endpoints}
    consumers_by_route: dict[str, set[str]] = {}
    for e in endpoints:
        consumers_by_route.setdefault(e["route"], set()).add(str(e.get("consumer_ref", "")).split(":")[0])
    visible: dict[str, dict[str, Any]] = {}
    for key, item in produced.items():
        if item["kind"] != "route":
            continue
        routes = {item["route"], *item["aliases"]}
        if item["dispatch_ref"] in consumed_refs or routes & consumed_routes:
            refs = sorted({str(e.get("consumer_ref")) for e in endpoints if e.get("dispatch_ref") == item["dispatch_ref"] or e.get("route") in routes})
            visible[key] = {"via": refs}

    evidence_consumers = sorted(consumers_by_route.get(OPERATOR_EVIDENCE_ROUTE, set()))
    renders_capabilities = any(
        re.search(r"capability_coverage|\.capability\b", (root / f).read_text(encoding="utf-8", errors="replace"))
        for f in evidence_consumers if (root / f).is_file()
    )
    if renders_capabilities:
        for row in cap_rows:
            visible[f"capability:{row.get('capability')}"] = {"via": [f"{OPERATOR_EVIDENCE_ROUTE} -> {c}" for c in evidence_consumers]}

    emitted: dict[str, set[str]] = {}
    for e in endpoints:
        for name in e.get("response_schemas") or []:
            emitted.setdefault(name, set()).add(e["route"])
    for name in schemas:
        if name in emitted:
            visible[f"schema:{name}"] = {"via": sorted(emitted[name])}

    produced_keys = set(produced)
    visible_keys = set(visible) & produced_keys
    produced_not_surfaced = sorted(produced_keys - visible_keys)

    # ── runtime proof of surfaced items ───────────────────────────────────────
    unproven: list[dict[str, Any]] = []
    for row in cap_rows:
        key = f"capability:{row.get('capability')}"
        state = str(row.get("state") or row.get("current_status") or "UNKNOWN")
        if key in visible_keys and state != "LIVE":
            unproven.append({
                "name": key,
                "runtime_state": state,
                "ui_label": state,  # CioOperatorEvidencePanel CoverageRow renders the state verbatim
                "ui_surface": "CIO › Operator evidence › Capability coverage",
                "reason": row.get("reason") or "runtime proof unavailable",
            })
    for artifact in ((evidence.get("blocks") or {}).get("research") or {}).get("artifacts") or []:
        if artifact.get("status") != "USED_IN_JUDGMENT":
            unproven.append({
                "name": f"research:{artifact.get('artifact_id')}",
                "runtime_state": artifact.get("status") or "UNKNOWN",
                "ui_label": artifact.get("status") or "UNKNOWN",
                "ui_surface": "CIO › Research provenance",
                "reason": "canonical use receipt does not prove judgment use",
            })
    runtime_unmeasured = sorted(k for k in visible_keys if not k.startswith("capability:"))

    counts = {state: 0 for state in ("LIVE", "PARTIAL", "UNWIRED", "DARK", "UNKNOWN")}
    for row in cap_rows:
        state = str(row.get("state") or row.get("current_status") or "UNKNOWN")
        counts[state] = counts.get(state, 0) + 1
    by_kind = {
        kind: {
            "produced": sum(1 for k in produced_keys if k.startswith(kind + ":")),
            "operator_visible": sum(1 for k in visible_keys if k.startswith(kind + ":")),
            "produced_not_surfaced": sum(1 for k in produced_not_surfaced if k.startswith(kind + ":")),
        }
        for kind in ("route", "capability", "schema")
    }
    return {
        "schema": SCHEMA,
        "authority": "READ_ONLY_ADVISORY",
        "composition_as_of": composed,
        "census_schema": census.get("schema"),
        "serving_sha": census.get("serving_sha"),
        "method": {
            "produced": "census CIO-family backend GET routes (alias groups) + capability coverage rows + Name@vN schemas defined in scripts/lib/cio_*.py",
            "operator_visible": "route consumed by a component in the routed pages' import closure; capability rows via a consumer of /api/v3/cio/operator-evidence that renders them; schema emitted by a consumed route's handler or its first delegated lib function",
            "limitations": [
                "Schemas nested deeper than one delegation level are reported as not surfaced even when a consumed payload may embed them.",
                "Static source only; a surfaced route/schema has no runtime capture here (surfaced_runtime_unmeasured).",
            ],
        },
        "cio_capabilities_produced": sorted(produced_keys),
        "cio_capabilities_operator_visible": sorted(visible_keys),
        "produced_not_surfaced": produced_not_surfaced,
        "surfaced_not_runtime_proven": unproven,
        "surfaced_runtime_unmeasured": runtime_unmeasured,
        "by_kind": by_kind,
        "visibility_evidence": {k: visible[k] for k in sorted(visible_keys)},
        "critical_edges_live": counts["LIVE"],
        "critical_edges_partial": counts["PARTIAL"],
        "critical_edges_unwired": counts["UNWIRED"],
        "critical_edges_dark": counts["DARK"],
        "critical_edges_unknown": counts["UNKNOWN"],
        "counts": {
            "produced": len(produced_keys),
            "operator_visible": len(visible_keys),
            "produced_not_surfaced": len(produced_not_surfaced),
            "surfaced_not_runtime_proven": len(unproven),
            "surfaced_runtime_unmeasured": len(runtime_unmeasured),
        },
        "source_acceptance": {
            "produced_not_surfaced_zero": not produced_not_surfaced,
            "runtime_unproven_items_labelled": all(item.get("ui_label") for item in unproven),
            "runtime_unproven_count": len(unproven),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--write", nargs="?", const=str(DEFAULT_ARTIFACT), default=None,
                        help=f"also write the JSON artifact (default {DEFAULT_ARTIFACT})")
    args = parser.parse_args()
    report = build_measurement()
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.write:
        out = ROOT / args.write if not Path(args.write).is_absolute() else Path(args.write)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
    print(text)
    if not args.json:
        for key, value in report["counts"].items():
            print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
