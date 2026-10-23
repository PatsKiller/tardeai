// Ops → Controls (feat/ops-controls-20261022): change how the system runs without touching files.
// Builds against docs/ops/OPS_CONTROLS_API.md (GET/POST /api/v2/ops/controls/*). Operator-only: the server refuses
// agent callers on every route. The server decides each change kind's direction:
//   safe  (release-train STOP/pause, kill-switch engage) — one click: POST /requests {one_click:true}, poll to terminal;
//   risky (everything else) — 3 steps: (1) preview (dry run) → (2) passkey (WebAuthn) + typed phrase → (3) approve, poll.
// Telegram is notification only; nothing here waits on it. While AGENTS.md 19.0.0 is not ACTIVE every action is
// disabled (the server also answers 409 POLICY_NOT_ACTIVE); data still renders. Missing data is UNAVAILABLE, never 0.
import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { useApi } from '../hooks/useApi'
import { Chip, ChipRow, Tooltip } from '../components/primitives'
import { TOKENS, TYPE } from '../lib/watchTokens'
import { FONT, RADIUS, SHADOW, toneVars, type Tone } from '../lib/designTokens'
import {
  actBlockReason, canAct, isTerminal, kindFor, opsApi, passkeyStepUp, phraseMatches, registerPasskey, validateSetting,
  type OpsControlsState, type OpsRequest, type SettingRow,
} from '../lib/opsControls'
import { classifyJob, FILTERS, filterCounts, matchesFilter, matchesQuery, type JobFilter, type JobRowX } from '../lib/opsControlsJobs'
import {
  CHECK_TIP, DATA_FILTERS, EXPLAINER, findingText, freshnessView, matchesDataFilter, scanText, sortRows, summarize, SUMMARY_TIP,
  VERDICT_TIP, verdictView, writerText, type DataFilter, type DataRow, type FileList,
} from '../lib/opsControlsData'
import {
  failuresBadge, GLOSSARY, healthView, lastRunView, matchesN8nFilter, matchesN8nQuery, N8N_FILTERS, n8nFilterCounts, nextRunView,
  readinessView, runsText, sortRows as sortN8nRows, stageView, summaryOf, type N8nFilter, type N8nRowX,
} from '../lib/opsControlsN8n'

// ── styles ──────────────────────────────────────────────────────────────────────────────────────────
const panel: CSSProperties = { background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md, padding: 14, minWidth: 0 }
const cell: CSSProperties = { padding: '6px 6px', fontSize: TYPE.sm, color: TOKENS.text[1], verticalAlign: 'top', textAlign: 'left' }
const h2: CSSProperties = { margin: '0 0 8px', fontSize: TYPE.base, color: TOKENS.text[0] }
const muted: CSSProperties = { fontSize: TYPE.sm, color: TOKENS.text[2], margin: '4px 0' }
const mono: CSSProperties = { fontFamily: FONT.mono, fontSize: TYPE.sm, color: TOKENS.text[0] }
const pre: CSSProperties = { ...mono, background: TOKENS.bg[2], border: `1px solid ${TOKENS.borderSubtle}`, borderRadius: RADIUS.sm, padding: '6px 8px', overflowX: 'auto', whiteSpace: 'pre', margin: '4px 0', minWidth: 0 }
const input: CSSProperties = { fontSize: TYPE.base, color: TOKENS.text[0], background: TOKENS.bg[2], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.sm, padding: '6px 8px', minWidth: 0, minHeight: 32 }
const label: CSSProperties = { display: 'grid', gap: 4, fontSize: TYPE.sm, color: TOKENS.text[2], minWidth: 0 }
function btnStyle(tone: Tone | 'plain', disabled = false): CSSProperties {
  const base: CSSProperties = { fontSize: TYPE.base, fontWeight: 600, borderRadius: RADIUS.sm, padding: '6px 10px', minHeight: 32, cursor: disabled ? 'not-allowed' : 'pointer', opacity: disabled ? 0.55 : 1, whiteSpace: 'nowrap' }
  if (tone === 'plain') return { ...base, color: TOKENS.text[1], background: TOKENS.bg[2], border: `1px solid ${TOKENS.border}` }
  const t = toneVars(tone)
  return { ...base, color: t.color, background: t.bg, border: `1px solid ${t.border}` }
}
const s = (v: unknown) => (v === null || v === undefined || v === '' ? '—' : typeof v === 'object' ? JSON.stringify(v) : String(v))
const et = (v: unknown) => {
  const t = Date.parse(String(v ?? ''))
  if (!Number.isFinite(t)) return s(v)
  return new Date(t).toLocaleString('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false }) + ' ET'
}
const errText = (e: unknown) => (e instanceof Error ? e.message : String(e))
const STATUS_TONE: Record<string, Tone> = {
  APPLIED: 'success', FAILED: 'danger', REFUSED: 'danger', EXPIRED: 'warning', CANCELLED: 'neutral',
  APPROVED: 'info', APPLYING: 'info', PREVIEWED: 'neutral', AWAITING_STEP_UP: 'warning', STEP_UP_VERIFIED: 'info',
}

// ── small building blocks ──────────────────────────────────────────────────────────────────────────
function Panel({ title, right, children }: { title: string; right?: ReactNode; children: ReactNode }) {
  return <div style={panel}>
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'baseline', justifyContent: 'space-between' }}><h2 style={h2}>{title}</h2>{right}</div>
    {children}
  </div>
}

function Table({ label: aria, heads, rows }: { label: string; heads: ReactNode[]; rows: Array<Array<ReactNode>> }) {
  return <div style={{ overflowX: 'auto', minWidth: 0 }}>
    <table aria-label={aria} style={{ width: '100%', borderCollapse: 'collapse' }}>
      <thead><tr>{heads.map((h, i) => <th key={i} style={{ ...cell, color: TOKENS.text[3], whiteSpace: 'nowrap' }}>{h}</th>)}</tr></thead>
      <tbody>
        {rows.map((r, i) => <tr key={i} style={{ borderTop: `1px solid ${TOKENS.borderSubtle}` }}>{r.map((c, j) => <td key={j} style={cell}>{c ?? '—'}</td>)}</tr>)}
        {!rows.length ? <tr><td colSpan={heads.length} style={{ ...cell, color: TOKENS.text[2] }}>No rows</td></tr> : null}
      </tbody>
    </table>
  </div>
}

function Banner({ tone, title, children }: { tone: Tone; title: string; children?: ReactNode }) {
  const t = toneVars(tone)
  return <div role="alert" style={{ background: t.bg, border: `1px solid ${t.border}`, borderRadius: RADIUS.md, padding: '10px 12px', minWidth: 0 }}>
    <div style={{ fontSize: TYPE.base, fontWeight: 700, color: t.color }}>{title}</div>
    {children ? <div style={{ fontSize: TYPE.sm, color: TOKENS.text[1], marginTop: 4 }}>{children}</div> : null}
  </div>
}

/** A section that is not OK renders its state and reason, never empty-green. */
function SectionGate({ sec, children }: { sec?: { state?: string; reason?: string | null } | null; children: ReactNode }) {
  if (!sec || sec.state !== 'OK') {
    return <p role="alert" style={{ ...muted, color: TOKENS.warning, fontWeight: 600 }}>
      {sec?.state === 'NOT_MIGRATED' ? 'NOT_MIGRATED' : 'UNAVAILABLE'} — {s(sec?.reason || (sec ? 'no reason given' : 'section missing from state'))}
    </p>
  }
  return <>{children}</>
}

type Run = (kind: string, params: Record<string, unknown>, title: string) => void
/** One action button. Tone follows the server's direction; unsupported kinds show the host-terminal reason. */
function ActionButton({ state, kind, text, params, title, run, extraDisabled }: {
  state: OpsControlsState | null; kind: string; text: string; params: Record<string, unknown>; title?: string; run: Run; extraDisabled?: string | null
}) {
  const k = kindFor(state, kind)
  const block = actBlockReason(state, kind) || extraDisabled || null
  const unsupported = !!k && !k.supported
  const tone: Tone = !k ? 'neutral' : k.direction === 'safe' ? 'success' : 'danger'
  return <span style={{ display: 'inline-grid', gap: 2, minWidth: 0 }}>
    <button type="button" disabled={!!block} aria-disabled={!!block} title={block || k?.label || kind}
      onClick={() => run(kind, params, title || `${text}`)} style={btnStyle(tone, !!block)}>
      {text}{k?.direction === 'risky' && k.supported ? ' (passkey)' : ''}
    </button>
    {unsupported ? <span style={{ fontSize: TYPE.xs, color: TOKENS.text[2], maxWidth: 240, whiteSpace: 'normal' }}>Host terminal only: {s(k?.reason)}</span> : null}
  </span>
}

// ── the change flow (safe one click, or the 3-step risky modal) ──────────────────────────────────────
type FlowStart = { title: string; start: () => Promise<OpsRequest> }
type Stage = 'creating' | 'preview' | 'auth' | 'register' | 'applying' | 'done'

