import React, { useState, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { timeAgo } from '../lib/format'

const F = { fontFamily: 'var(--sans)' as const }

interface AgentResult {
  symbol: string; recommendation: string; confidence: number
  summary: string; narrative: string; next_action: string; created_at: string
}
interface DistItem { recommendation: string; cnt: number }
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type AgentDetailData = { latest: any[]; distribution: any[]; top_symbols: any[] }

interface AgentConfig {
  id: string; name: string; role: string; color: string; icon: string; dbNames: string[]
}
interface AgentStats {
  total_analyses: number; avg_confidence: number; last_run: string
}
interface Props {
  agent: AgentConfig | null
  stats: AgentStats | null
  detail: AgentDetailData | null
  onClose: () => void
  onRunFresh: (question: string) => void
  onNavigate: (path: string) => void
}

const recColor: Record<string, string> = {
  BUY: '#0ecb81', HOLD: '#f0b90b', SELL: '#f6465d', TRIM: '#f6465d',
  ADD: '#0ecb81', NEUTRAL: '#8b95a5', AVOID: '#f6465d', RESEARCH_MORE: '#4a90f4',
}

export default function AgentModal({ agent, stats, detail, onClose, onRunFresh, onNavigate }: Props) {
  const [freshQuery, setFreshQuery] = useState('')
  const [runningFresh, setRunningFresh] = useState(false)
  const [freshResult, setFreshResult] = useState<string | null>(null)

  const handleRunFresh = useCallback(async () => {
    const q = freshQuery.trim()
    if (!q) return
    setRunningFresh(true)
    setFreshResult(null)
    try {
      const r = await fetch('/api/v2/ai-ask', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: q })
      })
      const d = await r.json()
      setFreshResult((d.data?.answer || d.answer || 'No response').slice(0, 2000))
    } catch { setFreshResult('Network error') }
    setRunningFresh(false)
  }, [freshQuery])

  const latest: AgentResult[] = (detail?.latest || []) as AgentResult[]
  const distribution: DistItem[] = (detail?.distribution || []) as DistItem[]
  const topSymbols: AgentResult[] = (detail?.top_symbols || []) as AgentResult[]
  const hasData = latest.length > 0

  // Build narrative from latest results
  const narrativeSummary = hasData
    ? `${agent?.name} has completed ${stats?.total_analyses ?? 0} analyses in the last 30 days with ${((stats?.avg_confidence ?? 0) * 100).toFixed(0)}% average confidence. Most recent focus: ${latest.slice(0, 3).map(r => r.symbol).join(', ')}.`
    : null

  // Build watch items from latest results
  const watchItems = latest.filter(r => r.next_action && r.next_action !== r.recommendation).slice(0, 4)

  return (
    <AnimatePresence>
      {agent && (
        <motion.div
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}
          onClick={onClose}
          style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999, backdropFilter: 'blur(4px)' }}
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 12 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 12 }}
            transition={{ duration: 0.2, ease: 'easeOut' }}
            onClick={e => e.stopPropagation()}
            style={{
              background: 'rgba(14,18,26,0.98)', border: '1px solid rgba(255,255,255,0.1)',
              borderRadius: 16, width: '92%', maxWidth: 720, maxHeight: '88vh',
              overflowY: 'auto', boxShadow: '0 24px 80px rgba(0,0,0,0.6)',
              borderTop: `3px solid ${agent.color}`,
            }}
          >
            {/* ── Header ── */}
            <div style={{ padding: '20px 24px 14px', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
                  <span style={{ fontSize: 28 }}>{agent.icon}</span>
                  <div>
                    <div style={{ ...F, fontSize: 18, fontWeight: 800, color: '#fff' }}>{agent.name}</div>
                    <div style={{ ...F, fontSize: 11, color: agent.color, fontWeight: 600 }}>{agent.role}</div>
                  </div>
                </div>
                <button onClick={onClose} style={{
                  ...F, fontSize: 14, width: 32, height: 32, border: '1px solid rgba(255,255,255,0.1)',
                  borderRadius: 8, background: 'transparent', color: 'var(--text3)', cursor: 'pointer',
                  display: 'grid', placeItems: 'center',
                }}>✕</button>
              </div>
              {stats && (
                <div style={{ display: 'flex', gap: 24, marginTop: 14 }}>
                  <StatBox label="Confidence" value={`${(stats.avg_confidence * 100).toFixed(0)}%`}
                    color={stats.avg_confidence >= 0.7 ? '#0ecb81' : '#f0b90b'} />
                  <StatBox label="Analyses (30d)" value={String(stats.total_analyses)} color="#fff" />
                  <StatBox label="Last Run" value={stats.last_run ? timeAgo(stats.last_run) : 'never'} color="var(--text2)" />
                </div>
              )}
            </div>

            {/* ── Body ── */}
            <div style={{ padding: '16px 24px 24px' }}>

              {!hasData ? (
                /* ── No data state ── */
                <div style={{ textAlign: 'center', padding: '30px 0' }}>
                  <div style={{ ...F, fontSize: 14, color: 'var(--text2)', marginBottom: 16 }}>
                    No recent analysis from {agent.name}.
                  </div>
                  <div style={{ ...F, fontSize: 11, color: 'var(--text3)', marginBottom: 16 }}>
                    Would you like to run a fresh analysis?
                  </div>
                  <div style={{ display: 'flex', gap: 8, justifyContent: 'center' }}>
                    <input value={freshQuery} onChange={e => setFreshQuery(e.target.value)}
                      onKeyDown={e => e.key === 'Enter' && handleRunFresh()}
                      placeholder={`Ask ${agent.name} anything...`}
                      style={{ ...F, fontSize: 12, padding: '8px 14px', width: 320, border: '1px solid rgba(255,255,255,0.1)', borderRadius: 8, background: 'rgba(255,255,255,0.05)', color: '#fff', outline: 'none' }} />
                    <button onClick={handleRunFresh} disabled={runningFresh || !freshQuery.trim()} style={{
                      ...F, fontSize: 11, fontWeight: 700, padding: '8px 18px', border: 'none', borderRadius: 8,
                      background: agent.color, color: '#000', cursor: 'pointer', opacity: freshQuery.trim() ? 1 : 0.4,
                    }}>{runningFresh ? 'Running...' : 'Run Analysis'}</button>
                  </div>
                </div>
              ) : (
                /* ── Rich narrative content ── */
                <>
                  {/* Narrative summary */}
                  {narrativeSummary && (
                    <div style={{ ...F, fontSize: 12, color: 'var(--text1)', lineHeight: 1.7, marginBottom: 16, padding: '12px 16px', background: 'rgba(255,255,255,0.03)', borderRadius: 10, borderLeft: `3px solid ${agent.color}` }}>
                      {narrativeSummary}
                    </div>
                  )}

                  {/* Latest discoveries */}
                  <SectionTitle text="Latest Discoveries" />
                  <div style={{ display: 'grid', gap: 8, marginBottom: 18 }}>
                    {latest.map((r, i) => (
                      <div key={i} onClick={() => { onClose(); onNavigate(`/research?symbol=${r.symbol}`) }} style={{
                        padding: '12px 14px', background: 'rgba(255,255,255,0.025)',
                        border: '1px solid rgba(255,255,255,0.05)', borderRadius: 10,
                        borderLeft: `3px solid ${recColor[r.recommendation] || '#555'}`,
                        cursor: 'pointer', transition: 'background 80ms',
                      }}
                        onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(255,255,255,0.06)' }}
                        onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(255,255,255,0.025)' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <span style={{ ...F, fontSize: 15, fontWeight: 800, color: '#fff' }}>{r.symbol}</span>
                            <RecBadge rec={r.recommendation} />
                            <span style={{ ...F, fontSize: 11, fontWeight: 700, color: r.confidence >= 0.8 ? '#0ecb81' : r.confidence >= 0.6 ? '#f0b90b' : '#f6465d' }}>
                              {(r.confidence * 100).toFixed(0)}%
                            </span>
                          </div>
                          <span style={{ ...F, fontSize: 9, color: 'var(--text3)' }}>{r.created_at ? timeAgo(r.created_at) : ''}</span>
                        </div>
                        <div style={{ ...F, fontSize: 11, color: 'var(--text2)', lineHeight: 1.6 }}>
                          {r.summary || r.narrative || '—'}
                        </div>
                        {r.next_action && r.next_action !== r.recommendation && (
                          <div style={{ ...F, fontSize: 10, color: '#4a90f4', marginTop: 6, fontWeight: 600 }}>
                            → {r.next_action}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>

                  {/* What to watch for */}
                  {watchItems.length > 0 && (
                    <>
                      <SectionTitle text="What to Watch For" />
                      <div style={{ display: 'grid', gap: 4, marginBottom: 18 }}>
                        {watchItems.map((w, i) => (
                          <div key={i} onClick={() => { onClose(); onNavigate(`/research?symbol=${w.symbol}`) }}
                            style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '6px 4px', borderBottom: '1px solid rgba(255,255,255,0.04)', cursor: 'pointer', borderRadius: 6, transition: 'background 80ms' }}
                            onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(255,255,255,0.04)' }}
                            onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = '' }}>
                            <span style={{ ...F, fontSize: 12, fontWeight: 800, color: '#fff', minWidth: 42 }}>{w.symbol}</span>
                            <span style={{ ...F, flex: 1, fontSize: 10, color: 'var(--text2)', lineHeight: 1.4 }}>{w.next_action}</span>
                            <span style={{ ...F, fontSize: 10, fontWeight: 700, color: w.confidence >= 0.8 ? '#0ecb81' : '#f0b90b', minWidth: 30, textAlign: 'right' }}>
                              {(w.confidence * 100).toFixed(0)}%
                            </span>
                            <span style={{ fontSize: 10, color: 'var(--accent)' }}>→</span>
                          </div>
                        ))}
                      </div>
                    </>
                  )}

                  {/* Recommendation breakdown */}
                  {distribution.length > 0 && (
                    <>
                      <SectionTitle text="Recommendation Breakdown (30d)" />
                      <div style={{ display: 'flex', gap: 8, marginBottom: 18, flexWrap: 'wrap' }}>
                        {distribution.map(d => {
                          const total = distribution.reduce((s, x) => s + x.cnt, 0)
                          const pct = total > 0 ? Math.round((d.cnt / total) * 100) : 0
                          return (
                            <div key={d.recommendation} onClick={() => { onClose(); onNavigate('/watchlist') }}
                              style={{
                                padding: '8px 14px', background: 'rgba(255,255,255,0.03)',
                                border: '1px solid rgba(255,255,255,0.06)', borderRadius: 8, textAlign: 'center',
                                cursor: 'pointer', transition: 'background 80ms',
                              }}
                              onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(255,255,255,0.07)' }}
                              onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(255,255,255,0.03)' }}>
                              <div style={{ ...F, fontSize: 18, fontWeight: 800, color: recColor[d.recommendation] || '#8b95a5' }}>{d.cnt}</div>
                              <div style={{ ...F, fontSize: 8, color: 'var(--text3)', marginTop: 2 }}>{d.recommendation} ({pct}%)</div>
                            </div>
                          )
                        })}
                      </div>
                    </>
                  )}

                  {/* Top confidence picks */}
                  {topSymbols.length > 0 && (
                    <>
                      <SectionTitle text="Highest Confidence This Week" />
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 18 }}>
                        {topSymbols.map((s, i) => (
                          <div key={i} onClick={() => { onClose(); onNavigate(`/research?symbol=${s.symbol}`) }}
                            style={{
                              ...F, display: 'flex', alignItems: 'center', gap: 5, fontSize: 10,
                              padding: '4px 10px', background: 'rgba(255,255,255,0.03)',
                              border: '1px solid rgba(255,255,255,0.06)', borderRadius: 99,
                              cursor: 'pointer', transition: 'background 80ms, border-color 80ms',
                            }}
                            onMouseEnter={e => { const el = e.currentTarget as HTMLElement; el.style.background = 'rgba(255,255,255,0.08)'; el.style.borderColor = 'rgba(255,255,255,0.15)' }}
                            onMouseLeave={e => { const el = e.currentTarget as HTMLElement; el.style.background = 'rgba(255,255,255,0.03)'; el.style.borderColor = 'rgba(255,255,255,0.06)' }}>
                            <span style={{ fontWeight: 800, color: '#fff' }}>{s.symbol}</span>
                            <span style={{ color: recColor[s.recommendation] || '#8b95a5', fontWeight: 700, fontSize: 9 }}>{s.recommendation}</span>
                            <span style={{ color: s.confidence >= 0.9 ? '#0ecb81' : '#f0b90b', fontWeight: 600 }}>
                              {(s.confidence * 100).toFixed(0)}%
                            </span>
                          </div>
                        ))}
                      </div>
                    </>
                  )}

                  {/* Run fresh analysis */}
                  <div style={{ borderTop: '1px solid rgba(255,255,255,0.06)', paddingTop: 14 }}>
                    <div style={{ ...F, fontSize: 10, color: 'var(--text3)', marginBottom: 6 }}>Ask {agent.name} a new question</div>
                    <div style={{ display: 'flex', gap: 6 }}>
                      <input value={freshQuery} onChange={e => setFreshQuery(e.target.value)}
                        onKeyDown={e => e.key === 'Enter' && handleRunFresh()}
                        placeholder={`E.g. Deep-dive on V fundamentals...`}
                        style={{ ...F, fontSize: 11, padding: '8px 12px', flex: 1, border: '1px solid rgba(255,255,255,0.1)', borderRadius: 8, background: 'rgba(255,255,255,0.04)', color: '#fff', outline: 'none' }} />
                      <button onClick={handleRunFresh} disabled={runningFresh || !freshQuery.trim()} style={{
                        ...F, fontSize: 10, fontWeight: 700, padding: '8px 16px', border: 'none', borderRadius: 8,
                        background: freshQuery.trim() ? agent.color : 'rgba(255,255,255,0.06)',
                        color: freshQuery.trim() ? '#000' : 'var(--text3)',
                        cursor: freshQuery.trim() ? 'pointer' : 'default', transition: 'all 100ms',
                      }}>{runningFresh ? 'Running...' : 'Run Fresh'}</button>
                    </div>
                    {freshResult && (
                      <div style={{ ...F, fontSize: 11, color: 'var(--text1)', lineHeight: 1.6, marginTop: 10, padding: '10px 14px', background: 'rgba(255,255,255,0.03)', borderRadius: 8, maxHeight: 200, overflowY: 'auto', whiteSpace: 'pre-wrap', borderLeft: `3px solid ${agent.color}` }}>
                        {freshResult}
                      </div>
                    )}
                  </div>
                </>
              )}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

function StatBox({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div>
      <div style={{ ...F, fontSize: 7, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.04em', marginBottom: 3 }}>{label}</div>
      <div style={{ ...F, fontSize: 16, fontWeight: 800, color }}>{value}</div>
    </div>
  )
}

function SectionTitle({ text }: { text: string }) {
  return <div style={{ ...F, fontSize: 10, fontWeight: 800, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.04em', marginBottom: 8 }}>{text}</div>
}

function RecBadge({ rec }: { rec: string }) {
  const color = recColor[rec] || '#8b95a5'
  return (
    <span style={{ ...F, fontSize: 8, fontWeight: 800, padding: '2px 8px', borderRadius: 99, background: `${color}20`, color, letterSpacing: '.02em' }}>
      {rec}
    </span>
  )
}
