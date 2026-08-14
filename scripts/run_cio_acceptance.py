#!/usr/bin/env python3
"""run_cio_acceptance.py — CIO LIVE acceptance auditor (v4, fail-closed).

Queries production endpoints and production artifacts only for LIVE_ACCEPTANCE.
Offline/tree composition is recorded under BUILD_CAPABILITY and cannot PASS
a live gate.

Never sends Telegram. Never places broker orders.
Exit 0 only when PRODUCTION_ACCEPTANCE == PASS (all hard gates green,
p0_p1_open empty). Evidence is still written on FAIL.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from scripts.lib.cio_acceptance_v4 import (  # noqa: E402
    ACCEPTANCE_VERSION,
    AUTHORITY,
    evaluate_live_snapshot,
)

LIVE_ROOT = Path("/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT")
HOLDINGS = Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/data/portfolios/state/holdings.json")
CIO_HUB = REPO / "apps/command-center-v3/src/pages/CioHub.tsx"
ADVISORY_HUB = REPO / "apps/command-center-v3/src/pages/AdvisoryDeskHub.tsx"


def _evidence_dir(now: datetime) -> Path:
    d = REPO / "data" / "audit" / f"cio_acceptance_{now.strftime('%Y%m%d')}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _git_sha(ref: str, cwd: Path = REPO) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(cwd), "rev-parse", ref], text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return ""


def _http_json(url: str, timeout: int = 45) -> tuple[Optional[dict], str]:
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            raw = r.read()
        d = json.loads(raw.decode())
        return (d.get("data") if isinstance(d, dict) and "data" in d and isinstance(d["data"], dict) else d), ""
    except Exception as e:
        return None, str(e)[:200]


def _transport_uses_general_token() -> bool:
    p = REPO / "scripts/lib/cio_telegram_transport.py"
    if not p.is_file():
        return True
    text = p.read_text(encoding="utf-8", errors="replace")
    # Allowed: comments that say NEVER use TELEGRAM_BOT_TOKEN
    # Forbidden: reading os.environ of the general token for send.
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#") or s.startswith('"""') or s.startswith("'"):
            continue
        if "TELEGRAM_BOT_TOKEN" in s and "NEVER" not in s.upper() and "never" not in s:
            if "os.environ" in s or "_env(" in s or "getenv" in s:
                return True
    return False


