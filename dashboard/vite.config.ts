import { defineConfig } from 'vitest/config';
import { loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_');
  return {
    plugins: [react()],
    server: {
      proxy: {
        '/v1-api': {
          target: env.VITE_V1_PROXY_TARGET || 'http://v1-transport:8012',
          changeOrigin: true,
          rewrite: path => path.replace(/^\/v1-api/, ''),
        },
      },
    },
    test: { environment: 'jsdom', setupFiles: ['./src/testSetup.ts'], clearMocks: true },
  };
});
