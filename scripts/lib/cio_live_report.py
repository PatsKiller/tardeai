"""cio_live_report.py — live holdings → capital plan → report v2 (Phases 8–9).

Live report generation uses the operator's holdings / capital plan, never a
synthetic $100k book. Renderer detection is honest: missing weasyprint /
chromium / wkhtmltopdf is ``pdf=missing`` (not ok=true). If python-docx is
importable, DOCX must be written.

READ_ONLY_ADVISORY. No broker / Telegram / order / stop authority.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

LIVE_REPORT_VERSION = "live_report_1.0.0"
AUTHORITY = "READ_ONLY_ADVISORY"

CANONICAL_HOLDINGS = Path(
    "/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/data/portfolios/state/holdings.json"
)
CANONICAL_STATE = CANONICAL_HOLDINGS.parent
CANONICAL_THESIS = Path(
    "/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/data/cio/cio_theses_projection.json"
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_DIR = REPO_ROOT / "data" / "audit" / "cio_live_report_dry"

_VALUE_KEYS = (
    "market_value",
    "value",
    "quantity",
    "shares",
    "is_cash",
    "current_price",
    "price",
)

DELTA_TOL_USD = 0.02


def git_source_sha(cwd: Optional[Path] = None) -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(cwd or REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return "unknown"


def is_holdings_shaped(doc: Any) -> bool:
    """True when ``doc`` looks like canonical holdings.json (not a toy book).

    Shape — not dollar amount — is the test. A fixture with ``holdings`` rows
    that carry ``symbol`` + a value field is live-shaped even if totals are small.
    """
    if not isinstance(doc, dict):
        return False
    rows = doc.get("holdings")
    if not isinstance(rows, list) or not rows:
        rows = doc.get("positions")
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            if row.get("symbol") or row.get("ticker") or row.get("is_cash"):
                if any(k in row for k in _VALUE_KEYS):
                    return True
    totals = doc.get("portfolio_totals")
    if (
        isinstance(totals, dict)
        and totals.get("total_value") is not None
        and isinstance(doc.get("holdings"), list)
    ):
        return True
    return False


def is_synthetic_book(doc: Any) -> bool:
    """Fail-closed: anything that is not holdings-shaped is synthetic.

    Explicit ``synthetic`` / ``toy`` markers win even on a shaped document.
    A bare ``portfolio_value=100000`` dict (the historic toy book) is synthetic.
    """
    if not isinstance(doc, dict):
        return True
    if doc.get("synthetic") is True or doc.get("toy") is True:
        return True
    if is_holdings_shaped(doc):
        return False
    return True


def resolve_live_holdings_path(explicit: Optional[os.PathLike[str] | str] = None) -> Path:
    """Prefer the canonical live book; fall back to this worktree's data/.

    Never invents a path. Raises if nothing exists.
    """
    if explicit:
        p = Path(explicit)
        if p.is_file():
            return p
        raise FileNotFoundError(f"holdings file not found: {p}")
    if CANONICAL_HOLDINGS.is_file():
        return CANONICAL_HOLDINGS
    repo = REPO_ROOT / "data" / "portfolios" / "state" / "holdings.json"
    if repo.is_file():
        return repo
    raise FileNotFoundError(
        "No live holdings.json at canonical path or repo data/; "
        "refusing synthetic $100k book"
    )


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_live_holdings(
    explicit: Optional[os.PathLike[str] | str] = None,
) -> tuple[dict[str, Any], Path]:
    path = resolve_live_holdings_path(explicit)
    doc = load_json(path)
    if not isinstance(doc, dict) or is_synthetic_book(doc):
        raise ValueError(
            f"holdings at {path} is missing or not holdings-shaped; "
            "refusing synthetic $100k book"
        )
    return doc, path


def detect_renderers() -> dict[str, Any]:
    from scripts.lib.cio_report_render import detect_renderers as _detect
    return _detect()


def _companion_dir(holdings_path: Optional[Path]) -> Path:
    if holdings_path is not None:
        return Path(holdings_path).parent
    repo_state = REPO_ROOT / "data" / "portfolios" / "state"
    if (repo_state / "holdings.json").is_file() or repo_state.is_dir():
        return repo_state
    return CANONICAL_STATE


def _load_thesis(holdings_path: Optional[Path]) -> dict[str, Any]:
    candidates = [
        REPO_ROOT / "data" / "cio" / "cio_theses_projection.json",
        CANONICAL_THESIS,
    ]
    if holdings_path is not None:
        candidates.insert(0, holdings_path.parent.parent.parent / "cio" / "cio_theses_projection.json")
    for p in candidates:
        blob = load_json(p)
        if isinstance(blob, dict):
            desk = ((blob.get("current") or {}).get("desk") or {})
            if desk:
                return desk
    return {}


def _file_bytes(path: Path) -> Any:
    try:
        return path.read_bytes()
    except Exception:
        return "unavailable"


def load_companion_payloads(holdings_path: Optional[Path]) -> dict[str, Any]:
    state = _companion_dir(holdings_path)
    payloads: dict[str, Any] = {}
    for name in (
        "holdings.json",
        "performance_history.json",
        "performance_attribution.json",
        "tax_lots.json",
        "fund_lookthrough.json",
    ):
        payloads[name] = _file_bytes(state / name)
    thesis = REPO_ROOT / "data" / "cio" / "cio_theses_projection.json"
    if not thesis.is_file():
        thesis = CANONICAL_THESIS
    payloads["cio_theses_projection.json"] = _file_bytes(thesis)
    return payloads


def try_load_live_queue_and_sectors() -> tuple[Any, Any, Any]:
    """Best-effort DB companions. Fail-soft; never required for a live book."""
    queue = None
    sectors = None
    open_events = None
    try:
        envp = Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.env")
        if envp.exists():
            for line in envp.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k.isidentifier() and k not in os.environ:
                    os.environ[k] = v
        import db_adapter  # type: ignore
        from lib.cio_opportunity_queue import build_queue_from_executor  # type: ignore
        from lib.redeploy_capital_book import build_opportunity_set  # type: ignore
        queue = build_queue_from_executor(db_adapter._execute)
        conn = db_adapter.get_connection()
        cur = conn.cursor()
        open_events = (build_opportunity_set(cur).get("open_events") or [])
        try:
            from lib.cio_sector_opportunity import build_synthesis_from_executor  # type: ignore
            synth = build_synthesis_from_executor(db_adapter._execute)
            sectors = (synth or {}).get("opportunities") or []
        except Exception:
            sectors = []
    except Exception:
        return None, None, None
    return queue, sectors, open_events


def build_capital_plan_from_live_sources(
    holdings_doc: Optional[dict[str, Any]] = None,
    *,
    holdings_path: Optional[os.PathLike[str] | str] = None,
    queue: Any = None,
    redeploy_open_events: Any = None,
    sector_opportunities: Any = None,
    attach_live_queue: bool = False,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Capital plan from a holdings-shaped document. Refuses a toy book."""
    path: Optional[Path] = None
    if holdings_doc is None:
        holdings_doc, path = load_live_holdings(holdings_path)
    elif is_synthetic_book(holdings_doc):
        raise ValueError(
            "Refusing to build capital plan from non-holdings-shaped / synthetic book"
        )
    if attach_live_queue and queue is None and sector_opportunities is None:
        q, s, ev = try_load_live_queue_and_sectors()
        queue = q
        sector_opportunities = s
        redeploy_open_events = ev
    from scripts.lib.cio_capital_plan import build_capital_plan_from_sources
    return build_capital_plan_from_sources(
        holdings_doc=holdings_doc,
        queue=queue,
        redeploy_open_events=redeploy_open_events,
        sector_opportunities=sector_opportunities,
        now=now,
    )


