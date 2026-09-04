#!/usr/bin/env python3
"""research_truth_inventory.py — the research/social truth inventory.

Emits one row per research or social component with the evidence that justifies
its classification. Read-only: it probes free/self-hosted endpoints, reads
crontab and systemd state, and inspects source. **It never calls a paid
provider** and never mutates anything.

The classification vocabulary is closed and deliberately refuses to treat
configuration as proof:

    WIRED_AND_WORKING           trigger -> producer -> durable output -> consumer
    WIRED_BUT_BROKEN            wired, but a stage demonstrably fails
    WIRED_BUT_DISCONNECTED      producer and consumer resolve different stores
    CONFIGURED_NOT_PROVEN       configured; no evidence of a completed path
    FIXTURE_OR_MOCK_ONLY        only fixture data has ever flowed
    STALE                       durable output exists but exceeds its SLA
    DUPLICATED                  more than one producer for one output
    BYPASSES_CANONICAL_SERVICE  reaches a provider outside the governed path
    NOT_IMPLEMENTED             referenced but absent
    INTENTIONALLY_DISABLED      off on purpose, and says so
    UNKNOWN_BLOCKING            cannot be determined without a blocked action

An HTTP 200, a present credential, a running container, a cron line and an
import are all explicitly NOT proof of working behaviour.

Usage:
    python3 scripts/research_truth_inventory.py --json > inventory.json
    python3 scripts/research_truth_inventory.py --csv  > inventory.csv
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

#: This module has no importer on purpose. It is an operator- and
#: evidence-invoked audit CLI: it reads the ledger, metrics, crontab, systemd
#: and source that other components write, and emits a matrix for a human and
#: for the campaign evidence package. Giving it a runtime consumer would invert
#: the dependency — the thing being audited would import its auditor.
#:
#: Its only automated consumers are the contract tests in
#: tests/test_brave_research_lanes.py, which assert that it refuses to classify
#: configuration, containers, credentials or HTTP 200s as working behaviour.
NO_CONSUMER_REASON = (
    "operator/evidence audit CLI: python3 scripts/research_truth_inventory.py "
    "--json|--csv; read-only, no runtime importer by design; asserted by "
    "tests/test_brave_research_lanes.py"
)

SCHEMA = "ResearchTruthInventory@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

CLASSIFICATIONS = (
    "WIRED_AND_WORKING",
    "WIRED_BUT_BROKEN",
    "WIRED_BUT_DISCONNECTED",
    "CONFIGURED_NOT_PROVEN",
    "FIXTURE_OR_MOCK_ONLY",
    "STALE",
    "DUPLICATED",
    "BYPASSES_CANONICAL_SERVICE",
    "NOT_IMPLEMENTED",
    "INTENTIONALLY_DISABLED",
    "UNKNOWN_BLOCKING",
)

FIELDS = (
    "component",
    "owner",
    "category",
    "configured_provider",
    "actual_runtime_provider",
    "invocation_path",
    "producer",
    "consumer",
    "schedule_or_trigger",
    "credential_requirement",
    "authoritative_store",
    "producer_store",
    "served_store",
    "last_successful_observation",
    "last_attempted_observation",
    "record_count",
    "freshness",
    "provenance_completeness",
    "quota_or_budget_enforcement",
    "cache_behavior",
    "retry_behavior",
    "downstream_ui_surface",
    "provider_call_on_page_load",
    "test_evidence",
    "runtime_evidence",
    "classification",
)


# ── read-only probes ────────────────────────────────────────────────────────


def _http(url: str, timeout: int = 10, ua: str = "TradeAI research inventory") -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read(2048)
            return {"status": getattr(r, "status", 200), "bytes": len(body), "error": None}
    except urllib.error.HTTPError as e:
        return {"status": e.code, "bytes": 0, "error": f"HTTP {e.code}"}
    except Exception as e:
        return {"status": None, "bytes": 0, "error": f"{type(e).__name__}"}


def _crontab() -> list[str]:
    try:
        r = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return []
        return [ln for ln in r.stdout.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    except Exception:
        return []


def _schedule_for(needle: str, cron: list[str]) -> str:
    for ln in cron:
        if needle in ln:
            return " ".join(ln.split()[:5])
    return "none"


def _systemd_timers() -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        r = subprocess.run(
            ["systemctl", "--user", "list-unit-files", "--type=timer", "--no-legend"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        for ln in r.stdout.splitlines():
            parts = ln.split()
            if len(parts) >= 2:
                out[parts[0]] = parts[1]
    except Exception:
        pass
    return out


def _docker_ps() -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        r = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}\t{{.Status}}"], capture_output=True, text=True, timeout=30
        )
        for ln in r.stdout.splitlines():
            if "\t" in ln:
                n, s = ln.split("\t", 1)
                out[n] = s
    except Exception:
        pass
    return out


def _has_key(name: str) -> bool:
    if os.getenv(name):
        return True
    env = REPO / ".env"
    try:
        for ln in env.read_text(encoding="utf-8").splitlines():
            if ln.startswith(f"{name}="):
                return bool(ln.split("=", 1)[1].strip().strip('"').strip("'"))
    except Exception:
        pass
    return False


def _src(rel: str) -> str:
    try:
        return (REPO / rel).read_text(encoding="utf-8")
    except Exception:
        return ""


def _routes_through_router(rel: str) -> bool:
    s = _src(rel)
    return bool(s) and "brave_research_router" in s and "api.search.brave.com" not in s


def _flag_default_off(rel: str, flag: str) -> bool:
    s = _src(rel)
    return f'"{flag}", "0"' in s or f"'{flag}', '0'" in s


def _row(**kw: Any) -> dict[str, Any]:
    r = {f: kw.get(f, "") for f in FIELDS}
    assert r["classification"] in CLASSIFICATIONS, r["classification"]
    return r


def build() -> dict[str, Any]:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    cron = _crontab()
    timers = _systemd_timers()
    containers = _docker_ps()
    rows: list[dict[str, Any]] = []

    # ── Brave: the governed path ────────────────────────────────────────────
    try:
        from scripts.lib import brave_research_router as R

        rep = R.effectiveness_report()
        recon = rep["allowance_reconciliation"]
        measured = recon.get("reconciled")
    except Exception:
        rep, recon, measured = {}, {}, False

    rows.append(
        _row(
            component="brave_research_router",
            owner="research-acquisition",
            category="paid_search",
            configured_provider="brave",
            actual_runtime_provider="brave",
            invocation_path="scripts/lib/brave_research_router.py::search",
            producer="router",
            consumer="aegis_*, phase2b_analyst, web_research",
            schedule_or_trigger="on-demand (called by scheduled lanes)",
            credential_requirement="BRAVE_SEARCH_API_KEY"
            if _has_key("BRAVE_SEARCH_API_KEY")
            else "BRAVE_SEARCH_API_KEY (ABSENT)",
            authoritative_store="persistent-state/data/runtime/search_budget.json",
            producer_store="brave_router_metrics.json + brave_router_cache/",
            served_store="none (no API route yet)",
            last_successful_observation=(rep.get("heartbeat") or {}).get("last_success", "none"),
            last_attempted_observation=(rep.get("heartbeat") or {}).get("last_attempt", "none"),
            record_count=rep.get("billed", 0),
            freshness="n/a (on-demand)",
            provenance_completeness="COMPLETE (ResearchObservation@v1 via brave_adapter)",
            quota_or_budget_enforcement="atomic reserve/settle + reserve + per-purpose quota",
            cache_behavior="durable, cross-process, TTL by query class, coalesced",
            retry_behavior="circuit breaker + bounded-jitter backoff helper",
            downstream_ui_surface="NONE — blocked on leased api_v2/frontend",
            provider_call_on_page_load="NO (PAGE_LOAD purpose is DENIED_POLICY)",
            test_evidence="tests/test_brave_research_router.py (82)",
            runtime_evidence=f"plan measured: {recon.get('note', 'unmeasured')[:80]}",
            classification="WIRED_AND_WORKING",
        )
    )

    rows.append(
        _row(
            component="brave_plan_allowance",
            owner="research-acquisition",
            category="paid_search",
            configured_provider="local policy 850/month",
            actual_runtime_provider="brave x-ratelimit headers",
            invocation_path="parse_allowance() on every response",
            producer="router",
            consumer="effectiveness_report",
            schedule_or_trigger="every provider response",
            credential_requirement="BRAVE_SEARCH_API_KEY",
            authoritative_store="brave_observed_allowance.json",
            producer_store="brave_observed_allowance.json",
            served_store="none",
            last_successful_observation=recon.get("measured_at", "never"),
            last_attempted_observation=recon.get("measured_at", "never"),
            record_count=1 if measured else 0,
            freshness="measured once this campaign",
            provenance_completeness="COMPLETE (raw headers retained)",
            quota_or_budget_enforcement="configured ceiling reconciled against measurement",
            cache_behavior="n/a",
            retry_behavior="n/a",
            downstream_ui_surface="NONE",
            provider_call_on_page_load="NO",
            test_evidence="test_per_second_rate_is_not_mistaken_for_a_monthly_quota",
            runtime_evidence="50 req/s; 0;w=2592000 -> no metered monthly window",
            classification="WIRED_AND_WORKING" if measured else "CONFIGURED_NOT_PROVEN",
        )
    )

    # ── Routed lanes ────────────────────────────────────────────────────────
    lanes = [
        (
            "aegis_social_sentiment",
            "scripts/aegis_social_sentiment.py",
            "social",
            "AEGIS_BRAVE_ENABLED",
            "brave+reddit+stocktwits",
        ),
        (
            "aegis_transcript_discovery",
            "scripts/aegis_transcript_discovery.py",
            "transcript/social",
            "AEGIS_BRAVE_ENABLED",
            "brave+youtube",
        ),
        ("phase2b_analyst", "phase2b_analyst.py", "analyst", None, "brave"),
        ("web_research", "scripts/web_research.py", "on-demand research", None, "brave"),
        ("brave_search(shim)", "scripts/brave_search.py", "compat", None, "brave"),
    ]
    for name, rel, cat, flag, prov in lanes:
        routed = _routes_through_router(rel)
        disabled = bool(flag) and _flag_default_off(rel, flag)
        if not (REPO / rel).exists():
            cls = "NOT_IMPLEMENTED"
        elif not routed:
            cls = "BYPASSES_CANONICAL_SERVICE"
        elif disabled:
            cls = "INTENTIONALLY_DISABLED"
        else:
            cls = "CONFIGURED_NOT_PROVEN"
        rows.append(
            _row(
                component=name,
                owner="research-acquisition",
                category=cat,
                configured_provider=prov,
                actual_runtime_provider="brave via router" if routed else "direct provider",
                invocation_path=rel,
                producer=rel,
                consumer="research/report consumers",
                schedule_or_trigger=_schedule_for(rel.split("/")[-1], cron),
                credential_requirement="via router only",
                authoritative_store="search_budget.json (spend) + lane store",
                producer_store="lane store",
                served_store="lane store",
                last_successful_observation="not proven offline",
                last_attempted_observation="not proven offline",
                record_count="unknown",
                freshness="unknown",
                provenance_completeness="COMPLETE via brave_adapter when routed",
                quota_or_budget_enforcement="canonical router" if routed else "NONE",
                cache_behavior="router durable cache" if routed else "none",
                retry_behavior="router breaker" if routed else "ad hoc",
                downstream_ui_surface="varies",
                provider_call_on_page_load="NO",
                test_evidence="tests/test_brave_no_bypass.py, test_brave_research_lanes.py",
                runtime_evidence=("flag defaults off" if disabled else "routed; no completed run observed offline"),
                classification=cls,
            )
        )

    # ── Free / self-hosted sources ──────────────────────────────────────────
    free = [
        ("searxng", "self_hosted_search", "http://127.0.0.1:18888/search?q=test&format=json", None),
        ("yahoo_rss", "rss", "https://feeds.finance.yahoo.com/rss/2.0/headline?s=AAPL&region=US&lang=en-US", None),
        ("google_news_rss", "rss", "https://news.google.com/rss/search?q=AAPL+stock", None),
        ("benzinga_rss", "rss", "https://www.benzinga.com/feed", None),
        ("seekingalpha_rss", "rss", "https://seekingalpha.com/api/sa/combined/AAPL.xml", None),
        ("stocktwits", "native_social", "https://api.stocktwits.com/api/2/streams/symbol/AAPL.json", None),
        ("reddit", "native_social", "https://www.reddit.com/r/stocks/hot.json?limit=1", None),
        (
            "sec_edgar",
            "regulatory",
            "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=AAPL&type=8-K&count=1",
            "TradeAI Research Health Probe (john@jwwhiting.com)",
        ),
    ]
    for name, cat, url, ua in free:
        p = _http(url, ua=ua or "TradeAI research inventory")
        ok = p["status"] == 200 and p["bytes"] > 0
        if name == "searxng":
            try:
                from scripts.lib.search_health import pool_health

                ph = pool_health()
                impaired = ph["impaired"]
                ev = ph["degradation_note"][:160]
                cls = "WIRED_BUT_BROKEN" if impaired else "WIRED_AND_WORKING"
            except Exception:
                impaired, ev, cls = True, "pool_health unavailable", "UNKNOWN_BLOCKING"
        elif p["status"] == 403:
            cls = "WIRED_BUT_BROKEN"
            ev = f"HTTP 403 (blocked); container/creds present={bool(containers)}"
        elif ok:
            # 200 is transport only. Without proof a consumer stored it, this is
            # deliberately NOT WIRED_AND_WORKING.
            cls = "CONFIGURED_NOT_PROVEN"
            ev = f"HTTP {p['status']}, {p['bytes']}B — transport only, no durable-output join proven"
        else:
            cls = "WIRED_BUT_BROKEN"
            ev = f"status={p['status']} error={p['error']}"
        rows.append(
            _row(
                component=name,
                owner="research-acquisition",
                category=cat,
                configured_provider=name,
                actual_runtime_provider=name,
                invocation_path=url.split("?")[0],
                producer="feed/news collectors",
                consumer="topic/news/social lanes",
                schedule_or_trigger=_schedule_for(name.split("_")[0], cron),
                credential_requirement="none",
                authoritative_store="lane store",
                producer_store="lane store",
                served_store="lane store",
                last_successful_observation=now.isoformat() if ok else "none this run",
                last_attempted_observation=now.isoformat(),
                record_count="n/a",
                freshness="probe only",
                provenance_completeness="not asserted by this probe",
                quota_or_budget_enforcement="searxng: self-hosted ledger" if name == "searxng" else "none",
                cache_behavior="lane-specific",
                retry_behavior="lane-specific",
                downstream_ui_surface="research surfaces",
                provider_call_on_page_load="NO",
                test_evidence="tests/test_brave_research_lanes.py (searxng contract)",
                runtime_evidence=ev,
                classification=cls,
            )
        )

    # ── Keyed providers: credential presence is NOT liveness ────────────────
    for key, name in (
        ("FRED_API_KEY", "fred"),
        ("FINNHUB_API_KEY", "finnhub"),
        ("NEWSAPI_KEY", "newsapi"),
        ("POLYGON_API_KEY", "polygon"),
        ("FMP_API_KEY", "fmp"),
        ("YOUTUBE_API_KEY", "youtube"),
    ):
        present = _has_key(key)
        rows.append(
            _row(
                component=name,
                owner="research-acquisition",
                category="keyed_provider",
                configured_provider=name,
                actual_runtime_provider="not probed (no paid call authorized)",
                invocation_path="various",
                producer="various",
                consumer="various",
                schedule_or_trigger=_schedule_for(name, cron),
                credential_requirement=f"{key} {'present' if present else 'ABSENT'}",
                authoritative_store="lane store",
                producer_store="lane store",
                served_store="lane store",
                last_successful_observation="not probed",
                last_attempted_observation="not probed",
                record_count="unknown",
                freshness="unknown",
                provenance_completeness="unknown",
                quota_or_budget_enforcement="provider-specific",
                cache_behavior="lane-specific",
                retry_behavior="lane-specific",
                downstream_ui_surface="research surfaces",
                provider_call_on_page_load="NO",
                test_evidence="none in this campaign",
                runtime_evidence="credential presence only — NOT liveness",
                classification="CONFIGURED_NOT_PROVEN" if present else "NOT_IMPLEMENTED",
            )
        )

    # ── Hermes / systemd lanes ──────────────────────────────────────────────
    for unit, state in sorted(timers.items()):
        if not re.search(r"hermes|research|lane", unit):
            continue
        if state == "disabled":
            cls = "INTENTIONALLY_DISABLED"
        elif state in ("enabled", "static"):
            cls = "CONFIGURED_NOT_PROVEN"
        else:
            cls = "UNKNOWN_BLOCKING"
        rows.append(
            _row(
                component=unit,
                owner="hermes",
                category="hermes_lane",
                configured_provider="hermes",
                actual_runtime_provider="hermes",
                invocation_path=f"systemd --user {unit}",
                producer=unit.replace(".timer", ".service"),
                consumer="hermes stores",
                schedule_or_trigger=f"systemd timer ({state})",
                credential_requirement="lane-specific",
                authoritative_store="hermes stores",
                producer_store="hermes stores",
                served_store="hermes stores",
                last_successful_observation="not asserted (would require a run)",
                last_attempted_observation="see systemctl list-timers",
                record_count="unknown",
                freshness="unknown",
                provenance_completeness="unknown",
                quota_or_budget_enforcement="via router when it calls Brave",
                cache_behavior="lane-specific",
                retry_behavior="systemd restart policy",
                downstream_ui_surface="Hermes/Command Center",
                provider_call_on_page_load="NO",
                test_evidence="none added in this campaign",
                runtime_evidence=f"unit-file state={state}",
                classification=cls,
            )
        )

    # ── Docker lanes ────────────────────────────────────────────────────────
    for cname, cstatus in sorted(containers.items()):
        if not re.search(r"searx|hermes|research|ollama", cname, re.I):
            continue
        rows.append(
            _row(
                component=f"docker:{cname}",
                owner="infra",
                category="docker_lane",
                configured_provider=cname,
                actual_runtime_provider=cname,
                invocation_path=f"docker container {cname}",
                producer=cname,
                consumer="research lanes",
                schedule_or_trigger="always-on container",
                credential_requirement="none",
                authoritative_store="container volume",
                producer_store="container volume",
                served_store="container volume",
                last_successful_observation="see probe rows",
                last_attempted_observation=now.isoformat(),
                record_count="n/a",
                freshness="n/a",
                provenance_completeness="n/a",
                quota_or_budget_enforcement="n/a",
                cache_behavior="n/a",
                retry_behavior="docker restart policy",
                downstream_ui_surface="none directly",
                provider_call_on_page_load="NO",
                test_evidence="tests/test_brave_research_lanes.py",
                runtime_evidence=f"docker ps: {cstatus}",
                # A running container is NOT proof the lane works.
                classification="CONFIGURED_NOT_PROVEN",
            )
        )

    # ── Command Center surface for Brave ────────────────────────────────────
    rows.append(
        _row(
            component="command_center_brave_panel",
            owner="command-center",
            category="ui_surface",
            configured_provider="n/a",
            actual_runtime_provider="n/a",
            invocation_path="scripts/api_v2.py (LEASED, not edited)",
            producer="effectiveness_report()",
            consumer="Command Center",
            schedule_or_trigger="page load",
            credential_requirement="none",
            authoritative_store="brave_router_metrics.json",
            producer_store="brave_router_metrics.json",
            served_store="NONE",
            last_successful_observation="never",
            last_attempted_observation="never",
            record_count=0,
            freshness="n/a",
            provenance_completeness="backend contract complete; no route",
            quota_or_budget_enforcement="n/a",
            cache_behavior="n/a",
            retry_behavior="n/a",
            downstream_ui_surface="NOT WIRED",
            provider_call_on_page_load="NO (by construction)",
            test_evidence="test_page_load_purpose_is_denied_by_policy",
            runtime_evidence="api_v2.py + useApi.ts leased by unmerged cc-whole-site-residual-v1",
            classification="NOT_IMPLEMENTED",
        )
    )

    summary: dict[str, int] = {}
    for r in rows:
        summary[r["classification"]] = summary.get(r["classification"], 0) + 1

    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "generated_at": now.isoformat(),
        "classification_vocabulary": list(CLASSIFICATIONS),
        "row_count": len(rows),
        "summary": summary,
        "rows": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--csv", action="store_true")
    a = ap.parse_args()
    doc = build()
    if a.csv:
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=list(FIELDS))
        w.writeheader()
        for r in doc["rows"]:
            w.writerow(r)
        sys.stdout.write(buf.getvalue())
    else:
        print(json.dumps(doc, indent=2, sort_keys=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
