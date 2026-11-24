/** The idea form validates and sends what the API expects (spec 007, FR-003, T023). */
import { describe, expect, it, vi } from 'vitest'
import userEvent from '@testing-library/user-event'

import { render, screen } from '@/test/test-utils'

import { IdeaForm } from './IdeaForm'
import { anIdea } from './ideaTestData'

describe('IdeaForm', () => {
  it('refuses a blank title and a link that is not http', async () => {
    const onSubmit = vi.fn()
    render(<IdeaForm onSubmit={onSubmit} />)
    await userEvent.type(screen.getByLabelText('Source link'), 'ftp://x')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(screen.getByText('Title is required')).toBeInTheDocument()
    expect(screen.getByText('Link must start with http:// or https://')).toBeInTheDocument()
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('sends title, tags and scores', async () => {
    const onSubmit = vi.fn()
    render(<IdeaForm onSubmit={onSubmit} submitLabel="Create" />)
    await userEvent.type(screen.getByLabelText('Title'), '  Visor clip ')
    await userEvent.type(screen.getByLabelText('Tags (comma separated)'), 'car, clip,')
    await userEvent.selectOptions(screen.getByLabelText('Frequency'), '4')
    await userEvent.click(screen.getByRole('button', { name: 'Create' }))
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        title: 'Visor clip',
        status: 'inbox',
        source: 'manual',
        source_url: null,
        tags: ['car', 'clip'],
        scores: expect.objectContaining({ frequency: 4, gap: null }),
      })
    )
  })

  it('offers no converted status, and leaves a converted idea converted unless changed', async () => {
    const onSubmit = vi.fn()
    render(<IdeaForm initial={anIdea({ status: 'converted' })} onSubmit={onSubmit} />)
    const status = screen.getByLabelText('Status')
    expect(
      Array.from((status as HTMLSelectElement).options).map((o) => o.value)
    ).not.toContain('converted')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(onSubmit.mock.calls[0][0]).not.toHaveProperty('status')
  })

  it('shows the error the server gave', () => {
    render(<IdeaForm onSubmit={vi.fn()} error="Title taken" />)
    expect(screen.getByRole('alert')).toHaveTextContent('Title taken')
  })
})
