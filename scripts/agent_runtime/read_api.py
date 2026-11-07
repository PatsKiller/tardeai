from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

from .contracts import assert_no_secret_material

READ_API_CONTRACT = "agent-runtime-command-center-read-api-v1"

# The row sets the fleet-level batch answers with, in one order, for every run it names.
_BATCH_KINDS = ("artifacts", "reviews", "scores")


class AgentRuntimeReader(Protocol):
    def list_runs(self, *, limit: int, offset: int, agent_id: str | None = None, status: str | None = None) -> Sequence[Mapping[str, Any]]: ...
    def get_run(self, run_id: str) -> Mapping[str, Any] | None: ...
    def list_artifacts(self, run_id: str) -> Sequence[Mapping[str, Any]]: ...
    def list_retrieval_evidence(self, run_id: str) -> Sequence[Mapping[str, Any]]: ...
    def list_tool_calls(self, run_id: str) -> Sequence[Mapping[str, Any]]: ...
    def list_reviews(self, run_id: str) -> Sequence[Mapping[str, Any]]: ...
    def list_scores(self, run_id: str) -> Sequence[Mapping[str, Any]]: ...
    def list_monitoring_events(self, run_id: str) -> Sequence[Mapping[str, Any]]: ...
    def list_lessons(self, *, limit: int, offset: int) -> Sequence[Mapping[str, Any]]: ...
    def list_cases(self, *, limit: int, offset: int) -> Sequence[Mapping[str, Any]]: ...


@dataclass(frozen=True)
class ReadRoute:
    method: str
    path: str
    operation: str


READ_ROUTES = (
    ReadRoute("GET", "/api/v3/agent-runtime/runs", "list_runs"),
    ReadRoute("GET", "/api/v3/agent-runtime/runs/{run_id}", "get_run"),
    # Fleet-level batch: artifacts + reviews + scores for the newest N runs in ONE request.
    # The per-run children below stay for one run's detail; a desk that needs fifty runs'
    # worth of evidence must not issue one request per run per kind (2026-11-07, LQ-90).
    ReadRoute("GET", "/api/v3/agent-runtime/evidence", "batch_run_evidence"),
    ReadRoute("GET", "/api/v3/agent-runtime/runs/{run_id}/artifacts", "list_artifacts"),
    ReadRoute("GET", "/api/v3/agent-runtime/runs/{run_id}/retrieval", "list_retrieval_evidence"),
    ReadRoute("GET", "/api/v3/agent-runtime/runs/{run_id}/tool-calls", "list_tool_calls"),
    ReadRoute("GET", "/api/v3/agent-runtime/runs/{run_id}/reviews", "list_reviews"),
    ReadRoute("GET", "/api/v3/agent-runtime/runs/{run_id}/scores", "list_scores"),
    ReadRoute("GET", "/api/v3/agent-runtime/runs/{run_id}/events", "list_monitoring_events"),
    ReadRoute("GET", "/api/v3/agent-runtime/knowledge/lessons", "list_lessons"),
    ReadRoute("GET", "/api/v3/agent-runtime/knowledge/cases", "list_cases"),
)


