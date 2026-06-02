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
  const { data: backlog } = useApi<any>('/api/v2/hermes/research-backlog', 120_000)
  const { data: dualOp } = useApi<any>('/api/v2/hermes/dual-opinion', 120_000)
  const { data: pipeQual } = useApi<any>('/api/v2/hermes/pipeline-quality', 120_000)

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

      {tab === 'Research' && backlog && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Research Backlog ({backlog.total ?? 0})</div>
          {backlog.advisory_notice && <div style={{ fontSize: 9, color: '#f59e0b', marginBottom: 8 }}>{backlog.advisory_notice}</div>}
          {(backlog.items ?? []).length === 0 ? <div style={{ color: 'var(--text3)', fontSize: 11 }}>No backlog items</div> :
          (backlog.items ?? []).slice(0, 12).map((item: any, i: number) => (
            <div key={i} onClick={() => onDrill({ title: item.topic ?? item.symbol ?? `Item ${i}`, subtitle: item.research_type ?? '', endpoint: '/api/v2/hermes/research-backlog', rows: [item] })}
              style={{ padding: '6px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 11, color: 'var(--text2)' }}>
              <span style={{ fontWeight: 600, color: 'var(--text0)' }}>{item.symbol ?? item.topic ?? ''}</span>
              <span style={{ marginLeft: 8, color: 'var(--text3)', fontSize: 9 }}>{item.research_type ?? item.status ?? ''}</span>
            </div>
          ))}
          <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/hermes/research-backlog</div>
        </div>
      )}

      {tab === 'Dual Opinion' && dualOp && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Dual Opinion Advisory ({dualOp.total ?? 0})</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10, marginBottom: 12 }}>
            {[{l:'Agrees',v:dualOp.agrees,c:'#22c55e'},{l:'Caution',v:dualOp.agrees_with_caution,c:'#f59e0b'},{l:'Needs Evidence',v:dualOp.needs_more_evidence,c:'#60a5fa'},{l:'Disagrees',v:dualOp.disagrees,c:'#ef4444'}].map(k => (
              <div key={k.l} style={{ background: 'var(--bg2)', borderRadius: 8, padding: '8px 10px', textAlign: 'center' }}>
                <div style={{ fontSize: 20, fontWeight: 700, color: k.c }}>{k.v ?? 0}</div>
                <div style={{ fontSize: 9, color: 'var(--text3)' }}>{k.l}</div>
              </div>
            ))}
          </div>
          {(dualOp.opinions ?? []).slice(0, 8).map((op: any, i: number) => (
            <div key={i} onClick={() => onDrill({ title: op.symbol ?? `Opinion ${i}`, subtitle: op.verdict ?? '', endpoint: '/api/v2/hermes/dual-opinion', rows: [op] })}
              style={{ padding: '6px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 11 }}>
              <span style={{ fontWeight: 600, color: 'var(--text0)', fontFamily: 'monospace' }}>{op.symbol ?? ''}</span>
              <span style={{ marginLeft: 8, color: op.verdict === 'AGREE' ? '#22c55e' : op.verdict === 'DISAGREE' ? '#ef4444' : '#f59e0b' }}>{op.verdict ?? '—'}</span>
            </div>
          ))}
          <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/hermes/dual-opinion</div>
        </div>
      )}

      {tab === 'Pipeline' && pipeQual && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Pipeline Quality ({pipeQual.total ?? 0} findings)</div>
          {pipeQual.advisory_notice && <div style={{ fontSize: 9, color: '#f59e0b', marginBottom: 8 }}>{pipeQual.advisory_notice}</div>}
          {(pipeQual.findings ?? []).length === 0 ? <div style={{ color: 'var(--text3)', fontSize: 11 }}>No quality findings</div> :
          (pipeQual.findings ?? []).slice(0, 10).map((f: any, i: number) => (
            <div key={i} onClick={() => onDrill({ title: f.finding_type ?? `Finding ${i}`, subtitle: f.severity ?? '', endpoint: '/api/v2/hermes/pipeline-quality', rows: [f] })}
              style={{ padding: '6px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 11 }}>
              <span style={{ color: f.severity === 'critical' ? '#ef4444' : f.severity === 'warning' ? '#f59e0b' : 'var(--text2)' }}>{f.severity ?? '—'}</span>
              <span style={{ marginLeft: 8, color: 'var(--text0)' }}>{f.finding_type ?? ''}</span>
              <span style={{ marginLeft: 8, color: 'var(--text3)', fontSize: 9 }}>{f.symbol ?? ''}</span>
            </div>
          ))}
          <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/hermes/pipeline-quality</div>
        </div>
      )}
    </div>
  )
}
