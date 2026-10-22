#!/usr/bin/env python3
"""Render docs/architecture/DATA_DICTIONARY.md from config/data_source_authority.json (AGENTS.md §7A registry).

The registry is the source; the dictionary is a view. Nothing below is typed by hand:

    python scripts/render_data_dictionary.py            # write the document
    python scripts/render_data_dictionary.py --check    # exit 1 if the committed document is stale

What is rendered, and from where:

    Entities (one source each)   proposed_domains[] and domains[] rows that carry a dictionary block
    Field level                  data_dictionary.records (the CIO prospect) and data_dictionary.facts
    Other granted domains        domains[] without a dictionary block (pointer to docs/SOURCE_OF_TRUTH.md)
    Declared but missing         domains[].store_presence
    Canonical key and aliases    data_dictionary.canonical_key

Deterministic: no clock, no repository scan, no database. Measured counts are the registry's own dated
``measured`` snapshots; the live counts are what scripts/check_data_source_authority.py prints.

AUTHORITY: READ_ONLY_ADVISORY. Writes one file, only without --check. EXIT 0 ok · 1 stale · 2 could not run.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUTH = ROOT / "config" / "data_source_authority.json"
DOC = ROOT / "docs" / "architecture" / "DATA_DICTIONARY.md"
NO_CONSUMER_REASON = "renderer + CI drift check; ai_local_acceptance runs --check and reads the exit code."


def _cell(v) -> str:
    if v is None or v == "" or v == []:
        return "—"
    if isinstance(v, list):
        v = ", ".join(str(x) for x in v)
    return str(v).replace("|", "\\|").replace("\n", " ")


def _store(store: dict | None) -> str:
    if not isinstance(store, dict):
        return "—"
    if store.get("table"):
        return f"`{store['table']}` (table)"
    if store.get("file"):
        return f"`{store['file']}` (file)"
    return "—"


def _writer(row: dict) -> str:
    if row.get("writer"):
        return f"`{row['writer']}`"
    if row.get("writer_status") == "UNCONSOLIDATED":
        tgt = row.get("writer_target")
        st = row.get("writer_target_status")
        return f"UNCONSOLIDATED → `{tgt}`" + (f" ({st})" if st else "")
    return "**none**"


def _lane(lane: dict | None) -> str:
    if not isinstance(lane, dict):
        return "—"
    s = f"{lane.get('runner')}: {lane.get('lane')}"
    if lane.get("never_list"):
        s += " · n8n never-list → host"
    return s


def _rows(auth: dict) -> list[tuple[dict, str]]:
    out = []
    for d in auth.get("domains") or []:
        if isinstance(d.get("dictionary"), dict):
            out.append((d, "APPROVED"))
    for r in auth.get("proposed_domains") or []:
        out.append((r, "PROPOSED"))
    return out


def render(auth: dict) -> str:
    dd = auth.get("data_dictionary") or {}
    key = dd.get("canonical_key") or {}
    rows = _rows(auth)
    dict_names = {r["domain"] for r, _ in rows}
    superseded = {}
    for r, _ in rows:
        for s in r.get("supersedes") or []:
            superseded[s] = r["domain"]
    L: list[str] = []
    a = L.append
    a("# Data dictionary — one source for every fact")
    a("")
    a("```")
    a("Status:      ACTIVE (granted rows bind; PROPOSED rows await the operator's grant, AGENTS.md §17)")
    a(f"as_of:       {dd.get('as_of', 'UNKNOWN')}")
    a("Measured at: registry config/data_source_authority.json; counts are the rows' dated `measured` snapshots")
    a("```")
    a("")
    a("**Rendered from `config/data_source_authority.json` (the AGENTS.md §7A registry) by "
      "`scripts/render_data_dictionary.py`. Do not edit by hand** — `--check` fails CI when this file and the "
      "registry disagree. Architecture: [`CIO_PROSPECT_DATA_FOUNDATION.md`](CIO_PROSPECT_DATA_FOUNDATION.md). "
      "Every granted domain: [`docs/SOURCE_OF_TRUTH.md`](../SOURCE_OF_TRUTH.md).")
    a("")
    a(_cell(dd.get("_why")))
    a("")
    a("## How to read this")
    a("")
    a("- **One fact → one domain → one store → one writer → one projection.** A page, an API or an alert reads "
      "the store through its projection, never a copy.")
    a("- **APPROVED** rows bind: `scripts/check_data_source_authority.py` fails CI on a second writer "
      "(`DICTIONARY_SECOND_WRITER`) or a page/API reading a derived or retiring copy (`NON_AUTHORITATIVE_READ`) "
      "above the ceilings recorded at the grant. **PROPOSED** rows are the agent's proposal: the same checks "
      "print as warnings and never fail, because nobody has granted them.")
    a("- **Copies.** `derived` = an export or view of the store (generated, never written independently); "
      "`retiring` = to be archived with a tripwire, never deleted (AGENTS.md §0 rule 6); `history` = an "
      "append-only log the row's writer or projection reads; `excluded` = deliberately outside the dictionary "
      "(the broker execution subsystem, AGENTS.md §0 rule 2).")
    a("- **Divergent copies are never auto-merged** (AGENTS.md §0 rule 5): both paths, hashes and timestamps are "
      "reported to the operator.")
    a("")
    a("## The key")
    a("")
    a(f"- Per security: **`{key.get('per_security', 'security_guid')}`** · per company: "
      f"**`{key.get('per_company', 'issuer_guid')}`** · GUID authority: {_cell(key.get('authority'))}")
    for alias, why in (key.get("aliases") or {}).items():
        a(f"- `{alias}` — {_cell(why)}")
    a("")
    a("## Entities at a glance")
    a("")
    a("| Entity | Domain | Status | Authoritative store | Single writer | Refresh lane | Freshness SLA | Readers |")
    a("|---|---|---|---|---|---|---|---|")
    for r, st in rows:
        a(f"| {_cell(r.get('entity'))} | **{r['domain']}** | {st} | {_store(r.get('store'))} | {_writer(r)} | "
          f"{_cell(_lane(r.get('refresh_lane')))} | {_cell(r.get('freshness_sla'))} | {_cell(r.get('readers'))} |")
    a("")
    a("## Entity by entity")
    for r, st in rows:
        a("")
        a(f"### {r.get('title') or r['domain']} — `{r['domain']}` ({st})")
        a("")
        prop = r.get("proposal") or {}
        if st == "PROPOSED":
            a(f"**Operator decision (§17):** {_cell(prop.get('decision'))}")
            a("")
        else:
            appr = r.get("approval") or {}
            a(f"**Granted:** {_cell(appr.get('approved_by'))} {_cell(appr.get('approved_on'))} — "
              f"{_cell(appr.get('reference'))}")
            a("")
        a(f"- **Facts:** {_cell(r.get('facts'))}")
        a(f"- **Store of record:** {_store(r.get('store'))}" +
          (f" — {_cell(r.get('store_detail'))}" if r.get("store_detail") else ""))
        a(f"- **Single writer:** {_writer(r)}" + (f" — {_cell(r.get('_writer_note'))}" if r.get("_writer_note") else ""))
        a(f"- **Cadence:** {_cell(r.get('cadence'))} · stale after {_cell(r.get('stale_after_hours'))} h")
        a(f"- **Freshness SLA:** {_cell(r.get('freshness_sla'))}")
        lane = r.get("refresh_lane") or {}
        a(f"- **Refresh lane:** {_cell(_lane(lane))} — {_cell(lane.get('note'))}")
        a(f"- **Read path (projection):** `{r.get('projection') or 'none'}`" +
          (f" — {_cell(r.get('projection_status'))}" if r.get("projection_status") else ""))
        a(f"- **Readers:** {_cell(r.get('readers'))}")
        if r.get("supersedes"):
            a(f"- **Supersedes (on grant):** {_cell(r.get('supersedes'))} — marked, never removed, until their "
              "readers move")
        m = r.get("measured") or {}
        if m:
            a(f"- **Measured {_cell(m.get('at'))}:** {m.get('writer_files', '?')} writer file(s) of the store")
        copies = r.get("derived_copies") or []
        if copies:
            a("")
            a("| Copy | Role | How | Page/API files reading it (measured) |")
            a("|---|---|---|---|")
            reads = m.get("surface_reads") or {}
            for c in copies:
                ck = (f"table:{c['store']['table']}" if c["store"].get("table") else f"file:{c['store'].get('file')}")
                n = reads.get(ck)
                a(f"| {_store(c.get('store'))} | {c.get('role')} | {_cell(c.get('how'))} | "
                  f"{'—' if n is None else n} |")
    a("")
    a("## Field level")
    for rname, rec in (dd.get("records") or {}).items():
        a("")
        a(f"### `{rname}` — domain `{rec.get('domain')}`; {_cell(rec.get('extends'))}")
        a("")
        a("| Field | Type | Meaning | Source domain | Required |")
        a("|---|---|---|---|---|")
        for f in rec.get("fields") or []:
            a(f"| `{f['field']}` | {_cell(f.get('type'))} | {_cell(f.get('meaning'))} | {_cell(f.get('source'))} | "
              f"{'yes' if f.get('required') else ''} |")
    a("")
    a("### Key facts — where each one is true")
    a("")
    a("| Fact | Entity | Domain | Store | Field | Unit | Meaning | Never read it from |")
    a("|---|---|---|---|---|---|---|---|")
    for f in dd.get("facts") or []:
        a(f"| **{_cell(f.get('fact'))}** | {_cell(f.get('entity'))} | `{f.get('domain')}` | `{f.get('store')}` | "
          f"{_cell(f.get('field'))} | {_cell(f.get('unit'))} | {_cell(f.get('meaning'))} | {_cell(f.get('never'))} |")
    a("")
    a("## Declared stores measured missing")
    a("")
    a("| Domain | Status | What | Why | Measured |")
    a("|---|---|---|---|---|")
    for d in auth.get("domains") or []:
        sp = d.get("store_presence")
        if isinstance(sp, dict):
            a(f"| `{d['domain']}` | {_cell(sp.get('status'))} | {_cell(sp.get('what'))} | {_cell(sp.get('why'))} | "
              f"{_cell(sp.get('measured_at'))} |")
    a("")
    a("## Other granted domains")
    a("")
    a("These carry no dictionary block yet; their store, writer and read path are in "
      "[`docs/SOURCE_OF_TRUTH.md`](../SOURCE_OF_TRUTH.md). A domain marked superseded becomes a derived copy "
      "when the superseding row is granted.")
    a("")
    others = []
    for d in auth.get("domains") or []:
        if d["domain"] in dict_names:
            continue
        tag = f" (superseded by `{superseded[d['domain']]}` on grant)" if d["domain"] in superseded else ""
        others.append(f"`{d['domain']}`{tag}")
    a(", ".join(others))
    a("")
    a("## Surfaces scanned for copy reads")
    a("")
    a(f"`{'`, `'.join(dd.get('surface_files') or [])}`")
    a("")
    for name, how in (dd.get("surfaces") or {}).items():
        a(f"- **{name}** — {_cell(how)}")
    a("")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    try:
        auth = json.loads(AUTH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"ERROR: cannot read {AUTH}: {exc}", file=sys.stderr)
        return 2
    text = render(auth)
    if args.check:
        current = DOC.read_text(encoding="utf-8") if DOC.exists() else ""
        if current != text:
            print(f"stale: {DOC.relative_to(ROOT)} — run scripts/render_data_dictionary.py")
            return 1
        print("data dictionary: current")
        return 0
    DOC.write_text(text, encoding="utf-8")
    print(f"wrote {DOC.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
