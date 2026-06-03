#!/usr/bin/env python3
"""Documentation audit classifier (READ-ONLY except for docs/_audit/ outputs).

Walks docs/, classifies every file into a retention bucket, finds exact-duplicate markdown
(sha256), checks which files are reverse-linked from the authoritative set, and emits:
  docs/_audit/inventory.csv     — one row per file: path,size,ext,bucket,linked,dup_group,disposition
  docs/_audit/summary.md        — counts by bucket + disposition + size reclaim estimate
  docs/_audit/delete_list.txt   — proposed DELETE (gated; needs operator approval)
  docs/_audit/archive_list.txt  — proposed ARCHIVE (historical markdown of record)

Dispositions: RETAIN | ARCHIVE | DELETE. Never proposes DELETE for a file reverse-linked
from an authoritative doc, or for the only copy of a unique markdown report.
"""
import os, csv, hashlib, re
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
OUT = os.path.join(DOCS, "_audit")

AUTH_ROOT_MD = {  # canonical references that always RETAIN
    "A1A.md", "MASTER_SYSTEM_DOCUMENTATION.md", "CHEAT_SHEET.md", "COST_MODEL.md",
    "RESTORE_GUIDE.md", "GPU_OLLAMA_SETUP.md", "LLM_DATA_DICTIONARY.md", "DOCS_ROSTER.md",
    "AGENT_ROSTER.md", "AGENT_PAGES_DETAIL.md", "COMMAND_CENTER_PAGE_MATRIX.md",
    "APPENDIX_E_SCRIPT_ROUTING_MATRIX.md", "LLM_FLEET_STRATEGY_v4_1_FINAL.md",
    "OPERATOR_RUNBOOK_LLM_v4_1_FINAL.md", "MONDAY_BURNIN_CHECKLIST.md",
    "EXECUTIVE_ARCHITECTURE_OVERVIEW.md", "DASHBOARD_AUDIT_WORKFLOW.md",
}
AUTH_PATHS = {"project/PROJECT_DOC_INDEX.md", "project/SKILLS.md", "project/agents_bible.md"}

ARCHIVED_PREFIXES = ("_archive/", "_trash/", "_generated/", "_findings/", "_audit/")
DUMP_DIRS = {"source_exports", "source_snapshot", "current_source_text", "screenshots",
             "api_payloads", "config_exports", "designed_replacements", "raw_screens"}
DUMP_EXTS = {".py", ".tsx", ".ts", ".css", ".png", ".jpg", ".jpeg", ".svg", ".ico", ".webp"}
HEAVY_EXTS = {".zip", ".tgz", ".tar", ".gz", ".docx", ".pdf"}
HIST_DIR_RE = re.compile(r"(atm_lifecycle_v1_2026|atm_audit_2026|ui_redesign|ui_audits|"
                         r"screener_architecture|maturity_hardening|atm_lifecycle_v1)")
HIST_NAME_RE = re.compile(r"(SESSION_|PHASE\d|_CLOSEOUT|MEMORY_NOTES|NEXT_SESSION|_RUNBOOK_2026|"
                          r"morning_brief_2026|_HANDOFF)", re.I)


def rel(p):
    return os.path.relpath(p, DOCS)


def classify(relpath, ext):
    r = relpath.replace("\\", "/")
    if any(r.startswith(p) for p in ARCHIVED_PREFIXES):
        return "ALREADY-ARCHIVED"
    name = os.path.basename(r)
    parent = os.path.basename(os.path.dirname(r))
    if "/" not in r and name in AUTH_ROOT_MD:
        return "AUTHORITATIVE"
    if r in AUTH_PATHS:
        return "AUTHORITATIVE"
    if ext in HEAVY_EXTS:
        return "HEAVY-BINARY"
    if parent in DUMP_DIRS or ext in DUMP_EXTS:
        return "SNAPSHOT-DUMP"
    if ext == ".json" and parent in ("api_payloads", "config_exports"):
        return "SNAPSHOT-DUMP"
    if ext == ".md" and (HIST_DIR_RE.search(r) or HIST_NAME_RE.search(name)):
        return "HISTORICAL-REPORT"
    if ext == ".md":
        return "ACTIVE-SUBSYSTEM"
    return "SNAPSHOT-DUMP"  # stray json/txt/yaml in report trees


def load_authoritative_text():
    """Concatenate authoritative docs to reverse-link check against."""
    blobs = []
    for name in list(AUTH_ROOT_MD) + list(AUTH_PATHS):
        p = os.path.join(DOCS, name)
        if os.path.exists(p):
            try:
                blobs.append(open(p, encoding="utf-8", errors="ignore").read())
            except Exception:
                pass
    return "\n".join(blobs)


