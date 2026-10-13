/**
 * Site-wide top banner when YouTube cookies are RED (logged-out / missing).
 * Deep-links to System → Pipeline YouTube cookie paste/upload.
 */
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

type Yt = {
  status?: string
  detail?: string
  auth_cookies?: number
}

export default function YoutubeCookieBanner() {
  const [yt, setYt] = useState<Yt | null>(null)
  const [dismissed, setDismissed] = useState(false)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const r = await fetch('/api/v2/system/pipeline-health', { cache: 'no-store' })
        if (!r.ok) return
        const j = await r.json()
        const d = j?.data ?? j
        const cookies = d?.ingestion?.youtube_cookies
        if (!cancelled && cookies) setYt(cookies)
      } catch {
        /* quiet */
      }
    }
    load()
    const id = window.setInterval(load, 120_000)
    return () => { cancelled = true; window.clearInterval(id) }
  }, [])

  if (dismissed || !yt || (yt.status || '').toLowerCase() !== 'red') return null

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
        YouTube cookies RED — transcript ingest blocked
        {typeof yt.auth_cookies === 'number' ? ` (${yt.auth_cookies} auth)` : ''}
        {yt.detail ? ` · ${yt.detail}` : ''}
      </span>
      <Link
        to="/system?tab=Pipeline&focus=youtube-cookies"
        style={{
          color: 'var(--text0)',
          fontWeight: 800,
          textDecoration: 'underline',
          whiteSpace: 'nowrap',
        }}
      >
        Fix in System → Pipeline
      </Link>
      <button
        type="button"
        onClick={() => setDismissed(true)}
        style={{
          background: 'transparent',
          border: '1px solid var(--red)',
          color: 'var(--red)',
          fontSize: 10,
          fontWeight: 700,
          padding: '2px 8px',
          borderRadius: 'var(--radius-sm)',
          cursor: 'pointer',
        }}
      >
        Dismiss
      </button>
    </div>
  )
}
