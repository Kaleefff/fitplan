import AsyncStorage from '@react-native-async-storage/async-storage';
import { createContext, useEffect, useState, type ReactNode } from 'react';
import { Appearance, Platform, useColorScheme } from 'react-native';

import {
  colors,
  radius,
  spacing,
  typography,
  type ColorScheme,
  type ThemeColors,
} from '@/theme/tokens';

export type ThemePreference = 'system' | 'light' | 'dark';

const STORAGE_KEY = 'theme.preference';

export type AppTheme = {
  /** The scheme actually shown */
  scheme: ColorScheme;
  /** What the user picked in Settings */
  preference: ThemePreference;
  setPreference: (preference: ThemePreference) => void;
  colors: ThemeColors;
  spacing: typeof spacing;
  radius: typeof radius;
  typography: typeof typography;
};

export const ThemeContext = createContext<AppTheme | null>(null);

function isPreference(value: unknown): value is ThemePreference {
  return value === 'system' || value === 'light' || value === 'dark';
}

// Makes native UI (alerts, pickers, keyboard) follow the same choice.
// react-native-web has no setColorScheme; on web the scheme computed below is enough.
function applyToNative(preference: ThemePreference) {
  if (Platform.OS === 'web') {
    return;
  }
  Appearance.setColorScheme(preference === 'system' ? 'auto' : preference);
}

export function AppThemeProvider({ children }: { children: ReactNode }) {
  const systemScheme = useColorScheme();
  const [preference, setPreferenceState] = useState<ThemePreference>('system');
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    AsyncStorage.getItem(STORAGE_KEY)
      .then((stored) => {
        if (isPreference(stored)) {
          setPreferenceState(stored);
          applyToNative(stored);
        }
      })
      .catch(() => {
        // Unreadable storage: keep following the system
      })
      .finally(() => setLoaded(true));
  }, []);

  const setPreference = (next: ThemePreference) => {
    setPreferenceState(next);
    applyToNative(next);
    AsyncStorage.setItem(STORAGE_KEY, next).catch(() => {
      // Not saved: the choice still applies until the app restarts
    });
  };

  // Wait for the stored choice so the first frame already has the right colours
  if (!loaded) {
    return null;
  }

  const scheme: ColorScheme =
    preference === 'system' ? (systemScheme === 'dark' ? 'dark' : 'light') : preference;

  const value: AppTheme = {
    scheme,
    preference,
    setPreference,
    colors: colors[scheme],
    spacing,
    radius,
    typography,
  };

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}
