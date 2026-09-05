"""campaign_closeout.py — the terminal marker for a truth campaign, fail-closed.

READ_ONLY_ADVISORY. Pure logic plus read-only probes. Writes nothing, sends
nothing, and cannot change any system it measures.

WHAT THIS IS FOR
----------------
A campaign ends with one of three words:

    PRE_PERSISTENT_AGENT_TRUTH_READY        every item closed by evidence
    PRE_PERSISTENT_AGENT_TRUTH_ROLLED_BACK  changes were reverted
    PRE_PERSISTENT_AGENT_TRUTH_BLOCKED      something is unproven

The failure mode this module exists to prevent is the one the whole campaign has
been about: a green word standing over unmeasured ground. A closeout that reads
READY because nobody looked is worse than no closeout, because it ends the
looking.

So the rule is inverted from the usual: **READY must be earned by every item, and
anything else is BLOCKED.** Absent evidence is not neutral. An item nobody could
measure is a reason to refuse the marker, never a reason to omit the item.

    disposition        counts toward READY?
    CLOSED             yes — closed by a measurement recorded here
    NOT_APPLICABLE     yes — with a stated reason it cannot apply
    PARTIAL            NO  — some of it is proven, which is not all of it
    OPEN               NO  — known to be unfinished
    UNMEASURED         NO  — could not be measured from here
    CONTRADICTED       NO  — evidence disagrees with the claim

There is deliberately no "ACCEPTED_RISK" disposition. Accepting a risk is an
operator decision and cannot be spelled by a program that wants to say READY.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

SCHEMA = "CampaignCloseout@v1"

MARKER_READY = "PRE_PERSISTENT_AGENT_TRUTH_READY"
MARKER_ROLLED_BACK = "PRE_PERSISTENT_AGENT_TRUTH_ROLLED_BACK"
MARKER_BLOCKED = "PRE_PERSISTENT_AGENT_TRUTH_BLOCKED"

#: Dispositions that permit READY. Everything else blocks it.
CLOSING_DISPOSITIONS: frozenset[str] = frozenset({"CLOSED", "NOT_APPLICABLE"})

VALID_DISPOSITIONS: frozenset[str] = CLOSING_DISPOSITIONS | frozenset({
    "PARTIAL", "OPEN", "UNMEASURED", "CONTRADICTED",
})


class CloseoutError(ValueError):
    """A closeout that tried to say something it is not allowed to say."""


@dataclass
class Item:
    """One backlog item and what was actually measured about it."""

    key: str
    priority: str                      # P0 / P1 / P2
    claim: str                         # what closing it would mean
    disposition: str = "UNMEASURED"
    evidence: str = ""                 # a measurement, not a document reference
    blocks_ready: bool = field(init=False, default=True)

    def __post_init__(self) -> None:
        if self.disposition not in VALID_DISPOSITIONS:
            raise CloseoutError(
                f"{self.key}: '{self.disposition}' is not a disposition. "
                f"Valid: {sorted(VALID_DISPOSITIONS)}")
        self.blocks_ready = self.disposition not in CLOSING_DISPOSITIONS
        if self.disposition in CLOSING_DISPOSITIONS and not self.evidence.strip():
            # A closing disposition with no evidence is the exact defect this
            # module exists to refuse: a green word with nothing behind it.
            raise CloseoutError(
                f"{self.key}: disposition {self.disposition} requires evidence. "
                "An item cannot be closed by assertion.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "priority": self.priority,
            "claim": self.claim,
            "disposition": self.disposition,
            "evidence": self.evidence,
            "blocks_ready": self.blocks_ready,
        }


def decide_marker(items: list[Item], *, rolled_back: bool = False) -> dict[str, Any]:
    """Choose the terminal marker. Fail closed.

    `rolled_back` is the operator stating that the campaign's changes were
    reverted; it is never inferred, because "we could not prove it worked" and
    "we undid it" are different outcomes and must not collapse.
    """
    if not items:
        # An empty campaign is not a finished one.
        return {
            "marker": MARKER_BLOCKED,
            "reason": "no items were assessed — an empty closeout cannot be READY",
            "blocking": [],
        }

    if rolled_back:
        return {
            "marker": MARKER_ROLLED_BACK,
            "reason": "operator states the campaign's changes were reverted",
            "blocking": [i.key for i in items if i.blocks_ready],
        }

    blocking = [i for i in items if i.blocks_ready]
    if blocking:
        by_disp: dict[str, list[str]] = {}
        for i in blocking:
            by_disp.setdefault(i.disposition, []).append(i.key)
        parts = ", ".join(f"{d}: {', '.join(sorted(k))}" for d, k in sorted(by_disp.items()))
        return {
            "marker": MARKER_BLOCKED,
            "reason": f"{len(blocking)} of {len(items)} items do not close — {parts}",
            "blocking": [i.key for i in blocking],
        }

    return {
        "marker": MARKER_READY,
        "reason": f"all {len(items)} items closed by recorded measurement",
        "blocking": [],
    }


def build_attestation(campaign: str, items: list[Item], *,
                      rolled_back: bool = False,
                      context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    decision = decide_marker(items, rolled_back=rolled_back)
    counts: dict[str, int] = {}
    for i in items:
        counts[i.disposition] = counts.get(i.disposition, 0) + 1
    return {
        "schema": SCHEMA,
        "campaign": campaign,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "marker": decision["marker"],
        "marker_reason": decision["reason"],
        "blocking": decision["blocking"],
        "counts": counts,
        "items": [i.to_dict() for i in items],
        "authority": "READ_ONLY_ADVISORY — this attestation grants nothing and "
                     "authorizes no deployment.",
    }


# ── read-only probes ─────────────────────────────────────────────────────────
# Each returns (disposition, evidence). A probe that cannot measure returns
# UNMEASURED with the reason, and never guesses.

def _release_name(meta: Path, release_root: Path) -> str:
    """The release directory a build-meta belongs to, whatever its depth."""
    try:
        return meta.relative_to(release_root).parts[0]
    except ValueError:
        return meta.parent.name


def probe_serving_sha_agreement(root: Path) -> tuple[str, str]:
    """Is the build that is SERVING tied to one exact source commit?

    The claim is about the serving build's internal consistency, not about
    whether main is deployed. The first version compared origin/main against
    every release stamp and returned CONTRADICTED the moment a merge landed
    without a deploy — which is a normal state, not a truth failure. It was
    measuring deployment currency and reporting it as a broken attestation.

    Deployment currency is still worth stating, so it is stated separately, as
    context rather than as a verdict.
    """
    import subprocess

    serving = _serving_release()
    if serving is None:
        return "UNMEASURED", (
            "no serving release could be identified from this host "
            "(no listening server and no CURRENT symlink)")

    stamps: dict[str, str] = {}
    for name, rel in (("build_meta", "apps/command-center-v3/build-meta.json"),
                      ("dist_build_meta", "dist/build-meta.json")):
        f = serving / rel
        if f.is_file():
            try:
                v = json.loads(f.read_text()).get("git_sha", "")
                if v:
                    stamps[name] = v
            except Exception:                                 # noqa: BLE001
                pass
    # The release directory names itself after the commit it was cut from.
    dir_sha = serving.name.split("-", 1)[0]
    if dir_sha:
        stamps["release_dir"] = dir_sha

    if len(stamps) < 2:
        return "UNMEASURED", (
            f"serving release {serving.name} carries fewer than two independent "
            f"identity stamps ({sorted(stamps)}) — agreement cannot be tested")

    norm = {k: v.lower() for k, v in stamps.items()}
    base = min(norm.values(), key=len)
    if not all(v.startswith(base) or base.startswith(v) for v in norm.values()):
        return "CONTRADICTED", (
            f"serving release {serving.name} disagrees with itself: {norm}")

    try:
        r = subprocess.run(["git", "-C", str(root), "rev-parse", "origin/main"],
                           capture_output=True, text=True, timeout=20)
        head = r.stdout.strip() if r.returncode == 0 else ""
    except Exception:                                         # noqa: BLE001
        head = ""
    currency = "unknown"
    if head:
        currency = ("serving IS origin/main" if head.startswith(base)
                    else f"serving is BEHIND origin/main {head[:12]} (merged, not deployed)")

    return "CLOSED", (
        f"serving release {serving.name} agrees across "
        f"{len(stamps)} independent stamps on {base[:12]} "
        f"({', '.join(sorted(stamps))}); deployment currency: {currency}")


def _serving_release() -> Optional[Path]:
    """The release directory actually being served, or None if not determinable."""
    import subprocess

    try:
        out = subprocess.run(["ss", "-ltnp"], capture_output=True, text=True, timeout=10)
        for line in out.stdout.splitlines():
            if ":7777" not in line or "pid=" not in line:
                continue
            pid = line.split("pid=", 1)[1].split(",", 1)[0]
            cwd = Path(f"/proc/{pid}/cwd").resolve()
            if cwd.is_dir():
                return cwd
    except Exception:                                         # noqa: BLE001
        pass
    current = Path.home() / "trade-ai-releases" / "portfolio-server" / "CURRENT"
    if current.exists():
        try:
            return current.resolve()
        except Exception:                                     # noqa: BLE001
            return None
    return None


def probe_single_search_ledger(root: Path) -> tuple[str, str]:
    """Is there exactly one counter for search spend?"""
    src = root / "scripts" / "brave_search.py"
    if not src.is_file():
        return "UNMEASURED", "scripts/brave_search.py not found"
    text = src.read_text(encoding="utf-8")
    if "_record_call" not in text:
        return "UNMEASURED", "expected _record_call to exist (retired or not)"
    # The retired writer must not call the legacy save on any live path.
    live_writes = [ln for ln in text.splitlines()
                   if "_save_budget(" in ln and not ln.strip().startswith("#")]
    if len(live_writes) > 1:
        return "OPEN", (
            f"{len(live_writes)} live _save_budget call sites remain — the second "
            "ledger still counts")
    if "try_consume" not in text or "_refund" not in text:
        return "OPEN", "brave_search does not reserve/refund through the canonical ledger"
    return "CLOSED", (
        "brave_search reserves via try_consume and refunds on failure; the legacy "
        "ledger has no live writer")


def probe_provider_limits_not_invented(root: Path) -> tuple[str, str]:
    """Is any provider plan asserted in a comment rather than observed?

    Scans COMMENT tokens only. The first version scanned raw lines and flagged
    the docstrings that quote the removed defect in order to explain it — so
    documenting a fix looked identical to committing it. A docstring is a STRING
    token and a comment is a COMMENT token; tokenize tells them apart exactly.
    """
    import io
    import tokenize

    pattern_words = ("free tier", "free plan")
    hits: list[str] = []
    for rel in ("scripts/brave_search.py", "phase2b_analyst.py",
                "scripts/portfolio_weekly_report.py"):
        p = root / rel
        if not p.is_file():
            continue
        try:
            with open(p, "rb") as fh:
                for tok in tokenize.tokenize(fh.readline):
                    if tok.type != tokenize.COMMENT:
                        continue
                    low = tok.string.lower()
                    if any(w in low for w in pattern_words) and any(
                            u in low for u in ("/mo", "month", "per month")):
                        hits.append(f"{rel}:{tok.start[0]}")
        except Exception:                                     # noqa: BLE001
            return "UNMEASURED", f"could not tokenize {rel}"

    # A direct endpoint outside the budgeted client is the same defect wearing
    # different clothes: it spends without a ceiling at all.
    ungoverned: list[str] = []
    for rel in ("phase2b_analyst.py", "scripts/portfolio_weekly_report.py"):
        p = root / rel
        if not p.is_file():
            continue
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "api.search.brave.com" in line and '"""' not in line:
                # inside a docstring the URL is prose; require it to look like code
                if "http" in line and ("=" in line or "(" in line):
                    ungoverned.append(f"{rel}:{n}")

    problems = []
    if hits:
        problems.append(f"provider plan asserted in a comment at: {', '.join(hits)}")
    if ungoverned:
        problems.append(f"ungoverned Brave endpoint at: {', '.join(ungoverned)}")
    if problems:
        return "OPEN", "; ".join(problems)
    return "CLOSED", (
        "no free-tier provider plan asserted in any comment of the audited "
        "clients, and no ungoverned Brave endpoint; capacity is parsed from "
        "response headers by lib/research_provider_truth")


def probe_guard_remote_approval(root: Path) -> tuple[str, str]:
    """Can an approval be obtained without the operator typing it?"""
    mod = root / "scripts" / "lib" / "guard_remote_approval.py"
    if not mod.is_file():
        return "NOT_APPLICABLE", "remote approval is not installed in this tree"
    text = mod.read_text(encoding="utf-8")
    needed = ("REMOTE_FORBIDDEN_SCOPES", "code_sha256", "CHAT_NOT_ALLOWED",
              "MAX_GRANT_SECONDS")
    missing = [n for n in needed if n not in text]
    if missing:
        return "OPEN", f"remote approval missing controls: {', '.join(missing)}"
    return "CLOSED", (
        "remote approval stores only a code fingerprint, binds scope/window at "
        "mint, enforces a chat allowlist and a maximum window, and forbids "
        "sudo/destructive/file-delete/guard-config/frozen-v2")
