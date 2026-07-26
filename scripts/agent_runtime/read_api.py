from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

from .contracts import assert_no_secret_material

READ_API_CONTRACT = "agent-runtime-command-center-read-api-v1"


class AgentRuntimeReader(Protocol):
    def list_runs(self, *, limit: int, offset: int, agent_id: str | None = None, status: str | None = None) -> Sequence[Mapping[str, Any]]: ...
    def get_run(self, run_id: str) -> Mapping[str, Any] | None: ...
    def list_artifacts(self, run_id: str) -> Sequence[Mapping[str, Any]]: ...
    def list_retrieval_evidence(self, run_id: str) -> Sequence[Mapping[str, Any]]: ...
    def list_tool_calls(self, run_id: str) -> Sequence[Mapping[str, Any]]: ...
    def list_reviews(self, run_id: str) -> Sequence[Mapping[str, Any]]: ...
    def list_scores(self, run_id: str) -> Sequence[Mapping[str, Any]]: ...
    def list_monitoring_events(self, run_id: str) -> Sequence[Mapping[str, Any]]: ...


@dataclass(frozen=True)
class ReadRoute:
    method: str
    path: str
    operation: str


READ_ROUTES = (
    ReadRoute("GET", "/api/v3/agent-runtime/runs", "list_runs"),
    ReadRoute("GET", "/api/v3/agent-runtime/runs/{run_id}", "get_run"),
    ReadRoute("GET", "/api/v3/agent-runtime/runs/{run_id}/artifacts", "list_artifacts"),
    ReadRoute("GET", "/api/v3/agent-runtime/runs/{run_id}/retrieval", "list_retrieval_evidence"),
    ReadRoute("GET", "/api/v3/agent-runtime/runs/{run_id}/tool-calls", "list_tool_calls"),
    ReadRoute("GET", "/api/v3/agent-runtime/runs/{run_id}/reviews", "list_reviews"),
    ReadRoute("GET", "/api/v3/agent-runtime/runs/{run_id}/scores", "list_scores"),
    ReadRoute("GET", "/api/v3/agent-runtime/runs/{run_id}/events", "list_monitoring_events"),
)


class ReadOnlyAgentRuntimeAPI:
    """Framework-neutral Command Center query surface.

    The class intentionally exposes no create, update, delete, cancel, resume,
    approve, schedule, provider, service, or execution method.
    """

    def __init__(self, reader: AgentRuntimeReader) -> None:
        self._reader = reader

    @staticmethod
    def routes() -> tuple[ReadRoute, ...]:
        return READ_ROUTES

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

    @staticmethod
    def _require_run_id(run_id: str) -> None:
        if not str(run_id or "").strip():
            raise ValueError("run_id is required")

    @staticmethod
    def _response(kind: str, data: Any, page: Mapping[str, Any] | None = None) -> dict[str, Any]:
        assert_no_secret_material(data)
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
        }
        if page is not None:
            response["page"] = dict(page)
        return response
