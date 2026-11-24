/**
 * Search, filters and sort of the ideas list (spec 007, FR-009).
 */
import { useEffect, useState } from 'react'

import { Input } from '@/components/ui/input'
import { useIdeaTags } from '@/hooks/useIdeas'
import type { IdeaListParams, IdeaSource, IdeaStatus } from '@/types/idea'

import { BOARD_STATUSES, SOURCE_LABELS, STATUS_LABELS } from './ideaText'

export const SEARCH_DELAY_MS = 300

interface IdeaFiltersProps {
  value: IdeaListParams
  onChange: (next: IdeaListParams) => void
}

const SELECT = 'h-9 rounded-md border bg-background px-2 text-sm'

export function IdeaFilters({ value, onChange }: IdeaFiltersProps) {
  const { tags } = useIdeaTags()
  const [search, setSearch] = useState(value.search ?? '')

  useEffect(() => {
    if (search === (value.search ?? '')) return
    const timer = setTimeout(
      () => onChange({ ...value, search: search || undefined }),
      SEARCH_DELAY_MS
    )
    return () => clearTimeout(timer)
  }, [search, value, onChange])

  return (
    <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Filters">
      <Input
        aria-label="Search ideas"
        placeholder="Search title and summary"
        className="w-64"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />
      <select
        aria-label="Status"
        className={SELECT}
        value={value.status?.[0] ?? ''}
        onChange={(e) =>
          onChange({
            ...value,
            status: e.target.value ? [e.target.value as IdeaStatus] : undefined,
          })
        }
      >
        <option value="">All statuses</option>
        {BOARD_STATUSES.map((s) => (
          <option key={s} value={s}>
            {STATUS_LABELS[s]}
          </option>
        ))}
      </select>
      <select
        aria-label="Tag"
        className={SELECT}
        value={value.tag?.[0] ?? ''}
        onChange={(e) => onChange({ ...value, tag: e.target.value ? [e.target.value] : undefined })}
      >
        <option value="">All tags</option>
        {tags.map((t) => (
          <option key={t} value={t}>
            {t}
          </option>
        ))}
      </select>
      <select
        aria-label="Source"
        className={SELECT}
        value={value.source ?? ''}
        onChange={(e) =>
          onChange({ ...value, source: (e.target.value || undefined) as IdeaSource | undefined })
        }
      >
        <option value="">All sources</option>
        {(Object.keys(SOURCE_LABELS) as IdeaSource[]).map((s) => (
          <option key={s} value={s}>
            {SOURCE_LABELS[s]}
          </option>
        ))}
      </select>
      <select
        aria-label="Archived"
        className={SELECT}
        value={value.archived ?? 'false'}
        onChange={(e) =>
          onChange({ ...value, archived: e.target.value as IdeaListParams['archived'] })
        }
      >
        <option value="false">Active</option>
        <option value="true">Archived</option>
        <option value="all">All</option>
      </select>
      <select
        aria-label="Sort"
        className={SELECT}
        value={value.sort ?? 'updated'}
        onChange={(e) => onChange({ ...value, sort: e.target.value as IdeaListParams['sort'] })}
      >
        <option value="updated">Last updated</option>
        <option value="score">Score</option>
      </select>
    </div>
  )
}
