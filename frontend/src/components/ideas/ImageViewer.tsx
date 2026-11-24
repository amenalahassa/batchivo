/**
 * An idea image at full size, in a dialog (spec 007).
 */
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'

import { AuthImage } from './AuthImage'

interface ImageViewerProps {
  path: string | null
  title: string
  onClose: () => void
}

export function ImageViewer({ path, title, onClose }: ImageViewerProps) {
  return (
    <Dialog open={Boolean(path)} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-4xl">
        <DialogTitle>{title}</DialogTitle>
        <AuthImage path={path} alt={title} className="max-h-[75vh] w-full object-contain" />
      </DialogContent>
    </Dialog>
  )
}
