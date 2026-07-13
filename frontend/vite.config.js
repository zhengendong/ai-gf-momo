import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig(({ mode }) => {
  // Read the repository-level .env so the development proxy always follows
  // the same SERVER_PORT as the backend launcher.
  const env = loadEnv(mode, '..', 'SERVER_')
  const backendPort = env.SERVER_PORT || '8001'
  const httpTarget = `http://127.0.0.1:${backendPort}`
  const wsTarget = `ws://127.0.0.1:${backendPort}`

  return {
    plugins: [vue()],
    server: {
      host: '0.0.0.0',
      port: 5173,
      proxy: {
        '/api': {
          target: httpTarget,
          changeOrigin: true
        },
        '/ws': {
          target: wsTarget,
          ws: true
        },
        '/static': {
          target: httpTarget,
          changeOrigin: true
        }
      }
    }
  }
})
