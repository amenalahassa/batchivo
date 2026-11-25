/**
 * "Add to product…": adopt an image result into a product the operator picks
 * (spec 008, US3 AS4, FR-030).
 *
 * A concept image or a draft photo made for an idea or a model can still end
 * up on a product. The picker searches products; adopting goes through
 * `AdoptConfirmDialog` when the server asks (an imagined picture). Meshes
 * cannot become product images, so callers offer this for images only.
 */
import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2, Search } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { listProducts } from '@/lib/api/products'
import type { AdoptResponse } from '@/types/genai'
import { AdoptConfirmDialog } from './AdoptConfirmDialog'
import { refusalMessage } from './genaiText'
import { useAdoptWithConfirmation } from './useAdoptWithConfirmation'

interface AddToProductProps {
  assetId: string
  onAdopted?: (result: AdoptResponse) => void
}

function useDebounced(value: string, delay = 250) {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(timer)
  }, [value, delay])
  return debounced
}

export function AddToProduct({ assetId, onAdopted }: AddToProductProps) {
  const [picking, setPicking] = useState(false)
  const [search, setSearch] = useState('')
  const [added, setAdded] = useState<string | null>(null)
  // The name of the product being adopted into, for the "Added to" line.
  const chosen = useRef<string | null>(null)
  const term = useDebounced(search.trim())
  const products = useQuery({
    queryKey: ['products', 'genai-adopt-picker', term],
    queryFn: () => listProducts({ search: term || undefined, limit: 10 }),
    enabled: picking,
  })
  const adoption = useAdoptWithConfirmation((result) => {
    setAdded(chosen.current)
    setPicking(false)
    onAdopted?.(result)
  })

  const pick = (id: string, name: string) => {
    chosen.current = name
    adoption.adopt(assetId, { type: 'product', id })
  }

  return (
    <div className="space-y-2">
      {added && <p className="text-xs text-muted-foreground">Added to {added}</p>}
      {!picking ? (
        <Button size="sm" variant="outline" className="w-full" onClick={() => setPicking(true)}>
          Add to product…
        </Button>
      ) : (
        <div className="space-y-2 rounded-md border p-2">
          <div className="relative">
            <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" aria-hidden />
            <Input
              autoFocus
              aria-label="Search products"
              placeholder="Search products"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="h-9 pl-8"
            />
          </div>
          {products.isLoading && (
            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" aria-label="Loading products" />
          )}
          {products.isError && <p className="text-xs text-destructive">Products could not be loaded.</p>}
          {products.data && products.data.products.length === 0 && (
            <p className="text-xs text-muted-foreground">No product matches.</p>
          )}
          {products.data && products.data.products.length > 0 && (
            <ul className="max-h-48 space-y-1 overflow-y-auto" aria-label="Products">
              {products.data.products.map((product) => (
                <li key={product.id}>
                  <button
                    type="button"
                    className="w-full rounded px-2 py-1 text-left text-sm hover:bg-muted disabled:opacity-50"
                    disabled={adoption.isPending}
                    onClick={() => pick(product.id, product.name)}
                  >
                    {product.name}
                    <span className="ml-2 text-xs text-muted-foreground">{product.sku}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <Button size="sm" variant="ghost" onClick={() => setPicking(false)}>
            Close
          </Button>
        </div>
      )}
      {adoption.error && <p className="text-xs text-destructive">{refusalMessage(adoption.error)}</p>}
      <AdoptConfirmDialog {...adoption.confirmDialog} />
    </div>
  )
}
