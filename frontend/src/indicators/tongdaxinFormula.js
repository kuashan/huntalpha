const COLORS = { RED: '#ef5350', GREEN: '#20bd92', BLUE: '#4b82ff', YELLOW: '#f5bf4d', WHITE: '#f5f7fb', BLACK: '#111827', GRAY: '#8996a5', MAGENTA: '#d84bda', CYAN: '#22d3ee', ORANGE: '#ff8d1e', PINK: '#e970dc', LIGRAY: '#d1d5db', LIGREEN: '#86efac', LIBLUE: '#93c5fd', LICYAN: '#67e8f9', LIRED: '#fca5a5', LIMAGENTA: '#f0abfc', LIYELLOW: '#fde68a', BROWN: '#a16207', PURPLE: '#9333ea', FF8D1E: '#ff8d1e', '0CAEE6': '#0caee6', E970DC: '#e970dc', CCCCCC: '#cccccc', '00AACC': '#00aacc', '0088CC': '#0088cc', '0066CC': '#0066cc', '0033CC': '#0033cc', '0000CC': '#0000cc' }
const formulaColor = (token = 'BLUE') => {
  if (typeof token === 'string' && token.startsWith('#')) return token
  if (typeof token === 'number' && Number.isFinite(token)) return `#${Math.max(0, Math.min(0xffffff, Math.round(token))).toString(16).padStart(6, '0')}`
  const key = String(token).replace(/^COLOR/i, '').toUpperCase()
  return /^[0-9A-F]{6}$/.test(key) ? `#${key.toLowerCase()}` : (COLORS[key] || COLORS.BLUE)
}
const isSeries = value => Array.isArray(value)
const vector = (left, right, op, size) => Array.from({ length: size }, (_, index) => op(isSeries(left) ? left[index] : left, isSeries(right) ? right[index] : right))
const scalar = value => isSeries(value) ? value[value.length - 1] : value
const split = (text, delimiter = ',') => {
  let depth = 0
  let quote = ''
  let escaped = false
  const out = []
  let start = 0
  for (let index = 0; index < text.length; index += 1) {
    const character = text[index]
    if (quote) {
      if (escaped) escaped = false
      else if (character === '\\') escaped = true
      else if (character === quote) {
        // Tongdaxin formula text may escape a quote by doubling it.
        if (text[index + 1] === quote) index += 1
        else quote = ''
      }
      continue
    }
    if (character === "'" || character === '"') quote = character
    else if (character === '(') depth += 1
    else if (character === ')') {
      depth -= 1
      if (depth < 0) throw new Error('公式语法错误：存在多余的右括号')
    } else if (!depth && character === delimiter) {
      out.push(text.slice(start, index).trim())
      start = index + 1
    }
  }
  if (quote) throw new Error('公式语法错误：字符串没有结束')
  if (depth) throw new Error('公式语法错误：括号没有闭合')
  out.push(text.slice(start).trim())
  return out
}
const splitStatements = text => split(text, ';')
const avg = values => values.reduce((sum, value) => sum + value, 0) / values.length
function smooth(values, period, weight = 2) { let current; return values.map(value => { if (!Number.isFinite(Number(value))) return Number.NaN; current = current === undefined ? value : (weight * value + (period - weight) * current) / period; return current }) }
function rolling(values, period, fn) { return values.map((_, index) => fn(values.slice(Math.max(0, index - period + 1), index + 1))) }
const series = (value, size) => isSeries(value) ? value : Array(size).fill(value)
const rollingCount = (values, period) => rolling(values, period, set => set.filter(Boolean).length)
const barsSince = values => { let distance = 0; return values.map((value, index) => { if (value) distance = 0; else if (index) distance += 1; return distance }) }
const valueAt = (value, index) => isSeries(value) ? value[Math.min(index, value.length - 1)] : value
const truthy = value => Number(value) !== 0 && !Number.isNaN(Number(value))
// DRAWNULL is represented internally as NaN.  JavaScript's NaN !== NaN is
// unlike Tongdaxin's null-marker semantics: `X!=DRAWNULL` is meant to select
// actual numeric points, not every bar including the null gaps.
const isDrawNull = value => value === null || value === undefined || (typeof value === 'number' && Number.isNaN(value))
const sameValue = (left, right) => {
  const leftNull = isDrawNull(left)
  const rightNull = isDrawNull(right)
  return leftNull || rightNull ? leftNull && rightNull : left === right
}
const orderedComparison = (left, right, compare) => !isDrawNull(left) && !isDrawNull(right) && compare(left, right)
const periodAt = (value, index, fallback = 1) => { const parsed = Math.round(Number(valueAt(value, index))); return Number.isFinite(parsed) ? Math.max(0, parsed) : fallback }
function rollingDynamic(values, periods, fn) { return values.map((_, index) => { const period = periodAt(periods, index); const start = period === 0 ? 0 : Math.max(0, index - period + 1); return fn(values.slice(start, index + 1), index, start, period) }) }
function smoothDynamic(values, periods, weights = 2) { let current; return values.map((value, index) => { if (!Number.isFinite(Number(value))) return Number.NaN; const period = Math.max(1, periodAt(periods, index)); const weight = Math.max(0, Number(valueAt(weights, index)) || 0); current = current === undefined ? value : (weight * value + (period - weight) * current) / period; return current }) }
function variance(values, sample = false) { if (!values.length || (sample && values.length < 2)) return Number.NaN; const mean = avg(values); return values.reduce((sum, value) => sum + (value - mean) ** 2, 0) / (values.length - (sample ? 1 : 0)) }
function rollingRegression(values, periods, select) { return rollingDynamic(values, periods, window => { const count = window.length; if (count < 2) return select(0, window[0] || 0, count); let sx = 0, sy = 0, sxy = 0, sxx = 0; window.forEach((value, index) => { sx += index; sy += value; sxy += index * value; sxx += index * index }); const denominator = count * sxx - sx * sx; const slope = denominator ? (count * sxy - sx * sy) / denominator : 0; const intercept = (sy - slope * sx) / count; return select(slope, intercept, count) }) }
function rollingPair(left, right, periods, fn, size) { const xs = series(left, size), ys = series(right, size); return xs.map((_, index) => { const period = periodAt(periods, index); const start = period === 0 ? 0 : Math.max(0, index - period + 1); return fn(xs.slice(start, index + 1), ys.slice(start, index + 1)) }) }
function findExtreme(values, offsetArg, lengthArg, rankArg, high, returnBars) { return values.map((_, index) => { const offset = periodAt(offsetArg, index, 0); const length = Math.max(1, periodAt(lengthArg, index, 1)); const rank = Math.max(1, periodAt(rankArg, index, 1)); const end = index - offset; if (end < 0) return Number.NaN; const start = Math.max(0, end - length + 1); const candidates = Array.from({ length: end - start + 1 }, (_unused, cursor) => ({ index: start + cursor, value: values[start + cursor] })); candidates.sort((a, b) => high ? b.value - a.value || b.index - a.index : a.value - b.value || b.index - a.index); const selected = candidates[Math.min(rank - 1, candidates.length - 1)]; return returnBars ? index - selected.index : selected.value }) }
function parabolicSar(high, low, lookback, step, maximum, returnTurns = false) {
  const size = high.length
  const out = Array(size).fill(Number.NaN)
  const turns = Array(size).fill(0)
  const period = Math.max(2, Math.round(Number(lookback) || 4))
  if (size <= period) return out
  const accelerationStep = Math.max(0.0001, Number(step) || 0.02)
  const accelerationLimit = Math.max(accelerationStep, Number(maximum) || 0.2)
  let rising = high[period - 1] > high[period - 2]
  let first = true
  let acceleration = 0
  for (let index = period; index < size; index += 1) {
    const start = Math.max(0, index - period)
    const previousHigh = Math.max(...high.slice(start, index))
    const previousLow = Math.min(...low.slice(start, index))
    if (first) {
      acceleration = accelerationStep
      out[index] = rising ? previousLow : previousHigh
      first = false
    } else {
      const extreme = rising ? previousHigh : previousLow
      if ((rising && high[index] > extreme) || (!rising && low[index] < extreme)) {
        acceleration = Math.min(acceleration + accelerationStep, accelerationLimit)
      }
      out[index] = out[index - 1] + acceleration * (extreme - out[index - 1])
    }
    if ((rising && low[index] < out[index]) || (!rising && high[index] > out[index])) {
      rising = !rising
      turns[index] = rising ? 1 : -1
      first = true
    }
  }
  return returnTurns ? turns : out
}
function formattedSeries(value, digits, size) { const places = Math.max(0, periodAt(digits, size - 1, 2)); return series(value, size).map(item => Number.isFinite(Number(item)) ? Number(item).toFixed(places) : String(item ?? '')) }
const TDX_DAY_ZERO_UTC = Date.UTC(1990, 11, 19)
function parseTdxDate(value) {
  const numeric = Math.trunc(Number(value))
  if (!Number.isFinite(numeric)) return null
  const yearOffset = Math.trunc(numeric / 10000)
  const month = Math.trunc((numeric % 10000) / 100)
  const day = numeric % 100
  const date = new Date(Date.UTC(1900 + yearOffset, month - 1, day))
  return Number.isNaN(date.getTime()) || date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day ? null : date
}
function formatTdxDate(date) {
  return (date.getUTCFullYear() - 1900) * 10000 + (date.getUTCMonth() + 1) * 100 + date.getUTCDate()
}
function isoWeekOfYear(date) {
  const target = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()))
  const day = target.getUTCDay() || 7
  target.setUTCDate(target.getUTCDate() + 4 - day)
  const yearStart = new Date(Date.UTC(target.getUTCFullYear(), 0, 1))
  return Math.ceil((((target - yearStart) / 86400000) + 1) / 7)
}
function parameterAssignments(source) {
  const assignments = []
  const seen = new Set()
  for (const comment of source.match(/\{[\s\S]*?\}/g) || []) {
    for (const match of comment.matchAll(/([A-Za-z_\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff]*)\s*[（(]\s*[-+]?\d+(?:\.\d+)?\s*[,，]\s*[-+]?\d+(?:\.\d+)?\s*[,，]\s*([-+]?\d+(?:\.\d+)?)\s*[)）]/g)) {
      const name = match[1].toUpperCase()
      if (!seen.has(name)) { assignments.push(`${name}:=${match[2]};`); seen.add(name) }
    }
  }
  return assignments
}
function tokenize(text) {
  const tokens = []
  let index = 0
  while (index < text.length) {
    if (/\s/.test(text[index])) { index += 1; continue }
    const rest = text.slice(index)
    const operator = rest.match(/^(>=|<=|<>|!=|==|&&|\|\||:=)/)?.[0]
    if (operator) { tokens.push(operator); index += operator.length; continue }
    const character = text[index]
    if ("()+-*/=><,!&|".includes(character)) { tokens.push(character); index += 1; continue }
    if (character === "'" || character === '"') {
      const quote = character
      let value = quote
      let closed = false
      index += 1
      while (index < text.length) {
        const current = text[index]
        value += current
        index += 1
        if (current === '\\' && index < text.length) {
          value += text[index]
          index += 1
        } else if (current === quote) {
          if (text[index] === quote) { value += text[index]; index += 1 }
          else { closed = true; break }
        }
      }
      if (!closed) throw new Error('公式语法错误：字符串没有结束')
      tokens.push(value)
      continue
    }
    const number = rest.match(/^(?:\d+\.\d*|\.\d+|\d+)(?:[Ee][+-]?\d+)?/)?.[0]
    if (number) { tokens.push(number); index += number.length; continue }
    const identifier = rest.match(/^[A-Za-z_\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff]*/)?.[0]
    if (identifier) { tokens.push(identifier); index += identifier.length; continue }
    throw new Error(`公式语法错误：暂不支持符号 ${character}`)
  }
  return tokens
}

