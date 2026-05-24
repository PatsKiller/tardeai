#!/usr/bin/env python3
"""agent_router.py — deterministic-first routing for Trade AI agents.

Routes a user request to the correct specialist agent, checks whether the request
is read-only or requires write approval, performs lightweight data freshness
checks, and optionally records the handoff to Postgres.

Install target:
    scripts/agent_router.py

Typical usage:
    python3 scripts/agent_router.py --message "maria should DGRO be added and which portfolio?"
    python3 scripts/agent_router.py --message "add DGRO to rebalancing" --from-agent maria --json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from agent_reliability import get_agent_reliability

# Pipeline telemetry
try:
    from pipeline_registry import PipelineRun
except ImportError:
    class PipelineRun:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def rows(self, n): pass

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "agents.json"
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
ASSETS_DIR = PROJECT_ROOT / "assets"

WRITE_WORDS = {
    "update", "write", "save", "add to", "add it to", "add this to", "add that to",
    "change", "modify", "delete", "remove", "email me", "send", "gmail", "apply",
    "commit", "edit", "append", "create", "write back", "record", "persist",
    "add to rebalancing", "add it to rebalancing", "update rebalancing", "yaml", "database",
}

ACTION_WORDS = {
    "add", "buy", "trim", "sell", "reduce", "exit", "rebalance", "target", "stop",
    "honor", "delay", "override", "allocate", "increase", "decrease",
}

TICKER_RE = re.compile(r"\b[A-Z]{1,5}(?:\.[A-Z])?\b")
MONEY_RE = re.compile(r"\$\s?([0-9][0-9,]*(?:\.[0-9]+)?)([kKmM]?)")


@dataclass
class RouteResult:
    created_at: str
    user_message: str
    from_agent: str
    to_agent: str
    intent: str
    confidence: float
    reason: str
    action_type: str
    status: str
    source_required: bool
    freshness_ok: Optional[bool]
    freshness_issues: List[str]
    high_impact: bool
    reviewers: List[str]
    context_packet: Dict[str, Any]
    pending_actions: List[Dict[str, Any]]
    short_telegram: str
    full_dashboard: str


def _load_env() -> None:
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def _load_config(path: Path = DEFAULT_CONFIG) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Agent config not found: {path}")
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
    else:
        try:
            import yaml  # type: ignore
        except Exception as exc:
            raise RuntimeError("PyYAML is required for YAML config. Use config/agents.json or install with: pip install pyyaml") from exc
        data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError(f"Invalid config file: {path}")
    return data


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _extract_tickers(text: str) -> List[str]:
    tickers = []
    for token in TICKER_RE.findall(text):
        if token in {"I", "A", "THE", "AND", "OR", "AI", "ETF", "IRA", "RMD", "SSDI"}:
            continue
        tickers.append(token)
    return sorted(set(tickers))


def _extract_amounts(text: str) -> List[float]:
    amounts = []
    for match in MONEY_RE.finditer(text):
        raw, suffix = match.groups()
        value = float(raw.replace(",", ""))
        if suffix.lower() == "k":
            value *= 1_000
        elif suffix.lower() == "m":
            value *= 1_000_000
        amounts.append(value)
    return amounts


def _keyword_score(text_norm: str, keywords: List[str]) -> Tuple[int, List[str]]:
    hits: List[str] = []
    for kw in keywords or []:
        k = str(kw).lower().strip()
        if not k:
            continue
        if k in text_norm:
            hits.append(k)
    return len(hits), hits


def _detect_write_action(text_norm: str) -> bool:
    return any(word in text_norm for word in WRITE_WORDS)


def _detect_action_request(text_norm: str) -> bool:
    return any(word in text_norm for word in ACTION_WORDS)


def _route_intent(text: str, config: Dict[str, Any]) -> Tuple[str, str, float, str, List[str]]:
    text_norm = _normalize_text(text)

    # Phase Router Tune 2026-04-26:
    # Deterministic obvious-intent overrides before generic keyword scoring.
    # This keeps routing from being too conservative and avoids sending clear
    # specialist requests back to the orchestrator.
    if re.search(r"\bmaria\b", text_norm):
        return "market_research", "maria", 0.95, "Explicit Maria request", ["maria"]

    if re.search(r"\bsteph\b", text_norm):
        return "portfolio_allocation", "steph", 0.95, "Explicit Steph request", ["steph"]

    if any(x in text_norm for x in ["which portfolio", "which account", "rollover ira", "where to put",
                                     "portfolio fit", "allocation", "target weight",
                                     "add to rebalancing", "add it to rebalancing", "update rebalancing"]):
        return "portfolio_allocation", "steph", 0.88, "Allocation/account placement intent -> Steph", ["allocation"]

    if any(x in text_norm for x in ["near my stop", "stop level", "honor stop", "ignore stop",
                                     "delay stop", "portfolio heat", "technical damage"]):
        return "stop_decision", "risk_agent", 0.88, "Stop/risk intent -> Risk Agent", ["risk"]

    if any(x in text_norm for x in ["roth", "taxable", "capital gains", "tax drag",
                                     "conversion", "asset location"]):
        return "tax_or_roth", "tax_agent", 0.88, "Tax/Roth intent -> Tax Agent", ["tax"]

    if any(x in text_norm for x in ["compare", "sector overlap", "holdings overlap", "analyst",
                                     "price target", "news", "reddit", "stocktwits", "yield",
                                     "expense ratio", "dividend growth"]):
        return "market_research", "maria", 0.86, "Research/comparison intent -> Maria", ["research"]
    intents = config.get("intents", {})
    best_intent = "general"
    best_agent = config.get("default_agent", "orchestrator")
    best_hits: List[str] = []
    best_score = 0

    for intent_name, intent_def in intents.items():
        score, hits = _keyword_score(text_norm, intent_def.get("keywords", []))
        if score > best_score:
            best_score = score
            best_hits = hits
            best_intent = intent_name
            best_agent = intent_def.get("agent", best_agent)

    # Direct agent name mentions should help but not blindly override allocation language.
    agents = config.get("agents", {})
    for agent_name, agent_def in agents.items():
        names = [agent_name, str(agent_def.get("title", "")).lower()]
        if any(name and name in text_norm for name in names):
            score, hits = _keyword_score(text_norm, agent_def.get("keywords", []))
            if score + 1 > best_score:
                best_score = score + 1
                best_hits = hits + [agent_name]
                best_agent = agent_name
                best_intent = _intent_for_agent(agent_name, config)

    # Confidence is intentionally simple and explainable.
    if best_score <= 0:
        return "general", config.get("default_agent", "orchestrator"), 0.30, "No strong keyword match", []

    confidence = min(0.95, 0.45 + (best_score * 0.12))
    reason = f"Matched intent '{best_intent}' via keywords: {', '.join(best_hits[:6])}"
    return best_intent, best_agent, confidence, reason, best_hits


def _intent_for_agent(agent: str, config: Dict[str, Any]) -> str:
    for intent_name, intent_def in config.get("intents", {}).items():
        if intent_def.get("agent") == agent and intent_name != "write_action":
            return intent_name
    return "general"


def _context_file_path(name: str) -> Path:
    if name.endswith(".yaml") or name.endswith(".yml"):
        return ASSETS_DIR / name if (ASSETS_DIR / name).exists() else PROJECT_ROOT / "config" / name
    return STATE_DIR / name


def _check_freshness(agent: str, config: Dict[str, Any]) -> Tuple[Optional[bool], List[str]]:
    agent_def = config.get("agents", {}).get(agent, {})
    required = agent_def.get("required_context", []) or []
    if not required:
        return None, []

    max_age = config.get("freshness", {}).get("max_age_hours", {}) or {}
    issues: List[str] = []
    now = datetime.now(timezone.utc).timestamp()

    for filename in required:
        path = _context_file_path(filename)
        if not path.exists():
            issues.append(f"MISSING: {filename}")
            continue
        limit = float(max_age.get(filename, 24))
        age_hours = (now - path.stat().st_mtime) / 3600.0
        if age_hours > limit:
            issues.append(f"STALE: {filename} is {age_hours:.1f}h old, max {limit:.0f}h")
    return len(issues) == 0, issues


def _detect_high_impact(text: str, config: Dict[str, Any], tickers: List[str], amounts: List[float]) -> Tuple[bool, List[str]]:
    text_norm = _normalize_text(text)
    hi = config.get("high_impact", {}) or {}
    threshold = float(hi.get("dollar_threshold", 10000))
    reviewers: List[str] = []

    if any(a >= threshold for a in amounts):
        reviewers.extend(["steph", "maria", "risk_agent"])

    concentration = set(hi.get("concentration_tickers", []) or [])
    if concentration.intersection(tickers) and _detect_action_request(text_norm):
        reviewers.extend(["steph", "tax_agent", "risk_agent"])

    for rule in hi.get("rules", []) or []:
        words = [str(x).lower() for x in rule.get("when_any", []) or []]
        rule_tickers = set(rule.get("tickers", []) or [])
        min_amount = rule.get("min_amount")
        word_hit = any(w in text_norm for w in words)
        ticker_hit = not rule_tickers or bool(rule_tickers.intersection(tickers))
        amount_hit = min_amount is None or any(a >= float(min_amount) for a in amounts)
        if word_hit and ticker_hit and amount_hit:
            reviewers.extend(rule.get("reviewers", []) or [])

    reviewers = sorted(set(reviewers))
    return bool(reviewers), reviewers


def build_route(message: str, from_agent: str = "user", config_path: Path = DEFAULT_CONFIG) -> RouteResult:
    config = _load_config(config_path)
    intent, to_agent, confidence, reason, hits = _route_intent(message, config)

    auto_threshold = float(config.get("confidence_thresholds", {}).get("auto_route", 0.70))
    review_threshold = float(config.get("confidence_thresholds", {}).get("orchestrator_review", 0.45))

    if confidence < review_threshold:
        to_agent = config.get("default_agent", "orchestrator")
        intent = "needs_clarification"
        reason = f"Low confidence route ({confidence:.2f}); sending to orchestrator"
    elif confidence < auto_threshold:
        to_agent = config.get("default_agent", "orchestrator")
        reason = f"Medium confidence route ({confidence:.2f}); orchestrator should review. Original match: {reason}"

    text_norm = _normalize_text(message)
    is_write = _detect_write_action(text_norm)
    action_type = "pending_write" if is_write else "read_only"
    status = "pending_approval" if is_write else "routed"

    agent_def = config.get("agents", {}).get(to_agent, {})
    source_required = bool(agent_def.get("source_required", False))
    freshness_ok, freshness_issues = _check_freshness(to_agent, config)

    tickers = _extract_tickers(message)
    amounts = _extract_amounts(message)
    high_impact, reviewers = _detect_high_impact(message, config, tickers, amounts)
    if high_impact and not is_write:
        # High impact recommendations may start read-only, but need multi-agent review before execution.
        status = "routed_multi_review"

    context_packet = {
        "tickers": tickers,
        "amounts": amounts,
        "keyword_hits": hits,
        "freshness_ok": freshness_ok,
        "freshness_issues": freshness_issues,
        "source_required": source_required,
        "requires_approval_before_write": is_write,
        "high_impact": high_impact,
        "reviewers": reviewers,
    }

    pending_actions: List[Dict[str, Any]] = []
    if is_write:
        pending_actions.append({
            "type": "approval_required",
            "message": "User requested a write/update action. Do not modify YAML, DB, alerts, Gmail, or app state until approved.",
        })
    if high_impact:
        pending_actions.append({
            "type": "multi_agent_review",
            "reviewers": reviewers,
            "message": "High-impact action or core holding detected; require reviewer agents before execution.",
        })
    if freshness_ok is False:
        pending_actions.append({
            "type": "freshness_warning",
            "issues": freshness_issues,
            "message": "Specialist advice should caveat or refresh stale/missing context first.",
        })

    short = f"Route: {to_agent} ({intent}, {confidence:.0%}). {reason}"
    if is_write:
        short += " Write approval required."
    if high_impact:
        short += f" Reviewers: {', '.join(reviewers)}."

    full = (
        f"Agent Router selected **{to_agent}** for intent **{intent}** with confidence {confidence:.0%}.\n\n"
        f"Reason: {reason}\n\n"
        f"Action type: {action_type}; status: {status}.\n"
        f"Tickers: {', '.join(tickers) if tickers else 'none detected'}.\n"
        f"Freshness: {'OK' if freshness_ok else ('not checked' if freshness_ok is None else 'issues found')}."
    )

    return RouteResult(
        created_at=datetime.now(timezone.utc).isoformat(),
        user_message=message,
        from_agent=from_agent,
        to_agent=to_agent,
        intent=intent,
        confidence=round(confidence, 4),
        reason=reason,
        action_type=action_type,
        status=status,
        source_required=source_required,
        freshness_ok=freshness_ok,
        freshness_issues=freshness_issues,
        high_impact=high_impact,
        reviewers=reviewers,
        context_packet=context_packet,
        pending_actions=pending_actions,
        short_telegram=short,
        full_dashboard=full,
    )


def save_handoff(result: RouteResult) -> bool:
    """Persist route result to Postgres if db_adapter is available."""
    _load_env()
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    try:
        from db_adapter import USE_DB, _execute  # type: ignore
    except Exception as exc:
        print(f"[agent_router] db_adapter unavailable: {exc}", file=sys.stderr)
        return False

    if not USE_DB:
        print("[agent_router] USE_DB is False; not writing handoff", file=sys.stderr)
        return False

    payload = asdict(result)
    res = _execute(
        """INSERT INTO agent_handoffs
           (user_message, from_agent, to_agent, intent, confidence, reason, action_type,
            status, source_required, freshness_ok, payload_json)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (
            result.user_message,
            result.from_agent,
            result.to_agent,
            result.intent,
            result.confidence,
            result.reason,
            result.action_type,
            result.status,
            result.source_required,
            result.freshness_ok,
            json.dumps(payload),
        ),
    )
    return res is not None


