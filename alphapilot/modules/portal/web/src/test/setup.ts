import "@testing-library/jest-dom";

// jsdom on an opaque origin does not expose Web Storage; provide a minimal
// in-memory localStorage so components that persist UI preferences can run.
if (typeof globalThis.localStorage === "undefined") {
  class MemoryStorage {
    private store = new Map<string, string>();
    getItem(key: string): string | null {
      return this.store.has(key) ? (this.store.get(key) as string) : null;
    }
    setItem(key: string, value: string): void {
      this.store.set(key, String(value));
    }
    removeItem(key: string): void {
      this.store.delete(key);
    }
    clear(): void {
      this.store.clear();
    }
    key(index: number): string | null {
      return Array.from(this.store.keys())[index] ?? null;
    }
    get length(): number {
      return this.store.size;
    }
  }
  Object.defineProperty(globalThis, "localStorage", {
    value: new MemoryStorage(),
    writable: true,
  });
}
