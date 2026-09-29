/** Entry alerts lane (2026-09-28) — the entry-state packets behind the Telegram BUY_READY /
 *  ENTRY_NEAR pages, on the Re-Entry page where the operator looks for them. Reads
 *  GET /api/v2/buy-ready/packets (BuyReadyPacketIndex@v1); every number and tone comes from
 *  the server (AGENTS §13). Advisory only: no order controls. */
import { useApi } from '../../hooks/useApi'
import { RADIUS, SHADOW, TOKENS, TYPE, numStyle, toneVars, type Tone } from '../../lib/designTokens'
import { Chip, ChipRow, Collapsible, Metric, MetricRow, ShowMore } from '../primitives'
import { optionsAltChip, type OptionsAltVerdict } from '../../lib/entryAlerts'

type Row = {
  symbol: string; state: string | null; plan_source?: string | null; saved_at?: string | null; packet_age_h?: number | null
  price?: number | null; quote_age_h?: number | null; entry_low?: number | null; entry_high?: number | null; stop?: number | null; target?: number | null
  zone: { position: string; distance_pct: number | null }
  rr_plan?: number | null; rr_plan_entry?: number | null; rr_at_quote?: number | null; rr_at_quote_entry?: number | null
  catalyst?: string | null
  cio_verdict: { verdict?: string | null; token?: string | null; rationale?: string | null }
  cio_review: { status?: string | null; mode?: string | null; as_of?: string | null }
  options_alt: OptionsAltVerdict & { chain_as_of?: string | null }
  desk: { status: string; proposal_id?: string | null; strategy?: string | null; approvable?: boolean | null; severity?: string | null; reason?: string | null; entry_state?: string | null }
}
type Index = { schema: string; as_of: string; count: number; counts: Record<string, number>; rows: Row[]; stale: Array<{ symbol: string; state: string | null; packet_age_h: number | null }>; max_age_h: number; errors: string[]; note: string }

const STATE_TONE: Record<string, Tone> = { BUY_READY: 'success', ENTRY_NEAR: 'warning', WATCH: 'neutral' }
const ZONE_TONE: Record<string, Tone> = { in_zone: 'success', above: 'warning', below: 'danger', unknown: 'neutral' }
const $ = (v: number | null | undefined, d = 2) => (v == null ? '—' : `$${Number(v).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d })}`)
const age = (h: number | null | undefined) => (h == null ? 'no time' : h < 1 ? `${Math.round(h * 60)}m ago` : h < 48 ? `${h.toFixed(1)}h ago` : `${Math.round(h / 24)}d ago`)

function toneFromToken(t?: string | null): Tone {
  const s = String(t || '').toUpperCase()
  return s === 'APPROVE' ? 'success' : s === 'MODIFY' ? 'warning' : s === 'REJECT' ? 'danger' : 'neutral'
}

function DeskChip({ d, symbol }: { d: Row['desk']; symbol: string }) {
  if (d.status === 'proposal') {
    return (
      <a href={`/v3/trading?tab=Options&otab=Proposals&symbol=${encodeURIComponent(symbol)}`} style={{ textDecoration: 'none' }} onClick={e => e.stopPropagation()}>
        <Chip tone={d.approvable ? 'success' : 'warning'} guideKey="entry.desk_link">desk: {String(d.strategy || 'proposal').replace(/_/g, ' ')}{d.approvable === false ? ' (blocked)' : ''} →</Chip>
      </a>
    )
  }
  if (d.status === 'not_built') return <Chip tone="warning" guideKey="entry.desk_link">desk: not built — {String(d.reason || 'reason missing').toLowerCase().replace(/_/g, ' ')}</Chip>
  return <Chip tone="neutral" variant="outline" guideKey="entry.desk_link">desk: not in the last scan</Chip>
}

