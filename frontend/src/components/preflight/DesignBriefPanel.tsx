/**
 * A part's design brief: Preflight's design file in Batchivo (spec 009, US1).
 *
 * Shown on an idea and on a model; a model converted from an idea shows the
 * idea's brief (one brief, never a copy). Sections: the fourteen steps, the
 * intent, the risk part, the plan and the parameters. Members edit; every
 * saved intent, risk part and plan stays readable in the history.
 */
import { useState } from 'react'
import { Link } from '@tanstack/react-router'
import { History } from 'lucide-react'

import { Markdown } from '@/components/ideas/Markdown'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { useDesignBrief, useStartDesignBrief, useUpdateDesignBrief } from '@/hooks/usePreflight'
import type { BriefOwner } from '@/lib/api/preflight'
import { apiErrorDetail } from '@/lib/apiError'
import type { DesignBrief, DesignBriefUpdate } from '@/types/preflight'
import { BriefRevisionsDialog } from './BriefRevisionsDialog'
import { IntentEditor } from './IntentEditor'
import { IntentView } from './IntentView'
import { ParamsEditor } from './ParamsEditor'
import { RISK_TEXT, blockText, preflightErrorText } from './preflightText'
import { PlanEditor, RiskEditor } from './RiskPlanEditor'
import { StepStrip } from './StepStrip'

type Section = 'intent' | 'risk' | 'plan' | 'params'

interface DesignBriefPanelProps {
  owner: BriefOwner
  canWrite: boolean
}

function SectionCard({
  title,
  description,
  editing,
  canWrite,
  onEdit,
  children,
}: {
  title: string
  description?: string
  editing: boolean
  canWrite: boolean
  onEdit: () => void
  children: React.ReactNode
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-2 space-y-0">
        <div>
          <CardTitle className="text-base">{title}</CardTitle>
          {description && <CardDescription>{description}</CardDescription>}
        </div>
        {canWrite && !editing && (
          <Button size="sm" variant="outline" onClick={onEdit} aria-label={`Edit ${title.toLowerCase()}`}>
            Edit
          </Button>
        )}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  )
}

