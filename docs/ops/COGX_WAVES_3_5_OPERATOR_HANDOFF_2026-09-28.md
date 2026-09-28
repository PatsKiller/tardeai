---
Status: PROPOSED
as_of: 2026-09-28T00:35:00-04:00
Measured at: wt/cogx-w5-t1-20260927 (PRs #1325 → #1326 → #1327 → #1328, CI green)
---
# COGX Waves 3–5 — operator handoff (merge order, grants, deploy, installs, first runs, flips)

The permission classifier refuses `gh pr merge` and guard grant minting for this agent, so these are the operator's. Everything deployed here runs SHADOW / opt-in; nothing changes routing, models, pages, restarts or prompts until a flip in §5.

```bash
# 1. merge in order (each is stacked on the previous)
for n in 1325 1326 1327 1328; do gh pr merge $n --merge && sleep 5; done
cd ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild && git checkout -- docs/project/RELEASE_MANIFEST_LATEST.md 2>/dev/null; git fetch -q origin && git merge --ff-only origin/main && SHA=$(git rev-parse HEAD) && echo $SHA

# 2. grants (one per tier in the store; reasons keep the other campaigns' scopes valid)
G=bin/guard; $G show
R="pkg:pkg-20260928-waves-3-5-cognition-unification-maturity-80f2 pr:1326 pr:1327 pr:1328 sha:$SHA campaign:cognitive-transformation-20260927"
$G grant release-write --for 4h --uses 6  --reason "prepare and promote and rollback of main sha $SHA (COMBINED: keeps every live release scope valid) AND $R: Waves 3-5 tranche 1, all SHADOW; exact merged SHA only; no broker writes"
$G grant service       --for 4h --uses 8  --reason "$R: install + enable tradeai-contradiction-adjudicator.timer; re-install tradeai-gir-projector.service (TRADEAI_GIR_DB_SOURCES=1) from CURRENT; never delete"
$G grant cron          --for 4h --uses 4  --reason "$R: append the maturity-remeasure line from docs/ops/COGX_WAVE2_CRONTAB_LINES.txt; crontab backed up first; nothing removed"
$G grant db-write      --for 4h --uses 10 --reason "$R: rows in the intelligence.* projection tables only (seed_supervisor_sla --apply, gir_projector --apply); canonical stores untouched"

# 3. deploy (the conformance gate runs in warn mode and prints its verdict)
TRADEAI_RELEASE_CAMPAIGN=cognitive-transformation-20260927 bash scripts/cio_phase2_exact_main_deploy.sh prepare
TRADEAI_RELEASE_CAMPAIGN=cognitive-transformation-20260927 bash scripts/cio_phase2_exact_main_deploy.sh promote "$(ls -d ~/trade-ai-releases/portfolio-server/${SHA:0:9}-main-exact-phase2-* | tail -1)"
git checkout -- docs/project/RELEASE_MANIFEST_LATEST.md
CUR=$(readlink -f ~/trade-ai-releases/portfolio-server/CURRENT); echo $CUR

# 4. units + cron (copy from the served release, never a worktree)
for u in tradeai-contradiction-adjudicator.service tradeai-contradiction-adjudicator.timer tradeai-gir-projector.service; do install -m 0644 $CUR/config/systemd/user/$u ~/.config/systemd/user/$u && echo installed $u; done
systemctl --user daemon-reload && systemctl --user enable --now tradeai-contradiction-adjudicator.timer && systemctl --user list-timers --all | grep -E "adjudicator|gir-projector"
mkdir -p ~/backups-crontab && crontab -l > ~/backups-crontab/crontab-$(date -u +%Y%m%dT%H%M%SZ)-pre-cogx-w35.txt
{ crontab -l; grep "maturity_remeasure" $CUR/docs/ops/COGX_WAVE2_CRONTAB_LINES.txt; } | crontab -
crontab -l | grep -c maturity_remeasure    # expect 1

# 5. first runs from CURRENT
cd $CUR && set -a && . /run/user/1000/tradeai/env && set +a && PY=~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python
$PY scripts/seed_supervisor_sla.py --apply | tail -3                                   # SLA rows for the 2 new lanes
$PY scripts/lesson_promotion_cli.py enqueue --apply | head -8                          # 617 candidates → QUEUED (nothing promoted)
$PY scripts/contradiction_adjudicator.py --max-pairs 5                                  # dry: selection only, no call
$PY scripts/maturity_remeasure.py --write | head -14                                    # first lane-written score
TRADEAI_GIR_DB_SOURCES=1 $PY scripts/gir_projector.py --apply --state ~/trade-ai-releases/persistent-state/data/runtime/gir_projector_state.json | tail -4   # DEC/ACT nodes
```

## 5. Flips (each one a §17 decision; flip one, watch the receipts, then the next)

| Flip | How | Watch |
|---|---|---|
| Lesson promotion (O-W3-2) | `lesson_promotion_cli.py package --apply` → reply APPROVE on the gate → `decide <id> PROMOTED --by operator:mine:typed` | `MemoryContext.lessons_state` = PROMOTED_PRESENT |
| Adjudicator live (O-W3-3) | the timer runs `--apply` daily 19:30; nothing else to flip (Tier-2 gate + $0.50 cap) | `contradiction_verdicts.jsonl`, `contradiction_adjudicator_latest.json` |
| Influence ADVISORY (O-W3-4) | policy row `influence.surfaces.research` → ADVISORY (PR) | commit receipts `influence.mir`; divergence in `memory_shadow_measure_latest.json` |
| Registry routing (O-W4-2) | `TRADEAI_AGENT_REGISTRY_ROUTING=1` on the reactive-cycle unit | `agent_registry_routing_receipts.jsonl` must be empty first |
| Model chooser (O-W4-3) | `TRADEAI_MODEL_CHOOSER=advise` then `enforce` | `model_chooser_receipts.jsonl` disagreements |
| Ladder L4/L5 (O-W4-5) | add `--ladder` to the detector unit | `supervisor_ladder_receipts.jsonl` would_page rows first |
| Self-heal L1/L2 (O-W5-3) | add `--heal` to the detector unit | `supervisor_recoveries.jsonl` would_execute rows first |
| Conformance gate block (O-W5-2) | `TRADEAI_CONFORMANCE_GATE=block` in the deploy env — only after the silos are above the floor (9/12 below today) | `conformance_gate_receipts.jsonl` |
| Embeddings (I-W5-1) | `ollama pull nomic-embed-text`; `TRADEAI_EMBEDDINGS=1` | ladder step 7 `hit` |
| Flip 1 semantics | decide: strict HOLD on unresolved subjects (re-flip after the mint lane) or narrow to memory outages (rule + test change) | REFUSED rows |

The maturity lane re-scores every Monday; the closeout quotes that file, never a session's estimate. First measurement: 2.11.
