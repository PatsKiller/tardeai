import {
  agentVerdictColor,
  computeAgentPending,
  dedupeAgentReviews,
  modelTierLabel,
  type NormalizedReview,
} from '../lib/agentReviews'
import { formatCloudRanAt, localLlmLabel } from '../lib/brokerThesis'
import { desk, sectionLabel } from '../lib/proposalDeskTheme'

function cloudColor(status: string | null | undefined) {
  const s = String(status || '').toLowerCase()
  if (s === 'agree') return desk.green
  if (s === 'caution') return desk.amber
  if (s === 'disagree') return desk.red
  if (s === 'running') return desk.amber
  return desk.textDim
}

function AgentRow({ r }: { r: NormalizedReview }) {
  const vc = agentVerdictColor(r.verdict)
  const tier = modelTierLabel(r.model)
  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: '72px 1fr auto',
      gap: '4px 10px',
      alignItems: 'start',
      padding: '8px 10px',
      borderRadius: desk.radius,
      background: r.pending ? desk.amberDim : desk.bgInset,
      border: `1px solid ${r.pending ? 'rgba(245,158,11,.2)' : desk.borderSubtle}`,
    }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: desk.text }}>{r.agent}</div>
      <div style={{ minWidth: 0 }}>
        {r.pending ? (
          <span style={{ fontSize: 10, fontWeight: 700, color: desk.amber }}>Awaiting review</span>
        ) : (
          <span style={{ fontSize: 10, fontWeight: 800, color: vc }}>{r.verdict?.replace(/_/g, ' ')}</span>
        )}
        {r.summary && !r.pending && (
          <div style={{
            fontSize: 10, color: desk.textMuted, lineHeight: 1.45, marginTop: 3,
            display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden',
          }}>
            {r.summary}
          </div>
        )}
      </div>
      <div style={{ textAlign: 'right', fontSize: 9, color: desk.textDim, lineHeight: 1.35 }}>
        <div style={{
          fontWeight: 700,
          color: tier.tier === 'fallback' ? desk.amber : tier.tier === 'cloud' ? desk.purple : desk.blue,
        }}>
          {tier.tier === 'fallback' ? 'fallback' : tier.tier}
        </div>
        {tier.label !== 'Rule-based fallback' && (
          <div style={{ maxWidth: 88, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {tier.label}
          </div>
        )}
      </div>
    </div>
  )
}

type Props = {
  reviews?: any[]
  oversight?: any
  localLlm?: any
  cloud?: any
  lanes?: { grok?: boolean; chatgpt?: boolean }
  onQueueOversight?: () => void
  onRunCloudOversight?: () => void
  oversightBusy?: boolean
  cloudBusy?: boolean
  ovStatus?: string | null
}

