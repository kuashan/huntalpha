const data = {
  '沪深 A 股': [{ code: 'SH.600519', name: '贵州茅台', price: 1493.62, change: 0.83 }, { code: 'SZ.300750', name: '宁德时代', price: 188.46, change: -1.24 }, { code: 'SZ.000001', name: '平安银行', price: 11.37, change: 1.07 }, { code: 'BJ.920522', name: '纳科诺尔（通达信校准样本）', price: null, change: null }],
  港股: [{ code: 'HK.00700', name: '腾讯控股', price: 438.8, change: 1.41 }, { code: 'HK.09988', name: '阿里巴巴-W', price: 118.7, change: -0.75 }, { code: 'HK.03690', name: '美团-W', price: 143.6, change: 0.92 }],
  美股: [{ code: 'US.AAPL', name: 'Apple', price: 214.4, change: 0.72 }, { code: 'US.NVDA', name: 'NVIDIA', price: 178.24, change: 1.83 }, { code: 'US.TSLA', name: 'Tesla', price: 331.2, change: -0.38 }],
  加密资产: [{ code: 'CC.BTCUSD', name: 'Bitcoin / USD', price: 104821.6, change: 2.08 }, { code: 'CC.ETHUSD', name: 'Ethereum / USD', price: 3427.45, change: 1.27 }, { code: 'CC.SOL', name: 'Solana', price: 181.31, change: -0.64 }],
}
export const markets = Object.keys(data)
export const commonIndicators = [
  { id: 'builtin-ma', name: 'MA', fullName: 'MA 均线', code: 'MA', placement: 'main', common: true, visitor_available: true },
  { id: 'builtin-boll', name: 'BOLL', fullName: 'BOLL 布林线', code: 'BOLL', placement: 'main', common: true, visitor_available: true },
  { id: 'builtin-vol', name: 'VOL', fullName: 'VOL 成交量', code: 'VOL', placement: 'sub', common: true, visitor_available: true },
  { id: 'builtin-macd', name: 'MACD', fullName: 'MACD', code: 'MACD', placement: 'sub', common: true, visitor_available: true },
  { id: 'builtin-kdj', name: 'KDJ', fullName: 'KDJ', code: 'KDJ', placement: 'sub', common: true, visitor_available: true },
  { id: 'builtin-rsi', name: 'RSI', fullName: 'RSI', code: 'RSI', placement: 'sub', common: true, visitor_available: true },
]
export const marketSummary = {
  '沪深 A 股': { value: '4,293.51', change: '+0.64%' },
  港股: { value: '23,718.62', change: '+0.41%' },
  美股: { value: '18,439.77', change: '+0.32%' },
  加密资产: { value: 'BTC 104,821', change: '+2.08%' },
}
export const symbolsFor = (market) => data[market] ?? []
const hash = (text) => [...text].reduce((sum, item) => sum + item.charCodeAt(0), 0)
export function makeBars(symbol, period) {
  const count = period === '分时' ? 120 : 160; const seed = hash(symbol.code + period); let price = (symbol.price || 20) * .92
  const step = { '1分': 60, '5分': 300, '15分': 900, '30分': 1800, '60分': 3600, '2小时': 7200, '4小时': 14400, '周线': 604800, '月线': 2592000 }[period] || 86400
  return Array.from({ length: count }, (_, index) => { const open = price; const move = (Math.sin((index + seed) * .3) * .018 + ((index * seed) % 9 - 4) / 950) * price; price = Math.max(.01, price + move); return { time: 1730000000 + index * step, open: +open.toFixed(2), high: +(Math.max(open, price) * 1.008).toFixed(2), low: +(Math.min(open, price) * .992).toFixed(2), close: +price.toFixed(2), volume: 400000 + ((seed * (index + 3)) % 900000) } })
}
export function ma(bars, length) { return bars.map((bar, i) => ({ time: bar.time, value: bars.slice(Math.max(0, i - length + 1), i + 1).reduce((sum, item) => sum + item.close, 0) / Math.min(i + 1, length) })) }
