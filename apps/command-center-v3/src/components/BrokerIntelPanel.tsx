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
  return MUTED
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
                <button type="button" onClick={onRunCloudOversight} disabled={cloudBusy}
                  style={{ fontSize: 9, fontWeight: 700, padding: '4px 8px', borderRadius: 5, border: `1px solid ${PURPLE}`, background: 'rgba(168,85,247,.12)', color: PURPLE, cursor: cloudBusy ? 'wait' : 'pointer' }}>
                  {cloudBusy ? 'Running Grok+ChatGPT…' : 'Run Grok+ChatGPT'}
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

          {cloud.consensus && (
            <div style={{ fontSize: 9, color: cloudColor(cloud.status), marginTop: 4 }}>
              Cloud consensus: {cloud.consensus.verdict}
              {cloud.consensus.lanes_ok != null ? ` (${cloud.consensus.lanes_ok} lanes)` : ''}
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
        {(cat.text || cat.critic_verdict) && (
          <div style={{ padding: '8px 10px', borderRadius: 8, background: 'rgba(245,158,11,.06)', border: '1px solid rgba(245,158,11,.2)' }}>
            <div style={sec}>Catalyst {cat.verified ? '✅' : '⚠️'}</div>
            <div style={body}>{cat.text ? String(cat.text).slice(0, compact ? 180 : 320) : '—'}</div>
            {cat.confidence != null && <div style={{ fontSize: 9, color: MUTED, marginTop: 3 }}>Confidence {cat.confidence}%</div>}
            {cat.critic_verdict && <div style={{ fontSize: 9, color: cat.critic_verdict === 'PASS' ? GREEN : AMBER, marginTop: 3 }}>Critic: {cat.critic_verdict}</div>}
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
          <div style={sec}>Analyst consensus</div>
          <div style={{ fontSize: 11, fontWeight: 700, color: String(an.rating || '').includes('buy') ? GREEN : TEXT0, fontFamily: 'monospace' }}>
            {String(an.rating || '—').replace(/_/g, ' ')}
            {an.opinions != null ? ` · ${an.opinions} analysts` : ''}
            {an.target != null ? ` · target $${an.target}` : ''}
            {an.upside_pct != null ? ` (${an.upside_pct >= 0 ? '+' : ''}${an.upside_pct}%)` : ''}
          </div>
          {(an.target_low != null || an.target_high != null) && (
            <div style={{ fontSize: 9, color: MUTED, marginTop: 3 }}>Range ${an.target_low ?? '—'} – ${an.target_high ?? '—'}</div>
          )}
          {an.distribution && (
            <div style={{ fontSize: 9, color: MUTED, marginTop: 3 }}>
              Votes: {an.distribution.strong_buy ?? 0} strong buy / {an.distribution.buy ?? 0} buy / {an.distribution.hold ?? 0} hold
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