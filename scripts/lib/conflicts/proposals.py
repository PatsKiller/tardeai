"""Unmatched conflicts -> AI-proposed rule -> operator approval -> versioned rulebook amendment.

Operator 2026-10-25 (verbatim): "if no rules on the resolution matches, it should put it out to AI to fix and
recommend a new resolution for my approval right there on that same page."

Four parts, one module (docs/ops/CONFLICT_RULE_PROPOSALS.md):

1. ``detect_unmatched`` (pure): a disagreement no rule/profile classifies becomes kind UNMATCHED: unknown domain,
   an input role the rulebook does not know, a stance label with no mapping after R8, a gate/protection/policy/safety
   value outside its known vocabulary, a schedule state outside the run map, an input the engine silently dropped,
   or a >=3-way split with no R11 finding. UNMATCHED is never auto-resolved and never dropped: it is reported with
   "AI proposal pending" and the engine's own finding (usually DATA_ERROR) still flags the card.
2. ``propose`` (job): one RuleProposal@v1 per pattern signature (not per row), rate-limited and capped, through the
   governed bridge (caller n8n_model_job, task conflict_rule_proposal -> grok OAuth -> chatgpt OAuth -> DeepSeek).
   Facts supplied: the pattern, example findings, the rulebook and the binding matrix (sha256-verified). The answer is
   validated here: schema, citations only to supplied fact ids, every number grounded in the supplied facts, the
   machine form limited to data under ``/amendments`` of the rulebook. Tier and never-auto are computed, never taken
   from the model.
3. ``decide`` (operator only; the API binds the identity): approve / edit-and-approve / reject. Approval appends a
   hash-chained RulebookAmendment@v1; the effective rulebook keeps the base version and matrix_sha256 and lists the
   amendments with their own sha256. A never-auto pattern (T0/T1/T2, safety, protection, policy, money, schedule,
   N-way with an owner side) can be proposed, but approval can never make it auto-resolvable.
4. ``notify_pending``: one grouped P2 comms intent for every new pending proposal, linking to the page.

Stores (append-only, data/conflicts/; proposed data_source_authority row ``conflict_rule_proposals``):
``rule_proposals.jsonl`` (RuleProposalEvent@v1) and ``rulebook_amendments.jsonl`` (RulebookAmendment@v1).
MBI_BEHAVIOR = 0: no broker, order, stop or size. This module never sends; the comms intent is queued.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Callable, Iterable, Optional

NO_CONSUMER_REASON = (
    "read by scripts/lib/conflicts/proposals_api.py (GET/POST /api/v3/conflicts/proposals) and the Conflict rules "
    "page; written by scripts/conflict_resolver.py (shadow: unmatched observations) and "
    "scripts/conflict_rule_proposals.py (proposal job)"
)
EVENT_SCHEMA = "RuleProposalEvent@v1"
PROPOSAL_SCHEMA = "RuleProposal@v1"
AMENDMENT_SCHEMA = "RulebookAmendment@v1"
EFFECTIVE_SCHEMA = "EffectiveConflictRulebook@v1"
UNMATCHED = "UNMATCHED"
PENDING, APPROVED, REJECTED = "PENDING", "APPROVED", "REJECTED"
EVENTS = {"unmatched_observed", "proposal_created", "proposal_failed", "decided", "notified", "notify_failed"}
DECISIONS = {"approve", "reject", "edit-and-approve"}
FINDING_KINDS = {"AGREEMENT", "SUPERSEDED", "CONFLICT", "GATE", "NEEDS_OPERATOR", "DATA_ERROR", UNMATCHED}
TIERS = ("T0", "T1", "T2", "T3", "T4")
ROLE_TIER = {"safety": 0, "protection": 1, "fact": 1, "policy": 2, "gate": 3, "claim": 4, "judgment": 4}
ROLE_CATEGORY = {"safety": "safety", "protection": "protection", "policy": "policy"}
DOMAIN_CATEGORY = {"numeric_fact": "money_mismatch", "schedule_state": "schedule_state"}
MACHINE_OPS = {"vocabulary_alias", "source_supersede_days", "source_label", "route_to_owner", "requires_code"}
AUTO_OPS = {"vocabulary_alias", "source_supersede_days"}
CONFIG_PATH = Path(__file__).resolve().parents[3] / "config/conflict_rule_proposals.json"
RULEBOOK_PATH = Path(__file__).resolve().parents[3] / "config/conflict_rulebook.json"
OUTPUT_KEYS = {"plain_rule", "tier", "proposed_resolution", "machine_form", "never_auto_implications", "test_cases",
               "risks", "citations", "confidence"}
_NUMBER = re.compile(r"(?<![A-Za-z0-9_.])-?\d+(?:\.\d+)?")


def _json(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False, default=str)


def _sha(value) -> str:
    return hashlib.sha256((value if isinstance(value, bytes) else _json(value).encode())).hexdigest()


def _iso(at: datetime) -> str:
    if not isinstance(at, datetime) or at.tzinfo is None:
        raise ValueError("explicit timezone-aware clock required")
    return at.isoformat()


def _at(value) -> Optional[datetime]:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else None
    except (TypeError, ValueError):
        return None


def _norm(value) -> str:
    return str(value or "").strip().upper().replace("-", "_").replace(" ", "_")


def load_config(path: Optional[Path] = None) -> dict:
    doc = json.loads(Path(path or CONFIG_PATH).read_text(encoding="utf-8"))
    if doc.get("schema") != "ConflictRuleProposalsConfig@v1":
        raise ValueError("unsupported conflict rule proposals config")
    return doc


def default_root() -> Path:
    """Same durable root as conflicts.api._root, without importing the API (keeps the lane's import closure small)."""
    from scripts.lib.persistent_state_root import resolve_durable_dir
    return Path(resolve_durable_dir("data/conflicts")).parent.parent


# ── 1. Unmatched detection (pure) ────────────────────────────────────────────────────────────────────────────────


def _rulebook():
    from .profiles.rulebook import RULEBOOK
    return RULEBOOK


def pattern_signature(pattern: dict) -> str:
    return "ups-" + _sha(pattern)[:24]


def pattern_policy(pattern: dict, rulebook: Optional[dict] = None) -> dict:
    """Tier and never-auto category are computed from the pattern, never taken from a model."""
    rulebook = rulebook or _rulebook()
    never = set(rulebook.get("never_auto", []))
    tier = ROLE_TIER.get(pattern.get("role"), 4)
    categories = set()
    if pattern.get("role") in ROLE_CATEGORY:
        categories.add(ROLE_CATEGORY[pattern["role"]])
    if pattern.get("domain") in DOMAIN_CATEGORY:
        categories.add(DOMAIN_CATEGORY[pattern["domain"]])
        tier = min(tier, 1)
    if pattern.get("gap") == "nway_uncovered" and pattern.get("owner_side"):
        categories.add("nway_recorded_split")
    if pattern.get("gap") == "unknown_domain":
        categories.add("unknown_domain")
    if pattern.get("gap") == "unknown_role":
        categories.add("unknown_role")
    categories = sorted(categories)
    never_auto = tier <= 2 or any(c in never for c in categories) or bool({"unknown_domain", "unknown_role"} & set(categories))
    return {"tier": f"T{tier}", "tier_rank": tier, "categories": categories, "never_auto": never_auto}


def _unmatched(bundle, pattern: dict, summary: str, sides: list, rulebook: dict) -> dict:
    from .engine import ENGINE_VERSION
    signature = pattern_signature(pattern)
    policy = pattern_policy(pattern, rulebook)
    return {"schema": "ConflictFinding@v1", "engine": ENGINE_VERSION, "kind": UNMATCHED, "rule": UNMATCHED,
            "summary": summary, "clears_when": "you approve a rule for this pattern (AI proposal pending)",
            "action": "ai_proposal", "severity": "warn", "sides": sides,
            "key": f"{bundle.subject.kind}:{bundle.subject.id}:UNMATCHED:{signature}", "owner": "the operator",
            "next_run": "next conflict-rule-proposals run", "never_auto": True, "tier": policy["tier_rank"],
            "signature": signature, "pattern": pattern, "policy": policy, "proposal_status": "AI proposal pending",
            "subject": {"kind": bundle.subject.kind, "id": bundle.subject.id, "label": bundle.subject.label}}


def detect_unmatched(bundle, findings: Iterable, *, profiles: Optional[dict] = None,
                     rulebook: Optional[dict] = None) -> list[dict]:
    """UNMATCHED findings for one evaluated subject. Never changes ``findings``; never resolves anything."""
    from .engine import side as engine_side
    from .profiles import PROFILES
    from .profiles.vocabulary import ordinal, posture
    profiles = PROFILES if profiles is None else profiles
    rulebook = rulebook or _rulebook()
    findings = [f.as_dict() if hasattr(f, "as_dict") else dict(f) for f in findings]
    profile = bundle.profile
    domain = getattr(profile, "name", None) or type(profile).__name__
    out: dict[str, dict] = {}

    def add(pattern, summary, item=None):
        pattern = {"domain": domain, "subject_kind": bundle.subject.kind, **pattern}
        try:
            sides = [engine_side(item, profile)] if item is not None else []
        except Exception:  # an unknown profile cannot describe its values
            sides = [{"source": item.source, "value": str(item.value)}] if item is not None else []
        row = _unmatched(bundle, pattern, summary, sides, rulebook)
        out.setdefault(row["key"], row)

    if domain not in profiles:
        add({"gap": "unknown_domain"}, f"No conflict profile covers '{domain}' subjects")
        return list(out.values())
    roles = set(rulebook.get("universal", {}).get("roles", []))
    sec = rulebook.get("security_stance", {})
    items = ([bundle.canonical] if bundle.canonical else []) + list(bundle.inputs)
    mentioned = {s.get("source") for f in findings for s in f.get("sides") or []}
    mentioned |= {part for f in findings for part in str(f.get("key", "")).split(":")}
    for item in items:
        role = item.role
        if role not in roles:
            add({"gap": "unknown_role", "role": str(role)}, f"{item.source}: input role '{role}' has no rule", item)
            continue
        label = _norm(item.value) if not isinstance(item.value, (dict, list)) else None
        if domain == "security_stance" and label is not None:
            if role in {"claim", "judgment"} and item.metadata.get("instrument", "equity") == "equity" and posture(label) is None:
                add({"gap": "vocabulary_unmapped", "role": "claim", "label": label,
                     "r8_listed": label in {_norm(v) for v in sec.get("unmapped_labels", [])}},
                    f"{item.source} says '{label}', which no vocabulary rule maps (R8)", item)
            elif role in {"gate", "protection", "safety"} and label not in {_norm(v) for v in sec.get(role + "_known", [])}:
                add({"gap": "vocabulary_unknown", "role": role, "label": label},
                    f"{item.source} reports {role} state '{label}', which no rule knows", item)
            elif role == "policy" and label not in {_norm(v) for v in sec.get("policy_known", [])}:
                add({"gap": "vocabulary_unknown", "role": role, "label": label},
                    f"{item.source} reports policy state '{label}', which no rule knows", item)
        if domain == "schedule_state" and label is not None and label not in rulebook.get("schedule_state", {}).get("runs", {}):
            add({"gap": "vocabulary_unknown", "role": role, "label": label},
                f"{item.source} reports schedule state '{label}', which no rule knows", item)
        dropped = (item is not bundle.canonical and role in {"claim", "fact", "judgment"} and item.source not in mentioned
                   and not item.metadata.get("conflict_key") and not item.metadata.get("paper")
                   and not item.metadata.get("intra_synthesis") and item.metadata.get("quality", "complete") == "complete")
        if dropped:
            add({"gap": "uncovered_input", "role": role, "source": item.source},
                f"{item.source} ({role}) produced no finding: no rule covers this input", item)
    if domain == "security_stance":
        held = bundle.subject.context.get("held")
        claims = [i for i in items if i.role in {"claim", "judgment"} and posture(i.value) is not None]
        ranks = {}
        for item in claims:
            rank = ordinal(item.value, held)
            if rank is not None:
                ranks.setdefault(rank, []).append(item.source)
        covered = any(f.get("rule") == "R11" or ":R11" in str(f.get("key", "")) for f in findings)
        if len(ranks) >= 3 and not covered:
            owner = any(i.metadata.get("recorded_by") in {"operator", "cio"} or i is bundle.canonical for i in claims)
            add({"gap": "nway_uncovered", "held": held, "ranks": sorted(ranks),
                 "sources": sorted(s for v in ranks.values() for s in v), "owner_side": owner},
                f"{len(ranks)}-way split with no N-way rule ({', '.join(sorted(s for v in ranks.values() for s in v))})")
    return list(out.values())


# ── amendments applied to a bundle before evaluation (data only) ─────────────────────────────────────────────────


def apply_amendments(bundle, effective: Optional[dict]):
    """Vocabulary aliases rewrite claim values (original kept in metadata); never touches gate/protection/policy."""
    overlay = (effective or {}).get("overlay") or {}
    aliases = overlay.get("vocabulary_aliases") or {}
    supersede = overlay.get("supersede_days") or {}
    if not aliases and not supersede:
        return bundle
    bundle = deepcopy(bundle)

    def rewrite(item):
        if item is None or item.role not in {"claim", "judgment"} or isinstance(item.value, (dict, list)):
            return item
        hit = aliases.get(_norm(item.value))
        if not hit:
            return item
        return replace(item, value=hit["maps_to"], metadata={**item.metadata, "amended_from": item.value,
                                                             "amendment_id": hit["amendment_id"]})
    bundle.canonical = rewrite(bundle.canonical)
    bundle.inputs = [rewrite(i) for i in bundle.inputs]
    return bundle


@contextmanager
def supersede_overlay(effective: Optional[dict]):
    """Scoped overlay of approved per-source supersede limits for one resolver run; restored afterwards."""
    rows = ((effective or {}).get("overlay") or {}).get("supersede_days") or {}
    target = _rulebook().get("security_stance", {}).setdefault("supersede_days", {})
    saved = {k: target[k] for k in rows if k in target}
    try:
        for source, row in rows.items():
            if source not in saved:  # an amendment never overrides a base limit
                target[source] = row["days"]
        yield
    finally:
        for source in rows:
            if source in saved:
                target[source] = saved[source]
            else:
                target.pop(source, None)


def route_findings(unmatched: list[dict], effective: Optional[dict]) -> tuple[list, list[dict]]:
    """Approved route_to_owner amendments turn their UNMATCHED pattern into a ledger-visible owner finding."""
    from .engine import Finding
    routes = ((effective or {}).get("overlay") or {}).get("routes") or {}
    specs = ((effective or {}).get("overlay") or {}).get("specs") or {}
    routed, remaining = [], []
    for row in unmatched:
        route = routes.get(row["signature"])
        if route:
            routed.append(Finding(route["kind"], route["amendment_id"], f"{row['summary']} — rule {route['amendment_id']}: "
                                  f"{route['plain_rule'][:160]}", f"{route['owner']} decides (rule {route['amendment_id']})",
                                  "notify_operator" if route["owner"] == "operator" else "queue_review",
                                  "operator" if route["kind"] == "NEEDS_OPERATOR" else "warn", row["sides"],
                                  row["key"].replace(":UNMATCHED:", f":{route['amendment_id']}:"),
                                  owner="the operator" if route["owner"] == "operator" else "the CIO",
                                  never_auto=True, tier=row["tier"]))
            continue
        if row["signature"] in specs:
            row = {**row, "proposal_status": f"Rule {specs[row['signature']]['amendment_id']} approved; needs an engine change"}
        remaining.append(row)
    return routed, remaining


def evaluate(bundle, *, now, history=(), effective=None, evaluate_inputs=None):
    """The ONE resolver hook: amendments -> unchanged engine -> unmatched detection -> approved routes."""
    if evaluate_inputs is None:
        from .adapters import evaluate_inputs
    amended = apply_amendments(bundle, effective)
    with supersede_overlay(effective):
        current = evaluate_inputs(amended, now=now, history=history)
    unmatched = detect_unmatched(amended, current)
    routed, unmatched = route_findings(unmatched, effective)
    return [*current, *routed], unmatched


# ── stores ───────────────────────────────────────────────────────────────────────────────────────────────────────


class ProposalStore:
    def __init__(self, root):
        self.root = Path(root)
        self.path = self.root / "data/conflicts/rule_proposals.jsonl"
        self.amendments_path = self.root / "data/conflicts/rulebook_amendments.jsonl"

    @contextmanager
    def locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_suffix(".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    @staticmethod
    def _read(path: Path, schema: str) -> list[dict]:
        if not path.exists():
            return []
        rows = []
        prev = None
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            try:
                row = json.loads(line)
                if row["schema"] != schema or row["sequence"] != len(rows) + 1 or row.get("prev_sha256") != prev:
                    raise ValueError("schema, sequence or chain mismatch")
                body = {k: v for k, v in row.items() if k != "sha256"}
                if _sha(body) != row["sha256"]:
                    raise ValueError("row hash mismatch")
            except (KeyError, ValueError, TypeError) as exc:
                raise ValueError(f"invalid {path.name} row {number}") from exc
            rows.append(row)
            prev = row["sha256"]
        return rows

    def events(self) -> list[dict]:
        rows = self._read(self.path, EVENT_SCHEMA)
        if any(r.get("event") not in EVENTS for r in rows):
            raise ValueError("unknown rule proposal event")
        return rows

    def amendments(self) -> list[dict]:
        return self._read(self.amendments_path, AMENDMENT_SCHEMA)

    @staticmethod
    def _append_row(path: Path, schema: str, row: dict, existing: list[dict]) -> dict:
        row = {"schema": schema, **row, "sequence": len(existing) + 1,
               "prev_sha256": existing[-1]["sha256"] if existing else None}
        row["sha256"] = _sha(row)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(_json(row) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        existing.append(row)
        return row

    def append(self, event: dict, *, events: Optional[list] = None) -> dict:
        if event.get("event") not in EVENTS:
            raise ValueError("unknown rule proposal event")
        return self._append_row(self.path, EVENT_SCHEMA, event, self.events() if events is None else events)

    # projections ------------------------------------------------------------------------------------------------
    def state(self) -> dict:
        events = self.events()
        patterns: dict[str, dict] = {}
        proposals: dict[str, dict] = {}
        failures: dict[str, list] = {}
        notified: set = set()
        for event in events:
            kind = event["event"]
            if kind == "unmatched_observed":
                row = patterns.setdefault(event["signature"], {"signature": event["signature"], "pattern": event["pattern"],
                                                               "policy": event["policy"], "examples": [],
                                                               "first_seen": event["at"]})
                for example in event["examples"]:
                    if example["key"] not in {e["key"] for e in row["examples"]}:
                        row["examples"].append(example)
                row["summary"], row["last_seen"] = event["summary"], event["at"]
            elif kind == "proposal_created":
                proposal = deepcopy(event["proposal"])
                proposal.update(status=PENDING, revision=event["sequence"], decision=None, history=[])
                proposals[proposal["proposal_id"]] = proposal
            elif kind == "proposal_failed":
                failures.setdefault(event["signature"], []).append(
                    {"at": event["at"], "reason": event["reason"], "detail": event.get("detail"),
                     "cost_estimate_usd": event.get("cost_estimate_usd") or 0.0})
            elif kind == "decided":
                proposal = proposals[event["proposal_id"]]
                proposal.update(status=APPROVED if event["decision"]["decision"] != "reject" else REJECTED,
                                decision=deepcopy(event["decision"]), revision=event["sequence"])
            elif kind == "notified":
                notified |= set(event["proposal_ids"])
            if event.get("proposal_id") in proposals:
                proposals[event["proposal_id"]]["history"].append(
                    {"event": kind, "at": event["at"], "sequence": event["sequence"]})
        return {"patterns": patterns, "proposals": proposals, "failures": failures, "notified": notified,
                "events": events}


def _patch_for(form: dict) -> list[dict]:
    op = form.get("op")
    if op == "vocabulary_alias":
        return [{"op": "add", "path": f"/amendments/vocabulary_aliases/{form['label']}", "value": form["maps_to"]}]
    if op == "source_supersede_days":
        return [{"op": "add", "path": f"/amendments/supersede_days/{form['source']}", "value": form["days"]}]
    if op == "source_label":
        return [{"op": "add", "path": f"/amendments/source_labels/{form['source']}", "value": form["label"]}]
    if op == "route_to_owner":
        return [{"op": "add", "path": "/amendments/routes/-", "value": {"owner": form["owner"], "kind": form["kind"]}}]
    return [{"op": "add", "path": "/amendments/specs/-", "value": {"requires_code": form.get("reason")}}]


def validate_machine_form(form, pattern: dict, *, rulebook: Optional[dict] = None) -> tuple[Optional[dict], Optional[str]]:
    """Data-only machine forms. Returns (normalized form, refusal reason)."""
    from .profiles.vocabulary import posture
    rulebook = rulebook or _rulebook()
    if not isinstance(form, dict) or form.get("op") not in MACHINE_OPS:
        return None, "machine_form.op must be one of " + ", ".join(sorted(MACHINE_OPS))
    op = form["op"]
    allowed = {"vocabulary_alias": {"op", "label", "maps_to"}, "source_supersede_days": {"op", "source", "days"},
               "source_label": {"op", "source", "label"}, "route_to_owner": {"op", "owner", "kind"},
               "requires_code": {"op", "reason"}}[op]
    if set(form) - allowed:
        return None, f"machine_form has fields outside {sorted(allowed)}"
    if op == "vocabulary_alias":
        label, target = _norm(form.get("label")), _norm(form.get("maps_to"))
        if pattern.get("gap") != "vocabulary_unmapped" or pattern.get("role") != "claim":
            return None, "vocabulary_alias applies only to an unmapped stance label (claim role)"
        if label != pattern.get("label"):
            return None, "vocabulary_alias label must be the pattern's label"
        if posture(target) is None:
            return None, "vocabulary_alias maps_to must be a label the rulebook already maps"
        return {"op": op, "label": label, "maps_to": target}, None
    if op == "source_supersede_days":
        source = str(form.get("source") or "").strip()
        days = form.get("days")
        limit = rulebook.get("security_stance", {}).get("default_supersede_days", 14)
        if not source or source in rulebook.get("security_stance", {}).get("supersede_days", {}):
            return None, "source_supersede_days may only add a limit for a source that has none"
        if type(days) is not int or not 1 <= days <= limit:
            return None, f"source_supersede_days.days must be an integer 1..{limit} (R1)"
        return {"op": op, "source": source, "days": days}, None
    if op == "source_label":
        source, label = str(form.get("source") or "").strip(), str(form.get("label") or "").strip()
        if not source or not label or len(label) > 80:
            return None, "source_label needs a source and a label of at most 80 characters"
        return {"op": op, "source": source, "label": label}, None
    if op == "route_to_owner":
        if form.get("owner") not in {"operator", "cio"} or form.get("kind") not in {"NEEDS_OPERATOR", "CONFLICT"}:
            return None, "route_to_owner needs owner operator|cio and kind NEEDS_OPERATOR|CONFLICT"
        if form["owner"] == "cio" and (form["kind"] != "CONFLICT" or pattern.get("subject_kind") != "security"):
            return None, "the CIO owns only security stance conflicts"
        return {"op": op, "owner": form["owner"], "kind": form["kind"]}, None
    reason = str(form.get("reason") or "").strip()
    if not reason or len(reason) > 600:
        return None, "requires_code needs a reason (at most 600 characters)"
    return {"op": op, "reason": reason}, None


def never_auto_refusal(policy: dict, form: dict) -> Optional[str]:
    if form.get("op") in AUTO_OPS and policy.get("never_auto"):
        what = ", ".join(policy.get("categories") or []) or "a fact/policy tier"
        return (f"This pattern is {policy['tier']} ({what}). The rulebook never resolves it automatically, so a rule "
                f"that would ('{form['op']}') cannot be approved. Approve it as 'route to owner' or 'requires code', "
                f"or reject it.")
    return None


# ── 2. effective rulebook (base + amendments) ────────────────────────────────────────────────────────────────────


def effective_rulebook(root, *, rulebook_path: Optional[Path] = None) -> dict:
    base_bytes = Path(rulebook_path or RULEBOOK_PATH).read_bytes()
    base = json.loads(base_bytes)
    amendments = ProposalStore(root).amendments()
    overlay = {"vocabulary_aliases": {}, "supersede_days": {}, "source_labels": {}, "routes": {}, "specs": {}}
    for row in amendments:
        rule, aid = row["rule"], row["amendment_id"]
        form = rule["machine_form"]
        if form["op"] == "vocabulary_alias":
            overlay["vocabulary_aliases"][form["label"]] = {"maps_to": form["maps_to"], "amendment_id": aid}
        elif form["op"] == "source_supersede_days":
            overlay["supersede_days"][form["source"]] = {"days": form["days"], "amendment_id": aid}
        elif form["op"] == "source_label":
            overlay["source_labels"][form["source"]] = {"label": form["label"], "amendment_id": aid}
        elif form["op"] == "route_to_owner":
            overlay["routes"][row["signature"]] = {**{k: form[k] for k in ("owner", "kind")}, "amendment_id": aid,
                                                   "plain_rule": rule["plain_rule"]}
        else:
            overlay["specs"][row["signature"]] = {"amendment_id": aid, "reason": form["reason"]}
    return {"schema": EFFECTIVE_SCHEMA, "base_version": base.get("version"),
            "version": f"{base.get('version')}.{len(amendments)}", "amendment_count": len(amendments),
            "status": base.get("status"), "matrix_sha256": base.get("matrix_sha256"),
            "base_rulebook_sha256": hashlib.sha256(base_bytes).hexdigest(),
            "amendments_head_sha256": amendments[-1]["sha256"] if amendments else None,
            "amendments": [{"amendment_id": r["amendment_id"], "sha256": r["sha256"], "proposal_id": r["proposal_id"],
                            "approved_by": r["provenance"]["approved_by"], "approved_at": r["provenance"]["approved_at"],
                            "plain_rule": r["rule"]["plain_rule"], "tier": r["rule"]["tier"],
                            "op": r["rule"]["machine_form"]["op"], "auto_resolvable": r["rule"]["auto_resolvable"],
                            "version_after": r["version_after"]} for r in amendments],
            "overlay": overlay}


# ── 3. proposal job ──────────────────────────────────────────────────────────────────────────────────────────────


def record_unmatched(root, unmatched: list[dict], *, at: datetime, run_id: str, config: Optional[dict] = None) -> list[dict]:
    """Shadow resolver runs append one observation per signature (new, new example, or refresh window)."""
    config = config or load_config()
    caps = config["caps"]
    store = ProposalStore(root)
    groups: dict[str, list] = {}
    for row in unmatched:
        groups.setdefault(row["signature"], []).append(row)
    written = []
    with store.locked():
        state = store.state()
        events = state["events"]
        for signature, rows in sorted(groups.items()):
            known = state["patterns"].get(signature)
            known_keys = {e["key"] for e in (known or {}).get("examples", [])}
            room = caps["max_examples_per_pattern"] - len(known_keys)
            fresh = [r for r in rows if r["key"] not in known_keys][:max(room, 0)]
            stale = known and _at(known["last_seen"]) and at - _at(known["last_seen"]) >= timedelta(
                hours=caps["observation_refresh_hours"])
            if known and not fresh and not stale:
                continue
            examples = [{"key": r["key"], "summary": r["summary"], "sides": r["sides"], "subject": r["subject"]}
                        for r in (fresh or rows[:1])]
            written.append(store.append({"event": "unmatched_observed", "signature": signature, "at": _iso(at),
                                         "run_id": run_id, "pattern": rows[0]["pattern"], "policy": rows[0]["policy"],
                                         "summary": rows[0]["summary"], "examples": examples,
                                         "occurrences": len(rows)}, events=events))
    return written


def matrix_text(root, config: dict, rulebook: dict) -> tuple[Optional[str], Optional[str]]:
    """The binding matrix, only if its bytes match the rulebook's matrix_sha256."""
    path = Path(root) / config["matrix_rel"]
    try:
        raw = path.read_bytes()
    except OSError:
        return None, "binding matrix not readable at " + config["matrix_rel"]
    if hashlib.sha256(raw).hexdigest() != rulebook.get("matrix_sha256"):
        return None, "binding matrix bytes do not match rulebook matrix_sha256"
    return raw.decode("utf-8"), None


def build_facts(pattern_row: dict, *, rulebook: dict, matrix: Optional[str]) -> dict:
    """Numbered supplied facts. The model may cite only these ids."""
    keep = ("version", "status", "never_auto", "universal", "security_stance", "numeric_fact", "schedule_state",
            "precedence", "hysteresis", "source_labels", "matrix_sha256")
    facts = {"F1": {"what": "unmatched pattern", "pattern": pattern_row["pattern"], "summary": pattern_row["summary"]},
             "F2": {"what": "computed tier and never-auto categories (binding; not yours to change)",
                    "policy": pattern_row["policy"]},
             "F3": {"what": "example findings", "examples": pattern_row["examples"]},
             "F4": {"what": "conflict rulebook (config/conflict_rulebook.json)", "rulebook": {k: rulebook.get(k) for k in keep}},
             "F5": {"what": "allowed machine forms (data only, under /amendments)", "ops": {
                 "vocabulary_alias": "{op, label, maps_to}: an unmapped stance label maps to a label the rulebook already maps",
                 "source_supersede_days": "{op, source, days}: a supersede limit for a source that has none (1..14)",
                 "source_label": "{op, source, label}: display name only",
                 "route_to_owner": "{op, owner: operator|cio, kind: NEEDS_OPERATOR|CONFLICT}: a human decides",
                 "requires_code": "{op, reason}: the rule needs an engine/profile change; the text is the spec"}}}
    if matrix:
        facts["F6"] = {"what": "binding exceptions matrix (sha256 = rulebook matrix_sha256)", "text": matrix}
    return facts


def build_messages(facts: dict) -> list[dict]:
    system = (
        "You draft ONE RuleProposal for the Trade-AI conflict engine for the operator to approve or reject. No rule in "
        "the rulebook classifies the supplied pattern. Use ONLY the supplied facts F1..Fn; cite every fact id you rely "
        "on in `citations`; never state a number that is not in the supplied facts. You never resolve anything: you "
        "propose. Safety, protection, policy, facts (tiers T0-T2) and every never_auto category stay human-decided; for "
        "those choose machine_form route_to_owner or requires_code. Return ONE JSON object with exactly these keys: "
        f"{sorted(OUTPUT_KEYS)}. plain_rule: one or two plain sentences. tier: one of {list(TIERS)}. "
        "proposed_resolution: list of {finding_key, resolution} for the example findings. machine_form: one object of "
        "the forms in F5. never_auto_implications: plain text. test_cases: 1-6 of {inputs: object, expected: {kind}}, "
        f"kind one of {sorted(FINDING_KINDS)}. risks: list of strings. citations: list of fact ids. confidence: 0..1."
    )
    return [{"role": "system", "content": system},
            {"role": "user", "content": "SUPPLIED FACTS\n" + json.dumps(facts, ensure_ascii=False, sort_keys=True, default=str)}]


def _numbers(text: str) -> set:
    out = set()
    for raw in _NUMBER.findall(text or ""):
        try:
            value = float(raw)
        except ValueError:
            continue
        out.add(value)
    return out


def validate_answer(answer, pattern_row: dict, facts: dict, *, rulebook: Optional[dict] = None) -> tuple[Optional[dict], Optional[str]]:
    """Deterministic acceptance of the model's JSON. Returns (normalized fields, refusal reason)."""
    if not isinstance(answer, dict) or set(answer) != OUTPUT_KEYS:
        return None, "schema_invalid: keys must be exactly " + ", ".join(sorted(OUTPUT_KEYS))
    if not isinstance(answer["plain_rule"], str) or not 10 <= len(answer["plain_rule"].strip()) <= 800:
        return None, "schema_invalid: plain_rule"
    if answer["tier"] not in TIERS:
        return None, "schema_invalid: tier"
    cites = answer["citations"]
    if not isinstance(cites, list) or not cites or any(c not in facts for c in cites):
        return None, "ungrounded: citations must name supplied fact ids"
    examples = {e["key"] for e in pattern_row["examples"]}
    resolution = answer["proposed_resolution"]
    if (not isinstance(resolution, list) or not resolution or len(resolution) > 20 or
            any(not isinstance(r, dict) or r.get("finding_key") not in examples or not isinstance(r.get("resolution"), str)
                or not r["resolution"].strip() for r in resolution)):
        return None, "schema_invalid: proposed_resolution must cover supplied example finding keys"
    tests = answer["test_cases"]
    if (not isinstance(tests, list) or not 1 <= len(tests) <= 6 or
            any(not isinstance(t, dict) or not isinstance(t.get("inputs"), dict) or not isinstance(t.get("expected"), dict)
                or t["expected"].get("kind") not in FINDING_KINDS for t in tests)):
        return None, "schema_invalid: test_cases"
    if not isinstance(answer["risks"], list) or any(not isinstance(r, str) for r in answer["risks"]):
        return None, "schema_invalid: risks"
    if not isinstance(answer["never_auto_implications"], str):
        return None, "schema_invalid: never_auto_implications"
    conf = answer["confidence"]
    if isinstance(conf, bool) or not isinstance(conf, (int, float)) or not 0 <= conf <= 1:
        return None, "schema_invalid: confidence"
    form, why = validate_machine_form(answer["machine_form"], pattern_row["pattern"], rulebook=rulebook)
    if why:
        return None, "machine_form_refused: " + why
    supplied = _numbers(json.dumps(facts, default=str))
    prose = " ".join([answer["plain_rule"], answer["never_auto_implications"], *answer["risks"],
                      *(r["resolution"] for r in resolution)])
    loose = sorted(n for n in _numbers(prose) if n not in supplied)
    if loose:
        return None, "ungrounded_number: " + ", ".join(f"{n:g}" for n in loose[:5])
    return {**answer, "machine_form": form, "plain_rule": answer["plain_rule"].strip()}, None


def _spent_today(state: dict, now: datetime) -> tuple[int, float, dict]:
    day = now.astimezone(timezone.utc).date()
    created = [p for p in state["proposals"].values() if _at(p["created_at"]) and _at(p["created_at"]).date() == day]
    cost = sum(float((p.get("cost") or {}).get("cost_estimate_usd") or 0) for p in created)
    attempts: dict[str, int] = {}
    for p in created:
        attempts[p["signature"]] = attempts.get(p["signature"], 0) + 1
    for signature, rows in state["failures"].items():
        for row in rows:
            if _at(row["at"]) and _at(row["at"]).date() == day:
                cost += float(row.get("cost_estimate_usd") or 0)
                attempts[signature] = attempts.get(signature, 0) + 1
    return len(created), cost, attempts


def due_patterns(state: dict, *, now: datetime, config: dict) -> list[dict]:
    """Signatures needing a proposal: none yet, not pending/approved, not inside a rejection cooldown."""
    caps = config["caps"]
    by_signature: dict[str, list] = {}
    for proposal in state["proposals"].values():
        by_signature.setdefault(proposal["signature"], []).append(proposal)
    due = []
    for signature, row in sorted(state["patterns"].items(), key=lambda kv: kv[1]["first_seen"]):
        prior = by_signature.get(signature, [])
        if any(p["status"] in {PENDING, APPROVED} for p in prior):
            continue
        rejected = [_at(p["decision"]["at"]) for p in prior if p["status"] == REJECTED and p.get("decision")]
        if rejected and now - max(rejected) < timedelta(days=caps["reject_cooldown_days"]):
            continue
        due.append(row)
    return due


def propose(root, *, now: datetime, governed_call: Optional[Callable] = None, apply: bool = False,
            config: Optional[dict] = None, rulebook: Optional[dict] = None, deferral: Optional[Callable] = None,
            sleep: Callable[[float], None] = lambda s: None, run_id: str = "") -> dict:
    """One proposal-job pass. ``apply=False`` is write-free and never calls a model."""
    config = config or load_config()
    rulebook = rulebook or _rulebook()
    caps = config["caps"]
    store = ProposalStore(root)
    state = store.state()
    due = due_patterns(state, now=now, config=config)
    made_today, cost_today, attempts = _spent_today(state, now)
    matrix, matrix_gap = matrix_text(root, config, rulebook)
    report = {"schema": "ConflictRuleProposalRun@v1", "run_id": run_id, "phase": "apply" if apply else "dry_run",
              "at": _iso(now), "due": [r["signature"] for r in due], "created": [], "failed": [], "skipped": [],
              "matrix_gap": matrix_gap, "caps": caps, "made_today": made_today,
              "cost_today_usd": round(cost_today, 6), "model_calls": 0}
    for row in due:
        signature = row["signature"]
        if len(report["created"]) >= caps["max_proposals_per_run"]:
            report["skipped"].append({"signature": signature, "reason": "max_proposals_per_run"})
            continue
        if made_today + len(report["created"]) >= caps["daily_proposal_cap"]:
            report["skipped"].append({"signature": signature, "reason": "daily_proposal_cap"})
            continue
        if cost_today >= caps["daily_cost_cap_usd"]:
            report["skipped"].append({"signature": signature, "reason": "daily_cost_cap_usd"})
            continue
        if attempts.get(signature, 0) >= caps["max_attempts_per_signature_per_day"]:
            report["skipped"].append({"signature": signature, "reason": "max_attempts_per_signature_per_day"})
            continue
        facts = build_facts(row, rulebook=rulebook, matrix=matrix)
        messages = build_messages(facts)
        size = len(_json(messages).encode())
        if size > caps["max_prompt_bytes"]:
            facts.pop("F6", None)
            messages = build_messages(facts)
            size = len(_json(messages).encode())
        if not apply:
            report["skipped"].append({"signature": signature, "reason": "dry_run", "prompt_bytes": size,
                                      "facts": sorted(facts)})
            continue
        decision = deferral(config["process_id"]) if deferral else None
        if decision is not None and getattr(decision, "defer", False):
            report["skipped"].append({"signature": signature, "reason": "offpeak_deferred",
                                      "run_after": str(getattr(decision, "run_after", ""))})
            continue
        if report["model_calls"]:
            sleep(caps["min_seconds_between_calls"])
        attempts[signature] = attempts.get(signature, 0) + 1
        report["model_calls"] += 1
        outcome = call_model(messages, row, facts, config=config, governed_call=governed_call, rulebook=rulebook,
                             request_id=f"{run_id or 'crp'}-{signature}"[:64])
        cost_today += float(outcome.get("cost_estimate_usd") or 0)
        with store.locked():
            if outcome.get("error"):
                event = store.append({"event": "proposal_failed", "signature": signature, "at": _iso(now),
                                      "run_id": run_id, "reason": outcome["error"], "detail": outcome.get("detail"),
                                      "route": outcome.get("route"), "cost_estimate_usd": outcome.get("cost_estimate_usd")})
                report["failed"].append({"signature": signature, "reason": outcome["error"], "sequence": event["sequence"]})
                continue
            proposal = make_proposal(row, outcome, facts, now=now, rulebook=rulebook)
            store.append({"event": "proposal_created", "proposal_id": proposal["proposal_id"], "at": _iso(now),
                          "run_id": run_id, "proposal": proposal})
            report["created"].append(proposal["proposal_id"])
    report["cost_today_usd"] = round(cost_today, 6)
    return report


def call_model(messages, row, facts, *, config, governed_call, rulebook, request_id) -> dict:
    from scripts.lib.n8n_model_job import governance_envelope, route_summary
    if governed_call is None:
        from scripts.lib.n8n_model_job import bridge_governed_call as governed_call
    try:
        result = governed_call(messages, process_id=config["process_id"], response_format={"type": "json_object"},
                               request_id=request_id, task_type=config["task_type"],
                               max_tokens=config["caps"]["max_output_tokens"])
    except Exception as exc:  # transport or stub failure is a typed refusal, never a fallback
        return {"error": "provider_outage", "detail": type(exc).__name__}
    if not isinstance(result, dict):
        return {"error": "governance_refused", "detail": "no result"}
    if result.get("error"):
        err = result["error"] if isinstance(result["error"], dict) else {"code": str(result["error"])}
        code = str(err.get("code") or "")
        reason = "over_cap" if ("CAP" in code or "BUDGET" in code) else "governance_refused"
        if int(err.get("status") or 0) >= 500 or any(t in code for t in ("PROVIDER", "TIMEOUT", "CIRCUIT")):
            reason = "provider_outage"
        return {"error": reason, "detail": code[:120]}
    gov = governance_envelope(result)
    if gov.get("process_id") not in (None, config["process_id"]):
        return {"error": "process_mismatch", "detail": str(gov.get("process_id"))[:80]}
    if not gov.get("governance_pass"):
        return {"error": "governance_refused", "detail": "governance_pass false"}
    cost = float(gov.get("cost_estimate") or 0)
    route = route_summary(gov)
    if cost > config["caps"]["per_call_cost_ceiling_usd"]:
        return {"error": "over_cap", "detail": f"call cost {cost} above ceiling", "cost_estimate_usd": cost, "route": route}
    try:
        content = result["choices"][0]["message"]["content"]
        answer = json.loads(content) if isinstance(content, str) else content
    except (KeyError, IndexError, TypeError, ValueError):
        return {"error": "invalid_json", "cost_estimate_usd": cost, "route": route}
    accepted, why = validate_answer(answer, row, facts, rulebook=rulebook)
    if why:
        return {"error": why.split(":", 1)[0], "detail": why[:300], "cost_estimate_usd": cost, "route": route}
    return {"answer": accepted, "cost_estimate_usd": cost, "route": route,
            "model": {"model_id": gov.get("model_id"), "provider": gov.get("provider"), "mock": bool(gov.get("mock")),
                      "reservation_id": gov.get("reservation_id"), "bridge_request_id": gov.get("request_id")}}


def make_proposal(row: dict, outcome: dict, facts: dict, *, now: datetime, rulebook: dict) -> dict:
    answer, policy = outcome["answer"], row["policy"]
    form = answer["machine_form"]
    tier = TIERS[min(TIERS.index(answer["tier"]), policy["tier_rank"])]
    auto = form["op"] in AUTO_OPS and not policy["never_auto"]
    implications = answer["never_auto_implications"]
    if policy["never_auto"]:
        implications = (f"Computed: {policy['tier']} never-auto ({', '.join(policy['categories']) or 'fact/policy tier'}); "
                        f"approval can only route it to a human or record a spec. Model: {implications}")
    proposal = {"schema": PROPOSAL_SCHEMA, "signature": row["signature"], "pattern": row["pattern"],
                "pattern_policy": policy, "example_findings": [e["key"] for e in row["examples"]],
                "summary": row["summary"], "plain_rule": answer["plain_rule"], "tier": tier, "model_tier": answer["tier"],
                "proposed_resolution": answer["proposed_resolution"], "machine_form": form, "patch": _patch_for(form),
                "auto_resolvable": auto, "never_auto": policy["never_auto"], "never_auto_implications": implications,
                "test_cases": answer["test_cases"], "risks": answer["risks"], "citations": answer["citations"],
                "confidence": answer["confidence"], "model": outcome["model"], "route": outcome["route"],
                "cost": {"cost_estimate_usd": outcome.get("cost_estimate_usd")},
                "facts_sha256": _sha(facts), "rulebook_matrix_sha256": rulebook.get("matrix_sha256"),
                "created_at": _iso(now), "status": PENDING}
    proposal["proposal_id"] = "rp-" + _sha({k: proposal[k] for k in ("signature", "created_at", "facts_sha256")})[:20]
    return proposal


# ── 4. operator decision ─────────────────────────────────────────────────────────────────────────────────────────


class DecisionRefused(ValueError):
    def __init__(self, status: int, code: str, reason: str = "") -> None:
        super().__init__(code)
        self.status, self.code, self.reason = status, code, reason


def decide(root, proposal_id: str, *, decision: str, reason: str, actor: str, at: datetime,
           expected_revision: Optional[int] = None, edited: Optional[dict] = None, apply_current_case: bool = False,
           rulebook_path: Optional[Path] = None, rulebook: Optional[dict] = None) -> dict:
    """Operator decision (the caller has proven operator identity). Appends; never edits or deletes."""
    if decision not in DECISIONS:
        raise DecisionRefused(400, "DECISION_INVALID", "decision must be approve, reject or edit-and-approve")
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 4000:
        raise DecisionRefused(400, "REASON_REQUIRED")
    if not actor:
        raise DecisionRefused(403, "AGENT_CALLER_REFUSED")
    rulebook = rulebook or _rulebook()
    store = ProposalStore(root)
    with store.locked():
        state = store.state()
        proposal = state["proposals"].get(proposal_id)
        if not proposal:
            raise DecisionRefused(404, "NOT_FOUND")
        if proposal["status"] != PENDING:
            raise DecisionRefused(409, "PROPOSAL_NOT_PENDING", proposal["status"])
        if expected_revision is not None and expected_revision != proposal["revision"]:
            raise DecisionRefused(409, "PROPOSAL_CHANGED", str(proposal["revision"]))
        rule = {k: deepcopy(proposal[k]) for k in ("plain_rule", "tier", "machine_form", "test_cases",
                                                    "never_auto_implications")}
        if decision == "edit-and-approve":
            if not isinstance(edited, dict) or not edited or set(edited) - {"plain_rule", "machine_form", "tier"}:
                raise DecisionRefused(400, "EDIT_INVALID", "edited may change plain_rule, machine_form and tier")
            if "plain_rule" in edited:
                if not isinstance(edited["plain_rule"], str) or not 10 <= len(edited["plain_rule"].strip()) <= 800:
                    raise DecisionRefused(400, "EDIT_INVALID", "plain_rule must be 10..800 characters")
                rule["plain_rule"] = edited["plain_rule"].strip()
            if "tier" in edited:
                if edited["tier"] not in TIERS:
                    raise DecisionRefused(400, "EDIT_INVALID", "tier must be T0..T4")
                rule["tier"] = edited["tier"]
            if "machine_form" in edited:
                form, why = validate_machine_form(edited["machine_form"], proposal["pattern"], rulebook=rulebook)
                if why:
                    raise DecisionRefused(400, "MACHINE_FORM_REFUSED", why)
                rule["machine_form"] = form
        elif edited:
            raise DecisionRefused(400, "EDIT_INVALID", "edited is only accepted with edit-and-approve")
        policy = proposal["pattern_policy"]
        # A tier can be made stricter by the operator, never looser than the computed pattern tier.
        rule["tier"] = TIERS[min(TIERS.index(rule["tier"]), policy["tier_rank"])]
        if decision != "reject":
            refusal = never_auto_refusal(policy, rule["machine_form"])
            if refusal:
                raise DecisionRefused(409, "NEVER_AUTO_REFUSED", refusal)
        at_iso = _iso(at)
        record = {"decision": decision, "actor_kind": "operator", "actor": actor, "reason": reason.strip(), "at": at_iso,
                  "expected_revision": proposal["revision"], "edited": bool(decision == "edit-and-approve")}
        amendment = None
        current_case = {"requested": bool(apply_current_case), "applied": False}
        if decision != "reject":
            existing = store.amendments()
            base_bytes = Path(rulebook_path or RULEBOOK_PATH).read_bytes()
            base = json.loads(base_bytes)
            number = len(existing) + 1
            rule.update(patch=_patch_for(rule["machine_form"]), never_auto=policy["never_auto"],
                        auto_resolvable=rule["machine_form"]["op"] in AUTO_OPS and not policy["never_auto"])
            amendment = store._append_row(store.amendments_path, AMENDMENT_SCHEMA, {
                "amendment_id": f"A{number}", "proposal_id": proposal_id, "signature": proposal["signature"],
                "rule": rule, "base": {"rulebook_version": base.get("version"), "matrix_sha256": base.get("matrix_sha256"),
                                       "rulebook_sha256": hashlib.sha256(base_bytes).hexdigest()},
                "version_after": f"{base.get('version')}.{number}",
                "provenance": {"proposal_id": proposal_id, "approved_by": actor, "approved_at": at_iso,
                               "reason": reason.strip(), "decision": decision, "edited": record["edited"],
                               "model": proposal.get("model"), "route": proposal.get("route"),
                               "facts_sha256": proposal.get("facts_sha256")}}, existing)
            record["amendment_id"] = amendment["amendment_id"]
            record["amendment_sha256"] = amendment["sha256"]
            if apply_current_case:
                # Recorded here as the operator's decision for the example cases. The conflict ledger takes a
                # chosen side only for owner-decidable stance conflicts; the next resolver run re-evaluates.
                current_case = {"requested": True, "applied": True, "recorded_in": "rule_proposals.jsonl",
                                "resolutions": deepcopy(proposal["proposed_resolution"]),
                                "takes_effect": "next conflict-resolver run re-evaluates these findings under "
                                                + amendment["amendment_id"]}
        record["current_case"] = current_case
        event = store.append({"event": "decided", "proposal_id": proposal_id, "at": at_iso, "decision": record})
    return {"ok": True, "event": event, "amendment": amendment, "current_case": current_case}


# ── 5. grouped notification ──────────────────────────────────────────────────────────────────────────────────────


def notify_pending(root, *, now: datetime, run_id: str, config: Optional[dict] = None,
                   queue: Optional[Callable] = None) -> dict:
    """One grouped P2 intent for every pending proposal not yet announced. Never per row; never a send."""
    config = config or load_config()
    store = ProposalStore(root)
    state = store.state()
    fresh = sorted(pid for pid, p in state["proposals"].items() if p["status"] == PENDING and pid not in state["notified"])
    if not fresh:
        return {"queued": False, "reason": "nothing_new"}
    pending = [p for p in state["proposals"].values() if p["status"] == PENDING]
    notify = config["notify"]
    titles = "; ".join(state["proposals"][pid]["summary"][:60] for pid in fresh[:3])
    summary = (f"{len(pending)} proposed conflict rule{'s' if len(pending) != 1 else ''} awaiting your approval "
               f"({len(fresh)} new): {titles}. Review: {notify['page_url']}")
    if queue is None:
        from .host_intent import queue_host_intent

        def queue(**kw):
            return queue_host_intent(ledger_path=None, **kw)
    try:
        receipt = queue(producer=notify["producer"], domain=notify["domain"], kind=notify["kind"],
                        subject=f"Conflict rules: {len(pending)} awaiting approval", summary=summary,
                        execution_id=run_id or "conflict-rule-proposals", node="notify_pending")
    except Exception as exc:
        reason = getattr(exc, "reason", type(exc).__name__)
        with store.locked():
            store.append({"event": "notify_failed", "at": _iso(now), "run_id": run_id, "proposal_ids": fresh,
                          "reason": str(reason)[:120]})
        return {"queued": False, "reason": str(reason)}
    with store.locked():
        store.append({"event": "notified", "at": _iso(now), "run_id": run_id, "proposal_ids": fresh,
                      "receipt": {k: receipt.get(k) for k in ("intent_id", "duplicate", "status") if k in receipt},
                      "summary": summary})
    return {"queued": True, "proposal_ids": fresh, "summary": summary}


# ── read model for the page ──────────────────────────────────────────────────────────────────────────────────────


def proposal_view(proposal: dict) -> dict:
    hidden = {"facts_sha256"}
    return {k: v for k, v in proposal.items() if k not in hidden}


def collection(root, *, status: Optional[str] = None, limit: int = 50, offset: int = 0,
               config: Optional[dict] = None) -> dict:
    config = config or load_config()
    state = ProposalStore(root).state()
    rows = sorted(state["proposals"].values(), key=lambda p: p["created_at"], reverse=True)
    rows.sort(key=lambda p: p["status"] != PENDING)  # pending first, newest first within each group
    if status and status != "ALL":
        rows = [p for p in rows if p["status"] == status]
    proposed = {p["signature"]: p for p in state["proposals"].values()}
    unmatched = []
    for signature, row in sorted(state["patterns"].items(), key=lambda kv: kv[1]["last_seen"], reverse=True):
        latest = proposed.get(signature)
        failure = (state["failures"].get(signature) or [None])[-1]
        status_text = ("AI proposal pending" if not latest else
                       {PENDING: "Proposed rule awaiting your approval", APPROVED: "Rule approved",
                        REJECTED: "Proposal rejected"}[latest["status"]])
        unmatched.append({"signature": signature, "summary": row["summary"], "pattern": row["pattern"],
                          "policy": row["policy"], "examples": row["examples"], "first_seen": row["first_seen"],
                          "last_seen": row["last_seen"], "proposal_status": status_text,
                          "proposal_id": latest["proposal_id"] if latest else None,
                          "last_failure": failure})
    counts = {"pending": sum(p["status"] == PENDING for p in state["proposals"].values()),
              "approved": sum(p["status"] == APPROVED for p in state["proposals"].values()),
              "rejected": sum(p["status"] == REJECTED for p in state["proposals"].values()),
              "unmatched_awaiting_ai": sum(u["proposal_status"] == "AI proposal pending" for u in unmatched)}
    page = rows[offset:offset + min(max(limit, 1), 200)]
    return {"schema": "RuleProposalCollection@v1", "proposals": [proposal_view(p) for p in page], "total": len(rows),
            "offset": offset, "unmatched": unmatched, "counts": counts,
            "decisions_enabled": bool(config.get("decision_writes_enabled")),
            "as_of": max((e["at"] for e in state["events"]), default=None)}
