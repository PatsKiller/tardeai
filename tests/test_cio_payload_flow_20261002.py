"""Payload-flow census: nested delegation counts, fetched-but-ignored does not.

Fixture trees are synthetic (tmp_path): a route handler delegates two levels
deep (handler -> api getter -> lib builder) and the consumer component either
reads the key the schema lands at or fetches the route and ignores it.
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts.cio_completeness_measurement import (
    build_measurement,
    classification_issues,
    deep_visibility,
    render_closure_text,
    verify_record_edge,
    _function_reaches_store,
)
from scripts.cio_payload_flow import PayloadFlow, consumer_reads_path

NOW = "2026-10-02T16:00:00+00:00"


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _tree(tmp_path: Path, consumer_reads: bool) -> Path:
    _write(tmp_path, "scripts/lib/cio_deep.py", '''
DEEP_SCHEMA = "CIODeepBlock@v1"

def _rows():
    return [{"symbol": "AAA"}]

def build_deep():
    return {"schema": DEEP_SCHEMA, "rows": _rows(), "state": "SHADOW"}

def build_ignored():
    return {"schema": "CIOIgnoredBlock@v1", "n": 1}
''')
    _write(tmp_path, "scripts/api_fx.py", '''
def get_section():
    from scripts.lib.cio_deep import build_deep, build_ignored
    return {"ok": True, "deep": build_deep(), "noise": build_ignored()}

def get_bundle():
    section = get_section()
    return {"schema": "CIOBundle@v1", "section": section.get("deep"), "other": section}
''')
    reads = "data?.section?.rows.length" if consumer_reads else "data?.unrelated"
    _write(tmp_path, "apps/command-center-v3/src/components/Bundle.tsx",
           f"export default function B() {{ const {{ data }} = useApi('/api/v3/cio/bundle'); return <div>{{{reads}}}</div> }}\n")
    return tmp_path


def _endpoint(route: str = "/api/v3/cio/bundle", producer: str = "api_fx.py::get_bundle") -> dict:
    return {"route": route, "method": "GET", "match": "EXACT", "producer": producer,
            "consumer_ref": "apps/command-center-v3/src/components/Bundle.tsx:1", "bound_names": ["data"],
            "dispatch_ref": "scripts/api_v2.py:1", "result_used": True, "response_schemas": ["CIOBundle@v1"]}


def test_nested_delegation_places_schema_at_its_key_path(tmp_path):
    root = _tree(tmp_path, consumer_reads=True)
    placements = PayloadFlow(root).placements("api_fx.py::get_bundle")
    # handler -> api getter -> lib builder, two levels below the route handler
    assert ("section",) in placements["schema:CIODeepBlock@v1"]
    assert placements["schema:CIOBundle@v1"] == {()}
    # the getter's whole envelope is under "other"; its ignored block lands at other.noise
    assert ("other", "noise") in placements["schema:CIOIgnoredBlock@v1"]
    assert ("section",) in placements["fn:api_fx.py::get_section"]


def test_nested_schema_counts_when_the_component_reads_the_block(tmp_path):
    root = _tree(tmp_path, consumer_reads=True)
    deep = deep_visibility([_endpoint()], PayloadFlow(root), root)
    assert "schema:CIODeepBlock@v1" in deep["visible"]
    assert "schema:CIOBundle@v1" in deep["visible"]
    # fetched, but the component never reads other.noise
    assert "schema:CIOIgnoredBlock@v1" not in deep["visible"]
    assert "schema:CIOIgnoredBlock@v1" in deep["fetched_but_ignored"]


def test_fetched_but_ignored_block_is_not_surfaced(tmp_path):
    root = _tree(tmp_path, consumer_reads=False)
    deep = deep_visibility([_endpoint()], PayloadFlow(root), root)
    assert "schema:CIODeepBlock@v1" not in deep["visible"]
    assert any("not read by" in v for v in deep["fetched_but_ignored"]["schema:CIODeepBlock@v1"])


def test_measurement_counts_nested_route_and_schema_and_drops_discarded_fetch(tmp_path):
    root = _tree(tmp_path, consumer_reads=True)
    backend = [
        {"route": "/api/v3/cio/bundle", "kind": "EXACT", "method": "GET", "producer": "api_fx.py::get_bundle",
         "dispatch_ref": "scripts/api_v2.py:1", "family": "CIO"},
        {"route": "/api/v3/cio/section", "kind": "EXACT", "method": "GET", "producer": "api_fx.py::get_section",
         "dispatch_ref": "scripts/api_v2.py:2", "family": "CIO"},
    ]
    census = {"schema": "CIOApiContractCensus@v2", "endpoints": [_endpoint()], "backend_routes": backend}
    schemas = {"CIODeepBlock@v1": ["scripts/lib/cio_deep.py"], "CIOIgnoredBlock@v1": ["scripts/lib/cio_deep.py"]}
    report = build_measurement(now=NOW, root=root, census=census, evidence={"blocks": {}}, schemas=schemas,
                               classification={"entries": []})
    assert "schema:CIODeepBlock@v1" in report["cio_capabilities_operator_visible"]
    # /section is never fetched, but get_section's output is embedded at bundle.section and read
    assert "route:/api/v3/cio/section" in report["cio_capabilities_operator_visible"]
    assert report["visibility_evidence"]["route:/api/v3/cio/section"]["method"] == "EMBEDDED_IN_CONSUMED_PAYLOAD"
    assert report["produced_not_surfaced"] == ["schema:CIOIgnoredBlock@v1"]
    # unclassified -> counted as operator-relevant (conservative) and named
    assert report["unclassified"] == ["schema:CIOIgnoredBlock@v1"]
    assert report["produced_not_surfaced_operator_relevant"] == ["schema:CIOIgnoredBlock@v1"]

    discarded = dict(_endpoint(), result_used=False)
    report = build_measurement(now=NOW, root=root, census=dict(census, endpoints=[discarded]), evidence={"blocks": {}},
                               schemas=schemas, classification={"entries": []})
    assert "route:/api/v3/cio/bundle" in report["produced_not_surfaced"]
    assert "schema:CIODeepBlock@v1" in report["produced_not_surfaced"]


def test_classification_moves_items_out_of_operator_relevant_only_with_specific_reasons(tmp_path):
    root = _tree(tmp_path, consumer_reads=True)
    census = {"schema": "CIOApiContractCensus@v2", "endpoints": [_endpoint()], "backend_routes": []}
    schemas = {"CIOIgnoredBlock@v1": ["scripts/lib/cio_deep.py"]}
    good = {"entries": [{"name": "schema:CIOIgnoredBlock@v1", "kind": "schema", "classification": "NOT_OPERATOR_RELEVANT",
                         "reason": "Fixture noise block: build_ignored returns a one-field counter that no operator decision uses.",
                         "owner_hint": "scripts/lib/cio_deep.py::build_ignored"}]}
    report = build_measurement(now=NOW, root=root, census=census, evidence={"blocks": {}}, schemas=schemas, classification=good)
    assert report["produced_not_surfaced_operator_relevant"] == []
    assert report["not_operator_relevant"][0]["name"] == "schema:CIOIgnoredBlock@v1"
    assert report["source_acceptance"]["every_non_surfaced_item_classified"] is True
    assert report["source_acceptance"]["classification_well_formed"] is True

    blanket = {"entries": [dict(good["entries"][0], reason="internal")]}
    report = build_measurement(now=NOW, root=root, census=census, evidence={"blocks": {}}, schemas=schemas, classification=blanket)
    assert report["source_acceptance"]["classification_well_formed"] is False
    assert any("blanket" in issue for issue in report["classification_issues"])


def test_classification_issues_reject_duplicate_reasons_and_bad_classes():
    reason = "A specific reason that is long enough to pass the minimum length rule for entries."
    issues = classification_issues([
        {"name": "schema:A@v1", "kind": "schema", "classification": "NOT_OPERATOR_RELEVANT", "reason": reason, "owner_hint": "x"},
        {"name": "schema:B@v1", "kind": "schema", "classification": "NOT_OPERATOR_RELEVANT", "reason": reason, "owner_hint": "x"},
        {"name": "route:/x", "kind": "schema", "classification": "MAYBE", "reason": reason + " more", "owner_hint": ""},
    ])
    assert any("duplicates" in i for i in issues)
    assert any("classification must be" in i for i in issues)
    assert any("kind must match" in i for i in issues)
    assert any("owner_hint" in i for i in issues)


def test_jsx_child_receiving_the_payload_counts_as_reading_it(tmp_path):
    _write(tmp_path, "apps/src/Page.tsx",
           "import Child from './Child'\nconst { data } = useApi('/api/v3/cio/home')\nconst home = data\n"
           "export default () => <Child home={home} />\n")
    _write(tmp_path, "apps/src/Child.tsx", "export default function Child({ home }) { return <i>{home.cash_letter?.rows}</i> }\n")
    text = render_closure_text(tmp_path, "apps/src/Page.tsx", ["data", "loading", "error"])
    assert consumer_reads_path(text, ("cash_letter", "rows"))
    assert not consumer_reads_path(render_closure_text(tmp_path, "apps/src/Page.tsx", ["loading"]), ("cash_letter",))


def test_record_edge_is_verified_link_by_link(tmp_path):
    _write(tmp_path, "scripts/lib/cio_rec.py", '''
REC_SCHEMA = "CIORecordRow@v1"

def write_row(path):
    row = {"schema": REC_SCHEMA}
    with open(path, "a") as fh:
        fh.write(str(row))

def read_rows():
    return [line for line in open(_store())]

def _store():
    return "data/cio/rec_rows.jsonl"
''')
    _write(tmp_path, "scripts/api_fx.py", '''
def get_rows():
    from scripts.lib.cio_rec import read_rows
    return {"rows": read_rows()}
''')
    _write(tmp_path, "apps/command-center-v3/src/components/Bundle.tsx", "const { data } = useApi('/api/v3/cio/rows'); data.rows\n")
    endpoint = dict(_endpoint("/api/v3/cio/rows", "api_fx.py::get_rows"))
    edge = {"route": "/api/v3/cio/rows", "path": ["rows"], "reader": "lib/cio_rec.py::read_rows",
            "writer": "lib/cio_rec.py::write_row", "store": "rec_rows.jsonl"}
    ok = verify_record_edge("schema:CIORecordRow@v1", edge, [endpoint], PayloadFlow(tmp_path), tmp_path)
    assert ok["verified"] is True, ok["checks"]
    bad = verify_record_edge("schema:CIORecordRow@v1", dict(edge, path=["missing"]), [endpoint], PayloadFlow(tmp_path), tmp_path)
    assert bad["verified"] is False and bad["checks"]["consumer_reads_path"] is False
    wrong_store = verify_record_edge("schema:CIORecordRow@v1", dict(edge, store="other.jsonl"), [endpoint], PayloadFlow(tmp_path), tmp_path)
    assert wrong_store["checks"]["store_shared"] is False


def test_real_tree_every_non_surfaced_item_is_classified_and_none_is_stale():
    report = build_measurement(now=NOW, evidence={"blocks": {"capability_coverage": {"rows": []}}})
    assert report["unclassified"] == [], "classify new produced items in config/cio_surface_classification.json"
    assert report["classification_issues"] == []
    assert report["classification_stale"] == []
    for edge in report["record_edges"]:
        assert edge["verified"], edge
    company = next(e for e in report["record_edges"] if e["name"] == "schema:CIOCompanyFacts@v1")
    assert company["route"] == "/api/v3/data-broker/watch-curation"
    assert company["path"] == ["my_watchlist", "rows", "company_facts"]
    assert company["store"] == "cio_instrument_records.jsonl"
    assert all(company["checks"].values()), company
    assert report["visibility_evidence"]["schema:CIOCompanyFacts@v1"]["method"] == "RECORD_EDGE_VERIFIED"
    review = next(e for e in report["record_edges"] if e["name"] == "schema:CIOReviewLifecycle@v1")
    assert review["route"] == "/api/v3/opportunities/{param}"
    assert review["path"] == ["cio_review", "lifecycle"]
    assert review["store"] == "cio_instrument_records.jsonl" and all(review["checks"].values())
    assert report["visibility_evidence"]["schema:CIOReviewLifecycle@v1"]["method"] == "RECORD_EDGE_VERIFIED"
    assert "schema:CIOReviewAging@v1" not in report["cio_capabilities_operator_visible"]
    assert any(r["name"] == "schema:CIOReviewAging@v1" and "DRAFT source-side diagnostic" in r["reason"] for r in report["not_operator_relevant"])
    # every remaining operator-relevant gap is an explicit, reasoned SURFACE entry
    entries = {e["name"]: e for e in json.loads(Path("config/cio_surface_classification.json").read_text())["entries"]}
    for name in report["produced_not_surfaced_operator_relevant"]:
        assert entries[name]["classification"] == "SURFACE"
        assert "NOT YET SURFACED" in entries[name]["reason"]
    # brain sub-projections are now counted (nested delegation) instead of over-reported
    visible = set(report["cio_capabilities_operator_visible"])
    for name in ("schema:MarketContextState@v1", "schema:CapitalDeploymentPlan@v1", "route:/api/v3/cio/brain/market-context",
                 "route:/api/v3/cio/brain/maturity-contract", "route:/api/v3/cio/records", "schema:OutcomeCheckpoint@v1"):
        assert name in visible, name


def test_query_wrapped_supplemental_surface_requires_a_real_fetch_and_handler(tmp_path):
    from scripts.cio_api_contract_census import scan_frontend, scan_api_v2, match_route
    _write(tmp_path, "apps/command-center-v3/src/pages/Facts.tsx", """
