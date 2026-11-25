/**
 * Retry an API call once when the connection was reset under it.
 *
 * Playwright's request context reuses keep-alive sockets. When the backend has
 * already closed an idle one, the next call on it fails with ECONNRESET or
 * "socket hang up" before the request reaches the server (seen once in the
 * e2e-slow-gate run, with 3 workers). That is a transport hiccup, not a test
 * result, so the call is sent once more on a fresh socket. Any other error,
 * and a second reset, still fails the test.
 *
 * No imports: `node --test e2e/connectionRetry.check.ts` checks it on its own.
 */

const CONNECTION_RESET = /ECONNRESET|socket hang up/i

/** Whether an error is a connection reset (and nothing else). */
export function isConnectionReset(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error)
  return CONNECTION_RESET.test(message)
}

/** Run `action`; if it fails with a connection reset, run it once more. */
export async function retryOnConnectionReset<T>(action: () => Promise<T>): Promise<T> {
  try {
    return await action()
  } catch (error) {
    if (!isConnectionReset(error)) throw error
    return action()
  }
}
