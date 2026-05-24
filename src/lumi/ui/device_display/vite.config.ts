import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import path from 'node:path';

// Build output lands inside the FastAPI static dir so the Python
// server can serve it directly without any proxy layer. The /device-display
// route maps to this directory's `index.html`.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Asset URLs in the built HTML get this prefix. The FastAPI app mounts
  // /device-display straight to the build output directory, so assets
  // resolve to /device-display/assets/... regardless of where on disk
  // the wheel lands.
  base: '/device-display/',
  build: {
    outDir: path.resolve(__dirname, '../web/static/device-display'),
    emptyOutDir: true,
    assetsDir: 'assets',
  },
  server: {
    // Dev server runs at :5173 by default. Use this when iterating on
    // the device display directly — FastAPI still serves the built
    // bundle for users.
    port: 5173,
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
});
