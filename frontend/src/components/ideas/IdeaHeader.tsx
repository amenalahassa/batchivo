/**
 * An idea's header: title, status, score, tags, summary, cover, links and the
 * actions on the whole idea (spec 007, FR-003 to FR-007, FR-023 to FR-030).
 */
import { useState } from 'react'
import { Link } from '@tanstack/react-router'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useUpdateIdea } from '@/hooks/useIdeas'
import { apiErrorDetail } from '@/lib/apiError'
import type { IdeaDetail, IdeaLink, WritableIdeaStatus } from '@/types/idea'

import { AuthImage } from './AuthImage'
import { ConvertIdeaDialog, PRODUCT_ROLE_REASON } from './ConvertIdeaDialog'
import { IdeaForm } from './IdeaForm'
import { Markdown } from './Markdown'
import { SOURCE_LABELS, STATUS_LABELS, WRITABLE_STATUSES, scoreText } from './ideaText'

interface IdeaHeaderProps {
  idea: IdeaDetail
  canWrite: boolean
  canCreateProduct: boolean
}

function LinkLine({ label, link, to }: { label: string; link: IdeaLink; to: 'model' | 'product' }) {
  if (link.state === 'none') return null
  if (link.state === 'gone' || !link.id)
    return (
      <li>
        {label}: <span className="text-muted-foreground">no longer exists</span>
      </li>
    )
  return (
    <li>
      {label}:{' '}
      {to === 'model' ? (
        <Link to="/models/$modelId" params={{ modelId: link.id }} className="text-primary underline">
          {link.name} {link.sku && `(${link.sku})`}
        </Link>
      ) : (
        <Link
          to="/products/$productId"
          params={{ productId: link.id }}
          className="text-primary underline"
        >
          {link.name} {link.sku && `(${link.sku})`}
        </Link>
      )}
    </li>
  )
}

export function IdeaHeader({ idea, canWrite, canCreateProduct }: IdeaHeaderProps) {
  const update = useUpdateIdea(idea.id)
  const [editing, setEditing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [convertTarget, setConvertTarget] = useState<'model' | 'product' | null>(null)

  const productDone = idea.product.state !== 'none'
  const modelDone = idea.model.state !== 'none'
  const productBlocked = !canCreateProduct ? PRODUCT_ROLE_REASON : null

  return (
    <header className="space-y-4">
      <div className="flex flex-wrap items-start gap-4">
        {idea.cover_image_path && (
          <AuthImage
            path={idea.cover_thumbnail_path ?? idea.cover_image_path}
            alt={`${idea.title} cover`}
            className="h-28 w-28 rounded"
          />
        )}
        <div className="min-w-0 flex-1 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-2xl font-bold">{idea.title}</h1>
            {idea.archived && <Badge variant="outline">Archived</Badge>}
          </div>
          <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            {canWrite ? (
              <select
                aria-label="Status"
                className="h-8 rounded-md border bg-background px-2 text-sm text-foreground"
                value={idea.status === 'converted' ? '' : idea.status}
                onChange={(e) =>
                  update.mutate({ status: e.target.value as WritableIdeaStatus })
                }
              >
                {idea.status === 'converted' && <option value="">Converted</option>}
                {WRITABLE_STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {STATUS_LABELS[s]}
                  </option>
                ))}
              </select>
            ) : (
              <Badge>{STATUS_LABELS[idea.status]}</Badge>
            )}
            <span>{scoreText(idea)}</span>
            {idea.report_score !== null && idea.score_source === 'scores' && (
              // The report's own total stays as history once the five scores replace it.
              <span title="Score given by the pain-point report">
                (report score {idea.report_score}/25)
              </span>
            )}
            <span>· {SOURCE_LABELS[idea.source]}</span>
            {idea.source_url && (
              <a
                href={idea.source_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-primary underline"
              >
                source
              </a>
            )}
            <span>· Iteration {idea.current_iteration}</span>
          </div>
          {idea.tags.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {idea.tags.map((t) => (
                <Badge key={t} variant="secondary">
                  {t}
                </Badge>
              ))}
            </div>
          )}
          <ul className="text-sm">
            <LinkLine label="Model" link={idea.model} to="model" />
            <LinkLine label="Product" link={idea.product} to="product" />
          </ul>
        </div>
        {canWrite && (
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" onClick={() => setEditing(true)}>
              Edit
            </Button>
            {!idea.archived && !modelDone && (
              <Button size="sm" onClick={() => setConvertTarget('model')}>
                Convert to model
              </Button>
            )}
            {!idea.archived && !productDone && (
              <span title={productBlocked ?? undefined}>
                <Button
                  size="sm"
                  variant={modelDone ? 'default' : 'outline'}
                  disabled={Boolean(productBlocked)}
                  onClick={() => setConvertTarget('product')}
                >
                  Convert to product
                </Button>
              </span>
            )}
            <Button
              variant="ghost"
              size="sm"
              onClick={() => update.mutate({ archived: !idea.archived })}
            >
              {idea.archived ? 'Restore' : 'Archive'}
            </Button>
          </div>
        )}
      </div>
      {productDone && (
        <p className="text-sm text-muted-foreground" role="status">
          Already converted to a product
          {idea.product.state === 'linked' && idea.product.id ? (
            <>
              {': '}
              <Link
                to="/products/$productId"
                params={{ productId: idea.product.id }}
                className="text-primary underline"
              >
                open it
              </Link>
            </>
          ) : (
            ', which no longer exists'
          )}
          .
        </p>
      )}
      {canWrite && !idea.archived && !productDone && productBlocked && (
        <p className="text-xs text-muted-foreground">{productBlocked}</p>
      )}
      {idea.summary && <Markdown>{idea.summary}</Markdown>}

      <Dialog open={editing} onOpenChange={setEditing}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Edit idea</DialogTitle>
          </DialogHeader>
          <IdeaForm
            initial={idea}
            isSubmitting={update.isPending}
            error={error}
            onCancel={() => setEditing(false)}
            onSubmit={(data) => {
              setError(null)
              update.mutate(data, {
                onSuccess: () => setEditing(false),
                onError: (err) => setError(apiErrorDetail(err)),
              })
            }}
          />
        </DialogContent>
      </Dialog>
      <ConvertIdeaDialog
        idea={idea}
        target={convertTarget}
        onClose={() => setConvertTarget(null)}
      />
    </header>
  )
}
