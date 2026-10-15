// @vitest-environment jsdom
import { describe, it, expect, afterEach, vi } from 'vitest'
import { render, screen, cleanup, waitFor } from '@testing-library/react'

const history = { checks: [], next_check_scheduled: null }
vi.mock('../lib/api.js', () => ({
  api: { getFootHistory: vi.fn(() => Promise.resolve(history)), requestFootCheck: vi.fn() },
  ApiError: class extends Error {},
}))

const { default: FootCheck } = await import('./FootCheck.jsx')

afterEach(() => {
  cleanup()
  history.checks = []
})

const check = (over = {}) => ({
  id: 1, timestamp: 1, t_left: 30.1, t_right: 32.9, delta_t: 2.8, valid: true, elevated: true,
  next_check_scheduled: null, ...over,
})

describe('FootCheck', () => {
  it('renders an empty history deliberately', async () => {
    render(<FootCheck liveResult={null} status={null} />)
    expect(await screen.findByText('No foot checks yet')).toBeTruthy()
    expect(screen.getByText('Simulated')).toBeTruthy()
  })

  it('shows the backend elevated flag rather than judging delta_t itself', async () => {
    history.checks = [check(), check({ id: 2, delta_t: 2.8, elevated: false }), check({ id: 3, valid: false, elevated: null })]
    render(<FootCheck liveResult={null} status={{ aux_source: 'ble', aux_connected: true }} />)
    await waitFor(() => expect(screen.getByText('Elevated')).toBeTruthy())
    expect(screen.getByText('Normal')).toBeTruthy()
    expect(screen.getByText('Invalid')).toBeTruthy()
    expect(screen.getByText('Connected (BLE)')).toBeTruthy()
  })

  it('disables the request button when the simulated module is set offline', async () => {
    render(<FootCheck liveResult={null} status={{ aux_source: 'simulator', aux_connected: false }} />)
    expect(await screen.findByText(/set to offline/)).toBeTruthy()
    expect(screen.getByRole('button', { name: /Request check now/ }).disabled).toBe(true)
  })

  it('disables the request button when the real module is out of range', async () => {
    render(<FootCheck liveResult={null} status={{ aux_source: 'ble', aux_connected: false }} />)
    expect(await screen.findByText(/Not found/)).toBeTruthy()
    expect(screen.getByRole('button', { name: /Request check now/ }).disabled).toBe(true)
  })
})
