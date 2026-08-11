/**
 * Site-wide top banner when Schwab OAuth is degraded or in the day-6 renewal window.
 * Links to /v3/system/schwab-reauth for manual URL → paste-code flow.
 */
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

type Health = {
  needs_reauth?: boolean
  degraded?: boolean
  show_banner?: boolean
  proactive_due?: boolean
  due_now?: boolean
  days_to_reauth?: number | null
  days_to_true_expiry?: number | null
  true_expiry?: string | null
  message?: string
}

function shouldShow(h: Health | null): boolean {
  if (!h) return false
  if (h.show_banner) return true
  if (h.needs_reauth || h.degraded) return true
  if (h.proactive_due || h.due_now) return true
  if (h.days_to_reauth != null && Number(h.days_to_reauth) <= 1) return true
  if (h.days_to_true_expiry != null && Number(h.days_to_true_expiry) <= 1) return true
  return false
}

export default function SchwabReauthBanner() {
  const [health, setHealth] = useState<Health | null>(null)
  const [dismissedSoft, setDismissedSoft] = useState(false)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const r = await fetch('/api/v2/brokers/schwab/token-health?probe=0', { cache: 'no-store' })
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

  const hard = !!(health?.needs_reauth || health?.degraded)
  const show = shouldShow(health) && (hard || !dismissedSoft)
  if (!show || !health) return null

  const urgent = hard
  const days = health.days_to_true_expiry ?? health.days_to_reauth
  const daysBit = days != null ? ` · ${Number(days).toFixed(1)}d left` : ''

  return (
    <div
      role="alert"
      style={{
        background: urgent ? 'var(--red-dim)' : 'var(--amber-dim)',
        color: urgent ? 'var(--red)' : 'var(--amber)',
        borderBottom: `1px solid ${urgent ? 'var(--red)' : 'var(--amber)'}`,
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
        🔐 Schwab login {urgent ? 'must be renewed' : 'renewal window'}
        {daysBit}
        {' — '}
        {health.message || 'renew before stops/quotes/orders fail'}
      </span>
      <Link
        to="/system/schwab-reauth"
        style={{
          color: 'var(--text0)',
          fontWeight: 800,
          textDecoration: 'underline',
          whiteSpace: 'nowrap',
        }}
      >
        Renew now →
      </Link>
      {!hard && (
        <button
          type="button"
          onClick={() => setDismissedSoft(true)}
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
