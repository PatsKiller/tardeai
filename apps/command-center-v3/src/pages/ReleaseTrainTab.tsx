// Coordination → Release train (Release Train v2, 2026-10-21). What is queued, what each train froze and did, and
// what has been processed — with STOP RELEASES. Read-only except the set-only STOP (components/ReleaseStopControl).
// Read shapes: docs/ops/RELEASE_TRAIN_API.md (summary, /queue, /trains/{id}, /events); STOP: docs/ops/
// RELEASE_TRAIN_UI_CONTRACT.md. Projections and the "never 0, never green" rules: lib/releaseTrain.ts.
import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { useApi } from '../hooks/useApi'
import { Chip, ChipRow, SortHeader, useSort } from '../components/primitives'
import { FONT, RADIUS, TOKENS, TYPE, toneVars } from '../lib/designTokens'
import ReleaseStopControl from '../components/ReleaseStopControl'
import {
  censusFrom, DESIGN_OUTCOMES, freshness, freshnessText, freshnessTone, historyFrom, HISTORY_OUTCOMES, OUTCOME_LABEL,
  OUTCOME_TONE, queueFrom, RELEASE_TRAIN_PATHS, summaryFrom, trainDetailFrom, trainDetailPath, TRAIN_ID_RE,
  type Freshness, type HistoryRow, type QueueRow, type ReleaseEventsWire, type ReleaseQueueWire,
  type ReleaseTrainDetailWire, type ReleaseTrainSummaryWire,
} from '../lib/releaseTrain'

const panel: CSSProperties = { background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md, padding: 14 }
const label: CSSProperties = { fontSize: TYPE.xs, color: TOKENS.text[3], textTransform: 'uppercase', letterSpacing: 0.5, fontWeight: 750 }
const cell: CSSProperties = { padding: '5px 6px', fontSize: TYPE.base, color: TOKENS.text[1], verticalAlign: 'top' }
const mono: CSSProperties = { ...cell, fontFamily: FONT.mono, fontSize: TYPE.sm }
const th: CSSProperties = { ...label, textAlign: 'left', padding: '5px 6px' }

function useNow(ms: number): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), ms)
    return () => clearInterval(id)
  }, [ms])
  return now
}

function FreshChip({ f, what }: { f: Freshness; what: string }) {
  return <Chip tone={freshnessTone(f)} title={`${what}: ${f.reason ?? f.asOf ?? ''}`}>{freshnessText(f)}</Chip>
}

function Header({ title, sub, f, what }: { title: string; sub: string; f?: Freshness; what?: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
      <div style={{ fontSize: TYPE.lg, fontWeight: 800, color: TOKENS.text[0] }}>{title}</div>
      <div style={label}>{sub}</div>
      {f && what ? <FreshChip f={f} what={what} /> : null}
    </div>
  )
}

function Unavailable({ f, what }: { f: Freshness; what: string }) {
  if (f.state !== 'UNAVAILABLE') return null
  return (
    <div role="status" style={{ marginTop: 8, padding: '8px 10px', borderRadius: RADIUS.sm, fontSize: TYPE.sm, fontWeight: 700,
      color: toneVars('warning').color, background: toneVars('warning').bg, border: `1px solid ${toneVars('warning').border}` }}>
      {what} UNAVAILABLE{f.reason ? ` · ${f.reason}` : ''} — not empty, not healthy: unknown.
    </div>
  )
}

function queueGetter(r: QueueRow, k: string): unknown {
  return k === 'age' ? r.ageS : (r as unknown as Record<string, unknown>)[k]
}
function historyGetter(r: HistoryRow, k: string): unknown {
  return (r as unknown as Record<string, unknown>)[k]
}

