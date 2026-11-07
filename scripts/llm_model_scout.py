#!/usr/bin/env python3
"""llm_model_scout.py — monthly Model Scout (LQ-20261107-197, DSN-20261107-ANTHROPIC-FIRST-ROUTING §5.2).

Read-only and advisory. It NEVER changes routing: it does not write config/llm_model_registry.json,
config/llm_task_classes.json or config/anthropic_credit_policy.json, and it calls no generation endpoint.

Steps:
  1. discover   GET each provider's list-models endpoint (Anthropic, DeepSeek, xAI while Grok is kept).
  2. diff       against config/llm_model_registry.json (+ the credit policy's tier models, which are routed):
                new ids; deprecated / retiring ids; routed ids the provider no longer lists (P1).
  3. price      price / context / output limit from the API where it says so, else the registry's curated
                row, else PRICE_UNCONFIRMED. A price is never guessed.
  4. eval       plan the frozen synthetic set (tests/fixtures/llm_eval) per new candidate in a family we use,
                capped at $2 per run. The scorer is here (score_case / run_eval with an injected generator);
                a live eval REFUSES with EVAL_RUNNER_NOT_GOVERNED until a governed model-override path exists.
  5. recommend  only from eval results; with none, the report says so.

Modes:
  --dry-run (default)  discover, diff and print; writes nothing.
  --write              also writes data/runtime/llm_model_scout/<YYYY-MM>.json, the lane receipt, and one
                       llm_model_scout_runs row when that table exists (the lead applies the migration).

Keys are read from the process environment, else from --env-file (default <repo>/.env), and are never printed:
every output string passes through a redactor holding the key values. A failed discovery is UNKNOWN, never a P1.

Exit: 0 ok; 3 a P1 finding (a routed model is no longer listed, or a routed model is marked retired);
1 no provider could be read; 2 refused (usage).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "scripts" / "lib", ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

LANE_ID = "llm-model-scout"
SCHEMA = "LlmModelScoutRun@v1"
EVAL_CAP_USD = Decimal("2.00")
EVAL_EST_INPUT_TOKENS = 400   # per case, prompt + system, generous
EVAL_EST_OUTPUT_TOKENS = 200  # per case
MAX_BODY_BYTES = 4 * 1024 * 1024
TIMEOUT_S = 20

PROVIDERS: dict[str, dict[str, Any]] = {
    "anthropic": {"url": "https://api.anthropic.com/v1/models", "key_names": ("ANTHROPIC_API_KEY",), "auth": "x-api-key",
                  "registered": True},
    "deepseek": {"url": "https://api.deepseek.com/v1/models", "key_names": ("deepseek_tradeai", "DEEPSEEK_API_KEY"),
                 "auth": "bearer", "registered": True},
    "xai": {"url": "https://api.x.ai/v1/models", "key_names": ("XAI_API_KEY",), "auth": "bearer", "registered": False},
}
KEY_NAMES = tuple(n for p in PROVIDERS.values() for n in p["key_names"])
DEPRECATION_FIELDS = ("deprecated", "deprecated_at", "deprecation_date", "retirement_date", "retires_at", "sunset_at")
CONTEXT_FIELDS = ("max_input_tokens", "context_window", "context_length")
OUTPUT_FIELDS = ("max_tokens", "max_output_tokens")
PRICE_FIELDS = ("pricing", "price")


# ---------------------------------------------------------------- secrets ----------------------------------------
class Redactor:
    """Replaces every known key value in a string. Built once per run; applied to everything printed or written."""

    def __init__(self, secrets: list[str]):
        self.secrets = sorted({s for s in secrets if s and len(s) >= 8}, key=len, reverse=True)

    def __call__(self, text: str) -> str:
        for s in self.secrets:
            text = text.replace(s, "[REDACTED]")
        return text

    def obj(self, value: Any) -> Any:
        return json.loads(self(json.dumps(value, default=str)))


def load_keys(env_file: Path | None, environ: dict | None = None) -> dict[str, str]:
    """Key values by name: the process environment first, then the env file. Values are never logged."""
    environ = os.environ if environ is None else environ
    keys = {n: environ[n] for n in KEY_NAMES if environ.get(n)}
    if env_file and env_file.is_file():
        try:
            lines = env_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, val = line.partition("=")
            name = name.strip().removeprefix("export ").strip()
            if name in KEY_NAMES and name not in keys:
                val = val.strip().strip('"').strip("'")
                if val:
                    keys[name] = val
    return keys


# ---------------------------------------------------------------- discover ---------------------------------------
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):  # noqa: ANN002, ANN003
        return None  # a key never follows a redirect off the fixed origin


def http_get(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with opener.open(req, timeout=TIMEOUT_S) as resp:  # noqa: S310 - fixed https origin
            return resp.status, resp.read(MAX_BODY_BYTES)
    except urllib.error.HTTPError as exc:
        return exc.code, b""


Fetch = Callable[[str, dict], "tuple[int, bytes]"]


def _headers(provider: str, key: str) -> dict[str, str]:
    h = {"User-Agent": "tradeai-model-scout/1.0", "Accept": "application/json"}
    if PROVIDERS[provider]["auth"] == "x-api-key":
        h.update({"x-api-key": key, "anthropic-version": "2023-06-01"})
    else:
        h["Authorization"] = f"Bearer {key}"
    return h


def _model_row(raw: dict) -> dict:
    row = {"id": str(raw.get("id"))}
    for k in ("display_name", "created_at", "created", "owned_by", *CONTEXT_FIELDS, *OUTPUT_FIELDS, *DEPRECATION_FIELDS,
              *PRICE_FIELDS):
        if raw.get(k) not in (None, ""):
            row[k] = raw[k]
    return row


def discover(provider: str, keys: dict[str, str], fetch: Fetch = http_get, max_pages: int = 20) -> dict:
    """List one provider's models. Never raises; a failure is a status, never a P1."""
    spec = PROVIDERS[provider]
    key = next((keys[n] for n in spec["key_names"] if keys.get(n)), None)
    if not key:
        return {"provider": provider, "status": "NO_KEY", "models": []}
    models: list[dict] = []
    url = spec["url"] + ("?limit=1000" if provider == "anthropic" else "")
    try:
        for _ in range(max_pages):
            status, body = fetch(url, _headers(provider, key))
            if status != 200:
                return {"provider": provider, "status": f"HTTP_{status}", "models": []}
            data = json.loads(body.decode("utf-8"))
            rows = data.get("data") if isinstance(data, dict) else None
            if not isinstance(rows, list):
                return {"provider": provider, "status": "BAD_SHAPE", "models": []}
            models += [_model_row(r) for r in rows if isinstance(r, dict) and r.get("id")]
            if provider == "anthropic" and data.get("has_more") and data.get("last_id"):
                url = spec["url"] + "?" + urllib.parse.urlencode({"limit": 1000, "after_id": data["last_id"]})
                continue
            break
    except Exception as exc:  # noqa: BLE001
        return {"provider": provider, "status": f"ERROR_{type(exc).__name__}", "models": []}
    return {"provider": provider, "status": "OK", "models": models}


