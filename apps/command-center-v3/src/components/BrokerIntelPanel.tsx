import { useState } from 'react'

const MUTED = '#94a3b8', TEXT0 = '#f8fafc', TEXT1 = '#dbeafe', GREEN = '#22c55e', AMBER = '#f59e0b', BLUE = '#60a5fa', RED = '#ef4444', PURPLE = '#a78bfa'
const sec = { fontSize: 9, fontWeight: 800, color: MUTED, textTransform: 'uppercase' as const, letterSpacing: '0.4px', marginBottom: 4 }
const body = { fontSize: 10, color: TEXT1, lineHeight: 1.45 }

function voteColor(vote: string | null | undefined) {
  const v = String(vote || '').toUpperCase()
  if (v === 'BLOCK' || v === 'REJECT') return RED
  if (v === 'APPROVE_TEST') return GREEN
  if (v === 'CAUTIOUS_TEST' || v === 'WAIT_FOR_DATA') return AMBER
  if (!v || v === 'PENDING') return MUTED
  return TEXT0
}

function cloudColor(status: string | null | undefined) {
  const s = String(status || '').toLowerCase()
  if (s === 'agree') return GREEN
  if (s === 'caution') return AMBER
  if (s === 'disagree') return RED
  if (s === 'running') return AMBER
  return MUTED
}

function criticColor(verdict: string | null | undefined) {
  const v = String(verdict || '').toUpperCase()
  if (v === 'BLOCK') return RED
  if (v === 'DOWNGRADE') return AMBER
  if (v === 'CONFIRM' || v === 'PASS') return GREEN
  return TEXT1
}

const VOTE_BUCKETS = [
  { key: 'strong_buy', label: 'Strong buy', color: '#16a34a' },
  { key: 'buy', label: 'Buy', color: '#4ade80' },
  { key: 'hold', label: 'Hold', color: '#94a3b8' },
  { key: 'sell', label: 'Sell', color: '#fb923c' },
  { key: 'strong_sell', label: 'Strong sell', color: '#ef4444' },
] as const

const SOURCE_LABELS: Record<string, string> = {
  yahoo: 'Yahoo',
  finviz: 'Finviz',
  pro_analyst: 'Pro-analyst',
  finnhub: 'Finnhub',
}

function coverageColor(cov: string | null | undefined) {
  const c = String(cov || '').toLowerCase()
  if (c === 'broad') return GREEN
  if (c === 'moderate') return BLUE
  if (c === 'thin') return AMBER
  return MUTED
}

function fmtRating(r: string | null | undefined) {
  return String(r || '—').replace(/_/g, ' ')
}

