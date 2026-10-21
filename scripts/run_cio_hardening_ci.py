#!/usr/bin/env python3
"""Local + CI runner for CIO production-hardening gates (Phase 10).

Runs the pure unit suites that must stay green on every push/PR for the
investment-office / Alex CIO hardening program. Never contacts brokers or
sends Telegram.

Exit 0 only if all gates pass.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Gate registry (2026-10-21, operator-approved process plan): ONE JSON FILE PER GATE under
# config/ci_gates/<name>.json (schema CiGate@v1, scripts/lib/ci_gates.py), loaded sorted by name.
# To add a gate, ADD A FILE there -- never an inline list here: parallel PRs that each appended to
# one list collided on every merge. How-to: docs/ops/CI_FAST_CORE_20260925.md "Adding a gate".
# scripts/ci_gates_migrate.py moves any inline entries back out (re-runnable).
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
from scripts.lib import ci_gates as _ci_gates  # noqa: E402

GATES = _ci_gates.load_gates(REPO)


# ---------------------------------------------------------------------------
# Execution profiles (2026-09-25, operator: "speed up to like 5 mins")
#
# Measured before this change (3 green CI runs, 2026-09-25): the gates step took
# 610-1090 s of a 1077-1127 s job. It ran 181 pytest invocations one after the
# other; one gate (maturity_overnight_20260912, 130 files) alone took 226-385 s.
# No test was run twice (567 unique files, 7 shared), so the only lever that
# keeps every registered test is PARALLELISM, not pruning.
#
#   fast (default; the required `cio-hardening` context): EVERY gate still runs.
#         Gates execute concurrently in a worker pool; gates with many files are
#         split into file chunks so no single gate bounds the wall clock. Gates
#         whose tests touch shared state (the live docs/INDEX.md, git in the repo,
#         a Postgres test database) run afterwards, one at a time.
#   full: the historical behaviour -- one gate at a time, in declared order. It is
#         the isolation reference (a test that only passes in `fast` or only in
#         `full` has a hidden dependency) and runs on push to main, nightly, and on
#         workflow_dispatch in `cio-hardening-full`.
#
#   pr:   the required `cio-hardening` context on pull requests (operator budget:
#         5 minutes wall clock including runner setup). Runs a SELECTION, in the
#         fast pool: the smoke gates, the full named gates of every HIGH risk tier
#         the diff touches, every changed test, every test that imports/references
#         a changed file, then further-reachable tests nearest-first while the
#         estimate fits config/ci_risk_tiers.json budget_seconds. What does not
#         fit is DEFERRED -- listed in the log and job summary -- and runs in the
#         post-merge `full` run (push to main), which opens an issue on failure.
#         See scripts/lib/test_impact.py. If the base ref or the map is unusable
#         it falls back to `fast` (everything).
#
# All profiles run the same tail checks (docs index drift, release manifest).
# Registration is unchanged: a test file is covered iff it is in GATES
# (check_test_coverage.py enforces that), whatever the profile.
# ---------------------------------------------------------------------------

#: Parallel work is packed into units of about this many seconds (by duration hint).
UNIT_TARGET_SECONDS = float(os.environ.get("CIO_CI_UNIT_SECONDS", "25"))

#: Per-file wall-second hints (config/ci_test_duration_hints.json). They only order
#: and pack work; a missing or stale hint can never drop a test.
DURATION_HINTS_PATH = REPO / "config" / "ci_test_duration_hints.json"
DEFAULT_FILE_SECONDS = 1.0

#: A FILE runs in the serial tail if it matches one of these. They mark tests that
#: touch state other workers can see: the committed docs index, git operations, a
#: Postgres test database, or a probe file planted in scripts/. (Per file, not per gate: the rest of a gate still runs in
#: parallel.) Conservative on purpose -- a false positive only costs a few seconds.
SHARED_STATE_PATTERNS = (
    r"docs/INDEX\.md",
    r"\bm2_conn\b",
    r"psycopg2\.connect",
    r"M2_TEST_DATABASE",
    r"\bgit\b[\"', ]+(?:stash|checkout|reset|commit|worktree|merge)\b",
    # plants a probe file INTO scripts/ (ROOT / "scripts" / "_pytest_..._probe.py") to
    # prove a tree-wide ratchet fires; any concurrent tree scan would see it too
    r"[\"']scripts[\"']\s*/\s*f?[\"']_",
)
_SHARED_STATE_RE = re.compile("|".join(SHARED_STATE_PATTERNS))

#: pytest exit 5 = "no tests collected": a unit whose every module skips at import
#: (e.g. the Postgres-only files split out of a gate when psycopg2 is absent). The
#: serial `full` profile never saw it because those files shared one invocation
#: with runnable tests.
#: Only when pytest reports skips -- a unit that collects nothing at all still fails.
PASS_CODES = frozenset({0, 5})


def _unit_passed(rc: int, out: str) -> bool:
    return rc == 0 or (rc == 5 and " skipped" in out)


#: Files proven to need the serial tail even though no pattern marks them.
SERIAL_FILES: frozenset[str] = frozenset()


def _profile_from_env() -> str:
    return (os.environ.get("CIO_CI_PROFILE") or "fast").strip().lower()


def _default_jobs() -> int:
    raw = os.environ.get("CIO_CI_JOBS")
    if raw and raw.strip().isdigit():
        return max(1, int(raw))
    return max(1, min(os.cpu_count() or 2, 8))


def load_duration_hints(path: Path = DURATION_HINTS_PATH) -> dict[str, float]:
    try:
        import json

        return {str(k): float(v) for k, v in (json.loads(path.read_text(encoding="utf-8")).get("files") or {}).items()}
    except (OSError, ValueError):
        return {}


def file_needs_serial(path: str) -> bool:
    if path in SERIAL_FILES:
        return True
    try:
        return bool(_SHARED_STATE_RE.search((REPO / path).read_text(encoding="utf-8", errors="replace")))
    except OSError:
        return False


def gate_needs_serial(name: str, paths: list[str]) -> bool:
    """True if any file of the gate needs the serial tail (kept for callers/tests)."""
    return any(file_needs_serial(p) for p in paths)


def plan_units(gates, *, unit_seconds: float = UNIT_TARGET_SECONDS, hints: dict[str, float] | None = None):
    """Return (parallel_units, serial_units); a unit is (gate_name, [files]).

    Every existing registered file appears in exactly one unit per registration.
    """
    hints = load_duration_hints() if hints is None else hints

    def w(p: str) -> float:
        return hints.get(p, DEFAULT_FILE_SECONDS)

    parallel, serial = [], []
    for name, paths in gates:
        existing = [p for p in paths if (REPO / p).is_file()]
        if not existing:
            continue
        shared = [p for p in existing if file_needs_serial(p)]
        free = [p for p in existing if p not in shared]
        if shared:
            serial.append((name, shared))
        chunk: list[str] = []
        acc = 0.0
        for p in free:
            if chunk and acc + w(p) > unit_seconds:
                parallel.append((name, chunk))
                chunk, acc = [], 0.0
            chunk.append(p)
            acc += w(p)
        if chunk:
            parallel.append((name, chunk))

    parallel.sort(key=lambda u: sum(w(p) for p in u[1]), reverse=True)  # longest first
    return parallel, serial


def _run_unit(unit):
    name, files = unit
    t0 = time.monotonic()
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--tb=line", "-p", "no:cacheprovider", *files],
        cwd=str(REPO),
        capture_output=True,
        text=True,
    )
    return name, files, r.returncode, (r.stdout or "") + (r.stderr or ""), time.monotonic() - t0


def run_gates(gates, *, profile: str, jobs: int) -> list[str]:
    """Run every gate; return the names of failed gates."""
    failed: list[str] = []
    if profile == "full" or jobs <= 1:
        for name, paths in gates:
            existing = [p for p in paths if (REPO / p).is_file()]
            if not existing:
                print(f"[SKIP] {name}: no test files", flush=True)
                continue
            print(f"[RUN]  {name}: {' '.join(existing)}", flush=True)
            r = subprocess.run([sys.executable, "-m", "pytest", "-q", "--tb=line", *existing], cwd=str(REPO))
            if r.returncode != 0:
                failed.append(name)
                print(f"[FAIL] {name}", flush=True)
            else:
                print(f"[PASS] {name}", flush=True)
        return failed

    parallel, serial = plan_units(gates)
    print(f"[plan] profile=fast jobs={jobs} parallel_units={len(parallel)} serial_gates={len(serial)}", flush=True)
    results: dict[str, list[tuple]] = {}

    def record(res):
        name, files, rc, out, secs = res
        results.setdefault(name, []).append(res)
        tail = (out.strip().splitlines() or [""])[-1]
        status = "PASS" if _unit_passed(rc, out) else "FAIL"
        print(f"[{status}] {name} ({len(files)} files, {secs:.1f}s) {tail[-100:]}", flush=True)
        if not _unit_passed(rc, out):
            print(out[-6000:], flush=True)

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for res in pool.map(_run_unit, parallel):
            record(res)
    for unit in serial:
        record(_run_unit(unit))

    declared = [n for n, _ in gates]
    for name in declared:
        if any(not _unit_passed(r[2], r[3]) for r in results.get(name, [])) and name not in failed:
            failed.append(name)
    return failed


ALARM_GATE_NAMES = ("alarm_fires", "alarm_document_sites_20260922")


def _touches_alarm_sites(changed: list[str]) -> bool:
    """True when a changed scripts/*.py file contains a send_telegram call (alarm-coverage scope)."""
    for p in changed or []:
        if not (p.startswith("scripts/") and p.endswith(".py")):
            continue
        try:
            if "send_telegram" in (REPO / p).read_text(encoding="utf-8", errors="ignore"):
                return True
        except OSError:
            continue
    return False


def select_pr_gates(
    base: str, *, include_worktree: bool = False, budget: float | None = None, changed: list[str] | None = None
):
    """Return (gates, profile) for the pr profile; falls back to (GATES, "fast")."""
    import json

    sys.path.insert(0, str(REPO))
    from scripts.lib import test_impact

    t0 = time.monotonic()
    if changed is None:
        changed = test_impact.changed_paths(base, root=REPO, include_worktree=include_worktree)
    if changed is None:
        print(f"[select] base {base!r} unusable -> FALLBACK to fast (every gate)", flush=True)
        return GATES, "fast"
    try:
        impact_map, status = test_impact.load_map(REPO)
        tiers = test_impact.load_tiers()
    except (OSError, ValueError) as exc:
        print(f"[select] impact map/tiers unusable ({exc}) -> FALLBACK to fast (every gate)", flush=True)
        return GATES, "fast"
    sel = test_impact.select(
        changed,
        GATES,
        impact_map=impact_map,
        tiers=tiers,
        hints=load_duration_hints(),
        default_seconds=DEFAULT_FILE_SECONDS,
        budget_seconds=budget,
    )
    # A new send_telegram call is invisible to the tier map and the import graph, so the
    # alarm-coverage gates ran only after merge and main went red (2026-10-04: two new alert senders
    # shipped without firing tests). Any changed script that sends Telegram pulls them in.
    if _touches_alarm_sites(changed):
        have = {name for name, _f in sel["gates"]}
        for name, files in GATES:
            if name in ALARM_GATE_NAMES and name not in have:
                sel["gates"].append((name, files))
                print(f"[select] ALARM: {name} added (a changed script calls send_telegram)", flush=True)
    n_files = sum(len(f) for _n, f in sel["gates"])
    print(
        f"[select] base={base} changed={len(changed)} tier={sel['tier']} map={status} "
        f"impacted={sel['impacted']} selected_files={n_files} gates={len(sel['gates'])} "
        f"estimate={sel['estimate_seconds']}s (mandatory {sel['mandatory_estimate_seconds']}s, "
        f"budget {sel['budget_seconds']}s) deferred={len(sel['deferred'])} "
        f"select_secs={time.monotonic() - t0:.1f}",
        flush=True,
    )
    for cat, paths in sorted(sel["high"].items()):
        print(f"[select] HIGH {cat}: {', '.join(paths[:8])}{' ...' if len(paths) > 8 else ''}", flush=True)
    for f in sel["deferred"][:25]:
        print(f"[select] DEFERRED to post-merge full run: {f}", flush=True)
    if len(sel["deferred"]) > 25:
        print(
            f"[select] ... and {len(sel['deferred']) - 25} more DEFERRED (all listed in the job summary "
            "and in CIO_CI_SELECTION_OUT when set)",
            flush=True,
        )
    if sel["unknown_gates"]:
        print(f"[select] WARNING tier config names unknown gates: {sel['unknown_gates']}", flush=True)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        lines = [
            "## cio-hardening (pr profile)",
            f"- changed paths: {len(changed)}; risk tier: **{sel['tier'].upper()}**",
            f"- selected: {n_files} test files in {len(sel['gates'])} gates; "
            f"estimate {sel['estimate_seconds']} s of {sel['budget_seconds']} s budget",
            f"- deferred to the post-merge full run: {len(sel['deferred'])}",
        ]
        if sel["high"]:
            lines.append("")
            lines.append("### HIGH-risk paths touched -- independent review required (reviewer is not the author)")
            for cat, paths in sorted(sel["high"].items()):
                lines.append(f"- **{cat}**: " + ", ".join(f"`{p}`" for p in paths))
        if sel["deferred"]:
            lines.append("")
            lines.append("<details><summary>Deferred tests</summary>\n")
            lines += [f"- `{f}`" for f in sel["deferred"]]
            lines.append("\n</details>")
        try:
            with open(summary, "a", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + "\n")
        except OSError:
            pass
    out = os.environ.get("CIO_CI_SELECTION_OUT")
    if out:
        Path(out).write_text(
            json.dumps({k: v for k, v in sel.items()}, indent=1, default=list) + "\n", encoding="utf-8"
        )
    return sel["gates"], "fast"


def write_duration_hints(*, jobs: int) -> int:
    """Measure per-file wall time and rewrite config/ci_test_duration_hints.json."""
    import json

    files = sorted({p for _n, ps in GATES for p in ps if (REPO / p).is_file() and not file_needs_serial(p)})

    def one(path: str):
        t0 = time.monotonic()
        subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", path],
            cwd=str(REPO),
            capture_output=True,
        )
        return path, round(time.monotonic() - t0, 1)

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        measured = dict(pool.map(one, files))
    doc = {
        "schema": "CiTestDurationHints@v1",
        "note": (
            "Per-file wall seconds (one pytest process per file). Used ONLY to order and pack work in "
            "run_cio_hardening_ci.py --profile fast; never decides which tests run. Files below 2 s are "
            "omitted (default weight 1 s). Refresh with scripts/run_cio_hardening_ci.py --write-duration-hints."
        ),
        "files": {k: v for k, v in sorted(measured.items()) if v >= 2.0},
    }
    DURATION_HINTS_PATH.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {DURATION_HINTS_PATH.relative_to(REPO)} ({len(doc['files'])} files >= 2 s of {len(files)})")
    return 0


# ---------------------------------------------------------------------------
# Sharded full suite (operator-approved 2026-10-09; .github/workflows/cio-full-suite-sharded.yml)
#
# `--shard I/N` runs shard I of N (or `serial/N`, `pg/N`) of EVERY registered file -- nothing
# deferred -- and writes a CiShardManifest@v1 naming each file it ran, its unit results and
# measured per-file seconds. `--verify-shards DIR --shards N` (the `ci-gate` job) recomputes the
# registered list from GATES and fails unless the shards' reported files are exactly that list,
# each once, all passed, on the same tree and plan. Planning: scripts/lib/ci_shards.py.
# ---------------------------------------------------------------------------

#: Per-file seconds measured by the sharded run (overlays DURATION_HINTS_PATH for balancing).
SHARD_HINTS_PATH = REPO / "config" / "ci_shard_duration_hints.json"


def shard_hints() -> dict[str, float]:
    hints = load_duration_hints()
    hints.update(load_duration_hints(SHARD_HINTS_PATH))
    return hints


def file_needs_db(path: str) -> bool:
    from scripts.lib import ci_shards

    try:
        return ci_shards.source_needs_db((REPO / path).read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return False


def shard_plan(n: int) -> dict:
    sys.path.insert(0, str(REPO))
    from scripts.lib import ci_shards

    hints = shard_hints()
    return ci_shards.plan_shards(
        GATES,
        n=n,
        weight=lambda p: hints.get(p, DEFAULT_FILE_SECONDS),
        needs_serial=file_needs_serial,
        needs_db=file_needs_db,
        exists=lambda p: (REPO / p).is_file(),
    )


def _git_value(*args: str) -> str:
    r = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True)
    out = (r.stdout or "").strip()
    if r.returncode != 0 or not out:
        raise RuntimeError("git " + " ".join(args) + " failed")
    return out


def _run_unit_junit(job):
    """One pytest process for a unit, with a junit report for per-file timings."""
    import xml.etree.ElementTree as ET

    from scripts.lib import ci_shards

    (name, files), xml_path = job[0], job[1]
    env = job[2] if len(job) > 2 else None
    t0 = time.monotonic()
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--tb=line",
            "-p",
            "no:cacheprovider",
            f"--junitxml={xml_path}",
            "-o",
            "junit_family=xunit1",
            *files,
        ],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        env=env,
    )
    secs = time.monotonic() - t0
    out = (r.stdout or "") + (r.stderr or "")
    try:
        xml_text = Path(xml_path).read_text(encoding="utf-8")
    except OSError:
        xml_text = ""
    skipped = 0
    try:
        skipped = sum(1 for _ in ET.fromstring(xml_text).iter("skipped")) if xml_text else 0
    except ET.ParseError:
        pass
    return {
        "gate": name,
        "files": list(files),
        "rc": r.returncode,
        # A registered file with no test functions (e.g. a script-style check) collects nothing:
        # pytest exit 5 "no tests ran". In the fast/full profiles it shares an invocation with
        # its gate's other files and is accepted there; a shard may run it alone, so accept it
        # the same way and record it. Collection errors (exit 2) still fail.
        "passed": _unit_passed(r.returncode, out) or (r.returncode == 5 and "no tests ran" in out),
        "no_tests": r.returncode == 5 and "no tests ran" in out,
        "seconds": round(secs, 1),
        "skipped": skipped,
        "tail": (out.strip().splitlines() or [""])[-1][-200:],
        "output": out,
        "file_seconds": ci_shards.file_seconds_from_junit(xml_text, files, secs),
    }


#: DSN env vars whose database each pg-shard file gets fresh (``<database>_f<i>``).
PER_FILE_DB_ENV = ("ALERT_TEST_DSN",)


def _per_file_db_env(path: str, index: int) -> dict | None:
    """Environment for one pg-shard file: each PER_FILE_DB_ENV DSN re-pointed at a new database.

    The database is created by scripts/ensure_m2_test_database.py, which refuses any name that
    is not ``m2_shadow_test[_suffix]`` -- so this can never point a test at a live database.
    A DSN whose database does not fit that pattern is left unchanged.
    """
    sys.path.insert(0, str(REPO))
    from scripts.lib.m2_live_shadow_guard import TEST_DATABASE_RE, dsn_database, with_database

    env = dict(os.environ)
    changed = False
    for var in PER_FILE_DB_ENV:
        dsn = env.get(var, "").strip()
        base = dsn_database(dsn) if dsn else ""
        if not base or not TEST_DATABASE_RE.match(f"{base}_f{index}"):
            continue
        name = f"{base}_f{index}"
        r = subprocess.run(
            [sys.executable, "scripts/ensure_m2_test_database.py", "--name", name],
            cwd=str(REPO),
            capture_output=True,
            text=True,
        )
        print(f"[shard] {path}: {var} -> database {name} (ensure rc={r.returncode})", flush=True)
        if r.returncode == 0:
            env[var] = with_database(dsn, name)
            changed = True
    return env if changed else None


def run_shard(shard_arg: str, *, jobs: int, out: Path | None) -> int:
    import json
    import tempfile

    sys.path.insert(0, str(REPO))
    from scripts.lib import ci_shards

    sid, n = ci_shards.parse_shard_arg(shard_arg)
    plan = shard_plan(n)
    files = plan["shards"][sid]
    parallel, serial = plan_units(ci_shards.gates_for_files(GATES, files), hints=shard_hints())
    one_at_a_time = sid in (ci_shards.SERIAL_SHARD, ci_shards.PG_SHARD) or jobs <= 1
    print(
        f"[shard] {sid}/{n} files={len(files)} est={plan['loads'][sid]}s parallel_units={len(parallel)} "
        f"serial_units={len(serial)} jobs={1 if one_at_a_time else jobs} plan={plan['digest'][:12]}",
        flush=True,
    )
    t0 = time.monotonic()
    results = []

    def record(res):
        results.append(res)
        status = "PASS" if res["passed"] else "FAIL"
        print(
            f"[{status}] {res['gate']} ({len(res['files'])} files, {res['seconds']:.1f}s, "
            f"skipped={res['skipped']}) {res['tail'][-100:]}",
            flush=True,
        )
        if not res["passed"]:
            print(res["output"][-6000:], flush=True)

    with tempfile.TemporaryDirectory(prefix=f"cio-shard-{sid}-") as tmp:
        jobs_list = [(u, str(Path(tmp) / f"u{i}.xml")) for i, u in enumerate(parallel + serial)]
        par_jobs, ser_jobs = jobs_list[: len(parallel)], jobs_list[len(parallel) :]
        if one_at_a_time:
            # serial/pg: one pytest process PER FILE (a gate unit may hold several files that
            # share state), and in the pg shard each file gets its own fresh database for the
            # per-file DSN env vars (two alert-DB files sharing one database failed in CI run
            # 37957892733: "cannot drop columns from view").
            singles = [(name, [f]) for name, fs in parallel + serial for f in fs]
            for i, u in enumerate(singles):
                env = _per_file_db_env(u[1][0], i) if sid == ci_shards.PG_SHARD else None
                record(_run_unit_junit((u, str(Path(tmp) / f"f{i}.xml"), env)))
        else:
            with ThreadPoolExecutor(max_workers=jobs) as pool:
                for res in pool.map(_run_unit_junit, par_jobs):
                    record(res)
            for j in ser_jobs:
                record(_run_unit_junit(j))
    wall = time.monotonic() - t0
    for res in results:
        res.pop("output", None)
    manifest = ci_shards.build_manifest(
        shard=sid,
        n=n,
        sha=_git_value("rev-parse", "HEAD"),
        tree=_git_value("rev-parse", "HEAD^{tree}"),
        digest=plan["digest"],
        files=files,
        units=results,
        wall=wall,
    )
    out = out or Path(os.environ.get("RUNNER_TEMP") or tempfile.gettempdir()) / f"cio_shard_{sid}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    failed = sorted({r["gate"] for r in results if not r["passed"]})
    print(f"[timing] shard={sid}/{n} files={len(manifest['files'])} wall={wall:.0f}s manifest={out}", flush=True)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        try:
            with open(summary, "a", encoding="utf-8") as fh:
                fh.write(
                    f"## shard {sid}/{n}\n- files: {len(manifest['files'])}; wall {wall:.0f} s; "
                    f"skipped tests: {sum(r['skipped'] for r in results)}; failed gates: {failed or 'none'}\n"
                )
        except OSError:
            pass
    if failed:
        print(f"\nCIO SHARD {sid}/{n} FAILED: {failed}")
        return 1
    print(f"\nCIO SHARD {sid}/{n}: ALL UNITS PASS")
    return 0


def verify_shards(
    manifest_dir: Path, *, n: int, timings_out: Path | None = None, attestation_out: Path | None = None
) -> int:
    """The `ci-gate` aggregate: completeness + success across every shard, then the attestation."""
    import json

    sys.path.insert(0, str(REPO))
    from scripts.lib import ci_shards, tree_attested_promote

    manifests = []
    for p in sorted(Path(manifest_dir).rglob("cio_shard_*.json")):
        try:
            manifests.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            manifests.append({"schema": "unreadable", "shard": p.name})
    expected = ci_shards.registered_files(GATES, lambda p: (REPO / p).is_file())
    needs = json.loads(os.environ.get("CI_GATE_NEEDS") or "null")
    res = ci_shards.verify_manifests(
        manifests,
        expected_files=expected,
        n=n,
        expected_tree=_git_value("rev-parse", "HEAD^{tree}"),
        expected_digest=shard_plan(n)["digest"],
        needs=needs if isinstance(needs, dict) else None,
    )
    print(json.dumps({k: v for k, v in res.items() if k not in ("missing_files", "extra_files")}, sort_keys=True))
    for f in res["missing_files"][:50]:
        print(f"[ci-gate] MISSING (registered, not run by any shard): {f}")
    for f in res["extra_files"][:50]:
        print(f"[ci-gate] UNREGISTERED (run but not in GATES): {f}")
    for m in manifests:
        for u in m.get("units") or []:
            if u.get("no_tests"):
                print(
                    f"[ci-gate] NOTE no test functions collected (accepted, as in the fast profile): {u.get('files')}"
                )
    if timings_out:
        timings_out.parent.mkdir(parents=True, exist_ok=True)
        timings_out.write_text(
            json.dumps(ci_shards.merge_timings(manifests), indent=1, sort_keys=True) + "\n", encoding="utf-8"
        )
    if attestation_out:
        att = tree_attested_promote.build_attestation(
            _git_value,
            ok=res["ok"],
            run_id=os.environ.get("GITHUB_RUN_ID"),
            run_attempt=os.environ.get("GITHUB_RUN_ATTEMPT"),
            summary=res,
        )
        attestation_out.parent.mkdir(parents=True, exist_ok=True)
        attestation_out.write_text(json.dumps(att, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        try:
            with open(summary, "a", encoding="utf-8") as fh:
                fh.write(
                    f"## ci-gate\n- {'PASS' if res['ok'] else 'FAIL'}: {res['ran_files']} of "
                    f"{res['expected_files']} registered files ran across {n}+2 shards\n"
                    f"- errors: {res['errors'] or 'none'}\n- shard walls (s): {res['shard_walls']}\n"
                )
        except OSError:
            pass
    print("\nCI-GATE: " + ("PASS" if res["ok"] else "FAIL " + ", ".join(res["errors"])))
    return 0 if res["ok"] else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--profile", choices=("pr", "fast", "full"), default=_profile_from_env())
    ap.add_argument("--base", default=os.environ.get("CIO_CI_BASE", "origin/main"), help="pr profile: diff base")
    ap.add_argument("--include-worktree", action="store_true", help="pr profile: add uncommitted/untracked paths")
    ap.add_argument("--print-selection", action="store_true", help="pr profile: print the selection and exit")
    ap.add_argument("--changed", nargs="+", default=None, help="pr profile: use these paths instead of the git diff")
    ap.add_argument("--budget", type=float, default=None, help="pr profile: override budget_seconds (fast_check.sh)")
    ap.add_argument(
        "--no-tail",
        action="store_true",
        help="skip the docs-index/manifest tail checks (fast_check.sh: the candidate manifest step writes files)",
    )
    ap.add_argument("--jobs", type=int, default=_default_jobs())
    ap.add_argument("--list-plan", action="store_true", help="print the fast-profile plan and exit")
    ap.add_argument(
        "--write-duration-hints",
        action="store_true",
        help="time every parallel-safe registered file (one pytest per file) and rewrite the hints file",
    )
    ap.add_argument("--shard", default=None, help="run shard I/N (or serial/N, pg/N) of every registered file")
    ap.add_argument("--shard-out", type=Path, default=None, help="--shard: manifest path")
    ap.add_argument("--print-shard-plan", type=int, default=None, metavar="N", help="print the N-shard plan")
    ap.add_argument("--verify-shards", type=Path, default=None, metavar="DIR", help="ci-gate: verify manifests")
    ap.add_argument("--shards", type=int, default=8, help="--verify-shards: shard count N")
    ap.add_argument("--timings-out", type=Path, default=None, help="--verify-shards: merged timing hints")
    ap.add_argument("--attestation-out", type=Path, default=None, help="--verify-shards: CiGateAttestation@v1")
    args = ap.parse_args(argv)

    os.chdir(REPO)
    os.environ.setdefault("TRADE_AI_CI", "1")
    os.environ.setdefault("CIO_TELEGRAM_INTERDICT", "1")
    # Ensure pytest interdicts telegram
    os.environ.setdefault("PYTEST_ADDOPTS", "")

    if args.write_duration_hints:
        return write_duration_hints(jobs=args.jobs)
    if args.shard:
        return run_shard(args.shard, jobs=args.jobs, out=args.shard_out)
    if args.verify_shards:
        return verify_shards(
            args.verify_shards, n=args.shards, timings_out=args.timings_out, attestation_out=args.attestation_out
        )
    if args.print_shard_plan:
        import json

        plan = shard_plan(args.print_shard_plan)
        print(
            json.dumps(
                {
                    "n": plan["n"],
                    "digest": plan["digest"],
                    "loads": plan["loads"],
                    "counts": {k: len(v) for k, v in plan["shards"].items()},
                },
                sort_keys=True,
            )
        )
        return 0

    if args.list_plan:
        parallel, serial = plan_units(GATES)
        print(f"parallel_units={len(parallel)} serial_gates={len(serial)}")
        for name, files in serial:
            print(f"  serial: {name} ({len(files)} files)")
        return 0

    t0 = time.monotonic()
    gates, profile = GATES, args.profile
    if profile == "pr":
        gates, profile = select_pr_gates(
            args.base, include_worktree=args.include_worktree, budget=args.budget, changed=args.changed
        )
        if args.print_selection:
            return 0
    failed = run_gates(gates, profile=profile, jobs=args.jobs)
    print(f"[timing] gates profile={args.profile} jobs={args.jobs} wall={time.monotonic() - t0:.0f}s", flush=True)

    if args.no_tail:
        if failed:
            print(f"\nCIO HARDENING CI FAILED: {failed}")
            return 1
        print("\nCIO HARDENING CI: ALL SELECTED GATES PASS (tail checks skipped)")
        return 0

    # Phase 2: never regenerate the committed manifest before validating it.
    # 1) check-committed — read-only integrity of the files in git
    # 2) candidate — write a generated copy to an isolated dir and show the diff
    print("[RUN]  docs_index_drift")
    dix = subprocess.run(
        [sys.executable, "scripts/report_docs_inventory.py", "--check-index"],
        cwd=str(REPO),
    )
    if dix.returncode != 0:
        failed.append("docs_index_drift")
        print("[FAIL] docs_index_drift — docs/INDEX.md does not match regenerate")
    else:
        print("[PASS] docs_index_drift")

    print("[RUN]  validate_committed_manifest")
    chk = subprocess.run(
        [sys.executable, "scripts/cio_release_manifest.py", "check-committed"],
        cwd=str(REPO),
    )
    if chk.returncode != 0:
        failed.append("validate_committed_manifest")
        print("[FAIL] validate_committed_manifest — committed RELEASE_MANIFEST failed integrity")
    else:
        print("[PASS] validate_committed_manifest")

    print("[RUN]  generate_candidate_manifest")
    cand = REPO / "data" / "audit" / "manifest_candidate"
    if os.environ.get("GITHUB_ACTIONS", "").lower() in ("1", "true"):
        cand = Path(os.environ.get("RUNNER_TEMP") or "/tmp") / "cio_manifest_candidate"
    gen = subprocess.run(
        [sys.executable, "scripts/cio_release_manifest.py", "candidate", "--out-dir", str(cand)],
        cwd=str(REPO),
    )
    if gen.returncode != 0:
        failed.append("generate_candidate_manifest")
        print("[FAIL] generate_candidate_manifest")
    else:
        print(f"[PASS] generate_candidate_manifest → {cand}")
        committed = REPO / "docs" / "investment-office" / "RELEASE_MANIFEST.json"
        generated = cand / "RELEASE_MANIFEST.json"
        if committed.is_file() and generated.is_file():
            diff = subprocess.run(
                ["diff", "-u", str(committed), str(generated)],
                cwd=str(REPO),
                capture_output=True,
                text=True,
            )
            if diff.returncode == 0:
                print("[info] candidate == committed pin")
            else:
                print(
                    "[info] candidate DIFFERS from committed pin (informational; not a substitute for check-committed)"
                )
                print((diff.stdout or "")[:2000])

    if failed:
        print(f"\nCIO HARDENING CI FAILED: {failed}")
        return 1
    print("\nCIO HARDENING CI: ALL GATES PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
