import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  base: '/static/app/',
  root: 'frontend',
  build: {
    outDir: '../english_overlap/static/app',
    emptyOutDir: true,
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8765',
      '/static': 'http://127.0.0.1:8765',
      '/app-config': 'http://127.0.0.1:8765',
      '/generate': 'http://127.0.0.1:8765',
      '/saved': 'http://127.0.0.1:8765',
      '/saved-data': 'http://127.0.0.1:8765',
      '/saved-audio': 'http://127.0.0.1:8765',
    },
  },
});
