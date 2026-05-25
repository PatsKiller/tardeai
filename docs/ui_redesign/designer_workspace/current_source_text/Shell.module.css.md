# Source Export: Shell.module.css

- **Original path:** apps/command-center-v2/src/components/Shell.module.css
- **Git branch:** main
- **Git commit:** d3fefdb9bd7af34f2ec2a6b0a31d89f24dbc8421
- **Export timestamp:** 2026-05-25T11:38:05-04:00
- **SHA256:** ae81d4dee41d2b5921afb5c9ce8b2761fab4afd61825b53399a921d1d8fa4401
- **File size:** 6325 bytes
- **Exists:** YES

```css
.shell {
  min-height: 100vh;
  background: linear-gradient(180deg, #070b12 0%, #090d14 100%);
}

.header {
  position: sticky;
  top: 0;
  z-index: 40;
  background: rgba(8, 12, 18, 0.97);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--border);
  box-shadow: 0 1px 4px rgba(0,0,0,.3);
}

.tape {
  display: grid;
  grid-template-columns: 240px repeat(8, minmax(92px, auto)) auto auto;
  gap: 0;
  align-items: stretch;
  min-height: 56px;
}

.brandWrap,
.metric,
.live,
.utilityBtn {
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 8px 12px;
}

.brandWrap {
  flex-direction: row;
  align-items: center;
  gap: 8px;
}

.brandBolt {
  font-size: 15px;
}

.brand {
  font-family: var(--sans);
  font-size: 14px;
  font-weight: 800;
  letter-spacing: -0.3px;
  color: #fff;
}

.metricLabel {
  font-family: var(--sans);
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: .45px;
  color: var(--text2);
  font-weight: 500;
}

.metric {
  transition: background var(--transition);
}
.metric:hover {
  background: var(--bg3);
}
.metric:active {
  background: var(--bg2);
}

.metricValue {
  margin-top: 3px;
  font-size: 12px;
  color: var(--text0);
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.good { color: var(--green); }
.bad { color: var(--red); }

.live {
  flex-direction: row;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: var(--text1);
}

.dot {
  width: 8px;
  height: 8px;
  background: var(--green);
  border-radius: 999px;
  box-shadow: 0 0 8px rgba(14, 203, 129, 0.6);
}

.utilityBtn {
  appearance: none;
  background: transparent;
  color: var(--text2);
  font-family: var(--mono);
  font-size: 10px;
  cursor: pointer;
  transition: color var(--transition), background var(--transition);
}

.utilityBtn:hover {
  color: var(--text0);
  background: var(--bg3);
}

.navRow {
  position: relative;
  border-top: 1px solid var(--border-subtle);
  min-height: 44px;
  display: flex;
  align-items: center;
  overflow: visible;
}

.nav {
  display: flex;
  flex-wrap: wrap;
  padding: 0 12px;
  width: 100%;
  gap: 0;
}

.navLink {
  padding: 11px 14px;
  font-size: 11px;
  font-weight: 500;
  color: var(--text3);
  border-bottom: 2px solid transparent;
  white-space: nowrap;
  transition: color var(--transition);
}

.navLink:hover {
  color: var(--text0);
}

.active {
  color: var(--accent-bright);
  border-bottom-color: var(--accent-bright);
}

.utilityMenu {
  position: absolute;
  right: 12px;
  top: 44px;
  min-width: 220px;
  background: var(--bg2);
  border: 1px solid var(--border-hover);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-md);
  padding: 8px;
}

.utilityTitle {
  padding: 4px 6px 8px;
  font-family: var(--sans);
  font-size: 10px;
  color: var(--text3);
  text-transform: uppercase;
  letter-spacing: .4px;
}

.utilityLink {
  display: block;
  padding: 8px 10px;
  border-radius: var(--radius);
  color: var(--text1);
  font-size: 11px;
}
.utilityLink:hover { background: var(--bg3); }

.dropLink {
  display: flex;
  align-items: center;
  padding: 8px 12px;
  border-radius: 6px;
  color: var(--text1);
  font-size: 11px;
  white-space: nowrap;
  transition: background var(--transition);
}
.dropLink:hover { background: var(--bg3); }

.dropActive {
  display: flex;
  align-items: center;
  padding: 8px 12px;
  border-radius: 6px;
  color: var(--accent-bright);
  font-size: 11px;
  font-weight: 700;
  white-space: nowrap;
  background: rgba(74, 144, 244, 0.08);
}

.main {
  padding: 20px 22px 32px;
  max-width: 1400px;
}

/* Hamburger button — hidden on desktop */
.hamburger {
  display: none;
  appearance: none;
  background: transparent;
  border: none;
  color: var(--text1);
  padding: 8px;
  cursor: pointer;
  min-width: 44px;
  min-height: 44px;
  align-items: center;
  justify-content: center;
}

/* Drawer backdrop — mobile only */
.backdrop {
  display: none;
  position: fixed;
  inset: 0;
  z-index: 45;
  background: rgba(0,0,0,0.55);
}

/* Drawer panel — off-screen by default */
.drawer {
  position: fixed;
  top: 0;
  left: 0;
  bottom: 0;
  z-index: 50;
  width: 280px;
  background: var(--bg1);
  border-right: 1px solid var(--border);
  overflow-y: auto;
  transform: translateX(-100%);
  transition: transform 0.2s ease;
}
.drawerOpen {
  transform: translateX(0);
}

.drawerHeader {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border-bottom: 1px solid var(--border);
}

.drawerGroup {
  padding: 8px 0;
  border-bottom: 1px solid var(--border-subtle);
}

.drawerGroupLabel {
  padding: 6px 16px;
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: .5px;
  color: var(--text3);
  font-weight: 600;
}

.drawerLink {
  display: block;
  padding: 10px 16px;
  font-size: 13px;
  color: var(--text1);
  min-height: 44px;
  display: flex;
  align-items: center;
}
.drawerLink:hover { background: var(--bg3); }
.drawerLinkActive {
  display: flex;
  align-items: center;
  padding: 10px 16px;
  font-size: 13px;
  color: var(--accent-bright);
  font-weight: 700;
  background: rgba(74, 144, 244, 0.08);
  min-height: 44px;
}

@media (max-width: 1400px) {
  .tape {
    grid-template-columns: 220px repeat(4, minmax(92px, auto)) auto auto;
  }
  .metric:nth-child(n + 7):nth-child(-n + 9) {
    display: none;
  }
}

/* ── Mobile: < 768px ── */
@media (max-width: 767px) {
  .hamburger {
    display: flex;
  }
  .backdrop {
    display: block;
  }

  /* Collapse tape to brand + hamburger + portfolio + today only */
  .tape {
    grid-template-columns: auto 1fr 1fr auto;
    min-height: 48px;
  }
  .metric:nth-child(n + 5) { display: none; }
  .live { display: none; }
  .utilityBtn { display: none; }
  .brandWrap { padding: 6px 8px; }
  .brand { font-size: 12px; }

  /* Hide desktop nav row — use drawer instead */
  .navRow { display: none; }

  /* Reduce main padding */
  .main {
    padding: 12px 12px 24px;
  }
}

/* ── Tablet: 768–1023px ── */
@media (min-width: 768px) and (max-width: 1023px) {
  .tape {
    grid-template-columns: 200px repeat(5, minmax(80px, auto)) auto;
  }
  .metric:nth-child(n + 8) { display: none; }
  .main {
    padding: 16px 16px 28px;
  }
}
```
