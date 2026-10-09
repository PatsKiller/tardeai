"""Dimensions 1–3 of N8nPlatformMaturity@v1: registry truth, rationalization, scheduler coverage.

Every number here is read through the ``core.Probe`` (READ-ONLY): ``config/lane_registry.json``,
``crontab -l`` (``probe.crontab()``), ``systemctl --user list-unit-files`` (``probe.run``), the
coordination ledger ``runs`` table (``probe.sqlite_ro``), the pipeline run summaries
(``data/runtime/pipeline_*_last.json``) and the rationalization plan data
(``docs/implementation/n8n-maturity/data/F_rationalization.json`` + ``cron_rows.json``).
``lane_registry`` helpers are called with the text the probe read; they never shell out from here.

Every threshold is read from ``config/n8n_platform_maturity.json`` with ``probe.need(dim, key)`` — there
is no in-code fallback; a missing key raises ``core.ConfigError`` (the orchestrator marks the dimension
UNVERIFIED). The gate score is the top-level ``gate_score``. Empty inputs never score as a pass: an
empty crontab is UNVERIFIED, an empty population is a None (unverified) sub-criterion. Evidence pointers
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

def _c(probe: core.Probe, dim_id: str, key: str) -> Any:
    return probe.need(dim_id, key)


def _gate_score(probe: core.Probe) -> float:
    return float(core.need_top(probe.config, "gate_score"))


def _home_norm(probe: core.Probe):
    """Normalise the home directory to ``~`` (and ``$HOME``/``${HOME}`` likewise) so committed plan data —
    which carries ``~`` instead of a home path — compares equal to the live crontab text."""
    home = str(probe.env.get("HOME") or Path.home()).rstrip("/")

    def norm(x: str) -> str:
        t = str(x or "").replace("${HOME}", "~").replace("$HOME", "~")
        return t.replace(home, "~") if home and home != "~" else t
    return norm


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
    reaches ``gate_score`` only at 100%). Gate (exemption size 0 AND every live line has a row) passes →
    score = gate_score + (10 − gate_score) × reverse (reverse unmeasured when there are no ACTIVE cron rows:
    no bonus). Missing registry, failed ``crontab -l`` or an EMPTY crontab → UNVERIFIED.
    """
    dim = "registry_truth"
    rule = str(probe.need(dim, "gate_rule"))
    gs = _gate_score(probe)
    initial = float(_c(probe, dim, "baseline_initial"))
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
    if not live:
        # rc 0 with no live lines: nothing to measure coverage against — never a vacuous 100%
        return core.unverified(dim, rule, "crontab -l returned no live lines (empty crontab is not evidence)",
                               metrics={"registry_rows": len(reg["lanes"]), "baseline_size": _baseline_size(reg)},
                               evidence_list=[core.evidence("crontab -l", live_lines=0)])
    if initial <= 0:
        raise core.ConfigError(f"config dimensions.{dim}.baseline_initial must be > 0")
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
    coverage = with_row / n_live
    progress = max(0.0, 1.0 - base / initial)
    # no ACTIVE cron rows → reverse is unmeasured (None): the gate scores gate_score, no bonus
    reverse: Optional[float] = (present / len(active_cron)) if active_cron else None
    gate = base == 0 and with_row == n_live
    if gate:
        score = gs + (10.0 - gs) * (reverse or 0.0)
    else:
        score = (core.ratio_score(coverage, 1.0, gate_score=gs) + core.ratio_score(progress, 1.0, gate_score=gs)) / 2
    metrics = {
        "baseline_size": base, "baseline_initial": int(initial),
        "live_cron_lines": n_live, "lines_with_row": with_row, "lines_without_row": len(without_row),
        "undeclared_beyond_baseline": len(beyond_baseline), "stale_exemption_entries": stale_exempt,
        "registry_rows": len(reg["lanes"]), "active_cron_rows": len(active_cron),
        "active_cron_rows_present": present, "coverage": round(coverage, 4),
        "baseline_progress": round(progress, 4),
        "reverse_coverage": None if reverse is None else round(reverse, 4),
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
    return core.dim_result(dim, score=core.cap_on_fail(probe, score, gate), gate_rule=rule, gate_pass=gate,
                           metrics=metrics, evidence_list=ev, notes=notes)


# ── 2. rationalization ──────────────────────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    return " ".join(str(s or "").split())


def _cron_cmd(cmd: str) -> str:
    """Command text without its trailing ``# comment`` (comments get edited; the command is the identity)."""
    return _norm(re.split(r"\s+#\s", " " + str(cmd or "") + " ", maxsplit=1)[0])


class _HostState:
    """Lazily read scheduler state used to decide whether a plan item is gone. None = could not read."""

    def __init__(self, probe: core.Probe, cfgget, live_lines: list[str]):
        self.home = _home_norm(probe)
        self.probe, self._cfg, self.live = probe, cfgget, [_norm(self.home(x)) for x in live_lines]
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
            cmd = _cron_cmd(host.home(row["cmd"]))
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
    rule = str(probe.need(dim, "gate_rule"))
    gs = _gate_score(probe)

    def cfg(key: str) -> Any:
        return _c(probe, dim, key)

    for k in ("plan_rows_path", "plan_cron_rows_path", "r0_target", "merged_target", "merged_stretch",
              "pipelines_live_target", "pipelines_live_stretch", "pipeline_receipt_max_age_hours",
              "eliminate_prefixes", "merge_prefixes", "n8n_active_snapshot", "health_tick_steps"):
        cfg(k)  # every key up front: a missing one is a ConfigError, never a half-scored dimension
    text = probe.crontab()
    empty_crontab = text is not None and not _lr.discover_cron(text=text)
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
    elif empty_crontab:
        # an empty crontab would read every plan cron line as "gone" — unverified, never a pass
        notes.append("crontab -l returned no live lines: eliminated/merged vs plan UNVERIFIED")
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
        elim_score = core.ratio_score(eliminated, r0_target, gate_score=gs)
        merged_score = core.ratio_score(merged, merged_target, gate_score=gs, top=float(cfg("merged_stretch")))
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
    pipe_score = core.ratio_score(pipelines_live, p_target, gate_score=gs, top=float(cfg("pipelines_live_stretch")))
    metrics.update({"pipeline_stage_receipts": total_receipts, "pipelines_live": pipelines_live})
    ev.append(core.evidence(str(probe.runtime() / "pipeline_*_last.json"), receipts=total_receipts,
                            live=pipelines_live,
                            newest_live=max((r["run_ts_utc"] or "" for r in live_receipts), default=None) or None))

    score, status, mnotes = core.mean_score([("eliminated_vs_plan", elim_score), ("merged_vs_plan", merged_score),
                                             ("pipelines_live", pipe_score)])
    gate = (eliminated is not None and eliminated >= r0_target and merged is not None and merged >= merged_target
            and pipelines_live >= p_target)
    return core.dim_result(dim, score=core.cap_on_fail(probe, score, gate), gate_rule=rule, gate_pass=gate,
                           metrics=metrics, evidence_list=ev, status=status, notes=notes + mnotes)


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
      finished within max(run_window_cadence_multiple × expected_cadence_hours, window_hours) / movable. ratio_score(run_proven, 0.60, top=1.0).
      Ledger or ``runs`` table absent → None (UNVERIFIED part).
    * ``watched`` = rows NOT dispatcher-run (stay-behinds + undispatched movable) with an
      output_signal.kind other than "none" / those rows. ratio_score(watched, 1.0).

    Score = core.mean_score of the three. Gate: run_proven ≥ 0.60 AND watched ≥ 1.0.
    Empty populations never score: no schedulable lanes → UNVERIFIED; 0 movable lanes → declared/run_proven
    are None; no "rest" lanes → watched is None (gate needs every part measured).
    """
    dim = "scheduler_coverage"
    rule = str(probe.need(dim, "gate_rule"))
    gs = _gate_score(probe)
    window_h = probe.window_hours(dim)

    def cfg(key: str) -> Any:
        return _c(probe, dim, key)

    sched_kinds = set(cfg("schedulable_kinds"))
    disp_kinds = set(cfg("dispatcher_kinds"))
    states, modes = list(cfg("run_states")), list(cfg("run_modes"))
    d_min = float(cfg("dispatched_min_fraction"))
    w_min = float(cfg("watched_min_fraction"))
    for k in ("stay_tokens", "stay_substrings", "stay_lane_ids", "stay_note_markers"):
        cfg(k)

    reg_path = probe.proj / REGISTRY_REL
    reg = _load_registry(probe)
    if reg is None:
        return core.unverified(dim, rule, f"registry unreadable: {reg_path}",
                               evidence_list=[core.evidence(str(reg_path), readable=False)])
    pop = [r for r in reg["lanes"] if r.get("state") == _lr.STATE_ACTIVE
           and (r.get("scheduler") or {}).get("kind") in sched_kinds]
    if not pop:
        return core.unverified(dim, rule, "no ACTIVE schedulable lanes in the registry (empty population)",
                               evidence_list=[core.evidence(str(reg_path), rows=len(reg["lanes"]))])
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
            q = ("SELECT lane_id, MAX(finished_at) FROM runs WHERE finished_at IS NOT NULL "
                 f"AND state IN ({','.join('?' * len(states))}) AND mode IN ({','.join('?' * len(modes))}) "
                 "GROUP BY lane_id")
            last_run = {str(a): str(b) for a, b in con.execute(q, (*states, *modes)).fetchall()}
        except Exception as exc:  # noqa: BLE001 — table absent/locked: run evidence UNVERIFIED
            ledger_note = f"ledger runs table unreadable: {type(exc).__name__}"
        finally:
            con.close()
    floor = window_h
    mult = float(cfg("run_window_cadence_multiple"))
    proven: list[str] = []
    if last_run is not None:
        for r in dispatched:
            lid = str(r.get("lane_id"))
            ts = core.parse_ts(last_run.get(lid))
            win = max(mult * float(r.get("expected_cadence_hours") or 0), floor)
            if ts is not None and ts >= probe.since(win):
                proven.append(lid)

    n_mov = len(movable)
    declared_frac: Optional[float] = len(dispatched) / n_mov if n_mov else None
    proven_frac: Optional[float] = (len(proven) / n_mov) if (n_mov and last_run is not None) else None
    rest = [r for r in pop if str(r.get("lane_id")) not in set(proven)]
    watched = [r for r in rest if ((r.get("output_signal") or {}).get("kind") or "none") != "none"]
    watched_frac: Optional[float] = len(watched) / len(rest) if rest else None

    def sub(v: Optional[float], g: float, top: Optional[float] = None) -> Optional[float]:
        return None if v is None else core.ratio_score(v, g, gate_score=gs, top=top)
    parts = [("declared_on_dispatcher", sub(declared_frac, d_min, 1.0)),
             ("run_proven_on_dispatcher", sub(proven_frac, d_min, 1.0)),
             ("rest_watched", sub(watched_frac, w_min))]
    score, status, mnotes = core.mean_score(parts)
    gate = (proven_frac is not None and proven_frac >= d_min and watched_frac is not None
            and watched_frac >= w_min)
    if not n_mov:
        mnotes.append("0 movable lanes: dispatcher coverage unmeasurable (not a vacuous 100%)")
    metrics = {
        "schedulable_active_lanes": len(pop), "stay_behind_lanes": len(stay), "movable_lanes": n_mov,
        "dispatcher_declared": len(dispatched), "dispatcher_run_proven": len(proven) if last_run is not None else None,
        "declared_fraction": None if declared_frac is None else round(declared_frac, 4),
        "run_proven_fraction": None if proven_frac is None else round(proven_frac, 4),
        "rest_lanes": len(rest), "rest_watched": len(watched), "watched_fraction": None if watched_frac is None else round(watched_frac, 4),
        "ledger_lanes_with_live_runs": None if last_run is None else len(last_run),
        "run_window_floor_hours": window_h,
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
    return core.dim_result(dim, score=core.cap_on_fail(probe, score, gate), gate_rule=rule, gate_pass=gate,
                           metrics=metrics, evidence_list=ev, status=status, notes=notes)


def _iso(d: Any) -> Optional[str]:
    return d.isoformat() if d is not None else None


COLLECTORS = {
    "registry_truth": registry_truth,
    "rationalization": rationalization,
    "scheduler_coverage": scheduler_coverage,
}
