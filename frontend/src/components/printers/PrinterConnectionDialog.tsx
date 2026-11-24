/**
 * PrinterConnectionDialog — a Bambu printer's LAN connection and Developer Mode (spec 011, US3).
 *
 * Sending prints from Batchivo needs the printer in LAN mode with Developer
 * Mode on, which Bambu printers only allow by turning cloud access off. The
 * operator declares the mode here (it cannot be read from the printer
 * reliably) and can check, without blocking the save, that the printer accepts
 * a file connection.
 */

import { useEffect, useState } from 'react'
import { AlertTriangle, CheckCircle2, Loader2, XCircle } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import {
  usePrinterConnection,
  useSavePrinterConnection,
  useTestFileTransfer,
} from '@/hooks/usePrintSends'
import { printSendErrorMessage } from '@/lib/api/printSends'

interface PrinterConnectionDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  printerId: string
  printerName: string
}

export function PrinterConnectionDialog({
  open,
  onOpenChange,
  printerId,
  printerName,
}: PrinterConnectionDialogProps) {
  const { connection, isLoading } = usePrinterConnection(open ? printerId : null)
  const save = useSavePrinterConnection(printerId)
  const transferTest = useTestFileTransfer(printerId)

  const [serial, setSerial] = useState('')
  const [ip, setIp] = useState('')
  const [accessCode, setAccessCode] = useState('')
  const [developerMode, setDeveloperMode] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    if (!open) return
    setSerial(connection?.serial_number ?? '')
    setIp(connection?.ip_address ?? '')
    setAccessCode('')
    setDeveloperMode(connection?.developer_mode ?? false)
    setSaved(false)
    transferTest.reset()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, connection?.id])

  const hasStoredCode = Boolean(connection?.access_code)
  // This dialog edits Bambu LAN connections; another kind is left untouched.
  const otherKind =
    connection != null && !['bambu_lan', 'bambu_cloud'].includes(connection.connection_type)

  const onSave = async () => {
    setSaved(false)
    await save.mutateAsync({
      connection_type: 'bambu_lan',
      serial_number: serial.trim() || null,
      ip_address: ip.trim() || null,
      access_code: accessCode.trim() || undefined,
      developer_mode: developerMode,
    })
    setAccessCode('')
    setSaved(true)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] max-w-lg overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Connection — {printerName}</DialogTitle>
          <DialogDescription>
            Bambu Lab printer on your local network (LAN mode).
          </DialogDescription>
        </DialogHeader>

        {isLoading ? (
          <Loader2 className="h-5 w-5 animate-spin" />
        ) : otherKind ? (
          <p className="text-sm text-muted-foreground">
            This printer uses a {connection?.connection_type} connection. Sending prints is only
            available for Bambu Lab printers on the local network.
          </p>
        ) : (
          <div className="space-y-4">
            <div className="space-y-1">
              <Label htmlFor="conn-serial">Serial number</Label>
              <Input id="conn-serial" value={serial} onChange={(e) => setSerial(e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="conn-ip">IP address</Label>
              <Input
                id="conn-ip"
                value={ip}
                placeholder="192.168.1.50"
                onChange={(e) => setIp(e.target.value)}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="conn-code">Access code</Label>
              <Input
                id="conn-code"
                type="password"
                autoComplete="off"
                value={accessCode}
                placeholder={hasStoredCode ? 'Leave blank to keep the current code' : ''}
                onChange={(e) => setAccessCode(e.target.value)}
              />
            </div>

            <div className="space-y-2 rounded-md border p-3">
              <div className="flex items-center justify-between gap-4">
                <Label htmlFor="conn-developer-mode" className="font-medium">
                  Developer Mode is on on this printer
                </Label>
                <Switch
                  id="conn-developer-mode"
                  checked={developerMode}
                  onCheckedChange={setDeveloperMode}
                />
              </div>
              <div className="space-y-1 text-sm text-muted-foreground">
                <p>
                  Sending prints from Batchivo needs the printer in <strong>LAN mode</strong> with{' '}
                  <strong>Developer Mode</strong> turned on, on the printer's own screen. Batchivo
                  then uploads the sliced file and starts it after you confirm a summary.
                </p>
                <p className="flex gap-2 text-amber-800">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                  <span>
                    Developer Mode turns off Bambu cloud access: no Bambu Handy app, no printing
                    from Bambu Studio through the cloud.
                  </span>
                </p>
                <p>
                  Without it, keep sending prints with Bambu Studio or Bambu Connect as before;
                  Batchivo still follows the printer's status.
                </p>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => transferTest.mutate()}
                disabled={transferTest.isPending || !connection}
              >
                {transferTest.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Test file transfer
              </Button>
              {!connection && (
                <span className="text-xs text-muted-foreground">Save the connection first.</span>
              )}
              {transferTest.data && (
                <span
                  className={`flex items-center gap-1 text-sm ${
                    transferTest.data.ok ? 'text-green-700' : 'text-destructive'
                  }`}
                  role="status"
                >
                  {transferTest.data.ok ? (
                    <CheckCircle2 className="h-4 w-4" />
                  ) : (
                    <XCircle className="h-4 w-4" />
                  )}
                  {transferTest.data.message}
                </span>
              )}
              {transferTest.error && (
                <span className="text-sm text-destructive" role="status">
                  {printSendErrorMessage(transferTest.error)}
                </span>
              )}
            </div>

            {save.error && (
              <p className="text-sm text-destructive" role="alert">
                {printSendErrorMessage(save.error)}
              </p>
            )}
            {saved && (
              <p className="text-sm text-green-700" role="status">
                Connection saved.
              </p>
            )}
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Close
          </Button>
          <Button
            onClick={() => void onSave().catch(() => undefined)}
            disabled={save.isPending || otherKind}
          >
            {save.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
