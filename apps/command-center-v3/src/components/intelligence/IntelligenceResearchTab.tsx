import { useApi } from '../../hooks/useApi'
import type { DrillContext } from '../DetailDrawer'

interface Props {
  onDrill: (ctx: DrillContext) => void
  onManageTopics: () => void
}

const card = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10 }

const GAP_REASON: Record<string, string> = {
  zero_articles_and_transcripts: 'No articles or transcripts',
  zero_articles: 'No articles',
  zero_transcripts: 'No transcripts',
  stale_search: 'Stale search (>14d)',
}

function fmtWhen(s?: string) {
  if (!s) return 'never'
  try { return new Date(s).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) } catch { return s }
}

export default function IntelligenceResearchTab({ onDrill, onManageTopics }: Props) {
  const { data, loading, error } = useApi<any>('/api/v2/research-topics', 120_000)

  if (loading && !data) {
    return <div style={{ ...card, padding: 24, textAlign: 'center', color: 'var(--text3)', fontSize: 12 }}>Loading research topics…</div>
  }
  if (error) {
    return <div style={{ ...card, padding: 16, color: '#ef4444', fontSize: 12 }}>Failed to load research topics: {error}</div>
  }

  const userTopics = (data?.user_topics ?? []).filter((t: any) => t.source !== 'auto_research.py')
  const autoBriefs = data?.auto_research_briefs ?? []
  const monitorTopics = data?.monitor_topics ?? []
  const gaps = data?.research_gaps ?? []
  const ytQueue = data?.youtube_research_queue ?? {}
  const ytItems = ytQueue.items ?? []
  const ytCount = ytQueue.count ?? ytItems.length

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }} data-testid="intelligence-research-tab">
      <div style={{ ...card, padding: 14, display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', flexWrap: 'wrap', gap: 10 }}>
        <div>
          <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text0)' }}>Research Topics</div>
          <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 2 }}>
            Auto-research · YouTube material queue (Q≥70) · operator topics · topic monitor · gaps → Iris
          </div>
        </div>
        <div style={{ display: 'flex', gap: 12, fontSize: 11, flexWrap: 'wrap' }}>
          <span style={{ color: '#22c55e' }}>Auto-research: {data?.auto_research_count ?? 0}</span>
          <span style={{ color: '#f97316' }} data-testid="yt-queue-count">YouTube: {ytCount}</span>
          <span style={{ color: '#60a5fa' }}>User: {userTopics.length}</span>
          <span style={{ color: 'var(--text2)' }}>Monitor: {data?.monitor_topic_count ?? 0}</span>
          <span style={{ color: (data?.gap_count ?? 0) > 0 ? '#f59e0b' : 'var(--text3)' }}>Gaps: {data?.gap_count ?? 0}</span>
          <button onClick={onManageTopics} style={{
            padding: '3px 10px', fontSize: 10, borderRadius: 5, border: '1px solid rgba(168,85,247,.3)',
            cursor: 'pointer', background: 'rgba(168,85,247,.12)', color: '#a855f7', fontWeight: 600,
          }}>Manage</button>
        </div>
      </div>

      <div style={{ ...card, padding: 14, border: '1px solid rgba(249,115,22,.25)' }} data-testid="youtube-research-queue">
        <div style={{ fontSize: 12, fontWeight: 700, color: '#f97316', marginBottom: 4 }}>
          YouTube Research Queue ({ytCount})
        </div>
        <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 10 }}>
          Material-only · promoted transcripts · quality ≥ {ytQueue.min_quality ?? 70}
          {ytQueue.built_at ? ` · built ${fmtWhen(ytQueue.built_at)}` : ''}
        </div>
        {ytItems.length === 0 ? (
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>
            No material YouTube items yet. Queue builds from promoted Q≥70 transcripts across all asset classes.
          </div>
        ) : (
          <div style={{ display: 'grid', gap: 8 }}>
            {ytItems.slice(0, 12).map((it: any, i: number) => (
              <div key={it.video_id ?? it.source_id ?? i}
                onClick={() => onDrill({
                  title: it.title ?? 'YouTube research',
                  subtitle: [it.asset_class, ...(it.tickers ?? [])].filter(Boolean).join(' · '),
                  endpoint: '/api/v2/cio/youtube-research-queue',
                  rows: [it],
                })}
                style={{
                  padding: '10px 12px', borderRadius: 8, background: 'var(--bg2)', cursor: 'pointer',
                  border: '1px solid rgba(249,115,22,.15)',
                }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'baseline' }}>
                  <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)' }}>{it.title ?? 'Untitled'}</div>
                  <div style={{ fontSize: 9, color: 'var(--text3)', whiteSpace: 'nowrap' }}>
                    Q{it.quality_score ?? '—'}{it.asset_class ? ` · ${String(it.asset_class).replace(/_/g, ' ')}` : ''}
                  </div>
                </div>
                {(it.tickers?.length > 0 || it.strategy_tags?.length > 0) && (
                  <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 3 }}>
                    {(it.tickers ?? []).slice(0, 6).join(', ')}
                    {(it.tickers?.length && it.strategy_tags?.length) ? ' · ' : ''}
                    {(it.strategy_tags ?? []).slice(0, 4).map((t: string) => String(t).replace(/_/g, ' ')).join(', ')}
                  </div>
                )}
                {it.summary && (
                  <div style={{ fontSize: 11, color: 'var(--text2)', marginTop: 6, lineHeight: 1.45 }}>
                    {String(it.summary).slice(0, 220)}{String(it.summary).length > 220 ? '…' : ''}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {autoBriefs.length > 0 && (
        <div style={{ ...card, padding: 14, border: '1px solid rgba(34,197,94,.25)' }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: '#22c55e', marginBottom: 4 }}>Auto-Research Briefs ({autoBriefs.length})</div>
          <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 10 }}>
            From <code>auto_research.py</code> (9 PM cron) · LLM router (local gemma or cloud fallback) · not Hermes · agent reviews queued when missing
          </div>
          <div style={{ display: 'grid', gap: 8 }}>
            {autoBriefs.slice(0, 12).map((b: any, i: number) => (
              <div key={b.topic ?? i}
                onClick={() => onDrill({
                  title: b.symbol ? `${b.symbol} auto-research` : b.topic,
                  subtitle: b.trigger ?? b.original_message ?? '',
                  endpoint: '/api/v2/research-topics',
                  rows: [b],
                })}
                style={{
                  padding: '10px 12px', borderRadius: 8, background: 'var(--bg2)', cursor: 'pointer',
                  border: '1px solid rgba(34,197,94,.15)',
                }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'baseline' }}>
                  <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', fontFamily: 'var(--mono)' }}>{b.symbol ?? b.topic}</div>
                  <div style={{ fontSize: 9, color: 'var(--text3)' }}>{fmtWhen(b.latest_finding_at ?? b.updated_at)}</div>
                </div>
                <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 3 }}>{b.trigger ?? b.original_message ?? ''}</div>
                {b.universe_note && <div style={{ fontSize: 9, color: 'var(--orange, #f59e0b)', marginTop: 3 }}>⚠ {b.universe_note}</div>}
                {b.summary_line && <div style={{ fontSize: 11.5, fontWeight: 700, color: 'var(--text1)', marginTop: 5 }}>{b.summary_line}</div>}
                <div style={{ fontSize: 11, color: 'var(--text2)', marginTop: 6, lineHeight: 1.45, whiteSpace: 'pre-wrap' }}>
                  {(b.findings ?? b.latest_findings ?? '').slice(0, 320)}{(b.findings ?? b.latest_findings ?? '').length > 320 ? '…' : ''}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {gaps.length > 0 && (
        <div style={{ ...card, padding: 14 }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: '#f59e0b', marginBottom: 8 }}>Research Gaps ({gaps.length})</div>
          <div style={{ display: 'grid', gap: 6 }}>
            {gaps.slice(0, 12).map((g: any, i: number) => (
              <div key={g.topic_id ?? i}
                onClick={() => onDrill({ title: g.display_name ?? g.topic_id, subtitle: g.reason ?? '', endpoint: '/api/v2/research-topics', rows: [g] })}
                style={{
                  padding: '8px 10px', borderRadius: 6, background: 'var(--bg2)', cursor: 'pointer',
                  display: 'grid', gridTemplateColumns: '1fr auto', gap: 8, alignItems: 'center',
                }}>
                <div>
                  <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text0)' }}>{g.display_name ?? g.topic_id}</div>
                  <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 2 }}>
                    {GAP_REASON[g.reason] ?? g.reason} · {g.detail ?? ''}
                    {(g.articles != null || g.transcripts != null) && ` · ${g.articles ?? 0} articles, ${g.transcripts ?? 0} transcripts`}
                  </div>
                </div>
                <div style={{ fontSize: 9, color: 'var(--text3)' }}>searched {fmtWhen(g.last_searched)}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <div style={{ ...card, padding: 14 }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>User Topics</div>
          {userTopics.length === 0 ? (
            <div style={{ fontSize: 11, color: 'var(--text3)' }}>No active user topics.</div>
          ) : userTopics.map((t: any, i: number) => (
            <div key={i}
              onClick={() => onDrill({ title: t.topic ?? `Topic ${i}`, subtitle: `${t.source ?? ''} · ${t.status ?? ''}`, endpoint: '/api/v2/research-topics', rows: [t] })}
              style={{ padding: '7px 0', borderBottom: '1px solid var(--border)', cursor: 'pointer' }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text0)' }}>{t.topic}</div>
              <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 2 }}>
                {t.source} · {t.status} · researched {t.research_count ?? 0}×
              </div>
            </div>
          ))}
        </div>

        <div style={{ ...card, padding: 14 }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Topic Monitor</div>
          {monitorTopics.length === 0 ? (
            <div style={{ fontSize: 11, color: 'var(--text3)' }}>No enabled monitor topics.</div>
          ) : monitorTopics.slice(0, 20).map((t: any, i: number) => (
            <div key={t.topic_id ?? i}
              onClick={() => onDrill({ title: t.display_name ?? t.topic_id, subtitle: `priority ${t.priority ?? '—'}`, endpoint: '/api/v2/research-topics', rows: [t] })}
              style={{ padding: '7px 0', borderBottom: '1px solid var(--border)', cursor: 'pointer' }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text0)' }}>{t.display_name ?? t.topic_id}</div>
              <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 2 }}>
                {t.article_count ?? 0} articles · {t.transcript_count ?? 0} transcripts · last {fmtWhen(t.last_searched)}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}