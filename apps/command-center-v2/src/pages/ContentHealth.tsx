import { useState, useEffect, useMemo } from 'react'

interface Channel {
  channel_name: string; channel_id: string; category: string; priority: string
  agent_tags: string[]; active: boolean; auto_promote_threshold: number
  transcript_count: number; promoted_count: number; avg_quality: number
}

type HealthStatus = 'HEALTHY' | 'BELOW_THRESHOLD' | 'NO_TRANSCRIPTS'

function getStatus(ch: Channel): HealthStatus {
  if (ch.transcript_count === 0) return 'NO_TRANSCRIPTS'
  if (ch.avg_quality < (ch.auto_promote_threshold || 70)) return 'BELOW_THRESHOLD'
  return 'HEALTHY'
}

const STATUS_ORDER: Record<HealthStatus, number> = { BELOW_THRESHOLD: 0, NO_TRANSCRIPTS: 1, HEALTHY: 2 }
const STATUS_COLOR: Record<HealthStatus, string> = { HEALTHY: '#00ff88', BELOW_THRESHOLD: '#ffaa00', NO_TRANSCRIPTS: '#5a7fa8' }
const CAT_COLOR: Record<string, string> = {
  disability_retirement: '#aa55ff', retirement_planning: '#4499ff', tax_strategy: '#ffaa00',
  dividend_income: '#00cc88', macro_economics: '#ff6644', etf_indexing: '#00d4ff',
  investment_general: '#7a9cc8', financial_education: '#888', trust_estate: '#aa55ff',
}

interface Mismatch { channel_name: string; tx_count: number }

