// Keep quote responses bound to their own symbol and latest request.
// Loading a watchlist must not block the selected stock's quote behind
// requests for other symbols, or overwrite a more recent click response.
const codeOf = value => String(value || '').trim().toUpperCase()
const owns = (values, key) => Object.prototype.hasOwnProperty.call(values, key)

export function createQuoteCoordinator({ readQuotes, writeQuotes, fetchQuote }) {
  const requestNumbers = new Map()
  let lifecycle = 0

  function writeIfPresent(code, value) {
    const current = readQuotes()
    if (owns(current, code)) writeQuotes({ ...current, [code]: value })
  }

  async function refresh(code, { showLoading = true } = {}) {
    const key = codeOf(code)
    if (!key) return
    const requestNumber = (requestNumbers.get(key) || 0) + 1
    requestNumbers.set(key, requestNumber)
    const startedIn = lifecycle
    if (!owns(readQuotes(), key)) writeQuotes({ ...readQuotes(), [key]: { status: 'loading' } })
    else if (showLoading) writeIfPresent(key, { status: 'loading' })

    let result
    try {
      const payload = await fetchQuote(key)
      if (!payload || (payload.code && codeOf(payload.code) !== key)) {
        throw new Error('行情返回的证券代码与所选股票不匹配')
      }
      result = { status: 'ready', data: payload }
    } catch (error) {
      result = { status: 'error', error: error?.message || '行情不可用' }
    }

    if (lifecycle === startedIn && requestNumbers.get(key) === requestNumber) {
      writeIfPresent(key, result)
    }
  }

  function refreshList(items, selectedCode) {
    const old = readQuotes()
    const next = {}
    for (const item of items) {
      const code = codeOf(item?.code)
      if (code) next[code] = old[code] || { status: 'loading' }
    }
    const selected = codeOf(selectedCode)
    if (selected && !owns(next, selected)) next[selected] = old[selected] || { status: 'loading' }
    writeQuotes(next)
    return Promise.all(items.map(item => refresh(item.code, { showLoading: false })))
  }

  function reset() {
    lifecycle += 1
    requestNumbers.clear()
  }

  return { refresh, refreshList, reset }
}
