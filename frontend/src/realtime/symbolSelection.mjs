// Keep the selected instrument's label and market bound to its code.
// A delayed selection/list refresh may hold older display metadata, but an
// authoritative visible catalog row must win for that *same* code only.
const codeKey = value => String(value || '').trim().toUpperCase()

export function resolveSelectedSymbol(selected, catalog) {
  if (!selected?.code) return null
  const key = codeKey(selected.code)
  const match = Array.isArray(catalog)
    ? catalog.find(item => codeKey(item?.code) === key)
    : null
  if (!match || typeof match.name !== 'string' || !match.name.trim() ||
      typeof match.market !== 'string' || !match.market) {
    return { ...selected }
  }
  return { ...selected, ...match }
}
