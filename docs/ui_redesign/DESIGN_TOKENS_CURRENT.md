# Design Tokens -- Current State

Status:      HISTORICAL
as_of:       2026-05-25T10:45:00-04:00
Measured at: efcc51365 / not measured

Generated: 2026-05-25
Source: `apps/command-center-v2/src/theme.css`

---

## Color Palette

### Backgrounds
| Token | Value | Usage |
|-------|-------|-------|
| `--bg0` | `#0a0d12` | Root background, darkest |
| `--bg1` | `#10141c` | Secondary background |
| `--bg2` | `#151a24` | Card/panel background |
| `--bg3` | `#1b2230` | Hover/active background |
| `--bg-card` | `#121921` | Card-specific background |

### Borders
| Token | Value | Usage |
|-------|-------|-------|
| `--border` | `#212d3f` | Standard border |
| `--border-subtle` | `#1a2233` | Subtle dividers |
| `--border-hover` | `#2c3a52` | Hover state border |

### Text
| Token | Value | Usage |
|-------|-------|-------|
| `--text0` | `#eef2f8` | Primary text (headings) |
| `--text1` | `#c4cdd8` | Secondary text (body) |
| `--text2` | `#8a95a8` | Tertiary text (labels) |
| `--text3` | `#586578` | Quaternary (muted, nav inactive) |

### Semantic Colors
| Token | Value | Usage |
|-------|-------|-------|
| `--accent` | `#4a90f4` | Primary accent (links, buttons) |
| `--accent-bright` | `#6aabff` | Active nav, bright accent |
| `--accent-dim` | `rgba(74,144,244,.10)` | Selection, active backgrounds |
| `--green` | `#0ecb81` | Positive values, live dot |
| `--green-dim` | `rgba(14,203,129,.08)` | Green tinted backgrounds |
| `--red` | `#f6465d` | Negative values, errors |
| `--red-dim` | `rgba(246,70,93,.08)` | Red tinted backgrounds |
| `--amber` | `#f0b90b` | Warnings, pending |
| `--amber-dim` | `rgba(240,185,11,.08)` | Amber tinted backgrounds |
| `--purple` | `#a78bfa` | Special/rare use |

## Typography

### Font Stacks
| Token | Value | Usage |
|-------|-------|-------|
| `--mono` | SF Mono, Cascadia Code, JetBrains Mono, Fira Code, Consolas, monospace | Default body font (yes, monospace is the body font) |
| `--sans` | -apple-system, BlinkMacSystemFont, Inter, Segoe UI, system-ui, sans-serif | Nav labels, brand, metric labels |

### Font Sizes (observed in components)
| Size | Usage |
|------|-------|
| 9px | Metric labels (uppercase), nav group labels, tiny buttons |
| 10px | Utility buttons, small labels |
| 11px | Nav links, dropdown items, body text |
| 12px | Root font-size, metric values |
| 13px | Drawer links, mobile nav |
| 14px | Brand text |
| 16px | 404 page heading |

### Line Height
- Root: 1.45

## Spacing

| Token | Value | Usage |
|-------|-------|-------|
| `--gap-sm` | 8px | Small gaps |
| `--gap-md` | 12px | Medium gaps |
| `--gap-lg` | 16px | Large gaps |

## Radii

| Token | Value | Usage |
|-------|-------|-------|
| `--radius` | 6px | Default border radius |
| `--radius-md` | 10px | Medium radius |
| `--radius-lg` | 12px | Large radius (dropdowns, panels) |

## Shadows

| Token | Value | Usage |
|-------|-------|-------|
| `--shadow-sm` | 0 2px 8px rgba(0,0,0,.2) | Small shadow |
| `--shadow-md` | 0 4px 16px rgba(0,0,0,.3) | Medium shadow (dropdowns) |

## Transitions

| Token | Value | Usage |
|-------|-------|-------|
| `--transition` | 120ms ease | Default transition |

## Animations

| Name | Purpose |
|------|---------|
| `tooltipFadeIn` | Tooltip entrance |
| `pulse` | Pulsing opacity |
| `shimmer` | Loading shimmer |
| `fadeInUp` | Content entrance |

## Responsive Breakpoints

| Breakpoint | Target |
|-----------|--------|
| `max-width: 767px` | Mobile |
| `768px - 1023px` | Tablet |
| `max-width: 1400px` | Compact desktop |
| `1400px+` | Full desktop |

## Shell Layout
- Header: sticky, `rgba(8,12,18,0.97)` with `backdrop-filter: blur(12px)`
- Tape grid: `240px + repeat(8, minmax(92px, auto)) + auto + auto`
- Main: `padding: 20px 22px 32px`, `max-width: 1400px`
- Mobile drawer: 280px wide, slide from left

## Design Characteristics
- **Dark theme only** -- no light mode
- **Monospace-first** -- body text is monospace (terminal/trading aesthetic)
- **Sans-serif for labels** -- metric labels and nav use system sans-serif
- **Binance-inspired palette** -- green (#0ecb81), red (#f6465d), amber (#f0b90b) match Binance colors
- **Minimal shadows** -- mostly flat with subtle borders
- **5px scrollbar** -- thin, dark track

## Notes for Redesign
- No CSS variables for font sizes -- all hardcoded in components
- No spacing scale token system -- gaps and paddings vary
- Color usage is inconsistent in page components (some use tokens, some use hardcoded hex)
- The `--bg-card` token exists but most pages use `--bg2` directly
