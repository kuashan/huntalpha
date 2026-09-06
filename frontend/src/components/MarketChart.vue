<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { CandlestickSeries, LineSeries, createChart } from 'lightweight-charts'
import { TongdaxinStickPrimitive } from '../indicators/TongdaxinStickPrimitive'
import { TongdaxinTextPrimitive } from '../indicators/TongdaxinTextPrimitive'
import { TongdaxinFixedTextPrimitive } from '../indicators/TongdaxinFixedTextPrimitive'
import { commonDrawing } from '../indicators/commonIndicators'
import { createRealtimeUiBuffer, mergeRealtimeBars } from '../realtime/realtimeUiBuffer.mjs'
import { reconcileRealtimeVersion } from '../realtime/realtimeGeneration.mjs'

const props = defineProps({
  symbol: Object,
  period: String,
  installedIndicators: { type: Array, default: () => [] },
  marketColorTokens: { type: Object, default: () => ({ up: '#ef5350', down: '#20bd92' }) },
})

const el = ref(null)
const mainIndicators = computed(() => props.installedIndicators.filter(item => item.placement === 'main'))
const subTitlePositions = ref([])
const renderErrors = ref([])
const historyStatus = ref('')
const realtimeStatus = ref('connecting')
const realtimeStatusText = computed(() => ({
  connecting: '连接实时行情…',
  live: '● 实时',
  polling: '轮询中',
  reconnecting: '重连中',
  unavailable: '行情暂不可用',
}[realtimeStatus.value] || '实时状态未知'))

let chart
let candleSeries
let marketCandleSeries = false
let resize
let panePointerUp
let visibilityHandler
let eventSource
let streamGeneration = 0
let drawVersion = 0
let drawQueue = Promise.resolve()
let loadedBars = []
let loadedKey = ''
let hasMoreHistory = false
let loadingHistory = false
let renderedItems = []
let layerRefs = new Map()
let realtimeEpoch = ''
let realtimeRevision = 0
let realtimeStatusGeneration = 0
let formulaTimer
let formulaInFlight = false
let formulaPendingRevision = 0
let formulaRunToken = 0
let realtimeUiBuffer

const backgroundStick = item => item.layer === 'background'
const savedSubPaneHeights = () => {
  try { return JSON.parse(localStorage.getItem('quantscope:sub-pane-heights') || '{}') } catch { return {} }
}

function syncSubTitlePositions(rendered) {
  if (!chart || !el.value) return
  const chartTop = el.value.getBoundingClientRect().top
  let paneIndex = 1
  subTitlePositions.value = rendered.filter(result => result.item.placement === 'sub').map(result => {
    const top = chart.panes()[paneIndex++]?.getHTMLElement()?.getBoundingClientRect().top
    return { code: result.item.code, name: result.item.name, top: (top === undefined ? 0 : top - chartTop) + 6 }
  })
}

function saveSubPaneHeights(rendered) {
  const heights = savedSubPaneHeights()
  let paneIndex = 1
  rendered.filter(result => result.item.placement === 'sub').forEach(result => {
    heights[result.item.code] = chart?.panes()[paneIndex++]?.getHeight() || 150
  })
  localStorage.setItem('quantscope:sub-pane-heights', JSON.stringify(heights))
}

async function requestFormulaDrawing(item, bars, revision = 0) {
  try {
    const params = new URLSearchParams({ period: props.period, count: String(bars.length), revision: String(revision) })
    if (realtimeEpoch) params.set('epoch', realtimeEpoch)
    const reply = await fetch(`http://127.0.0.1:8003/api/indicator-render/${encodeURIComponent(item.code)}/${props.symbol.code}/?${params}`, { credentials: 'include' })
    const payload = await reply.json()
    if (reply.ok) return { item, drawing: payload.drawing, epoch: payload.epoch || '', revision: Number(payload.revision || revision) }
    renderErrors.value.push(`${item.name}：${payload.error || '指标计算失败'}`)
  } catch {
    renderErrors.value.push(`${item.name}：无法连接指标计算服务`)
  }
  return null
}

