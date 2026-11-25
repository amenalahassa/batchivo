/**
 * Confirm adopting an image that does not show the real item (spec 008, FR-030).
 */
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'

interface AdoptConfirmDialogProps {
  open: boolean
  onConfirm: () => void
  onCancel: () => void
}

export function AdoptConfirmDialog({ open, onConfirm, onCancel }: AdoptConfirmDialogProps) {
  return (
    <AlertDialog open={open} onOpenChange={(next) => !next && onCancel()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Listings must show the real item</AlertDialogTitle>
          <AlertDialogDescription>
            This picture was imagined by AI: it is not a photo or a render of the product&apos;s
            real geometry. Buyers must see what they will receive. Add it as a product image only
            if it shows the real item faithfully.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel onClick={onCancel}>Cancel</AlertDialogCancel>
          <AlertDialogAction onClick={onConfirm}>Add anyway</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
