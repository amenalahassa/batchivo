/**
 * PrinterCostPolicyDialog — the machine cost policy, reachable from the fleet.
 *
 * `PrinterCostPolicyForm` knows how to read and write one printer's cost
 * policy; it had no way in. FR-010 and FR-011 make the hourly occupancy rate a
 * per-machine figure, and an item is costed at the rate of the machine it is
 * planned on — so every printer in the list needs a door to its own rate, not
 * one global setting.
 *
 * The dialog carries the title and the printer's name, and the form's card
 * carries the explanation, so the two do not repeat each other.
 */

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { PrinterCostPolicyForm } from './PrinterCostPolicyForm'

interface PrinterCostPolicyDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Null while no printer is selected; the dialog then renders nothing. */
  printerId: string | null
  printerName?: string
  /** False for a member or viewer: the rate is money, so FR-007a applies. */
  canEdit?: boolean
}

export function PrinterCostPolicyDialog({
  open,
  onOpenChange,
  printerId,
  printerName,
  canEdit = true,
}: PrinterCostPolicyDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            Machine cost{printerName ? ` — ${printerName}` : ''}
          </DialogTitle>
          <DialogDescription>
            An item is costed at the rate of the machine it is planned on, so this figure
            belongs to this printer alone.
          </DialogDescription>
        </DialogHeader>

        {printerId ? (
          <PrinterCostPolicyForm printerId={printerId} canEdit={canEdit} />
        ) : null}
      </DialogContent>
    </Dialog>
  )
}
