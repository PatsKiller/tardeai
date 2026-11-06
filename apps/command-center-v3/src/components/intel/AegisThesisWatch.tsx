/**
 * Aegis "thesis broken" inferences from the latest complete inference run, split by whether the name is held.
 * Held → CIO Desk › Holdings verdicts; not held → Research Intel › Thesis watch (intel/v001).
 * Read-only. The run currently scores only the accounts its inference job covers; the run id and time are shown.
 */
import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { useApi } from '../../hooks/useApi'
import { heldSymbolSet, splitAegisByHeld, type AegisRow } from '../../lib/intelConsolidation'
import W7DetailSheet, { useW7Detail } from '../W7DetailSheet'

const card = { border: '1px solid var(--border)', borderRadius: 8, background: 'var(--bg2)', padding: 12 } as const

export default function AegisThesisWatch({ held }: { held: boolean }) {
  const latest = useApi<any>('/api/v2/inference/latest', 300_000)
  const runId = latest.data?.run?.id
  const aegis = useApi<any>(`/api/v2/inference/results?run_id=${encodeURIComponent(String(runId ?? ''))}&type=aegis_thesis&limit=200`, 300_000, { enabled: runId != null })
  const holdings = useApi<any>('/api/v2/portfolio/holdings', 300_000)
  const detail = useW7Detail()
  const detailKey = held ? 'aegis-held' : 'aegis-watch'

  const hRows: any[] = holdings.data?.data?.holdings ?? holdings.data?.holdings ?? []
  // useApi unwraps {ok, data}: the results route arrives as the array itself.
  const results: AegisRow[] = Array.isArray(aegis.data) ? aegis.data : (aegis.data?.data ?? latest.data?.results ?? [])
  const split = useMemo(() => splitAegisByHeld(results, heldSymbolSet(hRows)), [results, hRows])
  const rows = held ? split.held : split.notHeld
  const bySymbol = useMemo(() => {
    const m = new Map<string, AegisRow[]>()
    for (const r of rows) { const k = String(r.subject).toUpperCase(); m.set(k, [...(m.get(k) || []), r]) }
    return [...m.entries()].sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]))
  }, [rows])
  const selected = detail.selected?.startsWith(`${detailKey}:`) ? detail.selected.slice(detailKey.length + 1) : null
  const selectedRows = selected ? bySymbol.find(([s]) => s === selected)?.[1] ?? [] : []

  const loading = latest.loading || holdings.loading || (runId != null && aegis.loading)
  const err = latest.error || holdings.error || aegis.error
  const run = latest.data?.run

  return (
    <section data-testid={held ? 'aegis-held' : 'aegis-thesis-watch'} style={{ ...card, marginBottom: 16 }}>
      <div style={{ fontWeight: 800, fontSize: 14 }}>{held ? 'Thesis broken · held names (Aegis)' : 'Thesis broken · not held'}</div>
      <div style={{ fontSize: 11, color: 'var(--text3)', margin: '2px 0 10px' }}>
        {run ? `inference run ${run.id}${run.finished_at || run.started_at ? ` · ${String(run.finished_at || run.started_at).slice(0, 16).replace('T', ' ')}` : ''}` : 'no inference run'}
        {held ? ' · also counted on Research Intel › Thesis watch' : ' · held names show on CIO Desk › Holdings verdicts'}
      </div>
      {loading && !bySymbol.length && <div style={{ fontSize: 12, color: 'var(--text2)' }}>Loading…</div>}
      {err && !bySymbol.length && <div style={{ fontSize: 12, color: 'var(--amber)' }}>Unavailable: {String(err)}</div>}
      {!loading && !err && !bySymbol.length && <div style={{ fontSize: 12, color: 'var(--text2)' }}>No {held ? 'held' : 'watch'} names with a broken thesis in the latest run.</div>}
      <div style={{ display: 'grid', gap: 6 }}>
        {bySymbol.map(([sym, list]) => (
          <button key={sym} type="button" data-testid={`aegis-${sym}`} onClick={() => detail.open(`${detailKey}:${sym}`)}
            style={{ textAlign: 'left', minHeight: 44, border: '1px solid var(--border)', borderRadius: 6, background: 'var(--bg)', color: 'var(--text)', padding: '8px 10px', cursor: 'pointer', display: 'flex', justifyContent: 'space-between', gap: 8, minWidth: 0 }}>
            <span style={{ minWidth: 0, overflowWrap: 'anywhere' }}><b>{sym}</b> <span style={{ color: 'var(--text2)', fontSize: 12 }}>{list[0]?.title || 'Aegis thesis check failed'}</span></span>
            <span style={{ fontSize: 11, color: 'var(--red)', whiteSpace: 'nowrap' }}>{list.length} failed check{list.length === 1 ? '' : 's'}</span>
          </button>
        ))}
      </div>
      {selected && (
        <W7DetailSheet title={selected} onClose={detail.close}>
          <div style={{ display: 'grid', gap: 10, padding: 4 }}>
            {selectedRows.map((r, i) => (
              <div key={i} style={card}>
                <div style={{ fontWeight: 700 }}>{r.title || 'Aegis thesis check'}</div>
                <div style={{ fontSize: 11, color: 'var(--text3)' }}>{[r.severity, r.confidence != null ? `confidence ${Number(r.confidence).toFixed(2)}` : null].filter(Boolean).join(' · ')}</div>
                {r.body && <div style={{ fontSize: 12, marginTop: 6, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{r.body}</div>}
              </div>
            ))}
            <Link to={`/prospectus/${encodeURIComponent(selected)}`} style={{ color: 'var(--accent)', minHeight: 44, display: 'inline-flex', alignItems: 'center' }}>Open prospectus →</Link>
          </div>
        </W7DetailSheet>
      )}
    </section>
  )
}
