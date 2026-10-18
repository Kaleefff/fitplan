import { Stack, ThemeProvider } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';

import { useAppTheme } from '@/hooks/use-app-theme';
import { navigationTheme } from '@/theme/navigation-theme';
import { AppThemeProvider } from '@/theme/theme-provider';

// Keep the splash screen until the saved theme has been read
SplashScreen.preventAutoHideAsync();

export default function RootLayout() {
  return (
    <AppThemeProvider>
      <RootNavigator />
    </AppThemeProvider>
  );
}

function RootNavigator() {
  const { scheme, colors } = useAppTheme();

  // Mounted only after AppThemeProvider has loaded the preference
  useEffect(() => {
    SplashScreen.hideAsync();
  }, []);

  return (
    <ThemeProvider value={navigationTheme(scheme, colors)}>
      <StatusBar style={scheme === 'dark' ? 'light' : 'dark'} />
      <Stack />
    </ThemeProvider>
  );
}
