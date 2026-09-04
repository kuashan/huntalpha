<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { CandlestickSeries, LineSeries, createChart } from 'lightweight-charts'
import { TongdaxinStickPrimitive } from '../indicators/TongdaxinStickPrimitive'
import { TongdaxinTextPrimitive } from '../indicators/TongdaxinTextPrimitive'
import { TongdaxinFixedTextPrimitive } from '../indicators/TongdaxinFixedTextPrimitive'
import { commonDrawing } from '../indicators/commonIndicators'

const props = defineProps({
  symbol: Object,
  period: String,
  installedIndicators: { type: Array, default: () => [] },
})

const el = ref(null)
const mainIndicators = computed(() => props.installedIndicators.filter(item => item.placement === 'main'))
const subTitlePositions = ref([])
const renderErrors = ref([])
const historyStatus = ref('')
let chart
let resize
let panePointerUp
let drawVersion = 0
let drawQueue = Promise.resolve()
let loadedBars = []
let loadedKey = ''
let hasMoreHistory = false
let loadingHistory = false

const backgroundStick = item => item.layer === 'background'
const savedSubPaneHeights = () => {
  try { return JSON.parse(localStorage.getItem('quantscope:sub-pane-heights') || '{}') } catch { return {} }
}

function syncSubTitlePositions(rendered) {
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

async function requestDrawings(bars) {
  renderErrors.value = []
  return (await Promise.all(props.installedIndicators.map(async item => {
    if (item.common) return { item, drawing: commonDrawing(item.code, bars) }
    try {
      const reply = await fetch(`http://127.0.0.1:8003/api/indicator-render/${encodeURIComponent(item.code)}/${props.symbol.code}/?period=${encodeURIComponent(props.period)}&count=${bars.length}`, { credentials: 'include' })
      const payload = await reply.json()
      if (reply.ok) return { item, drawing: payload.drawing }
      renderErrors.value.push(`${item.name}：${payload.error || '指标计算失败'}`)
    } catch {
      renderErrors.value.push(`${item.name}：无法连接指标计算服务`)
    }
    return null
  }))).filter(Boolean)
}

const chartKey = () => `${props.symbol?.code || ''}:${props.period || ''}`
const orderedUniqueBars = bars => [...new Map(bars.map(bar => [bar.time, bar])).values()].sort((left, right) => left.time - right.time)

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
  if (!groups.length) return
  const background = groups.filter(backgroundStick)
  const foreground = groups.filter(item => !backgroundStick(item))
  if (background.length) chart.panes()[pane]?.attachPrimitive(new TongdaxinStickPrimitive(chart, anchor, background, 'background'))
  if (foreground.length) chart.panes()[pane]?.attachPrimitive(new TongdaxinStickPrimitive(chart, anchor, foreground))
}

function addTextMarkers(groups, pane, anchor) {
  if (groups.length) chart.panes()[pane]?.attachPrimitive(new TongdaxinTextPrimitive(chart, anchor, groups))
}

function addFixedTexts(items, pane) {
  if (items?.length) chart.panes()[pane]?.attachPrimitive(new TongdaxinFixedTextPrimitive(items))
}