async function requestDrawings(bars, revision = 0) {
  renderErrors.value = []
  const results = (await Promise.all(props.installedIndicators.map(async item => {
    if (item.common) return { item, drawing: commonDrawing(item.code, bars), revision }
    return requestFormulaDrawing(item, bars, revision)
  }))).filter(Boolean)
  const responseEpoch = results.find(result => result.epoch)?.epoch
  if (responseEpoch && !realtimeEpoch) acceptRealtimeEpoch(responseEpoch)
  return results
}

const chartKey = () => `${props.symbol?.code || ''}:${props.period || ''}`
const orderedUniqueBars = bars => [...new Map(bars.map(bar => [bar.time, bar])).values()].sort((left, right) => left.time - right.time)

function cancelFormulaWork() {
  if (formulaTimer) window.clearTimeout(formulaTimer)
  formulaTimer = undefined
  formulaPendingRevision = 0
  formulaRunToken += 1
  formulaInFlight = false
}

function acceptRealtimeEpoch(epoch) {
  const incoming = String(epoch || '').trim()
  if (!incoming) return false
  if (!realtimeEpoch) {
    realtimeEpoch = incoming
    return true
  }
  if (incoming === realtimeEpoch) return true
  realtimeEpoch = incoming
  realtimeRevision = 0
  realtimeStatusGeneration += 1
  realtimeUiBuffer?.clear()
  cancelFormulaWork()
  return true
}

function setRealtimeStatus(status) {
  if (!status) return
  if (status === 'connecting' || status === 'reconnecting' || status === 'unavailable') {
    realtimeStatusGeneration += 1
    realtimeUiBuffer?.clear()
  }
  realtimeStatus.value = status
}

function acceptRealtimeVersion(payload) {
  const decision = reconcileRealtimeVersion(realtimeEpoch, realtimeRevision, payload)
  if (!decision.accepted) return false
  if (decision.changed) acceptRealtimeEpoch(decision.epoch)
  return true
}

async function fetchKlinePage(before = null) {
  const query = new URLSearchParams({ period: props.period, count: '1000' })
  if (before) query.set('before', String(before))
  const reply = await fetch(`http://127.0.0.1:8003/api/kline/${props.symbol.code}/?${query}`, { credentials: 'include' })
  const payload = await reply.json()
  if (!reply.ok) throw new Error(payload.error || '行情服务不可用')
  return payload
}

function addLine(color, data, pane, style = 'solid', width = 1) {
  const lineWidth = Math.max(1, Math.min(9, Number(width) || 1))
  const markerStyle = style === 'circle-dot'
  const series = chart.addSeries(LineSeries, {
    color, lineWidth,
    lineStyle: style === 'dotted' ? 1 : style === 'point-dot' ? 4 : style === 'cross-dot' ? 4 : 0,
    pointMarkersVisible: markerStyle,
    pointMarkersRadius: markerStyle ? Math.max(2, Math.min(5, lineWidth + 1)) : undefined,
    priceLineVisible: false, lastValueVisible: false,
  }, pane)
  series.setData(data)
  return series
}

function addSticks(groups, pane, anchor) {
  if (!groups.length) return { background: null, foreground: null }
  const background = groups.filter(backgroundStick)
  const foreground = groups.filter(item => !backgroundStick(item))
  const result = { background: null, foreground: null }
  if (background.length) {
    result.background = new TongdaxinStickPrimitive(chart, anchor, background, 'background')
    chart.panes()[pane]?.attachPrimitive(result.background)
  }
  if (foreground.length) {
    result.foreground = new TongdaxinStickPrimitive(chart, anchor, foreground)
    chart.panes()[pane]?.attachPrimitive(result.foreground)
  }
  return result
}

function addTextMarkers(groups, pane, anchor) {
  if (!groups.length) return null
  const primitive = new TongdaxinTextPrimitive(chart, anchor, groups)
  chart.panes()[pane]?.attachPrimitive(primitive)
  return primitive
}

