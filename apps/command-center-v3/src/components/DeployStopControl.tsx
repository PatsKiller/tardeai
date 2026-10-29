/** STOP DEPLOYS (2026-10-21; renamed from the retired release train's STOP RELEASES 2026-10-27) — the operator's
 * deploy kill button.
 *
 * POST /api/v2/ops/deploys/stop SETS the deploy STOP latch (set-only); the host deploy_on_main poller and emergency
 * promote refuse while it is set (AGENTS.md §25.10). The steps shown are requested (this browser sent it) →
 * acknowledged (the server wrote STOP.json and read it back) → settling (a deploy holds the release lock and finishes
 * its bounded verify / rollback) → stopped (an independent status read: latch SET, lock free). Resume is Ops →
 * Controls "Deploys: resume" (passkey) or the host CLI. This is NOT the trading kill switch and never touches it.
 */
import { useEffect, useState, type CSSProperties } from 'react'
import { useApi } from '../hooks/useApi'
import { Chip } from './primitives/Chip'
import { FONT, RADIUS, TOKENS, TYPE, toneVars } from '../lib/designTokens'
import {
  freshness, HOST_STOP_FALLBACK, newIdempotencyKey, NO_STOP_REQUEST, DEPLOYS_PATHS, stopModelFrom, stopReasonError,
  STOP_STALE_AFTER_S, type StopRequestState, type StopResultWire, type StopStatusWire,
} from '../lib/deploys'

function useNow(ms: number): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), ms)
    return () => clearInterval(id)
  }, [ms])
  return now
}

