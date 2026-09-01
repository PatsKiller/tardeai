# SystemHealth.tsx Replacement

Status:      HISTORICAL
as_of:       2026-05-25T14:00:12-04:00
Measured at: efcc51365 / not measured

- **Target**: `apps/command-center-v2/src/pages/SystemHealth.tsx`
- **Original SHA256**: `f2ed031181c2d2dbbfe04b8f9b94f07d7505230c9645ca91e9bb5f8636a8acd7`

## Changes

- Title: "System Health" -> "System Health & Services"
- Subtitle updated to: "Data products, services, LLM router, and freshness"
- Replaced inline `const btn` with `ActionButton` shared primitive
- Replaced hardcoded status color logic in Data Product Health with `StatusBadge`
- Added proper empty state for Data Product section when `data?.data_freshness` is missing
- Preserved weekend/holiday context (`weekend_market_closed` logic)
- Kept Orchestration navigation button
- Kept system info footer

## What did NOT change

- API calls: `useApi('/api/v2/system-health')`, `useApi('/api/v2/finviz-screeners')` -- identical
- Data access patterns: `data?.llm`, `data?.db_tables`, `data?.cio_decisions`, `data?.data_freshness` -- identical
- All MetricTile configurations for LLM Router -- identical
- DB State grid rendering -- identical
- CIO Decision Distribution rendering -- identical
- Finviz Screeners rendering -- identical
- Ollama offline warning -- identical

## Full Replacement