function FlowModal({ flow, state, onClose }: { flow: FlowStart; state: OpsControlsState | null; onClose: () => void }) {
  const [req, setReq] = useState<OpsRequest | null>(null)
  const [stage, setStage] = useState<Stage>('creating')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [typed, setTyped] = useState('')
  const [totp, setTotp] = useState('')
  const [timedOut, setTimedOut] = useState(false)
  const started = useRef(false)

  const isRegister = req?.kind === 'passkey.register'
  const useTotp = isRegister && (state?.factors?.passkeys_active ?? 0) === 0
  const allowed = req ? canAct(state, req.kind) : false
  const blockReason = req ? actBlockReason(state, req.kind) : null

  const afterApproved = (r: OpsRequest) => {
    setReq(r)
    if (isTerminal(r.status)) setStage('done')
    else if (r.kind === 'passkey.register' && r.status === 'APPROVED') setStage('register')
    else setStage('applying')
  }
  const route = (r: OpsRequest) => {
    setReq(r)
    if (isTerminal(r.status)) return setStage('done')
    if (r.status === 'APPROVED' || r.status === 'APPLYING') return afterApproved(r)
    setStage('preview')
  }

  useEffect(() => {
    if (started.current) return
    started.current = true
    flow.start().then(route).catch(e => { setErr(errText(e)); setStage('done') })
  }, [])

  // Poll GET /requests/{id} to a terminal status; the applier applies within 120 s.
  useEffect(() => {
    if (stage !== 'applying' || !req) return
    let alive = true
    let timer: ReturnType<typeof setTimeout> | undefined
    const t0 = Date.now()
    const tick = async () => {
      if (!alive) return
      try {
        const r = await opsApi.getRequest(req.request_id)
        if (!alive) return
        setReq(r); setErr(null)
        if (isTerminal(r.status)) { setStage('done'); return }
      } catch (e) { if (alive) setErr(errText(e)) }
      if (Date.now() - t0 > 180_000) { setTimedOut(true); return }
      timer = setTimeout(tick, 2000)
    }
    timer = setTimeout(tick, 1000)
    return () => { alive = false; if (timer) clearTimeout(timer) }
  }, [stage, req?.request_id])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape' && !busy) onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [busy, onClose])

  const act = async (fn: () => Promise<void>) => {
    setBusy(true); setErr(null)
    try { await fn() } catch (e) { setErr(errText(e)) } finally { setBusy(false) }
  }
  const approveSafe = () => act(async () => { if (req) afterApproved(await opsApi.approve(req.request_id)) })
  const stepUpPasskey = () => act(async () => {
    if (!req) return
    const token = await passkeyStepUp(req.request_id, typed)
    afterApproved(await opsApi.approve(req.request_id, token))
  })
  const stepUpTotp = () => act(async () => {
    if (!req) return
    const r = await opsApi.stepUpTotp(req.request_id, totp.trim(), typed)
    afterApproved(await opsApi.approve(req.request_id, r.step_up_token))
  })
  const createPasskey = () => act(async () => {
    if (!req) return
    await registerPasskey(req.request_id)
    const r = await opsApi.getRequest(req.request_id)
    setReq(r); setStage(isTerminal(r.status) ? 'done' : 'applying')
  })
  const cancel = () => act(async () => { if (req) { setReq(await opsApi.cancel(req.request_id)); setStage('done') } })

  const risky = req?.direction === 'risky'
  const stepNo = stage === 'preview' ? 1 : stage === 'auth' ? 2 : 3
  const pv = req?.preview
  const phraseOk = phraseMatches(typed, req?.phrase)
  const canCancel = !!req && !isTerminal(req.status) && req.status !== 'APPLYING' && req.status !== 'APPROVED'

  return <div role="dialog" aria-modal="true" aria-label={flow.title} data-testid="ops-controls-modal"
    onMouseDown={e => { if (e.target === e.currentTarget && !busy) onClose() }}
    style={{ position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(2,6,23,.72)', display: 'grid', placeItems: 'center', padding: 16 }}>
    <div style={{ ...panel, background: TOKENS.bg[1], width: 'min(680px, 100%)', maxHeight: '90vh', overflowY: 'auto', boxShadow: SHADOW[3], display: 'grid', gap: 10 }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'baseline', justifyContent: 'space-between' }}>
        <h2 style={{ ...h2, fontSize: TYPE.md, margin: 0 }}>{flow.title}</h2>
        <ChipRow>
          {req ? <Chip tone={risky ? 'danger' : 'success'}>{risky ? 'risky · passkey + phrase' : 'safe · one click'}</Chip> : null}
          {risky ? <Chip tone="neutral">step {stepNo} of 3</Chip> : null}
          {req ? <Chip tone={STATUS_TONE[req.status] || 'neutral'}>{req.status}</Chip> : null}
        </ChipRow>
      </div>
      {req ? <p style={{ ...muted, margin: 0 }}>{s(req.label || req.kind)} · <span style={mono}>{req.request_id}</span></p> : null}
      {blockReason && req && !isTerminal(req.status) && (stage === 'preview' || stage === 'auth') ? <Banner tone="warning" title="This change cannot be approved here">{blockReason}</Banner> : null}

      {stage === 'creating' ? <p style={muted}>Creating the request and its dry-run preview…</p> : null}

      {req && (stage === 'preview' || stage === 'auth' || stage === 'done') && pv ? <div style={{ display: 'grid', gap: 4, minWidth: 0 }}>
        <div style={{ fontSize: TYPE.sm, fontWeight: 700, color: TOKENS.text[2] }}>Preview · dry run</div>
        {pv.summary ? <p style={{ ...muted, color: TOKENS.text[1] }}>{pv.summary}</p> : null}
        {pv.diff?.length ? <pre style={pre}>{pv.diff.join('\n')}</pre>
          : (pv.before !== undefined || pv.after !== undefined) ? <pre style={pre}>{`before: ${s(pv.before)}\nafter:  ${s(pv.after)}`}</pre> : null}
        {(pv.warnings || []).map((w, i) => <p key={i} style={{ ...muted, color: TOKENS.warning }}>Warning: {w}</p>)}
        {req.expected_state_digest ? <p style={muted}>The applier refuses if the target changed since this preview (digest <span style={mono}>{req.expected_state_digest.slice(0, 16)}</span>).</p> : null}
      </div> : null}

      {req && stage === 'preview' && !risky ? <p style={muted}>Safe direction: approving applies it; no passkey needed.</p> : null}

      {req && stage === 'auth' ? <div style={{ display: 'grid', gap: 8, minWidth: 0 }}>
        <div style={{ fontSize: TYPE.sm, fontWeight: 700, color: TOKENS.text[2] }}>Authenticate</div>
        <p style={muted}>Type this phrase exactly:</p>
        <pre style={{ ...pre, fontSize: TYPE.base }} data-testid="ops-controls-phrase">{s(req.phrase)}</pre>
        <label style={label}>Confirmation phrase
          <input value={typed} onChange={e => setTyped(e.target.value)} autoComplete="off" spellCheck={false} aria-invalid={!!typed && !phraseOk} style={input} />
        </label>
        {typed && !phraseOk ? <span style={{ fontSize: TYPE.sm, color: TOKENS.warning }}>Does not match yet.</span> : null}
        {useTotp ? <>
          <p style={muted}>No active passkey exists, so this recovery registration uses your authenticator app (TOTP){state?.factors?.totp !== 'enrolled' ? ' — but TOTP is not enrolled; the server will refuse' : ''}.</p>
          <label style={label}>TOTP code
            <input value={totp} onChange={e => setTotp(e.target.value.replace(/\D/g, '').slice(0, 8))} inputMode="numeric" autoComplete="one-time-code" style={{ ...input, maxWidth: 160 }} />
          </label>
        </> : <p style={muted}>Then confirm with a passkey on this device{state?.factors?.webauthn_library === 'missing' ? ' — the server WebAuthn library is missing; verification will fail' : ''}.</p>}
        <p style={{ ...muted, fontStyle: 'italic' }}>Telegram is notified; it confirms nothing.</p>
      </div> : null}

      {req && stage === 'register' ? <div style={{ display: 'grid', gap: 6 }}>
        <p style={muted}>Approved. Create the new passkey “{s(req.params?.name)}” on this device. Your browser will ask for your screen lock or security key.</p>
      </div> : null}

      {req && stage === 'applying' ? <div style={{ display: 'grid', gap: 6 }}>
        <p style={muted} aria-live="polite">{req.executor === 'cc' ? 'Finishing…' : 'Approved. The host applier applies it within 120 s; this updates by itself.'} Status: <b>{req.status}</b></p>
        {timedOut ? <p style={{ ...muted, color: TOKENS.warning }}>Still not terminal after 3 minutes. Check the applier banner and the Audit & undo tab; nothing is assumed applied.</p> : null}
      </div> : null}

      {stage === 'done' && req ? <div style={{ display: 'grid', gap: 6 }}>
        <Banner tone={STATUS_TONE[req.status] || 'neutral'} title={req.status === 'APPLIED' ? 'Applied' : req.status}>
          {req.result ? <>{s(req.result.outcome)}{req.result.detail ? ` — ${req.result.detail}` : ''}{req.result.backup_ref ? <> · backup <span style={mono}>{req.result.backup_ref}</span></> : null}</> : 'No result recorded.'}
        </Banner>
        {req.status === 'APPLIED' ? <p style={muted}>Audited. {req.undo?.available ? `Undo is available on the Audit & undo tab (${s(req.undo.kind)}, ${s(req.undo.direction)} direction).` : req.undo?.reason ? `No undo: ${req.undo.reason}.` : 'See the Audit & undo tab.'}</p> : null}
      </div> : null}

      {err ? <Banner tone="danger" title="Request error">{err}</Banner> : null}

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, justifyContent: 'flex-end' }}>
        {canCancel ? <button type="button" disabled={busy} onClick={cancel} style={btnStyle('plain', busy)}>Cancel request</button> : null}
        <button type="button" disabled={busy} onClick={onClose} style={btnStyle('plain', busy)}>{stage === 'done' ? 'Close' : 'Close (keeps the request)'}</button>
        {req && stage === 'preview' && risky ? <button type="button" disabled={!allowed} onClick={() => setStage('auth')} style={btnStyle('info', !allowed)}>Next: authenticate</button> : null}
        {req && stage === 'preview' && !risky ? <button type="button" disabled={busy || !allowed} onClick={approveSafe} style={btnStyle('success', busy || !allowed)}>Approve (safe)</button> : null}
        {req && stage === 'auth' && useTotp ? <button type="button" disabled={busy || !allowed || !phraseOk || totp.length < 6} onClick={stepUpTotp}
          style={btnStyle('danger', busy || !allowed || !phraseOk || totp.length < 6)}>Verify TOTP and approve</button> : null}
        {req && stage === 'auth' && !useTotp ? <button type="button" disabled={busy || !allowed || !phraseOk} onClick={stepUpPasskey}
          style={btnStyle('danger', busy || !allowed || !phraseOk)}>{busy ? 'Waiting for passkey…' : 'Use passkey and approve'}</button> : null}
        {req && stage === 'register' ? <button type="button" disabled={busy} onClick={createPasskey} style={btnStyle('success', busy)}>{busy ? 'Creating…' : 'Create passkey'}</button> : null}
      </div>
    </div>
  </div>
}

// ── tabs ─────────────────────────────────────────────────────────────────────────────────────────────
type TabKey = 'jobs' | 'n8n' | 'flags' | 'data' | 'grants' | 'audit'
const count = (sec: { state?: string } | undefined, n: number | undefined) => (sec?.state === 'OK' ? String(n ?? 0) : '—')

