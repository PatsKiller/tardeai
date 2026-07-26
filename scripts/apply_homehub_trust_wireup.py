#!/usr/bin/env python3
"""Idempotent HomeHub wire-up for home-trust helpers.

Usage (from repo root, on grok/home-trust-harden-20260726 or main after merge):
    .venv/bin/python scripts/apply_homehub_trust_wireup.py
    .venv/bin/python scripts/apply_homehub_trust_wireup.py --check
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "apps/command-center-v3/src/pages/HomeHub.tsx"

REPLACEMENTS: list[tuple[str, str]] = [
    (
        "import { plain, plainAlert, runLabel, thresholdSentence } from '../lib/homeLabels'",
        "import { plain, plainAlert, runLabel, thresholdSentence, isScanStale } from '../lib/homeLabels'\n"
        "import { setupStateLabel, HermesGatewayLine, AiIntelligenceBriefing, EquityThinNote } from '../components/home/HomeTrustRender'",
    ),
    (
        "  const avoidCount = tradeAi?.avoid_count ?? 0\n  const journalPnl = journal?.total_pnl",
        "  const avoidCount = tradeAi?.avoid_count ?? 0\n"
        "  const scanStale = isScanStale(tradeAi?.run_date)\n"
        "  const setupLbl = setupStateLabel({ go: goCount, wait: waitCount, avoid: avoidCount, runLabel: tradeAi?.run_label, runDate: tradeAi?.run_date })\n"
        "  const journalPnl = journal?.total_pnl",
    ),
    (
        "{ label: 'SETUPS', value: `${goCount}/${waitCount}/${avoidCount}`, sub: 'GO/WAIT/NO · latest run', color: goCount > 0 ? '#22c55e' : 'var(--text3)',",
        "{ label: 'SETUPS', value: scanStale ? 'STALE' : `${goCount}/${waitCount}/${avoidCount}`, sub: scanStale ? setupLbl.value : 'GO/WAIT/NO · latest run', color: setupLbl.color,",
    ),
    (
        "{ label: 'Setup State', value: `${goCount} GO · ${waitCount} WAIT · ${avoidCount} NO GO`, color: goCount > 0 ? '#22c55e' : 'var(--text2)', loading: tradeAiLoading },",
        "{ label: 'Setup State', value: setupLbl.value, color: setupLbl.color, loading: tradeAiLoading },",
    ),
    (
        "                    <Area type=\"monotone\" dataKey=\"value\" stroke=\"#60a5fa\" fill=\"url(#eqGrad)\" strokeWidth={2} />\n                  </AreaChart>\n                </ResponsiveContainer>\n              )}",
        "                    <Area type=\"monotone\" dataKey=\"value\" stroke=\"#60a5fa\" fill=\"url(#eqGrad)\" strokeWidth={2} />\n"
        "                  </AreaChart>\n"
        "                </ResponsiveContainer>\n"
        "                <EquityThinNote days={equityCurve.length} />\n"
        "              )}",
    ),
    (
        "                  <Line><span>Gateway</span><span style={{ color: h.gateway_status === 'ok' ? '#22c55e' : '#ef4444' }}>{h.gateway_status ?? '—'}</span></Line>",
        "                  <HermesGatewayLine status={h.gateway_status} loopActive={h.autonomous_loop_active} />",
    ),
    (
        "          {cmd.llm_intelligence && (\n            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16, marginTop: 14 }}>\n"
        "              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>AI Intelligence Briefing</div>\n"
        "              {[['Portfolio Risk', cmd.llm_intelligence.portfolio_risk], ['Morning Synthesis', cmd.llm_intelligence.morning_synthesis]].filter(([, v]) => v).map(([k, v]: any) => (\n"
        "                <div key={k} style={{ marginBottom: 10 }}>\n"
        "                  <div style={{ fontSize: 9, color: '#60a5fa', textTransform: 'uppercase', marginBottom: 3 }}>{k}</div>\n"
        "                  {/* briefings are stored as JSON {\"content\": \"...\"} — render the prose, never raw JSON */}\n"
        "                  <div style={{ fontSize: 10, color: 'var(--text2)', lineHeight: 1.55, whiteSpace: 'pre-wrap' }}>{(() => {\n"
        "                    let x: any = v\n"
        "                    if (typeof x === 'string') { try { x = JSON.parse(x) } catch { return x } }\n"
        "                    return x?.content ?? x?.summary ?? x?.text ?? String(v)\n"
        "                  })()}</div>\n"
        "                </div>\n"
        "              ))}\n"
        "              <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 6 }}>Source: /api/v2/command → llm_intelligence (gemma3:12b daily)</div>\n"
        "            </div>\n"
        "          )}",
        "          {cmd.llm_intelligence && <AiIntelligenceBriefing llm={cmd.llm_intelligence} />}",
    ),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="Exit 0 if already wired")
    args = ap.parse_args()
    text = TARGET.read_text()
    if "HomeTrustRender" in text and "setupLbl" in text and "AiIntelligenceBriefing" in text:
        print("[ok] HomeHub already wired to HomeTrustRender")
        return 0
    if args.check:
        print("[missing] HomeHub not yet wired")
        return 1
    orig = text
    for old, new in REPLACEMENTS:
        if old not in text:
            print(f"[warn] pattern not found (may already be applied or file drifted):\n  {old[:80]}...")
            continue
        text = text.replace(old, new, 1)
    if text == orig:
        print("[fail] no replacements applied")
        return 2
    TARGET.write_text(text)
    print(f"[ok] wired {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
