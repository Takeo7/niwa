/**
 * jsdom polyfills required by Mantine components under test.
 * Loaded via ``vitest.config.ts``'s ``test.setupFiles``.
 */
import { vi } from 'vitest';

// @mantine/core's MantineProvider uses matchMedia to react to the
// prefers-color-scheme media query. jsdom doesn't ship it.
if (!window.matchMedia) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
}

// Mantine's ScrollArea / Popover / DatePicker rely on ResizeObserver.
if (!globalThis.ResizeObserver) {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}
