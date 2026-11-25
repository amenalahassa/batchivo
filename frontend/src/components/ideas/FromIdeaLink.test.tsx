/** Models and products show the idea they came from (spec 007, FR-027, FR-029, T044). */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

import { render, screen } from '@/test/test-utils'

import { FromIdeaLink } from './FromIdeaLink'

describe('FromIdeaLink', () => {
  it('links to the idea', () => {
    render(<FromIdeaLink ideaId="idea-1" title="Visor clip" archived={false} />)
    expect(screen.getByRole('link', { name: 'Visor clip' })).toHaveAttribute(
      'href',
      '/ideas/$ideaId'
    )
    expect(screen.queryByText('Archived')).not.toBeInTheDocument()
  })

  it('marks an archived idea', () => {
    render(<FromIdeaLink ideaId="idea-1" title="Visor clip" archived />)
    expect(screen.getByText('Archived')).toBeInTheDocument()
  })

  it('shows nothing for a record not made from an idea', () => {
    const { container } = render(<FromIdeaLink ideaId={null} title={null} archived={null} />)
    expect(container).toBeEmptyDOMElement()
  })

  it.each([
    ['models/ModelDetail.tsx', 'model'],
    ['products/ProductDetail.tsx', 'product'],
  ])('is shown on %s from its source idea fields', (file, record) => {
    const source = readFileSync(join(__dirname, '..', file), 'utf8')
    expect(source).toContain('<FromIdeaLink')
    expect(source).toContain(`ideaId={${record}.source_idea_id}`)
    expect(source).toContain(`archived={${record}.source_idea_archived}`)
  })
})