function AnalystSourceRow({ src, compact = false }: { src: any; compact?: boolean }) {
  const label = SOURCE_LABELS[src.source] || src.source || '—'
  const rating = fmtRating(src.rating)
  const ratingColor = String(src.rating || '').includes('buy') ? GREEN
    : String(src.rating || '').includes('sell') ? RED : TEXT0

  if (src.source === 'pro_analyst') {
    return (
      <div style={{ fontSize: 9.5, padding: '5px 0', borderBottom: '1px solid rgba(148,163,184,.08)' }}>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'baseline' }}>
          <b style={{ color: PURPLE, minWidth: 72 }}>{label}</b>
          <span style={{ color: TEXT1 }}>
            Internal <b style={{ color: src.internal_direction === 'bearish' ? RED : src.internal_direction === 'bullish' ? GREEN : TEXT0 }}>{src.internal_direction || '—'}</b>
            {' vs '}Street <b>{src.street_direction || '—'}</b>
            {src.divergence ? <span style={{ color: src.divergence === 'mixed' || src.divergence === 'divergent' ? AMBER : MUTED }}> · {src.divergence}</span> : null}
          </span>
          {src.confidence && <span style={{ color: String(src.confidence).toLowerCase() === 'low' ? AMBER : MUTED }}>conf {src.confidence}</span>}
        </div>
        {src.target != null && (
          <div style={{ fontSize: 9, color: MUTED, marginTop: 2, fontFamily: 'monospace' }}>
            Target ${src.target}
            {src.upside_pct != null && <span style={{ color: src.upside_pct >= 0 ? GREEN : RED, marginLeft: 6 }}>{src.upside_pct >= 0 ? '+' : ''}{src.upside_pct}%</span>}
            {src.opinions != null ? ` · ${src.opinions} analyst${src.opinions === 1 ? '' : 's'}` : ''}
          </div>
        )}
        {src.latest_event && (
          <div style={{ fontSize: 9, color: AMBER, marginTop: 3 }}>
            Latest: {src.latest_event_type ? `${src.latest_event_type.replace(/_/g, ' ')} — ` : ''}{String(src.latest_event).slice(0, compact ? 100 : 180)}
            {src.latest_event_at ? <span style={{ color: MUTED }}> · {String(src.latest_event_at).slice(0, 10)}</span> : null}
          </div>
        )}
      </div>
    )
  }

  return (
    <div style={{ fontSize: 9.5, padding: '5px 0', borderBottom: '1px solid rgba(148,163,184,.08)' }}>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'baseline' }}>
        <b style={{ color: label === 'Yahoo' ? BLUE : TEXT0, minWidth: 72 }}>{label}</b>
        <span style={{ color: ratingColor, fontWeight: 700, fontFamily: 'monospace' }}>{rating}</span>
        {src.opinions != null && <span style={{ color: MUTED }}>{src.opinions} analyst{src.opinions === 1 ? '' : 's'}</span>}
        {src.recom_score != null && <span style={{ color: MUTED, fontFamily: 'monospace' }}>score {Number(src.recom_score).toFixed(2)}</span>}
        {src.mean != null && <span style={{ color: MUTED, fontFamily: 'monospace' }}>mean {src.mean}</span>}
      </div>
      {(src.target != null || src.upside_pct != null) && (
        <div style={{ fontSize: 9, color: MUTED, marginTop: 2, fontFamily: 'monospace' }}>
          {src.target != null && <>Target <b style={{ color: BLUE }}>${src.target}</b></>}
          {src.upside_pct != null && (
            <span style={{ color: src.upside_pct >= 0 ? GREEN : RED, marginLeft: src.target != null ? 6 : 0 }}>
              {src.upside_pct >= 0 ? '+' : ''}{src.upside_pct}% vs current
            </span>
          )}
          {(src.target_low != null || src.target_high != null) && (
            <span style={{ marginLeft: 6 }}>range ${src.target_low ?? '—'} – ${src.target_high ?? '—'}</span>
          )}
        </div>
      )}
    </div>
  )
}

function AnalystVoteBar({ dist }: { dist: Record<string, number> }) {
  const total = VOTE_BUCKETS.reduce((s, b) => s + (Number(dist[b.key]) || 0), 0)
  if (!total) return null
  return (
    <div style={{ marginTop: 8 }}>
      <div style={{ display: 'flex', height: 8, borderRadius: 4, overflow: 'hidden', background: 'rgba(15,23,42,.6)' }}>
        {VOTE_BUCKETS.map(b => {
          const n = Number(dist[b.key]) || 0
          if (!n) return null
          return (
            <div key={b.key} title={`${b.label}: ${n}`}
              style={{ width: `${(n / total) * 100}%`, background: b.color, minWidth: n ? 4 : 0 }} />
          )
        })}
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px 10px', marginTop: 6, fontSize: 8.5, color: MUTED }}>
        {VOTE_BUCKETS.map(b => {
          const n = Number(dist[b.key]) || 0
          if (!n) return null
          return (
            <span key={b.key}><span style={{ color: b.color, fontWeight: 700 }}>{n}</span> {b.label}</span>
          )
        })}
      </div>
    </div>
  )
}

