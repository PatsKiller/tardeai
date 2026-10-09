#!/usr/bin/env python3
"""Measure CIO produced-vs-surfaced completeness without manufacturing runtime proof.

Schema: CIOCompletenessMeasurement@v2

produced (enumerated, not labelled by hand)
    route:<path>        every CIO-family backend GET route the census parsed from
                        the api_v2 dispatch (alias spellings collapse to one item)
    capability:<name>   every capability-coverage row from the operator evidence
    schema:<Name@vN>    every contract schema defined in scripts/lib/cio_*.py
                        (any *SCHEMA* constant incl. bare SCHEMA, or a schema /
                        schema_version / contract key); producer-catalog rows are
                        catalog_references, not definitions

operator_visible
    route       fetched (result not discarded) by a rendered component, or its
                handler's output embedded at a key path the consumer reads
    capability  the operator-evidence route is consumed by a component that
                renders capability rows
    schema      its own block lands, through transitive payload flow
                (scripts/cio_payload_flow.py), at a key path whose every segment
                the consumer (or a JSX child it hands the payload to) reads;
                record schemas only through a verified record edge

produced_not_surfaced = produced - operator_visible, NAMED.  Every such item must
be classified in config/cio_surface_classification.json; anything not classified
NOT_OPERATOR_RELEVANT / RETIRE_CANDIDATE is produced_not_surfaced_operator_relevant
(target 0).  Reported as measured; nothing is tuned to reach zero.

surfaced_not_runtime_proven
    surfaced capability rows whose runtime state is not LIVE, with the label the
    UI renders for them (the CoverageRow shows the state verbatim), plus
    research artifacts not USED_IN_JUDGMENT.  Surfaced routes and schemas have no
    runtime capture in this measurement and are listed separately as
    surfaced_runtime_unmeasured (never counted as LIVE).
"""
from __future__ import annotations

import argparse
import ast
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
CLASSIFICATION_PATH = Path("config/cio_surface_classification.json")
CLASSES = ("SURFACE", "NOT_OPERATOR_RELEVANT", "RETIRE_CANDIDATE")
MIN_REASON_CHARS = 60
sys.path.insert(0, str(ROOT))

from scripts.cio_api_contract_census import build_census  # noqa: E402
from scripts.cio_payload_flow import PayloadFlow, consumer_reads_path  # noqa: E402

SCHEMA_DEF_RE = re.compile(
    r"(?:^(?:[A-Z_][A-Z0-9_]*)?SCHEMA[A-Z0-9_]*\s*=\s*|[\"'](?:schema|schema_version|contract)[\"']\s*:\s*)[\"']([A-Z][A-Za-z0-9]+@v\d+)[\"']",
    re.MULTILINE,
)
OPERATOR_EVIDENCE_ROUTE = "/api/v3/cio/operator-evidence"
CIO_FAMILY = "CIO"


def _catalog_literal_lines(tree: ast.Module) -> set[int]:
    """Lines of schema literals that sit in a row of a module-level collection of dicts
    (a producer catalog such as ``_PRODUCERS = ({"schema": "X@v1", ...}, ...)``).  Such a
    row names ANOTHER module's contract; it is a reference, not a definition."""
    lines: set[int] = set()
    for node in tree.body:
        value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
        if isinstance(value, (ast.Tuple, ast.List, ast.Set)):
            for elt in value.elts:
                if isinstance(elt, ast.Dict):
                    for v in elt.values:
                        if isinstance(v, ast.Constant) and isinstance(v.value, str):
                            lines.add(v.lineno)
    return lines


def schema_definitions(root: Path) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """(defined, catalog_references): schema -> files.  A schema whose only literal in
    scripts/lib/cio_*.py is a producer-catalog row is a catalog reference.
    Explicit producer_path rows also verify classified schemas outside the CIO library namespace.
    A declaration alone is not production evidence: the named source must define that schema.
    """
    defined: dict[str, list[str]] = {}
    references: dict[str, list[str]] = {}
    paths = set((root / "scripts" / "lib").glob("cio_*.py"))
    external: dict[Path, set[str]] = {}
    try:
        entries = json.loads((root / CLASSIFICATION_PATH).read_text(encoding="utf-8")).get("entries", [])
    except (OSError, ValueError):
        entries = []
    for row in entries:
        name, source = row.get("name", ""), row.get("producer_path")
        if row.get("kind") != "schema" or not name.startswith("schema:") or not isinstance(source, str):
            continue
        rel = Path(source)
        if rel.is_absolute() or ".." in rel.parts or not rel.parts or rel.parts[0] != "scripts" or rel.suffix != ".py":
            continue
        path = root / rel
        if path not in paths and path.is_file() and path.resolve().is_relative_to(root.resolve()):
            external.setdefault(path, set()).add(name.removeprefix("schema:"))
    for path in sorted(paths | external.keys()):
        text = path.read_text(encoding="utf-8", errors="replace")
        try:
            catalog = _catalog_literal_lines(ast.parse(text))
        except SyntaxError:
            catalog = set()
        rel = str(path.relative_to(root))
        for m in SCHEMA_DEF_RE.finditer(text):
            if path in external and m.group(1) not in external[path]:
                continue
            line = text.count("\n", 0, m.start(1)) + 1
            bucket = references if line in catalog else defined
            files = bucket.setdefault(m.group(1), [])
            if rel not in files:
                files.append(rel)
    references = {k: v for k, v in references.items() if k not in defined}
    return defined, references


