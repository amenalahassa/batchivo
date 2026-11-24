/**
 * Product ideas with TanStack Query (spec 007).
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { ideasApi } from '@/lib/api/ideas'
import type {
  ConvertRequest,
  IdeaCreate,
  IdeaEntryCreate,
  IdeaEntryUpdate,
  IdeaListParams,
  IdeaUpdate,
  ImageEntryKind,
  ImportItem,
} from '@/types/idea'

export const ideaKeys = {
  all: ['ideas'] as const,
  list: (params: IdeaListParams) => ['ideas', 'list', params] as const,
  tags: () => ['ideas', 'tags'] as const,
  detail: (ideaId: string) => ['ideas', 'detail', ideaId] as const,
  entries: (ideaId: string, includeArchived: boolean) =>
    ['ideas', 'entries', ideaId, includeArchived] as const,
}

export function useIdeas(params: IdeaListParams, enabled = true) {
  const query = useQuery({
    queryKey: ideaKeys.list(params),
    queryFn: () => ideasApi.list(params),
    enabled,
    placeholderData: (previous) => previous,
  })
  return {
    ideas: query.data?.items ?? [],
    total: query.data?.total ?? 0,
    isLoading: query.isLoading,
    isFetching: query.isFetching,
    error: query.error,
  }
}

export function useIdeaTags() {
  const query = useQuery({ queryKey: ideaKeys.tags(), queryFn: ideasApi.tags })
  return { tags: query.data ?? [] }
}

export function useIdea(ideaId: string) {
  const query = useQuery({
    queryKey: ideaKeys.detail(ideaId),
    queryFn: () => ideasApi.get(ideaId),
    enabled: Boolean(ideaId),
  })
  return { idea: query.data, isLoading: query.isLoading, error: query.error }
}

export function useIdeaEntries(ideaId: string, includeArchived = false) {
  const query = useQuery({
    queryKey: ideaKeys.entries(ideaId, includeArchived),
    queryFn: () => ideasApi.listEntries(ideaId, includeArchived),
    enabled: Boolean(ideaId),
  })
  return {
    entries: query.data?.items ?? [],
    currentIteration: query.data?.current_iteration ?? 1,
    isLoading: query.isLoading,
    error: query.error,
  }
}

/** Everything about ideas is refetched after a write: lists, detail, timeline. */
function useInvalidateIdeas() {
  const queryClient = useQueryClient()
  return () => queryClient.invalidateQueries({ queryKey: ideaKeys.all })
}

export function useCreateIdea() {
  const invalidate = useInvalidateIdeas()
  return useMutation({ mutationFn: (data: IdeaCreate) => ideasApi.create(data), onSuccess: invalidate })
}

export function useUpdateIdea(ideaId: string) {
  const invalidate = useInvalidateIdeas()
  return useMutation({
    mutationFn: (data: IdeaUpdate) => ideasApi.update(ideaId, data),
    onSuccess: invalidate,
  })
}

/** Change one idea from a list (status menu on a board card, restore in the list). */
export function useUpdateAnyIdea() {
  const invalidate = useInvalidateIdeas()
  return useMutation({
    mutationFn: ({ ideaId, ...data }: IdeaUpdate & { ideaId: string }) =>
      ideasApi.update(ideaId, data),
    onSuccess: invalidate,
  })
}

export function useArchiveIdea(ideaId: string) {
  const invalidate = useInvalidateIdeas()
  return useMutation({ mutationFn: () => ideasApi.archive(ideaId), onSuccess: invalidate })
}

export function useCreateEntry(ideaId: string) {
  const invalidate = useInvalidateIdeas()
  return useMutation({
    mutationFn: (data: IdeaEntryCreate) => ideasApi.createEntry(ideaId, data),
    onSuccess: invalidate,
  })
}

export function useUploadImages(ideaId: string) {
  const invalidate = useInvalidateIdeas()
  return useMutation({
    mutationFn: ({ files, kind }: { files: File[]; kind?: ImageEntryKind }) =>
      ideasApi.uploadImages(ideaId, files, kind),
    onSuccess: invalidate,
  })
}

export function useUpdateEntry(ideaId: string) {
  const invalidate = useInvalidateIdeas()
  return useMutation({
    mutationFn: ({ entryId, ...data }: IdeaEntryUpdate & { entryId: string }) =>
      ideasApi.updateEntry(ideaId, entryId, data),
    onSuccess: invalidate,
  })
}

export function useStartIteration(ideaId: string) {
  const invalidate = useInvalidateIdeas()
  return useMutation({
    mutationFn: (note?: string) => ideasApi.startIteration(ideaId, note),
    onSuccess: invalidate,
  })
}

export function useConvertIdea(ideaId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: ConvertRequest) => ideasApi.convert(ideaId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ideaKeys.all })
      queryClient.invalidateQueries({ queryKey: ['models'] })
      queryClient.invalidateQueries({ queryKey: ['products'] })
    },
  })
}

export function useParseReport() {
  return useMutation({ mutationFn: (text: string) => ideasApi.parseReport(text) })
}

export function useImportIdeas() {
  const invalidate = useInvalidateIdeas()
  return useMutation({
    mutationFn: ({ items, dryRun }: { items: ImportItem[]; dryRun: boolean }) =>
      ideasApi.importItems(items, dryRun),
    onSuccess: (_data, variables) => {
      if (!variables.dryRun) invalidate()
    },
  })
}

/** An idea image as an object URL; fetched with the session, cached for the session. */
export function useIdeaImage(path: string | null | undefined) {
  const query = useQuery({
    queryKey: ['idea-image', path],
    queryFn: () => ideasApi.getImageBlob(path as string),
    enabled: Boolean(path),
    staleTime: Infinity,
    gcTime: 10 * 60 * 1000,
    retry: false,
  })
  return { blob: query.data, isLoading: query.isLoading, isError: query.isError }
}
