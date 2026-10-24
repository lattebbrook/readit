import '@testing-library/jest-dom/vitest';

/**
 * Recent Node versions expose their own `localStorage` global that shadows
 * jsdom's and silently drops writes when no backing file is configured.
 * Install a plain in-memory implementation so storage behaves predictably.
 */
function createMemoryStorage(): Storage {
  const entries = new Map<string, string>();
  return {
    get length() {
      return entries.size;
    },
    key: (index: number) => [...entries.keys()][index] ?? null,
    getItem: (key: string) => (entries.has(key) ? entries.get(key)! : null),
    setItem: (key: string, value: string) => void entries.set(key, String(value)),
    removeItem: (key: string) => void entries.delete(key),
    clear: () => entries.clear(),
  } as Storage;
}

const storage = createMemoryStorage();
for (const target of [globalThis, window]) {
  Object.defineProperty(target, 'localStorage', {
    value: storage,
    writable: true,
    configurable: true,
  });
}
