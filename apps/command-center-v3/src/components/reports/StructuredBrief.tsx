import { useEffect, useState } from 'react'
import { BB, T, TYPE, RAIL, numStyle, terminalButton } from '../../lib/watchTokens'
import { Chip } from '../TerminalChip'

// Reports Desk v1 (WS-B): render the morning brief from the brief.json sidecar —
// sections as DATA (the delivery layer already had them; the page no longer re-parses
// flattened text). Falls back silently when no sidecar exists (pre-existing briefs).

const SECTION_META: Record<string, { tone: 'red' | 'amber' | 'green' | 'slate'; rail: string }> = {
  'IMMEDIATE RISK': { tone: 'red', rail: RAIL.breach },
  'STEPH REVIEW NEEDED': { tone: 'amber', rail: RAIL.attention },
  'RECOVERY WATCH': { tone: 'slate', rail: RAIL.neutral },
  'COVERED CALLS': { tone: 'green', rail: RAIL.favorable },
  'ROTATION ALTERNATIVES': { tone: 'green', rail: RAIL.favorable },
  'RESEARCH ADVISORIES': { tone: 'slate', rail: RAIL.neutral },
}

// brief "/v2/..." strings → real v3 routes (same-origin)
const LINK_MAP: Record<string, string> = {
  risk: '/v3/risk', approvals: '/v3/trading', recovery: '/v3/portfolio',
  watchlist: '/v3/watchlist', portfolio: '/v3/portfolio', reports: '/v3/reports',
}
const linkFor = (frag: string): string => {
  const slug = frag.replace(/^\/v[23]\//, '').split(/[/?#]/)[0]
  return LINK_MAP[slug] || `/v3/${slug}`
}

function ItemLine({ text }: { text: string }) {
  const m = text.match(/^([A-Z]{1,5}):\s*(.*)$/s)
  const linkM = text.match(/(?:→|Check)\s*(\/v[23]\/[a-z-]+)/i)
  const body = (m ? m[2] : text).replace(/(?:→|Check)\s*\/v[23]\/[a-z-]+\s*(immediately\.?)?$/i, '').trim()
  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', padding: '3px 0', borderBottom: `1px solid ${BB.borderHair}` }}>
      {m && <span style={{ ...numStyle, fontWeight: 800, color: BB.text0, minWidth: 46 }}>{m[1]}</span>}
      <span style={{ fontSize: TYPE.sm, color: BB.text1, lineHeight: 1.5, flex: 1 }}>{body}</span>
      {linkM && (
        <a href={linkFor(linkM[1])} style={{ fontSize: TYPE.xs, fontWeight: 800, color: BB.amber, border: `1px solid ${BB.amber}55`, borderRadius: 999, padding: '1px 8px', textDecoration: 'none', whiteSpace: 'nowrap' }}>
          Open {linkM[1].replace(/^\/v[23]\//, '')}
        </a>
      )}
    </div>
  )
}

/** RECOVERY WATCH: "TDG: market_relist_monitor (alloc: stay_cash) → /v2/recovery" × 14
 *  → grouped pills per allocation bucket, expandable — not 14 identical lines. */
function RecoverySection({ items }: { items: string[] }) {
  const [open, setOpen] = useState<string | null>(null)
  const groups: Record<string, string[]> = {}
  for (const it of items) {
    const g = it.match(/\(alloc:\s*([a-z_]+)\)/i)?.[1] || 'other'
    ;(groups[g] = groups[g] || []).push(it.match(/^([A-Z]{1,5}):/)?.[1] || it.slice(0, 12))
  }
  return (
    <div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {Object.entries(groups).map(([g, syms]) => (
          <span key={g} onClick={() => setOpen(o => o === g ? null : g)} style={{ cursor: 'pointer' }}>
            <Chip kind="state" tone="slate">{`${syms.length} names in ${g}`}</Chip>
          </span>
        ))}
        <a href="/v3/portfolio" style={{ fontSize: TYPE.xs, color: T.link, alignSelf: 'center' }}>open recovery →</a>
      </div>
      {open && (
        <div style={{ ...numStyle, fontSize: TYPE.xs, color: BB.text2, marginTop: 6, lineHeight: 1.8 }}>
          {groups[open].join(' · ')}
        </div>
      )}
    </div>
  )
}

export default function StructuredBrief({ liveTotal, liveStopsTriggered }: { liveTotal?: number; liveStopsTriggered?: number }) {
  const [brief, setBrief] = useState<any | null | 'missing'>(null)
  const [regenState, setRegenState] = useState('')
  const today = new Date().toLocaleDateString('sv-SE', { timeZone: 'America/New_York' })
  useEffect(() => {
    fetch(`/data/portfolios/reports/aegis_morning_brief_${today}.json`)
      .then(r => r.ok ? r.json() : 'missing').then(setBrief).catch(() => setBrief('missing'))
  }, [today, regenState])
  if (brief === null || brief === 'missing') return null   // fallback renderer handles it

  const genAt = brief.generated_at ? new Date(brief.generated_at) : null
  const ageH = genAt ? (Date.now() - genAt.getTime()) / 3.6e6 : null
  const stale = ageH != null && ageH > 12
  const riskItems: string[] = (brief.sections || []).find((s: any) => s.title === 'IMMEDIATE RISK')?.items || []
  const briefStops = riskItems.map(t => t.match(/(\d+)\s+stop\(s\) TRIGGERED/)?.[1]).find(Boolean)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
        <Chip kind="state" tone={stale ? 'amber' : 'green'}>{stale ? `BRIEF STALE · ${Math.round(ageH!)}h` : 'BRIEF CURRENT'}</Chip>
        <span style={{ fontSize: TYPE.xs, color: BB.text3 }}>
          generated {genAt ? genAt.toLocaleString('en-US', { timeZone: 'America/New_York', hour: '2-digit', minute: '2-digit', month: 'short', day: 'numeric' }) + ' ET' : '—'}
          {' · run '}{brief.run_id || '—'}
        </span>
        {briefStops != null && liveStopsTriggered != null && Number(briefStops) !== liveStopsTriggered && (
          <Chip kind="state" tone="amber" title="the brief's stop count vs the live risk endpoint — a stale brief can't mislead">
            {`STOPS: brief ${briefStops} vs live ${liveStopsTriggered}`}
          </Chip>
        )}
        <button
          style={terminalButton('ghost')}
          disabled={regenState === 'running'}
          onClick={async () => {
            setRegenState('running')
            const r = await fetch('/api/v2/reports/brief/regenerate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }).then(x => x.json()).catch(() => null)
            setRegenState((r?.ok ?? r?.data?.ok) ? `done-${Date.now()}` : 'failed')
          }}>
          {regenState === 'running' ? 'Regenerating…' : regenState === 'failed' ? 'Regen failed — see logs' : '↻ Regenerate brief'}
        </button>
        <span style={{ fontSize: TYPE.xs, color: BB.text3 }}>deterministic-light: rebuilds .md + .json from live context; Telegram NOT re-sent</span>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 10 }}>
        {(brief.sections || []).map((s: any, i: number) => {
          const meta = SECTION_META[s.title] || { tone: 'slate' as const, rail: RAIL.neutral }
          return (
            <div key={i} style={{ background: BB.bg, border: `1px solid ${BB.border}`, borderLeft: `3px solid ${meta.rail}`, borderRadius: 2, padding: '10px 12px' }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 6 }}>
                <span style={{ fontSize: TYPE.xs, fontWeight: 800, letterSpacing: '.06em', color: BB.text2 }}>{s.title}</span>
                <Chip kind="count" warn={meta.tone === 'red' || meta.tone === 'amber'}>{(s.items || []).length}</Chip>
                {s.priority != null && <Chip kind="metric" title="section priority from the generator">p{s.priority}</Chip>}
              </div>
              {s.title === 'RECOVERY WATCH'
                ? <RecoverySection items={s.items || []} />
                : (s.items || []).map((it: string, j: number) => <ItemLine key={j} text={it} />)}
            </div>
          )
        })}
      </div>
    </div>
  )
}
