import { useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useApi } from '../../hooks/useApi'
import { useIntelligenceItemState } from '../../hooks/useIntelligenceItemState'
import type { DrillContext } from '../DetailDrawer'
import SynthesizedReportCard from '../SynthesizedReportCard'
import type { ReportCardItem } from '../SynthesizedReportCard'
import IntelligenceCardActions from './IntelligenceCardActions'
import { KPI, SectionHeader, MiniBarRow, dashboardCard } from './dashboardKit'
import { intelligenceItemId } from '../../lib/intelligenceItemId'

interface Props {
  onDrill: (ctx: DrillContext) => void
  onManageTopics: () => void
}

const GAP_REASON: Record<string, string> = {
  zero_articles_and_transcripts: 'No articles or transcripts',
  zero_articles: 'No articles',
  zero_transcripts: 'No transcripts',
  stale_search: 'Stale search (>14d)',
}

type SectionFocus = 'all' | 'briefs' | 'gaps' | 'user' | 'monitor'

function fmtWhen(s?: string) {
  if (!s) return 'never'
  try { return new Date(s).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) } catch { return s }
}

function briefId(b: any) {
  return intelligenceItemId('research_brief', 'auto_research', b.symbol, b.topic ?? b.symbol ?? String(b.summary_line ?? ''))
}

function gapId(g: any) {
  return intelligenceItemId('research_gap', g.reason ?? 'gap', undefined, g.display_name ?? g.topic_id ?? '')
}

