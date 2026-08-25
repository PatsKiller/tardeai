#!/bin/sh
# Install the no-secrets enforcement hooks. Run once after cloning. Hard rule: no credential ever reaches git.
# Prefer the tracked AI work-policy hooks (secrets + remote-sync gate) when present.
ROOT="$(git rev-parse --show-toplevel)"
if [ -x "$ROOT/scripts/install_ai_work_policy.sh" ] && [ -x "$ROOT/.githooks/pre-push" ]; then
  exec "$ROOT/scripts/install_ai_work_policy.sh"
fi
printf '#!/bin/sh\nexec python3 "%s/scripts/check_no_secrets.py"\n' "$ROOT" > "$ROOT/.git/hooks/pre-commit"
printf '#!/bin/sh\nexec python3 "%s/scripts/check_no_secrets.py" --tree\n' "$ROOT" > "$ROOT/.git/hooks/pre-push"
chmod +x "$ROOT/.git/hooks/pre-commit" "$ROOT/.git/hooks/pre-push"
echo "installed pre-commit + pre-push no-secrets hooks"
