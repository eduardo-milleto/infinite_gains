import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

const apiTarget = process.env.VITE_API_PROXY_TARGET ?? 'http://localhost:8081';
const wsTarget = apiTarget.startsWith('https://')
  ? apiTarget.replace('https://', 'wss://')
  : apiTarget.replace('http://', 'ws://');

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        target: apiTarget,
        changeOrigin: true,
      },
      '/ws': {
        target: wsTarget,
        ws: true,
        changeOrigin: true,
      },
    },
  },
});
