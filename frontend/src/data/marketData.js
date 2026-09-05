// Market labels are UI constants only. Securities come from Django's
// provider-neutral catalog API and are never maintained in this module.
export const markets = [
  { code: 'cn', name: '沪深 A 股' },
  { code: 'hk', name: '港股' },
  { code: 'us', name: '美股' },
  { code: 'crypto', name: '加密资产' },
]
export const commonIndicators = [
  { id: 'builtin-ma', name: 'MA', fullName: 'MA 均线', code: 'MA', placement: 'main', common: true, visitor_available: true },
  { id: 'builtin-boll', name: 'BOLL', fullName: 'BOLL 布林线', code: 'BOLL', placement: 'main', common: true, visitor_available: true },
  { id: 'builtin-vol', name: 'VOL', fullName: 'VOL 成交量', code: 'VOL', placement: 'sub', common: true, visitor_available: true },
  { id: 'builtin-macd', name: 'MACD', fullName: 'MACD', code: 'MACD', placement: 'sub', common: true, visitor_available: true },
  { id: 'builtin-kdj', name: 'KDJ', fullName: 'KDJ', code: 'KDJ', placement: 'sub', common: true, visitor_available: true },
  { id: 'builtin-rsi', name: 'RSI', fullName: 'RSI', code: 'RSI', placement: 'sub', common: true, visitor_available: true },
]
