#!/usr/bin/env python3
"""Deliver Ticker Prospectus run outboxes — host sender (operator 2026-10-26).

Operator: reports "should be sent out both in Word and PDF as a notification [on] Telegram and [email]". Email is the
run audit plus the PDF and Word files of the HOLDINGS reports (go-live direction 2026-10-26; ``delivery.email
.attach_scopes``), capped per email (``max_attachment_bytes``, ~20 MB; the rest linked); Watch reports are linked.
Telegram carries the summary plus each report's PDF and Word file.

The n8n lane ``prospectus-build`` (scripts/prospectus_window.py) writes one outbox record per run and sends nothing
(AGENTS.md §23.14, §24.1). This host job sends them through the existing chokepoints only:

* Telegram: ``telegram_alert.send_telegram`` (summary) and ``telegram_alert.send_telegram_document`` (each PDF and
  Word file), as P2 notification intents with the job's own ledger as dedupe (``dedupe_minutes=0``).
* Email: ``email_notifier.send_email`` (gog Gmail, the path the digests use): one plain-text audit per run, with the
  holdings reports' PDF and Word files attached (``attachments=``).

Idempotent per (symbol, version) and per run (``<state>/data/prospectus/delivery/ledger.json``). A record that still
fails after ``delivery.max_attempts`` raises one P2 failure alert and the job exits 1 (the unit shows failed; the
lane registry's freshness check sees the stale receipt).

    python3 scripts/prospectus_deliver.py            # dry run (default): print the plan, send nothing
    python3 scripts/prospectus_deliver.py --apply    # send (host timer tradeai-prospectus-deliver.timer)

READ_ONLY_ADVISORY (MBI_BEHAVIOR=0): research notifications only.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib.prospectus import delivery, load_config, store  # noqa: E402

LANE = "prospectus-deliver"
PRODUCER = "prospectus_deliver"


def state_root() -> Path:
    from scripts.lib.prospectus.inputs import _imp_any
    return Path(_imp_any("scripts.lib.anthropic_routing", "lib.anthropic_routing").state_root())


def transports():
    """The production chokepoints (imported only on --apply)."""
    from telegram_alert import send_telegram, send_telegram_document
    from email_notifier import send_email

    def text(msg: str) -> bool:
        return bool(send_telegram(msg, priority="P2", dedupe_minutes=0, producer=PRODUCER))

    def document(path: str, caption: str) -> bool:
        return bool(send_telegram_document(path, caption=caption, priority="P2", dedupe_minutes=0, producer=PRODUCER))

    def mail(subject: str, body: str, attachments: list[str] | None = None) -> bool:
        return bool(send_email(subject, body, attachments=attachments or None))

    return text, document, mail


def run(apply: bool, cfg: dict, root: Path, *, send_text=None, send_document=None, send_email=None) -> tuple[dict, int]:
    base = store.base_dir(root, cfg)
    if apply and send_text is None:
        send_text, send_document, send_email = transports()
    noop = lambda *a, **k: False  # noqa: E731 - dry run: never called
    out = delivery.deliver(base, cfg, text_fn=send_text or noop, file_fn=send_document or noop,
                           mail_fn=send_email or noop, apply=apply)
    code = 0
    if apply:
        max_attempts = int(delivery.delivery_cfg(cfg).get("max_attempts", 3))
        ledger = delivery.read_ledger(base)
        stuck = [k for k, v in ledger["runs"].items()
                 if not v.get("done") and int(v.get("attempts", 0)) >= max_attempts and not v.get("failure_alerted")]
        if stuck:
            msg = (f"Ticker Prospectus delivery FAILED after {max_attempts} attempts: {', '.join(stuck)}. "
                   "Reports are on the Prospectus page; outbox kept for retry.")
            try:
                send_text(msg)
            except Exception:  # noqa: BLE001 - the exit code and the receipt still carry the failure
                pass
            for k in stuck:
                ledger["runs"][k]["failure_alerted"] = datetime.now(timezone.utc).isoformat()
            delivery.write_ledger(base, ledger)
        out["stuck"] = stuck
        code = 1 if out["failures"] else 0
    return out, code


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Deliver Ticker Prospectus run outboxes (dry run by default).")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)
    cfg = load_config()
    root = state_root()
    started = datetime.now(timezone.utc).isoformat()
    out, code = run(args.apply, cfg, root)
    if args.apply:
        try:
            from scripts.lib.lane_last_receipt import write_lane_receipt
        except ImportError:  # pragma: no cover
            from lib.lane_last_receipt import write_lane_receipt  # type: ignore
        sent = len(out["records"])
        write_lane_receipt(LANE, ok=code == 0, exit_code=code, started_at=started, script="scripts/prospectus_deliver.py",
                           summary={"records": out["records"][:10], "failures": out["failures"][:10],
                                    "stuck": out.get("stuck")},
                           produced_count=sent, attempted_count=sent,
                           empty_reason=None if sent else "no_new_input",
                           error=json.dumps(out["failures"])[:500] if out["failures"] else None,
                           path=root / "data/runtime" / f"{LANE}_last.json")
    print(json.dumps(out, indent=2, default=str))
    return code


if __name__ == "__main__":
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    raise SystemExit(main())
