"""Dimensions 1–3 of N8nPlatformMaturity@v1: registry truth, rationalization, scheduler coverage.

Every number here is read through the ``core.Probe`` (READ-ONLY): ``config/lane_registry.json``,
``crontab -l`` (``probe.crontab()``), ``systemctl --user list-unit-files`` (``probe.run``), the
coordination ledger ``runs`` table (``probe.sqlite_ro``), the pipeline run summaries
(``data/runtime/pipeline_*_last.json``) and the rationalization plan data
(``docs/implementation/n8n-maturity/data/F_rationalization.json`` + ``cron_rows.json``).
``lane_registry`` helpers are called with the text the probe read; they never shell out from here.

Thresholds are read from ``config/n8n_platform_maturity.json`` (``probe.cfg(dim_id)``); when a key
is absent the fallback in ``*_DEFAULTS`` below applies (documented, never hidden). Evidence pointers
carry paths, counts and timestamps only — never crontab text, never secrets.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

from . import core

try:  # imported with scripts/lib on sys.path (the orchestrator) …
    import lane_registry as _lr  # type: ignore
except ImportError:  # pragma: no cover — … or as a package from the repo root
    from scripts.lib import lane_registry as _lr  # type: ignore

REGISTRY_REL = Path("config") / "lane_registry.json"
LEDGER_NAME = "n8n_coordination_ledger.sqlite"

# ── fallback thresholds (config keys of the same name override) ─────────────────────────────────
REGISTRY_TRUTH_DEFAULTS: dict[str, Any] = {
    # exemption size the program started from: 476 undeclared_baseline + 113 inherited-tranche lines
    # (config/lane_registry.json as of 2026-10-09). Progress = share of it retired.
    "baseline_initial": 589,
}

RATIONALIZATION_DEFAULTS: dict[str, Any] = {
    "plan_rows_path": "docs/implementation/n8n-maturity/data/F_rationalization.json",
    "plan_cron_rows_path": "docs/implementation/n8n-maturity/data/cron_rows.json",
    "r0_target": 37,              # plan R0: 17 cron, 9 timers, 9 n8n, 1 service, 1 tick step
    "merged_target": 60,          # ≥ 60 lines merged/consolidated away
    "merged_stretch": 120,        # 10/10 for the merged sub-score
    "pipelines_live_target": 8,   # the 8 dry-run pipeline stages switched to live
    "pipelines_live_stretch": 16,  # end state: 16 pipelines
    "pipeline_receipt_max_age_hours": 192,  # a live stage receipt older than this does not count
    "eliminate_prefixes": ["ELIMINATE"],
    "merge_prefixes": ["MERGE", "CONSOLIDATE"],
    "n8n_active_snapshot": "docs/implementation/n8n-parallel/workflows/active_workflows_snapshot.json",
    "health_tick_steps": "config/health_tick_steps.json",
}

SCHEDULER_COVERAGE_DEFAULTS: dict[str, Any] = {
    "dispatched_min_fraction": 0.60,   # gate: ≥ 60% of movable lanes run by the dispatcher
    "watched_min_fraction": 1.0,       # gate: the rest watched (all of them)
    "dispatcher_kinds": ["n8n", "dispatcher"],
    "schedulable_kinds": ["cron", "systemd", "n8n", "dispatcher"],
    "run_states": ["RUN_DONE", "RUN_SKIPPED_LOCK"],
    "run_modes": ["live"],
    "run_window_floor_hours": 24,      # run evidence window = max(2 × cadence, floor)
    # stay-behind classifier (broker / order / secret / daemon): whole tokens of lane_id + scheduler
    # expression/match, substrings of the same text, explicit lane ids, and note markers.
    "stay_tokens": ["broker", "order", "orders", "stop", "stops", "alpaca", "moomoo", "opend", "schwab",
                    "secret", "secrets", "token", "tokens", "credential", "credentials", "bws", "oauth",
                    "daemon", "service", "fill", "fills", "positions"],
    "stay_substrings": ["options_tick", "options-tick", "scalp_live", "scalp-live", "portfolio_reconcile",
                        ".service"],
    "stay_lane_ids": [],
    "stay_note_markers": ["retained on cron", "stays on cron", "stay on cron", "keep on cron",
                          "keep on systemd", "stays on systemd"],
}


def _c(probe: core.Probe, dim_id: str, defaults: dict, key: str) -> Any:
    v = probe.cfg(dim_id).get(key)
    return defaults[key] if v is None else v


def _gate_rule(probe: core.Probe, dim_id: str, fallback: str) -> str:
    return probe.cfg(dim_id).get("gate_rule") or fallback


def _load_registry(probe: core.Probe) -> Optional[dict]:
    reg = probe.json(probe.proj / REGISTRY_REL)
    return reg if isinstance(reg, dict) and isinstance(reg.get("lanes"), list) else None


def _baseline_size(reg: dict) -> int:
    n = len(reg.get("undeclared_baseline") or [])
    for t in reg.get("inherited_tranches") or []:
        n += len(t.get("lines") or [])
    return n


def _unit_files(probe: core.Probe, unit_type: str) -> Optional[dict[str, str]]:
    """{unit: enabled_state} from ``systemctl --user list-unit-files`` (None when it could not be read)."""
    try:
        rc, out, _ = probe.run(["systemctl", "--user", "list-unit-files", f"--type={unit_type}", "--no-legend"])
    except PermissionError:
        return None
    if rc != 0:
        return None
    units: dict[str, str] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].endswith(f".{unit_type}"):
            units[parts[0]] = parts[1]
    return units


# ── 1. registry truth ───────────────────────────────────────────────────────────────────────────

def registry_truth(probe: core.Probe) -> dict:
    """Registry truth — crontab ≡ registry.

    Inputs: ``config/lane_registry.json`` and ``crontab -l`` (live, uncommented lines via
    ``lane_registry.discover_cron(text=...)``).

    * ``coverage`` = live lines with a registry row / live lines, where "with a row" means
      ``lane_registry.find_undeclared`` reports it undeclared once the exemptions
      (``undeclared_baseline`` + ``inherited_tranches``) are emptied.
    * ``baseline_progress`` = 1 − exemption size / ``baseline_initial`` (589).
    * ``reverse`` = ACTIVE kind-cron rows whose ``match``/``expression`` is in a live line / ACTIVE cron rows.

    Score below the gate = mean(ratio_score(coverage, 1.0), ratio_score(baseline_progress, 1.0)) (each
    reaches 8.0 only at 100%). Gate (exemption size 0 AND every live line has a row) passes → score =
    8 + 2 × reverse (10 when no ACTIVE cron row is orphaned either). Missing crontab or registry → UNVERIFIED.
    """
    dim = "registry_truth"
    rule = _gate_rule(probe, dim, "undeclared_baseline = 0 and every live crontab line has a registry row")
    reg_path = probe.proj / REGISTRY_REL
    reg = _load_registry(probe)
    if reg is None:
        return core.unverified(dim, rule, f"registry unreadable: {reg_path}",
                               evidence_list=[core.evidence(str(reg_path), readable=False)])
    text = probe.crontab()
    if text is None:
        return core.unverified(dim, rule, "crontab -l failed (no live crontab evidence)",
                               metrics={"registry_rows": len(reg["lanes"]), "baseline_size": _baseline_size(reg)},
                               evidence_list=[core.evidence(str(reg_path), rows=len(reg["lanes"]))])
    live = _lr.discover_cron(text=text)
    found = {"cron": live}
    no_exempt = dict(reg, undeclared_baseline=[], inherited_tranches=[])
    without_row = _lr.find_undeclared(no_exempt, found)
    beyond_baseline = _lr.find_undeclared(reg, found)
    n_live = len(live)
    with_row = n_live - len(without_row)
    base = _baseline_size(reg)
    live_exprs = {j["expression"] for j in live}
    exempt = set(reg.get("undeclared_baseline") or [])
    for t in reg.get("inherited_tranches") or []:
        exempt.update(str(x) for x in (t.get("lines") or []))
    stale_exempt = len([x for x in exempt if x not in live_exprs])
    active_cron = [r for r in reg["lanes"] if r.get("state") == _lr.STATE_ACTIVE
                   and (r.get("scheduler") or {}).get("kind") == "cron"]
    present = 0
    for r in active_cron:
        s = r.get("scheduler") or {}
        marker = str(s.get("match") or s.get("expression") or "")
        if marker and any(marker in e for e in live_exprs):
            present += 1
    initial = float(_c(probe, dim, REGISTRY_TRUTH_DEFAULTS, "baseline_initial"))
    coverage = (with_row / n_live) if n_live else 1.0
    progress = max(0.0, 1.0 - base / initial) if initial > 0 else (1.0 if base == 0 else 0.0)
    reverse = (present / len(active_cron)) if active_cron else 1.0
    gate = base == 0 and with_row == n_live
    if gate:
        score = 8.0 + 2.0 * reverse
    else:
        score = (core.ratio_score(coverage, 1.0) + core.ratio_score(progress, 1.0)) / 2
    metrics = {
        "baseline_size": base, "baseline_initial": int(initial),
        "live_cron_lines": n_live, "lines_with_row": with_row, "lines_without_row": len(without_row),
        "undeclared_beyond_baseline": len(beyond_baseline), "stale_exemption_entries": stale_exempt,
        "registry_rows": len(reg["lanes"]), "active_cron_rows": len(active_cron),
        "active_cron_rows_present": present, "coverage": round(coverage, 4),
        "baseline_progress": round(progress, 4),
    }
    notes = [] if gate else [f"{len(without_row)} of {n_live} live crontab lines have no registry row; "
                             f"exemption list holds {base} entries"]
    if beyond_baseline:
        notes.append(f"{len(beyond_baseline)} live lines are undeclared even after the exemption list (CI gate red)")
    ev = [core.evidence(str(reg_path), rows=len(reg["lanes"]), undeclared_baseline=len(reg.get("undeclared_baseline")
                                                                                   or []),
                        inherited_tranche_lines=base - len(reg.get("undeclared_baseline") or []),
                        mtime=_iso(probe.mtime(reg_path))),
          core.evidence("crontab -l", live_lines=n_live, commented_lines=len(_lr.discover_commented_cron(text=text)))]
    return core.dim_result(dim, score=score, gate_rule=rule, gate_pass=gate, metrics=metrics,
                           evidence_list=ev, notes=notes)


# ── 2. rationalization ──────────────────────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    return " ".join(str(s or "").split())


def _cron_cmd(cmd: str) -> str:
    """Command text without its trailing ``# comment`` (comments get edited; the command is the identity)."""
    return _norm(re.split(r"\s+#\s", " " + str(cmd or "") + " ", maxsplit=1)[0])


