import AsyncStorage from "@react-native-async-storage/async-storage";
import type { KeyValueStore } from "@mandi/shared";

const PREFIX = "mandi.";

/**
 * The shared ApiClient expects synchronous storage. This keeps an in-memory copy,
 * hydrated from AsyncStorage before the app renders, and writes through.
 */
class HydratedStore implements KeyValueStore {
  private data = new Map<string, string>();

  async hydrate(): Promise<void> {
    const keys = (await AsyncStorage.getAllKeys()).filter((k) => k.startsWith(PREFIX));
    for (const [k, v] of await AsyncStorage.multiGet(keys)) if (v !== null) this.data.set(k, v);
  }

  get(key: string) {
    return this.data.get(key) ?? null;
  }

  set(key: string, value: string) {
    this.data.set(key, value);
    void AsyncStorage.setItem(key, value);
  }

  remove(key: string) {
    this.data.delete(key);
    void AsyncStorage.removeItem(key);
  }
}

export const store = new HydratedStore();

/** Offline cache for GET responses (last prices, meta). */
export async function cacheJson<T>(key: string, fetcher: () => Promise<T>): Promise<{ data: T; cached: boolean }> {
  const k = `${PREFIX}cache.${key}`;
  try {
    const data = await fetcher();
    void AsyncStorage.setItem(k, JSON.stringify(data));
    return { data, cached: false };
  } catch (err) {
    const raw = await AsyncStorage.getItem(k);
    if (raw) return { data: JSON.parse(raw) as T, cached: true };
    throw err;
  }
}