def _part_b_from_plan(plan: dict[str, Any]) -> dict[str, Any]:
    pv = float(plan.get("portfolio_value_usd") or 0.0)
    cash = float(plan.get("cash_total_usd") or 0.0)
    cash_pct = round(cash / pv * 100.0, 2) if pv else None
    return {
        "portfolio": {
            "total_value": pv,
            "cash_value": cash,
            "cash_pct": cash_pct,
            "positions_count": len(plan.get("position_decisions") or []),
        },
        "allocation": {
            "Cash & Equivalents": cash,
            "Equities": max(0.0, pv - cash),
        },
    }


def build_report_from_live_sources(
    holdings_doc: Optional[dict[str, Any]] = None,
    *,
    holdings_path: Optional[os.PathLike[str] | str] = None,
    capital_plan: Optional[dict[str, Any]] = None,
    queue: Any = None,
    redeploy_open_events: Any = None,
    sector_opportunities: Any = None,
    thesis: Optional[dict[str, Any]] = None,
    source_sha: Optional[str] = None,
    attach_live_queue: bool = False,
    allow_ms_assemble: bool = False,
    now: Optional[datetime] = None,
    render_errors: Optional[list[str]] = None,
) -> dict[str, Any]:
    """build_report_v2 over the live capital plan — never toy numbers."""
    path: Optional[Path] = Path(holdings_path) if holdings_path else None
    if holdings_doc is None:
        holdings_doc, path = load_live_holdings(holdings_path)
    elif is_synthetic_book(holdings_doc):
        raise ValueError(
            "Refusing to build report from non-holdings-shaped / synthetic book"
        )
    if capital_plan is None:
        capital_plan = build_capital_plan_from_live_sources(
            holdings_doc,
            holdings_path=path,
            queue=queue,
            redeploy_open_events=redeploy_open_events,
            sector_opportunities=sector_opportunities,
            attach_live_queue=attach_live_queue,
            now=now,
        )
    state = _companion_dir(path)
    perf_attr = load_json(state / "performance_attribution.json") or {}
    perf_hist = load_json(state / "performance_history.json") or {}
    if thesis is None:
        thesis = _load_thesis(path)

    part_b: dict[str, Any] = {}
    if allow_ms_assemble:
        try:
            from portfolio_report_ms import assemble as _ms_assemble  # type: ignore
            part_b = _ms_assemble() or {}
        except Exception:
            part_b = {}
    if not part_b:
        part_b = _part_b_from_plan(capital_plan)

    from scripts.lib.cio_report_v2 import build_report_v2
    det = detect_renderers()
    pdf_missing = not bool((det.get("pdf") or {}).get("available"))
    errors = list(render_errors or [])
    if pdf_missing and not any("pdf" in str(e).lower() for e in errors):
        errors.append("pdf renderer unavailable (weasyprint/wkhtmltopdf/chromium)")

    return build_report_v2(
        part_b_ctx=part_b,
        part_a_inputs={
            "thesis": thesis or {},
            "capital_plan": capital_plan,
            "sector_opportunities": sector_opportunities or [],
            "opportunity_queue": queue or {},
            "performance_attribution": perf_attr if isinstance(perf_attr, dict) else {},
            "performance": {
                "periods": (perf_hist or {}).get("periods") or {},
            },
        },
        source_sha=source_sha or git_source_sha(),
        input_payloads=load_companion_payloads(path),
        render_errors=errors,
        pdf_pages=None,
        now=now,
    )


