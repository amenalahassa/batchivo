/**
 * ModelFilesEditor Component (spec 004, T032, T043)
 *
 * A model's files grouped by version, newest first. One version is active: its
 * print file feeds the cost profile and its measured file gives the
 * dimensions. Uploading into a new version leaves it inactive and offers
 * "Make active", which opens the activation review (clarification Q3).
 * Every file can be opened in the 3D viewer, a lazily loaded chunk.
 *
 * A viewer-role user reads everything and changes nothing: the write actions
 * are not offered (FR-032); the API refuses them regardless.
 */

import { lazy, Suspense, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  Sparkles,
  Download,
  Eye,
  File,
  FileBox,
  FileCog,
  FolderOpen,
  Link2,
  Loader2,
  Pencil,
  Printer,
  Trash2,
  Upload,
} from 'lucide-react'

import {
  uploadModelFileWithResult,
  deleteModelFile,
  getModelFileDownloadUrl,
  inferModelFileType,
  linkLocalModelFile,
  validateLocalPath,
  getModel,
  type ModelFile,
  type ModelFileType,
  type LocalPathValidationResponse,
} from '@/lib/api/models'
import { getAuthTokens } from '@/lib/auth'
import { apiErrorDetail } from '@/lib/apiError'
import { useAuth } from '@/contexts/AuthContext'
import { canEditOperationalFigures } from '@/lib/pricing/permissions'
import {
  invalidateAfterFileChange,
  useFileVersions,
  useUpdateFileVersion,
} from '@/hooks/useModelFileVersions'
import type { FileVersion } from '@/types/model-file-version'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { FileMeasurementSummary } from './FileMeasurementSummary'
import { VersionActivationDialog } from './VersionActivationDialog'
import { refusalMessage } from './fileMessages'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { AIBadge } from '@/components/genai/AIBadge'
import { GenerateDialog, type InputCandidate } from '@/components/genai/GenerateDialog'
import { JobHistory } from '@/components/genai/JobHistory'
import { useGenAIRoles } from '@/components/genai/useGenAIRoles'

/** The label an adopted 3D draft's version carries (spec 008, US4). */
const AI_DRAFT_LABEL = 'AI draft'

// three.js weighs ~600 kB: keep it out of every other page (FR-024, SC-007).
const ModelViewerDialog = lazy(() => import('@/components/viewer/ModelViewerDialog'))

interface ModelFilesEditorProps {
  modelId: string
}

const FILE_TYPE_LABELS: Record<ModelFileType, string> = {
  source_stl: 'STL File',
  source_3mf: '3MF File',
  slicer_project: 'Slicer Project',
  gcode: 'G-code',
  plate_layout: 'Plate Layout',
}

/** Where an upload goes: the active version, another version, or a new one. */
const NEW_VERSION = '__new__'

