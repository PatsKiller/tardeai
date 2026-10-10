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

    python3 scripts/check_n8n_import_ready.py "$STAGE" --relay-url http://172.19.0.1:18092
    python3 scripts/check_n8n_import_ready.py "$STAGE" --relay-url http://172.19.0.1:18092 --json

Exit 0 every file passes, 1 any file refused, 2 cannot run (missing path, unreadable JSON, no allowlist).
"""

from __future__ import annotations

import argparse
import json
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


def exit_code(results: list[dict]) -> int:
    return 0 if all(r["ok"] for r in results) else 1


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="+", help="workflow JSON files or a staging directory")
    ap.add_argument("--relay-url", required=True, help="the granted relay base URL, e.g. http://172.19.0.1:18092")
    ap.add_argument("--allowlist", default=str(ALLOWLIST))
    ap.add_argument("--known-id", action="append", default=[], help="workflow id already in n8n (errorWorkflow)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        results = check_paths(
            [Path(p) for p in a.paths],
            relay_url=a.relay_url,
            allowlisted=load_allowlisted_lanes(Path(a.allowlist)),
            known_ids=set(a.known_id),
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
                },
                indent=1,
            )
        )
    else:
        for r in results:
            mark = "OK     " if r["ok"] else "REFUSED"
            extra = ", ".join(r["refusals"] + [f"warn:{w}" for w in r["warnings"]])
            print(f"{mark} {r['id']} {r['name']}  {extra}")
        print(f"{len(results)} checked, {sum(not r['ok'] for r in results)} refused")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
