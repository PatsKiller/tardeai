"""C3 — a swallowed alarm failure is a build failure.

An alarm whose failure is swallowed is worse than no alarm: it consumes the budget
of attention that would otherwise notice silence. `except Exception: pass` around an
alarm whose import could never resolve is exactly what hid a CRITICAL for 24 days
and STOP_HIT_CLOSE for 98.

The gate is a shrink-only baseline of named inherited debt, keyed by FILE rather
than line number -- a line-keyed baseline goes stale on the first unrelated edit
above it, and a stale baseline is a gate nobody trusts.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from alarm_swallow_scan import scan, DECLARED  # noqa: E402

BASELINE = ROOT / "config" / "alarm_swallow_baseline.txt"


def _baseline() -> dict[str, int]:
    out: dict[str, int] = {}
    for line in BASELINE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        path, _, n = line.rpartition(" ")
        out[path] = int(n)
    return out


def test_no_file_exceeds_its_baseline():
    current = Counter(r[0] for r in scan(ROOT / "scripts"))
    base = _baseline()
    regressions = []
    for path, n in sorted(current.items()):
        allowed = base.get(path, 0)
        if n > allowed:
            regressions.append(f"  {path}: {n} swallowing handlers, baseline {allowed}")
    assert not regressions, (
        "new swallowed alarm failures (the baseline may only shrink):\n"
        + "\n".join(regressions)
        + f"\n\nRecord the failure to a durable surface, or declare it with "
          f"'{DECLARED} <reason>' in the handler."
    )


def test_baseline_has_no_stale_entries():
    """A baseline that outlives its debt hides the next regression behind slack."""
    current = Counter(r[0] for r in scan(ROOT / "scripts"))
    stale = [f"  {p}: baseline {n}, actual {current.get(p, 0)}"
             for p, n in sorted(_baseline().items()) if current.get(p, 0) < n]
    assert not stale, (
        "baseline entries are larger than reality — lower them so the slack cannot "
        "absorb a future regression:\n" + "\n".join(stale)
    )


# ── the detector must be proven able to fail ─────────────────────────────────
def _write(d: Path, body: str) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    p = d / "probe.py"
    p.write_text(body)
    return p


def test_positive_control_pure_swallow_is_detected(tmp_path):
    """The exact shape that hid a CRITICAL for 24 days."""
    _write(tmp_path / "scripts", (
        "def f(msg):\n"
        "    try:\n"
        "        from telegram_alert import send_alert\n"
        "        send_alert(msg)\n"
        "    except Exception:\n"
        "        pass\n"
    ))
    rows = scan(tmp_path / "scripts")
    assert any(r[2] == "pure_swallow" for r in rows), rows


def test_positive_control_log_only_is_detected(tmp_path):
    """A log line is not a durable surface -- including when it formats with a helper.

    `log.error("...", type(exc).__name__)` was previously classified as "records",
    because descending into the log call's arguments counted `type(...)` as real
    work. That false negative hid seven handlers, one of them repaired in #787.
    """
    _write(tmp_path / "scripts", (
        "import logging\n"
        "log = logging.getLogger(__name__)\n"
        "def f(msg):\n"
        "    try:\n"
        "        send_telegram(msg)\n"
        "    except Exception as exc:\n"
        "        log.error('undelivered %s: %s', type(exc).__name__, msg)\n"
    ))
    rows = scan(tmp_path / "scripts")
    assert any(r[2] == "log_only" for r in rows), rows


def test_positive_control_a_recording_handler_is_not_flagged(tmp_path):
    """And it must not cry wolf, or the gate gets disabled."""
    _write(tmp_path / "scripts", (
        "def f(msg):\n"
        "    try:\n"
        "        send_telegram(msg)\n"
        "    except Exception as exc:\n"
        "        record_delivery_failure(msg, exc)\n"
        "        raise\n"
    ))
    assert scan(tmp_path / "scripts") == []


def test_positive_control_a_declaration_exempts(tmp_path):
    _write(tmp_path / "scripts", (
        "def f(msg):\n"
        "    try:\n"
        "        send_telegram(msg)\n"
        "    except Exception:\n"
        "        # ALARM-DELIVERY-DECLARED: best effort, caller re-checks delivery\n"
        "        pass\n"
    ))
    assert scan(tmp_path / "scripts") == []
