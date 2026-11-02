import { StyleSheet, View } from 'react-native';

import { AppText } from '@/components/app-text';
import { useAppTheme } from '@/hooks/use-app-theme';

type ProgressStepsProps = {
  /** 1-based */
  current: number;
  total: number;
  title: string;
};

// "Step 2 of 4" with a bar, for the profile wizard (Rys. 7.3)
export function ProgressSteps({ current, total, title }: ProgressStepsProps) {
  const { colors, radius, spacing } = useAppTheme();
  return (
    <View
      style={{ gap: spacing.sm }}
      accessibilityRole="progressbar"
      accessibilityValue={{ min: 1, max: total, now: current }}>
      <AppText variant="caption" color="textMuted">
        Step {current} of {total}
      </AppText>
      <AppText variant="headline">{title}</AppText>
      <View style={styles.row}>
        {Array.from({ length: total }, (_, index) => (
          <View
            key={index}
            style={[
              styles.segment,
              { borderRadius: radius.pill, backgroundColor: index < current ? colors.primary : colors.border },
            ]}
          />
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', gap: 6 },
  segment: { flex: 1, height: 6 },
});
