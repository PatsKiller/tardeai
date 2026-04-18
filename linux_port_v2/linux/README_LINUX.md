# Trade AI v12 + Portfolio Intelligence — Linux Setup Guide
Ubuntu 22.04 / 24.04 (Debian-based)

---

## Prerequisites

- Ubuntu 22.04 or 24.04 (or any Debian-based distro)
- Python 3.11+ (installer will handle this)
- Node.js 20+ (installer will handle this)
- Internet access for pip/npm installs
- All API keys ready (see assets/.env.template)

---

## Quick Install

```bash
# 1. Copy your project to the Linux machine
cp -r /path/to/trade-ai-v12-rebuild ~/trade-ai

# 2. Run the installer
cd ~/trade-ai
chmod +x linux/install.sh
./linux/install.sh

# 3. Edit your API keys
nano assets/.env

# 4. Build price cache (first run takes 2-5 min)
source venv/bin/activate
python3 scripts/portfolio_price_cache.py

# 5. Test the pipeline
python3 scripts/portfolio_orchestrator.py

# 6. Install cron jobs (see Scheduling section below)
```

---

## File Differences: Windows vs Linux

| Component | Windows | Linux |
|---|---|---|
| Launcher extension | `.bat` | `.sh` |
| venv activation | `venv\Scripts\activate.bat` | `source venv/bin/activate` |
| Python command | `python` | `python3` |
| Path separator | `\` | `/` |
| Scheduler | Task Scheduler | cron |
| Working dir in launcher | `cd /d C:\Users\...` | `cd "$PROJECT_ROOT"` |
| Browser open | `start "" "http://..."` | `xdg-open "http://..."` |

All Python scripts use `pathlib.Path()` and are cross-platform.
The `.env` file format is identical on both platforms.

---

## Launcher Files

All launchers are in `launchers/`. Make them executable after copying:

```bash
chmod +x launchers/*.sh
```

| Launcher | Purpose | Scheduled? |
|---|---|---|
| `run_continuous.sh` | Trade AI 4AM-10:30AM pipeline | Yes — Mon-Fri 4AM |
| `run_portfolio.sh` | Portfolio daily run | Yes — Mon-Fri 7AM |
| `run_portfolio_monthly.sh` | Portfolio monthly full run | Yes — 1st of month 7:05AM |
| `run_portfolio_weekly.sh` | Portfolio weekly technical scan | Yes — Sunday 8PM |
| `run_price_cache.sh` | Rebuild Yahoo price cache | Yes — Sunday 7PM |
| `run_dashboard.sh` | Start dashboard servers | Manual only |

---

## Scheduling with Cron

The `linux/crontab.txt` file contains ready-to-use cron entries.

**Install cron jobs:**
```bash
# Preview what will be installed
cat linux/crontab.txt

# Install (appends to existing crontab)
crontab -l > /tmp/existing.txt 2>/dev/null || true
cat linux/crontab.txt >> /tmp/existing.txt
crontab /tmp/existing.txt

# Verify
crontab -l
```

**Cron schedule:**
```
CRON_TZ=America/New_York

0  4  *  *  1-5   launchers/run_continuous.sh         # Trade AI   Mon-Fri 4AM
0  7  *  *  1-5   launchers/run_portfolio.sh           # Portfolio  Mon-Fri 7AM
5  7  1  *  *     launchers/run_portfolio_monthly.sh   # Monthly    1st 7:05AM
0  19 *  *  0     launchers/run_price_cache.sh         # Cache      Sunday 7PM
0  20 *  *  0     launchers/run_portfolio_weekly.sh    # Weekly     Sunday 8PM
```

**View cron logs:**
```bash
grep CRON /var/log/syslog | tail -20
tail -f ~/trade-ai/logs/cron_trade_ai.log
```

---

## Viewing the Dashboard

The dashboard requires a browser. On a headless server, use SSH port forwarding:

```bash
# On your local machine:
ssh -L 7777:localhost:7777 -L 7778:localhost:7778 user@server

# On the server, start the dashboard:
cd ~/trade-ai
source venv/bin/activate
python3 scripts/portfolio_server.py &
python3 scripts/portfolio_proxy.py --root . &

# Then open in your local browser:
# http://localhost:7777/portfolio_live.html
```

Or use `launchers/run_dashboard.sh` which handles both servers.

---

## Fidelity 401k CSV

The Fidelity 401k is loaded automatically by `portfolio_loader.py` when you
drop the exported CSV into `data/portfolios/input/`. The loader detects
Fidelity format by filename pattern. No manual entry required.

Export from: Fidelity.com → Accounts → Portfolio → Download (CSV format)
Drop into: `data/portfolios/input/`
Filename pattern: `Portfolio_Positions_*.csv`

---

## Fresh Restore Checklist

If restoring to a new Linux machine from scratch:

```bash
# 1. Clone or copy project
cp -r trade-ai-v12-rebuild ~/trade-ai
cd ~/trade-ai

# 2. Run installer
chmod +x linux/install.sh
./linux/install.sh

# 3. Restore your .env (contains all API keys — keep a secure backup)
cp /backup/assets/.env assets/.env

# 4. Restore state data (optional — contains price cache and snapshots)
cp -r /backup/data/portfolios/state data/portfolios/

# 5. Drop current Schwab + Fidelity CSVs
# Copy CSVs to data/portfolios/input/

# 6. Rebuild price cache if state not restored
python3 scripts/portfolio_price_cache.py

# 7. Run pipeline
python3 scripts/portfolio_orchestrator.py

# 8. Install cron jobs
crontab linux/crontab.txt
```

---

## Troubleshooting

**Permission denied on .sh files:**
```bash
chmod +x launchers/*.sh linux/*.sh
```

**Python package install fails:**
```bash
sudo apt-get install python3-dev build-essential libssl-dev
pip install -r requirements.txt
```

**yfinance SSL errors:**
```bash
pip install --upgrade certifi
```

**Cron jobs not running:**
```bash
# Check cron service is running
sudo systemctl status cron

# Check timezone is set in crontab
crontab -l | grep CRON_TZ

# Test launcher manually
bash launchers/run_portfolio.sh
```

**Dashboard not accessible remotely:**
Use SSH port forwarding (see Viewing the Dashboard section above).
The servers bind to localhost only for security.