# ---------------------------------------------------------------- registry ---------------------------------------
def _read_json(path: Path) -> dict:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def known_ids(registry: dict, policy: dict) -> dict[str, dict]:
    """Per registered provider: registered, routed, retired and rejected id sets plus the curated price rows."""
    out: dict[str, dict] = {}
    for prov, spec in (registry.get("providers") or {}).items():
        models = spec.get("models") or {}
        registered, routed, prices = set(), set(), {}
        for m in models.values():
            mid = m.get("model_id")
            if not mid:
                continue
            registered.add(mid)
            if m.get("enabled") and not m.get("historical_only"):
                routed.add(mid)
            if m.get("pricing_snapshot_usd_per_million_tokens"):
                prices[mid] = {"usd_per_mtok": m["pricing_snapshot_usd_per_million_tokens"], "source": "registry",
                               "effective_at": m.get("pricing_effective_at")}
            for k in ("context_window", "max_output_tokens"):
                if m.get(k):
                    prices.setdefault(mid, {})[k] = m[k]
        out[prov] = {"registered": registered, "routed": routed, "retired": set((spec.get("retired_models") or {})),
                     "rejected": set(spec.get("legacy_model_ids_rejected") or []), "curated": prices}
    anth = out.setdefault("anthropic", {"registered": set(), "routed": set(), "retired": set(), "rejected": set(),
                                        "curated": {}})
    tier_models = {v for v in (policy.get("models") or {}).values() if isinstance(v, str) and v}
    anth["routed"] |= tier_models
    anth["registered"] |= tier_models
    return out


