# Source Export: main.tsx

- **Original path:** apps/command-center-v2/src/main.tsx
- **Git branch:** main
- **Git commit:** d3fefdb9bd7af34f2ec2a6b0a31d89f24dbc8421
- **Export timestamp:** 2026-05-25T11:37:46-04:00
- **SHA256:** c085e3a342e43d17594eb84eb2b829fe849b9cecbbc36b0edf5dc200604100b7
- **File size:** 328 bytes
- **Exists:** YES

```tsx
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './theme.css'
import App from './App'
import { ToastProvider } from './components/ToastProvider'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ToastProvider>
      <App />
    </ToastProvider>
  </StrictMode>,
)
```
