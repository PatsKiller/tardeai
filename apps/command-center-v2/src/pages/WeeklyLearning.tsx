import { useState } from 'react'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import { useApi } from '../hooks/useApi'

const SC: Record<string, string> = {
  held:'#0ecb81', partially_held:'#f0b90b', failed:'#f6465d',
  unresolved:'#848e9c', invalidated_before_entry:'#848e9c',
  generated:'#0ecb81', draft:'#f0b90b', delivered:'#4a90f4',
}
const dot = (s: string) => <span style={{ display:'inline-block', width:8, height:8, borderRadius:4, background:SC[s]||'#848e9c', marginRight:6 }}/>
const btn: React.CSSProperties = { fontSize:10, padding:'4px 10px', border:'1px solid var(--border)', borderRadius:4, background:'var(--bg1)', color:'var(--text1)', cursor:'pointer' }
const n = (v: unknown, d=2) => typeof v === 'number' ? v.toFixed(d) : '—'

export default function WeeklyLearning() {
  const [rk, setRk] = useState(0)
  const [tab, setTab] = useState('digest')
  const { data: digests } = useApi<any>(`/api/v2/weekly-learning-digest?_r=${rk}`)
  const { data: latest } = useApi<any>(`/api/v2/weekly-learning-digest/latest?_r=${rk}`)
  const { data: reviews } = useApi<any>(`/api/v2/trade-thesis-reviews?_r=${rk}`)

  const d = latest?.data
  const tabBtn = (t: string, label: string) => (
    <button onClick={() => setTab(t)} style={{
      ...btn, background: tab === t ? 'var(--accent)' : 'var(--bg1)',
      color: tab === t ? '#fff' : 'var(--text1)'
    }}>{label}</button>
  )
  const th: React.CSSProperties = { padding:'6px 8px', textAlign:'left', color:'#848e9c', fontSize:10 }
  const td: React.CSSProperties = { padding:'6px 8px', fontSize:11 }

  return (
    <div style={{ padding:'16px 24px', maxWidth:1200 }}>
      <PageHeader title="Weekly Learning" subtitle="Digest, thesis reviews, lessons — operator review loop" actions={
        <button onClick={() => setRk(k=>k+1)} style={btn}>Refresh</button>
      }/>

      {d?.low_sample_size && (
        <div style={{ padding:'8px 14px', marginBottom:12, borderRadius:6,
          background:'rgba(240,185,11,.08)', border:'1px solid #f0b90b' }}>
          <span style={{ fontSize:12, fontWeight:700, color:'#f0b90b' }}>
            LOW SAMPLE SIZE — {d.paper_trades_closed} closed trades (need 30+)
          </span>
        </div>
      )}

      <div style={{ display:'flex', gap:6, marginBottom:16, flexWrap:'wrap' }}>
        {tabBtn('digest', 'Latest Digest')}
        {tabBtn('reviews', `Thesis Reviews (${(reviews?.data||[]).length})`)}
        {tabBtn('history', `Digest History (${(digests?.data||[]).length})`)}
      </div>

      {tab === 'digest' && (
        d ? (
          <Card title={`Digest: ${d.period_start} — ${d.period_end}`}>
            <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill, minmax(150px,1fr))', gap:8, marginBottom:12 }}>
              {[['Holdings', `$${(d.holdings_value||0).toLocaleString()}`],
                ['Closed', d.paper_trades_closed], ['WR', d.win_rate ? `${(Number(d.win_rate)*100).toFixed(0)}%` : '—'],
                ['PF', n(d.profit_factor)], ['Status', d.status],
              ].map(([l,v]) => (
                <div key={String(l)} style={{ padding:8, border:'1px solid var(--border)', borderRadius:4 }}>
                  <div style={{ fontSize:10, color:'#848e9c' }}>{String(l)}</div>
                  <div style={{ fontSize:16, fontWeight:700 }}>{String(v)}</div>
                </div>
              ))}
            </div>
            {d.top_lessons && (
              <div style={{ marginBottom:12 }}>
                <div style={{ fontSize:12, fontWeight:600, marginBottom:4 }}>Top Lessons</div>
                {(d.top_lessons as string[]).map((l: string, i: number) => (
                  <div key={i} style={{ fontSize:11, padding:'2px 0', color:'var(--text2)' }}>- {l}</div>
                ))}
              </div>
            )}
            {d.human_review_items && (d.human_review_items as any[]).length > 0 && (
              <div>
                <div style={{ fontSize:12, fontWeight:600, marginBottom:4, color:'#f0b90b' }}>
                  Pending Review ({(d.human_review_items as any[]).length})
                </div>
                {(d.human_review_items as any[]).map((item: any, i: number) => (
                  <div key={i} style={{ fontSize:11, padding:'2px 0' }}>- [{item.type}] {item.title}</div>
                ))}
              </div>
            )}
          </Card>
        ) : <Card title="Latest Digest">
          <div style={{ padding:16 }}>
            <div style={{ padding:'10px 14px', marginBottom:12, borderRadius:6, background:'rgba(240,185,11,.08)', border:'1px solid rgba(240,185,11,.3)' }}>
              <span style={{ fontSize:12, fontWeight:700, color:'#f0b90b' }}>NO DIGEST GENERATED</span>
              <div style={{ fontSize:10, color:'#848e9c', marginTop:4 }}>
                Weekly learning digests are generated from closed trade outcomes and agent recommendations.
                The system needs closed paper trades with scored outcomes to produce a meaningful digest.
              </div>
            </div>
            <div style={{ fontSize:10, color:'#848e9c' }}>
              <div><strong>Script:</strong> <code>scripts/weekly_learning_digest.py</code></div>
              <div><strong>Schedule:</strong> Manual (run weekly after trade review)</div>
              <div><strong>Status:</strong> Waiting for sufficient scored trade outcomes</div>
            </div>
          </div>
        </Card>
      )}

      {tab === 'reviews' && (
        <Card title="Trade Thesis Reviews">
          {!(reviews?.data?.length) ? <div style={{ color:'#848e9c', padding:16 }}>No thesis reviews yet. Run trade_thesis_review_engine.py</div> : (
            <table style={{ width:'100%', fontSize:11, borderCollapse:'collapse' }}>
              <thead><tr style={{ borderBottom:'1px solid var(--border)' }}>
                {['Trade','Symbol','Strategy','Status','Validity','Thesis','Exec','Risk','Agent','Outcome','Lesson'].map(h =>
                  <th key={h} style={th}>{h}</th>)}
              </tr></thead>
              <tbody>{(reviews.data as any[]).map((r: any) => (
                <tr key={r.review_id} style={{ borderBottom:'1px solid var(--border)' }}>
                  <td style={td}>#{r.paper_trade_id}</td>
                  <td style={{ ...td, fontWeight:600 }}>{r.symbol}</td>
                  <td style={td}>{r.strategy_id || '—'}</td>
                  <td style={td}>{r.trade_status}</td>
                  <td style={td}>{dot(r.thesis_validity)}{r.thesis_validity}</td>
                  <td style={td}>{n(r.thesis_score,0)}</td>
                  <td style={td}>{n(r.execution_score,0)}</td>
                  <td style={td}>{n(r.risk_management_score,0)}</td>
                  <td style={td}>{n(r.agent_alignment_score,0)}</td>
                  <td style={{ ...td, color: Number(r.outcome_score)>0?'#0ecb81':'#f6465d' }}>{n(r.outcome_score,0)}</td>
                  <td style={{ ...td, fontSize:10, maxWidth:200, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{r.lesson_summary}</td>
                </tr>
              ))}</tbody>
            </table>
          )}
        </Card>
      )}

      {tab === 'history' && (
        <Card title="Digest History">
          {!(digests?.data?.length) ? <div style={{ color:'#848e9c', padding:16 }}>No digests yet.</div> : (
            <table style={{ width:'100%', fontSize:11, borderCollapse:'collapse' }}>
              <thead><tr style={{ borderBottom:'1px solid var(--border)' }}>
                {['ID','Period','Status','Closed','WR','Low Sample','Generated'].map(h =>
                  <th key={h} style={th}>{h}</th>)}
              </tr></thead>
              <tbody>{(digests.data as any[]).map((d: any) => (
                <tr key={d.digest_id} style={{ borderBottom:'1px solid var(--border)' }}>
                  <td style={{ ...td, fontSize:9 }}>{d.digest_id?.slice(-12)}</td>
                  <td style={td}>{d.period_start}—{d.period_end}</td>
                  <td style={td}>{dot(d.status)}{d.status}</td>
                  <td style={td}>{d.paper_trades_closed}</td>
                  <td style={td}>{d.win_rate ? `${(Number(d.win_rate)*100).toFixed(0)}%` : '—'}</td>
                  <td style={td}>{d.low_sample_size ? 'Yes' : 'No'}</td>
                  <td style={{ ...td, fontSize:9 }}>{d.generated_at ? new Date(d.generated_at).toLocaleDateString() : ''}</td>
                </tr>
              ))}</tbody>
            </table>
          )}
        </Card>
      )}
    </div>
  )
}
