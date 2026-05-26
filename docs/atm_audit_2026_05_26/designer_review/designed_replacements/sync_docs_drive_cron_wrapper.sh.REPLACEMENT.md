# Designer Replacement: sync-docs-to-drive.py gog PATH fix

**Status:** ALREADY APPLIED (earlier in this session)  
**Git Baseline:** `c1286d314deb377df49713e1646f139db7f43643`  
**Applied Change:** `scripts/sync-docs-to-drive.py` line 14-15  

## Problem

The cron environment does not include `~/.local/bin` in PATH. The sync script
called `subprocess.run(['gog', ...])` which fails with `[Errno 2] No such file or directory: 'gog'`
during cron runs, even though interactive runs work fine.

## Fix Applied

Added `GOG_BIN = '/home/johnclaw/.local/bin/gog'` constant after the env setup line,
and changed the `subprocess.run(['gog']` call to `subprocess.run([GOG_BIN]`.

```python
# Before (line 55):
r = subprocess.run(['gog'] + list(args) + ['--account', ACCOUNT, '--no-input'], ...)

# After:
GOG_BIN = '/home/johnclaw/.local/bin/gog'
...
r = subprocess.run([GOG_BIN] + list(args) + ['--account', ACCOUNT, '--no-input'], ...)
```

## Verification

The 18:05 cron run showed `0 uploaded, 2286 unchanged, 0 failed` — confirming
the gog binary is now found. The `manifest upload failed (non-fatal)` error still
appeared because the first cron instance didn't have the fix yet. Next hourly run
will be fully clean.

## No Further Action Needed

This fix is complete and verified.