class _HostState:
    """Lazily read scheduler state used to decide whether a plan item is gone. None = could not read."""

    def __init__(self, probe: core.Probe, cfgget, live_lines: list[str]):
        self.probe, self._cfg, self.live = probe, cfgget, [_norm(x) for x in live_lines]
        self._units: dict[str, Optional[dict[str, str]]] = {}
        self._n8n: Any = False
        self._steps: Any = False
        self.sources: dict[str, Any] = {}

    def units(self, t: str) -> Optional[dict[str, str]]:
        if t not in self._units:
            self._units[t] = _unit_files(self.probe, t)
            self.sources[f"systemctl --user list-unit-files --type={t}"] = (
                None if self._units[t] is None else len(self._units[t]))
        return self._units[t]

    def n8n_active(self) -> Optional[set[str]]:
        if self._n8n is False:
            p = self.probe.proj / self._cfg("n8n_active_snapshot")
            doc = self.probe.json(p)
            ids = None
            if isinstance(doc, dict) and isinstance(doc.get("workflows"), list):
                ids = {str(w.get("id")) for w in doc["workflows"] if isinstance(w, dict)}
                self.sources[str(p)] = {"active": len(ids), "captured_at": doc.get("captured_at")}
            else:
                self.sources[str(p)] = "unreadable"
            self._n8n = ids
        return self._n8n

    def tick_steps(self) -> Optional[dict[str, bool]]:
        if self._steps is False:
            p = self.probe.proj / self._cfg("health_tick_steps")
            doc = self.probe.json(p)
            steps = doc.get("steps") if isinstance(doc, dict) else doc
            out = None
            if isinstance(steps, list):
                out = {str(s.get("step_id") or s.get("id") or s.get("name")): s.get("enabled", True) is not False
                       for s in steps if isinstance(s, dict)}
                self.sources[str(p)] = {"steps": len(out)}
            else:
                self.sources[str(p)] = "unreadable"
            self._steps = out
        return self._steps


