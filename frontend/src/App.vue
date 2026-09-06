<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import MarketChart from './components/MarketChart.vue'
import IndicatorManager from './components/IndicatorManager.vue'
import AuthGate from './components/AuthGate.vue'
import AiAnalysis from './components/AiAnalysis.vue'
import HuntAlphaLogo from './components/HuntAlphaLogo.vue'
import AccountPopover from './components/AccountPopover.vue'
import PersonalCenter from './components/PersonalCenter.vue'
import { commonIndicators, markets } from './data/marketData'
import { languages, locale, setLocale, t } from './i18n'
const API_BASE = 'http://127.0.0.1:8003'
const market = ref(markets[0]); const query = ref(''); const symbols = ref([]); const selected = ref(null); const period = ref('日线'); const mainInstalled = ref([]); const subInstalled = ref([]); const manager = ref(null)
const user = ref(null); const visitor = ref(false); const checkingSession = ref(true); const quotes = ref({})
const priceColorMode = ref('cn'); let initialPreferencesApplied = false
const accountSections = ['overview', 'profile', 'membership', 'security', 'preferences']
const routeFromLocation = () => {
  const path = window.location.pathname.replace(/\/+$/, '') || '/'
  const section = new URLSearchParams(window.location.search).get('section')
  return { page: path === '/account' ? 'account' : 'terminal', section: accountSections.includes(section) ? section : 'overview' }
}
const initialRoute = routeFromLocation(); const route = ref(initialRoute.page); const accountSection = ref(initialRoute.section)
const indexSnapshots = ref([]); const cryptoOverviewQuotes = ref({}); const indexLoading = ref(false); const indexError = ref(''); let indexRequestVersion = 0; let cryptoOverviewRequestVersion = 0; let indexRefreshTimer
const catalogLoading = ref(false); const catalogError = ref(''); let symbolRequestVersion = 0; let quoteRequestVersion = 0; let searchTimer
const watchlistTotal = ref(null); const watchlistLimit = ref(null); const watchlistRemaining = ref(null); const watchlistError = ref('')
const analysisCode = new URLSearchParams(window.location.search).get('analysis')
const analysisName = new URLSearchParams(window.location.search).get('name') || analysisCode
const analysisMarket = new URLSearchParams(window.location.search).get('market') || ''
const installedIndicators = computed(() => [...mainInstalled.value, ...subInstalled.value])
const visibleMarkets = computed(() => markets)
const indexMarketLayout = { cn: ['上证指数', '深证成指'], hk: ['恒生指数', '恒生科技指数'], us: ['标普500', '纳斯达克综合指数', '道琼斯工业平均指数'] }
const cryptoOverviewRows = [{ code: 'CC.BTC-USD', name: 'BTC' }, { code: 'CC.ETH-USD', name: 'ETH' }]
const displayIndexNames = { 上证指数: '上证', 深证成指: '深证', 恒生指数: '恒指', 恒生科技指数: '恒生科技', 标普500: '标普500', 标普500指数: '标普500', 纳斯达克综合指数: '纳斯达克', 道琼斯工业平均指数: '道琼斯', 道琼斯指数: '道琼斯' }
const displayIndexName = name => displayIndexNames[name] || name
const isFiniteNumber = value => typeof value === 'number' && Number.isFinite(value)
const indexRowsForMarket = code => {
  if (code === 'crypto') return cryptoOverviewRows.map(item => {
    const quote = cryptoOverviewQuotes.value[item.code]
    return { ...item, price: quote?.data?.price, change_percent: quote?.data?.change, updated_at: quote?.data?.updated_at, status: quote?.status === 'ready' ? 'ready' : 'unavailable', provider_status: quote?.status === 'ready' ? 'connected' : 'unavailable' }
  })
  const items = indexSnapshots.value.filter(item => item.market === code)
  return items.length ? items : (indexMarketLayout[code] || []).map(name => ({ name, status: indexLoading.value ? 'loading' : 'unavailable' }))
}
const indexTitle = index => {
  const status = index.provider_status === 'not_connected' ? '待接入真实数据源' : index.status === 'loading' ? t('indexLoading') : t('indexUnavailable')
  return [index.name, displayIndexPrice(index.price), displayIndexChange(index.change_percent), index.updated_at ? `更新时间：${index.updated_at}` : status].join(' · ')
}
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
const displayIndexPrice = value => typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString(undefined, { maximumFractionDigits: 2 }) : '—'
const displayIndexChange = value => typeof value === 'number' && Number.isFinite(value) ? `${value > 0 ? '+' : ''}${value.toFixed(2)}%` : '—'
const itemQuote = item => quotes.value[item.code]?.data
const itemQuoteError = item => quotes.value[item.code]?.error || ''
const symbolTitle = item => [item.name + ' · ' + item.code, itemQuoteError(item)].filter(Boolean).join(' · ')
const marketColorTokens = computed(() => priceColorMode.value === 'international' ? { up: '#3acba3', down: '#ef6671' } : { up: '#ef6671', down: '#3acba3' })
const marketChangeStyle = value => {
  if (!isFiniteNumber(value)) return { color: '#8193a7' }
  if (value === 0) return { color: '#aebdcc' }
  return { color: value > 0 ? marketColorTokens.value.up : marketColorTokens.value.down }
}
const catalogStatusText = computed(() => catalogError.value || (catalogLoading.value ? t('catalogLoading') : query.value.trim() && !list.value.length ? t('noSymbol') : ''))
const emptyWatchlistText = computed(() => t('watchlistEmpty'))
function updateWatchlistSummary(payload) {
  if (payload?.mode === 'watchlist') {
    watchlistTotal.value = payload.total ?? 0
    watchlistLimit.value = payload.limit ?? 0
    watchlistRemaining.value = payload.remaining ?? 0
  } else if (payload?.watchlist_total !== undefined) {
    watchlistTotal.value = payload.watchlist_total
    watchlistLimit.value = payload.watchlist_limit
    watchlistRemaining.value = payload.watchlist_remaining
  }
}
function readCookie(name) {
  const prefix = `${name}=`
  const value = document.cookie.split('; ').find(item => item.startsWith(prefix))
  return value ? decodeURIComponent(value.slice(prefix.length)) : ''
}
async function csrfHeaders() {
  let token = readCookie('csrftoken')
  if (!token) {
    const reply = await fetch(`${API_BASE}/api/csrf/`, { credentials: 'include' })
    if (!reply.ok) throw new Error(t('watchlistUnavailable'))
    token = readCookie('csrftoken')
  }
  if (!token) throw new Error(t('watchlistUnavailable'))
  return { 'X-CSRFToken': token }
}
function addIndicator(item) { if (visitor.value && !item.visitor_available) return; const list = item.placement === 'main' ? mainInstalled : subInstalled; if (item.placement === 'sub' && !list.value.some(current => current.code === item.code) && list.value.length >= 3) return; if (!list.value.some(current => current.code === item.code)) list.value = [...list.value, item] }
function removeIndicator(item) { if (item.placement === 'main') mainInstalled.value = mainInstalled.value.filter(current => current.code !== item.code); else subInstalled.value = subInstalled.value.filter(current => current.code !== item.code) }
function applyInitialPreferences(currentUser) {
  if (initialPreferencesApplied || !currentUser?.preferences) return
  const preferences = currentUser.preferences
  if (['cn', 'hk', 'us', 'crypto'].includes(preferences.default_market)) market.value = markets.find(item => item.code === preferences.default_market) || markets[0]
  if (['1分', '5分', '15分', '30分', '60分', '2小时', '4小时', '日线', '周线', '月线'].includes(preferences.default_period)) period.value = preferences.default_period
  if (['cn', 'international'].includes(preferences.price_color_mode)) priceColorMode.value = preferences.price_color_mode
  initialPreferencesApplied = true
}
function handleUserUpdated(updatedUser) { if (updatedUser) user.value = { ...user.value, ...updatedUser } }
function handlePreferencesUpdated(preferences) { if (preferences?.price_color_mode) priceColorMode.value = preferences.price_color_mode; user.value = { ...user.value, preferences: { ...(user.value?.preferences || {}), ...preferences } } }
function authenticated(currentUser) { applyInitialPreferences(currentUser); user.value = currentUser; visitor.value = Boolean(currentUser.visitor); if (window.location.pathname !== '/' || window.location.search) window.history.replaceState({}, '', '/'); syncRoute() }
function syncRoute() { const next = routeFromLocation(); route.value = next.page; accountSection.value = next.section }
function navigateToAccount(section = 'overview') { const next = accountSections.includes(section) ? section : 'overview'; window.history.pushState({}, '', next === 'overview' ? '/account' : `/account?section=${encodeURIComponent(next)}`); syncRoute(); stopMarketIndexRefresh() }
function navigateToTerminal() { window.history.pushState({}, '', '/'); syncRoute(); if (user.value) { loadSymbols(); startMarketIndexRefresh() } }
function toggleCommon(item) { const active = (item.placement === 'main' ? mainInstalled : subInstalled).value.some(current => current.code === item.code); if (active) removeIndicator(item); else addIndicator(item) }
function openAiAnalysis() { const url = `/?analysis=${encodeURIComponent(selected.value.code)}&name=${encodeURIComponent(selected.value.name)}&market=${encodeURIComponent(market.value.name)}`; window.open(url, '_blank', 'noopener') }
async function requestAiAccess() { if (!visitor.value) return openAiAnalysis(); await fetch(`${API_BASE}/api/auth/logout/`, { method: 'POST', credentials: 'include' }); user.value = null; visitor.value = false; window.location.assign('/?register=1') }
function backToTerminal() { window.location.assign('/') }
async function signOut() { await fetch(`${API_BASE}/api/auth/logout/`, { method: 'POST', credentials: 'include' }); user.value = null; visitor.value = false; initialPreferencesApplied = false; mainInstalled.value = []; subInstalled.value = []; symbols.value = []; selected.value = null; watchlistTotal.value = null; watchlistLimit.value = null; watchlistRemaining.value = null; watchlistError.value = ''; navigateToTerminal() }
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
async function toggleWatchlist(item) {
  if (visitor.value) {
    watchlistError.value = t('watchlistLoginRequired')
    return
  }
  const wasWatchlisted = Boolean(item.watchlisted)
  try {
    const headers = await csrfHeaders()
    const options = { method: wasWatchlisted ? 'DELETE' : 'POST', credentials: 'include', headers }
    if (!wasWatchlisted) {
      options.headers = { 'Content-Type': 'application/json', ...headers }
      options.body = JSON.stringify({ code: item.code })
    }
    const reply = await fetch(
      wasWatchlisted ? `${API_BASE}/api/watchlist/${encodeURIComponent(item.code)}/` : `${API_BASE}/api/watchlist/`,
      options,
    )
    const payload = await reply.json()
    if (!reply.ok) {
      if (payload.code === 'watchlist_limit_reached') {
        watchlistError.value = `${t('watchlistLimitReached')}（${payload.total}/${payload.limit}）`
      } else {
        watchlistError.value = payload.error || t('watchlistAddFailed')
      }
      return
    }
    updateWatchlistSummary({ mode: 'watchlist', ...payload })
    const next = symbols.value.map(current => current.code === item.code ? { ...current, watchlisted: !wasWatchlisted } : current)
    symbols.value = wasWatchlisted && !query.value.trim() ? next.filter(current => current.code !== item.code) : next
    watchlistError.value = ''
  } catch (error) {
    watchlistError.value = error.message || (wasWatchlisted ? t('watchlistRemoveFailed') : t('watchlistAddFailed'))
  }
}
async function loadMarketIndexes() {
  const version = ++indexRequestVersion
  indexLoading.value = true; indexError.value = ''
  try {
    const reply = await fetch(`${API_BASE}/api/market-index-snapshots/`, { credentials: 'include' })
    const payload = await reply.json()
    if (!reply.ok) throw new Error(payload.error || t('indexUnavailable'))
    const items = Array.isArray(payload.markets) ? payload.markets.flatMap(group => Array.isArray(group.items) ? group.items : []) : []
    if (version !== indexRequestVersion) return
    indexSnapshots.value = items
  } catch (error) {
    if (version !== indexRequestVersion) return
    indexSnapshots.value = []; indexError.value = error.message || t('indexUnavailable')
  } finally {
    if (version === indexRequestVersion) indexLoading.value = false
  }
  loadCryptoOverview()
}
async function loadCryptoOverview() {
  const version = ++cryptoOverviewRequestVersion
  const next = Object.fromEntries(cryptoOverviewRows.map(item => [item.code, { status: 'loading' }]))
  cryptoOverviewQuotes.value = next
  await Promise.all(cryptoOverviewRows.map(async item => {
    try {
      const reply = await fetch(`${API_BASE}/api/quote/${encodeURIComponent(item.code)}/`, { credentials: 'include' })
      const payload = await reply.json()
      if (!reply.ok) throw new Error(payload.error || 'Coinbase unavailable')
      next[item.code] = { status: 'ready', data: payload }
    } catch (error) {
      next[item.code] = { status: 'error', error: error.message || 'Coinbase unavailable' }
    }
  }))
  if (version === cryptoOverviewRequestVersion) cryptoOverviewQuotes.value = { ...next }
}
function stopMarketIndexRefresh() { window.clearInterval(indexRefreshTimer); indexRefreshTimer = undefined }
function startMarketIndexRefresh() {
  stopMarketIndexRefresh()
  if (document.hidden || !user.value || route.value !== 'terminal') return
  loadMarketIndexes()
  indexRefreshTimer = window.setInterval(loadMarketIndexes, 60000)
}
function handleVisibilityChange() {
  if (document.hidden) stopMarketIndexRefresh()
  else if (user.value) startMarketIndexRefresh()
}
async function loadSymbols() {
  const version = ++symbolRequestVersion
  catalogLoading.value = true; catalogError.value = ''; watchlistError.value = ''
  const search = query.value.trim()
  const endpoint = search ? `symbols/${market.value.code}/` : 'watchlist/'
  const params = new URLSearchParams(search ? { limit: '10', page: '1', q: search } : { market: market.value.code })
  try {
    const reply = await fetch(`${API_BASE}/api/${endpoint}?${params}`, { credentials: 'include' })
    const payload = await reply.json()
    if (!reply.ok) throw new Error(payload.error || t('catalogUnavailable'))
    if (version !== symbolRequestVersion) return
    const items = Array.isArray(payload.items) ? payload.items : []
    updateWatchlistSummary(payload)
    symbols.value = items.map(item => ({ ...item, watchlisted: Boolean(item.watchlisted) }))
    const selectedItem = items.find(item => item.code === selected.value?.code)
    if (selectedItem) selected.value = selectedItem
    else if (!selected.value && items[0]) selected.value = items[0]
    if (user.value && items.length) refreshQuotes(items)
    else { quoteRequestVersion += 1; quotes.value = {} }
    if (!items.length && !search && payload.error) catalogError.value = payload.error
  } catch (error) {
    if (version !== symbolRequestVersion) return
    symbols.value = []; quoteRequestVersion += 1; quotes.value = {}; catalogError.value = error.message || t('catalogUnavailable')
  } finally {
    if (version === symbolRequestVersion) catalogLoading.value = false
  }
}
function switchMarket(item) { if (market.value.code !== item.code) { market.value = item; selected.value = null } query.value = '' }
watch(market, () => { if (user.value && route.value === 'terminal') loadSymbols() })
watch(query, () => { window.clearTimeout(searchTimer); searchTimer = window.setTimeout(loadSymbols, 280) })
watch(user, currentUser => {
  if (currentUser) { if (route.value === 'terminal') loadSymbols(); startMarketIndexRefresh() }
  else { symbolRequestVersion += 1; quoteRequestVersion += 1; indexRequestVersion += 1; stopMarketIndexRefresh(); indexSnapshots.value = []; quotes.value = {}; symbols.value = []; selected.value = null; watchlistTotal.value = null; watchlistLimit.value = null; watchlistRemaining.value = null }
})
function handleRouteChange() { syncRoute(); if (route.value === 'terminal' && user.value) { loadSymbols(); startMarketIndexRefresh() } else stopMarketIndexRefresh() }
onMounted(async () => { syncRoute(); document.addEventListener('visibilitychange', handleVisibilityChange); window.addEventListener('popstate', handleRouteChange); try { const reply = await fetch(`${API_BASE}/api/auth/session/`, { credentials: 'include' }); const data = await reply.json(); if (reply.ok && data.authenticated) { applyInitialPreferences(data.user); user.value = data.user; visitor.value = Boolean(data.visitor) } } catch {} finally { checkingSession.value = false } })
onBeforeUnmount(() => { window.clearTimeout(searchTimer); stopMarketIndexRefresh(); document.removeEventListener('visibilitychange', handleVisibilityChange); window.removeEventListener('popstate', handleRouteChange) })
</script>
<template>
  <div v-if="checkingSession" class="boot-screen">HuntAlpha…</div>
  <AuthGate v-else-if="!user" @authenticated="authenticated" />
  <PersonalCenter v-else-if="route === 'account'" :user="user" :section="accountSection" @back="navigateToTerminal" @section-change="navigateToAccount" @logout="signOut" @user-updated="handleUserUpdated" @preferences-updated="handlePreferencesUpdated" />
  <AiAnalysis v-else-if="analysisCode" :code="analysisCode" :name="analysisName" :market="analysisMarket" @back="backToTerminal" />
  <main v-else class="terminal" :style="{ '--market-up': marketColorTokens.up, '--market-down': marketColorTokens.down }">
     <header><div class="brand"><HuntAlphaLogo class="brand-logo" /><span class="brand-name">HuntAlpha</span><small class="brand-hub">HUB</small></div><nav><a class="active">{{ t('market') }}</a><a>{{ t('watchlist') }}</a><a>{{ t('strategy') }}</a><a>{{ t('news') }}</a></nav><div class="header-account-controls"><div v-if="visitor" class="visitor-account"><div class="feed"><span class="feed-dot">●</span><span>{{ t('visitor') }}</span></div><button class="visitor-logout" @click="signOut">{{ t('logout') }}</button></div><AccountPopover v-else :user="user" :watchlist-total="watchlistTotal" :watchlist-limit="watchlistLimit" :watchlist-remaining="watchlistRemaining" @navigate="navigateToAccount" @logout="signOut" /><select class="terminal-language" :value="locale" @change="setLocale($event.target.value)"><option v-for="item in languages" :key="item.code" :value="item.code">{{ item.label }}</option></select></div></header>
    <section class="markets" aria-label="市场概览"><button v-for="item in visibleMarkets" :key="item.code" class="market-card" :class="{active: market.code === item.code}" @click="switchMarket(item)"><div class="market-card-title"><strong>{{ item.name }}</strong><small>{{ item.code === 'crypto' ? 'coinbase' : 'futu-opend' }}</small></div><div v-for="index in indexRowsForMarket(item.code)" :key="index.code || index.name" class="market-index" :title="indexTitle(index)" :aria-label="indexTitle(index)"><span class="market-index-name">{{ displayIndexName(index.name) }}</span><span class="market-index-values"><b :class="{unavailable: !isFiniteNumber(index.price)}">{{ displayIndexPrice(index.price) }}</b><em :style="marketChangeStyle(index.change_percent)" :class="{down: index.change_percent < 0, unavailable: !isFiniteNumber(index.change_percent)}">{{ displayIndexChange(index.change_percent) }}</em></span></div></button></section>
    <div class="workspace"><aside><div class="aside-title" :title="watchlistRemaining == null ? '' : `${watchlistRemaining} ${t('watchlistRemaining')}`"><span>{{ t('watchlistList') }}</span><b>{{ watchlistTotal == null ? '—' : watchlistTotal }} / {{ watchlistLimit == null ? '—' : watchlistLimit }}</b></div><label class="search">⌕ <input v-model="query" :placeholder="t('search')" /></label><div class="heads"><span>{{ t('nameCode') }}</span><span>{{ t('latest') }}</span><span>{{ t('change') }}</span><span aria-label="收藏">☆</span></div><div v-for="item in list" :key="item.code" class="symbol" :class="{selected: selected?.code === item.code}" :title="symbolTitle(item)" :aria-label="symbolTitle(item)" role="button" tabindex="0" @click="selected = item" @keydown.enter="selected = item"><span class="symbol-name"><strong>{{ item.name }}</strong><small>{{ item.code }}</small></span><b :style="marketChangeStyle(itemQuote(item)?.change)">{{ displayPrice(itemQuote(item)?.price) }}</b><em :style="marketChangeStyle(itemQuote(item)?.change)" :class="{down:itemQuote(item)?.change < 0}">{{ displayChange(itemQuote(item)?.change) }}</em><button type="button" class="star" :class="{active:item.watchlisted}" :aria-label="item.watchlisted ? t('watchlistUnstar') : t('watchlistStar')" :aria-pressed="item.watchlisted" @click.stop="toggleWatchlist(item)">{{ item.watchlisted ? '★' : '☆' }}</button></div><p v-if="catalogStatusText">{{ catalogStatusText }}</p><p v-if="!catalogLoading && !list.length && !catalogStatusText" class="watchlist-empty">{{ emptyWatchlistText }}<small v-if="!query.trim()">{{ market.code === 'crypto' ? '搜索 BTC 或 ETH 并点击 ☆ 添加' : t('watchlistSearchHint') }}</small></p><p v-if="watchlistError" class="watchlist-message">{{ watchlistError }}</p></aside>
      <section class="content"><div class="security"><div><p>{{ market.name }} · {{ quoteStatusText }}</p><h1>{{ selected?.name || '—' }} <small>{{ selected?.code || '' }}</small><button v-if="selected && !selected.code.startsWith('CC.')" class="ai-button" @click="requestAiAccess">AI 分析</button></h1></div><div class="price"><strong :style="marketChangeStyle(quoteData?.change)">{{ displayPrice(quoteData?.price) }}</strong><span :style="marketChangeStyle(quoteData?.change)" :class="{down:quoteData?.change < 0}">{{ displayChange(quoteData?.change) }}</span></div><dl><div><dt>{{ t('open') }}</dt><dd>{{ displayPrice(quoteData?.open) }}</dd></div><div><dt>{{ t('high') }}</dt><dd>{{ displayPrice(quoteData?.high) }}</dd></div><div><dt>{{ t('low') }}</dt><dd>{{ displayPrice(quoteData?.low) }}</dd></div></dl></div>
        <div class="toolbar"><div><button v-for="item in ['分时','1分','5分','15分','30分','60分','2小时','4小时','日线','周线','月线']" :key="item" :class="{active:period === item}" @click="period=item">{{ item }}</button></div><div class="common-tools"><button v-for="item in commonIndicators" :key="item.code" :class="{on:installedIndicators.some(current=>current.code===item.code)}" @click="toggleCommon(item)">{{item.name}}</button><button @click="manager.open()">{{ t('manager') }}</button></div></div>
        <div class="labels"><span>{{ t('main') }}{{ mainInstalled.map(item => item.name).join(' · ') || t('candle') }}</span></div><MarketChart v-if="selected" :symbol="selected" :period="period" :installed-indicators="installedIndicators" :market-color-tokens="marketColorTokens" /><div v-else class="catalog-empty">{{ catalogStatusText }}</div><footer>{{ t('disclaimer') }}</footer>
      </section></div>
    <IndicatorManager ref="manager" :main="mainInstalled" :sub="subInstalled" :visitor="visitor" @add="addIndicator" @remove="removeIndicator" />
  </main>
