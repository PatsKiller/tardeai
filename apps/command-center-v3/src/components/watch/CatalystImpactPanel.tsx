/** Catalyst impact for one tracked symbol (LQ-20261107-135).
 *
 *  The watch card has always said "Catalyst: —" / "UNAVAILABLE" and nothing read the per-symbol impact
 *  rows the lane writes (126 rows on 2026-11-06, one per catalyst event × tracked symbol). This panel
 *  is that reader: direction, recorded impact score, the price when the catalyst landed, and the
 *  holding's weight — one stacked row per catalyst, no table, so it reads on a phone.
 *
 *  Data: GET /api/v3/catalyst/symbol-impact (scripts/lib/catalyst_impact_reader.py). Read-only.
 *  An empty answer and an unread answer say different things (lib/catalystImpact.ts). */
import { useApi } from '../../hooks/useApi'
import { BB, TYPE } from '../../lib/watchTokens'
import { RADIUS } from '../../lib/designTokens'
import {
  dayText, describeRow, directionTone, impactView, magnitudeText, priceText, weightText,
  type CatalystImpactPayload, type CatalystImpactRow, type ImpactTone,
} from '../../lib/catalystImpact'

const TONE_COLOR: Record<ImpactTone, string> = {
  up: BB.green, down: BB.red, neutral: BB.text2, unknown: BB.text3,
}

function ImpactRow({ row }: { row: CatalystImpactRow }) {
  const tone = directionTone(row.expected_direction)
  const dirWord = tone === 'unknown' ? 'NO DIRECTION' : tone.toUpperCase()
  const headline = (row.headline || '').trim()
  return (
    <li
      data-catalyst-impact-row={row.symbol || ''}
      style={{
        border: `1px solid ${BB.border}`, borderRadius: RADIUS.md, background: BB.bgPanel,
        padding: '8px 10px', minWidth: 0,
      }}
    >
      <div style={{ display: 'flex', gap: 6, alignItems: 'baseline', flexWrap: 'wrap', minWidth: 0 }}>
        <span
          style={{
            fontSize: TYPE.xs, letterSpacing: 0.4, color: TONE_COLOR[tone],
            border: `1px solid ${TONE_COLOR[tone]}`, borderRadius: RADIUS.sm, padding: '1px 5px', flex: '0 0 auto',
          }}
        >{dirWord}</span>
        <span style={{ fontSize: TYPE.xs, color: BB.text3, minWidth: 0, overflowWrap: 'anywhere' }}>
          {String(row.catalyst_type || 'catalyst').replace(/_/g, ' ')} · {dayText(row.event_at)}
        </span>
      </div>
      {headline ? (
        <div
          style={{
            fontSize: TYPE.sm, color: BB.text1, marginTop: 5, lineHeight: 1.35,
            display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical', overflow: 'hidden',
          }}
          title={headline}
        >{headline}</div>
      ) : null}
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 5, fontSize: TYPE.xs, color: BB.text2 }}>
        <span>impact {magnitudeText(row)}</span>
        <span>{priceText(row)}</span>
        <span>{weightText(row)}</span>
      </div>
      <div style={{ marginTop: 4, fontSize: TYPE.xs, color: BB.text3 }}>
        <span title={describeRow(row)}>
          {row.source_url ? (
            <a href={row.source_url} target="_blank" rel="noopener noreferrer" style={{ color: BB.amber }}>
              source ↗
            </a>
          ) : 'no source link recorded'}
        </span>
      </div>
    </li>
  )
}

export default function CatalystImpactPanel({ symbol, limit = 5 }: { symbol: string; limit?: number }) {
  const path = symbol
    ? `/api/v3/catalyst/symbol-impact?symbol=${encodeURIComponent(symbol)}&days=90&limit=${limit}`
    : ''
  const { data, loading, error } = useApi<CatalystImpactPayload>(path, 600_000, { enabled: !!path })
  const view = impactView(data, { error, loading })

  return (
    <section data-catalyst-impact={view.state} style={{ marginTop: 10, minWidth: 0 }}>
      <div style={{ display: 'flex', gap: 6, alignItems: 'baseline', flexWrap: 'wrap' }}>
        <b style={{ fontSize: TYPE.xs, color: BB.text2 }}>Catalyst impact</b>
        <span style={{ fontSize: TYPE.xs, color: BB.text3 }}>
          {view.state === 'rows' ? view.sentence : ''}
        </span>
      </div>

      {view.state === 'loading' && (
        <div style={{ fontSize: TYPE.xs, color: BB.text3, marginTop: 4 }}>Reading catalyst impact…</div>
      )}

      {view.state === 'unavailable' && (
        <div data-catalyst-impact-unavailable style={{ fontSize: TYPE.xs, color: BB.amber, marginTop: 4, lineHeight: 1.35 }}>
          {view.sentence}
        </div>
      )}

      {view.state === 'empty' && (
        <div data-catalyst-impact-empty style={{ fontSize: TYPE.xs, color: BB.text3, marginTop: 4, lineHeight: 1.35 }}>
          {view.sentence}
          {view.detail ? <div style={{ marginTop: 2 }}>{view.detail}</div> : null}
        </div>
      )}

      {view.state === 'rows' && (
        <ol style={{ listStyle: 'none', margin: '6px 0 0', padding: 0, display: 'grid', gap: 6, minWidth: 0 }}>
          {view.rows.map((r, i) => <ImpactRow key={`${r.id ?? 'row'}-${i}`} row={r} />)}
        </ol>
      )}
    </section>
  )
}
