// Response/error handling for the backend API. Kept free of Vite-only code
// (import.meta.env) so it can be tested directly with `node --test`.

export const MESSAGES = {
  generic: 'Something went wrong. Please try again.',
  network: "Can't reach Orbit right now. Check your connection and try again.",
  validation: 'Please check your details and try again.',
  unavailable: 'Orbit is temporarily unavailable. Please try again.',
  server: 'Orbit ran into a problem. Please try again.',
  sessionExpired: 'Your session has expired. Please log in again.',
  rateLimited: 'Too many requests. Please try again later.',
}

export class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export function isAuthError(err) {
  return err instanceof ApiError && err.status === 401
}

// FastAPI validation errors (422) arrive as a list:
// [{ loc: ['body', 'password'], msg: 'Value error, Password must be at least 8 characters' }, ...]
function validationItemMessage(item) {
  if (!item || typeof item.msg !== 'string') return null
  if (item.msg.startsWith('Value error, ')) return item.msg.slice('Value error, '.length)
  const field = Array.isArray(item.loc) ? item.loc[item.loc.length - 1] : null
  return typeof field === 'string' ? `${field}: ${item.msg}` : item.msg
}

export function messageFromDetail(detail) {
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail)) {
    const messages = [...new Set(detail.map(validationItemMessage).filter(Boolean))]
    return messages.length ? messages.join(' ') : null
  }
  return null
}

function fallbackMessage(status) {
  if (status === 401) return MESSAGES.sessionExpired
  if (status === 422 || status === 400) return MESSAGES.validation
  if (status === 429) return MESSAGES.rateLimited
  if (status === 503) return MESSAGES.unavailable
  if (status >= 500) return MESSAGES.server
  return MESSAGES.generic
}

// Reads the body as text first, so non-JSON responses (a plain-text 500, a proxy's
// HTML error page, an empty body) never surface as a JSON parse error.
export async function parseResponse(res) {
  let data = null
  try {
    const text = await res.text()
    data = text ? JSON.parse(text) : null
  } catch {
    data = null
  }

  if (res.ok) {
    if (data === null) throw new ApiError(MESSAGES.generic, res.status)
    return data
  }
  throw new ApiError(messageFromDetail(data?.detail) || fallbackMessage(res.status), res.status)
}

export async function request(url, options, fetchImpl = fetch) {
  let res
  try {
    res = await fetchImpl(url, options)
  } catch {
    // fetch rejects on network failure, DNS errors, and CORS rejections.
    throw new ApiError(MESSAGES.network, 0)
  }
  return parseResponse(res)
}
