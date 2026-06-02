import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import type { DrillContext } from '../components/DetailDrawer'

interface Props { onDrill: (ctx: DrillContext) => void }
const TABS = ['Overview', 'Research', 'Dual Opinion', 'Pipeline'] as const

export default function HermesHub({ onDrill }: Props) {
  const [tab, setTab] = useState<typeof TABS[number]>('Overview')
  const { data: health } = useApi<any>('/api/v2/hermes/health', 120_000)
  const { data: selfLearn } = useApi<any>('/api/v2/hermes/self-learning-overview', 120_000)
  const { data: choices } = useApi<any>('/api/v2/hermes/advisory-choices', 120_000)

  const staging = health?.staging_counts ?? {}
  const killSwitch = health?.kill_switch_active ?? false
  const autonomous = health?.autonomous_loop_active ?? false
  const slData = selfLearn ?? {}

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text0)' }}>Hermes</div>
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>
            Sidecar research desk · {staging.hermes_research_intelligence ?? 0} intelligence rows
            {killSwitch && <span style={{ color: '#ef4444', marginLeft: 8 }}>KILL SWITCH ACTIVE</span>}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          {TABS.map(t => (
            <button key={t} onClick={() => setTab(t)} style={{
              padding: '4px 12px', fontSize: 11, borderRadius: 5, border: 'none', cursor: 'pointer',
              background: tab === t ? 'rgba(96,165,250,.15)' : 'var(--bg2)',
              color: tab === t ? '#60a5fa' : 'var(--text3)', fontWeight: tab === t ? 700 : 400,
            }}>{t}</button>
          ))}
        </div>
      </div>

      {tab === 'Overview' && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          {/* Staging counts */}
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Staging Counts</div>
            {Object.entries(staging).map(([k, v]: [string, any]) => (
              <div key={k} onClick={() => onDrill({ title: k.replace(/_/g, ' '), subtitle: `${v} rows`, endpoint: '/api/v2/hermes/health', rows: [{ table: k, count: v }] })}
                style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 11 }}>
                <span style={{ color: 'var(--text2)', fontFamily: 'monospace' }}>{k.replace('hermes_', '')}</span>
                <span style={{ fontWeight: 600, color: v > 0 ? '#60a5fa' : 'var(--text3)' }}>{v}</span>
              </div>
            ))}
            <div style={{ display: 'flex', gap: 12, marginTop: 10, fontSize: 10 }}>
              <span style={{ color: autonomous ? '#22c55e' : 'var(--text3)' }}>Autonomous: {autonomous ? 'ON' : 'OFF'}</span>
              <span style={{ color: killSwitch ? '#ef4444' : 'var(--text3)' }}>Kill switch: {killSwitch ? 'ACTIVE' : 'OFF'}</span>
            </div>
            <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 6 }}>Source: /api/v2/hermes/health</div>
          </div>

          {/* Advisory choices */}
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Advisory Choices</div>
            {choices ? (
              <>
                <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>{choices.total ?? 0} total</div>
                {Object.entries(choices.counts ?? {}).map(([choice, cnt]: [string, any]) => (
                  <div key={choice} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 6px', borderBottom: '1px solid var(--border)', fontSize: 10 }}>
                    <span style={{ color: 'var(--text2)' }}>{choice.replace(/_/g, ' ')}</span>
                    <span style={{ color: 'var(--text0)' }}>{cnt}</span>
                  </div>
                ))}
                {(choices.total ?? 0) === 0 && <div style={{ color: 'var(--text3)', fontSize: 11 }}>Insufficient data — no operator choices recorded yet</div>}
              </>
            ) : <div style={{ color: 'var(--text3)', fontSize: 11 }}>Loading...</div>}
            <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 6 }}>Source: /api/v2/hermes/advisory-choices</div>
          </div>
        </div>
      )}

      {tab === 'Research' && <div style={{ color: 'var(--text3)', fontSize: 12, padding: 20 }}>Hermes research — awaiting data integration</div>}
      {tab === 'Dual Opinion' && <div style={{ color: 'var(--text3)', fontSize: 12, padding: 20 }}>Dual opinion advisory — awaiting data integration</div>}
      {tab === 'Pipeline' && <div style={{ color: 'var(--text3)', fontSize: 12, padding: 20 }}>Pipeline quality — awaiting data integration</div>}
    </div>
  )
}
