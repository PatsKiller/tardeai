"""Poison-item quarantine: an item that fails a lane with the SAME DETERMINISTIC error in N consecutive runs is set
aside (receipt + one P2) so the lane carries on with every other item.

Coordinator 2026-10-31, under the operator's "validate all stuck agents and processes fix montior and make auto
healings with claude code": Ask-the-CIO thread thr_b00c8806cf63a6bf failed cio-ask-lifecycle three runs in a row,
the n8n breaker opened, and every other thread's hourly check stopped for a day.

Rules (independent review 2026-10-31):

* Only deterministic per-item errors count: an ALLOWLIST (``deterministic_patterns``). An unknown or missing reason,
  or a transient one (``transient_patterns``), neither counts nor resets: an outage must stay visible as a failing
  lane and still open its breaker.
* If more than ``max_share`` of the items fail in one run, the failure is systemic: nothing is quarantined. Otherwise
  at most ``max_per_run`` items (and at most ``max_share`` of them) are quarantined in one run.
* One store per lane (``store_dir_rel/<lane>.json``), updated read-modify-write under an exclusive flock.
* A corrupt store raises ``PoisonStoreCorrupt`` — never read as empty.
* A quarantine expires after ``expire_hours``: the item is re-checked once; a pass releases it, a deterministic
  failure re-quarantines it at once.
* Release by hand: ``python3 scripts/poison_quarantine.py release --lane L --item I --note "..." [--apply]``.

Disabled (``enabled: false``, the default) the class is inert. Never deletes the item or its data.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config" / "poison_quarantine.json"
SCHEMA_RECEIPT = "PoisonQuarantineReceipt@v1"
SCHEMA_STORE = "PoisonQuarantineStore@v1"


class PoisonStoreCorrupt(RuntimeError):
    pass


def load_config(path: Path | str = CONFIG_PATH) -> dict:
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    if cfg.get("schema") != "PoisonQuarantine@v1":
        raise ValueError(f"{path}: expected schema PoisonQuarantine@v1")
    return cfg


def state_root() -> Path:
    return Path(os.environ.get("TRADEAI_STATE_ROOT") or Path.home() / "trade-ai-releases" / "persistent-state")


def _lane_file(root: Path, cfg: Mapping[str, Any], lane: str) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,80}", lane):
        raise ValueError(f"bad lane id {lane!r}")
    return Path(root) / cfg["store_dir_rel"] / f"{lane}.json"


def read_store(path: Path) -> dict:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"schema": SCHEMA_STORE, "streaks": {}, "quarantined": {}}
    try:
        doc = json.loads(raw)
    except ValueError as exc:
        raise PoisonStoreCorrupt(f"{path}: {exc}") from exc
    if (
        not isinstance(doc, dict)
        or not isinstance(doc.get("quarantined"), dict)
        or not isinstance(doc.get("streaks"), dict)
    ):
        raise PoisonStoreCorrupt(f"{path}: not a {SCHEMA_STORE} document")
    return doc


def counts_as_poison(reason: Optional[str], cfg: Mapping[str, Any]) -> bool:
    """ALLOWLIST (review round 2): a failure counts only when its reason names a known deterministic error type
    (``deterministic_patterns``) and is not also transient. An unknown reason, or none at all, never counts — a new
    kind of outage (OSError, ConnectError, gaierror, SSLError, JSONDecodeError, BrokenPipeError, an API status
    error …) must never quarantine an item."""
    text = str(reason or "").strip()
    if not text or is_transient(text, cfg):
        return False
    return any(re.search(p, text) for p in cfg.get("deterministic_patterns") or [])


def is_transient(reason: Optional[str], cfg: Mapping[str, Any]) -> bool:
    text = str(reason or "")
    return any(re.search(p, text, re.I) for p in cfg.get("transient_patterns") or [])


class Quarantine:
    def __init__(
        self, lane: str, cfg: Mapping[str, Any], root: Path, *, dry_run: bool = False, now: Optional[datetime] = None
    ) -> None:
        self.lane, self.cfg, self.root, self.dry_run = lane, dict(cfg), Path(root), dry_run
        self.enabled = bool(cfg.get("enabled"))
        self.now = now or datetime.now(timezone.utc)
        self.path = _lane_file(self.root, cfg, lane)
        self.doc = read_store(self.path) if self.enabled else {"streaks": {}, "quarantined": {}}  # raises if corrupt
        self.newly: list[dict] = []
        self.released: list[dict] = []
        self.deltas: list[tuple[str, str, Any]] = []
        self.systemic: Optional[dict] = None  # replayed under the flock at save time

    @classmethod
    def for_lane(
        cls, lane: str, *, dry_run: bool = False, now: Optional[datetime] = None, config_path: Path | str = CONFIG_PATH
    ) -> "Quarantine":
        return cls(lane, load_config(config_path), state_root(), dry_run=dry_run, now=now)

    def _expired(self, rec: Mapping[str, Any]) -> bool:
        at = rec.get("at")
        try:
            t = datetime.fromisoformat(str(at))
        except ValueError:
            return False
        return self.now - t >= timedelta(hours=float(self.cfg["expire_hours"]))

    def is_quarantined(self, item: str) -> bool:
        rec = self.doc["quarantined"].get(str(item))
        return bool(self.enabled and rec and not self._expired(rec))

    def record_run(self, outcomes: Mapping[str, bool], *, reasons: Optional[Mapping[str, str]] = None) -> list[dict]:
        """``outcomes``: item -> failed this run (``reasons``: item -> error text). Returns the items quarantined by this
        run. Transient failures are ignored; at most max_per_run / max_share of the items are quarantined."""
        if not self.enabled:
            return []
        reasons = reasons or {}
        failing = sum(1 for f in outcomes.values() if f)
        if failing > float(self.cfg["max_share"]) * len(outcomes):
            # systemic (review round 2): more than max_share of the items failed together — quarantining them one by
            # one would hide the bug, so nothing is quarantined and the lane fails; streaks do not move either
            self.systemic = {"failing": failing, "items": len(outcomes)}
            return []
        cap = min(int(self.cfg["max_per_run"]), int(float(self.cfg["max_share"]) * len(outcomes)))
        for item, failed in outcomes.items():
            item = str(item)
            reason = reasons.get(item)
            held = self.doc["quarantined"].get(item)
            if held and not self._expired(held):
                continue
            if failed and not counts_as_poison(reason, self.cfg):
                continue  # not a known deterministic error: no count, no reset
            if not failed:
                if held:  # an expired quarantine re-checked and passed: released
                    self.released.append({"item": item, "action": "released_by_recheck"})
                    self.deltas.append(("release", item, None))
                self.deltas.append(("reset", item, None))
                continue
            n = self.cfg["threshold"] if held else int(self.doc["streaks"].get(item, 0)) + 1
            if int(n) >= int(self.cfg["threshold"]) and len(self.newly) < cap:
                rec = {
                    "schema": SCHEMA_RECEIPT,
                    "at": self.now.isoformat(),
                    "lane": self.lane,
                    "item": item,
                    "consecutive_failures": int(n),
                    "reason": reason,
                    "action": "quarantined",
                    "recheck": bool(held),
                    "dry_run": self.dry_run,
                }
                self.newly.append(rec)
                self.deltas.append(("quarantine", item, rec))
            else:
                self.deltas.append(("streak", item, int(n)))
        self._apply(self.doc)
        return list(self.newly)

    def _apply(self, doc: dict) -> None:
        for kind, item, val in self.deltas:
            if kind == "reset":
                doc["streaks"].pop(item, None)
            elif kind == "release":
                doc["quarantined"].pop(item, None)
            elif kind == "streak":
                doc["streaks"][item] = val
            elif kind == "quarantine":
                doc["quarantined"][item] = val
                doc["streaks"].pop(item, None)

    def save(self) -> list[str]:
        """Read-modify-write under an exclusive flock; receipts; one P2 per run that quarantined something. Errors are
        returned (and belong in the caller's report), never swallowed. Inert on dry run or when disabled."""
        if not self.enabled or self.dry_run:
            return []
        errors: list[str] = []
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(f"{self.path}.lock", "a+") as lk:
            fcntl.flock(lk.fileno(), fcntl.LOCK_EX)
            try:
                doc = read_store(self.path)  # another run may have written since we loaded
                self._apply(doc)
                doc["schema"] = SCHEMA_STORE
                tmp = self.path.with_name(f".{self.path.name}.tmp-{os.getpid()}")
                try:
                    with tmp.open("w", encoding="utf-8") as fh:
                        json.dump(doc, fh, indent=1)
                        fh.flush()
                        os.fsync(fh.fileno())
                    os.replace(tmp, self.path)
                except OSError as exc:
                    tmp.unlink(missing_ok=True)
                    errors.append(f"store: {type(exc).__name__}: {exc}")
            finally:
                fcntl.flock(lk.fileno(), fcntl.LOCK_UN)
        rec_p = self.root / self.cfg["receipts_rel"]
        if self.newly or self.released:
            try:
                rec_p.parent.mkdir(parents=True, exist_ok=True)
                with rec_p.open("a", encoding="utf-8") as fh:
                    for rec in self.newly + [
                        {"schema": SCHEMA_RECEIPT, "at": self.now.isoformat(), "lane": self.lane, **r}
                        for r in self.released
                    ]:
                        fh.write(json.dumps(rec) + "\n")
            except OSError as exc:
                errors.append(f"receipts: {type(exc).__name__}: {exc}")
        if self.newly:
            msg = "\n".join(
                [f"🧪 *Poison item quarantined* — {self.lane}"]
                + [
                    f"• {r['item']}: same error {r['consecutive_failures']} runs in a row ({r.get('reason') or 'n/a'})"
                    for r in self.newly
                ]
                + [
                    "The lane continues without it. Fix the cause; release: scripts/poison_quarantine.py release "
                    f"--lane {self.lane} --item <id> --note '<why>' --apply (it also expires and is re-checked)."
                ]
            )
            try:
                from telegram_alert import send_telegram

                if not send_telegram(
                    msg,
                    priority=self.cfg["alert_priority"],
                    dedupe_minutes=0,
                    producer=self.cfg["producer"],
                    message_class=self.cfg["message_class"],
                ):
                    errors.append("send_telegram returned falsy")
            except Exception as exc:  # noqa: BLE001 — returned to the caller, never swallowed
                errors.append(f"send: {type(exc).__name__}: {exc}")
        return errors


def release(
    lane: str, item: str, *, note: str, apply: bool, cfg: Mapping[str, Any], root: Path, by: str = "operator"
) -> dict:
    """Remove one item from a lane's quarantine (dry run unless ``apply``), with a receipt."""
    path = _lane_file(root, cfg, lane)
    with open(f"{path}.lock", "a+") if apply else open(os.devnull) as lk:
        if apply:
            fcntl.flock(lk.fileno(), fcntl.LOCK_EX)
        doc = read_store(path)
        if str(item) not in doc["quarantined"]:
            return {"ok": False, "why": f"{item} is not quarantined in {lane}"}
        if not apply:
            return {"ok": True, "dry_run": True, "would_release": doc["quarantined"][str(item)]}
        rec = doc["quarantined"].pop(str(item))
        tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
        tmp.write_text(json.dumps(doc, indent=1), encoding="utf-8")
        os.replace(tmp, path)
        fcntl.flock(lk.fileno(), fcntl.LOCK_UN)
    receipt = {
        "schema": SCHEMA_RECEIPT,
        "at": datetime.now(timezone.utc).isoformat(),
        "lane": lane,
        "item": str(item),
        "action": "released",
        "by": by,
        "note": note,
        "was": rec,
    }
    with (Path(root) / cfg["receipts_rel"]).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(receipt) + "\n")
    return {"ok": True, "released": receipt}