```tsx
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import SectionHeader from '../components/SectionHeader'
import MetricTile from '../components/MetricTile'
import StatusBadge from '../components/StatusBadge'
import ActionButton from '../components/ActionButton'
import { useApi } from '../hooks/useApi'

export default function SystemHealth() {
  const navigate = useNavigate()
  const [rk, setRk] = useState(0)
  const { data } = useApi<any>(`/api/v2/system-health?_r=${rk}`)
  const { data: screeners } = useApi<any>(`/api/v2/finviz-screeners?_r=${rk}`)

  const llm = data?.llm || {}
  const db = data?.db_tables || {}
  const cio = data?.cio_decisions || []

  return (
    <>
      <PageHeader title="System Health & Services" subtitle="Data products, services, LLM router, and freshness" actions={
        <div style={{ display: 'flex', gap: 6 }}>
          <ActionButton label="Orchestration" onClick={() => navigate('/orchestration')} variant="secondary" />
          <ActionButton label="Refresh" onClick={() => setRk(k => k + 1)} variant="secondary" />
        </div>
      } />

      {/* LLM Router */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 10, marginBottom: 14 }}>
        <MetricTile label="Local Ollama" value={llm?.local?.available ? 'Online' : 'Offline'}
          deltaColor={llm?.local?.available ? 'var(--green)' : 'var(--red)'}
          delta={llm?.local?.available ? `${llm.local.model || 'qwen3'}` : 'fallback to cloud APIs'}
          tooltip="Local LLM for fast/cheap analysis. When offline, falls back to Claude API (higher cost). Restart: systemctl --user start ollama" />
        <MetricTile label="Claude" value={llm?.claude?.configured ? 'Ready' : 'No Key'}
          deltaColor={llm?.claude?.configured ? 'var(--green)' : 'var(--text3)'}
          delta={llm?.claude?.configured ? 'ANTHROPIC_API_KEY set' : 'check .env file'}
          tooltip="API keys loaded from .env file. 'No Key' = ANTHROPIC_API_KEY not found." />
        <MetricTile label="Grok" value={llm?.grok?.configured ? 'Ready' : 'No Key'}
          deltaColor={llm?.grok?.configured ? 'var(--green)' : 'var(--amber)'}
          delta={llm?.grok?.configured ? 'XAI_API_KEY set' : 'optional — Claude is primary'}
          tooltip="xAI Grok API. Optional fallback when Claude is unavailable." />
        <MetricTile label="Daily Spend" value={`$${(llm?.daily_spend || 0).toFixed(4)}`}
          delta={`of $${(llm?.daily_budget || 2).toFixed(2)} budget`}
          deltaColor={(llm?.daily_spend || 0) > (llm?.daily_budget || 2) ? 'var(--red)' : 'var(--green)'}
          tooltip="LLM API spend today. Budget: $2/day. Local calls are free. Tracked in logs/llm_router.log." />
        <MetricTile label="Budget Left" value={`$${(llm?.budget_remaining || 0).toFixed(2)}`}
          deltaColor={(llm?.budget_remaining || 0) > 0.5 ? 'var(--green)' : (llm?.budget_remaining || 0) > 0 ? 'var(--amber)' : 'var(--red)'}
          delta={(llm?.budget_remaining || 0) <= 0 ? 'EXCEEDED — local only' : 'remaining today'} />
      </div>

      {!llm?.local?.available && (
        <div style={{ padding: '8px 12px', marginBottom: 12, background: 'var(--amber-dim)', border: '1px solid var(--amber)', borderRadius: 8, fontSize: 10, color: 'var(--amber)' }}>
          Ollama is offline — all LLM calls route to cloud APIs (higher cost). To restart: SSH to server and run <code style={{ background: 'var(--bg3)', padding: '1px 4px', borderRadius: 3 }}>systemctl --user start ollama</code>
        </div>
      )}

      {/* DB State */}
      <Card>
        <SectionHeader title="Database State" />
        {Object.keys(db).length > 0 ? (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, padding: 12 }}>
            {Object.entries(db).map(([t, c]) => (
              <div key={t} style={{ fontSize: 10 }}>
                <div style={{ color: 'var(--text3)', fontSize: 8 }}>{t.replace('watchlist_', 'wl_').replace('ticker_', 'tk_')}</div>
                <div style={{ fontWeight: 700, color: Number(c) > 0 ? 'var(--text1)' : 'var(--text3)' }}>{Number(c).toLocaleString()}</div>
              </div>
            ))}
          </div>
        ) : (
          <div style={{ padding: 14, color: 'var(--text3)', fontSize: 11 }}>Database state unavailable — check Ops page for table inventory or verify DB connection.</div>
        )}
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

      {/* Data Product Freshness */}
      <Card title={data?.data_freshness ? `Data Product Health — ${data.data_freshness.summary}` : 'Data Product Health'} style={{ marginTop: 14 }}>
        {data?.data_freshness ? (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 8 }}>
            {(data.data_freshness.products || []).map((p: any) => {
              const isWeekendStale = p.stale_reason === 'weekend_market_closed'
              const statusKey = p.status === 'fresh' ? 'green' : isWeekendStale ? 'info' : p.status === 'stale' ? 'red' : 'muted'
              const statusLabel = p.status === 'fresh' ? 'Fresh' : isWeekendStale ? 'Weekend Paused' : p.status === 'stale' ? 'Stale — Action Needed' : 'Unknown'
              const color = p.status === 'fresh' ? 'var(--green)' : isWeekendStale ? 'var(--accent)' : p.status === 'stale' ? 'var(--red)' : 'var(--text3)'
              return (
                <div key={p.product} title={p.remediation || ''} style={{ padding: '8px 12px', borderRadius: 6, border: `1px solid color-mix(in srgb, ${color} 20%, transparent)`, background: `color-mix(in srgb, ${color} 5%, transparent)`, cursor: p.remediation ? 'help' : 'default' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontSize: 11, fontWeight: 600, color }}>{p.product}</span>
                    <StatusBadge status={statusKey} label={statusLabel} />
                  </div>
                  <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 3 }}>
                    {p.age_hours != null ? `${Math.round(p.age_hours)}h old` : 'unknown'} / max {p.max_stale_hours}h
                  </div>
                  {p.owner && (
                    <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 2 }}>
                      Owner: {p.owner} · {p.schedule || 'manual'}
                    </div>
                  )}
                  {p.stale_reason && p.stale_reason !== 'weekend_market_closed' && p.remediation && (
                    <div style={{ fontSize: 9, color: 'var(--red)', marginTop: 2 }}>
                      Fix: <code style={{ fontSize: 8 }}>{p.remediation}</code>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        ) : (
          <div style={{ padding: 14, color: 'var(--text3)', fontSize: 11 }}>
            Data product freshness not yet loaded. Refresh to check status.
          </div>
        )}
      </Card>

      {/* System Info */}
      <div style={{ marginTop: 14, padding: '10px 14px', background: 'rgba(16,20,28,0.92)', border: '1px solid rgba(255,255,255,0.07)', borderRadius: 10, fontSize: 10, color: 'var(--text3)' }}>
        Cron jobs: {data?.cron_jobs || 0} | Finviz screeners: {data?.finviz_screeners || screeners?.screeners?.length || 0} active | Validation suites: {data?.validation_suites || 0}
        {data?.finviz_screeners === 0 && screeners?.screeners?.length > 0 && (
          <span style={{ color: 'var(--amber)', marginLeft: 8 }}>Note: DB shows {screeners.screeners.length} screeners — health check may query different source</span>
        )}
      </div>
    </>
  )
}
```