function JobsTab({ d, run }: { d: OpsControlsState | null; run: Run }) {
  const [reason, setReason] = useState('')
  const rt = d?.release_train
  const safeParams = reason.trim() ? { reason: reason.trim() } : {}
  const jobs = d?.jobs
  return <div style={{ display: 'grid', gap: 12, minWidth: 0 }}>
    <Panel title="Release train & kill switch">
      <p style={muted}>STOP, Pause and Engage are the safe direction: one click, no passkey. The way back (resume, arm, clear) is host terminal only for now.</p>
      <label style={{ ...label, maxWidth: 420, marginBottom: 8 }}>Reason (optional, recorded in the audit trail)
        <input value={reason} onChange={e => setReason(e.target.value)} maxLength={200} style={input} />
      </label>
      <Table label="Release train and kill switch" heads={['Control', 'State', 'Safe direction', 'Risky direction']} rows={[
        ['Release train', rt?.state === 'OK' ? <ChipRow><Chip tone="neutral">{s(rt.mode)}</Chip><Chip tone="neutral">epoch {s(rt.epoch)}</Chip><Chip tone={rt.latch === 'ABSENT' ? 'neutral' : 'warning'}>STOP latch {s(rt.latch)}</Chip></ChipRow> : <SectionGate sec={rt}>{null}</SectionGate>,
          <ChipRow><ActionButton state={d} kind="release_train.stop" text="STOP" params={safeParams} title="STOP the release train" run={run} />
            <ActionButton state={d} kind="release_train.pause" text="Pause" params={safeParams} title="Pause the release train" run={run} /></ChipRow>,
          <ChipRow><ActionButton state={d} kind="release_train.resume" text="Resume" params={{}} run={run} />
            <ActionButton state={d} kind="release_train.arm" text="Arm" params={{}} run={run} /></ChipRow>],
        ['Global kill switch', <span style={{ color: TOKENS.text[2] }}>state not in this read model</span>,
          <ActionButton state={d} kind="kill_switch.engage" text="Engage" params={{ scope: 'global', ...safeParams }} title="Engage the global kill switch" run={run} />,
          <ActionButton state={d} kind="kill_switch.clear" text="Clear" params={{ scope: 'global' }} run={run} />],
      ]} />
    </Panel>
    <JobsSchedules d={d} run={run} />
  </div>
}

// ── Jobs & schedules (readability, 2026-10-22) ──────────────────────────────────────────────────────────────────────
// Operator: "I have no idea how to interpret this … Is this actually N8N? There are no tooltips." Each row is one
// registry cron lane matched to the host crontab; src/lib/opsControlsJobs.ts turns it into a plain status and flags
// where the crontab and config/lane_registry.json disagree. Tooltip copy states what the server does (jobs_view,
// plan_change in scripts/lib/ops_controls_{api,core}.py), nothing more.
const tipHead: CSSProperties = { borderBottom: `1px dotted ${TOKENS.text[3]}`, cursor: 'help' }
function HeadTip({ text, tip }: { text: string; tip: ReactNode }) {
  return <Tooltip content={<div style={{ display: 'grid', gap: 4 }}>{tip}</div>} placement="bottom"><span style={tipHead}>{text}</span></Tooltip>
}
const LIVE_TIP: Record<string, string> = {
  ACTIVE: 'Live crontab: exactly one uncommented line contains this job’s match text, so cron runs it on its schedule.',
  PAUSED: 'Live crontab: the only matching line is commented out as “# PAUSED <date> <note> <line>”, so cron skips it. The date and note say when and why.',
  ABSENT: 'Live crontab: no matching line at all, active or paused. Cron never runs it (n8n may — see the n8n lanes tab).',
  AMBIGUOUS: 'Live crontab: more than one line contains this job’s match text. The page will not pick one, so it offers no action; change it at the host terminal.',
}
const REG_TIP: Record<string, string> = {
  ACTIVE: 'Registry (config/lane_registry.json) says this job should run.',
  PAUSED: 'Registry says this job is off for now; a paused row carries a review date so you are asked again.',
  RETIRED: 'Registry says this job is off for good. The row is kept so its silence reads as expected, not as a failure.',
  NEVER_SCHEDULED: 'Registry declares the job but it was never given a schedule.',
}
const LIVE_TONE: Record<string, Tone> = { ACTIVE: 'success', PAUSED: 'warning', ABSENT: 'neutral', AMBIGUOUS: 'warning' }
const COLS = 6

