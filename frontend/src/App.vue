<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import MarketChart from './components/MarketChart.vue'
import IndicatorManager from './components/IndicatorManager.vue'
import AuthGate from './components/AuthGate.vue'
import AiAnalysis from './components/AiAnalysis.vue'
import { commonIndicators, markets } from './data/marketData'
import { languages, locale, setLocale, t } from './i18n'
const API_BASE = 'http://127.0.0.1:8003'
const market = ref(markets[0]); const query = ref(''); const symbols = ref([]); const selected = ref(null); const period = ref('日线'); const mainInstalled = ref([]); const subInstalled = ref([]); const manager = ref(null)
const user = ref(null); const visitor = ref(false); const checkingSession = ref(true); const quotes = ref({})
const catalogLoading = ref(false); const catalogError = ref(''); let symbolRequestVersion = 0; let quoteRequestVersion = 0; let searchTimer
const analysisCode = new URLSearchParams(window.location.search).get('analysis')
const analysisName = new URLSearchParams(window.location.search).get('name') || analysisCode
const analysisMarket = new URLSearchParams(window.location.search).get('market') || ''
const installedIndicators = computed(() => [...mainInstalled.value, ...subInstalled.value])
const list = computed(() => symbols.value)
const selectedQuote = computed(() => quotes.value[selected.value?.code] || { status: 'idle' })
const quoteData = computed(() => selectedQuote.value.status === 'ready' ? selectedQuote.value.data : null)
const quoteStatusText = computed(() => {
  if (selectedQuote.value.status === 'ready') return t('quoteSource')
  if (selectedQuote.value.status === 'loading' || selectedQuote.value.status === 'idle') return t('quoteLoading')
  return `${t('quoteUnavailable')}：${selectedQuote.value.error}`
})
const displayPrice = value => typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString(undefined, { maximumFractionDigits: 4 }) : '—'
const displayChange = value => typeof value === 'number' && Number.isFinite(value) ? `${value > 0 ? '+' : ''}${value}%` : '—'
const itemQuote = item => quotes.value[item.code]?.data
const itemQuoteError = item => quotes.value[item.code]?.error || ''
const trimCompact = value => value.toFixed(2).replace(/\.?(0+)$/, '')
const displayMarketCap = (value, currency) => {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—'
  const code = String(currency || '').toUpperCase()
  const suffix = code && code !== 'CNY' ? ' ' + code : ''
  const sign = value < 0 ? '-' : ''
  const amount = Math.abs(value)
  if (code === 'USD') {
    if (amount >= 1e12) return sign + trimCompact(amount / 1e12) + 'T' + suffix
    if (amount >= 1e9) return sign + trimCompact(amount / 1e9) + 'B' + suffix
    if (amount >= 1e6) return sign + trimCompact(amount / 1e6) + 'M' + suffix
  }
  if (amount >= 1e12) return sign + trimCompact(amount / 1e12) + '万亿' + suffix
  if (amount >= 1e8) return sign + trimCompact(amount / 1e8) + '亿' + suffix
  if (amount >= 1e4) return sign + trimCompact(amount / 1e4) + '万' + suffix
  return sign + amount.toLocaleString(undefined, { maximumFractionDigits: 2 }) + suffix
}
const displayMarketCapExact = (value, currency) => typeof value === 'number' && Number.isFinite(value) ? (value.toLocaleString(undefined, { maximumFractionDigits: 4 }) + ' ' + (currency || '')).trim() : '—'
const symbolTitle = item => [
  item.market_cap != null ? t('marketCap') + '：' + displayMarketCapExact(item.market_cap, item.market_cap_currency) : '',
  itemQuoteError(item),
].filter(Boolean).join(' · ') || item.name + ' · ' + item.code
const catalogStatusText = computed(() => catalogError.value || (catalogLoading.value ? t('catalogLoading') : list.value.length ? '' : query.value.trim() ? t('noSymbol') : t('catalogNotSynced')))
function switchMarket(item) { market.value = item; query.value = '' }
function addIndicator(item) { if (visitor.value && !item.visitor_available) return; const list = item.placement === 'main' ? mainInstalled : subInstalled; if (item.placement === 'sub' && !list.value.some(current => current.code === item.code) && list.value.length >= 3) return; if (!list.value.some(current => current.code === item.code)) list.value = [...list.value, item] }
function removeIndicator(item) { if (item.placement === 'main') mainInstalled.value = mainInstalled.value.filter(current => current.code !== item.code); else subInstalled.value = subInstalled.value.filter(current => current.code !== item.code) }
function authenticated(currentUser) { user.value = currentUser; visitor.value = Boolean(currentUser.visitor); if (window.location.search) window.history.replaceState({}, '', '/') }
function toggleCommon(item) { const active = (item.placement === 'main' ? mainInstalled : subInstalled).value.some(current => current.code === item.code); if (active) removeIndicator(item); else addIndicator(item) }
function openAiAnalysis() { const url = `/?analysis=${encodeURIComponent(selected.value.code)}&name=${encodeURIComponent(selected.value.name)}&market=${encodeURIComponent(market.value.name)}`; window.open(url, '_blank', 'noopener') }
async function requestAiAccess() { if (!visitor.value) return openAiAnalysis(); await fetch(`${API_BASE}/api/auth/logout/`, { method: 'POST', credentials: 'include' }); user.value = null; visitor.value = false; window.location.assign('/?register=1') }
function backToTerminal() { window.location.assign('/') }
async function signOut() { await fetch(`${API_BASE}/api/auth/logout/`, { method: 'POST', credentials: 'include' }); user.value = null; visitor.value = false; mainInstalled.value = []; subInstalled.value = []; symbols.value = []; selected.value = null }
async function refreshQuotes(items) {
  const version = ++quoteRequestVersion
  const next = Object.fromEntries(items.map(item => [item.code, { status: 'loading' }]))
  quotes.value = next
  await Promise.all(items.map(async item => {
    try {
      const reply = await fetch(`${API_BASE}/api/quote/${encodeURIComponent(item.code)}/`, { credentials: 'include' })
      const payload = await reply.json()
      if (!reply.ok) throw new Error(payload.error || t('quoteUnavailable'))
      next[item.code] = { status: 'ready', data: payload }
    } catch (error) {
      next[item.code] = { status: 'error', error: error.message || t('quoteUnavailable') }
    }
  }))
  if (version === quoteRequestVersion) quotes.value = { ...next }
}
async function loadSymbols() {
  const version = ++symbolRequestVersion
  catalogLoading.value = true; catalogError.value = ''
  const search = query.value.trim()
  const endpoint = search ? 'symbols' : 'market-leaders'
  const params = new URLSearchParams({ limit: search ? '10' : '5', page: '1' })
  if (search) params.set('q', search)
  try {
    const reply = await fetch(`${API_BASE}/api/${endpoint}/${market.value.code}/?${params}`, { credentials: 'include' })
    const payload = await reply.json()
    if (!reply.ok) throw new Error(payload.error || t('catalogUnavailable'))
    if (version !== symbolRequestVersion) return
    const items = Array.isArray(payload.items) ? payload.items : []
    symbols.value = items
    selected.value = items.find(item => item.code === selected.value?.code) || items[0] || null
    if (user.value && items.length) refreshQuotes(items)
    else { quoteRequestVersion += 1; quotes.value = {} }
    if (!items.length && !search && payload.error) catalogError.value = payload.error
  } catch (error) {
    if (version !== symbolRequestVersion) return
    symbols.value = []; selected.value = null; quoteRequestVersion += 1; quotes.value = {}; catalogError.value = error.message || t('catalogUnavailable')
  } finally {
    if (version === symbolRequestVersion) catalogLoading.value = false
  }
}
watch(market, loadSymbols)
watch(query, () => { window.clearTimeout(searchTimer); searchTimer = window.setTimeout(loadSymbols, 280) })
watch(user, currentUser => {
  if (currentUser) loadSymbols()
  else { symbolRequestVersion += 1; quoteRequestVersion += 1; quotes.value = {}; symbols.value = []; selected.value = null }
})
onMounted(async () => { try { const reply = await fetch(`${API_BASE}/api/auth/session/`, { credentials: 'include' }); const data = await reply.json(); if (reply.ok && data.authenticated) { user.value = data.user; visitor.value = Boolean(data.visitor) } } catch {} finally { checkingSession.value = false } })
onBeforeUnmount(() => window.clearTimeout(searchTimer))
</script>
<template>
  <div v-if="checkingSession" class="boot-screen">QuantScope…</div>
  <AuthGate v-else-if="!user" @authenticated="authenticated" />
  <AiAnalysis v-else-if="analysisCode" :code="analysisCode" :name="analysisName" :market="analysisMarket" @back="backToTerminal" />
  <main v-else class="terminal">
    <header><div class="brand"><b>Q</b> QuantScope <small>{{ visitor ? t('visitor') : t('pro') }}</small></div><nav><a class="active">{{ t('market') }}</a><a>{{ t('watchlist') }}</a><a>{{ t('strategy') }}</a><a>{{ t('news') }}</a></nav><div class="feed">● {{ visitor ? t('visitorAi') : user.name }}</div><select class="terminal-language" :value="locale" @change="setLocale($event.target.value)"><option v-for="item in languages" :key="item.code" :value="item.code">{{ item.label }}</option></select><button class="logout" @click="signOut">{{ t('logout') }}</button></header>
    <section class="markets"><button v-for="item in markets" :key="item.code" :class="{active: market.code === item.code}" @click="switchMarket(item)"><strong>{{ item.name }}</strong><span>—</span><em class="unavailable">{{ t('marketUnavailable') }}</em></button></section>
    <div class="workspace"><aside><div class="aside-title">{{ t('marketList') }} <b>{{ market.name }}</b></div><label class="search">⌕ <input v-model="query" :placeholder="t('search')" /></label><div class="heads"><span>{{ t('nameCode') }}</span><span>{{ t('latest') }}</span><span>{{ t('change') }}</span></div><button v-for="item in list" :key="item.code" class="symbol" :class="{selected: selected?.code === item.code}" :title="symbolTitle(item)" :aria-label="symbolTitle(item)" @click="selected = item"><span class="symbol-name"><strong>{{ item.name }}</strong><small>{{ item.code }}</small><small v-if="item.market_cap != null" class="symbol-cap">{{ t('marketCap') }} {{ displayMarketCap(item.market_cap, item.market_cap_currency) }}</small></span><b>{{ displayPrice(itemQuote(item)?.price) }}</b><em :class="{down:itemQuote(item)?.change < 0}">{{ displayChange(itemQuote(item)?.change) }}</em></button><p v-if="catalogStatusText">{{ catalogStatusText }}</p></aside>
      <section class="content"><div class="security"><div><p>{{ market.name }} · {{ quoteStatusText }}</p><h1>{{ selected?.name || '—' }} <small>{{ selected?.code || '' }}</small><button v-if="selected && !selected.code.startsWith('CC.')" class="ai-button" @click="requestAiAccess">AI 分析</button></h1></div><div class="price"><strong>{{ displayPrice(quoteData?.price) }}</strong><span :class="{down:quoteData?.change < 0}">{{ displayChange(quoteData?.change) }}</span></div><dl><div><dt>{{ t('open') }}</dt><dd>{{ displayPrice(quoteData?.open) }}</dd></div><div><dt>{{ t('high') }}</dt><dd>{{ displayPrice(quoteData?.high) }}</dd></div><div><dt>{{ t('low') }}</dt><dd>{{ displayPrice(quoteData?.low) }}</dd></div></dl></div>
        <div class="toolbar"><div><button v-for="item in ['分时','1分','5分','15分','30分','60分','2小时','4小时','日线','周线','月线']" :key="item" :class="{active:period === item}" @click="period=item">{{ item }}</button></div><div class="common-tools"><button v-for="item in commonIndicators" :key="item.code" :class="{on:installedIndicators.some(current=>current.code===item.code)}" @click="toggleCommon(item)">{{item.name}}</button><button @click="manager.open()">{{ t('manager') }}</button></div></div>
        <div class="labels"><span>{{ t('main') }}{{ mainInstalled.map(item => item.name).join(' · ') || t('candle') }}</span></div><MarketChart v-if="selected" :symbol="selected" :period="period" :installed-indicators="installedIndicators" /><div v-else class="catalog-empty">{{ catalogStatusText }}</div><footer>{{ t('disclaimer') }}</footer>
      </section></div>
    <IndicatorManager ref="manager" :main="mainInstalled" :sub="subInstalled" :visitor="visitor" @add="addIndicator" @remove="removeIndicator" />
  </main>