def _item_gone(item: dict, host: _HostState, cron_rows: dict[str, dict]) -> Optional[bool]:
    """True when the plan item no longer schedules anything on the host, False when it still does,
    None when it cannot be told from evidence."""
    kind, name, iid = str(item.get("kind") or ""), str(item.get("name") or ""), str(item.get("id") or "")
    if kind == "cron":
        row = cron_rows.get(iid.lstrip("L"))
        if row and row.get("cmd"):
            cmd = _cron_cmd(row["cmd"])
            return not any(cmd in ln for ln in host.live) if cmd else None
        if not name or name in ("inline", "curl") or len(name) < 4:
            return None
        return not any(name in ln for ln in host.live)
    if kind in ("timer", "service"):
        units = host.units(kind)
        if units is None:
            return None
        unit = name if name.endswith(f".{kind}") else f"{name}.{kind}"
        return units.get(unit) is None or units.get(unit) in ("disabled", "masked")
    if kind == "n8n_workflow":
        active = host.n8n_active()
        return None if active is None else iid not in active
    if kind == "health_tick_step":
        steps = host.tick_steps()
        return None if steps is None else not steps.get(iid or name, False)
    return None


def _pipeline_receipts(probe: core.Probe, max_age_h: float) -> tuple[list[dict], int]:
    folder = probe.runtime()
    live: list[dict] = []
    total = 0
    try:
        files = sorted(folder.glob("pipeline_*_last.json"))
    except OSError:
        files = []
    cut = probe.since(max_age_h)
    for p in files:
        doc = probe.json(p)
        if not isinstance(doc, dict) or doc.get("schema", "PipelineRun@v1") != "PipelineRun@v1":
            continue
        total += 1
        ts = core.parse_ts(doc.get("run_ts_utc") or doc.get("started_at"))
        if (doc.get("dry_run") is False and doc.get("executed_any") is True
                and doc.get("overall_status") in ("ok", "degraded") and ts is not None and ts >= cut):
            live.append({"pipeline": doc.get("pipeline"), "stage": doc.get("stage"),
                         "status": doc.get("overall_status"), "run_ts_utc": doc.get("run_ts_utc")})
    return live, total