function AlertCard({ r }: { r: Row }) {
  const tone = STATE_TONE[r.state || ''] || 'neutral'
  const t = toneVars(tone)
  const zoneLabel = r.zone.position === 'in_zone' ? 'in zone' : r.zone.position === 'above' ? `${r.zone.distance_pct}% above zone` : r.zone.position === 'below' ? `${r.zone.distance_pct}% below zone` : 'zone unknown'
  const alt = r.options_alt
  // repair 2026-09-28: the chip state comes from the server verdict only (STALE_PRE_FIX / PACKET_UNVERIFIED
  // are warnings that say re-evaluate); a file's legacy qualified flag is never a green badge
  const chip = optionsAltChip(alt)
  return (
    <article data-testid="entry-alert-card" style={{ background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderLeft: `3px solid ${t.color}`, borderRadius: RADIUS.md, boxShadow: SHADOW[1], padding: '10px 14px', minWidth: 0 }}>
      <div style={{ display: 'flex', gap: 10, alignItems: 'baseline', flexWrap: 'wrap' }}>
        <a href={`/v3/watch/intelligence/${encodeURIComponent(r.symbol)}`} style={{ fontSize: TYPE.lg, fontWeight: 900, color: TOKENS.text[0], textDecoration: 'none' }}>{r.symbol}</a>
        <ChipRow>
          <Chip tone={tone} guideKey="entry.state">{String(r.state || 'unknown').replace(/_/g, ' ')}</Chip>
          <Chip tone={ZONE_TONE[r.zone.position] || 'neutral'} guideKey="entry.zone">{zoneLabel}</Chip>
          {r.cio_verdict?.verdict && <Chip tone={toneFromToken(r.cio_verdict.token)} variant="outline" title={r.cio_verdict.rationale || undefined}>CIO {String(r.cio_verdict.verdict).replace(/_/g, ' ').toLowerCase()}{r.cio_review?.mode === 'dry' ? ' · rule text, no model' : ''}</Chip>}
          {r.plan_source && <Chip tone="neutral" variant="outline">{String(r.plan_source).replace(/_/g, ' ')}</Chip>}
        </ChipRow>
        <span style={{ marginLeft: 'auto', fontSize: TYPE.xs, color: TOKENS.text[3] }}>alert {age(r.packet_age_h)} · quote {age(r.quote_age_h)}</span>
      </div>
      <MetricRow style={{ marginTop: 8 }}>
        <Metric guideKey="entry.zone" label="Price" value={$(r.price)} provenance={`zone ${$(r.entry_low)}–${$(r.entry_high)}`} />
        <Metric guideKey="watch.rr" label="Stop / target" value={`${$(r.stop)} / ${$(r.target)}`} />
        <Metric guideKey="entry.rr_plan" label="R:R plan" value={r.rr_plan != null ? `${r.rr_plan.toFixed(2)}:1` : '—'} provenance={r.rr_plan_entry != null ? `at ${$(r.rr_plan_entry)} (zone top)` : undefined} />
        <Metric guideKey="entry.rr_at_quote" label="R:R at quote" value={r.rr_at_quote != null ? `${r.rr_at_quote.toFixed(2)}:1` : 'withheld'} tone={r.rr_at_quote != null && r.rr_plan != null && r.rr_at_quote < r.rr_plan ? 'warning' : undefined} provenance={r.rr_at_quote_entry != null ? `at ${$(r.rr_at_quote_entry)} (now)` : 'price not above stop'} />
      </MetricRow>
      <ChipRow style={{ marginTop: 8 }}>
        <Chip tone={chip.tone} guideKey="entry.options_alt" title={chip.title || undefined} data-testid="entry-alert-options-chip">{chip.label}</Chip>
        {alt.gate_version && <Chip tone="neutral" variant="outline" title={alt.evaluated_at ? `evaluated ${alt.evaluated_at}` : undefined}>gate {alt.gate_version}</Chip>}
        <DeskChip d={r.desk} symbol={r.symbol} />
      </ChipRow>
      {alt.detail && <div style={{ marginTop: 4, fontSize: TYPE.xs, color: TOKENS.text[3] }}>{alt.detail}</div>}
      {r.catalyst && <ShowMore lines={1} style={{ marginTop: 6, fontSize: TYPE.sm, color: TOKENS.text[2] }}>Catalyst: {r.catalyst}</ShowMore>}
    </article>
  )
}

export default function EntryAlertsLane() {
  const idx = useApi<any>('/api/v2/buy-ready/packets', 60_000)
  const data: Index | null = (idx.data?.data ?? idx.data) as Index | null
  const rows = data?.rows || []
  const counts = data?.counts || {}
  const summary = data ? `${counts.BUY_READY || 0} buy-ready · ${counts.ENTRY_NEAR || 0} entry-near · ${rows.length - (counts.BUY_READY || 0) - (counts.ENTRY_NEAR || 0)} other${data.stale?.length ? ` · ${data.stale.length} older than ${data.max_age_h}h hidden` : ''}` : idx.error ? 'unavailable' : 'loading…'
  return (
    <section data-testid="entry-alerts-lane" style={{ marginBottom: 14 }}>
      <Collapsible title="Entry alerts (Telegram BUY_READY / ENTRY_NEAR)" summary={summary} count={rows.length} defaultOpen persistKey="reentry.entry-alerts">
        <div style={{ fontSize: TYPE.xs, color: TOKENS.text[3], marginBottom: 8 }}>
          {data?.note || 'Entry-state packets saved by the runner; advisory only.'}{data?.as_of ? ` · as of ${String(data.as_of).slice(0, 16).replace('T', ' ')}Z` : ''}
        </div>
        {idx.error && <div role="alert" style={{ fontSize: TYPE.sm, color: TOKENS.danger }}>Could not load entry alerts: {String(idx.error)}</div>}
        {data && rows.length === 0 && !idx.error && <div style={{ fontSize: TYPE.sm, color: TOKENS.text[2] }}>No entry-state packet in the last {data.max_age_h}h. The runner writes one per BUY_READY / ENTRY_NEAR symbol.</div>}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(420px, 1fr))', gap: 10 }}>
          {rows.map(r => <AlertCard key={r.symbol} r={r} />)}
        </div>
        {data?.errors?.length ? <div style={{ marginTop: 6, fontSize: TYPE.xs, color: TOKENS.warning }}>unreadable packets: {data.errors.join(', ')}</div> : null}
      </Collapsible>
    </section>
  )
}
