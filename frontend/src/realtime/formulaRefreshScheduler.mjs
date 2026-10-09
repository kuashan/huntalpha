export function shouldScheduleFormulaRefresh({
  pendingRevision,
  refreshPending,
  timerActive,
  hasChart,
  hasSymbol,
}) {
  return Boolean(
    !timerActive
    && hasChart
    && hasSymbol
    && (refreshPending || Number(pendingRevision || 0) > 0),
  )
}

export function isCurrentFormulaResult({ runToken, currentRunToken, generation, currentGeneration }) {
  return runToken === currentRunToken && generation === currentGeneration
}
