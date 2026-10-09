"""Shard the registered CIO hardening suite across N CI runners (operator-approved 2026-10-09).

Design: docs/architecture/ci/cio-hardening-design-audit-20261009.md, "Medium-term" item 1
(shard the full suite and run it on every PR) and item 3 (one aggregate required context).

Every registered, existing test file (``GATES`` in scripts/run_cio_hardening_ci.py) is put in
EXACTLY ONE shard:

* ``pg``      -- files that need a Postgres database (the m2_conn / psycopg2 / alert-DSN tests
                 that SKIP on a runner without one). The workflow gives this shard a service
                 container, and every file runs one at a time.
* ``serial``  -- the other files the runner's shared-state classifier sends to the serial
                 tail (docs/INDEX.md, git operations, probe files planted in scripts/). One at
                 a time, on their own runner, so no other test sees their side effects.
* ``0..N-1``  -- everything else, by greedy longest-processing-time assignment on duration
                 hints. Ties break on the path, so the plan is a pure function of
                 (registered files, hints, N): every shard job computes the same plan.

The aggregate job (``ci-gate``) does not trust the plan. It recomputes the registered file
list from GATES on the tested commit and compares it with the files each shard REPORTS it
ran (``verify_manifests``): a missing, duplicated or unknown file, a missing shard, a
failed unit, a disagreeing plan digest or a different tested tree fails the gate.

Pure functions, stdlib only: hermetic tests in tests/test_ci_shards_tree_attest_20261009.py.
AUTHORITY: READ_ONLY_ADVISORY (CI tooling; no broker, no Telegram, no DB writes).
"""

from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable, Sequence

MANIFEST_SCHEMA = "CiShardManifest@v1"
TIMINGS_SCHEMA = "CiShardTimings@v1"

SERIAL_SHARD = "serial"
PG_SHARD = "pg"

#: A file goes to the Postgres shard if its source matches one of these. Narrow on purpose:
#: the shard is serial, so a false positive costs its runtime, never correctness.
DB_PATTERNS = (
    r"\bm2_conn\b",
    r"psycopg2\.connect",
    r"M2_TEST_DATABASE",
    r"ALERT_TEST_DSN",
    r"importorskip\(\s*[\"']psycopg2[\"']",
)
_DB_RE = re.compile("|".join(DB_PATTERNS))


def source_needs_db(text: str) -> bool:
    return bool(_DB_RE.search(text or ""))


def shard_ids(n: int) -> list[str]:
    if n < 1:
        raise ValueError("shard count must be >= 1")
    return [str(i) for i in range(n)] + [SERIAL_SHARD, PG_SHARD]


def parse_shard_arg(value: str) -> tuple[str, int]:
    """``"3/8"`` -> ("3", 8); ``"serial/8"`` and ``"pg/8"`` name the dedicated shards."""
    m = re.fullmatch(r"\s*(\d+|serial|pg)\s*/\s*(\d+)\s*", value or "")
    if not m:
        raise ValueError(f"--shard expects I/N, serial/N or pg/N, got {value!r}")
    sid, n = m.group(1), int(m.group(2))
    if n < 1:
        raise ValueError("shard count must be >= 1")
    if sid.isdigit():
        if int(sid) >= n:
            raise ValueError(f"shard index {sid} out of range for N={n}")
        sid = str(int(sid))
    return sid, n


def registered_files(gates: Iterable[tuple[str, Sequence[str]]], exists: Callable[[str], bool]) -> list[str]:
    """Unique registered files that exist, in first-registration order."""
    seen: dict[str, None] = {}
    for _name, paths in gates:
        for p in paths:
            if p not in seen and exists(p):
                seen[p] = None
    return list(seen)


def first_gate_of(gates: Iterable[tuple[str, Sequence[str]]]) -> dict[str, str]:
    """file -> the first gate that registers it (labels a file registered in several gates)."""
    out: dict[str, str] = {}
    for name, paths in gates:
        for p in paths:
            out.setdefault(p, name)
    return out


