import { useState, useRef, useEffect } from 'react'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import { useApi } from '../hooks/useApi'

interface Message {
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp?: string
}

interface HermesHealth {
  gateway_status: string
  memories: Array<{ name: string; size: number; modified: number }>
  session_count: number
  staging_counts: Record<string, number>
}

const SYSTEM_PROMPT = `You are Hermes, Trade AI's research desk, second brain, memory layer, and independent challenger.
You are advisory only — you do not execute trades, place orders, or mutate production data.
You research, analyze, challenge, and recommend. Trade AI and the operator make all execution decisions.
Be direct, evidence-backed, and concise. Mark uncertainty clearly.`

export default function HermesChat() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const chatRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const { data: health } = useApi<HermesHealth>('/api/v2/hermes/health', 30000)

  useEffect(() => {
    if (chatRef.current) chatRef.current.scrollTop = chatRef.current.scrollHeight
  }, [messages])

  const send = async () => {
    const text = input.trim()
    if (!text || loading) return

    const userMsg: Message = { role: 'user', content: text, timestamp: new Date().toISOString() }
    const newMessages = [...messages, userMsg]
    setMessages(newMessages)
    setInput('')
    setLoading(true)
    setError(null)

    try {
      const apiMessages = [
        { role: 'system', content: SYSTEM_PROMPT },
        ...newMessages.map(m => ({ role: m.role, content: m.content })),
      ]
      const resp = await fetch('/api/v2/hermes/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: apiMessages }),
      })
      const data = await resp.json()
      if (data.ok && data.data?.choices?.[0]?.message?.content) {
        const browsed = data.data.browsed
        const searchQuery = data.data.search_query
        let content = data.data.choices[0].message.content
        if (browsed && searchQuery) {
          content = `🔍 *Browsed: "${searchQuery}"*\n\n${content}`
        }
        const assistantMsg: Message = {
          role: 'assistant',
          content,
          timestamp: new Date().toISOString(),
        }
        setMessages(prev => [...prev, assistantMsg])
      } else {
        setError(data.error || 'No response from Hermes')
      }
    } catch (e: any) {
      setError(e.message || 'Failed to reach Hermes')
    } finally {
      setLoading(false)
      inputRef.current?.focus()
    }
  }

  const handleKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  const gwStatus = health?.gateway_status || 'unknown'
  const statusColor = gwStatus === 'ok' ? 'var(--green)' : gwStatus === 'offline' ? 'var(--red)' : 'var(--amber)'
  const totalStaged = health ? Object.values(health.staging_counts).reduce((a, b) => a + b, 0) : 0

  return (
    <>
      <PageHeader title="Hermes Chat" subtitle="Research desk, challenger, and advisory agent" actions={
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{ width: 8, height: 8, borderRadius: '50%', background: statusColor }} />
          <span style={{ fontSize: 11, color: 'var(--text2)' }}>Gateway: {gwStatus}</span>
          {messages.length > 0 && (
            <button onClick={() => setMessages([])} style={{ fontSize: 10, padding: '3px 8px', border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg2)', color: 'var(--text2)', cursor: 'pointer', marginLeft: 8 }}>Clear</button>
          )}
        </div>
      } />

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 260px', gap: 12, height: 'calc(100vh - 140px)' }}>
        {/* Chat area */}
        <div style={{ display: 'flex', flexDirection: 'column', minHeight: 0 }}>
          <Card style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
            {/* Messages */}
            <div ref={chatRef} style={{ flex: 1, overflowY: 'auto', padding: '8px 0', minHeight: 0 }}>
              {messages.length === 0 && (
                <div style={{ textAlign: 'center', padding: 40, color: 'var(--text3)' }}>
                  <div style={{ fontSize: 24, marginBottom: 8 }}>Hermes</div>
                  <div style={{ fontSize: 12, maxWidth: 400, margin: '0 auto', lineHeight: 1.6 }}>
                    Trade AI's research desk and independent challenger.<br />
                    Ask about tickers, proposals, trades, strategy, risk, or system health.
                  </div>
                  <div style={{ display: 'flex', gap: 6, justifyContent: 'center', marginTop: 16, flexWrap: 'wrap' }}>
                    {['Analyze AAPL thesis', 'Review open trades', 'Challenge last proposal', 'What did I miss this week?', 'Portfolio risk summary'].map(q => (
                      <button key={q} onClick={() => { setInput(q); inputRef.current?.focus() }}
                        style={{ fontSize: 10, padding: '4px 10px', border: '1px solid var(--border)', borderRadius: 12, background: 'var(--bg2)', color: 'var(--text2)', cursor: 'pointer' }}>{q}</button>
                    ))}
                  </div>
                </div>
              )}
              {messages.map((m, i) => (
                <div key={i} style={{ display: 'flex', justifyContent: m.role === 'user' ? 'flex-end' : 'flex-start', padding: '4px 0' }}>
                  <div style={{
                    maxWidth: '80%', padding: '8px 12px', borderRadius: 8,
                    background: m.role === 'user' ? 'rgba(74,144,244,0.15)' : 'var(--bg2)',
                    border: `1px solid ${m.role === 'user' ? 'rgba(74,144,244,0.3)' : 'var(--border)'}`,
                  }}>
                    <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 4 }}>
                      {m.role === 'user' ? 'You' : 'Hermes'} {m.timestamp ? `· ${new Date(m.timestamp).toLocaleTimeString()}` : ''}
                    </div>
                    <div style={{ fontSize: 12, color: 'var(--text0)', whiteSpace: 'pre-wrap', lineHeight: 1.5 }}>{m.content}</div>
                  </div>
                </div>
              ))}
              {loading && (
                <div style={{ padding: '8px 12px', color: 'var(--text3)', fontSize: 11 }}>
                  Hermes is researching... (may browse the web)
                </div>
              )}
              {error && (
                <div style={{ padding: '8px 12px', color: 'var(--red)', fontSize: 11, background: 'rgba(246,70,93,.08)', borderRadius: 6, margin: '4px 0' }}>
                  {error}
                </div>
              )}
            </div>

            {/* Input */}
            <div style={{ borderTop: '1px solid var(--border)', padding: '8px 0 0', display: 'flex', gap: 8 }}>
              <textarea
                ref={inputRef}
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={handleKey}
                placeholder={gwStatus === 'ok' ? 'Ask Hermes...' : 'Hermes gateway is ' + gwStatus}
                disabled={gwStatus !== 'ok'}
                rows={2}
                style={{
                  flex: 1, fontSize: 12, padding: '8px 12px', border: '1px solid var(--border)',
                  borderRadius: 6, background: 'var(--bg2)', color: 'var(--text0)', resize: 'none',
                  fontFamily: 'inherit', lineHeight: 1.4,
                }}
              />
              <button
                onClick={send}
                disabled={loading || !input.trim() || gwStatus !== 'ok'}
                style={{
                  fontSize: 12, padding: '8px 16px', border: 'none', borderRadius: 6,
                  background: loading || !input.trim() ? 'var(--bg2)' : 'var(--accent)',
                  color: loading || !input.trim() ? 'var(--text3)' : '#fff',
                  cursor: loading || !input.trim() ? 'default' : 'pointer', alignSelf: 'flex-end',
                }}
              >Send</button>
            </div>
          </Card>
        </div>

        {/* Sidebar */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <Card title="Hermes Status">
            <div style={{ fontSize: 11, display: 'grid', gap: 6 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text3)' }}>Gateway</span>
                <span style={{ color: statusColor }}>{gwStatus}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text3)' }}>Sessions</span>
                <span style={{ color: 'var(--text1)' }}>{health?.session_count ?? '—'}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text3)' }}>Memories</span>
                <span style={{ color: 'var(--text1)' }}>{health?.memories?.length ?? '—'}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text3)' }}>Staged rows</span>
                <span style={{ color: 'var(--text1)' }}>{totalStaged}</span>
              </div>
            </div>
          </Card>

          <Card title="Staging Tables">
            <div style={{ fontSize: 10, display: 'grid', gap: 4 }}>
              {health && Object.entries(health.staging_counts).map(([tbl, cnt]) => (
                <div key={tbl} style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: 'var(--text3)' }}>{tbl.replace('hermes_', '')}</span>
                  <span style={{ color: cnt > 0 ? 'var(--accent)' : 'var(--text3)' }}>{cnt}</span>
                </div>
              ))}
            </div>
          </Card>

          <Card title="Quick Actions">
            <div style={{ display: 'grid', gap: 4 }}>
              {[
                { label: 'System Status', prompt: 'Give me a quick system health summary' },
                { label: 'Ticker Dossier', prompt: 'Build a ticker dossier for ' },
                { label: 'Trade Reflection', prompt: 'Reflect on my recent closed trades' },
                { label: 'Incubator Review', prompt: 'Review the current incubator candidates' },
                { label: 'Risk Check', prompt: 'What are my top portfolio risks right now?' },
              ].map(a => (
                <button key={a.label} onClick={() => { setInput(a.prompt); inputRef.current?.focus() }}
                  style={{ fontSize: 10, padding: '4px 8px', border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg2)', color: 'var(--text2)', cursor: 'pointer', textAlign: 'left' }}>
                  {a.label}
                </button>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </>
  )
}
