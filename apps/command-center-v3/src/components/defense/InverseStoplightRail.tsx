import { useEffect, useState } from 'react'
import { BB, DASH, numStyle } from '../../lib/watchTokens'

// Inverse-ETF hedge stoplights — THESIS | ENTRY | MANAGE | EXIT per -1x
// candidate. Every light carries its LABEL and plain-language reason (never an
// unlabeled dot). Two positive days are SHADOW telemetry ("day 1 of 2") — the
// pre-registered study (f2988645) REJECTED them as the actionable entry gate.

const COLOR: Record<string, string> = { GREEN: BB.green, AMBER: BB.amber, RED: BB.red }

function Light({ name, l }: { name: string; l: any }) {
  return (
    <span title={`${name} ${l.state} — ${l.label}\n${l.reason || ''}`}
      style={{ display: 'inline-flex', alignItems: 'center', gap: 4, cursor: 'help' }}>
      <span style={{ width: 8, height: 8, borderRadius: 999, background: COLOR[l.state] || BB.text3, display: 'inline-block' }} />
      <span style={{ fontSize: DASH.chip, fontWeight: 800, color: COLOR[l.state] || BB.text3 }}>
        {name} {l.state}
      </span>
    </span>
  )
}

export default function InverseStoplightRail({ compact = false }: { compact?: boolean }) {
  const [d, setD] = useState<any>(null)
  useEffect(() => {
    fetch('/api/v2/defense/inverse-stoplights').then(r => r.json())
      .then(r => setD(r?.data || r)).catch(() => null)
  }, [])
  if (!d?.candidates?.length) return null
  const rows = compact ? d.candidates.filter((c: any) => c.lights.THESIS.state !== 'RED') : d.candidates
  if (compact && !rows.length) return null
  return (
    <div style={{ background: BB.bg, border: `1px solid ${BB.border}`, borderRadius: 2, padding: '8px 11px' }}>
      <div style={{ fontSize: compact ? DASH.data : DASH.panel, fontWeight: 800, color: BB.text1, marginBottom: 6 }}>
        Inverse-ETF Hedge Stoplights
        <span style={{ fontSize: DASH.chip, color: BB.text3, fontWeight: 600, marginLeft: 8 }}
          title={d.path_warning}>
          -1× lane (SH/PSQ/DOG/RWM) · daily-reset products, governed max hold · SQQQ/SARK/REW LOCKED
        </span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {rows.map((c: any) => {
          const L = c.lights
          const en = L.ENTRY
          return (
            <div key={c.inverse} style={{ borderLeft: `3px solid ${COLOR[L.THESIS.state]}`, paddingLeft: 8 }}>
              <div style={{ display: 'flex', gap: 12, alignItems: 'baseline', flexWrap: 'wrap' }}>
                <b style={{ fontSize: DASH.data, color: BB.text1, minWidth: 74 }}>{c.inverse}/{c.bench}</b>
                <Light name="THESIS" l={L.THESIS} />
                <Light name="ENTRY" l={L.ENTRY} />
                <Light name="MANAGE" l={L.MANAGE} />
                <Light name="EXIT" l={L.EXIT} />
                {c.latest_close && (
                  <span style={{ ...numStyle, fontSize: DASH.chip, color: BB.text3, marginLeft: 'auto' }}>
                    close {c.latest_close.d} ${Number(c.latest_close.c).toFixed(2)}
                  </span>
                )}
              </div>
              {!compact && (
                <div style={{ fontSize: DASH.chip, color: BB.text3, marginTop: 2 }}>
                  {en.label}{en.arithmetic ? ` · d1 ${en.arithmetic.day1_ret_pct > 0 ? '+' : ''}${en.arithmetic.day1_ret_pct}% · d2 ${en.arithmetic.day2_ret_pct > 0 ? '+' : ''}${en.arithmetic.day2_ret_pct}% · 2-day ${en.arithmetic.two_day_cum_pct > 0 ? '+' : ''}${en.arithmetic.two_day_cum_pct}% (${en.arithmetic.atr_norm_bounce} ATR) · 50DMA ${en.arithmetic.dist_50dma_pct}%` : ''} — {en.reason}
                </div>
              )}
            </div>
          )
        })}
      </div>
      {!compact && (
        <div style={{ fontSize: DASH.chip, color: BB.text3, marginTop: 6 }}>
          a GREEN entry authorizes the Stage action ONLY (25% T1) — orders travel the existing approval→2FA rails ·
          two green days are shadow telemetry, not the gate (pre-registered study rejected them OOS)
        </div>
      )}
    </div>
  )
}
