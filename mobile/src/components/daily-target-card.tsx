import { ActivityIndicator, StyleSheet, View } from 'react-native';

import { AppText } from '@/components/app-text';
import { Button } from '@/components/button';
import { Card } from '@/components/card';
import type { TargetsState } from '@/hooks/use-nutrition-targets';
import { useAppTheme } from '@/hooks/use-app-theme';
import type { ColorName } from '@/theme/tokens';

type DailyTargetCardProps = {
  state: TargetsState;
  onRetry: () => void;
};

function Macro({ label, grams, color }: { label: string; grams: number; color: ColorName }) {
  return (
    <View style={styles.macro} accessible accessibilityLabel={`${label} ${Math.round(grams)} grams`}>
      <AppText variant="caption" color="textMuted">
        {label}
      </AppText>
      <AppText variant="title" color={color}>
        {Math.round(grams)} g
      </AppText>
    </View>
  );
}

// Calorie target and macros of the profile goal (FR-P4, FR-P5), colours as the diet mockup (Rys. 7.8)
export function DailyTargetCard({ state, onRetry }: DailyTargetCardProps) {
  const { spacing } = useAppTheme();

  if (state.status === 'unavailable') {
    return null;
  }

  return (
    <Card style={{ gap: spacing.md }}>
      <AppText variant="title">Daily target</AppText>
      {state.status === 'loading' ? <ActivityIndicator accessibilityLabel="Loading daily target" /> : null}
      {state.status === 'error' ? (
        <>
          <AppText color="textMuted">{state.message}</AppText>
          <Button title="Try again" variant="secondary" onPress={onRetry} />
        </>
      ) : null}
      {state.status === 'ready' ? (
        <>
          <View style={styles.kcalRow}>
            <AppText variant="display" color="kcal">
              {state.targets.target_kcal}
            </AppText>
            <AppText color="textMuted"> kcal / day</AppText>
          </View>
          <AppText variant="caption" color="textMuted">
            Your energy need (TDEE) is {state.targets.tdee} kcal
          </AppText>
          <View style={styles.macros}>
            <Macro label="Protein" grams={state.targets.protein_g} color="protein" />
            <Macro label="Carbs" grams={state.targets.carbs_g} color="carbs" />
            <Macro label="Fats" grams={state.targets.fat_g} color="fat" />
          </View>
        </>
      ) : null}
    </Card>
  );
}

const styles = StyleSheet.create({
  kcalRow: { flexDirection: 'row', alignItems: 'baseline' },
  macros: { flexDirection: 'row', justifyContent: 'space-between' },
  macro: { alignItems: 'center', flex: 1 },
});
