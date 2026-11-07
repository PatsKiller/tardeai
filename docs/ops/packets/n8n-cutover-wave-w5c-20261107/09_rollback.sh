#!/usr/bin/env bash
# W5C rollback. Each step is independent; run the ones that were applied, newest first.
#   R1 cron lines back : python3 scripts/pipelines/cutover/_cutover.py rollback --lane <lane> --apply   (per lane;
#                        uncomments exactly the `n8n-cutover <lane>` tagged lines) — or restore the 04 backup file.
#   R2 effect owners   : effect_claim.py set-owner --process <p> --owner cron --expect-epoch <e>  (keyed: finviz-enrichment-scalp-hot)
#   R3 relay live list : restore ~/.config/tradeai/n8n-live-lanes.env.bak-*-W5C and restart tradeai-n8n-run-relay
#   R4 registry        : revert the wave PR (rows back to shadow / dry_run) and promote; or dispatch.mode off.
# Lanes: finviz-enrichment-scalp-hot
echo "read the header; nothing is run automatically"
