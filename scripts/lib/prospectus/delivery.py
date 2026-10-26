"""Prospectus delivery: the window outbox (lane side) and the message plan (host sender side).

Operator 2026-10-26: reports "should be sent out both in Word and PDF as a notification [on] Telegram and [email]";
clarified the same day: EMAIL is "just the audit" — a summary of each run (which reports were written, trigger
reasons, verdict changes, gate status, the run's cost and the running monthly spend, links), no attachments.
TELEGRAM carries the summary plus each report's PDF and Word file.

Split on purpose (AGENTS.md §23.14, §24.1: an n8n lane is never a sender):

* ``write_outbox`` runs inside the n8n lane (``scripts/prospectus_window.py``). It writes one JSON record per run
  under ``<state>/data/prospectus/delivery/outbox/`` and sends nothing.
* ``plan_telegram`` / ``plan_email`` / ``deliver`` run in the host sender (``scripts/prospectus_deliver.py``), which
  injects the transports: ``telegram_alert.send_telegram`` / ``send_telegram_document`` (the chokepoint) and
  ``email_notifier.send_email`` (the gog Gmail path the digests use). This module imports neither.

Idempotency: ``delivery/ledger.json`` keys every report by ``SYMBOL@version`` and records, per channel, what reached
the transport. A rerun sends only what is missing. Accounts never appear (no account names, no numbers).
READ_ONLY_ADVISORY (MBI_BEHAVIOR=0).
"""
from __future__ import annotations

from datetime import datetime, timezone
import html
from pathlib import Path
import shutil
from typing import Any, Callable

from . import store

OUTBOX_SCHEMA = "ProspectusDeliveryOutbox@v1"
LEDGER_SCHEMA = "ProspectusDeliveryLedger@v1"
DEFAULT_LINK = "https://ms01-openclaw.tail163d14.ts.net/v3/prospectus/{symbol}"
TELEGRAM_FILE_MAX_BYTES = 50 * 1024 * 1024  # Bot API sendDocument limit
TELEGRAM_TEXT_MAX = 3800  # one message, under the 4,096 UTF-16 limit with room for the provenance footer


def delivery_cfg(cfg: dict) -> dict:
    return cfg.get("delivery") or {}


def outbox_dir(base: Path) -> Path:
    return base / "delivery" / "outbox"


def sent_dir(base: Path) -> Path:
    return base / "delivery" / "sent"


def link_for(cfg: dict, symbol: str) -> str:
    return str(delivery_cfg(cfg).get("link_template") or DEFAULT_LINK).format(symbol=symbol)


def scope_enabled(cfg: dict, scope: str) -> bool:
    """Holdings always deliver; the watch list follows ``delivery.scopes.watch`` (default on)."""
    if scope == "holding":
        return True
    return bool((delivery_cfg(cfg).get("scopes") or {}).get(scope, True))


def conviction_of(doc: dict | None) -> Any:
    for fact in (doc or {}).get("facts") or []:
        if fact.get("kind") == "cio" and str(fact.get("label") or "").lower() == "cio conviction":
            return fact.get("value")
    return None


def gate_of(entry: dict, doc: dict | None) -> str:
    gate = entry.get("gate_status") or (entry.get("gate") or {}).get("status") \
        or ((doc or {}).get("gate") or {}).get("status")
    return str(gate) if gate else "not gated"


