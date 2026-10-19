import { DarkTheme, DefaultTheme, type Theme } from 'expo-router';

import type { ColorScheme, ThemeColors } from '@/theme/tokens';

// Gives headers and tab bars the app colours instead of React Navigation's defaults
export function navigationTheme(scheme: ColorScheme, colors: ThemeColors): Theme {
  const base = scheme === 'dark' ? DarkTheme : DefaultTheme;
  return {
    ...base,
    colors: {
      ...base.colors,
      primary: colors.primary,
      background: colors.background,
      card: colors.surface,
      text: colors.text,
      border: colors.border,
      notification: colors.danger,
    },
  };
}
