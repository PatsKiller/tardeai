# New Component: ActionButton.tsx

Status:      HISTORICAL
as_of:       2026-05-25T13:05:19-04:00
Measured at: efcc51365 / not measured

- **Target repo path:** apps/command-center-v2/src/components/ActionButton.tsx
- **Design purpose:** Replace inline `<button style={{...}}>` elements across pages with a shared component. Supports primary/secondary/danger/ghost variants with loading and disabled states. Safety-critical: does not execute anything itself — just renders a button with consistent styling.

## Acceptance Checklist

- [ ] All 5 variants render correctly
- [ ] Loading state shows spinner
- [ ] Disabled state prevents click and dims
- [ ] Uses CSS variables from theme.css
- [ ] No new dependencies
- [ ] Does not execute trading/approval actions itself

```tsx
import type { CSSProperties, ReactNode, MouseEvent } from 'react'

type Variant = 'primary' | 'secondary' | 'danger' | 'ghost' | 'disabled'

const VARIANT_STYLES: Record<Variant, { bg: string; color: string; border: string; hoverBg?: string }> = {
  primary:   { bg: 'var(--accent)',     color: '#fff',          border: 'transparent' },
  secondary: { bg: 'var(--bg2)',        color: 'var(--text1)',  border: 'var(--border)' },
  danger:    { bg: 'var(--red-dim)',    color: 'var(--red)',    border: 'rgba(246,70,93,.3)' },
  ghost:     { bg: 'transparent',       color: 'var(--text2)',  border: 'transparent' },
  disabled:  { bg: 'var(--bg3)',        color: 'var(--text3)',  border: 'var(--border)' },
}

interface ActionButtonProps {
  variant?: Variant
  size?: 'sm' | 'md' | 'lg'
  loading?: boolean
  disabled?: boolean
  title?: string
  onClick?: (e: MouseEvent<HTMLButtonElement>) => void
  children: ReactNode
  style?: CSSProperties
}

export function ActionButton({
  variant = 'secondary',
  size = 'sm',
  loading = false,
  disabled = false,
  title,
  onClick,
  children,
  style,
}: ActionButtonProps) {
  const isDisabled = disabled || loading || variant === 'disabled'
  const effectiveVariant = isDisabled ? 'disabled' : variant
  const vs = VARIANT_STYLES[effectiveVariant]

  const sizeStyles: Record<string, CSSProperties> = {
    sm: { fontSize: 10, padding: '4px 10px' },
    md: { fontSize: 12, padding: '6px 14px' },
    lg: { fontSize: 13, padding: '8px 18px' },
  }

  const base: CSSProperties = {
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 5,
    borderRadius: 'var(--radius)',
    fontWeight: 600,
    fontFamily: 'var(--sans)',
    cursor: isDisabled ? 'not-allowed' : 'pointer',
    border: `1px solid ${vs.border}`,
    background: vs.bg,
    color: vs.color,
    opacity: isDisabled ? .5 : 1,
    transition: 'var(--transition)',
    whiteSpace: 'nowrap',
    ...sizeStyles[size],
    ...style,
  }

  return (
    <button
      style={base}
      onClick={isDisabled ? undefined : onClick}
      disabled={isDisabled}
      title={title}
    >
      {loading && <span style={{ width: 12, height: 12, border: '2px solid currentColor', borderTopColor: 'transparent', borderRadius: '50%', animation: 'spin .6s linear infinite', display: 'inline-block' }} />}
      {children}
    </button>
  )
}

export default ActionButton
```
