#!/usr/bin/env bash
# bare_metal_recover.sh — rebuild Trade AI (+ companion apps) from the offsite backups.
# Companion to docs/runbooks/BARE_METAL_RECOVERY.md (2026-07-17 audit).
#
# PARAMETERIZED: target directories, DB name/user, dashboard FQDN/hostname, repo URL and
# backup source are all choosable — nothing assumes /home/johnclaw or the old hostname.
# Absolute paths embedded in the restored crontab + systemd units are REWRITTEN from the
# old root to your chosen root; TAILSCALE_HOSTNAME in .env is rewritten to your FQDN.
#
# Usage (fresh box, after installing: git python3 gnupg postgresql curl node):
#   bash bare_metal_recover.sh \
#     --backup-dir  ~/restore-staging       # dir holding the downloaded *.gpg files
#     --pass-file   ~/env_data_backup.pass  # THE passphrase (from your password manager!)
#     [--project-dir "$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild"]
#     [--repo-url    git@github.com:PatsKiller/tardeai.git]
#     [--db-name trade_ai] [--db-user trade_ai]
#     [--fqdn <tailscale-or-dns-name>]      # rewrites TAILSCALE_HOSTNAME in .env
#     [--old-root /home/johnclaw]           # root embedded in the backed-up crontab/units
#     [--phases fetch,code,db,secrets,wiring,llm,verify]   # default: all
#     [--dry-run]
#
# Get the .gpg files first (browser: Google Drive folder "Trade_AI_Backups", or gog CLI
# restored from ops_backup). You need the NEWEST of: env, data, ops, apps, memory, db.
set -euo pipefail

PROJECT_DIR="$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
REPO_URL="git@github.com:PatsKiller/tardeai.git"
NYC_REPO_URL="git@github.com:PatsKiller/nyc-dof-auction.git"
DB_NAME="trade_ai"; DB_USER="trade_ai"
FQDN=""; OLD_ROOT="/home/johnclaw"
BACKUP_DIR=""; PASS_FILE=""
PHASES="fetch,code,db,secrets,wiring,llm,verify"
DRY=0

while [ $# -gt 0 ]; do
  case "$1" in
    --project-dir) PROJECT_DIR="$2"; shift 2 ;;
    --repo-url)    REPO_URL="$2"; shift 2 ;;
    --db-name)     DB_NAME="$2"; shift 2 ;;
    --db-user)     DB_USER="$2"; shift 2 ;;
    --fqdn)        FQDN="$2"; shift 2 ;;
    --old-root)    OLD_ROOT="$2"; shift 2 ;;
    --backup-dir)  BACKUP_DIR="$2"; shift 2 ;;
    --pass-file)   PASS_FILE="$2"; shift 2 ;;
    --phases)      PHASES="$2"; shift 2 ;;
    --dry-run)     DRY=1; shift ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

# Path rewrites for restored crontab/units: the OLD box embedded OLD_ROOT (home) and
# OLD_PROJ (project) absolute paths. Map both onto this box's choices.
NEW_ROOT="$HOME"
OLD_PROJ_DEFAULT="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
STAGE="${BACKUP_DIR:-$HOME/restore-staging}"
run() { if [ "$DRY" = 1 ]; then echo "DRY: $*"; else eval "$*"; fi }
phase_on() { case ",$PHASES," in *",$1,"*) return 0 ;; *) return 1 ;; esac; }
say() { echo ""; echo "━━━ $* ━━━"; }

newest() { ls -1 "$STAGE"/${1}_*.gpg 2>/dev/null | sort | tail -1; }
decrypt() { # decrypt <family> <dest-cmd...>  (streams tar; db streams gz)
  local fam="$1"; shift
  local f; f="$(newest "$fam")"
  [ -n "$f" ] || { echo "MISSING: no ${fam}_*.gpg in $STAGE" >&2; return 1; }
  echo "  using $(basename "$f")"
  if [ "$DRY" = 1 ]; then echo "DRY: gpg -d $f | $*"; else
    gpg --batch --pinentry-mode loopback --passphrase-file "$PASS_FILE" -d "$f" | "$@"
  fi
}