function addFixedTexts(items, pane) {
  if (!items?.length) return null
  const primitive = new TongdaxinFixedTextPrimitive(items)
  chart.panes()[pane]?.attachPrimitive(primitive)
  return primitive
}

function formulaAnchorData(drawing) {
  const values = new Map()
  drawing.lines.forEach(item => item.data.forEach(point => values.set(point.time, point.value)))
  drawing.sticks.forEach(item => item.data.forEach(point => {
    values.set(point.time, point.from)
    values.set(point.time, point.to)
  }))
  return [...values.entries()].sort(([left], [right]) => left - right).map(([time, value]) => ({ time, value }))
}

function addFormulaAnchor(drawing, pane) {
  const anchor = chart.addSeries(LineSeries, {
    color: 'transparent', lineVisible: false, priceLineVisible: false, lastValueVisible: false,
  }, pane)
  anchor.setData(formulaAnchorData(drawing))
  return anchor
}

function formulaOwnsMainCandles(rendered, bars) {
  const expected = new Map(bars.map(bar => [bar.time, bar]))
  const bodyTimes = new Set()
  rendered.filter(result => result.item.placement === 'main').forEach(result => {
    result.drawing.sticks.forEach(group => group.data.forEach(point => {
      const bar = expected.get(point.time)
      if (!bar || point.width < 2) return
      const matchesBody = Math.abs(point.from - bar.open) < 1e-6 && Math.abs(point.to - bar.close) < 1e-6
      if (matchesBody) bodyTimes.add(point.time)
    }))
  })
  return bars.length > 0 && bodyTimes.size >= bars.length * .95
}

function setCandleMode(rendered) {
  if (!candleSeries) return
  const formulaCandleLayer = formulaOwnsMainCandles(rendered, loadedBars)
  candleSeries.applyOptions(formulaCandleLayer ? {
    upColor: 'transparent', downColor: 'transparent', borderVisible: false,
    wickUpColor: 'transparent', wickDownColor: 'transparent',
  } : {
    upColor: props.marketColorTokens.up, downColor: props.marketColorTokens.down, borderVisible: false,
    wickUpColor: props.marketColorTokens.up, wickDownColor: props.marketColorTokens.down,
  })
  marketCandleSeries = !formulaCandleLayer
}

function installLayer(result, pane) {
  const lines = result.drawing.lines.map(item => addLine(item.color, item.data, pane, item.style, item.width))
  const layerAnchor = result.item.placement === 'main' ? candleSeries : (lines[0] || addFormulaAnchor(result.drawing, pane))
  return {
    pane,
    lines,
    anchor: layerAnchor,
    sticks: addSticks(result.drawing.sticks, pane, layerAnchor),
    markers: addTextMarkers(result.drawing.markers, pane, layerAnchor),
    fixedTexts: addFixedTexts(result.drawing.fixedTexts, pane),
  }
}

function attachStickPrimitive(groups, pane, anchor, layerName) {
  if (!groups.length) return null
  const primitive = new TongdaxinStickPrimitive(chart, anchor, groups, layerName)
  chart.panes()[pane]?.attachPrimitive(primitive)
  return primitive
}

function attachTextPrimitive(groups, pane, anchor) {
  if (!groups.length) return null
  const primitive = new TongdaxinTextPrimitive(chart, anchor, groups)
  chart.panes()[pane]?.attachPrimitive(primitive)
  return primitive
}

function attachFixedTextPrimitive(items, pane) {
  if (!items?.length) return null
  const primitive = new TongdaxinFixedTextPrimitive(items)
  chart.panes()[pane]?.attachPrimitive(primitive)
  return primitive
}

function detachPrimitive(pane, primitive) {
  if (primitive) chart.panes()[pane]?.detachPrimitive(primitive)
}

function destroyLayer(layer) {
  detachPrimitive(layer.pane, layer.sticks.background)
  detachPrimitive(layer.pane, layer.sticks.foreground)
  detachPrimitive(layer.pane, layer.markers)
  detachPrimitive(layer.pane, layer.fixedTexts)
  layer.lines.forEach(series => chart.removeSeries(series))
  if (layer.anchor && layer.anchor !== candleSeries && !layer.lines.includes(layer.anchor)) {
    chart.removeSeries(layer.anchor)
  }
}

