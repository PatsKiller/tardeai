# Moomoo Rollback — Stage 5

All Stage 5 install artifacts are isolated under the user's ~/.local/**; rollback never
touches production.

## Procedure
```bash
# 1. stop any lab user services / OpenD
pkill -f '/OpenD' 2>/dev/null
for u in opend gateway replay-writer feature-engine health-monitor; do
  systemctl --user stop trade-ai-lab-moomoo-$u.service 2>/dev/null || true
done
# 2. remove runtime tmpfs config (shred)
python3 -c "import sys;sys.path.insert(0,'scripts');from active_trader.moomoo import secret_render;secret_render.cleanup()"
# 3. restore previous 'current' symlinks (none prior — this is the first install; to fully
#    remove: rm the version dirs + symlinks)
rm -f ~/.local/opt/trade-ai-lab/moomoo/opend/current ~/.local/venvs/trade-ai-lab/moomoo-api/current
#    (retain/quarantine a FAILED release dir for evidence rather than deleting)
# 4. verify no listener
ss -tlnp | grep -E ':1111[12]'    # expect empty
# 5. remove disabled user units if desired
rm -f ~/.config/systemd/user/trade-ai-lab-moomoo-*.service; systemctl --user daemon-reload
# 6. verify production unchanged
#    - prod schema hash unchanged (verified this stage)
#    - repo .venv / requirements.txt unchanged (verified: 0 changes)
#    - system Python cannot import moomoo (verified)
```
Downloads (~/.cache/...) and replay evidence (~/.local/share/...) are retained unless
explicitly purged. No production package/service/DB is involved at any step.
