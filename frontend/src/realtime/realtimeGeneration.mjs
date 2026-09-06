export function reconcileRealtimeVersion(currentEpoch = '', currentRevision = 0, incoming = {}) {
  const epoch = String(incoming?.epoch || '').trim()
  if (!epoch) return { accepted: false, changed: false, epoch: currentEpoch, revision: currentRevision }
  const revision = Math.max(0, Number(incoming?.revision || 0))
  if (!currentEpoch || epoch !== currentEpoch) {
    return { accepted: true, changed: epoch !== currentEpoch, epoch, revision }
  }
  if (revision < Number(currentRevision || 0)) {
    return { accepted: false, changed: false, epoch, revision }
  }
  return { accepted: true, changed: false, epoch, revision }
}

export function isFormulaResponseGenerationSafe(currentEpoch = '', requestedEpoch = '', responseEpoch = '') {
  if (!responseEpoch) return false
  // A response from the epoch used by the request is stale if the stream has
  // already advanced to another epoch. A different response epoch is allowed
  // to establish the new authority when the stream has not done so yet.
  if (requestedEpoch && currentEpoch !== requestedEpoch && responseEpoch !== currentEpoch) return false
  return true
}
