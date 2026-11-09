#!/usr/bin/env python3
"""disk_usage_monitor.py — disk-usage bands for the configured mounts, alerting once per band change.

Operator, 2026-10-18: "monitor when a threshold is over 80%, fix and move to n8n where monitored." n8n lane
``disk-usage-monitor`` (*/15, tradeai-dispatcher). Thresholds, mounts and consumer categories:
``config/disk_hygiene_rules.json`` ``monitor``.

Each run, per mount: used% as df prints it (used / (used + available): the root reserve is not "free" to a normal
writer; disk_pressure_guard.py learned this 2026-09-21), band = ok | warn (>= warn_pct) | critical (>= critical_pct).
A band CHANGE (ok->warn, warn->critical, critical->warn, warn/critical->ok) queues ONE host comms intent
(routes config/host_comms_intent_routes.json host/disk_usage_*), which the comms
intent consumer turns into an incident fan-in incident and the incident notifier sends (DIGEST -> P2). The intent is
queued through CommsIntentStore directly (:func:`queue_host_intent`, same rows/dedupe/cap as host_comms_intents): that
module's import closure reaches broker modules via the gateway, which an n8n lane must not
(tests/test_lane_transitive_capabilities_20261015.py). Staying in a
band sends nothing: dedupe is by band, never by the raw percent. A bounded hourly category snapshot is kept in
the existing state and receipt even when the band stays unchanged. Unknown/partial sizes stay explicit.
The intent carries the measured top consumers and the reclaimable estimate from the latest hygiene manifest.

INODES (operator 2026-10-19, after /tmp, a tmpfs, reached 97% inodes with 20G of bytes free and tools failed with
ENOSPC): every mount is also banded by inode use% (statvfs f_files / f_ffree; used = f_files - f_ffree) against
``monitor.inodes`` warn/critical, kept apart from the byte bands. State and dedupe are per (mount, metric): an inode
band change queues its own intent (subject "Disk <mount> INODES <BAND> ..."), which names the top dirs by file count
(bounded scan: depth <= monitor.inodes.top_dirs.max_depth, a time and entry cap) and the latest tmp_hygiene
manifest's reclaimable inodes. A filesystem reporting f_files = 0 has no inode limit and is not banded. This lane never sends, never deletes, never
calls a sender (the n8n never-list); the host P1 backstop is the systemd disk_pressure_guard (proposed at
monitor.host_backstop_pct, packet docs/ops/packets/disk-hygiene-n8n-20261018/), because n8n's own Postgres fails
when the disk is full.

    python3 scripts/disk_usage_monitor.py --dry-run     # measure and print; writes nothing, queues nothing
    python3 scripts/disk_usage_monitor.py --apply       # state file + intent on a band change + LaneRunReceipt

Exit: 0 = every mount measured and every due intent queued; 1 = rules unreadable, a mount unmeasurable, an intent
could not be queued (the band is NOT recorded, so the next run retries), or a write failed; 2 = usage.

MBI_BEHAVIOR = 0. No broker, no network, no Telegram import, no DB.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import disk_hygiene as DH  # noqa: E402
from scripts.lib import lane_last_receipt as R  # noqa: E402

# A locked coordination ledger is transient. Exit 69 (EX_UNAVAILABLE) is in transient-2's
# retryable_exit_codes, so the executor records RUN_FAILED exit_69 and the policy retries.
# Exit 75 is not usable here: disk-usage-monitor is lock_kind flock, and n8n_run_executor
# classifies child exit 75 as RUN_SKIPPED_LOCK/flock_held, which the policy marks skipped.
EX_UNAVAILABLE = 69
_BUSY_ATTEMPTS = 4
_BUSY_BACKOFF_S = (0.05, 0.1, 0.2)
_LEDGER_BUSY_REASONS = frozenset({"intent_store_unavailable"})

NO_CONSUMER_REASON = (
    "self-contained monitor: DiskUsageMonitorState@v1 is read back only by this script (band dedupe); results reach "
    "consumers via the LaneRunReceipt@v2 receipt and the host comms intent"
)
LANE_ID = "disk-usage-monitor"
SCRIPT = "scripts/disk_usage_monitor.py"
STATE_SCHEMA = "DiskUsageMonitorState@v1"
BANDS = ("ok", "warn", "critical")
SKIP_DEPENDENCY = "dependency_unavailable"
# Diagnostic work fits inside the existing 180s lane cap; these never widen it.
CONSUMER_REFRESH_SECONDS = 3600
CONSUMER_SCAN_BUDGET_SECONDS = 30
CONSUMER_PATH_MAX_SECONDS = 10
CONSUMER_RUN_DEADLINE_SECONDS = 120


def measure(mount: str) -> Optional[dict[str, Any]]:
    """df-style usage of ``mount``; None when statvfs fails."""
    try:
        st = os.statvfs(mount)
    except OSError:
        return None
    used = (st.f_blocks - st.f_bfree) * st.f_frsize
    avail = st.f_bavail * st.f_frsize
    reach = used + avail
    return {
        "mount": mount,
        "used_pct": round(used / reach * 100.0, 2) if reach else 0.0,
        "used_bytes": used,
        "avail_bytes": avail,
        "size_bytes": st.f_blocks * st.f_frsize,
    }


def measure_inodes(mount: str) -> Optional[dict[str, Any]]:
    """Inode use of ``mount`` (statvfs f_files / f_ffree); None when statvfs fails or the filesystem reports no inode
    limit (f_files == 0, e.g. btrfs)."""
    try:
        st = os.statvfs(mount)
    except OSError:
        return None
    if not st.f_files:
        return None
    used = st.f_files - st.f_ffree
    return {
        "mount": mount,
        "inodes_used_pct": round(used / st.f_files * 100.0, 2),
        "inodes_used": used,
        "inodes_total": st.f_files,
        "inodes_free": st.f_ffree,
        "avail_bytes": st.f_bavail * st.f_frsize,
    }


def top_file_dirs(mount: str, cfg: Mapping[str, Any]) -> dict[str, Any]:
    """The directories under ``mount`` holding the most files: one bounded walk (lstat only, never follows a symlink,
    never leaves the device; stops at cfg time_cap_s / max_entries) counts entries per path prefix up to max_depth;
    from each of the largest top-level dirs it descends while one child holds >= dominant_share of its parent's count
    (so /tmp/claude-1000/<project>/<session> is named when one session holds the files, and a dir whose files are
    spread is named itself). Returns {dirs: [(path, count)], scanned, partial}."""
    max_depth = max(1, min(3, int(cfg.get("max_depth") or 3)))
    share = float(cfg.get("dominant_share") or 0.5)
    deadline = time.monotonic() + float(cfg.get("time_cap_s") or 20)
    max_entries = int(cfg.get("max_entries") or 3_000_000)
    counts: dict[tuple, int] = {}
    try:
        dev = os.lstat(mount).st_dev
    except OSError:
        return {"dirs": [], "scanned": 0, "partial": True}
    stack: list[tuple[str, tuple]] = [(mount, ())]
    scanned, partial = 0, False
    while stack:
        if scanned >= max_entries or time.monotonic() > deadline:
            partial = True
            break
        d, key = stack.pop()
        try:
            it = os.scandir(d)
        except OSError:
            continue
        with it:
            for e in it:
                scanned += 1
                k = key if len(key) >= max_depth else key + (e.name,)
                for i in range(1, len(k) + 1):
                    counts[k[:i]] = counts.get(k[:i], 0) + 1
                try:
                    if e.is_dir(follow_symlinks=False) and e.stat(follow_symlinks=False).st_dev == dev:
                        stack.append((e.path, k))
                except OSError:
                    continue
    kids: dict[tuple, list[tuple]] = {}
    for k in counts:
        if len(k) > 1:
            kids.setdefault(k[:-1], []).append(k)
    picked = []
    for top in sorted((k for k in counts if len(k) == 1), key=lambda k: -counts[k])[: int(cfg.get("top_n") or 3)]:
        cur = top
        while len(cur) < max_depth and kids.get(cur):
            best = max(kids[cur], key=lambda k: counts[k])
            if counts[best] < share * counts[cur]:
                break
            cur = best
        picked.append((os.path.join(mount, *cur), counts[cur]))
    return {"dirs": sorted(picked, key=lambda kv: -kv[1]), "scanned": scanned, "partial": partial}


def band_of(pct: float, mon: Mapping[str, Any]) -> str:
    if pct >= float(mon["critical_pct"]):
        return "critical"
    if pct >= float(mon["warn_pct"]):
        return "warn"
    return "ok"


def transition(prev: Optional[str], cur: str) -> Optional[str]:
    """The alert a band change calls for: the new band's name, or None (no change, or a first run at ok)."""
    if prev == cur:
        return None
    if prev in (None, "ok") and cur == "ok":
        return None
    return cur