function JobsSchedules({ d, run }: { d: OpsControlsState | null; run: Run }) {
  const jobs = d?.jobs
  const rows = (jobs?.rows || []) as JobRowX[]
  const [filter, setFilter] = useState<JobFilter>('all')
  const [q, setQ] = useState('')
  const [showQuiet, setShowQuiet] = useState(false)
  const [open, setOpen] = useState<Set<string>>(() => new Set())
  const views = rows.map(r => ({ r, v: classifyJob(r) }))
  const counts = filterCounts(rows)
  const attention = views.filter(x => x.v.mismatch)
  const searching = q.trim() !== ''
  const matched = views.filter(x => matchesFilter(x.r, x.v, filter) && matchesQuery(x.r, q))
  const hideQuiet = filter === 'all' && !searching && !showQuiet
  const quietN = matched.filter(x => x.v.quiet).length
  const shown = hideQuiet ? matched.filter(x => !x.v.quiet) : matched
  const toggle = (id: string) => setOpen(prev => { const n = new Set(prev); if (n.has(id)) n.delete(id); else n.add(id); return n })
  const pauseKind = kindFor(d, 'crontab.pause')

  return <Panel title="Jobs & schedules" right={jobs?.state === 'OK' ? <span style={muted}>as of {et(jobs.as_of)}</span> : null}>
    <SectionGate sec={jobs}>
      <p style={{ ...muted, color: TOKENS.text[1] }} data-testid="ops-jobs-explainer">
        One row per <b>cron job</b> declared in the lane registry (<span style={mono}>config/lane_registry.json</span>), matched to the
        live host crontab (<span style={mono}>crontab -l</span>). <b>Status</b> says, in words, what the crontab does right now and whether
        the registry agrees. Jobs that <b>n8n</b> schedules live on the <b>n8n lanes</b> tab; a row here says “Runs on n8n” when its cron
        line was removed at cut-over. Hover or tap any underlined heading or badge for its meaning. Times are host time (ET).
      </p>

      {attention.length ? <div role="region" aria-label="Needs attention" data-testid="ops-jobs-attention"
        style={{ background: toneVars('danger').bg, border: `1px solid ${toneVars('danger').border}`, borderRadius: RADIUS.md, padding: '8px 10px', margin: '8px 0', display: 'grid', gap: 4, minWidth: 0 }}>
        <div style={{ fontSize: TYPE.base, fontWeight: 700, color: toneVars('danger').color }}>
          Needs attention · {attention.length} job{attention.length === 1 ? '' : 's'} where the crontab and the registry disagree
        </div>
        {attention.map(({ r, v }) => <div key={r.lane_id} style={{ fontSize: TYPE.sm, color: TOKENS.text[1], minWidth: 0, overflowWrap: 'anywhere' }}>
          <button type="button" onClick={() => { setFilter('attention'); setOpen(prev => new Set(prev).add(r.lane_id)) }}
            style={{ background: 'transparent', border: 'none', padding: 0, color: TOKENS.text[0], fontWeight: 600, cursor: 'pointer', fontSize: TYPE.sm, textDecoration: 'underline' }}>{r.lane_id}</button>
          {' '}— {v.mismatch}.{r.broker_class ? ' Broker job.' : ''}
        </div>)}
      </div> : <p style={muted} data-testid="ops-jobs-attention-none">Needs attention: none — every job’s live crontab state agrees with the registry.</p>}

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center', margin: '8px 0' }} role="group" aria-label="Filter jobs">
        {FILTERS.map(([k, text]) => {
          const sel = filter === k
          return <button key={k} type="button" aria-pressed={sel} onClick={() => setFilter(k)}
            style={{ ...btnStyle(sel ? (k === 'attention' && counts.attention ? 'danger' : 'info') : 'plain'), padding: '4px 10px', minHeight: 28, fontSize: TYPE.sm }}>
            {text} <span style={{ fontFamily: FONT.mono, color: TOKENS.text[2] }}>{counts[k]}</span>
          </button>
        })}
        <input type="search" value={q} onChange={e => setQ(e.target.value)} placeholder="Search job name" aria-label="Search job name"
          style={{ ...input, flex: '1 1 180px', maxWidth: 280, minHeight: 28, fontSize: TYPE.sm }} />
      </div>

      <div style={{ overflowX: 'auto', minWidth: 0 }}>
        <table aria-label="Jobs and schedules" style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead><tr>
            <th style={{ ...cell, color: TOKENS.text[3] }}>Job</th>
            <th style={{ ...cell, color: TOKENS.text[3], whiteSpace: 'nowrap' }}><HeadTip text="Status" tip={<>
              <span>Plain words for two facts: what the live crontab does, and what the registry declares.</span>
              <span><b>Running</b> — cron runs it. <b>Paused since …</b> — the line is commented with a date and reason. <b>Retired</b> — off on purpose, no line. <b>Runs on n8n</b> — no cron line; n8n dispatches it live.</span>
              <span>“— but registry says …” means the two disagree; those rows are pinned under Needs attention.</span></>} /></th>
            <th style={{ ...cell, color: TOKENS.text[3], whiteSpace: 'nowrap' }}><HeadTip text="Runs on" tip={<>
              <span><b>cron</b> — a line in the host crontab (<span style={mono}>crontab -l</span>), found by the registry’s match text.</span>
              <span><b>cron + n8n</b> — the cron line is still there and n8n also fires it live under the same lock (canary).</span>
              <span><b>n8n</b> — the cron line was removed at cut-over; manage it on the n8n lanes tab.</span></>} /></th>
            <th style={{ ...cell, color: TOKENS.text[3], whiteSpace: 'nowrap' }}><HeadTip text="Crontab · registry" tip={<>
              <span>The raw badges behind Status.</span>
              <span><b>Crontab</b>: ACTIVE one live line · PAUSED one “# PAUSED” line · ABSENT no line · AMBIGUOUS several lines (no action here).</span>
              <span><b>Registry</b>: what <span style={mono}>config/lane_registry.json</span> declares — ACTIVE, PAUSED, RETIRED or NEVER_SCHEDULED.</span></>} /></th>
            <th style={{ ...cell, color: TOKENS.text[3] }}>Schedule</th>
            <th style={{ ...cell, color: TOKENS.text[3], whiteSpace: 'nowrap' }}><HeadTip text="Action" tip={<>
              <span><b>Pause</b> comments the exact line out as “# PAUSED &lt;today&gt; ops-controls:&lt;request&gt; …”; <b>Resume</b> uncomments it.</span>
              <span>Pausing is the lower-risk direction, but the server treats both as {pauseKind?.direction === 'safe' ? 'safe (one click)' : 'risky'}: a dry-run preview, then a passkey and the typed phrase “PAUSE CRON &lt;job&gt; &lt;date&gt;” or “RESUME CRON &lt;job&gt; &lt;date&gt;”. The host applier backs up the crontab, applies within 120 s, and offers an undo.</span>
              <span><b>Host terminal</b>: the page cannot act safely — several lines match, the paused note is more than one word, or there is no line.</span></>} /></th>
          </tr></thead>
          <tbody>
            {shown.map(({ r, v }) => {
              const isOpen = open.has(r.lane_id)
              const runsOn = v.label.startsWith('Runs on n8n') ? 'n8n' : String(r.dispatch_mode || '') === 'live' && r.cron_state !== 'ABSENT' ? 'cron + n8n' : s(r.scheduler_kind)
              const st = toneVars(v.tone)
              return [
                <tr key={r.lane_id} style={{ borderTop: `1px solid ${TOKENS.borderSubtle}` }} data-testid="ops-jobs-row">
                  <td style={cell}>
                    <span style={{ display: 'grid', gap: 2, minWidth: 0 }}>
                      <button type="button" aria-expanded={isOpen} onClick={() => toggle(r.lane_id)}
                        style={{ background: 'transparent', border: 'none', padding: 0, textAlign: 'left', cursor: 'pointer', color: TOKENS.text[0], fontWeight: 600, fontSize: TYPE.sm, overflowWrap: 'anywhere' }}>
                        <span aria-hidden style={{ color: TOKENS.text[3], marginRight: 4 }}>{isOpen ? '▾' : '▸'}</span>{r.lane_id}
                      </button>
                      {r.broker_class ? <Tooltip content={`Its command touches broker code (${(r.broker_tokens || []).join(', ') || 'broker tokens'}). Previews warn before pausing or resuming it.`}>
                        <Chip tone="warning">broker job</Chip></Tooltip> : null}
                    </span>
                  </td>
                  <td style={{ ...cell, color: st.color, fontWeight: 600, minWidth: 180 }}>{v.label}</td>
                  <td style={{ ...cell, whiteSpace: 'nowrap' }}>{runsOn}</td>
                  <td style={cell}><ChipRow>
                    <Tooltip content={LIVE_TIP[r.cron_state] || 'Unknown crontab state'}><Chip tone={LIVE_TONE[r.cron_state] || 'neutral'}>crontab {r.cron_state}</Chip></Tooltip>
                    {r.registry_state ? <Tooltip content={REG_TIP[r.registry_state] || `Registry declares ${r.registry_state}.`}><Chip tone="neutral">registry {r.registry_state}</Chip></Tooltip> : null}
                  </ChipRow></td>
                  <td style={cell}>
                    <span style={{ display: 'grid', gap: 2 }}>
                      {v.scheduleText ? <span style={{ color: TOKENS.text[0] }}>{v.scheduleText}</span> : null}
                      <span style={{ ...mono, color: TOKENS.text[2] }}>{v.cronExpr || s(r.schedule)}</span>
                    </span>
                  </td>
                  <td style={cell}>
                    {v.action === 'pause' && r.line_sha256 ? <ActionButton state={d} kind="crontab.pause" text="Pause" params={{ line_sha256: r.line_sha256, lane_id: r.lane_id }} title={`Pause ${r.lane_id}`} run={run} />
                      : v.action === 'resume' && r.line_sha256 ? <ActionButton state={d} kind="crontab.resume" text="Resume" params={{ line_sha256: r.line_sha256, lane_id: r.lane_id }} title={`Resume ${r.lane_id}`} run={run} />
                        : <Tooltip content={v.actionNote || 'No action'}><span style={{ color: TOKENS.text[2], ...tipHead }}>{r.cron_state === 'ABSENT' ? 'none' : 'host terminal'}</span></Tooltip>}
                  </td>
                </tr>,
                isOpen ? <tr key={`${r.lane_id}:detail`}>
                  <td colSpan={COLS} style={{ ...cell, background: TOKENS.bg[2], paddingLeft: 18 }}>
                    <div style={{ display: 'grid', gap: 4, minWidth: 0 }} data-testid="ops-jobs-detail">
                      {v.mismatch ? <span style={{ color: TOKENS.danger, fontWeight: 600 }}>Disagreement: {v.mismatch}.</span> : null}
                      <span><b>Registry:</b> {s(r.registry_state)}{r.registry_since ? ` since ${r.registry_since}` : ''}{r.registry_reason ? ` — ${r.registry_reason}` : ''}</span>
                      {r.dispatch_mode ? <span><b>n8n dispatch mode:</b> {r.dispatch_mode}</span> : null}
                      {r.match_counts ? <span><b>Matching crontab lines:</b> {r.match_counts.active} active, {r.match_counts.paused} paused</span> : null}
                      {v.pausedReason ? <span><b>Paused:</b> {s(r.paused_on)} · {v.pausedReason}</span> : null}
                      {v.actionNote ? <span><b>Action:</b> {v.actionNote}.</span> : null}
                      {r.broker_tokens?.length ? <span><b>Broker tokens:</b> <span style={mono}>{r.broker_tokens.join(', ')}</span></span> : null}
                      {r.note ? <span><b>Registry note:</b> {r.note}</span> : null}
                      {r.display ? <><b>Crontab line (secrets redacted):</b><pre style={{ ...pre, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>{r.display}</pre></> : <span><b>Crontab line:</b> none shown{r.cron_state === 'AMBIGUOUS' ? ' (several lines match)' : ''}</span>}
                    </div>
                  </td>
                </tr> : null,
              ]
            })}
            {!shown.length ? <tr><td colSpan={COLS} style={{ ...cell, color: TOKENS.text[2] }}>No jobs match.</td></tr> : null}
          </tbody>
        </table>
      </div>
      {hideQuiet && quietN ? <button type="button" onClick={() => setShowQuiet(true)} style={{ ...btnStyle('plain'), marginTop: 8 }} data-testid="ops-jobs-show-quiet">
        Show {quietN} retired / never-scheduled job{quietN === 1 ? '' : 's'} (off on purpose, no crontab line)</button>
        : filter === 'all' && showQuiet && !searching ? <button type="button" onClick={() => setShowQuiet(false)} style={{ ...btnStyle('plain'), marginTop: 8 }}>Hide retired / never-scheduled</button> : null}
      {(jobs?.unmatched_active_lines ?? 0) > 0 ? <p style={muted}>{jobs?.unmatched_active_lines} active crontab line(s) match no registry job, so they are not listed or controllable here.</p> : null}
    </SectionGate>
  </Panel>
}

// ── n8n lanes dashboard (outcomes, 2026-10-22) ──────────────────────────────────────────────────────────────────────
// Operator: "Why do some of these say live? Some of them say dry runs. I don't know if the last one was success or
// failure. This is not a real dashboard... When is everything going live?" Each row is one registry n8n lane joined (on
// the server, scripts/lib/ops_controls_n8n_outcomes.py) with the n8n coordination ledger: last run, health, next run and
// promotion readiness against the documented ladder. src/lib/opsControlsN8n.ts turns it into words. The live-list
// actions are unchanged (risky: preview + passkey + typed phrase).
const N8N_COLS = 8
const pl: CSSProperties = { whiteSpace: 'pre-line' }
function Tip({ tip, children }: { tip: string; children: ReactNode }) {
  return <Tooltip content={<span style={pl}>{tip}</span>}><span style={tipHead}>{children}</span></Tooltip>
}
const TILES: Array<{ key: 'live_healthy' | 'live_failing' | 'rehearsing' | 'ready_to_promote' | 'never_ran'; label: string; tone: Tone; filter: N8nFilter | null; tip: string }> = [
  { key: 'live_healthy', label: 'Live & healthy', tone: 'success', filter: 'live', tip: 'Lanes whose fires are real (live) today and whose last run succeeded, with no unanswered slot, open dead letter or breaker.' },
  { key: 'live_failing', label: 'Live & failing', tone: 'danger', filter: 'failing', tip: 'Live lanes whose last run failed or timed out, that have an unreleased dead letter or open breaker, or that missed a scheduled slot.' },
  { key: 'rehearsing', label: 'Rehearsing (shadow)', tone: 'info', filter: 'shadow', tip: 'Lanes n8n runs as a dry run today: shadow lanes, and canary lanes not on the live list. The cron line still does the real work.' },
  { key: 'ready_to_promote', label: 'Ready to promote', tone: 'info', filter: 'ready', tip: 'Lanes that meet every measurable documented condition for their next step (shadow → canary, or canary → cutover). Promotion is still the operator’s call by a reviewed registry PR.' },
  { key: 'never_ran', label: 'Never ran', tone: 'warning', filter: null, tip: 'Active lanes with no run in the n8n coordination ledger.' },
]

function N8nTab({ d, run }: { d: OpsControlsState | null; run: Run }) {
  const n = d?.n8n
  const rows = (n?.rows || []) as N8nRowX[]
  const [filter, setFilter] = useState<N8nFilter>('all')
  const [q, setQ] = useState('')
  const [open, setOpen] = useState<Set<string>>(() => new Set())
  const nowMs = Date.parse(String(n?.outcomes_as_of || d?.as_of || '')) || Date.now()
  const counts = n8nFilterCounts(rows)
  const summary = summaryOf(rows, n?.summary)
  const shown = sortN8nRows(rows.filter(r => matchesN8nFilter(r, filter) && matchesN8nQuery(r, q)))
  const toggle = (id: string) => setOpen(prev => { const x = new Set(prev); if (x.has(id)) x.delete(id); else x.add(id); return x })
  const head = (text: string, tip: string) => <th style={{ ...cell, color: TOKENS.text[3], whiteSpace: 'nowrap' }}><Tip tip={tip}>{text}</Tip></th>

  return <Panel title="n8n lanes" right={n?.outcomes_as_of ? <span style={muted}>run data as of {et(n.outcomes_as_of)} · refreshes every {n.cache_ttl_s ?? 60} s</span> : null}>
    <SectionGate sec={n}>
      <p style={{ ...muted, color: TOKENS.text[1] }} data-testid="ops-n8n-explainer">
        Every lane <b>n8n</b> schedules or dispatches, with what its <b>last run</b> actually did (from the n8n coordination ledger), when it runs
        <b> next</b>, and whether it may climb the ladder <Tip tip={GLOSSARY.shadow}>shadow</Tip> → <Tip tip={GLOSSARY.canary}>canary</Tip> → <Tip tip={GLOSSARY.cutover}>cutover</Tip>.
        A lane fires for real only when its stage allows <Tip tip={GLOSSARY.live}>live</Tip> <i>and</i> it is on the <Tip tip={GLOSSARY.live_list}>live list</Tip>; otherwise n8n runs it as a <Tip tip={GLOSSARY.dry_run}>dry run</Tip>.
        <b> When does it go live?</b> <Tip tip={GLOSSARY.promotion}>Promotion</Tip> is your decision, made by a reviewed registry PR; the Promotion column shows the evidence and what is missing.
      </p>
      {n?.outcomes_state === 'UNAVAILABLE' ? <Banner tone="warning" title="Run outcomes unavailable">{s(n.outcomes_reason)} — last run, health and readiness are not measured; nothing is assumed.</Banner> : null}

      {summary ? <div role="group" aria-label="n8n summary" data-testid="ops-n8n-summary"
        style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 8, margin: '8px 0', minWidth: 0 }}>
        {TILES.map(tile => {
          const v = summary[tile.key], tv = toneVars(v ? tile.tone : 'neutral'), sel = tile.filter !== null && filter === tile.filter
          return <Tooltip key={tile.key} content={tile.tip} as="div">
            <button type="button" aria-pressed={sel} disabled={tile.filter === null} onClick={() => tile.filter && setFilter(sel ? 'all' : tile.filter)}
              style={{ width: '100%', textAlign: 'left', background: tv.bg, border: `1px solid ${sel ? tv.color : tv.border}`, borderRadius: RADIUS.md, padding: '8px 10px', cursor: tile.filter ? 'pointer' : 'default', minWidth: 0 }}>
              <div style={{ fontFamily: FONT.mono, fontSize: TYPE.lg, fontWeight: 700, color: tv.color }}>{v}</div>
              <div style={{ fontSize: TYPE.sm, color: TOKENS.text[1] }}>{tile.label}</div>
            </button>
          </Tooltip>
        })}
      </div> : null}

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center', margin: '8px 0' }} role="group" aria-label="Filter n8n lanes">
        {N8N_FILTERS.map(([k, text]) => {
          const sel = filter === k
          return <button key={k} type="button" aria-pressed={sel} onClick={() => setFilter(k)}
            style={{ ...btnStyle(sel ? (k === 'failing' && counts.failing ? 'danger' : 'info') : 'plain'), padding: '4px 10px', minHeight: 28, fontSize: TYPE.sm }}>
            {text} <span style={{ fontFamily: FONT.mono, color: TOKENS.text[2] }}>{counts[k]}</span>
          </button>
        })}
        <input type="search" value={q} onChange={e => setQ(e.target.value)} placeholder="Search lane" aria-label="Search lane"
          style={{ ...input, flex: '1 1 180px', maxWidth: 280, minHeight: 28, fontSize: TYPE.sm }} />
      </div>

      <div style={{ overflowX: 'auto', minWidth: 0 }}>
        <table aria-label="n8n lanes" style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead><tr>
            <th style={{ ...cell, color: TOKENS.text[3] }}>Lane</th>
            {head('Stage', `${GLOSSARY.shadow}\n\n${GLOSSARY.canary}\n\n${GLOSSARY.cutover}`)}
            {head('Last run', '✓ succeeded · ✗ failed or timed out · ↷ skipped (the other scheduler held the shared lock) · · never ran. Hover a cell for the reason, mode and run id.')}
            {head('Health', 'OK · Failing (last run failed, dead letter or breaker open) · Stale (a scheduled slot has no run, 45 min grace) · Never ran · Off. The badge counts failed and timed-out runs.')}
            {head('7 days', 'Runs recorded in the last 7 days by mode: live (real) and dry (rehearsal).')}
            {head('Next run', 'Next fire of the registry schedule (dispatch cron, else the workflow cadence), in ET.')}
            {head('Promotion', GLOSSARY.promotion)}
            {head('Live list', `${GLOSSARY.live_list}\nBoth directions are risky on the server: dry-run preview, then a passkey and the typed phrase “ADD LIVE <lane> <date>” or “REMOVE LIVE <lane> <date>”. The host applier backs up the file, edits it, restarts the relay and gateway, and offers an undo.`)}
          </tr></thead>
          <tbody>
            {shown.map(r => {
              const isOpen = open.has(r.lane_id)
              const st = stageView(r), lr = lastRunView(r, nowMs), hv = healthView(r), fb = failuresBadge(r)
              const nx = nextRunView(r, nowMs), rv = readinessView(r), rd = r.readiness
              return [
                <tr key={r.lane_id} style={{ borderTop: `1px solid ${TOKENS.borderSubtle}` }} data-testid="ops-n8n-row">
                  <td style={cell}>
                    <button type="button" aria-expanded={isOpen} onClick={() => toggle(r.lane_id)}
                      style={{ background: 'transparent', border: 'none', padding: 0, textAlign: 'left', cursor: 'pointer', color: TOKENS.text[0], fontWeight: 600, fontSize: TYPE.sm, overflowWrap: 'anywhere' }}>
                      <span aria-hidden style={{ color: TOKENS.text[3], marginRight: 4 }}>{isOpen ? '▾' : '▸'}</span>{r.lane_id}
                    </button>
                  </td>
                  <td style={{ ...cell, minWidth: 170 }}><Tooltip content={<span style={pl}>{st.tip}</span>}><span style={{ color: toneVars(st.tone).color, fontWeight: 600, ...tipHead }}>{st.label}</span></Tooltip></td>
                  <td style={{ ...cell, whiteSpace: 'nowrap' }}><Tooltip content={<span style={pl}>{lr.tip}</span>}>
                    <span style={{ color: toneVars(lr.tone).color, ...tipHead }}><b aria-hidden>{lr.icon}</b> {lr.text}</span></Tooltip></td>
                  <td style={cell}><ChipRow>
                    <Tooltip content={<span style={pl}>{hv.reason ? `${hv.tip}\n\n${hv.reason}` : hv.tip}</span>}><Chip tone={hv.tone}>{hv.label}</Chip></Tooltip>
                    {fb ? <Chip tone={fb.tone}>{fb.text}</Chip> : null}
                  </ChipRow></td>
                  <td style={{ ...cell, whiteSpace: 'nowrap', fontFamily: FONT.mono }}>{runsText(r) ?? '—'}</td>
                  <td style={{ ...cell, whiteSpace: 'nowrap' }}>{nx ? <Tip tip={nx.tip}>{nx.text}</Tip> : '—'}</td>
                  <td style={cell}><Tooltip content={<span style={pl}>{rv.tip}</span>}><Chip tone={rv.tone}>{rv.label}</Chip></Tooltip></td>
                  <td style={cell}>
                    <span style={{ display: 'inline-grid', gap: 4, minWidth: 0 }}>
                      <Chip tone={r.on_live_list ? 'info' : 'neutral'}>{r.on_live_list === null || r.on_live_list === undefined ? 'unknown' : r.on_live_list ? 'on list' : 'not listed'}</Chip>
                      {r.on_live_list ? <ActionButton state={d} kind="n8n_live_list.remove" text="Remove" params={{ lane_id: r.lane_id }} title={`Remove ${r.lane_id} from the n8n live list`} run={run} />
                        : <ActionButton state={d} kind="n8n_live_list.add" text="Add to live list" params={{ lane_id: r.lane_id }} title={`Add ${r.lane_id} to the n8n live list`} run={run} />}
                    </span>
                  </td>
                </tr>,
                isOpen ? <tr key={`${r.lane_id}:detail`}>
                  <td colSpan={N8N_COLS} style={{ ...cell, background: TOKENS.bg[2], paddingLeft: 18 }}>
                    <div style={{ display: 'grid', gap: 4, minWidth: 0, overflowWrap: 'anywhere' }} data-testid="ops-n8n-detail">
                      <span><b>Registry:</b> stage <span style={mono}>{s(r.stage)}</span> · mode <span style={mono}>{s(r.mode)}</span> · state {s(r.registry_state)} · scheduler {s(r.scheduler_kind)} · class {s(r.dispatch_class)} · workflow <span style={mono}>{s(r.workflow)}</span></span>
                      {r.outcome ? <span><b>Runs today:</b> {s(r.outcome.effective_mode)}{r.outcome.last_success_at ? ` · last success ${et(r.outcome.last_success_at)}` : ''}{r.outcome.last_live_success_at ? ` · last live success ${et(r.outcome.last_live_success_at)}` : ''}{r.outcome.dead_letters_open ? ` · ${r.outcome.dead_letters_open} open dead letter(s)` : ''}{r.outcome.breaker_open ? ' · breaker open' : ''}</span> : null}
                      {hv.reason ? <span><b>Health:</b> {hv.reason}</span> : null}
                      {rd ? <>
                        <span><b>Promotion{rd.target ? ` to ${rd.target}` : ''}:</b> {rv.label}{rd.risk_tier_name ? ` · risk tier ${rd.risk_tier} (${rd.risk_tier_name})` : ''}{rd.p1_last ? ' · P1 lane (moves last)' : ''}</span>
                        {(rd.blocked_by || []).map((x, i) => <span key={`b${i}`} style={{ color: TOKENS.danger }}>Blocked: {x}</span>)}
                        {(rd.missing || []).map((x, i) => <span key={`m${i}`} style={{ color: TOKENS.warning }}>Missing: {x}</span>)}
                        {(rd.evidence || []).map((x, i) => <span key={`e${i}`}>Evidence: {x}</span>)}
                        {(rd.owed || []).map((x, i) => <span key={`o${i}`} style={{ color: TOKENS.text[2] }}>Owed in the PR: {x}</span>)}
                      </> : null}
                    </div>
                  </td>
                </tr> : null,
              ]
            })}
            {!shown.length ? <tr><td colSpan={N8N_COLS} style={{ ...cell, color: TOKENS.text[2] }}>No lanes match.</td></tr> : null}
          </tbody>
        </table>
      </div>
      <p style={muted}>Live list <span style={mono}>{s(n?.live_list_path)}</span> · {(n?.live_lanes || []).length} lane(s). Changing it restarts the relay and gateway.</p>
    </SectionGate>
  </Panel>
}

