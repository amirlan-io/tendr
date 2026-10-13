/** Private browser data is never shared across authenticated identities. */
let accountId: string | null = null;
let generation = 0;
const privateKey = (key: string) => /^tendr_(?:history|saved_lots|documents|ai_|active_|last_|assistant_|bid_|lot_cache)/.test(key);

export function storageGeneration(): number { return generation; }
export function assertStorageGeneration(expected: number): void {
  if (expected !== generation) throw new Error("Account changed during request");
}
export function setAccountStorageScope(id: string | null): void {
  if (id === accountId) return;
  const oldPrefix = accountId ? `tendr:user:${accountId}:` : null;
  if (typeof window !== "undefined") {
    try {
      for (const key of Object.keys(window.localStorage)) {
        if (privateKey(key) || (oldPrefix && key.startsWith(oldPrefix))) window.localStorage.removeItem(key);
      }
    } catch { /* inaccessible storage must not prevent logout */ }
  }
  accountId = id;
  generation += 1;
}
function scoped(key: string): string { return accountId ? `tendr:user:${accountId}:${key}` : key; }
function keys(): string[] {
  const prefix = accountId ? `tendr:user:${accountId}:` : null;
  return Object.keys(window.localStorage)
    .filter((key) => prefix ? key.startsWith(prefix) : privateKey(key))
    .map((key) => prefix ? key.slice(prefix.length) : key);
}
export const accountLocalStorage: Storage = {
  get length() { return keys().length; },
  key(index) { return keys()[index] ?? null; },
  getItem(key) { return window.localStorage.getItem(scoped(key)); },
  setItem(key, value) { window.localStorage.setItem(scoped(key), value); },
  removeItem(key) { window.localStorage.removeItem(scoped(key)); },
  clear() { keys().forEach((key) => window.localStorage.removeItem(scoped(key))); },
};
