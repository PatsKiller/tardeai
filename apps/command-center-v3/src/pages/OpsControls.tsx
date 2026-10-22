// Ops → Controls (feat/ops-controls-20261022): change how the system runs without touching files.
// Builds against docs/ops/OPS_CONTROLS_API.md (GET/POST /api/v2/ops/controls/*). Operator-only: the server refuses
// agent callers on every route. The server decides each change kind's direction:
//   safe  (release-train STOP/pause, kill-switch engage) — one click: POST /requests {one_click:true}, poll to terminal;
//   risky (everything else) — 3 steps: (1) preview (dry run) → (2) passkey (WebAuthn) + typed phrase → (3) approve, poll.
// Telegram is notification only; nothing here waits on it. While AGENTS.md 19.0.0 is not ACTIVE every action is
// disabled (the server also answers 409 POLICY_NOT_ACTIVE); data still renders. Missing data is UNAVAILABLE, never 0.
import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { useApi } from '../hooks/useApi'
import { Chip, ChipRow } from '../components/primitives'
import { TOKENS, TYPE } from '../lib/watchTokens'
import { FONT, RADIUS, SHADOW, toneVars, type Tone } from '../lib/designTokens'
import {
  actBlockReason, canAct, isTerminal, kindFor, opsApi, passkeyStepUp, phraseMatches, registerPasskey, validateSetting,
  type OpsControlsState, type OpsRequest, type SettingRow,
} from '../lib/opsControls'

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

function Table({ label: aria, heads, rows }: { label: string; heads: string[]; rows: Array<Array<ReactNode>> }) {
  return <div style={{ overflowX: 'auto', minWidth: 0 }}>
    <table aria-label={aria} style={{ width: '100%', borderCollapse: 'collapse' }}>
      <thead><tr>{heads.map(h => <th key={h} style={{ ...cell, color: TOKENS.text[3], whiteSpace: 'nowrap' }}>{h}</th>)}</tr></thead>
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
    <Panel title="Jobs & schedules" right={jobs?.state === 'OK' ? <span style={muted}>as of {et(jobs.as_of)}</span> : null}>
      <SectionGate sec={jobs}>
        <Table label="Jobs and schedules" heads={['Job', 'Runs on', 'State', "What's missing while off · note", 'Schedule', 'Action']}
          rows={(jobs?.rows || []).map(j => [
            <span style={{ display: 'grid', gap: 2 }}><span style={{ color: TOKENS.text[0], fontWeight: 600 }}>{j.lane_id}</span>
              {j.broker_class ? <Chip tone="warning" title={(j.broker_tokens || []).join(', ')}>broker job</Chip> : null}</span>,
            s(j.scheduler_kind),
            <ChipRow><Chip tone={j.cron_state === 'ACTIVE' ? 'success' : j.cron_state === 'PAUSED' ? 'warning' : 'danger'}>{j.cron_state}</Chip>
              {j.registry_state ? <Chip tone="neutral">registry {j.registry_state}</Chip> : null}</ChipRow>,
            <span style={{ display: 'grid', gap: 2 }}>
              {j.paused_on || j.paused_note ? <span>paused {s(j.paused_on)}{j.paused_note ? ` · ${j.paused_note}` : ''}</span> : null}
              {j.note ? <span>{j.note}</span> : null}
              {j.display ? <span style={{ ...mono, color: TOKENS.text[2], whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>{j.display}</span> : null}
            </span>,
            <span style={mono}>{s(j.schedule)}</span>,
            j.cron_state === 'ACTIVE' && j.line_sha256 ? <ActionButton state={d} kind="crontab.pause" text="Pause" params={{ line_sha256: j.line_sha256, lane_id: j.lane_id }} title={`Pause ${j.lane_id}`} run={run} />
              : j.cron_state === 'PAUSED' && j.line_sha256 ? <ActionButton state={d} kind="crontab.resume" text="Resume" params={{ line_sha256: j.line_sha256, lane_id: j.lane_id }} title={`Resume ${j.lane_id}`} run={run} />
                : <span style={{ color: TOKENS.text[2] }}>{j.cron_state === 'AMBIGUOUS' ? 'more than one line — host terminal' : j.cron_state === 'ABSENT' ? 'no cron line' : 'no line hash'}</span>,
          ])} />
        {(jobs?.unmatched_active_lines ?? 0) > 0 ? <p style={muted}>{jobs?.unmatched_active_lines} active crontab line(s) match no registry lane; they are not controllable here.</p> : null}
      </SectionGate>
    </Panel>
  </div>
}

function N8nTab({ d, run }: { d: OpsControlsState | null; run: Run }) {
  const n = d?.n8n
  return <Panel title="n8n lanes">
    <SectionGate sec={n}>
      <p style={muted}>Live list <span style={mono}>{s(n?.live_list_path)}</span>: {(n?.live_lanes || []).length ? (n?.live_lanes || []).join(', ') : 'empty'}. Changing it restarts the relay and gateway.</p>
      <Table label="n8n lanes" heads={['Lane', 'Stage', 'Mode', 'On live list', 'Workflow', 'Action']}
        rows={(n?.rows || []).map(r => [<span style={{ color: TOKENS.text[0], fontWeight: 600 }}>{r.lane_id}</span>, s(r.stage), s(r.mode),
          <Chip tone={r.on_live_list ? 'info' : 'neutral'}>{r.on_live_list ? 'yes' : 'no'}</Chip>, <span style={mono}>{s(r.workflow)}</span>,
          r.on_live_list ? <ActionButton state={d} kind="n8n_live_list.remove" text="Remove" params={{ lane_id: r.lane_id }} title={`Remove ${r.lane_id} from the n8n live list`} run={run} />
            : <ActionButton state={d} kind="n8n_live_list.add" text="Add to live list" params={{ lane_id: r.lane_id }} title={`Add ${r.lane_id} to the n8n live list`} run={run} />])} />
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

function DataTab({ d }: { d: OpsControlsState | null }) {
  const da = d?.data_approvals
  return <Panel title="Data dictionary approvals">
    <SectionGate sec={da}>
      <p style={muted}>{s(da?.note || 'Read-only.')}</p>
      <Table label="Data approvals" heads={['Domain', 'Title', 'Status']}
        rows={(da?.rows || []).map(r => [<span style={mono}>{r.domain}</span>, s(r.title), <Chip tone={r.status === 'approved' ? 'success' : 'neutral'}>{s(r.status)}</Chip>])} />
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
