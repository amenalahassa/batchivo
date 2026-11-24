/** A board card shows the idea and moves it (spec 007, FR-008, T024). */
import { describe, expect, it, vi } from 'vitest'
import userEvent from '@testing-library/user-event'

import { render, screen } from '@/test/test-utils'

import { IdeaCard } from './IdeaCard'
import { aSummary } from './ideaTestData'

vi.mock('@/lib/api/ideas', () => ({ ideasApi: { getImageBlob: vi.fn(() => new Promise(() => {})) } }))

describe('IdeaCard', () => {
  it('shows title, score and tags, linking to the idea', () => {
    render(
      <IdeaCard
        idea={aSummary({ score: 18, score_source: 'scores', tags: ['car', 'clip'] })}
        canWrite={false}
      />
    )
    expect(screen.getByRole('link', { name: 'Sun visor clip' })).toHaveAttribute(
      'href',
      '/ideas/$ideaId'
    )
    expect(screen.getByText('18/25')).toBeInTheDocument()
    expect(screen.getByText('clip')).toBeInTheDocument()
  })

  it('moves the idea to another status', async () => {
    const onMove = vi.fn()
    render(<IdeaCard idea={aSummary()} canWrite onMove={onMove} />)
    await userEvent.selectOptions(screen.getByLabelText('Move Sun visor clip'), 'ready')
    expect(onMove).toHaveBeenCalledWith('idea-1', 'ready')
  })

  it('gives a viewer no menu to move it', () => {
    render(<IdeaCard idea={aSummary()} canWrite={false} onMove={vi.fn()} />)
    expect(screen.queryByLabelText('Move Sun visor clip')).not.toBeInTheDocument()
  })

  it('shows the cover when there is one', () => {
    render(
      <IdeaCard idea={aSummary({ cover_thumbnail_path: '/api/v1/x' })} canWrite={false} />
    )
    expect(screen.getByLabelText('Loading Sun visor clip')).toBeInTheDocument()
  })
})
