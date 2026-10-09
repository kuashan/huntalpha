// Formula text/icons need their own price-coordinate renderer. Lightweight
// Charts series markers are anchored to a series value, not to the explicit
// DRAWTEXT/DRAWICON price supplied by Tongdaxin.
export class TongdaxinTextPrimitive {
  constructor(chart, priceSeries, groups) {
    this.chart = chart
    this.priceSeries = priceSeries
    this.groups = groups
    this.requestUpdate = undefined
    this.view = { zOrder: () => 'top', renderer: () => ({ draw: target => this.draw(target) }) }
  }

  paneViews() { return [this.view] }
  attached({ requestUpdate }) { this.requestUpdate = requestUpdate }
  detached() { this.requestUpdate = undefined }
  updateAllViews() { this.requestUpdate?.() }

  update(groups) {
    this.groups = groups || []
    this.updateAllViews()
  }

  draw(target) {
    target.useMediaCoordinateSpace(({ context }) => {
      context.save()
      context.font = '600 14px system-ui, "Microsoft YaHei", sans-serif'
      context.textAlign = 'center'
      context.textBaseline = 'bottom'
      for (const group of this.groups) {
        context.fillStyle = group.color
        for (const point of group.data) {
          const x = this.chart.timeScale().timeToCoordinate(point.time)
          const y = this.priceSeries.priceToCoordinate(point.value)
          if (x === null || y === null || !Number.isFinite(point.value)) continue
          const offset = group.text === '↑' || group.text === '↓' ? 7 : 4
          context.fillText(group.text, x, y - offset)
        }
      }
      context.restore()
    })
  }
}
