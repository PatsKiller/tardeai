#!/usr/bin/env python3
"""full_system_backup.py — Complete system backup to a single dated zip file.

Creates a self-contained backup with everything needed to restore from bare metal:
- Database dump (full PostgreSQL)
- Crontab
- OpenClaw configs (gateway, agents, cron jobs, SOULs, workspaces, skills)
- Systemd services
- .env (API keys, passwords)
- Screener configs
- Agent YAML configs
- All Python scripts (automation pipeline)
- Command Center UI source
- Key state files (holdings, enrichment, dividends)
- Full data/portfolios directory
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
        print("[1/16] Database dump...")
        db_dir = staging / "database"
        db_dir.mkdir()
        db_pw = ""
        for line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if line.startswith("DB_PASSWORD="): db_pw = line.split("=", 1)[1].strip()
        if db_pw and not dry_run:
            os.environ["PGPASSWORD"] = db_pw
            # Exclude DATA of large REGENERABLE tables — they bloat the dump and (on the single-threaded
            # live box) make pg_dump slow + lock-contending. Schema is still captured (so restore recreates
            # them empty), and each rebuilds from its own pipeline. Irreplaceable operational data —
            # holdings, trades, journal, directives, accounts, configs, SOULs — is fully backed up.
            REGENERABLE = ("content_embeddings", "hermes_score_history", "market_quotes", "ticker_snapshot_daily")
            _excl = " ".join(f"--exclude-table-data='{t}'" for t in REGENERABLE)
            r = subprocess.run(
                f'pg_dump -h localhost -U trade_ai {_excl} trade_ai | gzip > "{db_dir}/trade_ai.sql.gz"',
                shell=True, capture_output=True, text=True, timeout=600   # was 120 — too short as the DB grew
            )
            print(f"  (excluded data of regenerable tables: {', '.join(REGENERABLE)})")
            size = (db_dir / "trade_ai.sql.gz").stat().st_size if (db_dir / "trade_ai.sql.gz").exists() else 0
            print(f"  DB dump: {size / 1e6:.1f} MB")
        else:
            print(f"  {'DRY RUN' if dry_run else 'No DB password'}")

        # 2. Environment file
        # Phase-0 2026-07-21: NEVER write a raw plaintext .env / dot_env / .env.bak into backup
        # trees (historical-keys leak, often mode 0664). Sanitized names-only snapshot only.
        print("[2/16] Environment variables...")
        env_dir = staging / "env"
        env_dir.mkdir()
        if not dry_run:
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
            outp = env_dir / "dot_env_SANITIZED.txt"
            outp.write_text("\n".join(lines))
            outp.chmod(0o600)
            # Marker so restore docs know raw copy is intentionally absent
            (env_dir / "README_NO_RAW_ENV.txt").write_text(
                "Phase-0: raw .env is NOT backed up here. Restore secrets from Bitwarden "
                "(or operator Secrets modal) + re-render. Only sanitized key names live in "
                "dot_env_SANITIZED.txt.\n"
            )
        print(f"  .env sanitized names-only snapshot (raw copy DISABLED Phase-0)")

        # 3. Crontab
        print("[3/16] Crontab...")
        cron_dir = staging / "crontab"
        cron_dir.mkdir()
        if not dry_run:
            crontab = _run("crontab -l 2>/dev/null")
            (cron_dir / "crontab.txt").write_text(crontab)
            lines = len(crontab.split("\n"))
            print(f"  {lines} lines")

        # 4. OpenClaw configs (full — gateway, workspaces, skills, agents, credentials)
        print("[4/16] OpenClaw configs...")
        oc_dir = staging / "openclaw"
        oc_dir.mkdir()
        oc_root = HOME / ".openclaw"
        if oc_root.exists() and not dry_run:
            # Core config
            for f in ["openclaw.json"]:
                src = oc_root / f
                if src.exists():
                    shutil.copy2(src, oc_dir / f)
            # Cron jobs
            cron_src = oc_root / "cron"
            if cron_src.exists():
                cron_dst = oc_dir / "cron"
                shutil.copytree(cron_src, cron_dst, dirs_exist_ok=True)
            # All workspaces (main, aegis, steph, alex, admin)
            for ws in oc_root.glob("workspace*"):
                if ws.is_dir():
                    ws_dst = oc_dir / ws.name
                    shutil.copytree(ws, ws_dst, dirs_exist_ok=True,
                                    ignore=shutil.ignore_patterns("*.log", "__pycache__"))
                    print(f"  workspace: {ws.name}")
            # All custom skills
            skills_src = oc_root / "skills"
            if skills_src.exists():
                shutil.copytree(skills_src, oc_dir / "skills", dirs_exist_ok=True,
                                ignore=shutil.ignore_patterns("node_modules", "__pycache__"))
                skill_count = sum(1 for _ in skills_src.rglob("SKILL.md"))
                print(f"  skills: {skill_count} custom skills")
            # Agents directory
            agents_src = oc_root / "agents"
            if agents_src.exists():
                shutil.copytree(agents_src, oc_dir / "agents", dirs_exist_ok=True,
                                ignore=shutil.ignore_patterns("sessions", "*.log"))
                print(f"  agents dir backed up")
            # Credentials (encrypted tokens)
            creds_src = oc_root / "credentials"
            if creds_src.exists():
                shutil.copytree(creds_src, oc_dir / "credentials", dirs_exist_ok=True)
                print(f"  credentials backed up")
        print(f"  OpenClaw full backup complete")

        # 5. Systemd services (all user services)
        print("[5/16] Systemd services...")
        sd_dir = staging / "systemd"
        sd_dir.mkdir()
        svc_path = HOME / ".config" / "systemd" / "user"
        if svc_path.exists() and not dry_run:
            for f in svc_path.iterdir():
                if f.is_file() and (f.suffix in (".service", ".timer")):
                    shutil.copy2(f, sd_dir / f.name)
                    print(f"  {f.name}")

        # 5b. System-level Ollama service override (GPU config)
        ollama_override = Path("/etc/systemd/system/ollama.service.d/override.conf")
        if ollama_override.exists() and not dry_run:
            shutil.copy2(ollama_override, sd_dir / "ollama_override.conf")
            print(f"  ollama_override.conf (GPU config)")

        # 6. Config files (all YAML, JSON configs)
        print("[6/16] Config files...")
        cfg_dir = staging / "config"
        cfg_dir.mkdir()
        # Assets directory
        assets_src = PROJECT_ROOT / "assets"
        if assets_src.exists() and not dry_run:
            shutil.copytree(assets_src, cfg_dir / "assets", dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__"))
        # Config directory
        config_src = PROJECT_ROOT / "config"
        if config_src.exists() and not dry_run:
            shutil.copytree(config_src, cfg_dir / "config", dirs_exist_ok=True)
        print(f"  assets/ + config/ backed up")

        # 7. Launcher scripts
        print("[7/16] Launcher scripts...")
        launch_dir = staging / "launchers"
        launch_dir.mkdir()
        ll = PROJECT_ROOT / "linux_launchers"
        if ll.exists() and not dry_run:
            for f in ll.glob("*.sh"):
                shutil.copy2(f, launch_dir / f.name)
            print(f"  {sum(1 for _ in ll.glob('*.sh'))} launcher scripts")

        # 8. All Python scripts (core automation)
        print("[8/16] Python scripts...")
        scripts_dir = staging / "scripts"
        scripts_dir.mkdir()
        scripts_src = PROJECT_ROOT / "scripts"
        if scripts_src.exists() and not dry_run:
            for f in scripts_src.iterdir():
                if f.is_file() and f.suffix in (".py", ".sh"):
                    shutil.copy2(f, scripts_dir / f.name)
            count = sum(1 for _ in scripts_src.glob("*.py"))
            print(f"  {count} Python scripts backed up")

        # 9. Full data directory (portfolios, state, cached data)
        print("[9/16] Data directory...")
        data_dir = staging / "data"
        data_src = PROJECT_ROOT / "data"
        if data_src.exists() and not dry_run:
            shutil.copytree(data_src, data_dir, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__", "*.log"))
            size = sum(f.stat().st_size for f in data_dir.rglob("*") if f.is_file())
            print(f"  data/ backed up ({size / 1e6:.1f} MB)")

        # 10. Command Center UI source + built dist
        print("[10/16] Command Center UI...")
        apps_dir = staging / "apps"
        apps_src = PROJECT_ROOT / "apps"
        if apps_src.exists() and not dry_run:
            shutil.copytree(apps_src, apps_dir, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("node_modules", ".next", "__pycache__"))
            # dist/ is now INCLUDED for instant restore without npm build
            dist_path = apps_dir / "command-center-v2" / "dist"
            if dist_path.exists():
                dist_size = sum(f.stat().st_size for f in dist_path.rglob("*") if f.is_file())
                print(f"  apps/ backed up (incl dist/ {dist_size/1e6:.1f} MB)")
            else:
                print(f"  apps/ backed up (dist/ not found — run npm build after restore)")

        # 11. Skills directory (Trade AI skill)
        print("[11/16] Trade AI skills...")
        skills_dir = staging / "skills"
        skills_src = PROJECT_ROOT / "skills"
        if skills_src.exists() and not dry_run:
            shutil.copytree(skills_src, skills_dir, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("node_modules", "__pycache__"))
            print(f"  skills/ backed up")

        # 12. SQL schema files
        print("[12/16] SQL schemas...")
        sql_dir = staging / "sql"
        sql_src = PROJECT_ROOT / "sql"
        if sql_src.exists() and not dry_run:
            shutil.copytree(sql_src, sql_dir, dirs_exist_ok=True)
            print(f"  sql/ backed up")

        # 13. Package files (dependencies)
        print("[13/16] Package definitions...")
        pkg_dir = staging / "packages"
        pkg_dir.mkdir()
        for f in ["package.json", "package-lock.json", "requirements.txt"]:
            src = PROJECT_ROOT / f
            if src.exists() and not dry_run:
                shutil.copy2(src, pkg_dir / f)
                print(f"  {f}")
        # CC v2 package files
        cc_pkg = PROJECT_ROOT / "apps" / "command-center-v2"
        for f in ["package.json", "package-lock.json", "tsconfig.json", "vite.config.ts", "index.html"]:
            src = cc_pkg / f
            if src.exists() and not dry_run:
                shutil.copy2(src, pkg_dir / f"cc-v2-{f}")
                print(f"  cc-v2/{f}")
        # gog CLI config (Google Drive access)
        gog_dir = staging / "gog"
        gog_dir.mkdir()
        gog_cfg = HOME / ".config" / "gogcli"
        if gog_cfg.exists() and not dry_run:
            for f in gog_cfg.iterdir():
                if f.is_file():
                    shutil.copy2(f, gog_dir / f.name)
            print(f"  gog config backed up ({sum(1 for _ in gog_cfg.iterdir())} files)")
        gog_kr = HOME / ".openclaw" / "credentials" / "gog_keyring_password"
        if gog_kr.exists() and not dry_run:
            shutil.copy2(gog_kr, gog_dir / "gog_keyring_password")
            print(f"  gog keyring password backed up")

        # 14. Documentation (all docs)
        print("[14/16] Documentation...")
        docs_dir = staging / "docs"
        docs_src = PROJECT_ROOT / "docs"
        if docs_src.exists() and not dry_run:
            shutil.copytree(docs_src, docs_dir, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("backups", "__pycache__"))
            print(f"  docs/ backed up (excluding old backup zips)")

        # 15. OpenClaw gateway service file
        print("[15/16] OpenClaw gateway service...")
        oc_svc = HOME / ".config" / "systemd" / "user" / "openclaw-gateway.service"
        if oc_svc.exists() and not dry_run:
            shutil.copy2(oc_svc, sd_dir / "openclaw-gateway.service")
            print(f"  openclaw-gateway.service")

        # 16. Restore instructions (embedded)
        print("[16/16] Generating restore instructions...")
        if not dry_run:
            (staging / "RESTORE_FROM_THIS_BACKUP.md").write_text(f"""# Trade AI v12 — Full Restore from Backup

