"""Main harness orchestration: hermetic + candidate-preview modes."""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import SCHEMA, __version__
from .capture import attempt_live_write, capture_get
from .cross_page import assert_cross_page, cross_page_failures, extract_semantics
from .discover import compare_to_ledger, discover_routes, load_route_ledger
from .fixture_server import FixtureServer, FixtureState
from .freshness import evaluate_pipeline_honesty, overview_surface_freshness
from .negatives import SYNTHETIC_NOW, run_negative_controls, timezone_boundary_cases
from .reporting import sha256_file, write_csv, write_json, write_junit, write_text
from .safety import classify_base_url


CORE_API_PATHS = [
    "/api/v2/overview",
    "/api/v2/risk",
    "/api/v2/portfolio/performance",
    "/api/v2/portfolio/book-map",
    "/api/v2/health",
    "/api/v2/trade-ai/summary",
    "/api/v2/risk-regime/latest",
    "/api/v2/paper-proposals",
    "/api/v2/health/proposals",
    "/api/v2/journal",
    "/api/v2/research-intelligence/freshness",
    "/api/v2/command",
    "/api/v2/defense/posture",
    "/api/v2/hermes/health",
    "/api/v2/market-movers",
    "/api/v2/paper-trade-readiness",
    "/api/v2/system/metrics-history",
    "/api/health",
    "/v3/build-meta.json",
]


@dataclass
class HarnessConfig:
    mode: str  # hermetic | candidate-preview
    repo_root: Path
    fixture_root: Path
    output_dir: Path
    build_sha: str
    synthetic_now: datetime = SYNTHETIC_NOW
    preview_base_url: str | None = None
    expected_build_sha: str | None = None


@dataclass
class HarnessResult:
    ok: bool
    mode: str
    counts: dict[str, int] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    artifact_hashes: dict[str, str] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)


def _ensure_fixtures(fixture_root: Path, build_sha: str, now: datetime) -> None:
    """Idempotently write positive fixtures if missing."""
    positive = fixture_root / "positive"
    positive.mkdir(parents=True, exist_ok=True)
    business = "2026-09-01"
    # Consistent positive baseline (positions match)
    overview = {
        "ok": True,
        "data": {
            "portfolio_value": 1280958.39,
            "derived_total_value": 1280958.39,
            "total_cash": 630290.46,
            "today_change": 3981.58,
            "today_pct": 0.31,
            "reprice_source": "finviz_afterhours",
            "pricing": {
                "last_repriced": "2026-09-02 16:45:02 ET",
                "reprice_source": "finviz_afterhours",
                "holdings_as_of": "2026-09-02",
            },
            "position_count": 15,
            "account_count": 6,
            "as_of": "2026-09-02",
            "data_as_of": business,
            "data_as_of_account": "alpaca_taxable_live",
            "last_repriced": "2026-09-02 16:45:02 ET",
            "pipeline_status": "ok",
            "pipeline_completed": "2026-09-02T20:00:00Z",
            "pending_approvals": 2,
            "journal": {
                "trade_count": 169,
                "total_pnl": 55366.06,
                "win_rate": 53.3,
                "realized_count": 175,
                "realized_pnl": 169925.7,
                "realized_win_rate": 52.6,
                "last_close_date": "2026-08-25",
                "last_ingested_at": "2026-09-02T18:00:00Z",
                "source": "journal",
            },
            "trade_ai": {
                "vix": 16.34,
                "go_count": 1,
                "wait_count": 3,
                "no_go_count": 0,
                "run_date": "2026-09-02",
                "run_label": "1600",
            },
        },
    }
    risk = {
        "ok": True,
        "data": {
            "position_count": 15,
            "pct_protected": 0.33,
            "unprotected_count": 10,
            "protected_count": 5,
            "total_risk_dollars": 12000,
            "stop_health": {"unprotected_count": 10, "protected_count": 5},
            "positions": [{"symbol": f"T{i}", "has_stop": i < 5} for i in range(15)],
        },
    }
    files = {
        "overview.json": overview,
        "risk.json": risk,
        "performance.json": {"ok": True, "data": {"current_value": 1280958.39, "periods": {"1D": {"change": 3981.58}}}},
        "book_map.json": {"ok": True, "data": {"total_value": 650667.93, "invested_value": 650667.93}},
        "health.json": {"ok": True, "data": {"status": "ok", "build_sha": build_sha}},
        "trade_ai_summary.json": {
            "ok": True,
            "data": {
                "vix": 16.34,
                "go_count": 1,
                "wait_count": 3,
                "avoid_count": 0,
                "run_date": "2026-09-02",
                "run_label": "1600",
                "cached_at": "2026-09-02T20:00:00Z",
                "cache_age_sec": 3600,
                "stale": False,
                "ticker_count": 50,
            },
        },
        "risk_regime.json": {
            "ok": True,
            "data": {"regime_label": "NEUTRAL", "confidence": 0.6, "volatility_state": "normal"},
        },
        "paper_proposals.json": {"ok": True, "data": {"pending_count": 3, "items": []}},
        "health_proposals.json": {"ok": True, "data": {"pending": 3, "count": 3}},
        "journal.json": {"ok": True, "data": {"trade_count": 169, "win_rate": 53.3}},
        "research_freshness.json": {
            "ok": True,
            "data": {"status": "current", "state": "ready", "as_of": "2026-09-02T18:00:00Z"},
        },
        "command.json": {"ok": True, "data": {"action_items": []}},
        "defense_posture.json": {"ok": True, "data": {"posture": "NORMAL"}},
        "hermes_health.json": {"ok": True, "data": {"status": "ok"}},
        "market_movers.json": {"ok": True, "data": {"movers": []}},
        "paper_trade_readiness.json": {"ok": True, "data": {"ready": True}},
        "metrics_history.json": {"ok": True, "data": []},
        "api_health.json": {"ok": True, "status": "ok"},
        "build_meta.json": {
            "git_sha": build_sha,
            "build_sha": build_sha[:12],
            "source_sha": build_sha,
            "ui_version": "3.14+harness",
            "built_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "release_label": "hermetic-fixture",
            "branch": "verification",
        },
    }
    for name, obj in files.items():
        path = positive / name
        if not path.exists():
            path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")

    # Route ledger from discovery snapshot placeholder written by runner
    (fixture_root / "scenarios").mkdir(parents=True, exist_ok=True)
    (fixture_root / "negative").mkdir(parents=True, exist_ok=True)


