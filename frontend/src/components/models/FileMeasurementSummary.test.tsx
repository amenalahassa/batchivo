import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { FileMeasurement } from '@/types/packaging'
import { FileMeasurementSummary } from './FileMeasurementSummary'
import { anyMeasurementPending } from '@/lib/packaging'

const done: FileMeasurement = {
  length_mm: '60.0',
  width_mm: '30.0',
  height_mm: '20.0',
  objects: [
    { name: 'Body', length_mm: '40.0', width_mm: '30.0', height_mm: '20.0' },
    { name: 'Stand', length_mm: '10.0', width_mm: '10.0', height_mm: '10.0' },
  ],
  note: '2 objects; the overall size is the build plate as laid out',
  status: 'done',
  applied_to: [],
}

describe('FileMeasurementSummary', () => {
  it('shows the overall size, each object and the note', () => {
    render(<FileMeasurementSummary measurement={done} />)
    expect(screen.getByText('Measured 60.0 × 30.0 × 20.0 mm')).toBeInTheDocument()
    expect(screen.getByText('Body: 40.0 × 30.0 × 20.0 mm')).toBeInTheDocument()
    expect(screen.getByText(/2 objects/)).toBeInTheDocument()
  })

  it('says measuring while pending', () => {
    render(
      <FileMeasurementSummary
        measurement={{ ...done, length_mm: null, width_mm: null, height_mm: null, objects: [], note: null, status: 'pending' }}
      />,
    )
    expect(screen.getByText('Measuring…')).toBeInTheDocument()
  })

  it('shows why a file could not be measured', () => {
    render(
      <FileMeasurementSummary
        measurement={{ ...done, length_mm: null, width_mm: null, height_mm: null, objects: [], note: 'Not an STL file', status: 'failed' }}
      />,
    )
    expect(screen.getByText('Not an STL file')).toBeInTheDocument()
    expect(screen.queryByText(/Measured/)).not.toBeInTheDocument()
  })

  it('renders nothing for G-code', () => {
    const { container } = render(<FileMeasurementSummary measurement={null} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('knows when a file is still pending', () => {
    expect(anyMeasurementPending([{ measurement: done }])).toBe(false)
    expect(anyMeasurementPending([{ measurement: { ...done, status: 'pending' } }])).toBe(true)
  })
})