def rationalization(probe: core.Probe) -> dict:
    """Rationalization — lines eliminated/merged vs the plan (F_rationalization.json).

    * ``eliminated`` = plan items whose recommendation starts with ELIMINATE and that no longer schedule
      anything: cron → the plan line's command (``cron_rows.json`` by line number; script name when
      absent) is in no live crontab line; timer/service → unit absent, disabled or masked; n8n workflow →
      id not in the committed active snapshot; health-tick step → absent or ``enabled: false``.
      Sub-score ratio_score(eliminated, r0_target=37). Plan data absent → None (UNVERIFIED part).
    * ``merged`` = plan items recommended MERGE*/CONSOLIDATE* that are gone by the same test.
      Sub-score ratio_score(merged, 60, top=120). Plan absent → None.
    * ``pipelines_live`` = PipelineRun@v1 summaries ``data/runtime/pipeline_*_last.json`` with
      dry_run false, executed_any true, overall_status ok|degraded, run within 192 h.
      Sub-score ratio_score(pipelines_live, 8, top=16).

    Score = core.mean_score of the three. Gate: eliminated ≥ 37 AND merged ≥ 60 AND pipelines_live ≥ 8.
    Supporting metrics: retire-tagged commented cron lines, n8n-cutover tags, registry RETIRED rows.
    """
    dim = "rationalization"
    rule = _gate_rule(probe, dim, "R0 done (37 eliminated), >= 60 merged, 8 pipelines live")

    def cfg(key: str) -> Any:
        return _c(probe, dim, RATIONALIZATION_DEFAULTS, key)

    text = probe.crontab()
    reg = _load_registry(probe)
    ev: list[dict] = []
    metrics: dict[str, Any] = {}
    notes: list[str] = []

    live_lines = [j["expression"] for j in _lr.discover_cron(text=text)] if text is not None else []
    if text is not None:
        commented = _lr.discover_commented_cron(text=text)
        metrics["retire_tagged_commented_lines"] = sum(1 for c in commented if c.get("tags"))
        metrics["n8n_cutover_tagged_lines"] = sum(1 for c in commented if c.get("retired_lane_id"))
        metrics["live_cron_lines"] = len(live_lines)
        ev.append(core.evidence("crontab -l", live_lines=len(live_lines), commented_lines=len(commented)))
    if reg is not None:
        metrics["registry_retired_rows"] = sum(1 for r in reg["lanes"] if r.get("state") == _lr.STATE_RETIRED)
        metrics["registry_superseded_rows"] = sum(1 for r in reg["lanes"] if r.get("superseded_by"))

    # plan comparison
    plan_path = probe.proj / cfg("plan_rows_path")
    plan = probe.json(plan_path)
    elim_score: Optional[float] = None
    merged_score: Optional[float] = None
    eliminated = merged = None
    r0_target = int(cfg("r0_target"))
    merged_target = int(cfg("merged_target"))
    if not isinstance(plan, list):
        ev.append(core.evidence(str(plan_path), readable=False))
        notes.append(f"rationalization plan data absent at {cfg('plan_rows_path')}: eliminated/merged vs plan UNVERIFIED")
    elif text is None:
        notes.append("crontab -l failed: cannot tell which plan cron lines are gone")
    else:
        cr_path = probe.proj / cfg("plan_cron_rows_path")
        cr = probe.json(cr_path)
        cron_rows = {str(r.get("line")): r for r in cr if isinstance(r, dict)} if isinstance(cr, list) else {}
        host = _HostState(probe, cfg, live_lines)
        elim_pref = tuple(str(x).upper() for x in cfg("eliminate_prefixes"))
        merge_pref = tuple(str(x).upper() for x in cfg("merge_prefixes"))
        e_plan = [x for x in plan if isinstance(x, dict) and str(x.get("recommendation") or "").upper().startswith(elim_pref)]
        m_plan = [x for x in plan if isinstance(x, dict) and str(x.get("recommendation") or "").upper().startswith(merge_pref)]
        e_res = [_item_gone(x, host, cron_rows) for x in e_plan]
        m_res = [_item_gone(x, host, cron_rows) for x in m_plan]
        eliminated = sum(1 for v in e_res if v is True)
        merged = sum(1 for v in m_res if v is True)
        metrics.update({
            "plan_items": len(plan), "plan_eliminate": len(e_plan), "eliminated": eliminated,
            "eliminate_unverifiable": sum(1 for v in e_res if v is None),
            "plan_merge_consolidate": len(m_plan), "merged": merged,
            "merge_unverifiable": sum(1 for v in m_res if v is None),
        })
        elim_score = core.ratio_score(eliminated, r0_target)
        merged_score = core.ratio_score(merged, merged_target, top=float(cfg("merged_stretch")))
        ev.append(core.evidence(str(plan_path), items=len(plan), mtime=_iso(probe.mtime(plan_path))))
        ev.append(core.evidence(str(cr_path), rows=len(cron_rows) if cron_rows else None,
                                readable=bool(cron_rows)))
        for src, detail in host.sources.items():
            ev.append(core.evidence(src, detail=detail))
        if not cron_rows:
            notes.append("cron_rows.json absent: plan cron lines matched by script name (inline/curl lines unverifiable)")

    live_receipts, total_receipts = _pipeline_receipts(probe, float(cfg("pipeline_receipt_max_age_hours")))
    p_target = int(cfg("pipelines_live_target"))
    pipelines_live = len(live_receipts)
    pipe_score = core.ratio_score(pipelines_live, p_target, top=float(cfg("pipelines_live_stretch")))
    metrics.update({"pipeline_stage_receipts": total_receipts, "pipelines_live": pipelines_live})
    ev.append(core.evidence(str(probe.runtime() / "pipeline_*_last.json"), receipts=total_receipts,
                            live=pipelines_live,
                            newest_live=max((r["run_ts_utc"] or "" for r in live_receipts), default=None) or None))

    score, status, mnotes = core.mean_score([("eliminated_vs_plan", elim_score), ("merged_vs_plan", merged_score),
                                             ("pipelines_live", pipe_score)])
    gate = (eliminated is not None and eliminated >= r0_target and merged is not None and merged >= merged_target
            and pipelines_live >= p_target)
    return core.dim_result(dim, score=score, gate_rule=rule, gate_pass=gate, metrics=metrics,
                           evidence_list=ev, status=status, notes=notes + mnotes)


