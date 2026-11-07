#!/usr/bin/env bash
# CUT2 rollback. Each step is independent; run the ones that were applied, newest first.
#   R1 cron lines back : python3 scripts/pipelines/cutover/_cutover.py rollback --lane <lane> --apply   (per lane;
#                        uncomments exactly the `n8n-cutover <lane>` tagged lines) — or restore the 04 backup file.
#   R2 effect owners   : effect_claim.py set-owner --process <p> --owner cron --expect-epoch <e>  (keyed: hermes-research-worker-pool news-to-catalyst update-lockup-earnings-dates)
#   R3 relay live list : restore ~/.config/tradeai/n8n-live-lanes.env.bak-*-CUT2 and restart tradeai-n8n-run-relay
#   R4 registry        : revert the wave PR (rows back to shadow / dry_run) and promote; or dispatch.mode off.
# Lanes: hermes-research-worker-pool news-to-catalyst update-lockup-earnings-dates
echo "read the header; nothing is run automatically"
