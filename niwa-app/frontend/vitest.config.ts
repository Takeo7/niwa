import { defineConfig } from 'vitest/config';
import path from 'path';

// Minimal vitest setup. Uses jsdom so tests that poke at
// ``window.location`` (e.g. the reload-loop guard in
// ``src/shared/api/client.ts``) have a DOM available.
export default defineConfig({
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
  },
});