def assign_lpt(files: Sequence[str], weight: Callable[[str], float], n: int) -> list[list[str]]:
    """Greedy longest-processing-time: heaviest first onto the least-loaded shard.

    Deterministic: files are ordered by (-weight, path) and a load tie goes to the lowest index.
    Each shard's files are returned sorted by path.
    """
    if n < 1:
        raise ValueError("shard count must be >= 1")
    loads = [0.0] * n
    shards: list[list[str]] = [[] for _ in range(n)]
    for p in sorted(set(files), key=lambda f: (-float(weight(f)), f)):
        i = min(range(n), key=lambda k: (loads[k], k))
        shards[i].append(p)
        loads[i] += float(weight(p))
    return [sorted(s) for s in shards]


def plan_shards(
    gates: Sequence[tuple[str, Sequence[str]]],
    *,
    n: int,
    weight: Callable[[str], float],
    needs_serial: Callable[[str], bool],
    needs_db: Callable[[str], bool],
    exists: Callable[[str], bool],
) -> dict:
    """Return the full plan: ``{"n", "shards": {id: [files]}, "loads": {id: secs}, "digest"}``."""
    files = registered_files(gates, exists)
    db = sorted(p for p in files if needs_db(p))
    db_set = set(db)
    serial = sorted(p for p in files if p not in db_set and needs_serial(p))
    serial_set = set(serial)
    free = [p for p in files if p not in db_set and p not in serial_set]
    shards = {str(i): fs for i, fs in enumerate(assign_lpt(free, weight, n))}
    shards[SERIAL_SHARD] = serial
    shards[PG_SHARD] = db
    loads = {sid: round(sum(float(weight(p)) for p in fs), 1) for sid, fs in shards.items()}
    return {"n": n, "shards": shards, "loads": loads, "digest": plan_digest(shards)}


