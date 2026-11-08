import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';

const here = (file) => fileURLToPath(new URL(file, import.meta.url));

export default defineConfig({
  plugins: [
    react(),
    {
      // MSAL's redirect bridge page must never be cached.
      name: 'no-store-redirect-bridge',
      configureServer(server) {
        server.middlewares.use((req, res, next) => {
          if (req.url?.startsWith('/redirect.html')) res.setHeader('Cache-Control', 'no-store');
          next();
        });
      },
    },
  ],
  server: {
    port: 5243,
    strictPort: true,
    // Local dev: VITE_API_BASE_URL is unset, so the app calls /api/... on 5243 and Vite forwards it
    // to the FastAPI backend. In production the app calls the Container App URL directly.
    proxy: { '/api': 'http://localhost:8000' },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        main: here('./index.html'),
        redirect: here('./redirect.html'), // MSAL v5 redirect bridge
      },
    },
  },
});
