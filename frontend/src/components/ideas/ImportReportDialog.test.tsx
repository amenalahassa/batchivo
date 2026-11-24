/** Importing a pain-point report: read, preview, import (spec 007, FR-031 to FR-033, T051). */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import userEvent from '@testing-library/user-event'

import { render, screen, within } from '@/test/test-utils'

import { ImportReportDialog } from './ImportReportDialog'

const api = vi.hoisted(() => ({ parseReport: vi.fn(), importItems: vi.fn() }))
vi.mock('@/lib/api/ideas', () => ({ ideasApi: api }))

const ITEMS = [
  { title: 'Visor clip', report_score: 20, source_url: 'https://r/1', tags: ['car'] },
  { title: 'Hose guide', report_score: 18, source_url: 'https://r/2', tags: ['garden'] },
]

beforeEach(() => {
  api.parseReport.mockReset()
  api.importItems.mockReset()
  api.parseReport.mockResolvedValue({ items: ITEMS, warnings: ['Hose guide: no evidence link'] })
  api.importItems.mockImplementation(async (_items, dryRun: boolean) => ({
    created: [{ id: dryRun ? null : 'new', title: 'Visor clip' }],
    skipped: [{ title: 'Hose guide', source_url: 'https://r/2', existing_idea_id: 'old' }],
    refused: [],
  }))
})

describe('ImportReportDialog', () => {
  it('previews without writing, then imports on confirmation', async () => {
    render(<ImportReportDialog open onClose={vi.fn()} />)
    await userEvent.type(screen.getByLabelText('Report'), '### 1. Visor clip — 20/25')
    await userEvent.click(screen.getByRole('button', { name: 'Preview' }))

    expect(await screen.findByText('1 to create · 1 already imported · 0 refused')).toBeInTheDocument()
    expect(api.importItems).toHaveBeenCalledWith(ITEMS, true)
    expect(screen.getByLabelText('Warnings')).toHaveTextContent('no evidence link')
    // Each problem with its score, niche and link, and what the import will do.
    const rows = within(screen.getByRole('table', { name: 'Problems in the report' }))
      .getAllByRole('row')
      .slice(1)
      .map((r) => r.textContent)
    expect(rows).toEqual([
      'Visor clip20/25carhttps://r/1To create',
      'Hose guide18/25gardenhttps://r/2Already imported',
    ])

    await userEvent.click(screen.getByRole('button', { name: 'Import 1 ideas' }))
    expect(api.importItems).toHaveBeenLastCalledWith(ITEMS, false)
    expect(await screen.findByText('1 created · 1 skipped · 0 refused')).toBeInTheDocument()
    expect(screen.getByText('Hose guide')).toBeInTheDocument()
  })

  it('says when the text holds no problem', async () => {
    api.parseReport.mockResolvedValue({ items: [], warnings: [] })
    render(<ImportReportDialog open onClose={vi.fn()} />)
    await userEvent.type(screen.getByLabelText('Report'), 'hello')
    await userEvent.click(screen.getByRole('button', { name: 'Preview' }))
    expect(await screen.findByText('No problem was found in this text.')).toBeInTheDocument()
    expect(api.importItems).not.toHaveBeenCalled()
  })

  it('reads a dropped or picked .md file', async () => {
    render(<ImportReportDialog open onClose={vi.fn()} />)
    const file = new File(['### 1. Clip — 15/25'], 'report.md', { type: 'text/markdown' })
    await userEvent.upload(screen.getByLabelText('Report file'), file)
    expect(await screen.findByDisplayValue('### 1. Clip — 15/25')).toBeInTheDocument()
  })

  it('lists refused items with their reasons', async () => {
    api.importItems.mockResolvedValue({
      created: [],
      skipped: [],
      refused: [{ index: 1, title: null, reason: 'Title is required' }],
    })
    render(<ImportReportDialog open onClose={vi.fn()} />)
    await userEvent.type(screen.getByLabelText('Report'), 'x')
    await userEvent.click(screen.getByRole('button', { name: 'Preview' }))
    expect(await screen.findByText('Refused: Title is required')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Import 0 ideas' })).toBeDisabled()
  })
})