def plan_digest(shards: dict[str, Sequence[str]]) -> str:
    body = json.dumps({k: list(v) for k, v in sorted(shards.items())}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def gates_for_files(gates: Sequence[tuple[str, Sequence[str]]], files: Iterable[str]) -> list[tuple[str, list[str]]]:
    """Restrict GATES to ``files``; a file registered in several gates appears once (first gate)."""
    wanted = set(files)
    first = first_gate_of(gates)
    out = []
    for name, paths in gates:
        mine = [p for p in dict.fromkeys(paths) if p in wanted and first.get(p) == name]
        if mine:
            out.append((name, mine))
    return out


# ---------------------------------------------------------------------------
# Per-file timings from a pytest junit XML report (for duration-hint refresh)
# ---------------------------------------------------------------------------


def _classname_to_file(classname: str, files: Sequence[str]) -> str | None:
    """``tests.test_x.TestY`` -> ``tests/test_x.py`` when that file is in ``files``."""
    parts = (classname or "").split(".")
    for k in range(len(parts), 0, -1):
        cand = "/".join(parts[:k]) + ".py"
        if cand in files:
            return cand
    return None


def file_seconds_from_junit(xml_text: str, files: Sequence[str], wall: float) -> dict[str, float]:
    """Attribute a unit's wall time to its files.

    Test-case time is summed per file; the remainder (interpreter start, imports, collection)
    is spread evenly. An unreadable report spreads the whole wall evenly -- a hint is only
    ever an ordering input, never a decision about what runs.
    """
    files = list(files)
    if not files:
        return {}
    per = {f: 0.0 for f in files}
    try:
        root = ET.fromstring(xml_text) if xml_text else None
    except ET.ParseError:
        root = None
    if root is not None:
        for tc in root.iter("testcase"):
            f = tc.get("file")
            f = f if f in per else _classname_to_file(tc.get("classname", ""), files)
            if f is None:
                continue
            try:
                per[f] += float(tc.get("time") or 0.0)
            except ValueError:
                continue
    spread = max(0.0, float(wall) - sum(per.values())) / len(files)
    return {f: round(v + spread, 2) for f, v in per.items()}


# ---------------------------------------------------------------------------
# Aggregate verification (the `ci-gate` job)
# ---------------------------------------------------------------------------


def build_manifest(
    *, shard: str, n: int, sha: str, tree: str, digest: str, files: Sequence[str], units: Sequence[dict], wall: float
) -> dict:
    file_seconds: dict[str, float] = {}
    for u in units:
        file_seconds.update(u.get("file_seconds") or {})
    ran = sorted({f for u in units for f in u.get("files", [])})
    return {
        "schema": MANIFEST_SCHEMA,
        "shard": shard,
        "n": n,
        "sha": sha,
        "tree": tree,
        "plan_digest": digest,
        "planned_files": sorted(files),
        "files": ran,
        "units": [{k: v for k, v in u.items() if k != "file_seconds"} for u in units],
        "file_seconds": dict(sorted(file_seconds.items())),
        "ok": all(u.get("passed") for u in units),
        "wall_seconds": round(wall, 1),
    }


def verify_manifests(
    manifests: Sequence[dict],
    *,
    expected_files: Sequence[str],
    n: int,
    expected_tree: str | None = None,
    expected_digest: str | None = None,
    needs: dict | None = None,
) -> dict:
    """Prove the shards together ran every registered file exactly once, and all passed."""
    errors: list[str] = []
    by_shard: dict[str, dict] = {}
    for m in manifests:
        if m.get("schema") != MANIFEST_SCHEMA:
            errors.append("bad_schema")
            continue
        sid = str(m.get("shard"))
        if sid in by_shard:
            errors.append(f"duplicate_manifest:{sid}")
            continue
        by_shard[sid] = m
    want_ids = shard_ids(n)
    missing_shards = [s for s in want_ids if s not in by_shard]
    unknown_shards = sorted(s for s in by_shard if s not in want_ids)
    errors += [f"missing_shard:{s}" for s in missing_shards]
    errors += [f"unknown_shard:{s}" for s in unknown_shards]

    counts: dict[str, int] = {}
    failed_shards = []
    for sid, m in sorted(by_shard.items()):
        if int(m.get("n") or 0) != n:
            errors.append(f"shard_count_mismatch:{sid}")
        if expected_tree and m.get("tree") != expected_tree:
            errors.append(f"tree_mismatch:{sid}")
        if expected_digest and m.get("plan_digest") != expected_digest:
            errors.append(f"plan_digest_mismatch:{sid}")
        if sorted(m.get("files") or []) != sorted(m.get("planned_files") or []):
            errors.append(f"ran_not_planned:{sid}")
        if not m.get("ok") or any(not u.get("passed") for u in m.get("units") or []):
            failed_shards.append(sid)
        for f in m.get("files") or []:
            counts[f] = counts.get(f, 0) + 1
    errors += [f"failed_shard:{s}" for s in failed_shards]

    expected = set(expected_files)
    ran = set(counts)
    missing_files = sorted(expected - ran)
    extra_files = sorted(ran - expected)
    duplicate_files = sorted(f for f, c in counts.items() if c > 1)
    if missing_files:
        errors.append(f"missing_files:{len(missing_files)}")
    if extra_files:
        errors.append(f"unregistered_files:{len(extra_files)}")
    if duplicate_files:
        errors.append(f"duplicate_files:{len(duplicate_files)}")

    for job, res in sorted((needs or {}).items()):
        result = res.get("result") if isinstance(res, dict) else res
        if result != "success":
            errors.append(f"job_not_successful:{job}:{result}")

    return {
        "ok": not errors,
        "errors": errors,
        "expected_files": len(expected),
        "ran_files": len(ran),
        "missing_files": missing_files,
        "extra_files": extra_files,
        "duplicate_files": duplicate_files,
        "failed_shards": failed_shards,
        "missing_shards": missing_shards,
        "shard_walls": {s: by_shard[s].get("wall_seconds") for s in sorted(by_shard)},
    }


def merge_timings(manifests: Sequence[dict]) -> dict:
    """One hint candidate from every shard's measured per-file seconds (artifact for refresh)."""
    files: dict[str, float] = {}
    for m in manifests:
        for f, s in (m.get("file_seconds") or {}).items():
            files[f] = max(files.get(f, 0.0), float(s))
    return {
        "schema": TIMINGS_SCHEMA,
        "note": (
            "Measured per-file seconds from the sharded full-suite run (junit test time plus an even "
            "share of the unit's start-up). Candidate for config/ci_shard_duration_hints.json; hints "
            "only order and pack work, they never decide what runs."
        ),
        "files": dict(sorted((f, round(s, 1)) for f, s in files.items())),
    }
