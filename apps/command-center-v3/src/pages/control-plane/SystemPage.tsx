/** Control-plane system projection. GET /api/v3/control-plane/system. */

import { useEffect, useState } from 'react'

export default function ControlPlaneSystemPage() {
  const [body, setBody] = useState<Record<string, unknown> | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let cancelled = false
    fetch('/api/v3/control-plane/system', { method: 'GET', cache: 'no-store' })
      .then(r => r.json())
      .then(json => { if (!cancelled) setBody(json) })
      .catch(err => { if (!cancelled) setError(String(err)) })
    return () => { cancelled = true }
  }, [])
  const data = body && typeof body.data === 'object' && body.data ? body.data as Record<string, unknown> : {}
  const runtime = data.runtime && typeof data.runtime === 'object' ? data.runtime as Record<string, unknown> : {}
  return (
    <div data-page="control-plane-system" data-preview="true" style={{ display: 'grid', gap: 10, maxWidth: 900 }}>
      <div style={{ fontSize: 12, fontWeight: 800 }}>SYSTEM · PREVIEW</div>
      <div style={{ fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--text2)' }}>
        GET /api/v3/control-plane/system · authority {String(data.authority ?? 'absent')} ·
        MEMORY_BEHAVIOR_INFLUENCE={String(data.memory_behavior_influence ?? 'absent')} ·
        runtime.state={String(runtime.state ?? 'UNKNOWN')} · not a LIVE claim
      </div>
      {error ? <div style={{ color: 'var(--red)' }}>{error}</div> : null}
      <pre style={{ fontSize: 11, overflow: 'auto', background: 'var(--bg1)', padding: 12 }}>
        {JSON.stringify(body, null, 2)}
      </pre>
    </div>
  )
}
