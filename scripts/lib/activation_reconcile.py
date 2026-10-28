"""Approvals › Activations: reconcile governance packets with what is actually live, and describe each row.

A packet under ``docs/ops/packets/<id>/`` whose README says PROPOSED/DRAFT stays "waiting" only while nothing
shows it was already applied. ``config/activation_packet_targets.json`` declares, per packet, what "applied"
means as checkable facts:

- ``{"lane": id, "state": "ACTIVE", "scheduler": "n8n", "dispatch_mode": "live"}`` — the lane registry row
  (``config/lane_registry.json`` of the served code) has those values;
- ``{"n8n_live": lane}`` — the lane is on the n8n relay live list (the same file Ops › n8n reads);
- ``{"released_commit": sha}`` — the served code contains that commit (``git merge-base --is-ancestor``);
- ``{"policy_base": "X.Y.Z"}`` — the package was built on that AGENTS.md version; once the served policy is a
  different version the package's own apply step refuses, so it is superseded, not waiting.

All lane/n8n/release targets true -> LIVE; a ``policy_base`` that moved -> SUPERSEDED; anything unreadable or
false -> WAITING with the reason. Resolved packets are returned in their own group and never deleted. A packet with
no declared target stays waiting and says so. Read-only: nothing here writes, schedules or calls a network.
"""
from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

TARGETS_REL = "config/activation_packet_targets.json"
REGISTRY_REL = "config/lane_registry.json"
_SHA = re.compile(r"^[0-9a-f]{7,40}$")
_VERSION = re.compile(r"^\d+\.\d+\.\d+$")
_HEADER_FIELD = re.compile(r"^\s*(Owner|Proposed[ -]by|Author|Proposer|as_of)\s*:\s*(.+?)\s*$", re.I)
_MAX_HEADER_LINES = 40
LIVE, SUPERSEDED, WAITING = "LIVE", "SUPERSEDED", "WAITING"


def load_targets(root: Path) -> dict[str, Any]:
    path = Path(root) / TARGETS_REL
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    packets = doc.get("packets") if isinstance(doc, dict) else None
    return packets if isinstance(packets, dict) else {}


