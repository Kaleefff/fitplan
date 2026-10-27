import { Stack, ThemeProvider } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';

import { useSession, SessionProvider } from '@/auth/session';
import { ConnectionProblem } from '@/components/connection-problem';
import { useAppTheme } from '@/hooks/use-app-theme';
import { navigationTheme } from '@/theme/navigation-theme';
import { AppThemeProvider } from '@/theme/theme-provider';

// Keep the splash screen until the theme is read and the stored session is checked
SplashScreen.preventAutoHideAsync();

export default function RootLayout() {
  return (
    <AppThemeProvider>
      <SessionProvider>
        <RootNavigator />
      </SessionProvider>
    </AppThemeProvider>
  );
}

function RootNavigator() {
  const { scheme, colors } = useAppTheme();
  const { status } = useSession();

  useEffect(() => {
    if (status !== 'restoring') {
      SplashScreen.hideAsync();
    }
  }, [status]);

  if (status === 'restoring') {
    return null;
  }

  return (
    <ThemeProvider value={navigationTheme(scheme, colors)}>
      <StatusBar style={scheme === 'dark' ? 'light' : 'dark'} />
      {status === 'unreachable' ? (
        <ConnectionProblem />
      ) : (
        // Auth guard (M-03): each group exists only in its state. redirectTo names the start
        // screen of the new state; without it the router falls back to "/", which a signed-out
        // user has no screen for ("Unmatched Route" after signing out)
        <Stack>
          <Stack.Protected guard={status === 'signedOut'} redirectTo="/">
            <Stack.Screen name="(auth)" options={{ headerShown: false }} />
          </Stack.Protected>
          <Stack.Protected guard={status === 'signedIn'} redirectTo="/sign-in">
            {/* The tabs draw their own header */}
            <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
            <Stack.Screen name="settings" options={{ title: 'Settings' }} />
          </Stack.Protected>
        </Stack>
      )}
    </ThemeProvider>
  );
}
