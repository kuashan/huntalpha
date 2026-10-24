<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { API_BASE } from '../apiBase'
import { t } from '../i18n'

const props = defineProps({ symbol: { type: Object, required: true } })
const result = ref(null)
const state = ref('loading')
let controller
let generation = 0
let refreshTimer

const fields = {
  trend: 'tmTrend', bias: 'tmBias', volume: 'tmVolume',
  support: 'tmSupport', macd: 'tmMacd', rsi: 'tmRsi',
}
const errorText = computed(() => ({
  insufficient_history: 'tmInsufficient',
  unknown_symbol: 'tmUnsupported',
  unavailable: 'tmUnavailable',
  not_configured: 'tmUnavailable',
  invalid_result: 'tmUnavailable',
})[state.value] || 'tmUnavailable')
// Display the upstream trend-gated action, NOT only the score-band label.
const signalLabel = computed(() => ({
  '强烈买入': 'tmStrongBuy', '买入': 'tmBuy', '持有': 'tmHold',
  '观望': 'tmWatch', '卖出': 'tmSell', '强烈卖出': 'tmStrongSell',
})[result.value?.signal] || 'tmWatch')

async function refresh() {
  const code = String(props.symbol?.code || '')
  controller?.abort()
  const request = ++generation
  result.value = null
  if (!code) { state.value = 'unknown_symbol'; return }
  state.value = 'loading'
  controller = new AbortController()
  try {
    const reply = await fetch(`${API_BASE}/api/stock-technical-momentum/${encodeURIComponent(code)}/`, {
      credentials: 'include', cache: 'no-store', signal: controller.signal,
    })
    const data = await reply.json()
    if (request !== generation || controller.signal.aborted) return
    if (!reply.ok) { state.value = data?.status || 'unavailable'; return }
    if (String(data.code || '').toUpperCase() !== code.toUpperCase() ||
        data.period !== '1d' || !Number.isInteger(data.score) ||
        data.score < 0 || data.score > 100 ||
        !Array.isArray(data.dimensions) || data.dimensions.length !== 6 ||
        !data.dimensions.every(x => fields[x?.key] && typeof x.detail === 'string' &&
          Number.isInteger(x.max_score) && x.max_score > 0)) {
      state.value = 'invalid_result'
      return
    }
    result.value = data
    state.value = 'ready'
  } catch (err) {
    if (request !== generation && err?.name === 'AbortError') return
    if (err?.name !== 'AbortError') state.value = 'unavailable'
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
  <section class="tm-panel" :aria-label="t('tmTitle')">
    <div class="tm-header">
      <div>
        <h2>{{ t('tmTitle') }}</h2>
        <small>{{ t('tmDaily') }} · {{ symbol?.name || symbol?.code }}</small>
      </div>
    </div>
    <div v-if="state === 'ready' && result" class="tm-content">
      <div class="tm-score">
        <strong>{{ result.score }}<small> / 100</small></strong>
        <span>{{ t(signalLabel) }}</span>
        <small>{{ t('tmAsOf') }} {{ result.date }} · {{ t(result.intraday ? 'tmIntraday' : 'tmClosed') }}</small>
        <div class="tm-meter" role="meter" :aria-valuenow="result.score" aria-valuemin="0" aria-valuemax="100" :aria-label="t('tmTitle')">
          <div :style="{ width: result.score + '%' }"></div>
        </div>
      </div>
      <div class="tm-factors">
        <div v-for="item in result.dimensions" :key="item.key" class="tm-factor">
          <span>{{ t(fields[item.key]) }} <small>/ {{ item.max_score }}</small></span>
          <b>{{ item.detail }}</b>
        </div>
      </div>
    </div>
    <p v-else role="status" class="tm-status">{{ state === 'loading' ? t('tmLoading') : t(errorText) }}</p>
  </section>
</template>

<style scoped>
.tm-panel{margin:15px 0;padding:17px;border:1px solid #26394b;border-radius:8px;background:#111d2b;color:#dbe7f1;min-width:0}
.tm-header{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}
.tm-header h2{margin:0 0 4px;font-size:15px;font-weight:600}
.tm-header small,.tm-score small,.tm-status{color:#94a7ba;font-size:11px}
.tm-content{margin-top:14px;display:grid;grid-template-columns:minmax(125px,1fr) minmax(160px,1.6fr);gap:15px}
.tm-score{display:flex;flex-direction:column;gap:7px}
.tm-score strong{font-size:32px;color:#e5f5f6;font-variant-numeric:tabular-nums}
.tm-score strong small{font-size:12px}
.tm-score > span{font-size:13px;font-weight:600}
.tm-meter{height:8px;width:100%;overflow:hidden;background:#293c4a;border-radius:10px}
.tm-meter > div{height:100%;background:linear-gradient(90deg,#df6670,#e6bd6c,#55c5a5);border-radius:10px}
.tm-factors{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;align-content:center}
.tm-factor{display:flex;flex-direction:column;gap:3px;min-width:0;border-bottom:1px solid #293b4b;padding-bottom:5px;font-size:11px}
.tm-factor span{color:#a8bbcc}.tm-factor small{color:#6e899d}.tm-factor b{color:#e0ecf5;font-variant-numeric:tabular-nums;overflow-wrap:anywhere;font-weight:500}
.tm-status{margin:14px 0 0}
@media(max-width:700px){.tm-content{grid-template-columns:1fr}}
</style>
