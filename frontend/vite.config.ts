import { defineConfig, loadEnv } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const outDir = env.VITE_BUILD_OUT || '../backend/static';

  return {
    plugins: [svelte()],
    build: {
      outDir,
      emptyOutDir: true,
    },
    server: {
      proxy: {
        '/chat': 'http://127.0.0.1:8000',
        '/placeholder': 'http://127.0.0.1:8000',
        '/sessions': 'http://127.0.0.1:8000',
        '/history': 'http://127.0.0.1:8000',
        '/health': 'http://127.0.0.1:8000',
      },
    },
  };
});
