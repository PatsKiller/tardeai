import { useState } from 'react'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import { useApi } from '../hooks/useApi'

const SC: Record<string, string> = {
  risk_on_trend:'#0ecb81', broad_momentum:'#0ecb81', low_volatility_grind:'#4a90f4',
  risk_off:'#f6465d', high_volatility:'#f6465d', choppy_range:'#f0b90b',
  defensive_rotation:'#f0b90b', unknown:'#848e9c',
  favor:'#0ecb81', neutral:'#848e9c', de_emphasize:'#f0b90b',
  review_required:'#f0b90b', pause_candidate:'#f6465d',
  aligned:'#0ecb81', misaligned:'#f6465d', partially_aligned:'#f0b90b',
  bullish:'#0ecb81', bearish:'#f6465d',
}
const dot = (s: string) => <span style={{ display:'inline-block', width:8, height:8, borderRadius:4, background:SC[s]||'#848e9c', marginRight:6 }}/>
const btn: React.CSSProperties = { fontSize:10, padding:'4px 10px', border:'1px solid var(--border)', borderRadius:4, background:'var(--bg1)', color:'var(--text1)', cursor:'pointer' }
const th: React.CSSProperties = { padding:'6px 8px', textAlign:'left', color:'#848e9c', fontSize:10 }
const td: React.CSSProperties = { padding:'6px 8px', fontSize:11 }

