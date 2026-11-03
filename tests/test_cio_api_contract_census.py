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


def _named_opportunity_fixture(root: Path, body: str, *, alias: str = "BEST_OPPORTUNITIES_API",
                               exported: bool = True) -> Path:
    """Same imported template-constant shape as Home; symbols/data stay synthetic."""
    prefix = "export " if exported else ""
    quote = chr(96)
    _write(root / "apps/command-center-v3/src/lib/bestOpportunities.ts",
           "export const PRESET = 'top5'\n" + prefix + "const BEST_OPPORTUNITIES_API = " + quote +
           "/api/v3/opportunities?preset=" + "$" + "{PRESET}" + quote + "\n")
    _write(root / "apps/command-center-v3/src/pages/HomeDoNow.tsx",
           "import { BEST_OPPORTUNITIES_API" +
           (" as " + alias if alias != "BEST_OPPORTUNITIES_API" else "") +
           " } from '../lib/bestOpportunities'\n" + body)
    return root


def test_named_imported_route_constant_produces_real_consumer_evidence(tmp_path):
    from scripts.cio_api_contract_census import scan_frontend

    for alias in ("BEST_OPPORTUNITIES_API", "TOP_API"):
        root = _named_opportunity_fixture(tmp_path / alias, f"""
            export default function Home() {{
              const {{ data: oppTop }} = useApi<any>({alias}, 300_000)
              return <div>{{oppTop?.items.map(row => row.symbol)}}</div>
            }}
        """, alias=alias)
        # A same-named unrelated export cannot donate a route to this fetch.
        _write(root / "apps/command-center-v3/src/lib/other.ts",
               "export const BEST_OPPORTUNITIES_API = '/api/v3/unrelated'\n")
        home = root / "apps/command-center-v3/src/pages/HomeDoNow.tsx"
        home.write_text(home.read_text() + "\nimport { BEST_OPPORTUNITIES_API as UNUSED } from '../lib/other'\n")
        fetches, _, _ = scan_frontend(root, surfaces={"Home": "pages/HomeDoNow.tsx"})
        assert len(fetches) == 1
        fetch = fetches[0]
        assert fetch.route == "/api/v3/opportunities"
        assert fetch.file == "apps/command-center-v3/src/pages/HomeDoNow.tsx"
        assert fetch.callee == "useApi" and fetch.poll_ms == 300000
        assert fetch.bound_names == ["oppTop"] and fetch.used is True
        assert fetch.surfaces == ["Home"]


def test_named_route_constant_usage_requires_a_real_fetch_and_live_result(tmp_path):
    from scripts.cio_api_contract_census import scan_frontend

    bodies = {
        "comment": "// useApi(BEST_OPPORTUNITIES_API, 300_000)\nexport default function Home() { return null }\n",
        "block_comment": "/*\nuseApi(BEST_OPPORTUNITIES_API, 300_000)\n*/\nexport default function Home() { return null }\n",
        "string": "const label = 'useApi(BEST_OPPORTUNITIES_API, 300_000)'\nexport default function Home() { return label }\n",
        "non_fetch": "export default function Home() { return onDrill(BEST_OPPORTUNITIES_API) }\n",
    }
    for name, body in bodies.items():
        root = _named_opportunity_fixture(tmp_path / name, body)
        fetches, _, _ = scan_frontend(root, surfaces={"Home": "pages/HomeDoNow.tsx"})
        assert fetches == [], name

    for name, body in {
        "discarded": "export default function Home() {\nuseApi(BEST_OPPORTUNITIES_API, 300_000)\nreturn null\n}\n",
        "bound_unused": "export default function Home() {\nconst { data: oppTop } = useApi(BEST_OPPORTUNITIES_API, 300_000)\nreturn <div title='oppTop.items' />\n}\n",
    }.items():
        root = _named_opportunity_fixture(tmp_path / name, body)
        fetches, _, _ = scan_frontend(root, surfaces={"Home": "pages/HomeDoNow.tsx"})
        assert len(fetches) == 1 and fetches[0].used is False, name

    root = _named_opportunity_fixture(tmp_path / "not_exported",
        "export default function Home() {\nconst { data } = useApi(BEST_OPPORTUNITIES_API)\nreturn data.items\n}\n",
        exported=False)
    fetches, _, _ = scan_frontend(root, surfaces={"Home": "pages/HomeDoNow.tsx"})
    assert fetches == []


def test_local_declared_route_constant_reaches_indirect_fetch_matcher(tmp_path):
    from scripts.cio_api_contract_census import scan_frontend

    _write(tmp_path / "apps/command-center-v3/src/pages/HomeDoNow.tsx", """
        const ENDPOINT = '/api/v3/opportunities'
        export default function Home() {
          const { data } = useApi<any>(ENDPOINT, 60_000)
          return data.items
        }
    """)
    fetches, _, _ = scan_frontend(tmp_path, surfaces={"Home": "pages/HomeDoNow.tsx"})
    assert len(fetches) == 1
    assert fetches[0].route == "/api/v3/opportunities"
    assert fetches[0].bound_names == ["data"] and fetches[0].used is True
    assert fetches[0].poll_ms == 60000