export default function IntelligenceResearchTab({ onDrill, onManageTopics }: Props) {
  const { data, loading, error, refetch } = useApi<any>('/api/v2/research-topics', 120_000)
  const [focus, setFocus] = useState<SectionFocus>('all')
  const [showDismissed, setShowDismissed] = useState(false)

  const briefsRef = useRef<HTMLDivElement>(null)
  const gapsRef = useRef<HTMLDivElement>(null)
  const userRef = useRef<HTMLDivElement>(null)
  const monitorRef = useRef<HTMLDivElement>(null)

  const userTopics = (data?.user_topics ?? []).filter((t: any) => t.source !== 'auto_research.py')
  const autoBriefs = data?.auto_research_briefs ?? []
  const monitorTopics = data?.monitor_topics ?? []
  const gaps = data?.research_gaps ?? []

  const allIds = useMemo(() => [
    ...autoBriefs.map(briefId),
    ...gaps.map(gapId),
  ], [autoBriefs, gaps])
  const { byId: stateById, refresh: refreshState } = useIntelligenceItemState(allIds)
  const onActionDone = () => { refreshState(); refetch() }

  const gapReasonRows = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const g of gaps) {
      const label = GAP_REASON[g.reason] ?? g.reason ?? 'other'
      counts[label] = (counts[label] ?? 0) + 1
    }
    return Object.entries(counts)
      .sort((a, b) => b[1] - a[1])
      .map(([label, value]) => ({ label, value, sub: String(value) }))
  }, [gaps])

  const scrollTo = (section: SectionFocus) => {
    setFocus(section)
    const ref = section === 'briefs' ? briefsRef : section === 'gaps' ? gapsRef : section === 'user' ? userRef : section === 'monitor' ? monitorRef : null
    ref?.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const visibleBrief = (b: any) => {
    const id = briefId(b)
    const st = stateById.get(id) ?? 'active'
    return showDismissed || st !== 'dismissed'
  }
  const visibleGap = (g: any) => {
    const id = gapId(g)
    const st = stateById.get(id) ?? 'active'
    return showDismissed || st !== 'dismissed'
  }

  const dismissedCount = useMemo(() => {
    let n = 0
    for (const b of autoBriefs) if (stateById.get(briefId(b)) === 'dismissed') n++
    for (const g of gaps) if (stateById.get(gapId(g)) === 'dismissed') n++
    return n
  }, [autoBriefs, gaps, stateById])

  if (loading && !data) {
    return <div style={{ ...dashboardCard, padding: 24, textAlign: 'center', color: 'var(--text3)', fontSize: 12 }}>Loading research topics…</div>
  }
  if (error) {
    return <div style={{ ...dashboardCard, padding: 16, color: 'var(--red)', fontSize: 12 }}>Failed to load research topics: {error}</div>
  }

  const briefToCard = (b: any): ReportCardItem => ({
    id: briefId(b),
    type: 'Auto-research brief',
    channel: b.trigger ?? 'auto_research.py',
    title: b.symbol ? `${b.symbol} — ${b.topic ?? 'brief'}` : (b.topic ?? 'Brief'),
    summary: b.summary_line || (b.findings ?? b.latest_findings ?? '').slice(0, 280),
    severity: b.universe_note ? 'warning' : 'info',
    symbol: b.symbol,
    created_at: b.latest_finding_at ?? b.updated_at,
    actions: [{ label: 'Research Intel desk', url: '/v3/research-intelligence' }],
  })

  const gapToCard = (g: any): ReportCardItem => ({
    id: gapId(g),
    type: 'Research gap',
    channel: GAP_REASON[g.reason] ?? g.reason,
    title: g.display_name ?? g.topic_id,
    summary: g.detail ?? '',
    severity: 'warning',
    created_at: g.last_searched,
    actions: [{ label: 'Assign research', action: 'assign' }, { label: 'Manage topics', action: 'manage' }],
  })

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ ...dashboardCard, padding: '8px 14px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', border: '1px solid rgba(96,165,250,.25)', background: 'rgba(96,165,250,.05)' }}>
        <span style={{ fontSize: 11, color: 'var(--text2)' }}>Topic registry &amp; auto-research briefs. For curated article staging, use Research Intelligence desk.</span>
        <Link to="/research-intelligence" style={{ fontSize: 11, fontWeight: 700, color: 'var(--blue)', textDecoration: 'none', whiteSpace: 'nowrap', marginLeft: 10 }}>Open Research Intel desk →</Link>
      </div>

      <SectionHeader
        title="Topics Dashboard"
        subtitle="Auto-research · operator topics · monitor · gaps → Iris"
        accent="var(--purple)"
        right={
          <button onClick={onManageTopics} style={{
            padding: '5px 12px', fontSize: 10, borderRadius: 6, border: '1px solid rgba(168,85,247,.3)',
            cursor: 'pointer', background: 'rgba(168,85,247,.12)', color: 'var(--purple)', fontWeight: 700,
          }}>Manage topics</button>
        }
      />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10 }}>
        <KPI label="Auto-research" value={data?.auto_research_count ?? autoBriefs.length} sub="LLM briefs" color="var(--green)" active={focus === 'briefs'} onClick={() => scrollTo('briefs')} />
        <KPI label="Research gaps" value={data?.gap_count ?? gaps.length} sub="needs coverage" color={(data?.gap_count ?? gaps.length) > 0 ? 'var(--amber)' : 'var(--green)'} active={focus === 'gaps'} onClick={() => scrollTo('gaps')} />
        <KPI label="User topics" value={userTopics.length} sub="operator-owned" color="var(--blue)" active={focus === 'user'} onClick={() => scrollTo('user')} />
        <KPI label="Monitor topics" value={data?.monitor_topic_count ?? monitorTopics.length} sub="enabled watch" active={focus === 'monitor'} onClick={() => scrollTo('monitor')} />
      </div>

      {gapReasonRows.length > 0 && (focus === 'all' || focus === 'gaps') && (
        <div style={{ ...dashboardCard, borderLeft: '4px solid var(--amber)' }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Gap reasons</div>
          <MiniBarRow rows={gapReasonRows} />
        </div>
      )}

      {dismissedCount > 0 && (
        <button type="button" onClick={() => setShowDismissed(v => !v)} style={{ alignSelf: 'flex-start', fontSize: 10, padding: '5px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text2)', cursor: 'pointer' }}>
          {showDismissed ? 'Hide' : 'Show'} {dismissedCount} dismissed
        </button>
      )}

      {(focus === 'all' || focus === 'briefs') && autoBriefs.length > 0 && (
        <div ref={briefsRef} style={{ ...dashboardCard, borderLeft: '4px solid var(--green)' }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--green)', marginBottom: 4 }}>Auto-Research Briefs ({autoBriefs.length})</div>
          <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 10 }}>
            From auto_research.py · LLM narrative — verify figures against Portfolio/Risk before acting.
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {autoBriefs.filter(visibleBrief).slice(0, 12).map((b: any, i: number) => {
              const card = briefToCard(b)
              return (
                <div key={card.id + i} onClick={() => onDrill({ title: card.title, subtitle: card.channel, endpoint: '/api/v2/research-topics', rows: [b] })} style={{ cursor: 'pointer' }}>
                  <SynthesizedReportCard
                    item={card}
                    footer={<IntelligenceCardActions itemId={card.id} itemType="research_brief" symbol={b.symbol} onDone={onActionDone} />}
                  />
                </div>
              )
            })}
          </div>
        </div>
      )}

      {(focus === 'all' || focus === 'gaps') && gaps.length > 0 && (
        <div ref={gapsRef} style={{ ...dashboardCard, borderLeft: '4px solid var(--amber)' }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--amber)', marginBottom: 8 }}>Research Gaps ({gaps.length})</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {gaps.filter(visibleGap).slice(0, 12).map((g: any) => {
              const card = gapToCard(g)
              return (
                <div
                  key={card.id}
                  onClick={() => onDrill({ title: card.title, subtitle: card.channel, endpoint: '/api/v2/research-topics', rows: [g], links: [{ label: 'Manage topics', href: '#manage' }] })}
                  style={{ cursor: 'pointer' }}
                >
                  <SynthesizedReportCard
                    item={card}
                    onAction={async (action) => {
                      if (action === 'manage') { onManageTopics(); return }
                      if (action === 'assign' && g.topic_id) {
                        try {
                          await fetch('/api/v2/research-intelligence/run-topic', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ topic_id: g.topic_id, requested_by: 'intelligence_topics' }),
                          })
                        } catch { /* best-effort */ }
                        onActionDone()
                      }
                    }}
                    footer={<IntelligenceCardActions itemId={card.id} itemType="research_gap" onDone={onActionDone} />}
                  />
                </div>
              )
            })}
          </div>
        </div>
      )}

      {(focus === 'all' || focus === 'user' || focus === 'monitor') && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <div ref={userRef} style={{ ...dashboardCard, display: focus === 'monitor' ? 'none' : undefined }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>User Topics</div>
            {userTopics.length === 0 ? (
              <div style={{ fontSize: 11, color: 'var(--text3)' }}>No active user topics.</div>
            ) : userTopics.map((t: any, i: number) => (
              <div key={i} onClick={() => onDrill({ title: t.topic ?? `Topic ${i}`, subtitle: `${t.source ?? ''} · ${t.status ?? ''}`, endpoint: '/api/v2/research-topics', rows: [t] })}
                style={{ padding: '7px 0', borderBottom: '1px solid var(--border)', cursor: 'pointer' }}>
                <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text0)' }}>{t.topic}</div>
                <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 2 }}>{t.source} · {t.status} · researched {t.research_count ?? 0}×</div>
              </div>
            ))}
          </div>
          <div ref={monitorRef} style={{ ...dashboardCard, display: focus === 'user' ? 'none' : undefined }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Topic Monitor</div>
            {monitorTopics.length === 0 ? (
              <div style={{ fontSize: 11, color: 'var(--text3)' }}>No enabled monitor topics.</div>
            ) : monitorTopics.slice(0, 20).map((t: any, i: number) => (
              <div key={t.topic_id ?? i} onClick={() => onDrill({ title: t.display_name ?? t.topic_id, subtitle: `priority ${t.priority ?? '—'}`, endpoint: '/api/v2/research-topics', rows: [t] })}
                style={{ padding: '7px 0', borderBottom: '1px solid var(--border)', cursor: 'pointer' }}>
                <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text0)' }}>{t.display_name ?? t.topic_id}</div>
                <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 2 }}>{t.article_count ?? 0} articles · {t.transcript_count ?? 0} transcripts · last {fmtWhen(t.last_searched)}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
