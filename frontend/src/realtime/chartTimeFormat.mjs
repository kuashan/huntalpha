// Display-only time formatting. Raw UTC timestamps stay unchanged for all
// indicators, live updates, historical series and crosshair coordinates.
const CALENDAR_PERIODS = new Set(['日线', '周线', '月线'])

export function createChartTimeFormatters(period, timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone) {
  const calendarPeriod = CALENDAR_PERIODS.has(period)
  const partsFormatter = new Intl.DateTimeFormat('en-GB', {
    timeZone, year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  })
  function parts(time) {
    const date = typeof time === 'number'
      ? new Date(time * 1000)
      : new Date(Date.UTC(time.year, time.month - 1, time.day))
    return Object.fromEntries(partsFormatter.formatToParts(date).map(item => [item.type, item.value]))
  }
  return {
    timeVisible: !calendarPeriod,
    timeFormatter(time) {
      const { year, month, day, hour, minute } = parts(time)
      return calendarPeriod ? `${year}-${month}-${day}` : `${year}-${month}-${day} ${hour}:${minute}`
    },
    tickMarkFormatter(time, tickMarkType) {
      const { year, month, day, hour, minute } = parts(time)
      if (tickMarkType === 0) return year
      if (tickMarkType === 1) return `${month}/${year.slice(-2)}`
      if (calendarPeriod || tickMarkType === 2) return `${month}/${day}`
      return `${hour}:${minute}`
    },
  }
}
