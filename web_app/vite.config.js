import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    allowedHosts: ['b397-2409-40e1-1000-b2b8-81dd-8f4-c592-ce6c.ngrok-free.app']
  }
})