# ---------------------------------------------------------------- diff -------------------------------------------
def _family(provider: str, model_id: str) -> str | None:
    mid = model_id.lower()
    if provider == "anthropic":
        return next((f for f in ("haiku", "sonnet", "opus", "fable") if f in mid), None)
    if provider == "deepseek":
        return "deepseek" if mid.startswith("deepseek") else None
    return None


def diff(provider: str, discovered: dict, known: dict | None) -> dict:
    """Pure. new / deprecated / missing_routed (P1) / retired_but_routed (P1) / registered_not_listed."""
    if discovered.get("status") != "OK":
        return {"provider": provider, "status": "UNKNOWN", "reason": discovered.get("status"), "findings": []}
    listed = {m["id"]: m for m in discovered["models"]}
    if known is None:
        return {"provider": provider, "status": "UNREGISTERED_PROVIDER", "listed": sorted(listed), "findings": []}
    findings: list[dict] = []
    skip = known["registered"] | known["retired"] | known["rejected"]
    for mid in sorted(set(listed) - skip):
        findings.append({"kind": "NEW_MODEL", "severity": "INFO", "model_id": mid, "family": _family(provider, mid),
                         "display_name": listed[mid].get("display_name")})
    for mid in sorted(known["routed"] - set(listed)):
        findings.append({"kind": "ROUTED_MODEL_NOT_LISTED", "severity": "P1", "model_id": mid,
                         "note": "a model we route to is no longer listed by the provider: a lane breaks silently"})
    for mid in sorted(known["routed"] & known["retired"]):
        findings.append({"kind": "ROUTED_MODEL_MARKED_RETIRED", "severity": "P1", "model_id": mid})
    for mid, row in sorted(listed.items()):
        dep = {k: row[k] for k in DEPRECATION_FIELDS if k in row and row[k] not in (False, None)}
        if dep:
            findings.append({"kind": "DEPRECATION_NOTICE", "severity": "P2" if mid in known["routed"] else "INFO",
                             "model_id": mid, "routed": mid in known["routed"], "provider_fields": dep})
    for mid in sorted((known["registered"] - known["routed"]) - set(listed)):
        findings.append({"kind": "REGISTERED_NOT_LISTED", "severity": "INFO", "model_id": mid,
                         "note": "registered but not routed (historical or disabled)"})
    return {"provider": provider, "status": "OK", "listed_count": len(listed), "findings": findings}


# ---------------------------------------------------------------- price ------------------------------------------
def price_row(provider: str, model_id: str, discovered: dict, known: dict | None) -> dict:
    """API metadata first, then the curated registry row, else PRICE_UNCONFIRMED. Never a guess."""
    api = next((m for m in discovered.get("models") or [] if m.get("id") == model_id), {})
    row: dict[str, Any] = {"model_id": model_id}
    ctx = next((api[k] for k in CONTEXT_FIELDS if api.get(k)), None)
    out = next((api[k] for k in OUTPUT_FIELDS if api.get(k)), None)
    curated = (known or {}).get("curated", {}).get(model_id) or {}
    row["context_window"] = ctx or curated.get("context_window")
    row["max_output_tokens"] = out or curated.get("max_output_tokens")
    api_price = next((api[k] for k in PRICE_FIELDS if api.get(k)), None)
    if api_price:
        row.update(price=api_price, price_source="provider_api", price_status="CONFIRMED")
    elif curated.get("usd_per_mtok"):
        row.update(price=curated["usd_per_mtok"], price_source="registry_curated", price_status="CONFIRMED",
                   price_effective_at=curated.get("effective_at"))
    else:
        row.update(price=None, price_source=None, price_status="PRICE_UNCONFIRMED",
                   note="no price in the provider's listing and no curated row: the lead confirms one before any eval")
    return row


