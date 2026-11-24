/**
 * Create ideas from a pain-point report (spec 007, FR-031 to FR-033, clarification Q2).
 *
 * The report is read by the backend (one parser), previewed with a dry run that
 * writes nothing, then imported on confirmation.
 */
import { useState, type DragEvent } from 'react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/textarea'
import { useImportIdeas, useParseReport } from '@/hooks/useIdeas'
import { apiErrorDetail } from '@/lib/apiError'
import type { ImportItem, ImportResult } from '@/types/idea'

import { previewRows, type PreviewState } from './ideaText'

const STATE_LABELS: Record<PreviewState, string> = {
  create: 'To create',
  skip: 'Already imported',
  refused: 'Refused',
}

interface ImportReportDialogProps {
  open: boolean
  onClose: () => void
}

type Step = 'input' | 'preview' | 'done'

/** A dropped or picked report file as text (FileReader works in every browser). */
function readText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result ?? ''))
    reader.onerror = () => reject(reader.error)
    reader.readAsText(file)
  })
}

export function ImportReportDialog({ open, onClose }: ImportReportDialogProps) {
  const [text, setText] = useState('')
  const [step, setStep] = useState<Step>('input')
  const [items, setItems] = useState<ImportItem[]>([])
  const [warnings, setWarnings] = useState<string[]>([])
  const [preview, setPreview] = useState<ImportResult | null>(null)
  const [result, setResult] = useState<ImportResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const parse = useParseReport()
  const importIdeas = useImportIdeas()

  function reset() {
    setText('')
    setStep('input')
    setItems([])
    setWarnings([])
    setPreview(null)
    setResult(null)
    setError(null)
  }

  function close() {
    reset()
    onClose()
  }

  async function readReport() {
    setError(null)
    try {
      const parsed = await parse.mutateAsync(text)
      setWarnings(parsed.warnings)
      setItems(parsed.items)
      if (parsed.items.length === 0) return
      setPreview(await importIdeas.mutateAsync({ items: parsed.items, dryRun: true }))
      setStep('preview')
    } catch (err) {
      setError(apiErrorDetail(err))
    }
  }

  async function confirm() {
    setError(null)
    try {
      setResult(await importIdeas.mutateAsync({ items, dryRun: false }))
      setStep('done')
    } catch (err) {
      setError(apiErrorDetail(err))
    }
  }

  async function handleDrop(event: DragEvent) {
    event.preventDefault()
    const file = event.dataTransfer.files?.[0]
    if (file) setText(await readText(file))
  }

  const busy = parse.isPending || importIdeas.isPending

  return (
    <Dialog open={open} onOpenChange={(next) => !next && close()}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>Import a pain-point report</DialogTitle>
          <DialogDescription>
            Each problem in the report becomes an idea in the Inbox. Problems already imported
            from the same link are skipped.
          </DialogDescription>
        </DialogHeader>

        {step === 'input' && (
          <div className="space-y-2" onDragOver={(e) => e.preventDefault()} onDrop={handleDrop}>
            <Textarea
              aria-label="Report"
              rows={12}
              placeholder="Paste the report here, or drop its .md file"
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
            <input
              type="file"
              accept=".md,text/markdown,text/plain"
              aria-label="Report file"
              className="text-sm"
              onChange={async (e) => {
                const file = e.target.files?.[0]
                if (file) setText(await readText(file))
              }}
            />
            {!parse.isPending && parse.isSuccess && items.length === 0 && (
              <p role="status" className="text-sm text-muted-foreground">
                No problem was found in this text.
              </p>
            )}
          </div>
        )}

        {step === 'preview' && preview && (
          <div className="max-h-[50vh] space-y-3 overflow-y-auto text-sm">
            <p role="status">
              {preview.created.length} to create · {preview.skipped.length} already imported ·{' '}
              {preview.refused.length} refused
            </p>
            <table className="w-full text-left text-xs" aria-label="Problems in the report">
              <thead>
                <tr className="border-b">
                  <th className="py-1 pr-2">Problem</th>
                  <th className="py-1 pr-2">Score</th>
                  <th className="py-1 pr-2">Niche</th>
                  <th className="py-1 pr-2">Source</th>
                  <th className="py-1">Import</th>
                </tr>
              </thead>
              <tbody>
                {previewRows(items, preview).map((row, index) => (
                  <tr key={index} className="border-b align-top">
                    <td className="py-1 pr-2">{row.item.title || `Item ${index + 1}`}</td>
                    <td className="py-1 pr-2 whitespace-nowrap">
                      {row.item.report_score != null ? `${row.item.report_score}/25` : '—'}
                    </td>
                    <td className="py-1 pr-2">{(row.item.tags ?? []).join(', ') || '—'}</td>
                    <td className="py-1 pr-2 break-all">
                      {row.item.source_url ? (
                        <a
                          href={row.item.source_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-primary underline"
                        >
                          {row.item.source_url}
                        </a>
                      ) : (
                        '—'
                      )}
                    </td>
                    <td
                      className={`py-1 ${row.state === 'refused' ? 'text-destructive' : row.state === 'skip' ? 'text-muted-foreground' : ''}`}
                    >
                      {STATE_LABELS[row.state]}
                      {row.reason && `: ${row.reason}`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {step === 'done' && result && (
          <div className="space-y-2 text-sm" role="status">
            <p>
              {result.created.length} created · {result.skipped.length} skipped ·{' '}
              {result.refused.length} refused
            </p>
            {result.skipped.length > 0 && (
              <ul className="list-disc pl-5 text-muted-foreground">
                {result.skipped.map((s, i) => (
                  <li key={`${s.title}-${i}`}>{s.title}</li>
                ))}
              </ul>
            )}
          </div>
        )}

        {warnings.length > 0 && step !== 'done' && (
          <ul aria-label="Warnings" className="text-xs text-amber-700 dark:text-amber-400">
            {warnings.map((w, i) => (
              <li key={`${w}-${i}`}>{w}</li>
            ))}
          </ul>
        )}
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}

        <DialogFooter>
          {step === 'input' && (
            <>
              <Button variant="outline" onClick={close}>
                Cancel
              </Button>
              <Button onClick={readReport} disabled={busy || !text.trim()}>
                {busy ? 'Reading…' : 'Preview'}
              </Button>
            </>
          )}
          {step === 'preview' && (
            <>
              <Button variant="outline" onClick={() => setStep('input')}>
                Back
              </Button>
              <Button onClick={confirm} disabled={busy || preview?.created.length === 0}>
                Import {preview?.created.length ?? 0} ideas
              </Button>
            </>
          )}
          {step === 'done' && <Button onClick={close}>Close</Button>}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