# ── lane side: the outbox ─────────────────────────────────────────────────────────────────────────────────────
def report_item(base: Path, cfg: dict, symbol: str, *, row: dict, before: dict, universe: dict) -> dict | None:
    """One delivered report, read back from the index and its version directory."""
    entry = store.read_index(base)["items"].get(symbol) or {}
    version = entry.get("version")
    if not version:
        return None
    doc = store.read_prospectus(base, symbol, version)
    files = {}
    for kind in ("pdf", "docx"):
        path = store.file_path(base, symbol, kind, version)
        if path is not None:
            files[kind] = {"rel": str(path.relative_to(base)), "bytes": path.stat().st_size}
    prev = before.get(symbol) or {}
    verdict = entry.get("verdict_line") or ""
    u = universe.get(symbol) or {}
    return {"symbol": symbol, "version": version, "name": entry.get("name") or symbol,
            "scope": entry.get("scope") or row.get("scope") or "watch", "value_usd": u.get("value_usd"),
            "reason": row.get("reason") or "scheduled", "mode": (doc or {}).get("mode") or row.get("mode"),
            "verdict_line": verdict, "previous_verdict_line": prev.get("verdict_line"),
            "previous_version": prev.get("version"),
            "verdict_changed": bool(prev.get("verdict_line")) and prev.get("verdict_line") != verdict,
            "conviction": conviction_of(doc), "gate_status": gate_of(entry, doc), "status": entry.get("status"),
            "model": entry.get("model"), "cost_usd": entry.get("cost_usd"), "link": link_for(cfg, symbol),
            "files": files}


def write_outbox(base: Path, record: dict) -> Path:
    """Write one run's outbox record (atomic; one file per run key, never overwritten once delivered)."""
    key = str(record["run_key"]).replace(":", "_").replace("/", "_")
    path = outbox_dir(base) / f"{key}.json"
    store.write_json(path, {"schema": OUTBOX_SCHEMA, **record})
    return path


def pending_outbox(base: Path) -> list[Path]:
    folder = outbox_dir(base)
    return sorted(folder.glob("*.json")) if folder.is_dir() else []


# ── ledger ────────────────────────────────────────────────────────────────────────────────────────────────────
def read_ledger(base: Path) -> dict:
    doc = store._read_json(base / "delivery" / "ledger.json", None)
    if not isinstance(doc, dict) or not isinstance(doc.get("reports"), dict):
        return {"schema": LEDGER_SCHEMA, "reports": {}, "runs": {}}
    doc.setdefault("runs", {})
    return doc


def write_ledger(base: Path, doc: dict) -> None:
    store.write_json(base / "delivery" / "ledger.json", doc)


def item_key(item: dict) -> str:
    return f"{item['symbol']}@{item['version']}"


# ── host side: message plans ──────────────────────────────────────────────────────────────────────────────────
def _money(v: Any) -> str:
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return "n/a"


def _conv(v: Any) -> str:
    try:
        return f"{float(v):.0f}"
    except (TypeError, ValueError):
        return "n/a"


def _title(record: dict) -> str:
    label = record.get("window_label") or record.get("window_id") or "run"
    return f"Ticker Prospectus — {label} ({record.get('local_date') or ''})".strip()