# ---------------------------------------------------------------- eval -------------------------------------------
def load_eval_sets(fixtures: Path, classes: list[str]) -> dict[str, list[dict]]:
    sets = {}
    for cls in classes:
        doc = _read_json(fixtures / f"{cls}.json")
        sets[cls] = list(doc.get("cases") or [])
    return sets


def _usd_per_mtok(price: Any, field: str) -> Decimal | None:
    if not isinstance(price, dict):
        return None
    for k in ((field,) if field == "output" else ("cache_miss_input", "input")):
        if price.get(k) is not None:
            return Decimal(str(price[k]))
    return None


def eval_cost_estimate(price: Any, n_cases: int) -> Decimal | None:
    pin, pout = _usd_per_mtok(price, "input"), _usd_per_mtok(price, "output")
    if pin is None or pout is None:
        return None
    per_case = (pin * EVAL_EST_INPUT_TOKENS + pout * EVAL_EST_OUTPUT_TOKENS) / Decimal(1_000_000)
    return (per_case * n_cases).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def eval_plan(candidates: list[dict], sets: dict[str, list[dict]], cap: Decimal = EVAL_CAP_USD) -> dict:
    """Which (candidate, class) pairs fit under the cap, cheapest first. Unpriced candidates are blocked, not run."""
    n_per_class = {c: len(v) for c, v in sets.items()}
    items, blocked, spent = [], [], Decimal("0")
    for cand in candidates:
        if cand.get("price_status") != "CONFIRMED":
            blocked.append({"model_id": cand["model_id"], "reason": "EVAL_BLOCKED_PRICE_UNCONFIRMED"})
            continue
        for cls, n in n_per_class.items():
            est = eval_cost_estimate(cand.get("price"), n)
            if est is None:
                blocked.append({"model_id": cand["model_id"], "class": cls, "reason": "EVAL_BLOCKED_PRICE_SHAPE"})
            elif spent + est > cap:
                blocked.append({"model_id": cand["model_id"], "class": cls, "reason": "EVAL_CAP_REACHED",
                                "estimate_usd": str(est)})
            else:
                spent += est
                items.append({"model_id": cand["model_id"], "class": cls, "cases": n, "estimate_usd": str(est)})
    return {"cap_usd": str(cap), "planned_usd": str(spent), "items": items, "blocked": blocked}


def _norm(v: Any) -> Any:
    return v.strip().lower() if isinstance(v, str) else v


def score_case(case: dict, output_text: str) -> dict:
    """JSON validity and accuracy against the frozen expectation. Pure."""
    try:
        got = json.loads(output_text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip())
    except ValueError:
        return {"id": case["id"], "json_valid": False, "accuracy": 0.0}
    if not isinstance(got, dict):
        return {"id": case["id"], "json_valid": False, "accuracy": 0.0}
    exp, check = case["expected"], case.get("check") or {}
    if check.get("kind") == "summary":
        text = str(got.get("summary") or "")
        hits = sum(1 for t in exp["must_mention"] if t.lower() in text.lower())
        acc = hits / len(exp["must_mention"])
        if len(text.split()) > int(exp.get("max_words") or 10 ** 6):
            acc *= 0.5
        return {"id": case["id"], "json_valid": True, "accuracy": round(acc, 4)}
    tol = Decimal(str(check.get("numeric_tolerance") or 0))
    ok = 0
    for k, want in exp.items():
        have = got.get(k)
        if isinstance(want, bool) or isinstance(have, bool):
            ok += have is want
        elif isinstance(want, (int, float)):
            try:
                ok += abs(Decimal(str(have)) - Decimal(str(want))) <= tol
            except Exception:  # noqa: BLE001
                pass
        else:
            ok += _norm(have) == _norm(want)
    return {"id": case["id"], "json_valid": True, "accuracy": round(ok / max(len(exp), 1), 4)}


