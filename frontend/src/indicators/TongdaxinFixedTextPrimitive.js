// DRAWTEXT_FIX and DRAWNUMBER_FIX use pane-relative coordinates rather than
// price coordinates. Keeping them in a pane primitive mirrors Tongdaxin and
// prevents labels from moving when the price scale changes.
export class TongdaxinFixedTextPrimitive {
  constructor(items) {
    this.items = items
    this.view = { zOrder: () => 'top', renderer: () => ({ draw: target => this.draw(target) }) }
  }

  paneViews() { return [this.view] }
  updateAllViews() {}

  draw(target) {
    target.useMediaCoordinateSpace(({ context, mediaSize }) => {
      context.save()
      context.font = '600 13px system-ui, "Microsoft YaHei", sans-serif'
      context.textBaseline = 'top'
      for (const item of this.items) {
        context.fillStyle = item.color || '#f8fafc'
        context.textAlign = Number(item.align) === 1 ? 'right' : 'left'
        context.fillText(
          String(item.text || ''),
          Math.max(0, Math.min(mediaSize.width, Number(item.x || 0) * mediaSize.width)),
          Math.max(0, Math.min(mediaSize.height - 16, Number(item.y || 0) * mediaSize.height)),
        )
      }
      context.restore()
    })
  }
}