export default function AgentConsensusPanel({
  reviews = [],
  oversight,
  localLlm,
  cloud,
  lanes,
  onQueueOversight,
  onRunCloudOversight,
  oversightBusy,
  cloudBusy,
  ovStatus,
}: Props) {
  const deduped = dedupeAgentReviews(reviews)
  const pending = computeAgentPending(reviews, oversight?.agents?.pending)
  const local = localLlm || oversight?.local_llm || {}
  const cr = cloud || oversight?.cloud_review || {}
  const cloudLanes = cr.lanes || {}
  const staleFmt = cr.ran_at ? formatCloudRanAt(cr.ran_at) : null

  const btn = (label: string, onClick?: () => void, busy?: boolean, accent: string = desk.blue) => (
    <button
      type="button"
      onClick={onClick}
      disabled={busy}
      style={{
        fontSize: 10, fontWeight: 700, padding: '5px 10px', borderRadius: desk.radius,
        border: `1px solid ${accent}44`, background: `${accent}12`, color: accent,
        cursor: busy ? 'wait' : 'pointer', whiteSpace: 'nowrap',
      }}
    >
      {busy ? '…' : label}
    </button>
  )

  return (
    <div style={{
      padding: panelPadding(),
      borderRadius: desk.radiusLg,
      background: desk.bgInset,
      border: `1px solid ${desk.border}`,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10, flexWrap: 'wrap', marginBottom: 10 }}>
        <div>
          <div style={{ ...sectionLabel, marginBottom: 2 }}>AI consensus</div>
          <div style={{ fontSize: 12, fontWeight: 800, color: ovStatus === 'PASS' ? desk.green : ovStatus === 'WARN' ? desk.amber : ovStatus === 'BLOCK' ? desk.red : desk.text }}>
            Oversight {ovStatus || '—'}
            {pending.length > 0 && (
              <span style={{ fontSize: 10, fontWeight: 600, color: desk.amber, marginLeft: 8 }}>
                · {pending.length} agent{pending.length > 1 ? 's' : ''} pending
              </span>
            )}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {onQueueOversight && btn('Queue agents', onQueueOversight, oversightBusy, desk.blue)}
          {onRunCloudOversight && btn(
            cr.status === 'running' || cloudBusy ? 'Cloud running…' : 'Re-run cloud',
            onRunCloudOversight,
            cloudBusy || cr.status === 'running',
            desk.purple,
          )}
        </div>
      </div>

      {/* Pipeline status strip */}
      <div style={{
        display: 'flex', flexWrap: 'wrap', gap: '8px 16px', fontSize: 10, color: desk.textMuted,
        padding: '8px 10px', marginBottom: 10, borderRadius: desk.radius,
        background: desk.bg, border: `1px solid ${desk.borderSubtle}`,
      }}>
        <span>
          <b style={{ color: desk.textDim }}>Stage 2b</b>{' '}
          <span style={{ color: local.status === 'complete' ? desk.green : local.status === 'queued' ? desk.amber : desk.textDim }}>
            {localLlmLabel(local.status)}
          </span>
          {local.model ? <span style={{ color: desk.textDim }}> · {local.model}</span> : null}
        </span>
        <span>
          <b style={{ color: desk.textDim }}>Cloud</b>{' '}
          <span style={{ color: cloudColor(cr.status) }}>{cr.status || 'not_run'}</span>
          {staleFmt && (
            <span style={{ color: staleFmt.stale ? desk.amber : desk.textDim }}> · {staleFmt.label}</span>
          )}
          {cr.cached && <span style={{ color: desk.textDim }}> · cached</span>}
        </span>
        {(lanes?.grok || lanes?.chatgpt) && (
          <span style={{ color: desk.textDim }}>
            OAuth lanes: {[lanes?.grok && 'Grok', lanes?.chatgpt && 'ChatGPT'].filter(Boolean).join(', ')}
          </span>
        )}
      </div>

      {/* Local agents grid */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: Object.keys(cloudLanes).length ? 10 : 0 }}>
        <div style={sectionLabel}>Local agents (advisory)</div>
        {deduped.length === 0 ? (
          <div style={{ fontSize: 10, color: desk.textDim, fontStyle: 'italic', padding: '6px 0' }}>
            No agent reviews yet — queue agents to run Maria, Risk, and Steph.
          </div>
        ) : deduped.map(r => <AgentRow key={r.key} r={r} />)}
      </div>

      {/* Cloud lanes — separate from local agents */}
      {Object.keys(cloudLanes).length > 0 && (
        <div>
          <div style={sectionLabel}>Cloud second opinion (OAuth LLM)</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {Object.entries(cloudLanes).map(([lane, lr]: [string, any]) => (
              <div key={lane} style={{
                padding: '8px 10px', borderRadius: desk.radius,
                background: desk.bg, border: `1px solid ${desk.borderSubtle}`,
                borderLeft: `3px solid ${cloudColor(lr?.verdict)}`,
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                  <span style={{ fontSize: 11, fontWeight: 800, color: desk.text, minWidth: 64 }}>
                    {lane === 'grok' ? 'Grok' : lane === 'chatgpt' ? 'ChatGPT' : lane}
                  </span>
                  <span style={{ fontSize: 10, fontWeight: 800, color: cloudColor(lr?.verdict) }}>
                    {lr?.ok ? (lr?.verdict || '—') : 'unavailable'}
                  </span>
                </div>
                {lr?.assessment && (
                  <div style={{ fontSize: 10, color: desk.textMuted, marginTop: 4, lineHeight: 1.45 }}>
                    {String(lr.assessment).slice(0, 200)}
                  </div>
                )}
                {(lr?.concerns?.length > 0) && (
                  <div style={{ fontSize: 9.5, color: desk.amber, marginTop: 4 }}>
                    {lr.concerns.slice(0, 2).join(' · ')}
                  </div>
                )}
              </div>
            ))}
            {cr.consensus && (
              <div style={{ fontSize: 10, fontWeight: 700, color: cloudColor(cr.status), marginTop: 2 }}>
                Consensus: {cr.consensus.verdict}
                {cr.consensus.lanes_ok != null ? ` · ${cr.consensus.lanes_ok} lane(s) OK` : ''}
              </div>
            )}
          </div>
        </div>
      )}

      <div style={{ fontSize: 9, color: desk.textDim, marginTop: 10, lineHeight: 1.45, borderTop: `1px solid ${desk.borderSubtle}`, paddingTop: 8 }}>
        Agents are advisory — risk gate and oversight BLOCK override any APPROVE vote.
        Cloud LLMs require OAuth keys (Grok/ChatGPT); local stage 2b uses on-prem qwen3.
        Fallback reviews are rule-based when the local model is unavailable.
      </div>
    </div>
  )
}

function panelPadding() {
  return '10px 12px'
}