def produced_schemas(root: Path) -> dict[str, list[str]]:
    """schema -> defining files (CIO libraries and declared external producers), catalogs excluded."""
    return schema_definitions(root)[0]


def _capability_rows(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    return list(((evidence.get("blocks") or {}).get("capability_coverage") or {}).get("rows") or [])


def _flow_producer(producer: Optional[str]) -> Optional[str]:
    if not producer or "::" not in producer or "handle[inline:" in producer:
        return None
    return producer


_JSX_OPEN_RE = re.compile(r"<([A-Z][A-Za-z0-9_]*)\b")
_IMPORT_LOCAL_RE = re.compile(r"""import\s+(?:(\w+)|\{([^}]*)\})\s+from\s+['"](\.{1,2}/[^'"]+)['"]""")


def _jsx_attrs(text: str, start: int) -> str:
    """Attribute text of the JSX element opening at ``start`` (stops at the tag's '>')."""
    depth = 0
    i = start
    while i < len(text) and i - start < 2000:
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        elif ch == ">" and depth == 0:
            return text[start:i]
        i += 1
    return text[start:i]


def render_closure_text(root: Path, consumer: str, bound_names: list[str]) -> str:
    """Consumer source plus the local component files the fetched value is handed to.

    ``const { data } = useApi(...)`` then ``<Child home={data} />`` (or via a one-hop
    alias ``const home = data``) renders the payload inside Child, so Child's property
    reads count.  Only direct JSX children imported from a relative path are followed.
    """
    path = root / consumer
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    names = {n for n in bound_names if n and n not in ("loading", "error", "refetch", "stale", "refreshing")}
    for n in list(names):
        for m in re.finditer(rf"(?:const|let)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*(?:\(?\s*){re.escape(n)}\b", text):
            names.add(m.group(1))
    if not names:
        return text
    imports: dict[str, str] = {}
    for m in _IMPORT_LOCAL_RE.finditer(text):
        spec = m.group(3)
        for local in ([m.group(1)] if m.group(1) else [x.split(" as ")[-1].strip() for x in m.group(2).split(",")]):
            if local:
                imports[local] = spec
    from scripts.cio_api_contract_census import _resolve_import

    extra: list[str] = []
    seen: set[Path] = set()
    for m in _JSX_OPEN_RE.finditer(text):
        comp = m.group(1)
        if comp not in imports:
            continue
        attrs = _jsx_attrs(text, m.end())
        if not any(re.search(rf"\{{\s*{re.escape(n)}\b", attrs) for n in names):
            continue
        child = _resolve_import(path, imports[comp])
        if child and child not in seen:
            seen.add(child)
            extra.append(child.read_text(encoding="utf-8", errors="replace"))
    return "\n".join([text, *extra])


def deep_visibility(endpoints: list[dict[str, Any]], flow: PayloadFlow, root: Path) -> dict[str, Any]:
    """origin ('schema:X' / 'fn:mod.py::f') -> ['route#key.path -> consumer file:line', ...].

    An origin counts only at a key path the consumer file reads segment by segment.
    Endpoints whose handler the flow analysis cannot resolve are returned separately.
    """
    visible: dict[str, set[str]] = {}
    ignored: dict[str, set[str]] = {}
    unresolved: list[dict[str, Any]] = []
    texts: dict[tuple, str] = {}
    for e in endpoints:
        if e.get("match") == "NO_HANDLER":
            continue
        producer = _flow_producer(e.get("producer"))
        placements = flow.placements(producer) if producer else {}
        if not placements:
            unresolved.append(e)
            continue
        consumer = str(e.get("consumer_ref") or "").split(":")[0]
        key = (consumer, tuple(e.get("bound_names") or ()))
        if key not in texts:
            texts[key] = render_closure_text(root, consumer, list(e.get("bound_names") or ()))
        text = texts[key]
        for origin, paths in placements.items():
            read = sorted((p for p in paths if consumer_reads_path(text, p)), key=lambda p: (len(p), p))
            if read:
                visible.setdefault(origin, set()).add(f"{e['route']}#{'.'.join(read[0]) or '(root)'} -> {e.get('consumer_ref')}")
            else:
                shortest = sorted(paths, key=lambda p: (len(p), p))[0]
                ignored.setdefault(origin, set()).add(f"{e['route']}#{'.'.join(shortest)} not read by {consumer}")
    return {
        "visible": {k: sorted(v) for k, v in visible.items()},
        "fetched_but_ignored": {k: sorted(v) for k, v in ignored.items() if k not in visible},
        "unresolved_endpoints": unresolved,
    }


def load_classification(root: Path) -> dict[str, Any]:
    path = root / CLASSIFICATION_PATH
    if not path.is_file():
        return {"entries": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _fn_source(root: Path, ref: str) -> str:
    """Source text of ``mod.py::func`` under scripts/ ('' when unresolvable)."""
    if "::" not in ref:
        return ""
    rel, func = ref.split("::", 1)
    path = root / "scripts" / rel
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return ""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func.split(".")[-1]:
            return "\n".join(text.splitlines()[node.lineno - 1:node.end_lineno])
    return ""


def verify_record_edge(
    name: str, edge: dict[str, Any], endpoints: list[dict[str, Any]], flow: PayloadFlow, root: Path,
) -> dict[str, Any]:
    """A record schema is stamped by a WRITER into a store and served back by a READER
    without the reader naming the schema, so payload flow alone cannot see it.  The
    classification may declare that edge; every link except "reader reads the writer's
    store" is checked here, and that link must at least share a store-file literal:

      1. the route is fetched by a rendered component (result not discarded);
      2. the reader function lands at a prefix of ``path`` in the route's payload;
      3. the consumer reads every segment of ``path``;
      4. the writer function names the schema (literal or module constant);
      5. the store basename is a literal in the reader/route module AND in the writer
         module or a module that calls the writer.
    """
    schema = name.split(":", 1)[1]
    checks: dict[str, bool] = {}
    route = str(edge.get("route") or "")
    path = tuple(edge.get("path") or ())
    reader = str(edge.get("reader") or "")
    writer = str(edge.get("writer") or "")
    store = str(edge.get("store") or "")
    hits = [e for e in endpoints if e.get("route") == route and e.get("match") != "NO_HANDLER"]
    checks["route_consumed"] = bool(hits)
    placed = read = False
    for e in hits:
        producer = _flow_producer(e.get("producer"))
        prefixes = flow.placements(producer).get(f"fn:{reader}", set()) if producer else set()
        if any(path[:len(pfx)] == pfx for pfx in prefixes):
            placed = True
            consumer = str(e.get("consumer_ref") or "").split(":")[0]
            if consumer_reads_path(render_closure_text(root, consumer, list(e.get("bound_names") or ())), path):
                read = True
    checks["reader_placed_at_path"] = placed
    checks["consumer_reads_path"] = read
    writer_src = _fn_source(root, writer)
    writer_mod = root / "scripts" / writer.split("::", 1)[0] if "::" in writer else None
    mod_text = writer_mod.read_text(encoding="utf-8", errors="replace") if writer_mod and writer_mod.is_file() else ""
    consts = {m.group(1) for m in re.finditer(r"^([A-Z_][A-Z0-9_]*)\s*=\s*[\"']" + re.escape(schema) + r"[\"']", mod_text, re.M)}
    checks["writer_names_schema"] = bool(writer_src) and (schema in writer_src or any(re.search(rf"\b{c}\b", writer_src) for c in consts))
    reader_mod = root / "scripts" / reader.split("::", 1)[0] if "::" in reader else None
    reader_side = [reader_mod] + [root / "scripts" / str(e.get("producer") or "").split("::", 1)[0] for e in hits]
    literal = re.compile(r"[\"'][^\"'\n]*\b" + re.escape(store) + r"[\"']") if store else None
    def has_store(p: Optional[Path]) -> bool:
        return bool(literal and p and p.is_file() and literal.search(p.read_text(encoding="utf-8", errors="replace")))
    writer_side: list[Path] = [writer_mod] if writer_mod else []
    if "::" in writer:
        fn = writer.split("::", 1)[1].split(".")[-1]
        writer_side += [p for p in (root / "scripts").rglob("*.py")
                        if "tests" not in p.parts and re.search(rf"\b{re.escape(fn)}\s*\(", p.read_text(encoding="utf-8", errors="replace"))]
    checks["store_shared"] = any(has_store(p) for p in reader_side) and any(has_store(p) for p in writer_side)
    return {"name": name, **{k: edge.get(k) for k in ("route", "path", "reader", "writer", "store")},
            "checks": checks, "verified": all(checks.values())}


def classification_issues(entries: list[dict[str, Any]]) -> list[str]:
    """Structural gate on the classification file: class, specific reason, owner."""
    issues: list[str] = []
    seen_reasons: dict[str, str] = {}
    names: set[str] = set()
    for row in entries:
        name = str(row.get("name") or "")
        if not name:
            issues.append("entry without name")
            continue
        if name in names:
            issues.append(f"{name}: duplicate entry")
        names.add(name)
        if row.get("classification") not in CLASSES:
            issues.append(f"{name}: classification must be one of {CLASSES}")
        if row.get("kind") != name.split(":", 1)[0]:
            issues.append(f"{name}: kind must match the name prefix")
        reason = " ".join(str(row.get("reason") or "").split())
        if len(reason) < MIN_REASON_CHARS:
            issues.append(f"{name}: reason shorter than {MIN_REASON_CHARS} chars (blanket reasons are not accepted)")
        elif reason.lower() in seen_reasons:
            issues.append(f"{name}: reason duplicates {seen_reasons[reason.lower()]} (each item needs its own reason)")
        else:
            seen_reasons[reason.lower()] = name
        if not str(row.get("owner_hint") or "").strip():
            issues.append(f"{name}: owner_hint required")
    return issues


def build_measurement(
    *,
    now: Optional[str] = None,
    root: Path | str | None = None,
    census: Optional[dict[str, Any]] = None,
    evidence: Optional[dict[str, Any]] = None,
    schemas: Optional[dict[str, list[str]]] = None,
    flow: Optional[PayloadFlow] = None,
    classification: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    root = Path(root) if root else ROOT
    composed = now or datetime.now(timezone.utc).isoformat()
    census = census if census is not None else build_census(root)
    if evidence is None:
        from scripts.lib.cio_operator_evidence import build_operator_evidence

        evidence = build_operator_evidence(now=composed)
    if schemas is None:
        schemas, catalog_refs = schema_definitions(root)
    else:
        catalog_refs = {}

    # A GET whose result the component provably discards surfaces nothing.
    endpoints = [e for e in census.get("endpoints") or [] if e.get("method", "GET") == "GET" and e.get("result_used") is not False]
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

    # Schemas and embedded routes: follow delegation transitively (handler -> api getter ->
    # lib builder ...) with the key path each block lands at, and count a block only when
    # the consuming component reads every segment of that path (fetched-but-ignored != surfaced).
    flow = flow if flow is not None else PayloadFlow(root)
    deep = deep_visibility(endpoints, flow, root)
    route_by_producer: dict[str, list[str]] = {}
    for key, item in produced.items():
        if item["kind"] == "route" and item.get("producer"):
            route_by_producer.setdefault(str(item["producer"]), []).append(key)
    for origin, vias in deep["visible"].items():
        if origin.startswith("schema:") and origin in produced:
            visible.setdefault(origin, {"via": []})["via"] = sorted(set(visible.get(origin, {}).get("via", [])) | set(vias))
        elif origin.startswith("fn:"):
            for key in route_by_producer.get(origin[3:], []):
                if key not in visible:
                    visible[key] = {"via": sorted(vias), "method": "EMBEDDED_IN_CONSUMED_PAYLOAD"}
    for name in schemas:
        key = f"schema:{name}"
        if key in visible or key not in produced:
            continue
        # Fallback only for handlers the flow analysis cannot resolve (inline dispatch blocks).
        for e in deep["unresolved_endpoints"]:
            if name in (e.get("response_schemas") or []):
                visible[key] = {"via": [f"{e['route']} (census direct; handler not flow-resolvable)"]}

    # ── classification (config/cio_surface_classification.json) ─────────────
    classification = classification if classification is not None else load_classification(root)
    entries = list(classification.get("entries") or [])
    by_name = {str(r.get("name")): r for r in entries if r.get("name")}
    record_edges: list[dict[str, Any]] = []
    for name, row in sorted(by_name.items()):
        if row.get("record_edge") and name in produced and name not in visible:
            result = verify_record_edge(name, row["record_edge"], endpoints, flow, root)
            record_edges.append(result)
            if result["verified"]:
                visible[name] = {"via": [f"{result['route']}#{'.'.join(result['path'])} (record edge: {result['writer']} -> {result['store']} -> {result['reader']})"],
                                 "method": "RECORD_EDGE_VERIFIED"}

    produced_keys = set(produced)
    visible_keys = set(visible) & produced_keys
    produced_not_surfaced = sorted(produced_keys - visible_keys)

    unclassified = [k for k in produced_not_surfaced if k not in by_name]
    not_relevant = [
        {"name": k, "reason": by_name[k]["reason"], "owner_hint": by_name[k].get("owner_hint")}
        for k in produced_not_surfaced if by_name.get(k, {}).get("classification") == "NOT_OPERATOR_RELEVANT"
    ]
    retire = [
        {"name": k, "reason": by_name[k]["reason"], "owner_hint": by_name[k].get("owner_hint")}
        for k in produced_not_surfaced if by_name.get(k, {}).get("classification") == "RETIRE_CANDIDATE"
    ]
    # Conservative default: anything not classified away is operator-relevant.
    operator_relevant = [
        k for k in produced_not_surfaced
        if by_name.get(k, {}).get("classification") not in ("NOT_OPERATOR_RELEVANT", "RETIRE_CANDIDATE")
    ]
    stale = sorted(
        [f"{n}: not produced" for n in by_name if n not in produced]
        + [f"{n}: surfaced but classified {by_name[n].get('classification')}" for n in by_name
           if n in visible_keys and by_name[n].get("classification") != "SURFACE"]
        + [f"{n}: surfaced without a record edge; drop the NOT-YET-SURFACED entry" for n in by_name
           if n in visible_keys and by_name[n].get("classification") == "SURFACE" and not by_name[n].get("record_edge")]
    )
    issues = classification_issues(entries)

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
            "produced_not_surfaced_operator_relevant": sum(1 for k in operator_relevant if k.startswith(kind + ":")),
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
            "produced": "census CIO-family backend GET routes (alias groups) + capability coverage rows + Name@vN schemas defined in scripts/lib/cio_*.py or explicitly classified producer_path sources (any *SCHEMA* constant incl. bare SCHEMA, or a schema/schema_version/contract key); literals inside module-level producer-catalog rows are catalog_references, not definitions",
            "operator_visible": "route: fetched by a component in the routed pages' import closure with its result not discarded, or its handler's output embedded (envelope or one key below it) at a key path the consumer reads; capability rows via a consumer of /api/v3/cio/operator-evidence that renders them; schema: its own block lands (payload flow followed transitively handler -> api getter -> lib builder, with key paths) at a path whose every segment the consumer, or a local child component it hands the payload to as a JSX prop, reads as a property; record schemas only through a verified record edge",
            "classification": "config/cio_surface_classification.json: every produced_not_surfaced item must be classified; NOT_OPERATOR_RELEVANT and RETIRE_CANDIDATE need a specific reason; anything else counts as produced_not_surfaced_operator_relevant",
            "limitations": [
                "Static source only; a surfaced route/schema has no runtime capture here (surfaced_runtime_unmeasured).",
                "Payload flow over-approximates comprehensions and container-preserving calls (dict/list/sorted/copy) and does not follow calls through class instances.",
                "A consumer 'reads' a key when the file (or a JSX child receiving the fetched value) contains .key / ?.key / ['key'] / destructuring; that is file-scoped, not data-flow-scoped.",
                "Record edges declare reader-reads-writer's-store; that link is checked only by a shared store-file literal.",
            ],
        },
        "classification_path": str(CLASSIFICATION_PATH),
        "produced_not_surfaced_operator_relevant": operator_relevant,
        "not_operator_relevant": not_relevant,
        "retire_candidates": retire,
        "unclassified": unclassified,
        "classification_stale": stale,
        "classification_issues": issues,
        "record_edges": record_edges,
        "visibility_methods": {
            method: sorted(k for k in visible_keys if visible[k].get("method", "DIRECT_OR_PAYLOAD_FLOW") == method)
            for method in sorted({visible[k].get("method", "DIRECT_OR_PAYLOAD_FLOW") for k in visible_keys})
        },
        "catalog_references": catalog_refs,
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
            "produced_not_surfaced_operator_relevant": len(operator_relevant),
            "not_operator_relevant": len(not_relevant),
            "retire_candidates": len(retire),
            "unclassified": len(unclassified),
        },
        "source_acceptance": {
            "produced_not_surfaced_zero": not produced_not_surfaced,
            "operator_relevant_not_surfaced_zero": not operator_relevant,
            "every_non_surfaced_item_classified": not unclassified,
            "classification_well_formed": not issues and not stale,
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
