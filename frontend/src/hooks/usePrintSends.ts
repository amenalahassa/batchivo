/**
 * TanStack Query hooks for printer connections and print sends (spec 011).
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  getPrinterConnection,
  savePrinterConnection,
  testFileTransfer,
} from '@/lib/api/printers'
import { printSendsApi } from '@/lib/api/printSends'
import type { PrinterConnectionSave } from '@/types/printer'
import type { ConsumptionAcceptLine, PreparePrintSendInput } from '@/types/printSend'

export const printerConnectionKey = (printerId: string) =>
  ['printer-connection', printerId] as const
export const printSendsKey = (printerId: string) => ['print-sends', printerId] as const

export function usePrinterConnection(printerId: string | null) {
  const query = useQuery({
    queryKey: printerConnectionKey(printerId ?? ''),
    queryFn: () => getPrinterConnection(printerId as string),
    enabled: Boolean(printerId),
  })
  return { connection: query.data ?? null, isLoading: query.isLoading, error: query.error }
}

export function useSavePrinterConnection(printerId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: PrinterConnectionSave) => savePrinterConnection(printerId, data),
    onSuccess: (connection) => {
      queryClient.setQueryData(printerConnectionKey(printerId), connection)
    },
  })
}

export function useTestFileTransfer(printerId: string) {
  return useMutation({ mutationFn: () => testFileTransfer(printerId) })
}

export function usePreparePrintSend(printerId: string) {
  return useMutation({
    mutationFn: (input: PreparePrintSendInput) => printSendsApi.prepare(printerId, input),
  })
}

export function useConfirmPrintSend(printerId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ token, acknowledge }: { token: string; acknowledge: boolean }) =>
      printSendsApi.confirm(printerId, token, acknowledge),
    onSettled: () => queryClient.invalidateQueries({ queryKey: printSendsKey(printerId) }),
  })
}

export function usePrintSends(printerId: string | null) {
  const query = useQuery({
    queryKey: printSendsKey(printerId ?? ''),
    queryFn: () => printSendsApi.list(printerId as string),
    enabled: Boolean(printerId),
  })
  return { sends: query.data ?? [], isLoading: query.isLoading, error: query.error }
}

export function useAcceptConsumption(printerId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ sendId, lines }: { sendId: string; lines: ConsumptionAcceptLine[] }) =>
      printSendsApi.acceptConsumption(printerId, sendId, lines),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: printSendsKey(printerId) }),
  })
}

export function useDismissConsumption(printerId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (sendId: string) => printSendsApi.dismissConsumption(printerId, sendId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: printSendsKey(printerId) }),
  })
}