function FileTypeIcon({ type }: { type: ModelFileType }) {
  switch (type) {
    case 'source_stl':
    case 'source_3mf':
      return <FileBox className="h-5 w-5" />
    case 'slicer_project':
      return <FileCog className="h-5 w-5" />
    default:
      return <File className="h-5 w-5" />
  }
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatDate(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString()
}

export function ModelFilesEditor({ modelId }: ModelFilesEditorProps) {
  const queryClient = useQueryClient()
  const { user } = useAuth()
  const canWrite = canEditOperationalFigures(user)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const { versions: unsorted, isLoading } = useFileVersions(modelId)
  const versions = [...unsorted].sort((a, b) => b.sequence - a.sequence)
  const activeVersion = versions.find((v) => v.is_active) ?? null
  const fileCount = versions.reduce((n, v) => n + v.files.length, 0)

  const [isUploading, setIsUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [target, setTarget] = useState<string>('')
  const [newLabel, setNewLabel] = useState('')
  const [newNote, setNewNote] = useState('')
  const [selectedFileType, setSelectedFileType] = useState<ModelFileType | 'auto'>('auto')

  // The version just created by an upload, offered for activation (FR-009a).
  const [offerVersionId, setOfferVersionId] = useState<string | null>(null)
  // The activation review: which version, and which print file.
  const [review, setReview] = useState<{ versionId: string; printFileId?: string } | null>(null)
  const [viewing, setViewing] = useState<ModelFile | null>(null)
  const [editing, setEditing] = useState<string | null>(null)

  const [localPath, setLocalPath] = useState('')
  const [isValidatingPath, setIsValidatingPath] = useState(false)
  const [pathValidation, setPathValidation] = useState<LocalPathValidationResponse | null>(null)
  const [isLinking, setIsLinking] = useState(false)

  const updateVersion = useUpdateFileVersion(modelId)

  // Generative AI (spec 008, US4): members and up draft a 3D model from an image.
  const { canGenerate } = useGenAIRoles()
  const [historyOpen, setHistoryOpen] = useState(false)
  // The model the page already loaded; never fetched from here.
  const { data: model } = useQuery({
    queryKey: ['model', modelId],
    queryFn: () => getModel(modelId),
    enabled: false,
  })
  const draftInputs: InputCandidate[] = model?.image_url
    ? [{ ref: { type: 'model_image', id: modelId }, label: `${model.name} image` }]
    : []

  const deleteMutation = useMutation({
    mutationFn: (fileId: string) => deleteModelFile(modelId, fileId),
    onSuccess: () => {
      invalidateAfterFileChange(queryClient, modelId)
      setError(null)
    },
    onError: (err) => setError(refusalMessage(err)),
  })

  const targetIsNew = target === NEW_VERSION
  const versionTarget = () =>
    targetIsNew
      ? { newVersionLabel: newLabel.trim() || String((versions[0]?.sequence ?? 0) + 1), newVersionNote: newNote.trim() || undefined }
      : target
        ? { versionId: target }
        : {}

  const uploadFiles = async (files: File[]) => {
    if (files.length === 0) return
    setIsUploading(true)
    setError(null)
    let target_ = versionTarget()
    for (const file of files) {
      const fileType =
        selectedFileType === 'auto' ? inferModelFileType(file.name) ?? 'source_3mf' : selectedFileType
      try {
        const result = await uploadModelFileWithResult(modelId, file, fileType, target_)
        if (result.version_created && result.file.version_id) {
          setOfferVersionId(result.file.version_id)
          // The rest of a multi-file drop joins the version just made.
          target_ = { versionId: result.file.version_id }
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to upload file')
      }
    }
    invalidateAfterFileChange(queryClient, modelId)
    setIsUploading(false)
    if (targetIsNew) {
      setTarget('')
      setNewLabel('')
      setNewNote('')
    }
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  const handlePathChange = async (path: string) => {
    setLocalPath(path)
    setPathValidation(null)
    if (!path.trim()) return
    setIsValidatingPath(true)
    try {
      setPathValidation(await validateLocalPath(path))
    } catch {
      setPathValidation(null)
    } finally {
      setIsValidatingPath(false)
    }
  }

  const handleLinkLocalFile = async () => {
    if (!localPath.trim() || !pathValidation?.exists || !pathValidation?.is_file) return
    setIsLinking(true)
    setError(null)
    try {
      const fileType =
        selectedFileType === 'auto' ? inferModelFileType(localPath) ?? 'source_3mf' : selectedFileType
      await linkLocalModelFile(modelId, localPath, fileType, versionTarget())
      invalidateAfterFileChange(queryClient, modelId)
      setLocalPath('')
      setPathValidation(null)
    } catch (err) {
      setError(apiErrorDetail(err))
    } finally {
      setIsLinking(false)
    }
  }

  const handleDownload = (file: ModelFile) => {
    const token = getAuthTokens()?.accessToken
    fetch(getModelFileDownloadUrl(modelId, file.id), {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then((response) => response.blob())
      .then((blob) => {
        const blobUrl = window.URL.createObjectURL(blob)
        const link = document.createElement('a')
        link.href = blobUrl
        link.download = file.original_filename
        document.body.appendChild(link)
        link.click()
        document.body.removeChild(link)
        window.URL.revokeObjectURL(blobUrl)
      })
  }

  const choosePrintFile = (version: FileVersion, file: ModelFile) => {
    if (version.is_active) {
      // The active version's print file feeds the cost profile: review first.
      setReview({ versionId: version.id, printFileId: file.id })
    } else {
      updateVersion.mutate(
        { versionId: version.id, print_file_id: file.id },
        { onError: (err) => setError(refusalMessage(err)) }
      )
    }
  }

  const reviewVersion = versions.find((v) => v.id === review?.versionId) ?? null
  const offerVersion = versions.find((v) => v.id === offerVersionId && !v.is_active) ?? null

  const header = (
    <CardTitle className="flex items-center gap-2">
      <FileBox className="h-5 w-5" />
      3D Model Files
      {fileCount > 0 && (
        <Badge variant="secondary" className="ml-2">
          {fileCount}
        </Badge>
      )}
    </CardTitle>
  )

  if (isLoading) {
    return (
      <Card>
        <CardHeader>{header}</CardHeader>
        <CardContent>
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-6 w-6 animate-spin" />
          </div>
        </CardContent>
      </Card>
    )
  }

  const typeSelect = (
    <Select value={selectedFileType} onValueChange={(v) => setSelectedFileType(v as ModelFileType | 'auto')}>
      <SelectTrigger className="w-[180px]" aria-label="File type">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="auto">Type from name</SelectItem>
        <SelectItem value="source_stl">STL File</SelectItem>
        <SelectItem value="source_3mf">3MF File</SelectItem>
        <SelectItem value="slicer_project">Slicer Project</SelectItem>
        <SelectItem value="gcode">G-code</SelectItem>
        <SelectItem value="plate_layout">Plate Layout</SelectItem>
      </SelectContent>
    </Select>
  )

  const targetPicker = (
    <div className="space-y-2 text-left">
      <Select value={target || '__active__'} onValueChange={(v) => setTarget(v === '__active__' ? '' : v)}>
        <SelectTrigger className="w-full sm:w-[260px]" aria-label="Add to version">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="__active__">
            {activeVersion ? `Active version (${activeVersion.label})` : 'Version 1 (new model)'}
          </SelectItem>
          {versions
            .filter((v) => !v.is_active)
            .map((v) => (
              <SelectItem key={v.id} value={v.id}>
                Version {v.label}
              </SelectItem>
            ))}
          {versions.length > 0 && <SelectItem value={NEW_VERSION}>New version…</SelectItem>}
        </SelectContent>
      </Select>
      {targetIsNew && (
        <div className="grid gap-2 sm:grid-cols-[120px_1fr]">
          <Input
            aria-label="New version label"
            placeholder={String((versions[0]?.sequence ?? 0) + 1)}
            maxLength={50}
            value={newLabel}
            onChange={(e) => setNewLabel(e.target.value)}
          />
          <Input
            aria-label="What changed"
            placeholder="What changed, e.g. thicker walls"
            maxLength={2000}
            value={newNote}
            onChange={(e) => setNewNote(e.target.value)}
          />
        </div>
      )}
    </div>
  )

  return (
    <Card>
      <CardHeader>{header}</CardHeader>
      <CardContent className="space-y-4">
        {canWrite && (
          <Tabs defaultValue="upload" className="w-full">
            <TabsList className="grid w-full grid-cols-2">
              <TabsTrigger value="upload" className="flex items-center gap-2">
                <Upload className="h-4 w-4" />
                Upload File
              </TabsTrigger>
              <TabsTrigger value="link" className="flex items-center gap-2">
                <Link2 className="h-4 w-4" />
                Link Local File
              </TabsTrigger>
            </TabsList>

            <TabsContent value="upload">
              <div
                className={cn(
                  'border-2 border-dashed rounded-lg p-6 text-center transition-colors',
                  'hover:border-primary/50 hover:bg-muted/50',
                  isUploading && 'opacity-50 pointer-events-none'
                )}
                onDrop={(event) => {
                  event.preventDefault()
                  event.stopPropagation()
                  void uploadFiles(Array.from(event.dataTransfer.files ?? []))
                }}
                onDragOver={(event) => {
                  event.preventDefault()
                  event.stopPropagation()
                }}
              >
                <input
                  ref={fileInputRef}
                  type="file"
                  className="hidden"
                  accept=".stl,.3mf,.gcode,.gco,.g"
                  multiple
                  aria-label="Choose files to upload"
                  onChange={(event) => void uploadFiles(Array.from(event.target.files ?? []))}
                />
                <div className="flex flex-col items-center gap-3">
                  <Upload className="h-8 w-8 text-muted-foreground" />
                  <div className="text-sm text-muted-foreground">
                    Drag and drop files here, or click to select
                  </div>
                  <div className="text-xs text-muted-foreground">
                    STL, project 3MF, sliced .gcode.3mf and G-code (up to 500MB)
                  </div>
                  {targetPicker}
                  <div className="flex flex-wrap items-center justify-center gap-2 mt-2">
                    {typeSelect}
                    <Button
                      variant="outline"
                      onClick={() => fileInputRef.current?.click()}
                      disabled={isUploading}
                    >
                      {isUploading ? (
                        <Loader2 className="h-4 w-4 animate-spin mr-2" />
                      ) : (
                        <Upload className="h-4 w-4 mr-2" />
                      )}
                      Select Files
                    </Button>
                  </div>
                </div>
              </div>
            </TabsContent>

            <TabsContent value="link">
              <div className="border rounded-lg p-4 space-y-4">
                <div className="flex flex-col gap-2">
                  <div className="flex items-center gap-2">
                    <FolderOpen className="h-5 w-5 text-muted-foreground" />
                    <span className="text-sm font-medium">Local File Path</span>
                  </div>
                  <div className="text-xs text-muted-foreground">
                    Enter the full path to a file on your local filesystem (e.g., OrcaSlicer project)
                  </div>
                </div>
                <div className="relative">
                  <Input
                    placeholder="/path/to/your/file.3mf"
                    value={localPath}
                    onChange={(e) => void handlePathChange(e.target.value)}
                    className={cn(
                      'pr-10',
                      pathValidation?.exists && pathValidation?.is_file && 'border-green-500',
                      pathValidation && !pathValidation.exists && 'border-red-500'
                    )}
                  />
                  {isValidatingPath && (
                    <Loader2 className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 animate-spin text-muted-foreground" />
                  )}
                  {!isValidatingPath && pathValidation?.exists && pathValidation?.is_file && (
                    <CheckCircle2 className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-green-500" />
                  )}
                  {!isValidatingPath && pathValidation && !pathValidation.exists && (
                    <AlertCircle className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-red-500" />
                  )}
                </div>
                {pathValidation && (
                  <div
                    className={cn(
                      'text-sm p-2 rounded',
                      pathValidation.exists && pathValidation.is_file
                        ? 'bg-green-50 text-green-700 dark:bg-green-950 dark:text-green-300'
                        : 'bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-300'
                    )}
                  >
                    {pathValidation.exists && pathValidation.is_file
                      ? `Found: ${pathValidation.filename}${pathValidation.file_size ? ` (${formatFileSize(pathValidation.file_size)})` : ''}`
                      : pathValidation.exists
                        ? 'Path exists but is not a file (might be a directory)'
                        : 'File not found at this path'}
                  </div>
                )}
                {targetPicker}
                <div className="flex flex-wrap items-center gap-2">
                  {typeSelect}
                  <Button
                    onClick={handleLinkLocalFile}
                    disabled={isLinking || !pathValidation?.exists || !pathValidation?.is_file}
                  >
                    {isLinking ? (
                      <Loader2 className="h-4 w-4 animate-spin mr-2" />
                    ) : (
                      <Link2 className="h-4 w-4 mr-2" />
                    )}
                    Link File
                  </Button>
                </div>
              </div>
            </TabsContent>
          </Tabs>
        )}

        {error && (
          <div className="text-sm text-destructive bg-destructive/10 p-3 rounded-md" role="alert">
            {error}
          </div>
        )}

        {canWrite && offerVersion && (
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-primary/40 bg-primary/5 p-3 text-sm">
            <span>
              Version {offerVersion.label} was created. It is not used for printing until you make
              it active.
            </span>
            <div className="flex gap-2">
              <Button size="sm" variant="ghost" onClick={() => setOfferVersionId(null)}>
                Not now
              </Button>
              <Button
                size="sm"
                onClick={() => {
                  setReview({ versionId: offerVersion.id })
                  setOfferVersionId(null)
                }}
              >
                Make active
              </Button>
            </div>
          </div>
        )}

        {versions.length > 0 && (
          <ol className="space-y-3" aria-label="Versions">
            {versions.map((version) => (
              <VersionBlock
                key={version.id}
                version={version}
                canWrite={canWrite}
                editing={editing === version.id}
                onEdit={() => setEditing(version.id)}
                onEditDone={() => setEditing(null)}
                onSave={(label, note) =>
                  updateVersion.mutate(
                    { versionId: version.id, label, note },
                    {
                      onSuccess: () => setEditing(null),
                      onError: (err) => setError(refusalMessage(err)),
                    }
                  )
                }
                onMakeActive={() => setReview({ versionId: version.id })}
                onChoosePrintFile={(file) => choosePrintFile(version, file)}
                onDownload={handleDownload}
                onView={setViewing}
                onDelete={(file) => deleteMutation.mutate(file.id)}
              />
            ))}
          </ol>
        )}

        {versions.length === 0 && (
          <div className="text-center py-6 text-muted-foreground">
            No files uploaded yet. Upload STL, 3MF, or G-code files to get started.
          </div>
        )}

        {canGenerate && (
          <div className="flex justify-end">
            <GenerateDialog
              capability="image_to_3d"
              title="Draft 3D from image"
              target={{ type: 'model', id: modelId }}
              adoptTarget={{ type: 'model', id: modelId }}
              inputAssets={draftInputs}
              trigger={
                <Button variant="outline" size="sm" className="gap-2">
                  <Sparkles className="h-4 w-4" aria-hidden />
                  Draft 3D from image
                </Button>
              }
            />
          </div>
        )}

        {/* AI generations made for this model (spec 008, US5) */}
        <Collapsible open={historyOpen} onOpenChange={setHistoryOpen}>
          <CollapsibleTrigger asChild>
            <Button variant="ghost" size="sm" className="gap-2">
              <Sparkles className="h-4 w-4" aria-hidden />
              AI generations
              <ChevronDown className={cn('h-4 w-4 transition-transform', historyOpen && 'rotate-180')} aria-hidden />
            </Button>
          </CollapsibleTrigger>
          <CollapsibleContent className="pt-2">
            <JobHistory targetType="model" targetId={modelId} />
          </CollapsibleContent>
        </Collapsible>
      </CardContent>

      <VersionActivationDialog
        modelId={modelId}
        version={reviewVersion}
        printFileId={review?.printFileId}
        open={review !== null}
        onOpenChange={(open) => !open && setReview(null)}
      />

      {viewing && (
        <Suspense fallback={null}>
          <ModelViewerDialog
            modelId={modelId}
            file={viewing}
            versions={versions}
            canWrite={canWrite}
            open
            onOpenChange={(open) => !open && setViewing(null)}
          />
        </Suspense>
      )}
    </Card>
  )
}

interface VersionBlockProps {
  version: FileVersion
  canWrite: boolean
  editing: boolean
  onEdit: () => void
  onEditDone: () => void
  onSave: (label: string, note: string | null) => void
  onMakeActive: () => void
  onChoosePrintFile: (file: ModelFile) => void
  onDownload: (file: ModelFile) => void
  onView: (file: ModelFile) => void
  onDelete: (file: ModelFile) => void
}

function VersionBlock({
  version,
  canWrite,
  editing,
  onEdit,
  onEditDone,
  onSave,
  onMakeActive,
  onChoosePrintFile,
  onDownload,
  onView,
  onDelete,
}: VersionBlockProps) {
  const [label, setLabel] = useState(version.label)
  const [note, setNote] = useState(version.note ?? '')

  return (
    <li
      className={cn('rounded-lg border p-3 space-y-2', version.is_active && 'border-primary bg-primary/5')}
      aria-label={`Version ${version.label}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">Version {version.label}</span>
            {version.label === AI_DRAFT_LABEL && <AIBadge label={AI_DRAFT_LABEL} />}
            {version.is_active && <Badge>Active</Badge>}
            {version.open_note_count > 0 && (
              <Badge variant="secondary">
                {version.open_note_count} open note{version.open_note_count === 1 ? '' : 's'}
              </Badge>
            )}
          </div>
          <div className="text-xs text-muted-foreground">
            {formatDate(version.created_at)}
            {version.created_by && <> · {version.created_by.name}</>}
          </div>
          {!editing && version.note && <p className="text-sm mt-1">{version.note}</p>}
        </div>
        {canWrite && !editing && (
          <div className="flex items-center gap-1">
            <Button variant="ghost" size="sm" onClick={onEdit} aria-label={`Edit version ${version.label}`}>
              <Pencil className="h-4 w-4" />
            </Button>
            {!version.is_active && (
              <Button variant="outline" size="sm" onClick={onMakeActive}>
                Make active
              </Button>
            )}
          </div>
        )}
      </div>

      {editing && (
        <div className="space-y-2">
          <Input
            aria-label="Version label"
            maxLength={50}
            value={label}
            onChange={(e) => setLabel(e.target.value)}
          />
          <Textarea
            aria-label="Version note"
            maxLength={2000}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="What changed"
          />
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="ghost" onClick={onEditDone}>
              Cancel
            </Button>
            <Button
              size="sm"
              disabled={!label.trim()}
              onClick={() => onSave(label.trim(), note.trim() || null)}
            >
              Save
            </Button>
          </div>
        </div>
      )}

      {version.is_active && !version.has_measurable_file && (
        <p className="text-sm text-amber-600" role="status">
          No measurable file in the active version. Upload the .stl or the project .3mf to get the
          model&apos;s dimensions.
        </p>
      )}

      <ul className="space-y-2">
        {version.files.map((file) => {
          const isPrintFile = version.print_file_id === file.id
          return (
            <li key={file.id} className="flex items-center gap-3 rounded-md border bg-background p-2">
              <div className="text-muted-foreground">
                <FileTypeIcon type={file.file_type} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium truncate">{file.original_filename}</span>
                  {isPrintFile && (
                    <Badge variant="default" className="shrink-0">
                      <Printer className="h-3 w-3 mr-1" />
                      Print file
                    </Badge>
                  )}
                  {file.file_location === 'local_reference' && (
                    <Badge variant={file.local_path_exists ? 'secondary' : 'destructive'} className="shrink-0">
                      <Link2 className="h-3 w-3 mr-1" />
                      {file.local_path_exists ? 'Local' : 'Missing'}
                    </Badge>
                  )}
                </div>
                <div className="text-xs text-muted-foreground flex items-center gap-2 flex-wrap">
                  <span>{FILE_TYPE_LABELS[file.file_type]}</span>
                  {file.file_size ? <span>· {formatFileSize(file.file_size)}</span> : null}
                  {file.part_name && <span>· Part: {file.part_name}</span>}
                  <span>· {formatDate(file.uploaded_at)}</span>
                </div>
                <FileMeasurementSummary measurement={file.measurement} isSliced={file.is_sliced} />
              </div>
              <div className="flex items-center gap-1">
                <Button variant="ghost" size="icon" onClick={() => onView(file)} title="View">
                  <Eye className="h-4 w-4" />
                </Button>
                <Button variant="ghost" size="icon" onClick={() => onDownload(file)} title="Download">
                  <Download className="h-4 w-4" />
                </Button>
                {canWrite && file.is_sliced && !isPrintFile && (
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => onChoosePrintFile(file)}
                    title="Use as print file"
                  >
                    <Printer className="h-4 w-4" />
                  </Button>
                )}
                {canWrite && (
                  <AlertDialog>
                    <AlertDialogTrigger asChild>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="text-destructive hover:text-destructive"
                        title="Delete"
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </AlertDialogTrigger>
                    <AlertDialogContent>
                      <AlertDialogHeader>
                        <AlertDialogTitle>Delete File</AlertDialogTitle>
                        <AlertDialogDescription>
                          Are you sure you want to delete &quot;{file.original_filename}&quot;? This
                          action cannot be undone. Its notes are archived, not lost.
                        </AlertDialogDescription>
                      </AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel>Cancel</AlertDialogCancel>
                        <AlertDialogAction
                          onClick={() => onDelete(file)}
                          className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                        >
                          Delete
                        </AlertDialogAction>
                      </AlertDialogFooter>
                    </AlertDialogContent>
                  </AlertDialog>
                )}
              </div>
            </li>
          )
        })}
      </ul>
    </li>
  )
}
