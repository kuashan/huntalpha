/**
 * All deployed API calls stay on the current website origin.
 *
 * Only local Vite development may override the backend through VITE_API_BASE_URL.
 * With no override, Vite proxies /api to the local Django server.
 * Production builds must never point a visitor's browser at localhost.
 */
export const API_BASE = import.meta.env.PROD
  ? ''
  : (import.meta.env.VITE_API_BASE_URL || '').replace(/\/+$/, '')
