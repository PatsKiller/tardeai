import { useState } from 'react'
import { lanesForPolicy, runBrokerCloudLane, runManualCloud, runStopAdvisory, runStopAdvisoryBatch, runWatchlistCioSynthesis, type LanePolicy } from '../lib/cloudLlmRun'
import { useOAuthLanes, laneReady } from '../hooks/useOAuthLanes'
import { laneLabel } from '../lib/laneLabels'

const GROK = '#1d9bf0', GPT = '#10a37f', DEEPSEEK = '#6c5ce7', MUTED = '#94a3b8'

type Props = {
  processId: string
  lanePolicy?: LanePolicy | string
  /** When set, uses broker proposal cloud path (builds thesis server-side). */
  proposalId?: number
  /** Watchlist symbol — runs CIO synthesis for watchlist_cio_synthesis process. */
  symbol?: string
  prompt?: string
  taskSummary?: string
  compact?: boolean
  /** Stop advisory batch — top-N holdings via Grok (Manual mode safe). */
  batchLimit?: number
  onDone?: (result: any) => void
}

export default function CloudLlmRunButtons({
  processId, lanePolicy = 'either', proposalId, symbol, prompt, taskSummary, compact, batchLimit, onDone,
}: Props) {
  const oauth = useOAuthLanes(0)
  const [busy, setBusy] = useState<'grok' | 'chatgpt' | null>(null)
  const [msg, setMsg] = useState('')

  const lanes = lanesForPolicy(lanePolicy)
  const isBatch = batchLimit != null || processId === 'holding_protection_advisor_batch'
  const isWatchlistCio = processId === 'watchlist_cio_synthesis' && !!symbol
  const isStopAdvisory = processId === 'holding_protection_advisor' && !!symbol
  const needsPrompt = !proposalId && !prompt && !isBatch && !isWatchlistCio && !isStopAdvisory

  const run = async (lane: 'grok' | 'chatgpt') => {
    if (!laneReady(lane === 'grok' ? oauth.grok : oauth.chatgpt)) {
      setMsg(`⛔ ${lane} OAuth not ready — Ops → Consumption`)
      return
    }
    setBusy(lane)
    setMsg('')
    try {
      let result: any
      if (isBatch && lane === 'grok') {
        result = await runStopAdvisoryBatch({ limit: batchLimit ?? 6, lane: 'grok' })
        if (result?.ok) setMsg(`✓ ${laneLabel('grok')} batch · top ${result.limit ?? batchLimit ?? 6}`)
        else setMsg(`⛔ ${result?.error || 'batch failed'}`)
      } else if (isWatchlistCio) {
        result = await runWatchlistCioSynthesis(symbol!, lane)
        if (result?.ok) setMsg(`✓ ${lane} CIO · ${result.recommendation || 'done'}`)
        else setMsg(`⛔ ${result?.error || result?.hint || 'blocked (need agent reviews?)'}`)
      } else if (isStopAdvisory && lane === 'grok') {
        result = await runStopAdvisory(symbol!, 'grok')
        if (result?.ok && result?.protection) {
          const sp = result.protection.stop_price
          setMsg(`✓ ${laneLabel('grok')} stop${sp != null ? ` $${Number(sp).toFixed(2)}` : ''}`)
        } else setMsg(`⛔ ${result?.error || 'stop advisory failed'}`)
      } else if (proposalId) {
        result = await runBrokerCloudLane(proposalId, lane)
        if (result?.cloud?.ok || result?.ok) {
          setMsg(`✓ ${lane} oversight done`)
        } else {
          setMsg(`⛔ ${result?.error || result?.cloud?.error || 'failed'}`)
        }
      } else {
        if (!prompt?.trim()) {
          setMsg('⛔ No prompt — build context first')
          return
        }
        result = await runManualCloud({
          process_id: processId,
          lane,
          prompt: prompt!,
          task_summary: taskSummary || prompt!.slice(0, 120),
        })
        if (result?.ok) setMsg(`✓ ${lane} · ${(result.text || '').slice(0, 80)}…`)
        else setMsg(`⛔ ${result?.error || 'blocked (Manual mode?)'}`)
      }
      onDone?.(result)
    } catch (e: any) {
      setMsg(`⛔ ${String(e?.message || e).slice(0, 80)}`)
    } finally {
      setBusy(null)
    }
  }

  if (needsPrompt && !proposalId) return null

  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: compact ? 4 : 6, alignItems: 'center' }}>
      {lanes.includes('grok') && (
        <button type="button" disabled={!!busy} onClick={() => void run('grok')}
          style={btnStyle(GROK, busy === 'grok', compact)}>
          {busy === 'grok' ? '…' : isBatch ? `▶ ${laneLabel('grok')} (top ${batchLimit ?? 6})` : `▶ ${laneLabel('grok')}`}
        </button>
      )}
      {lanes.includes('chatgpt') && (
        <button type="button" disabled={!!busy} onClick={() => void run('chatgpt')}
          style={btnStyle(GPT, busy === 'chatgpt', compact)}>
          {busy === 'chatgpt' ? '…' : `▶ ${laneLabel('chatgpt')}`}
        </button>
      )}
      {msg && <span style={{ fontSize: compact ? 9 : 10, color: msg.startsWith('✓') ? '#22c55e' : '#ef4444', maxWidth: 220 }}>{msg}</span>}
      {/* DeepSeek lanes — visual options (not yet wired to API) */}
      <button type="button" disabled title="DeepSeek Flash (not yet wired)"
        style={btnStyle(DEEPSEEK, false, compact)}>
        ▶ {laneLabel('deepseek-flash')}
      </button>
      <button type="button" disabled title="DeepSeek v4 (not yet wired)"
        style={{ ...btnStyle('#a29bfe', false, compact), opacity: 0.5 }}>
        ▶ {laneLabel('deepseek-v4')}
      </button>
    </div>
  )
}

function btnStyle(color: string, active: boolean, compact?: boolean) {
  return {
    fontSize: compact ? 9 : 10,
    fontWeight: 800 as const,
    padding: compact ? '3px 8px' : '5px 10px',
    borderRadius: 6,
    border: `1px solid ${color}66`,
    background: `${color}14`,
    color,
    cursor: active ? 'wait' : 'pointer',
    whiteSpace: 'nowrap' as const,
  }
}