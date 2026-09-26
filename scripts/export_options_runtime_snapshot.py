#!/usr/bin/env python3
"""Redacted options runtime snapshot for the Drive mirror (operator 2026-09-26).

The options thesis log (data/cio/options_theses.jsonl) and the CIO options
decisions (cio_decisions, action_class='options_thesis_review') are runtime
state: they live outside git, so the hourly docs sync never saw them. This writes
a small, stable-named, REDACTED export the sync mirrors to Drive under
runtime/options/.

Operator decision: REDACTED -- no account names and no dollar amounts. Fields are
copied through a STRICT ALLOWLIST; nothing else leaves the machine. Account,
max loss/profit, capital, premium totals, contract counts, bid/ask, underlying
price, portfolio impact and cash are never read into the output. Free text that
is allowlisted (thesis summary, CIO reasoning, concerns) has dollar amounts and
account names scrubbed, and the whole payload is refused if anything that looks
like an account number survives.

    python3 scripts/export_options_runtime_snapshot.py            # dry run (default)
    python3 scripts/export_options_runtime_snapshot.py --apply    # write the files

Env:
    TRADEAI_RUNTIME_ROOT                  where data/cio/options_theses.jsonl lives (default: repo root)
    TRADEAI_RUNTIME_EXPORT_ROOT           output dir (default below)
    TRADEAI_OPTIONS_EXPORT_DECISIONS_MAX  newest decisions kept (default 50)
    TRADEAI_OPTIONS_EXPORT_DB             "0" skips the cio_decisions read (default "1")
    TRADEAI_EXPORT_ACCOUNT_DIGITS_MIN     digit-run length treated as an account number (default 8)
    TRADEAI_EXPORT_ACCOUNT_DIGITS_MAX     upper bound of that digit run (default 12)
    TRADEAI_EXPORT_TEXT_MAX_CHARS         cap on any exported free-text field (default 1200)
    TRADEAI_EXPORT_EXTRA_ACCOUNT_TERMS    comma list of extra account names to scrub

Read-only against the thesis log and the database. Advisory; moves no money.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable, Optional

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_EXPORT_ROOT = "/home/johnclaw/trade-ai-releases/persistent-state/exports/drive/runtime/options"
THESES_BASENAME = "options_theses_latest"
DECISIONS_BASENAME = "cio_options_decisions_latest"
DEFAULTS = {
    "decisions_max": 50,
    "account_digits_min": 8,
    "account_digits_max": 12,
    "text_max_chars": 1200,
}

# Keys that must never appear anywhere in the output, at any depth.
FORBIDDEN_KEYS = frozenset({
    "account", "account_id", "account_key", "account_number", "accounts",
    "max_loss", "max_profit", "capital_required", "premium_total", "premium", "contracts",
    "bid", "ask", "mid", "last", "underlying_price", "spot", "portfolio_impact", "cash",
    "cash_flow", "breakeven", "live", "recomputed", "proposal_id", "cost_estimate",
})
FORBIDDEN_SUFFIXES = ("_total",)

DOLLAR_RE = re.compile(r"\$\s?-?\d[\d,]*(?:\.\d+)?(?:\s?[kKmM]\b)?")
MONEY_PHRASE_RE = re.compile(
    r"\b(max(?:imum)?\s+(?:loss|profit)|premium(?:\s+total)?|capital(?:\s+required)?|cash|credit|debit|collateral)"
    r"(\s+(?:of|is|at|=|:|per\s+contract))?\s*(?:\$\s?)?\d[\d,]*(?:\.\d+)?",
    re.IGNORECASE,
)
MASKED_ACCOUNT_RE = re.compile(r"(?:[xX*]{2,}|\.{3}|#)\s?\d{3,6}\b")
CHANGE_RE = re.compile(r"^\s*([A-Za-z][A-Za-z _]*?)\s+-?[\d.,]+\s*->\s*-?[\d.,]+\s*(\([^)]*\))?\s*$")


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def settings() -> dict[str, Any]:
    return {
        "decisions_max": _int_env("TRADEAI_OPTIONS_EXPORT_DECISIONS_MAX", DEFAULTS["decisions_max"]),
        "account_digits_min": _int_env("TRADEAI_EXPORT_ACCOUNT_DIGITS_MIN", DEFAULTS["account_digits_min"]),
        "account_digits_max": _int_env("TRADEAI_EXPORT_ACCOUNT_DIGITS_MAX", DEFAULTS["account_digits_max"]),
        "text_max_chars": _int_env("TRADEAI_EXPORT_TEXT_MAX_CHARS", DEFAULTS["text_max_chars"]),
        "use_db": os.environ.get("TRADEAI_OPTIONS_EXPORT_DB", "1") != "0",
    }


def runtime_root() -> Path:
    return Path(os.environ.get("TRADEAI_RUNTIME_ROOT") or ROOT)


def export_root() -> Path:
    return Path(os.environ.get("TRADEAI_RUNTIME_EXPORT_ROOT") or DEFAULT_EXPORT_ROOT)


# ── redaction ────────────────────────────────────────────────────────────────

def account_terms(root: Optional[Path] = None) -> list[str]:
    """Account names to scrub from free text: the configured account keys plus extras."""
    terms: set[str] = set()
    for base in {root or runtime_root(), ROOT}:
        try:
            cfg = json.loads((base / "config" / "account_capabilities.json").read_text(encoding="utf-8"))
            terms.update(str(k) for k in (cfg.get("accounts") or {}).keys())
        except (OSError, ValueError, AttributeError):
            continue
    terms.update(t.strip() for t in os.environ.get("TRADEAI_EXPORT_EXTRA_ACCOUNT_TERMS", "").split(",") if t.strip())
    return sorted((t for t in terms if len(t) >= 3), key=len, reverse=True)


def _account_term_re(terms: Iterable[str]) -> Optional[re.Pattern[str]]:
    terms = list(terms)
    if not terms:
        return None
    return re.compile(r"(?<![A-Za-z0-9])(" + "|".join(re.escape(t) for t in terms) + r")(?![A-Za-z0-9])",
                      re.IGNORECASE)


def account_number_re(cfg: dict[str, Any]) -> re.Pattern[str]:
    lo, hi = int(cfg["account_digits_min"]), int(cfg["account_digits_max"])
    # A bare digit run not touching letters, digits, hyphens or dots (GUIDs, hashes,
    # ISO timestamps and decimals do not match).
    return re.compile(r"(?<![\w.\-])\d{%d,%d}(?![\w.\-])" % (lo, hi))


class Redactor:
    def __init__(self, cfg: dict[str, Any], terms: Optional[list[str]] = None):
        self.cfg = cfg
        self.terms = terms if terms is not None else account_terms()
        self.term_re = _account_term_re(self.terms)

    def text(self, v: Any) -> Optional[str]:
        if v is None:
            return None
        s = str(v)
        s = DOLLAR_RE.sub("$[redacted]", s)
        s = MONEY_PHRASE_RE.sub(lambda m: f"{m.group(1)}{m.group(2) or ''} [redacted]", s)
        if self.term_re is not None:
            s = self.term_re.sub("[account]", s)
        s = MASKED_ACCOUNT_RE.sub("[redacted]", s)
        n = int(self.cfg["text_max_chars"])
        if n > 0 and len(s) > n:
            s = s[:n].rstrip() + "…"
        return s

    def texts(self, v: Any) -> list[str]:
        if v is None:
            return []
        items = v if isinstance(v, (list, tuple)) else [v]
        out = []
        for x in items:
            if isinstance(x, dict):
                x = x.get("text") or x.get("question") or x.get("intent")
            t = self.text(x)
            if t:
                out.append(t)
        return out

    def change(self, v: Any) -> Optional[str]:
        """'premium 21.57 -> 19 (-11.9%)' -> 'premium (-11.9%)': the direction, not the price."""
        s = str(v or "").strip()
        m = CHANGE_RE.match(s)
        if m:
            return f"{m.group(1).strip()} {m.group(2) or 'changed'}".strip()
        return self.text(re.sub(r"(?<![\w%])\d[\d,]*\.\d+(?![\d%])", "[n]", s))


def find_violations(obj: Any, cfg: dict[str, Any], terms: list[str], path: str = "$") -> list[str]:
    """Anything that must not be written: forbidden keys, dollar amounts, account names/numbers."""
    out: list[str] = []
    acct_re = account_number_re(cfg)
    term_re = _account_term_re(terms)
    if isinstance(obj, dict):
        for k, v in obj.items():
            lk = str(k).lower()
            if lk in FORBIDDEN_KEYS or lk.endswith(FORBIDDEN_SUFFIXES):
                out.append(f"{path}.{k}: forbidden key")
            out += find_violations(v, cfg, terms, f"{path}.{k}")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            out += find_violations(v, cfg, terms, f"{path}[{i}]")
    elif isinstance(obj, str):
        if acct_re.search(obj) or MASKED_ACCOUNT_RE.search(obj):
            out.append(f"{path}: account-number-like value")
        if re.search(r"\$\s?-?\d", obj):
            out.append(f"{path}: dollar amount")
        if term_re is not None and term_re.search(obj):
            out.append(f"{path}: account name")
    elif isinstance(obj, int) and not isinstance(obj, bool):
        lo = int(cfg["account_digits_min"])
        if len(str(abs(obj))) >= lo:
            out.append(f"{path}: account-number-like value")
    return out


# ── sources ──────────────────────────────────────────────────────────────────

def read_events(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(e, dict):
            out.append(e)
    return out


def read_db_decisions(limit: int) -> tuple[list[dict[str, Any]], str]:
    """cio_decisions options reviews, newest first. Fail-soft: ([], reason) when unavailable."""
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        from db_adapter import _execute  # type: ignore
    except Exception as exc:  # noqa: BLE001
        return [], f"db_adapter unavailable: {type(exc).__name__}"
    try:
        rows = _execute(
            "SELECT decision_id, symbol, action, status, created_at, metadata FROM cio_decisions "
            "WHERE action_class = 'options_thesis_review' ORDER BY created_at DESC LIMIT %s",
            (int(limit),), fetch="all")
    except Exception as exc:  # noqa: BLE001
        return [], f"db read failed: {type(exc).__name__}"
    if rows is None:
        return [], "db unavailable"
    return [dict(r) for r in rows], "ok"


# ── projection (allowlist) ───────────────────────────────────────────────────

def _review_of(e: dict[str, Any]) -> dict[str, Any]:
    r = e.get("review")
    return r if isinstance(r, dict) else {}


def decision_from_event(e: dict[str, Any], red: Redactor, symbol: Optional[str]) -> dict[str, Any]:
    r = _review_of(e)
    return {
        "decision_guid": e.get("decision_guid"),
        "position_guid": e.get("position_guid"),
        "symbol": symbol,
        "outcome": e.get("outcome") or r.get("outcome"),
        "confidence": e.get("confidence") or r.get("confidence"),
        "reasoning": red.text(r.get("reasoning")),
        "concerns": red.texts(r.get("concerns")),
        "unknowns": red.texts(r.get("unknowns")),
        "reviewed_pin": e.get("reviewed_pin"),
        "recorded_at": e.get("recorded_at"),
        "source": "options_thesis_log",
    }


def decision_from_row(row: dict[str, Any], red: Redactor) -> dict[str, Any]:
    meta = row.get("metadata")
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except ValueError:
            meta = {}
    meta = meta if isinstance(meta, dict) else {}
    r = meta.get("review") if isinstance(meta.get("review"), dict) else {}
    at = row.get("created_at")
    return {
        "decision_guid": row.get("decision_id"),
        "position_guid": meta.get("position_guid"),
        "symbol": row.get("symbol"),
        "outcome": r.get("outcome") or row.get("action"),
        "confidence": r.get("confidence"),
        "reasoning": red.text(r.get("reasoning")),
        "concerns": red.texts(r.get("concerns")),
        "unknowns": red.texts(r.get("unknowns")),
        "status": row.get("status"),
        "recorded_at": at.isoformat() if hasattr(at, "isoformat") else (str(at) if at else None),
        "source": "cio_decisions",
    }


def thesis_projection(events: list[dict[str, Any]], red: Redactor) -> list[dict[str, Any]]:
    """Current version per position_guid, with lifecycle stage, latest decision, follow-up, validation."""
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        from lib.options_thesis import LIFECYCLE_EVENTS  # type: ignore
    except Exception:  # noqa: BLE001 -- keep the export alive if the lib moves
        LIFECYCLE_EVENTS = {}
    by_guid: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for e in events:
        g = e.get("position_guid")
        if not g:
            continue
        if g not in by_guid:
            by_guid[g] = []
            order.append(g)
        by_guid[g].append(e)
    out = []
    for g in order:
        evs = by_guid[g]
        versions = [e for e in evs if e.get("event_type") == "OPTIONS_THESIS_VERSION"]
        if not versions:
            continue
        cur = versions[-1]
        stage, stage_at = "CREATED", versions[0].get("recorded_at")
        for e in evs:
            if e.get("event_type") in LIFECYCLE_EVENTS:
                stage, stage_at = LIFECYCLE_EVENTS[e["event_type"]], e.get("recorded_at")
        decisions = [e for e in evs if e.get("event_type") == "OPTIONS_THESIS_DECISION"]
        followups = [e for e in evs if e.get("event_type") == "OPTIONS_THESIS_FOLLOWUP_REQUESTED"]
        validations = [e for e in evs if e.get("event_type") == "OPTIONS_VALIDATED"]
        entry = cur.get("entry_criteria") if isinstance(cur.get("entry_criteria"), dict) else {}
        it = cur.get("investment_thesis") if isinstance(cur.get("investment_thesis"), dict) else {}
        fu = followups[-1] if followups else None
        va = validations[-1] if validations else None
        out.append({
            "position_guid": g,
            "symbol": cur.get("symbol"),
            "strategy": cur.get("strategy_type") or cur.get("strategy"),
            "strike": entry.get("strike"),
            "expiration": entry.get("expiration"),
            "dte": entry.get("dte"),
            "pin": cur.get("pin"),
            "version": cur.get("version"),
            "supersedes": cur.get("supersedes"),
            "thesis_gate_state": cur.get("thesis_gate_state"),
            "missing_required": list(cur.get("missing_required") or []),
            "investment_thesis": red.text(it.get("summary")),
            "catalysts": red.texts(cur.get("catalysts")),
            "exit_criteria": red.texts(cur.get("exit_criteria")),
            "lifecycle_stage": stage,
            "lifecycle_stage_at": stage_at,
            "latest_decision": (decision_from_event(decisions[-1], red, cur.get("symbol")) if decisions else None),
            "followup": ({"deliverables": red.texts(fu.get("deliverables")), "due_at": fu.get("due_at"),
                          "recorded_at": fu.get("recorded_at")} if fu else None),
            "validation": ({"status": va.get("status"),
                            "material_changes": [c for c in (red.change(x) for x in (va.get("material_changes") or []))
                                                 if c],
                            "validated_at": va.get("validated_at")} if va else None),
            "recorded_at": cur.get("recorded_at"),
        })
    out.sort(key=lambda r: str(r.get("recorded_at") or ""), reverse=True)
    return out


def decisions_projection(events: list[dict[str, Any]], db_rows: list[dict[str, Any]], red: Redactor,
                         limit: int) -> list[dict[str, Any]]:
    sym_by_guid: dict[str, Any] = {}
    for e in events:
        if e.get("event_type") == "OPTIONS_THESIS_VERSION" and e.get("position_guid"):
            sym_by_guid[e["position_guid"]] = e.get("symbol")
    merged: dict[str, dict[str, Any]] = {}
    for row in db_rows:
        d = decision_from_row(row, red)
        if d.get("decision_guid"):
            merged[d["decision_guid"]] = d
    for e in events:
        if e.get("event_type") != "OPTIONS_THESIS_DECISION":
            continue
        d = decision_from_event(e, red, sym_by_guid.get(e.get("position_guid")))
        key = d.get("decision_guid") or f"{d.get('position_guid')}@{d.get('recorded_at')}"
        if key in merged:
            # The log carries the reviewed pin; the table carries the status. Keep both.
            base = merged[key]
            merged[key] = {**d, **{k: v for k, v in base.items() if v not in (None, [], "")},
                           "reviewed_pin": d.get("reviewed_pin"), "source": "options_thesis_log+cio_decisions"}
        else:
            merged[key] = d
    rows = sorted(merged.values(), key=lambda r: str(r.get("recorded_at") or ""), reverse=True)
    return rows[: max(0, int(limit))]


# ── rendering ────────────────────────────────────────────────────────────────

def _md_cell(v: Any) -> str:
    if v is None or v == [] or v == "":
        return "—"
    if isinstance(v, list):
        v = "; ".join(str(x) for x in v)
    return str(v).replace("|", "\\|").replace("\n", " ")


def theses_markdown(rows: list[dict[str, Any]], generated_at: str) -> str:
    lines = [
        "# Options theses — latest version per position",
        "",
        f"Generated {generated_at}. Redacted export: no account names, no dollar amounts. "
        "Advisory record only; nothing here is an order.",
        "",
        "| Symbol | Strategy | Strike | Expiration | DTE | Stage | Gate | Version | Latest decision |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        dec = r.get("latest_decision") or {}
        lines.append("| " + " | ".join(_md_cell(x) for x in (
            r.get("symbol"), r.get("strategy"), r.get("strike"), r.get("expiration"), r.get("dte"),
            r.get("lifecycle_stage"), r.get("thesis_gate_state"), r.get("version"),
            (f"{dec.get('outcome')} ({dec.get('confidence')})" if dec else None))) + " |")
    for r in rows:
        lines += ["", f"## {r.get('symbol')} {r.get('strategy')} {r.get('strike')} {r.get('expiration')}", "",
                  f"- Position GUID: `{r.get('position_guid')}`",
                  f"- Pin: `{r.get('pin')}` (supersedes: {_md_cell(r.get('supersedes'))})",
                  f"- Stage: {r.get('lifecycle_stage')} since {_md_cell(r.get('lifecycle_stage_at'))}",
                  f"- Thesis gate: {r.get('thesis_gate_state')}; missing: {_md_cell(r.get('missing_required'))}",
                  f"- Thesis: {_md_cell(r.get('investment_thesis'))}",
                  f"- Catalysts: {_md_cell(r.get('catalysts'))}",
                  f"- Exit criteria: {_md_cell(r.get('exit_criteria'))}"]
        dec = r.get("latest_decision")
        if dec:
            lines += [f"- Latest CIO decision `{dec.get('decision_guid')}`: {dec.get('outcome')} "
                      f"({dec.get('confidence')}) at {_md_cell(dec.get('recorded_at'))}",
                      f"  - Reasoning: {_md_cell(dec.get('reasoning'))}",
                      f"  - Concerns: {_md_cell(dec.get('concerns'))}",
                      f"  - Unknowns: {_md_cell(dec.get('unknowns'))}"]
        fu = r.get("followup")
        if fu:
            lines += [f"- Follow-up due {_md_cell(fu.get('due_at'))}: {_md_cell(fu.get('deliverables'))}"]
        va = r.get("validation")
        if va:
            lines += [f"- Validation: {va.get('status')} at {_md_cell(va.get('validated_at'))}; "
                      f"material changes: {_md_cell(va.get('material_changes'))}"]
    if not rows:
        lines += ["", "_No options theses on file._"]
    return "\n".join(lines) + "\n"


def decisions_markdown(rows: list[dict[str, Any]], generated_at: str, db_status: str) -> str:
    lines = [
        "# CIO options decisions — newest first",
        "",
        f"Generated {generated_at}. Redacted export: no account names, no dollar amounts. "
        f"Database read: {db_status}.",
        "",
        "| Recorded | Symbol | Outcome | Confidence | Decision GUID | Source |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append("| " + " | ".join(_md_cell(x) for x in (
            r.get("recorded_at"), r.get("symbol"), r.get("outcome"), r.get("confidence"),
            r.get("decision_guid"), r.get("source"))) + " |")
    for r in rows:
        lines += ["", f"## {r.get('symbol')} — {r.get('outcome')} ({r.get('confidence')})", "",
                  f"- Decision GUID: `{r.get('decision_guid')}`; position GUID: `{r.get('position_guid')}`",
                  f"- Reasoning: {_md_cell(r.get('reasoning'))}",
                  f"- Concerns: {_md_cell(r.get('concerns'))}",
                  f"- Unknowns: {_md_cell(r.get('unknowns'))}"]
    if not rows:
        lines += ["", "_No CIO options decisions on file._"]
    return "\n".join(lines) + "\n"


def _jsonl(rows: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(r, sort_keys=True, default=str) + "\n" for r in rows)


# ── writing ──────────────────────────────────────────────────────────────────

def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def build(cfg: Optional[dict[str, Any]] = None, *, events: Optional[list[dict[str, Any]]] = None,
          db_rows: Optional[list[dict[str, Any]]] = None, terms: Optional[list[str]] = None,
          generated_at: Optional[str] = None) -> dict[str, Any]:
    """Everything that would be written: {filename: text}, plus counts and violations."""
    from datetime import datetime, timezone
    cfg = cfg or settings()
    terms = terms if terms is not None else account_terms()
    red = Redactor(cfg, terms)
    src = runtime_root() / "data" / "cio" / "options_theses.jsonl"
    if events is None:
        events = read_events(src)
    db_status = "supplied"
    if db_rows is None:
        if cfg.get("use_db"):
            db_rows, db_status = read_db_decisions(int(cfg["decisions_max"]))
        else:
            db_rows, db_status = [], "skipped"
    theses = thesis_projection(events, red)
    decisions = decisions_projection(events, db_rows, red, int(cfg["decisions_max"]))
    violations = find_violations({"theses": theses, "decisions": decisions}, cfg, terms)
    gen = generated_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    files = {
        f"{THESES_BASENAME}.jsonl": _jsonl(theses),
        f"{THESES_BASENAME}.md": theses_markdown(theses, gen),
        f"{DECISIONS_BASENAME}.jsonl": _jsonl(decisions),
        f"{DECISIONS_BASENAME}.md": decisions_markdown(decisions, gen, db_status),
    }
    # The markdown is derived from the same allowlisted rows; scan it too.
    for name, text in files.items():
        if name.endswith(".md"):
            violations += [f"{name}{v[1:]}" for v in find_violations(text, cfg, terms)]
    return {"source": str(src), "events": len(events), "theses": len(theses), "decisions": len(decisions),
            "db_status": db_status, "db_rows": len(db_rows), "files": files, "violations": violations}


def write(result: dict[str, Any], out_dir: Path) -> list[str]:
    if result["violations"]:
        raise RuntimeError("refusing to write: " + "; ".join(result["violations"][:10]))
    written = []
    for name, text in result["files"].items():
        atomic_write(out_dir / name, text)
        written.append(str(out_dir / name))
    return written


def _load_env() -> None:
    for base in (runtime_root(), ROOT):
        f = base / ".env"
        if not f.is_file():
            continue
        for raw in f.read_text(errors="ignore").splitlines():
            s = raw.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Redacted options runtime snapshot for the Drive mirror")
    ap.add_argument("--apply", action="store_true", help="write the files (default: dry run)")
    ap.add_argument("--no-db", action="store_true", help="skip the cio_decisions read")
    a = ap.parse_args(argv)
    cfg = settings()
    if a.no_db:
        cfg["use_db"] = False
    if cfg["use_db"]:
        _load_env()
    res = build(cfg)
    out_dir = export_root()
    summary = {k: res[k] for k in ("source", "events", "theses", "decisions", "db_status", "db_rows")}
    summary.update(out_dir=str(out_dir), mode="apply" if a.apply else "dry_run",
                   files={n: len(t.encode("utf-8")) for n, t in res["files"].items()},
                   violations=res["violations"])
    if res["violations"]:
        summary["ok"] = False
        print(json.dumps(summary, indent=2))
        return 2
    if a.apply:
        summary["written"] = write(res, out_dir)
    summary["ok"] = True
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
