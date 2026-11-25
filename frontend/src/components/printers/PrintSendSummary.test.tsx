/**
 * PrintSendSummary (spec 011, US1): the summary the operator confirms.
 */
import { describe, expect, it } from 'vitest'
import { render, screen, within } from '@testing-library/react'

import { PrintSendSummary } from './PrintSendSummary'
import { summaryFixture } from './printSendFixtures'

describe('PrintSendSummary', () => {
  it('shows printer, file, plate, time and weight', () => {
    render(<PrintSendSummary summary={summaryFixture()} />)

    expect(screen.getByText('X1 Carbon')).toBeInTheDocument()
    expect(screen.getByText('dragon.gcode.3mf')).toBeInTheDocument()
    expect(screen.getByText('1 h 35 min')).toBeInTheDocument()
    expect(screen.getByText('35.10 g')).toBeInTheDocument()
  })

  it('shows each filament with its slot, spool and printer report', () => {
    render(<PrintSendSummary summary={summaryFixture()} />)

    expect(screen.getByText('→ AMS 1 · slot 2')).toBeInTheDocument()
    expect(screen.getByText(/SP-PETG/)).toBeInTheDocument()
    expect(screen.getByText('Printer: PETG')).toBeInTheDocument()
    expect(screen.getByText('Batchivo: external spool')).toBeInTheDocument()
  })

  it('flags the mismatch on the line and in the warning list', () => {
    render(<PrintSendSummary summary={summaryFixture()} />)

    expect(screen.getByText('Material differs')).toBeInTheDocument()
    const warnings = screen.getByRole('list', { name: 'Warnings' })
    expect(within(warnings).getByText(/Plate expects PLA/)).toBeInTheDocument()
  })

  it('lists blockers', () => {
    render(
      <PrintSendSummary
        summary={summaryFixture({
          blockers: [{ code: 'printer_busy', message: 'The printer is busy (RUNNING)', filament_id: null }],
        })}
      />
    )
    expect(screen.getByRole('list', { name: 'Blockers' })).toHaveTextContent('busy')
  })
})