def load_registry(root: Path) -> dict[str, dict] | None:
    try:
        doc = json.loads((Path(root) / REGISTRY_REL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    lanes = doc.get("lanes") if isinstance(doc, dict) else None
    if not isinstance(lanes, list):
        return None
    return {row["lane_id"]: row for row in lanes if isinstance(row, dict) and isinstance(row.get("lane_id"), str)}


def policy_version(text: str | None) -> str | None:
    match = re.search(r"^Policy-Version:\s*(\d+\.\d+\.\d+)\s*$", text or "", re.M)
    return match[1] if match else None


# --------------------------------------------------------------------------------------------- titles + metadata


def humanize_slug(slug: str) -> str:
    """'release-train-arming-20261021' -> 'Release train arming (Oct 21)'. Used only when the README has no H1."""
    words = [w for w in re.split(r"[-_]+", slug) if w]
    date = None
    if words and re.fullmatch(r"20\d{6}", words[-1]):
        raw = words.pop()
        try:
            date = datetime.strptime(raw, "%Y%m%d").strftime("%b %d").replace(" 0", " ")
        except ValueError:
            date = None
    text = " ".join(words) or slug
    text = text[:1].upper() + text[1:]
    return f"{text} ({date})" if date else text


def readme_meta(text: str) -> dict[str, Any]:
    """The README's H1 title and its header fields (Owner / Proposed by / Author / as_of), first lines only."""
    title, fields = None, {}
    for i, line in enumerate((text or "").splitlines()):
        if i >= _MAX_HEADER_LINES:
            break
        if title is None and line.startswith("# "):
            title = re.sub(r"[`*]", "", line[2:]).strip() or None
            continue
        match = _HEADER_FIELD.match(line.strip("`* "))
        if match:
            key = match[1].lower().replace(" ", "-")
            key = "owner" if key in ("owner", "proposed-by", "author", "proposer") else key
            value = match[2].strip("`* ")
            fields.setdefault(key, (_short_owner(value) if key == "owner" else value[:120]) or value[:120])
    return {"title": title, **fields}


def _short_owner(value: Any) -> str | None:
    """'platform. The operator approved…' -> 'platform'; long owner prose keeps only its first clause."""
    if not isinstance(value, str) or not value.strip():
        return None
    return re.split(r"\.\s|;\s?|\s—\s|\s\(", value.strip(), maxsplit=1)[0].strip(" .`*")[:120] or None


def _iso(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip().split()[0]
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _agent_from_trailer(trailer: str) -> str | None:
    names = [re.sub(r"\s*<[^>]*>\s*", "", part).strip() for part in (trailer or "").split(";")]
    names = [n for n in names if n]
    return names[0] if names else None


_ADDED_CACHE: dict[tuple, dict] = {}


def added_commits_cached(git: Callable[..., str], paths: Iterable[str], rev: str) -> dict[str, dict[str, str | None]]:
    """``added_commits`` memoised per (rev, paths): history of an exact commit never changes."""
    key = (rev, tuple(sorted(set(p for p in paths if p))))
    if key not in _ADDED_CACHE:
        if len(_ADDED_CACHE) > 16:
            _ADDED_CACHE.clear()
        _ADDED_CACHE[key] = added_commits(git, key[1], rev)
    return _ADDED_CACHE[key]


def added_commits(git: Callable[..., str], paths: Iterable[str], rev: str = "HEAD") -> dict[str, dict[str, str | None]]:
    """For each path: the commit that added it in ``rev``'s history (time + first Co-Authored-By agent). One ``git log``."""
    paths = list(dict.fromkeys(p for p in paths if p))
    if not paths:
        return {}
    try:
        out = git("log", rev, "--diff-filter=A", "--no-renames",
                  "--format=@@%H|%cI|%(trailers:key=Co-Authored-By,valueonly,separator=;)", "--name-only", "--", *paths)
    except (subprocess.SubprocessError, OSError, UnicodeDecodeError, ValueError):
        return {}
    found: dict[str, dict[str, str | None]] = {}
    current: dict[str, str | None] | None = None
    for line in (out or "").splitlines():
        if line.startswith("@@"):
            sha, _, rest = line[2:].partition("|")
            at, _, trailer = rest.partition("|")
            current = {"sha": sha.strip() or None, "at": _iso(at), "agent": _agent_from_trailer(trailer)}
        elif line.strip() and current is not None:
            found.setdefault(line.strip(), current)  # newest-first log: keep the latest add
    return found


_CLAIMS_CACHE: dict[str, Any] = {"key": None, "index": {}}


def claim_index(claims_dir: Path | None) -> dict[str, str]:
    """commit sha -> "vendor/agent" from the claim board (claims record head_sha / logged_sha). Cached per dir state."""
    if claims_dir is None:
        return {}
    try:
        files = sorted(Path(claims_dir).glob("*.json"))
        key = (str(claims_dir), len(files), max((f.stat().st_mtime_ns for f in files), default=0))
    except OSError:
        return {}
    if _CLAIMS_CACHE["key"] == key:
        return _CLAIMS_CACHE["index"]
    index: dict[str, str] = {}
    for f in files[:5000]:
        try:
            if f.stat().st_size > 200_000:
                continue
            row = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            continue
        if not isinstance(row, dict):
            continue
        who = "/".join(str(row[k]) for k in ("vendor", "agent") if isinstance(row.get(k), str) and row.get(k))
        if not who:
            continue
        for field in ("head_sha", "logged_sha"):
            sha = row.get(field)
            if isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{40}", sha):
                index.setdefault(sha, who)
    _CLAIMS_CACHE.update(key=key, index=index)
    return index


def describe(*, kind: str, ident: str, path: str | None, readme_text: str | None, owner: str | None,
             target: dict | None, added: dict[str, str | None] | None,
             claims: dict[str, str] | None = None, title: str | None = None) -> dict[str, Any]:
    """Title, proposer (with the reason when unknown) and created_at for one queue row."""
    meta = readme_meta(readme_text or "") if kind == "packet" else {}
    named = title if title and title != ident else None
    title = (target or {}).get("title") or meta.get("title") or named or humanize_slug(ident)
    proposer = (target or {}).get("proposed_by") or _short_owner(owner) or meta.get("owner")
    basis = "packet owner" if proposer else None
    if not proposer and added and added.get("sha") and (claims or {}).get(added["sha"]):
        proposer, basis = f"{claims[added['sha']]} (claim)", "claim metadata"
    if not proposer and added and added.get("agent"):
        proposer, basis = f"{added['agent']} (agent)", "commit trailer"
    if not proposer:
        where = "the packet README" if kind == "packet" else "the design file"
        proposer = f"unknown — {where} names no owner, and no claim or commit trailer names an agent"
        basis = "unknown"
    created = _iso(meta.get("as_of")) or (added or {}).get("at")
    created_basis = "README as_of" if _iso(meta.get("as_of")) else "commit that added it" if created else None
    return {"title": title, "proposed_by": proposer, "proposed_by_basis": basis, "created_at": created,
            "created_at_basis": created_basis, "path": path}


# --------------------------------------------------------------------------------------------- reconcile


class Facts:
    """What is live, read once per request. Every reader is injectable for tests."""

    def __init__(self, *, registry: dict[str, dict] | None, served_policy: str | None,
                 n8n_live: set[str] | None, is_released: Callable[[str], bool | None]):
        self.registry, self.served_policy, self.n8n_live, self.is_released = registry, served_policy, n8n_live, is_released


def _check(target: dict, facts: Facts) -> tuple[bool | None, str]:
    if "lane" in target:
        lane = str(target["lane"])
        if facts.registry is None:
            return None, "lane registry unreadable"
        row = facts.registry.get(lane)
        if row is None:
            return False, f"lane {lane} is not in the lane registry"
        want = {"state": target.get("state", "ACTIVE"), "scheduler": target.get("scheduler"),
                "dispatch_mode": target.get("dispatch_mode")}
        have = {"state": row.get("state"), "scheduler": (row.get("scheduler") or {}).get("kind"),
                "dispatch_mode": (row.get("dispatch") or {}).get("mode")}
        bad = [f"{k} {have[k] or 'unset'} (needs {v})" for k, v in want.items() if v is not None and have[k] != v]
        since = f" since {row['state_since']}" if row.get("state_since") else ""
        if bad:
            return False, f"lane {lane}: " + ", ".join(bad)
        return True, f"lane {lane} {have['state']}{' on ' + have['scheduler'] if have['scheduler'] else ''}" \
                     f"{' · dispatch ' + have['dispatch_mode'] if have['dispatch_mode'] else ''}{since}"
    if "n8n_live" in target:
        lane = str(target["n8n_live"])
        if facts.n8n_live is None:
            return None, "n8n live list unreadable"
        return (lane in facts.n8n_live), (f"{lane} is on the n8n live list" if lane in facts.n8n_live
                                          else f"{lane} is not on the n8n live list")
    if "released_commit" in target:
        sha = str(target["released_commit"])
        if not _SHA.fullmatch(sha):
            return None, "invalid released_commit target"
        released = facts.is_released(sha)
        if released is None:
            return None, f"could not check whether {sha[:9]} is released"
        return released, f"commit {sha[:9]} is {'in' if released else 'not in'} the served release"
    return None, "unknown target kind"


def reconcile(target: dict | None, facts: Facts) -> dict[str, Any]:
    if not target or not isinstance(target, dict):
        return {"state": WAITING, "evidence": [], "reason": "No activation target is declared for this packet, so it "
                                                           "cannot be checked against what is live."}
    base = target.get("policy_base")
    if isinstance(base, str) and _VERSION.fullmatch(base):
        if facts.served_policy is None:
            return {"state": WAITING, "evidence": [], "reason": "Served AGENTS.md version unreadable."}
        if facts.served_policy != base:
            return {"state": SUPERSEDED, "evidence": [f"built on AGENTS.md {base}; the served policy is {facts.served_policy}"],
                    "reason": f"Superseded: the package was built on AGENTS.md {base} and its apply step refuses a "
                              f"later policy. The served policy is {facts.served_policy}; rebuild it to propose again."}
    checks = [c for c in target.get("live_when") or [] if isinstance(c, dict)]
    if not checks:
        return {"state": WAITING, "evidence": [], "reason": "Waiting: no live check is declared for this packet."}
    results = [_check(c, facts) for c in checks]
    evidence = [why for _, why in results]
    if all(ok is True for ok, _ in results):
        return {"state": LIVE, "evidence": evidence, "reason": "Already live: " + "; ".join(evidence) + "."}
    unknown = [why for ok, why in results if ok is None]
    missing = [why for ok, why in results if ok is False]
    reason = "Waiting: " + "; ".join(missing or unknown) + "."
    return {"state": WAITING, "evidence": evidence, "reason": reason}


def default_facts(root: Path, git: Callable[..., str], served_sha: str, *, live_list_path: Path | None = None) -> Facts:
    registry = load_registry(root)
    try:
        served_policy = policy_version((Path(root) / "AGENTS.md").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        served_policy = None
    n8n_live = None
    path = live_list_path
    if path is None:
        try:
            from scripts.lib import ops_controls_core as ops
            path = ops.expand(ops.load_config()["live_list"]["file"])
        except Exception:  # noqa: BLE001 - optional; an unreadable list is reported per target
            path = None
    if path is not None:
        try:
            from scripts.check_registry_runtime_truth import parse_live_lanes
            n8n_live = set(parse_live_lanes(Path(path).read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            n8n_live = None

    def is_released(sha: str) -> bool | None:
        try:
            git("merge-base", "--is-ancestor", sha, served_sha)
            return True
        except subprocess.CalledProcessError as exc:
            return False if exc.returncode == 1 else None
        except (subprocess.SubprocessError, OSError, ValueError):
            return None

    return Facts(registry=registry, served_policy=served_policy, n8n_live=n8n_live, is_released=is_released)
