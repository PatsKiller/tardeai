import { useState } from 'react'
import { lanesForPolicy, runBrokerCloudLane, runManualCloud, runStopAdvisory, runStopAdvisoryBatch, runWatchlistCioSynthesis, type LanePolicy, type LaneId } from '../lib/cloudLlmRun'
import { useOAuthLanes, laneReady } from '../hooks/useOAuthLanes'

const GROK = '#1d9bf0', GPT = '#10a37f', DEEPSEEK = '#a855f7', MUTED = '#94a3b8'

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
  const [busy, setBusy] = useState<LaneId | null>(null)
  const [msg, setMsg] = useState('')

  const lanes = lanesForPolicy(lanePolicy)
  const isBatch = batchLimit != null || processId === 'holding_protection_advisor_batch'
  const isWatchlistCio = processId === 'watchlist_cio_synthesis' && !!symbol
  const isStopAdvisory = processId === 'holding_protection_advisor' && !!symbol
  const needsPrompt = !proposalId && !prompt && !isBatch && !isWatchlistCio && !isStopAdvisory

  const run = async (lane: 'grok' | 'chatgpt' | 'deepseek-flash' | 'deepseek-v4') => {
    const isOAuth = lane === 'grok' || lane === 'chatgpt'
    const isDeepSeek = lane === 'deepseek-flash' || lane === 'deepseek-v4'
    
    // Check readiness: OAuth lanes check via oauth hook, DeepSeek via ready flag
    if (isOAuth) {
      if (!laneReady(lane === 'grok' ? oauth.grok : oauth.chatgpt)) {
        setMsg(`⛔ ${lane} OAuth not ready — Ops → Consumption`)
        return
      }
    } else if (isDeepSeek && !oauth.deepseekReady) {
      setMsg(`⛔ ${lane} API not ready — check deepseek_tradeai key`)
      return
    }
    setBusy(lane)
    setMsg('')
    try {
      let result: any
      if (isBatch && lane === 'grok') {
        result = await runStopAdvisoryBatch({ limit: batchLimit ?? 6, lane: 'grok' })
        if (result?.ok) setMsg(`✓ Grok batch · top ${result.limit ?? batchLimit ?? 6}`)
        else setMsg(`⛔ ${result?.error || 'batch failed'}`)
      } else if (isWatchlistCio) {
        result = await runWatchlistCioSynthesis(symbol!, lane)
        if (result?.ok) setMsg(`✓ ${lane} CIO · ${result.recommendation || 'done'}`)
        else setMsg(`⛔ ${result?.error || result?.hint || 'blocked (need agent reviews?)'}`)
      } else if (isStopAdvisory && lane === 'grok') {
        result = await runStopAdvisory(symbol!, 'grok')
        if (result?.ok && result?.protection) {
          const sp = result.protection.stop_price
          setMsg(`✓ Grok stop${sp != null ? ` $${Number(sp).toFixed(2)}` : ''}`)
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
          {busy === 'grok' ? '…' : isBatch ? `▶ Grok (top ${batchLimit ?? 6})` : '▶ Grok'}
        </button>
      )}
      {lanes.includes('chatgpt') && (
        <button type="button" disabled={!!busy} onClick={() => void run('chatgpt')}
          style={btnStyle(GPT, busy === 'chatgpt', compact)}>
          {busy === 'chatgpt' ? '…' : '▶ ChatGPT'}
        </button>
      )}
      {lanes.includes('deepseek-flash') && (
        <button type="button" disabled={!!busy} onClick={() => void run('deepseek-flash')}
          style={btnStyle(DEEPSEEK, busy === 'deepseek-flash', compact)}>
          {busy === 'deepseek-flash' ? '…' : '▶ DeepSeek Flash'}
        </button>
      )}
      {lanes.includes('deepseek-v4') && (
        <button type="button" disabled={!!busy} onClick={() => void run('deepseek-v4')}
          style={btnStyle(DEEPSEEK, busy === 'deepseek-v4', compact)}>
          {busy === 'deepseek-v4' ? '…' : '▶ DeepSeek Pro'}
        </button>
      )}
      {msg && <span style={{ fontSize: compact ? 9 : 10, color: msg.startsWith('✓') ? '#22c55e' : '#ef4444', maxWidth: 220 }}>{msg}</span>}
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