_INHERITED_SETTINGS = ("realert_minutes", "warn_pct", "critical_pct")


def metric_policy(mon: Mapping[str, Any], band: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    """The effective settings for ONE band. A band inherits every inherited setting from its parent monitor and may
    override it — it cannot MISS one.

    2026-11-04 (cx-openai-4): `monitor.inodes` never carried `realert_minutes`, so the inode band alerted on first
    entry and then said nothing for as long as it stayed bad — the same 23-hour silence this change exists to end,
    still present on the second band. Resolving every band through this ONE function is what makes a third band
    inherit by construction: there is no path that reads a band's own dict for these settings.
    """
    if not isinstance(mon, Mapping) or "realert_minutes" not in mon:
        raise ValueError("monitor.realert_minutes is required: a band with no re-alert interval is a one-shot")
    merged = dict(mon)
    merged.update({k: v for k, v in dict(band or {}).items() if k in _INHERITED_SETTINGS})
    return merged


def _minutes_since(stamp: Any, now: datetime) -> Optional[float]:
    """Minutes from an ISO stamp to now; None when there is no usable stamp."""
    if not stamp:
        return None
    try:
        then = datetime.fromisoformat(str(stamp))
    except ValueError:
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    elapsed = (now - then).total_seconds() / 60.0
    # A stamp in the FUTURE is a clock correction, not a reason to stay silent (cx-openai-4 R2): a run that really
    # happened under a skewed clock left a stamp ahead of now, and treating the negative elapsed as "not due" made an
    # ongoing critical band emit nothing for 25 hours — the exact defect this PR exists to fix. Unknown timing is
    # reported as unknown, and every caller treats unknown as DUE.
    return None if elapsed < 0 else elapsed


def _minutes_since_last_alert(entry: Mapping[str, Any], now: datetime) -> Optional[float]:
    return _minutes_since(entry.get("alerted_at"), now)


def alert_for(prev: Optional[str], cur: str, entry: Mapping[str, Any], now: datetime,
              mon: Mapping[str, Any]) -> Optional[str]:
    """One decision point, ONE clock, ONE named exception, and a PENDING state that is not lost.

    Four measured defects shaped it, all 2026-11-04:
    * alerting only on a band CHANGE let `/` sit critical for 23 hours on a single alert;
    * throttling only the unchanged path let an ok<->critical flap produce 96 alerts in 24 hours;
    * letting a recovery OR ANY severity increase bypass the interval produced 65 alerts in 24 hours against a promise
      of 25 (`critical,critical,ok` repeated: each recovery reset the clock, so the next critical called itself an
      escalation);
    * comparing against the PREVIOUSLY OBSERVED band DISCARDED a recovery: the run records `band = ok` every poll, so a
      recovery throttled at +75 made every later poll look "unchanged ok" and it was never sent. The last REPORTED
      band stayed critical and was ignored.

    The comparison is against the band last REPORTED (`alerted_band`), not the band last seen. Inside the window
    nothing is said and the pending state is kept, so it goes out the moment the interval allows — delayed, never
    discarded.

    WARN -> CRITICAL IS THE ONE EXCEPTION (cc-deepseek-2's measurement, cx-openai-4 R6). A blanket interval made the
    escalation itself silent: a mount at 85% is reported WARN, crosses 90% at the next poll, and the operator heard
    nothing for a full interval — 45 minutes at the shipped 15-minute poll and 60-minute interval, long enough for the
    mount to reach 100%, and the ledger this lane writes lives on that mount. "You were told it is bad, now it is
    worse" is not a restatement and must not wait.

    It is narrow on purpose, and the narrowness is what keeps the bound: the bypass needs `alerted_band == "warn"`
    exactly, and delivering it sets `alerted_band = "critical"`, so every later critical is a REPEAT and stays
    interval-gated, and a re-cross after a recovery is interval-gated too because only a *reported* recovery can set
    the band back. Measured over 24 h at 15-minute polls: 24-25 on two- and four-band cycles, and **up to 33 on a
    three-band cycle** (`warn,critical,ok` repeating every 45 minutes), because such a cycle pays a warn, an escalation
    and a recovery every 90 minutes and neither the escalation nor the recovery may be suppressed. That is the stated
    ceiling and the reason for it (cc-deepseek-5's re-read, 2026-11-04); a promise of 25 on every shape would require
    dropping one of those two guarantees.

    `prev` is kept for call-site symmetry and is deliberately NOT consulted: only the last REPORTED band decides.
    """
    interval = float(mon["realert_minutes"])       # metric_policy guarantees it; a band cannot miss it
    reported = str(entry.get("alerted_band") or "")
    if reported == "warn" and cur == "critical":
        return cur      # escalation: said now, not at the end of the window (see above; bounded by construction)
    since = _minutes_since_last_alert(entry, now)
    if since is not None and since < interval:
        return None                                 # inside the window: silence, and the pending state is retained
    if cur == "ok":
        # A recovery is owed only if something bad was actually reported; an all-quiet mount says nothing.
        return "ok" if reported and reported != "ok" else None
    return cur                                      # due, and the band is bad: say it (restated or newly reached)


def latest_manifest(rules: Mapping[str, Any], state_root: Optional[Path]) -> Optional[dict[str, Any]]:
    try:
        p = DH.manifest_dir(rules, state_root) / rules["manifest"]["latest_name"]
        m = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError):
        return None
    t = m.get("totals") or {}
    return {
        "generated_at": m.get("generated_at"),
        "candidates": t.get("candidates"),
        "reclaimable_bytes": t.get("reclaimable_bytes"),
        "by_kind": t.get("by_kind"),
    }


GIB = 1024 ** 3


def latest_budget_report(rules: Mapping[str, Any], state_root: Optional[Path]) -> Optional[list]:
    """The lane's per-root budget report (``budget_report``) from the latest manifest, or None.

    Only the LANE can measure the roots it owns, and it already does so while planning; reading its own measurement
    keeps the monitor from running a second ``du`` over 91 GiB. A report that is absent is not an empty one: the
    caller measures those roots itself and never reads "no report" as "under cap".
    """
    try:
        p = DH.manifest_dir(rules, state_root) / rules["manifest"]["latest_name"]
        m = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError):
        return None
    rows = m.get("budget_report")
    return rows if isinstance(rows, list) else None


def latest_tmp_rows(rules: Mapping[str, Any], state_root: Optional[Path]) -> Optional[list]:
    """Every row (candidate and excluded) of the latest tmp_hygiene manifest, or None.

    The tmp lane owns /tmp/claude-1000; the monitor reads its measurement rather than walking that tree itself.
    Two walkers of the same tree disagree the moment one of them is a poll behind, and a second ``du`` over a tmpfs
    full of session scratch is exactly the load this lane is meant to observe, not add to.
    """
    try:
        p = DH.manifest_dir(rules, state_root) / rules["tmp"]["manifest_latest_name"]
        m = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError, TypeError):
        return None
    rows = m.get("items")
    rows = list(rows) if isinstance(rows, list) else []
    excluded = m.get("excluded")
    rows += list(excluded) if isinstance(excluded, list) else []
    return rows


