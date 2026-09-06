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
