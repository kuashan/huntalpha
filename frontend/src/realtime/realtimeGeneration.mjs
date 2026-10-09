export function reconcileRealtimeVersion(currentEpoch = '', currentRevision = 0, incoming = {}) {
  const epoch = String(incoming?.epoch || '').trim()
  if (!epoch) return { accepted: false, changed: false, reason: 'missing_epoch', epoch: currentEpoch, revision: currentRevision }
  const rawRevision = incoming?.revision ?? 0
  const parsedRevision = Number(rawRevision)
  if (!Number.isFinite(parsedRevision) || parsedRevision < 0) {
    return { accepted: false, changed: false, reason: 'invalid_revision', epoch, revision: currentRevision }
  }
  const revision = parsedRevision
  if (!currentEpoch || epoch !== currentEpoch) {
    return { accepted: true, changed: true, reason: 'new_epoch', epoch, revision }
  }
  if (revision < Number(currentRevision || 0)) {
    return { accepted: false, changed: false, reason: 'stale_revision', epoch, revision }
  }
  return { accepted: true, changed: false, reason: 'accepted', epoch, revision }
}

export function isFormulaResponseGenerationSafe(currentEpoch = '', requestedEpoch = '', responseEpoch = '') {
  if (!responseEpoch) return false
  // A response from the epoch used by the request is stale if the stream has
  // already advanced to another epoch. A different response epoch is allowed
  // to establish the new authority when the stream has not done so yet.
  if (requestedEpoch && currentEpoch !== requestedEpoch && responseEpoch !== currentEpoch) return false
  return true
}
