"""premarket_watcher per-day alert dedupe (operator 2026-10-16). Pure except the state file helpers."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


# ── per-day dedupe (operator 2026-10-16: the same SKYA 8-K was sent 12 times, every 15 min 07:01-09:46) ──────
#
# Key: symbol + filing/event id, per ET day. MATERIAL (re-alert) means one of:
#   * a filing whose event id (form + EDGAR accession, else form + file date) was not alerted today for the symbol;
#   * a StockTwits surge on a symbol with no surge alerted today, or a surge whose 2-hour post count is at least
#     SURGE_MATERIAL_RATIO x the last alerted count AND at least SURGE_MATERIAL_MIN_DELTA posts higher.
# Anything else (the same filing again, a flat or modestly higher surge) is dropped from the message; a message
# with nothing material is not sent. State: <state root>/data/runtime/premarket_watcher_sent.json (today only).
SURGE_MATERIAL_RATIO = 2.0
SURGE_MATERIAL_MIN_DELTA = 10
DEDUPE_STATE_REL = Path('data') / 'runtime' / 'premarket_watcher_sent.json'


def dedupe_state_path():
    try:
        if str(PROJECT_ROOT / "scripts") not in sys.path:
            sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from lib.canonical_store_registry import production_state_root
        return Path(production_state_root()) / DEDUPE_STATE_REL
    except Exception:
        return PROJECT_ROOT / DEDUPE_STATE_REL


def load_dedupe_state(path, day):
    try:
        doc = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {'day': day, 'symbols': {}}
    if not isinstance(doc, dict) or doc.get('day') != day:
        return {'day': day, 'symbols': {}}
    doc.setdefault('symbols', {})
    return doc


def select_material(items, state):
    """(material items, new state). Pure: never mutates ``state``."""
    symbols = {k: {'events': list(v.get('events') or []), 'surge_count': v.get('surge_count')}
               for k, v in (state.get('symbols') or {}).items()}
    out = []
    for it in items or []:
        sym = str(it.get('symbol') or '').upper()
        seen = symbols.setdefault(sym, {'events': [], 'surge_count': None})
        filings = [f for f in it.get('filings') or [] if f.get('event_id') not in seen['events']]
        surge = it.get('surge_count')
        last = seen.get('surge_count')
        surge_material = surge is not None and (
            last is None or (surge >= last * SURGE_MATERIAL_RATIO and surge - last >= SURGE_MATERIAL_MIN_DELTA))
        if not filings and not surge_material:
            continue
        for f in filings:
            if f.get('event_id'):
                seen['events'].append(f['event_id'])
        if surge_material:
            seen['surge_count'] = surge
        out.append({'symbol': sym, 'filings': filings, 'surge_count': surge if surge_material else None})
    return out, {'day': state.get('day'), 'symbols': symbols}


def render_items(items):
    blocks = []
    for it in items:
        parts = [f"PRE-MARKET: {it['symbol']}"]
        for f in it.get('filings') or []:
            parts.append(f"  SEC {f['type']}: {f['title'][:60]}")
        if it.get('surge_count') is not None:
            parts.append(f"  StockTwits: {it['surge_count']} posts/2hr")
        blocks.append('\n'.join(parts))
    return blocks


def save_dedupe_state(path, state):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=1))
    os.replace(tmp, path)
