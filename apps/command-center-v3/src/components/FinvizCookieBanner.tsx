/**
 * Site-wide top banner when Finviz Elite cookie / screener auth is degraded.
 * Links to System → Admin secrets (FINVIZ_COOKIE rotation).
 *
 * LQ-20261107-1289 (2026-11-08): a dead cookie with a working Elite API token is AMBER, not hidden.
 * The server now sets show_banner for that case and names the cookie-only features it costs; the
 * operator saw "set · 34d ago" and nothing else for three days. Red (both cookie and token dead,
 * or a failed probe) cannot be dismissed — only the amber rotation reminder can.
 */
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

type Health = {
  ok?: boolean
  status?: string
  // 'ok' | 'amber' (cookie dead, token carrying the screeners) | 'red' (screeners empty)
  severity?: string
  // 'ok' | 'expired' | 'missing' | 'unknown'
  cookie_status?: string
  degraded_features?: string[]
  degraded_count?: number
  detail?: string
  last_error?: string | null
  as_of?: string
  show_banner?: boolean
  message?: string
  admin_secrets_path?: string
}

function shouldShow(h: Health | null): boolean {
  if (!h) return false
  if (h.show_banner) return true
  if (h.ok === false) return true
  const st = (h.status || '').toLowerCase()
  if (st === 'token_ok') return true // cookie dead even though the token works (LQ-1289)
  return st === 'expired' || st === 'missing' || st === 'error' || st === 'check_failed' || st === 'invalid'
}

export default function FinvizCookieBanner() {
  const [health, setHealth] = useState<Health | null>(null)
  const [dismissed, setDismissed] = useState(false)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const r = await fetch('/api/v2/data-sources/finviz/credential-health', { cache: 'no-store' })
        if (!r.ok) return
        const j = await r.json()
        const d = j?.data ?? j
        if (!cancelled) setHealth(d)
      } catch {
        /* quiet — do not stack on reconnect banner */
      }
    }
    load()
    // Background tabs do not poll (2026-10-22); the server also caches the verdict per 5 min.
    // The visible 60 s poll is what lets the server alert on a fresh verdict (LQ-1289) without a
    // second Finviz request from any other process.
    const id = window.setInterval(() => { if (document.visibilityState !== 'hidden') void load() }, 60_000)
    return () => { cancelled = true; window.clearInterval(id) }
  }, [])

  const severe = !!(health && (health.severity === 'red' || health.ok === false || health.cookie_status === 'missing'))
  const show = shouldShow(health) && (severe || !dismissed)
  if (!show || !health) return null

  const tone = severe
    ? { bg: 'var(--red-dim)', fg: 'var(--red)', border: 'var(--red)' }
    : { bg: 'var(--amber-dim)', fg: 'var(--amber)', border: 'var(--amber)' }
  const names = health.degraded_features ?? []

  return (
    <div
      role="alert"
      title={names.length ? `Degraded: ${names.join(', ')}` : undefined}
      style={{
        background: tone.bg,
        color: tone.fg,
        borderBottom: `1px solid ${tone.border}`,
        fontSize: 11.5,
        fontWeight: 650,
        textAlign: 'center',
        padding: '5px 10px',
        letterSpacing: 0.15,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 10,
        flexWrap: 'wrap',
      }}
    >
      <span>
        {health.message || 'Finviz Elite cookie expired — screener and social scalp empty'}
      </span>
      <Link
        to="/system?tab=Admin"
        style={{
          color: 'var(--text0)',
          fontWeight: 800,
          textDecoration: 'underline',
          whiteSpace: 'nowrap',
        }}
      >
        {severe ? 'Admin secrets →' : 'Renew cookie →'}
      </Link>
      {!severe && (
        <button
          type="button"
          onClick={() => setDismissed(true)}
          style={{
            background: 'transparent', border: 'none', color: 'inherit', opacity: 0.75,
            cursor: 'pointer', fontSize: 11, fontWeight: 600, textDecoration: 'underline', padding: 0,
          }}
        >
          dismiss
        </button>
      )}
    </div>
  )
}
