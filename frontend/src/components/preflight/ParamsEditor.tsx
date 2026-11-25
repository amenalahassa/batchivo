/**
 * Edit a brief's design parameters (`params.yaml`) as YAML or JSON text (spec 009, US1).
 *
 * Sent as `params_yaml`; the server parses it. Parameters are replaced, not
 * revisioned (they are the design's current inputs, not a decision record).
 */
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { blockText } from './preflightText'

interface ParamsEditorProps {
  params: Record<string, unknown> | null
  saving: boolean
  error?: string | null
  onSave: (paramsYaml: string) => void
  onCancel: () => void
}

export function ParamsEditor({ params, saving, error, onSave, onCancel }: ParamsEditorProps) {
  const [text, setText] = useState(params ? blockText(params).trimEnd() : '')
  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault()
        onSave(text.trim() ? text : '{}')
      }}
    >
      <div className="space-y-1">
        <Label htmlFor="params-yaml">params.yaml (YAML or JSON)</Label>
        <Textarea
          id="params-yaml"
          value={text}
          spellCheck={false}
          onChange={(e) => setText(e.target.value)}
          className="min-h-40 font-mono text-xs"
        />
      </div>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      <div className="flex gap-2">
        <Button type="submit" disabled={saving}>
          {saving ? 'Saving…' : 'Save parameters'}
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  )
}
