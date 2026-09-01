"""Notifications must be remembered: content in the key, bounded by time.

The operator's question was "if I saw it today and nothing changed, why am I
seeing it again?" Three defects answered it:

B1  build_dedupe_key returned a content hash ONLY for message_class == "checkin".
    Every other class fell through to identity parts including `wake_job_id` --
    a fresh id every run -- so an unchanged message keyed differently each time.
    That is the defect #567 was written to fix, still live for every other class.

B4  The durable content-keyed gate read `splitlines()[-500:]`. The file stood at
    429 lines: 71 sends from silently dropping its own history, after which a key
    older than 500 lines but younger than the TTL reads as "never sent".

B6  The research-lane alert keyed on the lane NAME with a 6h window. Eight lanes,
    independent staggered windows, all firing -- ~25 byte-identical messages in
    36 hours, because content was not in the key.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.cio_notification_outbox import build_dedupe_key  # noqa: E402


# ── B1 ────────────────────────────────────────────────────────────────────────

BASE = {"message_class": "decision", "decision_id": "dec_1", "body_hash": "aaa"}


def test_unchanged_content_keys_the_same_across_runs():
    """The regression: a fresh run id must not mint a new identity."""
    k1 = build_dedupe_key(dict(BASE, wake_job_id="run-1"))
    k2 = build_dedupe_key(dict(BASE, wake_job_id="run-2"))
    assert k1 == k2, "same content in two runs produced two keys"


def test_changed_content_keys_differently():
    """A genuinely new message must still notify."""
    k1 = build_dedupe_key(dict(BASE, wake_job_id="run-1"))
    k2 = build_dedupe_key(dict(BASE, wake_job_id="run-1", body_hash="bbb"))
    assert k1 != k2


def test_without_content_the_run_id_is_still_a_discriminator():
    """Guard the guard: the fix must not blind the key where there is no body."""
    no_body = {"message_class": "decision", "decision_id": "dec_1"}
    k1 = build_dedupe_key(dict(no_body, wake_job_id="run-1"))
    k2 = build_dedupe_key(dict(no_body, wake_job_id="run-2"))
    assert k1 != k2, "with no content to key on, the run id is the last resort"


def test_checkin_content_keying_still_works():
    a = build_dedupe_key({"message_class": "checkin", "body_hash": "x"})
    b = build_dedupe_key({"message_class": "checkin", "body_hash": "x"})
    c = build_dedupe_key({"message_class": "checkin", "body_hash": "y"})
    assert a == b and a != c


# ── B4 ────────────────────────────────────────────────────────────────────────

def test_dedupe_read_is_not_bounded_by_a_line_count():
    """Assert on CODE, not on the file text.

    The first version of this test grepped the whole source and failed on its own
    explanatory comment, which quotes the old expression. A detector that keys on
    "the string appears anywhere" cannot tell code from prose.
    """
    src = (ROOT / "scripts" / "lib" / "cio_telegram_transport.py").read_text(
        encoding="utf-8", errors="replace")
    code = [ln for ln in src.splitlines() if not ln.lstrip().startswith("#")]
    offending = [ln for ln in code if "splitlines()[-500:]" in ln]
    assert not offending, f"the line-count bound is back: {offending}"
    assert "_prune_expired" in src, "the file must be bounded by TTL instead"


def test_prune_drops_expired_and_keeps_live_entries(tmp_path):
    from scripts.lib.cio_telegram_transport import _prune_expired, DEDUPE_TTL_SECONDS
    p = tmp_path / "dedupe.jsonl"
    now = time.time()
    old = {"key": "old", "ts": now - DEDUPE_TTL_SECONDS - 60}
    new = {"key": "new", "ts": now}
    p.write_text(json.dumps(old) + "\n" + json.dumps(new) + "\n", encoding="utf-8")
    _prune_expired(p)
    kept = [json.loads(l)["key"] for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert kept == ["new"], f"expected only the live entry, got {kept}"


def test_prune_never_discards_an_unparseable_line(tmp_path):
    """A line we cannot read is not a line we may throw away."""
    from scripts.lib.cio_telegram_transport import _prune_expired
    p = tmp_path / "dedupe.jsonl"
    p.write_text("not json at all\n", encoding="utf-8")
    _prune_expired(p)
    assert "not json at all" in p.read_text(encoding="utf-8")


# ── B6 ────────────────────────────────────────────────────────────────────────

def test_health_alert_keys_on_content_not_just_lane():
    src = (ROOT / "scripts" / "research_lane_health.py").read_text(encoding="utf-8")
    assert 'sig = f"{lane}|{reasons}"' in src, "the key must include the firing reasons"
    assert '"signature": sig' in src, "the signature must be persisted to compare against"


def test_health_alert_body_carries_state_duration():
    src = (ROOT / "scripts" / "research_lane_health.py").read_text(encoding="utf-8")
    assert "state held" in src, "a repeat must say how long the state has held"