function SettingEditor({ row, d, run, onDone }: { row: SettingRow; d: OpsControlsState | null; run: Run; onDone: () => void }) {
  const init = row.current ?? row.default
  const [raw, setRaw] = useState(init === null || init === undefined ? '' : String(init))
  const v = validateSetting(row, raw)
  const block = actBlockReason(d, 'setting.set')
  return <div style={{ ...panel, background: TOKENS.bg[2], display: 'grid', gap: 8 }}>
    <div style={{ fontSize: TYPE.base, color: TOKENS.text[0], fontWeight: 600 }}>Edit {row.label || row.key} <span style={{ ...mono, color: TOKENS.text[2] }}>{row.key}</span></div>
    <p style={muted}>Type {row.type}{row.min !== null && row.min !== undefined ? ` · min ${row.min}` : ''}{row.max !== null && row.max !== undefined ? ` · max ${row.max}` : ''} · default {s(row.default)} · current {s(row.current)}{row.wired === false ? ' · not wired: no consumer reads it yet' : ''}</p>
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'flex-end' }}>
      <label style={label}>New value
        {row.type === 'bool' ? <select value={raw} onChange={e => setRaw(e.target.value)} style={input}><option value="">—</option><option value="true">true</option><option value="false">false</option></select>
          : row.type === 'enum' ? <select value={raw} onChange={e => setRaw(e.target.value)} style={input}><option value="">—</option>{(row.choices || []).map(c => <option key={c} value={c}>{c}</option>)}</select>
            : <input value={raw} onChange={e => setRaw(e.target.value)} inputMode={row.type === 'int' || row.type === 'float' ? 'decimal' : undefined} style={input} />}
      </label>
      <button type="button" disabled={!v.ok || !!block} title={block || undefined}
        onClick={() => { if (v.ok) { run('setting.set', { key: row.key, value: v.value }, `Set ${row.label || row.key}`); onDone() } }}
        style={btnStyle('danger', !v.ok || !!block)}>Preview change (passkey)</button>
      <button type="button" onClick={onDone} style={btnStyle('plain')}>Cancel</button>
    </div>
    {!v.ok && raw ? <span style={{ fontSize: TYPE.sm, color: TOKENS.warning }}>{v.error}</span> : null}
  </div>
}

