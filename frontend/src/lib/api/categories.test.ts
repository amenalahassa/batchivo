/**
 * @vitest-environment node
 *
 * The categories client sends what FastAPI reads, and a move renumbers the
 * list so tied display orders still change (.specify/bugs/category-show-all-param,
 * .specify/bugs/category-reorder-noop).
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from '../api'
import { displayOrderUpdatesForMove, listCategories } from './categories'

vi.mock('../api', () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}))

const client = vi.mocked(apiClient)

beforeEach(() => vi.clearAllMocks())

describe('listCategories', () => {
  it('asks for inactive categories with include_inactive, the parameter the API reads', async () => {
    client.get.mockResolvedValue({ categories: [], total: 0 })
    await listCategories({ include_inactive: true, limit: 100 })
    const url = client.get.mock.calls[0][0] as string
    expect(url).toContain('include_inactive=true')
    expect(url).not.toContain('is_active')
  })

  it('leaves the parameter out for the default, active-only list', async () => {
    client.get.mockResolvedValue({ categories: [], total: 0 })
    await listCategories({ limit: 100 })
    expect(client.get).toHaveBeenCalledWith('/api/v1/categories?limit=100')
  })
})

describe('displayOrderUpdatesForMove', () => {
  it('moves a category down even when every order is 0', () => {
    const sorted = [
      { id: 'a', display_order: 0 },
      { id: 'b', display_order: 0 },
      { id: 'c', display_order: 0 },
    ]
    // New order b, a, c: b keeps 0, a and c are renumbered
    expect(displayOrderUpdatesForMove(sorted, 'a', 'down')).toEqual([
      { id: 'a', display_order: 1 },
      { id: 'c', display_order: 2 },
    ])
  })

  it('swaps two distinct orders and leaves the others alone', () => {
    const sorted = [
      { id: 'a', display_order: 0 },
      { id: 'b', display_order: 1 },
      { id: 'c', display_order: 2 },
    ]
    expect(displayOrderUpdatesForMove(sorted, 'c', 'up')).toEqual([
      { id: 'c', display_order: 1 },
      { id: 'b', display_order: 2 },
    ])
  })

  it('does nothing past either end of the list', () => {
    const sorted = [
      { id: 'a', display_order: 0 },
      { id: 'b', display_order: 1 },
    ]
    expect(displayOrderUpdatesForMove(sorted, 'a', 'up')).toEqual([])
    expect(displayOrderUpdatesForMove(sorted, 'b', 'down')).toEqual([])
    expect(displayOrderUpdatesForMove(sorted, 'missing', 'down')).toEqual([])
  })
})
