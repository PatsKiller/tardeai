import { useState } from 'react'
import { BB, T, TYPE, RAIL, numStyle, terminalButton } from '../../lib/watchTokens'
import { Chip } from '../TerminalChip'

// Reports Desk v1 (WS-A): the Library — every report family the system already
// produces, surfaced. Data: /api/v2/reports → report_catalog (built by the ONE
// indexer, generate_reports_hub.build_report_catalog). In-page viewer uses the
// artifact's HTML sibling in an iframe (the export pipeline already writes HTML
// for weekly/monthly/dashboard); DOCX/PDF are download buttons. Read-only.

const LANES: Array<{ key: string; label: string }> = [
  { key: 'daily', label: 'DAILY' },
  { key: 'weekly', label: 'WEEKLY' },
  { key: 'monthly', label: 'MONTHLY' },
  { key: 'on-event', label: 'ON-EVENT' },
]

const railFor = (status: string) =>
  status === 'fresh' ? RAIL.favorable : status === 'overdue' ? RAIL.attention :
  status === 'never-generated' ? RAIL.breach : RAIL.neutral

const fmtAge = (h?: number) => h == null ? '—' : h < 48 ? `${Math.round(h)}h ago` : `${Math.round(h / 24)}d ago`
const fmtET = (iso?: string | null) => {
  if (!iso) return 'never'
  try {
    return new Date(iso).toLocaleString('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) + ' ET'
  } catch { return iso }
}

export default function ReportLibrary({ catalog }: { catalog: any }) {
  const [viewer, setViewer] = useState<{ title: string; url: string; kind: string } | null>(null)
  const [histOpen, setHistOpen] = useState<Record<string, boolean>>({})
  const types: any[] = catalog?.types ?? []

  const openArtifact = (t: any, kind: string, url: string) => {
    if (kind === 'html' || kind === 'md') setViewer({ title: t.title, url, kind })
    else window.open(url, '_blank')
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {LANES.map(lane => {
        const rows = types.filter(t => t.cadence === lane.key)
        if (!rows.length) return null
        return (
          <div key={lane.key}>
            <div style={{ fontSize: TYPE.xs, fontWeight: 800, letterSpacing: '.08em', color: BB.text3, marginBottom: 6 }}>
              {lane.label} <Chip kind="count">{rows.length}</Chip>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: 10 }}>
              {rows.map(t => (
                <div key={t.key} style={{ background: BB.bg, border: `1px solid ${BB.border}`, borderLeft: `3px solid ${railFor(t.status)}`, borderRadius: 2, padding: '10px 12px' }}>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    <span style={{ fontSize: TYPE.base, fontWeight: 800, color: BB.text0 }}>{t.title}</span>
                    <Chip kind="state" tone={t.status === 'fresh' ? 'green' : t.status === 'overdue' ? 'amber' : t.status === 'never-generated' ? 'red' : 'slate'}>
                      {t.status === 'never-generated' ? 'NEVER RUN' : t.status.toUpperCase()}
                    </Chip>
                    {t.count != null && <Chip kind="count">{t.count}</Chip>}
                  </div>
                  <div style={{ fontSize: TYPE.xs, color: BB.text3, marginTop: 3 }}>
                    <span style={numStyle} title={t.last_generated_at || ''}>{fmtET(t.last_generated_at)}</span>
                    {' · '}{fmtAge(t.age_hours)} · {t.generator}
                  </div>
                  <div style={{ display: 'flex', gap: 6, marginTop: 8, flexWrap: 'wrap' }}>
                    {Object.entries(t.artifacts || {}).map(([kind, url]: any) => (
                      <button key={kind} onClick={() => openArtifact(t, kind, url)}
                              style={kind === 'html' || kind === 'md' ? terminalButton('primary') : terminalButton('secondary')}>
                        {kind === 'html' ? 'Open' : kind === 'md' ? 'Read' : `${kind.toUpperCase()} ↓`}
                      </button>
                    ))}
                    {(t.history?.length ?? 0) > 1 && (
                      <button onClick={() => setHistOpen(o => ({ ...o, [t.key]: !o[t.key] }))} style={terminalButton('ghost')}>
                        {histOpen[t.key] ? 'hide history' : `history (${t.history.length})`}
                      </button>
                    )}
                  </div>
                  {histOpen[t.key] && (
                    <div style={{ marginTop: 6, display: 'flex', flexDirection: 'column', gap: 2 }}>
                      {t.history.map((h: any, i: number) => (
                        <div key={i} style={{ display: 'flex', gap: 8, fontSize: TYPE.xs, alignItems: 'baseline', borderBottom: `1px solid ${BB.borderHair}`, padding: '2px 0' }}>
                          <span style={{ ...numStyle, color: BB.text2, minWidth: 130 }}>{fmtET(h.mtime)}</span>
                          {Object.entries(h.paths || {}).map(([kind, url]: any) => (
                            <a key={kind} href={url} target={kind === 'html' ? undefined : '_blank'} rel="noreferrer"
                               onClick={e => { if (kind === 'html' || kind === 'md') { e.preventDefault(); setViewer({ title: h.name, url, kind }) } }}
                               style={{ color: T.link, textDecoration: 'none' }}>{kind}</a>
                          ))}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )
      })}
      {types.length === 0 && <div style={{ color: BB.text3, fontSize: TYPE.sm }}>catalog empty — indexer has not run</div>}

      {/* in-page viewer: HTML sibling in an iframe (same-origin static serve), md fetched raw */}
      {viewer && (
        <div onClick={() => setViewer(null)} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.6)', zIndex: 90, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div onClick={e => e.stopPropagation()} style={{ width: '86vw', height: '88vh', background: BB.bgPanel, border: `1px solid ${BB.border}`, borderRadius: 2, display: 'flex', flexDirection: 'column' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 10px', borderBottom: `1px solid ${BB.border}` }}>
              <span style={{ fontSize: TYPE.base, fontWeight: 800, color: BB.text0 }}>{viewer.title}</span>
              <a href={viewer.url} target="_blank" rel="noreferrer" style={{ fontSize: TYPE.xs, color: T.link }}>open raw ↗</a>
              <button onClick={() => setViewer(null)} style={{ marginLeft: 'auto', ...terminalButton('ghost') }}>✕ close</button>
            </div>
            {viewer.kind === 'html'
              ? <iframe title={viewer.title} src={viewer.url} style={{ flex: 1, border: 'none', background: '#fff' }} />
              : <MdPane url={viewer.url} />}
          </div>
        </div>
      )}
    </div>
  )
}

function MdPane({ url }: { url: string }) {
  const [txt, setTxt] = useState<string | null>(null)
  if (txt === null) { void fetch(url).then(r => r.text()).then(setTxt).catch(() => setTxt('failed to load')) }
  return <pre style={{ flex: 1, overflow: 'auto', margin: 0, padding: 14, fontSize: TYPE.sm, color: BB.text1, fontFamily: BB.mono, whiteSpace: 'pre-wrap' }}>{txt ?? 'loading…'}</pre>
}
