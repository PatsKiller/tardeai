import React, { useState, useEffect, useCallback } from 'react'

const F = { fontFamily: 'var(--sans)' as const }
const glass = { background: 'rgba(16,20,28,0.96)', backdropFilter: 'blur(16px)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 12 }

type Screener = {
  id: string; display_name: string; description: string; group_name: string
  strategy_class: string; strategies: string[]; finviz_url: string
  run_windows: string[]; status: string; enabled: boolean
  quality_gates: Record<string, number>; last_run_at: string | null
  last_result_count: number | null; change_log: Array<{date: string; action: string; note: string}>
  created_at: string; updated_at: string
}

type Coverage = {
  total_strategies: number; covered: number; gaps: string[]
  gap_count: number; multi_mapped: Record<string, string[]>
}

type Tab = 'list' | 'coverage' | 'gaps' | 'add'

const BADGE_COLORS: Record<string, string> = {
  core: '#3b82f6', quality: '#10b981', event: '#f59e0b',
  growth: '#8b5cf6', sector: '#ec4899', pm_diversity: '#06b6d4', options: '#6b7280'
}

export default function ScreenerConfigModal({ onClose }: { onClose: () => void }) {
  const [screeners, setScreeners] = useState<Screener[]>([])
  const [coverage, setCoverage] = useState<Coverage | null>(null)
  const [tab, setTab] = useState<Tab>('list')
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState<string | null>(null)
  const [editForm, setEditForm] = useState<Partial<Screener>>({})
  const [addForm, setAddForm] = useState<Partial<Screener>>({ strategies: [], run_windows: [], enabled: true, quality_gates: { price_floor: 3, spread_max: 3, rsi_max: 80 } })
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const r = await fetch('/api/v2/strategy-analytics/screeners')
      const d = await r.json()
      if (d.ok) {
        setScreeners(d.data.screeners || [])
        setCoverage(d.data.strategy_coverage || null)
      }
    } catch { /* */ }
    setLoading(false)
  }, [])

  useEffect(() => { load() }, [load])

  const save = async (id: string, data: Record<string, any>, note: string) => {
    setSaving(true); setMsg('')
    try {
      const r = await fetch(`/api/v2/strategy-analytics/screeners/${id}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...data, change_note: note })
      })
      const d = await r.json()
      setMsg(d.ok ? `Saved ${id}` : d.error || 'Save failed')
      if (d.ok) { setEditing(null); load() }
    } catch { setMsg('Network error') }
    setSaving(false)
  }

  const create = async () => {
    if (!addForm.id) { setMsg('ID required'); return }
    setSaving(true); setMsg('')
    try {
      const r = await fetch('/api/v2/strategy-analytics/screeners', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(addForm)
      })
      const d = await r.json()
      setMsg(d.ok ? `Created ${addForm.id}` : d.error || 'Create failed')
      if (d.ok) { setAddForm({ strategies: [], run_windows: [], enabled: true, quality_gates: { price_floor: 3, spread_max: 3, rsi_max: 80 } }); setTab('list'); load() }
    } catch { setMsg('Network error') }
    setSaving(false)
  }

  const toggleEnabled = async (s: Screener) => {
    await save(s.id, { enabled: !s.enabled }, `${s.enabled ? 'Disabled' : 'Enabled'} via dashboard`)
  }

  const deleteScreener = async (id: string) => {
    if (!confirm(`Disable screener "${id}"? (soft delete)`)) return
    setSaving(true)
    try {
      const r = await fetch(`/api/v2/strategy-analytics/screeners/${id}`, { method: 'DELETE' })
      const d = await r.json()
      setMsg(d.ok ? `Disabled ${id}` : d.error || 'Failed')
      load()
    } catch { setMsg('Network error') }
    setSaving(false)
  }

  const startEdit = (s: Screener) => {
    setEditing(s.id)
    setEditForm({ ...s })
  }

  // ── Render ──
  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 9999, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.7)' }} onClick={onClose}>
      <div style={{ ...glass, width: '95vw', maxWidth: 1100, maxHeight: '90vh', overflow: 'auto', padding: 24 }} onClick={e => e.stopPropagation()}>

        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <div>
            <h2 style={{ ...F, fontSize: 18, fontWeight: 800, color: '#fff', margin: 0 }}>Finviz Screener Configuration</h2>
            <div style={{ ...F, fontSize: 11, color: 'var(--text2)', marginTop: 2 }}>
              {screeners.length} screeners | {coverage?.covered || 0}/{coverage?.total_strategies || 0} strategies covered | {coverage?.gap_count || 0} gaps
            </div>
          </div>
          <button onClick={onClose} style={{ ...F, background: 'none', border: 'none', color: 'var(--text2)', fontSize: 20, cursor: 'pointer' }}>x</button>
        </div>

        {msg && <div style={{ ...F, fontSize: 11, padding: '6px 10px', borderRadius: 6, background: msg.includes('error') || msg.includes('fail') ? '#7f1d1d' : '#14532d', color: '#fff', marginBottom: 10 }}>{msg}</div>}

        {/* Tabs */}
        <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
          {(['list', 'coverage', 'gaps', 'add'] as Tab[]).map(t => (
            <button key={t} onClick={() => setTab(t)}
              style={{ ...F, fontSize: 11, fontWeight: tab === t ? 800 : 500, padding: '6px 14px', borderRadius: 6,
                border: tab === t ? '1px solid var(--accent)' : '1px solid var(--border)',
                background: tab === t ? 'rgba(59,130,246,0.15)' : 'transparent', color: tab === t ? 'var(--accent)' : 'var(--text2)', cursor: 'pointer' }}>
              {t === 'list' ? `Screeners (${screeners.filter(s => s.status !== 'deleted').length})` : t === 'coverage' ? 'Strategy Coverage' : t === 'gaps' ? `Gaps (${coverage?.gap_count || 0})` : '+ Add Screener'}
            </button>
          ))}
        </div>

        {loading ? <div style={{ ...F, color: 'var(--text2)', padding: 20 }}>Loading...</div> : (
          <>
            {/* ── LIST TAB ── */}
            {tab === 'list' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {screeners.filter(s => s.status !== 'deleted').map(s => (
                  <div key={s.id} style={{ ...glass, padding: 12, opacity: s.enabled ? 1 : 0.5 }}>
                    {editing === s.id ? (
                      /* Edit Form */
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                          <label style={{ ...F, fontSize: 10, color: 'var(--text2)' }}>Display Name
                            <input value={editForm.display_name || ''} onChange={e => setEditForm(f => ({ ...f, display_name: e.target.value }))}
                              style={{ ...F, width: '100%', padding: 6, background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 4, color: '#fff', fontSize: 12, marginTop: 2 }} />
                          </label>
                          <label style={{ ...F, fontSize: 10, color: 'var(--text2)' }}>Group
                            <input value={editForm.group_name || ''} onChange={e => setEditForm(f => ({ ...f, group_name: e.target.value }))}
                              style={{ ...F, width: '100%', padding: 6, background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 4, color: '#fff', fontSize: 12, marginTop: 2 }} />
                          </label>
                        </div>
                        <label style={{ ...F, fontSize: 10, color: 'var(--text2)' }}>Description
                          <input value={editForm.description || ''} onChange={e => setEditForm(f => ({ ...f, description: e.target.value }))}
                            style={{ ...F, width: '100%', padding: 6, background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 4, color: '#fff', fontSize: 12, marginTop: 2 }} />
                        </label>
                        <label style={{ ...F, fontSize: 10, color: 'var(--text2)' }}>Finviz URL
                          <input value={editForm.finviz_url || ''} onChange={e => setEditForm(f => ({ ...f, finviz_url: e.target.value }))}
                            style={{ ...F, width: '100%', padding: 6, background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 4, color: '#fff', fontSize: 10, marginTop: 2 }} />
                        </label>
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                          <label style={{ ...F, fontSize: 10, color: 'var(--text2)' }}>Strategies (comma-sep)
                            <input value={(editForm.strategies || []).join(', ')} onChange={e => setEditForm(f => ({ ...f, strategies: e.target.value.split(',').map(s => s.trim()).filter(Boolean) }))}
                              style={{ ...F, width: '100%', padding: 6, background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 4, color: '#fff', fontSize: 11, marginTop: 2 }} />
                          </label>
                          <label style={{ ...F, fontSize: 10, color: 'var(--text2)' }}>Run Windows (comma-sep)
                            <input value={(editForm.run_windows || []).join(', ')} onChange={e => setEditForm(f => ({ ...f, run_windows: e.target.value.split(',').map(s => s.trim()).filter(Boolean) }))}
                              style={{ ...F, width: '100%', padding: 6, background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 4, color: '#fff', fontSize: 11, marginTop: 2 }} />
                          </label>
                        </div>
                        <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
                          <button disabled={saving} onClick={() => save(s.id, editForm, 'Edited via dashboard')}
                            style={{ ...F, fontSize: 11, fontWeight: 700, padding: '6px 16px', borderRadius: 6, border: 'none', background: '#2563eb', color: '#fff', cursor: 'pointer' }}>
                            {saving ? 'Saving...' : 'Save'}
                          </button>
                          <button onClick={() => setEditing(null)}
                            style={{ ...F, fontSize: 11, padding: '6px 12px', borderRadius: 6, border: '1px solid var(--border)', background: 'transparent', color: 'var(--text2)', cursor: 'pointer' }}>Cancel</button>
                        </div>
                      </div>
                    ) : (
                      /* Display Row */
                      <div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                          <div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                              <span style={{ ...F, fontSize: 13, fontWeight: 800, color: '#fff' }}>{s.display_name}</span>
                              <span style={{ ...F, fontSize: 9, fontWeight: 700, padding: '2px 6px', borderRadius: 4, background: BADGE_COLORS[s.group_name] || '#555', color: '#fff' }}>{s.group_name}</span>
                              {!s.enabled && <span style={{ ...F, fontSize: 9, padding: '2px 6px', borderRadius: 4, background: '#7f1d1d', color: '#fff' }}>DISABLED</span>}
                            </div>
                            <div style={{ ...F, fontSize: 10, color: 'var(--text2)', marginTop: 2 }}>{s.description}</div>
                          </div>
                          <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
                            <button onClick={() => toggleEnabled(s)} style={{ ...F, fontSize: 9, padding: '4px 8px', borderRadius: 4, border: '1px solid var(--border)', background: 'transparent', color: s.enabled ? 'var(--green)' : 'var(--red)', cursor: 'pointer' }}>
                              {s.enabled ? 'ON' : 'OFF'}
                            </button>
                            <button onClick={() => startEdit(s)} style={{ ...F, fontSize: 9, padding: '4px 8px', borderRadius: 4, border: '1px solid var(--border)', background: 'transparent', color: 'var(--text2)', cursor: 'pointer' }}>Edit</button>
                            <button onClick={() => deleteScreener(s.id)} style={{ ...F, fontSize: 9, padding: '4px 8px', borderRadius: 4, border: '1px solid #7f1d1d', background: 'transparent', color: '#ef4444', cursor: 'pointer' }}>Del</button>
                          </div>
                        </div>

                        {/* Meta row */}
                        <div style={{ display: 'flex', gap: 16, marginTop: 8, flexWrap: 'wrap' }}>
                          <div style={{ ...F, fontSize: 10, color: 'var(--text3)' }}>
                            <b style={{ color: 'var(--text1)' }}>Strategies:</b> {(s.strategies || []).join(', ') || 'none'}
                          </div>
                          <div style={{ ...F, fontSize: 10, color: 'var(--text3)' }}>
                            <b style={{ color: 'var(--text1)' }}>Windows:</b> {(s.run_windows || []).join(', ') || 'none'}
                          </div>
                          {s.last_run_at && <div style={{ ...F, fontSize: 10, color: 'var(--text3)' }}>
                            <b style={{ color: 'var(--text1)' }}>Last run:</b> {new Date(s.last_run_at).toLocaleString()} ({s.last_result_count ?? '?'} results)
                          </div>}
                        </div>

                        {/* Change log */}
                        {(s.change_log || []).length > 0 && (
                          <div style={{ marginTop: 6, padding: '4px 8px', background: 'rgba(255,255,255,0.03)', borderRadius: 4 }}>
                            <div style={{ ...F, fontSize: 9, fontWeight: 700, color: 'var(--text2)', marginBottom: 2 }}>Recent Changes</div>
                            {(s.change_log || []).slice(-3).reverse().map((c, i) => (
                              <div key={i} style={{ ...F, fontSize: 9, color: 'var(--text3)' }}>{c.date} — {c.action}: {c.note}</div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}

            {/* ── COVERAGE TAB ── */}
            {tab === 'coverage' && coverage && (
              <div>
                <div style={{ ...F, fontSize: 12, fontWeight: 700, color: '#fff', marginBottom: 8 }}>
                  Strategy Coverage: {coverage.covered}/{coverage.total_strategies} ({Math.round(coverage.covered / coverage.total_strategies * 100)}%)
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 6 }}>
                  {Object.entries(coverage.multi_mapped || {}).sort((a, b) => b[1].length - a[1].length).map(([strat, ids]) => (
                    <div key={strat} style={{ ...glass, padding: 8 }}>
                      <div style={{ ...F, fontSize: 11, fontWeight: 700, color: '#fff' }}>{strat.replace(/_/g, ' ')}</div>
                      <div style={{ ...F, fontSize: 9, color: 'var(--text2)', marginTop: 2 }}>
                        {ids.length} screener{ids.length > 1 ? 's' : ''}: {ids.join(', ')}
                      </div>
                    </div>
                  ))}
                  {coverage.gaps.map(g => (
                    <div key={g} style={{ ...glass, padding: 8, borderColor: '#7f1d1d' }}>
                      <div style={{ ...F, fontSize: 11, fontWeight: 700, color: '#ef4444' }}>{g.replace(/_/g, ' ')}</div>
                      <div style={{ ...F, fontSize: 9, color: '#f87171' }}>NO SCREENER — gap</div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* ── GAPS TAB ── */}
            {tab === 'gaps' && coverage && (
              <div>
                <div style={{ ...F, fontSize: 14, fontWeight: 800, color: '#ef4444', marginBottom: 12 }}>
                  {coverage.gap_count} Strategies Without Screener Coverage
                </div>
                {coverage.gaps.length === 0 ? (
                  <div style={{ ...F, fontSize: 12, color: 'var(--green)' }}>All strategies have at least one screener mapped.</div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    {coverage.gaps.map(g => (
                      <div key={g} style={{ ...glass, padding: 12, borderColor: '#7f1d1d' }}>
                        <div style={{ ...F, fontSize: 13, fontWeight: 700, color: '#fff' }}>{g.replace(/_/g, ' ')}</div>
                        <div style={{ ...F, fontSize: 10, color: '#f87171', marginTop: 4 }}>
                          Critical gap: No Finviz screener feeds this strategy. Candidates can only come from classification-based promotion.
                        </div>
                        <button onClick={() => { setTab('add'); setAddForm(f => ({ ...f, strategies: [g], id: g + '_screener' })) }}
                          style={{ ...F, fontSize: 10, fontWeight: 700, marginTop: 6, padding: '4px 12px', borderRadius: 4, border: 'none', background: '#2563eb', color: '#fff', cursor: 'pointer' }}>
                          Create Screener for {g.replace(/_/g, ' ')}
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* ── ADD TAB ── */}
            {tab === 'add' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10, maxWidth: 600 }}>
                <div style={{ ...F, fontSize: 14, fontWeight: 800, color: '#fff', marginBottom: 4 }}>Add New Screener</div>
                <label style={{ ...F, fontSize: 10, color: 'var(--text2)' }}>Screener ID (no spaces)
                  <input value={addForm.id || ''} onChange={e => setAddForm(f => ({ ...f, id: e.target.value.replace(/\s/g, '_').toLowerCase() }))}
                    style={{ ...F, width: '100%', padding: 6, background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 4, color: '#fff', fontSize: 12, marginTop: 2 }} />
                </label>
                <label style={{ ...F, fontSize: 10, color: 'var(--text2)' }}>Display Name
                  <input value={addForm.display_name || ''} onChange={e => setAddForm(f => ({ ...f, display_name: e.target.value }))}
                    style={{ ...F, width: '100%', padding: 6, background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 4, color: '#fff', fontSize: 12, marginTop: 2 }} />
                </label>
                <label style={{ ...F, fontSize: 10, color: 'var(--text2)' }}>Description
                  <input value={addForm.description || ''} onChange={e => setAddForm(f => ({ ...f, description: e.target.value }))}
                    style={{ ...F, width: '100%', padding: 6, background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 4, color: '#fff', fontSize: 12, marginTop: 2 }} />
                </label>
                <label style={{ ...F, fontSize: 10, color: 'var(--text2)' }}>Finviz URL
                  <input value={addForm.finviz_url || ''} onChange={e => setAddForm(f => ({ ...f, finviz_url: e.target.value }))}
                    style={{ ...F, width: '100%', padding: 6, background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 4, color: '#fff', fontSize: 10, marginTop: 2 }}
                    placeholder="https://elite.finviz.com/export?v=152&f=..." />
                </label>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                  <label style={{ ...F, fontSize: 10, color: 'var(--text2)' }}>Strategies (comma-sep)
                    <input value={(addForm.strategies || []).join(', ')} onChange={e => setAddForm(f => ({ ...f, strategies: e.target.value.split(',').map(s => s.trim()).filter(Boolean) }))}
                      style={{ ...F, width: '100%', padding: 6, background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 4, color: '#fff', fontSize: 11, marginTop: 2 }} />
                  </label>
                  <label style={{ ...F, fontSize: 10, color: 'var(--text2)' }}>Run Windows (comma-sep)
                    <input value={(addForm.run_windows || []).join(', ')} onChange={e => setAddForm(f => ({ ...f, run_windows: e.target.value.split(',').map(s => s.trim()).filter(Boolean) }))}
                      style={{ ...F, width: '100%', padding: 6, background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 4, color: '#fff', fontSize: 11, marginTop: 2 }}
                      placeholder="0900, 1000, 1400" />
                  </label>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                  <label style={{ ...F, fontSize: 10, color: 'var(--text2)' }}>Group
                    <input value={addForm.group_name || ''} onChange={e => setAddForm(f => ({ ...f, group_name: e.target.value }))}
                      style={{ ...F, width: '100%', padding: 6, background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 4, color: '#fff', fontSize: 11, marginTop: 2 }}
                      placeholder="quality / core / event / growth" />
                  </label>
                  <label style={{ ...F, fontSize: 10, color: 'var(--text2)' }}>Strategy Class
                    <input value={addForm.strategy_class || ''} onChange={e => setAddForm(f => ({ ...f, strategy_class: e.target.value }))}
                      style={{ ...F, width: '100%', padding: 6, background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 4, color: '#fff', fontSize: 11, marginTop: 2 }} />
                  </label>
                </div>
                <button disabled={saving || !addForm.id} onClick={create}
                  style={{ ...F, fontSize: 12, fontWeight: 800, padding: '8px 20px', borderRadius: 6, border: 'none', background: '#2563eb', color: '#fff', cursor: 'pointer', marginTop: 8, opacity: (!addForm.id || saving) ? 0.5 : 1 }}>
                  {saving ? 'Creating...' : 'Create Screener'}
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
