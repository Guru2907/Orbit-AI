// Reads the `exp` claim from a JWT without verifying it — only the backend can verify
// tokens. This just avoids restoring a session that has obviously expired.
function decodePayload(token) {
  const parts = typeof token === 'string' ? token.split('.') : []
  if (parts.length !== 3) return null
  try {
    const base64 = parts[1].replace(/-/g, '+').replace(/_/g, '/')
    const padded = base64 + '='.repeat((4 - (base64.length % 4)) % 4)
    const payload = JSON.parse(atob(padded))
    return payload && typeof payload === 'object' && !Array.isArray(payload) ? payload : null
  } catch {
    return null
  }
}

export function isTokenExpired(token, nowMs = Date.now()) {
  const payload = decodePayload(token)
  if (!payload) return true
  if (typeof payload.exp !== 'number') return false
  return payload.exp * 1000 <= nowMs
}
