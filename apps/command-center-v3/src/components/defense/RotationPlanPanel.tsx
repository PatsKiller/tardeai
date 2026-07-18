import { useState } from 'react'
import { BB, T, DASH, numStyle } from '../../lib/watchTokens'
import LadderTrack from './LadderTrack'
import { OversightPills } from './RecommendationsRail'

// Defense v5 RP2 — THE ROTATION PLAN: the page's memory, first-class above the rail.
// One row per position with ANY active rotation state: stance · ladder (T1/T2 chips,
// nearest triggers, fire/disarm states) · re-entry watches with live distances ·
// wash chip · days out. Tranche-granular one-tap confirm opens the slice's re-entry
// watch. Advisory-only; estimates, never order instructions.

const STANCE_COLOR: Record<string, string> = {
  HOLD: BB.green, ADD: T.link, TRIM: BB.red, 'TRIM-WATCH': BB.amber, ROTATE: BB.amber,
}
const TRIP_COLOR: Record<string, string> = {
  advised: BB.text3, stepped_out: BB.amber, rollback_open: BB.green,
}
const STATUS_TIP: Record<string, string> = {
  advised: 'advisory issued — no sell detected yet. Schwab ingest auto-detects fills (~12h lag); the button is an optional instant record',
  stepped_out: 'exit recorded (ingest or your tap) — the re-entry conditions below are watched nightly',
  rollback_open: 'a re-entry condition is MET — the window to rotate back in is open; ranks first for ★CORE',
}

