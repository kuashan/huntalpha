import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// In local development, use relative /api URLs and proxy them to Django.
// This server-only setting is not embedded into production browser bundles.
export default defineConfig(({ command }) => ({
  base: command === 'build' ? '/static/' : '/',
  plugins: [vue()],
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8003',
        changeOrigin: true,
      },
    },
  },
}))
