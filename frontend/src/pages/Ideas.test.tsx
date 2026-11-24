/** The Ideas pages: board or list, new idea, import, one idea (spec 007, T027, T036). */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import userEvent from '@testing-library/user-event'
import { AxiosError, AxiosHeaders } from 'axios'
import type { ReactNode } from 'react'

import { anIdea } from '@/components/ideas/ideaTestData'
import { render, screen } from '@/test/test-utils'

import { IdeaDetail } from './IdeaDetailPage'
import { IdeasView } from './Ideas'

const roles = vi.hoisted(() => ({ canWrite: true, canCreateProduct: false }))
vi.mock('@/components/ideas/useIdeaRoles', () => ({ useIdeaRoles: () => roles }))
vi.mock('@/components/layout/AppLayout', () => ({
  AppLayout: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}))
vi.mock('@/components/ideas/IdeaBoard', () => ({ IdeaBoard: () => <div>board</div> }))
vi.mock('@/components/ideas/IdeaList', () => ({ IdeaList: () => <div>list</div> }))

const api = vi.hoisted(() => ({
  create: vi.fn(),
  get: vi.fn(),
  listEntries: vi.fn(),
  getImageBlob: vi.fn(() => new Promise(() => {})),
}))
vi.mock('@/lib/api/ideas', () => ({ ideasApi: api }))

beforeEach(() => {
  roles.canWrite = true
  api.create.mockReset()
  api.get.mockReset()
  api.listEntries.mockResolvedValue({ items: [], current_iteration: 1 })
})

describe('Ideas page', () => {
  it('shows the board first and switches to the list', async () => {
    render(<IdeasView />)
    expect(screen.getByText('board')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'List' }))
    expect(screen.getByText('list')).toBeInTheDocument()
  })

  it('creates an idea from the dialog', async () => {
    api.create.mockResolvedValue(anIdea({ id: 'new' }))
    render(<IdeasView />)
    await userEvent.click(screen.getByRole('button', { name: 'New idea' }))
    await userEvent.type(screen.getByLabelText('Title'), 'Hose guide')
    await userEvent.click(screen.getByRole('button', { name: 'Create' }))
    expect(api.create).toHaveBeenCalledWith(expect.objectContaining({ title: 'Hose guide' }))
  })

  it('opens the report import', async () => {
    render(<IdeasView />)
    await userEvent.click(screen.getByRole('button', { name: 'Import report' }))
    expect(screen.getByLabelText('Report')).toBeInTheDocument()
  })

  it('gives a viewer neither new idea nor import', () => {
    roles.canWrite = false
    render(<IdeasView />)
    expect(screen.queryByRole('button', { name: 'New idea' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Import report' })).not.toBeInTheDocument()
  })
})

describe('Idea detail page', () => {
  it('shows the idea, the composer and the timeline', async () => {
    api.get.mockResolvedValue(anIdea())
    render(<IdeaDetail ideaId="idea-1" />)
    expect(await screen.findByRole('heading', { name: 'Sun visor clip' })).toBeInTheDocument()
    expect(screen.getByTestId('idea-composer')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Gallery' })).toBeInTheDocument()
  })

  it('hides the composer from a viewer', async () => {
    roles.canWrite = false
    api.get.mockResolvedValue(anIdea())
    render(<IdeaDetail ideaId="idea-1" />)
    await screen.findByRole('heading', { name: 'Sun visor clip' })
    expect(screen.queryByTestId('idea-composer')).not.toBeInTheDocument()
  })

  it('says when the idea does not exist', async () => {
    api.get.mockRejectedValue(
      new AxiosError('404', 'ERR_BAD_REQUEST', undefined, undefined, {
        status: 404,
        statusText: 'Not Found',
        headers: {},
        config: { headers: new AxiosHeaders() },
        data: { detail: 'Idea not found' },
      })
    )
    render(<IdeaDetail ideaId="nope" />)
    expect(await screen.findByRole('heading', { name: 'Idea not found' })).toBeInTheDocument()
  })
})
