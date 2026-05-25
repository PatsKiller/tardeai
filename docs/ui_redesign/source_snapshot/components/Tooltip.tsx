import { useState, useRef, type ReactNode, type CSSProperties } from 'react'

interface TooltipProps {
  content: string | ReactNode
  children: ReactNode
  position?: 'top' | 'bottom' | 'left' | 'right'
  delay?: number
}

export default function Tooltip({ content, children, position = 'top', delay = 200 }: TooltipProps) {
  const [visible, setVisible] = useState(false)
  const timeout = useRef<ReturnType<typeof setTimeout> | null>(null)

  const show = () => { timeout.current = setTimeout(() => setVisible(true), delay) }
  const hide = () => { if (timeout.current) clearTimeout(timeout.current); setVisible(false) }

  const posStyle: CSSProperties = position === 'top'
    ? { bottom: '100%', left: '50%', transform: 'translateX(-50%)', marginBottom: 6 }
    : position === 'bottom'
    ? { top: '100%', left: '50%', transform: 'translateX(-50%)', marginTop: 6 }
    : position === 'left'
    ? { right: '100%', top: '50%', transform: 'translateY(-50%)', marginRight: 6 }
    : { left: '100%', top: '50%', transform: 'translateY(-50%)', marginLeft: 6 }

  return (
    <div style={{ position: 'relative', display: 'inline-flex' }} onMouseEnter={show} onMouseLeave={hide}>
      {children}
      {visible && (
        <div style={{
          position: 'absolute', ...posStyle, zIndex: 100,
          padding: '8px 12px', borderRadius: 8,
          background: 'rgba(12, 16, 24, 0.97)', backdropFilter: 'blur(8px)',
          border: '1px solid rgba(74,144,244,0.2)',
          boxShadow: '0 8px 24px rgba(0,0,0,.6)',
          fontSize: 10, color: 'var(--text1)', lineHeight: 1.5,
          whiteSpace: 'nowrap', fontFamily: 'var(--sans)',
          pointerEvents: 'none',
          animation: 'tooltipFadeIn 150ms ease-out',
        }}>
          {content}
        </div>
      )}
    </div>
  )
}
