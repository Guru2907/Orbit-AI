// Offline tests for src/session.js — run with `npm test`.
import { test } from 'node:test'
import assert from 'node:assert/strict'

import { isTokenExpired } from '../src/session.js'

const NOW = Date.UTC(2026, 9, 16, 12, 0, 0)

function base64url(value) {
  return Buffer.from(JSON.stringify(value)).toString('base64url')
}

function makeToken(payload) {
  return `${base64url({ alg: 'HS256', typ: 'JWT' })}.${base64url(payload)}.signature`
}

test('token expiring in the future is not expired', () => {
  assert.equal(isTokenExpired(makeToken({ sub: 'a@x.com', exp: NOW / 1000 + 3600 }), NOW), false)
})

test('token whose exp has passed is expired', () => {
  assert.equal(isTokenExpired(makeToken({ sub: 'a@x.com', exp: NOW / 1000 - 1 }), NOW), true)
})

test('token expiring exactly now is expired', () => {
  assert.equal(isTokenExpired(makeToken({ sub: 'a@x.com', exp: NOW / 1000 }), NOW), true)
})

test('token without exp is left for the backend to judge', () => {
  assert.equal(isTokenExpired(makeToken({ sub: 'a@x.com' }), NOW), false)
})

test('payload using base64url-only characters decodes', () => {
  // "?>" style bytes produce "-" / "_" in base64url.
  const token = makeToken({ sub: '??>>~~', exp: NOW / 1000 + 60 })
  assert.match(token.split('.')[1], /[-_]/)
  assert.equal(isTokenExpired(token, NOW), false)
})

test('malformed tokens are treated as expired', () => {
  const malformed = [
    null, undefined, '', 'abc', 'a.b', 'a.!!!.c', 'a.b.c.d',
    `x.${base64url('just a string')}.y`,
    `x.${base64url(42)}.y`,
    `x.${base64url([1, 2])}.y`,
    `x.${base64url(null)}.y`,
  ]
  for (const token of malformed) {
    assert.equal(isTokenExpired(token, NOW), true, String(token))
  }
})
