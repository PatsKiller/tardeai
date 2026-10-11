#!/usr/bin/env python3
"""Nightly system rollup snapshot + Daily System Digest (Reports v3 WS-B).

1. Computes the 24h whole-system rollup (api_v2._system_rollup — same payload the
   Reports → System tab renders, so the digest can never disagree with the page).
2. Upserts ONE row/day into system_rollup_daily (trends corpus for the sparklines).
   The stored payload is bounded (scripts/lib/system_rollup_payload.py): no `trends`
   panel, compact headlines, hard byte cap → typed refusal ROLLUP_PAYLOAD_TOO_LARGE.
3. Renders a deterministic markdown digest → data/portfolios/reports/system_digest_<date>.md
   (indexed by the report catalog family 'system_digest') + an ai_reports row (archive).
4. Telegram gets ONE line (counts + archive pointer), never the body.
5. Every run appends a SystemRollupRunReceipt@v1 line (TRADEAI_SYSTEM_ROLLUP_RECEIPTS,
   default data/runtime/system_rollup_receipts.jsonl) and exits non-zero on any failed step
   (1) or a refused snapshot (3). Storage audit 2026-10-09: this job failed every night from
   2026-08-01 for ~70 days and nothing noticed.

--dry-run computes the rollup and the stored payload, measures it against the cap and renders
the digest, then prints a receipt. It writes no row, no file, no receipt and sends nothing.

Deterministic, zero LLM, advisory-only. Cron: 20:40 daily.
"""
import argparse
import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
try:  # reports live in persistent-state, not the release dir (lib/portfolio_reports_root.py)
    from lib.portfolio_reports_root import portfolio_reports_root as _portfolio_reports_root  # noqa: E402
except ImportError:  # pragma: no cover - imported as scripts.<module>
    from scripts.lib.portfolio_reports_root import portfolio_reports_root as _portfolio_reports_root  # noqa: E402
sys.path.insert(0, str(ROOT / "scripts"))

from lib.system_rollup_payload import (  # noqa: E402
    RollupPayloadRefused,
    build_stored_payload,
    max_payload_bytes,
    serialize_with_cap,
)

RECEIPT_SCHEMA = "SystemRollupRunReceipt@v1"
RECEIPTS_ENV = "TRADEAI_SYSTEM_ROLLUP_RECEIPTS"
EXIT_OK = 0
EXIT_STEP_FAILED = 1
EXIT_PAYLOAD_REFUSED = 3
REPORTS_DIR = _portfolio_reports_root()


def _headlines(panels: dict) -> dict:
    g = lambda n: (panels.get(n) or {}).get("data") or {}
    pipes = g("pipelines").get("rows") or []
    agents = g("agents").get("rows") or []
    props = g("proposals").get("rows") or []
    alerts = g("alerts").get("rows") or []
    return {
        "pipelines_run": sum(int(r.get("runs") or 0) for r in pipes),
        "pipeline_failures": sum(int(r.get("failures") or 0) for r in pipes),
        "agent_analyses": sum(int(r.get("analyses") or 0) for r in agents),
        "proposals": sum(int(r.get("cnt") or 0) for r in props),
        "paper_closed": g("paper_trades").get("closed", 0),
        "paper_pnl": g("paper_trades").get("pnl"),
        "alerts_raw": sum(int(r.get("n") or 0) for r in alerts),
        "research_items": (g("research").get("hermes_items") or 0),
        "reports_generated": sum(int(r.get("n") or 0) for r in (g("reports_generated").get("rows") or [])),
        "directive_hits": g("directives").get("hits", 0),
        "health_score": g("health").get("health_score"),
    }


def receipts_path() -> Path:
    raw = os.environ.get(RECEIPTS_ENV)
    return Path(raw) if raw else ROOT / "data" / "runtime" / "system_rollup_receipts.jsonl"


def write_receipt(receipt: dict) -> str | None:
    """Append one receipt line. A receipt that cannot be written is reported on stderr."""
    path = receipts_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(receipt, default=str, sort_keys=True) + "\n")
        return str(path)
    except OSError as exc:
        print(f"[system-digest] receipt: could not write {path} ({exc})", file=sys.stderr)
        return None