function BriefBody({ brief, canWrite, owner }: { brief: DesignBrief; canWrite: boolean; owner: BriefOwner }) {
  const [editing, setEditing] = useState<Section | null>(null)
  const [historyOpen, setHistoryOpen] = useState(false)
  const update = useUpdateDesignBrief(brief.id)
  const error = update.error ? preflightErrorText(update.error) : null

  const save = (data: DesignBriefUpdate) =>
    update.mutate(data, {
      onSuccess: () => setEditing(null),
    })
  const edit = (section: Section) => {
    update.reset()
    setEditing(section)
  }
  const stopEditing = () => {
    update.reset()
    setEditing(null)
  }
  const revisionTotal = brief.revision_counts.intent + brief.revision_counts.risk + brief.revision_counts.plan

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-sm text-muted-foreground">
          {'ideaId' in owner && brief.model_id && (
            <>
              Shared with model{' '}
              <Link to="/models/$modelId" params={{ modelId: brief.model_id }} className="underline">
                {brief.model_name ?? 'model'}
              </Link>
              {' · '}
            </>
          )}
          {'modelId' in owner && brief.idea_id && (
            <>
              From idea{' '}
              <Link to="/ideas/$ideaId" params={{ ideaId: brief.idea_id }} className="underline">
                {brief.idea_title ?? 'idea'}
              </Link>
              {' · '}
            </>
          )}
          Updated {new Date(brief.updated_at).toLocaleString()}
          {brief.updated_by && <> by {brief.updated_by.name}</>}
        </div>
        <Button size="sm" variant="outline" onClick={() => setHistoryOpen(true)} disabled={revisionTotal === 0}>
          <History className="mr-1 h-4 w-4" />
          History ({revisionTotal})
        </Button>
      </div>

      <StepStrip
        steps={brief.steps}
        canWrite={canWrite}
        disabled={update.isPending}
        onChange={(step, status) => update.mutate({ steps: { [step]: status } })}
      />
      {error && editing === null && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}

      <SectionCard
        title="Intent"
        description="What the part is for: loads, environment, interfaces, success criteria."
        editing={editing === 'intent'}
        canWrite={canWrite}
        onEdit={() => edit('intent')}
      >
        {editing === 'intent' ? (
          <IntentEditor
            intent={brief.intent}
            saving={update.isPending}
            error={error}
            onCancel={stopEditing}
            onSave={(intentYaml) => save({ intent_yaml: intentYaml })}
          />
        ) : brief.intent ? (
          <IntentView intent={brief.intent} validation={brief.validation} />
        ) : (
          <p className="text-sm text-muted-foreground">No intent yet.</p>
        )}
      </SectionCard>

      <SectionCard
        title="Risk"
        description="Preflight's risk class and risk.md."
        editing={editing === 'risk'}
        canWrite={canWrite}
        onEdit={() => edit('risk')}
      >
        {editing === 'risk' ? (
          <RiskEditor
            riskClass={brief.risk_class}
            riskMd={brief.risk_md}
            triage={brief.triage}
            saving={update.isPending}
            error={error}
            onCancel={stopEditing}
            onSave={(risk) => save({ risk })}
          />
        ) : (
          <div className="space-y-2">
            <Badge variant="outline">{brief.risk_class ? RISK_TEXT[brief.risk_class] : 'Not assessed'}</Badge>
            {brief.risk_md ? <Markdown>{brief.risk_md}</Markdown> : null}
          </div>
        )}
      </SectionCard>

      <SectionCard
        title="Plan"
        description="plan.md: material, orientation, critical dimensions, tests."
        editing={editing === 'plan'}
        canWrite={canWrite}
        onEdit={() => edit('plan')}
      >
        {editing === 'plan' ? (
          <PlanEditor
            planMd={brief.plan_md}
            saving={update.isPending}
            error={error}
            onCancel={stopEditing}
            onSave={(planMd) => save({ plan_md: planMd })}
          />
        ) : brief.plan_md ? (
          <Markdown>{brief.plan_md}</Markdown>
        ) : (
          <p className="text-sm text-muted-foreground">No plan yet.</p>
        )}
      </SectionCard>

      <SectionCard
        title="Parameters"
        description="params.yaml: the design's current inputs."
        editing={editing === 'params'}
        canWrite={canWrite}
        onEdit={() => edit('params')}
      >
        {editing === 'params' ? (
          <ParamsEditor
            params={brief.params}
            saving={update.isPending}
            error={error}
            onCancel={stopEditing}
            onSave={(paramsYaml) => save({ params_yaml: paramsYaml })}
          />
        ) : brief.params && Object.keys(brief.params).length > 0 ? (
          <pre className="overflow-x-auto whitespace-pre-wrap rounded-md bg-muted p-2 text-xs">
            {blockText(brief.params)}
          </pre>
        ) : (
          <p className="text-sm text-muted-foreground">No parameters yet.</p>
        )}
      </SectionCard>

      <BriefRevisionsDialog briefId={brief.id} open={historyOpen} onOpenChange={setHistoryOpen} />
    </div>
  )
}

export function DesignBriefPanel({ owner, canWrite }: DesignBriefPanelProps) {
  const { brief, isLoading, error } = useDesignBrief(owner)
  const start = useStartDesignBrief(owner)

  if (isLoading) return <p className="text-sm text-muted-foreground">Loading the design brief…</p>
  if (error) {
    return (
      <p role="alert" className="text-sm text-destructive">
        {apiErrorDetail(error)}
      </p>
    )
  }
  if (!brief) {
    return (
      <div className="rounded-md border border-dashed p-6 text-center">
        <p className="text-sm text-muted-foreground">
          No design brief yet. A brief holds Preflight's intent, risk, plan and step statuses for this part.
        </p>
        {canWrite && (
          <Button className="mt-3" onClick={() => start.mutate({})} disabled={start.isPending}>
            Start a design brief
          </Button>
        )}
        {start.error && (
          <p role="alert" className="mt-2 text-sm text-destructive">
            {apiErrorDetail(start.error)}
          </p>
        )}
      </div>
    )
  }
  return <BriefBody brief={brief} canWrite={canWrite} owner={owner} />
}
