// Work pipeline Tier 1 actions (operator 2026-10-23, "both"): one governed endpoint,
// POST /api/v2/coordination/commands (scripts/lib/work_pipeline_commands.py). Same-origin fetch, JSON body (the
// server enforces CSRF and takes the actor from the tailnet identity, never from this body), one idempotency key
// per press. Copy-command is client-side only: no server write.

export const COMMANDS_PATH = '/api/v2/coordination/commands'

export type CommandName =
  | 'note' | 'set_priority' | 'hold' | 'unhold' | 'batch_add' | 'batch_remove' | 'task_add' | 'task_split' | 'release_stale_claim'

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
