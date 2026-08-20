# CIO desk memo continuous regen — Phase C (2026-08-20)

**Authority:** READ_ONLY_ADVISORY · No broker / order / stop / 2FA  
**Status:** Units checked in **disabled by default**. Do **not** claim continuous live until the timer is enabled.

## Regenerate (manual)

From the canonical source tree (or this worktree after promote):

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
PYTHONPATH=scripts .venv/bin/python scripts/lib/cio_desk_synthesis.py
# writes: data/cio/cio_desk_note_latest.md
#         data/cio/cio_desk_memo_spine_latest.md
```

Same generator as `GET /api/v3/cio/desk-note`. Schema: `desk-note-v1.3.0`.

## Optional daily timer (off-peak 17:45 ET)

Units (WantedBy commented — **not** enabled):

- `config/systemd/user/tradeai-cio-desk-memo-regen.service`
- `config/systemd/user/tradeai-cio-desk-memo-regen.timer`

### Install (operator ack required)

```bash
mkdir -p ~/.config/systemd/user
ln -sf /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/config/systemd/user/tradeai-cio-desk-memo-regen.service \
  ~/.config/systemd/user/
ln -sf /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/config/systemd/user/tradeai-cio-desk-memo-regen.timer \
  ~/.config/systemd/user/
# Uncomment WantedBy= in both unit files, then:
systemctl --user daemon-reload
systemctl --user enable --now tradeai-cio-desk-memo-regen.timer
systemctl --user list-timers 'tradeai-cio-desk-memo-regen*'
```

Until that enable step: schedule is **optional / inactive**. Manual regen only.

## Tests

`tests/test_cio_desk_synthesis_golden.py` — fixture sections + dry generate schema `desk-note-v1.3.0`; rejects execution language (`buy now` / `place order`).

## Related

- [DESK_NOTE.md](../cio/DESK_NOTE.md) · [CIO_CLOSED_LOOP_LINEAGE_CLOSEOUT_2026-08-20.md](./CIO_CLOSED_LOOP_LINEAGE_CLOSEOUT_2026-08-20.md)
