import { BRAND } from '../../lib/watchTokens'

// v8.5c — tiny inline provider marks for the oversight pills (simplified brand
// shapes, colored from the BRAND tokens; no external assets, design-guard clean).

export function ClaudeMark({ size = 11 }: { size?: number }) {
  // the Claude spark — 8-ray starburst
  const c = size / 2
  const rays = [0, 45, 90, 135].map(a => {
    const r = (a * Math.PI) / 180
    return `M${c - c * Math.cos(r)} ${c - c * Math.sin(r)} L${c + c * Math.cos(r)} ${c + c * Math.sin(r)}`
  }).join(' ')
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} style={{ display: 'inline', verticalAlign: '-1px' }}>
      <path d={rays} stroke={BRAND.anthropic} strokeWidth={size / 7} strokeLinecap="round" fill="none" />
    </svg>
  )
}

export function OpenAiMark({ size = 11 }: { size?: number }) {
  // simplified hex knot — two rotated triangles
  const c = size / 2, r = c - 0.5
  const tri = (off: number) => Array.from({ length: 3 }, (_, i) => {
    const a = ((i * 120 + off) * Math.PI) / 180
    return `${c + r * Math.sin(a)},${c - r * Math.cos(a)}`
  }).join(' ')
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} style={{ display: 'inline', verticalAlign: '-1px' }}>
      <polygon points={tri(0)} stroke={BRAND.openai} strokeWidth={size / 9} fill="none" strokeLinejoin="round" />
      <polygon points={tri(60)} stroke={BRAND.openai} strokeWidth={size / 9} fill="none" strokeLinejoin="round" />
    </svg>
  )
}

export function XaiMark({ size = 11 }: { size?: number }) {
  // the xAI slashed X
  const s = size
  return (
    <svg width={s} height={s} viewBox={`0 0 ${s} ${s}`} style={{ display: 'inline', verticalAlign: '-1px' }}>
      <path d={`M${s * 0.1} ${s * 0.1} L${s * 0.9} ${s * 0.9} M${s * 0.9} ${s * 0.05} L${s * 0.55} ${s * 0.5} M${s * 0.1} ${s * 0.95} L${s * 0.42} ${s * 0.58}`}
        stroke={BRAND.xai} strokeWidth={s / 7} strokeLinecap="round" fill="none" />
    </svg>
  )
}

export function DeepSeekMark({ size = 11 }: { size?: number }) {
  const s = size
  const cx = s / 2, cy = s / 2, r = s * 0.4
  return (
    <svg width={s} height={s} viewBox={`0 0 ${s} ${s}`} style={{ display: 'inline', verticalAlign: '-1px' }}>
      <circle cx={cx} cy={cy} r={r} stroke={BRAND.deepseek} strokeWidth={s / 7} fill="none" />
      <path d={`M${s * 0.15} ${cy} L${s * 0.85} ${cy} M${cx} ${s * 0.15} L${cx} ${s * 0.85}`}
        stroke={BRAND.deepseek} strokeWidth={s / 8} strokeLinecap="round" fill="none" />
    </svg>
  )
}

export function ProviderMark({ provider, size = 11 }: { provider: string; size?: number }) {
  if (provider === 'anthropic') return <ClaudeMark size={size} />
  if (provider === 'openai') return <OpenAiMark size={size} />
  if (provider === 'xai') return <XaiMark size={size} />
  if (provider === 'deepseek') return <DeepSeekMark size={size} />
  return <XaiMark size={size} />
}
