"""Hermes CIO research worker: claim → backend.run → validate → persist → callback.

Worker is a job runner, not a second CIO. No Telegram, no orders/stops.
READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional, Protocol


class HermesWorkerError(Exception):
    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class HermesResearchStore(Protocol):
    def claim_next(self, *, worker_id: str, limit: int = 1) -> list[dict]: ...
    def mark_running(self, research_id: str, *, worker_id: str) -> None: ...
    def mark_completed(self, research_id: str, result: dict) -> dict: ...
    def mark_failed(self, research_id: str, error: str) -> None: ...
    def get_request(self, research_id: str) -> Optional[dict]: ...


class HermesResearchBackend(Protocol):
    def run(self, request: dict) -> dict:
        """Return ResearchResult body without identity stamping."""
        ...


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log_job(**fields: Any) -> None:
    row = {"event": "HERMES_WORKER_JOB", "ts": _now(), **fields}
    try:
        from pathlib import Path
        Path("data/cio").mkdir(parents=True, exist_ok=True)
        with open("data/cio/hermes_research_requests.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")
    except Exception:
        pass


class StubResearchBackend:
    """Deterministic answers from request questions — for tests and dry-run."""

    def run(self, request: dict) -> dict:
        auth = str(request.get("authority") or "READ_ONLY_ADVISORY")
        if auth != "READ_ONLY_ADVISORY":
            raise HermesWorkerError("authority_must_be_read_only_advisory", retryable=False)
        sym = request.get("symbol") or (request.get("subject") or {}).get("symbol") or "BOOK"
        pin = request.get("thesis_version") or "desk@?"
        answers = []
        findings = []
        for q in request.get("questions") or []:
            if not isinstance(q, dict):
                continue
            qid = q.get("question_id") or q.get("id") or "q"
            text = str(q.get("text") or "")
            intent = str(q.get("intent") or "thesis_check")
            summary = (
                f"[{intent}] Under {pin}, research for {sym}: "
                f"no execution path; hold/observe language only. Q: {text[:120]}"
            )
            answers.append({
                "question_id": qid,
                "status": "answered",
                "summary": summary[:400],
                "detail": summary[:800],
                "confidence": 0.55,
                "citations": [],
            })
            findings.append({
                "id": f"f_{qid}",
                "kind": "other",
                "severity": "low",
                "text": summary[:240],
                "confidence": 0.55,
            })
        if not answers:
            raise HermesWorkerError("no_questions", retryable=False)
        return {
            "as_of": _now(),
            "answers": answers,
            "findings": findings,
            "summary": f"Stub research for {sym} under {pin}: observe/hold bias; no orders.",
            "desk_implications": {
                "suggestion_bias": "hold_with_thesis",
                "changes_materiality": False,
                "watch_triggers": [],
                "notes": "Stub backend — replace with HermesBridgeBackend for live intel.",
            },
            "limitations": ["stub_backend"],
            "provenance": {"model_or_pipeline": "stub"},
        }


class CatalystFirstBackend:
    """Light narrative when catalyst_map intents dominate; falls back to stub."""

    def run(self, request: dict) -> dict:
        stub = StubResearchBackend().run(request)
        intents = [
            str(q.get("intent") or "")
            for q in (request.get("questions") or [])
            if isinstance(q, dict)
        ]
        if any("catalyst" in i for i in intents):
            cat = request.get("catalyst") or request.get("catalyst_pack") or {}
            ne = cat.get("next_event") if isinstance(cat, dict) else None
            if isinstance(ne, dict) and ne.get("session_date"):
                line = (
                    f"Calendar: {ne.get('kind')} on {ne.get('session_date')} "
                    f"severity={ne.get('severity')} — observe through event; "
                    f"does not alone authorize size change under READ_ONLY."
                )
                stub["findings"].insert(0, {
                    "id": "f_catalyst",
                    "kind": "catalyst",
                    "severity": ne.get("severity") or "low",
                    "text": line,
                    "confidence": 0.65,
                })
                stub["summary"] = line + " " + str(stub.get("summary") or "")
                stub["provenance"] = {"model_or_pipeline": "catalyst_first+stub"}
        return stub


class HermesWorker:
    def __init__(
        self,
        store: HermesResearchStore,
        backend: HermesResearchBackend,
        *,
        worker_id: str = "hermes-worker-1",
        on_completed: Optional[Callable[[dict, dict], Any]] = None,
        on_failed: Optional[Callable[[dict, str], Any]] = None,
    ):
        self.store = store
        self.backend = backend
        self.worker_id = worker_id
        self.on_completed = on_completed
        self.on_failed = on_failed

    def run_once(self, *, limit: int = 1) -> dict[str, Any]:
        claimed = self.store.claim_next(worker_id=self.worker_id, limit=limit)
        summary = {
            "claimed": len(claimed),
            "completed": 0,
            "failed": 0,
            "research_ids": [],
            "errors": [],
        }
        for req in claimed:
            rid = str(req.get("research_id") or "")
            summary["research_ids"].append(rid)
            try:
                self._process_one(req)
                summary["completed"] += 1
            except Exception as e:
                summary["failed"] += 1
                summary["errors"].append(f"{rid}:{type(e).__name__}:{e}")
        return summary

    def run_research_id(self, research_id: str) -> dict[str, Any]:
        req = self.store.get_request(research_id)
        if not req:
            return {"ok": False, "error": "unknown_research_id", "research_id": research_id}
        if req.get("status") not in ("queued", "running", "started", "failed"):
            # allow reprocess only queued/running/failed
            if req.get("status") == "completed":
                return {"ok": False, "error": "already_completed", "research_id": research_id}
        self.store.mark_running(research_id, worker_id=self.worker_id)
        req = self.store.get_request(research_id) or req
        req["status"] = "running"
        try:
            result = self._process_one(req)
            return {"ok": True, "result": result}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}:{e}", "research_id": research_id}

    def _process_one(self, request: dict[str, Any]) -> dict[str, Any]:
        try:
            from lib.hermes_research_schema import (
                AUTHORITY,
                stamp_result,
                validate_request,
                validate_result,
            )
        except Exception:
            from scripts.lib.hermes_research_schema import (  # type: ignore
                AUTHORITY,
                stamp_result,
                validate_request,
                validate_result,
            )

        rid = str(request.get("research_id") or "")
        if str(request.get("authority") or AUTHORITY) != AUTHORITY:
            raise HermesWorkerError("authority_must_be_read_only_advisory")

        ok, why = validate_request(request)
        if not ok:
            self.store.mark_failed(rid, error=why)
            if self.on_failed:
                try:
                    self.on_failed(request, why)
                except Exception:
                    pass
            _log_job(
                research_id=rid,
                plan_id=request.get("plan_id"),
                worker_id=self.worker_id,
                status="failed",
                error=why,
                priority=request.get("priority"),
            )
            raise HermesWorkerError(why)

        t0 = time.time()
        try:
            body = self.backend.run(request)
            latency_ms = int((time.time() - t0) * 1000)
            result = stamp_result(
                request, body, worker_id=self.worker_id, t0_ms=latency_ms,
            )
            vok, vwhy = validate_result(result, request)
            if not vok:
                self.store.mark_failed(rid, error=vwhy)
                if self.on_failed:
                    try:
                        self.on_failed(request, vwhy)
                    except Exception:
                        pass
                _log_job(
                    research_id=rid,
                    plan_id=request.get("plan_id"),
                    worker_id=self.worker_id,
                    status="failed",
                    latency_ms=latency_ms,
                    error=vwhy,
                    priority=request.get("priority"),
                )
                raise HermesWorkerError(vwhy)

            # Persist via store (complete_research_result path)
            stored = self.store.mark_completed(rid, result)
            if isinstance(stored, dict) and stored.get("result"):
                result = stored["result"]
            elif isinstance(stored, dict) and stored.get("ok") and stored.get("result"):
                result = stored["result"]

            if self.on_completed:
                try:
                    self.on_completed(request, result)
                except Exception as cb_err:
                    _log_job(
                        research_id=rid,
                        plan_id=request.get("plan_id"),
                        worker_id=self.worker_id,
                        status="completed_callback_error",
                        error=f"{type(cb_err).__name__}:{cb_err}",
                        priority=request.get("priority"),
                    )

            _log_job(
                research_id=rid,
                plan_id=request.get("plan_id"),
                worker_id=self.worker_id,
                status="completed",
                latency_ms=latency_ms,
                priority=request.get("priority"),
                error=None,
            )
            return result
        except HermesWorkerError:
            raise
        except Exception as e:
            err = f"{type(e).__name__}:{e}"[:500]
            try:
                self.store.mark_failed(rid, error=err)
            except Exception:
                pass
            if self.on_failed:
                try:
                    self.on_failed(request, err)
                except Exception:
                    pass
            _log_job(
                research_id=rid,
                plan_id=request.get("plan_id"),
                worker_id=self.worker_id,
                status="failed",
                error=err,
                priority=request.get("priority"),
            )
            raise
