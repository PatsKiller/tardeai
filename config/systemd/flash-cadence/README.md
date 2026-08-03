# Flash cadence (operator policy 2026-08-03)

## Defaults
- **DeepSeek Flash** is the fleet default for agents, watchlist, portfolio risk-ish, LLM intelligence, Hermes bulk.
- **DeepSeek Pro (v4)** is optional — see “When Pro is allowed” below.

## Schedules (host local time = ET)

| Job | Schedule | Command |
|-----|----------|---------|
| Watchlist Flash critics | **Weekdays 09:30** (skip if data/ticket fresh ~20h) | `flash_cadence_runner.py watchlist-daily` |
| Portfolio risk-ish Flash | **Hourly 07–19 weekdays**; **10:00 weekends** | `flash_cadence_runner.py portfolio-risk` |
| LLM intelligence Flash | **Weekdays 07:20, 12:20, 16:20** | `flash_cadence_runner.py llm-intelligence` |
| Agents / Hermes | Existing queues/timers; code paths default Flash | n/a |

## When Pro (deepseek-v4) is allowed
1. Operator clicks **DeepSeek v4** or **Paid…** on MAIN ticket desk  
2. CLI with explicit `--lane deepseek-v4` or `USE_PRO=1`  
3. Premium ticket review  
4. Documented CIO escalation after Flash + free dual lanes disagree/fail  
5. Monthly meta arbitration jobs  

Pro is **not** cron-default for agents, watchlist synthesis, Hermes batch, or home intel.

## Install timers (optional — operator)
```bash
# Example: install unit files from this directory into ~/.config/systemd/user/
# then: systemctl --user daemon-reload && systemctl --user enable --now tradeai-flash-watchlist-daily.timer
```
