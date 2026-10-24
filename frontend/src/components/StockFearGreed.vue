<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { API_BASE } from '../apiBase'
import { t } from '../i18n'

const props = defineProps({ symbol: { type: Object, required: true } })
const result = ref(null)
const state = ref('loading')
let generation = 0
let controller
let refreshTimer

const factorNames = {
  trend: 'fgTrend', momentum: 'fgMomentum', rsi: 'fgRsi',
  macd: 'fgMacd', drawdown: 'fgDrawdown',
  volatility: 'fgVolatility', mfi: 'fgMfi', bb_pct_b: 'fgBollinger',
}
const score = computed(() => result.value?.score)
const subscores = computed(() => Object.entries(result.value?.subscores || {})
  .filter(([key, value]) => factorNames[key] && typeof value === 'number' && Number.isFinite(value)))
const labels = {
  '极度恐惧': 'fgExtremeFear', '恐惧': 'fgFear', '中性': 'fgNeutral',
  '贪婪': 'fgGreed', '极度贪婪': 'fgExtremeGreed',
}
const sentiment = computed(() => t(labels[result.value?.label] || 'fgUnknown'))
const explanation = computed(() => ({
  not_configured: 'fgNotConfigured',
  unsupported_symbol: 'fgUnsupported',
  no_score: 'fgNoScore',
  unknown_symbol: 'fgUnsupported',
  upstream_unavailable: 'fgUnavailable',
  invalid_response: 'fgUnavailable',
  invalid_configuration: 'fgNotConfigured',
  unavailable: 'fgUnavailable',
})[state.value] || 'fgUnavailable')

async function refresh() {
  const code = String(props.symbol?.code || '')
  controller?.abort()
  const current = ++generation
  if (!code) {
    result.value = null
    state.value = 'unsupported_symbol'
    return
  }
  controller = new AbortController()
  result.value = null
  state.value = 'loading'
  try {
    const response = await fetch(`${API_BASE}/api/stock-fear-greed/${encodeURIComponent(code)}/`, {
      credentials: 'include',
      cache: 'no-store',
      signal: controller.signal,
    })
    const data = await response.json()
    if (current !== generation || controller.signal.aborted) return
    if (!response.ok) {
      state.value = data.status || 'unavailable'
      return
    }
    if (String(data.code).toUpperCase() !== code.toUpperCase() ||
        data.period !== '1d' || typeof data.score !== 'number' ||
        !Number.isFinite(data.score) || data.score < 0 || data.score > 100) {
      state.value = 'invalid_response'
      return
    }
    result.value = data
    state.value = 'ready'
  } catch (error) {
    if (current !== generation || error?.name === 'AbortError') return
    state.value = 'unavailable'
  }
}

watch(() => props.symbol?.code, () => { void refresh() }, { immediate: true })
onMounted(() => {
  refreshTimer = window.setInterval(() => {
    if (!document.hidden && props.symbol?.code) void refresh()
  }, 300000)
})
onBeforeUnmount(() => {
  generation += 1
  controller?.abort()
  window.clearInterval(refreshTimer)
})
</script>

<template>
  <section class="fg-panel" :aria-label="t('fgTitle')">
    <div class="fg-heading">
      <div>
        <h2>{{ t('fgTitle') }}</h2>
        <small>{{ t('fgDaily') }} · {{ symbol?.name || symbol?.code }}</small>
      </div>
    </div>
    <div v-if="state === 'ready' && result" class="fg-content">
      <div class="fg-score">
        <strong>{{ score.toFixed(1) }}<small> / 100</small></strong>
        <span>{{ sentiment }}</span>
        <small>{{ t('fgAsOf') }} {{ result.date }}</small>
        <div class="fg-meter" role="meter" :aria-label="t('fgTitle')" :aria-valuenow="score" aria-valuemin="0" aria-valuemax="100">
          <div :style="{ width: score + '%' }"></div>
        </div>
      </div>
      <div class="fg-factors">
        <div v-for="[key, value] in subscores" :key="key" class="fg-factor">
          <span>{{ t(factorNames[key]) }}</span><b>{{ value.toFixed(1) }}</b>
        </div>
      </div>
    </div>
    <p v-else role="status" class="fg-status">
      {{ state === 'loading' ? t('fgLoading') : t(explanation) }}
    </p>
  </section>
</template>

<style scoped>
.fg-panel { margin: 15px 0; padding: 17px; border: 1px solid #26394b; border-radius: 8px; background: #111d2b; color: #dbe7f1; }
.fg-heading { display:flex; align-items: flex-start; justify-content:space-between; gap:12px; }
.fg-heading h2 { font-size: 15px; margin:0 0 4px; font-weight:600; }
.fg-heading small,.fg-score small,.fg-status { font-size:11px; color:#94a7ba; }
.fg-content { margin-top:14px; display:grid; grid-template-columns:minmax(170px,1fr) minmax(180px,2fr); gap:18px; }
.fg-score { display:flex; flex-direction:column; gap:7px; }
.fg-score strong { font-size:32px; color:#e5f5f6; font-variant-numeric:tabular-nums; }
.fg-score strong small { font-size:12px; }
.fg-score > span { font-size:13px; font-weight:600; }
.fg-meter { height:8px; width:100%; overflow:hidden; background:#293c4a; border-radius:10px; }
.fg-meter > div { height:100%; background:linear-gradient(90deg,#df6670,#e6bd6c,#55c5a5); border-radius:10px; }
.fg-factors { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; align-content:center; }
.fg-factor { display:flex; gap:10px; justify-content:space-between; font-size:11px; min-width:0; border-bottom:1px solid #293b4b; padding-bottom:5px; }
.fg-factor span { color:#a8bbcc; }.fg-factor b { color:#e0ecf5; font-variant-numeric:tabular-nums; }
.fg-status { margin:14px 0 0; }
@media(max-width:700px) { .fg-content { grid-template-columns:1fr; } }
</style>