Generator = Callable[[str, dict], "dict"]  # (model_id, case) -> {"text", "usd", "latency_ms"}


def run_eval(model_id: str, cases: list[dict], generate: Generator, budget_usd: Decimal) -> dict:
    """Score one model on one class's cases through an injected generator; stops at the budget."""
    rows, spent = [], Decimal("0")
    for case in cases:
        if spent >= budget_usd:
            break
        res = generate(model_id, case)
        spent += Decimal(str(res.get("usd") or 0))
        s = score_case(case, str(res.get("text") or ""))
        s.update(latency_ms=res.get("latency_ms"), usd=str(res.get("usd") or 0))
        rows.append(s)
    n = len(rows) or 1
    return {"model_id": model_id, "cases": len(rows), "spent_usd": str(spent),
            "json_valid_rate": round(sum(r["json_valid"] for r in rows) / n, 4),
            "accuracy": round(sum(r["accuracy"] for r in rows) / n, 4), "rows": rows}


def recommend(results: dict[str, dict[str, dict]], incumbents: dict[str, str]) -> list[dict]:
    """From eval results only: a candidate beats its class incumbent on accuracy at no worse JSON validity.

    results: {class: {model_id: run_eval(...)}}; incumbents: {class: incumbent model_id}. Advisory text only."""
    recs = []
    for cls, by_model in results.items():
        inc = incumbents.get(cls)
        base = by_model.get(inc) if inc else None
        if not base:
            continue
        for mid, r in by_model.items():
            if mid == inc:
                continue
            if r["accuracy"] > base["accuracy"] and r["json_valid_rate"] >= base["json_valid_rate"]:
                recs.append({"class": cls, "candidate": mid, "incumbent": inc,
                             "accuracy_delta": round(r["accuracy"] - base["accuracy"], 4),
                             "cost_per_case_usd": str(Decimal(r["spent_usd"]) / max(r["cases"], 1)),
                             "action": "RECOMMEND_ONLY: the lead or operator approves; the registry change goes "
                                       "through the normal fold with the chooser in advise for 48 h"})
    return recs


