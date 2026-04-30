import React, { useState, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { timeAgo } from '../lib/format'

const F = { fontFamily: 'var(--sans)' as const }

interface AgentResult {
  symbol: string
  recommendation: string
  confidence: number
  summary: string
  narrative: string
  next_action: string
  created_at: string
}

interface AgentDistItem {
  recommendation: string
  cnt: number
}

interface AgentDetailData {
  latest: AgentResult[]
  distribution: AgentDistItem[]
  top_symbols: AgentResult[]
}

interface AgentConfig {
  id: string
  name: string
  role: string
  color: string
  icon: string
  dbNames: string[]
}

interface AgentStats {
  total_analyses: number
  avg_confidence: number
  last_run: string
}

interface Props {
  agent: AgentConfig | null
  stats: AgentStats | null
  detail: AgentDetailData | null
  onClose: () => void
  onRunFresh: (question: string) => void
}

const recColor: Record<string, string> = {
  BUY: 'var(--green)', HOLD: 'var(--amber)', SELL: 'var(--red)',
  TRIM: 'var(--red)', ADD: 'var(--green)', NEUTRAL: 'var(--text2)',
  AVOID: 'var(--red)', RESEARCH: 'var(--accent)',
}

export default function AgentModal({ agent, stats, detail, onClose, onRunFresh }: Props) {
  const [freshQuery, setFreshQuery] = useState('')

  const handleRunFresh = useCallback(() => {
    if (freshQuery.trim()) {
      onRunFresh(freshQuery.trim())
      setFreshQuery('')
    }
  }, [freshQuery, onRunFresh])

  return (
    <AnimatePresence>
      {agent && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}
          onClick={onClose}
          style={{
            position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            zIndex: 9999, backdropFilter: 'blur(4px)',
          }}
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 10 }}
            transition={{ duration: 0.2 }}
            onClick={e => e.stopPropagation()}
            style={{
              background: 'rgba(16,20,28,0.98)', border: '1px solid rgba(255,255,255,0.1)',
              borderRadius: 16, width: '90%', maxWidth: 700, maxHeight: '85vh',
              overflowY: 'auto', boxShadow: '0 24px 80px rgba(0,0,0,0.6)',
              borderTop: `3px solid ${agent.color}`,
            }}
          >
            {/* Header */}
            <div style={{ padding: '20px 24px 16px', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
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

              {/* Stats row */}
              {stats && (
                <div style={{ display: 'flex', gap: 20, marginTop: 14 }}>
                  <StatPill label="Confidence" value={`${(stats.avg_confidence * 100).toFixed(0)}%`}
                    color={stats.avg_confidence >= 0.7 ? 'var(--green)' : 'var(--amber)'} />
                  <StatPill label="Analyses (30d)" value={String(stats.total_analyses)} color="var(--text1)" />
                  <StatPill label="Last Run" value={stats.last_run ? timeAgo(stats.last_run) : 'never'} color="var(--text2)" />
                </div>
              )}
            </div>

            {/* Body */}
            <div style={{ padding: '16px 24px 20px' }}>

              {/* No data state */}
              {(!detail || detail.latest.length === 0) && (
                <div style={{ textAlign: 'center', padding: '24px 0' }}>
                  <div style={{ ...F, fontSize: 13, color: 'var(--text2)', marginBottom: 12 }}>
                    No recent analysis from {agent.name}. Would you like to run one?
                  </div>
                  <div style={{ display: 'flex', gap: 8, justifyContent: 'center' }}>
                    <input
                      value={freshQuery}
                      onChange={e => setFreshQuery(e.target.value)}
                      onKeyDown={e => e.key === 'Enter' && handleRunFresh()}
                      placeholder={`Ask ${agent.name} anything...`}
                      style={{
                        ...F, fontSize: 12, padding: '8px 14px', width: 300,
                        border: '1px solid rgba(255,255,255,0.1)', borderRadius: 8,
                        background: 'rgba(255,255,255,0.05)', color: '#fff', outline: 'none',
                      }}
                    />
                    <button onClick={handleRunFresh} style={{
                      ...F, fontSize: 11, fontWeight: 700, padding: '8px 16px', border: 'none',
                      borderRadius: 8, background: agent.color, color: '#000', cursor: 'pointer',
                    }}>Run Analysis</button>
                  </div>
                </div>
              )}

              {/* Latest discoveries */}
              {detail && detail.latest.length > 0 && (
                <>
                  <SectionTitle text="Latest Discoveries" />
                  <div style={{ display: 'grid', gap: 8, marginBottom: 16 }}>
                    {detail.latest.map((r, i) => (
                      <div key={i} style={{
                        padding: '10px 14px', background: 'rgba(255,255,255,0.03)',
                        border: '1px solid rgba(255,255,255,0.06)', borderRadius: 10,
                        borderLeft: `3px solid ${recColor[r.recommendation] || 'var(--text3)'}`,
                      }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <span style={{ ...F, fontSize: 14, fontWeight: 800, color: '#fff' }}>{r.symbol}</span>
                            <span style={{
                              ...F, fontSize: 8, fontWeight: 800, padding: '2px 8px', borderRadius: 99,
                              background: `${recColor[r.recommendation] || 'var(--text3)'}20`,
                              color: recColor[r.recommendation] || 'var(--text3)',
                            }}>{r.recommendation}</span>
                            <span style={{ ...F, fontSize: 10, fontWeight: 700, color: r.confidence >= 0.7 ? 'var(--green)' : 'var(--amber)' }}>
                              {(r.confidence * 100).toFixed(0)}%
                            </span>
                          </div>
                          <span style={{ ...F, fontSize: 8, color: 'var(--text3)' }}>{r.created_at ? timeAgo(r.created_at) : ''}</span>
                        </div>
                        <div style={{ ...F, fontSize: 11, color: 'var(--text2)', lineHeight: 1.6 }}>
                          {r.summary || r.narrative || '—'}
                        </div>
                        {r.next_action && (
                          <div style={{ ...F, fontSize: 10, color: 'var(--accent)', marginTop: 4, fontWeight: 600 }}>
                            Next: {r.next_action}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>

                  {/* Recommendation distribution */}
                  {detail.distribution.length > 0 && (
                    <>
                      <SectionTitle text="Recommendation Breakdown (30 days)" />
                      <div style={{ display: 'flex', gap: 10, marginBottom: 16, flexWrap: 'wrap' }}>
                        {detail.distribution.map(d => {
                          const total = detail.distribution.reduce((s, x) => s + x.cnt, 0)
                          const pct = total > 0 ? Math.round((d.cnt / total) * 100) : 0
                          return (
                            <div key={d.recommendation} style={{
                              padding: '6px 12px', background: 'rgba(255,255,255,0.04)',
                              border: '1px solid rgba(255,255,255,0.06)', borderRadius: 8,
                              textAlign: 'center', minWidth: 60,
                            }}>
                              <div style={{ ...F, fontSize: 16, fontWeight: 800, color: recColor[d.recommendation] || 'var(--text1)' }}>
                                {d.cnt}
                              </div>
                              <div style={{ ...F, fontSize: 8, color: 'var(--text3)' }}>{d.recommendation} ({pct}%)</div>
                            </div>
                          )
                        })}
                      </div>
                    </>
                  )}

                  {/* Top symbols with high confidence */}
                  {detail.top_symbols.length > 0 && (
                    <>
                      <SectionTitle text="Top Confidence Picks This Week" />
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 16 }}>
                        {detail.top_symbols.map((s, i) => (
                          <div key={i} style={{
                            ...F, display: 'flex', alignItems: 'center', gap: 4, fontSize: 10, padding: '4px 10px',
                            background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.06)',
                            borderRadius: 99,
                          }}>
                            <span style={{ fontWeight: 800, color: '#fff' }}>{s.symbol}</span>
                            <span style={{ color: recColor[s.recommendation] || 'var(--text3)', fontWeight: 700 }}>{s.recommendation}</span>
                            <span style={{ color: s.confidence >= 0.8 ? 'var(--green)' : 'var(--amber)', fontWeight: 600 }}>
                              {(s.confidence * 100).toFixed(0)}%
                            </span>
                          </div>
                        ))}
                      </div>
                    </>
                  )}

                  {/* Run fresh analysis */}
                  <div style={{ borderTop: '1px solid rgba(255,255,255,0.06)', paddingTop: 12 }}>
                    <div style={{ ...F, fontSize: 10, color: 'var(--text3)', marginBottom: 6 }}>Ask {agent.name} a question</div>
                    <div style={{ display: 'flex', gap: 6 }}>
                      <input
                        value={freshQuery}
                        onChange={e => setFreshQuery(e.target.value)}
                        onKeyDown={e => e.key === 'Enter' && handleRunFresh()}
                        placeholder={`E.g. Deep-dive on V fundamentals...`}
                        style={{
                          ...F, fontSize: 11, padding: '7px 12px', flex: 1,
                          border: '1px solid rgba(255,255,255,0.1)', borderRadius: 8,
                          background: 'rgba(255,255,255,0.05)', color: '#fff', outline: 'none',
                        }}
                      />
                      <button onClick={handleRunFresh} disabled={!freshQuery.trim()} style={{
                        ...F, fontSize: 10, fontWeight: 700, padding: '7px 14px', border: 'none',
                        borderRadius: 8, background: freshQuery.trim() ? agent.color : 'var(--bg3)',
                        color: freshQuery.trim() ? '#000' : 'var(--text3)', cursor: freshQuery.trim() ? 'pointer' : 'default',
                        transition: 'all 100ms',
                      }}>Run Fresh</button>
                    </div>
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

function StatPill({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div>
      <div style={{ ...F, fontSize: 7, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.04em', marginBottom: 2 }}>{label}</div>
      <div style={{ ...F, fontSize: 14, fontWeight: 800, color }}>{value}</div>
    </div>
  )
}

function SectionTitle({ text }: { text: string }) {
  return <div style={{ ...F, fontSize: 10, fontWeight: 800, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.03em', marginBottom: 8 }}>{text}</div>
}
