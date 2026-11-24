/**
 * PrinterSendActions — the connection, send and sends buttons of a printer row (spec 011).
 *
 * "Send print" appears only for a Bambu LAN printer whose connection says
 * Developer Mode is on (FR-014); the backend refuses a send otherwise anyway.
 */

import { History, Plug, Send } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { usePrinterConnection } from '@/hooks/usePrintSends'
import type { Printer } from '@/types/printer'

interface PrinterSendActionsProps {
  printer: Printer
  compact?: boolean
  onConnection: (printer: Printer) => void
  onSend: (printer: Printer) => void
  onSends: (printer: Printer) => void
}

export function PrinterSendActions({
  printer,
  compact = false,
  onConnection,
  onSend,
  onSends,
}: PrinterSendActionsProps) {
  const { connection } = usePrinterConnection(printer.id)
  const isBambu =
    connection != null && ['bambu_lan', 'bambu_cloud'].includes(connection.connection_type)
  const variant = compact ? 'ghost' : 'outline'
  const iconClass = compact ? 'h-4 w-4' : 'h-3 w-3 mr-1'

  return (
    <>
      <Button
        variant={variant}
        size="sm"
        aria-label={`Connection for ${printer.name}`}
        onClick={() => onConnection(printer)}
      >
        <Plug className={iconClass} />
        {!compact && 'Connection'}
      </Button>
      {connection?.can_send_prints && (
        <Button
          variant={variant}
          size="sm"
          aria-label={`Send print to ${printer.name}`}
          onClick={() => onSend(printer)}
        >
          <Send className={iconClass} />
          {!compact && 'Send print'}
        </Button>
      )}
      {isBambu && (
        <Button
          variant={variant}
          size="sm"
          aria-label={`Sends of ${printer.name}`}
          onClick={() => onSends(printer)}
        >
          <History className={iconClass} />
          {!compact && 'Sends'}
        </Button>
      )}
    </>
  )
}
