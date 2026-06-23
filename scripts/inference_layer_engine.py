#!/usr/bin/env python3
"""Inference Layers — orchestration engine.

A modular, reusable, layered reasoning pipeline that sits ON TOP of the existing
Trade AI intelligence stack (Hermes, RAG, LLM enrichment, journal analytics,
topic curation, risk gate, proposal lifecycle) and synthesizes all of it into
higher-order, actionable inferences.

Pipeline (each layer is a reusable, independently-importable module):

    Layer 1  Ingestion & Structuring   -> inference_layers.IngestionLayer
    Layer 2  Feature Extraction         -> inference_layers.FeatureLayer
    Layer 3  Cross-Regional Synthesis   -> inference_layers.RegionalLayer
    Layer 4  Higher-Order Inference      -> inference_layers.HigherOrderLayer

Each layer consumes the shared InferenceContext (which carries every prior
layer's structured output) and returns a LayerResult. The engine persists results
to the inference_* tables, optionally indexes them into RAG, and pushes a
prioritized digest to Telegram.

The engine is advisory-only: it NEVER places orders. Its sizing output is written
to inference_sizing_recommendations for the existing approval/execution path to
consume — it does not mutate proposals unless explicitly run with --apply-sizing.

Usage:
    python scripts/inference_layer_engine.py --run                 # full cycle (cron)
    python scripts/inference_layer_engine.py --run --layers regional,higher_order
    python scripts/inference_layer_engine.py --run --no-telegram --account rollover
    python scripts/inference_layer_engine.py --latest               # show last run
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# ── logging (matches repo idiom) ──────────────────────────────────────────────
(PROJECT_ROOT / "logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(PROJECT_ROOT / "logs" / "inference_layer.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("inference_engine")

DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "inference_layers.yaml"

LAYER_ORDER = ["ingestion", "features", "regional", "higher_order"]


# ── env loading (mirrors agent_router._load_env) ──────────────────────────────
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


def load_config(path: Optional[Path] = None) -> dict:
    """Load config/inference_layers.yaml -> the `inference_layers` block."""
    path = path or DEFAULT_CONFIG_PATH
    try:
        import yaml
        data = yaml.safe_load(path.read_text()) or {}
        return data.get("inference_layers", data) or {}
    except Exception as e:  # pragma: no cover - defensive
        log.warning("config load failed (%s); using defaults", e)
        return {}


# ── shared data models (reusable across all layers) ───────────────────────────
@dataclass
class Inference:
    """One higher-order inference, persisted to inference_results."""
    inference_type: str
    subject: str
    title: str
    body: str = ""
    confidence: float = 0.5
    severity: str = "low"             # low | medium | high | critical
    source_lane: str = "local"
    reasoning_trace: list = field(default_factory=list)
    evidence: list = field(default_factory=list)
    payload: dict = field(default_factory=dict)


@dataclass
class LayerResult:
    layer: str
    ok: bool = True
    summary: str = ""
    data: dict = field(default_factory=dict)          # reusable structured output
    inferences: list = field(default_factory=list)    # list[Inference]
    metrics: dict = field(default_factory=dict)
    error: str = ""
    elapsed_ms: int = 0


@dataclass
class InferenceContext:
    """Carried through every layer. Each layer reads prior layers' .data."""
    run_id: Optional[int]
    run_label: str
    trigger: str
    account: str
    cfg: dict
    store: dict = field(default_factory=dict)         # layer_name -> LayerResult
    scratch: dict = field(default_factory=dict)       # cross-layer notes (e.g. regime)
    dry_run: bool = False

    def layer_cfg(self, name: str) -> dict:
        return (self.cfg.get("layers", {}) or {}).get(name, {}) or {}

    def get(self, layer: str) -> dict:
        r = self.store.get(layer)
        return r.data if r else {}

    @property
    def regime(self) -> str:
        return self.scratch.get("regime", "neutral")