def budget_measurements(rules: Mapping[str, Any], lane_rows: Optional[list],
                        tmp_rows: Optional[list] = None) -> list[dict[str, Any]]:
    """One row per configured budget root: ABSOLUTE bytes against its cap, never a share of the mount.

    The numbers come from the lanes that own each tree — ``budget_report`` for the standing lane's roots, the tmp
    lane's manifest for /tmp/claude-1000 — so the monitor never walks a tree twice. A root no lane measured is
    ``unmeasured``: it is never coerced to 0, because a zero would read as a healthy root that simply holds nothing.
    """
    lane = {}
    for e in lane_rows or []:
        if isinstance(e, dict) and e.get("root"):
            lane[str(e["root"])] = e
    out: list[dict[str, Any]] = []
    for root in rules.get("_budget_roots") or []:
        name = str(root.get("name") or "")
        path = Path(str(root.get("_path") or root.get("path")))
        base = os.path.normpath(str(path))
        cap = int(float(root.get("max_total_gb") or 0) * GIB)
        e = lane.get(name) or {}
        measured = e.get("measured_bytes") if e.get("status") not in (None, "no_rows") else None
        source = "lane_manifest" if measured is not None else None
        partial = False
        if measured is None and "tmp" in (root.get("rules") or []) and tmp_rows is not None:
            total = 0
            seen = False
            for r in tmp_rows:
                if not isinstance(r, dict):
                    continue
                rp = os.path.normpath(str(r.get("path") or ""))
                if not (rp == base or rp.startswith(base + os.sep)):
                    continue
                seen = True
                v = r.get("size_bytes")
                if isinstance(v, int) and v >= 0:
                    total += v
                elif r.get("candidate") is not True:
                    partial = True  # a held row we could not weigh: the total is a floor, not the measurement
            if seen:
                measured = total
                source = "tmp_manifest"
        floor = e.get("floor_bytes") if isinstance(e.get("floor_bytes"), int) else None
        row: dict[str, Any] = {
            "root": name, "path": str(path), "cap_bytes": cap, "measured_bytes": measured,
            "measured_gb": round(measured / GIB, 2) if isinstance(measured, int) else None,
            "cap_gb": round(cap / GIB, 2), "source": source, "partial": partial,
            "floor_bytes": floor,
            "floor_exceeds_cap": bool(e.get("floor_exceeds_cap") is True),
            "over_max_age": e.get("over_max_age"),
        }
        if isinstance(measured, int):
            row["over_bytes"] = max(0, measured - cap)
            row["status"] = "over_cap" if measured > cap else "under_cap"
        else:
            row["over_bytes"] = None
            row["status"] = "unmeasured"
        out.append(row)
    return out


def budget_samples(previous: Any, rows: list[dict[str, Any]], now: datetime,
                   growth: Mapping[str, Any]) -> dict[str, list[list[Any]]]:
    """Append this poll's measurement per root; keep the window and a hard cap on stored samples.

    The samples are the only input to the growth rate, so an unmeasured root contributes nothing (its old samples
    stay, and the rate is computed over whatever real readings exist inside the window)."""
    window_days = float(growth.get("window_days") or 3)
    keep_max = int(growth.get("max_samples_per_root") or 96)
    cutoff = now.timestamp() - window_days * 86400.0
    out: dict[str, list[list[Any]]] = {}
    for key, series in (previous or {}).items() if isinstance(previous, dict) else []:
        if isinstance(series, list):
            out[str(key)] = [s for s in series if isinstance(s, list) and len(s) == 2 and isinstance(s[1], int)
                             and isinstance(s[0], (int, float)) and float(s[0]) >= cutoff][-keep_max:]
    for row in rows:
        if not isinstance(row.get("measured_bytes"), int):
            continue  # unmeasured is not a reading
        series = out.setdefault(str(row["root"]), [])
        series.append([now.timestamp(), row["measured_bytes"]])
        out[str(row["root"])] = series[-keep_max:]
    return out


def growth_gb_per_day(series: Any, now: datetime, growth: Mapping[str, Any]) -> Optional[float]:
    """GiB/day over the samples inside the window, or None when the window holds too few to date a rate."""
    if not isinstance(series, list):
        return None
    min_samples = int(growth.get("min_samples") or 3)
    window_days = float(growth.get("window_days") or 3)
    cutoff = now.timestamp() - window_days * 86400.0
    pts = sorted((float(s[0]), s[1]) for s in series if isinstance(s, list) and len(s) == 2
                 and isinstance(s[0], (int, float)) and isinstance(s[1], int) and float(s[0]) >= cutoff)
    if len(pts) < min_samples:
        return None
    span_days = (pts[-1][0] - pts[0][0]) / 86400.0
    if span_days <= 0:
        return None
    return round((pts[-1][1] - pts[0][1]) / GIB / span_days, 3)


def budget_findings(rows: list[dict[str, Any]], samples: Mapping[str, Any], now: datetime,
                    growth: Mapping[str, Any]) -> list[dict[str, Any]]:
    """What each root's budget says, with the band the alert dedupe uses.

    over a cap (or over the cap-floor it cannot cross) is ``critical`` — the operator named a number and the host is
    past it. A growth rate above the ceiling is ``warn`` — the root may still be under its cap today, which is exactly
    the state the used% bands are blind to. ``unmeasured`` carries band None so it can never be mistaken for ok.
    """
    ceiling = float(growth.get("max_gb_per_day") or 0)
    out = []
    for row in rows:
        rate = growth_gb_per_day(samples.get(str(row.get("root"))), now, growth)
        row = dict(row)
        row["growth_gb_per_day"] = rate
        if row.get("status") == "unmeasured":
            row["band"] = None
            row["why"] = "unmeasured"
        elif row.get("over_bytes", 0) > 0 or row.get("floor_exceeds_cap"):
            row["band"] = "critical"
            row["why"] = "over_cap"
        elif rate is not None and ceiling > 0 and rate > ceiling:
            row["band"] = "warn"
            row["why"] = "growth_rate"
        else:
            row["band"] = "ok"
            row["why"] = None
        out.append(row)
    return out


def budget_intent_text(finding: Mapping[str, Any]) -> tuple[str, str]:
    """Subject and summary for one root's budget alert, in the operator's own units (GiB, GiB/day).

    The summary names the cap, the measurement, the bytes that must come off, and — when the cap cannot be reached
    without touching held work — how much is held and why. "Still over cap" with no number is what the lane used to
    say by saying nothing."""
    name = finding.get("root")
    measured = finding.get("measured_gb")
    cap = finding.get("cap_gb")
    if finding.get("why") == "growth_rate":
        subject = f"Disk growth {name}: {finding.get('growth_gb_per_day')} GiB/day"
        text = (f"{name} ({finding.get('path')}) grew {finding.get('growth_gb_per_day')} GiB/day over the window; "
                f"now {measured} GiB of a {cap} GiB budget. Growth is alerted independently of used%.")
        return subject, text
    subject = f"Disk budget exceeded {name}: {measured} GiB of {cap} GiB"
    over = round((finding.get("over_bytes") or 0) / GIB, 2)
    text = (f"{name} ({finding.get('path')}) holds {measured} GiB against an absolute {cap} GiB cap: {over} GiB "
            f"must come off. Reclaimable under the reviewed rules is taken oldest-first first.")
    if finding.get("floor_exceeds_cap"):
        floor = finding.get("floor_bytes")
        floor_gb = round(floor / GIB, 2) if isinstance(floor, int) else None
        text += (f" The PROTECTED floor alone is {floor_gb} GiB, so the cap cannot be met by evicting eligible work: "
                 f"live claims, running processes, unmeasured or never-touch trees hold the rest. Escalated for a "
                 f"human decision — nothing protected was touched.")
    age = finding.get("over_max_age") or {}
    if age.get("count"):
        text += (f" {age['count']} held entr(y/ies) ({round((age.get('bytes') or 0) / GIB, 2)} GiB) are older than "
                 f"{age.get('max_item_age_days')} days; held by: {', '.join(age.get('reasons') or []) or 'unknown'}.")
    return subject, text


