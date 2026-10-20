/** Server times are UTC instants; display in the viewer's local timezone. */
export function membershipExpiryText(membership) {
  if (!membership || membership.tier !== 'pro') return ''
  if (!membership.expires_at) return '长期有效'
  const instant = new Date(membership.expires_at)
  if (!Number.isFinite(instant.getTime())) return '—'
  return new Intl.DateTimeFormat('sv-SE', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  }).format(instant)
}
