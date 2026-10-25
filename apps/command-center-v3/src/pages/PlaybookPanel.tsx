// Coordination → Playbook (operator 2026-10-23: "also add that the above should be part of the board"). Renders
// docs/ops/OPERATING_PLAYBOOK.md read-only — the handoff's Section A (resume procedure, system map, rules, how a change
// goes live) and B0 (the standard agent preamble every "Copy prompt" prepends) — with section anchors.
// Read: GET /api/v2/coordination/playbook (scripts/lib/handoff_playbook.py; parsed once per file mtime). The page polls
// rarely (10 min) because the file changes only by PR and release. "Export handoff" regenerates the full offline
// handoff (this playbook + every work package with status and proof evidence) from the board.
import { useState, type CSSProperties } from 'react'
import { useApi } from '../hooks/useApi'
import MiniMarkdown from '../components/MiniMarkdown'
import { FONT, RADIUS, TOKENS, TYPE } from '../lib/designTokens'
import { downloadHandoff } from '../lib/workPipelineActions'

export type PlaybookSection = { id: string; level: number; title: string; markdown: string }
export type PlaybookPayload = { ok?: boolean; schema?: string; bytes?: number; error?: string; path?: string; sha256?: string; as_of?: string | null; sections?: PlaybookSection[]; b0_preamble?: string | null }

const panel: CSSProperties = { background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md, padding: 12, minWidth: 0 }
const small: CSSProperties = { fontSize: TYPE.sm, color: TOKENS.text[2] }
const btn: CSSProperties = { background: TOKENS.bg[2], color: TOKENS.text[0], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.sm, padding: '3px 8px', fontSize: TYPE.sm, cursor: 'pointer' }

export function ExportHandoffButton() {
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  return <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
    <button type="button" style={btn} data-testid="export-handoff" disabled={busy} title="Regenerate the full handoff markdown (playbook + work packages with status and proof) from the board"
      onClick={async () => {
        setBusy(true); setMsg(null)
        try { const d = await downloadHandoff(); setMsg({ ok: true, text: `${d.filename}: ${d.work_packages} work packages, ${Math.round(d.bytes / 1024)} KB${d.truncated ? ' (truncated)' : ''}` }) } catch (e) { setMsg({ ok: false, text: `Export failed: ${String((e as Error).message || e)}` }) }
        setBusy(false)
      }}>{busy ? 'Exporting…' : 'Export handoff'}</button>
    {msg ? <span data-testid="export-handoff-result" style={{ ...small, color: msg.ok ? TOKENS.success : TOKENS.danger }}>{msg.text}</span> : null}
  </span>
}

export default function PlaybookPanel() {
  const api = useApi<PlaybookPayload>('/api/v2/coordination/playbook', 600_000)
  const pb = api.data
  const sections = pb?.sections || []
  return <section data-testid="playbook" style={{ display: 'grid', gap: 12, minWidth: 0 }}>
    <style>{`
      .pb-grid { grid-template-columns: 220px minmax(0, 1fr); }
      @media (max-width: 760px) { .pb-grid { grid-template-columns: minmax(0, 1fr); } .pb-toc { position: static !important; } }
    `}</style>
    <div style={panel}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap', alignItems: 'baseline' }}>
        <div style={{ minWidth: 0 }}>
          <h1 style={{ margin: 0, fontSize: TYPE.lg, color: TOKENS.text[0] }}>Operating playbook</h1>
          <div style={small} data-testid="playbook-source">
            Read-only. Source <code style={{ fontFamily: FONT.mono }}>{pb?.path || 'docs/ops/OPERATING_PLAYBOOK.md'}</code>
            {pb?.as_of ? ` · as of ${pb.as_of}` : ''}{pb?.sha256 ? ` · sha256 ${pb.sha256.slice(0, 12)}` : ''} · change it by PR; every Copy prompt prepends B0.
          </div>
        </div>
        <ExportHandoffButton />
      </div>
    </div>
    {api.error && !pb ? <div style={{ ...panel, color: TOKENS.danger }}>Playbook unavailable: {api.error}</div> : null}
    {pb && pb.ok === false ? <div style={{ ...panel, color: TOKENS.danger }} data-testid="playbook-error">Playbook unavailable: {pb.error}</div> : null}
    {api.loading && !pb ? <div style={{ ...panel, ...small }}>Loading…</div> : null}
    {sections.length ? <div className="pb-grid" style={{ display: 'grid', gap: 12, alignItems: 'start' }}>
      <nav className="pb-toc" aria-label="Playbook sections" data-testid="playbook-toc" style={{ ...panel, position: 'sticky', top: 8, display: 'grid', gap: 4 }}>
        {sections.filter(s => s.level === 2).map(s => <a key={s.id} href={`#${s.id}`} style={{ color: TOKENS.info, fontSize: TYPE.sm, overflowWrap: 'anywhere' }}
          onClick={e => { e.preventDefault(); document.getElementById(s.id)?.scrollIntoView({ behavior: 'smooth', block: 'start' }) }}>{s.title}</a>)}
      </nav>
      <div style={{ display: 'grid', gap: 12, minWidth: 0 }}>
        {sections.map(s => s.level === 1
          ? <div key={s.id} id={s.id} style={{ display: 'grid', gap: 6 }}>
            <h2 style={{ margin: '4px 0 0', fontSize: TYPE.md, color: TOKENS.text[0] }}>{s.title}</h2>
            {s.markdown.trim() ? <div style={panel}><MiniMarkdown text={s.markdown} /></div> : null}
          </div>
          : <article key={s.id} id={s.id} data-testid="playbook-section" data-section-id={s.id} style={panel}>
            <h3 style={{ margin: '0 0 6px', fontSize: TYPE.md, color: TOKENS.text[0] }}><a href={`#${s.id}`} style={{ color: 'inherit', textDecoration: 'none' }}>{s.title}</a></h3>
            <MiniMarkdown text={s.markdown} />
          </article>)}
      </div>
    </div> : null}
  </section>
}