def budget_alert_policy(mon: Mapping[str, Any], budget_cfg: Optional[Mapping[str, Any]]) -> Mapping[str, Any]:
    """The band machine, with the budget's own (slower) re-alert clock when one is configured.

    A budget breach is a structural condition (live sessions hold a scratch floor), not a mount filling up inside one
    interval, so repeating it every mount `realert_minutes` would be noise. The escalation and recovery paths are
    unchanged: "worse" and "fixed" are still said at once.
    """
    br = (budget_cfg or {}).get("realert_minutes")
    if type(br) in (int, float) and br > 0:
        return {**mon, "realert_minutes": float(br)}
    return mon


def latest_tmp_manifest(rules: Mapping[str, Any], state_root: Optional[Path]) -> Optional[dict[str, Any]]:
    """Totals of the latest tmp_hygiene manifest (DiskHygieneManifest@v1, scope tmp), or None."""
    try:
        p = DH.manifest_dir(rules, state_root) / rules["tmp"]["manifest_latest_name"]
        m = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if m.get("scope") != "tmp":
        return None
    t = m.get("totals") or {}
    return {
        "generated_at": m.get("generated_at"),
        "candidates": t.get("candidates"),
        "reclaimable_bytes": t.get("reclaimable_bytes"),
        "reclaimable_files": t.get("reclaimable_files"),
    }


