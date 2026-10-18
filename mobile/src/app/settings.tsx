import { AppText } from '@/components/app-text';
import { Card } from '@/components/card';
import { Screen } from '@/components/screen';
import { ThemeSwitch } from '@/components/theme-switch';

// Opened from the gear in the header; profile, account and reminders are added in later tasks
export default function SettingsScreen() {
  return (
    <Screen>
      <Card>
        <AppText variant="title">Appearance</AppText>
        <AppText color="textMuted">System follows the dark mode setting of your phone.</AppText>
        <ThemeSwitch />
      </Card>
    </Screen>
  );
}
