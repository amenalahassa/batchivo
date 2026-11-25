/** The design brief panel on an idea or a model (spec 009, US1). */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import userEvent from '@testing-library/user-event'

import { render, screen, waitFor } from '@/test/test-utils'
import { designBriefsApi } from '@/lib/api/preflight'
import { DesignBriefPanel } from './DesignBriefPanel'
import { TEMPLATE_INTENT, aBrief } from './preflightTestData'

vi.mock('@/lib/api/preflight', () => ({
  designBriefsApi: {
    getFor: vi.fn(),
    start: vi.fn(),
    get: vi.fn(),
    update: vi.fn(),
    revisions: vi.fn(),
  },
}))

describe('DesignBriefPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(designBriefsApi.revisions).mockResolvedValue([])
  })

  it('offers to start a brief when there is none', async () => {
    vi.mocked(designBriefsApi.getFor).mockResolvedValue(null)
    vi.mocked(designBriefsApi.start).mockResolvedValue(aBrief())
    render(<DesignBriefPanel owner={{ ideaId: 'idea-1' }} canWrite />)
    await userEvent.click(await screen.findByRole('button', { name: 'Start a design brief' }))
    expect(designBriefsApi.start).toHaveBeenCalledWith({ ideaId: 'idea-1' }, {})
  })

  it('shows a viewer the empty state without the start button', async () => {
    vi.mocked(designBriefsApi.getFor).mockResolvedValue(null)
    render(<DesignBriefPanel owner={{ ideaId: 'idea-1' }} canWrite={false} />)
    expect(await screen.findByText(/No design brief yet/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Start a design brief' })).not.toBeInTheDocument()
  })

  it('shows the sections of a brief', async () => {
    vi.mocked(designBriefsApi.getFor).mockResolvedValue(
      aBrief({
        intent: TEMPLATE_INTENT,
        risk_class: 'moyen',
        risk_md: '# Risque principal',
        plan_md: '# Plan',
        params: { wall_mm: 1.6 },
        revision_counts: { intent: 1, risk: 1, plan: 1 },
      })
    )
    render(<DesignBriefPanel owner={{ ideaId: 'idea-1' }} canWrite={false} />)
    expect(await screen.findByText('moyen (medium)')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Risque principal' })).toBeInTheDocument()
    expect(screen.getByText('wall_mm: 1.6')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /History \(3\)/ })).toBeEnabled()
    expect(screen.queryByRole('button', { name: /^Edit/ })).not.toBeInTheDocument()
  })

  it('saves a step status at once', async () => {
    vi.mocked(designBriefsApi.getFor).mockResolvedValue(aBrief())
    vi.mocked(designBriefsApi.update).mockResolvedValue({ ...aBrief(), created_revisions: [] })
    render(<DesignBriefPanel owner={{ ideaId: 'idea-1' }} canWrite />)
    await userEvent.selectOptions(await screen.findByLabelText('Risk status'), 'done')
    expect(designBriefsApi.update).toHaveBeenCalledWith('brief-1', { steps: { risk: 'done' } })
  })

  it('edits the plan and closes the editor once saved', async () => {
    vi.mocked(designBriefsApi.getFor).mockResolvedValue(aBrief())
    vi.mocked(designBriefsApi.update).mockResolvedValue({ ...aBrief(), created_revisions: ['plan'] })
    render(<DesignBriefPanel owner={{ ideaId: 'idea-1' }} canWrite />)
    await userEvent.click(await screen.findByRole('button', { name: 'Edit plan' }))
    await userEvent.type(screen.getByLabelText('plan.md'), '# PETG, couché')
    await userEvent.click(screen.getByRole('button', { name: 'Save plan' }))
    expect(designBriefsApi.update).toHaveBeenCalledWith('brief-1', { plan_md: '# PETG, couché' })
    await waitFor(() => expect(screen.queryByLabelText('plan.md')).not.toBeInTheDocument())
  })

  it('links a model brief to the idea it came from', async () => {
    vi.mocked(designBriefsApi.getFor).mockResolvedValue(aBrief({ model_id: 'model-1' }))
    render(<DesignBriefPanel owner={{ modelId: 'model-1' }} canWrite={false} />)
    expect(await screen.findByRole('link', { name: 'Porte-sac' })).toBeInTheDocument()
  })
})
