"""Read and validate the design/ folder (AGENTS.md §28.13, design/README.md).

Pure functions over repo files plus an optional read-only walk of the private design store. Nothing here writes.
Every Command Center page lives in design/registry.json; each version lives in
design/pages/<page>/versions/vNNN/{status.json,SPEC.md}. Private assets (mockups, screenshots, handoff specs) are
referenced from status.json by a path relative to the page's private folder and a sha256, never committed.

AUTHORITY: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATES = ("DRAFT", "PROPOSED", "APPROVED", "IMPLEMENTING", "VERIFIED", "CURRENT", "SUPERSEDED", "REJECTED", "BASELINE")
# States that carry an operator approval (BASELINE is a capture of what is live, never an approval).
APPROVED_STATES = ("APPROVED", "IMPLEMENTING", "VERIFIED", "CURRENT", "SUPERSEDED")
ROLES = ("mockups", "spec", "evidence", "evidence/batch27", "baselines", "capture")
BOUND_ROLES = ("mockups", "spec")  # the files an approval binds; evidence and captures are informational
PAGE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
VERSION = re.compile(r"^v\d{3}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
REMOVAL = re.compile(r'^\s*-\s*(remove|hide|move|rename):\s*([a-z][a-z /-]*?)\s+"([^"]+)"', re.I)

# Privacy scan (public repository). Money, grouped amounts and account-number shapes are refused in committed design
# text; real tickers and account names are refused when the host supplies them (--private-terms / holdings).
PRIVACY_PATTERNS = (
    ("money", re.compile(r"[$€£]\s?\d")),
    ("grouped_amount", re.compile(r"(?<![\w.])\d{1,3}(?:,\d{3})+(?:\.\d+)?(?![\w])")),
    ("account_number", re.compile(r"(?i)\b(?:acct|account)\s*(?:#|no\.?|number)\s*:?\s*\d{3,}|(?:…|\.\.\.|x{2,}|\*{2,})\d{3,4}\b")),
)


class DesignError(ValueError):
    pass


def design_dir(root: Path = ROOT) -> Path:
    return Path(root) / "design"


def load_registry(root: Path = ROOT) -> dict:
    return json.loads((design_dir(root) / "registry.json").read_text(encoding="utf-8"))


def version_fingerprint(files: list[dict]) -> str:
    """sha256 over the sorted (path, sha256) pairs of the files an approval binds (mockups + spec)."""
    bound = sorted((f["path"], f["sha256"]) for f in files if f.get("role") in BOUND_ROLES)
    return hashlib.sha256(json.dumps(bound, separators=(",", ":")).encode()).hexdigest()


def iter_versions(root: Path = ROOT):
    """Yield (page_id, version, status, version_dir) for every committed version folder, sorted."""
    pages = design_dir(root) / "pages"
    if not pages.is_dir():
        return
    for page in sorted(p for p in pages.iterdir() if p.is_dir()):
        versions = page / "versions"
        if not versions.is_dir():
            continue
        for vdir in sorted(v for v in versions.iterdir() if v.is_dir()):
            status_path = vdir / "status.json"
            status = json.loads(status_path.read_text(encoding="utf-8")) if status_path.is_file() else None
            yield page.name, vdir.name, status, vdir


def parse_removals(spec_text: str) -> list[dict]:
    """The machine-read removal list of a SPEC.md: '- <remove|hide|move|rename>: <kind> "<label>" — <why>'."""
    out, inside = [], False
    for line in spec_text.splitlines():
        if line.startswith("## "):
            inside = line.lower().startswith("## removals")
            continue
        if inside and (m := REMOVAL.match(line)):
            out.append({"action": m.group(1).lower(), "kind": m.group(2).strip().lower(), "label": m.group(3).strip()})
    return out


def _safe_rel(path: str) -> bool:
    p = Path(path)
    return bool(path) and not p.is_absolute() and ".." not in p.parts and "\\" not in path and not path.startswith("~")


def validate_status(page: str, version: str, status, *, spec_exists: bool) -> list[str]:
    where = f"design/pages/{page}/versions/{version}"
    if not isinstance(status, dict):
        return [f"{where}: status.json missing or not an object"]
    errs = []
    if status.get("schema") != "DesignVersionStatus@v1":
        errs.append(f"{where}: schema must be DesignVersionStatus@v1")
    if status.get("page") != page or status.get("version") != version:
        errs.append(f"{where}: page/version fields must match the folder")
    state = status.get("state")
    if state not in STATES:
        errs.append(f"{where}: unknown state {state!r}")
    if not spec_exists and state != "BASELINE":
        errs.append(f"{where}: SPEC.md missing")
    approval = status.get("approval")
    if state in APPROVED_STATES or state == "REJECTED":
        if not isinstance(approval, dict) or approval.get("by") != "operator" or not approval.get("at") or not approval.get("ref"):
            errs.append(f"{where}: state {state} needs approval {{by: operator, at, ref}}")
        elif not approval.get("ledger") and approval.get("kind") != "recorded in handoff, back-filled 2026-10-25":
            # Only the 10-24 back-fill may stand without a ledger decision (§28.13).
            errs.append(f"{where}: approval must cite its operator-decisions ledger row (approval.ledger)")
        elif approval.get("ledger") and not (isinstance(approval["ledger"], dict) and SHA256.fullmatch(str(approval["ledger"].get("hash_self", "")))):
            errs.append(f"{where}: approval.ledger must carry the ledger row hash_self")
    elif approval not in (None, {}):
        errs.append(f"{where}: state {state} must not carry an approval")
    assets = status.get("private_assets") or {}
    files = assets.get("files") if isinstance(assets, dict) else None
    if not isinstance(files, list):
        errs.append(f"{where}: private_assets.files must be a list")
        files = []
    if assets.get("root") not in (None, f"persistent-state/data/design/pages/{page}"):
        errs.append(f"{where}: private_assets.root must be persistent-state/data/design/pages/{page}")
    seen = set()
    for f in files:
        if not isinstance(f, dict) or not _safe_rel(str(f.get("path", ""))):
            errs.append(f"{where}: private asset path must be relative inside the page folder: {f!r}"[:240])
            continue
        if not SHA256.fullmatch(str(f.get("sha256", ""))):
            errs.append(f"{where}: {f['path']}: sha256 must be 64 lowercase hex")
        if f.get("role") not in ROLES:
            errs.append(f"{where}: {f['path']}: unknown role {f.get('role')!r}")
        if f.get("role") == "capture" and f.get("width") not in (1440, 412, 390):
            errs.append(f"{where}: {f['path']}: a capture names its width (1440, 412 or 390)")
        if state == "BASELINE" and f.get("role") != "capture":
            errs.append(f"{where}: {f['path']}: a BASELINE version holds only captures")
        if f["path"] in seen:
            errs.append(f"{where}: {f['path']}: listed twice")
        seen.add(f["path"])
    if state in ("PROPOSED",) + APPROVED_STATES and not any(f.get("role") in BOUND_ROLES for f in files if isinstance(f, dict)):
        errs.append(f"{where}: state {state} needs at least one private mockup or spec fingerprint")
    if files and status.get("fingerprint") != version_fingerprint([f for f in files if isinstance(f, dict) and "path" in f and "sha256" in f]):
        errs.append(f"{where}: fingerprint does not match the bound private files")
    return errs


def validate(root: Path = ROOT) -> list[str]:
    errs: list[str] = []
    try:
        reg = load_registry(root)
    except (OSError, ValueError) as exc:
        return [f"design/registry.json unreadable: {exc}"]
    if reg.get("schema") != "DesignRegistry@v1":
        errs.append("design/registry.json: schema must be DesignRegistry@v1")
    if tuple(reg.get("states") or ()) != STATES:
        errs.append("design/registry.json: states must equal " + ", ".join(STATES))
    pages = reg.get("pages")
    if not isinstance(pages, list) or not pages:
        return errs + ["design/registry.json: pages must be a non-empty list"]
    by_id = {}
    routes = set()
    for p in pages:
        pid = p.get("id") if isinstance(p, dict) else None
        if not isinstance(pid, str) or not PAGE_ID.fullmatch(pid):
            errs.append(f"design/registry.json: invalid page id {pid!r}")
            continue
        if pid in by_id:
            errs.append(f"design/registry.json: duplicate page id {pid}")
        by_id[pid] = p
        route = p.get("route")
        if route is not None:
            if not isinstance(route, str) or not route.startswith("/"):
                errs.append(f"design/registry.json: {pid}: route must start with / or be null")
            elif route in routes:
                errs.append(f"design/registry.json: {pid}: route {route} listed twice")
            routes.add(route)
        pdir = design_dir(root) / "pages" / pid
        for name in ("PAGE.md", "CHANGELOG.md"):
            if not (pdir / name).is_file():
                errs.append(f"design/pages/{pid}/{name} missing")
    committed: dict[tuple[str, str], dict] = {}
    for page, version, status, vdir in iter_versions(root):
        if page not in by_id:
            errs.append(f"design/pages/{page}: not in design/registry.json")
            continue
        if not VERSION.fullmatch(version):
            errs.append(f"design/pages/{page}/versions/{version}: version folders are vNNN")
            continue
        errs.extend(validate_status(page, version, status, spec_exists=(vdir / "SPEC.md").is_file()))
        if isinstance(status, dict):
            committed[(page, version)] = status
    for pid, p in by_id.items():
        listed = {v.get("version"): v for v in p.get("versions") or [] if isinstance(v, dict)}
        actual = {v for (pg, v) in committed if pg == pid}
        if set(listed) != actual:
            errs.append(f"design/registry.json: {pid}: versions {sorted(listed)} != folders {sorted(actual)}")
        for v, row in listed.items():
            st = committed.get((pid, v))
            if st and (row.get("state") != st.get("state") or row.get("fingerprint") != st.get("fingerprint")):
                errs.append(f"design/registry.json: {pid} {v}: state/fingerprint differ from status.json")
        for key, allowed in (("approved_version", APPROVED_STATES), ("current_version", ("CURRENT",)), ("baseline_version", ("BASELINE",))):
            v = p.get(key)
            if v is not None and (committed.get((pid, v)) or {}).get("state") not in allowed:
                errs.append(f"design/registry.json: {pid}: {key} {v} is not in state {'/'.join(allowed)}")
    return errs


def verify_private(root: Path, private_root: Path) -> list[str]:
    """Host-only: every private asset named in a status.json exists with the recorded sha256."""
    errs = []
    for page, version, status, _ in iter_versions(root):
        for f in ((status or {}).get("private_assets") or {}).get("files") or []:
            path = Path(private_root) / "pages" / page / f["path"]
            if not path.is_file():
                errs.append(f"{page}/{version}: private asset missing: {f['path']}")
                continue
            h = hashlib.sha256()
            with path.open("rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            if h.hexdigest() != f["sha256"]:
                errs.append(f"{page}/{version}: private asset changed: {f['path']}")
    return errs


def _text_values(path: Path) -> list[tuple[str, str]]:
    """(where, text) pairs to scan: whole Markdown files; JSON string values except hashes/paths of private files."""
    if path.suffix == ".md":
        return [(str(path), path.read_text(encoding="utf-8"))]
    if path.suffix != ".json":
        return []
    out = []

    def walk(x, key=""):
        if isinstance(x, dict):
            for k, v in x.items():
                if k not in ("sha256", "fingerprint", "hash_self", "hash_prev", "document_sha"):
                    walk(v, k)
        elif isinstance(x, list):
            for v in x:
                walk(v, key)
        elif isinstance(x, str):
            out.append((f"{path}:{key}", x))
    walk(json.loads(path.read_text(encoding="utf-8")))
    return out


def privacy_scan(paths: list[Path], private_terms: set[str] | frozenset = frozenset()) -> list[str]:
    """Findings for committed design text. private_terms (host-only: real tickers, account names) match whole words."""
    findings = []
    terms = sorted({t for t in private_terms if t and t.strip()}, key=len, reverse=True)
    term_rx = re.compile(r"(?<![A-Za-z0-9])(" + "|".join(re.escape(t) for t in terms) + r")(?![A-Za-z0-9])") if terms else None
    for base in paths:
        files = [base] if base.is_file() else sorted(p for p in Path(base).rglob("*") if p.is_file())
        for f in files:
            if f.name == "tokens.json":
                continue  # colour values only; checked by the token generator and contrast gate
            for where, text in _text_values(f):
                for kind, rx in PRIVACY_PATTERNS:
                    if m := rx.search(text):
                        findings.append(f"{where}: {kind}: {text[max(0, m.start() - 20):m.end() + 20]!r}")
                if term_rx and (m := term_rx.search(text)):
                    findings.append(f"{where}: private term {m.group(1)!r}")
    return findings


def holdings_terms(holdings_path: Path, account_names_path: Path | None = None) -> set[str]:
    """Host-only helper: real tickers and account display names to keep out of committed design text."""
    terms: set[str] = set()
    data = json.loads(Path(holdings_path).read_text(encoding="utf-8"))

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k in ("symbol", "ticker", "underlying") and isinstance(v, str) and 1 <= len(v) <= 6 and v.isalpha():
                    terms.add(v.upper())
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(data)
    if account_names_path and Path(account_names_path).is_file():
        names = json.loads(Path(account_names_path).read_text(encoding="utf-8"))
        for v in (names.values() if isinstance(names, dict) else []):
            if isinstance(v, str) and len(v) >= 4:
                terms.add(v)
            elif isinstance(v, dict):
                terms.update(s for s in v.values() if isinstance(s, str) and len(s) >= 4)
    return terms
