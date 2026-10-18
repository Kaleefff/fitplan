import { useContext } from 'react';

import { ThemeContext, type AppTheme } from '@/theme/theme-provider';

export function useAppTheme(): AppTheme {
  const theme = useContext(ThemeContext);
  if (!theme) {
    throw new Error('useAppTheme must be used inside AppThemeProvider');
  }
  return theme;
}