export default function ContentHealth() {
  const [data, setData] = useState<{ channels: Channel[]; name_mismatches?: Mismatch[]; orphan_tx_count?: number } | null>(null)
  const [loading, setLoading] = useState(true)
  const [guideOpen, setGuideOpen] = useState(false)
  const [flagged, setFlagged] = useState<Set<string>>(new Set())
  const [flagging, setFlagging] = useState<string | null>(null)
  const [fixingNames, setFixingNames] = useState(false)
  const [fixingOrphans, setFixingOrphans] = useState(false)
  const [adminMsg, setAdminMsg] = useState('')

  const reload = () => {
    fetch('/api/v2/youtube-audit').then(r => r.json())
      .then(d => { if (d.ok) setData(d.data) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }

  useEffect(() => { setLoading(true); reload() }, [])

  const channels = data?.channels || []

  const sorted = useMemo(() =>
    [...channels].sort((a, b) => STATUS_ORDER[getStatus(a)] - STATUS_ORDER[getStatus(b)] || a.channel_name.localeCompare(b.channel_name)),
    [channels])

  const healthy = channels.filter(c => getStatus(c) === 'HEALTHY').length
  const below = channels.filter(c => getStatus(c) === 'BELOW_THRESHOLD').length
  const noTx = channels.filter(c => getStatus(c) === 'NO_TRANSCRIPTS').length

  const handleFlag = async (ch: Channel) => {
    setFlagging(ch.channel_name)
    try {
      const res = await fetch('/api/v2/iris/hygiene-flag', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          channel_name: ch.channel_name, category: ch.category,
          avg_quality: ch.avg_quality, threshold: ch.auto_promote_threshold,
          reason: getStatus(ch) === 'NO_TRANSCRIPTS' ? 'no_transcripts_30d' : 'below_threshold',
        }),
      })
      const d = await res.json()
      if (d.ok) setFlagged(s => new Set(s).add(ch.channel_name))
    } catch {}
    finally { setFlagging(null) }
  }

  const handleFixNames = async () => {
    setFixingNames(true); setAdminMsg('')
    try {
      const r = await fetch('/api/v2/admin/fix-channel-name-mismatches', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
      const d = await r.json()
      if (d.ok) { setAdminMsg(`Fixed ${d.data?.fixes_applied || d.fixes_applied || 0} name mappings`); reload() }
    } catch {} finally { setFixingNames(false) }
  }

  const handleFixOrphans = async () => {
    setFixingOrphans(true); setAdminMsg('')
    try {
      const r = await fetch('/api/v2/admin/flag-orphan-transcripts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
      const d = await r.json()
      if (d.ok) { setAdminMsg(`Flagged ${d.data?.rows_flagged || d.rows_flagged || 0} orphan transcripts`); reload() }
    } catch {} finally { setFixingOrphans(false) }
  }

  if (loading) return <div style={{ padding: 40, color: '#5a7fa8', textAlign: 'center' }}>Loading content health...</div>

  return (
    <div style={{ padding: 24, color: '#c8daf5', fontFamily: 'system-ui, sans-serif', maxWidth: 1200, margin: '0 auto' }}>
      <h1 style={{ fontSize: 22, fontWeight: 700, color: '#fff', marginBottom: 4 }}>Content Health Dashboard</h1>
      <div style={{ fontSize: 13, color: '#5a7fa8', marginBottom: 20 }}>YouTube channel quality monitoring &middot; {channels.length} channels</div>

      {/* Section 1: Summary tiles */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 10, marginBottom: 12 }}>
        <Tile label="Healthy" value={healthy} color="#00ff88" />
        <Tile label="Below Threshold" value={below} color="#ffaa00" />
        <Tile label="No Transcripts" value={noTx} color="#5a7fa8" />
        <Tile label="Name Mismatches" value={data?.name_mismatches?.length || 0} color="#aa55ff" />
        <Tile label="Orphan Transcripts" value={data?.orphan_tx_count || 0} color="#ff6644" />
        <Tile label="Total Channels" value={channels.length} color="#c8daf5" />
      </div>
      {/* Admin actions */}
      {((data?.name_mismatches?.length || 0) > 0 || (data?.orphan_tx_count || 0) > 0) && (
        <div style={{ display: 'flex', gap: 8, marginBottom: 16, alignItems: 'center' }}>
          {(data?.name_mismatches?.length || 0) > 0 && (
            <button onClick={handleFixNames} disabled={fixingNames} style={{ fontSize: 10, padding: '5px 12px', borderRadius: 4, border: '1px solid rgba(170,85,255,.3)', background: 'rgba(170,85,255,.08)', color: '#aa55ff', cursor: 'pointer' }}>
              {fixingNames ? 'Fixing...' : `Fix ${data?.name_mismatches?.length} Name Mismatches`}
            </button>
          )}
          {(data?.orphan_tx_count || 0) > 0 && (
            <button onClick={handleFixOrphans} disabled={fixingOrphans} style={{ fontSize: 10, padding: '5px 12px', borderRadius: 4, border: '1px solid rgba(255,102,68,.3)', background: 'rgba(255,102,68,.08)', color: '#ff6644', cursor: 'pointer' }}>
              {fixingOrphans ? 'Flagging...' : `Flag ${data?.orphan_tx_count} Orphan Transcripts`}
            </button>
          )}
          {adminMsg && <span style={{ fontSize: 10, color: '#00ff88' }}>{adminMsg}</span>}
        </div>
      )}

      {/* Section 2: Scoring guide (collapsible) */}
      <div style={{ ...card, marginBottom: 16 }}>
        <button onClick={() => setGuideOpen(!guideOpen)} style={{ background: 'none', border: 'none', color: '#5a7fa8', cursor: 'pointer', fontSize: 11, fontFamily: "'JetBrains Mono', monospace", textTransform: 'uppercase', letterSpacing: 2, display: 'flex', alignItems: 'center', gap: 6, padding: 0, width: '100%' }}>
          <span>{guideOpen ? '\u25BC' : '\u25B6'}</span> How quality scores work
        </button>
        {guideOpen && (
          <div style={{ marginTop: 12, fontSize: 11 }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', marginBottom: 14 }}>
              <thead><tr style={{ borderBottom: '1px solid #1e3050', color: '#5a7fa8', textAlign: 'left' }}>
                <th style={{ padding: '6px 8px', fontSize: 10 }}>What adds points</th><th style={{ padding: '6px 8px', fontSize: 10 }}>Amount</th>
              </tr></thead>
              <tbody>
                {[['Base score', '50 pts'], ['Content length (5k+ words)', '+3 to +12'], ['Current year in title', '+4 to +8'],
                  ['SSDI / disability keywords', '+8 to +12'], ['IRMAA / special needs trust', '+8 to +10'],
                  ['Multi-agent content', '+4 to +6'], ['Channel category bonus', '+3 to +10']].map(([w, a]) => (
                  <tr key={w} style={{ borderBottom: '1px solid #0f1520' }}>
                    <td style={{ padding: '5px 8px', color: '#c8daf5' }}>{w}</td>
                    <td style={{ padding: '5px 8px', color: '#00d4ff', fontFamily: "'JetBrains Mono', monospace" }}>{a}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div style={{ fontSize: 10, fontWeight: 700, color: '#5a7fa8', textTransform: 'uppercase', letterSpacing: 2, marginBottom: 6 }}>Promotion thresholds by category</div>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 14 }}>
              {[['disability_retirement', 55], ['trust_estate', 55], ['retirement_planning', 60], ['roth_conversion', 60],
                ['tax_strategy', 60], ['dividend_income', 65], ['macro_economics', 65], ['investment_general', 70]].map(([c, t]) => (
                <span key={c as string} style={{ fontSize: 10, padding: '3px 8px', borderRadius: 4, background: `${CAT_COLOR[c as string] || '#5a7fa8'}15`, border: `1px solid ${CAT_COLOR[c as string] || '#5a7fa8'}30`, color: CAT_COLOR[c as string] || '#5a7fa8' }}>
                  {(c as string).replace(/_/g, ' ')} Q{'\u2265'}{t as number}
                </span>
              ))}
            </div>
            <div style={{ fontSize: 10, color: '#5a7fa8', lineHeight: 1.6 }}>
              <strong>UNSCORED</strong> = tagger hasn't run yet &middot; <strong>AI_VALIDATED</strong> = LLM confirmed tags &middot; <strong>PROMOTED</strong> = on whiteboard (L4) &middot; <strong>ARCHIVED</strong> = Iris hygiene moved out
            </div>
          </div>
        )}
      </div>

      {/* Section 3: Channel health table */}
      <div style={card}>
        <div style={{ fontSize: 11, fontFamily: "'JetBrains Mono', monospace", textTransform: 'uppercase', letterSpacing: 2, color: '#5a7fa8', marginBottom: 12 }}>Channel Health ({sorted.length})</div>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #1e3050', color: '#5a7fa8', textAlign: 'left' }}>
                {['Channel', 'Category', 'Transcripts', 'Avg Quality', 'Threshold', 'Promoted', 'Status', 'Action'].map(h => (
                  <th key={h} style={{ padding: '8px 6px', fontSize: 10, fontFamily: "'JetBrains Mono', monospace", textTransform: 'uppercase', letterSpacing: 1 }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.map(ch => {
                const status = getStatus(ch)
                const gap = ch.auto_promote_threshold - ch.avg_quality
                const promoPct = ch.transcript_count > 0 ? Math.round(ch.promoted_count / ch.transcript_count * 100) : 0
                const isFlagged = flagged.has(ch.channel_name)
                return (
                  <tr key={ch.channel_id} style={{ borderBottom: '1px solid #0f1520' }}>
                    <td style={{ padding: '7px 6px', color: '#c8daf5', fontWeight: 600 }}>{ch.channel_name}</td>
                    <td style={{ padding: '7px 6px' }}>
                      <span style={{ fontSize: 9, padding: '2px 6px', borderRadius: 3, background: `${CAT_COLOR[ch.category] || '#5a7fa8'}15`, color: CAT_COLOR[ch.category] || '#5a7fa8' }}>
                        {ch.category?.replace(/_/g, ' ') || '?'}
                      </span>
                    </td>
                    <td style={{ padding: '7px 6px', color: ch.transcript_count > 0 ? '#c8daf5' : '#3a5a80', textAlign: 'right' }}>{ch.transcript_count}</td>
                    <td style={{ padding: '7px 6px', textAlign: 'right' }}>
                      <span style={{ color: status === 'HEALTHY' ? '#00ff88' : status === 'BELOW_THRESHOLD' ? '#ffaa00' : '#3a5a80', fontWeight: 700 }}>
                        {ch.avg_quality > 0 ? ch.avg_quality.toFixed(1) : '\u2014'}
                      </span>
                      {ch.transcript_count > 0 && (
                        <div style={{ height: 3, background: '#1e3050', borderRadius: 2, marginTop: 3, overflow: 'hidden' }}>
                          <div style={{ height: '100%', width: `${Math.min(ch.avg_quality, 100)}%`, background: status === 'HEALTHY' ? '#00ff88' : '#ffaa00', borderRadius: 2 }} />
                        </div>
                      )}
                    </td>
                    <td style={{ padding: '7px 6px', color: '#5a7fa8', textAlign: 'right', fontFamily: "'JetBrains Mono', monospace" }}>Q{'\u2265'}{ch.auto_promote_threshold || 70}</td>
                    <td style={{ padding: '7px 6px', color: '#7a9cc8', textAlign: 'right' }}>
                      {ch.transcript_count > 0 ? `${ch.promoted_count}/${ch.transcript_count}` : '\u2014'}
                      {promoPct > 0 && <span style={{ color: '#5a7fa8', marginLeft: 4, fontSize: 9 }}>({promoPct}%)</span>}
                    </td>
                    <td style={{ padding: '7px 6px' }}>
                      <span style={{ fontSize: 9, fontWeight: 700, padding: '2px 8px', borderRadius: 3, background: `${STATUS_COLOR[status]}15`, color: STATUS_COLOR[status] }}>
                        {status === 'HEALTHY' ? 'HEALTHY' : status === 'BELOW_THRESHOLD' ? `BELOW (needs +${gap.toFixed(1)})` : 'NO TRANSCRIPTS'}
                      </span>
                    </td>
                    <td style={{ padding: '7px 6px' }}>
                      {status === 'HEALTHY' ? (
                        <span style={{ color: '#00ff88', fontSize: 11 }}>{'\u2713'}</span>
                      ) : isFlagged ? (
                        <span style={{ fontSize: 9, color: '#ffaa00' }}>Flagged {'\u2713'}</span>
                      ) : (
                        <button onClick={() => handleFlag(ch)} disabled={flagging === ch.channel_name}
                          style={{ fontSize: 9, padding: '3px 8px', borderRadius: 4, border: '1px solid rgba(255,170,0,.3)', background: 'rgba(255,170,0,.08)', color: '#ffaa00', cursor: 'pointer' }}>
                          {flagging === ch.channel_name ? '...' : 'Flag for Review'}
                        </button>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

function Tile({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div style={{ ...card, marginBottom: 0 }}>
      <div style={{ fontSize: 9, color: '#5a7fa8', fontFamily: "'JetBrains Mono', monospace", textTransform: 'uppercase', letterSpacing: 1, marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: 28, fontWeight: 700, color }}>{value}</div>
    </div>
  )
}

const card: React.CSSProperties = { background: '#0f1520', border: '1px solid #1e3050', borderRadius: 10, padding: 16, marginBottom: 16 }
