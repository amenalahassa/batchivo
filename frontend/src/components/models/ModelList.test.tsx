/**
 * Bug model-soft-delete-listed (bugcap #41).
 *
 * Deleting a model archives it (`is_active=false`). The list asked for every
 * model, active or not, so after "Delete" the model was still there and the
 * delete looked broken. The list now asks for active models unless the
 * operator chooses otherwise.
 */

import { describe, it, expect, vi, beforeEach, type Mock } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { render } from '@/test/test-utils'
import { ModelList } from './ModelList'
import { listModels } from '@/lib/api/models'

vi.mock('@/lib/api/models', () => ({
  listModels: vi.fn(),
  importModels: vi.fn(),
  exportModels: vi.fn(),
}))

const mockListModels = listModels as Mock

describe('ModelList', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockListModels.mockResolvedValue({ models: [], total: 0, skip: 0, limit: 50 })
  })

  it('asks for active models by default, so an archived (deleted) one is not listed', async () => {
    render(<ModelList />)

    await waitFor(() => expect(mockListModels).toHaveBeenCalled())
    expect(mockListModels.mock.calls[0][0]).toMatchObject({ is_active: true })
  })

  it('still reaches archived models through the Inactive filter', async () => {
    render(<ModelList />)
    await waitFor(() => expect(mockListModels).toHaveBeenCalled())

    await userEvent.click(await screen.findByRole('button', { name: /inactive/i }))

    await waitFor(() =>
      expect(mockListModels.mock.calls.at(-1)?.[0]).toMatchObject({ is_active: false })
    )
  })
})
