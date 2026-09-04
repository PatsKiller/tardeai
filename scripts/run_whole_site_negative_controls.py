#!/usr/bin/env python3
"""Negative controls for cc-whole-site-residual-v1.

Every guard this campaign adds is only worth what it detects. Each control below
applies a mutation to a DISPOSABLE COPY — a temp directory or an in-memory
object, never the worktree — and passes only when the guard goes red. A control
that "passes" without the mutation being detected is a guard keyed on nothing.

  NC-1  mock-as-live                 a fixture-backed surface forced to LIVE_GOVERNED
  NC-2  GET mutation                 a write issued into the hermetic matrix server
  NC-3  wrong method                 a UI POST to a GET-only route
  NC-4  client-side authority        an UNKNOWN write gate arming controls
  NC-5  stale-root masking           the checkout root answering for the served root
  NC-6  provider call during load    a live host / mutating method reaching the harness
  NC-7  financial-broker mutation    broker paths declassified from never-invoke
  NC-8  tracked-fixture mutation     CI rewriting a committed fixture

READ_ONLY with respect to the repository. Run from anywhere:
  python3 scripts/run_whole_site_negative_controls.py
"""

from __future__ import annotations

NO_CONSUMER_REASON = (
    "evidence artifact schema. WholeSiteNegativeControls@v1 stamps the negative-control receipt read"
    "by the operator and the validator; no module imports it."
)

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

results: list[dict] = []


def record(name: str, mutation: str, detected: bool, detail: str) -> None:
    results.append({"control": name, "mutation": mutation, "detected": detected, "detail": detail})
    print(f"  [{'DETECTED' if detected else 'NOT DETECTED'}] {name}: {detail}")


def _sandbox() -> Path:
    """A disposable copy of the two modules under test plus their package init."""
    tmp = Path(tempfile.mkdtemp(prefix="wsnc_"))
    (tmp / "lib").mkdir()
    (tmp / "lib" / "__init__.py").write_text("")
    for name in ("whole_site_truth.py", "operator_control_contract.py", "effective_truth.py"):
        shutil.copy2(ROOT / "scripts" / "lib" / name, tmp / "lib" / name)
    return tmp


# ── NC-1: mock-as-live ───────────────────────────────────────────────────────
def nc1_mock_as_live() -> None:
    tmp = _sandbox()
    src = (tmp / "lib" / "whole_site_truth.py").read_text()
    # Neuter the decision: everything claims LIVE_GOVERNED.
    mutated = src.replace(
        'if dom["served"] and quality == "AVAILABLE":',
        "if True:",
    )
    assert mutated != src, "NC-1 mutation did not apply"
    (tmp / "lib" / "whole_site_truth.py").write_text(mutated)

    code = (
        "import sys, json, os;"
        f"sys.path.insert(0, {str(tmp)!r});"
        "os.environ['TRADEAI_STATE_ROOT']=os.environ['NC_EMPTY_ROOT'];"
        "from lib.whole_site_truth import control_plane_surface_authority as f;"
        f"r=f({str(ROOT)!r});"
        "print(json.dumps(sorted({s['data_mode'] for s in r['surfaces']})))"
    )
    empty = tempfile.mkdtemp(prefix="wsnc_emptyroot_")
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=300,
        env={**dict(__import__("os").environ), "NC_EMPTY_ROOT": empty},
    )
    modes = json.loads(out.stdout.strip() or "[]")
    # The real module reports no LIVE surface against an empty root; the mutant
    # reports every surface LIVE. Detection = the invariant test would fail.
    detected = modes == ["LIVE_GOVERNED"]
    record(
        "mock_as_live",
        "force every control-plane surface to LIVE_GOVERNED regardless of what answered",
        detected,
        f"mutant modes against an empty state root = {modes} (real module reports no LIVE)",
    )
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(empty, ignore_errors=True)


