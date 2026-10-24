<script setup>
import { API_BASE } from '../apiBase'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { CandlestickSeries, LineSeries, createChart } from 'lightweight-charts'
import { TongdaxinStickPrimitive } from '../indicators/TongdaxinStickPrimitive'
import { TongdaxinTextPrimitive } from '../indicators/TongdaxinTextPrimitive'
import { TongdaxinFixedTextPrimitive } from '../indicators/TongdaxinFixedTextPrimitive'
import { commonDrawing } from '../indicators/commonIndicators'
import { hiddenIndicatorScaleId } from '../indicators/priceScalePolicy.mjs'
import { createRealtimeUiBuffer, mergeHistoricalTail, mergeRealtimePayload } from '../realtime/realtimeUiBuffer.mjs'
import { isFormulaResponseGenerationSafe, reconcileRealtimeVersion } from '../realtime/realtimeGeneration.mjs'
import { settleHistoryReconcile } from '../realtime/historyRecovery.mjs'
import { hasChangedBarSource } from '../realtime/sourceSwitch.mjs'
import { isCurrentFormulaResult, shouldScheduleFormulaRefresh } from '../realtime/formulaRefreshScheduler.mjs'
import { classifyChartUpdate, diffIndicatorSets, indicatorKey } from '../realtime/chartUpdatePolicy.mjs'
import { createChartTimeFormatters } from '../realtime/chartTimeFormat.mjs'

const emit = defineEmits(['indicator-denied', 'pane-heights-changed'])
const props = defineProps({
  symbol: Object,
  period: String,
  installedIndicators: { type: Array, default: () => [] },
  paneHeights: { type: Object, default: () => ({}) },
  marketColorTokens: { type: Object, default: () => ({ up: '#ef5350', down: '#20bd92' }) },
})

const el = ref(null)
const mainIndicators = computed(() => props.installedIndicators.filter(item => item.placement === 'main'))
// Reuse the hidden overlay-scale condition for hover values; never turn off the price-to-coordinate scale.
const hideYiQiSanQingAxis = item => Boolean(hiddenIndicatorScaleId(item))
const subTitlePositions = ref([])
const hiddenSubCrosshairValue = ref(null)
const renderErrors = ref([])
const historyStatus = ref('')
const realtimeStatus = ref('connecting')
const realtimeDataStatus = ref('')
const realtimeStatusText = computed(() => {
  if (realtimeDataStatus.value === 'delayed' && ['live', 'polling'].includes(realtimeStatus.value)) return '● 延迟行情'
  if (realtimeDataStatus.value === 'historical') return '历史行情'
  return ({
  connecting: '连接实时行情…',
  live: '● 实时',
  polling: '轮询中',
  reconnecting: '重连中',
  not_configured: '未配置实时行情源',
  unavailable: '行情暂不可用',
  }[realtimeStatus.value] || '实时状态未知')
})

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
let loadedSource = ''
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
let formulaRefreshPending = false
let formulaRunToken = 0
let indicatorRefreshTimer
let indicatorRefreshInFlight = false
let indicatorRefreshPending = false
let indicatorRefreshVersion = 0
const drawingRequestCache = new Map()
let lastChartState
let realtimeUiBuffer
let latestRealtimePayload
let latestRealtimePayloadGeneration = 0
let realtimePayloadSequence = 0
let historyReconcileInFlight = false
let historyReconcilePendingGeneration = null
let pendingRecoveryLiveStatus = false
let needsHistoryReconcile = false
let historyReconcileRetryTimer
let providerLive = false
const HISTORY_RECONCILE_RETRY_MS = 2000
// Match Crypto chart candle shades without changing the user's red/green direction.
const cryptoCandleColor = color => ({ '#ef6671': '#ef5350', '#3acba3': '#20bd92' })[String(color || '').toLowerCase()] || color

const backgroundStick = item => item.layer === 'background'
// The server-owned account layout replaces the old, browser-only height store.
// Visitors may adjust panes for the current tab, without storing them on the server.
let sessionPaneHeights = {}
const savedSubPaneHeights = () => ({ ...sessionPaneHeights, ...(props.paneHeights || {}) })

