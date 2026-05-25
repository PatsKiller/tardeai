# Source Export: ToastProvider.tsx

- **Original path:** apps/command-center-v2/src/components/ToastProvider.tsx
- **Git branch:** main
- **Git commit:** d3fefdb9bd7af34f2ec2a6b0a31d89f24dbc8421
- **Export timestamp:** 2026-05-25T11:37:46-04:00
- **SHA256:** e5c7dddd8bb7954e8e02057022d411633e19936d8825261a357492f6f6bc6c24
- **File size:** 1879 bytes
- **Exists:** YES

```tsx
import React, { createContext, useContext, useState, useCallback } from 'react'

interface Toast {
  id: string
  message: string
  type: 'success' | 'error' | 'info'
}

interface ToastContextType {
  showToast: (message: string, type?: 'success' | 'error' | 'info', duration?: number) => void
}

const ToastContext = createContext<ToastContextType | undefined>(undefined)

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  const showToast = useCallback((message: string, type: 'success' | 'error' | 'info' = 'success', duration = 3000) => {
    const id = Date.now().toString()
    setToasts(prev => [...prev, { id, message, type }])
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), duration)
  }, [])

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}
      <div style={{ position: 'fixed', top: 16, right: 16, zIndex: 10000, display: 'flex', flexDirection: 'column', gap: 8 }}>
        {toasts.map(toast => {
          const colors = {
            success: { bg: 'var(--green)', color: '#000' },
            error: { bg: 'var(--red)', color: '#fff' },
            info: { bg: 'var(--accent)', color: '#000' },
          }
          const s = colors[toast.type]
          return (
            <div key={toast.id} style={{
              padding: '10px 18px', background: s.bg, color: s.color,
              fontWeight: 700, fontSize: 12, borderRadius: 8, fontFamily: 'var(--sans)',
              boxShadow: '0 4px 20px rgba(0,0,0,.4)', minWidth: 240,
            }}>
              {toast.message}
            </div>
          )
        })}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast() {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used within ToastProvider')
  return ctx
}
```
