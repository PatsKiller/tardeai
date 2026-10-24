#!/usr/bin/env bash
set -euo pipefail
packet_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec /usr/bin/python3 "$packet_dir/packet.py" check "$@"
