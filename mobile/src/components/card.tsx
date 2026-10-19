import { View, type ViewProps } from 'react-native';

import { useAppTheme } from '@/hooks/use-app-theme';

export function Card({ style, ...rest }: ViewProps) {
  const { colors, radius, spacing, scheme } = useAppTheme();
  return (
    <View
      style={[
        {
          backgroundColor: colors.surface,
          borderColor: colors.border,
          borderWidth: 1,
          borderRadius: radius.lg,
          padding: spacing.lg,
          gap: spacing.sm,
          // Light mode shows depth with a shadow; dark mode with the lighter surface colour
          elevation: scheme === 'light' ? 1 : 0,
        },
        style,
      ]}
      {...rest}
    />
  );
}
