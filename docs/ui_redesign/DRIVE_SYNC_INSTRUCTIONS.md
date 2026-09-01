# Google Drive Sync Instructions

Status:      HISTORICAL
as_of:       2026-05-25T10:45:00-04:00
Measured at: efcc51365 / not measured

Generated: 2026-05-25

## Status: MANUAL SYNC REQUIRED

The gog CLI is installed at `/home/johnclaw/.local/bin/gog` but requires keyring password
access which was not available in this automated session.

## To Sync Manually

Run these commands:

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild

# Set keyring password
export GOG_KEYRING_PASSWORD=$(cat ~/.openclaw/credentials/gog_keyring_password)

# Find Trade_AI_Docs_v2 folder ID
gog drive ls --account john@jwwhiting.com \
  --query "name = 'Trade_AI_Docs_v2' and mimeType = 'application/vnd.google-apps.folder'"

# Create ui_redesign subfolder (replace PARENT_ID with folder ID above)
gog drive mkdir --account john@jwwhiting.com \
  --parent PARENT_ID --name ui_redesign

# Upload the archive
gog drive upload --account john@jwwhiting.com \
  --parent UI_REDESIGN_FOLDER_ID \
  docs/ui_redesign_trade_ai_command_center_full_20260525.tgz

# Or upload individual docs
gog drive upload --account john@jwwhiting.com \
  --parent UI_REDESIGN_FOLDER_ID \
  docs/ui_redesign/README_DESIGN_HANDOFF.md \
  docs/ui_redesign/ALL_V2_ROUTE_MAP.md \
  docs/ui_redesign/HANDOFF_MANIFEST.md
```

## Archive to Upload
- `docs/ui_redesign_trade_ai_command_center_full_20260525.tgz` (865K)