function FlagsTab({ d, run }: { d: OpsControlsState | null; run: Run }) {
  const st = d?.settings
  const [editing, setEditing] = useState<string | null>(null)
  const row = (st?.rows || []).find(r => r.key === editing)
  return <Panel title="Flags & thresholds">
    <SectionGate sec={st}>
      {row ? <SettingEditor key={row.key} row={row} d={d} run={run} onDone={() => setEditing(null)} /> : null}
      <Table label="Flags and thresholds" heads={['Setting', 'Type', 'Default', 'Current', 'Range / choices', 'Consumer', 'Updated', 'Action']}
        rows={(st?.rows || []).map(r => [
          <span style={{ display: 'grid', gap: 2 }}><span style={{ color: TOKENS.text[0], fontWeight: 600 }}>{r.label || r.key}</span><span style={{ ...mono, color: TOKENS.text[2] }}>{r.key}</span></span>,
          r.type, <span style={mono}>{s(r.default)}</span>,
          <ChipRow><span style={mono}>{s(r.current)}</span>{r.overridden ? <Chip tone="info">override</Chip> : null}</ChipRow>,
          r.type === 'enum' ? (r.choices || []).join(', ') || '—' : `${s(r.min)} … ${s(r.max)}`,
          <ChipRow>{s(r.consumer)}{r.wired === false ? <Chip tone="warning">not wired</Chip> : null}</ChipRow>,
          r.updated_at ? `${et(r.updated_at)} · ${s(r.updated_by)}` : '—',
          <ChipRow>
            <button type="button" disabled={!canAct(d, 'setting.set')} title={actBlockReason(d, 'setting.set') || undefined} onClick={() => setEditing(r.key)} style={btnStyle('danger', !canAct(d, 'setting.set'))}>Edit</button>
            {r.overridden ? <ActionButton state={d} kind="setting.unset" text="Unset" params={{ key: r.key }} title={`Unset ${r.label || r.key} (back to default)`} run={run} /> : null}
          </ChipRow>,
        ])} />
      <h3 style={{ ...h2, fontSize: TYPE.sm, marginTop: 12 }}>History</h3>
      <Table label="Setting history" heads={['At', 'Setting', 'Old', 'New', 'Actor', 'Request']}
        rows={(st?.history || []).map(h => [et(h.at), <span style={mono}>{h.key}</span>, <span style={mono}>{s(h.old_value)}</span>, <span style={mono}>{s(h.new_value)}</span>, s(h.actor), <span style={mono}>{s(h.request_id)}</span>])} />
    </SectionGate>
  </Panel>
}

// ── Data approvals (readiness, 2026-10-22) ──────────────────────────────────────────────────────────────────────────
// Operator: the tab listed 17 domains, all "proposed", with no other information — "This is not a dashboard."
// Each row is one data-dictionary domain (config/data_source_authority.json). The server
// (scripts/lib/data_domain_readiness.py) promotes each proposed row in memory with today's ceilings and runs the real
// gates on it; src/lib/opsControlsData.ts turns that into words. Read-only: nothing on this tab approves a row.
function Stat({ label: l, value, tone, tip, testId }: { label: string; value: ReactNode; tone: Tone; tip: string; testId: string }) {
  const t = toneVars(tone)
  return <Tooltip content={tip} as="div">
    <div data-testid={testId} style={{ background: t.bg, border: `1px solid ${t.border}`, borderRadius: RADIUS.md, padding: '8px 12px', minWidth: 120, cursor: 'help' }}>
      <div style={{ fontSize: TYPE.xs, color: TOKENS.text[2] }}>{l}</div>
      <div style={{ fontSize: TYPE.lg, fontWeight: 700, color: t.color, fontFamily: FONT.mono }}>{value}</div>
    </div>
  </Tooltip>
}

function FileListView({ fl, empty }: { fl?: FileList | null; empty: string }) {
  if (!fl || !fl.count) return <span style={{ color: TOKENS.text[2] }}>{empty}</span>
  return <span style={{ display: 'grid', gap: 2, minWidth: 0 }}>
    {fl.files.map(f => <span key={f} style={{ ...mono, overflowWrap: 'anywhere' }}>{f}</span>)}
    {fl.truncated ? <span style={{ color: TOKENS.text[2] }}>… and {fl.count - fl.files.length} more</span> : null}
  </span>
}

