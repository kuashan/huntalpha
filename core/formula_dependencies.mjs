const chipFunctions = new Set(['COST', 'WINNER', 'LWINNER'])

function skipQuoted(text, start) {
  const quote = text[start]
  let index = start + 1
  while (index < text.length) {
    if (text[index] === '\\') {
      index += 2
      continue
    }
    if (text[index] === quote) {
      if (text[index + 1] === quote) {
        index += 2
        continue
      }
      return index + 1
    }
    index += 1
  }
  return text.length
}

function skipComment(text, start) {
  if (text[start] === '{') {
    let depth = 1
    let index = start + 1
    while (index < text.length && depth) {
      if (text[index] === "'" || text[index] === '"') {
        index = skipQuoted(text, index)
      } else if (text[index] === '{') {
        depth += 1
        index += 1
      } else if (text[index] === '}') {
        depth -= 1
        index += 1
      } else {
        index += 1
      }
    }
    return index
  }
  if (text.startsWith('//', start)) {
    const newline = text.indexOf('\n', start + 2)
    return newline < 0 ? text.length : newline + 1
  }
  if (text.startsWith('/*', start)) {
    const end = text.indexOf('*/', start + 2)
    return end < 0 ? text.length : end + 2
  }
  return start
}

function skipTrivia(text, start) {
  let index = start
  while (index < text.length) {
    if (/\s/.test(text[index])) {
      index += 1
      continue
    }
    const afterComment = skipComment(text, index)
    if (afterComment !== index) {
      index = afterComment
      continue
    }
    break
  }
  return index
}

function identifierStart(character) {
  return /[A-Za-z_\u4e00-\u9fff]/.test(character)
}

function identifierPart(character) {
  return /[A-Za-z0-9_\u4e00-\u9fff]/.test(character)
}

// A dependency pre-check deliberately recognizes calls, not words. It skips
// strings and all supported formula comment forms so labels such as
// "COST(50)" and commented-out calls cannot trigger chip calculation.
export function formulaUsesChipFunctions(source) {
  const text = String(source || '')
  let index = 0
  while (index < text.length) {
    const afterTrivia = skipTrivia(text, index)
    if (afterTrivia !== index) {
      index = afterTrivia
      continue
    }
    if (text[index] === "'" || text[index] === '"') {
      index = skipQuoted(text, index)
      continue
    }
    if (!identifierStart(text[index])) {
      index += 1
      continue
    }
    const start = index
    index += 1
    while (index < text.length && identifierPart(text[index])) index += 1
    const name = text.slice(start, index).toUpperCase()
    const next = skipTrivia(text, index)
    if (text[next] === '(' && chipFunctions.has(name)) return true
    index = next
  }
  return false
}