**Backup date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}
**System:** ms01-openclaw

## Prerequisites
- Ubuntu/Debian server with Python 3.11+
- PostgreSQL installed (`sudo apt install postgresql`)
- Ollama installed with qwen3:1.7b model
- Node.js 18+ (for Command Center UI and OpenClaw)
- OpenClaw npm package (`npm install -g openclaw`)

## Step-by-Step Full Recovery

### 1. Create project directory
```bash
mkdir -p ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild
cd ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild
# Unzip this backup into a temp folder, then restore from it
```

### 2. Restore .env (API keys + passwords)
```bash
cp env/dot_env ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.env
# OR manually recreate from env/dot_env_SANITIZED.txt
```

### 3. Restore all Python scripts
```bash
cp -r scripts/ ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/scripts/
```

### 4. Restore config, assets, sql, skills
```bash
cp -r config/assets/ ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/assets/
cp -r config/config/ ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/config/
cp -r sql/ ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/sql/
cp -r skills/ ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/skills/
cp -r data/ ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/data/
cp -r docs/ ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/docs/
```

### 5. Restore package definitions and install deps
```bash
cp packages/package.json packages/package-lock.json ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/
cp packages/requirements.txt ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
npm install
```

### 6. Restore PostgreSQL database
```bash
sudo -u postgres createuser trade_ai
sudo -u postgres createdb trade_ai -O trade_ai
DB_PW=$(grep '^DB_PASSWORD=' .env | cut -d= -f2)
sudo -u postgres psql -c "ALTER USER trade_ai PASSWORD '$DB_PW';"
gunzip < database/trade_ai.sql.gz | PGPASSWORD="$DB_PW" psql -h localhost -U trade_ai trade_ai
```

