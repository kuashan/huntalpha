export function settleHistoryReconcile({
  current,
  pendingGeneration = null,
  currentGeneration,
  needsHistoryReconcile,
  hidden,
  hasChart,
  hasSymbol,
}) {
  const hasPending = pendingGeneration !== null && pendingGeneration !== undefined
  if (hasPending || (!current && needsHistoryReconcile)) {
    return {
      action: !hidden && hasChart && hasSymbol ? 'reconcile' : 'retry',
      generation: currentGeneration,
      needsHistoryReconcile: true,
    }
  }
  if (!current) return { action: 'idle', generation: currentGeneration, needsHistoryReconcile }
  return { action: 'complete', generation: currentGeneration, needsHistoryReconcile: false }
}
