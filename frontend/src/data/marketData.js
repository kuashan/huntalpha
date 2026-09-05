const data = {
  '沪深 A 股': [{ code: 'SH.600519', name: '贵州茅台' }, { code: 'SZ.300750', name: '宁德时代' }, { code: 'SZ.000001', name: '平安银行' }, { code: 'BJ.920522', name: '纳科诺尔（通达信校准样本）' }],
  港股: [{ code: 'HK.00700', name: '腾讯控股' }, { code: 'HK.09988', name: '阿里巴巴-W' }, { code: 'HK.03690', name: '美团-W' }],
  美股: [{ code: 'US.AAPL', name: 'Apple' }, { code: 'US.NVDA', name: 'NVIDIA' }, { code: 'US.TSLA', name: 'Tesla' }],
  加密资产: [{ code: 'CC.BTCUSD', name: 'Bitcoin / USD' }, { code: 'CC.ETHUSD', name: 'Ethereum / USD' }, { code: 'CC.SOL', name: 'Solana' }],
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
export const symbolsFor = (market) => data[market] ?? []
