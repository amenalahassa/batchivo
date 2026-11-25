/** One idea with generative AI: generate a concept and the AI tab (spec 008, T039, T046). */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'

import { aJob, capabilities } from '@/components/genai/genaiTestData'
import { anIdea, anImageEntry } from '@/components/ideas/ideaTestData'
import { render, screen, within } from '@/test/test-utils'

import { IdeaDetail } from './IdeaDetailPage'

const roles = vi.hoisted(() => ({ canWrite: true, canCreateProduct: false }))
vi.mock('@/components/ideas/useIdeaRoles', () => ({ useIdeaRoles: () => roles }))
const genaiRoles = vi.hoisted(() => ({ value: { canGenerate: true, canManageSettings: false } }))
vi.mock('@/components/genai/useGenAIRoles', () => ({ useGenAIRoles: () => genaiRoles.value }))
vi.mock('@/components/layout/AppLayout', () => ({
  AppLayout: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}))

const api = vi.hoisted(() => ({
  get: vi.fn(),
  listEntries: vi.fn(),
  getImageBlob: vi.fn(() => new Promise(() => {})),
}))
vi.mock('@/lib/api/ideas', () => ({ ideasApi: api }))

const genai = vi.hoisted(() => ({
  capabilities: vi.fn(),
  estimate: vi.fn(() => new Promise(() => {})),
  listJobs: vi.fn(),
  getJob: vi.fn(),
  cancelJob: vi.fn(),
  getBlob: vi.fn(() => new Promise(() => {})),
}))
vi.mock('@/lib/api/genai', () => ({ genaiApi: genai }))

beforeEach(() => {
  roles.canWrite = true
  genaiRoles.value = { canGenerate: true, canManageSettings: false }
  api.get.mockReset().mockResolvedValue(anIdea())
  api.listEntries.mockReset().mockResolvedValue({ items: [anImageEntry()], current_iteration: 1 })
  genai.capabilities.mockReset().mockResolvedValue(capabilities())
  genai.listJobs.mockReset().mockResolvedValue({
    items: [aJob({ id: 'job-1', status: 'succeeded', can_cancel: false })],
    total: 1,
  })
})

describe('Idea detail page, generative AI', () => {
  it('generates a concept with the prompt prefilled from the idea and its images offered', async () => {
    render(<IdeaDetail ideaId="idea-1" />)
    await screen.findByRole('heading', { name: 'Sun visor clip' })
    const composer = screen.getByTestId('idea-composer')
    await userEvent.click(within(composer).getByRole('button', { name: 'Generate concept' }))
    const prompt = await screen.findByLabelText('Describe the concept')
    expect(prompt).toHaveValue('Sun visor clip. Holds **cards** on the visor')
    expect(await screen.findByRole('button', { name: 'clip.png' })).toBeInTheDocument()
  })

  it('hides generate concept from a viewer', async () => {
    genaiRoles.value = { canGenerate: false, canManageSettings: false }
    render(<IdeaDetail ideaId="idea-1" />)
    await screen.findByRole('heading', { name: 'Sun visor clip' })
    expect(screen.queryByRole('button', { name: 'Generate concept' })).not.toBeInTheDocument()
  })

  it('lists the idea generations in the AI tab', async () => {
    render(<IdeaDetail ideaId="idea-1" />)
    await screen.findByRole('heading', { name: 'Sun visor clip' })
    await userEvent.click(screen.getByRole('tab', { name: 'AI' }))
    const list = await screen.findByRole('list', { name: 'AI generations' })
    expect(within(list).getAllByRole('listitem')).toHaveLength(1)
    expect(genai.listJobs).toHaveBeenCalledWith({
      target_type: 'idea',
      target_id: 'idea-1',
      limit: 50,
    })
  })
})
