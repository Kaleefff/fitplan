// 10.0.2.2 is the host machine as seen from the Android emulator
const DEFAULT_API_URL = 'http://10.0.2.2:8000/api/v1';

export const config = {
  /**
   * Backend base URL including `/api/v1`, from `EXPO_PUBLIC_API_URL` in `mobile/.env`.
   * Expo inlines EXPO_PUBLIC_* variables when bundling, so restart `npx expo start` after a change.
   */
  apiUrl: (process.env.EXPO_PUBLIC_API_URL ?? DEFAULT_API_URL).replace(/\/+$/, ''),
};
