// Canvas renderer for Tongdaxin STICKLINE.  A STICKLINE is a rectangle between
// two formula values at a bar, rather than a candlestick or a histogram from 0.
// Keeping it in a pane primitive also lets broad colour bands sit below K lines.
export class TongdaxinStickPrimitive {
  constructor(chart, priceSeries, groups, layer = 'normal') {
    this.chart = chart
    this.priceSeries = priceSeries
    this.groups = groups
    this.layer = layer
    this.view = {
      zOrder: () => layer === 'background' ? 'bottom' : 'normal',
      renderer: () => ({ draw: target => this.draw(target) }),
    }
  }

  paneViews() { return [this.view] }

  updateAllViews() {}

  barWidth() {
    const coordinates = []
    for (const group of this.groups) {
      for (const point of group.data) {
        const x = this.chart.timeScale().timeToCoordinate(point.time)
        if (x !== null) coordinates.push(x)
      }
    }
    coordinates.sort((left, right) => left - right)
    const gaps = coordinates.slice(1).map((value, index) => value - coordinates[index]).filter(value => value > 0.5)
    return gaps.length ? gaps[Math.floor(gaps.length / 2)] : 8
  }

  draw(target) {
    const spacing = this.barWidth()
    target.useMediaCoordinateSpace(({ context }) => {
      context.save()
      for (const group of this.groups) {
        context.strokeStyle = group.color
        context.fillStyle = group.color
        for (const point of group.data) {
          const x = this.chart.timeScale().timeToCoordinate(point.time)
          const first = this.priceSeries.priceToCoordinate(point.from)
          const second = this.priceSeries.priceToCoordinate(point.to)
          if (x === null || first === null || second === null) continue
          // Tongdaxin defines width 4 as the standard bar spacing. Width 0 is
          // still the one-pixel wick/line form used by formula-drawn candles.
          // Width 0 is the one-pixel wick/line form used by many formulas.
          const configuredWidth = Number(point.width || 0)
          // Full-height/background STICKLINE bands are visual regions rather
          // than formula K-line bodies. Keep them broad and continuous while
          // leaving normal candle bodies on the Tongdaxin 0–10 width scale.
          const width = this.layer === 'background'
            ? spacing * .96
            : configuredWidth <= 0
              ? 1
              : Math.max(1, Math.min(spacing * .95, spacing * (configuredWidth / 4) * .8))
          const left = Math.round(x - width / 2)
          const top = Math.round(Math.min(first, second))
          const height = Math.max(1, Math.round(Math.abs(second - first)))
          const emptyMode = Number(point.empty || 0)
          if (emptyMode === 1 || emptyMode === -1) {
            context.setLineDash(emptyMode === -1 ? [3, 2] : [])
            context.strokeRect(left + .5, top + .5, Math.max(1, Math.round(width - 1)), Math.max(1, height - 1))
            context.setLineDash([])
          } else context.fillRect(left, top, Math.round(width), height)
        }
      }
      context.restore()
    })
  }
}
