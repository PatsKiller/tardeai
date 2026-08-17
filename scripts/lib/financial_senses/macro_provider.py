"""FredAlfredProvider — FRED / ALFRED macro and vintage-aware provider.

Read-only macro context. Historical queries are vintage-aware: they distinguish
LATEST_REVISED_VALUE from VALUE_AVAILABLE_AS_OF_DECISION_TIME and never leak a
later revision backward into a historical decision. No network in unit tests —
the FRED client is injectable.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from .provider import BaseProvider, Capability
from .result import Fact, FinancialSenseResult, Quality, Subject, STATUS_OK
from .source_governance import SOURCE_PRIMARY_GOVERNMENT, grade_for_source
from . import macro_catalog

FRED_BASE = "https://api.stlouisfed.org/fred"
SOURCE_MACRO = SOURCE_PRIMARY_GOVERNMENT


def _parse_observations(payload: dict) -> list[dict]:
    rows = []
    for obs in (payload or {}).get("observations") or []:
        val = obs.get("value")
        if val in (None, ".", ""):
            continue
        try:
            num = float(val)
        except (TypeError, ValueError):
            continue
        rows.append({"date": obs.get("date"), "value": num})
    return rows


class FredClient:
    """Thin read-only client over the official FRED/ALFRED JSON API."""

    def __init__(
        self,
        api_key: str,
        fetcher: Optional[Callable[[str], dict]] = None,
        base: str = FRED_BASE,
    ) -> None:
        self.api_key = api_key
        self.base = base.rstrip("/")
        self._fetcher = fetcher or self._default_fetcher

    @staticmethod
    def _default_fetcher(url: str) -> dict:
        import json
        import urllib.request

        with urllib.request.urlopen(url, timeout=15.0) as resp:
            return json.loads(resp.read())

    def _get(self, path: str, params: dict) -> dict:
        params = dict(params)
        params["api_key"] = self.api_key
        params["file_type"] = "json"
        qs = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
        return self._fetcher(f"{self.base}/{path}?{qs}") or {}

    def observations(
        self,
        series_id: str,
        realtime_start: Optional[str] = None,
        realtime_end: Optional[str] = None,
    ) -> list[dict]:
        params = {"series_id": series_id}
        if realtime_start:
            params["realtime_start"] = realtime_start
        if realtime_end:
            params["realtime_end"] = realtime_end
        return _parse_observations(self._get("series/observations", params))

    def vintage_dates(self, series_id: str, limit: int = 10) -> list[str]:
        params = {"series_id": series_id, "limit": str(limit)}
        payload = self._get("series/vintagedates", params)
        return [d.get("date") for d in (payload or {}).get("vintage_dates") or [] if d.get("date")]

    def latest(self, series_id: str) -> Optional[dict]:
        obs = self.observations(series_id)
        return obs[-1] if obs else None

    def value_as_of(self, series_id: str, decision_date: str) -> Optional[dict]:
        """Value available as-of decision_date (ALFRED vintage, no future leak)."""
        obs = self.observations(series_id, realtime_start=decision_date, realtime_end=decision_date)
        # Only observations dated <= decision_date; realtime_end already bounds revisions.
        eligible = [o for o in obs if o["date"] <= decision_date]
        return eligible[-1] if eligible else None


class FredAlfredProvider(BaseProvider):
    name = "macro"
    version = "1.0.0"
    source_type = SOURCE_MACRO

    def __init__(
        self,
        api_key: Optional[str] = None,
        client: Optional[FredClient] = None,
        catalog: Optional[list[dict]] = None,
    ) -> None:
        self.api_key = api_key or ""
        self._client = client or (FredClient(api_key) if api_key else None)
        self._catalog = macro_catalog.load_catalog(catalog)
        self._configured = bool(api_key)
        self._config_detail = "FRED_API_KEY not set" if not api_key else ""

    def _capabilities(self) -> list[Capability]:
        ro = "READ_ONLY"
        return [
            Capability("macro.get_series", ro, input_schema={"series_id": "string"}),
            Capability(
                "macro.get_series_snapshot", ro, input_schema={"series_ids": "list<string>?"}
            ),
            Capability("macro.get_latest_observation", ro, input_schema={"series_id": "string"}),
            Capability("macro.get_release_dates", ro, input_schema={"series_id": "string"}),
            Capability(
                "macro.get_vintage",
                ro,
                input_schema={"series_id": "string", "decision_date": "string"},
            ),
            Capability(
                "macro.compare_vintages",
                ro,
                input_schema={"series_id": "string", "decision_date": "string"},
            ),
            Capability(
                "macro.get_decision_time_snapshot",
                ro,
                input_schema={"series_ids": "list<string>", "decision_date": "string"},
            ),
            Capability("macro.regime_inputs", ro, input_schema={"decision_date": "string?"}),
        ]

    def _query(self, capability: str, request: dict) -> FinancialSenseResult:
        if self._client is None:
            return self._not_configured(capability)
        dispatch = {
            "macro.get_series": self._get_series,
            "macro.get_series_snapshot": self._get_series_snapshot,
            "macro.get_latest_observation": self._get_latest_observation,
            "macro.get_release_dates": self._get_release_dates,
            "macro.get_vintage": self._get_vintage,
            "macro.compare_vintages": self._compare_vintages,
            "macro.get_decision_time_snapshot": self._get_decision_time_snapshot,
            "macro.regime_inputs": self._regime_inputs,
        }
        return dispatch[capability](request)

    # ── capability handlers ─────────────────────────────────────────────────
    def _get_series(self, request: dict) -> FinancialSenseResult:
        sid = str(request.get("series_id") or "").strip().upper()
        if not sid:
            return self._invalid("macro.get_series", "series_id is required")
        obs = self._client.observations(sid)
        r = self._ok("macro.get_series")
        r.data = {"series_id": sid, "observations": obs}
        r.facts.append(self._series_fact(sid, len(obs)))
        return r

    def _get_series_snapshot(self, request: dict) -> FinancialSenseResult:
        ids = request.get("series_ids") or [request.get("series_id")]
        ids = [str(i).strip().upper() for i in ids if str(i).strip()]
        if not ids:
            return self._invalid("macro.get_series_snapshot", "series_ids is required")
        snap = {}
        for sid in ids:
            latest = self._client.latest(sid)
            snap[sid] = latest or {"state": "DATA_UNAVAILABLE"}
        r = self._ok("macro.get_series_snapshot")
        r.data = {"snapshot": snap}
        r.observed_at = r.requested_at
        return r

    def _get_latest_observation(self, request: dict) -> FinancialSenseResult:
        sid = str(request.get("series_id") or "").strip().upper()
        if not sid:
            return self._invalid("macro.get_latest_observation", "series_id is required")
        latest = self._client.latest(sid)
        r = self._ok("macro.get_latest_observation")
        r.data = {"series_id": sid, "latest": latest or {"state": "DATA_UNAVAILABLE"}}
        if latest:
            r.observed_at = latest["date"]
            r.facts.append(
                Fact(
                    key=sid,
                    value=latest["value"],
                    source_type=SOURCE_MACRO,
                    source_ids=[f"fred:{sid}"],
                    observed_at=latest["date"],
                    as_of=latest["date"],
                    quality=grade_for_source(SOURCE_MACRO),
                )
            )
        else:
            r.set_status("PARTIAL")
            r.add_warning(f"no observation for {sid}")
        return r

    def _get_release_dates(self, request: dict) -> FinancialSenseResult:
        sid = str(request.get("series_id") or "").strip().upper()
        if not sid:
            return self._invalid("macro.get_release_dates", "series_id is required")
        vd = self._client.vintage_dates(sid)
        r = self._ok("macro.get_release_dates")
        r.data = {"series_id": sid, "vintage_dates": vd}
        return r

    def _get_vintage(self, request: dict) -> FinancialSenseResult:
        sid, ddate = self._sid_date(request, "macro.get_vintage")
        if sid is None:
            return ddate  # already an error result
        val = self._client.value_as_of(sid, ddate)
        r = self._ok("macro.get_vintage")
        r.data = {
            "series_id": sid,
            "decision_date": ddate,
            "decision_time_value": val or {"state": "DATA_UNAVAILABLE"},
        }
        if val:
            r.as_of = ddate
            r.facts.append(
                Fact(
                    key=f"{sid}@vintage",
                    value=val["value"],
                    source_type=SOURCE_MACRO,
                    source_ids=[f"fred:{sid}"],
                    observed_at=val["date"],
                    as_of=ddate,
                    quality=grade_for_source(SOURCE_MACRO),
                    notes="value available as-of decision time (vintage)",
                )
            )
        return r

    def _compare_vintages(self, request: dict) -> FinancialSenseResult:
        sid, ddate = self._sid_date(request, "macro.compare_vintages")
        if sid is None:
            return ddate
        vintage_val = self._client.value_as_of(sid, ddate)
        latest_val = self._client.latest(sid)
        r = self._ok("macro.compare_vintages")
        decision_value = vintage_val["value"] if vintage_val else None
        latest_value = latest_val["value"] if latest_val else None
        revision_delta = None
        if decision_value is not None and latest_value is not None:
            revision_delta = round(latest_value - decision_value, 6)
        r.data = {
            "series_id": sid,
            "decision_time_value": decision_value,
            "latest_revised_value": latest_value,
            "revision_delta": revision_delta,
            "vintage_date": ddate,
        }
        r.as_of = ddate
        r.facts.append(
            Fact(
                key=f"{sid}@decision_time",
                value=decision_value,
                source_type=SOURCE_MACRO,
                source_ids=[f"fred:{sid}"],
                observed_at=ddate,
                as_of=ddate,
                quality=grade_for_source(SOURCE_MACRO),
            )
        )
        if revision_delta not in (None, 0):
            r.facts.append(
                Fact(
                    key=f"{sid}@revision_delta",
                    value=revision_delta,
                    source_type=SOURCE_MACRO,
                    source_ids=[f"fred:{sid}"],
                    observed_at=latest_val["date"] if latest_val else None,
                    as_of=ddate,
                    quality=grade_for_source(SOURCE_MACRO),
                    notes="revision between decision-time and latest revised value",
                )
            )
        return r

    def _get_decision_time_snapshot(self, request: dict) -> FinancialSenseResult:
        ids = [str(i).strip().upper() for i in (request.get("series_ids") or []) if str(i).strip()]
        ddate = str(request.get("decision_date") or "").strip()
        if not ids or not ddate:
            return self._invalid(
                "macro.get_decision_time_snapshot", "series_ids and decision_date are required"
            )
        snap = {}
        for sid in ids:
            val = self._client.value_as_of(sid, ddate)
            snap[sid] = {"value": val["value"], "observed_at": val["date"]} if val else {
                "state": "DATA_UNAVAILABLE"
            }
        r = self._ok("macro.get_decision_time_snapshot")
        r.data = {"decision_date": ddate, "snapshot": snap}
        r.as_of = ddate
        return r

    def _regime_inputs(self, request: dict) -> FinancialSenseResult:
        ddate = str(request.get("decision_date") or "").strip()
        regime_ids = ["DFF", "DGS10", "T10Y2Y", "CPIAUCSL", "BAA10Y", "NFCI"]
        if ddate:
            return self._get_decision_time_snapshot({"series_ids": regime_ids, "decision_date": ddate})
        snap = {}
        for sid in regime_ids:
            latest = self._client.latest(sid)
            snap[sid] = latest or {"state": "DATA_UNAVAILABLE"}
        r = self._ok("macro.regime_inputs")
        r.data = {"regime_inputs": snap}
        r.observed_at = r.requested_at
        return r

    # ── helpers ─────────────────────────────────────────────────────────────
    def _sid_date(self, request: dict, cap: str):
        sid = str(request.get("series_id") or "").strip().upper()
        ddate = str(request.get("decision_date") or "").strip()
        if not sid or not ddate:
            return None, self._invalid(cap, "series_id and decision_date are required")
        return sid, ddate

    @staticmethod
    def _series_fact(sid: str, count: int) -> Fact:
        return Fact(
            key=f"{sid}_observations",
            value=count,
            source_type=SOURCE_MACRO,
            source_ids=[f"fred:{sid}"],
            quality=grade_for_source(SOURCE_MACRO),
        )
