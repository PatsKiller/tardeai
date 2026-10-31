"""Poison-item quarantine: an item that fails a lane in N consecutive runs is skipped (with a receipt and one P2) so
the lane carries on with every other item.

Coordinator 2026-10-31, under the operator's "validate all stuck agents and processes fix montior and make auto
healings with claude code": Ask-the-CIO thread thr_b00c8806cf63a6bf failed cio-ask-lifecycle three runs in a row,
the n8n breaker opened, and every other thread's hourly check stopped for a day.

Usage inside a lane (one instance per run):

    q = Quarantine.for_lane("cio-ask-lifecycle", dry_run=dry_run)
    if q.is_quarantined(item_id): skip
    ...
    newly = q.record_run({item_id: failed_bool, ...}, reasons={item_id: "..."})   # after the loop
    q.save()                                                                        # no-op on dry run / disabled

Disabled (config ``enabled: false``, the default) the class is inert: nothing is skipped, counted or written.
The stuck-work monitor reads the store and reports every quarantined item as ``poison_item`` (a code defect for the
Claude Code fixer). Never: deleting the item or its data — quarantine only skips it.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config" / "poison_quarantine.json"
SCHEMA_RECEIPT = "PoisonQuarantineReceipt@v1"


def load_config(path: Path | str = CONFIG_PATH) -> dict:
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    if cfg.get("schema") != "PoisonQuarantine@v1":
        raise ValueError(f"{path}: expected schema PoisonQuarantine@v1")
    return cfg


def state_root() -> Path:
    return Path(os.environ.get("TRADEAI_STATE_ROOT") or Path.home() / "trade-ai-releases" / "persistent-state")


class Quarantine:
    def __init__(
        self, lane: str, cfg: Mapping[str, Any], root: Path, *, dry_run: bool = False, now: Optional[datetime] = None
    ) -> None:
        self.lane, self.cfg, self.root, self.dry_run = lane, dict(cfg), Path(root), dry_run
        self.enabled = bool(cfg.get("enabled"))
        self.now = now or datetime.now(timezone.utc)
        self.store_p = self.root / cfg["store_rel"]
        self.rec_p = self.root / cfg["receipts_rel"]
        try:
            self.state = json.loads(self.store_p.read_text(encoding="utf-8")) if self.enabled else {}
        except (OSError, ValueError):
            self.state = {}
        self.lane_state = self.state.setdefault(lane, {"streaks": {}, "quarantined": {}})
        self.newly: list[dict] = []

    @classmethod
    def for_lane(
        cls, lane: str, *, dry_run: bool = False, now: Optional[datetime] = None, config_path: Path | str = CONFIG_PATH
    ) -> "Quarantine":
        return cls(lane, load_config(config_path), state_root(), dry_run=dry_run, now=now)

    def is_quarantined(self, item: str) -> bool:
        return self.enabled and str(item) in self.lane_state["quarantined"]

    def record_run(self, outcomes: Mapping[str, bool], *, reasons: Optional[Mapping[str, str]] = None) -> list[dict]:
        """``outcomes``: item -> failed this run. A success resets the streak; ``threshold`` consecutive failures
        quarantine the item. Returns the items quarantined by this run."""
        if not self.enabled:
            return []
        streaks = self.lane_state["streaks"]
        for item, failed in outcomes.items():
            item = str(item)
            if item in self.lane_state["quarantined"]:
                continue
            if not failed:
                streaks.pop(item, None)
                continue
            n = int(streaks.get(item, 0)) + 1
            streaks[item] = n
            if n >= int(self.cfg["threshold"]):
                rec = {
                    "schema": SCHEMA_RECEIPT,
                    "at": self.now.isoformat(),
                    "lane": self.lane,
                    "item": item,
                    "consecutive_failures": n,
                    "reason": (reasons or {}).get(item),
                    "action": "quarantined",
                    "dry_run": self.dry_run,
                }
                self.lane_state["quarantined"][item] = rec
                streaks.pop(item, None)
                self.newly.append(rec)
        return list(self.newly)

    def release(self, item: str) -> bool:
        return self.lane_state["quarantined"].pop(str(item), None) is not None

    def save(self) -> list[str]:
        """Persist state, append receipts, send one P2 per run that quarantined something. Errors are returned (and
        the caller's report should carry them), never swallowed."""
        if not self.enabled or self.dry_run:
            return []
        errors: list[str] = []
        self.store_p.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.store_p.with_name(f".{self.store_p.name}.tmp-{os.getpid()}")
        try:
            tmp.write_text(json.dumps(self.state, indent=1), encoding="utf-8")
            os.replace(tmp, self.store_p)
        except OSError as exc:
            tmp.unlink(missing_ok=True)
            errors.append(f"store: {type(exc).__name__}: {exc}")
        if self.newly:
            try:
                with self.rec_p.open("a", encoding="utf-8") as fh:
                    for rec in self.newly:
                        fh.write(json.dumps(rec) + "\n")
            except OSError as exc:
                errors.append(f"receipts: {type(exc).__name__}: {exc}")
            msg = "\n".join(
                [f"🧪 *Poison item quarantined* — {self.lane}"]
                + [
                    f"• {r['item']}: failed {r['consecutive_failures']} runs in a row ({r.get('reason') or 'no reason'})"
                    for r in self.newly
                ]
                + ["The lane continues without it. Fix the cause, then release it (scripts/lib/poison_quarantine.py)."]
            )
            try:
                from telegram_alert import send_telegram

                if not send_telegram(
                    msg, priority=self.cfg["alert_priority"], dedupe_minutes=0, producer=self.cfg["producer"]
                ):
                    errors.append("send_telegram returned falsy")
            except Exception as exc:  # noqa: BLE001 — returned to the caller, never swallowed
                errors.append(f"send: {type(exc).__name__}: {exc}")
        return errors