</template>

<style scoped>
.markets{grid-template-columns:repeat(4,minmax(0,1fr))}
.markets em.unavailable{color:#8193a7;font-size:10px}
.heads,.symbol{grid-template-columns:minmax(0,1fr) 58px 58px}
.symbol{min-height:55px}.symbol-name{min-width:0}.symbol b,.symbol em{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.symbol-cap{color:#8ba2b3!important;font:9px/1.2 'DM Mono',monospace!important;letter-spacing:-.02em}
.catalog-empty{min-height:460px;display:grid;place-items:center;color:#8193a7;font-size:13px}
.toolbar{gap:8px}.common-tools{display:flex;justify-content:flex-end;flex-wrap:wrap}.common-tools button:last-child{margin-left:4px;border-left:1px solid #31465a;color:#b8cee0}
.terminal-language{border:1px solid #344b5c;border-radius:4px;background:#101d29;color:#c4d4df;padding:5px;font-size:11px}
.ai-button{margin-left:10px;border:1px solid #3ccca3;border-radius:4px;background:#10372f;color:#75e2c1;padding:5px 8px;font-size:11px;vertical-align:middle}
@media(max-width:800px){.markets{grid-template-columns:repeat(4,minmax(92px,1fr));overflow-x:auto}.markets button{padding:11px 10px}.markets strong{font-size:12px}.markets span{font-size:12px}}
</style>