const unused = withQuery('/api/v3/data-broker/unused', {})
const {data: raw} = useApi(withQuery('/api/v3/data-broker/watch-curation', {}), 120000)
export default () => <i>{raw.my_watchlist.rows}</i>
""")
    _write(tmp_path, "scripts/api_v2.py", '\n'.join([
        'def handle(base_path, method):',
        '    if method == "GET" and (base_path == "/api/v3/data-broker" or base_path.startswith("/api/v3/data-broker/")):',
        '        import api_rows as rows',
        '        p = base_path[len("/api/v3/data-broker/"):].strip("/")',
        '        if p == "watch-curation":',
        '            return 200, rows.get_rows()',
    ]))
    fetches, _, _ = scan_frontend(tmp_path, surfaces={"Facts": "pages/Facts.tsx"})
    assert [f.route for f in fetches] == ["/api/v3/data-broker/watch-curation"]
    assert fetches[0].bound_names == ["raw"] and fetches[0].used is True
    handler, how = match_route(fetches[0].route, scan_api_v2(tmp_path), "GET")
    assert how == "EXACT" and handler.producer == "api_rows.py::get_rows"


def test_derived_row_jsx_counts_but_unrelated_import_does_not(tmp_path):
    _write(tmp_path, "apps/src/Page.tsx", """
