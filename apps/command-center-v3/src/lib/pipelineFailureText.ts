/** Plain English for the System page's "Recent pipeline failures" panel (FQ-065).
 *
 * The audit found the panel's reading line made of script identifiers (`process_watchlist_agent_jobs`), the word
 * "zombie", the table/status vocabulary (`pipeline_runs · status failed/error/timeout/crashed`) and raw parser text
 * (`Expecting value: line 1 column 1 (char 0)`). The operator needs the task and the consequence; the identifier and
 * the raw error stay on the page, in a disclosure.
 *
 * Unknown task ids are humanised (`some_new_task` → "Some new task"), so a new producer is legible the day it ships
 * without anyone editing this file. `humanize` never returns an underscore.
 */

const TASK_NAMES: Record<string, string> = {
  process_watchlist_agent_jobs: 'Watchlist agent jobs',
  rag_indexer: 'Research indexer',
  trade_ai_orchestrator: 'Orchestrator',
  finviz_screener_runner: 'Screener capture',
  social_ingest: 'Social ingest',
  earnings_ingest: 'Earnings ingest',
  news_ingest: 'News ingest',
  hermes_research_agent: 'Hermes research',
  cio_decision_engine: 'CIO decision engine',
  indicator_cache_refresh: 'Indicator refresh',
}

/** What a raw failure string means for the operator, and the raw string itself for the disclosure. */
export function failureCause(lastError: string | null | undefined, zombieCleared: number | null): { summary: string; technical: string | null } {
  if (zombieCleared && !lastError) {
    return {
      summary: `${zombieCleared} run${zombieCleared === 1 ? '' : 's'} never finished and ${zombieCleared === 1 ? 'was' : 'were'} closed as failed.`,
      technical: `zombie_cleared=${zombieCleared} · settled by remediate_pipeline_failures`,
    }
  }
  const raw = String(lastError ?? '').trim()
  if (!raw) {
    return { summary: 'No cause was recorded for the last failure.', technical: null }
  }
  const shapes: [RegExp, string][] = [
    [/^Expecting value: line \d+ column \d+/i, 'The response was empty or not valid JSON, so nothing could be read.'],
    [/terminated by SIGTERM|killed by a supervisor/i, 'A supervisor stopped the run before it could finish.'],
    [/deadline|timed? ?out/i, 'The run ran out of time before finishing.'],
    [/connection|refused|unreachable|network/i, 'A data source could not be reached.'],
    [/permission denied|unauthori[sz]ed|forbidden/i, 'The run was not allowed to read what it needed.'],
    [/no such (table|file)|does not exist/i, 'Something the run reads is no longer there.'],
  ]
  const hit = shapes.find(([re]) => re.test(raw))
  return {
    summary: hit ? hit[1] : 'The run stopped with an error (details below).',
    technical: raw,
  }
}

export function taskName(raw: unknown): string {
  const id = String(raw ?? '').trim()
  if (!id) return 'Unnamed task'
  const mapped = TASK_NAMES[id]
  if (mapped) return mapped
  const text = id.replace(/[_-]+/g, ' ').trim()
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : 'Unnamed task'
}
