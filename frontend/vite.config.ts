import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const API_TARGET = process.env.VITE_API_TARGET || 'http://localhost:5000'

export default defineConfig({
  plugins: [react()],
  css: {
    preprocessorOptions: {
      scss: { api: 'modern-compiler' },
    },
  },
  server: {
    host: true, // bind 0.0.0.0 so the devcontainer/host can reach it
    port: 5173,
    proxy: {
      // The GraphQL API and the /files download stream both live on the backend.
      '/graphql': { target: API_TARGET, changeOrigin: true },
      '/files': { target: API_TARGET, changeOrigin: true },
    },
  },
})
