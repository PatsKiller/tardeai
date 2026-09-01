# PHASE 214F — Kill-Switch Behavior Tests (2026-06-07)

Status:      HISTORICAL
as_of:       2026-06-07T17:19:21-04:00
Measured at: efcc51365 / not measured

- Helper: canonical absent → (False,''); describe shows retired ignored ✓
- Coordinator with no kill-switch → kill_switch_active()=None (proceeds) ✓
- `touch data/runtime/HERMES_DISABLED` → kill_switch_active() returns canonical path (Coordinator aborts) ✓
- removed file → kill_switch_active()=None (restored) ✓
- retired path never tripped (active path always canonical) ✓
- kill-switch file NOT left in place after tests ✓ (verified absent)
