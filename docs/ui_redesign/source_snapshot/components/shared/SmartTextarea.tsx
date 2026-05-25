import { useState, useRef, useCallback } from 'react'

interface Props {
  value: string
  onChange: (val: string) => void
  placeholder?: string
  minHeight?: number
  showMic?: boolean
  showAiRewrite?: boolean
  pageType?: string
  disabled?: boolean
}

export function SmartTextarea({ value, onChange, placeholder = 'Type here...', minHeight = 80, showMic = true, showAiRewrite = true, pageType = 'approval', disabled = false }: Props) {
  const [isListening, setIsListening] = useState(false)
  const [isRewriting, setIsRewriting] = useState(false)
  const [rewriteError, setRewriteError] = useState('')
  const [micError, setMicError] = useState('')
  const recognitionRef = useRef<SpeechRecognition | null>(null)

  const startMic = useCallback(async () => {
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    if (!SR) {
      setMicError('Speech recognition requires Chrome browser.')
      return
    }
    // Must request mic permission via getUserMedia BEFORE SpeechRecognition
    // Chrome blocks mic on HTTP — getUserMedia will throw NotAllowedError
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      // Stop the stream immediately — we only needed permission
      stream.getTracks().forEach(t => t.stop())
    } catch (err: any) {
      if (err?.name === 'NotAllowedError' || err?.name === 'PermissionDeniedError') {
        setMicError('Mic blocked \u2014 Chrome requires HTTPS for microphone access')
      } else if (err?.name === 'NotFoundError') {
        setMicError('No microphone detected on this device')
      } else {
        setMicError('Mic blocked \u2014 Chrome requires HTTPS for microphone access')
      }
      return
    }
    setMicError('')
    const r: SpeechRecognition = new SR()
    r.continuous = true; r.interimResults = true; r.lang = 'en-US'
    const base = value
    r.onresult = (e: SpeechRecognitionEvent) => {
      let interim = '', final = ''
      for (let i = e.resultIndex; i < e.results.length; i++) {
        if (e.results[i].isFinal) final += e.results[i][0].transcript
        else interim += e.results[i][0].transcript
      }
      onChange(base + (base ? ' ' : '') + final + interim)
    }
    r.onerror = (ev: any) => {
      setIsListening(false)
      if (ev?.error === 'not-allowed') {
        setMicError('Mic blocked \u2014 Chrome requires HTTPS for microphone access')
      } else {
        setMicError('Mic error \u2014 try again')
      }
    }
    r.onend = () => setIsListening(false)
    recognitionRef.current = r
    try {
      r.start()
      setIsListening(true)
    } catch {
      setMicError('Mic blocked \u2014 Chrome requires HTTPS for microphone access')
    }
  }, [value, onChange])

  const stopMic = useCallback(() => { recognitionRef.current?.stop(); setIsListening(false) }, [])

  const handleRewrite = async () => {
    if (!value.trim() || value.trim().length < 5) return
    setIsRewriting(true); setRewriteError('')
    try {
      const res = await fetch('/api/v2/rewrite-note', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: value, page_type: pageType }),
      })
      const data = await res.json()
      if (data.ok && data.rewritten) {
        onChange(data.rewritten)
        setRewriteError(data.provider === 'claude-haiku' ? 'via Claude' : '')
      } else {
        setRewriteError(data.error || 'Rewrite failed')
      }
    } catch { setRewriteError('Network error') }
    finally { setIsRewriting(false) }
  }

  const btnBase: React.CSSProperties = { background: 'transparent', border: '1px solid rgba(255,255,255,0.15)', borderRadius: 4, padding: '3px 8px', cursor: 'pointer', fontSize: 11, color: 'var(--text3)', fontFamily: 'var(--mono)' }

  return (
    <div style={{ position: 'relative', width: '100%' }}>
      <textarea value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder} disabled={disabled} spellCheck
        style={{
          width: '100%', minHeight, background: 'var(--bg1)',
          border: `2px solid ${isListening ? '#ff3355' : 'var(--border)'}`,
          borderRadius: 6, padding: '10px 12px 32px', color: 'var(--text1)',
          fontSize: 13, fontFamily: 'var(--sans)', resize: 'vertical', outline: 'none',
          boxSizing: 'border-box', transition: 'border-color .2s',
          animation: isListening ? 'smarttextarea-pulse 1.2s ease-in-out infinite' : 'none',
        }} />
      {/* Mic error message below textarea */}
      {micError && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 4, padding: '5px 10px', background: 'rgba(255,51,85,0.1)', border: '1px solid rgba(255,51,85,0.3)', borderRadius: 4, fontSize: 11, color: '#ff3355' }}>
          <span style={{ flex: 1 }}>{micError}</span>
          <button onClick={() => setMicError('')} style={{ background: 'none', border: 'none', color: '#ff3355', cursor: 'pointer', fontSize: 14, padding: 0, lineHeight: 1 }}>x</button>
        </div>
      )}
      {/* Toolbar */}
      <div style={{ position: 'absolute', bottom: micError ? 38 : 6, right: 8, display: 'flex', gap: 6, alignItems: 'center' }}>
        {rewriteError && <span style={{ fontSize: 10, color: rewriteError === 'via Claude' ? 'var(--accent)' : 'var(--red)' }}>{rewriteError}</span>}
        {showAiRewrite && (
          <button onClick={handleRewrite} disabled={isRewriting || !value.trim()}
            style={{ ...btnBase, color: isRewriting ? 'var(--text3)' : 'var(--accent)', borderColor: isRewriting ? 'var(--border)' : 'rgba(0,212,255,0.3)' }}
            title="AI rewrite (local qwen3 or Claude Haiku fallback)">
            {isRewriting ? '\u27F3 ...' : '\u2726 AI'}
          </button>
        )}
        {showMic && (
          <button onClick={isListening ? stopMic : startMic}
            style={{
              ...btnBase,
              color: isListening ? '#ff3355' : 'var(--text3)',
              borderColor: isListening ? 'rgba(255,51,85,0.6)' : 'rgba(255,255,255,0.15)',
              background: isListening ? 'rgba(255,51,85,0.1)' : 'transparent',
            }}
            title={isListening ? 'Stop dictation' : 'Start dictation (Chrome, HTTPS required)'}>
            {isListening ? '\u23F9 Stop' : '\uD83C\uDFA4 Mic'}
          </button>
        )}
      </div>
      <style>{`@keyframes smarttextarea-pulse {
        0%, 100% { border-color: #ff3355; box-shadow: 0 0 0 0 rgba(255,51,85,0.3); }
        50% { border-color: #ff6688; box-shadow: 0 0 8px 2px rgba(255,51,85,0.15); }
      }`}</style>
    </div>
  )
}