function rebuildLayer(result) {
  const previous = layerRefs.get(result.item.code)
  const pane = previous?.pane ?? (result.item.placement === 'main' ? 0 : 1)
  if (previous) destroyLayer(previous)
  const layer = installLayer(result, pane)
  layerRefs.set(result.item.code, layer)
  return layer
}

function updateLayer(result) {
  const layer = layerRefs.get(result.item.code)
  if (!layer || layer.lines.length !== result.drawing.lines.length) return false
  result.drawing.lines.forEach((item, index) => layer.lines[index].setData(item.data))
  const background = result.drawing.sticks.filter(backgroundStick)
  const foreground = result.drawing.sticks.filter(item => !backgroundStick(item))
  if (layer.sticks.background) layer.sticks.background.update(background)
  else if (background.length) layer.sticks.background = attachStickPrimitive(background, layer.pane, layer.anchor, 'background')
  if (layer.sticks.foreground) layer.sticks.foreground.update(foreground)
  else if (foreground.length) layer.sticks.foreground = attachStickPrimitive(foreground, layer.pane, layer.anchor, 'normal')
  if (layer.markers) layer.markers.update(result.drawing.markers)
  else if (result.drawing.markers.length) layer.markers = attachTextPrimitive(result.drawing.markers, layer.pane, layer.anchor)
  if (layer.fixedTexts) layer.fixedTexts.update(result.drawing.fixedTexts)
  else if (result.drawing.fixedTexts.length) layer.fixedTexts = attachFixedTextPrimitive(result.drawing.fixedTexts, layer.pane)
  if (layer.anchor && layer.anchor !== candleSeries && !layer.lines.length) layer.anchor.setData(formulaAnchorData(result.drawing))
  return true
}

function applyLayerResult(result) {
  const rendered = renderedItems.find(entry => entry.item.code === result.item.code)
  if (!rendered) return
  if (!updateLayer(result)) rebuildLayer(result)
  rendered.drawing = result.drawing
}

function refreshBuiltInLayers() {
  props.installedIndicators.filter(item => item.common).forEach(item => {
    const result = { item, drawing: commonDrawing(item.code, loadedBars) }
    applyLayerResult(result)
  })
  setCandleMode(renderedItems)
}

function queueFormulaRefresh(revision) {
  if (!props.installedIndicators.some(item => !item.common) || !chart) return
  formulaPendingRevision = Math.max(formulaPendingRevision, Number(revision || 0))
  if (formulaTimer || formulaInFlight) return
  formulaTimer = window.setTimeout(() => {
    formulaTimer = undefined
    runFormulaRefresh()
  }, 850)
}

async function runFormulaRefresh() {
  if (formulaInFlight || !props.symbol || !chart) return
  formulaInFlight = true
  const runToken = ++formulaRunToken
  const generation = drawVersion
  const requestRevision = formulaPendingRevision
  formulaPendingRevision = 0
  const bars = loadedBars.slice()
  const items = props.installedIndicators.filter(item => !item.common)
  try {
    const results = (await Promise.all(items.map(item => requestFormulaDrawing(item, bars, requestRevision)))).filter(Boolean)
    const responseEpoch = results.find(result => result.epoch)?.epoch
    if (responseEpoch && !realtimeEpoch) acceptRealtimeEpoch(responseEpoch)
    if (responseEpoch && responseEpoch !== realtimeEpoch) return
    if (results.some(result => result.epoch && result.epoch !== realtimeEpoch)) return
    const latestResponseRevision = results.reduce((latest, result) => Math.max(latest, result.revision), requestRevision)
    if (runToken !== formulaRunToken || generation !== drawVersion || latestResponseRevision < realtimeRevision) return
    results.forEach(applyLayerResult)
    setCandleMode(renderedItems)
  } finally {
    if (runToken !== formulaRunToken) return
    formulaInFlight = false
    if (formulaPendingRevision && !formulaTimer) {
      formulaTimer = window.setTimeout(() => {
        formulaTimer = undefined
        runFormulaRefresh()
      }, 850)
    }
  }
}