say "PREFLIGHT"
[ -n "$PASS_FILE" ] && [ -f "$PASS_FILE" ] || { echo "FATAL: --pass-file missing. This is the gpg passphrase from your PASSWORD MANAGER — without it the backups are unreadable." >&2; exit 1; }
for t in git python3 gpg psql tar node npm; do
  command -v "$t" >/dev/null || { echo "FATAL: '$t' not installed (see runbook step 3)" >&2; exit 1; }
done
echo "project-dir: $PROJECT_DIR"
echo "db: $DB_NAME/$DB_USER · fqdn: ${FQDN:-<keep from backup>} · old-root→new-root: $OLD_ROOT → $NEW_ROOT"
echo "backups: $STAGE · phases: $PHASES · dry-run: $DRY"

if phase_on fetch; then
  say "PHASE fetch — verify staged backups"
  mkdir -p "$STAGE"
  ok=1
  for fam in env_backup data_backup ops_backup apps_backup memory_backup db_backup; do
    f="$(newest "$fam")"
    if [ -n "$f" ]; then echo "  ✓ $fam: $(basename "$f")"; else echo "  ✗ $fam: MISSING — download from Drive folder 'Trade_AI_Backups'"; ok=0; fi
  done
  [ "$ok" = 1 ] || { echo "Stage all six families into $STAGE, then re-run." >&2; exit 1; }
fi

if phase_on code; then
  say "PHASE code — clone + build"
  if [ -e "$PROJECT_DIR/.git" ]; then echo "  repo exists — skipping clone"; else
    run "mkdir -p '$(dirname "$PROJECT_DIR")' && git clone '$REPO_URL' '$PROJECT_DIR'"
  fi
  run "cd '$PROJECT_DIR' && python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt"
  run "cd '$PROJECT_DIR/apps/command-center-v3' && npm ci --silent && npm run build"
  if [ ! -e "$NEW_ROOT/nyc-dof-auction/.git" ]; then
    run "git clone '$NYC_REPO_URL' '$NEW_ROOT/nyc-dof-auction' || echo '  (nyc-dof-auction clone failed — non-fatal)'"
  fi
fi

if phase_on db; then
  say "PHASE db — restore PostgreSQL"
  echo "  (needs: postgres server running; role password comes from restored .env after 'secrets' —"
  echo "   run secrets first if role does not exist yet, then re-run --phases db)"
  run "sudo -u postgres psql -tc \"SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'\" | grep -q 1 || sudo -u postgres psql -c \"CREATE ROLE $DB_USER LOGIN PASSWORD 'CHANGE_ME_FROM_ENV'\""
  run "sudo -u postgres psql -tc \"SELECT 1 FROM pg_database WHERE datname='$DB_NAME'\" | grep -q 1 || sudo -u postgres createdb -O '$DB_USER' '$DB_NAME'"
  echo "  restoring newest dump (this can take a while)…"
  decrypt db_backup bash -c "gunzip -c | psql -U '$DB_USER' -h localhost '$DB_NAME' -q"
  echo "  re-apply role guards per docs/runbooks/DB_HANG_PREVENTION.md (lock/statement/idle timeouts)"
fi

if phase_on secrets; then
  say "PHASE secrets — .env, data/, apps, memory, ops staging"
  decrypt env_backup    tar xzf - -C "$PROJECT_DIR"
  decrypt data_backup   tar xzf - -C "$PROJECT_DIR"
  decrypt apps_backup   tar xzf - -C "$HOME"
  decrypt memory_backup tar xzf - -C "$HOME"
  run "mkdir -p '$STAGE/ops' " ; decrypt ops_backup tar xzf - -C "$STAGE/ops"
  if [ -n "$FQDN" ]; then
    run "sed -i 's|^TAILSCALE_HOSTNAME=.*|TAILSCALE_HOSTNAME=$FQDN|' '$PROJECT_DIR/.env'"
    echo "  TAILSCALE_HOSTNAME → $FQDN (review FRESHNESS_HEARTBEAT_PING_URL and any other URL keys manually)"
  fi
  run "cp '$STAGE/ops/ops_state/pgpass' '$HOME/.pgpass' 2>/dev/null && chmod 600 '$HOME/.pgpass' || true"
  run "mkdir -p '$HOME/.config/gogcli' && cp -r '$STAGE/ops/ops_state/gogcli/.' '$HOME/.config/gogcli/' 2>/dev/null || true"
