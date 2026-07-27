-- Active Trader Stage 1 · 0005 feature flags, notifications, drive manifest, checkpoints (down)
DROP TABLE IF EXISTS active_trader_run_checkpoints;
DROP TABLE IF EXISTS active_trader_drive_sync_manifest;
DROP TABLE IF EXISTS active_trader_notification_events;
DROP TRIGGER IF EXISTS trg_feature_flags_append_only ON active_trader_feature_flags;
DROP TABLE IF EXISTS active_trader_feature_flags;