# ── persistence helpers (db_adapter._execute, advisory-only writes) ───────────
def _db():
    from db_adapter import _execute, USE_DB
    return _execute, USE_DB


def reap_stale_runs(max_age_minutes: int = 60) -> int:
    """Mark runs left 'running' beyond max_age (crashed/killed) as 'error'.

    A cycle can be killed mid-flight (e.g. a cron `timeout`), which would otherwise
    strand its row as status='running' forever and poison /latest. Reaped here at
    the start of every new cycle so the table self-heals.
    """
    _execute, use_db = _db()
    if not use_db:
        return 0
    res = _execute(
        """UPDATE inference_runs
           SET status='error', error=COALESCE(error,'')||'[reaped: stale running]',
               finished_at=now()
           WHERE status='running'
             AND started_at < now() - (%s || ' minutes')::interval""",
        (str(max_age_minutes),), fetch=None)
    return 1 if res else 0


def create_run(run_label: str, trigger: str, account: str) -> Optional[int]:
    _execute, use_db = _db()
    if not use_db:
        return None
    reap_stale_runs()
    row = _execute(
        """INSERT INTO inference_runs (run_label, trigger, account, status, started_at)
           VALUES (%s, %s, %s, 'running', now()) RETURNING id""",
        (run_label, trigger, account), fetch="one",
    )
    return row["id"] if row else None


def finalize_run(run_id: Optional[int], status: str, regime: str,
                 layers_run: list, summary: str, metrics: dict, error: str = "") -> None:
    if run_id is None:
        return
    _execute, use_db = _db()
    if not use_db:
        return
    _execute(
        """UPDATE inference_runs
           SET status=%s, regime=%s, layers_run=%s, summary=%s, metrics=%s,
               error=%s, finished_at=now()
           WHERE id=%s""",
        (status, regime, json.dumps(layers_run), summary[:4000],
         json.dumps(metrics, default=str), error[:2000], run_id), fetch=None,
    )


