import vue from '@vitejs/plugin-vue'
import { defineConfig, loadEnv } from 'vite'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const base = env.VITE_APP_BASE_URL || (mode === 'production' ? '/static/' : '/')
  return {
    base,
    plugins: [vue()],
  }
})
