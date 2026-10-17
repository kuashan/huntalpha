import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const load = relative => readFileSync(new URL(relative, import.meta.url), 'utf8')

const consumers = [
  './App.vue',
  './components/AccountPopover.vue',
  './components/PersonalCenter.vue',
  './components/AuthGate.vue',
  './components/AiAnalysis.vue',
  './components/IndicatorManager.vue',
  './components/MarketChart.vue',
]

function configuredBase(production, developmentUrl) {
  // Evaluate just this pure configuration assignment using two explicit Vite
  // build-time values; no browser/session/network is required.
  const expression = load('./apiBase.js')
    .split('export const API_BASE = ', 2)[1]
    .replaceAll('import.meta.env.PROD', JSON.stringify(production))
    .replaceAll('import.meta.env.VITE_API_BASE_URL', JSON.stringify(developmentUrl))
  return Function('return (' + expression + ')')()
}

test('production API remains same-origin regardless of local override', () => {
  assert.equal(configuredBase(true, 'http://127.0.0.1:8003'), '')
  assert.equal(configuredBase(true, 'https://another-domain.example'), '')
  assert.equal(configuredBase(false, ''), '')
  assert.equal(configuredBase(false, 'http://127.0.0.1:8003/'), 'http://127.0.0.1:8003')
})

test('all seven website API consumers use shared base, never hardcoded loopback', () => {
  for (const file of consumers) {
    const source = load(file)
    assert.match(source, /import \{ API_BASE \} from ['"](?:\.\/|\.\.\/)apiBase['"]/, file)
    assert.match(source, /\$\{API_BASE\}\/api\//, file)
    assert.doesNotMatch(source, /https?:\/\/(?:127\.0\.0\.1|localhost):8003/, file)
  }
})

test('Vite local server proxies relative /api requests, not production JS', () => {
  const source = load('../vite.config.js')
  assert.match(source, /['"]\/api['"]\s*:/)
  assert.match(source, /target:\s*['"]http:\/\/127\.0\.0\.1:8003['"]/)
})
