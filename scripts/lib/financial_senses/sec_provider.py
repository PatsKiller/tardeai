"""SecEdgarProvider — read-only adapter over the existing SEC EDGAR pipeline.

Reuses the canonical Trade AI SEC ingestion (scripts/sec_data_ingest.py) and the
canonical trade_ai database. It never starts a competing scheduler, never writes
production SEC data, and exposes clean read-only capabilities that the future
governed MCP gateway can register.

Company facts / filing metadata / filing-diff are served through a bounded
read-only extension (sec_companyfacts_reader) because the canonical store only
persists Form 4 (and reads 13F) — no second ingestion scheduler is created.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from .provider import BaseProvider, Capability
from .result import (
    DATA_UNAVAILABLE,
    NOT_APPLICABLE,
    NOT_FOUND,
    NOT_INGESTED,
    Fact,
    FinancialSenseResult,
    Provenance,
    Quality,
    Subject,
    STATUS_OK,
)
from .source_governance import SOURCE_PRIMARY_REGULATORY, grade_for_source
from . import sec_companyfacts_reader as reader
from . import sec_filing_diff as diff_mod

# Canonical SEC ingest + DB adapter are imported lazily so this module imports
# with no database/network access (required for offline unit tests).


def _default_conn_factory():
    from db_adapter import get_connection

    return get_connection()


def _default_cik_resolver(symbol: str) -> str:
    import sec_data_ingest as sdi

    return sdi._get_cik(symbol)


class SecEdgarProvider(BaseProvider):
    name = "sec_edgar"
    version = "1.0.0"
    source_type = SOURCE_PRIMARY_REGULATORY

    def __init__(
        self,
        conn_factory: Optional[Callable[[], Any]] = None,
        cik_resolver: Optional[Callable[[str], str]] = None,
        fetcher: Optional[Callable[[str], dict]] = None,
        configured: bool = True,
        config_detail: str = "",
    ) -> None:
        self._conn_factory = conn_factory or _default_conn_factory
        self._cik_resolver = cik_resolver or _default_cik_resolver
        self._fetcher = fetcher  # None -> use reader's default fetcher
        self._configured = configured
        self._config_detail = config_detail

    # ── capabilities ────────────────────────────────────────────────────────
    def _capabilities(self) -> list[Capability]:
        ro = "READ_ONLY"
        return [
            Capability("sec.resolve_cik", ro, input_schema={"symbol": "string"}),
            Capability(
                "sec.get_recent_filings",
                ro,
                input_schema={"symbol": "string", "form": "string?", "limit": "int?"},
            ),
            Capability("sec.get_form4_context", ro, input_schema={"symbol": "string", "limit": "int?"}),
            Capability("sec.get_13f_context", ro, input_schema={"symbol": "string", "limit": "int?"}),
            Capability("sec.get_company_facts", ro, input_schema={"symbol": "string?", "cik": "string?"}),
            Capability("sec.get_filing_metadata", ro, input_schema={"symbol": "string?", "cik": "string?"}),
            Capability(
                "sec.compare_filing_facts",
                ro,
                input_schema={"cik": "string", "period_a": "string", "period_b": "string"},
            ),
            Capability("sec.get_decision_evidence", ro, input_schema={"symbol": "string"}),
        ]

    # ── query dispatch ──────────────────────────────────────────────────────
    def _query(self, capability: str, request: dict) -> FinancialSenseResult:
        dispatch = {
            "sec.resolve_cik": self._resolve_cik,
            "sec.get_recent_filings": self._get_recent_filings,
            "sec.get_form4_context": self._get_form4_context,
            "sec.get_13f_context": self._get_13f_context,
            "sec.get_company_facts": self._get_company_facts,
            "sec.get_filing_metadata": self._get_filing_metadata,
            "sec.compare_filing_facts": self._compare_filing_facts,
            "sec.get_decision_evidence": self._get_decision_evidence,
        }
        return dispatch[capability](request)

    # ── helpers ─────────────────────────────────────────────────────────────
    def _resolve_cik(self, request: dict) -> FinancialSenseResult:
        symbol = str(request.get("symbol") or "").strip().upper()
        if not symbol:
            return self._invalid("sec.resolve_cik", "symbol is required")
        try:
            cik = self._cik_resolver(symbol)
        except Exception as exc:
            return self._unavailable("sec.resolve_cik", f"cik resolution failed: {exc}")
        r = self._ok("sec.resolve_cik")
        r.subject = Subject(symbol=symbol)
        if not cik:
            r.data = {"cik": None, "state": NOT_FOUND}
            r.add_warning(f"no CIK resolved for {symbol}")
            r.set_status("PARTIAL")
            return r
        r.data = {"cik": cik}
        r.facts.append(
            Fact(
                key="cik",
                value=cik,
                source_type=SOURCE_PRIMARY_REGULATORY,
                source_ids=["sec_company_tickers"],
                as_of=r.requested_at,
                quality=grade_for_source(SOURCE_PRIMARY_REGULATORY),
            )
        )
        return r

    def _get_recent_filings(self, request: dict) -> FinancialSenseResult:
        symbol = str(request.get("symbol") or "").strip().upper()
        if not symbol:
            return self._invalid("sec.get_recent_filings", "symbol is required")
        form = request.get("form")
        limit = int(request.get("limit") or 10)
        cik = self._safe_cik(symbol)
        if not cik:
            # No CIK for a symbol is a data state, not a provider configuration
            # problem. Reserve NOT_CONFIGURED for a missing provider config.
            r = self._ok("sec.get_recent_filings")
            r.subject = Subject(symbol=symbol)
            r.data = {"filings": [], "state": NOT_FOUND}
            r.set_status("PARTIAL")
            r.add_warning(f"no CIK resolved for {symbol}")
            return r
        try:
            filings = reader.list_filings(cik, form=form, limit=limit, fetcher=self._fetcher)
        except Exception as exc:
            return self._unavailable("sec.get_recent_filings", f"EDGAR read failed: {exc}")
        r = self._ok("sec.get_recent_filings")
        r.subject = Subject(symbol=symbol, cik=cik)
        r.data = {"filings": filings}
        r.quality = Quality(grade=grade_for_source(SOURCE_PRIMARY_REGULATORY), freshness="FRESH")
        r.facts.append(
            Fact(
                key="recent_filings_count",
                value=len(filings),
                source_type=SOURCE_PRIMARY_REGULATORY,
                source_ids=[f"sec_submissions_CIK{cik}"],
                as_of=r.requested_at,
                quality=grade_for_source(SOURCE_PRIMARY_REGULATORY),
            )
        )
        return r

    def _get_form4_context(self, request: dict) -> FinancialSenseResult:
        symbol = str(request.get("symbol") or "").strip().upper()
        if not symbol:
            return self._invalid("sec.get_form4_context", "symbol is required")
        limit = int(request.get("limit") or 3)
        rows = self._read_sec_table(
            "sec_form4",
            ["filer_name", "transaction_type", "filing_date", "sec_url"],
            "symbol=%s ORDER BY filing_date DESC LIMIT %s",
            (symbol, limit),
        )
        r = self._ok("sec.get_form4_context")
        r.subject = Subject(symbol=symbol)
        if rows is None:
            r.set_status("UNAVAILABLE")
            r.add_warning("sec_form4 store unavailable")
            r.data = {"rows": [], "state": DATA_UNAVAILABLE}
            return r
        r.data = {"rows": rows}
        if not rows:
            r.data = {"rows": [], "state": NOT_INGESTED}
            r.add_warning(f"no Form 4 rows ingested for {symbol}")
        else:
            r.facts.append(
                Fact(
                    key="form4_rows",
                    value=len(rows),
                    source_type=SOURCE_PRIMARY_REGULATORY,
                    source_ids=["sec_form4_table"],
                    as_of=r.requested_at,
                    quality=grade_for_source(SOURCE_PRIMARY_REGULATORY),
                )
            )
        return r

    def _get_13f_context(self, request: dict) -> FinancialSenseResult:
        symbol = str(request.get("symbol") or "").strip().upper()
        if not symbol:
            return self._invalid("sec.get_13f_context", "symbol is required")
        limit = int(request.get("limit") or 3)
        rows = self._read_sec_table(
            "sec_13f",
            ["institution", "shares", "value_thousands", "change_pct", "report_date"],
            "symbol=%s ORDER BY report_date DESC LIMIT %s",
            (symbol, limit),
        )
        r = self._ok("sec.get_13f_context")
        r.subject = Subject(symbol=symbol)
        r.data = {"rows": rows}
        if rows is None:
            r.set_status("UNAVAILABLE")
            r.add_warning("sec_13f store unavailable")
            r.data = {"rows": [], "state": DATA_UNAVAILABLE}
        elif not rows:
            r.data = {"rows": [], "state": NOT_INGESTED}
            r.add_warning(f"no 13F rows ingested for {symbol}")
        else:
            r.facts.append(
                Fact(
                    key="13f_institutions",
                    value=len(rows),
                    source_type=SOURCE_PRIMARY_REGULATORY,
                    source_ids=["sec_13f_table"],
                    as_of=r.requested_at,
                    quality=grade_for_source(SOURCE_PRIMARY_REGULATORY),
                )
            )
        return r

    def _get_company_facts(self, request: dict) -> FinancialSenseResult:
        cik = self._cik_from_request(request)
        if not cik:
            return self._invalid("sec.get_company_facts", "cik or resolvable symbol required")
        try:
            raw = reader.get_company_facts(cik, fetcher=self._fetcher)
            facts = reader.latest_values(raw)
        except Exception as exc:
            return self._unavailable("sec.get_company_facts", f"company facts read failed: {exc}")
        r = self._ok("sec.get_company_facts")
        r.subject = Subject(cik=cik, symbol=str(request.get("symbol") or "").upper() or None)
        r.data = {"facts": facts}
        r.quality = Quality(grade=grade_for_source(SOURCE_PRIMARY_REGULATORY), freshness="FRESH")
        r.facts.append(
            Fact(
                key="company_facts_tags",
                value=len(facts),
                source_type=SOURCE_PRIMARY_REGULATORY,
                source_ids=[f"sec_companyfacts_CIK{cik}"],
                as_of=r.requested_at,
                quality=grade_for_source(SOURCE_PRIMARY_REGULATORY),
            )
        )
        if not facts:
            r.set_status("PARTIAL")
            r.add_warning("company facts endpoint returned no facts")
        return r

    def _get_filing_metadata(self, request: dict) -> FinancialSenseResult:
        cik = self._cik_from_request(request)
        if not cik:
            return self._invalid("sec.get_filing_metadata", "cik or resolvable symbol required")
        try:
            sub = reader.get_submissions(cik, fetcher=self._fetcher)
        except Exception as exc:
            return self._unavailable("sec.get_filing_metadata", f"submissions read failed: {exc}")
        r = self._ok("sec.get_filing_metadata")
        r.subject = Subject(cik=cik, symbol=str(request.get("symbol") or "").upper() or None)
        r.data = {
            "name": sub.get("name"),
            "tickers": sub.get("tickers"),
            "cik": sub.get("cik"),
            "recent_count": len((sub.get("filings") or {}).get("recent", {}).get("form", []) or []),
        }
        r.facts.append(
            Fact(
                key="company_name",
                value=sub.get("name"),
                source_type=SOURCE_PRIMARY_REGULATORY,
                source_ids=[f"sec_submissions_CIK{cik}"],
                as_of=r.requested_at,
                quality=grade_for_source(SOURCE_PRIMARY_REGULATORY),
            )
        )
        if not sub:
            r.set_status("UNAVAILABLE")
            r.add_warning("no submissions metadata returned")
        return r

    def _compare_filing_facts(self, request: dict) -> FinancialSenseResult:
        cik = str(request.get("cik") or "").strip()
        period_a = str(request.get("period_a") or "").strip()
        period_b = str(request.get("period_b") or "").strip()
        if not cik or not period_a or not period_b:
            return self._invalid(
                "sec.compare_filing_facts", "cik, period_a, and period_b are required"
            )
        try:
            raw = reader.get_company_facts(cik, fetcher=self._fetcher)
            facts_a = self._facts_at_period(raw, period_a)
            facts_b = self._facts_at_period(raw, period_b)
        except Exception as exc:
            return self._unavailable("sec.compare_filing_facts", f"read failed: {exc}")
        if not facts_a or not facts_b:
            r = self._unavailable(
                "sec.compare_filing_facts",
                f"no facts for period(s): a={bool(facts_a)} b={bool(facts_b)}",
            )
            r.subject = Subject(cik=cik)
            return r
        compared = diff_mod.compare_filing_facts(facts_a, facts_b)
        r = self._ok("sec.compare_filing_facts")
        r.subject = Subject(cik=cik)
        r.data = compared
        r.as_of = period_b
        r.quality = Quality(grade=grade_for_source(SOURCE_PRIMARY_REGULATORY), freshness="FRESH")
        r.facts.append(
            Fact(
                key="compared_fact_keys",
                value=len(compared.get("comparisons", {})),
                source_type=SOURCE_PRIMARY_REGULATORY,
                source_ids=[f"sec_companyfacts_CIK{cik}"],
                observed_at=period_b,
                as_of=period_b,
                quality=grade_for_source(SOURCE_PRIMARY_REGULATORY),
            )
        )
        return r

    def _get_decision_evidence(self, request: dict) -> FinancialSenseResult:
        symbol = str(request.get("symbol") or "").strip().upper()
        if not symbol:
            return self._invalid("sec.get_decision_evidence", "symbol is required")
        cik = self._safe_cik(symbol)
        r = self._ok("sec.get_decision_evidence")
        r.subject = Subject(symbol=symbol, cik=cik)
        evidence: dict = {"cik": cik}
        # Form 4 (canonical store)
        form4 = self._read_sec_table(
            "sec_form4",
            ["filer_name", "transaction_type", "filing_date", "sec_url"],
            "symbol=%s ORDER BY filing_date DESC LIMIT 3",
            (symbol, 3),
        )
        evidence["form4"] = form4 if form4 is not None else {"state": DATA_UNAVAILABLE}
        # 13F (canonical store)
        f13 = self._read_sec_table(
            "sec_13f",
            ["institution", "shares", "value_thousands", "change_pct", "report_date"],
            "symbol=%s ORDER BY report_date DESC LIMIT 3",
            (symbol, 3),
        )
        evidence["13f"] = f13 if f13 is not None else {"state": DATA_UNAVAILABLE}
        # Recent filings (read-only EDGAR extension)
        if cik:
            try:
                evidence["recent_filings"] = reader.list_filings(cik, limit=5, fetcher=self._fetcher)
            except Exception:
                evidence["recent_filings"] = {"state": DATA_UNAVAILABLE}
        else:
            evidence["recent_filings"] = {"state": NOT_APPLICABLE}
        r.data = {"evidence": evidence}
        r.facts.append(
            Fact(
                key="decision_evidence_subject",
                value=symbol,
                source_type=SOURCE_PRIMARY_REGULATORY,
                source_ids=["sec_form4_table", "sec_13f_table"],
                as_of=r.requested_at,
                quality=grade_for_source(SOURCE_PRIMARY_REGULATORY),
            )
        )
        return r

    # ── internal helpers ────────────────────────────────────────────────────
    def _safe_cik(self, symbol: str) -> str:
        try:
            return self._cik_resolver(symbol)
        except Exception:
            return ""

    def _cik_from_request(self, request: dict) -> str:
        cik = str(request.get("cik") or "").strip()
        if cik:
            digits = "".join(ch for ch in cik if ch.isdigit())
            return digits.zfill(10) if digits else ""
        symbol = str(request.get("symbol") or "").strip().upper()
        if symbol:
            return self._safe_cik(symbol)
        return ""

    def _read_sec_table(self, table: str, columns: list[str], where: str, params: tuple):
        """Read rows from a canonical SEC table. Returns None on DB failure."""
        cols = ", ".join(columns)
        query = f"SELECT {cols} FROM {table} WHERE {where}"
        try:
            conn = self._conn_factory()
            cur = conn.cursor()
            cur.execute(query, params)
            colnames = [d[0] for d in cur.description] if cur.description else columns
            rows = [dict(zip(colnames, row)) for row in cur.fetchall()]
            try:
                conn.close()
            except Exception:
                pass
            return rows
        except Exception:
            return None

    @staticmethod
    def _facts_at_period(raw: dict, period: str) -> dict:
        """Extract tag -> full XBRL context dict as of a given period.

        Selection policy (documented, deterministic): for each tag+unit, among
        rows whose `end` equals `period` (exact) or starts with `period`
        (prefix), select the row with the latest `filed` date, preferring exact
        end matches. The full context (start, end, form, fp, fy, frame, filed)
        is preserved so the filing-diff layer can establish like-for-like
        duration semantics.
        """
        out: dict = {}
        body = (raw or {}).get("facts", raw or {})
        if isinstance(body, dict) and "us-gaap" in body:
            body = body["us-gaap"]
        for tag, entry in (body or {}).items():
            if not isinstance(entry, dict):
                continue
            units = entry.get("units") or {}
            for unit, rows in units.items():
                if not isinstance(rows, list):
                    continue
                candidates = []
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    end = str(row.get("end") or "")
                    if end == period:
                        candidates.append((0, row))
                    elif end.startswith(period):
                        candidates.append((1, row))
                if not candidates:
                    continue
                # Latest filed first (descending), then stable-sort exact matches
                # (0) before prefix matches (1).
                candidates.sort(key=lambda t: str(t[1].get("filed") or ""), reverse=True)
                candidates.sort(key=lambda t: t[0])
                row = candidates[0][1]
                out[tag] = {
                    "value": row.get("val"),
                    "units": unit,
                    "start": row.get("start"),
                    "end": str(row.get("end") or ""),
                    "form": row.get("form"),
                    "fp": row.get("fp"),
                    "fy": row.get("fy"),
                    "frame": row.get("frame"),
                    "filed": row.get("filed"),
                }
                break
        return out
