"""release_train_timing.py — measured promote / verify / rollback durations for the release train (Phase 7).

The 08:00 window's latest activation start is 09:00 minus the measured promote, verify and rollback time minus a
buffer (AGENTS.md §25.3), and the 06:00 drain probe needs the same measured restart impact
(``scripts/lib/release_train_drain.py``). Both read ONE history through ``DurationHistory``:

  * the train's own rows, ``<release_window state dir>/train_measurements.jsonl`` (``promote_s``, ``verify_s``,
    ``rollback_s``; written by ``release_train_controller`` after every activation);
  * the deploy receipt history, ``~/.local/state/cio-phase2-exact-main/deploy_receipt_history.jsonl``: one row per
    ``cio_phase2_exact_main_deploy.sh`` receipt (``exact_release_receipt.py`` appends it). A successful ``promote``
    row gives a ``promote_s`` sample and a successful ``rollback`` row a ``rollback_s`` sample, so manual releases and
    rollbacks (the L.1 fallback, drills) count too. Verification has no deploy receipt; ``verify_s`` comes from
    train rows only.

A promote measured by both (the train invoked the deploy script) is counted once: a deploy row whose
``(mode, sha)`` matches a train row's ``(promote|rollback, sha)`` is dropped.

Fail closed: a key with fewer than ``MIN_SAMPLES`` (3) valid samples is UNMEASURED, and every caller refuses.
Samples are finite, positive and at most ``MAX_SAMPLE_S``; anything else (a corrupt line, a string, NaN, a negative or
absurd value) is ignored, never coerced. The worst of the last ``WINDOW`` samples is used, never the mean.

Read-only. Stdlib only. AUTHORITY: READ_ONLY_ADVISORY (no broker, no network, no DB).
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Iterable, Optional

SCHEMA = "ReleaseTrainDurations@v1"
KEYS = ("promote_s", "verify_s", "rollback_s")
#: Operator directive (Phase 7 prerequisites, 2026-10-22): refuse until three durations are measured.
MIN_SAMPLES = 3
#: The worst of the last WINDOW samples per key.
WINDOW = 10
#: A sample over an hour is a stuck run or a clock jump, not a duration to plan around.
MAX_SAMPLE_S = 3600.0
#: Read at most this many trailing lines of either file.
MAX_ROWS = 500

DEPLOY_STATE_DIR = Path.home() / ".local" / "state" / "cio-phase2-exact-main"
DEPLOY_HISTORY = DEPLOY_STATE_DIR / "deploy_receipt_history.jsonl"
DEPLOY_HISTORY_SCHEMA = "CioExactMainDeployReceiptHistory@v1"

#: deploy receipt mode -> the duration key it measures
_DEPLOY_MODE_KEY = {"promote": "promote_s", "rollback": "rollback_s"}


def _rows(path: Optional[Path]) -> tuple[list[dict], Optional[str]]:
    """(rows, error). A missing file is ``([], None)``: no history yet, which is UNMEASURED, not an error."""
    if path is None:
        return [], None
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()[-MAX_ROWS:]
    except FileNotFoundError:
        return [], None
    except (OSError, UnicodeError) as exc:
        return [], f"{path}: {type(exc).__name__}"
    out = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out, None


def valid_sample(v: Any) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    if not math.isfinite(f) or f <= 0 or f > MAX_SAMPLE_S:
        return None
    return f


def deploy_samples(rows: Iterable[dict]) -> list[dict]:
    """Deploy receipt history rows -> ``{"key", "value", "sha", "at", "source"}`` samples (successful only)."""
    out = []
    for r in rows:
        if r.get("schema") != DEPLOY_HISTORY_SCHEMA or r.get("ok") is not True:
            continue
        key = _DEPLOY_MODE_KEY.get(str(r.get("mode")))
        v = valid_sample(r.get("duration_s"))
        if key is None or v is None:
            continue
        out.append({"key": key, "value": v, "sha": r.get("sha"), "at": r.get("at"), "source": "deploy_receipt"})
    return out


def train_samples(rows: Iterable[dict]) -> list[dict]:
    """A train row's promote is keyed by the merged ``sha``; its rollback by ``rollback_sha`` (the target the deploy
    script's rollback receipt names), so the dedup in ``DurationHistory.samples`` matches the deploy row."""
    out = []
    for r in rows:
        for key in KEYS:
            v = valid_sample(r.get(key))
            if v is not None:
                sha = r.get("rollback_sha") if key == "rollback_s" else r.get("sha")
                out.append({"key": key, "value": v, "sha": sha, "at": r.get("at"), "source": "train"})
    return out


class DurationHistory:
    """The merged duration history. ``train_path`` is the controller's ``train_measurements.jsonl``;
    ``deploy_path`` the deploy receipt history (None to ignore it, e.g. in a hermetic test)."""

    def __init__(self, train_path: Optional[Path], deploy_path: Optional[Path] = DEPLOY_HISTORY, *,
                 min_samples: int = MIN_SAMPLES, window: int = WINDOW) -> None:
        self.train_path = Path(train_path) if train_path is not None else None
        self.deploy_path = Path(deploy_path) if deploy_path is not None else None
        self.min_samples, self.window = int(min_samples), int(window)

    def samples(self) -> tuple[list[dict], list[str]]:
        trows, terr = _rows(self.train_path)
        drows, derr = _rows(self.deploy_path)
        train = train_samples(trows)
        seen = {(s["key"], s["sha"]) for s in train if s.get("sha")}
        deploy = [s for s in deploy_samples(drows) if not (s.get("sha") and (s["key"], s["sha"]) in seen)]
        return train + deploy, [e for e in (terr, derr) if e]

    def summary(self) -> dict:
        """Per key: count, worst of the last ``window``, and whether it is measured (>= ``min_samples``)."""
        samples, errors = self.samples()
        per: dict[str, Any] = {}
        for key in KEYS:
            vals = [s["value"] for s in samples if s["key"] == key]
            recent = vals[-self.window:]
            per[key] = {"count": len(vals), "worst": max(recent) if recent else None,
                        "measured": len(vals) >= self.min_samples and not errors,
                        "sources": sorted({s["source"] for s in samples if s["key"] == key})}
        return {"schema": SCHEMA, "min_samples": self.min_samples, "window": self.window, "keys": per,
                "errors": errors, "train_path": str(self.train_path) if self.train_path else None,
                "deploy_path": str(self.deploy_path) if self.deploy_path else None}

    def worst_all(self) -> tuple[Optional[dict[str, float]], str]:
        """({key: worst}, why) when every key is measured; (None, why) otherwise — the caller refuses."""
        s = self.summary()
        if s["errors"]:
            return None, f"duration history unreadable: {'; '.join(s['errors'])}"
        short = [f"{k} {v['count']}/{self.min_samples}" for k, v in s["keys"].items() if not v["measured"]]
        if short:
            return None, (f"unmeasured: {', '.join(short)} (needs {self.min_samples} measured promote, verify and "
                          "rollback durations)")
        return {k: float(v["worst"]) for k, v in s["keys"].items()}, "measured"