function DataDetail({ r }: { r: DataRow }) {
  const kv: CSSProperties = { display: 'grid', gridTemplateColumns: 'minmax(110px, 160px) minmax(0, 1fr)', gap: '4px 10px', fontSize: TYPE.sm, color: TOKENS.text[1], minWidth: 0 }
  const k: CSSProperties = { color: TOKENS.text[2] }
  const fv = freshnessView(r.freshness)
  const lane = r.refresh_lane
  return <div data-testid={`ops-data-detail-${r.domain}`} style={{ display: 'grid', gap: 10, padding: '8px 4px 12px', minWidth: 0 }}>
    {r.decision ? <p style={{ ...muted, color: TOKENS.text[1], margin: 0 }}><b>Decision asked:</b> {r.decision}</p> : null}
    {r.verdict && r.verdict !== 'APPROVED' ? <div style={{ minWidth: 0 }}>
      <div style={{ fontSize: TYPE.sm, fontWeight: 700, color: TOKENS.text[0], marginBottom: 4 }}>
        <HeadTip text="Readiness checks" tip={<span>Each check is a gate that already exists. The row is promoted in memory with the ceilings measured now — exactly what the approval PR records — and run through it. Nothing is written.</span>} />
      </div>
      <div style={{ display: 'grid', gap: 3 }}>
        {(r.criteria || []).map(c => <div key={c.id} style={{ fontSize: TYPE.sm, color: TOKENS.text[1], minWidth: 0, overflowWrap: 'anywhere' }}>
          <Tooltip content={`Source: ${c.source}`}><Chip tone={c.ok ? 'success' : 'warning'}>{c.ok ? 'pass' : 'missing'}</Chip></Tooltip> {c.label}
          {c.gaps.map((g, i) => <div key={i} style={{ marginLeft: 16, color: TOKENS.warning }}>– {g}</div>)}
        </div>)}
      </div>
    </div> : null}
    <div style={kv}>
      <span style={k}>Store</span><span style={{ ...mono, overflowWrap: 'anywhere' }}>{s(r.store)}{r.store_detail ? <span style={{ ...muted, display: 'block', fontFamily: FONT.sans }}>{r.store_detail}</span> : null}</span>
      <span style={k}>Writer</span><span style={{ overflowWrap: 'anywhere' }}>{writerText(r)}{r.writer_note ? <span style={{ ...muted, display: 'block' }}>{r.writer_note}</span> : null}</span>
      <span style={k}>Writes today</span><FileListView fl={r.live?.writer_files} empty="none seen by the scan (it reads SQL verbs and file markers only)" />
      <span style={k}>Read path</span><span>{r.projection ? <span style={mono}>{r.projection}</span> : 'no projection'}{r.projection_status ? ` (${r.projection_status})` : ''}</span>
      <span style={k}>Pages that read it</span><span>{(r.readers_declared || []).join(', ') || '—'}</span>
      <span style={k}>Files reading the store</span><FileListView fl={r.live?.store_readers} empty="none found" />
      {r.reader_gate ? <><span style={k}>Reader gate</span><span>gated tables {s((r.reader_gate.tables || []).join(', '))} — a reader needs an approved batch</span></> : null}
      {(r.approved_reader_batches || []).length ? <><span style={k}>Approved reader batches</span><span style={{ display: 'grid', gap: 2 }}>
        {(r.approved_reader_batches || []).map(b => <span key={String(b.batch)}>#{b.batch} <span style={mono}>{s(b.reader)}</span> · {s((b.surfaces || []).join(', '))} · approved {s(b.approved_on)}{b.facts ? ` — ${b.facts}` : ''}</span>)}
      </span></> : null}
      <span style={k}>Freshness</span><span><Tooltip content={fv.tip}><Chip tone={fv.tone}>{fv.text}</Chip></Tooltip> {r.freshness_sla ? <span style={muted}>SLA: {r.freshness_sla}</span> : null}</span>
      <span style={k}>Refresh lane</span><span>{lane ? `${s(lane.runner)} · ${s(lane.lane)}${lane.note ? ` — ${lane.note}` : ''}` : '—'}</span>
      {(r.derived_copies || []).length ? <><span style={k}>Copies</span><span style={{ display: 'grid', gap: 2 }}>
        {(r.derived_copies || []).map(c => <span key={String(c.store)}><span style={mono}>{s(c.store)}</span> <Chip tone={c.role === 'retiring' ? 'warning' : 'neutral'}>{s(c.role)}</Chip> {s(c.how)}</span>)}
      </span></> : null}
      {(r.supersedes || []).length ? <><span style={k}>Supersedes</span><span style={mono}>{(r.supersedes || []).join(', ')}</span></> : null}
      <span style={k}>Approval</span><span>{r.approval ? `${s(r.approval.approved_by)} · ${s(r.approval.approved_on)} — ${s(r.approval.scope)}`
        : r.operator_note?.approval_given ? `Operator approved: ${s(r.operator_note.decision)}; pending: ${s(r.operator_note.pending)}`
        : 'none recorded (proposed)'}{r.extends_approved && r.base_domain_approval ? <span style={{ ...muted, display: 'block' }}>Already a granted §7A domain (approved {s(r.base_domain_approval.approved_on)}); this adds its dictionary block.</span> : null}</span>
    </div>
    {(r.live?.findings || []).length ? <div style={{ minWidth: 0 }}>
      <div style={{ fontSize: TYPE.sm, fontWeight: 700, color: TOKENS.text[0], marginBottom: 4 }}>Live checker findings ({r.live?.findings.length})</div>
      {(r.live?.findings || []).map((f, i) => <div key={i} style={{ fontSize: TYPE.sm, color: TOKENS.text[1], minWidth: 0, overflowWrap: 'anywhere', marginBottom: 2 }}>
        <Tooltip content={CHECK_TIP[f.check] || f.check}><Chip tone={r.verdict === 'APPROVED' || f.check === 'UNAPPROVED_READER' ? 'danger' : 'warning'}>{f.check}</Chip></Tooltip> {findingText(f)}
        {f.files?.files?.length ? <span style={{ ...mono, display: 'block', marginLeft: 16, color: TOKENS.text[2] }}>{f.files.files.slice(0, 6).join(' · ')}{f.files.count > 6 ? ` … +${f.files.count - 6}` : ''}</span> : null}
      </div>)}
    </div> : null}
    {(r.approval_effects || []).length ? <div style={{ minWidth: 0 }}>
      <div style={{ fontSize: TYPE.sm, fontWeight: 700, color: TOKENS.text[0], marginBottom: 4 }}>What approving changes</div>
      <ul style={{ margin: 0, paddingLeft: 18, fontSize: TYPE.sm, color: TOKENS.text[1] }}>{(r.approval_effects || []).map((e, i) => <li key={i}>{e}</li>)}</ul>
    </div> : null}
  </div>
}

function DataTab({ d }: { d: OpsControlsState | null }) {
  const da = d?.data_approvals
  const rows = sortRows(da?.rows as DataRow[] | undefined)
  const sum = summarize(rows)
  const [filter, setFilter] = useState<DataFilter>('all')
  const [open, setOpen] = useState<Set<string>>(() => new Set())
  const toggle = (id: string) => setOpen(prev => { const n = new Set(prev); if (n.has(id)) n.delete(id); else n.add(id); return n })
  const shown = rows.filter(r => matchesDataFilter(r, filter))
  const scan = scanText(da?.scan)
  const legacy = rows.length > 0 && rows.every(r => r.verdict === undefined && r.store === undefined)
  return <Panel title="Data approvals" right={<span style={{ ...muted, color: toneVars(scan.tone).color }} data-testid="ops-data-scan">{scan.text}</span>}>
    <SectionGate sec={da}>
      <p style={{ ...muted, color: TOKENS.text[1] }} data-testid="ops-data-explainer">{EXPLAINER} Hover or tap any underlined heading, number or badge for its meaning.</p>
      {legacy ? <p role="alert" style={{ ...muted, color: TOKENS.warning, fontWeight: 600 }}>This server sends only domain names and status; readiness needs the newer server.</p> : null}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, margin: '8px 0' }} role="group" aria-label="Data approvals summary">
        <Stat testId="ops-data-approved" label="Approved" value={sum.approved} tone="success" tip={SUMMARY_TIP.approved} />
        <Stat testId="ops-data-ready" label="Ready to approve" value={sum.ready} tone="info" tip={SUMMARY_TIP.ready} />
        <Stat testId="ops-data-not-ready" label="Not ready" value={sum.notReady} tone={sum.notReady ? 'warning' : 'neutral'} tip={SUMMARY_TIP.not_ready} />
        <Stat testId="ops-data-findings" label="Findings" value={sum.findings} tone={sum.findings ? 'warning' : 'neutral'} tip={SUMMARY_TIP.findings} />
      </div>
      {sum.pendingPr.length ? <p style={muted}>Operator-approved, waiting for its promotion PR: <span style={mono}>{sum.pendingPr.join(', ')}</span>. It binds only once that PR merges.</p> : null}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center', margin: '8px 0' }} role="group" aria-label="Filter domains">
        {DATA_FILTERS.map(([k, text]) => {
          const sel = filter === k
          const n = rows.filter(r => matchesDataFilter(r, k)).length
          return <button key={k} type="button" aria-pressed={sel} onClick={() => setFilter(k)}
            style={{ ...btnStyle(sel ? 'info' : 'plain'), padding: '4px 10px', minHeight: 28, fontSize: TYPE.sm }}>
            {text} <span style={{ fontFamily: FONT.mono, color: TOKENS.text[2] }}>{n}</span>
          </button>
        })}
      </div>
      <div style={{ overflowX: 'auto', minWidth: 0 }}>
        <table aria-label="Data approvals" style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead><tr>
            <th style={{ ...cell, color: TOKENS.text[3] }}>Domain</th>
            <th style={{ ...cell, color: TOKENS.text[3], whiteSpace: 'nowrap' }}><HeadTip text="Verdict" tip={<>
              <span><b>Approved</b> — {VERDICT_TIP.APPROVED}</span><span><b>Ready to approve</b> — {VERDICT_TIP.READY_TO_APPROVE}</span>
              <span><b>Not ready</b> — {VERDICT_TIP.NOT_READY}</span></>} /></th>
            <th style={{ ...cell, color: TOKENS.text[3] }}><HeadTip text="Store · writer" tip="The one authoritative store, and the one module allowed to write it. “Not consolidated” means several files write it today under a ceiling that may only fall, with the module that should become the single writer." /></th>
            <th style={{ ...cell, color: TOKENS.text[3] }}><HeadTip text="Freshness" tip="How recently the store changed: file modification time for a file store; for a table, the newest value of a time column only when the registry declares one in the data dictionary. Shown as evidence; it is not a readiness check." /></th>
            <th style={{ ...cell, color: TOKENS.text[3] }}><HeadTip text="Findings" tip={SUMMARY_TIP.findings} /></th>
            <th style={{ ...cell, color: TOKENS.text[3] }}></th>
          </tr></thead>
          <tbody>
            {shown.map(r => {
              const v = verdictView(r)
              const fv = freshnessView(r.freshness)
              const isOpen = open.has(r.domain)
              const nf = r.live?.findings?.length || 0
              return [<tr key={r.domain} style={{ borderTop: `1px solid ${TOKENS.borderSubtle}` }}>
                <td style={cell}><span style={{ display: 'grid', gap: 2 }}><span style={{ color: TOKENS.text[0], fontWeight: 600 }}>{s(r.title || r.domain)}</span><span style={{ ...mono, color: TOKENS.text[2] }}>{r.domain}</span></span></td>
                <td style={cell}><span style={{ display: 'grid', gap: 2 }}><Tooltip content={v.tip}><Chip tone={v.tone}>{v.label}</Chip></Tooltip>
                  {(r.missing || []).length ? <span style={{ color: TOKENS.warning, fontSize: TYPE.xs }}>{(r.missing || []).length} missing</span> : null}</span></td>
                <td style={{ ...cell, overflowWrap: 'anywhere' }}><span style={mono}>{s(r.store)}</span><span style={{ display: 'block', color: TOKENS.text[2] }}>{writerText(r)}</span></td>
                <td style={cell}><Tooltip content={fv.tip}><Chip tone={fv.tone}>{fv.text}</Chip></Tooltip></td>
                <td style={cell}>{r.live ? <Chip tone={nf ? (r.verdict === 'APPROVED' ? 'danger' : 'warning') : 'success'}>{nf ? `${nf} finding${nf === 1 ? '' : 's'}` : 'none'}</Chip> : '—'}</td>
                <td style={cell}><button type="button" aria-expanded={isOpen} onClick={() => toggle(r.domain)} style={{ ...btnStyle('plain'), padding: '4px 10px', minHeight: 28, fontSize: TYPE.sm }}>{isOpen ? 'Hide' : 'Details'}</button></td>
              </tr>, isOpen ? <tr key={`${r.domain}-d`}><td colSpan={6} style={{ ...cell, background: TOKENS.bg[2] }}><DataDetail r={r} /></td></tr> : null]
            })}
            {!shown.length ? <tr><td colSpan={6} style={{ ...cell, color: TOKENS.text[2] }}>No rows</td></tr> : null}
          </tbody>
        </table>
      </div>
      <p style={muted}>{s(da?.note || 'Read-only.')}</p>
    </SectionGate>
  </Panel>
}

function GrantsTab({ d, run }: { d: OpsControlsState | null; run: Run }) {
  const g = d?.grants
  const [tier, setTier] = useState('')
  const [dur, setDur] = useState('2h')
  const [uses, setUses] = useState('')
  const [reason, setReason] = useState('')
  const durOk = /^\d+[mhd]$/.test(dur.trim())
  const usesOk = uses.trim() === '' || /^[1-9]\d*$/.test(uses.trim())
  const block = actBlockReason(d, 'grant.issue')
  const ready = !!tier && durOk && usesOk && reason.trim().length >= 4 && !block
  const issue = () => {
    const params: Record<string, unknown> = { tier, for: dur.trim(), reason: reason.trim() }
    if (uses.trim()) params.uses = Number(uses.trim())
    run('grant.issue', params, `Issue ${tier} grant`)
  }
  return <Panel title="Grants">
    <SectionGate sec={g}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'flex-end', marginBottom: 10 }}>
        <label style={label}>Tier
          <select value={tier} onChange={e => setTier(e.target.value)} style={input}><option value="">choose…</option>{(g?.tiers || []).map(t => <option key={t} value={t}>{t}</option>)}</select>
        </label>
        <label style={label}>For (e.g. 2h, 30m)
          <input value={dur} onChange={e => setDur(e.target.value)} aria-invalid={!durOk} style={{ ...input, width: 90 }} />
        </label>
        <label style={label}>Uses (optional)
          <input value={uses} onChange={e => setUses(e.target.value)} inputMode="numeric" aria-invalid={!usesOk} style={{ ...input, width: 90 }} />
        </label>
        <label style={{ ...label, flex: '1 1 220px' }}>Reason
          <input value={reason} onChange={e => setReason(e.target.value)} maxLength={300} style={input} />
        </label>
        <button type="button" disabled={!ready} title={block || undefined} onClick={issue} style={btnStyle('danger', !ready)}>Preview grant (passkey)</button>
      </div>
      <Table label="Active grants" heads={['Tier', 'Uses', 'Minutes left', 'Grant', 'Reason', 'Action']}
        rows={(g?.active || []).map(a => [<span style={{ color: TOKENS.text[0], fontWeight: 600 }}>{a.tier}</span>, s(a.uses), s(a.minutes_left),
          <span style={mono}>{s(a.grant_id8 || a.grant_id)}</span>, s(a.reason),
          <ActionButton state={d} kind="grant.revoke" text="Revoke" params={a.grant_id ? { tier: a.tier, grant_id: a.grant_id } : { tier: a.tier, grant_id8: a.grant_id8 }} title={`Revoke ${a.tier} grant ${s(a.grant_id8 || a.grant_id)}`} run={run} />])} />
    </SectionGate>
  </Panel>
}

