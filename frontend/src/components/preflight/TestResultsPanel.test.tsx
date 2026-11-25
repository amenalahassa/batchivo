/** A model's test prints and the SC-005 summary line (spec 009, US4). */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render as plainRender } from '@testing-library/react'

import { render, screen } from '@/test/test-utils'
import { listFileNotes } from '@/lib/api/modelFileNotes'
import { printTestResultsApi } from '@/lib/api/preflight'
import { SummaryLine, TestResultsPanel } from './TestResultsPanel'
import { aTestResult } from './preflightTestData'

vi.mock('@/lib/api/preflight', () => ({
  printTestResultsApi: {
    list: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    uploadPhoto: vi.fn(),
    photoPath: vi.fn(() => null),
  },
}))
vi.mock('@/lib/api/modelFileNotes', () => ({ listFileNotes: vi.fn() }))
vi.mock('@/lib/api/modelFileVersions', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/api/modelFileVersions')>()),
  listFileVersions: vi.fn().mockResolvedValue([]),
}))

describe('SummaryLine', () => {
  it('says how many failures are open and how the last test went', () => {
    plainRender(<SummaryLine openFailures={2} latest={aTestResult()} />)
    const line = screen.getByRole('status')
    expect(line).toHaveTextContent('2 open failures')
    expect(line).toHaveTextContent('Last test: Fail (Critical zone, version 1')
  })

  it('reads well with nothing recorded', () => {
    plainRender(<SummaryLine openFailures={0} latest={undefined} />)
    expect(screen.getByRole('status')).toHaveTextContent('No open failure · No test print recorded yet')
  })
})

describe('TestResultsPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(printTestResultsApi.list).mockResolvedValue({ items: [aTestResult()], total: 1 })
    vi.mocked(listFileNotes).mockResolvedValue([])
  })

  it('lists results with outcome, failure mode and measurements', async () => {
    render(<TestResultsPanel modelId="model-1" canWrite={false} />)
    expect(await screen.findByText('Failure: broke at the root at 7 kg')).toBeInTheDocument()
    expect(screen.getByText('load_kg: 7 kg (expected 5)')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Record a test' })).not.toBeInTheDocument()
    expect(listFileNotes).toHaveBeenCalledWith('model-1', { severity: 'failure', status: 'open' })
  })

  it('offers a member to record and correct', async () => {
    render(<TestResultsPanel modelId="model-1" canWrite />)
    expect(await screen.findByRole('button', { name: 'Record a test' })).toBeInTheDocument()
    expect(await screen.findByLabelText('Correct outcome')).toHaveValue('fail')
  })
})
