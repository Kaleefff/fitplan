import type { ReactNode } from 'react';
import { ScrollView, StyleSheet } from 'react-native';

import { useAppTheme } from '@/hooks/use-app-theme';

type ScreenProps = {
  children: ReactNode;
};

// Scrolls so that content also fits on 4.7-inch screens
export function Screen({ children }: ScreenProps) {
  const { colors, spacing } = useAppTheme();
  return (
    <ScrollView
      style={[styles.fill, { backgroundColor: colors.background }]}
      contentContainerStyle={{ padding: spacing.lg, gap: spacing.lg }}
      contentInsetAdjustmentBehavior="automatic">
      {children}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
});