function AuditTab({ d, startFlow }: { d: OpsControlsState | null; startFlow: (f: FlowStart) => void }) {
  const a = d?.audit
  const reqs = d?.requests || []
  const byId = new Map(reqs.map(r => [r.request_id, r]))
  return <div style={{ display: 'grid', gap: 12, minWidth: 0 }}>
    <Panel title="Audit & undo">
      <SectionGate sec={a}>
        <Table label="Audit trail" heads={['Seq', 'At', 'Actor', 'Action', 'Kind', 'Outcome', 'Request', 'Undo']}
          rows={(a?.rows || []).map(r => {
            const undoKind = r.request_id ? byId.get(r.request_id)?.undo?.kind : null
            // Gate on the inverse kind when the request is in the recent list, else on the applied kind.
            const block = actBlockReason(d, undoKind || r.kind || '')
            return [<span style={mono}>{r.seq}</span>, et(r.at), s(r.actor), s(r.action), <span style={mono}>{s(r.kind)}</span>,
              <Chip tone={r.outcome === 'ok' ? 'success' : r.outcome ? 'warning' : 'neutral'}>{s(r.outcome)}</Chip>, <span style={mono}>{s(r.request_id)}</span>,
              r.undo_available && r.request_id ? <button type="button" disabled={!!block} title={block || undefined}
                onClick={() => startFlow({ title: `Undo ${s(r.kind)}`, start: () => opsApi.undo(r.request_id as string) })} style={btnStyle('info', !!block)}>Undo</button> : '—']
          })} />
      </SectionGate>
    </Panel>
    <Panel title="Recent requests">
      <Table label="Recent requests" heads={['Created', 'Kind', 'Direction', 'Status', 'Request', 'Result', '']}
        rows={reqs.map(r => [et(r.created_at), s(r.label || r.kind), <Chip tone={r.direction === 'safe' ? 'success' : 'danger'}>{r.direction}</Chip>,
          <Chip tone={STATUS_TONE[r.status] || 'neutral'}>{r.status}</Chip>, <span style={mono}>{r.request_id}</span>,
          r.result ? `${s(r.result.outcome)}${r.result.detail ? ` — ${r.result.detail}` : ''}` : '—',
          !isTerminal(r.status) ? <button type="button" onClick={() => startFlow({ title: s(r.label || r.kind), start: () => opsApi.getRequest(r.request_id) })} style={btnStyle('plain')}>Open</button> : null])} />
    </Panel>
  </div>
}

function PasskeysPanel({ d, run }: { d: OpsControlsState | null; run: Run }) {
  const [name, setName] = useState('')
  const keys = d?.passkeys
  const block = actBlockReason(d, 'passkey.register')
  const ok = name.trim().length >= 2 && !block
  const active = d?.factors?.passkeys_active
  return <Panel title="Passkeys" right={<span style={muted}>{typeof active === 'number' ? `${active} active` : 'active count UNAVAILABLE'} · TOTP {s(d?.factors?.totp)}</span>}>
    <p style={muted}>Passkeys confirm every risky change. Adding one needs an existing passkey{active === 0 ? ' (none is active, so the authenticator-app code is used once, for recovery)' : ''}; revoking one is itself a risky change.</p>
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'flex-end', marginBottom: 10 }}>
      <label style={{ ...label, flex: '1 1 200px', maxWidth: 320 }}>Name (e.g. Pixel 11)
        <input value={name} onChange={e => setName(e.target.value)} maxLength={64} style={input} />
      </label>
      <button type="button" disabled={!ok} title={block || undefined} onClick={() => run('passkey.register', { name: name.trim() }, `Add passkey “${name.trim()}”`)} style={btnStyle('danger', !ok)}>Add passkey</button>
    </div>
    {Array.isArray(keys) ? <Table label="Passkeys" heads={['Name', 'Credential', 'Created', 'Last used', 'State', 'Action']}
      rows={keys.map(k => [<span style={{ color: TOKENS.text[0], fontWeight: 600 }}>{k.name}</span>, <span style={mono}>{k.credential_id8}</span>, et(k.created_at), et(k.last_used_at),
        k.revoked_at ? <Chip tone="neutral">revoked {et(k.revoked_at)}</Chip> : <Chip tone="success">active</Chip>,
        k.revoked_at ? '—' : <ActionButton state={d} kind="passkey.revoke" text="Revoke" params={k.credential_id ? { credential_id8: k.credential_id8, credential_id: k.credential_id } : { credential_id8: k.credential_id8 }} title={`Revoke passkey “${k.name}”`} run={run} />])} />
      : <p role="alert" style={{ ...muted, color: TOKENS.warning, fontWeight: 600 }}>UNAVAILABLE — passkey list missing from state</p>}
  </Panel>
}

// ── page ─────────────────────────────────────────────────────────────────────────────────────────────
export default function OpsControlsPage() {
  const api = useApi<OpsControlsState>(opsApi.statePath, 15_000)
  const d = api.data
  const [tab, setTab] = useState<TabKey>('jobs')
  const [flow, setFlow] = useState<FlowStart | null>(null)

  const startFlow = (f: FlowStart) => setFlow(f)
  // The server decides the direction; a safe kind goes one-click (approved in the same call), a risky one is previewed.
  const run: Run = (kind, params, title) => {
    const safe = kindFor(d, kind)?.direction === 'safe'
    startFlow({ title, start: () => opsApi.createRequest(kind, params, safe) })
  }
  const close = () => { setFlow(null); api.refetch() }

  const inert = !!d && d.policy?.state !== 'ACTIVE'
  const TABS: Array<[TabKey, string, string]> = [
    ['jobs', 'Jobs & schedules', count(d?.jobs, d?.jobs?.rows?.length)],
    ['n8n', 'n8n lanes', count(d?.n8n, d?.n8n?.rows?.length)],
    ['flags', 'Flags & thresholds', count(d?.settings, d?.settings?.rows?.length)],
    ['data', 'Data approvals', count(d?.data_approvals, d?.data_approvals?.rows?.length)],
    ['grants', 'Grants', count(d?.grants, d?.grants?.active?.length)],
    ['audit', 'Audit & undo', count(d?.audit, d?.audit?.rows?.length)],
  ]
  const policyTone: Tone = d?.policy?.state === 'ACTIVE' ? 'success' : 'danger'

  return <section data-testid="ops-controls" style={{ display: 'grid', gap: 12, minWidth: 0, maxWidth: '100%' }}>
    <div style={panel}>
      <h1 style={{ margin: 0, fontSize: TYPE.lg, color: TOKENS.text[0] }}>Ops · Controls</h1>
      <p style={muted}>Change how the system runs without touching files. Every change: validate → preview (dry run) → confirm → applied with backup → audited.</p>
      <ChipRow>
        {api.error && !d ? <Chip tone="warning">UNAVAILABLE</Chip> : api.loading && !d ? <Chip tone="neutral">Loading</Chip>
          : <Chip tone={policyTone}>policy {s(d?.policy?.state)} · needs {s(d?.policy?.required || '19.0.0')}</Chip>}
        {d ? <Chip tone={d.store?.state === 'OK' ? 'success' : 'warning'}>store {s(d.store?.state)}</Chip> : null}
        {d ? <Chip tone={d.applier?.state === 'OK' ? 'success' : 'warning'}>applier {s(d.applier?.state)}{typeof d.applier?.age_s === 'number' ? ` · ${d.applier.age_s}s` : ''}</Chip> : null}
        {d ? <Chip tone="neutral">operator {s(d.operator)}</Chip> : null}
        {d ? <Chip tone="neutral">observed {et(d.as_of)}</Chip> : null}
      </ChipRow>
      <p style={muted}>Agents cannot use this page. Safe direction (STOP, pause, engage kill switch) is one click; the risky direction needs a passkey on this device and a typed phrase. Telegram is notified; it confirms nothing. The host terminal remains a fallback.</p>
    </div>

    {api.error && !d ? <Banner tone="warning" title="UNAVAILABLE — controls state could not be read">{api.error}. Nothing here is reported as healthy, and no action is offered.</Banner> : null}
    {api.error && d ? <Banner tone="warning" title="Showing the last good state">Refresh failed: {api.error}</Banner> : null}
    {inert ? <Banner tone="danger" title="INERT — every action is disabled">
      Controls are inert until AGENTS.md 19.0.0 is ACTIVE and the operator applies the migrations. Policy {s(d?.policy?.state)}{d?.policy?.detail ? ` — ${d.policy.detail}` : ''}.
    </Banner> : null}
    {d && d.store?.state !== 'OK' ? <Banner tone="warning" title={`Store ${s(d.store?.state)}`}>
      {d.store?.state === 'NOT_MIGRATED' ? `Missing tables: ${(d.store.missing_tables || []).join(', ') || '—'}. ` : ''}{s(d.store?.reason)}
    </Banner> : null}
    {d && d.applier?.state !== 'OK' ? <Banner tone="warning" title={`Applier ${s(d.applier?.state)}`}>
      Approved changes are applied by the host applier; {d.applier?.state === 'ABSENT' ? 'no heartbeat has been seen' : `last heartbeat ${et(d.applier?.heartbeat_at)}`}. {s(d.applier?.reason)}
    </Banner> : null}
    {d && d.factors?.webauthn_library === 'missing' ? <Banner tone="warning" title="WebAuthn library missing on the server">Passkey step-up and registration will be refused until it is installed.</Banner> : null}
    {d && d.factors?.hmac_key === 'missing' ? <Banner tone="warning" title="HMAC key missing">Approvals cannot be signed, so the applier would refuse them.</Banner> : null}

    <div role="tablist" aria-label="Controls sections" style={{ display: 'flex', gap: 6, overflowX: 'auto', minWidth: 0, paddingBottom: 2 }}>
      {TABS.map(([k, text, n]) => {
        const sel = tab === k
        return <button key={k} type="button" role="tab" aria-selected={sel} onClick={() => setTab(k)}
          style={{ ...btnStyle(sel ? 'info' : 'plain'), display: 'inline-flex', gap: 6, alignItems: 'center', ...(sel ? {} : { background: 'transparent' }) }}>
          {text}<span style={{ fontSize: TYPE.xs, color: TOKENS.text[2], fontFamily: FONT.mono }}>{n}</span>
        </button>
      })}
    </div>

    {tab === 'jobs' ? <JobsTab d={d} run={run} /> : null}
    {tab === 'n8n' ? <N8nTab d={d} run={run} /> : null}
    {tab === 'flags' ? <FlagsTab d={d} run={run} /> : null}
    {tab === 'data' ? <DataTab d={d} /> : null}
    {tab === 'grants' ? <GrantsTab d={d} run={run} /> : null}
    {tab === 'audit' ? <AuditTab d={d} startFlow={startFlow} /> : null}

    <PasskeysPanel d={d} run={run} />

    {flow ? <FlowModal flow={flow} state={d} onClose={close} /> : null}
  </section>
}
