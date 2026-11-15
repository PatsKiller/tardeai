// Nav icons, ported verbatim from the v02 reference `icons` map (static constants, no user input).
const ICONS: Record<string, string> = {
  home: '<path d="m3 10 9-7 9 7v10H6V10m3 10v-7h6v7"/>',
  portfolio: '<rect x="3" y="7" width="18" height="14" rx="2"/><path d="M8 7V3h8v4M3 12h18m-10 0v3h2v-3"/>',
  watch: '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
  protection: '<path d="m12 2 8 4v6c0 5-8 10-8 10S4 17 4 12V6Z"/><path d="m8 12 3 3 5-6"/>',
  reposition: '<path d="M3 7h17l-5-5M21 17H4l5 5M20 7l-5 5M4 17l5-5"/>',
  trade: '<path d="M3 20V4m0 16h18M6 15l5-5 4 3 6-8"/>',
  intel: '<path d="M3 4h7l2 2 2-2h7v16h-7l-2 2-2-2H3Zm9 2v16"/>',
  ops: '<rect x="3" y="3" width="18" height="18" rx="3"/><path d="M6 13h3l2-6 3 10 2-4h3"/>',
}

export function Icon({ name }: { name: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round"
      aria-hidden="true" dangerouslySetInnerHTML={{ __html: ICONS[name] ?? ICONS.home }} />
  )
}
