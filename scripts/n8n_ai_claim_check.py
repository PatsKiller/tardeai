#!/usr/bin/env python3
"""n8n lane ``ai-claim-check``: AI-written lanes re-audited nightly, deterministically (LQ-20261107-154).

DSN-20261107-LLM-AUTOMATION-PROGRAM.md item 154: "AI claim check over every AI-written lane: extract 3 claims,
verify against the stored source rows, flag HALLUCINATION... Deterministic checks (null / duplicate / stale /
out-of-range on each lane's natural key)... Results feed verdicts.json so the Ops tab re-audits itself."

    --dry-run   read the targets, print the verdicts; write nothing (the allowlist dry_run_arg)
    (no flag)   + write data/quality/ai_claim_check_verdicts.json and the LaneRunReceipt@v2
    --no-model  deterministic checks only; every claim is recorded ``unverifiable`` (model_unavailable), never green

The LLM proposes (one governed call per record, capped in config/llm_process_registry.json); deterministic code
disposes (scripts/lib/ai_claim_check.validate_claims: a verdict outside the closed vocabulary, or an evidence quote
that is not a verbatim substring of the stored source rows, is recorded and never accepted). A model refusal is
evidence, not the run's death: the run completes and the claim is ``unverifiable``.

Exit: 0 the run completed (findings are output); 2 the targets file is unusable. MBI_BEHAVIOR = 0: no broker, no
order, no send.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib import ai_claim_check as acc  # noqa: E402
from lib.lane_last_receipt import runtime_dir, write_lane_receipt  # noqa: E402

LANE_ID = "ai-claim-check"
PROCESS_ID = "ai_claim_check"
LLM_LANE = "deepseek-flash"
TARGETS_REL = "config/ai_claim_check_targets.json"
INSTRUCTION = (
    "You are checking claims made by an automated market-analysis lane. For EACH claim below, answer only from the "
    "SOURCE rows: verdict 'supported' when a source states it, 'refuted' when a source contradicts it. Every answer "
    "MUST carry evidence_quote copied VERBATIM from one source row; an invented quote is a hallucination. Return "
    'JSON: {"claims": [{"verdict": "supported|refuted", "evidence_quote": "..."}]} in the order given. No prose.'
)
MAX_SOURCE_CHARS = 1500


def state_root(explicit: str | None) -> Path:
    """The persistent state root (never the release dir): explicit -> executor env -> durable resolver."""
    for candidate in (explicit, os.environ.get("TRADEAI_PERSISTENT_STATE_ROOT")):
        if candidate:
            return Path(candidate)
    return runtime_dir().parent.parent


def governed_model(timeout_s: int = 90):
    """The model job, or None when the governed lane refuses. Never raises into the run."""
    def call(payload: dict):
        sources = [str(s)[:MAX_SOURCE_CHARS] for s in (payload.get("sources") or [])][:12]
        request = {"lane": payload.get("lane"), "record_key": payload.get("record_key"),
                   "claims": payload.get("claims") or [], "sources": sources}
        try:
            # scripts/ is on sys.path inside the lane (the executor runs the script), so this module is top-level
            from llm_consumption import gate_and_generate  # type: ignore[import-not-found] -- lane import path
            text = gate_and_generate(INSTRUCTION + "\n\n" + json.dumps(request, ensure_ascii=False),
                                     lane=LLM_LANE, process_id=PROCESS_ID,
                                     task_summary=f"ai claim check {payload.get('record_key')}",
                                     response_json=True, max_tokens=700, timeout=timeout_s,
                                     metadata={"record_key": payload.get("record_key"), "prompt_version": "claim-check-v1"})
        except Exception as exc:  # noqa: BLE001 -- a refused/unavailable model is recorded, never fatal
            raise RuntimeError(f"model_unavailable:{type(exc).__name__}") from exc
        return json.loads(text) if isinstance(text, str) else text
    return call


def lane_output(doc: dict, targets: int, readable: int) -> dict:
    """The v2 receipt fields. produced and attempted count the SAME population: one graded verdict row per target.

    This lane's output is the verdict for each registered target, so ``produced_count`` is the number of verdict
    rows written and ``attempted_count`` is the number of targets examined — the same number by construction. An
    unreadable target still gets a row (graded FAIL, ``missing_artifact``), because "the checker could not read this
    artifact" is the finding; counting only readable targets as produced would pair produced with attempted from two
    populations, which the verdict rejects as ``counts_inconsistent`` (the conflict-resolver / macro shape,
    LQ-20261107-134). ``skipped_reasons`` and ``summary.missing_artifacts`` carry the read failures.
    """
    counts = doc.get("counts", {})
    return {
        "produced_count": len(doc.get("targets") or []),
        "attempted_count": targets,
        "skipped_reasons": ({"missing_artifact": targets - readable} if targets > readable else {}),
        "empty_reason": ("no_targets" if not targets else None),
        "summary": {"verdict": doc.get("verdict"), **counts},
        "output_evidence": [{"path": acc.VERDICTS_FILE, "kind": "verdicts"}],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("--dry-run", action="store_true", help="read and print; write nothing")
    ap.add_argument("--no-model", action="store_true", help="deterministic checks only; claims unverifiable")
    ap.add_argument("--targets")
    ap.add_argument("--state-root")
    a = ap.parse_args(argv)
    root = state_root(a.state_root)
    # the targets file is repository config, not state: resolved against the release tree this script lives in
    targets_path = Path(a.targets) if a.targets else _SCRIPTS.parent / TARGETS_REL
    started = acc.now_iso()
    try:
        targets = acc.load_targets(targets_path)
    except (OSError, ValueError) as exc:
        if not a.dry_run:
            write_lane_receipt(LANE_ID, ok=False, exit_code=2, started_at=started, script="scripts/n8n_ai_claim_check.py",
                               path=root / "data/runtime/ai-claim-check_last.json",
                               summary={"targets_file": str(targets_path)}, error=type(exc).__name__,
                               produced_count=0, attempted_count=0, empty_reason="targets_unusable")
        print(json.dumps({"ok": False, "error": type(exc).__name__, "targets_file": str(targets_path)}))
        return 2
    # a dry run never spends: no model call, no verdicts file, no receipt
    model = None if (a.no_model or a.dry_run) else governed_model()
    run_id = os.environ.get("TRADEAI_RUN_ID")
    doc = acc.build_verdicts(targets, root, model=model, run_id=run_id)
    readable = sum(1 for t in doc["targets"] if not any(f["kind"] == "missing_artifact" for f in t["findings"]))
    out = lane_output(doc, len(targets), readable)
    if a.dry_run:
        print(json.dumps({"mode": "dry_run", **out["summary"], "targets": len(targets), "readable": readable,
                          "verdicts": [(t["id"], t["verdict"], t["checked"]) for t in doc["targets"]]}))
        return 0
    written = acc.write_verdicts(root, doc)
    evidence = [{"path": acc.VERDICTS_FILE, "sha256": acc.sha256_file(written), "kind": "verdicts"}]
    receipt = write_lane_receipt(LANE_ID, ok=True, exit_code=0, started_at=started,
                                 script="scripts/n8n_ai_claim_check.py",
                                 path=root / "data/runtime/ai-claim-check_last.json", summary=out["summary"],
                                 produced_count=out["produced_count"], attempted_count=out["attempted_count"],
                                 skipped_reasons=out["skipped_reasons"], empty_reason=out["empty_reason"],
                                 output_evidence=evidence)
    if receipt is None:
        print(json.dumps({"ok": False, "error": "receipt_write_failed"}))
        return 1
    print(json.dumps({"ok": True, **out["summary"], "targets": len(targets), "readable": readable,
                      "verdicts_file": acc.VERDICTS_FILE}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
