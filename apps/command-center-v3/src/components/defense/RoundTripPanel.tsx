import { useState } from 'react'
import { BB, T, DASH, numStyle } from '../../lib/watchTokens'

// Defense v4 WS-RT — "Stepped out — watching for re-entry". Every open round trip
// renders with its conditions and distance; rollback_open leads; taxable-loss rows
// carry the wash-sale countdown (warning system, not tax advice — Alex route).
// One-tap confirm marks an advisory executed; ingest reconciles when it lands.

const STATUS_COLOR: Record<string, string> = {
  advised: BB.text3, stepped_out: BB.amber, rollback_open: BB.green,
}
const STATUS_LABEL: Record<string, string> = {
  advised: 'ADVISED — exit not detected', stepped_out: 'STEPPED OUT — watching',
  rollback_open: 'ROLLBACK WINDOW OPEN',
}

export default function RoundTripPanel({ trips, onConfirmed }: { trips: any[]; onConfirmed?: () => void }) {
  const [busy, setBusy] = useState<number | null>(null)
  if (!trips?.length) return null
  const ordered = [...trips].sort((a, b) =>
    (a.status === 'rollback_open' ? -1 : 1) - (b.status === 'rollback_open' ? -1 : 1))

  const confirm = async (id: number) => {
    setBusy(id)
    try {
      await fetch('/api/v2/defense/round-trips/confirm', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id }),
      })
      onConfirmed?.()
    } finally { setBusy(null) }
  }

  return (
    <div style={{ background: BB.bg, border: `1px solid ${BB.border}`, borderRadius: 2, padding: '10px 12px' }}>
      <div style={{ fontSize: DASH.panel, fontWeight: 800, color: BB.text1, marginBottom: 8 }}>
        Round trips <span style={{ fontSize: DASH.data, color: BB.text3, fontWeight: 600 }}>· step out, tracked back in — {trips.length} open</span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {ordered.map(t => (
          <div key={t.id} style={{ border: `1px solid ${BB.border}`, borderLeft: `3px solid ${STATUS_COLOR[t.status] || BB.text3}`, borderRadius: 2, padding: '8px 10px' }}>
            <div style={{ display: 'flex', gap: 10, alignItems: 'baseline', flexWrap: 'wrap' }}>
              <span style={{ fontSize: DASH.data + 1, fontWeight: 800, color: BB.text1 }}>{t.symbol}</span>
              <span style={{ fontSize: DASH.chip, fontWeight: 800, color: STATUS_COLOR[t.status], textTransform: 'uppercase' }}>{STATUS_LABEL[t.status] || t.status}</span>
              <span style={{ fontSize: DASH.data, color: BB.text3 }}>advised {t.advised_at} · {t.account.replace('schwab_', '')}</span>
              {t.exit?.detected_at && (
                <span style={{ fontSize: DASH.data, color: BB.text2 }}>
                  out {t.exit.detected_at}{t.exit.price ? <span style={numStyle}> @ ${t.exit.price}</span> : null} ({t.exit.source === 'operator_confirm' ? 'you confirmed' : 'ingest'})
                </span>
              )}
              {t.now_price != null && (
                <span style={{ fontSize: DASH.data, color: BB.text2 }}>
                  now <span style={numStyle}>${t.now_price}</span>
                  {t.now_vs_exit_pct != null && (
                    <b style={{ color: t.now_vs_exit_pct < 0 ? BB.green : BB.red }}> {t.now_vs_exit_pct > 0 ? '+' : ''}{t.now_vs_exit_pct}% vs your exit{t.now_vs_exit_pct < 0 ? ' — re-entry cheaper' : ''}</b>
                  )}
                </span>
              )}
              {t.status === 'advised' && (
                <button disabled={busy === t.id} onClick={() => confirm(t.id)} style={{
                  fontSize: DASH.chip, fontWeight: 800, textTransform: 'uppercase', cursor: 'pointer',
                  color: BB.text1, background: 'transparent', border: `1px solid ${BB.amber}`, borderRadius: 2, padding: '2px 8px',
                }}>{busy === t.id ? '…' : 'I executed this'}</button>
              )}
            </div>
            {t.wash_sale && (
              <div style={{ fontSize: DASH.data, color: BB.amber, marginTop: 4 }}>
                ⚠ {t.wash_sale.line}
              </div>
            )}
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 5 }}>
              {(t.conditions || []).map((c: any, i: number) => (
                <span key={i} style={{
                  fontSize: DASH.chip, fontWeight: 700, borderRadius: 2, padding: '1px 7px',
                  color: c.met ? BB.green : BB.text3, border: `1px solid ${c.met ? BB.green : BB.borderHair}`,
                }}>{c.met ? '✓ ' : ''}{c.label}</span>
              ))}
            </div>
          </div>
        ))}
      </div>
      <div style={{ fontSize: DASH.chip, color: BB.text3, marginTop: 6 }}>
        re-entry conditions are set AT exit from the advisory's own invalidation — whichever satisfies first opens the window · outcomes score vs having held (source_type=rotation_round_trip)
      </div>
    </div>
  )
}
