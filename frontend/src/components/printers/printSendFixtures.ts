/**
 * Shared print send summary fixture for the spec 011 component tests.
 */
import type { PrintSendSummary as Summary } from '@/types/printSend'

export function summaryFixture(overrides: Partial<Summary> = {}): Summary {
  return {
    id: 'send-1',
    status: 'prepared',
    expires_at: new Date(Date.now() + 5 * 60_000).toISOString(),
    printer: { id: 'printer-1', name: 'X1 Carbon' },
    file: { name: 'dragon.gcode.3mf', model_id: null, model_file_id: null },
    plate: { index: 1, print_time_minutes: 95, filament_weight_grams: '35.10' },
    lines: [
      {
        filament_id: 1,
        expected: { type: 'PLA', color: '#FF0000', grams: '30.10' },
        slot: { kind: 'ams', ams_id: 0, tray_id: 1, label: 'AMS 1 · slot 2' },
        mapped_spool: {
          id: 'spool-1',
          spool_id: 'SP-PETG',
          material: 'PETG',
          color: '#00FF00',
          current_weight: '800.00',
        },
        reported: { type: 'PETG', color: '#00FF00', present: true },
        warnings: ['material_mismatch'],
      },
      {
        filament_id: 3,
        expected: { type: 'PETG', color: '#00FF00', grams: '5.00' },
        slot: { kind: 'external', ams_id: null, tray_id: null, label: 'External spool' },
        mapped_spool: null,
        reported: null,
        warnings: [],
      },
    ],
    warnings: [
      {
        code: 'material_mismatch',
        message: 'Plate expects PLA, the spool mapped to this slot is PETG',
        filament_id: 1,
      },
    ],
    blockers: [],
    requires_acknowledgement: true,
    ...overrides,
  }
}
