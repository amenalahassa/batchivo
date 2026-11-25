/**
 * Unit check for connectionRetry.ts (not a Playwright spec: the name keeps it
 * out of every project). Run with:
 *
 *   node --test e2e/connectionRetry.check.ts
 */

import assert from 'node:assert/strict'
import { test } from 'node:test'

import { isConnectionReset, retryOnConnectionReset } from './connectionRetry.ts'

function failing(message: string, times: number) {
  let calls = 0
  const action = async () => {
    calls += 1
    if (calls <= times) throw new Error(message)
    return 'ok'
  }
  return { action, calls: () => calls }
}

test('recognises a connection reset and nothing else', () => {
  assert.equal(isConnectionReset(new Error('apiRequestContext.get: read ECONNRESET')), true)
  assert.equal(isConnectionReset(new Error('apiRequestContext.post: socket hang up')), true)
  assert.equal(isConnectionReset(new Error('GET /api/v1/x answered HTTP 500: boom')), false)
  assert.equal(isConnectionReset(new Error('connect ECONNREFUSED 127.0.0.1:8000')), false)
})

test('a call that succeeds runs once', async () => {
  const call = failing('unused', 0)
  assert.equal(await retryOnConnectionReset(call.action), 'ok')
  assert.equal(call.calls(), 1)
})

test('one reset is retried once and succeeds', async () => {
  const call = failing('read ECONNRESET', 1)
  assert.equal(await retryOnConnectionReset(call.action), 'ok')
  assert.equal(call.calls(), 2)
})

test('a second reset still fails', async () => {
  const call = failing('socket hang up', 2)
  await assert.rejects(retryOnConnectionReset(call.action), /socket hang up/)
  assert.equal(call.calls(), 2)
})

test('any other error fails at once, without a retry', async () => {
  const call = failing('POST /api/v1/x answered HTTP 422: invalid', 1)
  await assert.rejects(retryOnConnectionReset(call.action), /HTTP 422/)
  assert.equal(call.calls(), 1)
})