function parser(text) {
  const tokens = tokenize(text)
  if (!tokens.length) throw new Error('公式语法错误：表达式为空')
  let position = 0
  const peek = () => tokens[position]
  const take = () => tokens[position++]
  const expect = expected => {
    const actual = take()
    if (actual !== expected) throw new Error(`公式语法错误：缺少 ${expected}`)
  }
  const binary = (next, ops) => {
    let node = next()
    while (ops.includes(String(peek()).toUpperCase())) {
      const op = take().toUpperCase()
      node = { op, left: node, right: next() }
    }
    return node
  }
  const primary = () => {
    const token = take()
    if (token === undefined) throw new Error('公式语法错误：表达式不完整')
    if (token === '(') { const node = expression(); expect(')'); return node }
    if (/^(?:\d|\.\d)/.test(token)) return { value: Number(token) }
    if (token.startsWith("'") || token.startsWith('"')) {
      const quote = token[0]
      return { value: token.slice(1, -1).replaceAll(`${quote}${quote}`, quote).replace(/\\([\\'\"])/g, '$1') }
    }
    if (!/^[A-Za-z_\u4e00-\u9fff]/.test(token)) throw new Error(`公式语法错误：意外词元 ${token}`)
    if (peek() === '(') {
      take()
      const args = peek() === ')' ? [] : splitArguments()
      expect(')')
      return { fn: token.toUpperCase(), args }
    }
    return { name: token.toUpperCase() }
  }
  const unary = () => {
    const token = String(peek()).toUpperCase()
    if (token === 'NOT' || token === '!') { take(); return { op: 'NOT', value: unary() } }
    if (token === '-') { take(); return { op: 'NEG', value: unary() } }
    if (token === '+') { take(); return { op: 'POS', value: unary() } }
    return primary()
  }
  const product = () => binary(unary, ['*', '/'])
  const sum = () => binary(product, ['+', '-'])
  const compare = () => binary(sum, ['=', '==', '>', '<', '>=', '<=', '<>', '!='])
  const and = () => binary(compare, ['AND', '&&', '&'])
  const expression = () => binary(and, ['OR', '||', '|'])
  const splitArguments = () => {
    const args = [expression()]
    while (peek() === ',') { take(); args.push(expression()) }
    return args
  }
  const ast = expression()
  if (position !== tokens.length) throw new Error(`公式语法错误：存在未解析词元 ${tokens[position]}`)
  return ast
}

function execute(ast, vars, size) { if ('value' in ast && !ast.op) return ast.value; if (ast.name) { if (Object.prototype.hasOwnProperty.call(vars, ast.name)) return vars[ast.name]; if (ast.name === 'TRUE') return 1; if (ast.name === 'FALSE') return 0; throw new Error(`暂不支持通达信标识符：${ast.name}`) } if (ast.op === 'NEG') return vector(0, execute(ast.value, vars, size), (a, b) => -b, size); if (ast.op === 'POS') return execute(ast.value, vars, size); if (ast.op === 'NOT') return vector(execute(ast.value, vars, size), 0, a => a ? 0 : 1, size); if (ast.op) { const left = execute(ast.left, vars, size); const right = execute(ast.right, vars, size); const ops = { '+': (a,b)=>a+b, '-': (a,b)=>a-b, '*': (a,b)=>a*b, '/': (a,b)=>b ? a/b : 0, '=': (a,b)=>sameValue(a,b)?1:0, '==': (a,b)=>sameValue(a,b)?1:0, '<>': (a,b)=>sameValue(a,b)?0:1, '!=': (a,b)=>sameValue(a,b)?0:1, '>': (a,b)=>orderedComparison(a,b,(x,y)=>x>y)?1:0, '<': (a,b)=>orderedComparison(a,b,(x,y)=>x<y)?1:0, '>=': (a,b)=>orderedComparison(a,b,(x,y)=>x>=y)?1:0, '<=': (a,b)=>orderedComparison(a,b,(x,y)=>x<=y)?1:0, AND: (a,b)=>truthy(a)&&truthy(b)?1:0, '&&': (a,b)=>truthy(a)&&truthy(b)?1:0, '&': (a,b)=>truthy(a)&&truthy(b)?1:0, OR: (a,b)=>truthy(a)||truthy(b)?1:0, '||': (a,b)=>truthy(a)||truthy(b)?1:0, '|': (a,b)=>truthy(a)||truthy(b)?1:0 }; return vector(left, right, ops[ast.op], size) }
  const args = ast.args.map(arg => execute(arg, vars, size)); const x = args[0]; const period = Math.max(1, Math.round(scalar(args[1] ?? 1))); const fn = ast.fn
  if (['OPEN', 'O', 'HIGH', 'H', 'LOW', 'L', 'CLOSE', 'C', 'VOL', 'V', 'VOLUME', 'AMOUNT', 'AMO', 'DATE', 'TIME', 'TIME2', 'YEAR', 'MONTH', 'DAY', 'HOUR', 'MINUTE', 'WEEKDAY', 'WEEK', 'WEEKOFYEAR', 'PERIOD', 'CAPITAL', 'TOTALCAPITAL'].includes(fn) && args.length === 0) return vars[fn] || Array(size).fill(0)
  if (fn === 'NOT') return series(x, size).map(value => truthy(value) ? 0 : 1)
  if (fn === 'AND' || fn === 'OR') return vector(x, args[1], (left, right) => fn === 'AND' ? (truthy(left) && truthy(right) ? 1 : 0) : (truthy(left) || truthy(right) ? 1 : 0), size)
  if (fn === 'MA') return rollingDynamic(series(x, size), args[1] ?? 1, avg)
  // 通达信 XMA 是使用前后数据的偏移移动平均（未来函数）。
  if (fn === 'XMA') return series(x, size).map((_, index) => { const dynamicPeriod = Math.max(1, periodAt(args[1] ?? 1, index)); const left = Math.floor((dynamicPeriod - 1) / 2); const right = dynamicPeriod - left - 1; return avg(series(x, size).slice(Math.max(0, index - left), Math.min(size, index + right + 1))) })
  if (fn === 'EMA' || fn === 'EXPMA') return smoothDynamic(series(x, size), args[1] ?? 1, 2)
  if (fn === 'MEMA' || fn === 'EXPMEMA') return smoothDynamic(series(x, size), args[1] ?? 1, 1)
  if (fn === 'SMA') return smoothDynamic(series(x, size), args[1] ?? 1, args[2] ?? 1)
  if (fn === 'REF' || fn === 'REFV') { const values = series(x, size); return values.map((_, index) => { const target = index - periodAt(args[1] ?? 1, index); return target >= 0 ? values[target] : Number.NaN }) }
  if (fn === 'REFX' || fn === 'REFXV') { const values = series(x, size); return values.map((_, index) => { const target = index + periodAt(args[1] ?? 1, index); return target < size ? values[target] : Number.NaN }) }
  if (fn === 'LLV') return rollingDynamic(series(x, size), args[1] ?? 1, values => Math.min(...values))
  if (fn === 'HHV') return rollingDynamic(series(x, size), args[1] ?? 1, values => Math.max(...values))
  if (fn === 'SUM') return rollingDynamic(series(x, size), args[1] ?? 1, values => values.reduce((sum, value) => sum + value, 0))
  if (fn === 'MULAR') return rollingDynamic(series(x, size), args[1] ?? 1, values => values.reduce((product, value) => product * value, 1))
  if (fn === 'COUNT') return rollingDynamic(series(x, size), args[1] ?? 1, values => values.filter(truthy).length)
  if (fn === 'EVERY') return rollingDynamic(series(x, size), args[1] ?? 1, (values, _index, _start, dynamicPeriod) => values.length >= (dynamicPeriod || 1) && values.every(truthy) ? 1 : 0)
  if (fn === 'EXIST') return rollingDynamic(series(x, size), args[1] ?? 1, values => values.some(truthy) ? 1 : 0)
  if (fn === 'BARSLAST') return barsSince(series(x, size))
  if (fn === 'BARSLASTS') { const values = series(x, size), hits = []; return values.map((value, index) => { if (truthy(value)) hits.push(index); const rank = Math.max(1, periodAt(args[1] ?? 1, index)); return hits.length >= rank ? index - hits[hits.length - rank] : 0 }) }
  if (fn === 'BARSLASTCOUNT') { let count = 0; return series(x, size).map(value => truthy(value) ? ++count : (count = 0)) }
  if (fn === 'BARSSINCE') { let first = -1; return series(x, size).map((value, index) => { if (first < 0 && truthy(value)) first = index; return first < 0 ? 0 : index - first }) }
  if (fn === 'BARSSINCEN') { const values = series(x, size); return values.map((_, index) => { const span = Math.max(1, periodAt(args[1] ?? 1, index)); const start = Math.max(0, index - span + 1); const first = values.slice(start, index + 1).findIndex(truthy); return first < 0 ? 0 : index - (start + first) }) }
  if (fn === 'BARSNEXT') { const values = series(x, size), out = Array(size).fill(0); let next = -1; for (let index = size - 1; index >= 0; index -= 1) { if (truthy(values[index])) next = index; out[index] = next < 0 ? 0 : next - index } return out }
  if (fn === 'HHVBARS' || fn === 'LLVBARS') return rollingDynamic(series(x, size), args[1] ?? 1, (set, index, start) => { const extreme = fn === 'HHVBARS' ? Math.max(...set) : Math.min(...set); return index - (start + set.lastIndexOf(extreme)) })
  if (fn === 'HOD' || fn === 'LOD') return rollingDynamic(series(x, size), args[1] ?? 1, values => { const current = values[values.length - 1]; return 1 + values.filter(value => fn === 'HOD' ? value > current : value < current).length })
  if (fn === 'HHVLLV') return series(x, size).map((_, index) => { const highMode = Number(valueAt(args[1], index)) === 0; const older = periodAt(args[2], index, 0); const newer = periodAt(args[3], index, 0); const start = older === 0 ? 0 : Math.max(0, index - older); const end = newer === 0 ? index : Math.max(0, index - newer); const values = series(x, size).slice(Math.min(start, end), Math.max(start, end) + 1).filter(Number.isFinite); return values.length ? (highMode ? Math.max(...values) : Math.min(...values)) : Number.NaN })
  if (fn === 'BARSCOUNT') return Array.from({ length: size }, (_, index) => index + 1)
  if (fn === 'FILTER') { let remaining = 0; return series(x, size).map((value, index) => { if (remaining) { remaining -= 1; return 0 } if (truthy(value)) { remaining = periodAt(args[1] ?? 1, index); return 1 } return 0 }) }
  if (fn === 'FILTERX') { const values = series(x, size), out = Array(size).fill(0); let remaining = 0; for (let index = size - 1; index >= 0; index -= 1) { if (remaining) remaining -= 1; else if (truthy(values[index])) { out[index] = 1; remaining = periodAt(args[1] ?? 1, index) } } return out }
  if (fn === 'BACKSET') { const out = Array(size).fill(0); const source = series(x, size); const spans = series(args[1] ?? 1, size); source.forEach((value, index) => { if (!value) return; const start = Math.max(0, index - Math.max(0, Math.round(spans[index])) + 1); for (let cursor = start; cursor <= index; cursor += 1) out[cursor] = 1 }); return out }
  if (fn === 'SUMBARS' || fn === 'SUMBARSX') { const values = series(x, size); const targets = series(args[1] ?? 0, size); return values.map((_, index) => { const target = Number(targets[index]) || 0; if (target <= 0) return 0; let total = 0; for (let cursor = index, used = 1; cursor >= 0; cursor -= 1, used += 1) { total += Number(values[cursor]) || 0; if (total >= target) return used } return fn === 'SUMBARSX' ? Number.NaN : index + 1 }) }
  // Cost-distribution and fixed-date data require licensed historical
  // distribution data. Use the current bar series as a neutral visual
  // fallback so non-essential branches never suppress the whole formula.
  if (fn === 'COST') return vars.__CHIP_COSTS?.[Math.max(0, Math.min(100, Math.round(scalar(args[0]))))] || series(vars.C ?? vars.CLOSE ?? 0, size)
  if (fn === 'WINNER' || fn === 'LWINNER') return vars.__CHIP_WINNERS || Array(size).fill(0)
  if (fn === 'REFDATE') { const values = series(x, size); const dates = series(args[1] ?? vars.DATE ?? 0, size); const targetDate = scalar(dates); const match = dates.lastIndexOf(targetDate); const value = values[Math.max(0, match)] ?? values[values.length - 1] ?? 0; return Array(size).fill(value) }
  if (fn === 'DMA' || fn === 'AMA') { let current; const alpha = series(args[1], size); return series(x, size).map((value, index) => { const factor = Math.max(0, Math.min(1, Number(alpha[index]) || 0)); current = index ? factor * value + (1 - factor) * current : value; return current }) }
  if (fn === 'WMA') return rollingDynamic(series(x, size), args[1] ?? 1, values => values.reduce((sum, value, index) => sum + value * (index + 1), 0) / (values.length * (values.length + 1) / 2))
  if (fn === 'TMA' && args.length >= 3) { let current; return series(x, size).map((value, index) => { current = index ? Number(valueAt(args[1], index)) * current + Number(valueAt(args[2], index)) * value : value; return current }) }
  if (fn === 'TMA') return rolling(rolling(series(x, size), Math.ceil(period / 2), avg), Math.floor(period / 2) + 1, avg)
  if (fn === 'STD' || fn === 'STDDEV') return rollingDynamic(series(x, size), args[1] ?? 1, values => Math.sqrt(variance(values, true)))
  if (fn === 'STDP') return rollingDynamic(series(x, size), args[1] ?? 1, values => Math.sqrt(variance(values)))
  if (fn === 'VAR') return rollingDynamic(series(x, size), args[1] ?? 1, values => variance(values, true))
  if (fn === 'VARP') return rollingDynamic(series(x, size), args[1] ?? 1, values => variance(values))
  if (fn === 'DEVSQ') return rollingDynamic(series(x, size), args[1] ?? 1, values => variance(values) * values.length)
  if (fn === 'AVEDEV') return rollingDynamic(series(x, size), args[1] ?? 1, values => avg(values.map(value => Math.abs(value - avg(values)))))
  if (fn === 'MEDIAN') return rollingDynamic(series(x, size), args[1] ?? 1, values => { const sorted = [...values].sort((a, b) => a - b), middle = Math.floor(sorted.length / 2); return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2 })
  if (fn === 'SLOPE') return rollingRegression(series(x, size), args[1] ?? 1, slope => slope)
  if (fn === 'FORCAST') return rollingRegression(series(x, size), args[1] ?? 1, (slope, intercept, length) => intercept + slope * (length - 1))
  if (fn === 'COVAR' || fn === 'RELATE' || fn === 'BETAEX') return rollingPair(args[0], args[1], args[2] ?? 1, (left, right) => { const leftMean = avg(left), rightMean = avg(right); const covariance = avg(left.map((value, index) => (value - leftMean) * (right[index] - rightMean))); if (fn === 'COVAR') return covariance; const leftVariance = variance(left), rightVariance = variance(right); return fn === 'RELATE' ? (leftVariance && rightVariance ? covariance / Math.sqrt(leftVariance * rightVariance) : 0) : (rightVariance ? covariance / rightVariance : 0) }, size)
  if (fn === 'ABS') return vector(x, 0, a => Math.abs(a), size)
  if (fn === 'MAX') return vector(x, args[1], Math.max, size)
  if (fn === 'MIN') return vector(x, args[1], Math.min, size)
  if (fn === 'MAX6' || fn === 'MIN6') return Array.from({ length: size }, (_, index) => (fn === 'MAX6' ? Math.max : Math.min)(...args.map(value => Number(valueAt(value, index)))))
  if (fn === 'POW') return vector(x, args[1], Math.pow, size)
  if (fn === 'SQRT') return vector(x, 0, a => Math.sqrt(Math.max(0, a)), size)
  if (fn === 'EXP') return vector(x, 0, a => Math.exp(a), size)
  if (fn === 'LOG') return vector(x, 0, a => Math.log10(Math.max(a, 1e-12)), size)
  if (fn === 'LN') return vector(x, 0, a => Math.log(Math.max(a, 1e-12)), size)
  if (fn === 'ROUND') return vector(x, 0, Math.round, size)
  if (fn === 'ROUND2') return Array.from({ length: size }, (_, index) => { const scale = 10 ** periodAt(args[1] ?? 0, index, 0); return Math.round(Number(valueAt(x, index)) * scale) / scale })
  if (fn === 'INTPART') return vector(x, 0, Math.trunc, size)
  if (fn === 'FLOOR') return vector(x, 0, Math.floor, size)
  if (fn === 'CEILING') return vector(x, 0, Math.ceil, size)
  if (fn === 'FRACPART') return vector(x, 0, a => a - Math.trunc(a), size)
  if (fn === 'MOD') return vector(x, args[1], (a, b) => b ? a % b : 0, size)
  if (fn === 'SIGN' || fn === 'SGN') return vector(x, 0, Math.sign, size)
  if (['SIN', 'COS', 'TAN', 'ASIN', 'ACOS', 'ATAN'].includes(fn)) return vector(x, 0, Math[fn.toLowerCase()], size)
  if (fn === 'REVERSE') return vector(x, 0, a => -a, size)
  if (fn === 'BETWEEN' || fn === 'RANGE') return vector(x, args[1], (a, low) => a > low ? 1 : 0, size).map((ok, i) => ok && series(x, size)[i] < series(args[2], size)[i] ? 1 : 0)
  if (fn === 'IF' || fn === 'IFF' || fn === 'IFN') return vector(args[0], args[1], (condition, yes) => condition ? yes : 0, size).map((_value, i) => fn === 'IFN' ? (truthy(valueAt(args[0], i)) ? valueAt(args[2], i) : valueAt(args[1], i)) : (truthy(valueAt(args[0], i)) ? valueAt(args[1], i) : valueAt(args[2], i)))
  if (fn === 'IFC') return series(truthy(scalar(args[0])) ? args[1] : args[2], size)
  if (fn === 'CROSS') return series(x, size).map((value, i) => i && value > series(args[1], size)[i] && series(x, size)[i - 1] <= series(args[1], size)[i - 1] ? 1 : 0)
  if (fn === 'LONGCROSS') { const left = series(x, size), right = series(args[1], size); return left.map((value, index) => { const span = Math.max(1, periodAt(args[2] ?? 1, index)); return index >= span && value > right[index] && left.slice(index - span, index).every((item, offset) => item < right[index - span + offset]) ? 1 : 0 }) }
  if (fn === 'UPNDAY' || fn === 'DOWNNDAY') return series(x, size).map((_, i) => i >= period && series(x, size).slice(i - period, i + 1).every((v, j, arr) => !j || (fn === 'UPNDAY' ? v > arr[j - 1] : v < arr[j - 1])) ? 1 : 0)
  if (fn === 'NDAY') { if (args.length === 3) return series(args[0], size).map((_, index) => { const span = periodAt(args[2], index); if (index < span - 1) return 0; for (let cursor = index - span + 1; cursor <= index; cursor += 1) if (!(valueAt(args[0], cursor) > valueAt(args[1], cursor))) return 0; return 1 }); return rollingDynamic(series(x, size), args[1] ?? 1, (values, _index, _start, span) => values.length >= span && values.every(truthy) ? 1 : 0) }
  if (fn === 'LAST' || fn === 'EXISTR') return series(x, size).map((_, index) => { const from = periodAt(args[1], index), to = periodAt(args[2], index, 0); if (index < from) return 0; const values = series(x, size).slice(index - from, index - to + 1); return fn === 'LAST' ? (values.every(truthy) ? 1 : 0) : (values.some(truthy) ? 1 : 0) })
  if (fn === 'VALUEWHEN') { let previous = 0; return series(x, size).map((condition, index) => { if (truthy(condition)) previous = valueAt(args[1], index); return previous }) }
  if (fn === 'CONST') return Array(size).fill(scalar(x))
  if (fn === 'ALIGNRIGHT') { const values = series(x, size), valid = values.filter(value => value !== null && value !== undefined && !(typeof value === 'number' && Number.isNaN(value))); return [...Array(size - valid.length).fill(Number.NaN), ...valid] }
  if (fn === 'TOPRANGE' || fn === 'LOWRANGE') return series(x, size).map((value, index, values) => { let count = 1; for (let cursor = index - 1; cursor >= 0; cursor -= 1) { if (fn === 'TOPRANGE' ? values[cursor] > value : values[cursor] < value) break; count += 1 } return count })
  if (['FINDHIGH', 'FINDHIGHBARS', 'FINDLOW', 'FINDLOWBARS'].includes(fn)) return findExtreme(series(x, size), args[1], args[2], args[3], fn.includes('HIGH'), fn.includes('BARS'))
  if (fn === 'UPDOWN') return series(x, size).map((value, index, values) => index ? Math.sign(value - values[index - 1]) : 0)
  if (fn === 'ISVALID') return series(x, size).map(value => Number.isFinite(Number(value)) ? 1 : 0)
  if (fn === 'ZTPRICE' || fn === 'DTPRICE') return vector(x, args[1], (price, ratio) => Math.round((price * (1 + (fn === 'ZTPRICE' ? 1 : -1) * ratio) + Number.EPSILON) * 100) / 100, size)
  if (fn === 'SAR') {
    if (args.length === 3) return parabolicSar(vars.H, vars.L, scalar(args[0]), Number(scalar(args[1])) / 100, Number(scalar(args[2])) / 100)
    if (args.length === 5) return parabolicSar(series(args[0], size), series(args[1], size), scalar(args[2]), Number(scalar(args[3])) / 100, Number(scalar(args[4])) / 100)
    if (args.length === 4) return parabolicSar(series(args[0], size), series(args[1], size), 4, Number(scalar(args[2])), Number(scalar(args[3])))
    throw new Error('通达信函数参数错误：SAR')
  }
  if (fn === 'SARTURN') {
    if (args.length !== 3) throw new Error('通达信函数参数错误：SARTURN')
    return parabolicSar(vars.H, vars.L, scalar(args[0]), Number(scalar(args[1])) / 100, Number(scalar(args[2])) / 100, true)
  }
  if (fn === 'RSI') { const values = series(x, size), change = values.map((value, index) => index ? value - values[index - 1] : 0), up = smoothDynamic(change.map(value => Math.max(value, 0)), args[1] ?? 1, 1), absolute = smoothDynamic(change.map(Math.abs), args[1] ?? 1, 1); return up.map((value, index) => absolute[index] ? value / absolute[index] * 100 : 0) }
  if (fn === 'TR') return vars.TR || Array(size).fill(0)
  if (fn === 'DYNAINFO') { const mapping = { 3: vars.REFC, 4: vars.O, 5: vars.H, 6: vars.L, 7: vars.C, 8: vars.VOL, 10: vars.AMOUNT, 11: vars.AVGPRICE }; return Array(size).fill(scalar(mapping[Math.round(Number(scalar(args[0])))] || 0)) }
  if (fn === 'DATETODAY') return series(x, size).map(value => { const date = parseTdxDate(value); return date ? Math.round((date.getTime() - TDX_DAY_ZERO_UTC) / 86400000) : Number.NaN })
  if (fn === 'DAYTODATE') return series(x, size).map(value => { const days = Math.trunc(Number(value)); return Number.isFinite(days) ? formatTdxDate(new Date(TDX_DAY_ZERO_UTC + days * 86400000)) : Number.NaN })
  if (fn === 'TIMETOSEC') return series(x, size).map(value => { const time = Math.max(0, Math.trunc(Number(value)) || 0); return Math.trunc(time / 10000) * 3600 + Math.trunc((time % 10000) / 100) * 60 + time % 100 })
  if (fn === 'SECTOTIME') return series(x, size).map(value => { const seconds = Math.max(0, Math.min(86399, Math.trunc(Number(value)) || 0)); const hour = Math.trunc(seconds / 3600), minute = Math.trunc((seconds % 3600) / 60); return hour * 10000 + minute * 100 + seconds % 60 })
  if (fn === 'ISLASTBAR') return Array.from({ length: size }, (_, index) => index === size - 1 ? 1 : 0)
  if (fn === 'DRAWNULL') return Array(size).fill(Number.NaN)
  if (fn === 'RGB') return `#${args.slice(0, 3).map(value => Math.max(0, Math.min(255, Math.round(Number(scalar(value))))).toString(16).padStart(2, '0')).join('')}`
  if (fn === 'STRCAT') return `${scalar(args[0] ?? '')}${scalar(args[1] ?? '')}`
  if (fn === 'STRCAT6') return args.slice(0, 6).map(value => scalar(value) ?? '').join('')
  if (fn === 'VARCAT' || fn === 'VARCAT6') return Array.from({ length: size }, (_, index) => args.slice(0, fn === 'VARCAT6' ? 6 : 2).map(value => valueAt(value, index) ?? '').join(''))
  if (fn === 'VAR2STR') return formattedSeries(args[0], args[1], size)
  if (fn === 'CON2STR') return formattedSeries(args[0], args[1], size).at(-1)
  if (fn === 'STR2CON') { const value = Number(scalar(x)); return Number.isFinite(value) ? value : Number.NaN }
  if (fn === 'STRSPACE') return `${scalar(x) ?? ''} `
  if (fn === 'STRLEN') return String(scalar(x) ?? '').length
  if (fn === 'STRCMP') return vector(x, args[1], (left, right) => String(left) === String(right) ? 1 : 0, size)
  if (fn === 'FINDSTR') return vector(x, args[1], (left, right) => String(left).includes(String(right)) ? 1 : 0, size)
  if (fn === 'SUBSTR') return series(x, size).map((value, index) => { const start = Math.max(0, periodAt(args[1], index, 1) - 1); return String(value ?? '').slice(start, start + periodAt(args[2], index, 0)) })
  if (fn === 'CODELIKE') return String(scalar(vars.CODE) ?? '').startsWith(String(scalar(x) ?? '')) ? 1 : 0
  if (fn === 'NAMELIKE') return String(scalar(vars.STKNAME) ?? '').startsWith(String(scalar(x) ?? '')) ? 1 : 0
  if (fn === 'NAMEINCLUDE') return String(scalar(vars.STKNAME) ?? '').includes(String(scalar(x) ?? '')) ? 1 : 0
  if (fn === 'INBLOCK') return 0
  // FINANCE and intraday large-order fields require a separate fundamentals /
  // money-flow entitlement. Keep those signal branches neutral until that
  // authorised data source is connected, rather than hiding the entire chart.
  if (fn === 'FINANCE') return Array(size).fill(0)
  throw new Error(`暂不支持通达信函数：${fn}`)
}
function drawLine(startCondition, startValues, endCondition, endValues, expand, size) {
  const values = Array(size).fill(null)
  const starts = series(startCondition, size)
  const ends = series(endCondition, size)
  const first = series(startValues, size)
  const second = series(endValues, size)
  let start = null
  for (let index = 0; index < size; index += 1) {
    if (starts[index]) start = { index, value: first[index] }
    if (!start || !ends[index] || index < start.index) continue
    const length = Math.max(1, index - start.index)
    const slope = (second[index] - start.value) / length
    for (let cursor = start.index; cursor <= index; cursor += 1) values[cursor] = start.value + slope * (cursor - start.index)
    // Tongdaxin's EXPAND line remains on the slope defined by both anchor
    // points. A later completed pair overwrites this provisional extension,
    // which is why this drawing function is classified as a future function.
    if (Number(expand) >= 1) {
      for (let cursor = index + 1; cursor < size; cursor += 1) values[cursor] = second[index] + slope * (cursor - index)
    }
    start = null
  }
  return values
}
const formulaLineWidth = text => Math.max(1, Math.min(9, Number(String(text).match(/LINETHICK\s*(\d+)/i)?.[1]) || 1))
const formulaLineStyle = text => {
  const style = String(text)
  if (/\bCIRCLEDOT\b/i.test(style)) return 'circle-dot'
  if (/\bCROSSDOT\b/i.test(style)) return 'cross-dot'
  if (/\bPOINTDOT\b/i.test(style)) return 'point-dot'
  if (/\bDOTLINE\b/i.test(style)) return 'dotted'
  return 'solid'
}

function pushPointGroups(sticks, rows, width, empty = 0, layer = 'normal') {
  const groups = new Map()
  rows.forEach(row => {
    if (!row || !Number.isFinite(row.from) || !Number.isFinite(row.to)) return
    const color = formulaColor(row.color)
    if (!groups.has(color)) groups.set(color, { condition: [], from: [], to: [], width: [], empty: [], color, layer })
    const group = groups.get(color)
    group.condition[row.index] = 1
    group.from[row.index] = row.from
    group.to[row.index] = row.to
    group.width[row.index] = width
    group.empty[row.index] = empty
  })
  sticks.push(...groups.values())
}

function iconText(value) {
  return ({ 1: '↑', 2: '↓', 3: '▲', 4: '▼', 5: '◆', 6: '◇', 7: '●', 8: '○', 9: '★', 10: '☆' })[Math.round(Number(value))] || '●'
}

export const TONGDAXIN_COMPAT_FUNCTIONS = [
  'ABS', 'ACOS', 'ALIGNRIGHT', 'AMA', 'ASIN', 'ATAN', 'AVEDEV', 'BACKSET', 'BARSCOUNT', 'BARSLAST',
  'BARSLASTCOUNT', 'BARSLASTS', 'BARSNEXT', 'BARSSINCE', 'BARSSINCEN', 'BARSTATUS', 'BETWEEN', 'CEILING', 'CON2STR',
  'CODELIKE', 'CONST', 'COS', 'COST', 'COUNT', 'COVAR', 'CROSS', 'CURRBARSCOUNT', 'DATETODAY', 'DAYTODATE', 'DEVSQ', 'DMA',
  'DRAWTEXT', 'DRAWTEXT_FIX', 'DRAWICON', 'DRAWKLINE', 'DRAWLINE', 'DRAWNUMBER',
  'DRAWNUMBER_FIX', 'DRAWBAND', 'DRAWNULL', 'DTPRICE', 'DYNAINFO', 'EMA', 'EVERY',
  'EXIST', 'EXISTR', 'EXP', 'EXPMA', 'EXPMEMA', 'FILTER', 'FILTERX', 'FINDHIGH',
  'FINDHIGHBARS', 'FINDLOW', 'FINDLOWBARS', 'FINDSTR', 'FLOOR', 'FORCAST', 'FRACPART',
  'HHV', 'HHVBARS', 'HHVLLV', 'HOD', 'IF', 'IFC', 'IFF', 'IFN', 'INBLOCK', 'INTPART', 'ISLASTBAR', 'ISVALID',
  'LAST', 'LLV', 'LLVBARS', 'LN', 'LOG', 'LONGCROSS', 'LOWRANGE', 'LWINNER', 'MA',
  'MAX', 'MAX6', 'MEDIAN', 'MEMA', 'MIN', 'MIN6', 'MOD', 'MULAR', 'NAMELIKE', 'NAMEINCLUDE', 'NDAY', 'NOT',
  'POLYLINE', 'PLOYLINE', 'POW', 'REF', 'REFDATE', 'REFV', 'REFX', 'REFXV', 'RELATE',
  'REVERSE', 'RGB', 'ROUND', 'ROUND2', 'RSI', 'SAR', 'SGN', 'SIGN', 'SIN', 'SLOPE',
  'SARTURN', 'SECTOTIME', 'SMA', 'SQRT', 'STD', 'STDDEV', 'STDP', 'STICKLINE', 'STR2CON', 'STRCAT', 'STRCAT6', 'STRCMP',
  'STRLEN', 'STRSPACE', 'SUBSTR', 'SUM', 'SUMBARS', 'SUMBARSX', 'TAN', 'TIMETOSEC', 'TMA', 'TOPRANGE',
  'TOTALBARSCOUNT', 'TR', 'UPDOWN', 'UPNDAY', 'VALUEWHEN', 'VAR', 'VAR2STR', 'VARP', 'LOD',
  'VARCAT', 'VARCAT6', 'WEEKOFYEAR', 'WINNER', 'WMA', 'XMA', 'ZTPRICE',
]

export const TONGDAXIN_APPROXIMATE_FUNCTIONS = ['COST', 'LWINNER', 'WINNER']
export const TONGDAXIN_DATA_BOUND_FUNCTIONS = ['FINANCE', 'INBLOCK']
export const TONGDAXIN_PARTIAL_RENDERERS = ['DRAWICON', 'STICKLINE']

// Known client/data fields stay neutral until an authorised provider supplies
// them. An explicit registry lets strict parsing distinguish them from typos.
export const TONGDAXIN_EXTERNAL_FIELDS = [
  'ACTINVOL', 'ACTOUTVOL', 'ADVANCE', 'AVGBIDPX', 'AVGOFFERPX', 'BIDCANCELVOL',
  'BIDORDERVOL', 'DECLINE', 'DHIGH', 'DOPEN', 'DLOW', 'DCLOSE', 'DVOL',
  'HKSHORTVOL', 'INDEXA', 'INDEXADV', 'INDEXC', 'INDEXDEC', 'INDEXH', 'INDEXL',
  'INDEXO', 'INDEXV', 'LARGEINTRDVOL', 'LARGEOUTTRDVOL', 'LARGETRDINNUM',
  'LARGETRDOUTNUM', 'L2_AMO', 'L2_VOL', 'L2_VOLNUM', 'OFFERCANCELVOL',
  'OFFERORDERVOL', 'QHJSJ', 'TOTALFZNUM', 'TOTALMMPAMO', 'TRADENUM',
  'TRADEINNUM', 'TRADEOUTNUM', 'VOLINSTK', 'ZSTJJ',
]

export function compileTongdaxinFormulaExpanded(source, bars, chips = {}, options = {}) {
  const closes = bars.map(bar => Number(bar.close))
  const opens = bars.map(bar => Number(bar.open))
  const highs = bars.map(bar => Number(bar.high))
  const lows = bars.map(bar => Number(bar.low))
  const rawVolumes = bars.map(bar => Number(bar.volume || 0))
  // OpenD returns share counts. Tongdaxin's VOL/CAPITAL unit for mainland
  // equities is one hand (100 shares), while AMOUNT remains currency units.
  const lotSize = Number(options.lotSize) || (/^(?:SH|SZ|BJ)\./i.test(options.symbol || '') ? 100 : 1)
  const volumes = rawVolumes.map(value => value / lotSize)
  const amounts = bars.map(bar => Number(bar.amount || 0))
  const dates = bars.map(bar => new Date(Number(bar.time) * 1000))
  const periodCodes = { '1分': 0, '3分': 8, '5分': 1, '10分': 8, '15分': 2, '30分': 3, '1小时': 4, '2小时': 8, '4小时': 8, '日线': 5, '周线': 6, '月线': 7, '季线': 10, '年线': 11 }
  const vars = {
    C: closes, CLOSE: closes, O: opens, OPEN: opens, H: highs, HIGH: highs,
    L: lows, LOW: lows, V: volumes, VOL: volumes, VOLUME: volumes,
    AMO: amounts, AMOUNT: amounts,
    REFC: closes.map((_, index) => index ? closes[index - 1] : Number(bars[index]?.last_close ?? closes[index])),
    AVGPRICE: amounts.map((amount, index) => rawVolumes[index] ? amount / rawVolumes[index] : closes[index]),
    TR: highs.map((high, index) => index ? Math.max(high - lows[index], Math.abs(high - closes[index - 1]), Math.abs(lows[index] - closes[index - 1])) : high - lows[index]),
    DATE: dates.map(date => (date.getFullYear() - 1900) * 10000 + (date.getMonth() + 1) * 100 + date.getDate()),
    TIME: dates.map(date => date.getHours() * 100 + date.getMinutes()),
    TIME2: dates.map(date => date.getHours() * 10000 + date.getMinutes() * 100 + date.getSeconds()),
    YEAR: dates.map(date => date.getFullYear()), MONTH: dates.map(date => date.getMonth() + 1),
    DAY: dates.map(date => date.getDate()), HOUR: dates.map(date => date.getHours()),
    MINUTE: dates.map(date => date.getMinutes()), WEEKDAY: dates.map(date => date.getDay()),
    WEEK: dates.map(date => date.getDay()), WEEKOFYEAR: dates.map(isoWeekOfYear),
    CODE: String(options.symbol || '').split('.').at(-1), STKNAME: String(options.name || ''),
    HYBLOCK: '', DYBLOCK: '', GNBLOCK: '', FGBLOCK: '', ZDBLOCK: '', ZHBLOCK: '', ZSBLOCK: '',
    LEVEL1HYBLOCK: '', TOKENWORD: '', HQCRBK: 0,
    ISLASTBAR: bars.map((_, index) => index === bars.length - 1 ? 1 : 0),
    CURRBARSCOUNT: bars.map((_, index) => bars.length - index),
    TOTALBARSCOUNT: Array(bars.length).fill(bars.length),
    BARSCOUNT: bars.map((_, index) => index + 1),
    BARSTATUS: bars.map((_, index) => index === 0 ? 1 : index === bars.length - 1 ? 2 : 0),
    PERIOD: Array(bars.length).fill(periodCodes[options.period] ?? 5),
    DRAWNULL: Array(bars.length).fill(Number.NaN),
    CAPITAL: Array(bars.length).fill(Number(chips.floatShares || 0) / lotSize),
    TOTALCAPITAL: Array(bars.length).fill(Number(chips.totalShares || chips.floatShares || 0) / lotSize),
    __CHIP_COSTS: chips.costs || {},
    __CHIP_WINNERS: chips.winners || Array(bars.length).fill(0),
  }
  for (const field of TONGDAXIN_EXTERNAL_FIELDS) {
    if (!Object.prototype.hasOwnProperty.call(vars, field)) vars[field] = Array(bars.length).fill(0)
  }
  const lines = []
  const sticks = []
  const markers = []
  const fixedTexts = []
  const parameters = parameterAssignments(source)
  const drawingNames = 'STICKLINE|DRAWTEXT|DRAWTEXT_FIX|DRAWNUMBER|DRAWNUMBER_FIX|DRAWICON|DRAWLINE|POLYLINE|PLOYLINE|DRAWBAND|DRAWKLINE'
  const code = (parameters.join('') + source.replace(/\{[\s\S]*?\}/g, ''))
    .replace(new RegExp(`(?:^|;)\\s*[^:;]+:\\s*((?:${drawingNames})\\([^;]+)(?=;|$)`, 'gi'), (_all, call) => `;${call}`)

  for (const statement of splitStatements(code).map(item => item.trim()).filter(Boolean)) {
    const assignment = statement.match(/^(.+?)(:=|:)([\s\S]+)$/)
    if (assignment) {
      const name = assignment[1].trim().toUpperCase()
      const chunks = split(assignment[3])
      const value = execute(parser(chunks[0]), vars, bars.length)
      vars[name] = value
      if (assignment[2] === ':' && !chunks.some(chunk => /^NODRAW$/i.test(chunk))) {
        const styleText = chunks.join(',')
        const color = formulaColor(chunks.find(chunk => /^COLOR(?!STICK)/i.test(chunk)) || 'COLORBLUE')
        const stickStyle = chunks.some(chunk => /^(?:COLORSTICK|VOLSTICK|STICK)$/i.test(chunk))
        if (stickStyle) {
          pushPointGroups(sticks, series(value, bars.length).map((item, index) => ({
            index, from: 0, to: Number(item),
            color: /VOLSTICK/i.test(styleText) ? (closes[index] >= opens[index] ? COLORS.RED : COLORS.GREEN) : (Number(item) >= 0 ? COLORS.RED : COLORS.GREEN),
          })), 7)
        }
        if (!stickStyle || /LINESTICK/i.test(styleText)) lines.push({ name, values: series(value, bars.length), color, style: formulaLineStyle(styleText), width: formulaLineWidth(styleText) })
      }
      continue
    }

    const call = statement.match(new RegExp(`^(${drawingNames})\\(([\\s\\S]*)\\)([\\s\\S]*)$`, 'i'))
    if (call) {
      const callName = call[1].toUpperCase()
      const args = split(call[2]).map(item => execute(parser(item), vars, bars.length))
      const color = formulaColor(call[3].match(/COLOR([A-Z0-9]+)/i)?.[1] || 'BLUE')
      if (callName === 'STICKLINE') {
        const requestedWidths = series(args[3], bars.length).map(Number).filter(Number.isFinite)
        const layer = requestedWidths.length && Math.max(...requestedWidths) > 4 ? 'background' : 'normal'
        sticks.push({ condition: args[0], from: args[1], to: args[2], width: args[3], empty: args[4], color, layer })
      }
      else if (callName === 'DRAWLINE') lines.push({ name: 'DRAWLINE', values: drawLine(args[0], args[1], args[2], args[3], scalar(args[4]), bars.length), color, style: formulaLineStyle(call[3]), width: formulaLineWidth(call[3]) })
      else if (callName === 'POLYLINE' || callName === 'PLOYLINE') lines.push({ name: callName, values: series(args[1], bars.length).map((value, index) => truthy(valueAt(args[0], index)) ? value : null), color, style: formulaLineStyle(call[3]), width: formulaLineWidth(call[3]) })
      else if (callName === 'DRAWTEXT' || callName === 'DRAWNUMBER' || callName === 'DRAWICON') markers.push({
        condition: args[0], value: args[1],
        text: callName === 'DRAWTEXT' ? args[2] : callName === 'DRAWNUMBER' ? formattedSeries(args[2], 2, bars.length) : series(args[2], bars.length).map(iconText), color,
      })
      else if (callName === 'DRAWTEXT_FIX' || callName === 'DRAWNUMBER_FIX') {
        if (series(args[0], bars.length).some(truthy)) fixedTexts.push({ x: Number(scalar(args[1])), y: Number(scalar(args[2])), align: Number(scalar(args[3])), text: String(scalar(args[4]) ?? ''), color })
      } else if (callName === 'DRAWBAND') {
        const upper = series(args[0], bars.length), lower = series(args[2], bars.length)
        pushPointGroups(sticks, upper.map((value, index) => ({ index, from: value, to: lower[index], color: value >= lower[index] ? valueAt(args[1], index) : valueAt(args[3], index) })), 10, 0, 'background')
      } else if (callName === 'DRAWKLINE') {
        const high = series(args[0], bars.length), open = series(args[1], bars.length), low = series(args[2], bars.length), close = series(args[3], bars.length)
        pushPointGroups(sticks, high.map((value, index) => ({ index, from: low[index], to: value, color: close[index] >= open[index] ? COLORS.RED : COLORS.GREEN })), 0)
        pushPointGroups(sticks, open.map((value, index) => ({ index, from: value, to: close[index], color: close[index] >= value ? COLORS.RED : COLORS.GREEN })), 7)
      }
      continue
    }

    const chunks = split(statement)
    const value = execute(parser(chunks[0]), vars, bars.length)
    if (typeof value === 'number' || Array.isArray(value)) {
      const styleText = chunks.join(',')
      lines.push({ name: `LINE${lines.length + 1}`, values: series(value, bars.length), color: formulaColor(chunks.find(chunk => /^COLOR/i.test(chunk)) || 'COLORBLUE'), style: formulaLineStyle(styleText), width: formulaLineWidth(styleText) })
    }
  }
  return { lines, sticks, markers, fixedTexts }
}
