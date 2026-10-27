import { StyleSheet, View } from 'react-native';

import { useSession } from '@/auth/session';
import { AppText } from '@/components/app-text';
import { QuickActionTile } from '@/components/quick-action-tile';
import { Screen } from '@/components/screen';
import { MODULES } from '@/constants/modules';
import { useAppTheme } from '@/hooks/use-app-theme';

// Home (Rys. 7.5): greeting and Quick Actions; profile tiles come with the profile task (M-06)
export default function HomeScreen() {
  const { spacing } = useAppTheme();
  const { user } = useSession();

  return (
    <Screen>
      <View style={{ gap: spacing.xs }}>
        <AppText variant="display">{user ? `Welcome back, ${user.name}!` : 'Welcome back!'}</AppText>
        <AppText color="textMuted">Your fitness journey continues</AppText>
      </View>

      <AppText variant="title">Quick Actions</AppText>
      <View style={[styles.grid, { gap: spacing.md }]}>
        {MODULES.map((module) => (
          <QuickActionTile key={module.key} module={module} />
        ))}
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  grid: { flexDirection: 'row', flexWrap: 'wrap' },
});
