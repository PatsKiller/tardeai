#!/usr/bin/env node
// One-shot migration (PR3, 2026-09-27): the options tooltip dictionaries in
// apps/command-center-v3/src/lib/optionsMetricTooltips.ts (context functions) and
// optionsTooltips.ts (static strings) become entries in assets/ui_metric_guide.yaml, the single
// server-supplied source of metric help. Context placeholders become {symbol}/{strike}/... so the
// frontend fills them from payload values only. Kept for provenance; the YAML is the truth now.
//   node scripts/gen_metric_guide_from_ts.mjs > /dev/stdout   (writes assets/ui_metric_guide.yaml)
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
const HERE = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(HERE, '..')
const LIB = path.join(ROOT, 'apps/command-center-v3/src/lib')
const { getOptionsMetricTooltip } = await import(path.join(LIB, 'optionsMetricTooltips.ts'))
const OT = await import(path.join(LIB, 'optionsTooltips.ts'))

// Neutral context whose values survive as placeholders in the generated text.
const CTX = { symbol: '{symbol}', strategy: 'covered_call', strike: 100, spot: 100, delta: 0.3, breakeven: 100,
  breakeven_move_pct: 0, capital_ratio_pct: 0, dte: 30, dte_bucket: 30, iv_rank: 50, iv_days: 30, iv_required_days: 30,
  premium: 1, contracts: 1, validation_label: '{validation_label}', validation_message: '{validation_message}', blocks: [] }
const KEYS = ['dte_bucket', 'strike', 'delta', 'delta_proxy', 'breakeven', 'breakeven_move_pct', 'share_capital_pct', 'premium',
  'total_debit', 'total_credit', 'max_loss', 'max_profit', 'max_gain', 'iv_rank', 'iv_history_building', 'iv', 'oi', 'volume',
  'spread_pct', 'pop', 'ev', 'edge', 'rr', 'dte', 'earnings_before_expiry', 'thesis', 'conviction', 'paper_validation',
  'live_eligible_false', 'no_live_path', 'alpaca_paper_only', 'net_debit', 'net_credit', 'pkg_slippage', 'implied_move',
  'historical_move', 'event_confidence']
