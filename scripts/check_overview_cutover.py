#!/usr/bin/env python3
"""INC-OVW / OP-041: refuse to cut over to a STORED-ONLY overview reader without proof that it can be fed.

On 2026-11-14 R7 shipped a reader that never computes on top of a producer scheduled weekdays 04:00-20:00 ET.
Nothing at activation time asked whether the producer could keep that reader alive, so the first Saturday the
header answered UNKNOWN. This gate is the missing question, asked at the moment a release is activated:

    a stored-only reader is admitted only when ALL of these are true
      1. the 24/7 schedule contract holds (last-good window > max gap + retries + dispatch delay),
      2. the projection on disk is usable: right schema, status ok, a dict body, inside last-good, not from
         the future, built by THIS release (code_identity == the release's sha),
      3. the body carries SOURCE clocks (so an old body can say how old its DATA is), none from the future,
      4. an ACTUAL n8n lane receipt exists on THIS release: LaneRunReceipt@v2 with code_sha == the release's
         sha, status ok, and an ok_at inside one max gap (+ the allowed dispatch delay).

An INLINE-FALLBACK reader (R6 and earlier: ``_overview_served`` passes ``_overview_with_today_move`` to
``serve``) is admitted without those proofs - the projection is an optimisation there, not the answer - so a
rollback is never blocked by this gate's own state. The facts are still printed as warnings.

Exit codes: 0 admitted, 2 refused, 3 the gate could not read what it needs (a refusal too: fail closed).

Read-only: this script reads files and computes. It starts nothing, dispatches nothing, writes nothing.
``MBI_BEHAVIOR = 0``.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

#: The deploy script invokes this by absolute path (``$RELEASE_DIR/scripts/check_overview_cutover.py``), so sys.path[0]
#: is the release's ``scripts/``, not the repo root. Put the release root first so ``scripts.lib`` resolves here and
#: the fallback to ``lib`` still works when the checkout is imported as a plain directory.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

READER_STORED_ONLY = "stored_only"
READER_INLINE = "inline_fallback"
READER_UNKNOWN = "unknown"

#: a source clock may lead this host's clock by this much before it is a clock problem (NTP, a producer on a
#: slightly different clock). Mirrors overview_projection.FUTURE_TOLERANCE_S with room for a slow write.
SOURCE_CLOCK_FUTURE_TOLERANCE_S = 300.0

_SERVED_FN = re.compile(r"^def _overview_served\(.*?(?=^def |\Z)", re.S | re.M)
_SERVE_CALL = re.compile(r"\bserve\(\s*([^,\n)]*)", re.S)
_WINDOW = re.compile(r"^LAST_GOOD_MAX_S\s*=\s*([\d.]+)", re.M)


def release_window(release_dir: Path) -> float | None:
    """The last-good window the RELEASE will run with, read from the release's own module - or None.

    This is deliberately not the contract's ``last_good_max_s``: that number describes the tree the gate runs in,
    and on a fold tree the two can differ (R8 has no window at all, and the patch that raises R7's window travels
    separately). The question at cutover is what the code being activated will do, so the code being activated is
    what gets read. ``read()`` takes the window as a default argument, so the constant is the loaded value.
    """
    try:
        src = (Path(release_dir) / "scripts" / "lib" / "overview_projection.py").read_text(encoding="utf-8")
    except OSError:
        return None
    found = _WINDOW.search(src)
    return float(found.group(1)) if found else None


def reader_mode(api_v2_source: str) -> tuple[str, str]:
    """(mode, evidence) read from the SERVED route's source, not from a docstring.

    stored_only     ``serve(None, …)``                      - the module never computes
    inline_fallback ``serve(_overview_with_today_move, …)`` - the module computes when it cannot serve
    unknown         the function is not there, or its first argument is neither of those
    The import-failure branch ``if _overview_projection is None: return _overview_with_today_move()`` exists in
    every version and is NOT a serve() argument, so it is deliberately not a match.
    """
    found = _SERVED_FN.search(api_v2_source)
    if not found:
        return READER_UNKNOWN, "_overview_served not found"
    body = found.group(0)
    call = _SERVE_CALL.search(body)
    if not call:
        return READER_UNKNOWN, "no serve( call inside _overview_served"
    first = call.group(1).strip()
    if first == "None":
        return READER_STORED_ONLY, "serve(None, …)"
    if "_overview_with_today_move" in first:
        return READER_INLINE, f"serve({first}, …)"
    return READER_UNKNOWN, f"serve({first}, …) is neither None nor the inline compute"


def _json(path: Path) -> tuple[dict | None, str | None]:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, "missing"
    except (OSError, ValueError):
        return None, "unreadable"
    return (doc if isinstance(doc, dict) else None), (None if isinstance(doc, dict) else "not_an_object")


def _release_sha(release_dir: Path) -> str | None:
    for name in ("BUILD_SHA", "GIT_SHA", "SOURCE_COMMIT"):
        try:
            sha = (release_dir / name).read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if sha:
            return sha
    return None


def _default_state_root() -> Path | None:
    import os

    for key in ("TRADEAI_STATE_ROOT", "TRADEAI_PERSISTENT_STATE_ROOT"):
        raw = os.environ.get(key)
        if raw:
            return Path(raw)
    try:
        from scripts.lib.canonical_store_registry import production_state_root
    except ImportError:  # pragma: no cover
        try:
            from lib.canonical_store_registry import production_state_root
        except ImportError:
            return None
    try:
        return Path(production_state_root())
    except Exception:  # noqa: BLE001 - a missing root is a refusal, not a crash
        return None


def _epoch(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def _receipt_checks(receipt_path: Path, sha: str | None, now: float, max_gap_s: float, delay_s: float) -> list[dict]:
    """Every refusal the lane receipt produces. Empty list = an actual run on this release, recently."""
    doc, why = _json(receipt_path)
    if doc is None:
        return [{"code": "no_receipt", "detail": f"{receipt_path}: {why}"}]
    out: list[dict] = []
    if doc.get("schema") != "LaneRunReceipt@v2":
        out.append({"code": "receipt_schema", "detail": f"schema {doc.get('schema')!r}"})
    if doc.get("status") != "ok":
        out.append({"code": "receipt_failed",
                    "detail": f"status {doc.get('status')!r} (consecutive_failures {doc.get('consecutive_failures')!r})"})
    if sha:
        got = str(doc.get("code_sha") or "")
        if got != sha:
            out.append({"code": "receipt_code_mismatch", "detail": f"code_sha {got or '(none)'} != release {sha}"})
    ok_at = _epoch(doc.get("ok_at") or doc.get("finished_at"))
    if ok_at is None:
        out.append({"code": "receipt_no_clock", "detail": "no ok_at/finished_at"})
    elif now - ok_at > max_gap_s + delay_s:
        out.append({"code": "receipt_stale",
                    "detail": f"last ok {round(now - ok_at, 1)} s ago > {max_gap_s + delay_s:.0f} s "
                              f"(one max gap plus the allowed dispatch delay)"})
    elif ok_at - now > SOURCE_CLOCK_FUTURE_TOLERANCE_S:
        out.append({"code": "receipt_clock_skew", "detail": f"ok_at {round(ok_at - now, 1)} s in the future"})
    return out


def _projection_checks(projection_path: Path, sha: str | None, now: float,
                       last_good: float) -> list[dict]:
    """Every refusal the projection document produces. Empty list = usable, compatible, clocked."""
    doc, why = _json(projection_path)
    if doc is None:
        return [{"code": "projection_missing", "detail": f"{projection_path}: {why}"}]
    out: list[dict] = []
    if doc.get("schema") != "OverviewProjection@v1":
        out.append({"code": "projection_schema", "detail": f"schema {doc.get('schema')!r}"})
    if doc.get("status") != "ok":
        out.append({"code": "projection_status", "detail": f"status {doc.get('status')!r}"})
    if not isinstance(doc.get("body"), dict):
        out.append({"code": "projection_body", "detail": "body is not an object"})
    if sha:
        got = str(doc.get("code_identity") or "")
        if got != f"sha:{sha}":
            out.append({"code": "projection_code_mismatch",
                        "detail": f"code_identity {got or '(none)'} != sha:{sha} (built by another release)"})
    built = _epoch(doc.get("built_at_epoch", doc.get("built_at")))
    if built is None:
        out.append({"code": "projection_no_clock", "detail": "no built_at"})
    elif built - now > SOURCE_CLOCK_FUTURE_TOLERANCE_S:
        out.append({"code": "projection_clock_skew", "detail": f"built_at {round(built - now, 1)} s in the future"})
    elif now - built > last_good:
        out.append({"code": "projection_expired",
                    "detail": f"built {round(now - built, 1)} s ago > last-good {last_good:.0f} s"})
    clocks = doc.get("source_clocks")
    if not isinstance(clocks, dict) or not isinstance(clocks.get("clocks"), dict) or not clocks["clocks"]:
        out.append({"code": "source_clocks_absent",
                    "detail": "the document carries no source clocks; a reader could not tell DATA age from BUILD age"})
    else:
        for path, value in clocks["clocks"].items():
            stamp = _epoch(value)
            if stamp is not None and stamp - now > SOURCE_CLOCK_FUTURE_TOLERANCE_S:
                out.append({"code": "source_clock_in_future",
                            "detail": f"{path} = {value!r} is {round(stamp - now, 1)} s in the future"})
    return out


def check(*, release_dir: Path, projection_path: Path | None = None, receipt_path: Path | None = None,
          state_root: Path | None = None, sha: str | None = None, now: float | None = None,
          contract_doc: Mapping[str, Any] | None = None, wait_s: float = 0.0,
          sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.time) -> dict:
    """The verdict. Pure apart from the files it reads and the optional bounded wait."""
    try:
        from scripts.lib import overview_lane_contract as C
    except ImportError:  # pragma: no cover - invoked with the release's scripts/ on sys.path
        from lib import overview_lane_contract as C

    now = clock() if now is None else now
    release_dir = Path(release_dir)
    state_root = Path(state_root) if state_root is not None else _default_state_root()
    projection_path = Path(projection_path) if projection_path is not None else (
        Path(state_root) / "data" / "runtime" / "overview_projection.json" if state_root else None)
    receipt_path = Path(receipt_path) if receipt_path is not None else (
        Path(state_root) / "data" / "runtime" / "overview-projection_last.json" if state_root else None)

    refusals: list[dict] = []
    warnings: list[dict] = []
    try:
        api_src = (release_dir / "scripts" / "api_v2.py").read_text(encoding="utf-8")
    except OSError as exc:
        return {"admit": False, "reader_mode": READER_UNKNOWN, "reader_evidence": f"api_v2.py unreadable: {exc}",
                "refusals": [{"code": "release_unreadable", "detail": str(exc)}], "warnings": [],
                "at": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(), "checks": {}}
    mode, evidence = reader_mode(api_src)
    sha = sha or _release_sha(release_dir)
    contract_error: str | None = None
    try:
        doc = dict(contract_doc or C.contract())
    except Exception as exc:  # noqa: BLE001 - an unreadable contract is handled below, per reader mode
        doc = None
        contract_error = f"{type(exc).__name__}: {exc}"[:300]

    checks: dict[str, Any] = {"reader_mode": mode, "reader_evidence": evidence, "release_sha": sha}
    if doc is not None:
        checks["contract"] = {k: doc.get(k) for k in ("reader", "max_gap_s", "floor_s", "last_good_max_s",
                                                      "headroom_s", "schedules", "ok")}

    if mode == READER_UNKNOWN:
        refusals.append({"code": "reader_mode_unknown", "detail": evidence})

    if doc is not None and mode in (READER_STORED_ONLY, READER_INLINE) and doc.get("reader") not in (None, "", mode):
        # The contract block above is the TREE's; the verdict is the RELEASE's. Name the skew rather than let a
        # reader of the log mistake the tree's window for the one being activated (R7 tree judging an R6 release).
        warnings.append({"code": "contract::reader_skew",
                         "detail": f"this tree describes a {doc.get('reader')} reader, but the release is {mode}: "
                                   f"its window and headroom do not govern this release"})

    if mode == READER_STORED_ONLY and doc is not None:
        # The window that matters is the RELEASE's: the fold tree's contract may know nothing about it (R8 has no
        # window) or carry a different one (the patch travels separately). Judge what is being activated.
        window = release_window(release_dir)
        checks["release_window_s"] = window
        if window is None:
            refusals.append({"code": "release_window_absent",
                             "detail": "this release serves stored-only but its overview_projection.py declares no "
                                       "LAST_GOOD_MAX_S: no window to judge, so the release cannot be admitted"})
        elif window <= float(doc["floor_s"]):
            detail = (f"the release's LAST_GOOD_MAX_S = {window:.0f} s <= the derived floor {doc['floor_s']:.0f} s "
                      f"(max gap {doc['max_gap_s']:.0f} + retries + allowed delay): a scheduled outage would outlive "
                      f"the body")
            if doc.get("patched_last_good_max_s"):
                detail += f"; the verified patch {doc['patch_rel']} sets {doc['patched_last_good_max_s']:.0f} s"
            refusals.append({"code": "contract_unsatisfied", "detail": detail})
        if projection_path is None or receipt_path is None:
            refusals.append({"code": "no_state_root",
                             "detail": "a stored-only reader needs a projection and a receipt to point at"})
        else:
            last_good = window

            def evaluate() -> list[dict]:
                if last_good is None:
                    return [{"code": "release_window_absent", "detail": "no window: cannot judge the body"}]
                return _projection_checks(projection_path, sha, now, float(last_good)) + \
                    _receipt_checks(receipt_path, sha, now, float(doc["max_gap_s"]), float(doc["dispatch_delay_s"]))

            found = evaluate()
            if found and wait_s > 0:
                deadline = clock() + wait_s
                while found and clock() < deadline:
                    sleep(min(15.0, max(1.0, deadline - clock())))
                    now = clock()
                    found = evaluate()
            refusals.extend(found)
    elif mode == READER_INLINE:
        warnings.append({"code": "inline_fallback_reader",
                         "detail": "this release computes inline when it cannot serve the projection; the projection "
                                   "checks are informational, so a rollback is never blocked by this gate"})
        if projection_path is not None and doc is not None:
            # informational only: an inline reader has no window, so age is not a refusal - report it as the
            # contract's floor rather than as an expiry the reader could never produce
            for refusal in _projection_checks(projection_path, None, now, float(doc["floor_s"])):
                warnings.append({"code": "projection::" + refusal["code"], "detail": refusal["detail"]})

    if contract_error is not None:
        (refusals if mode != READER_INLINE else warnings).append(
            {"code": "contract_unreadable" if mode != READER_INLINE else "contract::contract_unreadable",
             "detail": f"this release's reader is {mode}, so the lane contract is informational here: {contract_error}"})

    return {
        "admit": not refusals,
        "reader_mode": mode,
        "reader_evidence": evidence,
        "release_sha": sha,
        "refusals": refusals,
        "warnings": warnings,
        "at": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
        "checks": checks,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--release-dir", help="the candidate release directory (default: $RELEASES_BASE/CURRENT)")
    ap.add_argument("--state-root", help="state root holding data/runtime/ (default: TRADEAI_STATE_ROOT)")
    ap.add_argument("--projection", help="override the projection path")
    ap.add_argument("--receipt", help="override the lane receipt path")
    ap.add_argument("--sha", help="the candidate's code identity (default: BUILD_SHA/GIT_SHA in the release)")
    ap.add_argument("--wait-s", type=float, default=0.0,
                    help="wait up to this many seconds for a lane receipt on this release (stored-only readers)")
    ap.add_argument("--json", action="store_true", help="machine-readable verdict")
    args = ap.parse_args(argv)

    release_dir = Path(args.release_dir) if args.release_dir else None
    if release_dir is None:
        import os
        # the deploy script always passes --release-dir; this default mirrors current_bound_units.RELEASES_BASE
        base = (os.environ.get("TRADEAI_RELEASES_BASE") or os.environ.get("RELEASES_BASE")
                or Path.home() / "trade-ai-releases" / "portfolio-server")
        release_dir = Path(base) / "CURRENT"
    verdict = check(
        release_dir=release_dir,
        projection_path=Path(args.projection) if args.projection else None,
        receipt_path=Path(args.receipt) if args.receipt else None,
        state_root=Path(args.state_root) if args.state_root else None,
        sha=args.sha, wait_s=args.wait_s,
    )
    if args.json:
        print(json.dumps(verdict, indent=1, sort_keys=True))
    else:
        print(f"overview cutover gate @ {verdict['at']}")
        print(f"  release   : {release_dir} ({verdict['release_sha'] or 'no sha'})")
        print(f"  reader    : {verdict['reader_mode']} — {verdict['reader_evidence']}")
        c = verdict["checks"].get("contract") or {}
        if c:
            if c.get("last_good_max_s") is None:
                print(f"  contract  : max_gap {c['max_gap_s']:.0f} s, floor {c['floor_s']:.0f} s, "
                      f"last-good n/a (reader {c.get('reader')!r})")
            else:
                print(f"  contract  : max_gap {c['max_gap_s']:.0f} s + floor {c['floor_s']:.0f} s "
                      f"< last-good {c['last_good_max_s']:.0f} s (headroom {c['headroom_s']:.0f} s) "
                      f"ok={c['ok']} reader={c.get('reader')!r}")
            print(f"  schedule  : {' + '.join(c['schedules'])}")
        for w in verdict["warnings"]:
            print(f"  WARN  {w['code']}: {w['detail']}")
        for r in verdict["refusals"]:
            print(f"  REFUSED {r['code']}: {r['detail']}")
        print("  ADMIT" if verdict["admit"] else "  REFUSED — see the refusals above")
    if verdict["admit"]:
        return 0
    return 2 if verdict["refusals"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