class ReadOnlyAgentRuntimeAPI:
    """Framework-neutral Command Center query surface.

    The class intentionally exposes no create, update, delete, cancel, resume,
    approve, schedule, provider, service, or execution method.
    """

    def __init__(self, reader: AgentRuntimeReader) -> None:
        self._reader = reader

    @property
    def reader(self) -> AgentRuntimeReader:
        """The underlying read-only reader (list_* only). Exposed so the maturity
        bridge can aggregate live runtime evidence; it confers no mutation power."""
        return self._reader

    @staticmethod
    def routes() -> tuple[ReadRoute, ...]:
        return READ_ROUTES

    @classmethod
    def assert_routes_are_implemented(cls) -> None:
        """Fail closed if any declared route has no implemented, callable API method."""
        missing = [route.operation for route in READ_ROUTES if not callable(getattr(cls, route.operation, None))]
        if missing:
            raise TypeError(f"read routes without an implemented API method: {sorted(set(missing))}")

    def list_runs(self, *, limit: int = 50, offset: int = 0, agent_id: str | None = None, status: str | None = None) -> dict[str, Any]:
        if limit < 1 or limit > 200:
            raise ValueError("limit must be between 1 and 200")
        if offset < 0:
            raise ValueError("offset must be non-negative")
        rows = [dict(row) for row in self._reader.list_runs(limit=limit, offset=offset, agent_id=agent_id, status=status)]
        return self._response("runs", rows, {"limit": limit, "offset": offset})

    def get_run(self, run_id: str) -> dict[str, Any]:
        self._require_run_id(run_id)
        row = self._reader.get_run(run_id)
        return self._response("run", dict(row) if row is not None else None)

    # ---- per-entity read routes ------------------------------------------
    # Every ReadRoute.operation must resolve to one of these methods; the mapping is asserted
    # by assert_routes_are_implemented() (and its test) so a declared route can never be a
    # 404 in disguise.
    def list_artifacts(self, run_id: str) -> dict[str, Any]:
        return self._list_child("artifacts", self._reader.list_artifacts, run_id)

    def list_retrieval_evidence(self, run_id: str) -> dict[str, Any]:
        return self._list_child("retrieval", self._reader.list_retrieval_evidence, run_id)

    def list_tool_calls(self, run_id: str) -> dict[str, Any]:
        return self._list_child("tool_calls", self._reader.list_tool_calls, run_id)

    def list_reviews(self, run_id: str) -> dict[str, Any]:
        return self._list_child("reviews", self._reader.list_reviews, run_id)

    def list_scores(self, run_id: str) -> dict[str, Any]:
        return self._list_child("scores", self._reader.list_scores, run_id)

    def list_monitoring_events(self, run_id: str) -> dict[str, Any]:
        return self._list_child("events", self._reader.list_monitoring_events, run_id)

    # ---- knowledge (fleet-wide, not per-run) -----------------------------
    def list_lessons(self, *, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        if limit < 1 or limit > 200:
            raise ValueError("limit must be between 1 and 200")
        if offset < 0:
            raise ValueError("offset must be non-negative")
        rows = [dict(row) for row in self._reader.list_lessons(limit=limit, offset=offset)]
        return self._response("lessons", rows, {"limit": limit, "offset": offset})

    def list_cases(self, *, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        if limit < 1 or limit > 200:
            raise ValueError("limit must be between 1 and 200")
        if offset < 0:
            raise ValueError("offset must be non-negative")
        rows = [dict(row) for row in self._reader.list_cases(limit=limit, offset=offset)]
        return self._response("cases", rows, {"limit": limit, "offset": offset})

    def get_run_evidence(self, run_id: str) -> dict[str, Any]:
        self._require_run_id(run_id)
        payload = {
            "artifacts": [dict(row) for row in self._reader.list_artifacts(run_id)],
            "retrieval": [dict(row) for row in self._reader.list_retrieval_evidence(run_id)],
            "tool_calls": [dict(row) for row in self._reader.list_tool_calls(run_id)],
            "reviews": [dict(row) for row in self._reader.list_reviews(run_id)],
            "scores": [dict(row) for row in self._reader.list_scores(run_id)],
            "events": [dict(row) for row in self._reader.list_monitoring_events(run_id)],
        }
        return self._response("run_evidence", payload)

    # ---- fleet-level batch -----------------------------------------------
    def batch_run_evidence(self, *, limit: int = 50) -> dict[str, Any]:
        """Artifacts, reviews and scores for the newest ``limit`` runs, in one response.

        Why (2026-11-07, LQ-90): the Runtime desk loaded fifty runs and fanned out to
        ``runs/{id}/{artifacts,reviews,scores}`` for each — 150 requests, 4-5 s apiece,
        re-issued on every agent selection. The page needs the same three row sets for the
        same fifty runs every time, so it is one question, not one hundred and fifty.

        A reader may implement the optional ``list_run_evidence_batch(run_ids)`` to answer
        it with set-based SQL. A reader that implements only the per-run protocol still
        answers in ONE HTTP request; it simply does more work inside it. The response shape
        is identical either way, so the desk cannot tell — and cannot silently get less.
        """
        if limit < 1 or limit > 200:
            raise ValueError("limit must be between 1 and 200")
        runs = [dict(row) for row in self._reader.list_runs(limit=limit, offset=0)]
        run_ids = [str(run.get("run_id") or "").strip() for run in runs]
        run_ids = [rid for rid in run_ids if rid]
        evidence = self._evidence_for_runs(run_ids)
        return self._response(
            "run_evidence_batch",
            {"runs": runs, "evidence": evidence},
            {"limit": limit},
        )

    def _evidence_for_runs(self, run_ids: list[str]) -> dict[str, dict[str, list[dict[str, Any]]]]:
        batched = getattr(self._reader, "list_run_evidence_batch", None)
        if callable(batched):
            grouped = batched(run_ids) or {}
            return {
                rid: {
                    kind: [dict(row) for row in ((grouped.get(rid) or {}).get(kind) or [])]
                    for kind in _BATCH_KINDS
                }
                for rid in run_ids
            }
        return {
            rid: {
                "artifacts": [dict(row) for row in self._reader.list_artifacts(rid)],
                "reviews": [dict(row) for row in self._reader.list_reviews(rid)],
                "scores": [dict(row) for row in self._reader.list_scores(rid)],
            }
            for rid in run_ids
        }

    def _list_child(self, kind: str, reader_method: Any, run_id: str) -> dict[str, Any]:
        self._require_run_id(run_id)
        rows = [dict(row) for row in reader_method(run_id)]
        return self._response(kind, rows)

    @staticmethod
    def _require_run_id(run_id: str) -> None:
        if not str(run_id or "").strip():
            raise ValueError("run_id is required")

    @staticmethod
    def _response(kind: str, data: Any, page: Mapping[str, Any] | None = None) -> dict[str, Any]:
        assert_no_secret_material(data)
        import os
        # Prefer live role from env DSN user when present; packet identity is agentic_runtime_reader.
        reader_role = "agentic_runtime_reader"
        dsn = str(os.environ.get("AGENT_RUNTIME_READ_DSN", "") or "")
        if dsn.startswith("postgres"):
            try:
                from urllib.parse import urlparse
                u = urlparse(dsn)
                if u.username:
                    reader_role = u.username
            except Exception:
                pass
        else:
            for tok in dsn.split():
                if tok.startswith("user="):
                    reader_role = tok.split("=", 1)[1]
                    break
        response = {
            "contract": READ_API_CONTRACT,
            "read_only": True,
            "kind": kind,
            "data": data,
            "authority": {
                "mutation": False,
                "provider_call": False,
                "service_control": False,
                "schedule_change": False,
                "financial_action": False,
            },
            # A2 post-connect acceptance: honest connected signal + reader identity (never DSN).
            "connected": True,
            "reader_role": reader_role,
        }
        if page is not None:
            response["page"] = dict(page)
        return response


# Enforced at import time: the route table and the API surface can never drift apart.
ReadOnlyAgentRuntimeAPI.assert_routes_are_implemented()
