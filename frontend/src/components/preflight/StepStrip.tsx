/**
 * Where a part stands in Preflight's fourteen steps (spec 009, US1).
 *
 * Each step shows its status; a member changes one with its select, which is
 * saved at once. A viewer reads the same strip without the selects.
 */
import { STEP_STATUSES, type StepName, type StepState, type StepStatus } from '@/types/preflight'
import { STEP_STATUS_CLASS, STEP_STATUS_TEXT, STEP_TEXT } from './preflightText'

interface StepStripProps {
  steps: StepState[]
  canWrite: boolean
  onChange: (step: StepName, status: StepStatus) => void
  disabled?: boolean
}

export function StepStrip({ steps, canWrite, onChange, disabled }: StepStripProps) {
  return (
    <ol aria-label="Preflight steps" className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
      {steps.map((state) => (
        <li
          key={state.step}
          className={`rounded-md border px-2 py-1 text-xs ${STEP_STATUS_CLASS[state.status]}`}
          title={state.updated_by ? `${state.updated_by.name}, ${new Date(state.updated_at ?? '').toLocaleString()}` : undefined}
        >
          <div className="font-semibold">{STEP_TEXT[state.step]}</div>
          {canWrite ? (
            <select
              aria-label={`${STEP_TEXT[state.step]} status`}
              className="mt-0.5 h-6 w-full rounded border bg-background px-1 text-xs text-foreground"
              value={state.status}
              disabled={disabled}
              onChange={(e) => onChange(state.step, e.target.value as StepStatus)}
            >
              {STEP_STATUSES.map((status) => (
                <option key={status} value={status}>
                  {STEP_STATUS_TEXT[status]}
                </option>
              ))}
            </select>
          ) : (
            <div>{STEP_STATUS_TEXT[state.status]}</div>
          )}
        </li>
      ))}
    </ol>
  )
}