def _collect_live(now: datetime, ev: Path) -> dict[str, Any]:
    live = ""
    if (LIVE_ROOT / "BUILD_SHA").is_file():
        live = (LIVE_ROOT / "BUILD_SHA").read_text(encoding="utf-8").strip().splitlines()[0].strip()
    main = _git_sha("origin/main")

    man_path = REPO / "docs/investment-office/RELEASE_MANIFEST.json"
    manifest = json.loads(man_path.read_text()) if man_path.is_file() else {}

    plan, plan_err = _http_json("http://localhost:7777/api/v2/cio/capital-plan")
    home, home_err = _http_json("http://localhost:7777/api/v3/cio/home")
    report, report_err = _http_json("http://localhost:7777/api/v2/cio/report-v2", timeout=60)
    advisory, adv_err = _http_json("http://localhost:7777/api/v3/advisory", timeout=40)

    if plan:
        (ev / "capital_plan_live.json").write_text(json.dumps(plan, indent=2, default=str)[:2_000_000])
    if home:
        (ev / "cio_home_live.json").write_text(json.dumps(home, indent=2, default=str)[:1_000_000])
    if advisory:
        (ev / "advisory_live.json").write_text(json.dumps(advisory, indent=2, default=str)[:1_500_000])

    ft = (plan or {}).get("financial_truth_gate") or {}
    # Prefer live gate exceptions; if only counts, keep conflicted_symbols
    exceptions = ft.get("exceptions") or []
    if not exceptions and HOLDINGS.is_file():
        # Classify from the same production holdings file the server uses
        # (canonical data symlink). This is production data, not a toy book.
        try:
            from scripts.lib.cio_financial_truth_gate import evaluate_holdings_document
            doc = json.loads(HOLDINGS.read_text(encoding="utf-8"))
            g = evaluate_holdings_document(doc)
            exceptions = g.get("exceptions") or []
            if not ft:
                ft = g
            (ev / "financial_truth_gate.json").write_text(json.dumps(g, indent=2, default=str)[:1_000_000])
        except Exception:
            pass

    parity = ((home or {}).get("consistency") or {}).get("decision_field_parity") or {}

    # Live frontend bundle (production asset, not an offline rebuild)
    bundle_text = ""
    dist = LIVE_ROOT / "apps/command-center-v3/dist"
    index = dist / "index.html"
    if index.is_file():
        html = index.read_text(encoding="utf-8", errors="replace")
        import re
        m = re.search(r'src="(/v3/assets/index-[^"]+\.js)"', html)
        if m:
            js = dist / "assets" / Path(m.group(1)).name
            if js.is_file():
                bundle_text = js.read_text(encoding="utf-8", errors="replace")[:8_000_000]

    cio_src = CIO_HUB.read_text(encoding="utf-8", errors="replace") if CIO_HUB.is_file() else ""
    # Product truth is the *served* bundle. Source is extra signal only.
    # G9 uses bundle + advisory API; also pass live CioHub source if present
    # in the *release* tree (what operators actually run).
    rel_cio = LIVE_ROOT / "apps/command-center-v3/src/pages/CioHub.tsx"
    if rel_cio.is_file():
        cio_src = rel_cio.read_text(encoding="utf-8", errors="replace")

    report_html = ""
    report_pdf = ""
    report_docx = ""
    report_sha = ""
    synthetic = True
    if isinstance(report, dict):
        report_sha = str((report.get("manifest") or {}).get("source_sha") or report.get("source_sha") or "")
        if report.get("html"):
            hp = ev / "report_live.html"
            hp.write_text(str(report["html"]), encoding="utf-8")
            report_html = str(hp)
        # Live API currently does not emit PDF/DOCX files.
        synthetic = False  # endpoint is live book, but formats may be missing

    # Telegram: measure, do not invent (no `or True` credit).
    cio_token_set = bool(os.environ.get("TELEGRAM_CIO_BOT_TOKEN"))
    interdict = os.environ.get("CIO_TELEGRAM_INTERDICT", "").lower() in ("1", "true", "yes", "on")
    general_used = _transport_uses_general_token()
    # Prefer the per-run evidence copy; else the Phase 10 canonical DRY receipt.
    canonical_canary = REPO / "data" / "audit" / "cio_telegram_canary_receipt.json"
    ev_canary = ev / "cio_telegram_canary_receipt.json"
    canary_path = ev_canary if ev_canary.is_file() else canonical_canary
    canary = None
    if canary_path.is_file():
        try:
            canary = json.loads(canary_path.read_text(encoding="utf-8"))
        except Exception:
            canary = None
    proof_general = None
    if isinstance(canary, dict) and "general_sends" in canary:
        try:
            proof_general = int(canary["general_sends"])
        except (TypeError, ValueError):
            proof_general = None

    # CI status on live SHA (best-effort; unproven → FAIL)
    ci_required = False
    ci_green = False
    try:
        prot = subprocess.check_output(
            ["gh", "api", "repos/PatsKiller/tardeai/branches/main/protection",
             "--jq", ".required_status_checks.contexts[]"],
            text=True, stderr=subprocess.DEVNULL, timeout=20,
        )
        ci_required = "cio-hardening" in prot
    except Exception:
        ci_required = False
    if live:
        try:
            chk = subprocess.check_output(
                ["gh", "api", f"repos/PatsKiller/tardeai/commits/{live}/status",
                 "--jq", ".statuses[] | select(.context==\"cio-hardening\") | .state"],
                text=True, stderr=subprocess.DEVNULL, timeout=20,
            )
            ci_green = "success" in chk
        except Exception:
            ci_green = False

    facts: list[dict] = []
    sc = (plan or {}).get("strategy_context") or {}
    facts = list(sc.get("relevant_facts") or [])
    if not facts:
        store = {}
        try:
            from scripts.lib.cio_strategy_knowledge import load_strategy_store
            store = load_strategy_store()
            facts = list(store.get("facts") or [])
            (ev / "strategy_store.json").write_text(json.dumps(store, indent=2, default=str))
        except Exception:
            pass

    surfaces = []
    for name, obj in (
        ("capital_plan", plan),
        ("cio_home", home),
        ("report", report),
        ("advisory", advisory),
    ):
        if isinstance(obj, dict):
            surfaces.append({"name": name, "authority": obj.get("authority")})

    snap = {
        "live_sha": live,
        "main_sha": main,
        "manifest": manifest,
        "git_manifest_hash": str(manifest.get("manifest_hash") or ""),
        "drive_proven": False,
        "drive_duplicate_count": 0,
        "financial_truth_gate": ft,
        "financial_exceptions": exceptions,
        "capital_plan": plan or {},
        "decision_parity": parity,
        "advisory_payload": advisory,
        "frontend_bundle_text": bundle_text,
        "cio_hub_source": cio_src,
        "report_html_path": report_html,
        "report_pdf_path": report_pdf,
        "report_docx_path": report_docx,
        "report_source_sha": report_sha,
        "report_synthetic": False if (report and not report_err) else True,
        "visual_qa_artifact": "",
        "visual_qa_pages": 0,
        "cio_token_env_set": cio_token_set,
        "general_token_used_in_cio_transport": general_used,
        "telegram_interdict_on": interdict,
        "telegram_sends_this_run": 0,
        "proof_general_sends": proof_general,
        "canary_evidence": canary,
        "authority_surfaces": surfaces,
        "cio_hardening_required": ci_required,
        "cio_hardening_green_on_sha": ci_green,
        "strategy_facts": facts,
        "claims_almanac_integrated": False,
        "claims_research_brain_integrated": False,
        "build_capability": {
            "note": "Offline/tree composition is not used for LIVE_ACCEPTANCE.",
            "collect_errors": {
                k: v for k, v in {
                    "capital_plan": plan_err, "home": home_err,
                    "report": report_err, "advisory": adv_err,
                }.items() if v
            },
        },
    }
    (ev / "live_snapshot_meta.json").write_text(json.dumps({
        "live_sha": live, "main_sha": main,
        "plan_ok": bool(plan), "home_ok": bool(home),
        "report_ok": bool(report), "advisory_ok": bool(advisory),
        "bundle_chars": len(bundle_text),
        "errors": snap["build_capability"]["collect_errors"],
    }, indent=2))
    return snap


