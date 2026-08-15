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

import hashlib
import json
import os
import shutil
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
    run_id = now.strftime("%Y%m%dT%H%M%SZ")
    d = REPO / "data" / "audit" / "cio_acceptance" / run_id
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
    from scripts.lib.cio_acceptance_purity import compare_audited, snapshot_audited_files
    from scripts.lib.cio_remote_sha_truth import resolve_remote_sha_truth

    man_path = REPO / "docs/investment-office/RELEASE_MANIFEST.json"
    audited_before = snapshot_audited_files(extra=[man_path], holdings=HOLDINGS)

    live = ""
    if (LIVE_ROOT / "BUILD_SHA").is_file():
        live = (LIVE_ROOT / "BUILD_SHA").read_text(encoding="utf-8").strip().splitlines()[0].strip()
    remote_truth = resolve_remote_sha_truth(REPO, fetch=True)
    (ev / "remote_git_truth.json").write_text(json.dumps(remote_truth, indent=2, default=str))
    main = remote_truth.get("remote_main_sha") or _git_sha("origin/main")

    from scripts.lib.cio_remote_sha_truth import collect_evaluator_attestation
    evaluator_attestation = collect_evaluator_attestation(REPO, remote_truth=remote_truth)
    (ev / "acceptance_evaluator_attestation.json").write_text(
        json.dumps(evaluator_attestation, indent=2, default=str), encoding="utf-8",
    )

    # Holdings SHA must be taken from the live file BEFORE the report is loaded.
    current_holdings_sha256 = ""
    if HOLDINGS.is_file():
        current_holdings_sha256 = hashlib.sha256(HOLDINGS.read_bytes()).hexdigest()

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

    home_parity = ((home or {}).get("consistency") or {}).get("decision_field_parity") or {}
    parity = dict(home_parity) if isinstance(home_parity, dict) else {}

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

    report_dir = ev / "report"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_html = ""
    report_pdf = ""
    report_docx = ""
    report_sha = ""
    if isinstance(report, dict):
        report_sha = str((report.get("manifest") or {}).get("source_sha") or report.get("source_sha") or "")
        if report.get("html"):
            hp = report_dir / "cio_live_report.html"
            hp.write_text(str(report["html"]), encoding="utf-8")
            report_html = str(hp)
    # Copy live-book export artifacts into this run's evidence dir (not only shared dry).
    live_rep = REPO / "data" / "audit" / "cio_live_report_dry"
    for name, attr in (
        ("cio_live_report.html", "html"),
        ("cio_live_report.pdf", "pdf"),
        ("cio_live_report.docx", "docx"),
    ):
        p = live_rep / name
        if p.is_file() and p.stat().st_size > 100:
            dest = report_dir / name
            if attr == "html" and report_html:
                # API HTML already written into the run dir; keep it.
                pass
            else:
                shutil.copy2(p, dest)
                if attr == "html":
                    report_html = str(dest)
                elif attr == "pdf":
                    report_pdf = str(dest)
                elif attr == "docx":
                    report_docx = str(dest)
    qa_src = live_rep / "visual_qa" / "VISUAL_QA.json"
    qa_json = report_dir / "VISUAL_QA.json"
    if qa_src.is_file():
        shutil.copy2(qa_src, qa_json)
    visual_artifact = ""
    visual_pages = 0
    if qa_json.is_file():
        try:
            qa = json.loads(qa_json.read_text(encoding="utf-8"))
            visual_artifact = str(qa_json)
            visual_pages = int(qa.get("pages_inspected") or 0)
        except Exception:
            pass

    # Telegram: measure, do not invent (no `or True` credit).
    cio_token_set = bool(os.environ.get("TELEGRAM_CIO_BOT_TOKEN"))
    interdict = os.environ.get("CIO_TELEGRAM_INTERDICT", "").lower() in ("1", "true", "yes", "on")
    general_used = _transport_uses_general_token()
    live_canary = REPO / "data" / "audit" / "cio_telegram_canary_receipt_live.json"
    canonical_canary = REPO / "data" / "audit" / "cio_telegram_canary_receipt.json"
    ev_live = ev / "cio_telegram_canary_receipt_live.json"
    ev_canary = ev / "cio_telegram_canary_receipt.json"
    canary = None
    for p in (live_canary, ev_live, ev_canary, canonical_canary):
        if not p.is_file():
            continue
        try:
            cand = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(cand, dict):
            continue
        if cand.get("proof") == "live" and cand.get("sent") is True:
            canary = cand
            break
        if canary is None:
            canary = cand
    proof_general = None
    if isinstance(canary, dict) and "general_sends" in canary:
        try:
            proof_general = int(canary["general_sends"])
        except (TypeError, ValueError):
            proof_general = None

    # G8: compare the live payloads already collected. Home-only parity.ok is not enough.
    try:
        from scripts.lib.cio_decision_parity import compare_decision_surfaces
        g8 = compare_decision_surfaces(
            plan=plan, cio_home=home, report=report, telegram_payload=canary,
        )
        parity = {
            **parity,
            "ok": bool(g8.get("ok")),
            "surfaces_complete": True,
            "surfaces": {
                "capital_plan": plan,
                "cio_home": home,
                "report": report,
                "telegram": canary,
            },
            "missing_from_surface": g8.get("missing_from_surface"),
            "extra_on_surface": g8.get("extra_on_surface"),
            "field_mismatch": g8.get("field_mismatch"),
            "digest_mismatch": g8.get("digest_mismatch"),
            "surface_decision_counts": g8.get("decision_count"),
        }
        (ev / "decision_parity.json").write_text(
            json.dumps(g8, indent=2, default=str)[:200_000], encoding="utf-8",
        )
    except Exception as e:
        parity = {
            **parity,
            "ok": False,
            "surfaces_complete": False,
            "error": f"{type(e).__name__}:{e}"[:200],
        }

    def _hardening_green(sha: str) -> bool:
        if not sha:
            return False
        try:
            chk = subprocess.check_output(
                ["gh", "api", f"repos/PatsKiller/tardeai/commits/{sha}/check-runs",
                 "--jq", ".check_runs[] | select(.name==\"cio-hardening\") | .conclusion"],
                text=True, stderr=subprocess.DEVNULL, timeout=20,
            )
            if "success" in chk:
                return True
        except Exception:
            pass
        try:
            chk = subprocess.check_output(
                ["gh", "api", f"repos/PatsKiller/tardeai/commits/{sha}/status",
                 "--jq", ".statuses[] | select(.context==\"cio-hardening\") | .state"],
                text=True, stderr=subprocess.DEVNULL, timeout=20,
            )
            return "success" in chk
        except Exception:
            return False

    # CI status on live content SHA and attestation SHA when distinct.
    ci_required = False
    try:
        prot = subprocess.check_output(
            ["gh", "api", "repos/PatsKiller/tardeai/branches/main/protection",
             "--jq", ".required_status_checks.contexts[]"],
            text=True, stderr=subprocess.DEVNULL, timeout=20,
        )
        ci_required = "cio-hardening" in prot
    except Exception:
        ci_required = False
    ci_green = _hardening_green(live)
    ci_attestation_sha = main if (main and live and main != live) else ""
    ci_attestation_green = _hardening_green(ci_attestation_sha) if ci_attestation_sha else None

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
    if isinstance(canary, dict):
        surfaces.append({
            "name": "telegram_payload",
            "authority": canary.get("authority") or "READ_ONLY_ADVISORY",
        })

    drive_proven = False
    drive_hash = ""
    drive_dups = None  # unknown must not become 0
    drive_file_id = "1yGys5GswSQWNzimGvTZh71I1sC9EtUaM"
    git_sha256 = ""
    git_bytes = (REPO / "docs/investment-office/RELEASE_MANIFEST.json")
    try:
        git_sha256 = hashlib.sha256(git_bytes.read_bytes()).hexdigest() if git_bytes.is_file() else ""
        env = os.environ.copy()
        env.setdefault("GOG_ACCOUNT", "john@jwwhiting.com")
        tmp = ev / "drive_RELEASE_MANIFEST.json"
        dl = subprocess.run(
            ["gog", "drive", "download", drive_file_id,
             "--out", str(tmp), "--account", env["GOG_ACCOUNT"], "--no-input"],
            capture_output=True, text=True, timeout=40, env=env,
        )
        if tmp.is_file() and tmp.stat().st_size > 20:
            drive_hash = hashlib.sha256(tmp.read_bytes()).hexdigest()
            drive_proven = bool(git_sha256) and drive_hash == git_sha256
        # Name-uniqueness is not queried here — leave count unknown.
    except Exception:
        drive_proven = False

    inst_path = REPO / "data" / "audit" / "cio_live_report_dry" / "cio_live_report.instance_manifest.json"
    report_instance = {}
    if inst_path.is_file():
        try:
            report_instance = json.loads(inst_path.read_text(encoding="utf-8"))
            (report_dir / "cio_live_report.instance_manifest.json").write_text(
                json.dumps(report_instance, indent=2, default=str), encoding="utf-8",
            )
        except Exception:
            report_instance = {}
    qa_pdf = ""
    qa_result = ""
    qa_instance = ""
    qa_page_hashes: list[str] = []
    if qa_json.is_file():
        try:
            qa = json.loads(qa_json.read_text(encoding="utf-8"))
            qa_pdf = str(qa.get("pdf_sha256") or "")
            qa_result = str(qa.get("result") or "")
            qa_instance = str(qa.get("report_instance_id") or "")
            raw_hashes = qa.get("page_image_hashes") or qa.get("page_hashes") or []
            if isinstance(raw_hashes, list):
                qa_page_hashes = [str(h) for h in raw_hashes if h]
        except Exception:
            pass
    live_plan_digest = ""
    live_decision_digest = ""
    if isinstance(plan, dict):
        live_plan_digest = str(plan.get("digest") or plan.get("plan_digest") or "")
        live_decision_digest = str(plan.get("decision_digest") or "")
        if not live_decision_digest:
            cons = (home or {}).get("consistency") if isinstance(home, dict) else {}
            if isinstance(cons, dict):
                live_decision_digest = str(cons.get("decision_digest") or "")

    audited_after = snapshot_audited_files(extra=[man_path], holdings=HOLDINGS)
    purity = compare_audited(audited_before, audited_after)
    (ev / "holdings_source_snapshot.json").write_text(json.dumps({
        "before": audited_before, "after": audited_after, "purity": purity,
    }, indent=2, default=str)[:200_000])

    snap = {
        "live_sha": live,
        "main_sha": main,
        "remote_sha_truth": remote_truth,
        "evaluator_attestation": evaluator_attestation,
        "current_holdings_sha256": current_holdings_sha256,
        "live_capital_plan_digest": live_plan_digest,
        "live_decision_digest": live_decision_digest,
        "manifest": manifest,
        "git_manifest_hash": git_sha256 if git_bytes.is_file() else str(manifest.get("manifest_hash") or ""),
        "drive_proven": drive_proven,
        "drive_canonical_hash": drive_hash,
        "drive_duplicate_count": drive_dups,
        "drive_canonical_file_id": drive_file_id,
        "acceptance_mutated_audited_book": not purity.get("audited_state_unchanged", True),
        "report_instance": {
            "report_instance_id": report_instance.get("report_id") or report_instance.get("report_instance_id"),
            "html_sha256": (report_instance.get("output_sha256") or {}).get("html"),
            "pdf_sha256": (report_instance.get("output_sha256") or {}).get("pdf"),
            "docx_sha256": (report_instance.get("output_sha256") or {}).get("docx"),
            "portfolio_snapshot_hash": (report_instance.get("input_hashes") or {}).get("holdings.json"),
            "expected_portfolio_snapshot_hash": current_holdings_sha256,
            "capital_plan_digest": report_instance.get("capital_plan_digest"),
            "decision_digest": report_instance.get("decision_digest"),
        },
        "report_pdf_sha256": (report_instance.get("output_sha256") or {}).get("pdf") or "",
        "pdf_page_count": int((report_instance.get("page_counts") or {}).get("pdf") or 0),
        "qa_pdf_sha256": qa_pdf,
        "qa_result": qa_result,
        "qa_instance_id": qa_instance,
        "qa_page_image_hashes": qa_page_hashes,
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
        "visual_qa_artifact": visual_artifact,
        "visual_qa_pages": visual_pages,
        "cio_token_env_set": cio_token_set,
        "general_token_used_in_cio_transport": general_used,
        "telegram_interdict_on": interdict,
        "telegram_sends_this_run": 0,
        "proof_general_sends": proof_general,
        "canary_evidence": canary,
        "authority_surfaces": surfaces,
        "cio_hardening_required": ci_required,
        "cio_hardening_green_on_sha": ci_green,
        "ci_content_sha": live,
        "ci_content_hardening_green": ci_green,
        "ci_attestation_sha": ci_attestation_sha,
        "ci_attestation_hardening_green": ci_attestation_green,
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
        "current_holdings_sha256": current_holdings_sha256,
        "report_dir": str(report_dir),
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
        "CORE_CIO_PRODUCTION_ACCEPTANCE": result.get("CORE_CIO_PRODUCTION_ACCEPTANCE"),
        "RESEARCH_GOVERNANCE_ACCEPTANCE": result.get("RESEARCH_GOVERNANCE_ACCEPTANCE"),
        "FULL_INVESTMENT_OFFICE_ACCEPTANCE": result.get("FULL_INVESTMENT_OFFICE_ACCEPTANCE"),
        "PRODUCTION_ACCEPTANCE": result["PRODUCTION_ACCEPTANCE"],
        "PRODUCTION_ACCEPTANCE_ALIAS_OF": result.get("PRODUCTION_ACCEPTANCE_ALIAS_OF"),
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