export default function ReleaseTrainTab() {
  const now = useNow(15_000)
  const sumApi = useApi<ReleaseTrainSummaryWire>(RELEASE_TRAIN_PATHS.summary, 60_000)
  const qApi = useApi<ReleaseQueueWire>(RELEASE_TRAIN_PATHS.queue, 60_000)
  const eApi = useApi<ReleaseEventsWire>(RELEASE_TRAIN_PATHS.events, 120_000)
  const sumF = freshness(sumApi.data?.generated_at, !!sumApi.data, { nowMs: now, loading: sumApi.loading, error: sumApi.error })
  const qT = freshness(qApi.data?.generated_at, !!qApi.data, { nowMs: now, loading: qApi.loading, error: qApi.error })
  const eT = freshness(eApi.data?.generated_at, !!eApi.data, { nowMs: now, loading: eApi.loading, error: eApi.error })
  const queue = useMemo(() => queueFrom(qApi.data, qT, now), [qApi.data, qT.state, now])
  const qF = queue.f
  const summary = summaryFrom(sumApi.data, sumF, now, queue)
  const census = censusFrom(sumApi.data?.census ?? qApi.data?.census, sumApi.data ? sumF : qT, now)
  const history = useMemo(() => historyFrom(eApi.data, eT, now), [eApi.data, eT.state, now])
  const hF = history.f
  const lastVerified = history.rows.find(r => r.outcome === 'VERIFIED') ?? null
  const qSort = useSort(queue.rows, { key: 'age', dir: 'desc' }, queueGetter)
  const hSort = useSort(history.rows, { key: 'started', dir: 'desc' }, historyGetter)
  const [selected, setSelected] = useState<string | null>(null)
  const trainId = selected ?? queue.currentTrainId
  const validId = !!trainId && TRAIN_ID_RE.test(trainId)
  const tApi = useApi<ReleaseTrainDetailWire>(validId ? trainDetailPath(trainId!) : RELEASE_TRAIN_PATHS.summary, 30_000, { enabled: validId })
  const tT = freshness(tApi.data?.generated_at, !!tApi.data, { nowMs: now, loading: tApi.loading, error: tApi.error })
  const tF: Freshness = tApi.data && String(tApi.data.freshness || '').toUpperCase() === 'UNAVAILABLE'
    ? { ...tT, state: 'UNAVAILABLE', reason: tApi.data.reason || 'store unavailable' } : tT
  const train = validId && tApi.data?.train?.train_id === trainId ? trainDetailFrom(tApi.data.train) : null

  return (
    <div data-testid="release-train-tab" style={{ display: 'grid', gap: 12, minWidth: 0 }}>
      <div style={panel} data-testid="release-train-stop-panel">
        <Header title="Release train" sub="agents queue PRs · the train integrates, releases and reports · this page shows; only STOP acts" />
        <div style={{ marginTop: 10 }}><ReleaseStopControl /></div>
      </div>

      <div style={panel} data-testid="release-train-summary">
        <Header title="Now" sub="next window · ready / held · current train · standing policy" f={sumF} what="summary" />
        <Unavailable f={sumF} what="Release-train summary" />
        <ChipRow style={{ marginTop: 8 }}>
          <Chip tone={summary.nextWindow.tone} title={summary.nextWindow.f.reason ?? undefined}>next window {summary.nextWindow.text}</Chip>
          <Chip tone={summary.ready.f.state === 'OK' ? summary.ready.tone : 'warning'} title={summary.ready.f.reason ?? undefined}>ready {summary.ready.text}</Chip>
          <Chip tone="warning" title={summary.held.f.reason ?? undefined}>held {summary.held.text}</Chip>
          <Chip tone={summary.lastOutcome.tone} title={summary.lastOutcome.f.reason ?? undefined}>last outcome {summary.lastOutcome.text}</Chip>
          <Chip tone={history.usable && lastVerified ? 'success' : 'neutral'} title="newest VERIFIED train in the events read">
            last verified {history.usable ? (lastVerified ? `${lastVerified.trainId} · ${lastVerified.finished}` : 'none in events read') : hF.state === 'LOADING' ? '…' : 'UNAVAILABLE'}
          </Chip>
          <Chip tone={summary.currentTrain.tone} title={summary.currentTrain.f.reason ?? undefined}>current train {summary.currentTrain.text}</Chip>
          <Chip tone={summary.policy.tone} title={summary.policy.f.reason ?? undefined}>standing policy {summary.policy.text}</Chip>
          <Chip tone={summary.stop.tone} title={summary.stop.f.reason ?? undefined}>STOP (summary read) {summary.stop.text}</Chip>
        </ChipRow>
        {summary.degraded.length > 0 && sumF.state !== 'UNAVAILABLE' && (
          <div style={{ marginTop: 6, fontSize: TYPE.sm, color: TOKENS.warning }}>STALE / UNAVAILABLE: {summary.degraded.join(' · ')}</div>
        )}
        <div style={{ marginTop: 12 }} data-testid="release-train-census">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <span style={label}>PR census</span>
            <Chip tone={census.state === 'OK' ? 'neutral' : census.state === 'INCOMPLETE' ? 'danger' : 'warning'} size="md"
              title={census.reason ?? 'open PRs = sum of buckets on a complete page'}>
              {census.state === 'OK' ? `${census.openPrs} open = ${census.bucketSum} bucketed` : census.state === 'LOADING' ? '…' : census.state}
            </Chip>
            {census.state !== 'UNAVAILABLE' && census.state !== 'LOADING' && <span style={{ fontSize: TYPE.xs, color: TOKENS.text[3] }}>census {census.f.ageLabel}</span>}
            {census.reason && <span style={{ fontSize: TYPE.sm, color: census.state === 'INCOMPLETE' ? TOKENS.danger : TOKENS.warning }}>{census.reason}</span>}
          </div>
          {census.buckets.length > 0 && (
            <>
              <div role="img" aria-label={`census: ${census.buckets.map(b => `${b.name} ${b.n}`).join(', ')}`}
                style={{ display: 'flex', height: 14, marginTop: 6, borderRadius: RADIUS.sm, overflow: 'hidden', border: `1px solid ${TOKENS.border}`,
                  opacity: census.state === 'OK' ? 1 : 0.55 }}>
                {census.buckets.map((b, i) => (
                  <div key={b.name} title={`${b.name}: ${b.n}`} style={{ width: `${b.share * 100}%`, background: TOKENS.chart[i % TOKENS.chart.length] }} />
                ))}
              </div>
              <ChipRow style={{ marginTop: 6 }}>
                {census.buckets.map(b => <Chip key={b.name} tone="neutral">{b.name.replace(/_/g, ' ')} {b.n}</Chip>)}
              </ChipRow>
            </>
          )}
        </div>
      </div>

      <div style={panel} data-testid="release-train-queue">
        <Header title="Queue" sub="what is waiting · risk · dependencies · blocker · next action · intended window" f={qF} what="queue" />
        <Unavailable f={qF} what="Queue" />
        {qApi.data?.store_state && qApi.data.store_state !== 'OK' && (
          <div style={{ marginTop: 6, fontSize: TYPE.sm, color: TOKENS.warning }}>queue store {qApi.data.store_state}{qApi.data.store_state === 'NOT_MIGRATED' ? ' — the operator applies migrations/2026_10_21_release_queue.sql; the census above still lists open PRs' : ''}</div>
        )}
        {queue.usable && (
          <ChipRow style={{ marginTop: 8 }}>
            {Object.entries(queue.counts).map(([state, n]) => <Chip key={state} tone="neutral">{state.replace(/_/g, ' ')} {n}</Chip>)}
          </ChipRow>
        )}
        <div style={{ overflowX: 'auto', marginTop: 8 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                <SortHeader sortKey="pr" sort={qSort.sort} onToggle={qSort.toggle} firstDir="asc">PR</SortHeader>
                <SortHeader sortKey="title" sort={qSort.sort} onToggle={qSort.toggle} firstDir="asc">title</SortHeader>
                <SortHeader sortKey="agent" sort={qSort.sort} onToggle={qSort.toggle} firstDir="asc">agent</SortHeader>
                <SortHeader sortKey="state" sort={qSort.sort} onToggle={qSort.toggle} firstDir="asc">state</SortHeader>
                <SortHeader sortKey="risk" sort={qSort.sort} onToggle={qSort.toggle} firstDir="asc">risk</SortHeader>
                <th style={th}>depends on</th>
                <SortHeader sortKey="age" sort={qSort.sort} onToggle={qSort.toggle} align="right">age</SortHeader>
                <th style={th}>blocker</th>
                <th style={th}>next action</th>
                <SortHeader sortKey="window" sort={qSort.sort} onToggle={qSort.toggle} firstDir="asc">window</SortHeader>
              </tr>
            </thead>
            <tbody>
              {qSort.rows.map(r => (
                <tr key={r.key} style={{ borderTop: `1px solid ${TOKENS.borderSubtle}` }}>
                  <td style={mono}>#{r.pr}</td>
                  <td style={cell}>{r.title}</td>
                  <td style={cell}>{r.agent}</td>
                  <td style={cell}><Chip tone={r.stateTone}>{r.state}</Chip></td>
                  <td style={cell}><Chip tone={r.riskTone} title={r.riskWhy || undefined}>{r.risk}</Chip></td>
                  <td style={mono}>{r.dependencies}</td>
                  <td style={{ ...mono, textAlign: 'right' }}>{r.age}</td>
                  <td style={cell}>{r.blocker}</td>
                  <td style={cell}>{r.nextAction}</td>
                  <td style={mono}>{r.window}</td>
                </tr>
              ))}
              {qSort.rows.length === 0 && (
                <tr><td colSpan={10} style={{ ...cell, color: TOKENS.text[3] }}>
                  {queue.usable ? (qF.state === 'STALE' ? 'queue empty as of a STALE read' : 'queue empty') : `queue ${qF.state === 'LOADING' ? 'loading' : 'UNAVAILABLE'}`}
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div style={panel} data-testid="release-train-detail">
        <Header title="Train" sub={selected ? 'selected from history' : 'current train (from the queue)'} f={validId ? tF : undefined} what="train" />
        {!trainId ? (
          <div style={{ marginTop: 8, fontSize: TYPE.sm, color: TOKENS.text[3] }}>
            {queue.usable && qF.state === 'OK' ? 'No train running. Pick one from History to inspect it.' : `Current train UNKNOWN (queue ${qF.state}${qF.reason ? `: ${qF.reason}` : ''}). Pick one from History.`}
          </div>
        ) : !validId ? (
          <div style={{ marginTop: 8, fontSize: TYPE.sm, color: TOKENS.warning }}>Train id {trainId} does not match the API pattern; detail UNAVAILABLE.</div>
        ) : !train ? (
          <Unavailable f={tF.state === 'LOADING' ? tF : { ...tF, state: 'UNAVAILABLE' }} what={`Train ${trainId}`} />
        ) : (
          <div style={{ marginTop: 8, display: 'grid', gap: 8 }}>
            <ChipRow>
              <Chip tone="info">{train.trainId}</Chip>
              <Chip tone="neutral">window {train.window}</Chip>
              <Chip tone="info">phase {train.phase}</Chip>
              <Chip tone={OUTCOME_TONE[train.outcome]}>{OUTCOME_LABEL[train.outcome]}</Chip>
              <Chip tone="neutral">frozen {train.frozenAt}</Chip>
              <Chip tone="neutral">elapsed {train.elapsed}</Chip>
              {selected && <Chip tone="neutral" onClick={() => setSelected(null)} title="back to the current train">clear selection</Chip>}
            </ChipRow>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(min(220px,100%),1fr))', gap: 8 }}>
              {([['base', train.base], ['candidate', train.candidate], ['main', train.main], ['served', train.served], ['artifact', train.artifact], ['rollback target', train.rollbackTarget], ['checks', train.checks]] as const).map(([k, v]) => (
                <div key={k}>
                  <div style={label}>{k}</div>
                  <div style={{ fontFamily: FONT.mono, fontSize: TYPE.sm, color: v === 'UNAVAILABLE' ? TOKENS.warning : TOKENS.text[0], wordBreak: 'break-all' }}>{v}</div>
                </div>
              ))}
            </div>
            {train.servedMatchesCandidate === false && <div role="alert" style={{ fontSize: TYPE.sm, color: TOKENS.danger }}>Served SHA ≠ candidate SHA.</div>}
            {train.servedMatchesCandidate === null && <div style={{ fontSize: TYPE.sm, color: TOKENS.warning }}>Served vs candidate UNKNOWN.</div>}
            <div>
              <div style={label}>frozen membership ({train.members.length})</div>
              <ul style={{ margin: '4px 0 0', paddingLeft: 18, fontSize: TYPE.sm, color: TOKENS.text[1] }}>
                {train.members.map(m => <li key={m.pr}><span style={{ fontFamily: FONT.mono }}>#{m.pr} @{m.head}</span> · {m.risk}</li>)}
                {train.members.length === 0 && <li style={{ color: TOKENS.text[3] }}>no members recorded</li>}
              </ul>
            </div>
            <div>
              <div style={label}>timeline</div>
              <ol style={{ margin: '4px 0 0', paddingLeft: 18, fontSize: TYPE.sm, color: TOKENS.text[1] }}>
                {train.timeline.map((e, i) => (
                  <li key={`${e.at}-${i}`}><span style={{ fontFamily: FONT.mono }}>{e.at}</span> · <strong>{e.step}</strong>{e.detail ? ` · ${e.detail}` : ''}{e.actor ? ` · ${e.actor}` : ''}</li>
                ))}
                {train.timeline.length === 0 && <li style={{ color: TOKENS.text[3] }}>no events recorded</li>}
              </ol>
            </div>
          </div>
        )}
      </div>

      <div style={panel} data-testid="release-train-history">
        <Header title="History" sub="merged-not-live · verified · observing · rolled back · rollback failed — kept apart · from the newest 500 train events" f={hF} what="history" />
        <Unavailable f={hF} what="History" />
        {history.usable && (
          <ChipRow style={{ marginTop: 8 }}>
            {HISTORY_OUTCOMES.filter(o => history.counts[o] > 0 || DESIGN_OUTCOMES.includes(o)).map(o => (
              <Chip key={o} tone={history.counts[o] > 0 ? OUTCOME_TONE[o] : 'neutral'} title={o}>{OUTCOME_LABEL[o]} {history.counts[o]}</Chip>
            ))}
          </ChipRow>
        )}
        <div style={{ overflowX: 'auto', marginTop: 8 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                <SortHeader sortKey="trainId" sort={hSort.sort} onToggle={hSort.toggle} firstDir="asc">train</SortHeader>
                <SortHeader sortKey="window" sort={hSort.sort} onToggle={hSort.toggle} firstDir="asc">window</SortHeader>
                <SortHeader sortKey="outcome" sort={hSort.sort} onToggle={hSort.toggle} firstDir="asc">outcome</SortHeader>
                <SortHeader sortKey="started" sort={hSort.sort} onToggle={hSort.toggle}>started</SortHeader>
                <th style={th}>finished</th>
                <th style={th}>candidate</th>
                <th style={th}>served</th>
                <th style={{ ...th, textAlign: 'right' }}>PRs</th>
                <th style={{ ...th, textAlign: 'right' }}>events</th>
              </tr>
            </thead>
            <tbody>
              {hSort.rows.map(r => (
                <tr key={r.key} style={{ borderTop: `1px solid ${TOKENS.borderSubtle}`, background: selected === r.trainId ? TOKENS.bg[2] : undefined }}>
                  <td style={mono}>
                    <button type="button" onClick={() => setSelected(r.trainId)} title="show this train's detail"
                      style={{ background: 'none', border: 'none', padding: 0, color: TOKENS.info, cursor: 'pointer', fontFamily: FONT.mono, fontSize: TYPE.sm }}>
                      {r.trainId}
                    </button>
                  </td>
                  <td style={mono}>{r.window}</td>
                  <td style={cell}><Chip tone={OUTCOME_TONE[r.outcome]} title={r.outcomeRaw}>{OUTCOME_LABEL[r.outcome]}</Chip></td>
                  <td style={mono}>{r.started}</td>
                  <td style={mono}>{r.finished}</td>
                  <td style={mono}>{r.candidate}</td>
                  <td style={mono}>{r.served}</td>
                  <td style={{ ...mono, textAlign: 'right' }}>{r.members}</td>
                  <td style={{ ...mono, textAlign: 'right' }}>{r.events}</td>
                </tr>
              ))}
              {hSort.rows.length === 0 && (
                <tr><td colSpan={9} style={{ ...cell, color: TOKENS.text[3] }}>
                  {history.usable ? 'no train events in the read (newest 500 events)' : `history ${hF.state === 'LOADING' ? 'loading' : 'UNAVAILABLE'}`}
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