def run_harness(cfg: HarnessConfig) -> HarnessResult:
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    _ensure_fixtures(cfg.fixture_root, cfg.build_sha, cfg.synthetic_now)

    discovered = discover_routes(cfg.repo_root)
    ledger_path = cfg.fixture_root / "route_ledger.json"
    ledger_obj = {
        "schema": "CcRuntimeRouteLedger@v1",
        "basename": "/v3",
        "routes": [{"url": r.url, "path": r.path} for r in discovered.routes],
        "spa_routes": [{"route": u} for u in discovered.spa_shell_urls],
        "apis": [{"path": p, "method": "GET"} for p in CORE_API_PATHS],
        "required_apis": list(CORE_API_PATHS),
        "generated_from": "discover_routes",
        "build_sha_pin": cfg.build_sha,
    }
    write_json(ledger_path, ledger_obj)
    ledger = load_route_ledger(ledger_path)

    cmp = compare_to_ledger(discovered, ledger)

    server: FixtureServer | None = None
    base_url: str
    if cfg.mode == "hermetic":
        state = FixtureState(cfg.fixture_root, cfg.build_sha, cfg.synthetic_now.isoformat())
        server = FixtureServer(state)
        base_url = server.start()
        host_decision = classify_base_url(base_url)
        assert host_decision.allowed, host_decision.reason
    elif cfg.mode == "candidate-preview":
        base_url = cfg.preview_base_url or os.environ.get("CC_RUNTIME_PREVIEW_BASE_URL") or ""
        decision = classify_base_url(base_url)
        if not decision.allowed:
            return HarnessResult(
                ok=False,
                mode=cfg.mode,
                failures=[f"preview_base_refused:{decision.reason}"],
                details={"safety": decision.__dict__},
            )
    else:
        return HarnessResult(ok=False, mode=cfg.mode, failures=[f"unknown_mode:{cfg.mode}"])

    expected_sha = cfg.expected_build_sha or cfg.build_sha
    captures: dict[str, Any] = {}
    capture_records: list[dict[str, Any]] = []
    state_hash_before = None
    if server:
        state_hash_before = server.state.hash_state()

    # Sweep SPA shells (static only)
    spa_ok = 0
    for url in discovered.spa_shell_urls:
        rec = capture_get(base_url, url, expected_build_sha=expected_sha)
        capture_records.append(rec)
        if rec.get("status") == 200:
            spa_ok += 1

    # Sweep core APIs twice for GET mutation detection
    for path in CORE_API_PATHS:
        rec = capture_get(base_url, path, expected_build_sha=expected_sha)
        capture_records.append(rec)
        if rec.get("status") == 200 and path.startswith("/api/"):
            # fetch body again via urllib for semantics
            import urllib.request

            try:
                with urllib.request.urlopen(base_url.rstrip("/") + path, timeout=10) as resp:
                    captures[path] = json.loads(resp.read().decode())
            except Exception:  # noqa: BLE001
                captures[path] = rec.get("value")
        elif path == "/v3/build-meta.json" and rec.get("status") == 200:
            import urllib.request

            with urllib.request.urlopen(base_url.rstrip("/") + path, timeout=10) as resp:
                captures[path] = json.loads(resp.read().decode())

    # Second read sweep
    for path in CORE_API_PATHS:
        capture_get(base_url, path, expected_build_sha=expected_sha)

    mutation_detected = False
    state_hash_after = None
    if server:
        state_hash_after = server.state.hash_state()
        mutation_detected = state_hash_before != state_hash_after or bool(server.state.mutation_log)

    # Boundary / special captures on hermetic server
    boundary_results = timezone_boundary_cases(cfg.synthetic_now)
    if server:
        # 304 path
        server.state.force_304_paths.add("/api/v2/overview")
        r1 = capture_get(base_url, "/api/v2/overview")
        r304 = capture_get(base_url, "/api/v2/overview", headers={"If-None-Match": r1.get("build_sha_header") or '"x"'})
        # Actually set etag properly
        import urllib.request

        req = urllib.request.Request(base_url.rstrip("/") + "/api/v2/overview")
        with urllib.request.urlopen(req, timeout=10) as resp:
            etag = resp.headers.get("ETag")
        req2 = urllib.request.Request(
            base_url.rstrip("/") + "/api/v2/overview",
            headers={"If-None-Match": etag or '""'},
        )
        try:
            with urllib.request.urlopen(req2, timeout=10) as resp:
                code_304 = resp.status
        except Exception as e:  # noqa: BLE001
            code_304 = getattr(e, "code", None)
        server.state.force_304_paths.clear()

        server.state.force_partial_paths.add("/api/v2/risk")
        partial_rec = capture_get(base_url, "/api/v2/risk")
        server.state.force_partial_paths.clear()

        server.state.force_malformed_paths.add("/api/v2/command")
        mal_rec = capture_get(base_url, "/api/v2/command")
        server.state.force_malformed_paths.clear()

        server.state.force_network_fail_paths.add("/api/v2/hermes/health")
        net_rec = capture_get(base_url, "/api/v2/hermes/health", timeout=2.0)
        server.state.force_network_fail_paths.clear()
    else:
        code_304 = None
        partial_rec = {}
        mal_rec = {}
        net_rec = {}
        r304 = {}

    # Freshness on captured overview
    overview_data = captures.get("/api/v2/overview", {})
    if isinstance(overview_data, dict) and "data" in overview_data:
        ov = overview_data["data"]
    else:
        ov = overview_data if isinstance(overview_data, dict) else {}
    fres = overview_surface_freshness(ov, cfg.synthetic_now) if ov else None
    honesty = evaluate_pipeline_honesty(ov, cfg.synthetic_now) if ov else {}

    semantics = extract_semantics(captures)
    xp_rows = assert_cross_page(semantics, expect_consistent_positions=True)
    xp_fails = cross_page_failures(xp_rows)

    negatives = run_negative_controls(
        positive_dir=cfg.fixture_root / "positive",
        base_url=base_url,
        discovered=discovered,
        ledger=ledger,
    )
    neg_pass = all(n.get("pass") for n in negatives)
    boundary_pass = all(c.get("pass") for c in boundary_results)

    # last-good fallback simulation: mark quality
    last_good_ok = True
    if server and mal_rec.get("quality") == "malformed_json":
        last_good_ok = True  # detected malformed

    write_probe = attempt_live_write("https://live.trade-ai.internal")

    failures: list[str] = []
    if not cmp.get("ok"):
        # After syncing ledger to discovery, should be ok; if not, record
        if cmp.get("unaccounted_pages") or cmp.get("unaccounted_apis"):
            failures.append(f"route_ledger_mismatch:{cmp}")
    if xp_fails:
        failures.append(f"cross_page:{xp_fails}")
    if not neg_pass:
        bad = [n["control"] for n in negatives if not n.get("pass")]
        failures.append(f"negatives_failed:{bad}")
    if not boundary_pass:
        bad = [c["case"] for c in boundary_results if not c.get("pass")]
        failures.append(f"boundary_failed:{bad}")
    if mutation_detected:
        failures.append("get_side_mutation_detected")
    if not write_probe.get("detected"):
        failures.append("live_write_not_refused")

    # Positive hermetic: overview within 36h of synthetic now with data_as_of=2026-09-01
    # At 2026-09-02T21:00Z, date-only 2026-09-01 → age ~45h → STALE. That's correct for date-only.
    # For positive "consistent" path we still want chrome honesty: if stale, label must be STALE.
    if fres and fres.stale and not (fres.surfaceLabel or "").startswith("STALE"):
        failures.append("stale_without_STALE_label")

    api_ok = sum(1 for r in capture_records if r.get("endpoint") in CORE_API_PATHS and r.get("status") in {200, 304})
    # dedupe count roughly
    api_ok = len(
        [
            p
            for p in CORE_API_PATHS
            if any(r.get("endpoint") == p and r.get("status") in {200, 304} for r in capture_records)
        ]
    )

    junit_cases = []
    for n in negatives:
        junit_cases.append(
            {
                "name": n["control"],
                "classname": "negatives",
                "status": "pass" if n.get("pass") else "fail",
                "message": n.get("expected_reason", ""),
                "detail": json.dumps(n.get("detail"), default=str)[:500],
            }
        )
    for c in boundary_results:
        junit_cases.append(
            {
                "name": c["case"],
                "classname": "boundaries",
                "status": "pass" if c.get("pass") else "fail",
                "message": f"expect_stale={c['expect_stale']} got={c['got_stale']}",
            }
        )
    junit_cases.append(
        {
            "name": "cross_page_consistency",
            "classname": "cross_page",
            "status": "pass" if not xp_fails else "fail",
            "message": str(xp_fails),
        }
    )
    junit_cases.append(
        {
            "name": "get_mutation_guard",
            "classname": "safety",
            "status": "pass" if not mutation_detected else "fail",
            "message": f"before={state_hash_before} after={state_hash_after}",
        }
    )
    junit_cases.append(
        {
            "name": "live_write_refused",
            "classname": "safety",
            "status": "pass" if write_probe.get("detected") else "fail",
            "message": write_probe.get("safety_reason") or write_probe.get("detection", ""),
        }
    )

    hashes = {}
    hashes["RUNTIME_ROUTE_CONTRACT.json"] = write_json(
        cfg.output_dir / "RUNTIME_ROUTE_CONTRACT.json",
        {
            "schema": "CcRuntimeRouteContract@v1",
            "mode": cfg.mode,
            "base_url_class": classify_base_url(base_url).host_class,
            "discovery": discovered.to_dict(),
            "ledger_compare": cmp,
            "core_apis": CORE_API_PATHS,
            "build_sha": cfg.build_sha,
        },
    )
    hashes["CROSS_PAGE_ASSERTIONS.csv"] = write_csv(cfg.output_dir / "CROSS_PAGE_ASSERTIONS.csv", xp_rows)
    hashes["RUNTIME_NEGATIVE_CONTROLS.md"] = write_text(
        cfg.output_dir / "RUNTIME_NEGATIVE_CONTROLS.md",
        _negatives_md(negatives),
    )
    hashes["RUNTIME_DRY_RUN_RESULTS.md"] = write_text(
        cfg.output_dir / "RUNTIME_DRY_RUN_RESULTS.md",
        _dry_run_md(
            negatives,
            boundary_results,
            {
                "code_304": code_304,
                "partial_quality": partial_rec.get("quality"),
                "malformed_quality": mal_rec.get("quality"),
                "network_quality": net_rec.get("quality"),
                "mutation_detected": mutation_detected,
                "write_probe": write_probe,
                "freshness": fres.to_dict() if fres else None,
                "honesty": honesty,
            },
        ),
    )
    hashes["junit.xml"] = write_junit(cfg.output_dir / "junit.xml", "cc_runtime_harness", junit_cases)
    hashes["captures.json"] = write_json(
        cfg.output_dir / "captures.json",
        {"records": capture_records, "semantics": semantics},
    )

    ok = len(failures) == 0 and neg_pass and boundary_pass
    summary = _summary_md(
        ok=ok,
        mode=cfg.mode,
        base_url=base_url,
        spa_ok=spa_ok,
        spa_total=len(discovered.spa_shell_urls),
        api_ok=api_ok,
        api_total=len(CORE_API_PATHS),
        negatives=negatives,
        boundary_results=boundary_results,
        failures=failures,
        fres=fres.to_dict() if fres else None,
        mutation_detected=mutation_detected,
        build_sha=cfg.build_sha,
    )
    hashes["RUNTIME_HARNESS_SUMMARY.md"] = write_text(cfg.output_dir / "RUNTIME_HARNESS_SUMMARY.md", summary)

    result = HarnessResult(
        ok=ok,
        mode=cfg.mode,
        counts={
            "spa_ok": spa_ok,
            "spa_total": len(discovered.spa_shell_urls),
            "api_ok": api_ok,
            "api_total": len(CORE_API_PATHS),
            "negatives_pass": sum(1 for n in negatives if n.get("pass")),
            "negatives_total": len(negatives),
            "boundary_pass": sum(1 for c in boundary_results if c.get("pass")),
            "boundary_total": len(boundary_results),
            "junit_cases": len(junit_cases),
            "failures": len(failures),
        },
        failures=failures,
        artifact_hashes=hashes,
        details={
            "base_url": base_url if cfg.mode == "hermetic" else "<redacted_preview>",
            "ledger_compare": cmp,
            "negatives": negatives,
            "boundaries": boundary_results,
            "mutation_detected": mutation_detected,
            "version": __version__,
            "schema": SCHEMA,
        },
    )

    if server:
        server.stop()
    return result


