import { useState, useEffect, useCallback } from 'react'

interface AdminModalProps { type: 'personal' | 'yaml' | 'env' | 'settings'; onClose: () => void }

export default function AdminModal({ type, onClose }: AdminModalProps) {
  const [data, setData] = useState<Record<string, unknown> | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const endpoints: Record<string, string> = {
    personal: '/api/personal/read',
    yaml: '/data/portfolios/state/yaml_advisor_output.json',
    env: '/api/env/read',
    settings: '/api/health',
  }
  const titles: Record<string, string> = {
    personal: 'Personal Situation',
    yaml: 'YAML Config Review',
    env: 'Environment Keys',
    settings: 'System Settings',
  }

  useEffect(() => {
    setLoading(true)
    fetch(endpoints[type]).then(r => r.json()).then(d => { setData(d); setLoading(false) }).catch(e => { setError(String(e)); setLoading(false) })
  }, [type])

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.6)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={onClose}>
      <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 'var(--radius-lg)', padding: '16px 20px', width: 560, maxHeight: '80vh', overflowY: 'auto' }} onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <h2 style={{ fontFamily: 'var(--sans)', fontSize: 14, fontWeight: 700, color: 'var(--text0)', margin: 0 }}>{titles[type]}</h2>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text3)', cursor: 'pointer', fontSize: 16, fontFamily: 'var(--mono)' }}>{'\u00d7'}</button>
        </div>

        {loading && <div style={{ color: 'var(--text3)', padding: 20 }}>Loading...</div>}
        {error && <div style={{ color: 'var(--red)', padding: 10 }}>{error}</div>}

        {!loading && data && type === 'personal' && <PersonalView data={data} />}
        {!loading && data && type === 'yaml' && <YamlView data={data} />}
        {!loading && data && type === 'env' && <EnvView data={data} />}
        {!loading && data && type === 'settings' && <SettingsView data={data} />}
      </div>
    </div>
  )
}

function PersonalView({ data }: { data: Record<string, unknown> }) {
  const fields = (data as { fields?: Record<string, { value: unknown; category: string; description: string }> }).fields || {}
  const categories = Array.from(new Set(Object.values(fields).map(f => f.category || 'general'))).sort()

  return (
    <>
      {categories.map(cat => (
        <div key={cat} style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text2)', textTransform: 'uppercase', letterSpacing: '.4px', marginBottom: 6, borderBottom: '1px solid var(--border-subtle)', paddingBottom: 4 }}>{cat}</div>
          {Object.entries(fields).filter(([, f]) => (f.category || 'general') === cat).map(([key, f]) => (
            <div key={key} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: 11 }}>
              <span style={{ color: 'var(--text2)' }}>{key.replace(/_/g, ' ')}</span>
              <span style={{ color: 'var(--text0)', fontWeight: 600 }}>{String(f.value ?? '—')}</span>
            </div>
          ))}
        </div>
      ))}
      <div style={{ marginTop: 10, padding: '6px 10px', background: 'var(--bg3)', borderRadius: 'var(--radius)', fontSize: 9, color: 'var(--text3)' }}>
        Read-only view. Edit via v1 Command Center personal modal or /api/personal/write.
      </div>
    </>
  )
}

function YamlView({ data }: { data: Record<string, unknown> }) {
  const status = (data as { status?: string }).status || 'unknown'
  const summary = (data as { ground_truth_summary?: Record<string, unknown> }).ground_truth_summary || {}
  const opus = (data as { opus_output?: unknown }).opus_output

  return (
    <>
      <div style={{ fontSize: 10, color: status === 'complete' ? 'var(--green)' : 'var(--amber)', marginBottom: 8 }}>Status: {status}</div>
      {Object.keys(summary).length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text2)', marginBottom: 4 }}>Ground Truth Summary</div>
          <div style={{ fontSize: 10, color: 'var(--text1)', whiteSpace: 'pre-wrap', maxHeight: 200, overflowY: 'auto', background: 'var(--bg3)', padding: 8, borderRadius: 'var(--radius)' }}>{JSON.stringify(summary, null, 2)}</div>
        </div>
      )}
      {opus && (
        <div>
          <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text2)', marginBottom: 4 }}>AI Output</div>
          <div style={{ fontSize: 10, color: 'var(--text1)', whiteSpace: 'pre-wrap', maxHeight: 300, overflowY: 'auto', background: 'var(--bg3)', padding: 8, borderRadius: 'var(--radius)' }}>
            {typeof opus === 'string' ? opus.slice(0, 2000) : JSON.stringify(opus, null, 2).slice(0, 2000)}
          </div>
        </div>
      )}
    </>
  )
}

function EnvView({ data }: { data: Record<string, unknown> }) {
  const vars = (data as { env?: Record<string, string> }).env || (data as Record<string, string>)
  const sensitive = ['PASSWORD', 'KEY', 'TOKEN', 'COOKIE', 'SECRET']

  return (
    <>
      {Object.entries(vars).filter(([k]) => !k.startsWith('_')).map(([key, val]) => {
        const isSensitive = sensitive.some(s => key.toUpperCase().includes(s))
        return (
          <div key={key} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: 10 }}>
            <span style={{ color: 'var(--text2)', fontWeight: 600 }}>{key}</span>
            <span style={{ color: 'var(--text1)', maxWidth: 250, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {isSensitive ? (String(val || '').slice(0, 4) + '****') : String(val || '—').slice(0, 60)}
            </span>
          </div>
        )
      })}
      <div style={{ marginTop: 10, padding: '6px 10px', background: 'var(--bg3)', borderRadius: 'var(--radius)', fontSize: 9, color: 'var(--text3)' }}>
        Read-only view. Edit via v1 Command Center ENV modal or /api/env/write.
      </div>
    </>
  )
}

function SettingsView({ data }: { data: Record<string, unknown> }) {
  return (
    <>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
        {Object.entries(data).map(([key, val]) => (
          <div key={key} style={{ padding: '6px 0', borderBottom: '1px solid var(--border-subtle)' }}>
            <div style={{ fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase' }}>{key.replace(/_/g, ' ')}</div>
            <div style={{ fontSize: 11, color: 'var(--text0)', fontWeight: 600 }}>{String(val)}</div>
          </div>
        ))}
      </div>
      <div style={{ marginTop: 10, padding: '6px 10px', background: 'var(--bg3)', borderRadius: 'var(--radius)', fontSize: 9, color: 'var(--text3)' }}>
        System health overview. DataProvider configuration available in v1 Settings drawer.
      </div>
    </>
  )
}
