/**
 * Turn an idea into a model, or a product with its model (spec 007, FR-023 to FR-028).
 *
 * The backend creates both through the same creation as the models and
 * products screens, all or nothing; this dialog only collects the names.
 */
import { useEffect, useState } from 'react'
import { Link } from '@tanstack/react-router'

import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useConvertIdea } from '@/hooks/useIdeas'
import { useNextSKU } from '@/hooks/useSKU'
import { apiErrorDetail } from '@/lib/apiError'
import type { ConvertResponse, IdeaDetail } from '@/types/idea'

export const PRODUCT_ROLE_REASON = 'Creating a product requires the admin role'

interface ConvertIdeaDialogProps {
  idea: IdeaDetail
  target: 'model' | 'product' | null
  onClose: () => void
}

export function ConvertIdeaDialog({ idea, target, onClose }: ConvertIdeaDialogProps) {
  const open = target !== null
  const reusesModel = target === 'product' && idea.model.state === 'linked'
  const needsModel = open && !reusesModel
  const modelSku = useNextSKU('MOD', needsModel)
  const productSku = useNextSKU('PROD', target === 'product')
  const convert = useConvertIdea(idea.id)

  const [name, setName] = useState(idea.title)
  const [mod, setMod] = useState('')
  const [prod, setProd] = useState('')
  const [includeImages, setIncludeImages] = useState(true)
  const [result, setResult] = useState<ConvertResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (open) {
      setName(idea.title)
      setResult(null)
      setError(null)
    }
  }, [open, idea.title])
  useEffect(() => {
    if (modelSku.nextSKU) setMod((current) => current || (modelSku.nextSKU as string))
  }, [modelSku.nextSKU])
  useEffect(() => {
    if (productSku.nextSKU) setProd((current) => current || (productSku.nextSKU as string))
  }, [productSku.nextSKU])

  function confirm() {
    if (!target) return
    setError(null)
    convert.mutate(
      {
        target,
        name: name.trim() || undefined,
        model_sku: needsModel ? mod.trim() || undefined : undefined,
        product_sku: target === 'product' ? prod.trim() || undefined : undefined,
        include_images: includeImages,
      },
      {
        onSuccess: setResult,
        onError: (err) => setError(apiErrorDetail(err)),
      }
    )
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {target === 'product' ? 'Convert to product' : 'Convert to model'}
          </DialogTitle>
          <DialogDescription>
            {target === 'product'
              ? reusesModel
                ? `The product uses the model ${idea.model.name ?? ''} already made from this idea.`
                : 'A model is made from this idea, then a product with that model.'
              : 'A model is made from this idea: its title, summary and cover.'}
          </DialogDescription>
        </DialogHeader>

        {result ? (
          <div className="space-y-2 text-sm" role="status">
            <p>Done.</p>
            <ul className="space-y-1">
              <li>
                <Link
                  to="/models/$modelId"
                  params={{ modelId: result.model_id }}
                  className="text-primary underline"
                >
                  Open the model
                </Link>
              </li>
              {result.product_id && (
                <li>
                  <Link
                    to="/products/$productId"
                    params={{ productId: result.product_id }}
                    className="text-primary underline"
                  >
                    Open the product
                  </Link>{' '}
                  ({result.copied_images} image{result.copied_images === 1 ? '' : 's'} copied)
                </li>
              )}
            </ul>
            {result.warnings.length > 0 && (
              <ul aria-label="Warnings" className="text-amber-700 dark:text-amber-400">
                {result.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            )}
            <DialogFooter>
              <Button onClick={onClose}>Close</Button>
            </DialogFooter>
          </div>
        ) : (
          <div className="space-y-3">
            <div className="space-y-1">
              <Label htmlFor="convert-name">Name</Label>
              <Input id="convert-name" value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            {needsModel && (
              <div className="space-y-1">
                <Label htmlFor="convert-model-sku">Model reference</Label>
                <Input id="convert-model-sku" value={mod} onChange={(e) => setMod(e.target.value)} />
              </div>
            )}
            {target === 'product' && (
              <>
                <div className="space-y-1">
                  <Label htmlFor="convert-product-sku">Product reference</Label>
                  <Input
                    id="convert-product-sku"
                    value={prod}
                    onChange={(e) => setProd(e.target.value)}
                  />
                </div>
                <div className="flex items-center gap-2">
                  <Checkbox
                    id="convert-images"
                    checked={includeImages}
                    onCheckedChange={(checked) => setIncludeImages(checked === true)}
                  />
                  <Label htmlFor="convert-images">Copy the cover and pinned images</Label>
                </div>
              </>
            )}
            {error && (
              <p role="alert" className="text-sm text-destructive">
                {error}
              </p>
            )}
            <DialogFooter>
              <Button variant="outline" onClick={onClose}>
                Cancel
              </Button>
              <Button onClick={confirm} disabled={convert.isPending || !name.trim()}>
                {convert.isPending ? 'Converting…' : 'Convert'}
              </Button>
            </DialogFooter>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