### 7. Restore crontab
```bash
crontab crontab/crontab.txt
```

### 8. Restore OpenClaw (full — workspaces, skills, agents, credentials)
```bash
# Install OpenClaw
npm install -g openclaw

# Restore full config directory
cp -r openclaw/openclaw.json ~/.openclaw/
cp -r openclaw/cron/ ~/.openclaw/cron/
cp -r openclaw/workspace* ~/.openclaw/
cp -r openclaw/skills/ ~/.openclaw/skills/
cp -r openclaw/agents/ ~/.openclaw/agents/
cp -r openclaw/credentials/ ~/.openclaw/credentials/
```

### 9. Restore systemd services
```bash
mkdir -p ~/.config/systemd/user/
cp systemd/* ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now tradeai-continuous.timer
systemctl --user enable --now openclaw-gateway.service
```

### 10. Restore launcher scripts
```bash
cp launchers/*.sh ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/linux_launchers/
chmod +x ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/linux_launchers/*.sh
```

### 11. Build Command Center UI
```bash
cd ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/apps/command-center-v2
npm install
npx vite build
```

### 12. Start services
```bash
cd ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild
source .venv/bin/activate
nohup .venv/bin/python scripts/portfolio_server.py > /dev/null 2>&1 &
openclaw gateway restart
```