def plan_telegram(record: dict, cfg: dict, ledger: dict, base: Path) -> dict:
    """The Telegram summary text and the documents to attach, for the items not yet delivered."""
    tcfg = delivery_cfg(cfg).get("telegram") or {}
    items = [i for i in record.get("items") or [] if scope_enabled(cfg, i.get("scope", "watch"))]
    todo = [i for i in items if not (ledger["reports"].get(item_key(i)) or {}).get("telegram_summary")]
    max_attach = int(tcfg.get("max_attached_reports", 10))
    attach_scope_all = len(items) <= max_attach
    docs, linked_only = [], []
    for i in items:
        done = set((ledger["reports"].get(item_key(i)) or {}).get("telegram_files") or [])
        if not attach_scope_all and i.get("scope") != "holding":
            linked_only.append(i["symbol"])
            continue
        for kind in tcfg.get("formats") or ["pdf", "docx"]:
            meta = (i.get("files") or {}).get(kind)
            if not meta or kind in done:
                continue
            if int(meta.get("bytes") or 0) > TELEGRAM_FILE_MAX_BYTES:
                linked_only.append(f"{i['symbol']} {kind.upper()} (over 50 MB)")
                continue
            label = "PDF" if kind == "pdf" else "Word"
            docs.append({"key": item_key(i), "kind": kind, "path": str(base / meta["rel"]),
                         "caption": f"{i['symbol']} — Ticker Prospectus {i['version']} ({label})"})
    lines = [f"<b>{html.escape(_title(record))}</b>",
             f"{len(items)} report(s) written" + (f" · {len(record.get('failed') or [])} failed"
                                                   if record.get("failed") else "")
             + (f" · {record.get('queue_left', 0)} still queued" if record.get("queue_left") else ""), ""]
    for i in todo:
        verdict = html.escape((i.get("verdict_line") or "")[:220])
        change = " (verdict changed)" if i.get("verdict_changed") else ""
        lines.append(f"<b>{html.escape(i['symbol'])}</b> · {html.escape(i.get('scope', ''))} · "
                     f"CIO conviction {_conv(i.get('conviction'))} · gate {html.escape(str(i.get('gate_status')))}")
        lines.append(f"Trigger: {html.escape(str(i.get('reason')))}{change}")
        if verdict:
            lines.append(f"Verdict: {verdict}")
        lines.append(html.escape(i["link"]))
        lines.append("")
    if linked_only:
        lines.append("Linked, not attached: " + html.escape(", ".join(linked_only)))
    lines.append("Research only — not an order.")
    text = "\n".join(lines).strip()
    if len(text) > TELEGRAM_TEXT_MAX:
        text = text[: TELEGRAM_TEXT_MAX - 40].rsplit("\n", 1)[0] + "\n… (full list on the Prospectus page)"
    return {"text": text if todo else None, "summary_keys": [item_key(i) for i in todo], "documents": docs,
            "linked_only": linked_only}


def plan_email(record: dict, cfg: dict) -> dict:
    """The run audit: what was written, why, verdict changes, gate status, cost and the month's spend, links."""
    items = [i for i in record.get("items") or [] if scope_enabled(cfg, i.get("scope", "watch"))]
    subject = f"[Trade AI] {_title(record)}: {len(items)} report(s), run cost {_money(record.get('cost_usd'))}"
    out = [_title(record), "=" * len(_title(record)), "",
           f"Window: {record.get('window_id')} (started {record.get('started_at')}, finished {record.get('finished_at')})",
           f"Reports written: {len(items)}   Failed: {len(record.get('failed') or [])}   "
           f"Still queued: {record.get('queue_left', 0)}",
           f"Run cost: {_money(record.get('cost_usd'))}   Month to date ({record.get('month')}): "
           f"{_money(record.get('month_spend_usd'))}"]
    if record.get("stopped_reason"):
        out.append(f"Stopped early: {record['stopped_reason']}")
    if record.get("enqueued"):
        out.append(f"Newly queued by triggers this run: {record['enqueued']}")
    out.append("")
    for i in items:
        out.append(f"{i['symbol']} ({i.get('name')}) — {i.get('scope')}, version {i['version']}")
        out.append(f"  Trigger: {i.get('reason')}   Gate: {i.get('gate_status')}   Status: {i.get('status')}   "
                   f"CIO conviction: {_conv(i.get('conviction'))}   Cost: {_money(i.get('cost_usd'))}")
        if i.get("verdict_changed"):
            out.append(f"  Verdict CHANGED. Was: {i.get('previous_verdict_line')}")
            out.append(f"               Now: {i.get('verdict_line')}")
        else:
            out.append(f"  Verdict: {i.get('verdict_line')}")
        out.append(f"  {i['link']}")
        out.append("")
    for f in record.get("failed") or []:
        out.append(f"FAILED {f.get('symbol')}: {f.get('error') or 'see the Prospectus page'}")
    out += ["", "PDF and Word files are on the Prospectus page and in Telegram.",
            "Research only — not an order (READ_ONLY_ADVISORY)."]
    return {"subject": subject, "body": "\n".join(out)}


