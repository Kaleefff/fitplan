import AsyncStorage from '@react-native-async-storage/async-storage';

export type DraftStore = {
  get: () => Promise<number | null>;
  set: (planId: number) => Promise<void>;
  clear: () => Promise<void>;
};

/**
 * Remembers the id of the last generated draft plan: the API has no "current draft"
 * endpoint, so without it a draft is lost when the app restarts. A stale id is harmless:
 * the plan then answers 404 or is no longer a draft, and the screen forgets it.
 */
export function createDraftStore(key: string): DraftStore {
  return {
    async get() {
      try {
        const value = await AsyncStorage.getItem(key);
        return value === null ? null : Number(value);
      } catch {
        return null;
      }
    },
    async set(planId) {
      await AsyncStorage.setItem(key, String(planId)).catch(() => undefined);
    },
    async clear() {
      await AsyncStorage.removeItem(key).catch(() => undefined);
    },
  };
}
