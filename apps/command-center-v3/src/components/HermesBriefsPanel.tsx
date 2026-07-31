/** Hermes Briefs — the Intel section's analyst-report landing view.
 *  Pulls Hermes-sourced rows straight out of the shared Research Intelligence feed
 *  (source_system=hermes) and renders them via the shared IntelBriefCard, instead of
 *  the raw pipeline-ops telemetry that used to occupy the default Hermes tab.
 */
import { useApi } from '../hooks/useApi'
import { TYPE } from '../lib/watchTokens'
import IntelBriefCard, { type IntelBrief } from './intel/IntelBriefCard'
import type { DrillContext } from './DetailDrawer'

interface RawSource { title?: string; url?: string; source?: string }

interface RawBriefItem {
  id: string
  title: string
  summary?: string
  thesis?: string | null
  symbol?: string | null
  confidence?: number | null
  freshness_label?: string
  research_type?: string
  actionability?: string
  sources?: RawSource[]
  key_questions?: string[]
  is_holdings?: boolean
  created_at?: string
}

interface FeedResponse { ok?: boolean; items?: RawBriefItem[] }

function toIntelBrief(item: RawBriefItem): IntelBrief {
  return {
    id: item.id,
    title: item.title,
    symbol: item.symbol,
    tag: 'Hermes',
    body: item.thesis || item.summary || '',
    confidence: item.confidence,
    freshnessLabel: item.freshness_label,
    actionability: item.actionability,
    openQuestion: item.key_questions?.[0],
    isHeld: item.is_holdings,
    sources: (item.sources ?? []).map(s => ({ label: s.source || s.title, url: s.url })),
  }
}

export default function HermesBriefsPanel({ onDrill }: { onDrill: (ctx: DrillContext) => void }) {
  const { data, loading } = useApi<FeedResponse>('/api/v2/research-intelligence?source_system=hermes&limit=20&primary_only=0', 120_000)
  const rawItems = data?.items ?? []

  return (
    <div>
      <div style={{ fontSize: TYPE.xs, color: 'var(--text3)', marginBottom: 10, padding: '6px 10px', background: 'var(--bg2)', borderRadius: 6 }}>
        Hermes-authored research briefs — headline, thesis, and sources for what the fleet actually produced. For raw pipeline
        telemetry (staging counts, queues, agent footprint), see the <b>Pipeline Ops</b> tab.
      </div>
      {loading && rawItems.length === 0 ? (
        <div style={{ color: 'var(--text3)', fontSize: TYPE.sm }}>Loading briefs…</div>
      ) : rawItems.length === 0 ? (
        <div style={{ color: 'var(--text3)', fontSize: TYPE.sm }}>No Hermes-sourced briefs in the feed yet.</div>
      ) : (
        rawItems.map(it => (
          <IntelBriefCard
            key={it.id}
            brief={toIntelBrief(it)}
            onOpen={b => onDrill({ title: b.title, subtitle: b.symbol || it.research_type || 'Hermes brief', endpoint: '/api/v2/research-intelligence?source_system=hermes', rows: [it] })}
          />
        ))
      )}
      <div style={{ fontSize: TYPE.xs, color: 'var(--text3)', marginTop: 4 }}>
        Source: /api/v2/research-intelligence?source_system=hermes
      </div>
    </div>
  )
}