function randomId(): string {
  try {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  } catch { /* fall through */ }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`
}

function timeOf(iso: string | null): string {
  if (!iso) return '—'
  const t = Date.parse(iso)
  return Number.isFinite(t) ? new Date(t).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : iso
}

const code: CSSProperties = {
  fontFamily: FONT.mono, fontSize: TYPE.sm, background: TOKENS.bg[2], border: `1px solid ${TOKENS.borderSubtle}`,
  borderRadius: RADIUS.sm, padding: '4px 6px', display: 'block', overflowX: 'auto', whiteSpace: 'pre', color: TOKENS.text[1],
}

export default function DeployStopControl({ compact = false }: { compact?: boolean }) {
  const statusApi = useApi<StopStatusWire>(DEPLOYS_PATHS.stop, 15_000)
  const now = useNow(5_000)
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState('')
  const [key, setKey] = useState<string | null>(null)
  const [req, setReq] = useState<StopRequestState>(NO_STOP_REQUEST)
  const f = freshness(statusApi.data?.as_of, !!statusApi.data, { nowMs: now, loading: statusApi.loading, error: statusApi.error, staleAfterS: STOP_STALE_AFTER_S })
  const m = stopModelFrom(statusApi.data, req, f)
  const reasonErr = stopReasonError(reason)
  const danger = toneVars('danger')

  const begin = () => {
    setOpen(true)
    setKey(newIdempotencyKey(randomId))   // one key per press; a retry of this press reuses it
  }

  const send = async () => {
    if (reasonErr || !key || req.inFlight) return
    const requestedAt = new Date().toISOString()
    setReq({ requestedAt, inFlight: true, result: null, httpStatus: null, error: null })
    try {
      const r = await fetch(DEPLOYS_PATHS.stop, {
        method: 'POST', credentials: 'same-origin', cache: 'no-store',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: reason.trim(), idempotency_key: key }),
      })
      let body: StopResultWire | null = null
      try { body = await r.json() } catch { body = null }
      setReq({ requestedAt, inFlight: false, result: body, httpStatus: r.status, error: body ? null : `HTTP ${r.status}, unreadable body` })
      if (body?.ok) setOpen(false)
    } catch (e) {
      setReq({ requestedAt, inFlight: false, result: null, httpStatus: null, error: String(e) })
    }
    statusApi.refetch()  // the independent read that confirms "stopped"
  }

  const button: CSSProperties = {
    padding: compact ? '8px 14px' : '10px 18px', borderRadius: RADIUS.md, border: `2px solid ${danger.color}`,
    background: danger.bg, color: danger.color, fontSize: TYPE.md, fontWeight: 900, letterSpacing: 0.8, cursor: 'pointer',
  }

  return (
    <div data-testid="deploy-stop-control" style={{ display: 'grid', gap: 8 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <button type="button" data-testid="deploy-stop-button" onClick={begin} style={button} aria-haspopup="dialog">
          STOP DEPLOYS
        </button>
        <Chip tone={m.latchTone} size="md" title={f.reason ?? undefined}>{m.headline}</Chip>
        <span style={{ fontSize: TYPE.xs, color: f.state === 'OK' ? TOKENS.text[3] : TOKENS.warning }}>
          latch read {f.state === 'LOADING' ? '…' : f.state === 'UNAVAILABLE' ? `UNAVAILABLE${f.reason ? ` (${f.reason})` : ''}` : `${f.ageLabel}${f.state === 'STALE' ? ' · STALE' : ''}`}
        </span>
      </div>

      {m.latch === 'SET' && (
        <div data-testid="deploy-stop-latched" style={{ fontSize: TYPE.sm, color: TOKENS.text[1] }}>
          Latched {timeOf(m.latchedAt)}{m.latchedBy ? ` by ${m.latchedBy}` : ''}{m.latchOutcome ? ` · ${m.latchOutcome}` : ''}{m.latchReason ? ` — ${m.latchReason}` : ''}
        </div>
      )}
      {m.readerNote && <div style={{ fontSize: TYPE.sm, color: TOKENS.warning }}>{m.readerNote}</div>}

      {open && (
        <div role="dialog" aria-label="Confirm STOP DEPLOYS" data-testid="deploy-stop-confirm"
          style={{ border: `1px solid ${danger.border}`, background: TOKENS.bg[2], borderRadius: RADIUS.md, padding: 10, display: 'grid', gap: 6 }}>
          <div style={{ fontSize: TYPE.base, color: TOKENS.text[0], fontWeight: 700 }}>Stop host deploys?</div>
          <div style={{ fontSize: TYPE.sm, color: TOKENS.text[2] }}>
            Writes the deploy STOP latch. The host poller stops promoting new main commits; a deploy already
            mid-run finishes its bounded verify or rollback. Mergify may still merge. Trading is not affected.
          </div>
          <label style={{ fontSize: TYPE.sm, color: TOKENS.text[1] }}>
            Reason (required, recorded with your Tailscale identity)
            <textarea data-testid="deploy-stop-reason" value={reason} onChange={e => setReason(e.target.value)} rows={2} maxLength={500}
              style={{ display: 'block', width: '100%', marginTop: 4, fontSize: TYPE.base, fontFamily: FONT.sans, background: TOKENS.bg[1],
                color: TOKENS.text[0], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.sm, padding: 6, boxSizing: 'border-box' }} />
          </label>
          {reason && reasonErr && <div style={{ fontSize: TYPE.xs, color: TOKENS.warning }}>{reasonErr}</div>}
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button type="button" data-testid="deploy-stop-send" disabled={!!reasonErr || req.inFlight} onClick={send}
              style={{ ...button, opacity: reasonErr || req.inFlight ? 0.5 : 1, cursor: reasonErr || req.inFlight ? 'not-allowed' : 'pointer' }}>
              {req.inFlight ? 'Stopping…' : 'Stop deploys now'}
            </button>
            <button type="button" onClick={() => setOpen(false)}
              style={{ padding: '8px 14px', borderRadius: RADIUS.md, border: `1px solid ${TOKENS.border}`, background: TOKENS.bg[1], color: TOKENS.text[1], fontSize: TYPE.base, cursor: 'pointer' }}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {(req.requestedAt || m.latch === 'SET') && (
        <ol data-testid="deploy-stop-steps" style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: 3 }}>
          {m.steps.filter(s => s.key !== 'settling' || s.done).map((s, i) => (
            <li key={s.key} data-testid={`deploy-stop-step-${s.key}`} style={{ display: 'flex', gap: 8, alignItems: 'baseline', fontSize: TYPE.sm }}>
              <Chip tone={s.done ? (s.key === 'stopped' ? 'danger' : 'info') : 'neutral'}>{i + 1}. {s.label}</Chip>
              <span style={{ fontFamily: FONT.mono, color: s.done ? TOKENS.text[0] : TOKENS.text[3] }}>{s.done ? timeOf(s.at) : 'pending'}</span>
              {!compact && <span style={{ color: TOKENS.text[2] }}>{s.detail}</span>}
            </li>
          ))}
        </ol>
      )}

      {m.refused && <div role="alert" style={{ fontSize: TYPE.sm, color: TOKENS.danger }}>Refused — {m.refused}</div>}
      {m.unconfirmed && (
        <div role="alert" style={{ fontSize: TYPE.sm, color: TOKENS.warning }}>
          STOP NOT CONFIRMED. {m.unconfirmed} Host fallback:
          <code style={code}>{HOST_STOP_FALLBACK}</code>
        </div>
      )}

      <div style={{ fontSize: TYPE.xs, color: TOKENS.text[2], display: 'grid', gap: 4 }}>
        <span>
          Deploy STOP only — this is not the trading kill switch and does not touch it. Trading containment, stops and
          monitoring keep running.
        </span>
        <span>Resume: Ops → Controls “Deploys: resume” (passkey), or at the host:</span>
        <code style={code} data-testid="deploy-stop-resume-command">{m.resumeCommand}</code>
      </div>
    </div>
  )
}
