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

  // First screen of the current state; a group that closes sends the user here
  const startScreen = status === 'signedOut' ? '/sign-in' : status === 'needsProfile' ? '/onboarding' : '/';

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
          <Stack.Protected guard={status === 'signedOut'} redirectTo={startScreen}>
            <Stack.Screen name="(auth)" options={{ headerShown: false }} />
          </Stack.Protected>
          <Stack.Protected guard={status === 'needsProfile'} redirectTo={startScreen}>
            <Stack.Screen name="onboarding" options={{ title: 'Set Up Your Profile' }} />
          </Stack.Protected>
          <Stack.Protected guard={status === 'signedIn'} redirectTo={startScreen}>
            {/* The tabs draw their own header */}
            <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
            <Stack.Screen name="settings" options={{ title: 'Settings' }} />
            <Stack.Screen name="edit-profile" options={{ title: 'Edit Profile' }} />
          </Stack.Protected>
        </Stack>
      )}
    </ThemeProvider>
  );
}