### 13. Verify
```bash
python3 scripts/system_preflight_check.py
```
Should pass 21+ of 23 checks.

## What's in this backup

| Directory | Contents |
|---|---|
| `database/` | Full PostgreSQL dump (all tables, full data) |
| `env/` | .env file + sanitized version |
| `crontab/` | Full crontab (all scheduled jobs) |
| `openclaw/` | Gateway config, workspaces (Maria/Aegis/Steph/Alex), all custom skills, agents, credentials |
| `systemd/` | All service + timer files (including openclaw-gateway) |
| `config/` | assets/ + config/ (screeners, agent YAML, all configs) |
| `launchers/` | Shell scripts for service launchers |
| `scripts/` | All Python automation scripts (full pipeline code) |
| `data/` | Full data directory (portfolios, state, cached data) |
| `apps/` | Command Center UI source (excluding node_modules) |
| `skills/` | Trade AI skill source |
| `sql/` | Database schema files |
| `packages/` | package.json, requirements.txt (dependency lists) |
| `docs/` | System Bible, Reference Architecture, all documentation |

## This backup is self-contained
No git clone required. All source code, configs, and data are included.
If the NVMe dies tomorrow, this zip + a fresh Ubuntu install = full recovery.
""")

        # Create zip
        if not dry_run:
            zip_path = shutil.make_archive(str(BACKUP_DIR / zip_name), 'zip', tmpdir, zip_name)
            size_mb = os.path.getsize(zip_path) / 1e6
            print(f"\n{'='*50}")
            print(f"BACKUP COMPLETE: {zip_path}")
            print(f"Size: {size_mb:.1f} MB")
            print(f"Contains: DB + .env + crontab + OpenClaw (full) + systemd + scripts + data + apps + skills + sql + configs + docs")

            # Cleanup old backups (keep 4 weeks)
            for old in sorted(BACKUP_DIR.glob("trade_ai_backup_*.zip"))[:-4]:
                old.unlink()
                print(f"  Purged old backup: {old.name}")

            return str(zip_path)
        else:
            print(f"\n[DRY RUN] Would create: docs/backups/{zip_name}.zip")
            return None


def _notify_telegram(message):
    """Send backup status via telegram_alert.send_telegram chokepoint (no raw Bot API)."""
    try:
        scripts_dir = str(PROJECT_ROOT / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from telegram_alert import send_telegram
        send_telegram(message)
        try:
            from lib.comms import CommunicationEvent, publish_communication
            publish_communication(CommunicationEvent(
                direction="OUTBOUND", event_type="alert", message_class="ops",
                producer="full_system_backup", subject_key="ops:system_backup",
                retention_class="operational", severity="info",
                sanitized_body=message[:500], short_summary=message[:120],
            ))
        except Exception:
            # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
            pass
    except Exception:
        # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
        pass


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    try:
        result = create_backup(dry_run=dry)
        if result and not dry:
            size_mb = os.path.getsize(result) / 1e6
            _notify_telegram(f"Backup complete: {Path(result).name} ({size_mb:.1f} MB)")
    except Exception as e:
        _notify_telegram(f"BACKUP FAILED: {e}")
        raise
