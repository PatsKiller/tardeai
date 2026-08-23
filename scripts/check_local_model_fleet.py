#!/usr/bin/env python3
"""Audit the embedding-only Ollama runtime; never invoke local generation."""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.ollama_embedding_policy import (  # noqa: E402
    ALLOWED_MODEL,
    ALLOWED_MODEL_DIGEST,
    EXPECTED_DIMENSION,
    embed,
)

BASE = "http://127.0.0.1:11434"


def _get(path: str) -> dict:
    with urllib.request.urlopen(f"{BASE}{path}", timeout=10) as response:
        return json.loads(response.read())


def run() -> dict:
    try:
        installed = _get("/api/tags").get("models") or []
        resident = _get("/api/ps").get("models") or []
    except Exception as exc:
        return {
            "gpu_mode": "UNMEASURED",
            "ollama_reachable": False,
            "error": f"{type(exc).__name__}:{exc}",
            "compliant": False,
        }

    allowed_names = {ALLOWED_MODEL, f"{ALLOWED_MODEL}:latest"}
    forbidden_installed = sorted(
        str(item.get("name") or "") for item in installed
        if str(item.get("name") or "") not in allowed_names
    )
    forbidden_resident = sorted(
        str(item.get("name") or "") for item in resident
        if str(item.get("name") or "") not in allowed_names
    )
    approved = next(
        (item for item in installed if str(item.get("name") or "") in allowed_names),
        None,
    )
    digest = str((approved or {}).get("digest") or "")
    digest_match = digest == ALLOWED_MODEL_DIGEST
    latency_s = None
    dimension = None
    embed_error = None
    if approved and digest_match and not forbidden_resident:
        started = time.monotonic()
        try:
            dimension = len(embed("Trade AI embedding health probe", timeout_s=30))
            latency_s = round(time.monotonic() - started, 4)
        except Exception as exc:
            embed_error = f"{type(exc).__name__}:{exc}"

    compliant = bool(
        approved
        and digest_match
        and dimension == EXPECTED_DIMENSION
        and not forbidden_installed
        and not forbidden_resident
    )
    return {
        "gpu_mode": "EMBEDDINGS_ONLY" if compliant else "UNMEASURED",
        "ollama_reachable": True,
        "approved_model": ALLOWED_MODEL,
        "expected_digest": ALLOWED_MODEL_DIGEST,
        "installed_digest": digest or None,
        "digest_match": digest_match,
        "dimension": dimension,
        "expected_dimension": EXPECTED_DIMENSION,
        "latency_s": latency_s,
        "embedding_error": embed_error,
        "forbidden_installed": forbidden_installed,
        "forbidden_resident": forbidden_resident,
        "compliant": compliant,
    }


def _emit_alert(report: dict) -> None:
    if report.get("compliant"):
        return
    try:
        from alert_event_writer import save_alert_event
        save_alert_event(
            alert_type="system_health",
            raw_text="[gpu_embedding_policy] " + json.dumps(report, default=str),
            severity="critical",
            source_script="check_local_model_fleet.py",
            parsed_payload={"kind": "gpu_embedding_policy", **report},
        )
    except Exception as exc:
        print(f"[alert] could not write GPU policy alert: {exc}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--alert", action="store_true")
    args = parser.parse_args()
    report = run()
    print(json.dumps(report, indent=2, sort_keys=True))
    if args.alert:
        _emit_alert(report)
    return 0 if report.get("compliant") else 1


if __name__ == "__main__":
    raise SystemExit(main())
