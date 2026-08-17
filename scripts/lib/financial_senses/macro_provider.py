"""FredAlfredProvider — FRED / ALFRED macro and vintage-aware provider.

Read-only macro context. Historical queries are vintage-aware: they distinguish
LATEST_REVISED_VALUE from VALUE_AVAILABLE_AS_OF_DECISION_TIME and never leak a
later revision backward into a historical decision.

A revision compares the SAME observation date across two vintages, not two
different observations. No network in unit tests — the FRED client is
injectable.
"""
from __future__ import annotations

from datetime import date as _date
from typing import Any, Callable, Optional
from urllib.parse import urlencode

from .provider import BaseProvider, Capability
from .result import DATA_UNAVAILABLE, Fact, FinancialSenseResult, STATUS_OK
from .source_governance import SOURCE_PRIMARY_GOVERNMENT, grade_for_source

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


def _validate_date(value: str) -> bool:
    """True if value is a well-formed ISO YYYY-MM-DD date."""
    if not value:
        return False
    try:
        _date.fromisoformat(value)
        return True
    except ValueError:
        return False


class FredClient:
    """Thin read-only client over the official FRED/ALFRED JSON API.

    Supports the real-time/vintage model: `realtime_end` bounds the vintage
    (what was known as of that date), while `observation_start`/`observation_end`
    bound the economic observation dates.
    """

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
        q = dict(params)
        q["api_key"] = self.api_key
        q["file_type"] = "json"
        # URL-encode all parameters (do not hand-concatenate).
        qs = urlencode({k: v for k, v in q.items() if v is not None})
        return self._fetcher(f"{self.base}/{path}?{qs}") or {}

    def observations(
        self,
        series_id: str,
        realtime_start: Optional[str] = None,
        realtime_end: Optional[str] = None,
        observation_start: Optional[str] = None,
        observation_end: Optional[str] = None,
    ) -> list[dict]:
        params = {"series_id": series_id}
        if realtime_start:
            params["realtime_start"] = realtime_start
        if realtime_end:
            params["realtime_end"] = realtime_end
        if observation_start:
            params["observation_start"] = observation_start
        if observation_end:
            params["observation_end"] = observation_end
        return _parse_observations(self._get("series/observations", params))

    def vintage_dates(self, series_id: str, limit: int = 10) -> list[str]:
        """Return vintage dates. Official shape is a list of date strings."""
        params = {"series_id": series_id, "limit": str(limit)}
        payload = self._get("series/vintagedates", params)
        raw = (payload or {}).get("vintage_dates") or []
        out: list[str] = []
        for d in raw:
            if isinstance(d, str):
                out.append(d)
            elif isinstance(d, dict):
                out.append(d.get("date"))
        return [x for x in out if x]

    def latest(self, series_id: str) -> Optional[dict]:
        """Most recent observation under the latest vintage."""
        obs = self.observations(series_id)
        return obs[-1] if obs else None

    def latest_as_of(self, series_id: str, decision_date: str) -> Optional[dict]:
        """Most recent observation known as-of decision_date (vintage-bounded).

        FRED's `series/observations` defaults BOTH `realtime_start` and
        `realtime_end` to today. A historical decision-time query therefore
        must pin the real-time period on BOTH ends to request the vintage that
        existed as-of `decision_date`, and must bound `observation_end` so a
        future economic observation is never injected into the decision.
        """
        obs = self.observations(
            series_id,
            realtime_start=decision_date,
            realtime_end=decision_date,
            observation_end=decision_date,
        )
        return obs[-1] if obs else None

    def observation_value(
        self,
        series_id: str,
        observation_date: str,
        realtime_end: Optional[str] = None,
    ) -> Optional[float]:
        """Value of a specific observation_date. realtime_end=None => latest vintage."""
        obs = self.observations(
            series_id,
            observation_start=observation_date,
            observation_end=observation_date,
            realtime_end=realtime_end,
        )
        for o in obs:
            if o["date"] == observation_date:
                return o["value"]
        return None


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
        self._catalog = catalog
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
            Capability("macro.get_vintage_dates", ro, input_schema={"series_id": "string"}),
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
            "macro.get_vintage_dates": self._get_vintage_dates,
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
        r.observed_at = r.requested_at
        r.facts.append(
            Fact(
                key=f"{sid}_observations",
                value=len(obs),
                source_type=SOURCE_MACRO,
                source_ids=[f"fred:{sid}"],
                as_of=r.requested_at,
                quality=grade_for_source(SOURCE_MACRO),
            )
        )
        return r

    def _get_series_snapshot(self, request: dict) -> FinancialSenseResult:
        ids = request.get("series_ids") or [request.get("series_id")]
        ids = [str(i).strip().upper() for i in ids if str(i).strip()]
        if not ids:
            return self._invalid("macro.get_series_snapshot", "series_ids is required")
        snap = {}
        for sid in ids:
            latest = self._client.latest(sid)
            snap[sid] = latest or {"state": DATA_UNAVAILABLE}
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
        r.data = {"series_id": sid, "latest": latest or {"state": DATA_UNAVAILABLE}}
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

    def _get_vintage_dates(self, request: dict) -> FinancialSenseResult:
        sid = str(request.get("series_id") or "").strip().upper()
        if not sid:
            return self._invalid("macro.get_vintage_dates", "series_id is required")
        vd = self._client.vintage_dates(sid)
        r = self._ok("macro.get_vintage_dates")
        r.data = {"series_id": sid, "vintage_dates": vd}
        r.observed_at = r.requested_at
        return r

    def _get_vintage(self, request: dict) -> FinancialSenseResult:
        sid, ddate = self._sid_date(request, "macro.get_vintage")
        if sid is None:
            return ddate  # already an error result
        val = self._client.latest_as_of(sid, ddate)
        r = self._ok("macro.get_vintage")
        r.data = {
            "series_id": sid,
            "decision_date": ddate,
            "decision_time_value": val or {"state": DATA_UNAVAILABLE},
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
        decision_obs = self._client.latest_as_of(sid, ddate)
        if decision_obs is None:
            r = self._unavailable(
                "macro.compare_vintages", f"no observation available as-of {ddate}"
            )
            r.subject = r.subject
            r.data = {
                "series_id": sid,
                "decision_date": ddate,
                "observation_date": None,
                "decision_time_value": None,
                "latest_revised_value": None,
                "revision_delta": None,
                "vintage_date": ddate,
                "state": DATA_UNAVAILABLE,
            }
            return r
        obs_date = decision_obs["date"]
        decision_value = decision_obs["value"]
        # Latest vintage value for the SAME observation date.
        latest_value = self._client.observation_value(sid, obs_date)
        revision_delta = None
        if decision_value is not None and latest_value is not None:
            revision_delta = round(latest_value - decision_value, 6)
        r = self._ok("macro.compare_vintages")
        retrieval_date = r.requested_at
        r.data = {
            "series_id": sid,
            "observation_date": obs_date,
            "decision_time_value": decision_value,
            "latest_revised_value": latest_value,
            "revision_delta": revision_delta,
            "vintage_date": ddate,
            "retrieval_date": retrieval_date,
        }
        r.as_of = ddate
        r.facts.append(
            Fact(
                key=f"{sid}@{obs_date}",
                value=decision_value,
                source_type=SOURCE_MACRO,
                source_ids=[f"fred:{sid}"],
                observed_at=obs_date,
                as_of=ddate,
                quality=grade_for_source(SOURCE_MACRO),
                notes="value known as-of decision time",
            )
        )
        if revision_delta not in (None, 0):
            # The revision was, by definition, learned AFTER the decision-time
            # vintage. Its as_of must be the retrieval/latest-vintage time, never
            # the historical decision date.
            r.facts.append(
                Fact(
                    key=f"{sid}@revision_delta",
                    value=revision_delta,
                    source_type=SOURCE_MACRO,
                    source_ids=[f"fred:{sid}"],
                    observed_at=obs_date,
                    as_of=retrieval_date,
                    quality=grade_for_source(SOURCE_MACRO),
                    notes="revision for the SAME observation date; known at retrieval time",
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
        if not _validate_date(ddate):
            return self._invalid("macro.get_decision_time_snapshot", "decision_date must be YYYY-MM-DD")
        snap = {}
        for sid in ids:
            val = self._client.latest_as_of(sid, ddate)
            snap[sid] = {"value": val["value"], "observed_at": val["date"]} if val else {
                "state": DATA_UNAVAILABLE
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
            snap[sid] = latest or {"state": DATA_UNAVAILABLE}
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
        if not _validate_date(ddate):
            return None, self._invalid(cap, "decision_date must be YYYY-MM-DD")
        return sid, ddate
