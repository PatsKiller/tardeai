// Work pipeline Tier 1 actions (operator 2026-10-23, "both"): one governed endpoint,
// POST /api/v2/coordination/commands (scripts/lib/work_pipeline_commands.py). Same-origin fetch, JSON body (the
// server enforces CSRF and takes the actor from the tailnet identity, never from this body), one idempotency key
// per press. Copy-command is client-side only: no server write.

export const COMMANDS_PATH = '/api/v2/coordination/commands'

export type CommandName =
  | 'note' | 'set_priority' | 'hold' | 'unhold' | 'batch_add' | 'batch_remove' | 'task_add' | 'task_split' | 'task_done' | 'release_stale_claim'

export type CommandResult = { ok: boolean; status: number | null; error?: string; detail?: string; result?: unknown; replayed?: boolean }

export function newCommandKey(): string {
  const c: { randomUUID?: () => string } | undefined = (globalThis as { crypto?: { randomUUID?: () => string } }).crypto
  if (c?.randomUUID) return `wp-${c.randomUUID()}`
  return `wp-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`
}

/** The JSON body the endpoint expects. The actor is never part of it. */
export function commandBody(command: CommandName, params: Record<string, unknown>, key: string) {
  return { command, params, idempotency_key: key }
}

export async function sendCommand(command: CommandName, params: Record<string, unknown>, key: string = newCommandKey()): Promise<CommandResult> {
  try {
    const r = await fetch(COMMANDS_PATH, {
      method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(commandBody(command, params, key)),
    })
    let body: { ok?: boolean; error?: string; detail?: string; result?: unknown; replayed?: boolean } | null = null
    try { body = await r.json() } catch { body = null }
    return { ok: !!body?.ok, status: r.status, error: body?.error, detail: body?.detail, result: body?.result, replayed: body?.replayed }
  } catch (e) {
    return { ok: false, status: null, error: 'NETWORK', detail: String(e) }
  }
}

/** Clipboard copy with a textarea fallback (http on the tailnet has no async clipboard). */
export async function copyText(text: string): Promise<boolean> {
  try {
    const nav = (globalThis as { navigator?: { clipboard?: { writeText(t: string): Promise<void> } } }).navigator
    if (nav?.clipboard?.writeText) { await nav.clipboard.writeText(text); return true }
  } catch { /* fall through */ }
  try {
    const d = (globalThis as { document?: Document }).document
    if (!d) return false
    const ta = d.createElement('textarea')
    ta.value = text; ta.setAttribute('readonly', ''); ta.style.position = 'fixed'; ta.style.opacity = '0'
    d.body.appendChild(ta); ta.select()
    const ok = d.execCommand('copy')
    d.body.removeChild(ta)
    return ok
  } catch { return false }
}

/** `title | area1,area2 | acceptance1; acceptance2` per line → split parts (same grammar as agent_claim.py). */
export function parseSplitParts(text: string): Array<{ title: string; areas: string[]; acceptance: string[] }> {
  return text.split('\n').map(l => l.trim()).filter(Boolean).map(line => {
    const [title, areas = '', acc = ''] = line.split('|').map(s => s.trim())
    return { title, areas: areas.split(',').map(s => s.trim()).filter(Boolean), acceptance: acc.split(';').map(s => s.trim()).filter(Boolean) }
  }).filter(p => p.title)
}

// "Export handoff" (operator 2026-10-23: the offline handoff is always produced from the board). GET only: the server
// regenerates the markdown from the board + docs/ops/OPERATING_PLAYBOOK.md (cached 30 s); the browser saves it.
export const HANDOFF_EXPORT_PATH = '/api/v2/coordination/handoff-export'
export type HandoffExport = { markdown: string; filename: string; bytes: number; work_packages: number; truncated?: boolean; as_of?: string }

export async function fetchHandoff(): Promise<HandoffExport> {
  const r = await fetch(HANDOFF_EXPORT_PATH, { method: 'GET', credentials: 'same-origin', cache: 'no-store' })
  const body = await r.json().catch(() => null) as { ok?: boolean; data?: HandoffExport; error?: string } | null
  if (!r.ok || !body?.ok || !body.data) throw new Error(body?.error || `HTTP ${r.status}`)
  return body.data
}

/** Fetch the export and hand the browser a .md file to save. Returns the export (for the status line). */
export async function downloadHandoff(): Promise<HandoffExport> {
  const d = await fetchHandoff()
  const doc = (globalThis as { document?: Document }).document
  const url = URL.createObjectURL(new Blob([d.markdown], { type: 'text/markdown;charset=utf-8' }))
  try {
    if (doc) {
      const a = doc.createElement('a')
      a.href = url; a.download = d.filename || 'HANDOFF_ORDERED_WORK.md'; a.style.display = 'none'
      doc.body.appendChild(a); a.click(); doc.body.removeChild(a)
    }
  } finally {
    setTimeout(() => URL.revokeObjectURL(url), 5000)
  }
  return d
}