# ── 3. scheduler coverage ───────────────────────────────────────────────────────────────────────

def _tokens(s: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", s.lower()) if t}


def is_stay_behind(row: dict, cfgget) -> Optional[str]:
    """Reason string when the lane must stay on cron/systemd (broker/order/secret/daemon), else None."""
    lid = str(row.get("lane_id") or "")
    if lid in set(cfgget("stay_lane_ids") or []):
        return "stay_lane_ids"
    s = row.get("scheduler") or {}
    ident = " ".join([lid, str(s.get("expression") or ""), str(s.get("match") or "")])
    toks = _tokens(ident)
    hit = sorted(toks & {str(k).lower() for k in cfgget("stay_tokens") or []})
    if hit:
        return f"token:{hit[0]}"
    low = ident.lower()
    for sub in cfgget("stay_substrings") or []:
        if str(sub).lower() in low:
            return f"substring:{sub}"
    note = " ".join(str(row.get(k) or "") for k in ("note", "state_reason")).lower()
    for m in cfgget("stay_note_markers") or []:
        if str(m).lower() in note:
            return f"note:{m}"
    return None


def scheduler_coverage(probe: core.Probe) -> dict:
    """Scheduler coverage — share of movable lanes run by the dispatcher; the rest watched.

    Population: ACTIVE registry rows whose scheduler.kind is schedulable (cron/systemd/n8n/dispatcher).
    Stay-behinds (broker/order/secret/daemon; config-driven ``is_stay_behind``) are not movable.

    * ``declared`` = movable rows with scheduler.kind in dispatcher_kinds (n8n) / movable.
      Sub-score ratio_score(declared, 0.60, top=1.0).
    * ``run_proven`` = movable dispatcher rows with a ``runs`` row (mode live, state RUN_DONE|RUN_SKIPPED_LOCK)
      finished within max(2 × expected_cadence_hours, 24 h) / movable. ratio_score(run_proven, 0.60, top=1.0).
      Ledger or ``runs`` table absent → None (UNVERIFIED part).
    * ``watched`` = rows NOT dispatcher-run (stay-behinds + undispatched movable) with an
      output_signal.kind other than "none" / those rows. ratio_score(watched, 1.0).

    Score = core.mean_score of the three. Gate: run_proven ≥ 0.60 AND watched ≥ 1.0.
    """
    dim = "scheduler_coverage"
    rule = _gate_rule(probe, dim, ">= 60% of movable lanes run by the dispatcher; the rest watched")

    def cfg(key: str) -> Any:
        return _c(probe, dim, SCHEDULER_COVERAGE_DEFAULTS, key)

    reg_path = probe.proj / REGISTRY_REL
    reg = _load_registry(probe)
    if reg is None:
        return core.unverified(dim, rule, f"registry unreadable: {reg_path}",
                               evidence_list=[core.evidence(str(reg_path), readable=False)])
    sched_kinds = set(cfg("schedulable_kinds"))
    disp_kinds = set(cfg("dispatcher_kinds"))
    pop = [r for r in reg["lanes"] if r.get("state") == _lr.STATE_ACTIVE
           and (r.get("scheduler") or {}).get("kind") in sched_kinds]
    stay: dict[str, str] = {}
    movable: list[dict] = []
    for r in pop:
        if (r.get("scheduler") or {}).get("kind") in disp_kinds:
            movable.append(r)          # already on the dispatcher: movable by definition
            continue
        why = is_stay_behind(r, cfg)
        if why:
            stay[str(r.get("lane_id"))] = why
        else:
            movable.append(r)
    dispatched = [r for r in movable if (r.get("scheduler") or {}).get("kind") in disp_kinds]

    ledger = probe.gov() / LEDGER_NAME
    last_run: Optional[dict[str, str]] = None
    con = probe.sqlite_ro(ledger)
    ledger_note = None
    if con is None:
        ledger_note = f"coordination ledger absent: {ledger}"
    else:
        try:
            states, modes = list(cfg("run_states")), list(cfg("run_modes"))
            q = ("SELECT lane_id, MAX(finished_at) FROM runs WHERE finished_at IS NOT NULL "
                 f"AND state IN ({','.join('?' * len(states))}) AND mode IN ({','.join('?' * len(modes))}) "
                 "GROUP BY lane_id")
            last_run = {str(a): str(b) for a, b in con.execute(q, (*states, *modes)).fetchall()}
        except Exception as exc:  # noqa: BLE001 — table absent/locked: run evidence UNVERIFIED
            ledger_note = f"ledger runs table unreadable: {type(exc).__name__}"
        finally:
            con.close()
    floor = float(cfg("run_window_floor_hours"))
    proven: list[str] = []
    if last_run is not None:
        for r in dispatched:
            lid = str(r.get("lane_id"))
            ts = core.parse_ts(last_run.get(lid))
            win = max(2.0 * float(r.get("expected_cadence_hours") or 0), floor)
            if ts is not None and ts >= probe.since(win):
                proven.append(lid)

    n_mov = len(movable)
    declared_frac = len(dispatched) / n_mov if n_mov else 0.0
    proven_frac = (len(proven) / n_mov if n_mov else 0.0) if last_run is not None else None
    rest = [r for r in pop if str(r.get("lane_id")) not in set(proven)]
    watched = [r for r in rest if ((r.get("output_signal") or {}).get("kind") or "none") != "none"]
    watched_frac = len(watched) / len(rest) if rest else 1.0
    d_min = float(cfg("dispatched_min_fraction"))
    w_min = float(cfg("watched_min_fraction"))
    parts = [("declared_on_dispatcher", core.ratio_score(declared_frac, d_min, top=1.0) if n_mov else 0.0),
             ("run_proven_on_dispatcher",
              None if proven_frac is None else core.ratio_score(proven_frac, d_min, top=1.0)),
             ("rest_watched", core.ratio_score(watched_frac, w_min))]
    score, status, mnotes = core.mean_score(parts)
    gate = proven_frac is not None and proven_frac >= d_min and watched_frac >= w_min
    metrics = {
        "schedulable_active_lanes": len(pop), "stay_behind_lanes": len(stay), "movable_lanes": n_mov,
        "dispatcher_declared": len(dispatched), "dispatcher_run_proven": len(proven) if last_run is not None else None,
        "declared_fraction": round(declared_frac, 4),
        "run_proven_fraction": None if proven_frac is None else round(proven_frac, 4),
        "rest_lanes": len(rest), "rest_watched": len(watched), "watched_fraction": round(watched_frac, 4),
        "ledger_lanes_with_live_runs": None if last_run is None else len(last_run),
    }
    reasons: dict[str, int] = {}
    for why in stay.values():
        reasons[why.split(":")[0]] = reasons.get(why.split(":")[0], 0) + 1
    ev = [core.evidence(str(reg_path), rows=len(reg["lanes"]), schedulable_active=len(pop),
                        stay_behind_by_rule=reasons),
          core.evidence(f"{ledger}#runs", readable=last_run is not None, mtime=_iso(probe.mtime(ledger)),
                        lanes_with_live_runs=None if last_run is None else len(last_run),
                        newest_live_run=max(last_run.values(), default=None) if last_run else None)]
    notes = ([ledger_note] if ledger_note else []) + mnotes
    return core.dim_result(dim, score=score, gate_rule=rule, gate_pass=gate, metrics=metrics,
                           evidence_list=ev, status=status, notes=notes)


def _iso(d: Any) -> Optional[str]:
    return d.isoformat() if d is not None else None


COLLECTORS = {
    "registry_truth": registry_truth,
    "rationalization": rationalization,
    "scheduler_coverage": scheduler_coverage,
}