def _format_status(
    *,
    name: str,
    path: Optional[str],
    available: bool,
    error: Optional[str] = None,
) -> dict[str, Any]:
    if path and Path(path).is_file() and Path(path).stat().st_size > 0:
        return {"status": "ok", "ok": True, "path": path, "error": None}
    if not available:
        return {
            "status": "missing",
            "ok": False,
            "path": None,
            "error": error or f"{name} renderer/library missing",
        }
    return {
        "status": "error",
        "ok": False,
        "path": None,
        "error": error or f"{name} render failed",
    }


def render_live_report(
    holdings_doc: Optional[dict[str, Any]] = None,
    *,
    holdings_path: Optional[os.PathLike[str] | str] = None,
    out_dir: Optional[os.PathLike[str] | str] = None,
    basename: str = "cio_live_report",
    source_sha: Optional[str] = None,
    queue: Any = None,
    redeploy_open_events: Any = None,
    sector_opportunities: Any = None,
    attach_live_queue: bool = False,
    allow_ms_assemble: bool = False,
    now: Optional[datetime] = None,
    write_files: bool = True,
) -> dict[str, Any]:
    """Render HTML + DOCX (if python-docx) + PDF (if a real renderer).

    ``synthetic`` is False when a holdings-shaped document is passed.
    Missing PDF renderer → ``formats.pdf.status == "missing"`` and
    ``formats.pdf.ok is not True``. Never fakes a PDF PASS.
    """
    sha = source_sha or git_source_sha()
    dest = Path(out_dir) if out_dir is not None else DEFAULT_EVIDENCE_DIR

    if holdings_doc is not None and is_synthetic_book(holdings_doc):
        return {
            "ok": False,
            "live": False,
            "synthetic": True,
            "html": None,
            "pdf": None,
            "docx": None,
            "source_sha": sha,
            "error": "Refusing synthetic/toy $100k book; holdings-shaped document required",
            "formats": {
                "html": {"status": "refused", "ok": False, "path": None},
                "pdf": {"status": "missing", "ok": False, "path": None},
                "docx": {"status": "refused", "ok": False, "path": None},
            },
            "authority": AUTHORITY,
            "version": LIVE_REPORT_VERSION,
        }

    path: Optional[Path] = Path(holdings_path) if holdings_path else None
    if holdings_doc is None:
        holdings_doc, path = load_live_holdings(holdings_path)

    synthetic = is_synthetic_book(holdings_doc)
    live = (not synthetic) and is_holdings_shaped(holdings_doc)

    plan = build_capital_plan_from_live_sources(
        holdings_doc,
        holdings_path=path,
        queue=queue,
        redeploy_open_events=redeploy_open_events,
        sector_opportunities=sector_opportunities,
        attach_live_queue=attach_live_queue,
        now=now,
    )
    model = build_report_from_live_sources(
        holdings_doc,
        holdings_path=path,
        capital_plan=plan,
        queue=queue,
        redeploy_open_events=redeploy_open_events,
        sector_opportunities=sector_opportunities,
        source_sha=sha,
        attach_live_queue=False,
        allow_ms_assemble=allow_ms_assemble,
        now=now,
    )

    det = detect_renderers()
    pdf_avail = bool((det.get("pdf") or {}).get("available"))
    docx_avail = bool((det.get("docx") or {}).get("available"))

    formats_requested = ["html"]
    if docx_avail:
        formats_requested.append("docx")
    if pdf_avail:
        formats_requested.append("pdf")

    paths: dict[str, Optional[str]] = {"html": None, "pdf": None, "docx": None}
    errors: dict[str, str] = {}
    export_result: dict[str, Any] = {}

    if write_files:
        dest.mkdir(parents=True, exist_ok=True)
        from scripts.lib.cio_report_render import export_report_formats
        export_result = export_report_formats(
            model,
            dest,
            basename=basename,
            formats=formats_requested,
        )
        exp_paths = export_result.get("paths") or {}
        exp_errors = export_result.get("errors") or {}
        paths["html"] = exp_paths.get("html")
        paths["docx"] = exp_paths.get("docx")
        paths["pdf"] = exp_paths.get("pdf")
        errors.update({k: str(v) for k, v in exp_errors.items()})
        (dest / f"{basename}.capital_plan.json").write_text(
            json.dumps(plan, indent=2, default=str), encoding="utf-8",
        )
        (dest / f"{basename}.holdings_meta.json").write_text(
            json.dumps({
                "holdings_path": str(path) if path else None,
                "synthetic": synthetic,
                "live": live,
                "holdings_shaped": is_holdings_shaped(holdings_doc),
                "portfolio_value_usd": plan.get("portfolio_value_usd"),
                "cash_total_usd": plan.get("cash_total_usd"),
                "decision_count": len(plan.get("position_decisions") or []),
                "source_sha": sha,
            }, indent=2, default=str),
            encoding="utf-8",
        )

    html_st = _format_status(name="html", path=paths.get("html"), available=True)
    pdf_reason = (det.get("pdf") or {}).get("reason") or errors.get("pdf")
    docx_reason = (det.get("docx") or {}).get("reason") or errors.get("docx")
    if pdf_avail:
        pdf_st = _format_status(
            name="pdf", path=paths.get("pdf"), available=True, error=errors.get("pdf"),
        )
    else:
        pdf_st = _format_status(
            name="pdf", path=None, available=False, error=pdf_reason,
        )
    if docx_avail:
        docx_st = _format_status(
            name="docx", path=paths.get("docx"), available=True, error=errors.get("docx"),
        )
        if not docx_st["ok"]:
            docx_st["status"] = "error"
            docx_st["error"] = docx_st.get("error") or (
                "python-docx is present but DOCX was not created"
            )
    else:
        docx_st = _format_status(
            name="docx", path=None, available=False, error=docx_reason,
        )

    parity = compare_plan_report_decisions(plan, model)

    html_ok = bool(html_st.get("ok"))
    docx_ok_or_absent = bool(docx_st.get("ok")) if docx_avail else True
    production_ok = html_ok and bool(pdf_st.get("ok")) and (bool(docx_st.get("ok")) if docx_avail else False)

    result = {
        "ok": html_ok and docx_ok_or_absent and not synthetic,
        "production_formats_ok": production_ok,
        "live": live,
        "synthetic": synthetic,
        "html": html_st.get("path"),
        "pdf": pdf_st.get("path"),
        "docx": docx_st.get("path"),
        "source_sha": sha,
        "formats": {"html": html_st, "pdf": pdf_st, "docx": docx_st},
        "renderers": det,
        "holdings_path": str(path) if path else None,
        "portfolio_value_usd": plan.get("portfolio_value_usd"),
        "cash_total_usd": plan.get("cash_total_usd"),
        "decision_count": len(plan.get("position_decisions") or []),
        "plan_report_parity": parity,
        "out_dir": str(dest) if write_files else None,
        "basename": basename,
        "authority": AUTHORITY,
        "version": LIVE_REPORT_VERSION,
        "report_version": model.get("report_version"),
        "facts_fingerprint": model.get("facts_fingerprint"),
        "errors": errors,
        "export": {
            "report_id": export_result.get("report_id"),
            "phase7_exit_gate": export_result.get("phase7_exit_gate"),
        } if export_result else {},
    }

    if write_files:
        status_path = dest / f"{basename}.render_status.json"
        status_path.write_text(
            json.dumps(result, indent=2, default=str), encoding="utf-8",
        )
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Decision parity — capital_plan.position_decisions vs report model
# ─────────────────────────────────────────────────────────────────────────────