# ── NC-2: GET mutation / any write into the hermetic matrix ──────────────────
def nc2_get_mutation() -> None:
    import urllib.error
    import urllib.request

    sys.path.insert(0, str(ROOT))
    from scripts.cc_browser_matrix import server as srv

    dist = ROOT / "apps" / "command-center-v3" / "dist"
    httpd, st, base = srv.start(dist, {}, "nc2")
    try:
        req = urllib.request.Request(
            f"{base}/api/v2/broker-orders/approve",
            data=json.dumps({"intent_id": "nc2", "confirm": True}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        code = None
        try:
            urllib.request.urlopen(req, timeout=10)
        except urllib.error.HTTPError as e:
            code = e.code
        detected = code == 403 and len(st.mutation_attempts) == 1
        detail = f"POST refused with {code}; harness logged {len(st.mutation_attempts)} attempt(s)"
    finally:
        httpd.shutdown()
    record("get_mutation", "issue a POST to a broker path inside the no-write matrix", detected, detail)


# ── NC-3: wrong method ───────────────────────────────────────────────────────
def nc3_wrong_method() -> None:
    from lib import operator_control_contract as occ

    tmp = Path(tempfile.mkdtemp(prefix="wsnc_wm_"))
    api = tmp / "api_stub.py"
    api.write_text(
        'def handle(path, method="GET", body=None, query=None):\n'
        "    base_path = path\n"
        '    if method == "GET" and base_path == "/api/v2/thing/do":\n'
        "        return 200, {}\n"
        '    if method == "POST" and base_path == "/api/v2/other":\n'
        "        return 200, {}\n"
        "    return 404, {}\n"
    )
    src = tmp / "src"
    src.mkdir()
    (src / "Bad.tsx").write_text(
        "await fetch('/api/v2/other', { method: 'DELETE', body: JSON.stringify({ id: 1 }) })\n"
    )
    rep = occ.contract(src_root=src, api_path=api)
    detected = rep["wrong_method_count"] == 1
    record(
        "wrong_method",
        "UI issues DELETE to a path the dispatcher only routes for POST",
        detected,
        f"wrong_method_count={rep['wrong_method_count']} (expected 1)",
    )
    shutil.rmtree(tmp, ignore_errors=True)


# ── NC-4: client-side authority ──────────────────────────────────────────────
def nc4_client_side_authority() -> None:
    app = ROOT / "apps" / "command-center-v3"
    tmp = Path(tempfile.mkdtemp(prefix="wsnc_auth_"))
    lib = tmp / "lib"
    lib.mkdir()
    for name in ("operatorBoundary.ts", "operatorBoundary.test.ts"):
        shutil.copy2(app / "src" / "lib" / name, lib / name)
    mod = lib / "operatorBoundary.ts"
    src = mod.read_text()
    mutated = src.replace(
        "      controlsMayArm: false,\n      disabledReason:\n",
        "      controlsMayArm: true,\n      disabledReason:\n",
        1,
    )
    assert mutated != src, "NC-4 mutation did not apply"
    mod.write_text(mutated)
    out = subprocess.run(
        ["node", str(lib / "operatorBoundary.test.ts")],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=str(app),
    )
    detected = out.returncode != 0 and "[FAIL]" in out.stdout
    fails = out.stdout.count("[FAIL]")
    record(
        "client_side_authority",
        "let an UNKNOWN write gate arm operator controls",
        detected,
        f"suite exit={out.returncode}, {fails} assertion(s) went red",
    )
    shutil.rmtree(tmp, ignore_errors=True)


# ── NC-5: stale-root masking ─────────────────────────────────────────────────
def nc5_stale_root_masking() -> None:
    tmp = _sandbox()
    mod = tmp / "lib" / "whole_site_truth.py"
    src = mod.read_text()
    mutated = src.replace(
        '    return Path.home() / "trade-ai-releases" / "persistent-state"',
        "    return Path(__file__).resolve().parents[2]",
        1,
    )
    assert mutated != src, "NC-5 mutation did not apply"
    mod.write_text(mutated)

    def modes(path: Path) -> dict:
        code = (
            "import sys, json;"
            f"sys.path.insert(0, {str(path)!r});"
            "from lib.whole_site_truth import control_plane_surface_authority as f;"
            f"r=f({str(ROOT)!r});"
            "print(json.dumps(r['mode_counts']))"
        )
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=300)
        return json.loads(out.stdout.strip() or "{}")

    real = modes(ROOT / "scripts")
    mutant = modes(tmp)
    detected = real != mutant and real.get("LIVE_GOVERNED", 0) > mutant.get("LIVE_GOVERNED", 0)
    record(
        "stale_root_masking",
        "resolve the served state root from the checkout instead of the persistent root",
        detected,
        f"real={real} vs mutant={mutant}; the mutant hides live surfaces behind the checkout's empty tree",
    )
    shutil.rmtree(tmp, ignore_errors=True)


# ── NC-6: provider call during page load ─────────────────────────────────────
def nc6_provider_call_during_load() -> None:
    sys.path.insert(0, str(ROOT))
    from scripts.cc_runtime_harness import safety

    live = safety.classify_base_url("https://trade-ai.production.example")
    write_live = safety.assert_method_allowed("POST", "https://trade-ai.production.example")
    write_local = safety.assert_method_allowed("POST", "http://127.0.0.1:9")
    read_local = safety.assert_method_allowed("GET", "http://127.0.0.1:9")
    detected = (not live.allowed) and (not write_live.allowed) and (not write_local.allowed) and read_local.allowed
    record(
        "provider_call_during_load",
        "aim the harness at a production host, and send a write to both a live and a loopback host",
        detected,
        f"live-host base allowed={live.allowed} ({live.host_class}); live POST allowed={write_live.allowed}; "
        f"loopback POST allowed={write_local.allowed}; loopback GET allowed={read_local.allowed}",
    )


# ── NC-7: financial / broker mutation ────────────────────────────────────────
def nc7_broker_mutation() -> None:
    tmp = _sandbox()
    mod = tmp / "lib" / "operator_control_contract.py"
    src = mod.read_text()
    start = src.index("BROKER_MARKERS = (")
    end = src.index(")", start) + 1
    mutated = src[:start] + "BROKER_MARKERS = ()" + src[end:]
    mod.write_text(mutated)

    def broker_count(path: Path) -> int:
        code = (
            "import sys, json;"
            f"sys.path.insert(0, {str(path)!r});"
            "from lib.operator_control_contract import contract, OUT_OF_SCOPE_BROKER;"
            "r=contract();"
            "print(len([c for c in r['controls'] if c['provability']==OUT_OF_SCOPE_BROKER]))"
        )
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=600)
        return int((out.stdout.strip() or "0").splitlines()[-1])

    real = broker_count(ROOT / "scripts")
    mutant = broker_count(tmp)
    detected = real > 0 and mutant == 0
    record(
        "financial_broker_mutation",
        "empty BROKER_MARKERS so broker-order controls lose their never-invoke class",
        detected,
        f"real classifies {real} broker control(s) as never-invoke; mutant classifies {mutant}",
    )
    shutil.rmtree(tmp, ignore_errors=True)


