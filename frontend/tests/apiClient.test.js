// Offline tests for src/apiClient.js — run with `npm test` (Node's built-in test runner).
// Response bodies below were captured from the real FastAPI backend via its offline test client.
import { test } from 'node:test'
import assert from 'node:assert/strict'

import { ApiError, MESSAGES, isAuthError, messageFromDetail, parseResponse, request } from '../src/apiClient.js'

function jsonResponse(status, body) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function textResponse(status, text, contentType = 'text/plain; charset=utf-8') {
  return new Response(text, { status, headers: { 'Content-Type': contentType } })
}

async function rejection(promise) {
  try {
    await promise
  } catch (err) {
    return err
  }
  assert.fail('expected the promise to reject')
}

// --- success ------------------------------------------------------------------

test('returns parsed JSON for a successful response', async () => {
  const data = await parseResponse(jsonResponse(200, { answer: 'Hi', sources: ['pricing.md'] }))
  assert.deepEqual(data, { answer: 'Hi', sources: ['pricing.md'] })
})

test('a successful but non-JSON response becomes a generic ApiError, not a SyntaxError', async () => {
  const err = await rejection(parseResponse(textResponse(200, '<html>oops</html>', 'text/html')))
  assert.ok(err instanceof ApiError)
  assert.equal(err.message, MESSAGES.generic)
})

// --- non-JSON errors ------------------------------------------------------------

test('plain-text 500 (FastAPI default) gives a friendly message', async () => {
  const err = await rejection(parseResponse(textResponse(500, 'Internal Server Error')))
  assert.ok(err instanceof ApiError)
  assert.equal(err.status, 500)
  assert.equal(err.message, MESSAGES.server)
  assert.doesNotMatch(err.message, /Unexpected token|JSON/)
})

test('HTML 502 from a proxy gives the server message', async () => {
  const err = await rejection(parseResponse(textResponse(502, '<html><body>Bad Gateway</body></html>', 'text/html')))
  assert.equal(err.status, 502)
  assert.equal(err.message, MESSAGES.server)
})

test('non-JSON 503 still gives the unavailable message', async () => {
  const err = await rejection(parseResponse(textResponse(503, 'Service Unavailable')))
  assert.equal(err.message, MESSAGES.unavailable)
})

test('empty error body falls back by status', async () => {
  const err = await rejection(parseResponse(new Response(null, { status: 504 })))
  assert.equal(err.status, 504)
  assert.equal(err.message, MESSAGES.server)
})

test('JSON error without a usable detail falls back by status', async () => {
  const err = await rejection(parseResponse(jsonResponse(400, { error: 'x' })))
  assert.equal(err.message, MESSAGES.validation)
})

// --- 503 / 401 with JSON detail -------------------------------------------------

test('503 from /chat shows the backend detail', async () => {
  const err = await rejection(
    parseResponse(jsonResponse(503, { detail: 'Orbit is temporarily unavailable. Please try again.' })),
  )
  assert.equal(err.status, 503)
  assert.equal(err.message, 'Orbit is temporarily unavailable. Please try again.')
  assert.equal(isAuthError(err), false)
})

test('401 from /login keeps the backend message', async () => {
  const err = await rejection(parseResponse(jsonResponse(401, { detail: 'Invalid email or password' })))
  assert.equal(err.message, 'Invalid email or password')
  assert.equal(isAuthError(err), true)
})

test('401 with expired token is detected as an auth error', async () => {
  const err = await rejection(parseResponse(jsonResponse(401, { detail: 'Invalid or expired token' })))
  assert.equal(isAuthError(err), true)
})

test('401 without a body falls back to the session-expired message', async () => {
  const err = await rejection(parseResponse(new Response(null, { status: 401 })))
  assert.equal(err.message, MESSAGES.sessionExpired)
})

// --- 422 validation -------------------------------------------------------------

test('422 shows the readable validation message without the "Value error" prefix', async () => {
  const body = {
    detail: [{
      type: 'value_error', loc: ['body', 'password'],
      msg: 'Value error, Password must be at least 8 characters', input: 'short', ctx: { error: {} },
    }],
  }
  const err = await rejection(parseResponse(jsonResponse(422, body)))
  assert.equal(err.status, 422)
  assert.equal(err.message, 'Password must be at least 8 characters')
  assert.equal(isAuthError(err), false)
})

test('422 with several errors joins them', async () => {
  const body = {
    detail: [
      { type: 'value_error', loc: ['body', 'email'], msg: 'Value error, Enter a valid email address', input: 'nope' },
      { type: 'value_error', loc: ['body', 'password'], msg: 'Value error, Password must be at most 72 bytes', input: 'aaa' },
    ],
  }
  const err = await rejection(parseResponse(jsonResponse(422, body)))
  assert.equal(err.message, 'Enter a valid email address Password must be at most 72 bytes')
})

test('422 in the sanitized backend shape (no input/ctx) still gives readable messages', async () => {
  const body = {
    detail: [
      { type: 'value_error', loc: ['body', 'password'], msg: 'Value error, Password must be at least 8 characters' },
      { type: 'missing', loc: ['body', 'email'], msg: 'Field required' },
    ],
  }
  const err = await rejection(parseResponse(jsonResponse(422, body)))
  assert.equal(err.status, 422)
  assert.equal(err.message, 'Password must be at least 8 characters email: Field required')
})

test('422 for a missing field names the field', async () => {
  const body = { detail: [{ type: 'missing', loc: ['body', 'password'], msg: 'Field required', input: {} }] }
  const err = await rejection(parseResponse(jsonResponse(422, body)))
  assert.equal(err.message, 'password: Field required')
})

test('422 messages never include the submitted input', async () => {
  const body = { detail: [{ type: 'value_error', loc: ['body', 'password'], msg: 'Value error, Too short', input: 'hunter2' }] }
  const err = await rejection(parseResponse(jsonResponse(422, body)))
  assert.doesNotMatch(err.message, /hunter2/)
})

test('messageFromDetail ignores unusable shapes', () => {
  assert.equal(messageFromDetail(undefined), null)
  assert.equal(messageFromDetail(''), null)
  assert.equal(messageFromDetail([{ nope: true }]), null)
  assert.equal(messageFromDetail({ msg: 'x' }), null)
})

// --- network failures -----------------------------------------------------------

test('fetch rejection (offline, DNS, CORS) becomes a network ApiError', async () => {
  const failingFetch = async () => { throw new TypeError('Failed to fetch') }
  const err = await rejection(request('http://example.invalid/chat', {}, failingFetch))
  assert.ok(err instanceof ApiError)
  assert.equal(err.status, 0)
  assert.equal(err.message, MESSAGES.network)
  assert.equal(isAuthError(err), false)
})

test('request passes url and options through to fetch', async () => {
  const calls = []
  const fakeFetch = async (url, options) => {
    calls.push([url, options])
    return jsonResponse(200, { ok: true })
  }
  const options = { method: 'POST', body: '{}' }
  assert.deepEqual(await request('http://api/chat', options, fakeFetch), { ok: true })
  assert.deepEqual(calls, [['http://api/chat', options]])
})

test('isAuthError is false for plain Errors', () => {
  const err = new Error('x')
  err.status = 401
  assert.equal(isAuthError(err), false)
})
