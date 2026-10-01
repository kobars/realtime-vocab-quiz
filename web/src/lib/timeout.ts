// AI-ASSISTED: a deadline for an HTTP request, headers and body together, that holds even when the request ignores its abort signal.

/**
 * Runs `request` with a signal that aborts after `timeoutMs`. At that moment the result rejects with a
 * `TimeoutError`, even when the request ignores the signal and never settles.
 */
export async function withTimeout<T>(timeoutMs: number, request: (signal: AbortSignal) => Promise<T>): Promise<T> {
  const controller = new AbortController()
  let timer: ReturnType<typeof setTimeout> | undefined
  const timedOut = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      const error = new DOMException(`no reply within ${timeoutMs} ms`, 'TimeoutError')
      controller.abort(error)
      reject(error)
    }, timeoutMs)
  })
  try {
    return await Promise.race([request(controller.signal), timedOut])
  } finally {
    clearTimeout(timer)
  }
}
