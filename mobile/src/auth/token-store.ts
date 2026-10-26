import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

const REFRESH_TOKEN_KEY = 'auth.refreshToken';

export type TokenStore = {
  getRefreshToken: () => Promise<string | null>;
  setRefreshToken: (token: string) => Promise<void>;
  clear: () => Promise<void>;
};

// Android Keystore / iOS Keychain through expo-secure-store (NFR-SEC)
const secureStore: TokenStore = {
  getRefreshToken: () => SecureStore.getItemAsync(REFRESH_TOKEN_KEY),
  setRefreshToken: (token) => SecureStore.setItemAsync(REFRESH_TOKEN_KEY, token),
  clear: () => SecureStore.deleteItemAsync(REFRESH_TOKEN_KEY),
};

// expo-secure-store has no web implementation; the web build is only a development preview
const webStore: TokenStore = {
  getRefreshToken: async () => globalThis.localStorage?.getItem(REFRESH_TOKEN_KEY) ?? null,
  setRefreshToken: async (token) => globalThis.localStorage?.setItem(REFRESH_TOKEN_KEY, token),
  clear: async () => globalThis.localStorage?.removeItem(REFRESH_TOKEN_KEY),
};

export const tokenStore: TokenStore = Platform.OS === 'web' ? webStore : secureStore;
