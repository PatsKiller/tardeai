#!/usr/bin/env python3
"""Refuse an n8n workflow JSON that is not fit to import — run before every `n8n import:workflow`.

2026-10-10 (n8n install audit V8 F3): premarket-data-pipeline-shadow (f4553ff360e21a9f) was imported straight
from generated/pending/ without the --relay-url render, so its Set node still held http://RELAY_HOST:18092 and the
operator's manual run failed `getaddrinfo EAI_AGAIN relay_host`. Its lane is not in config/n8n_run_allowlist.json,
so the gateway would have refused it even with the right host. 16 such workflows were in n8n; nothing checked a
file before import.

Read-only. Takes files or directories; a directory is scanned the way `n8n import:workflow --separate` reads it
(top-level *.json only, INDEX.json skipped). A file is refused for:

  placeholder_unsubstituted  the generator placeholder host RELAY_HOST is still in it
  relay_url_mismatch         an http(s) URL whose host:port is not the granted relay (--relay-url)
  active_in_file             "active": true — import inactive; activation is its own grant (AGENTS §23.2/§23.11)
  lane_not_allowlisted       meta.lane_id is not a config/n8n_run_allowlist.json lane (the gateway refuses it)
  no_lane_or_kind            neither meta.lane_id (per-lane) nor meta.kind (generic) — unknown provenance
  error_workflow_unknown     settings.errorWorkflow names an id neither in this import set nor in --known-id

and warned (not refused) for save_manual_executions_true (overrides EXECUTIONS_DATA_SAVE_MANUAL_EXECUTIONS=false).

The mandatory §23.24 promotion gate (2026-10-18 campaign, closing the opt-in gap from audit DD16)
(``scripts/check_n8n_workflow_framework.py --gate activation``) runs on every statically admissible file and refuses each one that is not
activation-eligible (``framework_gate``): any element FAIL, PARTIAL on a critical element, platform element not
PASS, or a runtime obligation without evidence (``--runtime-evidence``), unless an operator exception names it
(``--exceptions``). Existing ``--framework-gate activation`` callers remain compatible; omitting it never skips the gate.

Platform elements FW-P1..P6 (n8n platform hardening packet 2026-10-22): the gate reads them from ``--platform-facts``
(default ``$N8N_PLATFORM_FACTS``, else the committed 2026-10-15 measurement), or with ``--probe-host`` measures them
now from this host (``scripts/probe_n8n_platform_facts.py``, read-only). An element PASSes only from a fresh host
probe; a cited file caps at PARTIAL. Every run prints each element, its status, its evidence and where the facts
came from (``platform`` / ``platform_source`` in ``--json``).

    python3 scripts/check_n8n_import_ready.py "$STAGE" --relay-url http://172.19.0.1:18092
    python3 scripts/check_n8n_import_ready.py "$STAGE" --relay-url http://172.19.0.1:18092 --json
    python3 scripts/check_n8n_import_ready.py "$STAGE" --relay-url http://172.19.0.1:18092 --probe-host

Exit 0 every file passes, 1 any file refused, 2 cannot run (missing path, unreadable JSON, no allowlist).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Iterable, Optional

ROOT = Path(__file__).resolve().parent.parent
ALLOWLIST = ROOT / "config" / "n8n_run_allowlist.json"
PLACEHOLDER_HOST = "RELAY_HOST"
URL_RE = re.compile(r"https?://([^/\"'\s\\]+)")
NO_CONSUMER_REASON = (
    "Operator pre-import step (docs/implementation/n8n-parallel/17-n8n-operating-model-20261008.md §5.3)."
)


class CannotRun(Exception):
    pass


def load_allowlisted_lanes(path: Path = ALLOWLIST) -> set[str]:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CannotRun(f"allowlist unreadable: {path}: {exc}") from exc
    return {str(lane["lane_id"]) for lane in doc.get("lanes", []) if lane.get("lane_id")}


def _host_port(url: str) -> str:
    m = URL_RE.match(url)
    return m.group(1).lower() if m else url.lower()


def collect_files(paths: Iterable[Path]) -> list[Path]:
    files: list[Path] = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            files.extend(sorted(f for f in p.glob("*.json") if f.name != "INDEX.json"))
        elif p.is_file():
            files.append(p)
        else:
            raise CannotRun(f"no such file or directory: {p}")
    return files


def check_doc(doc: dict, *, relay_url: str, allowlisted: set[str], known_ids: set[str]) -> tuple[list[str], list[str]]:
    refusals: list[str] = []
    warnings: list[str] = []
    text = json.dumps(doc.get("nodes") or []) + json.dumps(doc.get("connections") or {})
    if PLACEHOLDER_HOST in text:
        refusals.append("placeholder_unsubstituted")
    want = _host_port(relay_url)
    if any(h != want for h in (m.lower() for m in URL_RE.findall(text))):
        refusals.append("relay_url_mismatch")
    if doc.get("active") is True:
        refusals.append("active_in_file")
    meta = doc.get("meta") or {}
    lane = meta.get("lane_id")
    if lane:
        if str(lane) not in allowlisted:
            refusals.append("lane_not_allowlisted")
    elif not meta.get("kind"):
        refusals.append("no_lane_or_kind")
    settings = doc.get("settings") or {}
    err = settings.get("errorWorkflow")
    if err and str(err) not in known_ids:
        refusals.append("error_workflow_unknown")
    if settings.get("saveManualExecutions") is True:
        warnings.append("save_manual_executions_true")
    return sorted(set(refusals)), warnings


def check_paths(
    paths: Iterable[Path], *, relay_url: str, allowlisted: set[str], known_ids: Optional[set[str]] = None
) -> list[dict]:
    files = collect_files(paths)
    docs: list[tuple[Path, dict]] = []
    for f in files:
        try:
            docs.append((f, json.loads(f.read_text(encoding="utf-8"))))
        except (OSError, ValueError) as exc:
            raise CannotRun(f"unreadable workflow JSON: {f}: {exc}") from exc
    ids = set(known_ids or set()) | {str(d.get("id")) for _, d in docs if d.get("id")}
    results = []
    for f, doc in docs:
        refusals, warnings = check_doc(doc, relay_url=relay_url, allowlisted=allowlisted, known_ids=ids)
        results.append(
            {
                "file": str(f),
                "id": doc.get("id"),
                "name": doc.get("name"),
                "ok": not refusals,
                "refusals": refusals,
                "warnings": warnings,
            }
        )
    return results


PLATFORM_ENV = "N8N_PLATFORM_FACTS"


def load_platform_facts(
    path: Optional[str] = None, *, probe_host: bool = False, prober=None
) -> tuple[Optional[dict], dict]:
    """(facts, source) for the FW-P elements: a live host probe, an explicit file, $N8N_PLATFORM_FACTS, or the
    committed measurement — in that order. A probe or file that cannot be read is CannotRun (fail closed)."""
    sys.path.insert(0, str(ROOT / "scripts"))
    if probe_host:
        try:
            if prober is None:
                import probe_n8n_platform_facts as P  # noqa: PLC0415

                prober = P.probe
            facts = prober()
        except Exception as exc:  # noqa: BLE001 — a probe that cannot run never reads as a pass
            raise CannotRun(f"host probe cannot run: {type(exc).__name__}: {exc}") from exc
        return facts, {"kind": "host_probe", "path": None, "probed_at": facts.get("probed_at")}
    chosen = path or os.environ.get(PLATFORM_ENV) or None
    import check_n8n_workflow_framework as F  # noqa: PLC0415

    p = Path(chosen) if chosen else ROOT / F.DEFAULT_PLATFORM
    if not p.exists():
        if chosen:
            raise CannotRun(f"platform facts not found: {p}")
        return None, {"kind": "missing", "path": str(p)}
    try:
        facts = F._load(p)
    except (OSError, ValueError) as exc:
        raise CannotRun(f"platform facts unreadable: {p}: {exc}") from exc
    if facts.get("schema") != F.PLATFORM_FACTS_SCHEMA:
        raise CannotRun(f"platform facts {p}: not {F.PLATFORM_FACTS_SCHEMA}")
    return facts, {
        "kind": facts.get("source_kind") or "cited",
        "path": str(p),
        "probed_at": facts.get("probed_at") or facts.get("as_of"),
    }


def platform_report(facts: Optional[dict]) -> Optional[dict]:
    if facts is None:
        return None
    import check_n8n_workflow_framework as F  # noqa: PLC0415

    return F.score_platform(facts)


def apply_framework_gate(
    results: list[dict],
    *,
    runtime_evidence: Optional[str] = None,
    exceptions: Optional[str] = None,
    platform_facts: Optional[dict] = None,
    platform_given: bool = False,
) -> None:
    """Refuse (``framework_gate``) every file the §23.24 activation gate does not pass. Any error is CannotRun."""
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import check_n8n_workflow_framework as F  # noqa: PLC0415

        ctx = F.build_context(ROOT)
        if platform_given:
            platform = platform_facts
        else:
            platform = F._load(ROOT / F.DEFAULT_PLATFORM) if (ROOT / F.DEFAULT_PLATFORM).exists() else None
        ev = F._load_optional(runtime_evidence, F.RUNTIME_EVIDENCE_SCHEMA)
        exc = F._load_optional(exceptions, F.EXCEPTIONS_SCHEMA).get("exceptions") or []
        report = F.build_report(
            [(Path(r["file"]), None) for r in results],
            ctx,
            platform,
            source="import guard",
            gate="activation",
            runtime_evidence=ev,
            exceptions=exc,
        )
    except Exception as exc_:  # noqa: BLE001 — fail closed: a gate that cannot run refuses the import
        raise CannotRun(f"framework gate cannot run: {type(exc_).__name__}: {exc_}") from exc_
    for r, row in zip(results, report["workflows"]):
        gate = row["activation_eligibility"]
        r["framework_gate"] = gate
        if not gate["eligible"]:
            r["refusals"] = sorted(set(r["refusals"]) | {"framework_gate"})
            r["ok"] = False


def exit_code(results: list[dict]) -> int:
    return 0 if all(r["ok"] for r in results) else 1


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="+", help="workflow JSON files or a staging directory")
    ap.add_argument("--relay-url", required=True, help="the granted relay base URL, e.g. http://172.19.0.1:18092")
    ap.add_argument("--allowlist", default=str(ALLOWLIST))
    ap.add_argument("--known-id", action="append", default=[], help="workflow id already in n8n (errorWorkflow)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument(
        "--framework-gate",
        choices=("activation",),
        default="activation",
        help="§23.24 activation gate (mandatory; retained for existing packet compatibility)",
    )
    ap.add_argument("--runtime-evidence", default=None, help="N8nFrameworkRuntimeEvidence@v1 for the gate")
    ap.add_argument("--exceptions", default=None, help="N8nFrameworkExceptions@v1 for the gate")
    ap.add_argument(
        "--platform-facts",
        default=None,
        help=f"N8nPlatformFacts@v1 for FW-P1..P6 (default ${PLATFORM_ENV}, else the committed 2026-10-15 measurement)",
    )
    ap.add_argument(
        "--probe-host",
        action="store_true",
        help="measure FW-P1..P6 on this host now (scripts/probe_n8n_platform_facts.py, read-only) instead of a file",
    )
    a = ap.parse_args(argv)
    try:
        results = check_paths(
            [Path(p) for p in a.paths],
            relay_url=a.relay_url,
            allowlisted=load_allowlisted_lanes(Path(a.allowlist)),
            known_ids=set(a.known_id),
        )
        facts, platform_source = load_platform_facts(a.platform_facts, probe_host=a.probe_host)
        platform = platform_report(facts)
        candidates = [row for row in results if row["ok"]]
        if candidates:
            apply_framework_gate(
                candidates,
                runtime_evidence=a.runtime_evidence,
                exceptions=a.exceptions,
                platform_facts=facts,
                platform_given=True,
            )
    except CannotRun as exc:
        print(f"n8n import guard CANNOT RUN: {exc}", file=sys.stderr)
        return 2
    rc = exit_code(results)
    if a.json:
        print(
            json.dumps(
                {
                    "schema": "N8nImportGuard@v1",
                    "files": results,
                    "refused": sum(not r["ok"] for r in results),
                    "checked": len(results),
                    "platform": platform,
                    "platform_source": platform_source,
                },
                indent=1,
            )
        )
    else:
        for r in results:
            mark = "OK     " if r["ok"] else "REFUSED"
            extra = ", ".join(r["refusals"] + [f"warn:{w}" for w in r["warnings"]])
            print(f"{mark} {r['id']} {r['name']}  {extra}")
        src = platform_source
        print(
            f"platform facts: {src['kind']}"
            + (f" {src['path']}" if src.get("path") else "")
            + (f" (as of {src['probed_at']})" if src.get("probed_at") else "")
        )
        for k, v in (platform or {}).items():
            print(f"  {k} {v['status'].upper():7s} {v['evidence']}")
        print(f"{len(results)} checked, {sum(not r['ok'] for r in results)} refused")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
