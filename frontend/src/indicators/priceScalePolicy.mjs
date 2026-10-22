// A formula with only STICKLINE primitives still needs an invisible anchor series
// on the same price scale as its plotted lines. An overlay price scale hides
// numeric labels without disabling the scale used by priceToCoordinate().
export const hiddenIndicatorScaleId = item => {
  if (item?.placement !== 'sub' || String(item.name || '').replace(/\s/g, '') !== '一气三清') return undefined
  return `yi-qi-san-qing-${String(item.code || 'formula')}`
}