# ── NC-8: CI mutating a tracked fixture ──────────────────────────────────────
def nc8_tracked_fixture_mutation() -> None:
    """The rail must notice when validation rewrites a tracked file.

    A hermetic run is executed against a COPY of the fixture tree with the
    regeneration flag forced on — the exact behaviour ordinary CI used to have.
    The hash comparison must catch it; if it cannot, the immutability rail is
    keyed on nothing.
    """
    import hashlib
    from datetime import datetime, timezone as _tz

    sys.path.insert(0, str(ROOT))
    from scripts.cc_runtime_harness.runner import HarnessConfig, run_harness

    src = ROOT / "fixtures" / "cc_runtime"
    tmp = Path(tempfile.mkdtemp(prefix="wsnc_fx_"))
    copy_root = tmp / "cc_runtime"
    shutil.copytree(src, copy_root)

    def tree_hash(root: Path) -> dict[str, str]:
        return {
            str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*"))
            if p.is_file()
        }

    def run(regenerate: bool) -> list[str]:
        before = tree_hash(copy_root)
        run_harness(
            HarnessConfig(
                mode="hermetic",
                repo_root=ROOT,
                fixture_root=copy_root,
                output_dir=tmp / f"out_{regenerate}",
                build_sha="e" * 40,
                synthetic_now=datetime(2026, 9, 2, 21, 0, 0, tzinfo=_tz.utc),
                regenerate_fixtures=regenerate,
            )
        )
        after = tree_hash(copy_root)
        return [k for k in before if before[k] != after.get(k)]

    mutated = run(regenerate=True)
    clean = run(regenerate=False)
    detected = bool(mutated) and not clean
    record(
        "tracked_fixture_mutation",
        "force the old behaviour (regenerate_fixtures=True) on a copy of the fixture tree",
        detected,
        f"regeneration rewrote {mutated or 'nothing'}; the ordinary run rewrote {clean or 'nothing'}",
    )
    shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    print("cc-whole-site-residual-v1 negative controls")
    for fn in (
        nc1_mock_as_live,
        nc2_get_mutation,
        nc3_wrong_method,
        nc4_client_side_authority,
        nc5_stale_root_masking,
        nc6_provider_call_during_load,
        nc7_broker_mutation,
        nc8_tracked_fixture_mutation,
    ):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            record(fn.__name__, "control raised", False, f"{type(exc).__name__}: {exc}")

    detected = sum(1 for r in results if r["detected"])
    payload = {
        "schema": "WholeSiteNegativeControls@v1",
        "detected": detected,
        "total": len(results),
        "detected_all": detected == len(results),
        "controls": results,
    }
    out = ROOT / "evidence" / "whole_site" / "NEGATIVE_CONTROLS.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2))
    print(f"\nnegative controls: {detected}/{len(results)} detected")
    print(f"wrote {out}")
    return 0 if payload["detected_all"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
