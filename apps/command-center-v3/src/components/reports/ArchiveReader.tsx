import { useEffect, useMemo, useState } from 'react'
import BriefSectionPanels from './BriefSectionPanels'
import DocxDownloads from './DocxDownloads'
import ActionDeck, { buildDeckActions, type DeckAction } from './ActionDeck'
import { parseBriefSections, executiveSummaryText } from './briefUtils'
import { relUrl } from './reportLinks'

const FQDN = typeof window !== 'undefined' ? window.location.origin : ''
const TABS = ['Overview', 'Full text', 'Actions'] as const

const WM_GROUPS = [
  { tt: 'risk_stop', label: 'Risk', c: '#ef4444' },
  { tt: 'approval', label: 'Approvals', c: '#a855f7' },
  { tt: 'recovery', label: 'Recovery', c: '#06b6d4' },
  { tt: 'research', label: 'Research', c: '#14b8a6' },
  { tt: 'system', label: 'System', c: '#60a5fa' },
]

function SeverityBadge({ sev }: { sev?: string }) {
  const SEV: Record<string, string> = { critical: '#ef4444', urgent: '#ef4444', warning: '#f59e0b', info: '#60a5fa' }
  const c = SEV[(sev || 'info').toLowerCase()] || '#60a5fa'
  return <span style={{ fontSize: 9, fontWeight: 800, padding: '2px 8px', borderRadius: 5, background: c + '22', color: c, textTransform: 'uppercase' }}>{sev || 'info'}</span>
}

function SynthChips({ it }: { it: any }) {
  const chips: { label: string; color: string }[] = []
  if (it.sector) chips.push({ label: it.sector, color: '#94a3b8' })
  if (it.trend) chips.push({ label: it.trend, color: /bull|up/i.test(it.trend) ? '#22c55e' : '#ef4444' })
  if (it.finance_score >= 28) chips.push({ label: `finance ${Math.round(it.finance_score)}`, color: '#60a5fa' })
  if (it.retirement_relevance) chips.push({ label: `retire ${it.retirement_relevance}`, color: '#f59e0b' })
  if (!chips.length) return null
  return (
    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8 }}>
      {chips.map(c => (
        <span key={c.label} style={{ fontSize: 9, fontWeight: 700, padding: '2px 8px', borderRadius: 5, background: 'var(--bg2)', color: c.color }}>{c.label}</span>
      ))}
    </div>
  )
}

export default function ArchiveReader({
  item,
  reportActions,
  fmtDate,
  renderArticle,
}: {
  item: any
  reportActions: any[]
  fmtDate: (s?: string) => string
  renderArticle: (text: string) => React.ReactNode
}) {
  const [tab, setTab] = useState<typeof TABS[number]>('Overview')
  const itemKey = item ? `${item.source}-${item.id}` : ''
  useEffect(() => { setTab('Overview') }, [itemKey])
  const body = item?.summary || ''
  const sections = useMemo(() => parseBriefSections(body), [body])
  const isBriefLike = sections.some(s => ['exec', 'risk', 'steph'].includes(s.id))
  const deckActions: DeckAction[] = useMemo(() => buildDeckActions({
    briefActions: reportActions.map(a => ({ ...a, _classes: [a.action_class] })),
    rankedLines: [],
    cap: 8,
  }), [reportActions])

  if (!item) {
    return (
      <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 48, textAlign: 'center', color: 'var(--text3)', fontSize: 12, minHeight: 320 }}>
        Select a report from the library to read it here.
      </div>
    )
  }

  const sev = (item.severity || 'info').toLowerCase()
  const borderC = sev === 'urgent' || sev === 'critical' ? '#ef4444' : sev === 'warning' ? '#f59e0b' : '#60a5fa'

  return (
    <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden', minHeight: 420, display: 'flex', flexDirection: 'column' }}>
      <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--border-subtle)', borderTop: `3px solid ${borderC}` }}>
        <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start', flexWrap: 'wrap' }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 16, fontWeight: 800, color: 'var(--text0)', lineHeight: 1.3 }}>{item.title}</div>
            <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 5, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <span>{fmtDate(item.created_at)}</span>
              <span>{item.channel}</span>
              <span>{item.type}</span>
              {item.source && <span style={{ fontFamily: 'var(--mono)', fontSize: 9 }}>{item.source}</span>}
            </div>
          </div>
          <SeverityBadge sev={item.severity} />
        </div>
        <SynthChips it={item} />
        <div style={{ display: 'flex', gap: 4, marginTop: 12 }}>
          {TABS.map(t => {
            const on = tab === t
            const n = t === 'Actions' ? deckActions.length : 0
            return (
              <button key={t} onClick={() => setTab(t)} style={{
                fontSize: 10, fontWeight: on ? 800 : 600, padding: '5px 12px', borderRadius: 6, cursor: 'pointer', border: 'none',
                background: on ? 'rgba(96,165,250,.15)' : 'var(--bg2)', color: on ? '#60a5fa' : 'var(--text3)',
              }}>{t}{n > 0 && t === 'Actions' ? ` (${n})` : ''}</button>
            )
          })}
        </div>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: '14px 18px', maxHeight: 'calc(100vh - 220px)' }}>
        {tab === 'Overview' && (
          <>
            {isBriefLike ? (
              <BriefSectionPanels sections={sections} executiveFallback={executiveSummaryText(body)} />
            ) : (
              <div style={{ fontSize: 13, color: 'var(--text1)', lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>
                {(item.synthesized_insight || body.slice(0, 1200)) + (body.length > 1200 && !item.synthesized_insight ? '…' : '')}
              </div>
            )}
            <DocxDownloads itemDocx={item.docx_file} />
            {reportActions.length > 0 && (
              <div style={{ marginTop: 14, padding: '10px 12px', background: 'var(--bg2)', borderRadius: 8, border: '1px solid var(--border-subtle)' }}>
                <div style={{ fontSize: 9, fontWeight: 800, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: 0.4, marginBottom: 8 }}>Quick links</div>
                {WM_GROUPS.map(g => {
                  const grp = reportActions.filter((a: any) => (a.target?.target_type || '') === g.tt)
                  if (!grp.length) return null
                  return (
                    <div key={g.tt} style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 6, alignItems: 'center' }}>
                      <span style={{ fontSize: 9, fontWeight: 800, color: g.c, minWidth: 72 }}>{g.label}</span>
                      {grp.slice(0, 4).map((a: any) => {
                        const tg = a.target || {}
                        return (
                          <a key={a.id} href={FQDN + relUrl(tg.route || a.route)} style={{ fontSize: 9, fontWeight: 700, padding: '3px 8px', borderRadius: 5, textDecoration: 'none', border: `1px solid ${g.c}44`, color: g.c, background: g.c + '10' }}>
                            {tg.route_label || a.route_label} →
                          </a>
                        )
                      })}
                    </div>
                  )
                })}
              </div>
            )}
            {(item.actions || []).length > 0 && (
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 12 }}>
                {item.actions.map((a: any, i: number) => (
                  <a key={i} href={relUrl(a.url)} style={{ fontSize: 10, fontWeight: 700, padding: '6px 11px', borderRadius: 6, border: '1px solid #60a5fa44', background: '#60a5fa12', color: '#60a5fa', textDecoration: 'none' }}>{a.label} →</a>
                ))}
              </div>
            )}
          </>
        )}
        {tab === 'Full text' && renderArticle(body)}
        {tab === 'Actions' && <ActionDeck actions={deckActions} />}
      </div>
    </div>
  )
}