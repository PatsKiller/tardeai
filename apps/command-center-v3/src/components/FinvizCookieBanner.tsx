/**
 * Site-wide top banner when Finviz Elite cookie / screener auth is degraded.
 * Links to System → Admin secrets (FINVIZ_COOKIE rotation).
 */
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

type Health = {
  ok?: boolean
  status?: string
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
    const id = window.setInterval(load, 60_000)
    return () => { cancelled = true; window.clearInterval(id) }
  }, [])

  const show = shouldShow(health) && !dismissed
  if (!show || !health) return null

  return (
    <div
      role="alert"
      style={{
        background: 'var(--red-dim)',
        color: 'var(--red)',
        borderBottom: '1px solid var(--red)',
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
        Admin secrets →
      </Link>
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
    </div>
  )
}