function CatalystCritic({ cat, compact }: { cat: any; compact: boolean }) {
  const [open, setOpen] = useState(!compact && ['BLOCK', 'DOWNGRADE'].includes(String(cat.critic_verdict || '').toUpperCase()))
  const reasoning = cat.critic_reasoning ? String(cat.critic_reasoning).trim() : ''
  const previewLen = compact ? 140 : 220
  const preview = reasoning.slice(0, previewLen)
  const hasMore = reasoning.length > previewLen

  return (
    <>
      {cat.critic_verdict && (
        <div style={{ fontSize: 9, color: criticColor(cat.critic_verdict), marginTop: 4, fontWeight: 700 }}>
          Critic: {cat.critic_verdict}
        </div>
      )}
      {reasoning ? (
        <div style={{ marginTop: 6 }}>
          <div style={{ fontSize: 9, color: MUTED, marginBottom: 3 }}>Catalyst review</div>
          <div style={{ ...body, fontSize: 9.5, color: TEXT1 }}>
            {open ? reasoning : (hasMore ? `${preview}…` : reasoning)}
          </div>
          {hasMore && (
            <button type="button" onClick={() => setOpen(v => !v)}
              style={{ marginTop: 4, fontSize: 9, fontWeight: 700, padding: 0, border: 'none', background: 'transparent', color: BLUE, cursor: 'pointer' }}>
              {open ? 'Show less' : 'Show full critic review'}
            </button>
          )}
        </div>
      ) : cat.critic_verdict ? (
        <div style={{ fontSize: 9, color: MUTED, marginTop: 4, fontStyle: 'italic' }}>No critic narrative stored for this scan.</div>
      ) : null}
    </>
  )
}

type Props = {
  intel?: any
  compact?: boolean
  onQueueOversight?: () => void
  onRunCloudOversight?: () => void
  oversightBusy?: boolean
  cloudBusy?: boolean
}

