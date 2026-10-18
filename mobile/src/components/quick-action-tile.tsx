import { router } from 'expo-router';
import { Pressable, StyleSheet } from 'react-native';

import { AppText } from '@/components/app-text';
import { ModuleIcon } from '@/components/module-icon';
import type { AppModule } from '@/constants/modules';
import { useAppTheme } from '@/hooks/use-app-theme';

type QuickActionTileProps = {
  module: AppModule;
};

// Home screen tile (Rys. 7.5) that opens the module's tab.
// Navigates in onPress: <Link asChild> would drop the pressed-state style function.
export function QuickActionTile({ module }: QuickActionTileProps) {
  const { colors, radius, spacing, scheme } = useAppTheme();

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`${module.title}. ${module.description}`}
      onPress={() => router.push(module.href)}
      style={({ pressed }) => [
        styles.tile,
        {
          backgroundColor: colors.surface,
          borderColor: colors.border,
          borderRadius: radius.lg,
          padding: spacing.lg,
          gap: spacing.sm,
          elevation: scheme === 'light' ? 1 : 0,
          opacity: pressed ? 0.7 : 1,
        },
      ]}>
      <ModuleIcon icon={module.icon} color={module.color} />
      <AppText variant="bodyStrong">{module.title}</AppText>
      <AppText variant="caption" color="textMuted">
        {module.description}
      </AppText>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  // Two tiles per row at any screen width
  tile: { flexBasis: '47%', flexGrow: 1, borderWidth: 1 },
});
