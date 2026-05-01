import { useState, useRef, useEffect } from 'react'

const CATEGORIES = [
  { value: 'disability_retirement', label: 'Disability & Retirement', agents: ['alex','tax'], threshold: 55 },
  { value: 'retirement_planning', label: 'Retirement Planning', agents: ['alex','steph'], threshold: 60 },
  { value: 'tax_strategy', label: 'Tax Strategy', agents: ['alex','tax'], threshold: 60 },
  { value: 'dividend_income', label: 'Dividend & Income', agents: ['steph','maria'], threshold: 65 },
  { value: 'macro_economics', label: 'Macro & Fed Policy', agents: ['maria','risk'], threshold: 65 },
  { value: 'etf_indexing', label: 'ETF & Index Funds', agents: ['steph','risk'], threshold: 70 },
  { value: 'investment_general', label: 'General Investing', agents: ['maria','steph'], threshold: 70 },
  { value: 'financial_education', label: 'Financial Education', agents: ['maria','steph'], threshold: 70 },
]

const AGENTS = ['alex','tax','maria','steph','risk']
const AGENT_COLORS: Record<string,string> = { alex:'#aa55ff', tax:'#ffaa00', maria:'#4488ff', steph:'#00cc88', risk:'#ff4466' }

interface Props { isOpen: boolean; onClose: () => void; onSuccess?: (name: string) => void }