function processRealtimePayload(payload, payloadGeneration = realtimeStatusGeneration) {
  if (!payload || !props.symbol || payload.symbol !== props.symbol.code.toUpperCase() || payload.period !== props.period) return
  if (payloadGeneration !== realtimeStatusGeneration) return
  if (!acceptRealtimeVersion(payload)) {
    setRealtimeStatus('unavailable')
    return
  }
  const revision = Number(payload.revision || 0)
  if (revision && revision < realtimeRevision) return
  realtimeRevision = Math.max(realtimeRevision, revision)
  realtimeStatus.value = payload.status || realtimeStatus.value
  const hasClosedBar = Number.isFinite(Number(payload.last_closed_bar?.time))
  const hasCurrentBar = Number.isFinite(Number(payload.bar?.time))
  if (!hasClosedBar && !hasCurrentBar) return
  loadedBars = mergeRealtimeBars(loadedBars, payload)
  if (candleSeries) {
    if (hasClosedBar) candleSeries.setData(loadedBars)
    else candleSeries.update({ ...payload.bar, time: Number(payload.bar.time) })
  }
  refreshBuiltInLayers()
  queueFormulaRefresh(realtimeRevision)
}

function queueRealtimePayload(payload) {
  if (!payload || !props.symbol || payload.symbol !== props.symbol.code.toUpperCase() || payload.period !== props.period) return
  if (!acceptRealtimeVersion(payload)) {
    setRealtimeStatus('unavailable')
    return
  }
  const revision = Number(payload.revision || 0)
  if (revision && revision < realtimeRevision) return
  if (payload.type === 'status' || (payload.status && !payload.bar && !payload.last_closed_bar)) {
    setRealtimeStatus(payload.status)
    return
  }
  if (realtimeUiBuffer) realtimeUiBuffer.push(payload, realtimeStatusGeneration)
  else processRealtimePayload(payload, realtimeStatusGeneration)
}

function connectRealtime() {
  if (!props.symbol || !props.period || typeof EventSource === 'undefined') {
    setRealtimeStatus('unavailable')
    return
  }
  const generation = ++streamGeneration
  setRealtimeStatus('connecting')
  const url = `http://127.0.0.1:8003/api/realtime/market-stream/${encodeURIComponent(props.symbol.code)}/?period=${encodeURIComponent(props.period)}`
  const source = new EventSource(url, { withCredentials: true })
  eventSource = source
  const handle = event => {
    if (generation !== streamGeneration) return
    try { queueRealtimePayload(JSON.parse(event.data)) } catch { setRealtimeStatus('unavailable') }
  }
  source.addEventListener('snapshot', handle)
  source.addEventListener('bar', handle)
  source.addEventListener('status', handle)
  source.onmessage = handle
  source.onerror = () => {
    if (generation !== streamGeneration) return
    setRealtimeStatus(source.readyState === EventSource.CLOSED ? 'unavailable' : 'reconnecting')
  }
}

function disconnectRealtime() {
  streamGeneration += 1
  eventSource?.close()
  eventSource = undefined
  realtimeUiBuffer?.clear()
  cancelFormulaWork()
}

function handleVisibilityChange() {
  if (document.hidden) {
    disconnectRealtime()
    return
  }
  if (props.symbol && chart) {
    connectRealtime()
  }
}