def extract_report_decisions(report_model: Any) -> list[dict[str, Any]]:
    if not isinstance(report_model, dict):
        return []
    pa = report_model.get("part_a") or {}
    rows = pa.get("decisions_now")
    if not rows:
        view = report_model.get("view") or {}
        facts = view.get("facts") or {}
        rows = facts.get("decisions")
    if not rows and isinstance(report_model.get("decisions_now"), list):
        rows = report_model["decisions_now"]
    return [r for r in (rows or []) if isinstance(r, dict)]


def extract_plan_decisions(capital_plan: Any) -> list[dict[str, Any]]:
    if isinstance(capital_plan, list):
        return [r for r in capital_plan if isinstance(r, dict)]
    if isinstance(capital_plan, dict):
        return [r for r in (capital_plan.get("position_decisions") or []) if isinstance(r, dict)]
    return []


def _stance_key(row: dict[str, Any]) -> str:
    code = row.get("stance_code") or row.get("cio_stance")
    if code:
        return str(code).upper().strip()
    return str(row.get("stance") or row.get("action") or "").upper().strip()


def _decision_id_of(row: dict[str, Any]) -> str:
    did = str(row.get("decision_id") or "").strip()
    if did:
        return did
    try:
        from scripts.lib.cio_decision_semantics import make_decision_id
        return make_decision_id(
            row.get("symbol"),
            row.get("stance_code") or row.get("cio_stance") or row.get("stance"),
            row.get("recommended_delta_usd"),
            row.get("why_now"),
        )
    except Exception:
        body = json.dumps({
            "symbol": str(row.get("symbol") or "").upper(),
            "stance": _stance_key(row),
            "delta": row.get("recommended_delta_usd"),
        }, sort_keys=True, default=str)
        return "dec_" + hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def compare_plan_report_decisions(
    capital_plan: Any,
    report_model: Any,
) -> dict[str, Any]:
    """Compare decision_id, symbol, recommended_delta_usd, stance.

    Report decisions (the published surface) must match the capital-plan row
    of the same identity. Matching surfaces → ok. A delta mismatch → fail.
    Plan-only HOLD rows that the report omits as immaterial are not mismatches.
    """
    plan_rows = extract_plan_decisions(capital_plan)
    report_rows = extract_report_decisions(report_model)

    by_id: dict[str, dict[str, Any]] = {}
    by_symbol: dict[str, dict[str, Any]] = {}
    for row in plan_rows:
        did = _decision_id_of(row)
        by_id[did] = row
        sym = str(row.get("symbol") or "").upper().strip()
        if sym:
            by_symbol[sym] = row

    mismatches: list[dict[str, Any]] = []
    compared: list[dict[str, Any]] = []

    for rrow in report_rows:
        rid = _decision_id_of(rrow)
        rsym = str(rrow.get("symbol") or "").upper().strip()
        prow = by_id.get(rid) or (by_symbol.get(rsym) if rsym else None)
        if prow is None:
            mismatches.append({
                "field": "missing_in_plan",
                "decision_id": rid or None,
                "symbol": rsym or None,
                "values": [None, rrow.get("symbol")],
            })
            continue
        pid = _decision_id_of(prow)
        psym = str(prow.get("symbol") or "").upper().strip()
        pair = {
            "decision_id": rid or pid,
            "symbol": rsym or psym,
        }
        if rid and pid and rid != pid:
            mismatches.append({
                "field": "decision_id",
                "decision_id": rid,
                "symbol": rsym or psym,
                "values": [pid, rid],
            })
        if psym and rsym and psym != rsym:
            mismatches.append({
                "field": "symbol",
                "decision_id": rid or pid,
                "symbol": rsym,
                "values": [psym, rsym],
            })
        pdelta = prow.get("recommended_delta_usd")
        rdelta = rrow.get("recommended_delta_usd")
        try:
            if pdelta is None or rdelta is None:
                if pdelta != rdelta:
                    mismatches.append({
                        "field": "recommended_delta_usd",
                        "decision_id": rid or pid,
                        "symbol": rsym or psym,
                        "values": [pdelta, rdelta],
                    })
            elif abs(float(pdelta) - float(rdelta)) > DELTA_TOL_USD:
                mismatches.append({
                    "field": "recommended_delta_usd",
                    "decision_id": rid or pid,
                    "symbol": rsym or psym,
                    "values": [pdelta, rdelta],
                })
        except (TypeError, ValueError):
            mismatches.append({
                "field": "recommended_delta_usd",
                "decision_id": rid or pid,
                "symbol": rsym or psym,
                "values": [pdelta, rdelta],
            })
        pstance = _stance_key(prow)
        rstance = _stance_key(rrow)
        if pstance and rstance and pstance != rstance:
            mismatches.append({
                "field": "stance",
                "decision_id": rid or pid,
                "symbol": rsym or psym,
                "values": [pstance, rstance],
            })
        pair.update({
            "plan_delta": pdelta,
            "report_delta": rdelta,
            "plan_stance": pstance,
            "report_stance": rstance,
        })
        compared.append(pair)

    ok = not mismatches
    return {
        "ok": ok,
        "version": "plan_report_decision_parity_1.0.0",
        "compared": len(compared),
        "plan_count": len(plan_rows),
        "report_count": len(report_rows),
        "mismatches": mismatches[:40],
        "fields": ["decision_id", "symbol", "recommended_delta_usd", "stance"],
        "authority": AUTHORITY,
    }