</template>

<style scoped>
.markets{grid-template-columns:repeat(4,minmax(0,1fr));min-height:100px}
.brand{gap:8px;min-width:0}.brand-logo{width:30px;height:30px}.brand-name{color:#f4f8fb;white-space:nowrap}.brand-hub{padding:2px 5px;border:1px solid #3b5369;border-radius:3px;color:#9eb0c0;font-size:10px;font-weight:500;letter-spacing:.08em;white-space:nowrap}.header-account-controls{display:flex;align-items:center;gap:10px;margin-left:auto;min-width:0;flex:0 0 auto}.feed{display:flex;align-items:center;gap:8px;margin-left:0;white-space:nowrap}.feed-dot{color:#f4bf50;font-size:10px}.visitor-account{display:flex;align-items:center;gap:10px;min-width:0}.visitor-logout{border:1px solid #34485b;border-radius:4px;background:transparent;color:#9eb0c0;padding:5px 9px;font-size:11px}.visitor-logout:hover{border-color:#65d8b6;color:#e7f1f6}
.market-card{display:block;min-width:0;border:0;border-right:1px solid #233143;color:#95a7ba;padding:11px 16px;text-align:left;background:#101a26}
.market-card:last-child{border-right:0}.market-card:hover,.market-card.active{background:#162435}
.market-card-title{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:8px}.market-card-title strong{color:#dce7f1;font-size:13px}.market-card-title small{color:#61788c;font:9px 'DM Mono',monospace}
.market-index{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:2px 10px;padding:4px 0}.market-index-name{grid-row:auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#aebdca;font:11px 'Noto Sans SC',sans-serif}.market-index-values{grid-row:auto;display:flex;align-items:baseline;gap:8px;white-space:nowrap;font:12px 'DM Mono',monospace}.market-index-values b{color:#f0f5fa;font-weight:500}.market-index-values em{color:#ef6671;font-style:normal}.market-index-values em.down{color:#3acba3}.market-index-updated,.market-index-status{grid-column:1 / -1;color:#61788c;font:9px 'DM Mono',monospace;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.market-index-status{color:#8193a7}
.heads,.symbol{grid-template-columns:minmax(0,1fr) 58px 58px}
.symbol{min-height:55px}.symbol-name{min-width:0}.symbol b,.symbol em{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.symbol-cap{color:#8ba2b3!important;font:9px/1.2 'DM Mono',monospace!important;letter-spacing:-.02em}
.catalog-empty{min-height:460px;display:grid;place-items:center;color:#8193a7;font-size:13px}
.toolbar{gap:8px}.common-tools{display:flex;justify-content:flex-end;flex-wrap:wrap}.common-tools button:last-child{margin-left:4px;border-left:1px solid #31465a;color:#b8cee0}
.terminal-language{border:1px solid #344b5c;border-radius:4px;background:#101d29;color:#c4d4df;padding:5px;font-size:11px}
.ai-button{margin-left:10px;border:1px solid #3ccca3;border-radius:4px;background:#10372f;color:#75e2c1;padding:5px 8px;font-size:11px;vertical-align:middle}
.market-card{min-height:100px;padding:9px 14px}.market-card-title{margin-bottom:5px}.market-index{display:flex;align-items:center;gap:8px;min-height:21px;padding:2px 0}.market-index-name{flex:1;min-width:0}.market-index-values{flex:0 0 auto;display:flex;align-items:baseline;gap:6px;white-space:nowrap}.market-index-values b.unavailable,.market-index-values em.unavailable{color:#8193a7!important}.market-index-updated,.market-index-status{display:none}
.heads,.symbol{grid-template-columns:minmax(0,1fr) 68px 55px 28px}
.symbol{cursor:pointer}
.star{width:28px;padding:0;border:0;background:transparent;color:#718398;font:20px/1 'Noto Sans SC',sans-serif;text-align:center}
.star.active{color:#f3c453}
.watchlist-empty,.watchlist-message{padding:4px 18px;text-align:center;line-height:1.6}
.watchlist-empty{display:grid;gap:3px;color:#9aafbd}
.watchlist-empty small{color:#718398;font-size:11px}
.watchlist-message{color:#ff9a82}
@media(max-width:800px){.markets{grid-template-columns:repeat(2,minmax(0,1fr))}.market-card{border-right:0;border-bottom:1px solid #233143;padding:8px 10px}.market-card:nth-child(odd){border-right:1px solid #233143}.market-card:last-child{border-bottom:0}.market-card-title{margin-bottom:4px}.market-index{padding:2px 0}.brand-name{font-size:16px}.brand-hub{display:none}header{gap:12px}.feed{display:flex;min-width:0}.feed>span:nth-child(2){max-width:100px;overflow:hidden;text-overflow:ellipsis}.header-account-controls{gap:8px}.account-tier-badge{width:50px;height:46px}.visitor-account{gap:7px}}
@media(max-width:520px){.feed-dot,.feed>span:nth-child(2){display:none}.header-account-controls{gap:6px}.terminal-language{display:block;width:48px;min-width:48px;padding:4px 1px;font-size:10px}.account-tier-badge{width:46px;height:42px}}
.terminal .market-index-values em,.terminal .symbol em,.terminal .price span{color:var(--market-up)}.terminal .market-index-values em.down,.terminal .symbol em.down,.terminal .price span.down{color:var(--market-down)}
</style>
