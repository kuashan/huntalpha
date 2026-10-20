import assert from 'node:assert/strict'
import { membershipExpiryText } from './membershipExpiry.mjs'
assert.equal(membershipExpiryText({ tier:'free' }), '')
assert.equal(membershipExpiryText({ tier:'pro', expires_at:null }), '长期有效')
assert.equal(membershipExpiryText({ tier:'pro', expires_at:'bogus' }), '—')
const shown = membershipExpiryText({tier:'pro',expires_at:'2026-11-17T07:00:00+00:00'})
assert.match(shown, /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/)
console.log('Membership display: PASS')
