// Same-origin read client. It carries the browser's existing session (Tailscale identity via the
// existing serve listener). It never holds, reads or sends a token, and it issues GET only: the
// Wealth app has no write path, approval path or order path of its own.
export interface Envelope<T> { ok: boolean; status: number; data: T | null; error: string | null; fetchedAt: string }

export async function getJson<T>(path: string, signal?: AbortSignal): Promise<Envelope<T>> {
  if (!path.startsWith('/api/')) throw new Error('wealth client reads canonical /api/ readers only')
  const fetchedAt = new Date().toISOString()
  try {
    const r = await fetch(path, { method: 'GET', credentials: 'same-origin', signal, headers: { Accept: 'application/json' } })
    const body = r.headers.get('content-type')?.includes('json') ? await r.json() : null
    return { ok: r.ok, status: r.status, data: r.ok ? (body as T) : null, error: r.ok ? null : `HTTP ${r.status}`, fetchedAt }
  } catch (e) {
    return { ok: false, status: 0, data: null, error: String(e), fetchedAt }
  }
}