def render_digest(today, hl: dict, panels: dict, snapshot_note: str | None = None) -> str:
    fails = [r for r in ((panels.get("pipelines") or {}).get("data") or {}).get("rows", [])
             if int(r.get("failures") or 0) > 0]
    lines = [
        f"# Daily System Digest — {today}",
        "",
        f"*Deterministic 24h rollup · generated {datetime.now(timezone.utc).isoformat()[:16]}Z · advisory only*",
        "",
    ]
    if snapshot_note:
        lines += [f"> Snapshot: {snapshot_note}", ""]
    lines += [
        "## Headlines",
        f"- Pipelines: {hl['pipelines_run']} runs · {hl['pipeline_failures']} failures",
        f"- Agents: {hl['agent_analyses']} analyses",
        f"- Proposals: {hl['proposals']} created",
        f"- Paper trades closed: {hl['paper_closed']} · P&L ${hl['paper_pnl'] or 0}",
        f"- Alerts (raw events): {hl['alerts_raw']}",
        f"- Research items: {hl['research_items']} · Reports generated: {hl['reports_generated']}",
        f"- Directive hits: {hl['directive_hits']} · Health score: {hl['health_score']}",
        "",
    ]
    if fails:
        lines.append("## Pipeline failures (red rail)")
        for r in fails:
            lines.append(f"- {r.get('pipeline_key')}: {r.get('failures')} failed of {r.get('runs')}")
        lines.append("")
    lines.append("## Panel detail (corpus-tagged)")
    for name, p in panels.items():
        if name == "trends":
            continue
        lines.append(f"### {name} · corpus: {p.get('corpus')}")
        lines.append("```json")
        lines.append(json.dumps(p.get("data") if not p.get("error") else {"error": p["error"]},
                                indent=1, default=str)[:2000])
        lines.append("```")
    return "\n".join(lines)