import Child from './Child'
import Ignored from './Ignored'
const {data: raw} = useApi('/api/v3/cio/facts')
const c = useMemo(() => unwrap(raw), [raw])
const mw = c?.my_watchlist
const rows = mw?.rows || []
export default () => rows.map((row) => <Child row={row} />)
""")
    _write(tmp_path, "apps/src/Child.tsx", "export default ({row}) => <i>{row.company_facts.description}</i>")
    _write(tmp_path, "apps/src/Ignored.tsx", "export default ({row}) => <i>{row.ignored_secret}</i>")
    text = render_closure_text(tmp_path, "apps/src/Page.tsx", ["raw"])
    assert consumer_reads_path(text, ("my_watchlist", "rows", "company_facts"))
    assert not consumer_reads_path(text, ("my_watchlist", "rows", "ignored_secret"))


def test_store_provenance_requires_used_import_or_called_facade(tmp_path):
    _write(tmp_path, "scripts/lib/store.py", 'DEFAULT_PATH = "data/cio/record.jsonl"\ndef reader():\n return DEFAULT_PATH\n')
    _write(tmp_path, "scripts/lib/adapter.py", """
from scripts.lib.store import DEFAULT_PATH, reader

def calls_store():
    return reader()

def uses_imported_path():
    return DEFAULT_PATH

def unrelated():
    return []
""")
    flow = PayloadFlow(tmp_path)
    for name in ("calls_store", "uses_imported_path"):
        assert _function_reaches_store(tmp_path, f"lib/adapter.py::{name}", "record.jsonl", flow)
        assert not _function_reaches_store(tmp_path, f"lib/adapter.py::{name}", "other.jsonl", flow)
    assert not _function_reaches_store(tmp_path, "lib/adapter.py::unrelated", "record.jsonl", flow)