def render_for_agent(result: RouteResult) -> str:
    """Return a compact handoff packet for downstream agent prompts."""
    packet = {
        "handoff": {
            "from_agent": result.from_agent,
            "to_agent": result.to_agent,
            "intent": result.intent,
            "confidence": result.confidence,
            "reason": result.reason,
            "action_type": result.action_type,
            "status": result.status,
        },
        "context_packet": result.context_packet,
        "pending_actions": result.pending_actions,
        "instructions": [
            "Use current portfolio/app data before giving account, allocation, tax, or risk advice.",
            "Do not perform writes unless status is approved_write or the user explicitly approves after this handoff.",
            "If source_required is true, include source metadata in the final answer or dashboard card.",
        ],
    }
    return json.dumps(packet, indent=2)


def main() -> int:
    parser = argparse.ArgumentParser(description="Route a Trade AI user message to the correct agent.")
    parser.add_argument("--message", "-m", required=True, help="User message to route")
    parser.add_argument("--from-agent", default="user", help="Agent/user producing the message")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Path to agents.yaml")
    parser.add_argument("--json", action="store_true", help="Print full JSON route result")
    parser.add_argument("--handoff", action="store_true", help="Print downstream agent handoff packet")
    parser.add_argument("--save", action="store_true", help="Save route result to Postgres agent_handoffs")
    args = parser.parse_args()

    result = build_route(args.message, from_agent=args.from_agent, config_path=Path(args.config))

    if args.save:
        saved = save_handoff(result)
        if not saved:
            print("[agent_router] warning: route was not saved", file=sys.stderr)

    if args.handoff:
        print(render_for_agent(result))
    elif args.json:
        print(json.dumps(asdict(result), indent=2))
    else:
        print(result.short_telegram)
        if result.pending_actions:
            print("Pending actions:")
            for action in result.pending_actions:
                print(f"- {action['type']}: {action.get('message', '')}")
    return 0


