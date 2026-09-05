import { readFileSync } from 'node:fs'
import { runFormulaRequest } from './formula_runner_core.mjs'

try {
  const request = JSON.parse(readFileSync(0, 'utf8'))
  process.stdout.write(JSON.stringify(runFormulaRequest(request)))
} catch (error) {
  process.stderr.write(error instanceof Error ? error.message : String(error))
  process.exitCode = 1
}
