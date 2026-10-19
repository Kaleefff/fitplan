import Ionicons from '@expo/vector-icons/Ionicons';
import { router } from 'expo-router';
import { Pressable, StyleSheet } from 'react-native';

import { useAppTheme } from '@/hooks/use-app-theme';
import { minTouchSize, spacing } from '@/theme/tokens';

// Gear icon in the header (Rys. 7.5) that opens Settings
export function HeaderSettingsButton() {
  const { colors } = useAppTheme();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel="Settings"
      hitSlop={spacing.sm}
      onPress={() => router.push('/settings')}
      style={({ pressed }) => [styles.button, { opacity: pressed ? 0.5 : 1 }]}>
      <Ionicons name="settings-outline" size={24} color={colors.text} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  button: {
    minWidth: minTouchSize,
    minHeight: minTouchSize,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: spacing.xs,
  },
});