async function draw(options = {}) {
  if (!el.value || !props.symbol) return
  const version = ++drawVersion
  disconnectRealtime()
  const key = chartKey()
  subTitlePositions.value = []
  historyStatus.value = ''
  realtimeRevision = 0
  renderedItems = []
  layerRefs = new Map()
  if (panePointerUp) el.value.removeEventListener('pointerup', panePointerUp)
  chart?.remove()
  candleSeries = undefined
  marketCandleSeries = false

  if (!options.keepBars || loadedKey !== key || !loadedBars.length) {
    loadedKey = key
    loadedBars = []
    hasMoreHistory = false
    try {
      const payload = await fetchKlinePage()
      if (payload.bars?.length) {
        loadedBars = orderedUniqueBars(payload.bars)
        hasMoreHistory = Boolean(payload.has_more)
      } else {
        historyStatus.value = '行情不可用：富途 OpenD 未返回真实 K 线'
      }
    } catch (error) {
      historyStatus.value = `行情加载失败：${error.message}`
    }
  }
  // Never substitute generated candles for a failed market-data request.
  const bars = loadedBars
  if (version !== drawVersion || !el.value) return

  const rendered = await requestDrawings(bars, realtimeRevision)
  if (version !== drawVersion || !el.value) return
  renderedItems = rendered

  const savedHeights = savedSubPaneHeights()
  const subHeight = rendered.filter(result => result.item.placement === 'sub')
    .reduce((sum, result) => sum + (savedHeights[result.item.code] || 150), 0)
  const chartHeight = 460 + subHeight
  el.value.style.height = `${chartHeight}px`
  chart = createChart(el.value, {
    width: el.value.clientWidth, height: chartHeight,
    layout: { background: { color: '#101722' }, textColor: '#8798ab', panes: { separatorColor: '#263241' } },
    grid: { vertLines: { color: '#1a2634' }, horzLines: { color: '#1a2634' } },
    rightPriceScale: { borderColor: '#263241' }, timeScale: { borderColor: '#263241', timeVisible: true },
  })
  const formulaCandleLayer = formulaOwnsMainCandles(rendered, bars)
  const candle = chart.addSeries(CandlestickSeries, formulaCandleLayer ? {
    upColor: 'transparent', downColor: 'transparent', borderVisible: false,
    wickUpColor: 'transparent', wickDownColor: 'transparent',
  } : {
    upColor: props.marketColorTokens.up, downColor: props.marketColorTokens.down, borderVisible: false,
    wickUpColor: props.marketColorTokens.up, wickDownColor: props.marketColorTokens.down,
  }, 0)
  candleSeries = candle
  marketCandleSeries = !formulaCandleLayer
  candle.setData(bars)

  let nextPane = 1
  for (const result of rendered) {
    const pane = result.item.placement === 'main' ? 0 : nextPane++
    layerRefs.set(result.item.code, installLayer(result, pane))
    if (result.item.placement === 'sub') chart.panes()[pane]?.setHeight(savedHeights[result.item.code] || 150)
  }
  chart.panes()[0]?.setHeight(440)
  panePointerUp = () => window.setTimeout(() => {
    saveSubPaneHeights(renderedItems)
    syncSubTitlePositions(renderedItems)
  }, 0)
  el.value.addEventListener('pointerup', panePointerUp)
  let historyWatchReady = false
  chart.timeScale().subscribeVisibleLogicalRangeChange(range => {
    if (historyWatchReady && range && range.from < 80) loadOlderBars()
  })
  requestAnimationFrame(() => requestAnimationFrame(() => {
    if (version === drawVersion && el.value) syncSubTitlePositions(renderedItems)
  }))
  if (options.visibleRange) chart.timeScale().setVisibleLogicalRange(options.visibleRange)
  else chart.timeScale().fitContent()
  requestAnimationFrame(() => { historyWatchReady = true })
  connectRealtime()
}

async function loadOlderBars() {
  if (loadingHistory || !hasMoreHistory || !loadedBars.length) return
  const key = chartKey()
  const currentChart = chart
  const range = chart?.timeScale().getVisibleLogicalRange()
  loadingHistory = true
  historyStatus.value = '正在加载更早的 K 线…'
  try {
    const payload = await fetchKlinePage(loadedBars[0].time)
    if (key !== chartKey() || currentChart !== chart) return
    const previousLength = loadedBars.length
    loadedBars = orderedUniqueBars([...payload.bars, ...loadedBars])
    const added = loadedBars.length - previousLength
    hasMoreHistory = Boolean(payload.has_more) && added > 0
    historyStatus.value = added ? `已加载 ${loadedBars.length} 根 K 线` : '没有更早的 K 线数据'
    if (added) {
      const visibleRange = range && { from: range.from + added, to: range.to + added }
      await scheduleDraw({ keepBars: true, visibleRange })
    }
  } catch (error) {
    hasMoreHistory = false
    historyStatus.value = `无法加载更早 K 线：${error.message}`
  } finally {
    loadingHistory = false
  }
}

