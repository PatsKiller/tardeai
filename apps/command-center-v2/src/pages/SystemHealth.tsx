import { useState } from 'react'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import SectionHeader from '../components/SectionHeader'
import MetricTile from '../components/MetricTile'
import { useApi } from '../hooks/useApi'

export default function SystemHealth() {
  const [rk, setRk] = useState(0)
  const { data } = useApi<any>(`/api/v2/system-health?_r=${rk}`)
  const { data: screeners } = useApi<any>(`/api/v2/finviz-screeners?_r=${rk}`)

  const llm = data?.llm || {}
  const db = data?.db_tables || {}
  const cio = data?.cio_decisions || []

  return (
    <>
      <PageHeader title="System Health" subtitle="LLM router, DB state, screeners, pipeline status" actions={
        <button onClick={() => setRk(k => k + 1)} style={btn}>Refresh</button>
      } />

      {/* LLM Router */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 10, marginBottom: 14 }}>
        <MetricTile label="Local Ollama" value={llm?.local?.available ? 'Online' : 'Offline'} deltaColor={llm?.local?.available ? 'var(--green)' : 'var(--red)'} />
        <MetricTile label="Claude" value={llm?.claude?.configured ? 'Ready' : 'No Key'} deltaColor={llm?.claude?.configured ? 'var(--green)' : 'var(--text3)'} />
        <MetricTile label="Grok" value={llm?.grok?.configured ? 'Ready' : 'No Key'} deltaColor={llm?.grok?.configured ? 'var(--green)' : 'var(--amber)'} />
        <MetricTile label="Daily Spend" value={`$${(llm?.daily_spend || 0).toFixed(4)}`} />
        <MetricTile label="Budget Left" value={`$${(llm?.budget_remaining || 0).toFixed(2)}`} deltaColor={(llm?.budget_remaining || 0) > 1 ? 'var(--green)' : 'var(--amber)'} />
      </div>

      {/* DB State */}
      <Card>
        <SectionHeader title="Database State" />
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, padding: 12 }}>
          {Object.entries(db).map(([t, c]) => (
            <div key={t} style={{ fontSize: 10 }}>
              <div style={{ color: 'var(--text3)', fontSize: 8 }}>{t.replace('watchlist_', '').replace('ticker_', '')}</div>
              <div style={{ fontWeight: 700, color: Number(c) > 0 ? 'var(--text1)' : 'var(--text3)' }}>{String(c)}</div>
            </div>
          ))}
        </div>
      </Card>

      {/* CIO Decisions */}
      <Card>
        <SectionHeader title="CIO Decision Distribution" />
        <div style={{ padding: 12 }}>
          {cio.map((d: any, i: number) => (
            <div key={i} style={{ display: 'flex', gap: 8, fontSize: 10, padding: '3px 0', borderBottom: '1px solid var(--border-subtle)' }}>
              <span style={{ fontWeight: 700, color: 'var(--accent)', minWidth: 120 }}>{d.action}</span>
              <span style={{ color: 'var(--text2)' }}>{d.cnt}</span>
            </div>
          ))}
        </div>
      </Card>

      {/* Finviz Screeners */}
      <Card>
        <SectionHeader title="Finviz Screeners" count={screeners?.screeners?.length} />
        <div style={{ maxHeight: 300, overflowY: 'auto' }}>
          {(screeners?.screeners || []).map((s: any) => (
            <div key={s.screener_id} style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '8px 12px', borderBottom: '1px solid var(--border-subtle)' }}>
              <span style={{ fontWeight: 700, color: 'var(--accent)', fontSize: 11, minWidth: 180 }}>{s.display_name}</span>
              <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 99, background: 'rgba(74,144,244,0.1)', color: 'var(--accent)' }}>{s.strategy_type?.replace(/_/g, ' ')}</span>
              <span style={{ fontSize: 9, color: 'var(--text3)', flex: 1 }}>{s.description?.slice(0, 60)}</span>
              <a href={s.finviz_url} target="_blank" rel="noreferrer" style={{ fontSize: 9, color: 'var(--accent)' }}>Open</a>
            </div>
          ))}
        </div>
      </Card>

      {/* System Info */}
      <div style={{ marginTop: 14, padding: '10px 14px', background: 'rgba(16,20,28,0.92)', border: '1px solid rgba(255,255,255,0.07)', borderRadius: 10, fontSize: 10, color: 'var(--text3)' }}>
        Cron jobs: {data?.cron_jobs || 0} | Validation suites: {data?.validation_suites || 0} | Screeners: {data?.finviz_screeners || 0}
      </div>
    </>
  )
}

const btn: React.CSSProperties = { padding: '4px 12px', fontSize: 10, border: '1px solid rgba(255,255,255,0.08)', borderRadius: 8, background: 'rgba(255,255,255,0.04)', color: 'var(--text1)', cursor: 'pointer', fontFamily: 'var(--sans)' }
