import { StyleSheet, View } from 'react-native';

import { useSession } from '@/auth/session';
import { AppText } from '@/components/app-text';
import { DailyTargetCard } from '@/components/daily-target-card';
import { MetricTile } from '@/components/metric-tile';
import { QuickActionTile } from '@/components/quick-action-tile';
import { Screen } from '@/components/screen';
import { MODULES } from '@/constants/modules';
import { useAppTheme } from '@/hooks/use-app-theme';
import { useNutritionTargets } from '@/hooks/use-nutrition-targets';
import { GOAL_OPTIONS, labelOf, LEVEL_OPTIONS } from '@/profile/options';

// Home (Rys. 7.5): greeting, profile tiles, daily target, Quick Actions
export default function HomeScreen() {
  const { spacing } = useAppTheme();
  const { user, profile } = useSession();
  const { state: targets, retry } = useNutritionTargets(profile?.profile_update);

  return (
    <Screen>
      <View style={{ gap: spacing.xs }}>
        <AppText variant="display">{user ? `Welcome back, ${user.name}!` : 'Welcome back!'}</AppText>
        <AppText color="textMuted">Your fitness journey continues</AppText>
      </View>

      {profile ? (
        <View style={[styles.grid, { gap: spacing.md }]}>
          <MetricTile
            icon="trending-up-outline"
            color="training"
            label="Current weight"
            value={`${profile.current_weight} kg`}
          />
          <MetricTile icon="flag-outline" color="diet" label="Goal" value={labelOf(GOAL_OPTIONS, profile.goal)} />
          <MetricTile
            icon="ribbon-outline"
            color="scanner"
            label="Training level"
            value={labelOf(LEVEL_OPTIONS, profile.experience_level)}
          />
          <MetricTile
            icon="calendar-outline"
            color="analytics"
            label="Activity level"
            value={`PAL ${profile.activity_level_pal}`}
          />
        </View>
      ) : null}

      <DailyTargetCard state={targets} onRetry={retry} />

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