export function AddYouTubeChannelModal({ isOpen, onClose, onSuccess }: Props) {
  const [name, setName] = useState('')
  const [channelId, setChannelId] = useState('')
  const [url, setUrl] = useState('')
  const [category, setCategory] = useState('investment_general')
  const [priority, setPriority] = useState('medium')
  const [agentTags, setAgentTags] = useState<string[]>(['maria','steph'])
  const [threshold, setThreshold] = useState(70)
  const [saving, setSaving] = useState(false)
  const [result, setResult] = useState<'success'|'error'|null>(null)
  const [errorMsg, setErrorMsg] = useState('')
  const nameRef = useRef<HTMLInputElement>(null)

  const [lookupMsg, setLookupMsg] = useState('')

  useEffect(() => { if (isOpen) setTimeout(() => nameRef.current?.focus(), 100) }, [isOpen])

  // Auto-map when URL is pasted
  useEffect(() => {
    if (!url.trim()) return
    const m = url.match(/youtube\.com\/(?:channel\/|@|c\/|user\/)([^/?&]+)/)
    if (m) {
      setChannelId(m[1])
      // Lookup in DB
      fetch(`/api/v2/youtube/channel-lookup?url=${encodeURIComponent(url)}`)
        .then(r => r.json())
        .then(d => {
          const ch = d.data || d
          if (ch.found && ch.channel) {
            setName(ch.channel.channel_name || '')
            setChannelId(ch.channel.channel_id || m[1])
            if (ch.channel.category) handleCategoryChange(ch.channel.category)
            if (ch.channel.priority) setPriority(ch.channel.priority)
            if (ch.channel.auto_promote_threshold) setThreshold(ch.channel.auto_promote_threshold)
            if (ch.channel.agent_tags) setAgentTags(Array.isArray(ch.channel.agent_tags) ? ch.channel.agent_tags : [])
            setLookupMsg('Channel already tracked \u2014 editing existing entry')
          } else {
            setLookupMsg('New channel \u2014 fill in name and category')
          }
        })
        .catch(() => {})
    }
  }, [url])

  const handleCategoryChange = (cat: string) => {
    setCategory(cat)
    const def = CATEGORIES.find(c => c.value === cat)
    if (def) { setAgentTags(def.agents); setThreshold(def.threshold) }
  }

  const handleSave = async () => {
    if (!name.trim()) return
    setSaving(true); setErrorMsg('')
    try {
      const res = await fetch('/api/v2/youtube/channels/add', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          channel_name: name.trim(),
          channel_id: channelId.trim() || name.trim().toLowerCase().replace(/\s+/g, '_'),
          channel_url: url.trim(),
          category, priority,
          agent_tags: agentTags,
          auto_promote_threshold: threshold,
          strategy_focus: category,
          added_by: 'dashboard',
        }),
      })
      const data = await res.json()
      if (data.ok) { setResult('success'); onSuccess?.(name.trim()) }
      else { setErrorMsg(data.error || 'Failed'); setResult('error') }
    } catch { setErrorMsg('Network error'); setResult('error') }
    finally { setSaving(false) }
  }

  const reset = () => { setName(''); setChannelId(''); setUrl(''); setCategory('investment_general'); setPriority('medium'); setAgentTags(['maria','steph']); setThreshold(70); setResult(null); setErrorMsg('') }
  const close = () => { reset(); onClose() }

  if (!isOpen) return null

  return (
    <div style={{ position:'fixed', inset:0, zIndex:1100, background:'rgba(0,0,0,.6)', display:'flex', alignItems:'center', justifyContent:'center' }} onClick={e => { if (e.target === e.currentTarget) close() }}>
      <div style={{ background:'var(--bg1)', border:'1px solid var(--border)', borderRadius:10, width:480, maxHeight:'85vh', overflowY:'auto', padding:'20px 24px', fontFamily:'var(--sans)' }} onClick={e => e.stopPropagation()}>
        <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:16 }}>
          <div style={{ fontSize:16, fontWeight:800, color:'var(--text0)' }}>Add YouTube Channel</div>
          <button onClick={close} style={{ background:'transparent', border:'1px solid var(--border)', borderRadius:4, padding:'2px 8px', color:'var(--text3)', cursor:'pointer', fontSize:14 }}>x</button>
        </div>

        {result === 'success' ? (
          <div style={{ textAlign:'center', padding:'20px 0' }}>
            <div style={{ fontSize:32, marginBottom:12 }}>Done</div>
            <div style={{ fontSize:14, fontWeight:700, color:'var(--green)', marginBottom:8 }}>Channel added: {name}</div>
            <div style={{ fontSize:11, color:'var(--text3)', marginBottom:16 }}>Transcripts will be fetched at 7 PM daily. Tagged for: {agentTags.join(', ')}</div>
            <div style={{ display:'flex', gap:8, justifyContent:'center' }}>
              <button onClick={reset} style={{ padding:'8px 16px', border:'1px solid var(--accent)', borderRadius:6, background:'transparent', color:'var(--accent)', cursor:'pointer', fontSize:12 }}>Add Another</button>
              <button onClick={close} style={{ padding:'8px 16px', border:'1px solid var(--border)', borderRadius:6, background:'transparent', color:'var(--text3)', cursor:'pointer', fontSize:12 }}>Done</button>
            </div>
          </div>
        ) : (
          <>
            {result === 'error' && <div style={{ background:'var(--red-dim)', border:'1px solid var(--red)', borderRadius:6, padding:'8px 12px', marginBottom:12, fontSize:11, color:'var(--red)' }}>{errorMsg}</div>}

            <Label>Channel URL (paste to auto-fill)</Label>
            <input value={url} onChange={e => setUrl(e.target.value)} placeholder="https://youtube.com/@ChannelName or /channel/UC..." style={inputStyle} />
            {lookupMsg && (
              <div style={{ fontSize: 10, padding: '4px 8px', marginBottom: 4, borderRadius: 4, color: lookupMsg.includes('already') ? 'var(--green)' : 'var(--accent)', background: lookupMsg.includes('already') ? 'rgba(0,255,136,.06)' : 'rgba(0,212,255,.06)' }}>{lookupMsg}</div>
            )}

            <Label>Channel Name *</Label>
            <input ref={nameRef} value={name} onChange={e => setName(e.target.value)} placeholder="e.g. Ben Felix" style={inputStyle} />

            <Label>Channel ID (auto-detected from URL)</Label>
            <input value={channelId} onChange={e => setChannelId(e.target.value)} placeholder="UC... (auto-generated if blank)" style={inputStyle} />

            <Label>Category</Label>
            <select value={category} onChange={e => handleCategoryChange(e.target.value)} style={{ ...inputStyle, width:'100%' }}>
              {CATEGORIES.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
            </select>

            <Label>Priority</Label>
            <div style={{ display:'flex', gap:6, marginBottom:12 }}>
              {(['high','medium','low'] as const).map(p => (
                <button key={p} onClick={() => setPriority(p)} style={{ flex:1, padding:'6px', background: priority===p ? 'rgba(41,121,255,0.15)' : 'transparent', border:`1px solid ${priority===p ? 'rgba(41,121,255,0.5)' : 'var(--border)'}`, borderRadius:4, color: priority===p ? 'var(--accent)' : 'var(--text3)', cursor:'pointer', fontSize:11, fontWeight:700, textTransform:'capitalize' }}>{p}</button>
              ))}
            </div>

            <Label>Agent Tags</Label>
            <div style={{ display:'flex', gap:6, flexWrap:'wrap', marginBottom:12 }}>
              {AGENTS.map(a => {
                const sel = agentTags.includes(a)
                const col = AGENT_COLORS[a] || 'var(--text3)'
                return <button key={a} onClick={() => setAgentTags(prev => sel ? prev.filter(x => x !== a) : [...prev, a])} style={{ padding:'4px 10px', borderRadius:4, background: sel ? `${col}18` : 'transparent', border:`1px solid ${sel ? col+'60' : 'var(--border)'}`, color: sel ? col : 'var(--text3)', cursor:'pointer', fontSize:11, fontFamily:'var(--mono)' }}>{sel ? '\u2713 ' : ''}{a}</button>
              })}
            </div>

            <Label>Promote at Quality &ge;</Label>
            <div style={{ display:'flex', alignItems:'center', gap:10, marginBottom:16 }}>
              <input type="range" min={40} max={90} value={threshold} onChange={e => setThreshold(Number(e.target.value))} style={{ flex:1, accentColor:'var(--accent)' }} />
              <span style={{ fontFamily:'var(--mono)', fontSize:14, fontWeight:700, color: threshold <= 60 ? 'var(--green)' : threshold <= 75 ? 'var(--amber)' : 'var(--red)', minWidth:30 }}>{threshold}</span>
            </div>

            <button onClick={handleSave} disabled={saving || !name.trim()} style={{ width:'100%', padding:'10px', background: name.trim() ? 'rgba(0,255,136,0.12)' : 'transparent', border:`1px solid ${name.trim() ? 'rgba(0,255,136,0.35)' : 'var(--border)'}`, borderRadius:6, color: name.trim() ? 'var(--green)' : 'var(--text3)', cursor: name.trim() ? 'pointer' : 'not-allowed', fontSize:13, fontWeight:700 }}>
              {saving ? 'Saving...' : 'Add Channel'}
            </button>
          </>
        )}
      </div>
    </div>
  )
}

function Label({ children }: { children: React.ReactNode }) {
  return <div style={{ fontSize:9, fontWeight:700, color:'var(--text3)', textTransform:'uppercase', letterSpacing:'.04em', marginBottom:4, marginTop:8 }}>{children}</div>
}

const inputStyle: React.CSSProperties = { width:'100%', background:'var(--bg3)', border:'1px solid var(--border)', borderRadius:6, padding:'8px 12px', color:'var(--text1)', fontSize:12, fontFamily:'var(--mono)', outline:'none', boxSizing:'border-box', marginBottom:4 }
