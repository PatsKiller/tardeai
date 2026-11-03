from __future__ import annotations

import textwrap

import pytest
from scripts import cio_api_contract_census as mod
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

def _scan_repair_case(tmp_path,body,export="export const API = '/api/v3/a'\n"):
    src=tmp_path/'apps/command-center-v3/src'
    (src/'pages').mkdir(parents=True,exist_ok=True)
    (src/'lib').mkdir(exist_ok=True)
    (src/'lib/r.ts').write_text(export)
    (src/'pages/H.tsx').write_text("import { API } from '../lib/r'\n"+body)
    return mod.scan_frontend(tmp_path,surfaces={'Home':'pages/H.tsx'})[0]


def test_regex_then_literal_is_preserved(tmp_path):
    found=_scan_repair_case(tmp_path,"const p = s.replace(/\\//g, '-'); useApi('/api/v3/x')\n")
    assert [(f.route,f.callee) for f in found]==[('/api/v3/x','useApi')]


def test_jsx_apostrophe_cannot_uncomment_named_call(tmp_path):
    assert _scan_repair_case(tmp_path,"export default function H() { return <div>Don't panic</div> }\n// useApi(API, 300_000)\nconst tail = 'end'\n")==[]


@pytest.mark.parametrize('body',[
    'function f(API: string) { return useApi(API) }',
    'const f = (API: string): string => useApi(API)',
    'const x = { f(API: string) { return useApi(API) } }',
    'function H() { const x = 1, API = buildUrl(); return useApi(API) }',
    'function H() { function API() {} return useApi(API) }',
    'function H() { class API {} return useApi(API) }',
    'function f() { const API = buildUrl(); return useApi(API) }',
    'function f() { let API = buildUrl(); return useApi(API) }',
    'function f() { if (true) { var API = buildUrl() }; return useApi(API) }',
    'const f = (API: string) => { return useApi(API) }',
    'const f = API => useApi(API)',
    'const f = ({API}: any) => useApi(API)',
    'try {} catch (API) { useApi(API) }',
    'function f() { const { API } = buildUrl(); return useApi(API) }',
    "const label = 'useApi(API)'",
    '// useApi(API)',
    '/* useApi(API) */',
    'onDrill(API)',
    'useApi(API + suffix)',
])
def test_shadow_and_mentions_cannot_donate_import(tmp_path,body):
    assert _scan_repair_case(tmp_path,body+'\n')==[]


def test_nested_shadow_keeps_outer_consumer_and_uses_inner_route(tmp_path):
    body="const {data: top} = useApi(API)\nfunction f() { const API = '/api/v3/b'; return useApi(API) }\nrender(top)\n"
    found=_scan_repair_case(tmp_path,body)
    assert [(f.route,f.bound_names) for f in found]==[('/api/v3/a',['top']),('/api/v3/b',[])]
    assert found[0].used is True


def test_parameter_shadow_does_not_leak_into_module(tmp_path):
    found=_scan_repair_case(tmp_path,"function f(API:string) { return useApi(API) }\nconst { data } = useApi(API)\nrender(data)\n")
    assert [(f.route,f.bound_names,f.used) for f in found]==[('/api/v3/a',['data'],True)]


def test_lexical_block_shadow_does_not_leak(tmp_path):
    found=_scan_repair_case(tmp_path,"function H() {\n{ const API = buildUrl(); useApi(API) }\nreturn useApi(API)\n}\n")
    assert [f.route for f in found]==['/api/v3/a']


@pytest.mark.parametrize('call,used',[
    ("useApi('/api/v3/x').then(r => setData(r.data))",None),
    ("useApi('/api/v3/x')",False),
    ("await useApi('/api/v3/x')",False),
    ("void useApi('/api/v3/x')",False),
    ("useApi(API).then(r => setData(r.data))",None),
    ("useApi(API)",False),
])
def test_discarded_is_distinct_from_chained_result(tmp_path,call,used):
    found=_scan_repair_case(tmp_path,call+'\n')
    assert len(found)==1
    assert found[0].used is used


