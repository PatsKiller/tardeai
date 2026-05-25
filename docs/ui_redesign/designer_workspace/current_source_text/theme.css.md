# Source Export: theme.css

- **Original path:** apps/command-center-v2/src/theme.css
- **Git branch:** main
- **Git commit:** d3fefdb9bd7af34f2ec2a6b0a31d89f24dbc8421
- **Export timestamp:** 2026-05-25T11:37:46-04:00
- **SHA256:** b06fa055902104842a75d2d519319d7bf833d77d294164f13b17128084e0e1b9
- **File size:** 4499 bytes
- **Exists:** YES

```css
:root {
  --bg0: #0a0d12;
  --bg1: #10141c;
  --bg2: #151a24;
  --bg3: #1b2230;
  --bg-card: #121921;
  --border: #212d3f;
  --border-subtle: #1a2233;
  --border-hover: #2c3a52;
  --text0: #eef2f8;
  --text1: #c4cdd8;
  --text2: #8a95a8;
  --text3: #586578;
  --accent: #4a90f4;
  --accent-bright: #6aabff;
  --accent-dim: rgba(74,144,244,.10);
  --green: #0ecb81;
  --green-dim: rgba(14,203,129,.08);
  --red: #f6465d;
  --red-dim: rgba(246,70,93,.08);
  --amber: #f0b90b;
  --amber-dim: rgba(240,185,11,.08);
  --purple: #a78bfa;
  --mono: 'SF Mono', 'Cascadia Code', 'JetBrains Mono', 'Fira Code', Consolas, monospace;
  --sans: -apple-system, BlinkMacSystemFont, 'Inter', 'Segoe UI', system-ui, sans-serif;
  --radius: 6px;
  --radius-md: 10px;
  --radius-lg: 12px;
  --shadow-sm: 0 2px 8px rgba(0,0,0,.2);
  --shadow-md: 0 4px 16px rgba(0,0,0,.3);
  --transition: 120ms ease;
  --gap-sm: 8px;
  --gap-md: 12px;
  --gap-lg: 16px;
}

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

html, body, #root {
  min-height: 100vh;
  background: var(--bg0);
  color: var(--text0);
  font-family: var(--mono);
  font-size: 12px;
  line-height: 1.45;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

a { color: var(--accent); text-decoration: none; transition: color var(--transition); }
a:hover { color: var(--accent-bright); }

button { font-family: var(--mono); }

::selection { background: var(--accent-dim); color: var(--text0); }

::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--border-hover); }

@keyframes tooltipFadeIn {
  from { opacity: 0; transform: translateX(-50%) translateY(4px); }
  to { opacity: 1; transform: translateX(-50%) translateY(0); }
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

@keyframes shimmer {
  0% { background-position: -200% 0; }
  100% { background-position: 200% 0; }
}

@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

/* ── Mobile responsive ── */
@media (max-width: 767px) {
  button, a, [role="button"], [role="tab"] { min-height: 44px; }
  input, select, textarea { font-size: 16px !important; }
  #root { overflow-x: hidden; }

  /* Force ALL multi-column grids to 2-col on phone */
  [style*="grid-template-columns: repeat(3"] { grid-template-columns: 1fr 1fr !important; }
  [style*="grid-template-columns: repeat(4"] { grid-template-columns: 1fr 1fr !important; }
  [style*="grid-template-columns: repeat(5"] { grid-template-columns: 1fr 1fr !important; }
  [style*="grid-template-columns: repeat(6"] { grid-template-columns: 1fr 1fr !important; }
  [style*="grid-template-columns: repeat(7"] { grid-template-columns: 1fr 1fr !important; }
  [style*="grid-template-columns: repeat(8"] { grid-template-columns: 1fr 1fr !important; }
  /* Explicit multi-column patterns */
  [style*="grid-template-columns: 1fr 1fr 1fr 1fr"] { grid-template-columns: 1fr 1fr !important; }
  [style*="grid-template-columns: 1fr 1fr 1fr"] { grid-template-columns: 1fr 1fr !important; }
  /* Two-pane layouts to single column */
  [style*="grid-template-columns: 1.15fr"] { grid-template-columns: 1fr !important; }
  [style*="grid-template-columns: 1fr 1fr;"] { grid-template-columns: 1fr !important; }
  [style*="grid-template-columns: 2fr 1fr"] { grid-template-columns: 1fr !important; }
  [style*="grid-template-columns: 1fr 2fr"] { grid-template-columns: 1fr !important; }
  [style*="grid-template-columns: 3fr 1fr"] { grid-template-columns: 1fr !important; }

  /* Tables scroll horizontally */
  table { display: block; overflow-x: auto; -webkit-overflow-scrolling: touch; }

  /* Prevent wide children from overflowing */
  main > * { max-width: 100% !important; overflow-x: hidden; }
  main > * > * { max-width: 100%; }
  pre, code { max-width: 100%; overflow-x: auto; word-break: break-word; }

  /* Reduce gaps on mobile */
  [style*="gap: 12px"] { gap: 8px !important; }
  [style*="gap: 16px"] { gap: 8px !important; }
  [style*="gap: 20px"] { gap: 10px !important; }
  [style*="gap: 24px"] { gap: 12px !important; }

  /* Reduce padding */
  [style*="padding: 16px"] { padding: 10px !important; }
  [style*="padding: 20px"] { padding: 12px !important; }
  [style*="padding: 24px"] { padding: 12px !important; }
}
```
