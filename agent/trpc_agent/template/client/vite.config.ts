import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import tsconfigPaths from 'vite-tsconfig-paths';
import { viteEnvs } from 'vite-envs';

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    tsconfigPaths(),
    viteEnvs({
      declarationFile: '.env.example',
    }),
  ],
  server: {
    // Allow connections from outside the container
    host: '0.0.0.0',
    allowedHosts: ['debughost', 'localhost'],
    proxy: {
      '/api': {
        target: 'http://localhost:2022',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
});