function syncSubTitlePositions(rendered) {
  if (!chart || !el.value) return
  const chartTop = el.value.getBoundingClientRect().top
  let paneIndex = 1
  subTitlePositions.value = rendered.filter(result => result.item.placement === 'sub').map(result => {
    const top = chart.panes()[paneIndex++]?.getHTMLElement()?.getBoundingClientRect().top
    return { code: result.item.code, name: result.item.name, top: (top === undefined ? 0 : top - chartTop) + 6 }
  })
}

// The hidden pane's full values are still readable on hover / mobile long press.
function updateHiddenSubCrosshairValue(param) {
  const result = renderedItems.find(entry => hideYiQiSanQingAxis(entry.item) && layerRefs.get(entry.item.code)?.pane === param.paneIndex)
  if (!result || !param.point || param.time == null) {
    hiddenSubCrosshairValue.value = null
    return
  }
  const layer = layerRefs.get(result.item.code)
  const data = [...layer.lines, layer.anchor].map(series => param.seriesData.get(series))
    .find(point => Number.isFinite(point?.value))
  if (!data) {
    hiddenSubCrosshairValue.value = null
    return
  }
  const title = subTitlePositions.value.find(position => position.code === result.item.code)
  hiddenSubCrosshairValue.value = { top: title?.top ?? 6, text: String(data.value) }
}

function saveSubPaneHeights(rendered) {
  // Never mutate a Vue prop: the parent compares old/new heights to decide whether to save.
  const heights = { ...savedSubPaneHeights() }
  let paneIndex = 1
  rendered.filter(result => result.item.placement === 'sub').forEach(result => {
    heights[result.item.code] = chart?.panes()[paneIndex++]?.getHeight() || 150
  })
  sessionPaneHeights = heights
  emit('pane-heights-changed', heights)
}

async function requestFormulaDrawing(item, bars, revision = 0) {
  try {
    const params = new URLSearchParams({ period: props.period, count: String(bars.length), revision: String(revision) })
    if (realtimeEpoch) params.set('epoch', realtimeEpoch)
    const reply = await fetch(`${API_BASE}/api/indicator-render/${encodeURIComponent(item.code)}/${props.symbol.code}/?${params}`, { credentials: 'include', cache: 'no-store' })
    const payload = await reply.json()
    if ((reply.status === 403 && payload.code === 'indicator_not_allowed') || (reply.status === 404 && payload.code === 'fixed_indicator_disabled')) {
      emit('indicator-denied', item)
      return null
    }
    if (reply.ok) return { item, drawing: payload.drawing, epoch: payload.epoch || '', revision: Number(payload.revision || revision) }
    renderErrors.value.push(`${item.name}：${payload.error || '指标计算失败'}`)
  } catch (error) {
    if (error?.name === 'AbortError') return null
    renderErrors.value.push(`${item.name}：无法连接指标计算服务`)
  }
  return null
}

async function requestDrawing(item, bars, revision = 0) {
  if (item.common) return { item, drawing: commonDrawing(item.code, bars), revision }
  return requestFormulaDrawing(item, bars, revision)
}

function requestDrawingOnce(item, bars, revision = 0) {
  const key = `${chartKey()}|${indicatorKey(item)}|${realtimeEpoch}|${revision}`
  if (drawingRequestCache.has(key)) return drawingRequestCache.get(key)
  const request = requestDrawing(item, bars, revision).finally(() => {
    if (drawingRequestCache.get(key) === request) drawingRequestCache.delete(key)
  })
  drawingRequestCache.set(key, request)
  return request
}

async function requestDrawings(bars, revision = 0) {
  renderErrors.value = []
  const requestedEpoch = realtimeEpoch
  const results = (await Promise.all(props.installedIndicators.map(item => requestDrawingOnce(item, bars, revision)))).filter(Boolean)
  const responseEpoch = results.find(result => result.epoch)?.epoch
  if (responseEpoch && !acceptFormulaResponseEpoch(responseEpoch, requestedEpoch)) return []
  if (responseEpoch && results.some(result => result.epoch && result.epoch !== responseEpoch)) return []
  return results
}

const chartKey = () => `${props.symbol?.code || ''}:${props.period || ''}`
const orderedUniqueBars = bars => [...new Map(bars.map(bar => [bar.time, bar])).values()].sort((left, right) => left.time - right.time)

