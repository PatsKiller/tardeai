from __future__ import annotations

import textwrap
from pathlib import Path

from scripts.cio_api_contract_census import build_census, normalize_route


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text), encoding="utf-8")


def _fixture(root: Path) -> Path:
    _write(root / "apps/command-center-v3/src/hooks/useApi.ts", "export function useApi(p: string, ms?: number) { return { data: null } }\n")
    _write(root / "apps/command-center-v3/src/pages/HermesHub.tsx", """\
        import { useApi } from '../hooks/useApi'
        import Panel from '../components/HermesPanel'
        export default function HermesHub() {
          const { data: health } = useApi<any>('/api/v2/hermes/health', 120_000)
          const { data: ghost } = useApi<any>('/api/v2/hermes/ghost-route', 60_000)
          const { data: unused } = useApi<any>('/api/v2/hermes/infra', 30_000)
          const memo = useMemo(() => 1, [unused])
          return <div title={`unused ${'x'}`}>{health?.ok}{ghost?.ok}<Panel /></div>
        }
        """)
    _write(root / "apps/command-center-v3/src/components/HermesPanel.tsx", """\
        export default function HermesPanel() {
          const endpoint = flag ? `/api/v3/cio/brain${q ? `?x=${q}` : ''}` : '/api/v3/cio/home'
          const { data } = useApi<any>(endpoint, 300_000)
          return <div>{data?.x}</div>
        }
        """)
    _write(root / "scripts/api_v2.py", """\
        def _hermes_health():
            try:
                x = 1
            except Exception:
                pass
            return {"schema": "HermesHealth@v1", "as_of": "now"}


        def _hermes_infra():
            return {"ok": True}


        def _hermes_orphan():
            return {"ok": True}


        ROUTES = {
            "/api/v2/hermes/health": lambda: _hermes_health(),
            "/api/v2/hermes/infra": lambda: _hermes_infra(),
            "/api/v2/hermes/orphan": lambda: _hermes_orphan(),
        }


        def handle(path, method="GET", body=None, query=None):
            base_path = path
            if base_path.startswith("/api/v3/cio"):
                try:
                    import api_v3_cio as _cio

                    p = base_path[len("/api/v3/cio") :].strip("/")
                    if method == "GET":
                        if p == "brain":
                            return 200, _cio.get_brain()
                        if p in ("home", "start"):
                            return 200, _cio.get_home()
                        return 404, {"ok": False}
                except Exception as e:
                    return 500, {"ok": False}
        """)
    _write(root / "scripts/api_v3_cio.py", """\
        def get_brain():
            return {"schema": "CIOBrainSnapshot@v1", "composition_as_of": "t", "source_as_of": "t"}


        def get_home():
            return {"ok": True}
        """)
    return root


def test_census_detects_injected_dead_fetch_unused_fetch_and_unconsumed_route(tmp_path):
    report = build_census(_fixture(tmp_path))
    assert report["schema"] == "CIOApiContractCensus@v2"
    dead = {row["route"] for row in report["dead_calls"]}
    assert dead == {"/api/v2/hermes/ghost-route"}
    unused = {row["route"] for row in report["unused_fetches"]}
    assert unused == {"/api/v2/hermes/infra"}  # deps-array and string mentions are not uses
    unconsumed = {row["route"] for row in report["unconsumed_routes"]}
    assert "/api/v2/hermes/orphan" in unconsumed
    assert "/api/v2/hermes/health" not in unconsumed
    assert "/api/v3/cio/start" not in unconsumed  # alias of a consumed branch


def test_census_maps_producers_schemas_clocks_and_silent_excepts(tmp_path):
    report = build_census(_fixture(tmp_path))
    rows = {row["route"]: row for row in report["endpoints"]}
    health = rows["/api/v2/hermes/health"]
    assert health["producer"] == "api_v2.py::_hermes_health"
    assert health["response_schema"] == "HermesHealth@v1"
    assert health["source_clock"] == "as_of"
    assert health["error_behavior"] == "SILENT_EXCEPT_PASS"
    assert health["poll_ms"] == 120000
    assert health["consumer_ref"].endswith("HermesHub.tsx:4")
    brain = rows["/api/v3/cio/brain"]  # indirect: const endpoint = cond ? `...${nested}` : '...'
    assert brain["producer"] == "api_v3_cio.py::get_brain"
    assert brain["source_clock"] == "source_as_of"
    assert brain["composition_clock"] == "composition_as_of"
    assert "/api/v3/cio/home" in rows
    assert any(s["routes"] == ["/api/v2/hermes/health"] for s in report["silent_exception_paths"])
    assert report["v2_v3_mixing"] == {}  # Hermes v2 only, CIO v3 only
    assert report["machine_claims"]["runtime_complete"] is False


def test_route_normalization_handles_nested_templates():
    assert normalize_route("/api/v3/cio/research-provenance${id ? `?decision_id=${id}` : ''}") == "/api/v3/cio/research-provenance"
    assert normalize_route("${base}/api/v3/agent-runtime/runs/${runId}/artifacts") == "/api/v3/agent-runtime/runs/{param}/artifacts"


def test_real_tree_census_is_computed_not_hardcoded():
    report = build_census()
    assert {"CIO", "Advisory", "Agents", "Hermes", "Research Intelligence"} <= set(report["scope"])
    assert report["endpoint_count"] > 0
    assert report["backend_routes_parsed"] > 0
    routes = {row["route"] for row in report["endpoints"]}
    assert "/api/v3/hermes/research-links" in routes
    assert "/api/v3/agents/runtime-proof" in routes
    # The two Hermes fetches proven dead on 2026-10-02 were removed and must not return.
    assert not {"/api/v2/hermes/self-learning-overview", "/api/v2/hermes/promotion-review"} & {
        row["route"] for row in report["unused_fetches"]
    }
    for row in report["endpoints"]:
        assert row["route"].startswith("/api/v")
        assert row["evidence_class"] == "SOURCE_ONLY"