def _err(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {str(exc)[:300]}"


def run(dry_run: bool = False, today=None) -> tuple[int, dict]:
    """Run the job. Returns (exit_code, receipt). Never raises. `today` is injectable for tests."""
    today = today or datetime.now(timezone.utc).date()
    cap = max_payload_bytes()
    receipt: dict = {
        "schema": RECEIPT_SCHEMA,
        "day": str(today),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": bool(dry_run),
        "cap_bytes": cap,
        "payload_bytes": None,
        "steps": {},
    }
    steps = receipt["steps"]

    def _finish(code: int, status: str) -> tuple[int, dict]:
        receipt["status"] = status
        receipt["exit_code"] = code
        receipt["finished_at"] = datetime.now(timezone.utc).isoformat()
        if not dry_run:
            receipt["receipt_path"] = write_receipt(receipt)
        return code, receipt

    try:
        import api_v2

        rollup = api_v2._system_rollup("24h")
        panels = rollup.get("panels") or {}
        hl = _headlines(panels)
        steps["rollup"] = {"status": "ok", "panels": sorted(panels)}
    except Exception as exc:
        steps["rollup"] = {"status": "failed", "error": _err(exc)}
        traceback.print_exc()
        return _finish(EXIT_STEP_FAILED, "failed")

    refused: RollupPayloadRefused | None = None
    payload_text = None
    try:
        payload_text, size = serialize_with_cap(build_stored_payload(hl, panels), cap)
        receipt["payload_bytes"] = size
        steps["snapshot"] = {"status": "would_write" if dry_run else "pending", "payload_bytes": size}
    except RollupPayloadRefused as exc:
        refused = exc
        receipt["payload_bytes"] = exc.payload_bytes
        steps["snapshot"] = {"status": "refused", **exc.as_dict()}
        print(f"[system-digest] {exc}", file=sys.stderr)

    note = (f"REFUSED {refused.code} ({refused.payload_bytes} B > cap {refused.cap_bytes} B)"
            if refused else None)
    md = render_digest(today, hl, panels, note)
    receipt["digest_bytes"] = len(md.encode("utf-8"))

    if dry_run:
        steps["digest"] = {"status": "would_write"}
        steps["telegram"] = {"status": "skipped_dry_run"}
        return _finish(EXIT_PAYLOAD_REFUSED if refused else EXIT_OK, "refused" if refused else "ok")

    conn = cur = None
    try:
        from db_adapter import _get_conn

        conn = _get_conn()
        cur = conn.cursor()
    except Exception as exc:
        steps["db_connect"] = {"status": "failed", "error": _err(exc)}

    if refused is None:
        if cur is None:
            steps["snapshot"] = {"status": "failed", "error": "no database connection"}
        else:
            try:
                cur.execute(
                    """INSERT INTO system_rollup_daily (day, payload) VALUES (%s, %s::jsonb)
                       ON CONFLICT (day) DO UPDATE SET payload = EXCLUDED.payload, created_at = now()""",
                    (today, payload_text))
                conn.commit()
                steps["snapshot"]["status"] = "ok"
            except Exception as exc:
                conn.rollback()
                steps["snapshot"] = {"status": "failed", "error": _err(exc)}

    out = REPORTS_DIR / f"system_digest_{today}.md"
    try:
        out.write_text(md)
        steps["digest"] = {"status": "ok", "path": out.name}
    except Exception as exc:
        steps["digest"] = {"status": "failed", "error": _err(exc)}

    if cur is None:
        steps["ai_reports"] = {"status": "failed", "error": "no database connection"}
    else:
        try:
            cur.execute(
                """INSERT INTO ai_reports (report_type, title, content, provider, cost, generated_at)
                   VALUES ('system_digest', %s, %s, 'deterministic', 0, now())""",
                (f"Daily System Digest — {today}", md))
            conn.commit()
            steps["ai_reports"] = {"status": "ok"}
        except Exception as exc:
            conn.rollback()
            steps["ai_reports"] = {"status": "failed", "error": _err(exc)}

    # refresh the catalog so the Library row appears without waiting for its cron (advisory)
    try:
        from generate_reports_hub import build_report_catalog
        build_report_catalog(str(ROOT))
        steps["catalog"] = {"status": "ok"}
    except Exception as e:
        steps["catalog"] = {"status": "warn", "error": _err(e)}
        print(f"[system-digest] catalog refresh failed: {e}")

    failed = sorted(k for k, v in steps.items() if v.get("status") == "failed")
    one_liner = (f"System digest ready · {hl['pipelines_run']} pipelines · "
                 f"{hl['pipeline_failures']} failures · {hl['paper_closed']} trades closed · "
                 f"health {hl['health_score']} → Reports › Library")
    if refused is not None:
        one_liner += f" · snapshot {note}"
    if failed:
        one_liner += f" · FAILED steps: {', '.join(failed)}"
    try:
        from telegram_alert import send_telegram
        accepted = bool(send_telegram(one_liner, priority="P2", producer="system_rollup_snapshot"))
        steps["telegram"] = {"status": "accepted" if accepted else "failed",
                             **({} if accepted else {"error": "send_telegram returned False"})}
    except Exception as e:
        steps["telegram"] = {"status": "failed", "error": _err(e)}
        print(f"[system-digest] telegram failed: {e}\n{one_liner}")

    failed = sorted(k for k, v in steps.items() if v.get("status") == "failed")
    receipt["failed_steps"] = failed
    print(f"[system-digest] {out.name}, snapshot {steps['snapshot'].get('status')}, "
          f"payload {receipt['payload_bytes']} B (cap {cap} B); {one_liner}")
    if refused is not None:
        return _finish(EXIT_PAYLOAD_REFUSED, "refused")
    if failed:
        return _finish(EXIT_STEP_FAILED, "failed")
    return _finish(EXIT_OK, "ok")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true",
                    help="compute + measure + render only; no DB write, file, receipt or Telegram")
    args = ap.parse_args(argv)
    code, receipt = run(dry_run=args.dry_run)
    if args.dry_run or code != EXIT_OK:
        print(json.dumps(receipt, default=str, indent=1))
    return code


if __name__ == "__main__":
    sys.exit(main())