function invalidateFormulaResults({ clearPending = true } = {}) {
  if (formulaTimer) window.clearTimeout(formulaTimer)
  formulaTimer = undefined
  if (clearPending) {
    formulaPendingRevision = 0
    formulaRefreshPending = false
  }
  formulaRunToken += 1
}

function cancelFormulaWork() {
  invalidateFormulaResults()
}

function clearHistoryReconcileRetry() {
  if (historyReconcileRetryTimer) window.clearTimeout(historyReconcileRetryTimer)
  historyReconcileRetryTimer = undefined
}

function markHistoryReconcileNeeded() {
  needsHistoryReconcile = true
  if (providerLive && realtimeStatus.value === 'live') realtimeStatus.value = 'reconnecting'
}

function cancelHistoryReconcile({ clearLatch = false } = {}) {
  clearHistoryReconcileRetry()
  historyReconcilePendingGeneration = null
  if (clearLatch) needsHistoryReconcile = false
}

function scheduleHistoryReconcileRetry() {
  if (historyReconcileRetryTimer || document.hidden || !needsHistoryReconcile) return
  historyReconcileRetryTimer = window.setTimeout(() => {
    historyReconcileRetryTimer = undefined
    if (document.hidden || !needsHistoryReconcile || !props.symbol || !chart) return
    requestHistoryTailReconcile(streamGeneration)
  }, HISTORY_RECONCILE_RETRY_MS)
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
  latestRealtimePayload = undefined
  latestRealtimePayloadGeneration = 0
  realtimePayloadSequence = 0
  realtimeStatusGeneration += 1
  realtimeUiBuffer?.clear()
  cancelFormulaWork()
  markHistoryReconcileNeeded()
  return true
}

function setRealtimeStatus(status) {
  if (!status) return
  if (status === 'live') providerLive = true
  else if (status === 'unavailable' || status === 'not_configured' || status === 'connecting' || status === 'reconnecting') providerLive = false
  if (status === 'live' && (needsHistoryReconcile || historyReconcileInFlight)) {
    pendingRecoveryLiveStatus = true
    realtimeStatus.value = 'reconnecting'
    return
  }
  if (status !== 'live') pendingRecoveryLiveStatus = false
  if (status === 'connecting' || status === 'reconnecting' || status === 'unavailable' || status === 'not_configured') {
    realtimeStatusGeneration += 1
    realtimeUiBuffer?.clear()
  }
  realtimeStatus.value = status
}

function acceptRealtimeVersion(payload) {
  const hadEpoch = Boolean(realtimeEpoch)
  const decision = reconcileRealtimeVersion(realtimeEpoch, realtimeRevision, payload)
  if (!decision.accepted) return decision
  if (decision.changed) acceptRealtimeEpoch(decision.epoch)
  realtimeEpoch = decision.epoch
  realtimeRevision = decision.revision
  if (decision.changed && hadEpoch && chart && !document.hidden) requestHistoryTailReconcile()
  return decision
}

function acceptFormulaResponseEpoch(responseEpoch, requestedEpoch) {
  if (!responseEpoch) return true
  if (!isFormulaResponseGenerationSafe(realtimeEpoch, requestedEpoch, responseEpoch)) return false
  if (!realtimeEpoch || responseEpoch !== realtimeEpoch) acceptRealtimeEpoch(responseEpoch)
  return responseEpoch === realtimeEpoch
}

async function fetchKlinePage(before = null) {
  const query = new URLSearchParams({ period: props.period, count: '1000' })
  if (before) query.set('before', String(before))
  const reply = await fetch(`${API_BASE}/api/kline/${props.symbol.code}/?${query}`, { credentials: 'include' })
  const payload = await reply.json()
  if (!reply.ok) throw new Error(payload.error || '行情服务不可用')
  return payload
}

