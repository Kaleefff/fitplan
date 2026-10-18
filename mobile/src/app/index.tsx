import { Stack } from 'expo-router';
import { StyleSheet, View } from 'react-native';

import { AppText } from '@/components/app-text';
import { Card } from '@/components/card';
import { Screen } from '@/components/screen';
import { ThemeSwitch } from '@/components/theme-switch';
import { useAppTheme } from '@/hooks/use-app-theme';
import type { ColorName } from '@/theme/tokens';

// Temporary preview of the theme; replaced by the Home tab in the navigation step
const MODULES: { label: string; color: ColorName; tint: ColorName }[] = [
  { label: 'Training Plan', color: 'training', tint: 'trainingTint' },
  { label: 'Diet Plan', color: 'diet', tint: 'dietTint' },
  { label: 'AI Food Scanner', color: 'scanner', tint: 'scannerTint' },
  { label: 'Analytics', color: 'analytics', tint: 'analyticsTint' },
];

const MACROS: { label: string; color: ColorName }[] = [
  { label: 'Cal', color: 'kcal' },
  { label: 'Protein', color: 'protein' },
  { label: 'Carbs', color: 'carbs' },
  { label: 'Fats', color: 'fat' },
];

export default function ThemePreview() {
  const { colors, radius, spacing, scheme } = useAppTheme();

  return (
    <Screen>
      <Stack.Screen options={{ title: 'FitPlan Pro' }} />

      <Card>
        <AppText variant="title">Appearance</AppText>
        <AppText color="textMuted">Now showing: {scheme}</AppText>
        <ThemeSwitch />
      </Card>

      <View style={[styles.grid, { gap: spacing.md }]}>
        {MODULES.map((module) => (
          <View
            key={module.label}
            style={[
              styles.tile,
              { backgroundColor: colors[module.tint], borderRadius: radius.lg, padding: spacing.lg },
            ]}>
            <View
              style={[styles.dot, { backgroundColor: colors[module.color], borderRadius: radius.sm }]}
            />
            <AppText variant="bodyStrong">{module.label}</AppText>
          </View>
        ))}
      </View>

      <Card>
        <AppText variant="title">Today&apos;s Totals</AppText>
        <View style={styles.row}>
          {MACROS.map((macro) => (
            <View key={macro.label} style={styles.macro}>
              <AppText variant="caption" color="textMuted">
                {macro.label}
              </AppText>
              <AppText variant="headline" color={macro.color}>
                0
              </AppText>
            </View>
          ))}
        </View>
      </Card>

      <Card>
        <AppText variant="display">Display 28</AppText>
        <AppText variant="headline">Headline 22</AppText>
        <AppText variant="title">Title 18</AppText>
        <AppText variant="bodyLarge">Body large 16</AppText>
        <AppText>Body 14</AppText>
        <AppText variant="caption" color="textMuted">
          Caption 12
        </AppText>
        <AppText color="danger">Error text</AppText>
      </Card>
    </Screen>
  );
}

const styles = StyleSheet.create({
  grid: { flexDirection: 'row', flexWrap: 'wrap' },
  // Two tiles per row at any screen width
  tile: { flexBasis: '47%', flexGrow: 1, gap: 8 },
  dot: { width: 40, height: 40 },
  row: { flexDirection: 'row', justifyContent: 'space-between' },
  macro: { alignItems: 'center' },
});
