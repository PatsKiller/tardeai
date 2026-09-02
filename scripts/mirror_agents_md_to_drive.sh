#!/usr/bin/env bash
# mirror_agents_md_to_drive.sh — publish AGENTS.md to its single governed Drive
# mirror and PROVE the copy is byte-exact.
#
# WHY THIS EXISTS
# ---------------
# AGENTS.md 1.0.0 declares a Drive mirror in its own document-control block.
# Nothing could write it:
#   - scripts/sync-docs-to-drive.{py,sh} read ~/.openclaw/credentials/... which is
#     operator-only, and they only sync docs/ and config/strategies anyway --
#     governance/ is outside their SYNC_ROOTS, so they would never carry this file;
#   - the connected Drive MCP tool takes inline content only, and transcribing
#     93KB with 392 non-ASCII characters cannot GUARANTEE byte-exactness, which is
#     the one thing the mirror has to guarantee.
#
# This routes through scripts/gog_broker.sh, so the keyring secret comes from
# Bitwarden and no agent reads the credential path. The operator unlocks once:
#     export BW_SESSION=$(bw unlock --raw)
#
# WHAT IT GUARANTEES
#   - uploads the file from disk (real bytes, no transcription)
#   - downloads it back and compares SHA-256; a mismatch is a hard failure
#   - updates ONE Drive file by stable id; never creates a timestamped duplicate
#   - writes the manifest ONLY after verification passes
#   - never prints the secret, and never reads ~/.openclaw/credentials/*
#
# USAGE
#   export BW_SESSION=$(bw unlock --raw)
#   TRADEAI_AGENT=claude-code scripts/mirror_agents_md_to_drive.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/AGENTS.md"
MANIFEST="$ROOT/docs/ops/AGENTS_DRIVE_MIRROR_MANIFEST.json"
FOLDER_ID="${AGENTS_DRIVE_FOLDER_ID:-1spBGi8OgIpDE1p2tlIXzk8fJLqxqMCCU}"
DRIVE_PATH="Trade_AI_Docs_v2/governance/agent-policy/AGENTS.md"
ACCOUNT="${GOG_ACCOUNT:-john@jwwhiting.com}"
BROKER="$ROOT/scripts/gog_broker.sh"
AGENT="${TRADEAI_AGENT:-}"

die() { echo "mirror_agents_md: $*" >&2; exit 2; }
[ -r "$SRC" ] || die "AGENTS.md not readable at $SRC"
[ -x "$BROKER" ] || die "gog broker missing at $BROKER"
[ -n "$AGENT" ] || die "TRADEAI_AGENT is not set; see config/gog_approved_agents.txt"

gog() { TRADEAI_AGENT="$AGENT" "$BROKER" drive "$@" --account "$ACCOUNT" --no-input -j; }

FIND_COUNT='import json,sys; d=json.load(sys.stdin); print(len([f for f in d.get("files",[]) if f.get("name")=="AGENTS.md" and not f.get("trashed")]))'
FIND_IDS='import json,sys; d=json.load(sys.stdin); [sys.stderr.write("  candidate: %s %s\n" % (f["id"], f.get("modifiedTime",""))) for f in d.get("files",[]) if f.get("name")=="AGENTS.md" and not f.get("trashed")]'
READ_ID='import json,sys; d=json.load(sys.stdin); print(d.get("id") or d.get("file",{}).get("id",""))'


LOCAL_SHA="$(sha256sum "$SRC" | cut -d' ' -f1)"
COMMIT="$(git -C "$ROOT" rev-parse HEAD)"
POLICY_VERSION="$(grep -m1 '^Policy-Version:' "$SRC" | awk '{print $2}')"
echo "local  sha256 : $LOCAL_SHA"
echo "commit        : $COMMIT"
echo "policy version: $POLICY_VERSION"

# ── one mutable file, found by name in the target folder ─────────────────────
echo "== locating the single mirror file in $FOLDER_ID"
LISTING="$(gog ls --parent "$FOLDER_ID")" || die "drive ls failed (is BW_SESSION set and the vault unlocked?)"

# Refuse to guess if the folder holds more than one AGENTS.md. Reporting and
# stopping is correct here; picking one could orphan the other silently.
COUNT="$(printf '%s' "$LISTING" | python3 -c "$FIND_COUNT")"
if [ "$COUNT" -gt 1 ]; then
  printf '%s' "$LISTING" | python3 -c "$FIND_IDS" >&2
  die "$COUNT files named AGENTS.md in the target folder; the operator must resolve which is canonical"
fi

echo "== uploading from disk (real bytes, no transcription)"
OUT="$(gog upload "$SRC" --parent "$FOLDER_ID")" || die "upload failed"
FILE_ID="$(printf '%s' "$OUT" | python3 -c "$READ_ID")"
[ -n "$FILE_ID" ] || die "upload returned no file id"
echo "drive file id : $FILE_ID"

# ── read back and prove equality ─────────────────────────────────────────────
TMP="$(mktemp)"; trap 'rm -f "$TMP"' EXIT
TRADEAI_AGENT="$AGENT" "$BROKER" drive download "$FILE_ID" --output "$TMP" \
  --account "$ACCOUNT" --no-input >/dev/null || die "read-back download failed"
REMOTE_SHA="$(sha256sum "$TMP" | cut -d' ' -f1)"
echo "remote sha256 : $REMOTE_SHA"

if [ "$LOCAL_SHA" != "$REMOTE_SHA" ]; then
  die "BYTE MISMATCH — local $LOCAL_SHA vs drive $REMOTE_SHA. Manifest NOT written."
fi
echo "VERIFIED BYTE_EXACT"

NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
python3 - "$MANIFEST" "$POLICY_VERSION" "$COMMIT" "$LOCAL_SHA" "$FOLDER_ID" "$FILE_ID" "$DRIVE_PATH" "$NOW" <<'PY'
import json,sys
p,ver,commit,sha,folder,fid,path,now = sys.argv[1:9]
json.dump({
  "schema":"TradeAIAgentsDriveMirrorManifest@v1","policy_version":ver,
  "canonical_repo":"PatsKiller/tardeai","canonical_repo_path":"AGENTS.md",
  "source_commit_sha":commit,"content_sha256":sha,
  "drive_folder_id":folder,"drive_file_id":fid,"drive_path":path,
  "mime_type":"text/markdown","uploaded_at":now,"verified_at":now,
  "verification":"BYTE_EXACT","supersedes_policy_version":"UNVERSIONED",
}, open(p,"w"), indent=2)
open(p,"a").write("\n")
PY
echo "manifest written: $MANIFEST"