function addLine(color, data, pane, style = 'solid', width = 1, priceScaleId) {
  const lineWidth = Math.max(1, Math.min(9, Number(width) || 1))
  const markerStyle = style === 'circle-dot'
  const series = chart.addSeries(LineSeries, {
    color, lineWidth,
    lineStyle: style === 'dotted' ? 1 : style === 'point-dot' ? 4 : style === 'cross-dot' ? 4 : 0,
    pointMarkersVisible: markerStyle,
    pointMarkersRadius: markerStyle ? Math.max(2, Math.min(5, lineWidth + 1)) : undefined,
    priceLineVisible: false, lastValueVisible: false,
    ...(priceScaleId ? { priceScaleId } : {}),
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

function addFormulaAnchor(drawing, pane, priceScaleId) {
  const anchor = chart.addSeries(LineSeries, {
    color: 'transparent', lineVisible: false, priceLineVisible: false, lastValueVisible: false,
    ...(priceScaleId ? { priceScaleId } : {}),
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
    upColor: cryptoCandleColor(props.marketColorTokens.up), downColor: cryptoCandleColor(props.marketColorTokens.down), borderVisible: false,
    wickUpColor: cryptoCandleColor(props.marketColorTokens.up), wickDownColor: cryptoCandleColor(props.marketColorTokens.down),
  })
  marketCandleSeries = !formulaCandleLayer
}

function installLayer(result, pane) {
  // Attach all series and the STICKLINE/text anchor to the same hidden overlay
  // scale; hiding the normal right scale broke primitive rendering in V1.1.7.
  const priceScaleId = hiddenIndicatorScaleId(result.item)
  const lines = result.drawing.lines.map(item => addLine(item.color, item.data, pane, item.style, item.width, priceScaleId))
  const layerAnchor = result.item.placement === 'main' ? candleSeries : (lines[0] || addFormulaAnchor(result.drawing, pane, priceScaleId))
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
  formulaRefreshPending = true
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
  const requestedEpoch = realtimeEpoch
  formulaPendingRevision = 0
  formulaRefreshPending = false
  const bars = loadedBars.slice()
  const items = props.installedIndicators.filter(item => !item.common)
  try {
    const results = (await Promise.all(items.map(item => requestFormulaDrawing(item, bars, requestRevision)))).filter(Boolean)
    const responseEpoch = results.find(result => result.epoch)?.epoch
    if (responseEpoch && !acceptFormulaResponseEpoch(responseEpoch, requestedEpoch)) return
    if (results.some(result => result.epoch && result.epoch !== realtimeEpoch)) return
    const latestResponseRevision = results.reduce((latest, result) => Math.max(latest, result.revision), requestRevision)
    if (!isCurrentFormulaResult({ runToken, currentRunToken: formulaRunToken, generation, currentGeneration: drawVersion }) || latestResponseRevision < realtimeRevision) return
    results.forEach(applyLayerResult)
    setCandleMode(renderedItems)
  } finally {
    formulaInFlight = false
    if (shouldScheduleFormulaRefresh({
      pendingRevision: formulaPendingRevision,
      refreshPending: formulaRefreshPending,
      timerActive: Boolean(formulaTimer),
      hasChart: Boolean(chart),
      hasSymbol: Boolean(props.symbol),
    })) {
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
  if (hasChangedBarSource(loadedSource, payload)) {
    latestRealtimePayload = undefined
    markHistoryReconcileNeeded()
    requestHistoryTailReconcile()
    return
  }
  const version = acceptRealtimeVersion(payload)
  if (!version.accepted) {
    if (version.reason !== 'stale_revision') setRealtimeStatus('unavailable')
    return
  }
  if (payload.status) setRealtimeStatus(payload.status)
  if (payload.data_status || payload.bar?.data_status) realtimeDataStatus.value = payload.data_status || payload.bar.data_status
  const hasClosedBar = Number.isFinite(Number(payload.last_closed_bar?.time))
  const hasCurrentBar = Number.isFinite(Number(payload.bar?.time))
  if (!hasClosedBar && !hasCurrentBar) return
  const merged = mergeRealtimePayload(loadedBars, payload)
  loadedBars = merged.bars
  if (candleSeries) {
    if (merged.closedChanged) candleSeries.setData(loadedBars)
    else if (merged.currentBar && merged.currentChanged) candleSeries.update(merged.currentBar)
  }
  refreshBuiltInLayers()
  queueFormulaRefresh(realtimeRevision)
}

function queueRealtimePayload(payload) {
  if (!payload || !props.symbol || payload.symbol !== props.symbol.code.toUpperCase() || payload.period !== props.period) return
  if (hasChangedBarSource(loadedSource, payload)) {
    latestRealtimePayload = undefined
    markHistoryReconcileNeeded()
    requestHistoryTailReconcile()
    return
  }
  const version = acceptRealtimeVersion(payload)
  if (!version.accepted) {
    if (version.reason !== 'stale_revision') setRealtimeStatus('unavailable')
    return
  }
  if (payload.bar || payload.last_closed_bar) {
    latestRealtimePayload = payload
    latestRealtimePayloadGeneration = streamGeneration
    realtimePayloadSequence += 1
  }
  if (payload.type === 'status' || (payload.status && !payload.bar && !payload.last_closed_bar)) {
    const wasReconnecting = realtimeStatus.value === 'reconnecting'
    if (payload.status === 'live' && (wasReconnecting || needsHistoryReconcile)) markHistoryReconcileNeeded()
    setRealtimeStatus(payload.status)
    if (payload.data_status) realtimeDataStatus.value = payload.data_status
    if (payload.status === 'live' && (wasReconnecting || needsHistoryReconcile) && !historyReconcileInFlight) {
      requestHistoryTailReconcile()
    }
    return
  }
  if (realtimeUiBuffer) realtimeUiBuffer.push(payload, realtimeStatusGeneration)
  else processRealtimePayload(payload, realtimeStatusGeneration)
}

async function reconcileHistoryTail(streamGenerationAtStart = streamGeneration) {
  if (historyReconcileInFlight) {
    historyReconcilePendingGeneration = streamGenerationAtStart
    return
  }
  const version = drawVersion
  const key = chartKey()
  historyReconcileInFlight = true
  pendingRecoveryLiveStatus = false
  clearHistoryReconcileRetry()
  realtimeStatus.value = 'reconnecting'
  let succeeded = false
  let current = true
  try {
    const query = new URLSearchParams({ period: props.period, count: '100' })
    const reply = await fetch(`${API_BASE}/api/kline/${encodeURIComponent(props.symbol.code)}/?${query}`, { credentials: 'include' })
    let payload = await reply.json()
    if (!reply.ok) throw new Error(payload.error || '行情历史不可用')
    if (version !== drawVersion || key !== chartKey() || streamGenerationAtStart !== streamGeneration) {
      current = false
      return
    }
    const sourceChanged = Boolean(loadedSource && payload.source && payload.source !== loadedSource)
    // Replacing the source requires its *complete* historical window, not
    // the short tail used for ordinary reconnect recovery.
    if (sourceChanged) payload = await fetchKlinePage()
    if (version !== drawVersion || key !== chartKey() || streamGenerationAtStart !== streamGeneration) {
      current = false
      return
    }
    if (!Array.isArray(payload.bars) || (loadedBars.length > 0 && payload.bars.length === 0)) {
      throw new Error('行情历史返回空尾部，恢复尚未完成')
    }
    const latestPayload = latestRealtimePayload
      && latestRealtimePayloadGeneration === streamGenerationAtStart
      && latestRealtimePayload.symbol === props.symbol.code.toUpperCase()
      && latestRealtimePayload.period === props.period
      && String(latestRealtimePayload.epoch || '') === String(realtimeEpoch || '')
      ? latestRealtimePayload
      : null
    const merged = sourceChanged
      ? { bars: orderedUniqueBars(payload.bars), changed: true }
      : mergeHistoricalTail(loadedBars, payload.bars, latestPayload)
    const visibleRange = chart?.timeScale().getVisibleLogicalRange()
    loadedBars = merged.bars
    loadedSource = payload.source || loadedSource
    if (merged.changed) {
      invalidateFormulaResults({ clearPending: false })
      if (candleSeries) {
        candleSeries.setData(loadedBars)
        if (sourceChanged && loadedBars.length) {
          chart?.timeScale().setVisibleLogicalRange({ from: Math.max(0, loadedBars.length - 90), to: loadedBars.length - 1 })
        } else if (visibleRange) chart?.timeScale().setVisibleLogicalRange(visibleRange)
      }
      refreshBuiltInLayers()
      queueFormulaRefresh(realtimeRevision)
    }
    succeeded = true
  } catch {
    if (version === drawVersion && key === chartKey() && streamGenerationAtStart === streamGeneration) {
      needsHistoryReconcile = true
      if (realtimeStatus.value !== 'unavailable') realtimeStatus.value = 'reconnecting'
      scheduleHistoryReconcileRetry()
    } else {
      current = false
    }
  } finally {
    historyReconcileInFlight = false
    const recovery = settleHistoryReconcile({
      current,
      pendingGeneration: historyReconcilePendingGeneration,
      currentGeneration: streamGeneration,
      needsHistoryReconcile,
      hidden: document.hidden,
      hasChart: Boolean(chart),
      hasSymbol: Boolean(props.symbol),
    })
    historyReconcilePendingGeneration = null
    if (recovery.action === 'reconcile') {
      needsHistoryReconcile = true
      requestHistoryTailReconcile(recovery.generation)
    } else if (recovery.action === 'retry') {
      needsHistoryReconcile = true
      scheduleHistoryReconcileRetry()
    } else if (recovery.action === 'complete' && succeeded) {
      needsHistoryReconcile = false
      clearHistoryReconcileRetry()
      pendingRecoveryLiveStatus = false
      if (providerLive) realtimeStatus.value = 'live'
    }
  }
}

function requestHistoryTailReconcile(streamGenerationAtStart = streamGeneration) {
  markHistoryReconcileNeeded()
  if (historyReconcileInFlight) {
    historyReconcilePendingGeneration = streamGenerationAtStart
    return
  }
  void reconcileHistoryTail(streamGenerationAtStart)
}

function connectRealtime({ reconcileHistory = false } = {}) {
  if (!props.symbol || !props.period || typeof EventSource === 'undefined') {
    setRealtimeStatus('unavailable')
    return
  }
  const generation = ++streamGeneration
  let needsRecovery = reconcileHistory
  if (reconcileHistory) markHistoryReconcileNeeded()
  realtimeDataStatus.value = ''
  setRealtimeStatus('connecting')
  const url = `${API_BASE}/api/realtime/market-stream/${encodeURIComponent(props.symbol.code)}/?period=${encodeURIComponent(props.period)}`
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
  source.onopen = () => {
    if (generation !== streamGeneration || !needsRecovery) return
    needsRecovery = false
    markHistoryReconcileNeeded()
    requestHistoryTailReconcile(generation)
  }
  source.onerror = () => {
    if (generation !== streamGeneration) return
    needsRecovery = true
    markHistoryReconcileNeeded()
    setRealtimeStatus(source.readyState === EventSource.CLOSED ? 'unavailable' : 'reconnecting')
  }
}

function disconnectRealtime({ clearRecovery = false } = {}) {
  streamGeneration += 1
  eventSource?.close()
  eventSource = undefined
  realtimeUiBuffer?.clear()
  cancelHistoryReconcile({ clearLatch: clearRecovery })
  cancelFormulaWork()
  latestRealtimePayload = undefined
  latestRealtimePayloadGeneration = 0
  realtimePayloadSequence = 0
}

function handleVisibilityChange() {
  if (document.hidden) {
    disconnectRealtime()
    return
  }
  if (props.symbol && chart) {
    markHistoryReconcileNeeded()
    connectRealtime({ reconcileHistory: true })
  }
}

async function draw(options = {}) {
  if (!el.value || !props.symbol) return
  const version = ++drawVersion
  cancelIndicatorRefresh()
  disconnectRealtime({ clearRecovery: true })
  const key = chartKey()
  subTitlePositions.value = []
  historyStatus.value = ''
  realtimeRevision = 0
  latestRealtimePayload = undefined
  latestRealtimePayloadGeneration = 0
  realtimePayloadSequence = 0
  renderedItems = []
  layerRefs = new Map()
  if (panePointerUp) el.value.removeEventListener('pointerup', panePointerUp)
  chart?.remove()
  candleSeries = undefined
  marketCandleSeries = false

  if (!options.keepBars || loadedKey !== key || !loadedBars.length) {
    loadedKey = key
    loadedBars = []
    loadedSource = ''
    hasMoreHistory = false
    try {
      const payload = await fetchKlinePage()
      if (payload.bars?.length) {
        loadedBars = orderedUniqueBars(payload.bars)
        loadedSource = payload.source || ''
        hasMoreHistory = Boolean(payload.has_more)
        if (payload.data_status) realtimeDataStatus.value = payload.data_status
      } else {
        historyStatus.value = '行情不可用：统一行情源未返回真实 K 线'
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
  // Calendar labels are dates of the exchange, not of the browser's locale.
  const marketZone = {
    SH: 'Asia/Shanghai', SZ: 'Asia/Shanghai', HK: 'Asia/Hong_Kong',
    US: 'America/New_York', CC: 'UTC',
  }[String(props.symbol?.code || '').split('.')[0]] || 'UTC'
  const chartTime = createChartTimeFormatters(props.period, marketZone)
  chart = createChart(el.value, {
    width: el.value.clientWidth, height: chartHeight,
    layout: { background: { color: '#080d17' }, textColor: '#8798ab', panes: { separatorColor: '#263241' } },
    grid: { vertLines: { color: '#172234' }, horzLines: { color: '#172234' } },
    rightPriceScale: { borderColor: '#263241' },
    localization: { timeFormatter: chartTime.timeFormatter },
    timeScale: { borderColor: '#263241', timeVisible: chartTime.timeVisible, tickMarkFormatter: chartTime.tickMarkFormatter, secondsVisible: false, rightOffset: 4, barSpacing: 7, minBarSpacing: 2 },
    crosshair: { mode: 0 },
    handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
    handleScale: { axisPressedMouseMove: true, mouseWheel: true, pinch: true },
    kineticScroll: { mouse: true, touch: true },
  })
  chart.subscribeCrosshairMove(updateHiddenSubCrosshairValue)
  const formulaCandleLayer = formulaOwnsMainCandles(rendered, bars)
  const candle = chart.addSeries(CandlestickSeries, formulaCandleLayer ? {
    upColor: 'transparent', downColor: 'transparent', borderVisible: false,
    wickUpColor: 'transparent', wickDownColor: 'transparent',
  } : {
    upColor: cryptoCandleColor(props.marketColorTokens.up), downColor: cryptoCandleColor(props.marketColorTokens.down), borderVisible: false,
    wickUpColor: cryptoCandleColor(props.marketColorTokens.up), wickDownColor: cryptoCandleColor(props.marketColorTokens.down),
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
  else if (bars.length > 90) chart.timeScale().setVisibleLogicalRange({ from: bars.length - 90, to: bars.length - 1 })
  else chart.timeScale().fitContent()
  requestAnimationFrame(() => { historyWatchReady = true })
  connectRealtime()
  lastChartState = { symbol: props.symbol, period: props.period, indicators: props.installedIndicators }
}

function clearIndicatorLayers() {
  layerRefs.forEach(destroyLayer)
  layerRefs = new Map()
  renderedItems = []
}

function cancelIndicatorRefresh() {
  if (indicatorRefreshTimer) window.clearTimeout(indicatorRefreshTimer)
  indicatorRefreshTimer = undefined
  indicatorRefreshPending = false
  indicatorRefreshVersion += 1
}

function syncIndicatorLayout() {
  if (!chart || !el.value) return
  hiddenSubCrosshairValue.value = null
  const subCount = renderedItems.filter(result => result.item.placement === 'sub').length
  const chartHeight = 460 + subCount * 150
  el.value.style.height = `${chartHeight}px`
  chart.applyOptions({ height: chartHeight })
  chart.panes()[0]?.setHeight(440)
}

async function refreshIndicatorLayers() {
  if (!chart || !props.symbol || !loadedBars.length) return scheduleDraw()
  const version = indicatorRefreshVersion
  const generation = drawVersion
  indicatorRefreshInFlight = true
  cancelFormulaWork()
  try {
    const currentItems = props.installedIndicators.slice()
    const presentItems = renderedItems.map(result => result.item)
    const { added, removed } = diffIndicatorSets(presentItems, currentItems)
    removed.forEach(item => {
      const layer = layerRefs.get(item.code)
      if (layer) destroyLayer(layer)
      layerRefs.delete(item.code)
    })
    const currentByKey = new Map(currentItems.map(item => [indicatorKey(item), item]))
    renderedItems = renderedItems
      .filter(result => currentByKey.has(indicatorKey(result.item)))
      .map(result => ({ ...result, item: currentByKey.get(indicatorKey(result.item)) }))

    const rendered = (await Promise.all(added.map(item => requestDrawingOnce(item, loadedBars.slice(), realtimeRevision)))).filter(Boolean)
    if (version !== indicatorRefreshVersion || generation !== drawVersion || !chart || !props.symbol) return
    let nextPane = 1 + renderedItems.filter(result => result.item.placement === 'sub').length
    for (const result of rendered) {
      const pane = result.item.placement === 'main' ? 0 : nextPane++
      layerRefs.set(result.item.code, installLayer(result, pane))
      renderedItems.push(result)
      if (result.item.placement === 'sub') chart.panes()[pane]?.setHeight(savedSubPaneHeights()[result.item.code] || 150)
    }
    syncIndicatorLayout()
    setCandleMode(renderedItems)
    syncSubTitlePositions(renderedItems)
    lastChartState = { symbol: props.symbol, period: props.period, indicators: props.installedIndicators }
  } finally {
    indicatorRefreshInFlight = false
    if (indicatorRefreshPending) {
      indicatorRefreshPending = false
      scheduleIndicatorRefresh()
    }
  }
}

function scheduleIndicatorRefresh() {
  indicatorRefreshVersion += 1
  indicatorRefreshPending = true
  renderErrors.value = []
  if (indicatorRefreshInFlight || indicatorRefreshTimer) return
  indicatorRefreshTimer = window.setTimeout(() => {
    indicatorRefreshTimer = undefined
    indicatorRefreshPending = false
    void refreshIndicatorLayers()
  }, 0)
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
  // The previous symbol's queued requests must not draw after Vue replaces
  // its keyed MarketChart instance.
  drawVersion += 1
  cancelIndicatorRefresh()
  disconnectRealtime({ clearRecovery: true })
  if (visibilityHandler) document.removeEventListener('visibilitychange', visibilityHandler)
  if (panePointerUp) el.value?.removeEventListener('pointerup', panePointerUp)
  resize?.disconnect()
  chart?.remove()
})
watch(() => [props.symbol, props.period, props.installedIndicators], (next, previous) => {
  const update = classifyChartUpdate(
    lastChartState || { symbol: previous?.[0], period: previous?.[1], indicators: previous?.[2] },
    { symbol: next?.[0], period: next?.[1], indicators: next?.[2] },
  )
  if (update === 'indicators') scheduleIndicatorRefresh()
  else if (update === 'full') scheduleDraw()
})
watch(() => props.marketColorTokens, tokens => {
  if (marketCandleSeries && candleSeries && tokens) candleSeries.applyOptions({ upColor: cryptoCandleColor(tokens.up), downColor: cryptoCandleColor(tokens.down), wickUpColor: cryptoCandleColor(tokens.up), wickDownColor: cryptoCandleColor(tokens.down) })
}, { deep: true })
</script>

<template>
  <div class="chart-wrap">
    <div ref="el" class="chart" />
    <div class="main-titles"><b v-for="(item, index) in mainIndicators" :key="item.code" :style="{ top: `${10 + index * 26}px` }">{{ item.name }}</b></div>
    <div class="sub-titles"><b v-for="item in subTitlePositions" :key="item.code" :style="{ top: `${item.top}px` }">{{ item.name }}</b></div>
    <Teleport to="#market-chart-status-host">
      <span class="realtime-status" :class="`status-${realtimeStatus}`" role="status" aria-live="polite">{{ realtimeStatusText }}</span>
    </Teleport>
    <span v-if="hiddenSubCrosshairValue" class="hidden-sub-crosshair-value" :style="{ top: `${hiddenSubCrosshairValue.top}px` }" aria-hidden="true">{{ hiddenSubCrosshairValue.text }}</span>
    <div v-if="historyStatus" class="history-status">{{ historyStatus }}</div>
    <div v-if="renderErrors.length" class="chart-errors"><span v-for="message in renderErrors" :key="message">{{ message }}</span></div>
  </div>
</template>

<style scoped>
.chart-wrap { position: relative }
.chart { width: 100%; min-height: 460px }
.main-titles, .sub-titles { position: absolute; inset: 0; z-index: 5; pointer-events: none }
.main-titles b, .sub-titles b { position: absolute; left: 9px; color: #f4f7fb; font-size: 14px; font-weight: 700; line-height: 1.1; letter-spacing: .2px; text-shadow: 0 1px 3px #000 }
.realtime-status { color: #94a3b8; font-size: 11px; white-space: nowrap; pointer-events: none; text-shadow: 0 1px 3px #000 }
.hidden-sub-crosshair-value { position: absolute; right: 6px; z-index: 6; padding: 2px 4px; border-radius: 3px; background: #101a26; color: #b9c7d6; font-size: 11px; pointer-events: none }
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
