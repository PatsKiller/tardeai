---
Status: PROPOSED
as_of: 2026-09-27T22:45:00-04:00
Measured at: wt/cogx-w2-t4-20260927 b138c2684 (CI green on #1319 and #1321)
---
# COGX Wave 2 tranches 3 + 4 — operator handoff (merge, deploy, install)

The permission classifier refused `gh pr merge` and the guard grant requests this session, so these steps are the operator's. Run in order; each block is idempotent.

```bash
# 1. merge in order (tranche 4 is stacked on tranche 3)
gh pr merge 1319 --merge && sleep 5 && gh pr merge 1321 --merge
cd ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild && git checkout -- docs/project/RELEASE_MANIFEST_LATEST.md 2>/dev/null; git fetch -q origin && git merge --ff-only origin/main && SHA=$(git rev-parse HEAD) && echo $SHA

# 2. grants (one grant per tier lives in the store; these reasons keep the other campaigns' scopes valid)
G=bin/guard; $G show
R="pkg:pkg-20260928-wave-2-enforcement-35c4 pr:1319 pr:1321 sha:$SHA campaign:cognitive-transformation-20260927"
$G grant release-write --for 4h --uses 6  --reason "prepare and promote and rollback of main sha $SHA (COMBINED: keeps the live options-fill-truth-20260927 AND audit-rest-20260927 AND platform-due-diligence-20260927 release scope valid) AND $R: Wave 2 tranches 3+4; exact merged SHA only; no broker writes"
$G grant service       --for 4h --uses 6  --reason "$R: install + enable tradeai-edge-fanout-consumer.timer from CURRENT (items 3-4); never delete"
$G grant cron          --for 4h --uses 4  --reason "$R: append the one crontab line in docs/ops/COGX_WAVE2_CRONTAB_LINES.txt (lane sec-filings-feed, item 5); crontab backed up first; nothing removed"
$G grant db-write      --for 4h --uses 10 --reason "$R: rows in the intelligence.* projection tables only (seed_supervisor_sla --apply, gir_projector --apply, research_index via the feed); canonical stores untouched"

# 3. deploy
TRADEAI_RELEASE_CAMPAIGN=cognitive-transformation-20260927 bash scripts/cio_phase2_exact_main_deploy.sh prepare
TRADEAI_RELEASE_CAMPAIGN=cognitive-transformation-20260927 bash scripts/cio_phase2_exact_main_deploy.sh promote "$(ls -d ~/trade-ai-releases/portfolio-server/${SHA:0:9}-main-exact-phase2-* | tail -1)"
git checkout -- docs/project/RELEASE_MANIFEST_LATEST.md
CUR=$(readlink -f ~/trade-ai-releases/portfolio-server/CURRENT); echo $CUR

# 4. install the fan-out timer (copy from the served release, never a worktree)
for u in tradeai-edge-fanout-consumer.service tradeai-edge-fanout-consumer.timer; do install -m 0644 $CUR/config/systemd/user/$u ~/.config/systemd/user/$u && echo installed $u; done
systemctl --user daemon-reload && systemctl --user enable --now tradeai-edge-fanout-consumer.timer
systemctl --user list-timers --all | grep edge-fanout

# 5. cron line for the filings feed (back up, append, reinstall via stdin)
mkdir -p ~/backups-crontab && crontab -l > ~/backups-crontab/crontab-$(date -u +%Y%m%dT%H%M%SZ)-pre-cogx-w2.txt
{ crontab -l; grep -v '^#' $CUR/docs/ops/COGX_WAVE2_CRONTAB_LINES.txt; } | crontab -
crontab -l | grep -c sec_filings_feed    # expect 1

# 6. first runs from CURRENT (SLA rows for the two new lanes; first filing events; project them)
cd $CUR && set -a && . /run/user/1000/tradeai/env && set +a && PY=~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python
$PY scripts/seed_supervisor_sla.py --apply | tail -3
$PY scripts/sec_filings_feed.py --apply --since-days 45 | head -20
$PY scripts/gir_projector.py --apply --state ~/trade-ai-releases/persistent-state/data/runtime/gir_projector_state.json | tail -4
systemctl --user start tradeai-edge-fanout-consumer.service && cat ~/trade-ai-releases/persistent-state/data/runtime/edge_fanout_consumer_latest.json
```

Proof to expect: `sec_filings_feed_latest.json` with `new` > 0 and `high_severity_new` ≥ 2 (DELL 09-01 / 09-15); projector counts `filing_events` > 0; `edge_fanout_consumer_latest.json` with `pg: true`; the next detector cycle (`*/30`) reports `stats.sec_filing.fired`; `research_write_path_receipts.jsonl` grows as producers run. Then I flip the two lane rows to ACTIVE in the closeout PR.

Open operator decision (flip 1): ENFORCED currently HOLDS on unresolved subjects (strict). Either re-flip after the mint lane closes the identity gaps, or approve narrowing ENFORCED to memory outages only (a façade rule + test change). The row is SHADOW until decided.