if __name__ == "__main__":
    with PipelineRun("agent_router") as _run:
        raise SystemExit(main())


def _attach_reliability_context(route):
    """Attach DB-backed reliability context and reduce confidence if data history is weak."""
    try:
        agent = route.get("to_agent", "orchestrator")
        rel = get_agent_reliability(agent)
        route["reliability"] = rel

        adjustment = float(rel.get("confidence_adjustment", 0.0) or 0.0)
        old_conf = float(route.get("confidence", 0.0) or 0.0)
        new_conf = max(0.0, min(1.0, round(old_conf + adjustment, 2)))
        route["confidence_before_reliability"] = old_conf
        route["confidence"] = new_conf

        warnings = rel.get("warnings") or []
        if warnings:
            route.setdefault("pending_actions", []).append({
                "type": "reliability_warning",
                "message": "DB freshness history reduced confidence.",
                "warnings": warnings,
                "confidence_adjustment": adjustment,
            })
            route["short_telegram"] = (
                route.get("short_telegram", "")
                + f" Reliability score: {rel.get('reliability_score')}."
            )
            route["full_dashboard"] = (
                route.get("full_dashboard", "")
                + "\n\nReliability: "
                + "; ".join(warnings)
            )
        return route
    except Exception as exc:
        route.setdefault("pending_actions", []).append({
            "type": "reliability_error",
            "message": f"Could not load DB reliability context: {exc}",
        })
        return route