fi

if phase_on wiring; then
  say "PHASE wiring — crontab + systemd units (with $OLD_ROOT → $NEW_ROOT rewrite)"
  OPS="$STAGE/ops/ops_state"
  [ -f "$OPS/crontab.txt" ] || { echo "FATAL: run 'secrets' phase first (ops staging missing)" >&2; exit 1; }
  # project path first (more specific), then remaining home-root references
  run "sed -e 's|$OLD_PROJ_DEFAULT|$PROJECT_DIR|g' -e 's|$OLD_ROOT|$NEW_ROOT|g' '$OPS/crontab.txt' > '$OPS/crontab.rewritten.txt'"
  run "crontab '$OPS/crontab.rewritten.txt'"
  run "mkdir -p '$HOME/.config/systemd/user'"
  if [ "$DRY" = 1 ]; then echo "DRY: rewrite+install $(ls "$OPS/systemd_user" 2>/dev/null | wc -l) unit files"; else
    for u in "$OPS/systemd_user"/*; do
      [ -f "$u" ] || continue
      sed -e "s|$OLD_PROJ_DEFAULT|$PROJECT_DIR|g" -e "s|$OLD_ROOT|$NEW_ROOT|g" "$u" > "$HOME/.config/systemd/user/$(basename "$u")"
    done
  fi
  run "systemctl --user daemon-reload"
  run "loginctl enable-linger \"\$(whoami)\" 2>/dev/null || sudo loginctl enable-linger \"\$(whoami)\""
  run "systemctl --user enable --now portfolio-server.service"
  run "for t in \$(ls '$HOME/.config/systemd/user' | grep -E '\\.timer\$'); do systemctl --user enable --now \"\$t\"; done"
fi

if phase_on llm; then
  say "PHASE llm — ollama models"
  if [ -f "$STAGE/ops/ops_state/manifests/ollama_models.txt" ]; then
    if [ "$DRY" = 1 ]; then echo "DRY: ollama pull each model in manifest"; else
      awk 'NR>1 {print $1}' "$STAGE/ops/ops_state/manifests/ollama_models.txt" | while read -r m; do
        [ -n "$m" ] && ollama pull "$m" || true
      done
    fi
  else echo "  no ollama manifest staged — skip"; fi
fi

if phase_on verify; then
  say "PHASE verify"
  run "sleep 5; curl -s -o /dev/null -w 'health: %{http_code}\\n' http://localhost:7777/api/v2/health"
  run "cd '$PROJECT_DIR' && .venv/bin/python scripts/health_agent.py | tail -1 || true"
  cat <<'EOM'

  MANUAL RE-AUTH CHECKLIST (no backup can restore these):
    1. Schwab OAuth : .venv/bin/python scripts/schwab_token_manager.py reauth-url <acct>
                      (open URL, complete login; auth is AUTO afterwards — never hand-edit)
    2. Tailscale    : tailscale up  (re-authorize node; update --fqdn if the name changed)
    3. Grok/ChatGPT free OAuth lanes (:8645/:8646): one manual login each; keepalive cron maintains
    4. Confirm tonight's 02:30 backup cadence fires (journalctl --user -u tradeai-portfolio-backup-cadence)
EOM
fi

say "DONE (phases: $PHASES$( [ "$DRY" = 1 ] && echo ' · DRY-RUN — nothing changed'))"
