#!/bin/sh
# Install the no-secrets enforcement hooks. Run once after cloning. Hard rule: no credential ever reaches git.
ROOT="$(git rev-parse --show-toplevel)"
printf '#!/bin/sh\nexec python3 "%s/scripts/check_no_secrets.py"\n' "$ROOT" > "$ROOT/.git/hooks/pre-commit"
printf '#!/bin/sh\nexec python3 "%s/scripts/check_no_secrets.py" --tree\n' "$ROOT" > "$ROOT/.git/hooks/pre-push"
chmod +x "$ROOT/.git/hooks/pre-commit" "$ROOT/.git/hooks/pre-push"
echo "installed pre-commit + pre-push no-secrets hooks"
