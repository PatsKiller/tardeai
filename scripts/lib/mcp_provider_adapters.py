"""mcp_provider_adapters.py — read-only provider contracts + local test doubles.

READ_ONLY_ADVISORY. These adapters are in-memory, deterministic, and expose
NO write methods. They are the only thing the MCP gateway is allowed to call.

External backends (Google Calendar / Google Documents) are intentionally
NOT_CONFIGURED: there are no credentials and no network path, so the gateway
fails soft instead of fabricating a connection.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ReadOnlyProvider(Protocol):
    """Narrow, duck-typed contract every read-only provider satisfies."""

    name: str
    domain: str

    def get(self, **kwargs: Any) -> dict: ...

    def search(self, **kwargs: Any) -> dict: ...

    def health(self) -> bool: ...


class _BaseLocalProvider:
    """Shared read-only scaffolding. No write methods exist here or below."""

    name = "LocalProvider"
    domain = "local"
    _SOURCE_ASOF = "2026-08-16T00:00:00+00:00"

    def health(self) -> bool:
        return True

    def _result(self, **payload: Any) -> dict:
        out = dict(payload)
        out.setdefault("source_asof", self._SOURCE_ASOF)
        out.setdefault("provider", self.name)
        return out


class LocalPortfolioProvider(_BaseLocalProvider):
    name = "LocalPortfolioProvider"
    domain = "portfolio"

    def __init__(self) -> None:
        self._snapshots = {
            "verified": {
                "account_id": "acct_1",
                "holdings": [{"symbol": "SCHD", "shares": 100}],
                "verified": True,
            },
            "cash": {"account_id": "acct_1", "cash": 25000.0, "currency": "USD"},
            "risk": {"account_id": "acct_1", "risk_score": "LOW", "limits_ok": True},
        }

    def get(self, **kwargs: Any) -> dict:
        tool = str(kwargs.get("tool", ""))
        if tool.endswith("get_cash_snapshot"):
            return self._result(kind="cash", snapshot=self._snapshots["cash"])
        if tool.endswith("get_risk_snapshot"):
            return self._result(kind="risk", snapshot=self._snapshots["risk"])
        return self._result(kind="verified", snapshot=self._snapshots["verified"])

    def search(self, **kwargs: Any) -> dict:
        return self._result(kind="verified", snapshot=self._snapshots["verified"])


class LocalDecisionsProvider(_BaseLocalProvider):
    name = "LocalDecisionsProvider"
    domain = "decisions"

    def __init__(self) -> None:
        self._decisions = {
            "dec_1": {"decision_id": "dec_1", "action": "HOLD", "act_now": False},
            "dec_2": {"decision_id": "dec_2", "action": "WAIT", "act_now": False},
        }

    def get(self, **kwargs: Any) -> dict:
        decision_id = kwargs.get("decision_id")
        return self._result(decision=self._decisions.get(str(decision_id), {}))

    def search(self, **kwargs: Any) -> dict:
        decisions = list(self._decisions.values())
        return self._result(decisions=decisions, count=len(decisions))


class LocalResearchProvider(_BaseLocalProvider):
    name = "LocalResearchProvider"
    domain = "research"

    def __init__(self) -> None:
        self._sources = {
            "src_1": {"source_id": "src_1", "title": "Q2 earnings note", "url": None},
            "src_2": {"source_id": "src_2", "title": "Dividend anchor thesis", "url": None},
        }
        self._results = [
            {"source_id": "src_1", "excerpt": "SCHD income anchor"},
            {"source_id": "src_2", "excerpt": "re-entry wait regime"},
        ]

    def get(self, **kwargs: Any) -> dict:
        source_id = kwargs.get("source_id")
        return self._result(source=self._sources.get(str(source_id), {}))

    def search(self, **kwargs: Any) -> dict:
        return self._result(results=self._results, count=len(self._results))


class LocalDocumentsProvider(_BaseLocalProvider):
    name = "LocalDocumentsProvider"
    domain = "documents"

    def __init__(self) -> None:
        self._documents = {
            "doc_1": {"document_id": "doc_1", "title": "Capital plan v3", "path": "plans/capital_v3.pdf"},
            "doc_2": {"document_id": "doc_2", "title": "Risk policy (read)", "path": "policy/risk.md"},
        }

    def get(self, **kwargs: Any) -> dict:
        document_id = kwargs.get("document_id")
        return self._result(document=self._documents.get(str(document_id), {}))

    def search(self, **kwargs: Any) -> dict:
        documents = list(self._documents.values())
        return self._result(documents=documents, count=len(documents))


class LocalCalendarProvider(_BaseLocalProvider):
    name = "LocalCalendarProvider"
    domain = "calendar"

    def __init__(self) -> None:
        self._events = {
            "evt_1": {"event_id": "evt_1", "summary": "Earnings call", "when": "2026-08-18"},
            "evt_2": {"event_id": "evt_2", "summary": "Quarterly review", "when": "2026-08-25"},
        }

    def get(self, **kwargs: Any) -> dict:
        event_id = kwargs.get("event_id")
        return self._result(event=self._events.get(str(event_id), {}))

    def search(self, **kwargs: Any) -> dict:
        events = list(self._events.values())
        return self._result(events=events, count=len(events))


class LocalGoalsPlansProvider(_BaseLocalProvider):
    name = "LocalGoalsPlansProvider"
    domain = "goals_plans"

    def __init__(self) -> None:
        self._goals = [
            {"goal_id": "goal_1", "title": "Income stability"},
            {"goal_id": "goal_2", "title": "Capital preservation"},
        ]
        self._plans = {
            "plan_1": {"plan_id": "plan_1", "title": "Q3 allocation plan", "status": "draft"},
        }

    def get(self, **kwargs: Any) -> dict:
        plan_id = kwargs.get("plan_id")
        return self._result(plan=self._plans.get(str(plan_id), {}))

    def search(self, **kwargs: Any) -> dict:
        return self._result(goals=self._goals, count=len(self._goals))


class NotConfiguredProvider:
    """Fail-soft stub for external backends (Google Calendar / Documents).

    ``health()`` is False and every read reports NOT_CONFIGURED, so the gateway
    returns ok=False / status=NOT_CONFIGURED instead of fabricating a backend.
    """

    name = "NotConfiguredProvider"
    domain = "external"
    configured = False

    def health(self) -> bool:
        return False

    def get(self, **kwargs: Any) -> dict:
        return {"status": "NOT_CONFIGURED", "error": "external backend has no credentials"}

    def search(self, **kwargs: Any) -> dict:
        return {"status": "NOT_CONFIGURED", "error": "external backend has no credentials"}


def build_local_provider_registry() -> dict[str, object]:
    """Map each allowlisted tool name to a fresh, in-memory local provider."""
    portfolio = LocalPortfolioProvider()
    decisions = LocalDecisionsProvider()
    research = LocalResearchProvider()
    documents = LocalDocumentsProvider()
    calendar = LocalCalendarProvider()
    goals_plans = LocalGoalsPlansProvider()
    registry: dict[str, object] = {
        "portfolio.get_verified_snapshot": portfolio,
        "portfolio.get_cash_snapshot": portfolio,
        "portfolio.get_risk_snapshot": portfolio,
        "decisions.get": decisions,
        "decisions.search_history": decisions,
        "research.search": research,
        "research.get_source": research,
        "documents.search": documents,
        "documents.get": documents,
        "calendar.search": calendar,
        "calendar.get_event": calendar,
        "goals.list": goals_plans,
        "plans.get": goals_plans,
    }
    # Financial Senses: same gateway, fixture providers (no network).
    try:
        from scripts.lib.financial_senses_aif import (
            build_financial_senses_registry,
            build_fixture_providers,
        )
        registry.update(build_financial_senses_registry(build_fixture_providers()))
    except Exception:
        pass
    return registry


def build_external_not_configured_registry() -> dict[str, object]:
    """Calendar/documents external backends, all NOT_CONFIGURED until credentials exist."""
    nc = NotConfiguredProvider()
    return {
        "calendar.search": nc,
        "calendar.get_event": nc,
        "documents.search": nc,
        "documents.get": nc,
    }
