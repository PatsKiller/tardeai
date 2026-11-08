#!/usr/bin/env python3
"""lane_artifact_triage.py — map each remediation-catalogue, migration-tranche and writer-restoration item to a
lane of the one lane manifest (LaneManifest@v1), or archive it (LQ-20261107-1009, Fable audit #15).

Three config files carry per-lane drafts written before the manifest existed:

  config/n8n_remediation_catalogue.json   runtime heal actions, read by scripts/n8n_failure_diagnosis.py
  config/n8n_migration_tranches.json      the cron -> n8n program list, read by scripts/n8n_migration_board.py
  config/n8n_writer_restoration.json      W8 drafts for restoring absorbed writers, read by n8n_writer_restoration.py

An item MAPS when the manifest has its lane in a state the item can act on; otherwise it is ARCHIVED:

  catalogue, tranches   the lane must be able to run: ACTIVE or PAUSED. A heal action or a migration step for a
                        RETIRED or NEVER_SCHEDULED lane, or for a lane the manifest does not have, is dead.
  writer restoration    the file exists to restore retired writers, so any manifest row maps (RETIRED included).
                        A draft whose lane the manifest lacks but which a non-operative pending_changes proposal in
                        config/lane_registry.json still names is HELD, not archived: the proposal (mirrored in the
                        allowlist and contracts files) lists it, and archiving one side alone would split them.
                        Only a draft named by neither is archived.

Archived items are MOVED, never deleted: --apply writes them, with the manifest state that decided each one, to
config/archive/<stamp>/<file stem>.archived.json beside a README, and rewrites the live file without them (the
catalogue's summary is recomputed by the catalogue library; the tranche counts are recomputed here). Nothing under
scripts/ may read config/archive/ (tests/test_lane_artifact_triage_20261108.py is the tripwire).

Default is a dry run: the table goes to stdout as JSON (LaneArtifactTriage@v1) and nothing is written.
The manifest is built in memory from config/lane_registry.json + n8n_run_allowlist.json + n8n_health_contracts.json
(scripts/lib/lane_manifest.build_manifest); --manifest FILE reads a saved one instead.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib import lane_manifest as LM  # noqa: E402
from scripts.lib import n8n_remediation_catalogue as RC  # noqa: E402

SCHEMA = "LaneArtifactTriage@v1"
ARCHIVE_SCHEMA = "LaneArtifactArchive@v1"
RUNNABLE = frozenset({"ACTIVE", "PAUSED"})
ANY_ROW = frozenset(LM.STATES)
CATALOGUE = Path("config/n8n_remediation_catalogue.json")
TRANCHES = Path("config/n8n_migration_tranches.json")
WRITERS = Path("config/n8n_writer_restoration.json")
#: rel path -> (item kind, states that map, json indent the file is written with)
FILES: dict[Path, tuple[str, frozenset, int]] = {
    CATALOGUE: ("remediation_catalogue", RUNNABLE, 1),
    TRANCHES: ("migration_tranche", RUNNABLE, 1),
    WRITERS: ("writer_restoration", ANY_ROW, 2),
}


def manifest_states(manifest: Mapping[str, Any]) -> dict[str, str]:
    return {str(lane["id"]): str(lane["state"]) for lane in manifest.get("lanes") or []}


def pending_proposals(registry: Mapping[str, Any]) -> dict[str, str]:
    """{lane id: proposal key} for every lane a NON-operative registry pending_changes proposal names."""
    out: dict[str, str] = {}
    for key, prop in sorted((registry.get("pending_changes") or {}).items()):
        if isinstance(prop, Mapping) and prop.get("operative") is False:
            for lane in prop.get("lane_ids") or []:
                out.setdefault(str(lane), str(key))
    return out


def _verdict(lane_id: Any, states: Mapping[str, str], maps: frozenset,
             pending: Mapping[str, str] = {}) -> tuple[str, Optional[str], str]:  # noqa: B006 -- read-only default
    """(MAPPED|HELD|ARCHIVE, manifest state or None, why)."""
    state = states.get(str(lane_id)) if isinstance(lane_id, str) else None
    if state is None:
        if str(lane_id) in pending:
            return ("HELD", None, f"no manifest lane, but pending proposal {pending[str(lane_id)]} (not operative) "
                    "names it; archive only together with that proposal")
        return "ARCHIVE", None, "no manifest lane"
    if state in maps:
        return "MAPPED", state, f"manifest lane {state}"
    return "ARCHIVE", state, f"manifest lane {state}: nothing left to act on"


def triage_doc(rel: Path, doc: Mapping[str, Any], states: Mapping[str, str],
               pending: Mapping[str, str] = {}) -> list[dict[str, Any]]:  # noqa: B006 -- read-only default
    """One row per item: {file, kind, item, lane_id, verdict, manifest_state, why, [tranche]}."""
    kind, maps, _ = FILES[rel]
    rows: list[dict[str, Any]] = []

    def row(item: str, lane_id: Any, **extra: Any) -> None:
        verdict, state, why = _verdict(lane_id, states, maps, pending if rel == WRITERS else {})
        rows.append({"file": str(rel), "kind": kind, "item": item, "lane_id": lane_id, "verdict": verdict,
                     "manifest_state": state, "why": why, **extra})

    if rel == CATALOGUE:
        for e in doc.get("lanes") or []:
            row(str(e.get("lane_id")), e.get("lane_id"))
    elif rel == TRANCHES:
        for tname, tdoc in (doc.get("tranches") or {}).items():
            for e in tdoc.get("lanes") or []:
                row(f"{tname}/{e.get('lane_id')}", e.get("lane_id"), tranche=tname)
    elif rel == WRITERS:
        for w in doc.get("writers") or []:
            row(str(w.get("key")), w.get("lane_id"))
    return rows


def split_doc(rel: Path, doc: Mapping[str, Any], rows: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict]]:
    """(the live doc without the archived items, the archived items each with its triage row). Pure."""
    gone = {r["item"] for r in rows if r["verdict"] == "ARCHIVE"}
    why = {r["item"]: r for r in rows}
    live = copy.deepcopy(dict(doc))
    moved: list[dict[str, Any]] = []
    if rel == CATALOGUE:
        keep = []
        for e in live.get("lanes") or []:
            (moved.append({"triage": why[str(e.get("lane_id"))], "entry": e}) if str(e.get("lane_id")) in gone
             else keep.append(e))
        live["lanes"] = keep
        live["summary"] = RC.summarise(keep)
    elif rel == TRANCHES:
        for tname, tdoc in (live.get("tranches") or {}).items():
            keep = []
            for e in tdoc.get("lanes") or []:
                item = f"{tname}/{e.get('lane_id')}"
                (moved.append({"triage": why[item], "entry": e}) if item in gone else keep.append(e))
            tdoc["lanes"] = keep
        total = sum(len(t.get("lanes") or []) for t in live["tranches"].values())
        retained = sum(len(t.get("lanes") or []) for t in live["tranches"].values() if t.get("status"))
        if "lane_count" in live:
            live["lane_count"] = total
        if "retained_lane_count" in live:
            live["retained_lane_count"] = retained
        if "in_scope_lane_count" in live:
            live["in_scope_lane_count"] = total - retained
    elif rel == WRITERS:
        keep = []
        for w in live.get("writers") or []:
            (moved.append({"triage": why[str(w.get("key"))], "entry": w}) if str(w.get("key")) in gone
             else keep.append(w))
        live["writers"] = keep
    return live, moved


def render(doc: Mapping[str, Any], indent: int) -> str:
    return json.dumps(doc, indent=indent, ensure_ascii=False) + "\n"


def readme(stamp: str, archived: Mapping[str, list[dict]], now: str) -> str:
    lines = [f"# Archived lane drafts — {stamp}", "",
             "LQ-20261107-1009 (Fable audit #15). Each item below was mapped against the one lane manifest",
             "(LaneManifest@v1) by `scripts/ops/lane_artifact_triage.py` and had no lane it could act on, so it was",
             "MOVED here out of its live config file. Nothing was deleted: every archived JSON keeps the full original",
             "entry next to the triage row (manifest state and reason) that decided it.", "",
             "**Nothing may read this directory.** It is history, not config. `tests/test_lane_artifact_triage_20261108.py`",
             "fails if any file under `scripts/` names `config/archive/`.", "",
             "To restore an item: copy its `entry` back into the live file and give it a manifest lane first.", "",
             f"Archived at {now}.", "", "| file | archived | item | manifest state | why |", "|---|---|---|---|---|"]
    for rel, items in archived.items():
        for m in items:
            t = m["triage"]
            lines.append(f"| {rel} | {Path(rel).stem}.archived.json | {t['item']} | {t['manifest_state'] or '-'} | "
                         f"{t['why']} |")
    return "\n".join(lines) + "\n"


def triage(root: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    states = manifest_states(manifest)
    pending = pending_proposals(json.loads((root / "config" / "lane_registry.json").read_text(encoding="utf-8")))
    out: dict[str, Any] = {"rows": [], "docs": {}}
    for rel in FILES:
        doc = json.loads((root / rel).read_text(encoding="utf-8"))
        rows = triage_doc(rel, doc, states, pending)
        out["docs"][str(rel)] = doc
        out["rows"].extend(rows)
    return out


def build_manifest(root: Path, now: str) -> dict[str, Any]:
    names = ("lane_registry.json", "n8n_run_allowlist.json", "n8n_health_contracts.json")
    docs = [json.loads((root / "config" / n).read_text(encoding="utf-8")) for n in names]
    return LM.build_manifest(*docs, generated_at=now, sources={n: f"config/{n}" for n in names})


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--manifest", type=Path, help="a saved LaneManifest@v1 (default: built in memory)")
    ap.add_argument("--stamp", default=None, help="archive folder name (default lq1009-<UTC date>)")
    ap.add_argument("--now", default=None, help="aware ISO time to stamp the archive (default: now)")
    ap.add_argument("--apply", action="store_true", help="move archived items out of the live files")
    args = ap.parse_args(argv)
    root = args.root.resolve()
    now = args.now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    stamp = args.stamp or f"lq1009-{now[:10].replace('-', '')}"
    manifest = (json.loads(args.manifest.read_text(encoding="utf-8")) if args.manifest else build_manifest(root, now))
    t = triage(root, manifest)
    rows = t["rows"]
    counts: dict[str, dict[str, int]] = {}
    for r in rows:
        counts.setdefault(r["kind"], {"MAPPED": 0, "HELD": 0, "ARCHIVE": 0})[r["verdict"]] += 1
    archive_dir = Path("config") / "archive" / stamp
    report: dict[str, Any] = {"schema": SCHEMA, "generated_at": now, "mode": "apply" if args.apply else "dry-run",
                              "manifest_lanes": len(manifest.get("lanes") or []), "counts": counts,
                              "archive_dir": str(archive_dir), "wrote": [], "rows": rows}
    if args.apply:
        archived: dict[str, list[dict]] = {}
        for rel, (_, _, indent) in FILES.items():
            live, moved = split_doc(rel, t["docs"][str(rel)], [r for r in rows if r["file"] == str(rel)])
            if not moved:
                continue
            archived[str(rel)] = moved
            dest = root / archive_dir / f"{rel.stem}.archived.json"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(render({"schema": ARCHIVE_SCHEMA, "source": str(rel), "archived_at": now,
                                    "rule": sorted(FILES[rel][1]), "items": moved}, 1), encoding="utf-8")
            (root / rel).write_text(render(live, indent), encoding="utf-8")
            report["wrote"] += [str(archive_dir / dest.name), str(rel)]
        if archived:
            (root / archive_dir / "README.md").write_text(readme(stamp, archived, now), encoding="utf-8")
            report["wrote"].append(str(archive_dir / "README.md"))
    print(json.dumps(report, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
