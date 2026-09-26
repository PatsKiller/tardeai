import { agentModelLabel, MODEL_NOT_REPORTED } from './agentModelLabel.ts'

function eq(a: unknown, b: unknown, msg: string) {
  if (a !== b) throw new Error(`FAIL ${msg}: ${String(a)} !== ${String(b)}`)
}
eq(agentModelLabel({ agent: 'alex' }), MODEL_NOT_REPORTED, 'no model field -> not reported (never a hardcoded model)')
eq(agentModelLabel(null), MODEL_NOT_REPORTED, 'missing row')
eq(agentModelLabel({ runtime_model: 'deepseek-v4' }), 'deepseek-v4', 'runtime_model wins')
eq(agentModelLabel({ model: '  qwen3:14b ' }), 'qwen3:14b', 'model trimmed')
eq(agentModelLabel({ model: '' }), MODEL_NOT_REPORTED, 'blank model')
console.log('agentModelLabel.test: ok')