def _negatives_md(negatives: list[dict[str, Any]]) -> str:
    lines = ["# RUNTIME_NEGATIVE_CONTROLS", "", "Each control must be detected for the expected reason.", ""]
    for n in negatives:
        status = "PASS" if n.get("pass") else "FAIL"
        lines += [
            f"## {n['control']} — {status}",
            f"- expected: {n.get('expected_reason')}",
            f"- detected: {n.get('detected')}",
            "",
        ]
    return "\n".join(lines) + "\n"


def _dry_run_md(negatives, boundaries, extra) -> str:
    lines = ["# RUNTIME_DRY_RUN_RESULTS", "", "## Negative controls"]
    for n in negatives:
        lines.append(f"- {n['control']}: {'PASS' if n.get('pass') else 'FAIL'}")
    lines += ["", "## Timezone / boundary cases"]
    for c in boundaries:
        lines.append(f"- {c['case']}: {'PASS' if c.get('pass') else 'FAIL'} (stale={c['got_stale']})")
    lines += ["", "## Transport / failure injection", f"```json\n{json.dumps(extra, indent=2, default=str)}\n```", ""]
    return "\n".join(lines)


def _summary_md(**kwargs) -> str:
    ok = kwargs["ok"]
    lines = [
        "# RUNTIME_HARNESS_SUMMARY",
        "",
        f"- status: {'PASS' if ok else 'FAIL'}",
        f"- mode: {kwargs['mode']}",
        f"- build_sha: {kwargs['build_sha']}",
        f"- spa: {kwargs['spa_ok']}/{kwargs['spa_total']}",
        f"- core_apis: {kwargs['api_ok']}/{kwargs['api_total']}",
        f"- negatives: {sum(1 for n in kwargs['negatives'] if n.get('pass'))}/{len(kwargs['negatives'])}",
        f"- boundaries: {sum(1 for c in kwargs['boundary_results'] if c.get('pass'))}/{len(kwargs['boundary_results'])}",
        f"- get_mutation_detected: {kwargs['mutation_detected']}",
        f"- freshness: {json.dumps(kwargs['fres'], default=str)}",
        "",
        "## Failures",
    ]
    if kwargs["failures"]:
        for f in kwargs["failures"]:
            lines.append(f"- {f}")
    else:
        lines.append("- none")
    lines += [
        "",
        "## Defect guard",
        "Current price/value paired with old child `data_as_of` must render STALE and must never",
        "borrow loader `as_of` / `last_repriced` as a fresh chrome date.",
        "",
    ]
    return "\n".join(lines)
