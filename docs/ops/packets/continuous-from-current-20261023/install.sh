#!/usr/bin/env bash
set -euo pipefail
packet_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$packet_dir"
sha256sum -c SHA256SUMS >&2
exec /usr/bin/python3 "$packet_dir/packet.py" install "$@"
