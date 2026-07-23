# Moomoo Installation Manifest — Stage 5

Isolated, lab-scoped, reproducible. Nothing in the repository .venv, requirements.txt,
system Python, or any production service/package was touched.

## Pins (all verified before install)
| Component | Pin | Source | Hash |
|---|---|---|---|
| moomoo-api | 10.9.6908 | PyPI sdist | sha256 6df0370e…0304 — **VERIFIED == launcher pin** |
| pyarrow | 25.0.0 | PyPI | pip-installed into isolated venv |
| OpenD | 10.9.6908 Ubuntu command-line | official CDN softwaredownload.futustatic.com (resolved from www.moomoo.com/download/fetch-lasted-link) | OFFICIAL_CHECKSUM_STATUS: UNAVAILABLE → LOCAL_ARCHIVE_SHA256 e60713be…c512b619 (466,858,781 bytes) |
| OpenD 10.9.6918 | newer | official | CANDIDATE ONLY — not installed (no silent upgrade) |

## Paths
- OpenD: `~/.local/opt/trade-ai-lab/moomoo/opend/10.9.6908` + `current` symlink (atomic)
- SDK venv: `~/.local/venvs/trade-ai-lab/moomoo-api/10.9.6908` + `current`
- state: `~/.local/state/trade-ai-lab/moomoo/` (INSTALL_MANIFEST.json, lockfiles 0600)
- replay: `~/.local/share/trade-ai-lab/moomoo/replay/` (0700)
- downloads: `~/.cache/trade-ai-lab/moomoo/downloads/`
- runtime tmpfs: `$XDG_RUNTIME_DIR/trade-ai-lab/moomoo/` (0700)

## Archive safety (all passed)
418 members · 0 traversal/absolute-path entries · 0 setuid/setgid · OpenD is ELF x86-64 ·
official XML template + AppData.dat present · extracted to a temp staging dir then atomically
moved into the versioned path (never overwriting another version) · GUI AppImage deliberately
NOT installed (command-line ruling).

## Interpreter
Python 3.14.4 (highest and only installed; SDK import → `10.09.6908`, pyarrow → `25.0.0`).
System Python cannot import moomoo (isolation verified); the isolated venv can.

## Lockfiles (in ~/.local/state/trade-ai-lab/moomoo/)
requirements-stage5.lock (hash-pinned) · pip-freeze-stage5.txt · INSTALL_MANIFEST.json
