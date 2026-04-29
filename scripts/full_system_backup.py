#!/usr/bin/env python3
"""full_system_backup.py — Complete system backup to a single dated zip file.

Creates a self-contained backup with everything needed to restore from bare metal:
- Database dump (full PostgreSQL)
- Crontab
- OpenClaw configs (gateway, agents, cron jobs, SOULs)
- Systemd services
- .env (API keys, passwords)
- Screener configs
- Agent YAML configs
- Key state files (holdings, enrichment, dividends)
- Restore instructions (embedded in zip)

Output: docs/backups/trade_ai_backup_YYYYMMDD.zip

Usage:
    python3 scripts/full_system_backup.py
    python3 scripts/full_system_backup.py --dry-run
"""
import json, os, shutil, subprocess, sys, tempfile
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKUP_DIR = PROJECT_ROOT / "docs" / "backups"
HOME = Path.home()


def _run(cmd, capture=True):
    """Run a shell command and return output."""
    r = subprocess.run(cmd, shell=True, capture_output=capture, text=True, timeout=120)
    return r.stdout.strip() if capture else ""


def create_backup(dry_run=False):
    today = datetime.now().strftime("%Y%m%d")
    zip_name = f"trade_ai_backup_{today}"
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmpdir:
        staging = Path(tmpdir) / zip_name
        staging.mkdir()

        print(f"=== Full System Backup — {today} ===\n")

        # 1. Database dump
        print("[1/10] Database dump...")
        db_dir = staging / "database"
        db_dir.mkdir()
        db_pw = ""
        for line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if line.startswith("DB_PASSWORD="): db_pw = line.split("=", 1)[1].strip()
        if db_pw and not dry_run:
            os.environ["PGPASSWORD"] = db_pw
            r = subprocess.run(
                f'pg_dump -h localhost -U trade_ai trade_ai | gzip > "{db_dir}/trade_ai.sql.gz"',
                shell=True, capture_output=True, text=True, timeout=120
            )
            size = (db_dir / "trade_ai.sql.gz").stat().st_size if (db_dir / "trade_ai.sql.gz").exists() else 0
            print(f"  DB dump: {size / 1e6:.1f} MB")
        else:
            print(f"  {'DRY RUN' if dry_run else 'No DB password'}")

        # 2. Environment file
        print("[2/10] Environment variables...")
        env_dir = staging / "env"
        env_dir.mkdir()
        if not dry_run:
            shutil.copy2(PROJECT_ROOT / ".env", env_dir / "dot_env")
            # Also create a sanitized version (keys masked)
            lines = []
            for line in (PROJECT_ROOT / ".env").read_text().splitlines():
                if "=" in line and not line.startswith("#"):
                    key, val = line.split("=", 1)
                    if any(s in key.upper() for s in ["PASSWORD", "TOKEN", "KEY", "SECRET", "AUTH", "COOKIE"]):
                        lines.append(f"{key}=<REDACTED — {len(val)} chars>")
                    else:
                        lines.append(line)
                else:
                    lines.append(line)
            (env_dir / "dot_env_SANITIZED.txt").write_text("\n".join(lines))
        print(f"  .env backed up (+ sanitized version)")

        # 3. Crontab
        print("[3/10] Crontab...")
        cron_dir = staging / "crontab"
        cron_dir.mkdir()
        if not dry_run:
            crontab = _run("crontab -l 2>/dev/null")
            (cron_dir / "crontab.txt").write_text(crontab)
            lines = len(crontab.split("\n"))
            print(f"  {lines} lines")

        # 4. OpenClaw configs
        print("[4/10] OpenClaw configs...")
        oc_dir = staging / "openclaw"
        oc_dir.mkdir()
        oc_files = [
            (HOME / ".openclaw" / "openclaw.json", "openclaw.json"),
            (HOME / ".openclaw" / "cron" / "jobs.json", "cron_jobs.json"),
            (HOME / ".openclaw" / "agents" / "steph" / "agent" / "SOUL.md", "steph_SOUL.md"),
            (HOME / ".openclaw" / "agents" / "aegis" / "SOUL.md", "aegis_SOUL.md"),
        ]
        for src, dst in oc_files:
            if src.exists() and not dry_run:
                shutil.copy2(src, oc_dir / dst)
                print(f"  {dst}")

        # 5. Systemd services
        print("[5/10] Systemd services...")
        sd_dir = staging / "systemd"
        sd_dir.mkdir()
        svc_path = HOME / ".config" / "systemd" / "user"
        if svc_path.exists() and not dry_run:
            for f in svc_path.glob("tradeai-*"):
                shutil.copy2(f, sd_dir / f.name)
                print(f"  {f.name}")
            for f in svc_path.glob("aegis-*"):
                shutil.copy2(f, sd_dir / f.name)
                print(f"  {f.name}")
            for f in svc_path.glob("portfolio-*"):
                shutil.copy2(f, sd_dir / f.name)
                print(f"  {f.name}")
            for f in svc_path.glob("recovery-*"):
                shutil.copy2(f, sd_dir / f.name)
                print(f"  {f.name}")

        # 6. Config files
        print("[6/10] Config files...")
        cfg_dir = staging / "config"
        cfg_dir.mkdir()
        configs = [
            PROJECT_ROOT / "assets" / "screeners.yaml",
            PROJECT_ROOT / "config" / "agents_sec_interaction.yaml",
        ]
        for c in configs:
            if c.exists() and not dry_run:
                shutil.copy2(c, cfg_dir / c.name)
                print(f"  {c.name}")

        # 7. Launcher scripts
        print("[7/10] Launcher scripts...")
        launch_dir = staging / "launchers"
        launch_dir.mkdir()
        ll = PROJECT_ROOT / "linux_launchers"
        if ll.exists() and not dry_run:
            for f in ll.glob("*.sh"):
                shutil.copy2(f, launch_dir / f.name)
                print(f"  {f.name}")

        # 8. Key state files
        print("[8/10] State files...")
        state_dir = staging / "state"
        state_dir.mkdir()
        state_src = PROJECT_ROOT / "data" / "portfolios" / "state"
        state_files = ["holdings.json", "ticker_enrichment_cache.json", "dividend_calendar.json",
                       "retirement_roadmap.json", "risk_management.json", "stops.json"]
        for f in state_files:
            p = state_src / f
            if p.exists() and not dry_run:
                shutil.copy2(p, state_dir / f)
                print(f"  {f} ({p.stat().st_size / 1e3:.0f} KB)")

        # 9. Documentation
        print("[9/10] Documentation...")
        docs_dir = staging / "docs"
        docs_dir.mkdir()
        for f in (PROJECT_ROOT / "docs").glob("TRADE_AI_V12_SYSTEM_BIBLE*.md"):
            if not dry_run:
                shutil.copy2(f, docs_dir / f.name)
        if (PROJECT_ROOT / "docs" / "RESTORE_GUIDE.md").exists() and not dry_run:
            shutil.copy2(PROJECT_ROOT / "docs" / "RESTORE_GUIDE.md", docs_dir / "RESTORE_GUIDE.md")
        print(f"  Bible + Restore Guide")

        # 10. Restore instructions (embedded)
        print("[10/10] Generating restore instructions...")
        if not dry_run:
            (staging / "RESTORE_FROM_THIS_BACKUP.md").write_text(f"""# Trade AI v12 — Restore from Backup

**Backup date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}
**System:** ms01-openclaw

## Prerequisites
- Ubuntu/Debian server with Python 3.11+
- PostgreSQL installed (`sudo apt install postgresql`)
- Ollama installed with qwen3:1.7b model
- Node.js 18+ (for Command Center UI)

## Step-by-Step Restore

### 1. Clone the git repo
```bash
git clone <repo_url> ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild
cd ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild
```

### 2. Restore .env (API keys + passwords)
```bash
cp env/dot_env ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.env
# OR manually recreate from env/dot_env_SANITIZED.txt
```

### 3. Create Python virtual environment
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install psycopg2-binary yfinance requests pyyaml youtube-transcript-api
```

### 4. Restore PostgreSQL database
```bash
sudo -u postgres createuser trade_ai
sudo -u postgres createdb trade_ai -O trade_ai
sudo -u postgres psql -c "ALTER USER trade_ai PASSWORD '<password_from_env>';"
DB_PW=$(grep '^DB_PASSWORD=' .env | cut -d= -f2)
gunzip < database/trade_ai.sql.gz | PGPASSWORD="$DB_PW" psql -h localhost -U trade_ai trade_ai
```

### 5. Restore crontab
```bash
crontab crontab/crontab.txt
```

### 6. Restore OpenClaw configs
```bash
mkdir -p ~/.openclaw/cron ~/.openclaw/agents/steph/agent ~/.openclaw/agents/aegis
cp openclaw/openclaw.json ~/.openclaw/
cp openclaw/cron_jobs.json ~/.openclaw/cron/jobs.json
cp openclaw/steph_SOUL.md ~/.openclaw/agents/steph/agent/SOUL.md
cp openclaw/aegis_SOUL.md ~/.openclaw/agents/aegis/SOUL.md
```

### 7. Restore systemd services
```bash
cp systemd/* ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now tradeai-continuous.timer
```

### 8. Restore config files
```bash
cp config/screeners.yaml ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/assets/
cp config/agents_sec_interaction.yaml ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/config/
```

### 9. Restore launcher scripts
```bash
cp launchers/*.sh ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/linux_launchers/
chmod +x ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/linux_launchers/*.sh
```

### 10. Restore state files (optional — will regenerate on next pipeline run)
```bash
mkdir -p ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/data/portfolios/state
cp state/*.json ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/data/portfolios/state/
```

### 11. Start services
```bash
cd ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild
source .venv/bin/activate
nohup .venv/bin/python scripts/portfolio_server.py > /dev/null 2>&1 &
openclaw gateway restart
```

### 12. Verify
```bash
python3 scripts/system_preflight_check.py
```
Should pass 21+ of 23 checks.

### 13. Build Command Center UI
```bash
cd apps/command-center-v2
npm install
npx vite build
```

## What's in this backup

| Directory | Contents |
|---|---|
| `database/` | Full PostgreSQL dump (143 tables, ~105 MB uncompressed) |
| `env/` | .env file + sanitized version |
| `crontab/` | Full crontab (46 active entries) |
| `openclaw/` | Gateway config, cron jobs, agent SOULs |
| `systemd/` | Service + timer files |
| `config/` | Screener YAML, agent YAML |
| `launchers/` | Shell scripts for service launchers |
| `state/` | Current portfolio state files |
| `docs/` | System Bible + Restore Guide |
""")

        # Create zip
        if not dry_run:
            zip_path = shutil.make_archive(str(BACKUP_DIR / zip_name), 'zip', tmpdir, zip_name)
            size_mb = os.path.getsize(zip_path) / 1e6
            print(f"\n{'='*50}")
            print(f"BACKUP COMPLETE: {zip_path}")
            print(f"Size: {size_mb:.1f} MB")
            print(f"Contains: DB dump + .env + crontab + OpenClaw + systemd + configs + state + docs + restore instructions")

            # Cleanup old backups (keep 4 weeks)
            for old in sorted(BACKUP_DIR.glob("trade_ai_backup_*.zip"))[:-4]:
                old.unlink()
                print(f"  Purged old backup: {old.name}")

            return str(zip_path)
        else:
            print(f"\n[DRY RUN] Would create: docs/backups/{zip_name}.zip")
            return None


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    create_backup(dry_run=dry)