def persist_inferences(run_id: Optional[int], layer: str, inferences: list) -> list:
    """Insert inferences; return the list of inserted ids (None per failed row),
    aligned with `inferences` order so callers can target rows (e.g. ensemble jobs)."""
    if run_id is None or not inferences:
        return []
    _execute, use_db = _db()
    if not use_db:
        return []
    ids: list = []
    for inf in inferences:
        row = _execute(
            """INSERT INTO inference_results
               (run_id, layer, inference_type, subject, title, body, confidence,
                severity, source_lane, reasoning_trace, evidence, payload)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (run_id, layer, inf.inference_type, inf.subject[:300], inf.title[:500],
             (inf.body or "")[:8000], float(inf.confidence or 0), inf.severity,
             inf.source_lane, json.dumps(inf.reasoning_trace, default=str),
             json.dumps(inf.evidence, default=str), json.dumps(inf.payload, default=str)),
            fetch="one",
        )
        ids.append(row["id"] if row else None)
    return ids


def enqueue_ensemble_jobs(items: list, cfg: dict) -> int:
    """Queue ensemble-validation jobs for the highest-severity inferences this cycle.

    `items` is a list of (inference_id, Inference). The worker
    (inference_ensemble_worker.py) runs them off-cycle so the engine stays bounded.
    Controlled by cfg.ensemble.auto_enqueue / *_severities / *_max.
    """
    ens = cfg.get("ensemble", {}) or {}
    if not ens.get("auto_enqueue"):
        return 0
    sevs = set(ens.get("auto_enqueue_severities", ["high", "critical"]))
    cap = int(ens.get("auto_enqueue_max", 4))   # <=0 means no cap (all high-severity)
    _execute, use_db = _db()
    if not use_db:
        return 0
    picked = [(iid, inf) for iid, inf in items if iid and inf.severity in sevs]
    picked.sort(key=lambda x: (x[1].severity != "critical", -float(x[1].confidence or 0)))
    selected = picked if cap <= 0 else picked[:cap]
    n = 0
    for iid, inf in selected:
        content = f"{inf.title}\n{inf.body or ''}"[:8000]
        res = _execute(
            """INSERT INTO inference_ensemble_jobs
               (target_type, target_id, subject, content, task, requested_by, status)
               VALUES ('inference', %s, %s, %s, 'inference_quality', 'auto', 'queued')""",
            (str(iid), inf.subject[:300], content), fetch=None)
        if res:
            n += 1
    return n


def ensemble_validate_inferences(layer: str, inferences: list, cfg: dict) -> int:
    """FREE-lane multi-LLM ensemble second-opinion on the SYNTHESIZED inferences before they're surfaced.
    Annotates each with payload['ensemble'] (score/decision/consensus/lanes), folds the ensemble score into
    confidence, and downgrades severity on a consensus 'block'. Only runs for the configured synthesis layers
    (higher_order/regional — the opinion layers, not the structural ones) and is capped per cycle so the loop
    stays bounded. No metered keys. Returns count validated."""
    ecfg = (cfg.get("ensemble") or {})
    if not ecfg.get("validate_in_loop", False):
        return 0
    if layer not in (ecfg.get("validate_layers") or ["higher_order", "regional"]) or not inferences:
        return 0
    try:
        from inference_ensemble import ensemble_validate
    except Exception:
        return 0
    cap = int(ecfg.get("validate_max", 4))
    sev_rank = {"critical": 3, "high": 2, "medium": 1, "low": 0}
    targets = sorted(inferences, key=lambda i: (sev_rank.get(i.severity, 0), i.confidence or 0), reverse=True)[:cap]
    done = 0
    for inf in targets:
        try:
            res = ensemble_validate(f"{inf.title}\n{inf.body}",
                                    context=f"Layer-4 {inf.inference_type} on {inf.subject}; advisory inference for a retail investor (retirement/markets)",
                                    task="validate this inference's quality + actionability before surfacing")
        except Exception:
            continue
        if not res.get("lanes_used"):
            continue
        inf.payload = dict(inf.payload or {})
        inf.payload["ensemble"] = {"score": res.get("final_score"), "decision": res.get("final_decision"),
                                   "consensus": res.get("consensus_reached"), "lanes": res.get("lanes_used")}
        inf.reasoning_trace = list(inf.reasoning_trace or []) + [f"ensemble: {res.get('reasoning_summary', '')}"]
        blended = (float(inf.confidence or 0.5) + (float(res.get("final_score", 5)) / 10.0)) / 2.0
        if res.get("final_decision") == "block" and res.get("consensus_reached"):
            blended = min(blended, 0.45)
            if inf.severity == "critical":
                inf.severity = "high"
        inf.confidence = round(max(0.05, min(0.98, blended)), 2)
        done += 1
    return done


def remember(mem_key: str, kind: str, value: dict, salience: float = 0.5) -> None:
    """Upsert persistent inference memory (the 'mind of its own' state)."""
    _execute, use_db = _db()
    if not use_db:
        return
    _execute(
        """INSERT INTO inference_memory (mem_key, kind, value, salience, updated_at)
           VALUES (%s,%s,%s,%s, now())
           ON CONFLICT (mem_key) DO UPDATE
             SET value=EXCLUDED.value,
                 salience=EXCLUDED.salience,
                 hit_count=inference_memory.hit_count + 1,
                 updated_at=now()""",
        (mem_key, kind, json.dumps(value, default=str), float(salience)), fetch=None,
    )


# ── engine ────────────────────────────────────────────────────────────────────
class InferenceEngine:
    def __init__(self, cfg: dict):
        self.cfg = cfg

    def _build_layers(self, only: Optional[set]) -> list:
        # imported lazily to avoid an import cycle (layers import this module)
        from inference_layers import (
            IngestionLayer, FeatureLayer, RegionalLayer, HigherOrderLayer,
        )
        registry = {
            "ingestion": IngestionLayer(),
            "features": FeatureLayer(),
            "regional": RegionalLayer(),
            "higher_order": HigherOrderLayer(),
        }
        layers = []
        for name in LAYER_ORDER:
            if only and name not in only:
                continue
            cfg = (self.cfg.get("layers", {}) or {}).get(name, {})
            if cfg.get("enabled", True) is False:
                continue
            layers.append((name, registry[name]))
        return layers

    def run(self, trigger: str = "manual", account: Optional[str] = None,
            only_layers: Optional[set] = None, dry_run: bool = False,
            send_telegram: bool = True) -> dict:
        account = account or self.cfg.get("account", "rollover")
        run_label = datetime.now(timezone.utc).strftime("inf_%Y%m%d_%H%M%S")
        run_id = None if dry_run else create_run(run_label, trigger, account)
        ctx = InferenceContext(run_id=run_id, run_label=run_label, trigger=trigger,
                               account=account, cfg=self.cfg, dry_run=dry_run)
        log.info("=== inference cycle %s (trigger=%s account=%s run_id=%s) ===",
                 run_label, trigger, account, run_id)

        layers_run: list = []
        total_inf = 0
        hi_sev: list = []   # (inference_id, Inference) for auto ensemble-enqueue
        for name, layer in self._build_layers(only_layers):
            t0 = time.time()
            try:
                result = layer.run(ctx)
            except Exception as e:  # a layer must never kill the cycle
                log.error("layer %s crashed: %s\n%s", name, e, traceback.format_exc())
                result = LayerResult(layer=name, ok=False, error=str(e))
            result.elapsed_ms = int((time.time() - t0) * 1000)
            ctx.store[name] = result
            # Ensemble second-opinion on synthesized inferences before they're persisted/surfaced (free lanes).
            try:
                nv = ensemble_validate_inferences(name, result.inferences, self.cfg)
                if nv:
                    log.info("layer %-13s ensemble-validated %d inference(s)", name, nv)
            except Exception as e:
                log.warning("ensemble validation skipped for %s: %s", name, str(e)[:80])
            if dry_run:
                n = len(result.inferences)
            else:
                inserted = persist_inferences(run_id, name, result.inferences)
                n = sum(1 for i in inserted if i)
                for iid, inf in zip(inserted, result.inferences):
                    if iid and inf.severity in ("high", "critical"):
                        hi_sev.append((iid, inf))
            total_inf += n
            layers_run.append({"layer": name, "ok": result.ok, "ms": result.elapsed_ms,
                               "n": len(result.inferences), "summary": result.summary[:200]})
            log.info("layer %-13s ok=%s %4dms inferences=%d :: %s",
                     name, result.ok, result.elapsed_ms, len(result.inferences), result.summary[:120])

            # Autonomous rotation response when FeatureLayer detects small-cap outperform
            if name == "features" and not dry_run:
                rot = (result.data or {}).get("small_cap_rotation") or {}
                if rot.get("signal") == "small_cap_outperform":
                    try:
                        from rotation_autopilot import run_autopilot_tick
                        ap = run_autopilot_tick(trigger=f"inference:{trigger}")
                        if ap.get("bridge_ran"):
                            log.info("rotation_autopilot bridge ran (%s) from inference cycle",
                                     ap.get("bridge_reason"))
                    except Exception as e:
                        log.warning("rotation_autopilot from inference skipped: %s", str(e)[:120])

        # Auto-enqueue ensemble validation for the cycle's highest-severity inferences
        # (the worker runs them off-cycle; bounded by ensemble.auto_enqueue_max).
        enqueued = 0
        if not dry_run:
            try:
                enqueued = enqueue_ensemble_jobs(hi_sev, self.cfg)
                if enqueued:
                    log.info("auto-enqueued %d ensemble validation job(s)", enqueued)
            except Exception as e:
                log.warning("ensemble auto-enqueue failed: %s", e)

        summary = self._summarize(ctx, total_inf)
        metrics = {"total_inferences": total_inf,
                   "regime": ctx.regime,
                   "layers": len(layers_run),
                   "ensemble_enqueued": enqueued}
        if not dry_run:
            finalize_run(run_id, "complete", ctx.regime, layers_run, summary, metrics)

        # Telegram digest (prioritized, advisory)
        if send_telegram and self.cfg.get("telegram", {}).get("enabled", True) and not dry_run:
            try:
                from inference_telegram import send_inference_digest
                send_inference_digest(ctx, run_id)
            except Exception as e:
                log.warning("telegram digest failed: %s", e)

        log.info("=== cycle %s complete: %d inferences, regime=%s ===",
                 run_label, total_inf, ctx.regime)
        return {"ok": True, "run_id": run_id, "run_label": run_label,
                "regime": ctx.regime, "total_inferences": total_inf,
                "layers": layers_run, "summary": summary}

    @staticmethod
    def _summarize(ctx: InferenceContext, total: int) -> str:
        parts = [f"regime={ctx.regime}", f"inferences={total}"]
        reg = ctx.store.get("regional")
        if reg and reg.metrics.get("signals"):
            parts.append(f"regional_signals={reg.metrics['signals']}")
        ho = ctx.store.get("higher_order")
        if ho and ho.metrics.get("sizing_recs"):
            parts.append(f"sizing_recs={ho.metrics['sizing_recs']}")
        return "; ".join(parts)


# ── CLI ────────────────────────────────────────────────────────────────────────
def _show_latest() -> int:
    _execute, use_db = _db()
    if not use_db:
        print("DB disabled")
        return 1
    run = _execute("SELECT * FROM inference_runs ORDER BY id DESC LIMIT 1", fetch="one")
    if not run:
        print("no inference runs yet")
        return 0
    print(json.dumps(dict(run), indent=2, default=str))
    rows = _execute(
        """SELECT layer, inference_type, subject, title, confidence, severity
           FROM inference_results WHERE run_id=%s
           ORDER BY (severity='critical') DESC, confidence DESC LIMIT 25""",
        (run["id"],), fetch="all") or []
    print(f"\n--- {len(rows)} top inferences ---")
    for r in rows:
        print(f"[{r['severity']:>8}] {r['confidence']:.2f} {r['inference_type']:>16} "
              f"{r['subject']:<22} {r['title'][:70]}")
    return 0


def main() -> int:
    _load_env()
    ap = argparse.ArgumentParser(description="Inference Layers engine")
    ap.add_argument("--run", action="store_true", help="run a full inference cycle")
    ap.add_argument("--latest", action="store_true", help="show the most recent run")
    ap.add_argument("--trigger", default="manual", help="trigger label (cron|manual|event:*)")
    ap.add_argument("--account", default=None, help="account_key to reason about")
    ap.add_argument("--layers", default=None,
                    help="comma list subset of: " + ",".join(LAYER_ORDER))
    ap.add_argument("--dry-run", action="store_true", help="run layers, persist nothing")
    ap.add_argument("--no-telegram", action="store_true", help="suppress Telegram digest")
    ap.add_argument("--config", default=None, help="path to inference_layers.yaml")
    args = ap.parse_args()

    if args.latest:
        return _show_latest()

    if not args.run:
        ap.print_help()
        return 0

    cfg = load_config(Path(args.config) if args.config else None)
    if cfg.get("enabled", True) is False:
        log.warning("inference_layers disabled in config; exiting")
        return 0
    only = set(s.strip() for s in args.layers.split(",")) if args.layers else None
    engine = InferenceEngine(cfg)
    out = engine.run(trigger=args.trigger, account=args.account, only_layers=only,
                     dry_run=args.dry_run, send_telegram=not args.no_telegram)
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