def _consumer_config_digest(mon: Mapping[str, Any]) -> str:
    raw = json.dumps(mon.get("consumer_categories") or [], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def consumer_snapshot_due(snapshot: Any, mon: Mapping[str, Any], now: datetime) -> bool:
    """Legacy, malformed, changed-config, future and expired snapshots are not prior measurements."""
    if not isinstance(snapshot, dict) or type(snapshot.get("version")) is not int or snapshot["version"] != 1:
        return True
    if snapshot.get("config_digest") != _consumer_config_digest(mon) or not isinstance(snapshot.get("categories"), list):
        return True
    for row in snapshot["categories"]:
        if not isinstance(row, dict) or row.get("status") not in {"measured", "partial", "unknown"}:
            return True
        if not isinstance(row.get("category"), str) or "bytes" not in row or type(row.get("known_bytes")) is not int or row["known_bytes"] < 0:
            return True
        paths = row.get("paths")
        if not isinstance(paths, list) or not paths:
            return True
        for p in paths:
            if not isinstance(p, dict) or p.get("status") not in {"measured", "unavailable", "budget_exhausted"}:
                return True
            if p["status"] == "measured":
                if type(p.get("bytes")) is not int or p["bytes"] < 0:
                    return True
            elif p.get("bytes") is not None:
                return True
        good = sum(p["status"] == "measured" for p in paths)
        expected_status = "measured" if good == len(paths) else "partial" if good else "unknown"
        if row["status"] != expected_status or row["known_bytes"] != sum(p["bytes"] for p in paths if p["status"] == "measured"):
            return True
        if row["status"] == "measured":
            if type(row.get("bytes")) is not int or row["bytes"] != row["known_bytes"]:
                return True
        elif row.get("bytes") is not None:
            return True
    expected = {c["category"] for c in mon.get("consumer_categories") or []}
    if len(snapshot["categories"]) != len(expected) or {r["category"] for r in snapshot["categories"]} != expected:
        return True
    try:
        captured = datetime.fromisoformat(snapshot["captured_at"])
        age = (now - captured).total_seconds()
    except (KeyError, TypeError, ValueError):
        return True
    return not 0 <= age < CONSUMER_REFRESH_SECONDS


def collect_consumer_snapshot(
    rules: Mapping[str, Any], mon: Mapping[str, Any], now: datetime, *, deadline: Optional[float] = None,
) -> dict[str, Any]:
    """One shared bounded capture, including failed/unstarted paths and partial category totals."""
    started = time.monotonic()
    deadline = min(started + CONSUMER_SCAN_BUDGET_SECONDS, deadline if deadline is not None else float("inf"))
    paths = list(mon.get("consumer_categories") or [])
    categories: dict[str, dict[str, Any]] = {}
    for i, c in enumerate(paths):
        row = categories.setdefault(c["category"], {"category": c["category"], "known_bytes": 0, "paths": []})
        p = DH._expand(str(c["path"]), rules["_home"])
        remaining = deadline - time.monotonic()
        measured, status = None, "budget_exhausted"
        if remaining > 0:
            timeout = max(0.0, min(float(mon.get("du_timeout_s", 60)), CONSUMER_PATH_MAX_SECONDS,
                                   remaining / (len(paths) - i)))
            try:
                p.lstat()
                if timeout > 0:
                    measured = DH.du_bytes(p, timeout)
                    status = "measured" if type(measured) is int and measured >= 0 else "unavailable"
            except OSError:
                status = "unavailable"
        if status == "measured":
            row["known_bytes"] += measured
        else:
            measured = None
        row["paths"].append({"path": str(p), "bytes": measured, "status": status})
    for row in categories.values():
        good = sum(p["status"] == "measured" for p in row["paths"])
        row["status"] = "measured" if good == len(row["paths"]) else "partial" if good else "unknown"
        row["bytes"] = row["known_bytes"] if row["status"] == "measured" else None
    elapsed = max(0.0, time.monotonic() - started)
    # Internal nested monitor state, read by consumer_snapshot_due/top_consumers;
    # no separate store or authoritative contract is introduced.
    return {"version": 1, "captured_at": now.isoformat(),
            "finished_at": (now + timedelta(seconds=elapsed)).isoformat(),
            "elapsed_seconds": round(elapsed, 3), "budget_seconds": max(0.0, deadline - started),
            "config_digest": _consumer_config_digest(mon), "categories": list(categories.values()),
            "complete": all(r["status"] == "measured" for r in categories.values())}


def top_consumers(
    rules: Mapping[str, Any], mon: Mapping[str, Any], manifest: Optional[Mapping[str, Any]],
    snapshot: Optional[Mapping[str, Any]] = None,
) -> list:
    """Rank complete measurements; keep every unknown category outside the ranking cap."""
    snapshot = snapshot if snapshot is not None else collect_consumer_snapshot(rules, mon, datetime.now(timezone.utc))
    sizes = {r["category"]: r["bytes"] for r in snapshot["categories"]}
    if manifest and manifest.get("by_kind"):
        git = sum(v.get("bytes") or 0 for k, v in manifest["by_kind"].items() if k.startswith("G:"))
        if git:
            sizes["git_trees_reclaimable"] = git
    known = sorted(((c, b) for c, b in sizes.items() if b is not None), key=lambda kv: -kv[1])
    unknown = sorted((c, b) for c, b in sizes.items() if b is None)
    return known[: int(mon.get("top_consumers") or 5)] + unknown


def _gb(n: Optional[int]) -> str:
    return f"{(n or 0) / 1024**3:.1f}G"


def intent_text(
    m: Mapping[str, Any], band: str, mon: Mapping[str, Any], consumers: list, manifest: Optional[Mapping[str, Any]],
    consumer_captured_at: Optional[str] = None,
) -> tuple[str, str]:
    """(subject, summary). The subject is band-stable (no percent) so the store's own dedupe agrees with ours."""
    mount = m["mount"]
    if band == "ok":
        subject = f"Disk {mount} recovered: below {float(mon['warn_pct']):.0f}% used"
    else:
        thr = float(mon["critical_pct"] if band == "critical" else mon["warn_pct"])
        subject = f"Disk {mount} {band.upper()}: at or above {thr:.0f}% used"
    parts = [f"{m['used_pct']:.1f}% used, {_gb(m['avail_bytes'])} free of {_gb(m['size_bytes'])}"]
    unknown = [c for c, b in consumers if b is None]
    known = [(c, b) for c, b in consumers if b is not None]
    if unknown:
        parts.append("unmeasured: " + ", ".join(unknown))
    if known:
        parts.append("top: " + ", ".join(f"{c} {_gb(b)}" for c, b in known))
    if consumer_captured_at:
        parts.append("category sizes as of " + consumer_captured_at)
    if manifest and manifest.get("reclaimable_bytes") is not None:
        parts.append(
            f"reclaimable {_gb(manifest['reclaimable_bytes'])} in {manifest.get('candidates')} items per hygiene"
            f" manifest {str(manifest.get('generated_at') or '')[:16]} (apply is operator-gated)"
        )
    else:
        parts.append("no hygiene manifest yet")
    return subject, "; ".join(parts)


def _kfiles(n: Optional[int]) -> str:
    n = n or 0
    return f"{n / 1e6:.2f}M" if n >= 1_000_000 else f"{n / 1000:.0f}k" if n >= 1000 else str(n)


def _short(path: str, mount: str) -> str:
    """``path`` relative to ``mount`` (the subject names the mount) with long components clipped, so three dirs fit
    the 300-char summary."""
    rel = os.path.relpath(path, mount)
    parts = [p if len(p) <= 18 else p[:8] + "…" + p[-6:] for p in Path(rel).parts]
    return os.path.join(*parts) if parts else "."


def inode_intent_text(
    m: Mapping[str, Any],
    band: str,
    ino: Mapping[str, Any],
    top: Optional[Mapping[str, Any]],
    tmp_manifest: Optional[Mapping[str, Any]],
) -> tuple[str, str]:
    """(subject, summary) for an inode band change. The subject is band-stable and names INODES, so the store's
    (domain, kind, subject) dedupe never merges it with the byte alert of the same mount."""
    mount = m["mount"]
    if band == "ok":
        subject = f"Disk {mount} INODES recovered: below {float(ino['warn_pct']):.0f}% inodes used"
    else:
        thr = float(ino["critical_pct"] if band == "critical" else ino["warn_pct"])
        subject = f"Disk {mount} INODES {band.upper()}: at or above {thr:.0f}% inodes used"
    parts = [
        f"{m['inodes_used_pct']:.1f}% inodes used ({_kfiles(m['inodes_used'])} of {_kfiles(m['inodes_total'])}),"
        f" {_gb(m.get('avail_bytes'))} bytes free"
    ]
    if top and top.get("dirs"):
        parts.append(
            "top files: "
            + ", ".join(f"{_short(p, mount)} {_kfiles(n)}" for p, n in top["dirs"])
            + (" (partial scan)" if top.get("partial") else "")
        )
    if tmp_manifest and tmp_manifest.get("reclaimable_files") is not None:
        parts.append(
            f"tmp plan {str(tmp_manifest.get('generated_at') or '')[:16]}: {tmp_manifest.get('candidates')} items,"
            f" {_kfiles(tmp_manifest['reclaimable_files'])} files reclaimable (apply is operator-gated)"
        )
    return subject, "; ".join(parts)


def _execution_id(now: datetime) -> str:
    rid = os.environ.get("TRADEAI_RUN_ID") or f"manual-{now.strftime('%Y%m%dT%H%M%S')}"
    return re.sub(r"[^A-Za-z0-9_-]", "-", rid)[-40:]


class HostIntentError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def default_ledger_path(environ: Optional[Mapping[str, str]] = None) -> Path:
    """Same resolution as scripts/n8n_coordination_gateway.default_ledger_path (not imported: see queue_host_intent)."""
    source = environ if environ is not None else os.environ
    explicit = source.get("TRADEAI_N8N_COORDINATION_LEDGER")
    if explicit:
        return Path(explicit)
    root = source.get("TRADEAI_STATE_ROOT") or str(Path.home() / "trade-ai-releases" / "persistent-state")
    return Path(root) / "data" / "governance" / "n8n_coordination_ledger.sqlite"


class _LedgerConn:
    """The two attributes CommsIntentStore uses (``_conn``, ``lock``) on a plain sqlite connection to an EXISTING
    ledger. Same rows, dedupe and cap as scripts/lib/host_comms_intents.queue_intent, whose import closure (via
    scripts/n8n_coordination_gateway.py) reaches broker modules — an n8n-allowlisted lane must not
    (tests/test_lane_transitive_capabilities_20261015.py), so this lane talks to the store directly. Mirrors
    scripts/check_registry_runtime_truth.py."""

    read_only = False

    def __init__(self, path: Path) -> None:
        import sqlite3
        import threading

        self.lock = threading.RLock()  # CommsIntentStore re-enters it (accept -> _receipt -> get)
        self._conn = sqlite3.connect(str(path), timeout=10, isolation_level=None)
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self._conn.close()


def queue_host_intent(
    *,
    producer: str,
    domain: str,
    kind: str,
    subject: str,
    summary: str,
    execution_id: str,
    node: str,
    ledger_path: Optional[Path],
    now: Optional[float] = None,
) -> dict[str, Any]:
    """Queue one host comms intent (never a send). Raises HostIntentError(<reason>) with host_comms_intents' reasons:
    producer_refused, intent_unrouted, intent_rate_limited, intent_routes_unreadable, malformed_event, ledger_absent
    (the consumer and gateway create the ledger; a lane never does), intent_store_unavailable."""
    import sqlite3
    import time

    from scripts.lib.n8n_fabric_store import (
        PRODUCER_RE,
        SUBJECT_MAX,
        SUMMARY_MAX,
        CommsIntentStore,
        FabricStoreError,
        load_host_intent_routes,
        load_intent_routes,
        merged_intent_routes,
    )

    if not PRODUCER_RE.fullmatch(producer):
        raise HostIntentError("producer_refused")
    try:
        hosts = load_host_intent_routes()
        routes = merged_intent_routes(load_intent_routes(), hosts)
    except FabricStoreError as exc:
        raise HostIntentError(getattr(exc, "reason", "intent_routes_unreadable")) from exc
    route = hosts["routes"].get((domain, kind))
    if route is None:
        raise HostIntentError("intent_unrouted")
    if route.get("producer") != producer:
        raise HostIntentError("producer_refused")
    path = Path(ledger_path) if ledger_path is not None else default_ledger_path()
    if not path.exists():
        raise HostIntentError("ledger_absent")

    def clean(text: Any, limit: int) -> str:
        flat = " ".join("".join(" " if ord(ch) < 32 or ord(ch) == 127 else ch for ch in str(text or "")).split())
        return flat if len(flat) <= limit else flat[: max(0, limit - 1)] + "…"

    request = {
        "domain": domain,
        "kind": kind,
        "subject": clean(subject, SUBJECT_MAX),
        "summary": clean(summary, SUMMARY_MAX),
        "workflow_id": f"host.{producer}",
        "execution_id": str(execution_id)[:40],
        "node": clean(node, 64),
    }
    stamp = time.time() if now is None else now
    last: BaseException | None = None
    for attempt in range(_BUSY_ATTEMPTS):
        if attempt:
            time.sleep(_BUSY_BACKOFF_S[min(attempt - 1, len(_BUSY_BACKOFF_S) - 1)])
        ledger = None
        try:
            ledger = _LedgerConn(path)
            store = CommsIntentStore(ledger, routes=routes)
            return dict(store.accept(request, caller_id=f"host:{producer}", now=stamp))
        except FabricStoreError as exc:
            raise HostIntentError(getattr(exc, "reason", "intent_store_unavailable")) from exc
        except (sqlite3.Error, OSError) as exc:
            last = exc
            if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
                raise HostIntentError("intent_store_unavailable") from exc
        finally:
            if ledger is not None:
                ledger.close()
    raise HostIntentError("intent_store_unavailable") from last


def standing_hygiene_status(rules: Mapping, state_root: Optional[Path], previous: Mapping, now: datetime,
                            used_pct: Optional[float]) -> dict:
    """Read the optional hygiene receipt; never run cleanup or send directly.

    Only distinct manifest runs advance the held-byte streak. Missing/future or
    malformed receipts are not proof of a successful hygiene run.

    ONE UNUSABLE RECEIPT MUST NOT BLIND THE DIRECTORY (LQ-20261107-1527). Until this fix the
    loop returned on the FIRST bad file, so a single refused run on 2026-11-05 that wrote
    `run_id: null` made every later poll answer `invalid_receipt`. The monitor's own
    disk-hygiene reporting went dead with it: `disk_hygiene_digest` / `disk_hygiene_alert`
    queued nothing between 2026-11-02T15:45 and this fix — 61 distinct unseen runs — while
    `/` sat in the critical band at 92.9%. An unusable receipt is now SKIPPED and counted in
    `skipped_unusable`; `invalid_receipt` is returned only when files exist and not one of
    them is usable, which is the only state that means the directory cannot be read at all.

    A report older than the freshness bound is not news. The monitor polls every 15 minutes,
    so a real run is read long before the bound; anything past it was missed by an outage or
    by the fault above, and re-dialling a week of digests is noise, not reporting. Those are
    counted in `stale_skipped` and never queued. The bound is
    `standing_apply.monitor.max_report_age_hours` when set, else the already-reviewed
    `standing_apply.manifest_max_age_hours` — no new operator value is introduced.
    """
    if not isinstance(rules.get("standing_apply"), dict):
        return {"status": "not_configured"}
    cfg = rules["standing_apply"]
    max_age_h = (cfg.get("monitor") or {}).get("max_report_age_hours") or cfg.get("manifest_max_age_hours")
    max_age_h = float(max_age_h) if max_age_h else None
    reports = []
    usable = invalid = stale = 0
    directory = DH.manifest_dir(rules, state_root)
    for path in sorted(directory.glob("disk_hygiene_standing_apply_*.json")):
        try:
            report = json.loads(path.read_text())
        except (OSError, ValueError):
            invalid += 1          # unreadable: not evidence of a run, and not a reason to drop the rest
            continue
        if not isinstance(report, dict) or not report.get("run_id"):
            invalid += 1
            continue
        finished = DH.SR.aware(report.get("finished_at"))
        if finished is None or finished > now:
            invalid += 1
            continue
        usable += 1
        if report["run_id"] in previous.get("seen_run_ids", []) or report["run_id"] == previous.get("run_id"):
            continue                      # already reported; an old one is not "skipped", it was read
        if max_age_h is not None and (now - finished).total_seconds() > max_age_h * 3600:
            stale += 1
            continue
        reports.append(report)
    counts = {k: v for k, v in (("skipped_unusable", invalid), ("stale_skipped", stale)) if v}
    if not usable and invalid:
        return {"status": "invalid_receipt", **counts}
    if not reports:
        return {"status": "already_observed" if previous.get("run_id") else "not_measured",
                "state": dict(previous), **counts}
    report = min(reports, key=lambda r: r["finished_at"])
    result = DH.SR.monitor_decision(report, previous, used_pct)
    after = (report.get("post_apply_usage") or {}).get("used_pct")
    if isinstance(after, (int, float)) and after > 85:
        result["alert"] = "post_apply_disk_above_85"
    result.update(status="new_run", digest=report.get("operator_digest") or "Disk hygiene result unavailable",
                  refused=report.get("refused"), finished_at=report.get("finished_at"), **counts)
    if report.get("refused"):
        result["alert"] = "hygiene_refused"
    return result


@contextmanager
def _state_lock(state_path: Path):
    """Serialise the WHOLE read / decide / queue / write transition for this state identity.

    cx-openai-2 (2026-11-04): two supported `--apply` processes could interleave, and atomic replacement only prevents
    TORN json — it does not prevent a read-modify-write from overwriting a snapshot written by another process in
    between. A run paused between its read and its write erased a `critical` band another run had just reported, so the
    recovery was never emitted. The n8n wrapper flocks its own launcher; the documented direct CLI and the exported
    run() take no lock, so they can race each other and the wrapped job.

    The lock is keyed to the state FILE, so every entrypoint that writes this state takes the same lock — a new caller
    inherits it by writing the same state, not by remembering to ask. Wall-clock time is never used to order writers:
    a legitimate clock rollback is supported and must keep working.
    """
    lock_path = state_path.with_name(state_path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def run(
    *,
    rules: Mapping[str, Any],
    state_root: Optional[Path],
    ledger: Optional[Path],
    apply: bool,
    now: datetime,
    wall_start: Optional[datetime] = None,
) -> int:
    """Every apply path goes through here, so it takes the state lock before reading the snapshot."""
    state_path = R.runtime_dir(state_root) / rules["monitor"]["state_name"]
    with _state_lock(state_path):
        return _run_locked(rules=rules, state_root=state_root, ledger=ledger, apply=apply, now=now,
                           wall_start=wall_start, state_path=state_path)


def _run_locked(
    *,
    rules: Mapping[str, Any],
    state_root: Optional[Path],
    ledger: Optional[Path],
    apply: bool,
    now: datetime,
    wall_start: Optional[datetime] = None,
    state_path: Path,
) -> int:
    run_started = time.monotonic()
    # the receipt's started_at is the real start (the executor binds it to the attempt window); `now` is the
    # logical clock for bands and idle math and may be injected
    wall_start = wall_start or datetime.now(timezone.utc)
    mon = rules["monitor"]
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("schema") != STATE_SCHEMA:
            state = {}
    except (OSError, ValueError):
        state = {}
    mounts_state: dict[str, Any] = dict(state.get("mounts") or {})
    inodes_state: dict[str, Any] = dict(state.get("inodes") or {})
    ino = mon.get("inodes") or None
    manifest = latest_manifest(rules, state_root)
    results: list[dict[str, Any]] = []
    failures = 0
    ledger_busy_failures = 0

    def _count_intent_failure(reason: str) -> None:
        nonlocal failures, ledger_busy_failures
        failures += 1
        if reason in _LEDGER_BUSY_REASONS:
            ledger_busy_failures += 1

    def queue(kind_band: str, subject: str, summary: str, node: str) -> dict[str, Any]:
        return queue_host_intent(
            producer=mon["producer"],
            domain=mon["intent_domain"],
            kind=mon["intent_kinds"][kind_band],
            subject=subject,
            summary=summary,
            execution_id=_execution_id(now),
            node=node,
            ledger_path=ledger,
            now=now.timestamp(),
        )

    inode_results: list[dict[str, Any]] = []
    for mount in mon["mounts"] if ino else []:
        m = measure_inodes(mount)
        if m is None:
            inode_results.append(
                {"mount": mount, "metric": "inodes", "band": None, "note": "no_inode_limit_or_statvfs"}
            )
            continue
        cur = band_of(m["inodes_used_pct"], ino)
        prev = (inodes_state.get(mount) or {}).get("band")
        alert = alert_for(prev, cur, inodes_state.get(mount) or {}, now, metric_policy(mon, ino))
        row: dict[str, Any] = {**m, "metric": "inodes", "band": cur, "previous_band": prev, "alert": alert}
        if alert:
            top_cfg = ino.get("top_dirs") or {}
            top = top_file_dirs(mount, top_cfg) if mount in (top_cfg.get("mounts") or []) and cur != "ok" else None
            subject, summary = inode_intent_text(m, cur, ino, top, latest_tmp_manifest(rules, state_root))
            row.update(subject=subject, summary=summary, top_dirs=top)
            if apply:
                try:
                    rec = queue(cur, subject, summary, "disk_usage_monitor.inodes")
                    row["intent"] = {"intent_id": rec.get("intent_id"), "duplicate": rec.get("duplicate")}
                except HostIntentError as exc:
                    row["intent_error"] = exc.reason
                    _count_intent_failure(exc.reason)
                    inode_results.append(row)
                    continue  # band NOT recorded: the next run retries the alert
        if apply:
            entry = dict(inodes_state.get(mount) or {})
            if entry.get("band") != cur:
                entry["since"] = now.isoformat()
            entry.update(band=cur, last_pct=m["inodes_used_pct"], checked_at=now.isoformat())
            if alert:
                entry["alerted_at"] = now.isoformat()
                entry["alerted_band"] = cur
            inodes_state[mount] = entry
        inode_results.append(row)

    consumer_snapshot = state.get("consumer_snapshot")
    refreshed = False
    if mon.get("measure_consumers_on") == "alert":
        if consumer_snapshot_due(consumer_snapshot, mon, now):
            consumer_snapshot = collect_consumer_snapshot(
                rules, mon, now, deadline=run_started + CONSUMER_RUN_DEADLINE_SECONDS)
            refreshed = True
    else:
        consumer_snapshot = None

    for mount in mon["mounts"]:
        m = measure(mount)
        if m is None:
            results.append({"mount": mount, "error": "statvfs_failed"})
            failures += 1
            continue
        cur = band_of(m["used_pct"], mon)
        prev = (mounts_state.get(mount) or {}).get("band")
        alert = alert_for(prev, cur, mounts_state.get(mount) or {}, now, metric_policy(mon, mon))
        row: dict[str, Any] = {**m, "band": cur, "previous_band": prev, "alert": alert}
        if alert:
            consumers = top_consumers(rules, mon, manifest, consumer_snapshot) if consumer_snapshot is not None else []
            captured_at = consumer_snapshot["captured_at"] if consumer_snapshot is not None else None
            subject, summary = intent_text(m, cur, mon, consumers, manifest, captured_at)
            row.update(subject=subject, summary=summary)
            if apply:
                try:
                    rec = queue(cur, subject, summary, "disk_usage_monitor")
                    row["intent"] = {"intent_id": rec.get("intent_id"), "duplicate": rec.get("duplicate")}
                except HostIntentError as exc:
                    row["intent_error"] = exc.reason
                    _count_intent_failure(exc.reason)
                    results.append(row)
                    continue  # band NOT recorded: the next run retries the alert
        if apply:
            entry = dict(mounts_state.get(mount) or {})
            if entry.get("band") != cur:
                entry["since"] = now.isoformat()
            entry.update(band=cur, last_pct=m["used_pct"], checked_at=now.isoformat())
            if alert:
                entry["alerted_at"] = now.isoformat()
                entry["alerted_band"] = cur
            mounts_state[mount] = entry
        results.append(row)
    # ── absolute budgets (LQ-20261107-1638) ───────────────────────────────────────────────────────────────────────
    # Independent of the used% bands by construction: a 2 TB disk at 20% with a 40 GiB scratch root is a budget
    # breach, and the percentage bands would never say a word about it.
    budget_cfg = rules.get("budgets") if isinstance(rules.get("budgets"), dict) else None
    budget_results: list[dict[str, Any]] = []
    budget_state: dict[str, Any] = dict(state.get("budget_roots") or {})
    budget_samples_state = state.get("budget_samples")
    if budget_cfg and budget_cfg.get("enabled") and rules.get("_budget_roots"):
        growth = budget_cfg.get("growth") or {}
        kinds = budget_cfg.get("alert_kinds") or {}
        policy = budget_alert_policy(mon, budget_cfg)
        budget_rows = budget_measurements(
            rules, latest_budget_report(rules, state_root), latest_tmp_rows(rules, state_root),
        )
        samples = budget_samples(budget_samples_state, budget_rows, now, growth)
        for finding in budget_findings(budget_rows, samples, now, growth):
            entry = dict(budget_state.get(str(finding["root"])) or {})
            if finding["band"] is None:
                # unmeasured is not a band: never recorded as ok, never alerts, retried next poll
                finding["alert"] = None
                budget_results.append(finding)
                continue
            alert = alert_for(entry.get("band"), finding["band"], entry, now, policy)
            finding["alert"] = alert
            if alert:
                kind = kinds.get("over_cap") if finding["why"] == "over_cap" else kinds.get("growth")
                subject, text = budget_intent_text(finding)
                if apply:
                    try:
                        rec = queue_host_intent(
                            producer=mon["producer"], domain=mon["intent_domain"], kind=kind,
                            subject=subject, summary=text, execution_id=_execution_id(now),
                            node="disk_usage_monitor.budget", ledger_path=ledger, now=now.timestamp(),
                        )
                        finding["intent"] = {"intent_id": rec.get("intent_id"), "duplicate": rec.get("duplicate")}
                    except HostIntentError as exc:
                        finding["intent_error"] = exc.reason
                        _count_intent_failure(exc.reason)
                        budget_results.append(finding)
                        continue  # band NOT recorded: the next run retries the alert
            if apply:
                if entry.get("band") != finding["band"]:
                    entry["since"] = now.isoformat()
                entry.update(band=finding["band"], last_bytes=finding["measured_bytes"],
                             checked_at=now.isoformat(), growth_gb_per_day=finding["growth_gb_per_day"])
                if alert:
                    entry["alerted_at"] = now.isoformat()
                    entry["alerted_band"] = alert
                budget_state[str(finding["root"])] = entry
            budget_results.append(finding)
        budget_samples_state = samples
    standing_previous = dict(state.get("standing_hygiene") or {})
    measured_pct = [r["used_pct"] for r in results if isinstance(r.get("used_pct"), (int, float))]
    standing = standing_hygiene_status(rules, state_root, standing_previous, now, max(measured_pct) if measured_pct else None)
    if standing["status"] == "new_run" and apply:
        # New routes remain an operator proposal until the reviewed config is installed.
        cfg = (rules.get("standing_apply") or {}).get("monitor") or {}
        kind = cfg.get("alert_kind") if standing.get("alert") else cfg.get("digest_kind")
        try:
            if not kind:
                raise HostIntentError("standing_monitor_unconfigured")
            rec = queue_host_intent(producer=mon["producer"], domain=mon["intent_domain"], kind=kind,
                                    subject=("Disk hygiene alert " if standing.get("alert") else "Disk hygiene run digest ") + str(standing["run_id"]),
                                    summary=standing["digest"] + ("; " + standing["alert"] if standing.get("alert") else ""),
                                    execution_id=_execution_id(now), node="disk_usage_monitor.standing_hygiene",
                                    ledger_path=ledger, now=now.timestamp())
            standing["intent"] = {"intent_id": rec.get("intent_id"), "duplicate": rec.get("duplicate")}
            standing_previous = {"manifest_sha256": standing["manifest_sha256"], "run_id": standing["run_id"],
                                 "held_bytes": standing.get("held_bytes"), "observed_at": now.isoformat(),
                                 "seen_run_ids": list(dict.fromkeys([*standing_previous.get("seen_run_ids", []), standing["run_id"]]))}
        except HostIntentError as exc:
            standing["intent_error"] = exc.reason
            _count_intent_failure(exc.reason)  # Do not consume the run; next monitor attempt retries.
    pressure_active = bool(state.get("standing_pressure_active"))
    pressure_epoch = int(state.get("standing_pressure_epoch") or 0)
    current_pressure = bool(measured_pct and max(measured_pct) > 85)
    pressure = {"above_85": current_pressure, "observation_basis": "current_monitor_poll"}
    if isinstance(rules.get("standing_apply"), dict) and current_pressure and not pressure_active:
        if standing.get("intent") and standing.get("alert"):
            pressure_active = True
            pressure_epoch += 1
        elif apply:
            cfg = rules["standing_apply"].get("monitor") or {}
            try:
                if not cfg.get("alert_kind"):
                    raise HostIntentError("standing_monitor_unconfigured")
                rec = queue_host_intent(producer=mon["producer"], domain=mon["intent_domain"], kind=cfg["alert_kind"],
                                        subject=f"Disk hygiene pressure boundary {pressure_epoch + 1}",
                                        summary=f"Disk above 85% at {now.isoformat()} ({max(measured_pct):.2f}%, current monitor poll)",
                                        execution_id=_execution_id(now), node="disk_usage_monitor.standing_pressure", ledger_path=ledger, now=now.timestamp())
                pressure["intent"] = {"intent_id": rec.get("intent_id"), "duplicate": rec.get("duplicate")}
                pressure_active = True
                pressure_epoch += 1
            except HostIntentError as exc:
                pressure["intent_error"] = exc.reason
                _count_intent_failure(exc.reason)
    if measured_pct and not current_pressure:
        pressure_active = False
    summary = {"mounts": results, "inodes": inode_results, "manifest": manifest, "standing_hygiene": standing,
               "standing_pressure": pressure, "consumer_snapshot": consumer_snapshot,
               "consumer_snapshot_refreshed": refreshed, "budgets": budget_results, "failures": failures}
    if failures and failures == ledger_busy_failures:
        busy_rc = EX_UNAVAILABLE
    else:
        busy_rc = 1
    if not apply:
        R.dry_run_report(LANE_ID, summary, would_write=[str(state_path)], receipt=R.receipt_path(LANE_ID, state_root))
        return 0 if not failures else busy_rc
    measured = sum(1 for r in results if "band" in r)
    ok = failures == 0
    try:
        from scripts.lib.atomic_json_store import atomic_write_json

        atomic_write_json(
            state_path,
            {"schema": STATE_SCHEMA, "updated_at": now.isoformat(), "mounts": mounts_state, "inodes": inodes_state,
             "standing_hygiene": standing_previous, "standing_pressure_active": pressure_active,
             "standing_pressure_epoch": pressure_epoch, "consumer_snapshot": consumer_snapshot,
             "budget_roots": budget_state, "budget_samples": budget_samples_state},
            indent=1,
        )
    except OSError as exc:
        ok = False
        summary["error"] = f"state_write_failed:{type(exc).__name__}"
    output = {
        "produced_count": measured,
        "attempted_count": len(mon["mounts"]),
        "skipped_reasons": {SKIP_DEPENDENCY: len(mon["mounts"]) - measured} if measured < len(mon["mounts"]) else {},
        "empty_reason": None,
        "output_evidence": [{"kind": "file", "ref": str(state_path)}],
    }
    if ok:
        rc = 0
    elif failures and failures == ledger_busy_failures:
        rc = EX_UNAVAILABLE
    else:
        rc = 1
    written = R.write_lane_receipt(
        LANE_ID,
        ok=ok,
        exit_code=rc,
        started_at=wall_start,
        script=SCRIPT,
        summary=summary,
        error=summary.get("error"),
        path=R.receipt_path(LANE_ID, state_root),
        output=output,
    )
    print(
        json.dumps(
            {
                "mode": "apply",
                "ok": ok,
                "receipt": str(written) if written else None,
                "bands": {r["mount"]: r.get("band") for r in results},
                "alerts": {r["mount"]: r.get("alert") for r in results if r.get("alert")},
                "inode_bands": {r["mount"]: r.get("band") for r in inode_results},
                "inode_alerts": {r["mount"]: r.get("alert") for r in inode_results if r.get("alert")},
                "failures": failures,
                "ledger_busy_failures": ledger_busy_failures,
            }
        )
    )
    if ok and not written:
        return 1
    return rc


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", help="the default: measure and print, write nothing")
    g.add_argument("--apply", action="store_true", help="record bands, queue an intent on a band change, receipt")
    ap.add_argument("--rules", help="rules file (default config/disk_hygiene_rules.json)")
    ap.add_argument("--state-root", help="persistent-state root (default TRADEAI_STATE_ROOT / resolver)")
    ap.add_argument("--ledger", help="coordination ledger (default: TRADEAI_N8N_COORDINATION_LEDGER, else state root)")
    ap.add_argument("--home", help=argparse.SUPPRESS)  # tests
    ap.add_argument("--now", help=argparse.SUPPRESS)  # tests: aware ISO 8601
    try:
        a = ap.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    wall_start = datetime.now(timezone.utc)
    now = DH._parse_now(a.now)
    if now is None:
        print("--now must be an aware ISO 8601 timestamp", file=sys.stderr)
        return 2
    state_root = Path(a.state_root) if a.state_root else None
    try:
        rules = DH.load_rules(Path(a.rules) if a.rules else None, home=Path(a.home) if a.home else None)
        mon = rules["monitor"]
        # `realert_minutes` is required at RUNTIME by metric_policy, so it is required at STARTUP too: otherwise a
        # rules file missing it passes validation and then dies inside the mount loop with a traceback, exit 1, no
        # JSON error line, no receipt and no state write (cc-deepseek-2 R6). Refuse it before the lane runs.
        for key in ("mounts", "warn_pct", "critical_pct", "realert_minutes", "state_name", "producer",
                    "intent_domain", "intent_kinds"):
            if key not in mon:
                raise DH.RulesError(f"rules_missing:monitor.{key}")
        if not float(mon["warn_pct"]) < float(mon["critical_pct"]):
            raise DH.RulesError("monitor_thresholds_out_of_order")
        ino = mon.get("inodes")
        if ino is not None:
            for key in ("warn_pct", "critical_pct"):
                if key not in ino:
                    raise DH.RulesError(f"rules_missing:monitor.inodes.{key}")
            if not float(ino["warn_pct"]) < float(ino["critical_pct"]):
                raise DH.RulesError("monitor_inode_thresholds_out_of_order")
        # LQ-20261107-1638: an enabled budget with no routeable kind would measure a breach and say nothing.
        bud = rules.get("budgets")
        if isinstance(bud, dict) and bud.get("enabled"):
            kinds = bud.get("alert_kinds")
            if not isinstance(kinds, dict) or not kinds.get("over_cap") or not kinds.get("growth"):
                raise DH.RulesError("budgets_alert_kinds")
    except (DH.RulesError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        if a.apply:
            R.write_lane_receipt(
                LANE_ID,
                ok=False,
                exit_code=1,
                started_at=wall_start,
                script=SCRIPT,
                summary={"error": str(exc)},
                path=R.receipt_path(LANE_ID, state_root),
                output={
                    "produced_count": 0,
                    "attempted_count": 0,
                    "skipped_reasons": {SKIP_DEPENDENCY: 1},
                    "empty_reason": None,
                },
            )
        return 1
    ledger = Path(a.ledger) if a.ledger else None
    if ledger is None and state_root is not None and not os.environ.get("TRADEAI_N8N_COORDINATION_LEDGER"):
        ledger = state_root / "data" / "governance" / "n8n_coordination_ledger.sqlite"
    return run(rules=rules, state_root=state_root, ledger=ledger, apply=bool(a.apply), now=now, wall_start=wall_start)


if __name__ == "__main__":
    raise SystemExit(main())
