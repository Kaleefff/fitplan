import { router } from 'expo-router';
import { useState } from 'react';

import { useSession } from '@/auth/session';
import { AppText } from '@/components/app-text';
import { Button } from '@/components/button';
import { Card } from '@/components/card';
import { Screen } from '@/components/screen';
import { ThemeSwitch } from '@/components/theme-switch';

// Opened from the gear in the header; account and reminders are added in later tasks
export default function SettingsScreen() {
  const { user, signOut } = useSession();
  const [signingOut, setSigningOut] = useState(false);

  async function handleSignOut() {
    setSigningOut(true);
    await signOut(); // the router then shows the sign-in screen
  }

  return (
    <Screen>
      <Card>
        <AppText variant="title">Profile</AppText>
        <AppText color="textMuted">Your body data, goal, training settings, injuries and allergies.</AppText>
        <Button title="Edit profile" variant="secondary" onPress={() => router.push('/edit-profile')} />
      </Card>

      <Card>
        <AppText variant="title">Appearance</AppText>
        <AppText color="textMuted">System follows the dark mode setting of your phone.</AppText>
        <ThemeSwitch />
      </Card>

      <Card>
        <AppText variant="title">Account</AppText>
        {user ? (
          <AppText color="textMuted">
            {user.name} {user.surname} · {user.email}
          </AppText>
        ) : null}
        <Button title="Sign out" variant="secondary" onPress={handleSignOut} loading={signingOut} />
      </Card>
    </Screen>
  );
}