function addFormulaAnchor(drawing, pane) {
  const values = new Map()
  drawing.lines.forEach(item => item.data.forEach(point => values.set(point.time, point.value)))
  drawing.sticks.forEach(item => item.data.forEach(point => {
    values.set(point.time, point.from)
    values.set(point.time, point.to)
  }))
  const anchor = chart.addSeries(LineSeries, {
    color: 'transparent', lineVisible: false, priceLineVisible: false, lastValueVisible: false,
  }, pane)
  anchor.setData([...values.entries()].sort(([left], [right]) => left - right).map(([time, value]) => ({ time, value })))
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

async function draw(options = {}) {
  if (!el.value || !props.symbol) return
  const version = ++drawVersion
  const key = chartKey()
  subTitlePositions.value = []
  historyStatus.value = ''
  if (panePointerUp) el.value.removeEventListener('pointerup', panePointerUp)
  chart?.remove()

  if (!options.keepBars || loadedKey !== key || !loadedBars.length) {
    loadedKey = key
    loadedBars = []
    hasMoreHistory = false
    try {
      const payload = await fetchKlinePage()
      if (payload.bars?.length) {
        loadedBars = orderedUniqueBars(payload.bars)
        hasMoreHistory = Boolean(payload.has_more)
      }
    } catch (error) {
      historyStatus.value = `行情加载失败：${error.message}`
    }
  }
  // Never substitute generated candles for a failed market-data request:
  // a blank chart plus the visible error is safer than fake price history.
  const bars = loadedBars
  if (version !== drawVersion || !el.value) return

  const rendered = await requestDrawings(bars)
  if (version !== drawVersion || !el.value) return

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
    upColor: '#ef5350', downColor: '#20bd92', borderVisible: false,
    wickUpColor: '#ef5350', wickDownColor: '#20bd92',
  }, 0)
  candle.setData(bars)

  let nextPane = 1
  for (const result of rendered) {
    const pane = result.item.placement === 'main' ? 0 : nextPane++
    const lines = result.drawing.lines.map(item => addLine(item.color, item.data, pane, item.style, item.width))
    const anchor = result.item.placement === 'main' ? candle : (lines[0] || addFormulaAnchor(result.drawing, pane))
    addSticks(result.drawing.sticks, pane, anchor)
    addTextMarkers(result.drawing.markers, pane, anchor)
    addFixedTexts(result.drawing.fixedTexts, pane)
    if (result.item.placement === 'sub') chart.panes()[pane]?.setHeight(savedHeights[result.item.code] || 150)
  }
  chart.panes()[0]?.setHeight(440)
  panePointerUp = () => window.setTimeout(() => {
    saveSubPaneHeights(rendered)
    syncSubTitlePositions(rendered)
  }, 0)
  el.value.addEventListener('pointerup', panePointerUp)
  // fitContent() starts at the left boundary and also emits this event.  Do
  // not mistake that initial layout event for a user dragging toward history.
  let historyWatchReady = false
  chart.timeScale().subscribeVisibleLogicalRangeChange(range => {
    if (historyWatchReady && range && range.from < 80) loadOlderBars()
  })
  requestAnimationFrame(() => requestAnimationFrame(() => {
    if (version === drawVersion && el.value) syncSubTitlePositions(rendered)
  }))
  if (options.visibleRange) chart.timeScale().setVisibleLogicalRange(options.visibleRange)
  else chart.timeScale().fitContent()
  requestAnimationFrame(() => { historyWatchReady = true })
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
  scheduleDraw()
  resize = new ResizeObserver(() => chart?.applyOptions({ width: el.value.clientWidth }))
  resize.observe(el.value)
})
onBeforeUnmount(() => {
  if (panePointerUp) el.value?.removeEventListener('pointerup', panePointerUp)
  resize?.disconnect()
  chart?.remove()
})
watch(() => [props.symbol, props.period, props.installedIndicators], scheduleDraw, { deep: true })
</script>

<template>
  <div class="chart-wrap">
    <div ref="el" class="chart" />
    <div class="main-titles"><b v-for="(item, index) in mainIndicators" :key="item.code" :style="{ top: `${10 + index * 26}px` }">{{ item.name }}</b></div>
    <div class="sub-titles"><b v-for="item in subTitlePositions" :key="item.code" :style="{ top: `${item.top}px` }">{{ item.name }}</b></div>
    <div v-if="historyStatus" class="history-status">{{ historyStatus }}</div>
    <div v-if="renderErrors.length" class="chart-errors"><span v-for="message in renderErrors" :key="message">{{ message }}</span></div>
  </div>
</template>

<style scoped>
.chart-wrap { position: relative }
.chart { width: 100%; min-height: 460px }
.main-titles, .sub-titles { position: absolute; inset: 0; z-index: 5; pointer-events: none }
.main-titles b, .sub-titles b { position: absolute; left: 9px; color: #f4f7fb; font-size: 14px; font-weight: 700; line-height: 1.1; letter-spacing: .2px; text-shadow: 0 1px 3px #000 }
.chart-errors { position: absolute; top: 38px; right: 12px; z-index: 6; display: grid; gap: 4px; max-width: 48%; color: #fecaca; font-size: 12px; text-align: right; pointer-events: none }
.chart-errors span { padding: 5px 7px; border: 1px solid #7f1d1d; border-radius: 4px; background: rgba(69, 10, 10, .85) }
.history-status { position: absolute; right: 12px; bottom: 8px; z-index: 6; color: #94a3b8; font-size: 12px; pointer-events: none; text-shadow: 0 1px 3px #000 }
</style>
