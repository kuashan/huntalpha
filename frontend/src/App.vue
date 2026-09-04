<script setup>
import { computed, onMounted, ref } from 'vue'
import MarketChart from './components/MarketChart.vue'
import IndicatorManager from './components/IndicatorManager.vue'
import AuthGate from './components/AuthGate.vue'
import AiAnalysis from './components/AiAnalysis.vue'
import { commonIndicators, marketSummary, markets, symbolsFor } from './data/marketData'
import { languages, locale, setLocale, t } from './i18n'
const market = ref('沪深 A 股'); const query = ref(''); const selected = ref(symbolsFor(market.value)[0]); const period = ref('日线'); const mainInstalled = ref([]); const subInstalled = ref([]); const manager = ref(null)
const user = ref(null); const visitor = ref(false); const checkingSession = ref(true)
const analysisCode = new URLSearchParams(window.location.search).get('analysis')
const analysisName = new URLSearchParams(window.location.search).get('name') || analysisCode
const analysisMarket = new URLSearchParams(window.location.search).get('market') || ''
const installedIndicators = computed(() => [...mainInstalled.value, ...subInstalled.value])
const list = computed(() => symbolsFor(market.value).filter(item => `${item.code}${item.name}`.toLowerCase().includes(query.value.toLowerCase())))
const displayPrice = value => typeof value === 'number' ? value.toLocaleString() : t('pending')
const displayChange = value => typeof value === 'number' ? `${value > 0 ? '+' : ''}${value}%` : '—'
function switchMarket(item) { market.value = item; query.value = ''; selected.value = symbolsFor(item)[0] }
function addIndicator(item) { if (visitor.value && !item.visitor_available) return; const list = item.placement === 'main' ? mainInstalled : subInstalled; if (item.placement === 'sub' && !list.value.some(current => current.code === item.code) && list.value.length >= 3) return; if (!list.value.some(current => current.code === item.code)) list.value = [...list.value, item] }
function removeIndicator(item) { if (item.placement === 'main') mainInstalled.value = mainInstalled.value.filter(current => current.code !== item.code); else subInstalled.value = subInstalled.value.filter(current => current.code !== item.code) }
function authenticated(currentUser) { user.value = currentUser; visitor.value = Boolean(currentUser.visitor); if (window.location.search) window.history.replaceState({}, '', '/') }
function toggleCommon(item) { const active = (item.placement === 'main' ? mainInstalled : subInstalled).value.some(current => current.code === item.code); if (active) removeIndicator(item); else addIndicator(item) }
function openAiAnalysis() { const url = `/?analysis=${encodeURIComponent(selected.value.code)}&name=${encodeURIComponent(selected.value.name)}&market=${encodeURIComponent(market.value)}`; window.open(url, '_blank', 'noopener') }
async function requestAiAccess() { if (!visitor.value) return openAiAnalysis(); await fetch('http://127.0.0.1:8003/api/auth/logout/', { method: 'POST', credentials: 'include' }); user.value = null; visitor.value = false; window.location.assign('/?register=1') }
function backToTerminal() { window.location.assign('/') }
async function signOut() { await fetch('http://127.0.0.1:8003/api/auth/logout/', { method: 'POST', credentials: 'include' }); user.value = null; visitor.value = false; mainInstalled.value = []; subInstalled.value = [] }
onMounted(async () => { try { const reply = await fetch('http://127.0.0.1:8003/api/auth/session/', { credentials: 'include' }); const data = await reply.json(); if (reply.ok && data.authenticated) { user.value = data.user; visitor.value = Boolean(data.visitor) } } catch {} finally { checkingSession.value = false } })
</script>
<template>
  <div v-if="checkingSession" class="boot-screen">QuantScope…</div>
  <AuthGate v-else-if="!user" @authenticated="authenticated" />
  <AiAnalysis v-else-if="analysisCode" :code="analysisCode" :name="analysisName" :market="analysisMarket" @back="backToTerminal" />
  <main v-else class="terminal">
    <header><div class="brand"><b>Q</b> QuantScope <small>{{ visitor ? t('visitor') : t('pro') }}</small></div><nav><a class="active">{{ t('market') }}</a><a>{{ t('watchlist') }}</a><a>{{ t('strategy') }}</a><a>{{ t('news') }}</a></nav><div class="feed">● {{ visitor ? t('visitorAi') : user.name }}</div><select class="terminal-language" :value="locale" @change="setLocale($event.target.value)"><option v-for="item in languages" :key="item.code" :value="item.code">{{ item.label }}</option></select><button class="logout" @click="signOut">{{ t('logout') }}</button></header>
    <section class="markets"><button v-for="item in markets" :key="item" :class="{active: market === item}" @click="switchMarket(item)"><strong>{{ item }}</strong><span>{{ marketSummary[item].value }}</span><em>{{ marketSummary[item].change }}</em></button></section>
    <div class="workspace"><aside><div class="aside-title">{{ t('marketList') }} <b>{{ market }}</b></div><label class="search">⌕ <input v-model="query" :placeholder="t('search')" /></label><div class="heads"><span>{{ t('nameCode') }}</span><span>{{ t('latest') }}</span><span>{{ t('change') }}</span></div><button v-for="item in list" :key="item.code" class="symbol" :class="{selected: selected.code === item.code}" @click="selected = item"><span><strong>{{ item.name }}</strong><small>{{ item.code }}</small></span><b>{{ displayPrice(item.price) }}</b><em :class="{down:item.change < 0}">{{ displayChange(item.change) }}</em></button><p v-if="!list.length">{{ t('noSymbol') }}</p></aside>
      <section class="content"><div class="security"><div><p>{{ market }} · {{ selected.price === null ? t('pending') : t('demo') }}</p><h1>{{ selected.name }} <small>{{ selected.code }}</small><button v-if="!selected.code.startsWith('CC.')" class="ai-button" @click="requestAiAccess">AI 分析</button></h1></div><div class="price"><strong>{{ displayPrice(selected.price) }}</strong><span :class="{down:selected.change < 0}">{{ displayChange(selected.change) }}</span></div><dl><div><dt>{{ t('open') }}</dt><dd>{{ selected.price === null ? '—' : (selected.price * .996).toFixed(2) }}</dd></div><div><dt>{{ t('high') }}</dt><dd>{{ selected.price === null ? '—' : (selected.price * 1.014).toFixed(2) }}</dd></div><div><dt>{{ t('low') }}</dt><dd>{{ selected.price === null ? '—' : (selected.price * .987).toFixed(2) }}</dd></div></dl></div>
        <div class="toolbar"><div><button v-for="item in ['分时','1分','5分','15分','30分','60分','2小时','4小时','日线','周线','月线']" :key="item" :class="{active:period === item}" @click="period=item">{{ item }}</button></div><div class="common-tools"><button v-for="item in commonIndicators" :key="item.code" :class="{on:installedIndicators.some(current=>current.code===item.code)}" @click="toggleCommon(item)">{{item.name}}</button><button @click="manager.open()">{{ t('manager') }}</button></div></div>
        <div class="labels"><span>{{ t('main') }}{{ mainInstalled.map(item => item.name).join(' · ') || t('candle') }}</span></div><MarketChart :symbol="selected" :period="period" :installed-indicators="installedIndicators" /><footer>{{ t('disclaimer') }}</footer>
      </section></div>
    <IndicatorManager ref="manager" :main="mainInstalled" :sub="subInstalled" :visitor="visitor" @add="addIndicator" @remove="removeIndicator" />
  </main>
</template>

<style scoped>
.markets{grid-template-columns:repeat(4,minmax(0,1fr))}
.toolbar{gap:8px}.common-tools{display:flex;justify-content:flex-end;flex-wrap:wrap}.common-tools button:last-child{margin-left:4px;border-left:1px solid #31465a;color:#b8cee0}
.terminal-language{border:1px solid #344b5c;border-radius:4px;background:#101d29;color:#c4d4df;padding:5px;font-size:11px}
.ai-button{margin-left:10px;border:1px solid #3ccca3;border-radius:4px;background:#10372f;color:#75e2c1;padding:5px 8px;font-size:11px;vertical-align:middle}
@media(max-width:800px){.markets{grid-template-columns:repeat(4,minmax(92px,1fr));overflow-x:auto}.markets button{padding:11px 10px}.markets strong{font-size:12px}.markets span{font-size:12px}}
</style>