# ---------------------------------------------------------------- run --------------------------------------------
def scout(*, keys: dict[str, str], registry: dict, policy: dict, fixtures: Path, task_classes: dict,
          fetch: Fetch = http_get, providers: tuple[str, ...] = tuple(PROVIDERS), now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    known = known_ids(registry, policy)
    eval_classes = list(task_classes.get("eval_classes") or [])
    sets = load_eval_sets(fixtures, eval_classes)
    discovered = {p: discover(p, keys, fetch) for p in providers}
    diffs, candidates = {}, []
    for p, d in discovered.items():
        reg = known.get(p) if PROVIDERS[p]["registered"] else None
        diffs[p] = diff(p, d, reg)
        created = {m["id"]: str(m.get("created_at") or "") for m in d["models"]}
        newest_routed: dict[str, str] = {}
        for m in (reg or {}).get("routed", set()):
            fam = _family(p, m)
            if fam:
                newest_routed[fam] = max(newest_routed.get(fam, ""), created.get(m, ""))
        for f in diffs[p]["findings"]:
            if f["kind"] == "NEW_MODEL":
                pr = price_row(p, f["model_id"], d, reg)
                f["price"] = pr
                f["created_at"] = created.get(f["model_id"]) or None
                fam = f.get("family")
                # A candidate is a new id in a family we route that is newer than the routed model of that family.
                # Without both dates it stays a candidate (the eval decides); an older id is listed, not evaluated.
                older = bool(fam in newest_routed and newest_routed[fam] and created.get(f["model_id"])
                             and created[f["model_id"]] <= newest_routed[fam])
                f["older_than_routed"] = older
                if fam and fam in newest_routed and not older:
                    candidates.append({**pr, "provider": p, "family": fam})
    p1 = [dict(f, provider=p) for p, dd in diffs.items() for f in dd["findings"] if f["severity"] == "P1"]
    plan = eval_plan(candidates, sets)
    return {
        "schema": SCHEMA, "lane_id": LANE_ID, "period": now.strftime("%Y-%m"), "generated_at": now.isoformat(),
        "authority": "READ_ONLY_ADVISORY: the scout never changes routing",
        "discovery": {p: {"status": d["status"], "listed": len(d["models"]),
                          "ids": sorted(m["id"] for m in d["models"])} for p, d in discovered.items()},
        "diff": diffs, "p1": p1,
        "eval": {"classes": eval_classes, "cases_per_class": {c: len(v) for c, v in sets.items()},
                 "candidates": candidates, "plan": plan, "results": None,
                 "status": "NOT_RUN: EVAL_RUNNER_NOT_GOVERNED (no governed model-override generation path yet)"
                 if candidates else "NO_CANDIDATES"},
        "recommendations": [], "recommendations_status": "NO_EVAL_RESULTS",
    }


def render(report: dict) -> str:
    lines = [f"Model Scout {report['period']} ({report['generated_at']})"]
    for p, d in report["discovery"].items():
        lines.append(f"  discover {p}: {d['status']} listed={d['listed']}")
    for p, dd in report["diff"].items():
        if dd["status"] != "OK":
            extra = dd.get("reason") or ", ".join(dd.get("listed") or [])
            lines.append(f"  diff {p}: {dd['status']} {extra}".rstrip())
            continue
        if not dd["findings"]:
            lines.append(f"  diff {p}: no change vs registry")
        for f in dd["findings"]:
            tail = ""
            if f["kind"] == "NEW_MODEL":
                pr = f.get("price") or {}
                tail = (f" family={f.get('family')} created={str(f.get('created_at') or '')[:10]} "
                        f"{'older-than-routed' if f.get('older_than_routed') else 'CANDIDATE' if f.get('family') else ''} "
                        f"price={pr.get('price_status')} ctx={pr.get('context_window')}")
            elif f["kind"] == "DEPRECATION_NOTICE":
                tail = " " + " ".join(f"{k}={v}" for k, v in f["provider_fields"].items()) + (
                    " (ROUTED)" if f.get("routed") else " (not routed)")
            lines.append(f"  diff {p}: [{f['severity']}] {f['kind']} {f['model_id']}{tail}")
    ev = report["eval"]
    lines.append(f"  eval: {ev['status']}; planned ${ev['plan']['planned_usd']} of ${ev['plan']['cap_usd']} "
                 f"({len(ev['plan']['items'])} items, {len(ev['plan']['blocked'])} blocked)")
    lines.append(f"  recommendations: {report['recommendations_status']}")
    lines.append(f"  P1: {len(report['p1'])}" + "".join(f"\n    P1 {f['provider']} {f['kind']} {f['model_id']}"
                                                          for f in report["p1"]))
    return "\n".join(lines)


def _state_root() -> Path:
    try:
        from canonical_store_registry import production_state_root  # type: ignore
        return Path(production_state_root())
    except Exception:  # noqa: BLE001
        return Path(os.environ.get("TRADEAI_STATE_ROOT") or ROOT)


def _db_insert(report: dict) -> str:
    try:
        from db_adapter import _execute  # type: ignore
        row = _execute("SELECT to_regclass('public.llm_model_scout_runs') AS t", None, "one")
        if not row or not (row.get("t") if isinstance(row, dict) else row[0]):
            return "TABLE_ABSENT"
        _execute("INSERT INTO llm_model_scout_runs (period, generated_at, p1_count, new_count, discovery, report) "
                 "VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb)",
                 (report["period"], report["generated_at"], len(report["p1"]),
                  sum(1 for d in report["diff"].values() for f in d["findings"] if f["kind"] == "NEW_MODEL"),
                  json.dumps(report["discovery"]), json.dumps(report)), None)
        return "INSERTED"
    except Exception as exc:  # noqa: BLE001
        return f"DB_ERROR_{type(exc).__name__}"


def main(argv: list[str] | None = None, *, fetch: Fetch = http_get, environ: dict | None = None) -> int:
    ap = argparse.ArgumentParser(description="Monthly Model Scout: discover, diff, price, eval plan; never routes.",
                                 allow_abbrev=False)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="discover, diff and print; write nothing (default)")
    mode.add_argument("--write", action="store_true", help="also write the monthly JSON, the receipt and a DB row")
    ap.add_argument("--eval", action="store_true", help="run the live eval (refuses: EVAL_RUNNER_NOT_GOVERNED)")
    ap.add_argument("--env-file", default=str(ROOT / ".env"), help="key source when the environment lacks a key")
    ap.add_argument("--providers", default=",".join(PROVIDERS), help="comma list of anthropic,deepseek,xai")
    ap.add_argument("--registry", default=str(ROOT / "config" / "llm_model_registry.json"))
    ap.add_argument("--policy", default=str(ROOT / "config" / "anthropic_credit_policy.json"))
    ap.add_argument("--task-classes", default=str(ROOT / "config" / "llm_task_classes.json"))
    ap.add_argument("--fixtures", default=str(ROOT / "tests" / "fixtures" / "llm_eval"))
    ap.add_argument("--json", action="store_true", help="print the full report JSON after the summary")
    args = ap.parse_args(argv)
    if args.eval:
        print("REFUSED: EVAL_RUNNER_NOT_GOVERNED — no governed generation path accepts a candidate model id yet; "
              "the eval plan is in the report.", file=sys.stderr)
        return 2
    provs = tuple(p for p in args.providers.split(",") if p)
    if any(p not in PROVIDERS for p in provs):
        print(f"REFUSED: unknown provider in {provs}", file=sys.stderr)
        return 2
    keys = load_keys(Path(args.env_file) if args.env_file else None, environ)
    red = Redactor(list(keys.values()))
    started = datetime.now(timezone.utc)
    report = scout(keys=keys, registry=_read_json(Path(args.registry)), policy=_read_json(Path(args.policy)),
                   fixtures=Path(args.fixtures), task_classes=_read_json(Path(args.task_classes)), fetch=fetch,
                   providers=provs, now=started)
    report["key_names_present"] = sorted(keys)  # names only, never values
    report = red.obj(report)
    readable = sum(1 for d in report["discovery"].values() if d["status"] == "OK")
    rc = 3 if report["p1"] else (0 if readable else 1)
    print(red(("DRY-RUN " if not args.write else "") + render(report)))
    if args.json:
        print(red(json.dumps(report, indent=1, sort_keys=True)))
    if not args.write:
        print(red(f"DRY-RUN {LANE_ID}: nothing written (exit {rc})"))
        return rc
    out = _state_root() / "data" / "runtime" / "llm_model_scout" / f"{report['period']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(red(json.dumps(report, indent=1, sort_keys=True)) + "\n", encoding="utf-8")
    tmp.replace(out)
    db = _db_insert(report)
    from lib import lane_last_receipt as receipts
    receipts.write_lane_receipt(
        LANE_ID, ok=rc == 0, exit_code=rc, started_at=started, script="llm_model_scout.py",
        summary={"p1": len(report["p1"]), "readable_providers": readable, "db": db},
        error=("P1: " + "; ".join(f"{f['provider']} {f['kind']} {f['model_id']}" for f in report["p1"]))
        if report["p1"] else None,
        produced_count=1, attempted_count=len(provs), output_evidence=[{"kind": "file", "path": str(out)}])
    print(red(f"[{LANE_ID}] wrote {out}; db={db}; exit {rc}"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