def deliver(base: Path, cfg: dict, *, send_text: Callable[[str], bool], send_document: Callable[[str, str], bool],
            send_email: Callable[[str, str], bool], apply: bool, log: Callable[[str], None] = print,
            now: datetime | None = None) -> dict:
    """Deliver every pending outbox record. Dry (``apply=False``) returns the plan and sends nothing."""
    now = now or datetime.now(timezone.utc)
    dcfg = delivery_cfg(cfg)
    tel_on, mail_on = bool(dcfg.get("telegram", {}).get("enabled", True)), bool(dcfg.get("email", {}).get("enabled", True))
    summary = {"records": [], "failures": [], "mode": "apply" if apply else "dry_run"}
    ledger = read_ledger(base)
    for path in pending_outbox(base):
        record = store._read_json(path, None)
        if not isinstance(record, dict) or record.get("schema") != OUTBOX_SCHEMA:
            summary["failures"].append({"outbox": path.name, "error": "unreadable outbox record"})
            continue
        run = ledger["runs"].setdefault(record["run_key"], {})
        rec = {"run_key": record["run_key"], "items": len(record.get("items") or []), "telegram": None, "email": None}
        if not record.get("items") and not record.get("failed"):
            rec["telegram"] = rec["email"] = "nothing_to_send"
        if tel_on and record.get("items"):
            plan = plan_telegram(record, cfg, ledger, base)
            rec["telegram"] = {"summary": bool(plan["text"]), "documents": len(plan["documents"]),
                               "linked_only": plan["linked_only"]}
            if apply:
                ok = True
                if plan["text"]:
                    if send_text(plan["text"]):
                        for k in plan["summary_keys"]:
                            ledger["reports"].setdefault(k, {})["telegram_summary"] = now.isoformat()
                    else:
                        ok = False
                for d in plan["documents"]:
                    if send_document(d["path"], d["caption"]):
                        files = ledger["reports"].setdefault(d["key"], {}).setdefault("telegram_files", [])
                        files.append(d["kind"])
                    else:
                        ok = False
                if not ok:
                    summary["failures"].append({"outbox": path.name, "channel": "telegram"})
                write_ledger(base, ledger)
        elif not tel_on:
            rec["telegram"] = "disabled"
        if mail_on and (record.get("items") or record.get("failed")) and not run.get("email"):
            plan = plan_email(record, cfg)
            rec["email"] = {"subject": plan["subject"], "chars": len(plan["body"])}
            if apply:
                if send_email(plan["subject"], plan["body"]):
                    run["email"] = now.isoformat()
                    for i in record.get("items") or []:
                        ledger["reports"].setdefault(item_key(i), {})["email"] = now.isoformat()
                else:
                    summary["failures"].append({"outbox": path.name, "channel": "email"})
                write_ledger(base, ledger)
        elif not mail_on:
            rec["email"] = "disabled"
        if apply:
            run["attempts"] = int(run.get("attempts", 0)) + 1
            if _record_done(record, cfg, ledger, tel_on, mail_on):
                run["done"] = now.isoformat()
                sent_dir(base).mkdir(parents=True, exist_ok=True)
                shutil.move(str(path), str(sent_dir(base) / path.name))  # archived, never deleted
            write_ledger(base, ledger)
        summary["records"].append(rec)
        log(f"{'SENT' if apply else 'PLAN'} {record['run_key']}: {rec}")
    return summary


def _record_done(record: dict, cfg: dict, ledger: dict, tel_on: bool, mail_on: bool) -> bool:
    if mail_on and (record.get("items") or record.get("failed")) and not ledger["runs"][record["run_key"]].get("email"):
        return False
    if tel_on and record.get("items"):
        plan = plan_telegram(record, cfg, ledger, Path("."))
        if plan["text"] or plan["documents"]:
            return False
    return True
