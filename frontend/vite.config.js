import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// GlucoSentry dashboard dev server.
// API_BASE is read at runtime from VITE_API_BASE (see .env.example); this file
// only needs to know the dev port so it stays predictable across sessions.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
  },
  test: {
    environment: 'jsdom',
  },
})