export default function BrokerIntelPanel({
  intel, compact = false, onQueueOversight, onRunCloudOversight, oversightBusy, cloudBusy,
}: Props) {
  if (!intel?.ok) {
    return (
      <div style={{ padding: compact ? '6px 0' : '10px 12px', fontSize: 10, color: MUTED, fontStyle: 'italic' }}>
        Decision context not loaded — run Enrich on the paper proposal or refresh.
      </div>
    )
  }

  const co = intel.company || {}
  const cat = intel.catalyst || {}
  const tech = intel.technicals || {}
  const an = intel.analyst
  const why = intel.why_purchase || {}
  const reviews: any[] = intel.agent_reviews || []
  const news: any[] = intel.news || []
  const oversight = intel.oversight || {}
  const ovAgents = oversight.agents || {}
  const localLlm = oversight.local_llm || {}
  const cloud = oversight.cloud_review || {}
  const lanes = oversight.lanes_available || {}
  const ovViolations: string[] = oversight.violations || []
  const ovWarnings: string[] = oversight.warnings || []
  const ovStatus = oversight.status || (ovViolations.length ? 'BLOCK' : ovWarnings.length ? 'WARN' : reviews.length ? 'PENDING' : null)
  const showOversight = Boolean(ovStatus || reviews.length > 0 || onQueueOversight || onRunCloudOversight || ovViolations.length || ovWarnings.length)
  const dist = an?.distribution as Record<string, number> | null | undefined
  const hasDist = dist && VOTE_BUCKETS.some(b => Number(dist[b.key]) > 0)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: compact ? 8 : 10 }}>
      {showOversight && (
        <div style={{ padding: '8px 10px', borderRadius: 8, background: 'rgba(168,85,247,.06)', border: '1px solid rgba(168,85,247,.22)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6, flexWrap: 'wrap', gap: 6 }}>
            <div style={{ ...sec, color: PURPLE, marginBottom: 0 }}>AI oversight {ovStatus ? `· ${ovStatus}` : ''}</div>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {onQueueOversight && (
                <button type="button" onClick={onQueueOversight} disabled={oversightBusy}
                  style={{ fontSize: 9, fontWeight: 700, padding: '4px 8px', borderRadius: 5, border: `1px solid ${BLUE}`, background: 'rgba(96,165,250,.1)', color: BLUE, cursor: oversightBusy ? 'wait' : 'pointer' }}>
                  {oversightBusy ? 'Queuing…' : 'Queue local reviews'}
                </button>
              )}
              {onRunCloudOversight && (
                <button type="button" onClick={onRunCloudOversight} disabled={cloudBusy || cloud.status === 'running'}
                  style={{ fontSize: 9, fontWeight: 700, padding: '4px 8px', borderRadius: 5, border: `1px solid ${PURPLE}`, background: 'rgba(168,85,247,.12)', color: PURPLE, cursor: (cloudBusy || cloud.status === 'running') ? 'wait' : 'pointer' }}>
                  {(cloudBusy || cloud.status === 'running') ? 'Cloud running…' : 'Re-run Grok+ChatGPT'}
                </button>
              )}
            </div>
          </div>

          <div style={{ fontSize: 9.5, color: TEXT1, marginBottom: 6 }}>
            Local: <span style={{ color: localLlm.status === 'complete' ? GREEN : localLlm.status === 'queued' ? AMBER : MUTED }}>
              {localLlm.status || 'unknown'}
            </span>
            {localLlm.model ? ` (${localLlm.model})` : ''}
            {' · '}
            Cloud: <span style={{ color: cloudColor(cloud.status) }}>{cloud.status || 'not_run'}</span>
            {cloud.ran_at ? ` · ${cloud.ran_at}` : ''}
            {(lanes.grok || lanes.chatgpt) && (
              <span style={{ color: MUTED }}> · lanes: {[lanes.grok && 'Grok', lanes.chatgpt && 'ChatGPT'].filter(Boolean).join(', ')}</span>
            )}
          </div>

          {(ovAgents.pending?.length > 0) && (
            <div style={{ fontSize: 9, color: AMBER, marginBottom: 4 }}>Pending agents: {ovAgents.pending.join(', ')}</div>
          )}

          {reviews.map((r, i) => {
            const pending = !r.verdict && (r.status === 'pending' || !r.status)
            return (
            <div key={i} style={{ fontSize: 9.5, marginBottom: 4, paddingLeft: 6, borderLeft: `2px solid ${voteColor(r.verdict || (pending ? 'PENDING' : ''))}` }}>
              <b style={{ color: TEXT0 }}>{r.agent}</b>
              <span style={{ color: pending ? AMBER : MUTED }}> · {r.status || (pending ? 'pending' : '—')}</span>
              {r.verdict && <span style={{ color: voteColor(r.verdict) }}> · {r.verdict}</span>}
              {r.model && <span style={{ color: MUTED }}> · {r.model}</span>}
              {r.summary && <div style={{ color: TEXT1, marginTop: 2 }}>{r.summary}</div>}
            </div>
          )})}

          {cloud.lanes && Object.keys(cloud.lanes).length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 6 }}>
              {Object.entries(cloud.lanes).map(([lane, lr]: [string, any]) => (
                <div key={lane} style={{ fontSize: 9.5, padding: '4px 8px', borderRadius: 5, background: 'rgba(15,23,42,.5)', borderLeft: `3px solid ${cloudColor(lr?.verdict)}` }}>
                  <b style={{ color: lane === 'grok' ? '#1d9bf0' : lane === 'chatgpt' ? '#10a37f' : TEXT0 }}>
                    {lane === 'grok' ? 'Grok' : lane === 'chatgpt' ? 'ChatGPT' : lane}
                  </b>
                  <span style={{ color: cloudColor(lr?.verdict), marginLeft: 6, fontWeight: 800 }}>
                    {lr?.ok ? (lr?.verdict || '—') : 'unavailable'}
                  </span>
                  {lr?.assessment && <div style={{ color: TEXT1, marginTop: 2 }}>{String(lr.assessment).slice(0, compact ? 120 : 220)}</div>}
                  {(lr?.concerns?.length > 0) && (
                    <div style={{ color: AMBER, marginTop: 2 }}>⚠ {lr.concerns.slice(0, 2).join(' · ')}</div>
                  )}
                </div>
              ))}
            </div>
          )}

          {cloud.consensus && (
            <div style={{ fontSize: 9, color: cloudColor(cloud.status), marginTop: 6, fontWeight: 700 }}>
              Consensus: {cloud.consensus.verdict}
              {cloud.consensus.lanes_ok != null ? ` · ${cloud.consensus.lanes_ok} lane(s) OK` : ''}
            </div>
          )}

          {ovViolations.map((v, i) => <div key={`v${i}`} style={{ fontSize: 9, color: RED, marginTop: 3 }}>⛔ {v}</div>)}
          {ovWarnings.map((w, i) => <div key={`w${i}`} style={{ fontSize: 9, color: AMBER, marginTop: 3 }}>⚠ {w}</div>)}
        </div>
      )}

      {co.description && (
        <div>
          <div style={sec}>What the company does</div>
          <div style={body}>{co.description}</div>
          {(co.sector || co.industry) && (
            <div style={{ fontSize: 9, color: MUTED, marginTop: 3 }}>{[co.sector, co.industry].filter(Boolean).join(' · ')}</div>
          )}
        </div>
      )}

      {(why.headline || why.approve_case || why.strategy_purpose) && (
        <div style={{ padding: '8px 10px', borderRadius: 8, background: 'rgba(34,197,94,.08)', border: '1px solid rgba(34,197,94,.2)' }}>
          <div style={{ ...sec, color: GREEN }}>Why purchase</div>
          {why.strategy_purpose && <div style={{ fontSize: 9, color: MUTED, marginBottom: 4 }}>Strategy: {why.strategy_purpose}</div>}
          <div style={body}>{why.headline || why.approve_case || why.summary}</div>
          {why.rr != null && <div style={{ fontSize: 9, color: MUTED, marginTop: 4 }}>Plan R:R {why.rr}:1{why.signal_grade ? ` · ${why.signal_grade} grade` : ''}</div>}
          {why.invalidation && <div style={{ fontSize: 9, color: AMBER, marginTop: 4 }}>Invalidate if: {why.invalidation}</div>}
          {why.reject_case && <div style={{ fontSize: 9, color: RED, marginTop: 4 }}>Bear case: {String(why.reject_case).slice(0, 200)}</div>}
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: compact ? '1fr' : '1fr 1fr', gap: 8 }}>
        {(cat.text || cat.critic_verdict || cat.critic_reasoning) && (
          <div style={{ padding: '8px 10px', borderRadius: 8, background: 'rgba(245,158,11,.06)', border: '1px solid rgba(245,158,11,.2)' }}>
            <div style={sec}>Catalyst {cat.verified ? '✅' : '⚠️'}</div>
            <div style={body}>{cat.text ? String(cat.text).slice(0, compact ? 220 : 400) : '—'}</div>
            {cat.confidence != null && <div style={{ fontSize: 9, color: MUTED, marginTop: 3 }}>Confidence {cat.confidence}%</div>}
            <CatalystCritic cat={cat} compact={compact} />
          </div>
        )}

        {(tech.summary || tech.rsi != null) && (
          <div style={{ padding: '8px 10px', borderRadius: 8, background: 'rgba(96,165,250,.06)', border: '1px solid rgba(96,165,250,.2)' }}>
            <div style={sec}>Technicals</div>
            <div style={{ ...body, fontFamily: 'monospace', fontSize: 10 }}>{tech.summary || '—'}</div>
            {tech.technical_grade && <div style={{ fontSize: 9, color: MUTED, marginTop: 3 }}>Grade: {tech.technical_grade}{tech.confluence_tier ? ` · ${tech.confluence_tier}` : ''}</div>}
          </div>
        )}
      </div>

      {an && (
        <div style={{ padding: '8px 10px', borderRadius: 8, background: 'rgba(15,23,42,.5)', border: '1px solid rgba(148,163,184,.15)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 6, marginBottom: 4 }}>
            <div style={{ ...sec, marginBottom: 0 }}>
              Analyst consensus
              {an.quality?.source_count ? ` · ${an.quality.source_count} source${an.quality.source_count === 1 ? '' : 's'}` : ''}
            </div>
            {an.quality?.coverage && (
              <span style={{ fontSize: 8.5, fontWeight: 800, padding: '2px 7px', borderRadius: 4, background: `${coverageColor(an.quality.coverage)}18`, color: coverageColor(an.quality.coverage) }}>
                {String(an.quality.coverage).toUpperCase()} COVERAGE
              </span>
            )}
          </div>

          <div style={{ fontSize: 11, fontWeight: 700, color: String(an.rating || '').includes('buy') ? GREEN : TEXT0, fontFamily: 'monospace' }}>
            {fmtRating(an.rating)}
            {an.opinions != null ? ` · ${an.opinions} analyst${an.opinions === 1 ? '' : 's'}` : ''}
            {an.mean != null ? ` · score ${an.mean}` : ''}
            {an.primary_source && <span style={{ fontSize: 9, color: MUTED, fontWeight: 500 }}> ({SOURCE_LABELS[an.primary_source] || an.primary_source})</span>}
          </div>
          <div style={{ fontSize: 10, color: TEXT1, marginTop: 5, fontFamily: 'monospace' }}>
            {an.target != null && <span>Mean target <b style={{ color: BLUE }}>${an.target}</b></span>}
            {an.upside_pct != null && (
              <span style={{ color: an.upside_pct >= 0 ? GREEN : RED, marginLeft: 8 }}>
                {an.upside_pct >= 0 ? '+' : ''}{an.upside_pct}% vs current
              </span>
            )}
          </div>
          {(an.target_low != null || an.target_high != null) && (
            <div style={{ fontSize: 9, color: MUTED, marginTop: 4 }}>
              Street range ${an.target_low ?? '—'} – ${an.target_high ?? '—'}
            </div>
          )}

          {(an.quality?.warnings?.length > 0) && (
            <div style={{ marginTop: 6 }}>
              {an.quality.warnings.map((w: string, i: number) => (
                <div key={i} style={{ fontSize: 9, color: AMBER, marginTop: i ? 2 : 0 }}>⚠ {w}</div>
              ))}
            </div>
          )}

          {an.opinions === 1 && (
            <div style={{ fontSize: 9, color: AMBER, marginTop: 6, padding: '5px 8px', borderRadius: 6, background: 'rgba(245,158,11,.08)', border: '1px solid rgba(245,158,11,.2)' }}>
              Single-analyst coverage is unreliable for micro-caps — treat street target as directional only, not a sizing input.
            </div>
          )}

          {(an.sources?.length > 1) && (
            <div style={{ marginTop: 8 }}>
              <div style={{ fontSize: 9, color: MUTED, marginBottom: 2 }}>Sources</div>
              {an.sources.map((src: any, i: number) => (
                <AnalystSourceRow key={`${src.source}-${i}`} src={src} compact={compact} />
              ))}
            </div>
          )}

          {hasDist ? (
            <>
              <div style={{ fontSize: 9, color: MUTED, marginTop: 6 }}>Analyst vote distribution{an.sources?.[0]?.distribution_provider ? ` (${an.sources[0].distribution_provider})` : ''}</div>
              <AnalystVoteBar dist={dist!} />
            </>
          ) : (
            <div style={{ fontSize: 9, color: MUTED, marginTop: 6, fontStyle: 'italic' }}>
              Vote breakdown not loaded — rating/target from {an.sources?.length ? an.sources.map((s: any) => SOURCE_LABELS[s.source] || s.source).join(', ') : 'Yahoo'}.
            </div>
          )}
        </div>
      )}

      {news.length > 0 && (
        <div>
          <div style={sec}>Recent news</div>
          {news.slice(0, compact ? 2 : 3).map((n, i) => (
            <div key={i} style={{ fontSize: 9, color: TEXT1, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              <span style={{ color: MUTED }}>{n.source} · </span>{n.title}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}