export default function RiskRegime() {
  const [rk, setRk] = useState(0)
  const [tab, setTab] = useState('regime')
  const { data: regime } = useApi<any>(`/api/v2/risk-regime/status?_r=${rk}`)
  const { data: indicators } = useApi<any>(`/api/v2/risk-regime/indicators?_r=${rk}`)
  const { data: signals } = useApi<any>(`/api/v2/strategy-rotation/signals?_r=${rk}`)
  const { data: profiles } = useApi<any>(`/api/v2/strategy-rotation/profiles?_r=${rk}`)
  const { data: alignments } = useApi<any>(`/api/v2/strategy-rotation/alignments?_r=${rk}`)

  const r = regime || null
  const tabBtn = (t: string, label: string) => (
    <button onClick={() => setTab(t)} style={{
      ...btn, background: tab === t ? 'var(--accent)' : 'var(--bg1)', color: tab === t ? '#fff' : 'var(--text1)'
    }}>{label}</button>
  )

  return (
    <div style={{ padding:'16px 24px', maxWidth:1200 }}>
      <PageHeader title="Risk Regime" subtitle="Market regime detection, strategy rotation signals — proposal-only, no auto-rotation" actions={
        <button onClick={() => setRk(k=>k+1)} style={btn}>Refresh</button>
      }/>

      {/* Regime Banner */}
      {r ? (
        <div style={{ padding:'10px 16px', marginBottom:14, borderRadius:6,
          background: r.stale_data ? 'rgba(240,185,11,.08)' : 'rgba(14,203,129,.08)',
          border: `1px solid ${r.stale_data ? '#f0b90b' : '#0ecb81'}` }}>
          <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center' }}>
            <span style={{ fontSize:16, fontWeight:700 }}>
              {dot(r.regime_label)}{(r.regime_label||'unknown').replace(/_/g,' ').toUpperCase()}
            </span>
            <span style={{ fontSize:11, color:'var(--text2)' }}>
              Confidence: {r.confidence ? `${(Number(r.confidence)*100).toFixed(0)}%` : '?'}
              {r.stale_data && ' | STALE DATA'}
            </span>
          </div>
          <div style={{ fontSize:11, color:'var(--text3)', marginTop:4 }}>{r.summary}</div>
        </div>
      ) : <div style={{ color:'#848e9c', padding:16, marginBottom:14 }}>No regime snapshot. Run classifier first.</div>}

      <div style={{ display:'flex', gap:6, marginBottom:16, flexWrap:'wrap' }}>
        {tabBtn('regime', 'Regime')}
        {tabBtn('indicators', `Indicators (${(indicators||[]).length})`)}
        {tabBtn('rotation', `Rotation (${(signals||[]).length})`)}
        {tabBtn('profiles', `Profiles (${(profiles||[]).length})`)}
        {tabBtn('alignment', `Alignment (${(alignments||[]).length})`)}
      </div>

      {tab === 'indicators' && (
        <Card title="Regime Indicators">
          {!(indicators?.length) ? <div style={{ color:'#848e9c', padding:16 }}>No indicators</div> : (
            <table style={{ width:'100%', fontSize:11, borderCollapse:'collapse' }}>
              <thead><tr style={{ borderBottom:'1px solid var(--border)' }}>
                {['Key','Group','Value','Signal','Source'].map(h => <th key={h} style={th}>{h}</th>)}
              </tr></thead>
              <tbody>{((Array.isArray(indicators) ? indicators : []) as any[]).map((i: any) => (
                <tr key={i.indicator_id} style={{ borderBottom:'1px solid var(--border)' }}>
                  <td style={{ ...td, fontWeight:600 }}>{i.indicator_key}</td>
                  <td style={td}>{i.indicator_group}</td>
                  <td style={td}>{i.value ?? i.value_text ?? '—'}</td>
                  <td style={td}>{dot(i.signal)}{i.signal}</td>
                  <td style={td}>{i.source_key}</td>
                </tr>
              ))}</tbody>
            </table>
          )}
        </Card>
      )}

      {tab === 'rotation' && (
        <Card title="Strategy Rotation Signals">
          {!(signals?.length) ? <div style={{ color:'#848e9c', padding:16 }}>No signals</div> : (
            <table style={{ width:'100%', fontSize:11, borderCollapse:'collapse' }}>
              <thead><tr style={{ borderBottom:'1px solid var(--border)' }}>
                {['Strategy','Signal','Strength','Confidence','Action','Reason'].map(h => <th key={h} style={th}>{h}</th>)}
              </tr></thead>
              <tbody>{((Array.isArray(signals) ? signals : []) as any[]).map((s: any) => (
                <tr key={s.signal_id} style={{ borderBottom:'1px solid var(--border)' }}>
                  <td style={{ ...td, fontWeight:600 }}>{s.strategy_id}</td>
                  <td style={td}>{dot(s.signal)}{s.signal}</td>
                  <td style={td}>{typeof s.signal_strength === 'number' ? s.signal_strength.toFixed(2) : '—'}</td>
                  <td style={td}>{s.confidence ? `${(Number(s.confidence)*100).toFixed(0)}%` : '—'}</td>
                  <td style={td}>{s.recommended_action}</td>
                  <td style={{ ...td, fontSize:10, maxWidth:250, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{s.reason}</td>
                </tr>
              ))}</tbody>
            </table>
          )}
        </Card>
      )}

      {tab === 'profiles' && (
        <Card title="Strategy Regime Profiles">
          {!(profiles?.length) ? <div style={{ color:'#848e9c', padding:16 }}>No profiles</div> : (
            <table style={{ width:'100%', fontSize:11, borderCollapse:'collapse' }}>
              <thead><tr style={{ borderBottom:'1px solid var(--border)' }}>
                {['Strategy','Favored','Disfavored','Vol','Trend','Horizon'].map(h => <th key={h} style={th}>{h}</th>)}
              </tr></thead>
              <tbody>{((Array.isArray(profiles) ? profiles : []) as any[]).map((p: any) => (
                <tr key={p.strategy_id} style={{ borderBottom:'1px solid var(--border)' }}>
                  <td style={{ ...td, fontWeight:600 }}>{p.strategy_id}</td>
                  <td style={{ ...td, fontSize:10 }}>{(p.favored_regimes||[]).join(', ')}</td>
                  <td style={{ ...td, fontSize:10 }}>{(p.disfavored_regimes||[]).join(', ')}</td>
                  <td style={td}>{p.volatility_preference}</td>
                  <td style={td}>{p.trend_preference}</td>
                  <td style={td}>{p.time_horizon}</td>
                </tr>
              ))}</tbody>
            </table>
          )}
        </Card>
      )}

      {tab === 'alignment' && (
        <Card title="Trade / Proposal Regime Alignment">
          {!(alignments?.length) ? <div style={{ color:'#848e9c', padding:16 }}>No alignments</div> : (
            <table style={{ width:'100%', fontSize:11, borderCollapse:'collapse' }}>
              <thead><tr style={{ borderBottom:'1px solid var(--border)' }}>
                {['Symbol','Strategy','Type','Alignment','Score','Regime','Reason'].map(h => <th key={h} style={th}>{h}</th>)}
              </tr></thead>
              <tbody>{((Array.isArray(alignments) ? alignments : []) as any[]).map((a: any) => (
                <tr key={a.alignment_id} style={{ borderBottom:'1px solid var(--border)' }}>
                  <td style={{ ...td, fontWeight:600 }}>{a.symbol}</td>
                  <td style={td}>{a.strategy_id}</td>
                  <td style={td}>{a.alignment_type}</td>
                  <td style={td}>{dot(a.alignment_label)}{a.alignment_label}</td>
                  <td style={td}>{a.alignment_score}</td>
                  <td style={td}>{a.regime_label}</td>
                  <td style={{ ...td, fontSize:10 }}>{(a.reason||'').slice(0,60)}</td>
                </tr>
              ))}</tbody>
            </table>
          )}
        </Card>
      )}
    </div>
  )
}
