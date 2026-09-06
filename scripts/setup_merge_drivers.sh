#!/usr/bin/env bash
# Register the regenerate merge driver. Per-clone: git does not ship driver
# definitions in the repo, only the .gitattributes that reference them.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
git config merge.regenerate.name "recompute generated artifacts instead of line-merging"
git config merge.regenerate.driver "scripts/git_merge_regenerate.sh %O %A %B %L %P"
echo "  merge driver 'regenerate' registered for this clone"
echo "  after any merge touching generated files, run:"
echo "    bash scripts/regenerate_generated_files.sh"
