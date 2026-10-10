const configuredBase = String(import.meta.env.VITE_API_BASE_URL || '').trim()

// Keep loopback only for local Vite development. Production builds use
// same-origin requests so the HTTPS reverse proxy serves API and SSE traffic.
export const API_BASE = (configuredBase || (import.meta.env.DEV ? 'http://127.0.0.1:8003' : '')).replace(/\/+$/, '')