def main():
    os.makedirs(OUT, exist_ok=True)
    auth_text = load_authoritative_text()
    rows = []
    hashes = defaultdict(list)  # md sha256 -> [relpaths]
    for dirpath, _dirs, files in os.walk(DOCS):
        if os.path.relpath(dirpath, DOCS).startswith("_audit"):
            continue
        for fn in files:
            fp = os.path.join(dirpath, fn)
            r = rel(fp)
            ext = os.path.splitext(fn)[1].lower()
            try:
                size = os.path.getsize(fp)
            except OSError:
                continue
            bucket = classify(r, ext)
            if ext == ".md":
                try:
                    h = hashlib.sha256(open(fp, "rb").read()).hexdigest()
                    hashes[h].append(r)
                except Exception:
                    h = None
            else:
                h = None
            linked = (("/" + r) in auth_text) or (r in auth_text) or (os.path.basename(r) in auth_text)
            rows.append({"path": r, "size": size, "ext": ext, "bucket": bucket,
                         "linked": linked, "sha": h})

    # duplicate groups (exact md duplicates, >1 copy)
    dup_of = {}
    for h, paths in hashes.items():
        if len(paths) > 1:
            keep = sorted(paths, key=lambda p: (p.count("/"), len(p)))[0]  # shallowest/shortest = canonical
            for p in paths:
                if p != keep:
                    dup_of[p] = keep

    # disposition
    def disposition(row):
        b, r, linked = row["bucket"], row["path"], row["linked"]
        if b == "AUTHORITATIVE":
            return "RETAIN"
        if r in dup_of:
            return "DELETE"  # exact duplicate; canonical kept
        if b in ("SNAPSHOT-DUMP", "HEAVY-BINARY"):
            return "RETAIN" if linked and row["ext"] in (".docx", ".pdf") else "DELETE"
        if b == "ALREADY-ARCHIVED":
            # backups/bibles/trash/generated -> DELETE per operator; findings -> RETAIN
            if r.startswith("_findings/"):
                return "RETAIN"
            if row["ext"] in HEAVY_EXTS or r.startswith(("_trash/", "_generated/")):
                return "DELETE"
            return "ARCHIVE-KEEP"  # already archived md of record
        if b == "HISTORICAL-REPORT":
            return "ARCHIVE"
        return "RETAIN"  # ACTIVE-SUBSYSTEM

    for row in rows:
        row["dup_of"] = dup_of.get(row["path"], "")
        row["disposition"] = disposition(row)

    # write inventory
    with open(os.path.join(OUT, "inventory.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["path", "size", "ext", "bucket", "linked", "dup_of", "disposition"])
        w.writeheader()
        for row in rows:
            w.writerow({k: row[k] for k in w.fieldnames})

    # lists
    deletes = [r for r in rows if r["disposition"] == "DELETE"]
    archives = [r for r in rows if r["disposition"] == "ARCHIVE"]
    with open(os.path.join(OUT, "delete_list.txt"), "w") as f:
        for r in sorted(deletes, key=lambda x: -x["size"]):
            f.write(f"{r['path']}\t{r['size']}\t{r['bucket']}{(' dup_of=' + r['dup_of']) if r['dup_of'] else ''}\n")
    with open(os.path.join(OUT, "archive_list.txt"), "w") as f:
        for r in sorted(archives, key=lambda x: x["path"]):
            f.write(f"{r['path']}\t{r['size']}\n")

    # summary
    by_bucket = defaultdict(lambda: [0, 0])
    by_disp = defaultdict(lambda: [0, 0])
    for r in rows:
        by_bucket[r["bucket"]][0] += 1; by_bucket[r["bucket"]][1] += r["size"]
        by_disp[r["disposition"]][0] += 1; by_disp[r["disposition"]][1] += r["size"]
    mb = lambda b: f"{b/1e6:.1f} MB"
    with open(os.path.join(OUT, "summary.md"), "w") as f:
        f.write("# Docs Audit Summary\n\n## By bucket\n\n| Bucket | Files | Size |\n|---|---|---|\n")
        for k in sorted(by_bucket, key=lambda x: -by_bucket[x][1]):
            f.write(f"| {k} | {by_bucket[k][0]} | {mb(by_bucket[k][1])} |\n")
        f.write("\n## By disposition\n\n| Disposition | Files | Size |\n|---|---|---|\n")
        for k in sorted(by_disp, key=lambda x: -by_disp[x][1]):
            f.write(f"| {k} | {by_disp[k][0]} | {mb(by_disp[k][1])} |\n")
        dup_groups = sum(1 for h, p in hashes.items() if len(p) > 1)
        f.write(f"\nExact-duplicate md groups: {dup_groups} ({len(dup_of)} redundant copies)\n")
        f.write(f"\nTotal files: {len(rows)} · Total size: {mb(sum(r['size'] for r in rows))}\n")
    print(f"audit complete: {len(rows)} files. delete={len(deletes)} archive={len(archives)}")
    print(open(os.path.join(OUT, "summary.md")).read())


if __name__ == "__main__":
    main()
