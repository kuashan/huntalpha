// Independent daily chip-distribution engine.  It deliberately models a
// transparent approximation, rather than claiming to reproduce any terminal's
// proprietary COST data.
const number = value => Number.isFinite(Number(value)) ? Number(value) : 0

function priceStep(bars) {
  const low = Math.min(...bars.map(bar => number(bar.low)))
  const high = Math.max(...bars.map(bar => number(bar.high)))
  return high - low > 200 ? 1 : high - low > 20 ? 0.1 : 0.01
}

function distributeTriangle(low, high, average, step) {
  if (high <= low) return [[Number(average.toFixed(6)), 1]]
  const start = Math.floor(low / step) * step
  const end = Math.ceil(high / step) * step
  const entries = []
  for (let price = start; price <= end + step / 2; price += step) {
    const center = Number((price + step / 2).toFixed(6))
    const left = Math.max(average - low, step)
    const right = Math.max(high - average, step)
    const density = center <= average
      ? Math.max(0, (center - low) / left)
      : Math.max(0, (high - center) / right)
    entries.push([center, density])
  }
  const total = entries.reduce((sum, [, weight]) => sum + weight, 0) || 1
  return entries.map(([price, weight]) => [price, weight / total])
}

function quantile(chips, percentage) {
  const target = Math.min(1, Math.max(0, percentage / 100))
  let cumulative = 0
  for (const [price, weight] of [...chips.entries()].sort((a, b) => a[0] - b[0])) {
    cumulative += weight
    if (cumulative >= target) return price
  }
  return [...chips.keys()].sort((a, b) => b - a)[0] || 0
}

export function calculateChipDistribution(rawBars, { floatShares = 0, decay = 1 } = {}) {
  const bars = rawBars.filter(bar => number(bar.high) >= number(bar.low) && number(bar.high) > 0)
  const step = priceStep(bars)
  const costs = Object.fromEntries(Array.from({ length: 101 }, (_, key) => [key, []]))
  const winners = []
  const knownFloatShares = number(floatShares)
  let chips = new Map()

  for (const bar of bars) {
    const low = number(bar.low)
    const high = number(bar.high)
    // On adjusted (前/后复权) exports, AMOUNT/VOL may still represent the
    // unadjusted transaction price.  Only use it when it lies in the same
    // price scale as this bar; otherwise preserve price-scale consistency.
    const tradedAverage = number(bar.amount) > 0 && number(bar.volume) > 0 ? number(bar.amount) / number(bar.volume) : 0
    const average = tradedAverage >= low && tradedAverage <= high
      ? tradedAverage
      : (low + high + number(bar.close)) / 3
    // `turnover` is the monetary trading amount, not a replacement ratio.
    // OpenD supplies `turnover_rate` as a percentage; use it first and only
    // derive a rate from volume/current circulating shares when unavailable.
    const suppliedTurnoverRate = number(bar.turnover_rate)
    const turnover = Math.min(1, Math.max(0,
      suppliedTurnoverRate > 0
        ? suppliedTurnoverRate / 100
        : (knownFloatShares > 0 ? number(bar.volume) / knownFloatShares : 0),
    ))
    let replacement = Math.min(1, turnover * Math.max(0, number(decay) || 1))
    const today = distributeTriangle(low, high, average, step)
    if (!chips.size) replacement = 1
    for (const [price, weight] of chips) chips.set(price, weight * (1 - replacement))
    for (const [price, weight] of today) chips.set(price, (chips.get(price) || 0) + weight * replacement)
    const total = [...chips.values()].reduce((sum, weight) => sum + weight, 0) || 1
    for (const [price, weight] of chips) chips.set(price, weight / total)
    for (const percentage of Object.keys(costs)) {
      costs[percentage].push(quantile(chips, Number(percentage)))
    }
    const close = number(bar.close)
    winners.push([...chips.entries()].reduce((sum, [price, weight]) => sum + (price <= close ? weight : 0), 0))
  }
  return { costs, winners, available: knownFloatShares > 0, method: 'triangular-turnover' }
}
