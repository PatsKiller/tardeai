#!/usr/bin/env python3
"""Read-only WP-34 design evidence validator: paths, pinned source anchors and registered phases.

No config values, credentials, live endpoints, runtime writer calls or apply operations.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

PACKET = Path(__file__).resolve().parent
ROOT = PACKET.parents[3]


def validate() -> dict:
    inventory = json.loads((PACKET / 'inventory.json').read_text())
    census = json.loads((PACKET / 'config-path-census.json').read_text())
    tracked = subprocess.check_output(['git', '-C', str(ROOT), 'ls-files', 'config'], text=True).splitlines()
    rows = census['rows']
    assert sorted(tracked) == sorted(r['path'] for r in rows)
    assert len(rows) == len({r['path'] for r in rows}) == 1110
    assert sum(r['path'].count('/') == 1 for r in rows) == 248
    families = {f['id']: f for f in inventory['families']}
    counts = Counter(r['family_id'] for r in rows)
    assert dict(counts) == inventory['counts']['paths_by_family']
    seen = []
    anchors = literals = 0
    for family in families.values():
        seen.extend(family['paths'])
        for field in ('current_writer', 'verified_reader', 'existing_modal_or_gap', 'proposed_modal',
                      'proposed_authority', 'validation', 'preview_and_readback'):
            assert family[field], (family['id'], field)
        for ref in family['evidence']:
            source = ROOT / ref['path']
            assert hashlib.sha256(source.read_bytes()).hexdigest() == ref['source_sha256'], ref
            assert ref['anchor'] in source.read_text().splitlines()[ref['line'] - 1], ref
            anchors += 1
    assert sorted(seen) == sorted(tracked)
    sources = {}
    for row in rows:
        assert row['family_id'] in families
        assert any(fnmatch.fnmatchcase(row['path'][7:], p) for p in families[row['family_id']]['patterns'])
        assert row['content_read_for_census'] is False
        assert len(row['source_references']) == row['source_reference_count']
        for ref in row['source_references']:
            lines = sources.setdefault(ref['path'], None)
            if lines is None:
                lines = (ROOT / ref['path']).read_text().splitlines()
                sources[ref['path']] = lines
            assert ref['literal'] in lines[ref['line'] - 1], ref
            literals += 1
    specs = inventory['existing_settings_catalogue_public_spec']
    assert len(specs) == 4 and sum(s['wired'] is True for s in specs) == 2
    assert {s['key'] for s in specs if s['wired'] is False} == {
        'active_trader_alerts.min_buy_ratio', 'active_trader_alerts.max_spread_bps'}
    sys.path.insert(0, str(ROOT))
    from scripts.lib.design_registry import parse_design
    name = inventory['design_id']
    design = parse_design((ROOT / 'docs/designs' / (name + '.md')).read_text(), stem=name)
    assert design['status'] == 'PROPOSED'
    assert [p['id'] for p in design['phases']] == [name + '-P1', name + '-P2', name + '-P3']
    html = (PACKET / 'modal-mockup.html').read_text()
    assert 'NonOperativeModalExample@v1' in html and 'id="apply" type="button" disabled' in html
    assert not re.search(r'\b(fetch|XMLHttpRequest|WebSocket|sendBeacon)\s*\(', html)
    return {'status': 'PASS', 'base_sha': inventory['base_sha'], 'config_paths': len(rows),
            'top_level_paths': 248, 'populated_families': len(counts), 'family_source_anchors': anchors,
            'literal_reference_anchors': literals, 'source_reference_files': len(sources),
            'settings_catalogue': {'keys': 4, 'wired': 2, 'unwired': 2},
            'design_status': 'PROPOSED', 'runtime_writer_calls_or_effects': 0, 'live_server_requests': 0}


if __name__ == '__main__':
    print(json.dumps(validate(), indent=2))
