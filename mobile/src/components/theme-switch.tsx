import { Pressable, StyleSheet, View } from 'react-native';

import { AppText } from '@/components/app-text';
import { useAppTheme } from '@/hooks/use-app-theme';
import type { ThemePreference } from '@/theme/theme-provider';
import { minTouchSize } from '@/theme/tokens';

const OPTIONS: { value: ThemePreference; label: string }[] = [
  { value: 'system', label: 'System' },
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
];

export function ThemeSwitch() {
  const { preference, setPreference, colors, radius, spacing } = useAppTheme();

  return (
    <View
      accessibilityRole="radiogroup"
      style={[
        styles.row,
        { backgroundColor: colors.surfaceAlt, borderRadius: radius.md, padding: spacing.xs },
      ]}>
      {OPTIONS.map((option) => {
        const selected = option.value === preference;
        return (
          <Pressable
            key={option.value}
            accessibilityRole="radio"
            accessibilityState={{ selected }}
            onPress={() => setPreference(option.value)}
            style={({ pressed }) => [
              styles.option,
              {
                borderRadius: radius.sm,
                backgroundColor: selected ? colors.primary : 'transparent',
                opacity: pressed ? 0.7 : 1,
              },
            ]}>
            <AppText variant="bodyStrong" color={selected ? 'onPrimary' : 'text'}>
              {option.label}
            </AppText>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row' },
  option: {
    flex: 1,
    minHeight: minTouchSize,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
