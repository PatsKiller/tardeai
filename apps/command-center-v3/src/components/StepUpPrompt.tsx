/**
 * StepUpPrompt — 6-digit authenticator code for a cc_auth step-up refusal (2026-10-16).
 *
 * Render it when stepUpChallenge(status, body) returns a challenge. On a verified code it calls
 * onUnlocked(), and the caller retries the refused action once. A wrong code is never retried
 * automatically: each one counts toward the server-side lockout.
 */
import { useEffect, useRef, useState } from 'react'
import { BB, TYPE } from '../lib/watchTokens'
import { codeComplete, sanitizeCode, submitStepUp, type StepUpChallenge } from '../lib/stepUp'

const ACTION_LABEL: Record<string, string> = {
  schwab_reauth: 'Schwab re-auth',
  credential_change: 'credential change',
  risk_control_change: 'risk-control change',
  stop_change: 'stop change',
}

type Props = {
  challenge: StepUpChallenge
  onUnlocked: () => void
  onCancel: () => void
}

export default function StepUpPrompt({ challenge, onUnlocked, onCancel }: Props) {
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => { inputRef.current?.focus() }, [])

  const verify = async () => {
    if (!codeComplete(code) || busy) return
    setBusy(true)
    setErr(null)
    const res = await submitStepUp(challenge, code)
    setBusy(false)
    if (res.ok) {
      setCode('')
      onUnlocked()
      return
    }
    setCode('')
    let msg = res.error || 'Code not accepted'
    if (res.attempts_left != null) msg += ` · ${res.attempts_left} tries left`
    if (res.locked_until) msg += ` · locked until ${new Date(res.locked_until * 1000).toLocaleTimeString()}`
    setErr(msg)
    inputRef.current?.focus()
  }

  const label = ACTION_LABEL[challenge.action] || challenge.action
  const ready = codeComplete(code) && !busy

  return (
    <div
      role="dialog"
      aria-label="Step-up authentication"
      style={{
        marginTop: 10, padding: 12, borderRadius: 'var(--radius-md)',
        background: BB.amberDim, border: `1px solid ${BB.amber}`,
      }}
    >
      <div style={{ fontSize: TYPE.base, fontWeight: 800, color: BB.amber }}>Step-up required</div>
      <div style={{ fontSize: TYPE.sm, color: BB.text1, marginTop: 4, lineHeight: 1.45 }}>
        Enter the 6-digit code from your authenticator to unlock {label} for a few minutes.
        Nothing has been sent anywhere yet.
      </div>
      <form
        onSubmit={e => { e.preventDefault(); void verify() }}
        style={{ display: 'flex', gap: 8, marginTop: 10, alignItems: 'center', flexWrap: 'wrap' }}
      >
        <input
          ref={inputRef}
          value={code}
          onChange={e => setCode(sanitizeCode(e.target.value))}
          inputMode="numeric"
          autoComplete="one-time-code"
          pattern="[0-9]{6}"
          maxLength={6}
          aria-label="Authenticator code"
          placeholder="000000"
          disabled={busy}
          style={{
            width: 120, fontSize: TYPE.md, letterSpacing: 4, padding: '6px 10px',
            borderRadius: 'var(--radius-sm)', border: `1px solid ${BB.border}`,
            background: BB.bgPanel, color: BB.text0, fontFamily: BB.mono,
          }}
        />
        <button
          type="submit"
          disabled={!ready}
          style={{
            fontSize: TYPE.base, fontWeight: 800, padding: '7px 14px', borderRadius: 'var(--radius-sm)',
            border: 'none', cursor: ready ? 'pointer' : 'not-allowed',
            background: ready ? BB.amber : BB.bgShift, color: ready ? BB.bg : BB.text3,
          }}
        >
          {busy ? 'Verifying…' : 'Verify & retry'}
        </button>
        <button
          type="button"
          onClick={onCancel}
          style={{
            fontSize: TYPE.sm, fontWeight: 700, padding: '6px 10px', borderRadius: 'var(--radius-sm)',
            border: `1px solid ${BB.border}`, background: 'transparent', color: BB.text2, cursor: 'pointer',
          }}
        >
          Cancel
        </button>
      </form>
      {err && <div style={{ marginTop: 8, fontSize: TYPE.sm, color: BB.red }}>{err}</div>}
    </div>
  )
}