def main() -> int:
    os.chdir(REPO)
    now = datetime.now(timezone.utc)
    ev = _evidence_dir(now)
    snap = _collect_live(now, ev)
    result = evaluate_live_snapshot(snap, now=now)
    result["evidence_dir"] = str(ev)
    result["acceptance_version"] = ACCEPTANCE_VERSION
    result["authority"] = AUTHORITY
    (ev / "ACCEPTANCE_SCORECARD.json").write_text(
        json.dumps(result, indent=2, default=str), encoding="utf-8",
    )
    summary = {
        "acceptance_version": ACCEPTANCE_VERSION,
        "PRODUCTION_ACCEPTANCE": result["PRODUCTION_ACCEPTANCE"],
        "categories": result["categories"],
        "OPEN_P0": result["OPEN_P0"],
        "OPEN_P1": result["OPEN_P1"],
        "OPEN_P2": result["OPEN_P2"],
        "p0_p1_open": result["p0_p1_open"],
        "git_main": result.get("git_main"),
        "live_sha": result.get("live_sha"),
        "gates": {g["gate"]: g["status"] for g in result["gates"]},
        "evidence_dir": str(ev),
    }
    print(json.dumps(summary, indent=2))
    return 0 if result["PRODUCTION_ACCEPTANCE"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
