/**
 * API client for sending prints to Bambu printers (spec 011).
 *
 * Prepare returns a summary and a confirmation token; confirm starts the print.
 * Both can take longer than the default timeout (the backend waits for the
 * printer), hence the per-call timeout.
 */

import { isAxiosError } from 'axios'

import { api } from '../api'
import type {
  ConsumptionAcceptLine,
  PreparePrintSendInput,
  PrintSend,
  PrintSendPrepared,
} from '@/types/printSend'

const BASE = '/api/v1/printers'
const SLOW_CALL_MS = 120_000

export const printSendsApi = {
  async prepare(printerId: string, input: PreparePrintSendInput): Promise<PrintSendPrepared> {
    const form = new FormData()
    form.append('plate', String(input.plate))
    form.append('ams_mapping', JSON.stringify(input.mapping))
    if (input.file) form.append('file', input.file)
    if (input.modelFileId) form.append('model_file_id', input.modelFileId)
    if (input.attachToModelId) form.append('attach_to_model_id', input.attachToModelId)
    const response = await api.post<PrintSendPrepared>(
      `${BASE}/${printerId}/prints/prepare`,
      form,
      { headers: { 'Content-Type': 'multipart/form-data' }, timeout: SLOW_CALL_MS }
    )
    return response.data
  },

  async confirm(
    printerId: string,
    confirmationToken: string,
    acknowledgeWarnings: boolean
  ): Promise<PrintSend> {
    const response = await api.post<PrintSend>(
      `${BASE}/${printerId}/prints/confirm`,
      { confirmation_token: confirmationToken, acknowledge_warnings: acknowledgeWarnings },
      { timeout: SLOW_CALL_MS }
    )
    return response.data
  },

  async list(printerId: string, limit = 20): Promise<PrintSend[]> {
    const response = await api.get<{ items: PrintSend[] }>(
      `${BASE}/${printerId}/prints?limit=${limit}`
    )
    return response.data.items
  },

  async acceptConsumption(
    printerId: string,
    sendId: string,
    lines: ConsumptionAcceptLine[]
  ): Promise<PrintSend> {
    const response = await api.post<PrintSend>(
      `${BASE}/${printerId}/prints/${sendId}/consumption/accept`,
      { lines }
    )
    return response.data
  },

  async dismissConsumption(printerId: string, sendId: string): Promise<PrintSend> {
    const response = await api.post<PrintSend>(
      `${BASE}/${printerId}/prints/${sendId}/consumption/dismiss`
    )
    return response.data
  },
}

const CODE_MESSAGES: Record<string, string> = {
  send_expired: 'This summary has expired. Prepare the send again.',
  send_already_used: 'This summary was already confirmed. Prepare a new send.',
  acknowledgement_required: 'Tick "I have checked the warnings" to start the print.',
  printer_busy: 'The printer is busy. Wait for it to finish, then prepare again.',
  printer_unreachable: 'The printer is not reachable. Check it is on and on the network.',
  send_not_available: 'Sending is not available: turn on Developer Mode in the connection settings.',
}

/** A readable message from a print send API error. */
export function printSendErrorMessage(error: unknown): string {
  if (isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (detail && typeof detail === 'object' && 'code' in detail) {
      const { code, message } = detail as { code: string; message: string }
      return CODE_MESSAGES[code] ?? message
    }
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) return 'Some fields are invalid.'
  }
  return error instanceof Error ? error.message : 'Something went wrong.'
}