const LABEL = k => k.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
const yq = s => JSON.stringify(String(s ?? ''))   // JSON strings are valid YAML scalars
const entries = {}
for (const k of KEYS) {
  const t = getOptionsMetricTooltip(k, CTX)
  // Replace the neutral numbers with placeholders where they were interpolated.
  const ph = s => String(s || '').replace(/\$100(\.00)?/g, '{strike}').replace(/\b30d\b/g, '{dte}d').replace(/\b30 days\b/g, '{dte} days')
    .replace(/\+0\.0%/g, '{breakeven_move_pct}%').replace(/\b50%\b/g, '{iv_rank}%')
  entries[`options.${k}`] = { label: LABEL(k), short: ph(t.short), definition: ph(t.more), why_it_matters: ph(t.more).split('. ')[0] + '.',
    interpretation: ph(t.watch || t.more), benchmark: '', watch: ph(t.watch || ''), warning: ph(t.warning || ''), sources: ['options_engine'] }
}
for (const [group, dict] of Object.entries(OT)) {
  if (typeof dict !== 'object' || !dict) continue
  for (const [k, text] of Object.entries(dict)) {
    if (typeof text !== 'string') continue
    // UI chrome strings (tabs, filters, buttons) are not metrics: one sentence answers all four.
    const snake = k.replace(/([a-z0-9])([A-Z])/g, '$1_$2').toLowerCase()
    entries[`options.ui.${group.toLowerCase()}.${snake}`] = { label: LABEL(snake), short: text, definition: text, why_it_matters: text, interpretation: text, benchmark: '', sources: ['options desk UI'] }
  }
}
// House metrics the redesign adds (PR1 economics / contract fields); authored, not migrated.
Object.assign(entries, {
  'options.credit_basis': { label: 'Credit basis', short: 'Whether the credit shown is executable (sell the short leg at its bid, buy the long leg at its ask) or a leg midpoint.', definition: 'A credit spread has two quotes. The executable credit is short bid minus long ask, the credit a marketable limit at the displayed quotes would receive. The midpoint credit averages each leg and is not a fill.', why_it_matters: 'The desk once advertised the midpoint ($8.10 on DELL) while crossing the quotes paid $6.35; on ETON the midpoint was a credit and the executable price a debit.', interpretation: 'Use the executable figure for max profit, max loss and breakeven; treat the midpoint as an upper bound.', benchmark: 'Haircut from mid to executable under 15% of the mid on liquid names; over 25% means the quote is not tradeable.', watch: 'A closed-market quote inflates the haircut; revalidate at the open.', sources: ['options_economics.spread_quote'] },
  'options.loss_to_credit_ratio': { label: 'Loss : credit', short: 'Max loss divided by the credit received.', definition: 'For a defined-risk credit spread, (width − credit) ÷ credit.', why_it_matters: 'It is the number of winning trades one full loss erases.', interpretation: 'Above 3 needs a probability of profit well over 75% to break even over many trades.', benchmark: 'Desk floor: return on risk ≥ 25% (ratio ≤ 4).', sources: ['options_cio_review.build_facts'] },
  'options.annualized_yield_on_strike_pct': { label: 'Annualized yield on strike', short: 'Credit ÷ short strike, annualized by days to expiry.', definition: 'credit / short strike × 365 / dte. One of several yield denominators; not an expected return.', why_it_matters: 'The denominator changes the answer: on width or on max loss the same trade reads very differently.', interpretation: 'Compare like with like; the expected P/L in the economics block is the model estimate.', benchmark: '', sources: ['options_cio_review.build_facts'] },
  'options.hedged_max_loss_from_mark': { label: 'Max loss (hedged shares)', short: 'What the insured shares can lose from today\'s mark, premium included, before the put floor holds.', definition: '(mark − (strike − premium)) × insured shares.', why_it_matters: 'A protective put card is insurance on held stock; the put\'s own premium is not the position\'s max loss.', interpretation: 'Compare with the loss to the floor from your cost basis, which is usually larger.', benchmark: '', watch: 'Shares beyond the insured count are unhedged.', sources: ['options_economics'] },
  'options.floor_value': { label: 'Floor after premium', short: 'Value the insured shares cannot fall below, net of the premium paid.', definition: '(strike − premium) × insured shares.', why_it_matters: 'It is the number the insurance actually guarantees.', interpretation: 'Read it against your cost basis, not only the mark.', benchmark: '', sources: ['options_economics'] },
  'sentiment.score': { label: 'Sentiment score', short: 'Quick read of the house view on this name, 0 to 100.', definition: 'A server-computed blend of the thesis stance, the latest CIO decision and research freshness. The frontend never computes it.', why_it_matters: 'It is the one-glance answer before the details.', interpretation: 'Above 65 leans positive, 35 to 65 is watch, below 35 leans risk; the tone chip carries the same meaning.', benchmark: '', sources: ['ticker_cio_view'] },
  'cio.decision': { label: 'CIO decision', short: 'The latest recorded CIO review outcome for this idea.', definition: 'APPROVE, MONITOR_ONLY, MORE_RESEARCH or REJECT, with confidence, from the options lifecycle review.', why_it_matters: 'An order needs APPROVE; MONITOR_ONLY is not approval.', interpretation: 'Read the reasoning and concerns on the card; a decision older than the recheck window is re-reviewed.', benchmark: '', sources: ['options_thesis_lifecycle'] },
  'cio.conviction': { label: 'Conviction', short: 'How strongly the house thesis takes a position.', definition: 'Thesis confidence and stance from the symbol thesis on file.', why_it_matters: 'Low conviction with strong fundamentals means the evidence is thin, not that the name is bad.', interpretation: 'Pair with the research count; THIN theses are marked.', benchmark: '', sources: ['symbol_thesis'] },
  'watch.rr': { label: 'Reward : risk', short: 'Distance to target divided by distance to stop.', definition: 'From the re-entry or watch plan levels.', why_it_matters: 'Below 1 the plan risks more than it can make.', interpretation: 'The desk floor is 0.3 for premium-selling, higher for directional entries.', benchmark: '', sources: ['watch desk'] },
  'position.unrealized_pct': { label: 'Unrealized P/L %', short: 'Gain or loss versus cost basis, before fees and tax.', definition: '(mark − basis) ÷ basis.', why_it_matters: 'It is the operator\'s number; the mark-based figures on cards are not.', interpretation: 'Compare with the plan\'s stop and target distances.', benchmark: '', sources: ['holdings snapshot'] },
  'freshness.as_of': { label: 'As of', short: 'When this number was last computed, in ET.', definition: 'Every operator-facing field carries its own as_of and provenance (AGENTS §13).', why_it_matters: 'A stale number can look current.', interpretation: 'Chips turn to watch when older than the surface\'s freshness rule.', benchmark: '', sources: ['surface freshness'] },
})
const lines = ['# Metric guide (PR3, 2026-09-27) — THE source of every metric tooltip in the Command Center.',
  '# Served at GET /api/v2/ui/metric-guide; keys are generated into',
  '# apps/command-center-v3/src/lib/metricGuide.keys.generated.ts (scripts/gen_metric_guide_keys.mjs).',
  '# Fields: label, short, definition, why_it_matters, interpretation, benchmark, watch, warning, unit, sources.',
  '# {placeholders} are filled by the frontend from values already in the payload (AGENTS §13).',
  'version: 1', `as_of: "${new Date().toISOString().slice(0, 10)}"`, 'entries:']
for (const k of Object.keys(entries).sort()) {
  const e = entries[k]
  lines.push(`  ${k}:`)
  for (const f of ['label', 'short', 'definition', 'why_it_matters', 'interpretation', 'benchmark', 'watch', 'warning', 'unit']) {
    if (e[f] !== undefined && e[f] !== '') lines.push(`    ${f}: ${yq(e[f])}`)
  }
  if (e.sources?.length) lines.push(`    sources: [${e.sources.map(yq).join(', ')}]`)
}
fs.mkdirSync(path.join(ROOT, 'assets'), { recursive: true })
fs.writeFileSync(path.join(ROOT, 'assets/ui_metric_guide.yaml'), lines.join('\n') + '\n')
console.log(`wrote assets/ui_metric_guide.yaml with ${Object.keys(entries).length} entries`)