function scheduleDraw(options) {
  drawQueue = drawQueue.catch(() => {}).then(() => draw(options))
  return drawQueue
}

onMounted(async () => {
  await nextTick()
  realtimeUiBuffer = createRealtimeUiBuffer({
    flushMs: 300,
    onFlush: processRealtimePayload,
    isPaused: () => document.hidden,
  })
  visibilityHandler = handleVisibilityChange
  document.addEventListener('visibilitychange', visibilityHandler)
  scheduleDraw()
  resize = new ResizeObserver(() => chart?.applyOptions({ width: el.value.clientWidth }))
  resize.observe(el.value)
})
onBeforeUnmount(() => {
  disconnectRealtime()
  if (visibilityHandler) document.removeEventListener('visibilitychange', visibilityHandler)
  if (panePointerUp) el.value?.removeEventListener('pointerup', panePointerUp)
  resize?.disconnect()
  chart?.remove()
})
watch(() => [props.symbol, props.period, props.installedIndicators], scheduleDraw, { deep: true })
watch(() => props.marketColorTokens, tokens => {
  if (marketCandleSeries && candleSeries && tokens) candleSeries.applyOptions({ upColor: tokens.up, downColor: tokens.down, wickUpColor: tokens.up, wickDownColor: tokens.down })
}, { deep: true })
</script>

<template>
  <div class="chart-wrap">
    <div ref="el" class="chart" />
    <div class="main-titles"><b v-for="(item, index) in mainIndicators" :key="item.code" :style="{ top: `${10 + index * 26}px` }">{{ item.name }}</b></div>
    <div class="sub-titles"><b v-for="item in subTitlePositions" :key="item.code" :style="{ top: `${item.top}px` }">{{ item.name }}</b></div>
    <div class="realtime-status" :class="`status-${realtimeStatus}`" role="status" aria-live="polite">{{ realtimeStatusText }}</div>
    <div v-if="historyStatus" class="history-status">{{ historyStatus }}</div>
    <div v-if="renderErrors.length" class="chart-errors"><span v-for="message in renderErrors" :key="message">{{ message }}</span></div>
  </div>
</template>

<style scoped>
.chart-wrap { position: relative }
.chart { width: 100%; min-height: 460px }
.main-titles, .sub-titles { position: absolute; inset: 0; z-index: 5; pointer-events: none }
.main-titles b, .sub-titles b { position: absolute; left: 9px; color: #f4f7fb; font-size: 14px; font-weight: 700; line-height: 1.1; letter-spacing: .2px; text-shadow: 0 1px 3px #000 }
.realtime-status { position: absolute; top: 9px; right: 12px; z-index: 6; color: #94a3b8; font-size: 11px; pointer-events: none; text-shadow: 0 1px 3px #000 }
.status-live { color: #5eead4 }
.status-reconnecting, .status-connecting { color: #facc15 }
.status-unavailable { color: #94a3b8 }
.chart-errors { position: absolute; top: 38px; right: 12px; z-index: 6; display: grid; gap: 4px; max-width: 48%; color: #fecaca; font-size: 12px; text-align: right; pointer-events: none }
.chart-errors span { padding: 5px 7px; border: 1px solid #7f1d1d; border-radius: 4px; background: rgba(69, 10, 10, .85) }
.history-status { position: absolute; right: 12px; bottom: 8px; z-index: 6; color: #94a3b8; font-size: 12px; pointer-events: none; text-shadow: 0 1px 3px #000 }
@media (prefers-reduced-motion: reduce) {
  .realtime-status { transition: none }
}
</style>