@pytest.mark.parametrize("body", [
    "function f(API: string): { ok: boolean } { return useApi(API) }",
    "function f(API: string): Promise<{ok:boolean}> { return useApi(API) }",
    "const f = (API: string): {ok:boolean} => useApi(API)",
    "const x = { f<T>(API: T) { return useApi(API) } }",
    "export default function H() { return <div>Docs: useApi(API) is the pattern</div> }",
    "const documentation = /useApi(API)/",
])
def test_typed_shadow_jsx_text_and_regex_cannot_supply_named_consumer(tmp_path, body):
    assert _scan_repair_case(tmp_path, body + "\n") == []


@pytest.mark.parametrize("shadow", [
    "function f(API: string): { ok: boolean } { return useApi(API) }",
    "function f(API: string): Promise<{ok:boolean}> { return useApi(API) }",
    "const f = (API: string): {ok:boolean} => useApi(API)",
    "const x = { f<T>(API: T) { return useApi(API) } }",
])
def test_typed_nested_shadow_keeps_module_consumer(tmp_path, shadow):
    found = _scan_repair_case(tmp_path, shadow + "\nconst {data: top} = useApi(API)\nrender(top)\n")
    assert [(f.route, f.bound_names, f.used) for f in found] == [("/api/v3/a", ["top"], True)]


@pytest.mark.parametrize("body", [
    "export default function H() { return <div>{useApi(API)}</div> }",
    "export default function H() { return <div>useApi(API)<span>{useApi(API)}</span>useApi(API)</div> }",
    "function f(other: string): {ok:boolean} { return useApi(API) }",
    "const f = (other: string): {ok:boolean} => useApi(API)",
    "const doc = /useApi(API)/; const {data: top} = useApi(API)\nrender(top)",
    "const label = 'useApi(API)'\nconst {data: top} = useApi(API)\nrender(top)",
])
def test_named_expression_remains_evidence_beside_typed_heads_or_text(tmp_path, body):
    found = _scan_repair_case(tmp_path, body + "\n")
    assert len(found) == 1 and found[0].route == "/api/v3/a"


@pytest.mark.parametrize("body", [
    "function f<T>(API: string): T extends X ? {ok: true} : {ok: false} { return useApi(API) }",
    "function f(API: string): [a: {ok:boolean}] { return useApi(API) }",
])
def test_balanced_conditional_and_tuple_return_types_cannot_donate_import(tmp_path, body):
    assert _scan_repair_case(tmp_path, body + "\n") == []


@pytest.mark.parametrize("body, count", [
    ("export default function H() { return <>Docs: useApi(API) is the pattern</> }", 0),
    ("export default function H() { return <>Docs: {useApi(API)}</> }", 1),
])
def test_jsx_fragment_text_is_not_code_but_expression_is(tmp_path, body, count):
    found = _scan_repair_case(tmp_path, body + "\n")
    assert len(found) == count
    assert all(row.route == "/api/v3/a" for row in found)


def test_a_line_leading_division_does_not_swallow_a_real_consumer(tmp_path):
    # cc4's regression: `_named_code_only` treated a line-leading `/` as a regex opener, so the mask ran
    # from the division to the next `/` and blanked the real useApi call in between.
    body = ("const total = 10\nconst count = 2\n"
            "const ratio = total\n  / count; const {data: top} = useApi(API) / ratio\nrender(top)\n")
    found = _scan_repair_case(tmp_path, body)
    assert [(f.route, f.bound_names) for f in found] == [("/api/v3/a", ["top"])]


def test_a_line_leading_regex_statement_stays_invisible(tmp_path):
    # The other side of the same rule: a regex in statement position follows a line that cannot end an
    # expression (here the import), so it must be masked — otherwise dropping `^` invents a consumer.
    body = "/useApi(API)/.test('synthetic')\nrender('synthetic')\n"
    assert _scan_repair_case(tmp_path, body) == []


def test_an_expression_start_regex_is_still_masked(tmp_path):
    # Dropping the `^` alternative must not un-mask a regex in a real expression-start position.
    body = "const re = /useApi(API)/\nrender(re)\n"
    assert _scan_repair_case(tmp_path, body) == []