export default function RotationPlanPanel({ plan, onConfirmed, oversight }: { plan: any[]; onConfirmed?: () => void; oversight?: any }) {
  const [busy, setBusy] = useState<string | null>(null)

  const confirm = async (body: any, key: string) => {
    setBusy(key)
    try {
      await fetch('/api/v2/defense/round-trips/confirm', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      })
      onConfirmed?.()
    } finally { setBusy(null) }
  }

  return (
    <div style={{ background: BB.bg, border: `1px solid ${BB.border}`, borderRadius: 2, padding: '10px 12px' }}>
      <div style={{ fontSize: DASH.panel, fontWeight: 800, color: BB.text1, marginBottom: 8 }}>
        Rotation Plan <span title="every advisory you act on lands here automatically: ladders escalate/stand down nightly, executed slices open re-entry watches, outcomes score vs having held. Fills auto-detect from Schwab ingest (~12h) — buttons are optional instant records." style={{ fontSize: DASH.data, color: BB.text3, fontWeight: 600, cursor: 'help' }}>· the desk's memory — trims, ladders, re-entry watches</span>
      </div>
      {(!plan || plan.length === 0) && (
        <div style={{ fontSize: DASH.data, color: BB.text3 }}>
          No active rotation plans — advisories you act on appear here automatically.
        </div>
      )}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {(plan || []).map(r => {
          const lad = r.ladder_detail
          return (
            <div key={`${r.symbol}-${r.account}`} style={{ border: `1px solid ${BB.border}`, borderLeft: `3px solid ${STANCE_COLOR[r.stance] || BB.text3}`, borderRadius: 2, padding: '8px 10px' }}>
              <div style={{ display: 'flex', gap: 10, alignItems: 'baseline', flexWrap: 'wrap', marginBottom: 4 }}>
                <span style={{ fontSize: DASH.data + 1, fontWeight: 800, color: BB.text1 }}>{r.symbol}</span>
                {r.value != null && <span style={{ ...numStyle, fontSize: DASH.data, color: BB.text2 }}>${Math.round(r.value / 1000)}K</span>}
                <span style={{ fontSize: DASH.chip, color: BB.text3 }}>{r.account_label}</span>
                {r.stance && <span style={{ fontSize: DASH.chip, fontWeight: 800, color: STANCE_COLOR[r.stance] || BB.text2, textTransform: 'uppercase' }}>{r.stance}</span>}
                <OversightPills cardId={(r.ladder_detail?.advisory_id) || `moveout-${r.symbol}-${r.account}-*`} factorsN={null} oversight={oversight} />
              </div>
              {lad && (
                <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center', marginBottom: 4 }}>
                  <LadderTrack ladder={lad} />
                  {lad.t1_status !== 'executed' && (
                    <button disabled={busy === `${lad.ladder_id}-T1`}
                      onClick={() => confirm({ ladder_id: lad.ladder_id, tranche: 'T1' }, `${lad.ladder_id}-T1`)}
                      title="OPTIONAL — Schwab ingest auto-detects a T1-sized sell (≥60% of advised shares) within ~12h and marks it sold; tap for an instant record"
                      style={{ fontSize: DASH.chip, fontWeight: 800, textTransform: 'uppercase', cursor: 'pointer', color: BB.text1, background: 'transparent', border: `1px solid ${BB.amber}`, borderRadius: 2, padding: '2px 8px' }}>
                      {busy === `${lad.ladder_id}-T1` ? '…' : 'mark T1 sold'}
                    </button>
                  )}
                  {(lad.tranches || []).filter((t: any) => t.status === 'fired').map((t: any) => (
                    <button key={t.tranche} disabled={busy === `${lad.ladder_id}-${t.tranche}`}
                      onClick={() => confirm({ ladder_id: lad.ladder_id, tranche: t.tranche }, `${lad.ladder_id}-${t.tranche}`)}
                      style={{ fontSize: DASH.chip, fontWeight: 800, textTransform: 'uppercase', cursor: 'pointer', color: BB.text1, background: 'transparent', border: `1px solid ${BB.red}`, borderRadius: 2, padding: '2px 8px' }}>
                      {busy === `${lad.ladder_id}-${t.tranche}` ? '…' : `mark ${t.tranche} sold`}
                    </button>
                  ))}
                </div>
              )}
              {(r.round_trips || []).map((t: any) => (
                <div key={t.id} style={{ marginBottom: 3 }}>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap', fontSize: DASH.data }}>
                    <span title={STATUS_TIP[t.status] || ''} style={{ fontSize: DASH.chip, fontWeight: 800, color: TRIP_COLOR[t.status] || BB.text3, textTransform: 'uppercase', cursor: 'help' }}>
                      {t.status === 'rollback_open' ? 'ROLLBACK WINDOW OPEN' : t.status.replace('_', ' ')}
                    </span>
                    {t.exit?.detected_at && <span style={{ color: BB.text3 }}>out {t.exit.detected_at}{t.exit.price ? ` @ $${t.exit.price}` : ''}</span>}
                    {t.now_vs_exit_pct != null && (
                      <b style={{ color: t.now_vs_exit_pct < 0 ? BB.green : BB.red }}>
                        {t.now_vs_exit_pct > 0 ? '+' : ''}{t.now_vs_exit_pct}% vs exit{t.now_vs_exit_pct < 0 ? ' — re-entry cheaper' : ''}
                      </b>
                    )}
                    {t.status === 'advised' && (
                      <button disabled={busy === `rt-${t.id}`} onClick={() => confirm({ id: t.id }, `rt-${t.id}`)}
                        title="OPTIONAL — Schwab ingest auto-detects the sell within ~12h and records it for you; tap only if you want it logged immediately"
                        style={{ fontSize: DASH.chip, fontWeight: 800, textTransform: 'uppercase', cursor: 'pointer', color: BB.text1, background: 'transparent', border: `1px solid ${BB.amber}`, borderRadius: 2, padding: '1px 7px' }}>
                        {busy === `rt-${t.id}` ? '…' : 'I executed this'}
                      </button>
                    )}
                  </div>
                  {t.wash_sale && <div style={{ fontSize: DASH.data, color: BB.amber }}>⚠ {t.wash_sale.line}</div>}
                  <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', marginTop: 2 }}>
                    {(t.conditions || []).map((c: any, i: number) => (
                      <span key={i} title={c.met ? 'condition MET — contributes to opening the rollback window (whichever condition satisfies first opens it)' : 're-entry condition frozen at advise time — evaluated nightly; not met yet'} style={{ fontSize: DASH.chip, fontWeight: 700, borderRadius: 2, padding: '1px 6px', color: c.met ? BB.green : BB.text3, border: `1px solid ${c.met ? BB.green : BB.borderHair}`, cursor: 'help' }}>
                        {c.met ? '✓ ' : ''}{c.label}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )
        })}
      </div>
      <div style={{ fontSize: DASH.chip, color: BB.text3, marginTop: 6 }}>
        tranche triggers frozen at creation (machine-evaluable only) · executed slices open re-entry watches automatically · outcomes score vs having held
      </div>
    </div>
  )
}
