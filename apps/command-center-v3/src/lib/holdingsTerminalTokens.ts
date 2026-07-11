/** Bloomberg Terminal–inspired tokens for Portfolio Holdings table (v2). */
export const BB = {
  bg: '#0a0c10',
  bgRow: '#0f1218',
  bgRowAlt: '#12161e',
  bgRowHover: '#181d28',
  border: '#1e2430',
  borderSubtle: '#151a22',
  text0: '#e8eaf0',
  text1: '#c4c8d8',
  text2: '#9098b0',
  text3: '#5a6180',
  amber: '#ffb000',
  amberDim: 'rgba(255, 176, 0, 0.14)',
  green: '#3dca5c',
  greenDim: 'rgba(61, 202, 92, 0.12)',
  red: '#ff433d',
  redDim: 'rgba(255, 67, 61, 0.12)',
  orange: '#f59e0b',
  mono: "'JetBrains Mono', 'Consolas', monospace",
  rowH: 36,
  fontXs: 9,
  fontSm: 10,
  fontMd: 11,
} as const

export type StopStatusTone = 'stable' | 'concern' | 'action'

export function stopStatusColor(s: StopStatusTone): string {
  return s === 'stable' ? BB.green : s === 'concern' ? BB.amber : BB.red
}