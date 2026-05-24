import { useEffect, useState, useRef, useCallback } from 'react'
import { useToast } from './ToastProvider'

interface ScalpSignal {
  symbol: string
  grade: string
  score: number
  decision: string
  change_percent: string
  rvol: number
  critic_verdict: string
  catalyst_verified: boolean
  source: string
  mention_count?: number
  verdict_changed?: boolean
}

const DECISION_COLOR: Record<string, string> = {
  GO: 'var(--green)',
  WAIT: 'var(--amber)',
  AVOID: 'var(--text3)',
  'NO GO': 'var(--red)',
}

const DECISION_BG: Record<string, string> = {
  GO: 'var(--green-dim)',
  WAIT: 'var(--amber-dim)',
  AVOID: 'rgba(88,101,120,.08)',
  'NO GO': 'var(--red-dim)',
}

const CRITIC_COLOR: Record<string, string> = {
  CONFIRM: 'var(--green)',
  DOWNGRADE: 'var(--amber)',
  BLOCK: 'var(--red)',
}

function Badge({ label, color, bg }: { label: string; color: string; bg?: string }) {
  return (
    <span style={{
      fontSize: 10, fontFamily: 'var(--mono)', padding: '2px 6px',
      borderRadius: 3, border: `1px solid ${color}`, color,
      background: bg || 'transparent', whiteSpace: 'nowrap',
    }}>
      {label}
    </span>
  )
}

const POLL_INTERVAL = 5000
const WS_PORT = 7778

export default function ScalpLiveFeed() {
  const [signals, setSignals] = useState<ScalpSignal[]>([])
  const [mode, setMode] = useState<'polling' | 'ws'>('polling')
  const [connected, setConnected] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const seenRef = useRef<Set<string>>(new Set())
  const { showToast } = useToast()

  // Dedup key: symbol + decision + source (avoid showing same signal twice)
  const signalKey = useCallback((s: ScalpSignal) => `${s.symbol}_${s.decision}_${s.source}`, [])

  // HTTP polling through port 7777 (always works)
  useEffect(() => {
    if (mode !== 'polling') return
    let unmounted = false

    async function poll() {
      try {
        const res = await fetch('/api/v2/scalp/live')
        const data = await res.json()
        if (!unmounted && data.signals?.length) {
          const newSignals: ScalpSignal[] = data.signals.map((s: any) => s.data)
          // Check for new GO signals to toast
          for (const s of newSignals) {
            const key = signalKey(s)
            if (s.decision === 'GO' && !seenRef.current.has(key)) {
              showToast(`LIVE: ${s.symbol} ${s.decision} (${s.score})`, 'success', 3000)
            }
            seenRef.current.add(key)
          }
          setSignals(newSignals.slice(0, 30))
          setConnected(true)
        } else if (!unmounted) {
          setConnected(true)
        }
      } catch {
        if (!unmounted) setConnected(false)
      }
    }

    poll()
    const interval = setInterval(poll, POLL_INTERVAL)
    return () => { unmounted = true; clearInterval(interval) }
  }, [mode, showToast, signalKey])

  // Try WS upgrade in background — if it connects, switch to WS mode
  useEffect(() => {
    let unmounted = false
    let ws: WebSocket | null = null

    async function tryWs() {
      if (unmounted) return
      try {
        // Probe WS availability via API before attempting connection (avoids browser console error)
        const probe = await fetch(`/api/v2/scalp/live`).catch(() => null)
        if (!probe || !probe.ok) return // WS server likely down, stay on polling
        const wsHost = window.location.hostname
        ws = new WebSocket(`ws://${wsHost}:${WS_PORT}`)
        wsRef.current = ws

        ws.onopen = () => {
          if (!unmounted) {
            setMode('ws')
            setConnected(true)
          }
        }

        ws.onmessage = (event) => {
          try {
            const msg = JSON.parse(event.data)
            if (msg.type === 'scalping_update' && msg.data) {
              const s = msg.data as ScalpSignal
              setSignals(prev => [s, ...prev].slice(0, 30))
              if (s.decision === 'GO') {
                showToast(`LIVE: ${s.symbol} ${s.decision} (${s.score})`, 'success', 3000)
              }
            }
          } catch { /* ignore */ }
        }

        ws.onerror = () => { /* WS not available, keep polling */ }
        ws.onclose = () => {
          if (!unmounted) {
            setMode('polling')
            // Retry WS in 30s
            setTimeout(tryWs, 30000)
          }
        }
      } catch { /* WS not available */ }
    }

    // Try WS after a short delay (let polling start first)
    const timeout = setTimeout(tryWs, 2000)
    return () => {
      unmounted = true
      clearTimeout(timeout)
      ws?.close()
    }
  }, [showToast])

  // Keepalive ping when in WS mode
  useEffect(() => {
    if (mode !== 'ws') return
    const interval = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send('ping')
      }
    }, 25000)
    return () => clearInterval(interval)
  }, [mode])

  return (
    <div style={{
      background: 'var(--bg-card)', border: '1px solid var(--border)',
      borderRadius: 'var(--radius)', padding: 12, minWidth: 280,
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        marginBottom: 10, fontSize: 11, fontWeight: 700,
        color: 'var(--text0)', textTransform: 'uppercase',
        letterSpacing: '0.5px',
      }}>
        <span style={{
          width: 7, height: 7, borderRadius: '50%',
          background: connected ? 'var(--green)' : 'var(--text3)',
          display: 'inline-block', flexShrink: 0,
        }} />
        LIVE SCALP FEED
        <span style={{ color: 'var(--text3)', fontWeight: 400, marginLeft: 'auto', fontSize: 10 }}>
          {signals.length} signals {mode === 'ws' ? '(ws)' : ''}
        </span>
      </div>

      {signals.length === 0 && (
        <div style={{ color: 'var(--text3)', fontSize: 11, padding: '12px 0', textAlign: 'center' }}>
          {connected ? 'Waiting for signals...' : 'Connecting...'}
        </div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 400, overflowY: 'auto' }}>
        {signals.map((s, i) => (
          <div key={i} style={{
            display: 'flex', alignItems: 'center', gap: 8,
            padding: '6px 8px', borderRadius: 'var(--radius)',
            background: i === 0 ? 'rgba(74,144,244,.04)' : 'transparent',
            borderLeft: `3px solid ${DECISION_COLOR[s.decision] || 'var(--text3)'}`,
            transition: 'background var(--transition)',
          }}>
            <Badge
              label={s.decision}
              color={DECISION_COLOR[s.decision] || 'var(--text3)'}
              bg={DECISION_BG[s.decision]}
            />
            <span style={{ fontWeight: 700, fontSize: 12, color: 'var(--text0)', minWidth: 48 }}>
              {s.symbol}
            </span>
            <span style={{ color: 'var(--text2)', fontSize: 10 }}>
              {s.score}/55
            </span>
            {s.change_percent && (
              <span style={{
                fontSize: 10,
                color: String(s.change_percent).startsWith('-') ? 'var(--red)' : 'var(--green)',
              }}>
                {s.change_percent}
              </span>
            )}
            {s.rvol > 0 && (
              <span style={{ fontSize: 10, color: 'var(--text3)' }}>
                {s.rvol.toFixed(1)}x
              </span>
            )}
            {s.critic_verdict && (
              <Badge
                label={s.critic_verdict}
                color={CRITIC_COLOR[s.critic_verdict] || 'var(--purple)'}
              />
            )}
            <span style={{ fontSize: 9, color: 'var(--text3)', marginLeft: 'auto' }}>
              {s.source}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
