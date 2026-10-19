import { StyleSheet, View } from 'react-native';

import { AppText } from '@/components/app-text';
import { QuickActionTile } from '@/components/quick-action-tile';
import { Screen } from '@/components/screen';
import { MODULES } from '@/constants/modules';
import { useAppTheme } from '@/hooks/use-app-theme';

// Home screen (Rys. 7.5); profile metrics are added once the API is connected
export default function HomeScreen() {
  const { spacing } = useAppTheme();

  return (
    <Screen>
      <View style={{ gap: spacing.xs }}>
        <AppText variant="display">Welcome back!</AppText>
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
