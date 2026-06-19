#!/usr/bin/env python3
"""Validate Rotation Intelligence production-readiness guardrails.

This is a static + lightweight semantic validator for the advisory-only rotation
advisor and Command Center integration. It does not call brokers, Grok, ChatGPT,
or any external network service.

Exit codes:
  0 = advisory production-readiness gate passed
  1 = blockers found
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

FILES = {
    "dual_script": ROOT / "scripts" / "rotation_dual_llm_advisor.py",
    "local_script": ROOT / "scripts" / "rotation_llm_advisor.py",
    "rotation_page": ROOT / "apps" / "command-center-v3" / "src" / "pages" / "RotationIntelligence.tsx",
    "changes_page": ROOT / "apps" / "command-center-v3" / "src" / "pages" / "AdvisorChangesHub.tsx",
    "app": ROOT / "apps" / "command-center-v3" / "src" / "App.tsx",
    "nav": ROOT / "apps" / "command-center-v3" / "src" / "components" / "NavRail.tsx",
    "runbook": ROOT / "docs" / "project" / "ROTATION_LLM_ADVISOR.md",
}

SCRIPT_FORBIDDEN = [
    "XAI_API_KEY",
    "XAI_BASE_URL",
    "XAI_GROK_MODEL",
    "api.x.ai",
    "chat/completions",
    "urllib.request",
    "requests.post",
]

REQUIRED_DUAL_STRINGS = [
    "--print-grok-prompt-path",
    "--print-grok-prompt",
    "--skip-local",
    "trust_verdict",
    "grounded_no_supported_action",
    "grok_can_override_grounding",
    "uses_api_key",
    "uses_paid_xai_api",
    "uses_direct_grok_http",
    "broker_action",
    "local_console_output",
    "contextlib.redirect_stdout",
    "contextlib.redirect_stderr",
]

REQUIRED_UI_STRINGS = [
    "RotationIntelligence",
    "AdvisorChangesHub",
    "path=\"rotation\"",
    "path=\"advisor-changes\"",
    "to: '/rotation'",
    "to: '/advisor-changes'",
]

ADVISORY_LANGUAGE = [
    "advisory only",
    "no broker action",
    "human review",
]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def add(checks: list[dict[str, Any]], name: str, ok: bool, severity: str = "blocker", detail: str = "") -> None:
    checks.append({"name": name, "ok": ok, "severity": severity, "detail": detail})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    checks: list[dict[str, Any]] = []
    contents = {k: read(v) for k, v in FILES.items()}

    for key, path in FILES.items():
        add(checks, f"file_exists:{key}", path.exists(), detail=str(path))

    dual = contents["dual_script"]
    for token in SCRIPT_FORBIDDEN:
        add(checks, f"no_forbidden_dual_token:{token}", token not in dual, detail="direct paid/API Grok path must not exist")

    for token in REQUIRED_DUAL_STRINGS:
        add(checks, f"dual_contains:{token}", token in dual, detail="dual advisor must expose production guardrail")

    # The manual prompt mode may mention Grok, but it must also state that it does not use an API key.
    lowered_dual = dual.lower()
    add(checks, "dual_declares_no_api_key", "no api key" in lowered_dual or "no api keys" in lowered_dual)
    add(checks, "dual_declares_no_outbound_http", "no outbound http" in lowered_dual)
    add(checks, "dual_declares_manual_second_opinion", "manual" in lowered_dual and "second-opinion" in lowered_dual)

    app_nav = contents["app"] + "\n" + contents["nav"]
    for token in REQUIRED_UI_STRINGS:
        add(checks, f"ui_contains:{token}", token in app_nav)

    rotation_page = contents["rotation_page"].lower()
    for phrase in ADVISORY_LANGUAGE:
        add(checks, f"rotation_page_language:{phrase}", phrase in rotation_page, severity="warning")
    add(checks, "rotation_page_mentions_free_oauth", "free" in rotation_page and "oauth" in rotation_page, severity="warning")
    add(checks, "rotation_page_has_defensive_json_parse", "non-json" in rotation_page and "truncated" in rotation_page, severity="warning")

    runbook = contents["runbook"].lower()
    add(checks, "runbook_documents_no_api_key", "no api key" in runbook or "no api keys" in runbook, severity="warning")
    add(checks, "runbook_documents_manual_or_oauth_grok", "oauth" in runbook and "grok" in runbook, severity="warning")

    # Flag dangerous imperative language in the rotation page only if it appears near broker/order context.
    dangerous_patterns = [
        r"place\s+order",
        r"execute\s+trade",
        r"broker\s+submit",
        r"buy\s+now",
        r"sell\s+now",
    ]
    for pat in dangerous_patterns:
        add(checks, f"no_dangerous_ui_language:{pat}", re.search(pat, rotation_page) is None)

    blockers = [c for c in checks if not c["ok"] and c["severity"] == "blocker"]
    warnings = [c for c in checks if not c["ok"] and c["severity"] == "warning"]
    passed = not blockers

    # Mature advisory production target: static blockers clean + only low-risk warnings.
    maturity_score = 8.0 if passed and len(warnings) <= 2 else 7.0 if passed else 6.0
    result = {
        "ok": passed,
        "advisory_only": True,
        "maturity_score": maturity_score,
        "target_state": "8.x advisory-production-ready" if passed else "blocked",
        "blocker_count": len(blockers),
        "warning_count": len(warnings),
        "blockers": blockers,
        "warnings": warnings,
        "checks": checks,
    }

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"rotation_readiness_ok={str(passed).lower()} maturity_score={maturity_score} blockers={len(blockers)} warnings={len(warnings)}")
        if blockers:
            print("BLOCKERS:")
            for b in blockers:
                print(f"- {b['name']}: {b['detail']}")
        if warnings:
            print("WARNINGS:")
            for w in warnings:
                print(f"- {w['name']}: {w['detail']}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
